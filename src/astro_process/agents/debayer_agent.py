"""Debayer Agent — converts Bayer CFA frames to RGB 3D FITS."""

from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field
import structlog

from ..core.debayer import debayer_fits
from ..core.seq_file import write_seq
from ..models.core import ObservationContext

logger = structlog.get_logger(__name__)


@dataclass
class DebayerResult:
    working_dir: Path
    debayered_frames: List[Path] = field(default_factory=list)
    seq_path: Optional[Path] = None
    # Fix 2026-08-21 (Log-Oddität): Tatsächlich verwendete Debayer-Methode
    # ("superpixel" | "bilinear") — der Archive-Agent weist sie im
    # agent-log aus statt sie zu hardcoden. None bei Legacy-Ergebnissen.
    method: Optional[str] = None
    # Fix B1 ray-Review 2026-08-23 (V1.7-4, AC-EQPT-C5): Aufgeloester
    # stack_scale_factor + Quelle ("explicit" | "preset" | "auto_data" |
    # "default") — der Archive-Agent weist beide strukturell im agent-log
    # aus (Konsolen-Event allein genuegt der AC nicht). Befuellt durch die
    # CLI nach der finalen datengetriebenen Aufloesung; None bei Legacy-
    # Ergebnissen (agent-log bleibt valide).
    stack_scale_factor: Optional[float] = None
    stack_scale_factor_source: Optional[str] = None


class DebayerAgent:
    """Converts calibrated 2D Bayer CFA frames to RGB 3D FITS.

    V1.6-2 (BIL-D): Waehlt zwischen Super-Pixel (Default, DADR-003)
    und Bilinear basierend auf der Config (debayer_method).
    """
    
    def __init__(self, working_dir: Path, config=None, debayer_method_override: str = None):
        self.working_dir = working_dir
        self.config = config
        self.debayered_dir = working_dir / "02_debayered"
        self._debayer_method_override = debayer_method_override
    
    def _resolve_debayer_method(self) -> str:
        """V1.6-2 (AC-BIL-D1): Debayer-Methode aus Config aufloesen.

        Precedence: CLI-Override > AppConfig.debayer_method > Default "superpixel".
        """
        # CLI-Override (highest priority)
        if self._debayer_method_override:
            return self._debayer_method_override
        # AppConfig.debayer_method (Top-Level Override)
        if self.config and self.config.debayer_method:
            return self.config.debayer_method
        # Default
        return "superpixel"

    def run(self, context: ObservationContext, calibration_result) -> DebayerResult:
        """Debayer all calibrated light frames.
        
        T5 (E1): Fehlerhafte Einzelframes werden uebersprungen
        (``debayer.frame_failed``); schlagen ALLE Frames fehl -> ValueError
        (kein stilles Ergebnis).
        
        V1.6-2 (BIL-D1): Nutzt debayer_method aus Config.
        """
        debayer_method = self._resolve_debayer_method()
        logger.info("debayer.start", target=context.target.name, method=debayer_method)
        
        result = DebayerResult(working_dir=self.working_dir)
        
        if not calibration_result.calibrated_lights:
            logger.warning("debayer.no_frames")
            return result
        
        self.debayered_dir.mkdir(parents=True, exist_ok=True)
        debayered: List[Path] = []
        for i, frame_path in enumerate(calibration_result.calibrated_lights):
            out_path = self.debayered_dir / f"deb_{i:04d}.fits"
            try:
                debayer_fits(frame_path, out_path, method=debayer_method)
            except Exception as e:
                # T5 (E1): Einzelframe ueberspringen, Rest weiterverarbeiten
                logger.warning("debayer.frame_failed", path=str(frame_path), error=str(e))
                continue
            debayered.append(out_path)
        
        if not debayered:
            logger.error("debayer.empty_result",
                         frames=len(calibration_result.calibrated_lights))
            raise ValueError(
                "Debayer failed for all calibrated light frames — no valid "
                "frames to debayer"
            )
        
        result.debayered_frames = debayered
        seq_path = self.debayered_dir.parent / f"{self.debayered_dir.name}.seq"
        write_seq(seq_path, debayered, prefix="deb_")
        result.seq_path = seq_path
        result.method = debayer_method
        
        logger.info("debayer.complete", 
                    count=len(result.debayered_frames),
                    method=debayer_method,
                    seq=str(result.seq_path))
        return result


def create_debayer_agent(working_dir: Path, config=None, debayer_method_override: str = None) -> DebayerAgent:
    return DebayerAgent(working_dir, config, debayer_method_override)
