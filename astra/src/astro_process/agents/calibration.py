"""
Calibration Agent — Dark, Bias, Flat stacking and light frame calibration.

CR-001 W5 (P5): Darks Library + Per-Group Master-Darks (E1/E2)
- Matching: local -> library exact -> library nearest-temp
- Per-Group Master-Darks in generated/{ts}/00_input/master/
- E1: Ein Calibration-Pfad in BEIDEN Modi (Single + Multi)
- E2: KEIN Kopieren ins Target-darks/ (nur lesender Zugriff auf _darks/)
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

import numpy as np
from astropy.io import fits

import structlog

from ..config.models import AppConfig
from ..models.core import (
    FrameSet,
    ObservationContext,
    AcquisitionInfo,
    compute_group_hash,
)

logger = structlog.get_logger(__name__)


@dataclass
class CalibrationResult:
    """Result of calibration workflow."""
    working_dir: Path
    master_dark: Optional[Path] = None
    master_bias: Optional[Path] = None
    master_flat: Optional[Path] = None
    master_dark_flat: Optional[Path] = None
    calibrated_lights: List[Path] = field(default_factory=list)
    # W5: Track dark source per group (for reporting)
    dark_sources: Dict[str, str] = field(default_factory=dict)
    # T3: Per-Group-Dark-Quelle und Master-Pfad (group_hash -> Wert).
    # Quelltypen: "local" | "library_exact" | "library_nearest" | "none"
    master_dark_sources: Dict[str, str] = field(default_factory=dict)
    master_dark_paths: Dict[str, Path] = field(default_factory=dict)


class CalibrationAgent:
    """Handles calibration frame stacking and light frame calibration."""

    def __init__(self, working_dir: Path, config=None, darks_repository: Optional[Path] = None):
        self.working_dir = working_dir
        self.config = config
        self.darks_repository = darks_repository
        # Subdirectories (numbered for natural pipeline order)
        # Master-Darks unter 00_input/master (Staging laeuft vor Calibration,
        # 00_input existiert an dieser Stelle garantiert).
        self.masters_dir = working_dir / "00_input" / "master"
        self.calibrated_dir = working_dir / "01_calibrated"
        self.masters_dir.mkdir(parents=True, exist_ok=True)
        self.calibrated_dir.mkdir(parents=True, exist_ok=True)

    def run(self, context: ObservationContext) -> CalibrationResult:
        """Run full calibration workflow."""
        logger.info("calibration.start", target=context.target.name)

        result = CalibrationResult(working_dir=self.working_dir)

        # W5/B2: Runtime-Check fuer Darks-Verfuegbarkeit. Lokale Darks im
        # Target haben Vorrang; sonst brauchen wir eine Darks-Bibliothek.
        local_darks = context.get_darks()
        has_local_darks = len(local_darks.frames) > 0 if local_darks and hasattr(local_darks, "frames") else False
        if not has_local_darks and self.darks_repository is None:
            raise ValueError(
                "Kein Darks-Pfad gesetzt: Kalibration benoetigt Darks. "
                "Setze darks_repository in config.yaml "
                '(z.B. darks_repository: "C:/Astra/_darks") '
                "oder uebergib --darks-path <Pfad>."
            )

        # 1. Create master dark(s) — T3: Per-Group in BOTH modes (E1).
        # Gruppen IMMER aus group_by_params() ableiten (Single- UND Multi-Group);
        # der tote hasattr(context, "groups")-Zweig ist entfernt.
        groups = context.get_lights().group_by_params()
        result.master_dark = self._create_master_darks(context, groups, result)
        
        # 2. Create master bias
        if context.calibration.bias_available:
            result.master_bias = self._create_master_bias(context)
        
        # 3. Create master flat(s)
        if context.calibration.flat_available:
            result.master_flat = self._create_master_flat(context)
        
        # 4. Create master dark flat (if available)
        if context.calibration.dark_flat_available:
            result.master_dark_flat = self._create_master_dark_flat(context)
        
        # 5. Apply calibration to lights
        if context.total_light_frames > 0:
            result.calibrated_lights = self._calibrate_lights(context, result)
        
        logger.info("calibration.complete", 
                    master_dark=result.master_dark is not None,
                    master_bias=result.master_bias is not None,
                    master_flat=result.master_flat is not None,
                    calibrated_count=len(result.calibrated_lights))
        
        return result

    def _find_darks_for_group(self, context: ObservationContext, group_key: tuple, temp: Optional[float] = None) -> tuple[List[Path], str]:
        """
        Find dark frames for a specific (EXPTIME, GAIN) group.
        
        Matching order (W5, E1/E2):
        1. Local target/darks/ (physically taken darks)
        2. Library exact: darks_repository/{exposure}{gain}/ with matching temp
        3. Library nearest: nearest temperature (≤3°C tolerance)
        
        Args:
            context: Observation context (local darks).
            group_key: (exptime, gain, filter) tuple.
            temp: Sensortemperatur der GRUPPE (aus den eigenen Light-Frames).
                  T3-Fix: nicht first-frame-global, sondern gruppenspezifisch.
        
        Returns: (list of dark paths, source_string)
        """
        # Unpack group key: (exptime, gain, filter)
        exptime, gain, filter_name = group_key

        # QF-03 (QG4-Close): Dark-Matching ist FILTERUNABHAENGIG — das
        # Dark-Signal haengt nur von EXPTIME/GAIN/TEMP ab, nicht vom
        # optischen Filter. Ein Light MIT Filter (z.B. "Duo-" nach DEF-001)
        # darf Darks OHNE Filter (header-lose Dumps: filter_name=None) nicht
        # ausschliessen: vorher blockierte der Filter-Check in
        # get_for_calibration (None != "Duo-") das Matching — M27-Lights
        # liefen unkalibriert (master_dark: false), obwohl 30s40-Darks
        # (lokal wie Bibliothek) vorhanden waren.
        match_filter = None
        
        # 1. LOCAL: target/darks/
        local_darks = context.get_darks()
        if local_darks.frames:
            # Filter by exptime and gain
            matched = local_darks.get_for_calibration(exptime, gain, match_filter, temp)
            if matched:
                logger.info("calibration.dark_match_local", 
                           count=len(matched), exptime=exptime, gain=gain)
                return [f.path for f in matched], "local"
        
        # 2. & 3. LIBRARY: darks_repository/{exposure}{gain}/
        if self.darks_repository and self.darks_repository.exists():
            lib_path = self.darks_repository / f"{int(exptime)}s{gain}"
            if lib_path.exists():
                # Find dark frames in library
                from ..core.fits_parser import scan_directory
                from ..models.core import FrameType

                # scan_directory liefert dict[FrameType, FrameSet]
                # (kein ObservationContext — Typ-Annotation dort irrefuehrend)
                lib_frames = scan_directory(lib_path)
                lib_darks = lib_frames.get(FrameType.DARK)
                
                if lib_darks.frames:
                    matched = lib_darks.get_for_calibration(exptime, gain, match_filter, temp)
                    if matched:
                        logger.info("calibration.dark_match_library_exact",
                                   count=len(matched), path=str(lib_path))
                        return [f.path for f in matched], "library_exact"
                    
                    # Nearest temperature fallback
                    if temp:
                        matched = lib_darks.get_for_calibration(exptime, gain, match_filter, temp, temp_tolerance=10.0)
                        if matched:
                            logger.warning("calibration.dark_match_library_nearest",
                                          count=len(matched), path=str(lib_path),
                                          temp=temp, tolerance=10.0)
                            return [f.path for f in matched], "library_nearest"
        
        logger.warning("calibration.no_dark_match", exptime=exptime, gain=gain, filter=filter_name)
        return [], "none"

    def _create_group_master_dark(self, dark_paths: List[Path], group_hash: str) -> Optional[Path]:
        """Create master dark for a specific group."""
        if not dark_paths:
            return None
        
        output = self.masters_dir / f"master_dark_{group_hash}.fits"
        if len(dark_paths) == 1:
            # Einzelner Dark-Frame: direkt als Master uebernehmen (kein Stack
            # noetig — ein einziger passender Dark ist ein valider Master).
            shutil.copy2(dark_paths[0], output)
        else:
            # Leo-Auftrag 2026-08-10 (Bad-Pixel-Korrektur, Teil C): Dark-
            # Master-Stack auf MEDIAN statt Average. Grund (stella-Diagnose
            # C20 20260810-052954): Average wird von zeitlich instabilen
            # Hot Pixels einzelner Darks verfaelscht (ein Dark mit einem
            # heissen Pixel +50..400 DN hebt den Mittelwert lokal um
            # delta/n). Median ist dagegen robust gegen einzelne Ausreisser
            # und bleibt bei gleichbleibendem BG-Level (Real-Validierung
            # 30s40: Average-BG 198.6 vs Median-BG 198.5). Einziges
            # Einzel-Dark ohne Stack ist davon nicht betroffen (kein
            # Stacking noetig).
            self._stack_frames_python(dark_paths, output, method="median")
        logger.info("calibration.group_master_dark_created", 
                   path=str(output), group=group_hash, count=len(dark_paths))
        return output

    def _create_master_darks(
        self,
        context: ObservationContext,
        groups: dict,
        result: CalibrationResult,
    ) -> Optional[Path]:
        """T3: Erzeuge Per-Group-Master-Darks (Single- UND Multi-Group-Modus).

        Gruppen stammen IMMER aus ``context.get_lights().group_by_params()``.
        - Multi-Group-Modus (len(groups) > 1): ``master_dark_{group_hash}.fits``
          je Gruppe im selben Master-Verzeichnis (00_input/master-Konvention).
        - Single-Group-Modus (len(groups) == 1): weiterhin
          ``master_dark_single.fits`` (Backward-Compat, keine Namensänderung).

        Quelltyp-Logik (aus _find_darks_for_group):
        - lokaler Dark im Target fuer diese Gruppe -> "local"
        - Library mit exaktem Exposure/Gain-Match -> "library_exact"
        - Library mit naechstem Temp-Match (kein exakter Treffer) -> "library_nearest"
        - kein Dark verfuegbar -> "none"

        Gruppe OHNE eigenes Dark (weder lokal noch Library) -> KEIN Master fuer
        diese Gruppe, ``logger.warning("calibration.dark_missing", group=...)``,
        dark_source "none", Lights dieser Gruppe bleiben UNKALIBRIERT (KEIN
        Fallback auf andere Gruppe / globalen Master — keine Cross-Contamination).

        Args:
            context: Observation context.
            groups: ``{group_key: FrameSet}`` aus ``group_by_params()``.
            result: CalibrationResult, das befuellt wird (master_dark_sources,
                    master_dark_paths, dark_sources).

        Returns:
            Single-Group-Modus: Pfad zu ``master_dark_single.fits`` (oder None).
            Multi-Group-Modus: None (Per-Group-Master liegen in
            ``result.master_dark_paths``; ``result.master_dark`` bleibt None).
        """
        is_multi_group = len(groups) > 1
        single_master: Optional[Path] = None

        for group_key, frames_fs in groups.items():
            exptime, gain, filter_name = group_key
            group_hash = compute_group_hash(
                float(exptime), int(gain), str(filter_name)
            )

            # T3-Fix: Temperatur der GRUPPE (eigene Light-Frames, Mittelwert),
            # nicht die des ersten Light-Frames des gesamten Kontexts.
            group_temps = [
                f.header.ccd_temp
                for f in frames_fs.frames
                if f.header and f.header.ccd_temp is not None
            ]
            group_temp = (sum(group_temps) / len(group_temps)) if group_temps else None

            dark_paths, source = self._find_darks_for_group(context, group_key, group_temp)

            # Report-Felder (T3): group_hash -> Quelltyp
            result.master_dark_sources[group_hash] = source
            result.dark_sources[group_hash] = source
            context.calibration.dark_sources[group_hash] = source

            if not dark_paths:
                # T3: KEIN Fallback — Gruppe bleibt unkalibriert
                logger.warning("calibration.dark_missing", group=group_hash,
                               exptime=exptime, gain=gain, filter=filter_name)
                continue

            try:
                if is_multi_group:
                    master_path = self._create_group_master_dark(dark_paths, group_hash)
                else:
                    master_path = self._create_group_master_dark(dark_paths, "single")
                    single_master = master_path
            except Exception as e:
                # T5 (E1): Master-Build (Stacking) dieser Gruppe schlaegt fehl —
                # Gruppe bleibt unkalibriert (dark_source "none"), kein Abbruch.
                logger.warning("calibration.master_build_failed", group=group_hash,
                               exptime=exptime, gain=gain, filter=filter_name,
                               error=str(e))
                result.master_dark_sources[group_hash] = "none"
                result.dark_sources[group_hash] = "none"
                context.calibration.dark_sources[group_hash] = "none"
                continue

            result.master_dark_paths[group_hash] = master_path
            logger.info("calibration.master_dark_created", path=str(master_path),
                        group=group_hash, source=source, count=len(dark_paths))

        return single_master

    def _create_master_bias(self, context: ObservationContext) -> Optional[Path]:
        """Stack bias frames into master bias using Python."""
        bias = context.get_bias()
        if not bias.frames:
            return None
        
        output = self.masters_dir / "master_bias.fits"
        self._stack_frames_python([f.path for f in bias.frames], output, method="average")
        logger.info("calibration.master_bias_created", count=len(bias.frames))
        return output

    def _create_master_flat(self, context: ObservationContext) -> Optional[Path]:
        """Stack flat frames into master flat(s) per filter."""
        flats = context.get_flats()
        if not flats.frames:
            return None
        
        filter_groups = flats.group_by_filter()
        master_flats = []
        
        for filter_name, frames in filter_groups.items():
            if len(frames) < 2:
                continue
            
            output = self.masters_dir / f"master_flat_{filter_name}.fits"
            self._stack_frames_python([f.path for f in frames], output, method="average", normalization="mul")
            master_flats.append(output)
            logger.info("calibration.master_flat_created", filter=filter_name, count=len(frames))
        
        return master_flats[0] if master_flats else None

    def _create_master_dark_flat(self, context: ObservationContext) -> Optional[Path]:
        """Stack dark flat frames."""
        dark_flats = context.get_dark_flats()
        if not dark_flats.frames:
            return None
        
        output = self.masters_dir / "master_dark_flat.fits"
        self._stack_frames_python([f.path for f in dark_flats.frames], output, method="average")
        return output

    def _stack_frames_python(self, input_paths: List[Path], output_path: Path, method: str = "average", normalization: str = "no"):
        """Stack frames using astropy/numpy.

        V1.1-Hardening (m6): Single-Frame-Edge — bei genau 1 Frame wird
        das Frame direkt kopiert (Average/Median von 1 Frame = das Frame
        selbst). Verhindert Crash bei 1 Bias/Flat/DarkFlat.
        """
        if len(input_paths) == 0:
            raise ValueError("Need at least 1 frame to stack")
        if len(input_paths) == 1:
            shutil.copy2(input_paths[0], output_path)
            logger.info("stack.single_frame", output=str(output_path))
            return
        
        # Load all frames
        frames = []
        for path in input_paths:
            with fits.open(path) as hdul:
                data = hdul[0].data.astype(np.float32)
                frames.append(data)
        
        stack = np.stack(frames, axis=0)
        
        # Apply normalization if needed
        if normalization == "mul":
            # Multiplicative normalization - scale by median
            medians = np.median(stack, axis=(1, 2))
            stack = stack / medians[:, np.newaxis, np.newaxis]
        
        # Stack
        if method == "average":
            result = np.mean(stack, axis=0)
        elif method == "median":
            result = np.median(stack, axis=0)
        elif method == "winsorized":
            # Simple winsorized - clip extremes
            p5, p95 = np.percentile(stack, [5, 95], axis=0)
            clipped = np.clip(stack, p5, p95)
            result = np.mean(clipped, axis=0)
        else:
            result = np.mean(stack, axis=0)
        
        # Save result
        hdu = fits.PrimaryHDU(result.astype(np.float32))
        hdu.writeto(output_path, overwrite=True)
        logger.info("stack.complete", output=str(output_path), frames=len(frames))

    def _calibrate_lights(self, context: ObservationContext, result: CalibrationResult) -> List[Path]:
        """Apply calibration using Python (dark subtraction, flat division, bias subtraction).

        T3: Pro-Group-Master-Darks aus ``result.master_dark_paths`` verwenden.
        KEIN Fallback auf andere Gruppe / globalen Master (keine Cross-Contamination):
        Gruppe ohne eigenes Dark -> kein Dark-Abzug (nur ggf. Bias/Flat).
        """
        lights = context.get_lights()
        calibrated = []

        # Group lights by (EXPTIME, GAIN, FILTER) -> key = (exptime, gain, filter) tuple
        light_groups = lights.group_by_params()

        # Pre-load master darks per group (group_hash -> data array)
        group_masters = {}
        for group_key, _frames_fs in light_groups.items():
            group_hash = compute_group_hash(
                float(group_key[0]), int(group_key[1]), str(group_key[2])
            )
            master_path = result.master_dark_paths.get(group_hash)
            if master_path is not None:
                group_masters[group_hash] = self._load_fits(master_path)

        master_flat = self._load_fits(result.master_flat) if result.master_flat else None
        master_bias = self._load_fits(result.master_bias) if result.master_bias else None

        for group_key, frames_fs in light_groups.items():
            group_hash = compute_group_hash(
                float(group_key[0]), int(group_key[1]), str(group_key[2])
            )
            # T3: KEIN Fallback auf anderen Gruppen-Master oder globalen Master
            master_dark = group_masters.get(group_hash)

            for light in frames_fs.frames:
                output_dir = self.calibrated_dir
                stem = light.path.stem
                suffix = light.path.suffix
                output = output_dir / f"cal_{stem}{suffix}"

                light_data = self._load_fits(light.path)

                calibrated_data = self._apply_calibration(
                    light_data, master_dark, master_flat, master_bias
                )

                hdu = fits.PrimaryHDU(calibrated_data.astype(np.float32))
                hdu.writeto(output, overwrite=True)
                calibrated.append(output)

                # Track dark source for reporting (W5)
                if group_hash in result.master_dark_sources:
                    result.dark_sources[group_hash] = result.master_dark_sources[group_hash]

        logger.info("calibration.lights_calibrated", count=len(calibrated))
        return calibrated

    def _load_fits(self, path: Path) -> np.ndarray:
        """Load FITS file as float32 array."""
        with fits.open(path) as hdul:
            return hdul[0].data.astype(np.float32)

    def _apply_calibration(self, light: np.ndarray, 
                          dark: Optional[np.ndarray],
                          flat: Optional[np.ndarray],
                          bias: Optional[np.ndarray]) -> np.ndarray:
        """Apply calibration: (light - dark - bias) / flat * median(flat).
        
        W4: Only apply flat/bias if config.use_flats/use_bias is True.

        Leo-Auftrag 2026-08-09 (Dark-Offset-Abgleich, Teil 1+2):
        Vor der Dark-Subtraktion werden die Mediane von Light und Dark
        verglichen (robust: Median statt Mean — Sterne/Nebel verfaelschen
        den Schaetzer nicht). Ist der Dark HELLER als das Light ueber der
        Schwelle (``delta = dark_bg - light_bg > threshold``, C20-Fall:
        Master-Dark 213.0-214.7 vs Lights ~205.0), wird nur die
        Dark-STRUKTUR subtrahiert (``dark_adj = dark - dark_bg``, Median
        0): der Hintergrund bleibt auf Light-Niveau (~205) statt auf 0
        geklemmt, das schwache Nebelsignal (~5-20 DN) bleibt erhalten.
        Plain-Subtraktion waere bei delta > Schwelle mathematisch falsch —
        sie drueckt den Hintergrund um delta und kollabiert bei
        delta >= light_bg auf 0 (Frame schwarz).
        ABWEICHUNG von der Formel in der Auftragsquelle (2026-08-09): das
        dortige ``dark_adj = dark - dark_bg + light_bg`` wuerde den
        Hintergrund auf 0 bringen — im C20-Fall ergaeve das Frame-Median
        ≈ 0 und damit in der Stack-Normalisierung "mul" wieder
        divide-by-zero (der urspruengliche 100 %-NaN-Bug). Die korrigierte
        Formel ``result = light - dark + dark_bg`` erfuellt die
        Akzeptanzkriterien der Quelle (Hintergrund ≈ Light-Niveau, Stack
        ohne NaN).
        Sanity-Check (High-Side): ``delta > Schwelle`` -> Warning
        ``calibration.dark_scale_mismatch`` (delta, Schwellenwert) UND
        Offset-Abgleich — KEIN Abbruch, es wird trotzdem
        weiterverarbeitet. Die Schwelle
        (``_dark_scale_mismatch_threshold``, Default max(5.0, 0.04 *
        light_bg)) entscheidet als Gating: erst bei Ueberschreitung wird
        der Adjusted-Pfad genommen, darunter bleibt die Plain-Subtraktion
        (v1.2-identisch).
        Zu DUNKLE Darks (delta < 0, z.B. Lights mit Himmelshintergrund)
        loesen auf der High-Seite KEINE Warnung aus — bewusste Abweichung
        vom abs()-Vorschlag der Quelle (Normal-Fall: Light = Dark +
        Himmelshintergrund + Signal).
        Sanity-Check (Low-Side, M-1-Fix/Ray-Review): ``dark_bg <
        dark_scale_mismatch_low_frac * light_bg`` -> Warning
        ``calibration.dark_scale_mismatch_low`` (dark_bg, light_bg) — C20-
        Fehlerklasse 2 (Lokal-Dark float32 ~0.003-0.04 vs Light ~205):
        Subtraktion wirkungslos, Hot Pixels bleiben. Nur Warnung, KEIN
        Abbruch, Plain-Subtraktion bleibt (v1.2-neutral).
        Neutralitaet: bei delta <= Schwelle (inklusive delta <= 0 und
        delta == 0) bleibt es bei der bisherigen Plain-Subtraktion
        (v1.2-identisch, byte-identisch wo moeglich — M3/M13/M27-Verhalten
        unveraendert).
        """
        result = light.copy()
        
        # W4: Bias only if use_bias config is True
        if bias is not None and (self.config is None or getattr(self.config, 'use_bias', False)):
            result = result - bias
        
        # W4: Dark subtraction (always applied if available)
        if dark is not None:
            light_bg = float(np.median(result))
            dark_bg = float(np.median(dark))
            delta = dark_bg - light_bg
            threshold = self._dark_scale_mismatch_threshold(light_bg)
            if np.isfinite(delta) and delta > threshold:
                # Dark HELLER als Light ueber der Schwelle (C20-Fall):
                # Sanity-Warnung (High-Side) + Struktur-Abgleich.
                # Plain-Subtraktion waere hier mathematisch falsch — sie
                # drueckt den Hintergrund um delta und kollabiert bei
                # delta >= light_bg auf 0 (Frame schwarz).
                logger.warning(
                    "calibration.dark_scale_mismatch",
                    delta=round(delta, 3),
                    threshold=round(threshold, 3),
                    dark_bg=round(dark_bg, 3),
                    light_bg=round(light_bg, 3),
                )
                dark_adj = dark - dark_bg
                result = result - dark_adj
                logger.info(
                    "calibration.dark_offset_adjusted",
                    dark_bg=round(dark_bg, 3),
                    light_bg=round(light_bg, 3),
                    delta=round(delta, 3),
                )
            else:
                # delta <= Schwelle (bzw. NaN-Mediane): Dark dunkler/gleich
                # Light (Normal-Fall). Plain-Subtraktion bleibt
                # (v1.2-identisch, M3/M13/M27-Verhalten unveraendert);
                # Low-Side-Check (M-1-Fix) bleibt.
                low_frac = self._dark_scale_mismatch_low_frac()
                if np.isfinite(dark_bg) and dark_bg < low_frac * light_bg:
                    logger.warning(
                        "calibration.dark_scale_mismatch_low",
                        dark_bg=round(dark_bg, 3),
                        light_bg=round(light_bg, 3),
                        low_frac=low_frac,
                    )
                # Neutraler Pfad (auch bei NaN-Medianen): bisheriges Verhalten.
                result = result - dark
        
        # W4: Flat only if use_flats config is True
        if flat is not None and (self.config is None or getattr(self.config, 'use_flats', False)):
            flat_norm = flat / np.median(flat)
            result = result / flat_norm
        
        # Ensure no negative values
        result = np.maximum(result, 0)
        
        return result.astype(np.float32)

    def _dark_scale_mismatch_threshold(self, light_bg: float) -> float:
        """Schwelle der Dark-Sanity-Warnung (Leo-Auftrag 2026-08-09, Teil 2).

        Effektiv: ``max(dark_scale_mismatch_abs, dark_scale_mismatch_frac *
        light_bg)`` — konfigurierbar ueber AppConfig (Default 5.0 DN / 4 %),
        aus der Produktion (cli.py reicht ``cfg`` als ``config`` herein).
        Fuer C20 (light_bg ~205) ergibt sich 8.2 DN < gemessenes
        Delta ~9.7 DN -> Warnung + Offset-Abgleich greifen (Schwellen-
        Gating: Plain vs. Adjusted entscheidet sich an dieser Schwelle,
        darunter bleibt v1.2-Plain-Subtraktion). Der
        Auftragsvorschlag (10 % bzw. 10 DN) wuerde C20 mit delta 9.7 knapp
        verfehlen.
        """
        if self.config is None:
            abs_floor = 5.0
            frac = 0.04
        else:
            abs_floor = float(getattr(self.config, "dark_scale_mismatch_abs", 5.0))
            frac = float(getattr(self.config, "dark_scale_mismatch_frac", 0.04))
        return max(abs_floor, frac * float(light_bg))

    def _dark_scale_mismatch_low_frac(self) -> float:
        """Low-Seite-Schwelle der Dark-Sanity-Warnung (M-1-Fix, Ray-Review).

        Effektiv: ``dark_scale_mismatch_low_frac`` (Default 0.5) — konfigu-
        rierbar ueber AppConfig (Precedence Config > Default, kein CLI-Flag).
        Default 0.5 (ray-Vorgabe ~0.5): gesunde Darks liegen immer >= ~90 %
        von light_bg, also keine Fehlwarnungen; die C20-Fehlerklasse 2
        (Lokal-Dark float32 0.003-0.04 vs Light ~205) loest aus
        (dark_bg < 0.5 * light_bg).
        """
        if self.config is None:
            return 0.5
        return float(getattr(self.config, "dark_scale_mismatch_low_frac", 0.5))


def create_calibration_agent(working_dir: Path, config=None, darks_repository: Optional[Path] = None) -> CalibrationAgent:
    return CalibrationAgent(working_dir, config, darks_repository)