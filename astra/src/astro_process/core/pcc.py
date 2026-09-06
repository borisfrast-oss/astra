"""Photometric Color Calibration (PCC) — star detection + color correction.

Uses FITS header values (RA, DEC, FOCALLEN, XPIXSZ) to build an approximate WCS
for position-based star matching with photometric catalogs.

V1.6-5: Catalog order changed to VizieR (primary) → GAIA (fallback) → Gray-World.
VizieR (ATLAS Refcat2 / APASS DR9) is typically 20-30s faster than GAIA for PCC.
"""

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Timeout (seconds) for GAIA catalog queries. Guards against indefinite
# hangs when the GAIA TAP service is slow or unreachable.
GAIA_QUERY_TIMEOUT_SECONDS: float = 30.0

# V1.6-5: Catalog order changed — VizieR (primary, 20-30s faster) →
# GAIA (fallback with retry backoff) → Gray-World.
PCC_FALLBACK_CHAIN_TIMEOUT_MULTIPLIERS: tuple = (1.0, 2.0, 3.0)

# V1.6-5: VizieR is now the PRIMARY catalog (APASS DR9 → ATLAS Refcat2).
# (name, VizieR-Katalog-ID, (B, V, R)-Spalten, (RA, Dec)-Spalten).
# Kanal-Zuordnung wie GAIA: B->BP, V->G, R->RP.
#
# Korrektur 2026-08-17 (Bug 2): Spalte "rmag" existiert nicht in APASS DR9
# (heisst "r'mag" — Sloan r') und ATLAS Refcat2 hat die falsche
# Katalog-ID (II/384/refcat2 liefert leere Tabelle). Korrekte Werte
# per astroquery verifiziert:
#   APASS DR9: Bmag, Vmag, r'mag  (Katalog II/336/apass9)
#   Refcat2:   Gmag, BPmag, RPmag  (Katalog J/ApJ/867/105/refcat2,
#              RA/Dec = RA_ICRS/DE_ICRS statt RAJ2000/DEJ2000)
_VIZIER_CATALOGS: tuple = (
    ("apass_dr9", "II/336/apass9", ("Bmag", "Vmag", "r'mag"), ("RAJ2000", "DEJ2000")),
    ("atlas_refcat2", "J/ApJ/867/105/refcat2", ("Gmag", "BPmag", "RPmag"), ("RA_ICRS", "DE_ICRS")),
)


@dataclass
class PCCResult:
    """Structured result from apply_pcc() — carries status alongside the image.

    Replaces the bare ``np.ndarray | None`` return to make the PCC status
    machine-readable for merge_report.json (pcc_status field).

    Status values:
        gaia_success: GAIA DR3 TAP catalog match succeeded.
        vizier_apass_success: VizieR APASS DR9 catalog match succeeded.
        vizier_refcat2_success: VizieR ATLAS Refcat2 catalog match succeeded.
        fallback_gray_world: All catalogs failed; gray-world white balance applied.
        pcc_skipped: PCC completely skipped (no coords, or fallback="skip").
        rejected_implausible_factors: Quality Gate — mindestens ein Kanal-
            Faktor <= 0 oder ausserhalb [min_factor, max_factor]; Stack
            wurde NICHT ueberschrieben (2026-08-21).
    """

    corrected: np.ndarray | None
    status: str  # one of the status values documented above
    # Quality-Gate-Input (2026-08-21): Kanal-Faktoren des Katalog-Matchs.
    # None bei Pfaenden ohne Faktorberechnung (gray_world, skip, alte Mocks).
    r_factor: float | None = None
    g_factor: float | None = None
    b_factor: float | None = None


# M2 (ray-Review v1.1): Optional-Dependencies (astroquery/sep) werden EINMAL
# auf Modulebene geprueft — NICHT im Worker-Thread von _run_with_timeout und
# NICHT bei jedem _gaia_pcc-Aufruf. Fehlt eine Dependency, wird GAIA-PCC
# komplett uebersprungen (Flag False): Der Thread wird gar nicht erst
# gestartet und der Gray-World-Fallback greift direkt. Das verhindert stumme
# Thread-Crashes durch ImportError bei fehlendem Optional-Dependency.
# V1.4-19: VizieR (astroquery.vizier) wird im selben Block geprueft — fehlt
# astroquery, ist auch der Zweit-Katalog deaktiviert (_VIZIER_OPT_AVAILABLE).
try:
    import sep as _sep
    from astroquery.gaia import Gaia as _Gaia
    from astroquery.vizier import Vizier as _Vizier

    _GAIA_OPT_AVAILABLE = True
    _VIZIER_OPT_AVAILABLE = True
except ImportError:
    _Gaia = None
    _sep = None
    _Vizier = None
    _GAIA_OPT_AVAILABLE = False
    _VIZIER_OPT_AVAILABLE = False
    logger.warning(
        "pcc.gaia_optional_unavailable",
        reason="astroquery or sep not installed — GAIA-PCC und VizieR-Katalog-Fallback deaktiviert, Gray-World-Fallback aktiv",
    )


def detect_stars(image: np.ndarray, threshold: float = 5.0, min_area: int = 5) -> list:
    """Detect stars in a 2D image using threshold segmentation.

    Blob detection: seed pixels are strict 3x3 local maxima above
    ``median + threshold * sigma`` (robust MAD sigma); each seed is then
    grown to all 8-connected pixels above the same detection floor, so
    an extended PSF contributes one segment of ``area >= min_area``
    instead of a single peak pixel (the strict-maximum mask alone always
    has area 1 for a smooth Gaussian — unusable for FWHM estimation).
    Flux is summed over the segment aperture; ``fwhm_est`` is the
    median aperture radius converted to FWHM.

    Args:
        image: 2D array (H×W)
        threshold: Detection threshold in sigma above background
        min_area: Minimum pixel area for a star

    Returns:
        List of dicts with keys: x, y, flux, peak, fwhm_est
    """
    from scipy.ndimage import center_of_mass, label, maximum_filter

    # Estimate background noise via robust MAD
    mad = np.median(np.abs(image - np.median(image)))
    sigma = mad * 1.4826  # Convert MAD to sigma

    if sigma < 1e-10:
        return []

    background = float(np.median(image))
    floor = background + threshold * sigma

    # Peak seeds: strict 3x3 local maxima above the detection floor.
    footprint = np.ones((3, 3))
    max_filtered = maximum_filter(image, footprint=footprint)
    seeds = (image == max_filtered) & (image > floor)

    if not np.any(seeds):
        return []

    # Grow each seed to all connected pixels above the floor: one
    # segment per star, so flux/FWHM apertures are meaningful.
    mask = image > floor
    labeled, n_labels = label(mask, structure=np.ones((3, 3)))
    seed_labels = {int(label_id) for label_id in labeled[seeds] if label_id > 0}

    stars = []
    for label_id in sorted(seed_labels):
        seg = labeled == label_id
        area = int(np.sum(seg))
        if area < min_area:
            continue

        cy, cx = center_of_mass(image * seg, labeled, label_id)
        flux = float(np.sum(image[seg]))
        peak = float(np.max(image[seg]))

        # Estimate FWHM from the aperture radius distribution
        y_grid, x_grid = np.ogrid[-cy : image.shape[0] - cy, -cx : image.shape[1] - cx]
        r_grid = np.sqrt(y_grid**2 + x_grid**2)
        r_vals = r_grid[seg]
        fwhm_est = float(np.median(r_vals)) * 2.355 if len(r_vals) > 0 else 3.0

        stars.append(
            {
                "x": float(cx),
                "y": float(cy),
                "flux": float(flux),
                "peak": float(peak),
                "fwhm_est": fwhm_est,
            }
        )

    return stars


def compute_pixel_scale(
    focal_length_mm: float, pixel_size_um: float, binning: float = 2.0
) -> float:
    """Compute pixel scale in arcsec/pixel from optics and sensor params.

    Args:
        focal_length_mm: Focal length in mm (from FITS FOCALLEN)
        pixel_size_um: Pixel size in µm (from FITS XPIXSZ/YPIXSZ)
        binning: Effektiver Stack-Faktor (Superpixel-Debayer, ggf. Hardware-
                 Binning) — entspricht ``registration.stack_scale_factor``.
                 Default 2.0 = Teleskop (z.B. Dwarf3): nativ 1920x1080 (~2MP) mit
                 2x2-Superpixel-Debayer -> 2.9 µm x 2 = 5.8 µm.

    Returns:
        Pixel scale in arcsec/pixel
    """
    if focal_length_mm <= 0 or pixel_size_um <= 0:
        return 0.0
    return 206.265 * pixel_size_um * binning / focal_length_mm


def _pixel_to_sky(
    x_pix: float, y_pix: float, ra0: float, dec0: float, pixel_scale: float, width: int, height: int
) -> tuple:
    """Convert pixel coordinates to approximate RA/Dec (degrees).

    Uses a simple TAN-like projection centered on (ra0, dec0).
    Assumes north is approximately up (+y). Field rotation NOT handled,
    but for our ~2-4 degree fields the error is small.

    Args:
        x_pix, y_pix: Pixel coordinates (0-indexed)
        ra0, dec0: Field center in degrees
        pixel_scale: Arcsec per pixel
        width, height: Image dimensions in pixels

    Returns:
        (ra_deg, dec_deg)
    """
    # Center of image in pixel coordinates
    cx = width / 2.0
    cy = height / 2.0

    # Pixel offset from center
    dx = x_pix - cx
    dy = -(y_pix - cy)  # flip y: image y-down → sky y-up

    # Convert to angular offset in degrees
    scale_deg = pixel_scale / 3600.0
    dra = dx * scale_deg
    ddec = dy * scale_deg

    # Apply to center (small-angle approximation, valid for our FOV)
    ra = ra0 + dra / np.cos(np.radians(dec0))
    dec = dec0 + ddec

    return (ra, dec)


def gray_world_white_balance(rgb: np.ndarray, percentile: float = 99.0) -> np.ndarray:
    """Simple gray-world white balance using bright star regions.

    Computes per-channel scaling factors so that the brightest non-saturated
    pixels have equal R, G, B values.

    Args:
        rgb: 3D input array (H×W×3) in R, G, B order
        percentile: Percentile of channel values to use for scaling

    Returns:
        White-balanced RGB array (same shape)
    """
    # Compute per-channel percentiles
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]

    r_val = np.percentile(r[r > 0], percentile) if np.any(r > 0) else 1.0
    g_val = np.percentile(g[g > 0], percentile) if np.any(g > 0) else 1.0
    b_val = np.percentile(b[b > 0], percentile) if np.any(b > 0) else 1.0

    # Prevent division by zero
    r_val = max(r_val, 1e-10)
    g_val = max(g_val, 1e-10)
    b_val = max(b_val, 1e-10)

    # Scale to mean of channels (preserves overall brightness)
    target = (r_val + g_val + b_val) / 3.0
    r_scale = target / r_val
    g_scale = target / g_val
    b_scale = target / b_val

    result = rgb.copy().astype(np.float32)
    result[:, :, 0] *= r_scale
    result[:, :, 1] *= g_scale
    result[:, :, 2] *= b_scale

    logger.info(
        "pcc.gray_world",
        r_scale=round(r_scale, 4),
        g_scale=round(g_scale, 4),
        b_scale=round(b_scale, 4),
    )

    return result


def _run_with_timeout(func, timeout: float, *args, **kwargs):
    """Run ``func`` in a daemon thread and wait up to ``timeout`` seconds.

    Uses the ``threading.Thread(daemon=True)`` + ``queue.Queue`` pattern
    instead of ``concurrent.futures.ThreadPoolExecutor``, whose non-daemon
    threads would block interpreter exit if a GAIA query hangs.

    V1.1-Hardening (m7): Konsistente Semantik mit ``cli._run_with_timeout`` —
    Timeout wird als ``TimeoutError`` geworfen (statt ``None``-Rueckgabe).
    Der Aufrufer entscheidet ueber Fallback/Logging.

    Args:
        func: Callable to execute.
        timeout: Maximum wall-clock seconds to wait for func.
        *args, **kwargs: Forwarded to func.

    Returns:
        func's return value.

    Raises:
        TimeoutError: If func did not complete within timeout.
        Any exception raised by func is re-raised in the caller thread.
    """
    q = queue.Queue(maxsize=1)

    def _worker():
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            q.put(("exception", e))
        else:
            q.put(("result", result))

    threading.Thread(target=_worker, daemon=True).start()

    try:
        kind, payload = q.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"Operation timed out after {timeout}s")

    if kind == "exception":
        raise payload
    return payload


def _detect_and_measure(rgb: np.ndarray):
    """Stern-Detection (sep) + Apertur-Photometrie (R,G,B).

    V1.4-19 (Extraktion aus ``_gaia_pcc``, Verhalten identisch): Gemeinsame
    Basis fuer GAIA- und VizieR-PCC. Bei < 5 Sternen wird ``pcc.few_stars``
    geloggt und None zurueckgegeben (wie bisher in _gaia_pcc).

    Returns:
        (img_x, img_y, r_flux, g_flux, b_flux) oder None.
    """
    lum = rgb.mean(axis=-1).astype(np.float64)
    bg = _sep.Background(lum)
    bg_sub = lum - bg
    objects = _sep.extract(bg_sub, thresh=3.0, minarea=5)

    if len(objects) < 5:
        logger.warning("pcc.few_stars", count=len(objects))
        return None

    # Measure fluxes in R, G, B apertures
    ap_radius = max(3.0, np.median(objects["npix"]) ** 0.5)
    r_flux = _sep.sum_circle(
        rgb[:, :, 0].astype(np.float64), objects["x"], objects["y"], ap_radius
    )[0]
    g_flux = _sep.sum_circle(
        rgb[:, :, 1].astype(np.float64), objects["x"], objects["y"], ap_radius
    )[0]
    b_flux = _sep.sum_circle(
        rgb[:, :, 2].astype(np.float64), objects["x"], objects["y"], ap_radius
    )[0]

    return objects["x"], objects["y"], r_flux, g_flux, b_flux


def _position_match_and_correct(
    rgb: np.ndarray,
    img_x,
    img_y,
    r_flux,
    g_flux,
    b_flux,
    cat_ra,
    cat_dec,
    cat_bp,
    cat_g,
    cat_rp,
    ra: float,
    dec: float,
    pixel_scale: float,
    *,
    event_prefix: str = "pcc",
    complete_event_name: str = "pcc.complete",
) -> tuple[Optional[np.ndarray], Optional[tuple[float, float, float]]]:
    """Positions-Match (KDTree auf Katalog-RA/Dec) + Farb-Korrektur.

    V1.4-19 (Extraktion aus ``_gaia_pcc``, Verhalten identisch): Gemeinsame
    Match-Logik fuer GAIA- und VizieR-PCC. Kanal-Zuordnung: cat_bp->B,
    cat_g->G, cat_rp->R (Flux-Ratios image/catalog, robuste Mediane,
    Normalisierung auf G).

    Args:
        rgb: 3D array (H×W×3)
        img_x/img_y/r_flux/g_flux/b_flux: Detektierte Sterne + Apertur-Fluxe.
        cat_ra/cat_dec: Katalog-Positionen (deg).
        cat_bp/cat_g/cat_rp: Katalog-Helligkeiten (Flux-Einheiten, analog
                             GAIA 10^(-mag/2.5)).
        ra/dec/pixel_scale: Feldzentrum + Skala (deg/pix).
        event_prefix: Event-Praefix (GAIA "pcc", VizieR "pcc.vizier").
        complete_event_name: Event-Name der Erfolgsmeldung (GAIA
                             "pcc.gaia_complete", VizieR "pcc.vizier_complete"
                             — Event-Namen unveraendert, V1.4-19).

    Returns:
        (Korrigiertes RGB | None, Faktoren (r, g, b) | None).
        (None, None) bei < 3 Matches — Faktoren nur bei erfolgreicher
        Korrektur gesetzt (Quality-Gate-Input, 2026-08-21).
    """
    from scipy.spatial import KDTree

    height, width, _ = rgb.shape

    # Convert catalog to radians for KDTree (unit vectors)
    cat_ra_rad = np.radians(cat_ra)
    cat_dec_rad = np.radians(cat_dec)
    cat_xyz = np.column_stack(
        [
            np.cos(cat_dec_rad) * np.cos(cat_ra_rad),
            np.cos(cat_dec_rad) * np.sin(cat_ra_rad),
            np.sin(cat_dec_rad),
        ]
    )

    tree = KDTree(cat_xyz)

    # Convert detected star pixels to approximate RA/Dec
    matched_r, matched_g, matched_b = [], [], []
    matched_cat_g, matched_cat_bp, matched_cat_rp = [], [], []

    # Max matching distance in radians (≈ 2× pixel scale × 3 pixels)
    if pixel_scale > 0:
        max_dist_rad = np.radians(3 * pixel_scale / 3600.0)
    else:
        max_dist_rad = np.radians(0.01)  # ~36 arcsec fallback

    for i in range(len(img_x)):
        pix_ra, pix_dec = _pixel_to_sky(img_x[i], img_y[i], ra, dec, pixel_scale, width, height)

        # Convert to 3D unit vector
        pix_ra_rad = np.radians(pix_ra)
        pix_dec_rad = np.radians(pix_dec)
        pix_vec = np.array(
            [
                np.cos(pix_dec_rad) * np.cos(pix_ra_rad),
                np.cos(pix_dec_rad) * np.sin(pix_ra_rad),
                np.sin(pix_dec_rad),
            ]
        )

        dist, idx = tree.query(pix_vec)

        if dist <= max_dist_rad:
            matched_r.append(r_flux[i])
            matched_g.append(g_flux[i])
            matched_b.append(b_flux[i])
            matched_cat_g.append(cat_g[idx])
            matched_cat_bp.append(cat_bp[idx])
            matched_cat_rp.append(cat_rp[idx])

    n_matched = len(matched_r)
    if n_matched < 3:
        logger.warning(
            f"{event_prefix}.few_matches",
            count=n_matched,
            max_dist_arcsec=round(np.degrees(max_dist_rad) * 3600, 1),
        )
        return None, None

    logger.info(
        f"{event_prefix}.match_complete",
        detected=len(img_x), catalog=len(cat_ra), matched=n_matched,
    )

    # 4. Compute color correction from matched stars
    matched_r = np.array(matched_r)
    matched_g = np.array(matched_g)
    matched_b = np.array(matched_b)
    matched_cat_g = np.array(matched_cat_g)
    matched_cat_bp = np.array(matched_cat_bp)
    matched_cat_rp = np.array(matched_cat_rp)

    # Per-channel ratios: image_flux / catalog_flux
    # RP→R, G→G, BP→B (catalog mags → approximate RGB)
    r_ratios = matched_r / matched_cat_rp
    g_ratios = matched_g / matched_cat_g
    b_ratios = matched_b / matched_cat_bp

    # Clip outliers (5th-95th percentile)
    def _robust_median(arr):
        lo, hi = np.percentile(arr, [5, 95])
        clipped = arr[(arr >= lo) & (arr <= hi)]
        return np.median(clipped) if len(clipped) > 0 else np.median(arr)

    r_scale = _robust_median(r_ratios)
    g_scale = _robust_median(g_ratios)
    b_scale = _robust_median(b_ratios)

    # Normalize: scale such that green stays roughly unchanged
    mean_scale = (r_scale + g_scale + b_scale) / 3.0
    r_factor = mean_scale / r_scale
    g_factor = mean_scale / g_scale
    b_factor = mean_scale / b_scale

    logger.info(
        complete_event_name,
        r_factor=round(r_factor, 4),
        g_factor=round(g_factor, 4),
        b_factor=round(b_factor, 4),
        matched_stars=n_matched,
    )

    # Apply correction
    result = rgb.copy().astype(np.float32)
    result[:, :, 0] *= r_factor
    result[:, :, 1] *= g_factor
    result[:, :, 2] *= b_factor

    return result, (float(r_factor), float(g_factor), float(b_factor))


def _gaia_pcc(
    rgb: np.ndarray,
    ra: float,
    dec: float,
    pixel_scale: float = 0.0,
    timeout: float = GAIA_QUERY_TIMEOUT_SECONDS,
) -> PCCResult:
    """Attempt GAIA-based PCC with position-based star matching.

    Uses pixel scale to build an approximate WCS and matches detected
    stars to catalog stars by position (KDTree nearest-neighbor).

    Args:
        rgb: 3D array (H×W×3)
        ra, dec: Field center in degrees
        pixel_scale: Arcsec/pixel for the image (debayered scale)
        timeout: Max seconds to wait for the GAIA query; on timeout the
                 function returns PCCResult(corrected=None, ...).

    Returns:
        PCCResult with corrected image and status.
    """
    if not _GAIA_OPT_AVAILABLE:
        logger.warning("pcc.gaia_unavailable", reason="astroquery or sep not installed")
        return PCCResult(corrected=None, status="skipped")

    try:
        height, width, _ = rgb.shape

        # 1. Detect stars with sep (on luminance)
        det = _detect_and_measure(rgb)
        if det is None:
            return PCCResult(corrected=None, status="skipped")
        img_x, img_y, r_flux, g_flux, b_flux = det

        # 2. Query GAIA catalog within a generous radius
        if pixel_scale > 0:
            field_deg = max(width, height) * pixel_scale / 3600.0
            search_radius = field_deg * 0.8
        else:
            search_radius = 0.3

        query = f"""
        SELECT ra, dec, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag
        FROM gaiadr3.gaia_source
        WHERE 1=CONTAINS(
          POINT('ICRS', ra, dec),
          CIRCLE('ICRS', {ra}, {dec}, {search_radius})
        )
        AND phot_g_mean_mag < 16
        AND phot_g_mean_mag > 6
        AND phot_bp_mean_mag IS NOT NULL
        AND phot_rp_mean_mag IS NOT NULL
        """

        try:
            if getattr(_Gaia, "TIMEOUT", None) is not None:
                _Gaia.TIMEOUT = timeout
        except Exception as e:
            logger.debug("pcc.gaia_timeout_set_failed", error=str(e))

        try:
            job = _run_with_timeout(_Gaia.launch_job, timeout, query)
        except TimeoutError:
            logger.warning("pcc.gaia_timeout", timeout=timeout)
            return PCCResult(corrected=None, status="skipped")
        catalog = job.get_results()

        if len(catalog) < 3:
            logger.warning("pcc.few_catalog_stars", count=len(catalog))
            return PCCResult(corrected=None, status="skipped")

        cat_ra = np.array(catalog["ra"])
        cat_dec = np.array(catalog["dec"])
        cat_g = 10.0 ** (-np.array(catalog["phot_g_mean_mag"]) / 2.5)
        cat_bp = 10.0 ** (-np.array(catalog["phot_bp_mean_mag"]) / 2.5)
        cat_rp = 10.0 ** (-np.array(catalog["phot_rp_mean_mag"]) / 2.5)

        # 3. Position matching + color correction
        corrected, factors = _position_match_and_correct(
            rgb, img_x, img_y, r_flux, g_flux, b_flux,
            cat_ra, cat_dec, cat_bp, cat_g, cat_rp,
            ra, dec, pixel_scale,
            event_prefix="pcc",
            complete_event_name="pcc.gaia_complete",
        )
        if corrected is not None:
            return PCCResult(
                corrected=corrected, status="gaia_success",
                r_factor=factors[0], g_factor=factors[1], b_factor=factors[2],
            )
        return PCCResult(corrected=None, status="skipped")

    except Exception as e:
        logger.warning("pcc.gaia_failed", error=str(e))
        return PCCResult(corrected=None, status="skipped")


def _col_float(table, name: str) -> np.ndarray:
    """VizieR-Spalte robust als float64-Array (MaskedColumn → NaN)."""
    col = table[name]
    if hasattr(col, "filled"):  # astropy MaskedColumn
        col = col.filled(np.nan)
    return np.asarray(col, dtype=np.float64)


def _vizier_pcc(
    rgb: np.ndarray,
    ra: float,
    dec: float,
    pixel_scale: float = 0.0,
    timeout_apass: float = 30.0,
    timeout_refcat2: float = 30.0,
) -> PCCResult:
    """VizieR-Zweit-Katalog PCC (V1.4-19, Stufe 2).

    Gleiche Match-Logik wie ``_gaia_pcc`` (KDTree-Positions-Match), aber
    statt GAIA DR3/TAP die VizieR-Kataloge APASS DR9 (II/336/apass9) →
    ATLAS Refcat2 (J/ApJ/867/105/refcat2) — Kanal-Zuordnung wie Siril-PCC:
    B→BP, V→G, R→RP. Die Kataloge werden in ``_VIZIER_CATALOGS``-Reihen-
    folge versucht; der erste mit >= 3 Stern-Matches gewinnt. Ohne
    astroquery (Flag False) → PCCResult(None) ohne Thread/Netzwerk
    (M2-Semantik wie GAIA).

    Args:
        rgb: 3D array (H×W×3)
        ra, dec: Field center in degrees
        pixel_scale: Arcsec/pixel (0.0 → 0.3° Suchradius / 36″-Match).
        timeout_apass: Max seconds for APASS DR9 query.
        timeout_refcat2: Max seconds for ATLAS Refcat2 query.

    Returns:
        PCCResult with corrected image and catalog-specific status.
    """
    if not _VIZIER_OPT_AVAILABLE:
        logger.warning("pcc.vizier_unavailable", reason="astroquery not installed")
        return PCCResult(corrected=None, status="skipped")

    try:
        # 1. Detect + measure (gemeinsame Basis mit GAIA-PCC, V1.4-19)
        det = _detect_and_measure(rgb)
        if det is None:
            return PCCResult(corrected=None, status="skipped")
        img_x, img_y, r_flux, g_flux, b_flux = det
        height, width, _ = rgb.shape

        # Feldgröße wie bei GAIA schätzen (sonst 0.3 deg)
        if pixel_scale > 0:
            field_deg = max(width, height) * pixel_scale / 3600.0
            search_radius = field_deg * 0.8
        else:
            search_radius = 0.3

        from astropy import units as u
        from astropy.coordinates import SkyCoord

        center = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg), frame="icrs")
        radius = u.Quantity(search_radius, unit=u.deg)

        # 2. Katalog-Schleife (APASS DR9 → ATLAS Refcat2)
        for cat_name, cat_id, (b_col, g_col, r_col), (ra_col, dec_col) in _VIZIER_CATALOGS:
            timeout = timeout_apass if "apass" in cat_name else timeout_refcat2
            try:
                vizier = _Vizier(
                    columns=[ra_col, dec_col, b_col, g_col, r_col],
                    row_limit=-1,
                )
                try:
                    vizier.timeout = timeout
                except Exception:
                    pass  # Belt-and-braces; _run_with_timeout sichert ab.

                try:
                    tables = _run_with_timeout(
                        lambda: vizier.query_region(center, radius=radius, catalog=cat_id),
                        timeout,
                    )
                except TimeoutError:
                    logger.warning("pcc.vizier_timeout", catalog=cat_id, timeout=timeout)
                    continue
                table = tables[0] if isinstance(tables, (list, tuple)) else tables

                cat_ra = _col_float(table, ra_col)
                cat_dec = _col_float(table, dec_col)
                cat_bp = _col_float(table, b_col)   # Bmag
                cat_g = _col_float(table, g_col)    # Vmag (G-Kanal)
                cat_rp = _col_float(table, r_col)   # r'mag (R-Kanal)

                # Helligkeitsfilter analog GAIA (6 < mag < 16 auf G-Kanal)
                # — auf MAGNITUDEN, VOR der Flux-Konvertierung (Fix
                # 2026-08-21: Filter lief NACH der Konvertierung und
                # filterte damit Flux-Werte -> nur Sterne mag -3.0..-1.9
                # passierten -> VizieR matched praktisch immer 0 Sterne).
                ok = (
                    np.isfinite(cat_ra) & np.isfinite(cat_dec)
                    & np.isfinite(cat_bp) & np.isfinite(cat_g) & np.isfinite(cat_rp)
                )
                ok &= (cat_g > 6.0) & (cat_g < 16.0)
                cat_ra, cat_dec = cat_ra[ok], cat_dec[ok]
                cat_bp, cat_g, cat_rp = cat_bp[ok], cat_g[ok], cat_rp[ok]

                # Magnitudes → Fluxes (wie GAIA-PCC: 10^(-mag/2.5))
                cat_bp = 10.0 ** (-cat_bp / 2.5)
                cat_g = 10.0 ** (-cat_g / 2.5)
                cat_rp = 10.0 ** (-cat_rp / 2.5)

                # NaN/Inf-Guard NACH der Konvertierung (unveraendert;
                # faengt z.B. nicht-finite Werte aus der Potenz-Rechnung).
                ok = (
                    np.isfinite(cat_ra) & np.isfinite(cat_dec)
                    & np.isfinite(cat_bp) & np.isfinite(cat_g) & np.isfinite(cat_rp)
                )
                cat_ra, cat_dec = cat_ra[ok], cat_dec[ok]
                cat_bp, cat_g, cat_rp = cat_bp[ok], cat_g[ok], cat_rp[ok]

                if len(cat_ra) < 3:
                    logger.warning("pcc.vizier_few_catalog_stars",
                                   catalog=cat_id, count=len(cat_ra))
                    continue

                result, factors = _position_match_and_correct(
                    rgb, img_x, img_y, r_flux, g_flux, b_flux,
                    cat_ra, cat_dec, cat_bp, cat_g, cat_rp,
                    ra, dec, pixel_scale,
                    event_prefix="pcc.vizier",
                    complete_event_name="pcc.vizier_complete",
                )
                if result is not None:
                    if cat_name == "apass_dr9":
                        status = "vizier_apass_success"
                    else:
                        status = "vizier_refcat2_success"
                    return PCCResult(
                        corrected=result, status=status,
                        r_factor=factors[0], g_factor=factors[1],
                        b_factor=factors[2],
                    )
                logger.warning("pcc.vizier_few_matches", catalog=cat_id)
            except Exception as e:
                logger.warning("pcc.vizier_failed", catalog=cat_id, error=str(e))
        return PCCResult(corrected=None, status="skipped")
    except Exception as e:
        logger.warning("pcc.vizier_failed", error=str(e))
        return PCCResult(corrected=None, status="skipped")


def _final_pcc_fallback(
    rgb: np.ndarray, fallback: str, *, from_chain: bool
) -> PCCResult:
    """V1.4-19 Stufe 3: preset-abhaengige finale PCC-Stufe.

    "auto"/"gray_world" → gray-world White-Balance (Deep-Sky-Approximation;
    51-Cyg-Erfahrung: bei Stern-Presets NICHT verwenden — "skip").
    "skip" → PCCResult(None, "pcc_skipped") (kein PCC statt kaputtem PCC;
             Frame bleibt unveraendert).
    "fail" → RuntimeError (harter Abbruch).
    """
    if fallback in ("auto", "gray_world"):
        if from_chain:
            logger.info("pcc.fallback_to_gray_world")
        logger.info("pcc.start", method="gray_world")
        return PCCResult(corrected=gray_world_white_balance(rgb), status="fallback_gray_world")
    if fallback == "skip":
        logger.info("pcc.fallback_skip", reason="no_gray_world_for_star_preset")
        return PCCResult(corrected=None, status="pcc_skipped")
    # "fail"
    raise RuntimeError(
        "PCC catalog chain failed (VizieR + GAIA retries) and "
        "pcc_fallback='fail' configured"
    )


def _factors_plausible(
    r_factor: float,
    g_factor: float,
    b_factor: float,
    min_factor: float,
    max_factor: float,
) -> bool:
    """Quality Gate (2026-08-21): Alle Kanal-Faktoren plausibel?

    Ablehnung, wenn irgendein Faktor <= 0 (Kanal-Inversion) ODER
    ausserhalb [min_factor, max_factor] (Default 0.5–2.0) liegt.
    Hintergrund: M92-Lauf 171059 wandte r_factor=-9.73 an und meldete
    trotzdem 'gaia_success' (siehe orion/_work/stella/
    issue-pcc-quality-gate.md).
    """
    for f in (r_factor, g_factor, b_factor):
        if not np.isfinite(f) or f <= 0.0 or f < min_factor or f > max_factor:
            return False
    return True


def _reject_implausible_factors(
    result: PCCResult, min_factor: float, max_factor: float
) -> PCCResult:
    """Gate-Ablehnung: Log-Event + PCCResult ohne Korrektur.

    Die Ablehnung ENDET die PCC-Kette (leo-Entscheidung 2026-08-21):
    kein weiterer Katalog-Fallback und kein gray_world — die Fallback-
    Leiter existiert fuer "kein Match", nicht fuer "physisch unplausibler
    Match". Der Stack wird vom Aufrufer (photometric_color_calibration)
    nicht ueberschrieben.
    """
    logger.warning(
        "pcc.rejected_implausible_factors",
        r_factor=round(result.r_factor, 4),
        g_factor=round(result.g_factor, 4),
        b_factor=round(result.b_factor, 4),
        min_factor=min_factor,
        max_factor=max_factor,
    )
    return PCCResult(
        corrected=None,
        status="rejected_implausible_factors",
        r_factor=result.r_factor,
        g_factor=result.g_factor,
        b_factor=result.b_factor,
    )


def _gate_rejects(
    result: PCCResult,
    enabled: bool,
    min_factor: float,
    max_factor: float,
) -> bool:
    """Zentrale Gate-Pruefung fuer Katalog-Ergebnisse (GAIA UND VizieR).

    Ergebnisse ohne Faktoren (gray_world, skip, faktorlose Mocks) passieren
    unveraendert — das Gate bewertet nur echte Katalog-Matches.
    """
    if not enabled:
        return False
    if result.r_factor is None or result.g_factor is None or result.b_factor is None:
        return False
    return not _factors_plausible(
        result.r_factor, result.g_factor, result.b_factor, min_factor, max_factor
    )


def apply_pcc(
    rgb: np.ndarray,
    ra: float | None = None,
    dec: float | None = None,
    pixel_scale_arcsec: float = 0.0,
    gaia_timeout: float = GAIA_QUERY_TIMEOUT_SECONDS,
    vizier_apass_timeout: float = 30.0,
    vizier_refcat2_timeout: float = 30.0,
    fallback: str = "auto",
    quality_gate_enabled: bool = True,
    quality_gate_min_factor: float = 0.5,
    quality_gate_max_factor: float = 2.0,
) -> PCCResult:
    """Apply PCC to RGB image — V1.6-5: VizieR primary, GAIA fallback.

    Catalog order (V1.6-5, performance optimization):
      1. VizieR (ATLAS Refcat2 / APASS DR9) — typically 20-30s faster
         than GAIA; smaller catalog but sufficient for PCC.
      2. GAIA DR3 (TAP) with Retry-Backoff 1x/2x/3x `gaia_timeout`
         (Default 30.0 → 30s/60s/90s; gleiche Query je Versuch).
      3. Erst danach preset-abhaengig: "auto"/"gray_world" → gray-world
         White-Balance (Deep-Sky), "skip" → None (Sterne,
         51-Cyg-Erfahrung: gray_world zerstoert Stern-Bilder), "fail" →
         RuntimeError.

    Mit Koordinaten wird `pcc.start` (method vizier_position/gaia_position)
    geloggt wie bisher; ohne Koordinaten ist kein Katalog-Match moeglich
    → sofort finale Stufe (gray_world bei auto/gray_world).

    Args:
        rgb: 3D input array (H×W×3)
        ra: Right Ascension in degrees (optional)
        dec: Declination in degrees (optional)
        pixel_scale_arcsec: Pixel scale in arcsec/pixel (Stack-Skala, z.B.
                           ~8'' beim Teleskop (z.B. Dwarf3) mit 2x Superpixel-Debayer)
        gaia_timeout: Basis-Timeout fuer GAIA-Versuche (V1.4-19: Backoff
                      1x/2x/3x; Default GAIA_QUERY_TIMEOUT_SECONDS).
        vizier_apass_timeout: Timeout fuer VizieR APASS DR9 Query.
        vizier_refcat2_timeout: Timeout fuer VizieR ATLAS Refcat2 Query.
        fallback: "auto" | "gray_world" | "skip" | "fail" (V1.4-19).
                  Default "auto" — Kette + gray_world als letzte Stufe.
        quality_gate_enabled: Quality Gate (2026-08-21). True = Katalog-
                  Ergebnisse mit unplausiblen Faktoren (<= 0 oder
                  ausserhalb [min, max]) werden abgelehnt; die Ablehnung
                  ENDET die Kette (kein naechster Katalog, kein gray_world).
        quality_gate_min_factor: Untere Grenze (Default 0.5).
        quality_gate_max_factor: Obere Grenze (Default 2.0).

    Returns:
        PCCResult with corrected RGB array and status string.
    """
    if ra is not None and dec is not None:
        if pixel_scale_arcsec > 0:
            logger.info(
                "pcc.start", method="vizier_position", ra=ra, dec=dec, pixel_scale=pixel_scale_arcsec
            )
        else:
            logger.info("pcc.start", method="vizier_nopos", ra=ra, dec=dec)
    else:
        # Ohne Koordinaten: kein Katalog-Match moeglich — direkt finale
        # Stufe (V1.4-19; bisher gray_world, jetzt preset-abhaengig).
        return _final_pcc_fallback(rgb, fallback, from_chain=False)

    # Stufe 1 (V1.6-5): VizieR als Primary (kleinerer Katalog, 20-30s
    # schneller als GAIA fuer PCC).
    vizier_result = _vizier_pcc(
        rgb, ra, dec, pixel_scale=pixel_scale_arcsec,
        timeout_apass=vizier_apass_timeout, timeout_refcat2=vizier_refcat2_timeout,
    )
    if vizier_result.corrected is not None:
        if _gate_rejects(vizier_result, quality_gate_enabled,
                         quality_gate_min_factor, quality_gate_max_factor):
            return _reject_implausible_factors(
                vizier_result, quality_gate_min_factor, quality_gate_max_factor
            )
        return vizier_result

    # Stufe 2 (V1.6-5): GAIA-Retry mit Backoff 1x/2x/3x gaia_timeout
    # als Fallback (V1.4-19).
    for i, mult in enumerate(PCC_FALLBACK_CHAIN_TIMEOUT_MULTIPLIERS):
        attempt = i + 1
        t = gaia_timeout * mult
        gaia_result = _gaia_pcc(rgb, ra, dec, pixel_scale=pixel_scale_arcsec, timeout=t)
        if gaia_result.corrected is not None:
            if _gate_rejects(gaia_result, quality_gate_enabled,
                             quality_gate_min_factor, quality_gate_max_factor):
                return _reject_implausible_factors(
                    gaia_result, quality_gate_min_factor, quality_gate_max_factor
                )
            if attempt > 1:
                logger.info("pcc.gaia_retry_success", attempts=attempt, timeout=round(t, 1))
            return gaia_result
        logger.warning("pcc.gaia_attempt_failed", attempt=attempt, timeout=round(t, 1))

    # Stufe 3 (V1.4-19): preset-abhaengige finale Stufe. Grund ins
    # agent-log (v14-konkretisierung §V1.4-19 Punkt 4).
    logger.warning(
        "pcc.catalog_chain_failed",
        reason="vizier_and_gaia_retries_unavailable",
        timeout_base=gaia_timeout,
    )
    return _final_pcc_fallback(rgb, fallback, from_chain=True)


def apply_scnr(rgb: np.ndarray, amount: float = 0.5) -> np.ndarray:
    """Remove green cast (SCNR — Subtract Chromatic Noise from RGB).

    Standard Siril-compatible SCNR: reduce green in pixels where G > R and G > B.

    Args:
        rgb: 3D array (H×W×3)
        amount: Strength of correction (0.0 = none, 1.0 = full)

    Returns:
        Corrected RGB array
    """
    result = rgb.copy().astype(np.float32)
    r, g, b = result[:, :, 0], result[:, :, 1], result[:, :, 2]

    # Find pixels where green is dominant
    g_excess = g - np.maximum(r, b)
    mask = g_excess > 0

    if not np.any(mask):
        logger.info("pcc.scnr_no_green_cast")
        return result

    # Reduce green: new_g = g - amount * g_excess
    reduction = amount * g_excess[mask]
    g[mask] -= reduction

    logger.info("pcc.scnr_applied", amount=amount, affected_pixels=int(np.sum(mask)))
    return result


# ═══════════════════════════════════════════════════════════════════
# Agent-Wrapper (Refactor 2026-08-14, Cluster 5)
# Verschoben aus ``astro_process/agents/processing_agent.py``
# (ProcessingAgent._get_pcc_fallback, _photometric_color_calibration,
# _scnr). Rein verschoben, KEINE Verhaltensaenderung: Event-Namen und
# Datei-Semantik identisch. Frame-I/O erfolgt ueber die Callables
# ``load_frame``/``save_frame``; der Agent bindet dafuer seine Methoden
# und reicht seinen Modul-Logger als ``logger=`` durch.
# ═══════════════════════════════════════════════════════════════════


def get_pcc_fallback(config) -> str:
    """Get the PCC fallback strategy from config.

    Refactor: moved from ``ProcessingAgent._get_pcc_fallback`` in
    ``astro_process/agents/processing_agent.py`` (Cluster 5, 2026-08-14;
    unveraendert — statt ``self.config`` wird ``config`` explizit uebergeben).

    V1.4-19: Default "auto" — stufenweise Kette (GAIA-Retry → VizieR →
    gray_world). Ohne Config-Block gilt damit der neue Default statt
    direkt gray_world.

    Returns:
        One of "auto", "gray_world", "skip", "fail"
    """
    if config and hasattr(config, 'multi_group') and config.multi_group:
        return config.multi_group.pcc_fallback
    return "auto"


def photometric_color_calibration(
    stacked: Optional[Path],
    params: dict,
    *,
    load_frame: Callable[[Path], np.ndarray],
    save_frame: Callable[[np.ndarray, Path], None],
    config=None,
    logger: Optional[logging.Logger] = None,
    ra: Optional[float] = None,
    dec: Optional[float] = None,
    pixel_scale_arcsec: float = 0.0,
) -> Optional[str]:
    """Apply PCC to the stacked frame (in-place overwrite).

    Refactor: moved from ``ProcessingAgent._photometric_color_calibration``
    in ``astro_process/agents/processing_agent.py`` (Cluster 5, 2026-08-14;
    unveraendert). Frame-I/O erfolgt ueber die Callables ``load_frame``/
    ``save_frame``; ``config`` steuert den Fallback (``get_pcc_fallback``).

    Returns:
        PCC status string (e.g. ``"gaia_success"``,
        ``"fallback_gray_world"``, ``"pcc_skipped"``) or ``None`` if the
        stack was missing/invalid (no PCC attempted).

    Args:
        stacked: Path to the stacked FITS file (overwritten on success).
        params: Processing params (liest ``gaia_timeout``, F-P2-GAIA-TIMEOUT).
        load_frame: Callable Path -> RGB array (H×W×3).
        save_frame: Callable (array, Path) -> None (ueberschreibt Datei).
        config: AppConfig (fuer ``multi_group.pcc_fallback``).
        logger: Optional structlog-Logger (Agent reicht seinen durch).
        ra/dec/pixel_scale_arcsec: WCS-Kontext fuer GAIA-PCC.
    """
    log = logger or logging.getLogger(__name__)
    if not stacked or not stacked.exists():
        return None

    log.info("pipeline.pcc_start")
    data = load_frame(stacked)

    if data.ndim != 3 or data.shape[-1] != 3:
        log.warning("pipeline.pcc_skipped", reason=f"expected 3D RGB, got shape {data.shape}")
        return None

    try:
        # F-P2-GAIA-TIMEOUT (S3-C5): Config-Feld `gaia_timeout` aus den
        # Processing-Params an apply_pcc durchreichen. Fehlt das Feld
        # (alte Presets), gilt der bisherige Default 30.0 (rueckwaerts-
        # kompatibel).
        #
        # Config-Level Precedence: AppConfig-Werte ueberschreiben
        # ProcessingParams-Defaults wenn der Preset den Default-Wert
        # (30.0) hat oder das Feld fehlt. Presets mit explizitem Timeout
        # != 30.0 behalten ihren Wert (Precedence: AppConfig > Preset
        # Default > Code Default).
        gaia_timeout = params.get("gaia_timeout", GAIA_QUERY_TIMEOUT_SECONDS)
        vizier_apass_timeout = params.get("vizier_apass_timeout", 30.0)
        vizier_refcat2_timeout = params.get("vizier_refcat2_timeout", 30.0)
        if config is not None:
            _cfg_gaia = getattr(config, "gaia_timeout", None)
            if _cfg_gaia is not None and gaia_timeout == GAIA_QUERY_TIMEOUT_SECONDS:
                gaia_timeout = _cfg_gaia
            _cfg_apass = getattr(config, "vizier_apass_timeout", None)
            if _cfg_apass is not None and vizier_apass_timeout == 30.0:
                vizier_apass_timeout = _cfg_apass
            _cfg_refcat2 = getattr(config, "vizier_refcat2_timeout", None)
            if _cfg_refcat2 is not None and vizier_refcat2_timeout == 30.0:
                vizier_refcat2_timeout = _cfg_refcat2
        # V1.4-19: Die Fallback-Strategie (auto/gray_world/skip/fail)
        # steuert die KETTE in apply_pcc (GAIA-Retry → VizieR → finale
        # Stufe) — nicht mehr erst den Fehlerpfad hier. apply_pcc gibt
        # bei "skip" + gescheiterter Kette None zurueck (kein gray_world).
        fallback = get_pcc_fallback(config)
        # Quality Gate (2026-08-21): Config pcc.quality_gate.{enabled,
        # min_factor, max_factor}; Defaults im Model (True, 0.5, 2.0).
        gate_enabled, gate_min_f, gate_max_f = True, 0.5, 2.0
        if config is not None:
            _qg = getattr(getattr(config, "pcc", None), "quality_gate", None)
            if _qg is not None:
                gate_enabled = bool(_qg.enabled)
                gate_min_f = float(_qg.min_factor)
                gate_max_f = float(_qg.max_factor)
        pcc_result = apply_pcc(
            data,
            ra=ra,
            dec=dec,
            pixel_scale_arcsec=pixel_scale_arcsec,
            gaia_timeout=gaia_timeout,
            vizier_apass_timeout=vizier_apass_timeout,
            vizier_refcat2_timeout=vizier_refcat2_timeout,
            fallback=fallback,
            quality_gate_enabled=gate_enabled,
            quality_gate_min_factor=gate_min_f,
            quality_gate_max_factor=gate_max_f,
        )
        if pcc_result.status == "rejected_implausible_factors":
            # Quality-Gate-Ablehnung: Stack NICHT ueberschreiben —
            # stacked.fits bleibt linear (stacked_linear.fits-Backup-
            # Logik unveraendert). Marker mit Faktoren macht den Zustand
            # maschinenlesbar; der Rueckgabe-Status fliesst via
            # ProcessingResult.pcc_status in agent-log.yaml UND
            # run-info.json.
            log.warning("pcc.status", status="rejected_implausible_factors")
            try:
                marker_path = stacked.parent / "PCC_REJECTED_FACTORS.txt"
                marker_path.write_text(
                    "PCC rejected: implausible color factors "
                    "(quality gate).\n"
                    f"r_factor={pcc_result.r_factor}\n"
                    f"g_factor={pcc_result.g_factor}\n"
                    f"b_factor={pcc_result.b_factor}\n"
                    f"allowed_range=[{gate_min_f}, {gate_max_f}]\n"
                    "Stack left linear (not overwritten).\n"
                )
            except Exception as marker_e:
                log.warning("pcc.reject_marker_failed", error=str(marker_e))
            # PCC_STATUS.txt auch hier schreiben — apply_pcc_per_group
            # leitet den Gruppen-Status daraus ab; ohne Datei wuerde der
            # Rejection-Status verloren gehen (Legacy-Heuristik).
            try:
                status_path = stacked.parent / "PCC_STATUS.txt"
                status_path.write_text(
                    "pcc_status=rejected_implausible_factors\n"
                )
            except Exception as status_e:
                log.warning("pcc.status_write_failed", error=str(status_e))
            log.info("pipeline.status", status="success_with_warnings",
                     warning="pcc_rejected_implausible_factors")
            return "rejected_implausible_factors"
        if pcc_result.corrected is None:
            # V1.4-19 (51 Cyg): "skip" — Katalog-Kette (GAIA-Retry +
            # VizieR) fehlgeschlagen, KEIN gray_world bei Stern-Presets.
            # Frame bleibt unveraendert (kein save_frame); der
            # PCC_SKIPPED.txt-Marker macht den Zustand maschinenlesbar
            # (apply_pcc_per_group liefert damit Status "skipped" statt
            # faelschlich "gaia_success").
            log.warning("pcc.status", status="skipped",
                        reason="catalog_chain_failed_no_gray_world_skip_preset")
            try:
                marker_path = stacked.parent / "PCC_SKIPPED.txt"
                marker_path.write_text(
                    "PCC (Photometric Color Calibration) skipped.\n"
                    "Catalog chain failed (GAIA retries + VizieR) and "
                    "pcc_fallback='skip' — no gray world for star presets.\n"
                    "Frame left uncorrected.\n"
                )
            except Exception as marker_e:
                log.warning("pcc.skip_marker_failed", error=str(marker_e))
            log.info("pipeline.status", status="success_with_warnings",
                     warning="pcc_skipped")
            return pcc_result.status or "pcc_skipped"
        # Backup linear stack BEFORE PCC overwrite (Fix: Problem 2)
        import shutil
        backup = stacked.parent / "stacked_linear.fits"
        shutil.copy2(stacked, backup)
        log.info("pcc.backup_created", path=str(backup))
        # Overwrite stacked with PCC-corrected version
        save_frame(pcc_result.corrected, stacked)
        # Write PCC_STATUS.txt for apply_pcc_per_group to read (replaces
        # marker-file detection logic with precise status propagation).
        try:
            status_path = stacked.parent / "PCC_STATUS.txt"
            status_path.write_text(f"pcc_status={pcc_result.status}\n")
        except Exception as status_e:
            log.warning("pcc.status_write_failed", error=str(status_e))
        log.info("pipeline.pcc_complete", ra=ra, dec=dec, pixel_scale=pixel_scale_arcsec,
                 pcc_status=pcc_result.status)
        return pcc_result.status
    except Exception as e:
        fallback = get_pcc_fallback(config)
        log.warning("pcc.apply_failed", error=str(e), fallback=fallback)

        if fallback in ("gray_world", "auto"):
            log.warning("pcc.status", status="fallback_gray_world", error=str(e))
            corrected = gray_world_white_balance(data)
            save_frame(corrected, stacked)
            # Write marker file
            marker_path = stacked.parent / "PCC_FALLBACK_GRAY_WORLD.txt"
            marker_path.write_text(
                "PCC (Photometric Color Calibration) failed.\n"
                f"Error: {e}\n"
                "Gray World fallback applied — colors are approximate only.\n"
                "Re-run with Gaia available for accurate color calibration.\n"
            )
            log.info("pipeline.status", status="success_with_warnings",
                     warning="pcc_fallback_gray_world")
            return "fallback_gray_world"
        elif fallback == "skip":
            log.warning("pcc.status", status="skipped", error=str(e))
            # V1.4-19: Zustand maschinenlesbar machen (analog
            # PCC_FALLBACK_GRAY_WORLD.txt) — apply_pcc_per_group erkennt
            # "skipped" statt faelschlich "gaia_success".
            try:
                marker_path = stacked.parent / "PCC_SKIPPED.txt"
                marker_path.write_text(
                    "PCC (Photometric Color Calibration) skipped.\n"
                    f"Error: {e}\n"
                    "No gray world for star presets — frame left uncorrected.\n"
                )
            except Exception as marker_e:
                log.warning("pcc.skip_marker_failed", error=str(marker_e))
            log.info("pipeline.status", status="success_with_warnings",
                     warning="pcc_skipped")
            return "pcc_skipped"
        else:  # "fail"
            log.error("pcc.status", status="failed", error=str(e))
            raise


def scnr(
    stacked: Optional[Path],
    params: dict,
    *,
    load_frame: Callable[[Path], np.ndarray],
    save_frame: Callable[[np.ndarray, Path], None],
    logger: Optional[logging.Logger] = None,
) -> None:
    """Remove green cast (SCNR) from the stacked frame (in-place overwrite).

    Refactor: moved from ``ProcessingAgent._scnr`` in
    ``astro_process/agents/processing_agent.py`` (Cluster 5, 2026-08-14;
    unveraendert). Frame-I/O erfolgt ueber die Callables ``load_frame``/
    ``save_frame``.

    Args:
        stacked: Path to the stacked FITS file (overwritten on success).
        params: Processing params (liest ``scnr_amount``).
        load_frame: Callable Path -> RGB array (H×W×3).
        save_frame: Callable (array, Path) -> None (ueberschreibt Datei).
        logger: Optional structlog-Logger (Agent reicht seinen durch).
    """
    log = logger or logging.getLogger(__name__)
    if not stacked or not stacked.exists():
        return

    amount = params.get("scnr_amount", 0.5)
    log.info("pipeline.scnr_start", amount=amount)
    data = load_frame(stacked)

    if data.ndim != 3 or data.shape[-1] != 3:
        log.warning("pipeline.scnr_skipped", reason=f"expected 3D RGB, got shape {data.shape}")
        return

    corrected = apply_scnr(data, amount=amount)
    save_frame(corrected, stacked)
    log.info("pipeline.scnr_complete")
