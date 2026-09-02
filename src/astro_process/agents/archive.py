"""Archive Agent — creates agent-log.yaml in the output directory."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
import yaml
from astropy.io import fits

from ..models.core import ObservationContext, compute_group_hash

logger = structlog.get_logger(__name__)


@dataclass
class ArchiveResult:
    output_dir: Path
    final_fits: Path | None = None
    agent_log: Path | None = None
    run_info: Path | None = None


class ArchiveAgent:
    """Creates agent-log.yaml summarizing the pipeline run."""

    def __init__(self, output_root: Path, config=None):
        self.output_root = output_root
        self.config = config

    def run(self, context: ObservationContext,
            proc_result,
            calibration_result,
            debayer_result=None,
            discovery_result=None,
            keep_working: bool = False,
            multi_group_metadata: dict | None = None) -> ArchiveResult:
        """Create processing log.
        
        Args:
            context: Observation context
            proc_result: Processing result
            calibration_result: Calibration result
            debayer_result: Debayer result (optional)
            discovery_result: Discovery result (optional)
            keep_working: Whether to keep working directory
            multi_group_metadata: Multi-group metadata dict for agent-log (optional)
        """
        logger.info("archive.start", target=context.target.name)

        output_dir = self.output_root
        result = ArchiveResult(output_dir=output_dir)

        # Find final FITS: merged/ ist der konsistente finale Output fuer
        # Multi- UND Single-Group (V1.3-6: Single-Group legt eine byte-
        # identische Trivial-Merge-Kopie in merged/ ab); Top-Level
        # {safe_name}_final.fits bleibt als Legacy erhalten.
        safe_name = context.target.name.replace(" ", "_").replace("(", "").replace(")", "")
        result.final_fits = self._resolve_final_fits(output_dir, safe_name)

        # Create agent-log.yaml
        result.agent_log = self._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            debayer_result=debayer_result,
            discovery_result=discovery_result,
            multi_group_metadata=multi_group_metadata,
        )

        # Fix-Sammlung v1.3 §3 (P0): run-info.json im Lauf-Ordner
        # (Aufnahmemodus + Gruppen-Uebersicht, leicht maschinenlesbar).
        result.run_info = self._write_run_info(
            output_dir, context,
            proc_result=proc_result,
            discovery_result=discovery_result,
            multi_group_metadata=multi_group_metadata,
        )

        logger.info("archive.complete", output_dir=str(output_dir))
        return result

    def _write_run_info(
        self,
        output_dir: Path,
        context: ObservationContext,
        proc_result=None,
        discovery_result=None,
        multi_group_metadata: dict | None = None,
    ) -> Path | None:
        """Fix-Sammlung v1.3 §3 (P0): `run-info.json` im Lauf-Ordner.

        Fasst den Aufnahmemodus (eq/eq_source) und die Gruppen-Uebersicht
        (hash, frame_count, exptime, gain, filter, weight) als JSON
        zusammen. eq/eq_source stammen aus dem DiscoveryResult
        (V1.3-6: ``resolve_eq_flag`` — sources: shotsinfo/eqmode/
        az_fallback/unknown); die Gruppen-Uebersicht aus dem
        ``multi_group_metadata``-Dict (Multi-Group) bzw. wird fuer
        Single-Group-Laeufe aus dem Context abgeleitet (``group_by_params``
        + ``compute_group_hash`` — identische Logik wie
        ``DiscoveryAgent.discover_groups``).

        run-info.json ist ein DIAGNOSE-Additiv (Boris 2026-08-16): ein
        Schreibfehler wird geloggt, ABBRICHT den Lauf NICHT — das
        kritische Artefakt des Archive-Agents bleibt agent-log.yaml (T5).
        Ohne verwendbare Quellen (kein multi_group_metadata, kein Context-
        Header) wird ``groups: []`` geschrieben bzw. None zurueckgegeben.
        """
        run_info: dict[str, Any] = {
            "run": {
                "date": datetime.now().isoformat(),
                "version": "0.1.0",
            },
            "acquisition": {
                "eq": (
                    discovery_result.eq
                    if discovery_result is not None
                    and getattr(discovery_result, "eq", None) is not None
                    else None
                ),
                "eq_source": (
                    getattr(discovery_result, "eq_source", None)
                    if discovery_result is not None
                    else "unknown"
                ),
            },
            "groups": self._collect_group_overview(
                context, multi_group_metadata
            ),
            "pcc_status": getattr(proc_result, "pcc_status", None) if proc_result is not None else None,
        }

        log_path = output_dir / "run-info.json"
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(run_info, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("archive.run_info_write_failed",
                           path=str(log_path), error=str(e))
            return None

        logger.info("archive.run_info_created", path=str(log_path))
        return log_path

    def _collect_group_overview(
        self,
        context: ObservationContext,
        multi_group_metadata: dict | None,
    ) -> list[dict[str, Any]]:
        """Gruppen-Uebersicht fuer run-info.json.

        Multi-Group: aus ``multi_group_metadata["groups"]`` (exakt die
        Felder aus dem Fix-Sammlung-v1.3-§3-Katalog). Single-Group:
        Fallback aus dem Context via ``group_by_params`` (gleiche
        Hash-Logik wie DiscoveryAgent.discover_groups).
        """
        if multi_group_metadata:
            groups = multi_group_metadata.get("groups") or {}
            if groups:
                return [
                    {
                        "hash": gh,
                        "frame_count": meta.get("frame_count", 0),
                        "exptime": meta.get("exptime", 0.0),
                        "gain": meta.get("gain", 0),
                        "filter": meta.get("filter"),
                        "weight": meta.get("weight", 0.0),
                    }
                    for gh, meta in groups.items()
                ]

        overview: list[dict[str, Any]] = []
        try:
            lights = context.get_lights()
        except Exception as e:
            logger.warning("archive.run_info_context_lights_failed", error=str(e))
            return overview
        for (exptime, gain, filter_name), frameset in lights.group_by_params().items():
            group_hash = compute_group_hash(
                float(exptime), int(gain), str(filter_name)
            )
            overview.append({
                "hash": group_hash,
                "frame_count": frameset.count,
                "exptime": exptime,
                "gain": gain,
                "filter": None if str(filter_name) == "none" else filter_name,
                "weight": float(frameset.count),
            })
        return overview

    def _resolve_final_fits(self, output_dir: Path, safe_name: str) -> Path | None:
        """Resolve the final FITS path from the output directory structure.

        V1.3-6: merged/ ist der konsistente finale Output fuer Multi- UND
        Single-Group-Runs — "{safe_name}_merged.fits" (Single-Group: trivialer
        Merge, byte-identische Kopie des Top-Level-Exports). Der Top-Level
        "{safe_name}_final.fits" bleibt als Legacy erhalten
        (Rueckwaertskompatibilitaet fuer v1.2-Workflows; ob er kuenftig
        entfaellt, ist offene Review-Frage — nicht stillschweigend anders
        loesen). Resolution ist name-based auf der Zielstruktur (nicht auf
        proc_result-Pfaden), damit der Archive-Agent von Processing-Interna
        unabhaengig und robust gegen Temp-Dir-Artefakte bleibt. Returns None
        if neither file exists.
        """
        merged_fits = output_dir / "merged" / f"{safe_name}_merged.fits"
        if merged_fits.exists():
            return merged_fits
        legacy_fits = output_dir / f"{safe_name}_final.fits"
        if legacy_fits.exists():
            return legacy_fits
        return None

    @staticmethod
    def _resolve_registered_frames(proc_result, multi_group_metadata: dict | None = None) -> int:
        """DEF-009: Ermittelt registered_frames aus der Quelle der Wahrheit.

        Reihenfolge:
        1. Multi-Group: Summe von frames_registered ueber alle Gruppen in
           multi_group_metadata["groups"][*]["registration_metrics"].
        2. Single-Group: proc_result.registration_metrics["frames_registered"].
        3. Legacy-Fallback: Laenge von proc_result.registered_frames.
        """
        # 1. Multi-Group
        if multi_group_metadata:
            groups = multi_group_metadata.get("groups") or {}
            total = 0
            found = False
            for meta in groups.values():
                reg_metrics = meta.get("registration_metrics") or {}
                frames_registered = reg_metrics.get("frames_registered")
                if frames_registered is not None:
                    total += int(frames_registered)
                    found = True
            if found:
                return total

        # 2. Single-Group
        reg_metrics = getattr(proc_result, "registration_metrics", None) or {}
        frames_registered = reg_metrics.get("frames_registered")
        if frames_registered is not None:
            return int(frames_registered)

        # 3. Legacy-Fallback
        registered_frames = getattr(proc_result, "registered_frames", None) or []
        return len(registered_frames) if registered_frames else 0

    @staticmethod
    def _read_reg_rot_from_fits(fits_path: Path | None) -> float | None:
        """V1.5-4 / DADR-014: REG_ROT aus dem Final-FITS-Header lesen.

        Returns den Rotationswinkel (Grad) oder None falls nicht vorhanden.
        Best effort — Fehler werden nicht geloggt (Archive-Agent darf nicht
        am FITS-Lesen scheitern).
        """
        if fits_path is None or not fits_path.exists():
            return None
        try:
            with fits.open(fits_path) as hdul:
                return float(hdul[0].header["REG_ROT"])
        except (KeyError, Exception):
            return None

    _EQUIPMENT_LOG_FIELDS = (
        "telescope", "camera", "pixel_size_um",
        "focal_length_mm", "aperture_mm",
    )

    @classmethod
    def _equipment_block(cls, context: ObservationContext) -> dict:
        """V1.7-4 (AC-EQPT-D1): Wert + Quelle je Equipment-Feld.

        Quelle aus ``context.equipment.sources`` (befuellt durch
        resolve_equipment). Fehlt der Eintrag (Legacy-Pfade ohne V1.7-4-
        Discovery), wird aus der Wertlage abgeleitet: Wert gesetzt ->
        fits_header, sonst none.

        Fix (Voll-CI-Fund 2026-08-23): ALLE Werte laufen durch
        _log_scalar_or_none. getattr() auf einem MagicMock erzeugt beim
        ersten Zugriff Child-Attribute — Tests mit MagicMock-context.
        equipment liessen yaml.dump sonst mit 'dictionary update sequence
        element #0 has length 1' abstuerzen (width_px/bayer_pattern/
        profile_name landeten als Mock-Objekte im Log). Echte Werte sind
        Skalare und bleiben unveraendert.
        """
        eq = getattr(context, "equipment", None)

        def _entry(field: str) -> dict:
            value = cls._log_scalar_or_none(
                getattr(eq, field, None) if eq is not None else None
            )
            source = (
                cls._log_scalar_or_none(
                    eq.sources.get(field) if eq is not None else None
                )
                or ("fits_header" if value is not None else "none")
            )
            return {"value": value, "source": source}

        width_px = cls._log_scalar_or_none(
            getattr(eq, "width_px", None) if eq is not None else None
        )
        height_px = cls._log_scalar_or_none(
            getattr(eq, "height_px", None) if eq is not None else None
        )
        bayer = cls._log_scalar_or_none(
            getattr(eq, "bayer_pattern", None) if eq is not None else None
        )
        profile_name = cls._log_scalar_or_none(
            getattr(eq, "profile_name", None) if eq is not None else None
        )

        return {
            **{field: _entry(field) for field in cls._EQUIPMENT_LOG_FIELDS},
            # EQPT-B: Aufloesung rein dokumentarisch (OQ-EQPT-2).
            "resolution": {
                "width_px": width_px,
                "height_px": height_px,
                "source": "fits_header" if (width_px and height_px) else "none",
            },
            # EQPT-C (AC-EQPT-C4): Header-Wert oder RGGB-Annahme dokumentiert.
            "bayer_pattern": bayer or "assumed: RGGB",
            "profile_name": profile_name,
        }

    @staticmethod
    def _log_scalar_or_none(value):
        """Fix B1 (Voll-CI-Fund 2026-08-23): Nur echte Skalare/None ins
        agent-log durchreichen. getattr() auf einem MagicMock ERZEUGT beim
        ersten Zugriff ein Child-Attribut — ein gemocktes DebayerResult
        liess yaml.dump sonst mit 'dictionary update sequence element #0
        has length 1' abstuerzen (MagicMocks sind nicht YAML-serialisier-
        bar). Echte Werte (float/int Faktor, str Quelle) und None laufen
        unveraendert durch."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        return None

    def _create_agent_log(self, output_dir: Path, context: ObservationContext,
                         proc_result, calibration_result,
                         debayer_result=None,
                         discovery_result=None,
                         multi_group_metadata: dict | None = None) -> Path:
        """Create agent-log.yaml with processing summary."""

        safe_name = context.target.name.replace(" ", "_").replace("(", "").replace(")", "")
        final_fits = self._resolve_final_fits(output_dir, safe_name)

        log = {
            "run": {
                "date": datetime.now().isoformat(),
                "version": "0.1.0",
            },
            "target": {
                "name": context.target.name,
                "type": context.target.target_type.value,
            },
            "acquisition": {
                "total_integration_time": context.total_integration_time,
            },
            "frames": {
                "lights": context.total_light_frames,
                "darks": context.calibration.dark_count,
                "flats": context.calibration.flat_count,
                "bias": context.calibration.bias_count,
            },
            "calibration": {
                "master_dark": str(calibration_result.master_dark) if calibration_result.master_dark else None,
                "calibrated_lights": len(calibration_result.calibrated_lights),
            },
            "debayer": {
                "debayered_frames": len(debayer_result.debayered_frames) if debayer_result and debayer_result.debayered_frames else 0,
                # Fix 2026-08-21 (Log-Oddität Lauf 171059): Methode war
                # hardcodet "superpixel_rggb" — auch wenn real bilinear lief
                # (V1.6-2). Jetzt: tatsächliche Methode aus DebayerResult,
                # Label-Konvention "<method>_rggb" (Pipeline nutzt RGGB).
                # Legacy-Ergebnisse ohne method-Feld → "unknown" statt
                # falscher Behauptung.
                "method": (
                    f"{debayer_result.method}_rggb"
                    if getattr(debayer_result, "method", None)
                    else "unknown"
                ),
                # Fix B1 ray-Review 2026-08-23 (V1.7-4, AC-EQPT-C5): der
                # aufgeloeste stack_scale_factor wird MIT Quelle
                # ("explicit" | "preset" | "auto_data" | "default")
                # strukturell dokumentiert (analog AC-BIL-E4) — das reine
                # Konsolen-Event cli.process.stack_scale_factor_resolved
                # genuegt der AC nicht. Legacy-Ergebnisse ohne Felder
                # bleiben valide (None). _log_scalar_or_none filtert
                # Nicht-Zahlen heraus (z.B. MagicMock-Attribute aus
                # gemockten Debayer-Results — getattr auf einem Mock
                # ERZEUGT sonst Attribute, die yaml.dump zum Absturz
                # bringen; Crash-Fund Voll-CI 2026-08-23).
                "stack_scale_factor": self._log_scalar_or_none(
                    getattr(debayer_result, "stack_scale_factor", None)
                ) if debayer_result is not None else None,
                "stack_scale_factor_source": self._log_scalar_or_none(
                    getattr(debayer_result, "stack_scale_factor_source", None)
                ) if debayer_result is not None else None,
            },
            # V1.7-4 (AC-EQPT-D1): Equipment-Block mit Wert + Quelle je Feld
            # (fits_header | config | none). Quellen aus context.equipment.
            # sources (befuellt durch resolve_equipment in der Discovery).
            "equipment": self._equipment_block(context),
            "processing": {
                # DEF-009: registered_frames aus registration_metrics speisen
                # (Quelle der Wahrheit). Multi-Group: Summe ueber die Gruppen;
                # Single-Group: top-level registration_metrics.frames_registered;
                # Legacy: Fallback auf die Frame-Liste.
                "registered_frames": (
                    self._resolve_registered_frames(proc_result, multi_group_metadata)
                ),
                "stacked": str(proc_result.stacked) if proc_result.stacked else None,
                "exports": [str(e) for e in proc_result.exports] if proc_result.exports else [],
                # QF-B (AC-QF-B1): frame_quality je Frame (QF-A-Schema,
                # frame + correlation vom Registrations-Pass gefuellt) und
                # Stack-Zusammenfassung (Median-FWHM, Median-SNR,
                # Outlier-Rate). Additiv — bestehende Felder unveraendert.
                "frame_quality": (
                    list(proc_result.frame_qualities)
                    if getattr(proc_result, "frame_qualities", None)
                    else []
                ),
                "stack_quality": dict(getattr(proc_result, "stack_quality", None) or {}),
                # GR-E (AC-GR-E1): Gradient-Removal-Report (Single-Group
                # run()). Additiv — Legacy-Ergebnisse ohne GR-Felder bleiben
                # valide (leeres dict).
                "gradient_removal": dict(getattr(proc_result, "gradient_removal", None) or {}),
                # V1.3-3: Registrierungs-Metriken (Befund 4 stella: Frame-
                # Qualitaets-Metriken erfassen Registrierungs-Qualitaet
                # nicht — corr_hp-Verteilung, method_counts, zero_shift/
                # rejected-Zaehler). Additiv — Legacy-Ergebnisse ohne Feld
                # bleiben valide (leeres dict).
                "registration_metrics": dict(getattr(proc_result, "registration_metrics", None) or {}),
                # PCC-Status: Ergebnis der photometrischen Farbkalibrierung
                # (Single-Group: direkt aus _photometric_color_calibration;
                # Multi-Group: aggregiert aus group_metadata). None wenn
                # kein PCC-Pipeline-Step vorhanden oder Legacy-Ergebnis.
                "pcc_status": getattr(proc_result, "pcc_status", None),
                # V1.5-4 / DADR-014: REG_ROT aus dem Final-FITS-Header
                # (Provenienz-Rotation der Registration, in Grad). Additiv —
                # Legacy-Ergebnisse ohne REG_ROT-Feld bleiben valide (None).
                "reg_rot": self._read_reg_rot_from_fits(final_fits),
                # V1.8-2 (AC-PREV-A5): effektive Preview/Export-Pipeline Settings.
                # Additiv — Legacy-Ergebnisse ohne Feld bleiben valide (None).
                "preview_export": dict(getattr(proc_result, "preview_export", None) or {}),
                # V1.8-3 (AC-FITS-A4): Gestretchter FITS Status.
                # Additiv — Legacy-Ergebnisse ohne Feld bleiben valide (None).
                # MagicMock-Attribute werden explizit ausgeschlossen, damit
                # yaml.dump keine nicht-serialisierbaren Objekte erhaelt.
                "stretched_fits": (
                    dict(_sf)
                    if isinstance(_sf := getattr(proc_result, "stretched_fits", None), dict)
                    else None
                ),
            },
            "outputs": {
                "final_fits": str(final_fits) if final_fits else None,
                "agent_log": str(output_dir / "agent-log.yaml"),
            },
        }

        # Add multi-group section if available
        if multi_group_metadata:
            mg_section: dict[str, Any] = {
                "enabled": True,
                "groups": [],
                "merge": {},
            }
            for gh, meta in multi_group_metadata.get("groups", {}).items():
                mg_section["groups"].append({
                    "hash": gh,
                    "frame_count": meta.get("frame_count", 0),
                    "exptime": meta.get("exptime", 0.0),
                    "gain": meta.get("gain", 0),
                    "filter": meta.get("filter"),
                    "total_exposure": meta.get("total_exposure", 0.0),
                    "weight": meta.get("weight", 0.0),
                    "pcc_status": meta.get("pcc_status", "pending"),
                    # QF-B (AC-QF-B1): je Frame + Stack-Zusammenfassung
                    # (per Group, additiv aus group_metadata).
                    "frame_quality": meta.get("frame_quality", []),
                    "quality": meta.get("quality", {}),
                    # GR-E (AC-GR-E1, AC-GR-D2): Gradient-Removal-Report
                    # je Gruppe (applied + Modell-Parameter). Additiv —
                    # Legacy-Gruppen ohne GR-Felder bleiben valide.
                    "gradient_removal": meta.get("gradient_removal", {}),
                    # V1.3-3: Registrierungs-Metriken je Gruppe (method_counts,
                    # zero_shift_count, rejected_count, corr_hp-Verteilung,
                    # n_control_points-Median). Additiv — Legacy-Gruppen ohne
                    # registration_metrics bleiben valide (leeres dict).
                    "registration_metrics": meta.get("registration_metrics", {}),
                    # V1.7-2 FSEL-C/D: Frame-Selection Trichter + per-frame Entscheidungen.
                    # AC-FSEL-C2: total → percentile_rejected → threshold_rejected → stacked
                    # AC-FSEL-D1: je Light-Frame score + Entscheidung (kept|percentile_rejected|threshold_rejected) + Grund
                    # Additiv — Legacy-Gruppen ohne selection bleiben valide (leeres dict).
                    "selection": meta.get("selection", {}),
                })
            mg_section["merge"] = {
                "method": multi_group_metadata.get("method", "weighted_average"),
                "weight_by": multi_group_metadata.get("weight_by", "frame_count"),
                "reference_group": multi_group_metadata.get("reference_group", ""),
            }
            # V1.7-1 FSM-C2/C4: effektive Filter-Liste + Zuordnung Kandidat/excluded je Gruppe (additiv, AC-C1..C4)
            # Nur wenn Filter gesetzt (AC-FSM-B5: kein Ballast bei None -> byte-identisch)
            if multi_group_metadata.get("merge_filters") is not None:
                mg_section["merge"]["filters"] = list(multi_group_metadata["merge_filters"])
            if multi_group_metadata.get("filter_status") is not None:
                mg_section["filter_status"] = dict(multi_group_metadata["filter_status"])
            if multi_group_metadata.get("filter_warnings") is not None:
                mg_section["filter_warnings"] = dict(multi_group_metadata["filter_warnings"])
            # V1.3-3 (stella-Befund 4): Cross-Group-Registrations-Metriken
            # (Pass 2 — der M13-Fehlerort). corr_hp/method/rotation/scale/
            # n_control_points/status je Nicht-Referenz-Gruppe. Additiv —
            # Legacy ohne Feld bleibt [].
            mg_section["cross_group_registrations"] = (
                multi_group_metadata.get("cross_group_registrations", [])
            )
            log["multi_group"] = mg_section

        # V1.5-14 (W5): Strukturierte Warnings-Sektion im agent-log.yaml.
        # Alle Warnungen als maschinenlesbare YAML-Dicts statt Freitext.
        # Quellen: (1) DiscoveryResult.warnings, (2) ProcessingResult-
        # Metriken (outlier/rejection, eq_mix), (3) Calibration/Debayer.
        warnings_list: list[dict[str, Any]] = []

        # Discovery warnings
        if discovery_result is not None:
            for w in (getattr(discovery_result, "warnings", None) or []):
                if isinstance(w, dict):
                    warnings_list.append(w)
                else:
                    warnings_list.append({"source": "discovery", "message": str(w)})

        # Processing warnings: outlier-rejection summary
        if proc_result is not None:
            fq = getattr(proc_result, "frame_qualities", None)
            if fq:
                rejected = [
                    f for f in fq
                    if f.get("outlier_reasons") or f.get("rejected")
                ]
                if rejected:
                    warnings_list.append({
                        "source": "outlier_rejection",
                        "rejected_count": len(rejected),
                        "total_frames": len(fq),
                        "details": [
                            {"frame": r.get("frame", ""), "reasons": r.get("outlier_reasons", [])}
                            for r in rejected
                        ],
                    })

            # Registration metrics warnings
            reg_metrics = getattr(proc_result, "registration_metrics", None)
            if reg_metrics:
                rejected_count = reg_metrics.get("rejected_count", 0)
                if rejected_count > 0:
                    warnings_list.append({
                        "source": "registration",
                        "message": f"{rejected_count} frames rejected during registration",
                        "rejected_count": rejected_count,
                        "zero_shift_count": reg_metrics.get("zero_shift_count", 0),
                    })

        # Multi-group EQ mix warning
        if multi_group_metadata:
            eq_warnings = multi_group_metadata.get("eq_warnings", [])
            for ew in eq_warnings:
                if isinstance(ew, dict):
                    warnings_list.append(ew)
                else:
                    warnings_list.append({"source": "eq_mix", "message": str(ew)})

        if warnings_list:
            log["warnings"] = warnings_list

        # V1.3-1 (RE-C, AC-RE-C1): additive recommendation-Sektion — NUR bei
        # Empfehlungs-Trigger (discovery_result.recommendation); ohne Trigger
        # keine Sektion und keine sonstige Schema-Aenderung (R8/AC-RE-C2).
        # Der bisher ungenutzte discovery_result-Parameter liefert die
        # Empfehlung (durchgereicht aus cli.py).
        if discovery_result is not None and getattr(
            discovery_result, "recommendation", None
        ):
            rec = discovery_result.recommendation
            log["recommendation"] = {
                "method": rec.get("method"),
                "suggested_cli": rec.get("suggested_cli"),
                "reason": rec.get("reason"),
                "eq_source": rec.get("eq_source"),
            }
            if rec.get("max_rotation_suggestion") is not None:
                log["recommendation"]["max_rotation_suggestion"] = (
                    rec["max_rotation_suggestion"]
                )

        log_path = output_dir / "agent-log.yaml"
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                yaml.dump(log, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        except Exception as e:
            # T5 (E1): agent-log ist das kritische Artefakt des Archive-Agents —
            # Fehler hier fuehrt zum Abbruch mit klarer Meldung (kein stilles
            # Weitermachen mit unvollstaendigem Ergebnis).
            logger.error("archive.log_write_failed", path=str(log_path), error=str(e))
            raise RuntimeError(
                f"Archive failed: could not write agent-log to {log_path}: {e}"
            ) from e

        logger.info("archive.log_created", path=str(log_path))
        return log_path


def create_archive_agent(output_root: Path, config=None) -> ArchiveAgent:
    return ArchiveAgent(output_root, config)
