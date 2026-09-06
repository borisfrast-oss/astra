"""Core data models for the Astra processing pipeline."""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, ConfigDict
import yaml


class FrameType(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    FLAT = "flat"
    BIAS = "bias"
    DARK_FLAT = "dark_flat"
    UNKNOWN = "unknown"


class TargetType(str, Enum):
    GALAXY = "galaxy"
    NEBULA = "nebula"
    STAR = "star"
    CLUSTER = "cluster"
    PLANETARY_NEBULA = "planetary_nebula"
    COMET = "comet"
    SOLAR_SYSTEM = "solar_system"
    UNKNOWN = "unknown"


class FitsHeader(BaseModel):
    model_config = ConfigDict(extra="allow")
    
    object: Optional[str] = None
    exptime: Optional[float] = None
    gain: Optional[int] = None
    offset: Optional[int] = None
    ccd_temp: Optional[float] = None
    filter_name: Optional[str] = None
    xbinning: int = 1
    ybinning: int = 1
    date_obs: Optional[datetime] = None
    telescope: Optional[str] = None
    instrument: Optional[str] = None
    focal_length: Optional[float] = None
    aperture: Optional[float] = None
    pixel_size_x: Optional[float] = None
    pixel_size_y: Optional[float] = None
    site_lat: Optional[float] = None
    site_lon: Optional[float] = None
    site_elev: Optional[float] = None
    ra: Optional[float] = None
    dec: Optional[float] = None
    # V1.3-6 (EQ-B): EQMODE aus dem Light-Header — 0=AZ, 1=EQ, None=unbekannt.
    # Additiv/lesend (OQ-V1.3-6-2, Boris 2026-08-08): kein Schema-Bruch;
    # konsumiert von der V1.3-1-Empfehlung (resolve_eq_flag).
    eq_mode: Optional[int] = None
    raw_cards: dict = Field(default_factory=dict)


class FrameInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    path: Path
    frame_type: FrameType
    header: Optional[FitsHeader] = None
    index: int = 0
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    checksum: Optional[str] = None


class FrameSet(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    frame_type: FrameType
    frames: list[FrameInfo] = Field(default_factory=list)
    
    @property
    def count(self) -> int:
        return len(self.frames)
    
    def group_by_filter(self) -> dict[str, list[FrameInfo]]:
        groups = {}
        for f in self.frames:
            key = f.header.filter_name if f.header and f.header.filter_name else "none"
            groups.setdefault(key, []).append(f)
        return groups
    
    def group_by_exptime(self) -> dict[float, list[FrameInfo]]:
        groups = {}
        for f in self.frames:
            key = f.header.exptime if f.header and f.header.exptime else 0.0
            groups.setdefault(key, []).append(f)
        return groups
    
    def group_by_params(self, keys: Optional[list[str]] = None) -> dict[tuple, FrameSet]:
        """Group frames by acquisition parameters.
        
        Groups frames by the specified FITS header keys. Handles missing
        header values gracefully with fallbacks.
        
        Args:
            keys: List of FITS header keywords to group by.
                  Default: ["EXPTIME", "GAIN", "FILTER"]
                  
        Returns:
            Dict mapping parameter tuples to FrameSet instances
        """
        if keys is None:
            keys = ["EXPTIME", "GAIN", "FILTER"]
        
        groups: dict[tuple, list[FrameInfo]] = {}
        for f in self.frames:
            if not f.header:
                continue
            key_parts = []
            for k in keys:
                if k == "EXPTIME":
                    key_parts.append(f.header.exptime if f.header.exptime is not None else 0.0)
                elif k == "GAIN":
                    key_parts.append(f.header.gain if f.header.gain is not None else 0)
                elif k == "FILTER":
                    key_parts.append(f.header.filter_name if f.header.filter_name else "none")
                else:
                    key_parts.append(None)
            key = tuple(key_parts)
            groups.setdefault(key, []).append(f)
        
        return {k: FrameSet(frame_type=self.frame_type, frames=v) for k, v in groups.items()}
    
    def get_for_calibration(self, exptime: float, gain: int, filter_name: Optional[str] = None, temp: Optional[float] = None, temp_tolerance: float = 3.0) -> list[FrameInfo]:
        """Get frames matching calibration frames suitable for calibration of given parameters."""
        candidates = []
        for f in self.frames:
            if not f.header:
                continue
            # EXPTIME tolerance instead of exact match.
            # None-Guard: header-lose Frames (leerer FITS-Header + unparsbarer
            # Dateiname -> exptime None) werden uebersprungen, nicht crashen
            # (konsistent mit `if not f.header: continue`; Bug 2026-08-09).
            if f.header.exptime is None or abs(f.header.exptime - exptime) > 0.5:
                continue
            if filter_name and (
                f.header.filter_name is None or f.header.filter_name != filter_name
            ):
                continue
            # Gain matching (None-Guard analog zu EXPTIME)
            if f.header.gain is None or f.header.gain != gain:
                continue
            if temp and f.header.ccd_temp:
                if abs(f.header.ccd_temp - temp) > temp_tolerance:
                    continue
            candidates.append(f)
        return candidates


@dataclass
class GroupInfo:
    """Information about a group of frames with matching acquisition parameters."""
    key: tuple           # (exptime, gain, filter)
    hash: str            # Human-readable hash for directory naming
    frame_count: int
    total_exposure: float
    working_dir: Optional[Path] = None


def compute_group_hash(exptime: float, gain: int, filter_name: str) -> str:
    """Compute a human-readable group hash from acquisition parameters.
    
    Produces strings like "15s60" for (15.0, 60, "none")
    or "60s40_Duo-Band" for (60.0, 40, "Duo-Band").
    
    Args:
        exptime: Exposure time in seconds
        gain: Camera gain
        filter_name: Filter name from FITS header
        
    Returns:
        Human-readable hash string suitable for directory names
    """
    exptime_str = f"{exptime:.0f}s" if float(exptime) == int(exptime) else f"{exptime}s"
    gain_str = str(gain)
    safe_filter = filter_name.strip().replace(" ", "_") if filter_name and filter_name.lower() not in ("none", "") else ""
    if safe_filter:
        return f"{exptime_str}{gain_str}_{safe_filter}"
    return f"{exptime_str}{gain_str}"


class ObservationTarget(BaseModel):
    name: str
    target_type: TargetType = TargetType.UNKNOWN
    ra: Optional[float] = None
    dec: Optional[float] = None
    magnitude: Optional[float] = None
    size_arcmin: Optional[float] = None


class EquipmentInfo(BaseModel):
    telescope: Optional[str] = None
    aperture_mm: Optional[int] = None
    focal_length_mm: Optional[int] = None
    camera: Optional[str] = None
    pixel_size_um: Optional[float] = None
    filters: list[str] = Field(default_factory=list)
    # V1.7-4 (EQPT-B): Aufloesung des ersten Light-Frames (NAXIS1/NAXIS2 —
    # bei 3D-Daten die beiden Bildachsen, scan_directory nutzt shape[-2:]).
    # Rein dokumentarisch in v1.7 (OQ-EQPT-2: KEINE Verhaltenssteuerung).
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    # V1.7-4 (EQPT-C): Bayer-Pattern best effort aus dem Header
    # (BAYERPAT o.ae.). None = RGGB-Annahme (heutiges Verhalten,
    # debayer_superpixel arbeitet layout-fix).
    bayer_pattern: Optional[str] = None
    # V1.7-4 (EQPT-D): Quelle je Feld — "fits_header" | "config" | "none".
    # Befuellt durch resolve_equipment() (core/equipment.py); leere Keys
    # bedeuten "nicht aufgeloest" (Legacy-Pfade).
    sources: Dict[str, str] = Field(default_factory=dict)
    # V1.7-4 (OQ-EQPT-1): gematchtes Config-Equipment-Profil (oder None,
    # wenn kein Profil greift).
    profile_name: Optional[str] = None


class AcquisitionInfo(BaseModel):
    date: Optional[datetime] = None
    location: Optional[str] = None
    bortle: Optional[int] = None
    gain: Optional[int] = None
    offset: Optional[int] = None
    temperature_c: Optional[float] = None
    total_integration_time: float = 0.0
    notes: Optional[str] = None


class CalibrationStatus(BaseModel):
    dark_available: bool = False
    flat_available: bool = False
    bias_available: bool = False
    dark_flat_available: bool = False
    dark_count: int = 0
    flat_count: int = 0
    bias_count: int = 0
    dark_flat_count: int = 0
    # W5: Dark source per group for reporting
    dark_sources: Dict[str, str] = Field(default_factory=dict)


class ObservationContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    target: ObservationTarget
    frames: dict[FrameType, FrameSet] = Field(default_factory=dict)
    calibration: CalibrationStatus = Field(default_factory=CalibrationStatus)
    equipment: EquipmentInfo = Field(default_factory=EquipmentInfo)
    acquisition: AcquisitionInfo = Field(default_factory=AcquisitionInfo)
    source_path: Path
    created_at: datetime = Field(default_factory=datetime.now)
    
    def get_lights(self) -> FrameSet:
        return self.frames.get(FrameType.LIGHT, FrameSet(frame_type=FrameType.LIGHT))
    
    def get_darks(self) -> FrameSet:
        return self.frames.get(FrameType.DARK, FrameSet(frame_type=FrameType.DARK))
    
    def get_flats(self) -> FrameSet:
        return self.frames.get(FrameType.FLAT, FrameSet(frame_type=FrameType.FLAT))
    
    def get_bias(self) -> FrameSet:
        return self.frames.get(FrameType.BIAS, FrameSet(frame_type=FrameType.BIAS))
    
    def get_dark_flats(self) -> FrameSet:
        return self.frames.get(FrameType.DARK_FLAT, FrameSet(frame_type=FrameType.DARK_FLAT))
    
    @property
    def total_light_frames(self) -> int:
        return self.get_lights().count
    
    @property
    def total_integration_time(self) -> float:
        lights = self.get_lights()
        return sum(
            f.header.exptime for f in lights.frames 
            if f.header and f.header.exptime
        )
    
    def to_yaml(self, path: Optional[Path] = None) -> str:
        """Serialize to YAML."""
        data = self.model_dump(exclude={"frames"})
        # Add frames summary
        data["frame_summary"] = {
            ft.value: fs.count for ft, fs in self.frames.items()
        }
        yaml_str = yaml.dump(data, allow_unicode=True, sort_keys=False)
        if path:
            path.write_text(yaml_str, encoding="utf-8")
        return yaml_str
    
    @classmethod
    def from_yaml(cls, path: Path) -> "ObservationContext":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        # Frames need special handling
        return cls(**data)


# Processing phase states
class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PhaseResult(BaseModel):
    phase: str
    status: PhaseStatus = PhaseStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    input_files: list[str] = Field(default_factory=list)
    output_files: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class PipelineConfig(BaseModel):
    name: str
    target_type: TargetType
    steps: list[str] = Field(default_factory=list)
    processing_params: dict = Field(default_factory=dict)
    graxpert_params: dict = Field(default_factory=dict)
    gimp_params: dict = Field(default_factory=dict)


# Default pipeline presets
GALAXY_STANDARD = PipelineConfig(
    name="galaxy_standard",
    target_type=TargetType.GALAXY,
    steps=[
        "create_master_dark",
        "create_master_bias",
        "calibrate_lights",
        "register_frames",
        "stack_frames",
        "background_extraction",
        "photometric_color_calibration",
        "stretch",
        "export",
    ],
    processing_params={
        "registration_method": "global",
        "stacking_method": "weighted",
        "rejection": "winsorized",
        "normalization": "mul",
        "weight": "noise",
    }
)

NEBULA_ENHANCED = PipelineConfig(
    name="nebula_enhanced",
    target_type=TargetType.NEBULA,
    steps=[
        "create_master_dark",
        "create_master_bias",
        "calibrate_lights",
        "register_frames",
        "stack_frames",
        "graxpert_gradient_removal",
        "background_extraction",
        "structure_enhancement",
        "star_reduction",
        "photometric_color_calibration",
        "stretch",
        "export",
    ],
    processing_params={
        "registration_method": "global",
        "stacking_method": "weighted",
        "rejection": "winsorized",
    },
    graxpert_params={
        "model": "background",
        "strength": 1.0,
    }
)

STAR_STANDARD = PipelineConfig(
    name="star_standard",
    target_type=TargetType.STAR,
    steps=[
        "create_master_dark",
        "calibrate_lights",
        "register_frames",
        "stack_frames",
        "natural_color_calibration",
        "gentle_stretch",
        "export",
    ],
    processing_params={
        "registration_method": "translation",
        "stacking_method": "average",
        "rejection": "none",
    }
)

CLUSTER_STANDARD = PipelineConfig(
    name="cluster_standard",
    target_type=TargetType.CLUSTER,
    steps=[
        "create_master_dark",
        "calibrate_lights",
        "register_frames",
        "stack_frames",
        "star_preserving_stretch",
        "export",
    ],
    processing_params={
        "registration_method": "global",
        "stacking_method": "weighted",
    }
)


PRESETS = {
    "galaxy_standard": GALAXY_STANDARD,
    "nebula_enhanced": NEBULA_ENHANCED,
    "star_standard": STAR_STANDARD,
    "cluster_standard": CLUSTER_STANDARD,
}