"""Processing Agent - Registration, stacking, PCC, SCNR, export (Python, 3D RGB, Multi-Group)."""

import json
import shutil
import warnings
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING
from dataclasses import dataclass, field
import structlog
import numpy as np
from astropy.io import fits

from ..models.core import ObservationContext, GroupInfo
from ..config.loader import resolve_export_config, resolve_preview_export_config
from ..config.models import PipelinePreset, MultiGroupConfig, PipelineStep

if TYPE_CHECKING:
    from .merge_agent import MergeAgent
from ..core.pcc import (
    compute_pixel_scale,
    get_pcc_fallback,
    photometric_color_calibration,
    scnr,
)
from ..core.plugins import Plugin, PluginContext, PluginResult, resolve_step
from ..core.preview import create_preview_jpg
from ..core.gradient_removal import background_extraction
from ..core.quality import FrameQuality, qual_to_dict, summarize_qualities
from ..core.registration import register_frames, RegistrationResult
from ..core.seq_file import write_seq
from ..core.stacking import stack_frames
from ..core.export import export
# Refactor 2026-08-14 (Cluster 6): Multi-Group-Kern-Logik in
# ``agents/multi_group_agent.py`` — hier nur Importe fuer die dünnen
# Delegationen und den ``MultiGroupProcessor``. Kein Zyklus: das Modul
# importiert processing_agent nicht (MergeAgent nur TYPE_CHECKING).
from .multi_group_agent import (
    MultiGroupProcessor,
    apply_cross_group_skip_filter,
    apply_pcc_per_group,
    build_reference_selection,
    cleanup_group_dirs,
    copy_wcs_headers,
    register_to_reference_stack,
    select_reference_group,
)

logger = structlog.get_logger(__name__)

# S2-B10 (AC-GR-B4, E1-Close): Preset-Steps mit explizitem Handler in
# ``run()``. Jeder Step ausserhalb dieser Menge (und ausserhalb
# ``_EXTERNALLY_HANDLED_STEPS``) erzeugt eine
# ``pipeline.step_unhandled``-Warning statt stiller Ignoranz.
_RUN_HANDLED_STEPS = frozenset({
    "register_frames",
    "stack_frames",
    "background_extraction",
    "gradient_removal",
    "photometric_color_calibration",
    "natural_color_processing",
    "scnr",
    "green_removal",
    "stretch",
    "gentle_stretch",
    "star_preserving_stretch",
    "export",
})

# S2-B10: Steps, die NICHT in ``run()``, aber in anderen Phasen behandelt
# werden (Kalibration/Debayer in cli.py). Keine Unhandled-Warning.
_EXTERNALLY_HANDLED_STEPS = frozenset({
    "create_master_dark",
    "calibrate_lights",
})

# Stacking-Logik: verschoben nach ``core/stacking.py`` (Refactor 2026-08-14,
# Cluster 1) — `resolve_stack_method`, `winsorized_sigma_clip`,
# `stack_frames`, `stack_frames_python`, `stack_2d`. Der Agent ruft
# ``stack_frames`` aus ``..core.stacking``.

# Export-Logik: verschoben nach ``core/export.py`` (Refactor 2026-08-14,
# Cluster 2) — `EXPORT_LIGHT_HEADER_KEYS`, `effective_pixel_size_um`,
# `annotate_export_header`, `export`. Der Agent ruft ``export`` direkt
# (Single-Group); ``annotate_export_header`` wird im Multi-Group-Pfad
# von ``multi_group_agent.py`` genutzt.

# Registrierungs-Logik: verschoben nach ``core/registration.py``
# (Refactor 2026-08-14, Cluster 3) — `RegistrationResult`,
# `register_frames`, `compute_shift`, `corr_grid_shift`,
# `select_registration_channel`, `compute_shift_star_centroid` sowie der
# Modul-Helfer `_corr_pearson` (die identische Agent-Version wurde
# entfernt). `register_frames` gibt den Registrierungs-Zustand als
# `RegisterFramesResult` zurueck; der Agent schreibt die Werte danach in
# seine `_last_*`-Attribute (V1.3-3-Semantik unveraendert).


@dataclass
class ProcessingResult:
    registered_frames: List[Path] = field(default_factory=list)
    stacked: Optional[Path] = None
    exports: List[Path] = field(default_factory=list)
    multi_group_metadata: Optional[dict] = None  # M2/ray: for archive agent-log
    # Format: {
    #     "groups": {group_hash: {frame_count, exptime, gain, filter, total_exposure, weight, pcc_status}},
    #     "method": str, "weight_by": str, "reference_group": str,
    #     "pcc_fallback_groups": list[str]
    # }
    # QF-B (AC-QF-B1): frame_quality je Frame (QF-A-Schema als dict,
    # frame + correlation vom Aufrufer gefuellt) und Stack-Zusammenfassung.
    frame_qualities: List[dict] = field(default_factory=list)
    stack_quality: Optional[dict] = None
    # GR-E (AC-GR-E1): Gradient-Removal-Report (Single-Group run()).
    # None wenn GR disabled/kein Stack/kein Attempt; sonst dict mit
    # applied + Modell-Parameter (degree, grid, n_samples, residual_*).
    gradient_removal: Optional[dict] = None
    # V1.3-3: Registrierungs-Metriken des letzten register_frames-Aufrufs
    # (method_counts, zero_shift_count, rejected_count, corr_hp-Verteilung,
    # n_control_points-Median). Additiv — Legacy-Ergebnisse ohne Feld ok.
    registration_metrics: Optional[dict] = None
    # PCC-Status (persistiert in agent-log.yaml + run-info.json).
    # Single-Group: Ergebnis von _photometric_color_calibration;
    # Multi-Group: aggregiert aus group_metadata.
    pcc_status: Optional[str] = None
    # V1.8-2 (AC-PREV-A5): Effektive Preview/Export-Pipeline Einstellungen
    # fuer agent-log.yaml / inspect. None wenn nicht aufgeloest.
    preview_export: Optional[dict] = None
    # V1.8-3 (AC-FITS-A4): Gestretchter FITS Status fuer agent-log/inspect.
    # None wenn nicht aufgeloest; sonst {enabled: bool, created: bool,
    # method: str, a: float}.
    stretched_fits: Optional[dict] = None


class ProcessingAgent:
    """Python processing pipeline for 3D RGB data: registration, stacking, export."""
    
    def __init__(self, working_dir: Path, config=None):
        self.working_dir = working_dir
        self.config = config
        
        # Fix-Sammlung v1.3 §3 (P0, Boris 2026-08-16): Root-`03_registered`/
        # `04_stacked` werden NICHT mehr in __init__ angelegt — im Multi-Group-
        # Modus arbeiten die Gruppen in eigenen Unterordnern
        # (`group_{hash}/03_registered`, `group_{hash}/04_stacked`); die
        # leeren Root-Ordner waren irrefuehrend (C19-Lauf 20260816-070501).
        # Nur der working_dir selbst wird angelegt (Eigentums-Vertrag des
        # Agents an seinem Ausgabe-Ordner; Aufrufer exportieren/Ablegen dort
        # direkt — z.B. `export(..., working_dir=agent.working_dir)`).
        # Die Anlage der PHASEN-Ordner erfolgt LAZY:
        # - Single-Group-Pfad: `run()` -> `_ensure_phase_dirs()` (Verhalten
        #   des Single-Group-Laufs byte-identisch).
        # - Multi-Group-Pfad: `process_multi_group` nutzt nur die
        #   `group_{hash}/`-Unterordner; Root-`04_stacked` entsteht nur noch
        #   fuer die Plugin-Materialisierung (multi_group_agent.py, SE-B2-
        #   Vertrag). Root-`03_registered` entsteht im Multi-Group-Modus
        #   nie.
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.registered_dir = working_dir / "03_registered"
        self.stacked_dir = working_dir / "04_stacked"

        # QF-B: Frame-Metriken des letzten _register_frames-Aufrufs
        # (Ref-Frame + je Frame, outlier-geflaggt). Wird bei jedem Aufruf
        # neu befuellt; run()/process_multi_group lesen danach.
        self._last_frame_qualities: List[FrameQuality] = []
        # P2-1 (ray-Review): Zaehler der `registration.frame_rejected`-
        # Ereignisse des letzten _register_frames-Aufrufs (RE-F/R3-Randfall:
        # alle Nicht-Referenz-Frames verworfen -> nur Referenz bleibt).
        self._last_frame_rejected: int = 0
        # V1.3-3 (stella-Befund 4): Registrierungs-Metriken des letzten
        # _register_frames-Aufrufs (method_counts, zero_shift_count,
        # rejected_count, frames_total/registered, corr_hp-Verteilung,
        # n_control_points-Median). Frame-Qualitaets-Metriken (QF-B)
        # erfassen die REGISTRIERUNGS-Qualitaet nicht — corr_hp/method-
        # Verteilung macht "Metriken taeuschen" kuenftig erkennbar.
        # Wird bei jedem Aufruf neu befuellt; run()/process_multi_group
        # lesen danach.
        self._last_registration_metrics: dict = {}
        # V1.5-12 (W3): Pixel-Skala CLI-Override — wird in run() und
        # process_multi_group() vor der Equipment-basierten Berechnung
        # geprueft. None = kein Override (Default-Verhalten).
        self.pixel_scale_override: float | None = None

    def _ensure_phase_dirs(self) -> None:
        """Anlage der Root-Phasen-Ordner (`03_registered`/`04_stacked`).

        Fix-Sammlung v1.3 §3 (P0): NUR der Single-Group-Pfad (`run()`) legt
        die Root-Ordner an — dort werden sie fuer Registrierung/Stacking/
        Plugin-Output genutzt. Der Multi-Group-Pfad nutzt ausschliesslich
        `group_{hash}/03_registered` + `group_{hash}/04_stacked` und legt
        die Root-Ordner nicht an.
        """
        self.registered_dir.mkdir(parents=True, exist_ok=True)
        self.stacked_dir.mkdir(parents=True, exist_ok=True)

    def run(self, context: ObservationContext, calibration_result,
            debayer_result, pipeline: PipelinePreset) -> ProcessingResult:
        """Run Python processing on 3D RGB frames.

        .. deprecated::
            Single-path ``run()`` is deprecated since v1.7 (Always Multi-Group,
            OQ-AMG-3). Use ``process_multi_group`` instead. Grace period v1.7,
            removal planned for v1.8. Behaviour is unchanged, only a
            DeprecationWarning is emitted.
        """
        warnings.warn(
            "deprecated, use process_multi_group (Always Multi-Group)",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.info("processing.start", target=context.target.name, pipeline=pipeline.name)
        self._ensure_phase_dirs()
        
        def _has_step(name: str) -> bool:
            return any(s.name == name for s in pipeline.steps)
        
        proc_params = pipeline.processing_params.model_dump()
        
        # Determine input frames: debayered (3D) if available, else calibrated (2D)
        input_frames = debayer_result.debayered_frames if debayer_result.debayered_frames else calibration_result.calibrated_lights
        is_3d = bool(debayer_result.debayered_frames)
        
        result = ProcessingResult()
        
        # 1. Registration (G-channel for 3D, or direct for 2D)
        if _has_step("register_frames") and input_frames:
            # Refactor 2026-08-14 (Cluster 3): register_frames ist
            # Modul-Funktion in core/registration.py; der Registrierungs-
            # Zustand kommt als RegisterFramesResult zurueck und wird in
            # die _last_*-Attribute geschrieben (V1.3-3-Semantik: Reset
            # VOR dem Early-Return-Guard steckt im Rueckgabe-Zustand).
            reg_result = register_frames(
                input_frames, proc_params, is_3d=is_3d,
                registered_dir=self.registered_dir,
                load_frame=self._load_frame,
                save_frame=self._save_frame,
            )
            result.registered_frames = reg_result.registered
            self._last_frame_qualities = reg_result.last_frame_qualities
            self._last_frame_rejected = reg_result.last_frame_rejected
            self._last_registration_metrics = reg_result.last_registration_metrics
            # QF-B (AC-QF-B1): frame_quality je Frame + Stack-Zusammenfassung
            # aus dem Registrations-Pass (Aufrufer fuellt frame/correlation).
            # Refactor 2026-08-14 (Cluster 4): qual_to_dict/summarize_qualities
            # sind Modul-Funktionen in core/quality.py.
            result.frame_qualities = [
                qual_to_dict(q) for q in self._last_frame_qualities
            ]
            result.stack_quality = summarize_qualities(
                self._last_frame_qualities
            )
            # V1.3-3 (stella-Befund 4): Registrierungs-Metriken ins Ergebnis
            # (agent-log processing.registration_metrics). None wenn der
            # register_frames-Aufruf nichts befuellt hat (additiv).
            result.registration_metrics = self._last_registration_metrics or None
        
        # 2. Stacking
        if _has_step("stack_frames") and result.registered_frames:
            result.stacked = stack_frames(
                result.registered_frames, proc_params, is_3d=is_3d,
                stacked_dir=self.stacked_dir,
                load_frame=self._load_frame,
                save_frame=self._save_frame,
            )
        
        # 3. Background extraction / gradient removal (GR-C, AC-GR-B2):
        # die Preset-Steps `background_extraction` (galaxy_standard) und
        # `gradient_removal` (nebula_standard, nebula_narrowband) werden
        # BEIDE real verarbeitet — kein stiller Ignorier-Fall mehr.
        # GR-E (AC-GR-E1): Report (applied + Modell-Parameter) wird am
        # ProcessingResult exponiert (agent-log processing.gradient_removal).
        if _has_step("background_extraction") or _has_step("gradient_removal"):
            result.gradient_removal = self._background_extraction(
                result.stacked, proc_params
            )
        # GR-01 (E1-Close): GR enabled (CLI/Config) aber Preset ohne GR-Step
        # -> Warning `pipeline.gradient_removal_unhandled` statt stiller
        # Ignoranz (Muster pipeline.step_unhandled, S2-B10). Kein Abbruch.
        elif (proc_params.get("gradient_removal") or {}).get("enabled"):
            logger.warning(
                "pipeline.gradient_removal_unhandled",
                msg=(
                    "Gradient removal enabled but preset has no "
                    "background_extraction/gradient_removal step — "
                    "verify the pipeline preset"
                ),
            )
        
        # 4. PCC (GAIA-based or gray-world fallback)
        # F-META-1.2: wcs_info wird aus der vorhandenen Datenhaltung aufgebaut
        # (Zielkoordinaten + Equipment-Pixel-Skala) und an
        # export weitergereicht -> approximatives TAN-WCS im Final-Header.
        wcs_info: dict | None = None
        if _has_step("photometric_color_calibration") or _has_step("natural_color_processing"):
            # Compute pixel scale for position-based star matching.
            # F-META-1.2 (stella Punkt 5): die Stack-Skala wird aus dem
            # verankerten stack_scale_factor der Registrations-Config
            # abgeleitet (Precedence CLI > Config > Preset > Default) —
            # KEIN fester 4.0-Faktor. Teleskop (z.B. Dwarf3): nativ 2.9 µm, nur 2x
            # Superpixel-Debayer -> 2.9 x 2.0 = 5.8 µm -> 7.98 arcsec/px.
            # V1.5-12 (W3): --pixel-scale CLI-Override — Precedence
            # CLI > Equipment-Header (focal/pixel) > 0.0.
            if self.pixel_scale_override is not None and self.pixel_scale_override > 0:
                pixel_scale = self.pixel_scale_override
                logger.info(
                    "processing.pixel_scale_override",
                    pixel_scale=pixel_scale,
                    source="cli",
                )
            else:
                reg_cfg = proc_params.get("registration", {}) or {}
                stack_scale_factor = float(reg_cfg.get("stack_scale_factor", 2.0))
                focal = context.equipment.focal_length_mm
                pix_um = context.equipment.pixel_size_um
                if focal and pix_um and focal > 0 and pix_um > 0:
                    pixel_scale = compute_pixel_scale(focal, pix_um, binning=stack_scale_factor)
                else:
                    pixel_scale = 0.0

            if (
                context.target.ra is not None
                and context.target.dec is not None
                and pixel_scale > 0
            ):
                wcs_info = {
                    "ra": context.target.ra,
                    "dec": context.target.dec,
                    "pixel_scale_arcsec": pixel_scale,
                }

            result.pcc_status = self._photometric_color_calibration(
                result.stacked, proc_params,
                ra=context.target.ra, dec=context.target.dec,
                pixel_scale_arcsec=pixel_scale
            )
        
        # 5. SCNR (green removal)
        if _has_step("scnr") or _has_step("green_removal"):
            self._scnr(result.stacked, proc_params)
        
        # 6. Stretch (user does this manually in Siril)
        if _has_step("stretch") or _has_step("gentle_stretch") or _has_step("star_preserving_stretch"):
            logger.info("pipeline.stretch_skipped", reason="user prefers Siril autostretch")

        # 6b. Plugin-Steps (PL-B, SE-D): an deklarierter Position VOR
        # stretch/export — so landet die Enhancement im Export-Artefakt
        # (AC-SE-D2). Ein erfolgreicher Plugin-Lauf mit FITS-Artefakt in
        # 04_stacked/ ersetzt den aktuellen Stack (SE-B2 Uebernahme);
        # die Kern-Kette bekannter Steps bleibt unangetastet (AC-PL-B3).
        plugin_results = self._run_plugin_steps(pipeline, context)
        for pr in plugin_results:
            artifact = pr.artifact
            if (
                artifact is not None
                and artifact.suffix.lower() == ".fits"
                and artifact.parent == self.stacked_dir
            ):
                logger.info(
                    "processing.plugin_adopted_artifact",
                    step=pr.step,
                    artifact=str(artifact),
                )
                result.stacked = artifact

        # 7. Export: 3D FITS only (linear, color-calibrated)
        if _has_step("export") and result.stacked:
            # V1.8-2 (AC-PREV-A4/A5): effektive Preview/Export-Pipeline Config
            # aufloesen. Ohne Config-Block -> Asinh-only (byte-identisch v1.6).
            preview_cfg = resolve_preview_export_config(
                self.config, pipeline
            ) if self.config is not None else None
            result.preview_export = preview_cfg.model_dump() if preview_cfg is not None else None

            # V1.8-3 (AC-FITS-A1..A4): effektive Export-Config aufloesen
            # (stretched_fits + stretch). Ohne Config-Block -> Default false.
            export_cfg = resolve_export_config(
                self.config, pipeline
            ) if self.config is not None else None

            # F-META-1.2 (stella Punkt 5): effektive Pixelgroesse fuer den
            # Export-Header aus der verankerten Registrations-Config
            # (Precedence CLI > Config > Preset > Default, resolve_registration).
            reg_cfg = proc_params.get("registration", {}) or {}
            stack_scale_factor = float(reg_cfg.get("stack_scale_factor", 2.0))
            result.exports = export(
                result.stacked, context.target.name,
                context=context, wcs=wcs_info,
                stack_scale_factor=stack_scale_factor,
                working_dir=self.working_dir,
                preview_config=preview_cfg,
                export_config=export_cfg,
            )

            # V1.8-3 (AC-FITS-A4): Dokumentation fuer agent-log/inspect.
            stretched_created = any(
                e.name.endswith("_stretched.fits") for e in result.exports
            )
            result.stretched_fits = {
                "enabled": bool(export_cfg.stretched_fits) if export_cfg is not None else False,
                "created": stretched_created,
                "method": export_cfg.stretch.method if export_cfg is not None else "asinh",
                "a": export_cfg.stretch.a if export_cfg is not None else 0.01,
            }

        # 7b. V1.3-6: konsistenter finaler Output-Pfad — Single-Group legt
        # nach dem Export einen zusaetzlichen merged/-Output ab (trivialer
        # Merge: byte-identische Kopie des Top-Level-Exports, P0). Top-Level
        # {safe_name}_final.fits bleibt Legacy (Rueckwaertskompatibilitaet
        # fuer v1.2-Workflows, offene Review-Frage); Multi-Group-Pfad
        # (process_multi_group) bleibt unveraendert.
        top_level_export = next(
            (
                e for e in result.exports
                if e.suffix.lower() == ".fits" and e.parent == self.working_dir
            ),
            None,
        )
        if top_level_export is not None and top_level_export.exists():
            safe_name = context.target.name.replace(" ", "_").replace("(", "").replace(")", "")
            merged_dir = self.working_dir / "merged"
            merged_dir.mkdir(parents=True, exist_ok=True)
            merged_fits = merged_dir / f"{safe_name}_merged.fits"
            # P0: reines shutil.copy2 NACH der Header-Anreicherung -> die
            # merged/-Kopie ist byte-identisch zum Top-Level-Export.
            shutil.copy2(top_level_export, merged_fits)
            jpg_out = merged_dir / f"{safe_name}_merged_preview.jpg"
            preview = create_preview_jpg(
                merged_fits, jpg_out,
                preview_config=preview_cfg,
            )
            # exports-Reihenfolge: Top-Level zuerst (aus export), dann
            # merged/-Artefakte (agent-log processing.exports zeigt beide).
            result.exports.append(merged_fits)
            if preview:
                result.exports.append(preview)
            logger.info(
                "processing.merged_output",
                path=str(merged_fits),
                preview=bool(preview),
            )
        
        # Write seq file for registered frames
        if result.registered_frames:
            seq_path = self.registered_dir.parent / f"{self.registered_dir.name}.seq"
            write_seq(seq_path, result.registered_frames, prefix="reg_")

        logger.info("processing.complete", stacked=result.stacked is not None, exports=len(result.exports))
        return result

    # ── Plugin Steps (PL-B, v1.2) ──────────────────────────────

    @staticmethod
    def _pipeline_has_plugin_steps(pipeline: PipelinePreset) -> bool:
        """True, wenn der Preset mindestens einen Plugin-Step enthaelt
        (Step ausserhalb ``_RUN_HANDLED_STEPS``/``_EXTERNALLY_HANDLED_STEPS``).

        Fix-Sammlung v1.3 §3 (P0): identische Filter-Logik wie
        ``_run_plugin_steps``; steuert die LAZY-Materialisierung des
        Root-``04_stacked/stacked.fits`` im Multi-Group-Modus
        (Plugin-Input-Konvention SE-B2). Ohne Plugin-Steps bleibt der
        Root-``04_stacked``-Ordner im Multi-Group-Modus unangetastet.
        """
        for step in pipeline.steps:
            if step.name in _RUN_HANDLED_STEPS:
                continue
            if step.name in _EXTERNALLY_HANDLED_STEPS:
                continue
            return True
        return False

    def _run_plugin_steps(
        self, pipeline: PipelinePreset, context: ObservationContext
    ) -> list[PluginResult]:
        """PL-B (AC-PL-B1..B3): Step-Validierung + Plugin-Ausfuehrung.

        Fuer jeden Preset-Step ausserhalb des Kern-Handlings
        (``_RUN_HANDLED_STEPS``/``_EXTERNALLY_HANDLED_STEPS``):
        - ``resolve_step()`` findet ein Plugin -> ``_run_plugin`` (Fehler des
          Plugins -> Warning + Skip, nie Abbruch — OQ-PL-4/E1).
        - kein Plugin -> ``pipeline.step_unhandled``-Warning (E1-Close,
          AC-GR-B4). Kein Refactoring der Kern-Step-Kette (AC-PL-B3).

        Returns:
            Erfolgreiche ``PluginResult``-Objekte (ok=True). Der Aufrufer
            (run/process_multi_group) kann ein FITS-Artefakt in 04_stacked/
            als neuen aktuellen Stack uebernehmen (SE-B2, AC-SE-D2).
        """
        results: list[PluginResult] = []
        for step in pipeline.steps:
            if step.name in _RUN_HANDLED_STEPS:
                continue
            if step.name in _EXTERNALLY_HANDLED_STEPS:
                continue
            plugin = resolve_step(step.name)
            if plugin is None:
                logger.warning(
                    "pipeline.step_unhandled",
                    step=step.name,
                    msg="No handler for this preset step — verify the pipeline preset",
                )
                continue
            result = self._run_plugin(plugin, step, pipeline, context)
            if result is not None:
                results.append(result)
        return results

    def _run_plugin(
        self,
        plugin: Plugin,
        step: PipelineStep,
        pipeline: PipelinePreset,
        context: ObservationContext,
    ) -> PluginResult | None:
        """Fuehrt ein Plugin fuer ``step`` aus (AC-PL-B2).

        Plugin-Fehler (Exception oder ``PluginResult(ok=False)``) -> Warning
        + Skip, nie Abbruch; Pipeline laeuft weiter (Exit 0 mit Warnings).
        Liefert das erfolgreiche ``PluginResult`` (None bei Fehler/Skip).
        Uebergibt die Step-Params des aktuellen Preset-Steps additiv via
        ``PluginContext.step_params`` (SE-B-PluginContext-Amendment).
        """
        plugin_context = PluginContext(
            working_dir=self.working_dir,
            # Der Agent kennt kein separates Output-Dir (Output kommt aus
            # CLI/AppConfig-Ebene) — Plugins schreiben daher ins Working-Dir
            # (03_registered/04_stacked liegen dort als Unterverzeichnisse).
            output_dir=self.working_dir,
            processing_params=pipeline.processing_params,
            target_name=context.target.name if context.target else "",
            step_params=step.params,
        )
        try:
            result = plugin.run(plugin_context)
        except Exception as e:  # noqa: BLE001 - Plugin-Fehler duerfen den Kern nie stoppen (OQ-PL-4)
            logger.warning(
                "pipeline.plugin_failed",
                plugin=plugin.name,
                step=step.name,
                error=str(e),
                msg="Plugin raised — step skipped (E1)",
            )
            return None
        if not result.ok:
            logger.warning(
                "pipeline.plugin_failed",
                plugin=plugin.name,
                step=step.name,
                ok=False,
                log_fields=result.log_fields,
                msg="Plugin reported failure — step skipped (E1)",
            )
            return None
        logger.info(
            "pipeline.plugin_complete",
            plugin=plugin.name,
            step=step.name,
            artifact=str(result.artifact) if result.artifact else None,
            log_fields=result.log_fields,
        )
        return result
    
    # ── Frame I/O ──────────────────────────────────────────────
    
    def _load_frame(self, path: Path) -> np.ndarray:
        """Load FITS frame as float32. Transposes from (C,H,W) FITS convention to (H,W,C)."""
        with fits.open(path) as hdul:
            data = hdul[0].data.astype(np.float32)
            # FITS stores multi-dimensional data with axes reversed (NAXIS1=fastest)
            # For 3D RGB: FITS has shape (C, H, W), transpose to (H, W, C)
            if data.ndim == 3:
                data = data.transpose(1, 2, 0)  # (C, H, W) → (H, W, C)
            return data
    
    def _save_frame(self, data: np.ndarray, path: Path) -> None:
        """Save float32 array as FITS. Transposes (H,W,C) to (C,H,W) for FITS convention."""
        out = data.astype(np.float32)
        if out.ndim == 3:
            # Transpose from internal (H, W, C) to FITS (C, H, W)
            out = out.transpose(2, 0, 1)  # (H, W, C) → (C, H, W)
        hdu = fits.PrimaryHDU(out)
        if data.ndim == 3:
            hdu.header["CTYPE3"] = "RGB"
            hdu.header["CUNIT3"] = "channel"
        # Fix-Sammlung v1.3 §3 (P0): parent defensiv anlegen (astropy
        # `writeto` erzeugt KEINE fehlenden Verzeichnisse). Seit die Root-
        # Phasen-Ordner nicht mehr in __init__ angelegt werden, kann ein
        # Direkt-Aufruf (Tests, Callables) ein noch nicht existierendes
        # Zielverzeichnis treffen — mkdir ist hier harmlos und robust.
        path.parent.mkdir(parents=True, exist_ok=True)
        hdu.writeto(path, overwrite=True)
    
    # ── Gradient Removal (GR-C) ─────────────────────────────────

    def _background_extraction(self, stacked: Optional[Path], params: dict) -> Optional[dict]:
        """GR-C (AC-GR-C1..C3): Gradient-Removal auf dem gestackten Frame.

        Refactor 2026-08-14 (Cluster 7): Kern-Logik in ``core/gradient_removal.py``
        (``background_extraction``); hier dünne Delegation — Tests rufen
        diese Methode direkt auf dem Agent auf (Log-Events laufen ueber den
        Agent-Modul-Logger, siehe Docstring dort fuer GR-C-Referenzen).

        Returns:
            GR-E-Report (AC-GR-E1) — Schema identisch zu vorher.
        """
        return background_extraction(
            stacked,
            params,
            load_frame=self._load_frame,
            save_frame=self._save_frame,
            logger=logger,
        )

    # QF-B-Summaries (_qual_to_dict/_summarize_qualities): verschoben nach
    # ``core/quality.py`` (Refactor 2026-08-14, Cluster 4) — Modul-Funktionen
    # `qual_to_dict`/`summarize_qualities`; der Agent importiert sie oben.

    def _get_pcc_fallback(self) -> str:
        """Get the PCC fallback strategy from config.

        Refactor 2026-08-14 (Cluster 5): Kern-Logik in ``core/pcc.py``
        (``get_pcc_fallback``); hier dünne Delegation fuer Test-Direktaufrufe.

        Returns:
            One of "gray_world", "skip", "fail"
        """
        return get_pcc_fallback(self.config)

    def _photometric_color_calibration(self, stacked: Optional[Path], params: dict,
                                        ra: Optional[float] = None, dec: Optional[float] = None,
                                        pixel_scale_arcsec: float = 0.0) -> Optional[str]:
        """Apply PCC to the stacked frame.

        Refactor 2026-08-14 (Cluster 5): Kern-Logik in ``core/pcc.py``
        (``photometric_color_calibration``); hier duenne Delegation — Tests
        patchen/rufen diese Methode direkt auf dem Agent auf.

        Returns:
            PCC status string or None if no PCC was attempted.
        """
        return photometric_color_calibration(
            stacked,
            params,
            load_frame=self._load_frame,
            save_frame=self._save_frame,
            config=self.config,
            logger=logger,
            ra=ra,
            dec=dec,
            pixel_scale_arcsec=pixel_scale_arcsec,
        )
    
    def _scnr(self, stacked: Optional[Path], params: dict):
        """Remove green cast (SCNR) from the stacked frame.

        Refactor 2026-08-14 (Cluster 5): Kern-Logik in ``core/pcc.py``
        (``scnr``); hier dünne Delegation — Tests patchen/rufen diese
        Methode direkt auf dem Agent auf.
        """
        scnr(
            stacked,
            params,
            load_frame=self._load_frame,
            save_frame=self._save_frame,
            logger=logger,
        )

    # ════════════════════════════════════════════════════════════════
    # Multi-Group Stacking (Phase 2 — T5–T8)
    # ════════════════════════════════════════════════════════════════
    #
    # Refactor 2026-08-14 (Cluster 6): Kern-Logik in
    # ``agents/multi_group_agent.py`` (Modul-Funktionen + MultiGroupProcessor).
    # Hier nur dünne Delegationen — Tests rufen die Methoden direkt auf dem
    # Agent auf und patchen sie (``patch.object``), deshalb bleiben Namen
    # und Signaturen unverändert. Der Logger (``logger``) wird überall
    # durchgereicht, damit ``processing_agent_mod.logger``-Patches in Tests
    # (z.B. ``multi_group.skip_group``) weiterhin greifen.

    def process_multi_group(
        self, context: ObservationContext,
        calibration_result, debayer_result,
        pipeline: PipelinePreset,
        multi_group_config: MultiGroupConfig,
        merge_agent: Optional['MergeAgent'] = None,
        target_name: str = "",
    ) -> ProcessingResult:
        """Multi-Group Pipeline: Discovery → Pass 1 (intra-group) → Pass 2 (cross-group) → PCC → Merge.

        Refactor 2026-08-14 (Cluster 6): Der Multi-Group-Ablauf liegt in
        ``MultiGroupProcessor`` (``agents/multi_group_agent.py``). Dieser
        Delegate erzeugt den Processor, reicht die Agent-Methoden als
        Callables durch (Frame-I/O, Plugin-Steps,
        ``ProcessingResult`` sowie die test-patchbaren Hooks
        ``_select_reference_group``/``_register_to_reference_stack``/
        ``_apply_pcc_per_group``) und übernimmt die ``_last_*``-Attribute
        nach dem Lauf (V1.3-3-Semantik unverändert).

        V1.7-5 (Always Multi-Group): Genau 1 Gruppe läuft durch denselben
        Pfad wie N Gruppen — der frühere 1-Gruppen-Fallback auf ``run()``
        ist entfernt (siehe ``multi_group.single_group_unified``).

        Args:
            context: Full observation context with all frames
            calibration_result: Result from CalibrationAgent
            debayer_result: Result from DebayerAgent (may be None for 2D)
            pipeline: Pipeline preset with steps and processing params
            multi_group_config: Multi-group configuration

        Returns:
            ProcessingResult with merged stack path and exports
        """
        processor = MultiGroupProcessor(
            self.working_dir, self.config,
            load_frame=self._load_frame,
            save_frame=self._save_frame,
            run_plugin_steps=self._run_plugin_steps,
            processing_result_class=ProcessingResult,
            select_reference_group=self._select_reference_group,
            register_to_reference_stack=self._register_to_reference_stack,
            apply_pcc_per_group=self._apply_pcc_per_group,
            has_plugin_steps=ProcessingAgent._pipeline_has_plugin_steps,
            logger=logger,
        )
        result = processor.process_multi_group(
            context, calibration_result, debayer_result,
            pipeline, multi_group_config,
            merge_agent=merge_agent, target_name=target_name,
        )
        # V1.3-3-Semantik: Registrierungs-Zustand des letzten Pass-1
        # register_frames-Aufrufs (Gruppen-Loop) zurueckuebernehmen —
        # Agent-Leser (Tests, run()) greifen auf self._last_* zu
        # (unveraendert).
        self._last_frame_qualities = processor.last_frame_qualities
        self._last_frame_rejected = processor.last_frame_rejected
        self._last_registration_metrics = processor.last_registration_metrics
        # Aggregate per-group PCC status into top-level result for
        # agent-log.yaml / run-info.json persistence.
        if result.multi_group_metadata and result.multi_group_metadata.get("groups"):
            statuses = [
                m.get("pcc_status", "unknown")
                for m in result.multi_group_metadata["groups"].values()
            ]
            unique = list(dict.fromkeys(statuses))  # preserve order, dedup
            if unique == ["pending"] and getattr(
                processor, "last_merged_pcc_status", None
            ) is not None:
                # ray Review Fix 1 (2026-08-21): Merged-PCC-Modus
                # (pcc_per_group=False) — Gruppen-Metadaten tragen nur
                # "pending"; der Status des Merge-PCC-Laufs ist die
                # Wahrheit (z.B. rejected_implausible_factors).
                result.pcc_status = processor.last_merged_pcc_status
            else:
                result.pcc_status = unique[0] if len(unique) == 1 else "mixed"
        elif getattr(processor, "last_merged_pcc_status", None) is not None:
            # Keine Gruppen-Metadaten, aber Merge-PCC lief: Status direkt
            # uebernehmen (ray Review Fix 1).
            result.pcc_status = processor.last_merged_pcc_status
        return result

    # ── Referenz-Auswahl (V1.3-5/W14) ─────────────────────────

    @staticmethod
    def _select_reference_group(
        groups: dict[str, GroupInfo],
        strategy: str = "largest",
        group_stacks: Optional[dict[str, Path]] = None,
        registration_metrics: Optional[dict[str, dict]] = None,
    ) -> str:
        """Select the reference group hash based on the configured strategy.

        Refactor 2026-08-14 (Cluster 6): Delegation auf
        ``agents/multi_group_agent.py::select_reference_group``
        (unveraendert; wird als Hook an den MultiGroupProcessor
        durchgereicht — Tests patchen/rufen diese Methode direkt).

        Args:
            groups: Dict mapping group hash → GroupInfo
            strategy: "largest" | "signal" | "quality" | Group-Hash
            group_stacks: {group_hash: stacked.fits path} (signal/quality)
            registration_metrics: {group_hash: Metriken-Dict} (quality)

        Returns:
            Group hash of the selected reference group
        """
        return select_reference_group(
            groups, strategy, group_stacks, registration_metrics,
            logger=logger,
        )

    def _build_reference_selection(
        self,
        groups: dict[str, GroupInfo],
        strategy: str,
        ref_hash: str,
        group_stacks: dict[str, Path],
        registration_metrics: Optional[dict[str, dict]] = None,
    ) -> dict:
        """CR-001 W14 (AC-W14-2): Referenz-Wahl im Report dokumentieren.

        Refactor 2026-08-14 (Cluster 6): Delegation auf
        ``agents/multi_group_agent.py::build_reference_selection``
        (unveraendert).

        Returns:
            Report-Sektion dict.
        """
        return build_reference_selection(
            groups, strategy, ref_hash, group_stacks,
            registration_metrics=registration_metrics,
            logger=logger,
        )

    # ── W3: min_correlation-Skip-Sicherheitsnetz ──────────────

    @staticmethod
    def _apply_cross_group_skip_filter(
        aligned_stacks: dict[str, Path],
        cross_group_registrations: list[dict],
        ref_hash: str,
        min_correlation: float,
        group_metadata: Optional[dict] = None,
        preview_paths: Optional[dict] = None,
        working_dir: Optional[Path] = None,
        group_avg_rotation: float = 0.0,
    ) -> tuple[dict[str, Path], list[dict]]:
        """CR-001 W3 (AC-W3-1/2): `merge.min_correlation`-Sicherheitsnetz.

        Refactor 2026-08-14 (Cluster 6): Delegation auf
        ``agents/multi_group_agent.py::apply_cross_group_skip_filter``
        (unveraendert; Tests rufen diese Methode direkt auf dem Agent auf).

        Returns:
            (gefilterte aligned_stacks, skipped_groups)
        """
        return apply_cross_group_skip_filter(
            aligned_stacks, cross_group_registrations, ref_hash,
            min_correlation,
            group_metadata=group_metadata,
            preview_paths=preview_paths,
            working_dir=working_dir,
            group_avg_rotation=group_avg_rotation,
            logger=logger,
        )

    # ── Cross-Group Registration (W1/W2/W9-D2) ────────────────

    def _register_to_reference_stack(
        self, stack_path: Path, ref_stack_path: Path,
        filter_name: str, output_dir: Path,
        params: Optional[dict] = None,
        eq: Optional[bool] = None,
    ) -> RegistrationResult:
        """Register a group stack to a reference stack (cross-group, stack-level).

        Refactor 2026-08-14 (Cluster 6): Delegation auf
        ``agents/multi_group_agent.py::register_to_reference_stack``
        (unveraendert; Frame-I/O wird durchgereicht — Tests patchen/rufen
        diese Methode direkt auf dem Agent auf).

        Args:
            stack_path: Path to the group stack to register
            ref_stack_path: Path to the reference stack
            filter_name: Filter name for channel selection
            output_dir: Directory to save the aligned stack
            params: Processing params (ProcessingParams.model_dump())

        Returns:
            RegistrationResult with aligned FITS path, shift, post-shift
            corr_hp/correlation, ok/warning/rejected status and W9-D2-
            Metadaten.
        """
        return register_to_reference_stack(
            stack_path, ref_stack_path, filter_name, output_dir,
            load_frame=self._load_frame,
            save_frame=self._save_frame,
            logger=logger,
            params=params,
            eq=eq,
        )

    @staticmethod
    def _copy_wcs_headers(
        source_path: Path, target_path: Path, rotation_deg: float = 0.0,
    ) -> None:
        """Copy WCS header keywords from source FITS to target FITS.

        Refactor 2026-08-14 (Cluster 6): Delegation auf
        ``agents/multi_group_agent.py::copy_wcs_headers`` (V1.5-4-Stand,
        unveraendert; Tests rufen diese Methode direkt auf dem Agent auf).

        V1.5-4 / DADR-014: bei rotation_deg != 0 wird REG_ROT (Grad) als
        separates Keyword gesetzt — die CD-Matrix wird nicht geschrieben,
        WCS bleibt CDELT-only.

        Args:
            source_path: FITS with authoritative WCS (reference stack)
            target_path: FITS to update (aligned stack)
            rotation_deg: Rotation in Grad, die auf die Stack-Pixel
                angewendet wurde (0.0 = keine Rotation -> CDELT).
        """
        copy_wcs_headers(
            source_path, target_path, rotation_deg=rotation_deg,
            logger=logger,
        )

    # ── Per-Group PCC (T6) ────────────────────────────────────

    def _apply_pcc_per_group(
        self, stack_path: Path, context: ObservationContext,
        multi_group_config: MultiGroupConfig, group_dir: Path,
        pixel_scale_arcsec: float = 0.0,
        ra: Optional[float] = None, dec: Optional[float] = None,
        group_metadata: Optional[dict] = None,
    ) -> tuple[Path, str]:
        """Apply PCC to one group stack. Idempotent — skips if already applied.

        Refactor 2026-08-14 (Cluster 6): Delegation auf
        ``agents/multi_group_agent.py::apply_pcc_per_group``
        (unveraendert; der PCC-Schritt wird als Callable durchgereicht —
        Agent ``_photometric_color_calibration``, Tests patchen diese
        Methode auf dem Agent).

        Returns:
            Tuple of (pcc_path: Path, status: str)
        """
        return apply_pcc_per_group(
            stack_path, context, multi_group_config, group_dir,
            photometric_color_calibration_fn=self._photometric_color_calibration,
            logger=logger,
            pixel_scale_arcsec=pixel_scale_arcsec,
            ra=ra, dec=dec,
            group_metadata=group_metadata,
        )

    # ── Cleanup Group Directories ─────────────────────────────

    def _cleanup_group_dirs(self, groups: dict[str, GroupInfo], target_name: str) -> None:
        """Remove per-group working directories after successful merge.

        Refactor 2026-08-14 (Cluster 6): Delegation auf
        ``agents/multi_group_agent.py::cleanup_group_dirs`` (unveraendert;
        Tests rufen diese Methode direkt auf dem Agent auf).

        Args:
            groups: Dict mapping group hash → GroupInfo
            target_name: Target name for logging
        """
        cleanup_group_dirs(groups, target_name, logger=logger)


def create_processing_agent(working_dir: Path, config=None) -> ProcessingAgent:
    return ProcessingAgent(working_dir, config)
