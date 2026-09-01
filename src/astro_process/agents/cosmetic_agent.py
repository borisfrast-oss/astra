"""Cosmetic Correction Agent — Bad-Pixel-Korrektur vor dem Debayer.

Leo-Auftrag 2026-08-10 (Bad-Pixel-Korrektur, Teil A):
Pipeline-Stufe zwischen Kalibrierung (``01_calibrated``) und Debayer
(``02_debayered``). Die Bad-Pixel-Map wird aus den KALIBRIERTEN Lights
abgeleitet (``core/cosmetic.detect_bad_pixels``) — stella-Diagnose C20
``20260810-052954``: die ε-Flecken sind light-only Hot Pixels (zeitlich
instabil, Dark kennt sie nicht, Median-Stacking entfernt sie nicht),
deshalb kann die Map NICHT aus dem Master-Dark kommen (Siril-``find_cosme``
waere hier blind). Der Master-Dark dient nur als Ausschlusskriterium:
Pixel, an denen das Dark selbst heiss ist (``dark >= dark_bg + tolerance``),
sind echte Dark-Hot-Pixels und werden NICHT als light-only-Defekte
gewertet.

Ablauf je Gruppe (EXPTIME/GAIN/FILTER, Single- UND Multi-Group-Modus —
kein Cross-Group-Fallback beim Master-Dark, konsistent mit T3):
1. Frames der Gruppe laden (streaming, memory-schonend).
2. ``detect_bad_pixels`` -> Bool-Maske (pro Gruppe).
3. Jedes Frame interpolieren (``core/cosmetic.interpolate_bad_pixels``,
   Median der Nachbarpixel derselben Bayer-Farbe, Distanz 2).
4. Korrigierte Frames nach ``01b_cosmetic/cos_*.fits`` schreiben.

Debug-Ausgaben nach ``generated/<run>/`` (Vorgabe stella, Punkt 4):
- ``bad_pixel_map.fits``: erkannte defekte Pixel (0/1, ODER-Verknuepfung
  ueber alle Gruppen).
- ``interpolated_pixels.fits``: Anzahl Frames je Pixel, in denen
  interpoliert wurde (uint16; 0 = nie).

Config: ``AppConfig.cosmetic_correction`` (Default: enabled false,
n_frames 3, threshold 50.0, dark_tolerance 20.0). Precedence
Config > Default (kein CLI-Flag). Deaktiviert -> run() liefert None und
die Pipeline bleibt v1.3-identisch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import structlog
from astropy.io import fits

from ..config.models import CosmeticCorrectionConfig
from ..core.cosmetic import detect_bad_pixels, interpolate_bad_pixels
from ..models.core import ObservationContext, compute_group_hash
from .calibration import CalibrationResult

logger = structlog.get_logger(__name__)


@dataclass
class CosmeticResult:
    """Result of the cosmetic correction stage."""
    working_dir: Path
    corrected_lights: List[Path] = field(default_factory=list)
    bad_pixel_map: Optional[Path] = None
    interpolated_pixels: Optional[Path] = None
    bad_pixel_count: int = 0
    groups: int = 0


class CosmeticCorrectionAgent:
    """Bad-Pixel-Detektion + Interpolation auf kalibrierten CFA-Lights."""

    def __init__(self, working_dir: Path, config=None):
        self.working_dir = working_dir
        self.config = config
        # 01b: zwischen 01_calibrated und 02_debayered (numerische
        # Pipeline-Ordnung, konsistent mit 00_input/master (Input) und 01_calibrated).
        self.corrected_dir = working_dir / "01b_cosmetic"
        self.corrected_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def _config_block(self) -> CosmeticCorrectionConfig:
        """Effektive Cosmetic-Correction-Config (Config > Default)."""
        if self.config is None or getattr(self.config, "cosmetic_correction", None) is None:
            return CosmeticCorrectionConfig()
        return self.config.cosmetic_correction

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def run(
        self,
        context: ObservationContext,
        calibration_result: CalibrationResult,
    ) -> Optional[CosmeticResult]:
        """Fuehre die Bad-Pixel-Korrektur aus.

        Args:
            context: Observation context (fuer die Light->Gruppen-Zuordnung
                und die Pro-Group-Master-Darks).
            calibration_result: Ergebnis der Kalibration. Die korrigierten
                Frames ersetzen NICHT direkt die Liste — der Aufrufer
                (cli.py) setzt
                ``calibration_result.calibrated_lights =
                cosmetic_result.corrected_lights``.

        Returns:
            CosmeticResult, oder None wenn die Stufe deaktiviert ist
            (Pipeline bleibt unveraendert).
        """
        cfg = self._config_block()
        if not cfg.enabled:
            logger.info("cosmetic.skipped", reason="disabled_in_config")
            return None

        calibrated_lights = list(calibration_result.calibrated_lights)
        if not calibrated_lights:
            logger.warning("cosmetic.no_frames")
            return None

        logger.info(
            "cosmetic.start",
            frames=len(calibrated_lights),
            n_frames=cfg.n_frames,
            threshold=cfg.threshold,
            dark_tolerance=cfg.dark_tolerance,
        )

        if len(calibrated_lights) < 8:
            # stella-Vorgabe "3 von >= 8": unter 8 Frames ist die
            # Detektion unzuverlaessig — Warnung, kein Abbruch (der
            # n_frames-Count-Mechanismus filtert ohnehin).
            logger.warning(
                "cosmetic.low_frame_count",
                frames=len(calibrated_lights),
                min_frames=8,
            )

        result = CosmeticResult(working_dir=self.working_dir)

        # Light -> Gruppe-Mapping (konsistent mit calibration._calibrate_lights:
        # cal_{stem}{suffix} in 01_calibrated; im no_calib-Fall die rohen
        # Input-Pfade). Gruppe -> Master-Dark aus CalibrationResult (T3:
        # kein Cross-Group-Fallback).
        path_to_group, group_masters = self._build_group_mapping(
            context, calibration_result
        )

        # Pro-Gruppe arbeiten: eigene Bad-Map, eigene Dark-Bedingung.
        groups: Dict[str, List[Path]] = {}
        for path in calibrated_lights:
            gh = path_to_group.get(str(path), "<unknown>")
            groups.setdefault(gh, []).append(path)

        combined_bad: Optional[np.ndarray] = None
        combined_interp: Optional[np.ndarray] = None

        for group_hash, frame_paths in groups.items():
            master_dark = group_masters.get(group_hash)
            if master_dark is None:
                logger.warning(
                    "cosmetic.no_dark_for_group",
                    group=group_hash,
                    reason="dark_condition_skipped",
                )

            bad_map, interp_counts, corrected = self._process_group(
                frame_paths,
                master_dark,
                cfg.n_frames,
                cfg.threshold,
                cfg.dark_tolerance,
            )
            if bad_map is None:
                continue

            result.groups += 1
            result.bad_pixel_count += int(np.count_nonzero(bad_map))
            result.corrected_lights.extend(corrected)
            combined_bad = (
                bad_map
                if combined_bad is None
                else (combined_bad | bad_map)
            )
            combined_interp = (
                interp_counts
                if combined_interp is None
                else (combined_interp + interp_counts)
            )

        if not result.corrected_lights:
            logger.warning("cosmetic.no_corrected_frames")
            return None

        # Debug-Ausgaben nach generated/<run>/ (stella-Vorgabe Punkt 4).
        result.bad_pixel_map = self._write_debug_map(
            "bad_pixel_map.fits", combined_bad, dtype=np.uint8
        )
        result.interpolated_pixels = self._write_debug_map(
            "interpolated_pixels.fits",
            combined_interp,
            dtype=np.uint16,
        )

        logger.info(
            "cosmetic.complete",
            frames=len(result.corrected_lights),
            bad_pixels=result.bad_pixel_count,
            groups=result.groups,
            bad_pixel_map=str(result.bad_pixel_map),
            interpolated_pixels=str(result.interpolated_pixels),
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_group_mapping(
        self,
        context: ObservationContext,
        calibration_result: CalibrationResult,
    ) -> tuple[Dict[str, str], Dict[str, Optional[np.ndarray]]]:
        """Light-Pfad -> group_hash und group_hash -> Master-Dark-Array.

        Spiegel von ``CalibrationAgent._calibrate_lights``: Die kalibrierten
        Frames heissen ``cal_{stem}{suffix}`` im ``01_calibrated``-Verzeichnis;
        im ``--no-calib``-Fall sind es die rohen Input-Pfade. Master-Darks
        kommen aus ``master_dark_paths`` (per-group) bzw. ``master_dark``
        (single-group) — kein Cross-Group-Fallback (T3-Konsistenz).
        """
        lights = context.get_lights()
        light_groups = lights.group_by_params()
        calibrated_dir = self.working_dir / "01_calibrated"

        path_to_group: Dict[str, str] = {}
        group_masters: Dict[str, Optional[np.ndarray]] = {}

        for group_key, frames_fs in light_groups.items():
            group_hash = compute_group_hash(
                float(group_key[0]), int(group_key[1]), str(group_key[2])
            )
            master_path = calibration_result.master_dark_paths.get(group_hash)
            if master_path is None:
                master_path = calibration_result.master_dark
            group_masters[group_hash] = (
                self._load_fits(master_path) if master_path is not None else None
            )
            for f in frames_fs.frames:
                cal = calibrated_dir / f"cal_{f.path.stem}{f.path.suffix}"
                path_to_group[str(cal)] = group_hash
                path_to_group[str(f.path)] = group_hash

        # Fallback: Pfade, die keinem Light direkt zugeordnet werden
        # konnten (defensiv, sollte nicht auftreten).
        if not path_to_group:
            logger.warning(
                "cosmetic.group_mapping_empty",
                fallback="master_dark_single",
            )
            default_master = (
                self._load_fits(calibration_result.master_dark)
                if calibration_result.master_dark is not None
                else None
            )
            group_masters["<unknown>"] = default_master

        return path_to_group, group_masters

    def _process_group(
        self,
        frame_paths: List[Path],
        master_dark: Optional[np.ndarray],
        n_frames: int,
        threshold: float,
        dark_tolerance: float,
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray], List[Path]]:
        """Detektion + Interpolation einer Gruppe.

        Returns:
            (bad_map, interp_counts, corrected_paths) oder
            (None, None, []) wenn die Gruppe kein korrektes Frame liefert.
        """
        if len(frame_paths) < n_frames:
            logger.warning(
                "cosmetic.group_too_few_frames",
                frames=len(frame_paths),
                n_frames=n_frames,
            )

        # Streaming-Detektion: Frames einzeln laden, Zaehler akkumulieren.
        def _frames_iter():
            for path in frame_paths:
                yield self._load_fits(path)

        try:
            bad_map = detect_bad_pixels(
                _frames_iter(),
                master_dark=master_dark,
                n_frames=n_frames,
                threshold=threshold,
                dark_tolerance=dark_tolerance,
            )
        except Exception as e:
            logger.warning(
                "cosmetic.group_detection_failed",
                group_frames=len(frame_paths),
                error=str(e),
            )
            return None, None, []

        interp_counts = np.zeros(bad_map.shape, dtype=np.uint16)
        corrected: List[Path] = []
        for path in frame_paths:
            out_path = self.corrected_dir / f"cos_{path.stem}{path.suffix}"
            try:
                frame = self._load_fits(path)
                corrected_frame = interpolate_bad_pixels(frame, bad_map)
                self._write_fits(corrected_frame, out_path)
            except Exception as e:
                logger.warning(
                    "cosmetic.frame_failed",
                    path=str(path),
                    error=str(e),
                )
                continue
            corrected.append(out_path)
            interp_counts += bad_map.astype(np.uint16)

        if not corrected:
            logger.warning("cosmetic.group_empty", frames=len(frame_paths))
            return None, None, []

        return bad_map, interp_counts, corrected

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _load_fits(self, path: Path) -> np.ndarray:
        with fits.open(path) as hdul:
            return hdul[0].data.astype(np.float32)

    def _write_fits(self, data: np.ndarray, path: Path) -> None:
        fits.PrimaryHDU(data.astype(np.float32)).writeto(path, overwrite=True)

    def _write_debug_map(
        self,
        name: str,
        data: Optional[np.ndarray],
        dtype: np.dtype,
    ) -> Optional[Path]:
        """Debug-Map nach generated/<run>/ schreiben (stella-Vorgabe Punkt 4)."""
        if data is None:
            return None
        out_path = self.working_dir / name
        fits.PrimaryHDU(data.astype(dtype)).writeto(out_path, overwrite=True)
        return out_path


def create_cosmetic_agent(working_dir: Path, config=None) -> CosmeticCorrectionAgent:
    return CosmeticCorrectionAgent(working_dir, config)
