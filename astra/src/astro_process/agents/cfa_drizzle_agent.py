"""V1.8-1 CFA-Drizzle Agent (Scale 2.0).

Eigenimplementation (kein Siril Wrapper, OQ-DRZ-5 A).
- register_cfa_subpixel via scikit-image phase_cross_correlation + gaussian_filter(sigma=30) wie PoC, upsample=10, ≤0.1px.
- compute_pixfrac(n_frames) -> 1.0 (<10), 0.7 (10-30), 0.5 (>30) (OQ-DRZ-2 A, stella).
- cfa_drizzle(frames, shifts, scale=2.0, pixfrac, kernel="lanczos3") -> RGB 3840x2160 (Scale 2.0). Bayer-Kanaele R/G1+G2->G/B separat, output/weights Normalisierung, float32, sequentiell frame-fuer-frame (<4GB, OQ-DRZ-4 B).
- CFADrizzleAgent Klasse mit run() analog anderen Agents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import structlog
from astropy.io import fits
from scipy.ndimage import gaussian_filter

logger = structlog.get_logger(__name__)

# ── V19-CFA-GATE G1: CFA vs DEBAYERED Defaults + Resolver ─────────────────

CFA_DEFAULTS = {
    "rejection_enabled": True,
    "thresholds": {
        "fwhm": [1.0, 8.0],
        "snr": [5, None],
        "star_count": [1, None],
        "correlation": [0.1, None],
    },
    "elongation_unusable": True,
    "min_stars_cfa": 1,
}

DEBAYERED_DEFAULTS = {
    "rejection_enabled": True,
    "thresholds": {
        "fwhm": [1.5, 5.0],
        "snr": [10, None],
        "star_count": [20, None],
        "correlation": [0.3, None],
    },
    "elongation_unusable": True,
    "min_stars_cfa": 3,
}


def _warn_if_overly_strict(user_gate: dict, cfa_defaults: dict):
    """G2: Warning wenn User-Schwellen strenger als CFA-Empfehlung."""
    user_thresholds = user_gate.get("thresholds", {}) if user_gate else {}
    if not user_thresholds:
        return
    cfa_thresh = cfa_defaults.get("thresholds", {})
    checks = []
    # star_count >1 ?
    uc = user_thresholds.get("star_count")
    if uc is not None and isinstance(uc, (list, tuple)) and len(uc) >= 1:
        try:
            uv = uc[0]
            cv = cfa_thresh.get("star_count", [1, None])[0]
            if uv is not None and cv is not None and float(uv) > float(cv):
                checks.append(f"star_count={uv} > CFA-Empfehlung {cv}")
        except Exception:
            pass
    uc = user_thresholds.get("snr")
    if uc is not None and isinstance(uc, (list, tuple)) and len(uc) >= 1:
        try:
            uv = uc[0]
            cv = cfa_thresh.get("snr", [5, None])[0]
            if uv is not None and cv is not None and float(uv) > float(cv):
                checks.append(f"snr={uv} > CFA-Empfehlung {cv}")
        except Exception:
            pass
    uc = user_thresholds.get("correlation")
    if uc is not None and isinstance(uc, (list, tuple)) and len(uc) >= 1:
        try:
            uv = uc[0]
            cv = cfa_thresh.get("correlation", [0.1, None])[0]
            if uv is not None and cv is not None and float(uv) > float(cv):
                checks.append(f"correlation={uv} > CFA-Empfehlung {cv}")
        except Exception:
            pass
    uc = user_thresholds.get("fwhm")
    if uc is not None and isinstance(uc, (list, tuple)) and len(uc) >= 2:
        try:
            uv_min = uc[0]
            cv_min = cfa_thresh.get("fwhm", [1.0, 8.0])[0]
            if uv_min is not None and cv_min is not None and float(uv_min) > float(cv_min):
                checks.append(f"fwhm_min={uv_min} > CFA-Empfehlung {cv_min}")
            uv_max = uc[1]
            cv_max = cfa_thresh.get("fwhm", [1.0, 8.0])[1]
            if uv_max is not None and cv_max is not None and float(uv_max) < float(cv_max):
                checks.append(f"fwhm_max={uv_max} < CFA-Empfehlung {cv_max}")
        except Exception:
            pass
    if checks:
        logger.warning(
            "cfa_drizzle.quality_gate_relaxed",
            detail=(
                f"Quality Gate fuer CFA-Drizzle automatisch angepasst: {', '.join(checks)}. "
                f"Bayer-Daten haben andere Statistiken als debayerte RGB. "
                f"Empfohlen: CFA-Defaults nutzen oder Config anpassen."
            ),
            user_thresholds=user_thresholds,
            cfa_defaults=cfa_thresh,
        )


def resolve_cfa_drizzle_quality_gate(user_gate: dict | None, is_cfa: bool = True, cli_overrides: dict | None = None) -> dict:
    """Resolver mit CLI-Precedence. Deep-Merge thresholds rekursiv."""
    if not user_gate and not cli_overrides:
        # Return copy to avoid mutation
        base = CFA_DEFAULTS if is_cfa else DEBAYERED_DEFAULTS
        return {"rejection_enabled": base["rejection_enabled"], "thresholds": dict(base["thresholds"]), "elongation_unusable": base["elongation_unusable"], "min_stars_cfa": base["min_stars_cfa"]}
    base = CFA_DEFAULTS if is_cfa else DEBAYERED_DEFAULTS
    effective = dict(base)
    effective["thresholds"] = {**base["thresholds"], **(user_gate.get("thresholds", {}) if user_gate else {})}
    if user_gate:
        for k, v in user_gate.items():
            if k != "thresholds":
                effective[k] = v
        if is_cfa:
            _warn_if_overly_strict(user_gate, CFA_DEFAULTS)
    if cli_overrides:
        for k, v in cli_overrides.items():
            if k == "thresholds":
                effective["thresholds"].update(v)
            elif k == "star_count":
                effective["thresholds"]["star_count"] = [v, None]
            elif k == "snr_min":
                effective["thresholds"]["snr"] = [v, None]
            elif k == "correlation_min":
                effective["thresholds"]["correlation"] = [v, None]
            elif k == "fwhm_range":
                # fwhm_range as "min,max" string
                try:
                    parts = str(v).split(",")
                    mn = float(parts[0]) if parts[0].strip() else None
                    mx = float(parts[1]) if len(parts) > 1 and parts[1].strip() else None
                    effective["thresholds"]["fwhm"] = [mn, mx]
                except Exception:
                    pass
            else:
                effective[k] = v
        # spezielle CLI-Felder: cli_star_count etc. -> thresholds.star_count
        if "star_count" in cli_overrides and isinstance(cli_overrides["star_count"], (int, float)):
            effective["thresholds"]["star_count"] = [cli_overrides["star_count"], None]
    return effective

# ── Subpixel Registration ──────────────────────────────────────────────

def register_cfa_subpixel(
    ref_cfa: np.ndarray,
    target_cfa: np.ndarray,
    upsample_factor: int = 10,
) -> Tuple[float, float]:
    """Spec-Vorgabe: Hochpass sigma=30 + phase_cross_correlation upsample=10.

    Rueckgabe: (shift_y, shift_x) um target auf ref zu alignen (phase_cross conv).
    Wenn target = shift(ref, (dy,dx)), liefert Funktion (-dy, -dx).
    Genau wie PoC `poc_cfa_drizzle_subpixel.py` (stella OQ Empfehlung, AC-DRZ-3 ≤0.1px).
    """
    try:
        from skimage.registration import phase_cross_correlation
    except ImportError as e:
        raise ImportError("scikit-image required for phase_cross_correlation") from e

    ref_f = ref_cfa.astype(np.float32)
    tgt_f = target_cfa.astype(np.float32)
    ref_hp = ref_f - gaussian_filter(ref_f, 30.0)
    tgt_hp = tgt_f - gaussian_filter(tgt_f, 30.0)
    result = phase_cross_correlation(ref_hp, tgt_hp, upsample_factor=upsample_factor)
    # Neue API: (shift ndarray, error, phasediff); alte: (y,x,error)
    if isinstance(result, tuple) and len(result) == 3:
        first = result[0]
        if isinstance(first, np.ndarray) and first.size == 2:
            shift_arr = first
            return float(shift_arr[0]), float(shift_arr[1])
        else:
            try:
                return float(result[0]), float(result[1])  # type: ignore
            except Exception:
                arr = np.asarray(first)
                return float(arr.flat[0]), float(arr.flat[1])
    elif isinstance(result, np.ndarray):
        return float(result[0]), float(result[1])
    else:
        arr = np.asarray(result)
        return float(arr[0]), float(arr[1])


def compute_pixfrac(n_frames: int, scale: float = 2.0) -> float:
    """Dynamische Pixfrac basierend auf Frame-Anzahl (OQ-DRZ-2 A).

    - <10  -> 1.0 (grosse Drops, Luecken fuellen)
    - 10-30 -> 0.7
    - >30  -> 0.5 (maximale Aufloesung, viele Frames)

    Typische Dwarf Mini Gruppen: M92 41->0.5, M31 90s40 53->0.5, 60s60 16->0.7, 120s60 7->1.0.
    """
    if n_frames < 10:
        return 1.0
    elif n_frames < 30:
        return 0.7
    return 0.5


# ── Kernel Helpers ─────────────────────────────────────────────────────

def _lanczos_weight(dy: float, dx: float, a: int = 3) -> float:
    r = math.hypot(dy, dx)
    if r < 1e-9:
        return 1.0
    if abs(r) >= a:
        return 0.0
    # lanczos = sinc(r) * sinc(r/a)
    # sinc(r) = sin(pi r)/(pi r)
    sinc_r = math.sin(math.pi * r) / (math.pi * r)
    sinc_ra = math.sin(math.pi * r / a) / (math.pi * r / a)
    return sinc_r * sinc_ra


def _gaussian_weight(dy: float, dx: float, sigma: float) -> float:
    r2 = dy * dy + dx * dx
    return math.exp(-r2 / (2 * sigma * sigma)) if sigma > 1e-9 else (1.0 if r2 == 0 else 0.0)


# ── Core Drizzle ───────────────────────────────────────────────────────

def cfa_drizzle(
    frames: List[np.ndarray],
    shifts: List[Tuple[float, float]],
    scale: float = 2.0,
    pixfrac: Optional[float] = None,
    kernel: str = "lanczos3",
) -> np.ndarray:
    """Drizzle auf CFA-Ebene -> RGB (Scale 2.0).

    Bayer-Kanaele R/G1+G2->G/B separat drizzeln, output/weights Normalisierung
    (DrizzlePac-Formel). Kernel lanczos3 Default, gaussian/tophat als Option (reicht Stub/branch).

    Memory: sequentiell frame-fuer-frame, float32, <4GB (OQ-DRZ-4 B).
    Output: RGB (out_H, out_W, 3) float32, out_H=H*scale, out_W=W*scale (3840x2160 fuer 1920x1080).

    Args:
        frames: Liste 2D CFA Arrays (H, W) float32/uint16.
        shifts: Liste (shift_y, shift_x) pro Frame (phase_cross Konvention, um target auf ref zu alignen).
        scale: Aufloesungsfaktor (Default 2.0).
        pixfrac: Drop-Groesse (0.5-1.0). None = auto via compute_pixfrac(len(frames)).
        kernel: "lanczos3" | "gaussian" | "tophat".

    Returns:
        RGB Array (out_H, out_W, 3) float32.
    """
    if not frames:
        raise ValueError("cfa_drizzle: no frames")
    if len(frames) != len(shifts):
        raise ValueError(f"cfa_drizzle: frames {len(frames)} != shifts {len(shifts)}")
    H, W = frames[0].shape
    if any(f.shape != (H, W) for f in frames):
        raise ValueError("cfa_drizzle: frames must have identical shape")
    if pixfrac is None:
        pixfrac = compute_pixfrac(len(frames), scale=scale)
    out_H = int(H * scale)
    out_W = int(W * scale)

    # Output/Weghts je Kanal float32
    output_r = np.zeros((out_H, out_W), dtype=np.float32)
    output_g = np.zeros((out_H, out_W), dtype=np.float32)
    output_b = np.zeros((out_H, out_W), dtype=np.float32)
    weights_r = np.zeros((out_H, out_W), dtype=np.float32)
    weights_g = np.zeros((out_H, out_W), dtype=np.float32)
    weights_b = np.zeros((out_H, out_W), dtype=np.float32)

    # Bayer offsets RGGB
    bayer_specs = [
        ("R", 0, 0, output_r, weights_r, "R"),
        ("G1", 0, 1, output_g, weights_g, "G"),
        ("G2", 1, 0, output_g, weights_g, "G"),
        ("B", 1, 1, output_b, weights_b, "B"),
    ]

    # Kernel params
    footprint = float(pixfrac) * float(scale)  # drop size in output pixels
    # For gaussian, sigma ~ footprint/2.355 (FWHM->sigma) or footprint/2
    sigma = footprint / 2.0 if footprint > 0 else 1.0
    half = footprint / 2.0

    # For lanczos3 we need to handle weights per offset
    # Determine radius for iteration: if footprint <=1.5 single pixel, else 2x2
    use_single = footprint <= 1.5

    for frame, (sy, sx) in zip(frames, shifts):
        # Ensure float32 for memory
        frame_f = frame.astype(np.float32, copy=False)
        for bname, off_y, off_x, out_arr, w_arr, _chn in bayer_specs:
            # Extract plane
            if bname == "R":
                plane = frame_f[0::2, 0::2]
            elif bname == "B":
                plane = frame_f[1::2, 1::2]
            elif bname == "G1":
                plane = frame_f[0::2, 1::2]
            else:  # G2
                plane = frame_f[1::2, 0::2]
            ph, pw = plane.shape
            # Centers in output grid (float, pixel center at 0.5 convention via -0.5)
            # y_center = (y_cfa*scale) ; y_cfa = row*2+off_y+0.5+sy
            # So iterative formula as spec: (np.arange(H)+0.5+sy)*scale -0.5
            # For plane: row*2+off_y
            y_centers = (np.arange(ph, dtype=np.float32) * 2 + off_y + 0.5 + float(sy)) * float(scale) - 0.5
            x_centers = (np.arange(pw, dtype=np.float32) * 2 + off_x + 0.5 + float(sx)) * float(scale) - 0.5

            if use_single:
                # Vectorized single-pixel splat (footprint <=1.5) -> each source maps to one output pixel.
                oy = np.round(y_centers).astype(int)  # (ph,)
                ox = np.round(x_centers).astype(int)  # (pw,)
                # Precompute weights per row/col for kernel
                # dy per row, dx per col
                dy_arr = y_centers - oy.astype(np.float32)  # (ph,)
                dx_arr = x_centers - ox.astype(np.float32)  # (pw,)
                # Build per-element weight matrix ph x pw for kernel
                if kernel == "lanczos3":
                    # Vectorized lanczos via broadcasting: w = lanczos(dy,dx)
                    # Compute r = hypot(dy[:,None], dx[None,:])
                    dy_grid = dy_arr[:, None]  # ph,1
                    dx_grid = dx_arr[None, :]  # 1,pw
                    r = np.hypot(dy_grid, dx_grid)  # ph,pw
                    # lanczos weight
                    # r==0 ->1, r>=3->0
                    w_mat = np.zeros((ph, pw), dtype=np.float32)
                    # Use mask
                    mask = (r < 3) & (r > 1e-9)
                    # For r==0, w=1 already
                    w_mat[r < 1e-9] = 1.0
                    # For 0<r<3
                    r_m = r[mask]
                    w_mat[mask] = (np.sin(np.pi * r_m) / (np.pi * r_m) * np.sin(np.pi * r_m / 3) / (np.pi * r_m / 3)).astype(np.float32)
                    # r>=3 stays 0
                elif kernel == "gaussian":
                    dy2 = (dy_arr**2)[:, None]
                    dx2 = (dx_arr**2)[None, :]
                    w_mat = np.exp(-(dy2 + dx2) / (2*sigma*sigma)).astype(np.float32) if sigma > 0 else np.ones((ph,pw), dtype=np.float32)
                else:  # tophat
                    w_mat = np.ones((ph, pw), dtype=np.float32)
                # Flatten and add via bincount-like scattering
                # Valid mask for oy/ox in bounds
                valid_y = (oy >= 0) & (oy < out_H)
                valid_x = (ox >= 0) & (ox < out_W)
                # Create 2D valid grid
                # Use numpy advanced indexing with np.add.at for weights/output
                # Build flat indices for output 2D -> 1D for add.at
                # Create mesh: oy_2d shape ph,pw ; ox_2d shape ph,pw
                oy_2d = np.broadcast_to(oy[:, None], (ph, pw))
                ox_2d = np.broadcast_to(ox[None, :], (ph, pw))
                valid = valid_y[:, None] & valid_x[None, :] & (w_mat > 1e-6)
                if not np.any(valid):
                    continue
                flat_out_idx_y = oy_2d[valid]
                flat_out_idx_x = ox_2d[valid]
                flat_vals = plane[valid]  # plane is ph,pw, valid selects same
                flat_w = w_mat[valid]
                # Use np.add.at for accumulation (handles duplicate indices via sum)
                # For output and weights, we need 2D arrays; flatten index = y*W + x
                # But np.add.at on 2D with tuple indices works directly
                np.add.at(out_arr, (flat_out_idx_y, flat_out_idx_x), flat_vals * flat_w)
                np.add.at(w_arr, (flat_out_idx_y, flat_out_idx_x), flat_w)
            else:
                # Footprint 2x2: distribute to 2x2 block
                for py in range(ph):
                    yc = float(y_centers[py])
                    y0 = int(math.floor(yc - half + 0.5))
                    y1 = int(math.ceil(yc + half + 0.5))
                    # Clamp handled per y
                    for px in range(pw):
                        v = float(plane[py, px])
                        xc = float(x_centers[px])
                        x0 = int(math.floor(xc - half + 0.5))
                        x1 = int(math.ceil(xc + half + 0.5))
                        for oy in range(y0, y1):
                            if oy < 0 or oy >= out_H:
                                continue
                            dy = yc - (oy + 0.5) + 0.5  # distance from center to output pixel center? Approximation: yc - oy
                            # Simpler: distance = yc - oy
                            dy = yc - float(oy)
                            for ox in range(x0, x1):
                                if ox < 0 or ox >= out_W:
                                    continue
                                dx = xc - float(ox)
                                if kernel == "lanczos3":
                                    w = _lanczos_weight(dy, dx)
                                elif kernel == "gaussian":
                                    w = _gaussian_weight(dy, dx, sigma)
                                else:  # tophat
                                    w = 1.0 if max(abs(dy), abs(dx)) < half + 1e-6 else 0.0
                                if w <= 1e-6:
                                    continue
                                out_arr[oy, ox] += v * w
                                w_arr[oy, ox] += w

    # Normalisation output/weights
    rgb = np.zeros((out_H, out_W, 3), dtype=np.float32)
    # R
    mask_r = weights_r > 1e-6
    rgb[mask_r, 0] = (output_r[mask_r] / weights_r[mask_r]).astype(np.float32)
    mask_g = weights_g > 1e-6
    rgb[mask_g, 1] = (output_g[mask_g] / weights_g[mask_g]).astype(np.float32)
    mask_b = weights_b > 1e-6
    rgb[mask_b, 2] = (output_b[mask_b] / weights_b[mask_b]).astype(np.float32)

    # Holes: where weights zero, leave 0 (or could fill with median, but test expects no NaN)
    # Ensure finite
    rgb[~np.isfinite(rgb)] = 0

    logger.info("cfa_drizzle.complete", scale=scale, pixfrac=pixfrac, kernel=kernel, n_frames=len(frames), out_shape=list(rgb.shape))
    return rgb


# ── Agent ───────────────────────────────────────────────────────────────

@dataclass
class CFADrizzleResult:
    group_hash: str
    drizzled_master: Optional[Path] = None
    drizzled_cfa: Optional[Path] = None
    n_frames_in: int = 0
    n_frames_out: int = 0
    scale: float = 2.0
    pixfrac: float = 0.5
    kernel: str = "lanczos3"
    status: str = "ok"  # ok | fallback | skipped
    fallback_method: Optional[str] = None


class CFADrizzleAgent:
    """Agent fuer CFA-Drizzle pro Gruppe (V1.8-1).

    Input = calibrated lights (2D CFA) je Gruppe, nutzt QualityGate filtering
    (nur non-outlier), min_frames Guard, fallback malvar/superpixel/skip,
    schreibt pro Gruppe `group_*/01c_drizzle/drizzled_master.fits` (und drizzled_cfa.fits optional) 3840x2160.
    """

    def __init__(self, working_dir: Path, config=None):
        self.working_dir = Path(working_dir)
        self.config = config
        self.logger = structlog.get_logger(__name__)

    def _resolve_config(self):
        from ..config.loader import resolve_cfa_drizzle
        from ..config.models import PipelinePreset
        # Dummy pipeline for resolver (only config matters when CLI not used)
        dummy = PipelinePreset(name="dummy", target_types=["*"], steps=[])
        return resolve_cfa_drizzle(self.config if self.config else type("C", (), {"cfa_drizzle": None})(), None, None, None, None)

    def run(
        self,
        context=None,
        calibration_result=None,
        groups: Optional[dict] = None,
        calibrated_by_group: Optional[dict] = None,
    ) -> List[CFADrizzleResult]:
        """Run CFA-Drizzle per Gruppe.

        Wenn cfa_drizzle.enabled false -> pass-through (kein Overhead, keine Outputs).
        Sonst pro Gruppe: QualityGate -> min_frames -> register/shifts -> drizzle -> save.

        Returns list of CFADrizzleResult (je Gruppe).
        """
        from ..config.loader import resolve_cfa_drizzle
        from ..config.models import PipelinePreset
        dummy = PipelinePreset(name="dummy", target_types=["*"], steps=[])
        cfg_obj = self.config if self.config is not None else type("C", (), {"cfa_drizzle": None})()
        drz_cfg = resolve_cfa_drizzle(cfg_obj, None, None, None, None)

        if not drz_cfg.enabled:
            self.logger.info("cfa_drizzle.disabled", msg="CFA-Drizzle disabled (AC-DRZ-1 byte-identisch)")
            return []

        results: List[CFADrizzleResult] = []

        # Need mapping if not provided: build from context
        if calibrated_by_group is None and context is not None and calibration_result is not None:
            from ..models.core import compute_group_hash
            lights = context.get_lights()
            calibrated_by_group = {h: [] for h in (groups or {})}
            # Map calibrated_lights index to group via lights header
            for i, f in enumerate(lights.frames):
                if not f.header:
                    continue
                exptime = f.header.exptime if f.header.exptime is not None else 0.0
                gain = f.header.gain if f.header.gain is not None else 0
                filter_name = f.header.filter_name if f.header.filter_name else ""
                gh = compute_group_hash(float(exptime), int(gain), str(filter_name))
                if gh in calibrated_by_group and i < len(calibration_result.calibrated_lights):
                    calibrated_by_group[gh].append(calibration_result.calibrated_lights[i])
            if groups is None:
                groups = {gh: None for gh in calibrated_by_group}

        if not calibrated_by_group:
            return results

        for group_hash, cfa_paths in calibrated_by_group.items():
            n_in = len(cfa_paths)
            # Load frames as 2D CFA
            cfa_frames: List[np.ndarray] = []
            valid_paths: List[Path] = []
            for p in cfa_paths:
                try:
                    with fits.open(p) as hdul:
                        data = hdul[0].data.astype(np.float32)
                        if data.ndim == 3:
                            # Already debayered -> cannot drizzle (fallback)
                            raise ValueError("already RGB, not CFA")
                        # Handle BZERO
                        hdr = hdul[0].header
                        bzero = hdr.get("BZERO", 0.0)
                        if bzero != 0.0:
                            data = data - bzero
                        cfa_frames.append(data)
                        valid_paths.append(p)
                except Exception as e:
                    self.logger.warning("cfa_drizzle.frame_load_failed", group=group_hash, path=str(p), error=str(e))
                    continue

            if not cfa_frames:
                results.append(CFADrizzleResult(group_hash=group_hash, n_frames_in=n_in, n_frames_out=0, status="skipped", fallback_method=drz_cfg.fallback))
                continue

            # Quality Gate filtering (nur non-outlier) — V19-CFA-GATE G5: Resolver statt direkter Config
            from ..core.quality import compute_frame_quality, reject_outlier_frames
            qg = drz_cfg.quality_gate
            # Mode handling G3: auto -> CFA bei is_cfa True
            try:
                mode = getattr(qg, "mode", "auto") if qg is not None else "auto"
            except Exception:
                mode = "auto"
            is_cfa_input = True  # CFA-Drizzle laeuft nur auf CFA-Raw
            if mode == "cfa":
                is_cfa_effective = True
            elif mode == "debayered":
                is_cfa_effective = False
            else:
                is_cfa_effective = is_cfa_input
            # User gate als dict (inkl. mode, thresholds)
            user_gate = None
            if qg is not None:
                try:
                    if hasattr(qg, "model_dump"):
                        user_gate = qg.model_dump()
                    else:
                        user_gate = dict(qg)  # type: ignore
                except Exception:
                    user_gate = {"thresholds": dict(qg.thresholds) if getattr(qg, "thresholds", None) else {}, "rejection_enabled": getattr(qg, "rejection_enabled", True), "elongation_unusable": getattr(qg, "elongation_unusable", True), "min_stars_cfa": getattr(qg, "min_stars_cfa", 3)}
            cli_overrides = getattr(self.config, "_cfa_cli_overrides", None) if self.config else None
            # Resolver
            effective_gate = resolve_cfa_drizzle_quality_gate(user_gate, is_cfa=is_cfa_effective, cli_overrides=cli_overrides)
            # Qualities berechnen mit effective min_stars
            effective_min_stars = effective_gate.get("min_stars_cfa", 3)
            effective_highpass = getattr(qg, "highpass_sigma", 30.0) if qg is not None else 30.0
            # thresholds rekursiv bereits gemerged
            thresholds = dict(effective_gate.get("thresholds", {}))
            # legacy star_count_cfa fallback: wenn noch im user_gate vorhanden und nicht ueberschrieben, bereits in effective
            elong_enabled = bool(effective_gate.get("elongation_unusable", True))
            qualities = []
            for idx, arr in enumerate(cfa_frames):
                try:
                    q = compute_frame_quality(
                        arr,
                        min_stars=effective_min_stars,
                        cfa_mode=True,
                        cfa_highpass_sigma=effective_highpass,
                    )
                    q.frame = str(valid_paths[idx])
                    qualities.append(q)
                except Exception as e:
                    self.logger.warning("cfa_drizzle.quality_failed", group=group_hash, error=str(e))
                    q = type("Q", (), {"frame": str(valid_paths[idx]), "snr": 0, "fwhm_median": None, "star_count": 0, "correlation": None, "elongation_unusable": False})()
                    qualities.append(q)  # fallback

            try:
                filtered_qualities = reject_outlier_frames(
                    qualities,  # type: ignore
                    thresholds=thresholds,
                    elongation_unusable_enabled=elong_enabled,
                )
            except Exception as e:
                self.logger.warning("cfa_drizzle.rejection_failed", group=group_hash, error=str(e))
                filtered_qualities = qualities

            # Keep only non-outlier (outlier_excluded False)
            good_indices = [i for i, q in enumerate(filtered_qualities) if not getattr(q, "outlier_excluded", False)]
            # If rejection disabled, all are good
            if not effective_gate.get("rejection_enabled", True):
                good_indices = list(range(len(cfa_frames)))
                filtered_qualities = qualities

            good_frames = [cfa_frames[i] for i in good_indices]
            good_paths = [valid_paths[i] for i in good_indices]
            n_out = len(good_frames)

            # min_frames Guard
            if n_out < drz_cfg.min_frames:
                self.logger.warning(
                    "cfa_drizzle.min_frames_fallback",
                    group=group_hash,
                    n_frames_in=n_in,
                    n_frames_out=n_out,
                    min_frames=drz_cfg.min_frames,
                    fallback=drz_cfg.fallback,
                )
                if drz_cfg.fallback == "skip":
                    results.append(CFADrizzleResult(group_hash=group_hash, n_frames_in=n_in, n_frames_out=n_out, status="skipped", fallback_method="skip", scale=drz_cfg.scale, pixfrac=drz_cfg.pixfrac if drz_cfg.pixfrac_mode=="fixed" else compute_pixfrac(n_out, drz_cfg.scale), kernel=drz_cfg.kernel))
                    continue
                elif drz_cfg.fallback in ("malvar", "superpixel"):
                    # Fallback: no drizzle, caller will use debayer path. Mark as fallback so merge knows.
                    results.append(CFADrizzleResult(group_hash=group_hash, n_frames_in=n_in, n_frames_out=n_out, status="fallback", fallback_method=drz_cfg.fallback, scale=drz_cfg.scale, pixfrac=drz_cfg.pixfrac if drz_cfg.pixfrac_mode=="fixed" else compute_pixfrac(n_out, drz_cfg.scale), kernel=drz_cfg.kernel))
                    continue
                else:
                    results.append(CFADrizzleResult(group_hash=group_hash, n_frames_in=n_in, n_frames_out=n_out, status="skipped", fallback_method=drz_cfg.fallback))
                    continue

            # Compute shifts: ref = first good frame, others via register_cfa_subpixel
            ref = good_frames[0]
            shifts: List[Tuple[float,float]] = [(0.0,0.0)]
            for tgt in good_frames[1:]:
                try:
                    sy, sx = register_cfa_subpixel(ref, tgt, upsample_factor=10)
                    shifts.append((sy, sx))
                except Exception as e:
                    self.logger.warning("cfa_drizzle.registration_failed", group=group_hash, error=str(e))
                    shifts.append((0.0,0.0))

            # Pixfrac
            if drz_cfg.pixfrac_mode == "fixed":
                pixfrac = float(drz_cfg.pixfrac)
            else:
                pixfrac = compute_pixfrac(n_out, scale=drz_cfg.scale)

            # Drizzle
            try:
                rgb = cfa_drizzle(good_frames, shifts, scale=float(drz_cfg.scale), pixfrac=pixfrac, kernel=drz_cfg.kernel)
            except Exception as e:
                self.logger.warning("cfa_drizzle.failed", group=group_hash, error=str(e))
                results.append(CFADrizzleResult(group_hash=group_hash, n_frames_in=n_in, n_frames_out=n_out, status="fallback", fallback_method=drz_cfg.fallback, scale=drz_cfg.scale, pixfrac=pixfrac, kernel=drz_cfg.kernel))
                continue

            # Save
            group_dir = self.working_dir / f"group_{group_hash}"
            drizzle_dir = group_dir / "01c_drizzle"
            drizzle_dir.mkdir(parents=True, exist_ok=True)
            stack_dir = group_dir / "04_stacked"
            stack_dir.mkdir(parents=True, exist_ok=True)
            drizzled_master_path = drizzle_dir / "drizzled_master.fits"
            # Save RGB as FITS (C,H,W)
            out = rgb.astype(np.float32)
            # Transpose to FITS (C,H,W)
            hdu = fits.PrimaryHDU(out.transpose(2,0,1))
            hdu.header["CTYPE3"] = "RGB"
            hdu.header["BAYERPAT"] = "RGGB"
            hdu.header["DRZSCALE"] = float(drz_cfg.scale)
            hdu.header["DRZPIXFR"] = float(pixfrac)
            hdu.header["DRZKERNL"] = drz_cfg.kernel
            hdu.header["NFRAMES"] = n_out
            hdu.writeto(drizzled_master_path, overwrite=True)

            # Optional drizzled_cfa.fits (2x CFA) - create dummy 2D version by averaging RGB weighted? Simplified: create 2D CFA 2x by interleaving R/G/B
            # For now create same as master but 2D by taking luminance? Optional, we write drizzled_cfa as 2D CFA (out_H,out_W) by mosaicing RGB back to Bayer RGGB.
            drizzled_cfa_path = drizzle_dir / "drizzled_cfa.fits"
            try:
                out_H, out_W = rgb.shape[0], rgb.shape[1]
                cfa2d = np.zeros((out_H, out_W), dtype=np.float32)
                # mosaic: R at (0,0), G at (0,1)+(1,0), B at (1,1)
                cfa2d[0::2, 0::2] = rgb[0::2, 0::2, 0]
                cfa2d[0::2, 1::2] = rgb[0::2, 1::2, 1]
                cfa2d[1::2, 0::2] = rgb[1::2, 0::2, 1]
                cfa2d[1::2, 1::2] = rgb[1::2, 1::2, 2]
                hdu2 = fits.PrimaryHDU(cfa2d)
                hdu2.header["BAYERPAT"] = "RGGB"
                hdu2.header["DRZSCALE"] = float(drz_cfg.scale)
                hdu2.writeto(drizzled_cfa_path, overwrite=True)
            except Exception as e:
                self.logger.warning("cfa_drizzle.cfa_save_failed", group=group_hash, error=str(e))
                drizzled_cfa_path = None

            # Also copy to stack_dir/stacked.fits for downstream (PCC, merge) – mirrors multi_group_agent behaviour
            try:
                import shutil as _sh2
                _sh2.copy2(drizzled_master_path, stack_dir / "stacked.fits")
            except Exception as e:
                self.logger.warning("cfa_drizzle.stack_copy_failed", group=group_hash, error=str(e))

            self.logger.info(
                "cfa_drizzle.complete",
                group=group_hash,
                scale=float(drz_cfg.scale),
                pixfrac=float(pixfrac),
                kernel=drz_cfg.kernel,
                n_frames_in=n_in,
                n_frames_out=n_out,
            )

            results.append(CFADrizzleResult(
                group_hash=group_hash,
                drizzled_master=drizzled_master_path,
                drizzled_cfa=drizzled_cfa_path,
                n_frames_in=n_in,
                n_frames_out=n_out,
                scale=float(drz_cfg.scale),
                pixfrac=float(pixfrac),
                kernel=drz_cfg.kernel,
                status="ok",
            ))

        return results


def create_cfa_drizzle_agent(working_dir: Path, config=None) -> CFADrizzleAgent:
    return CFADrizzleAgent(working_dir, config)

