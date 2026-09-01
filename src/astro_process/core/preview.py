"""Auto-stretched JPG preview generation for quick visual inspection."""

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
import structlog

if TYPE_CHECKING:
    from ..config.models import PreviewExportConfig

logger = structlog.get_logger(__name__)


def auto_asinh(data: np.ndarray, sigma_factor: float = 3.0) -> np.ndarray:
    """Auto-stretch linear astro data using asinh (arcsinh) stretch.
    
    This is the standard stretch used in astrophotography (same as Siril's
    autostretch). It compresses bright star cores while lifting faint details.
    
    Steps:
    1. Subtract background (median per channel)
    2. Clip negative values
    3. Robust noise estimate (MAD→sigma)
    4. Arcsinh stretch: stretched = asinh(data / (sigma * sigma_factor))
    5. Normalize to [0, 1]
    
    Args:
        data: Linear float32 array (H×W or H×W×C)
        sigma_factor: How many sigma above background to stretch (3=Siril default)
        
    Returns:
        Stretched float64 array in range [0, 1]
    """
    data = data.astype(np.float64)
    
    if data.ndim == 3:
        # Per-channel stretch to preserve color balance
        result = np.zeros_like(data)
        for c in range(data.shape[-1]):
            result[:, :, c] = _apply_asinh(data[:, :, c], sigma_factor)
        return result
    else:
        return _apply_asinh(data, sigma_factor)


def _apply_asinh(channel: np.ndarray, sigma_factor: float) -> np.ndarray:
    """Apply asinh stretch to a single channel."""
    # Background subtraction (robust median)
    bg = np.median(channel)
    stretched = channel - bg
    stretched = np.clip(stretched, 0.0, None)
    
    # Robust noise estimate via MAD
    mad = np.median(np.abs(channel - bg))
    sigma = float(mad) * 1.4826 if mad > 0 else 1.0
    
    stretch_val = max(sigma * sigma_factor, 1e-10)
    stretched = np.arcsinh(stretched / stretch_val)
    
    # Normalize to [0, 1]
    mx = np.max(stretched)
    if mx > 0:
        stretched = stretched / mx
    
    return stretched


def _apply_background_neutralization(data: np.ndarray) -> np.ndarray:
    """Median-basierte Hintergrund-Neutralisierung (V1.8-2, AC-PREV-A3).

    Schätzt den Hintergrund-Median pro Kanal, zieht ihn ab und clamped
    auf >= 0. Robust gegen Gradienten/Offsets in linearen Daten.
    """
    result = data.astype(np.float64).copy()
    if result.ndim == 3:
        for c in range(result.shape[-1]):
            bg = np.median(result[:, :, c])
            result[:, :, c] -= bg
    else:
        bg = np.median(result)
        result -= bg
    return np.clip(result, 0.0, None)


def _apply_saturation(data: np.ndarray, factor: float) -> np.ndarray:
    """Sättigungsanpassung in HSV (V1.8-2, AC-PREV-A2).

    factor=1.0 -> neutral. Werte im Bereich 0.5..2.0 validiert.
    Kein Clipping, keine NaN/Inf.
    """
    if factor == 1.0:
        return data
    if data.ndim != 3 or data.shape[-1] != 3:
        return data

    # RGB -> HSV (vectorized)
    r = data[:, :, 0].astype(np.float64)
    g = data[:, :, 1].astype(np.float64)
    b = data[:, :, 2].astype(np.float64)

    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    delta = mx - mn

    # Hue
    h = np.zeros_like(mx)
    mask = delta > 0
    r_eq = np.isclose(mx, r) & mask
    g_eq = np.isclose(mx, g) & mask & ~r_eq
    b_eq = np.isclose(mx, b) & mask & ~r_eq & ~g_eq
    h[r_eq] = ((g[r_eq] - b[r_eq]) / delta[r_eq]) % 6.0
    h[g_eq] = ((b[g_eq] - r[g_eq]) / delta[g_eq]) + 2.0
    h[b_eq] = ((r[b_eq] - g[b_eq]) / delta[b_eq]) + 4.0
    h = h / 6.0

    # Saturation
    s = np.zeros_like(mx)
    mx_pos = mx > 0
    s[mx_pos] = delta[mx_pos] / mx[mx_pos]

    # Value
    v = mx.copy()

    # Adjust saturation
    s = np.clip(s * factor, 0.0, 1.0)

    # HSV -> RGB
    hi = (h * 6.0).astype(np.int32) % 6
    f = (h * 6.0) - hi
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)

    rgb = np.zeros(data.shape, dtype=np.float64)
    for i in range(6):
        m = hi == i
        if i == 0:
            rgb[:, :, 0][m] = v[m]
            rgb[:, :, 1][m] = t[m]
            rgb[:, :, 2][m] = p[m]
        elif i == 1:
            rgb[:, :, 0][m] = q[m]
            rgb[:, :, 1][m] = v[m]
            rgb[:, :, 2][m] = p[m]
        elif i == 2:
            rgb[:, :, 0][m] = p[m]
            rgb[:, :, 1][m] = v[m]
            rgb[:, :, 2][m] = t[m]
        elif i == 3:
            rgb[:, :, 0][m] = p[m]
            rgb[:, :, 1][m] = q[m]
            rgb[:, :, 2][m] = v[m]
        elif i == 4:
            rgb[:, :, 0][m] = t[m]
            rgb[:, :, 1][m] = p[m]
            rgb[:, :, 2][m] = v[m]
        elif i == 5:
            rgb[:, :, 0][m] = v[m]
            rgb[:, :, 1][m] = p[m]
            rgb[:, :, 2][m] = q[m]

    return rgb


def _apply_stretch(data: np.ndarray, method: str, sigma_factor: float) -> np.ndarray:
    """Stretch-Schritt (V1.8-2).

    - asinh: bestehende auto_asinh (rueckwaertskompatibel zu v1.6).
    - linear: lineare Normalisierung auf [0, 1] (globaler Max-Wert).
    - none: kein Stretch, nur cast nach float64.
    """
    if method == "asinh":
        return auto_asinh(data, sigma_factor=sigma_factor)
    if method == "linear":
        arr = data.astype(np.float64)
        mx = np.max(arr)
        if mx > 0:
            arr = arr / mx
        return arr
    # method == "none"
    return data.astype(np.float64)


def create_preview_jpg(
    fits_path: Path, jpg_path: Path, quality: int = 85,
    stretch_factor: float = 1000.0,
    preview_config: Optional["PreviewExportConfig"] = None,
) -> Optional[Path]:
    """Create an auto-stretched JPG preview from a linear FITS file.

    Uses asinh (arcsinh) stretch for better dynamic range in astro images
    (compresses bright star cores while lifting faint nebula detail).

    V1.8-2: Optional ``preview_config`` aktiviert die erweiterte Pipeline
    (background_neutralization -> scnr -> stretch -> saturation -> jpg).
    Ohne ``preview_config`` bleibt das Verhalten byte-identisch zu v1.6.

    Args:
        fits_path: Path to input linear FITS file (H×W×3 RGB)
        jpg_path: Path for output JPG file
        quality: JPEG quality (0-100)
        stretch_factor: Asinh stretch factor (Default 1000.0). Higher values
            produce a more linear (less stretched) result; lower values
            produce a more aggressive stretch. Typical range: 100-5000.
        preview_config: V1.8-2 Preview/Export-Pipeline Einstellungen.
            ``None`` -> Asinh-only Verhalten (v1.6).

    Returns:
        Path to JPG if created, None on failure
    """
    try:
        from astropy.io import fits
        from PIL import Image
    except ImportError as e:
        logger.warning("preview.unavailable", package=e.name)
        return None

    try:
        # Load FITS
        with fits.open(fits_path) as h:
            data = h[0].data.astype(np.float32)

        # Handle axis order: FITS stores as (C, H, W), convert to (H, W, C)
        if data.ndim == 3 and data.shape[0] == 3:
            data = data.transpose(1, 2, 0)  # (C, H, W) → (H, W, C)

        if preview_config is None:
            # Legacy v1.6 path — byte-identisch
            sigma_factor = max(stretch_factor / 333.3, 0.1)
            stretched = auto_asinh(data, sigma_factor=sigma_factor)
        else:
            # V1.8-2 Pipeline (stella OQ-PEX-1):
            # background_neutralization -> scnr -> stretch -> saturation
            from .pcc import apply_scnr

            stretched = data.astype(np.float64)

            if preview_config.background_neutralization:
                stretched = _apply_background_neutralization(stretched)

            if preview_config.scnr:
                stretched = apply_scnr(stretched, amount=0.5)

            sigma_factor = max(stretch_factor / 333.3, 0.1)
            stretched = _apply_stretch(stretched, preview_config.stretch, sigma_factor)

            if preview_config.saturation != 1.0:
                stretched = _apply_saturation(stretched, preview_config.saturation)

        # Convert to 8-bit RGB
        img_8bit = (np.clip(stretched, 0.0, 1.0) * 255).astype(np.uint8)

        # Save as JPG
        img = Image.fromarray(img_8bit, mode='RGB')
        img.save(jpg_path, 'JPEG', quality=quality)

        size_kb = jpg_path.stat().st_size // 1024
        logger.info("preview.created", path=str(jpg_path), size_kb=size_kb)
        return jpg_path

    except Exception as e:
        logger.warning("preview.failed", error=str(e))
        return None
