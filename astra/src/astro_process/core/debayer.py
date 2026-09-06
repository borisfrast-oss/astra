"""Debayering — convert Bayer CFA 2D data to RGB 3D."""

import warnings
from pathlib import Path
from typing import Tuple
import numpy as np
from astropy.io import fits
from scipy.ndimage import convolve

from .seq_file import write_seq


# Bayer pattern offsets (RGGB):
# R = (0, 0)  G = (0, 1), (1, 0)  B = (1, 1)
BAYER_RGGB = {
    "R": (0, 0),
    "G1": (0, 1),
    "G2": (1, 0),
    "B": (1, 1),
}


def debayer_superpixel(data: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    """Convert Bayer CFA 2D array to RGB 3D using super-pixel method.
    
    Each 2×2 Bayer block becomes 1 RGB pixel. Output is half the input resolution.
    This is the preferred method for astrophotography as it introduces no
    interpolation artifacts and preserves photometric accuracy.
    
    Args:
        data: 2D input array (H × W), raw Bayer CFA data
        pattern: Bayer pattern string, e.g. "RGGB", "BGGR", "GBRG"
        
    Returns:
        3D array (H//2 × W//2 × 3) in R, G, B channel order
    """
    h, w = data.shape
    if h % 2 != 0 or w % 2 != 0:
        raise ValueError(f"Dimensions must be even, got {h}×{w}")
    
    # Reshape to access 2×2 blocks
    # Shape: (H//2, 2, W//2, 2) -> (H//2, W//2, 2, 2)
    blocks = data.reshape(h // 2, 2, w // 2, 2).transpose(0, 2, 1, 3)
    
    # Default pattern: RGGB
    # R = block[0, 0], G1 = block[0, 1], G2 = block[1, 0], B = block[1, 1]
    r = blocks[:, :, 0, 0]
    g1 = blocks[:, :, 0, 1]
    g2 = blocks[:, :, 1, 0]
    b = blocks[:, :, 1, 1]
    
    # Average the two green channels
    g = (g1.astype(np.float32) + g2.astype(np.float32)) / 2.0
    
    # Stack into RGB
    rgb = np.stack([r, g, b], axis=-1)
    
    return rgb


# V1.6-2 (BIL-A): Bilinear Debayer — volle Aufloesung (H, W, 3).
# Bilineare Interpolation fuer jeden CFA-Pixel, basierend auf den
# benachbarten Farbkanälen. Output = gleiche Aufloesung wie Input
# (keine 2x-Herunterskalierung wie Super-Pixel).
# DADR-003: Super-Pixel bleibt Default/Preferred; Bilinear ist
# eine Alternative fuer Anwendungen mit Fokus auf Detailerkennung.

# Bayer-Koordinaten fuer RGGB
_BAYER_RGGB_COORDS = {
    "R":  (0, 0),
    "G1": (0, 1),
    "G2": (1, 0),
    "B":  (1, 1),
}


def debayer_bilinear(data: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    """Convert Bayer CFA 2D array to RGB 3D using bilinear interpolation.

    Jeder Pixel wird durch gewichtete Interpolation der benachbarten
    CFA-Werte derselben Farbe berechnet. Output: (H, W, 3) — volle
    Aufloesung, keine Herunterskalierung.

    .. deprecated::
        V1.8-0: Use ``malvar`` or ``superpixel`` instead. Bilinear shows
        colour fringes / moire and is kept only for Grace v1.8.

    Args:
        data: 2D input array (H x W), raw Bayer CFA data (uint16 oder float32)
        pattern: Bayer pattern string, z.B. "RGGB", "BGGR", "GBRG", "GRBG"

    Returns:
        3D array (H x W x 3) in R, G, B channel order, float32

    Raises:
        ValueError: Bei ungueltigen Dimensionen oder Pattern.
    """
    warnings.warn(
        "debayer_bilinear is deprecated, use malvar or superpixel",
        DeprecationWarning,
        stacklevel=2,
    )
    h, w = data.shape
    if h < 3 or w < 3:
        raise ValueError(f"Dimensions must be at least 3x3 for bilinear, got {h}x{w}")

    pattern_upper = pattern.upper()
    if pattern_upper not in ("RGGB", "BGGR", "GBRG", "GRBG"):
        raise ValueError(f"Unsupported Bayer pattern: {pattern}")

    # Farb-Zuordnung: (row_offset, col_offset) -> Kanal-Index (0=R, 1=G, 2=B)
    color_map = {
        "RGGB": {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 2},
        "BGGR": {(0, 0): 2, (0, 1): 1, (1, 0): 1, (1, 1): 0},
        "GBRG": {(0, 0): 1, (0, 1): 0, (1, 0): 2, (1, 1): 1},
        "GRBG": {(0, 0): 1, (0, 1): 2, (1, 0): 0, (1, 1): 1},
    }[pattern_upper]

    data_f = data.astype(np.float32)
    rgb = np.zeros((h, w, 3), dtype=np.float32)

    # Bilineare Interpolation fuer jeden Farbkanal
    # Kernel: [[0, 1/4, 0], [1/4, 1, 1/4], [0, 1/4, 0]]
    kernel = np.array([[0, 0.25, 0],
                       [0.25, 1.0, 0.25],
                       [0, 0.25, 0]], dtype=np.float32)

    for color_idx in range(3):
        # Maske: welche Pixel haben diese Farbe?
        mask = np.zeros((h, w), dtype=bool)
        for (ro, co), ci in color_map.items():
            if ci == color_idx:
                mask[ro::2, co::2] = True

        # Kanal mit Originalwerten an Farb-Positionen, 0 sonst
        channel = np.zeros((h, w), dtype=np.float32)
        channel[mask] = data_f[mask]

        # Gewichts-Maske: 1.0 wo Farbe vorhanden, 0 sonst
        weights = np.zeros((h, w), dtype=np.float32)
        weights[mask] = 1.0

        # Bilineare Interpolation via Konvolution
        interpolated = convolve(channel, kernel, mode='constant', cval=0.0)
        weight_map = convolve(weights, kernel, mode='constant', cval=0.0)

        # Normalisieren (nur wo Gewicht > 0)
        valid = weight_map > 0
        result = np.zeros((h, w), dtype=np.float32)
        result[valid] = interpolated[valid] / weight_map[valid]

        # Am Rand: fuer Pixel ohne Interpolations-Nachbarn, Originalwert uebernehmen
        result[mask] = data_f[mask]

        rgb[:, :, color_idx] = result

    return rgb


# V1.8-0 (MALVAR): Malvar2004 Debayer — volle Aufloesung (H, W, 3),
# kanten-erhaltend, hochwertige Alternative zu bilinear (ohne Farbsaeume).
def debayer_malvar2004(data: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    """Convert Bayer CFA 2D array to RGB 3D using Malvar2004.

    Kanten-erhaltende Gradient-korrigierte Interpolation (Malvar et al.
    2004). Output: (H, W, 3) — volle Aufloesung, keine Herunterskalierung.

    Args:
        data: 2D input array (H x W), raw Bayer CFA data (uint16 oder float32)
        pattern: Bayer pattern string, z.B. "RGGB", "BGGR", "GBRG", "GRBG"

    Returns:
        3D array (H x W x 3) in R, G, B channel order, float32

    Raises:
        ValueError: Bei ungueltigen Dimensionen oder Pattern.
    """
    h, w = data.shape
    if h < 3 or w < 3:
        raise ValueError(f"Dimensions must be at least 3x3 for malvar, got {h}x{w}")

    pattern_upper = pattern.upper()
    if pattern_upper not in ("RGGB", "BGGR", "GBRG", "GRBG"):
        raise ValueError(f"Unsupported Bayer pattern: {pattern}")

    # colour_demosaicing erwartet float; uint16 -> float64 intern, Wertebereich bleibt erhalten
    # Lazy import damit fehlende Dependency klarere Fehler liefert
    try:
        from colour_demosaicing import demosaicing_CFA_Bayer_Malvar2004
    except ImportError as e:
        raise ImportError(
            "colour-demosaicing is required for malvar method — install via "
            "`pip install colour-demosaicing` or `pip install -e .`"
        ) from e

    # Sicherstellen dass Input 2D ist; colour_demosaicing toleriert float32/float64/uint16
    rgb = demosaicing_CFA_Bayer_Malvar2004(data, pattern=pattern_upper)

    # Output garantiert (H, W, 3) — sicherstellen float32
    rgb = np.asarray(rgb, dtype=np.float32)
    if rgb.shape != (h, w, 3):
        # Falls Library unerwartete Shape liefert, klaren Fehler
        raise ValueError(f"Malvar output shape mismatch: expected {(h, w, 3)}, got {rgb.shape}")
    return rgb


def apply_bzero(data: np.ndarray, bzero: float = 32768.0) -> np.ndarray:
    """Convert unsigned 16-bit FITS data (BZERO=32768) to signed float."""
    return data.astype(np.float32) - bzero


def debayer_fits(input_path: Path, output_path: Path, method: str = "superpixel") -> np.ndarray:
    """Debayer a single FITS file and save as 3D RGB FITS.
    
    Handles BZERO/BSCALE unsigned encoding common in Teleskop (z.B. Dwarf3) FITS.
    
    Args:
        input_path: Path to input 2D CFA FITS
        output_path: Path to output 3D RGB FITS
        method: Debayer method - "superpixel" (default, DADR-003), "bilinear"
            (deprecated, Grace v1.8) or "malvar" (High-Quality, volle Auflösung)
        
    Returns:
        The RGB data array
    """
    with fits.open(input_path) as hdul:
        header = hdul[0].header
        data = hdul[0].data.astype(np.float32)
        
        # Handle BZERO offset (Teleskop (z.B. Dwarf3) unsigned 16-bit encoding)
        bzero = header.get("BZERO", 0.0)
        if bzero != 0.0:
            data = data - bzero
    
    # V1.6-2 (BIL-D1) + V1.8-0 (MALVAR): Debayer-Methode waehler
    if method == "bilinear":
        rgb = debayer_bilinear(data)
    elif method == "malvar":
        rgb = debayer_malvar2004(data)
    else:
        rgb = debayer_superpixel(data)
    
    # Save as 3D FITS (NAXIS=3) with correct axis order for Siril compatibility
    # Internal: (H, W, C) -> FITS: (C, H, W)
    # So Siril sees NAXIS1=W, NAXIS2=H, NAXIS3=3
    hdu = fits.PrimaryHDU(rgb.transpose(2, 0, 1).astype(np.float32))
    hdu.header["CTYPE3"] = "RGB"
    hdu.header["CUNIT3"] = "channel"
    hdu.writeto(output_path, overwrite=True)
    
    return rgb


def batch_debayer(input_files: list, debayer_dir: Path, prefix: str = "deb_", method: str = "superpixel") -> tuple:
    """Debayer a batch of FITS files.
    
    Args:
        input_files: List of input FITS paths
        debayer_dir: Output directory for debayered files
        prefix: Output filename prefix
        method: Debayer method - "superpixel" (default), "bilinear" (deprecated) or "malvar"
        
    Returns:
        Tuple of (output_files list, seq_path Path)
    """
    debayer_dir.mkdir(parents=True, exist_ok=True)
    
    output_files = []
    for i, fpath in enumerate(input_files):
        out_name = f"{prefix}{i:04d}.fits"
        out_path = debayer_dir / out_name
        debayer_fits(fpath, out_path, method=method)
        output_files.append(out_path)
    
    # Write seq file
    seq_path = debayer_dir.parent / f"{debayer_dir.name}.seq"
    write_seq(seq_path, output_files, prefix=prefix)
    
    return output_files, seq_path
