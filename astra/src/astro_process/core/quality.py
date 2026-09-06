"""Frame Quality Metrics (QF-A) — SNR, FWHM-Median, Outlier-Flagging,
Double-Rate, Elongation, Outlier-Rejection.

Reine numpy plus Wiederverwendung von ``pcc.detect_stars`` — es wird
keine zweite Stern-Detection implementiert (AC-QF-A2) und keine neue
Dependency eingefuehrt (AC-QF-A1, L3).

Metrik-Definitionen (einmal fixiert, OQ-QF-2-A — interpretierbar ueber
Runs hinweg):

- **Noise (Background-MAD, AC-QF-A5):** Vor der Rauschberechnung werden
  Hot-Pixel entfernt: Pixel ausserhalb
  ``|x - median| <= k_hot * 1.4826 * MAD`` werden auf den Background-
  Median gesetzt, **aber nur isolierte Einzelpixel** (3x3-Nachbarschaft
  ohne weiteren Kandidaten). Ausgedehnte Strukturen (Sterne, Nebel)
  bleiben erhalten, damit das Signal-P95 den Objektanteil misst und
  ``star_count``/``fwhm_median`` unverfaelscht bleiben (Teleskop (z.B. Dwarf3) hat bei
  37-39 °C Hot-Pixel; ohne Clipping wird das Rauschmass verfaelscht —
  stella-Hinweis 3). ``noise = 1.4826 * MAD`` des geclippten Bildes.
- **Signal (OQ-QF-2-A):** Objektanteil-Hoehe = Perzentil
  (``signal_percentile``, Default 95) des geclippten Bildes minus
  Background-Median. Klassische, interpretierbare Definition — Signal
  ist die Helligkeit des hellen Objektanteils, nicht der absolute Wert.
- **SNR = signal / noise.** Bei Noise ~ 0 (flaches Bild) und bei
  negativem Signal wird ``snr = 0.0`` geliefert (kein Objektanteil).
- **FWHM-Median (AC-QF-A2):** Median der ``fwhm_est``-Werte aus
  :func:`astro_process.core.pcc.detect_stars`. Wird mit < ``min_stars``
  Sternen ``None`` + Warning geliefert (AC-QF-A3) — kein Abbruch.
  Hot-Pixel werden vor der Detection auf Background gesetzt, damit sie
  weder als Sterne gezaehlt werden noch die Sigma-Schwelle verfaelschen.
- **Outlier (AC-QF-A4):** Frame-Level-Scores (snr, fwhm_median,
  star_count) gegen die Gruppen-Statistik (Median +/- k*MAD). Es wird
  **geflaggt, nicht verworfen** (Rejection = v1.3+); der Grund
  (snr/fwhm/star_count) wird dokumentiert.
- **Double-Rate (V1.5-9, AC-SD-1/2):** Anteil der Sterne mit einem
  benachbarten Flux-aequivalenten Maximum (Radius 5px, Flux-Ratio
  0.5-2.0). Additive Metrik fuer Outlier-Rejection (V1.5-8).
  sternhaufentolerant — natuerliche Dichte wird gemessen, nicht
  interpretiert (Schwelle liegt in V1.5-8).
- **Elongation (V1.5-3):** x/y-FWHM-Ratio (min/max) der hellsten
  Sterne. Misst elliptische Sternbilder durch AZ-Feldrotation oder
  Nachfuehrungsfehler. Ratio < 0.8 = Warning; Ratio < 0.6 = unusable.
  Require min_stars mit gueltigen FWHM_x/FWHM_y-Werten.
- **Outlier-Rejection (V1.5-8):** Frame-basierte Weighting/Rejection
  basierend auf QF-Metriken. Default-off — wenn
  ``rejection_enabled=False`` (Default), bleibt die Ausgabe
  byte-identisch zu v1.2.

Das Modul arbeitet auf 2D-Frames (H, W) — der Aufrufer (QF-B
Integration) waehlt den Frame-Kanal (z.B. den Registrations-Kanal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter

from astro_process.core.pcc import detect_stars

logger = structlog.get_logger(__name__)


@dataclass
class FrameQuality:
    """Per-frame quality metrics (QF-A schema).

    Attributes:
        frame: Optional frame identifier (path/name) filled by the
            caller; the core module leaves it ``None``.
        snr: Signal-to-noise ratio (see module docstring).
        fwhm_median: Median FWHM estimate of detected stars, or ``None``
            if fewer than ``min_stars`` stars were detected (AC-QF-A3).
        star_count: Number of detected stars.
        correlation: Optional registration correlation filled by the
            caller (QF-B integration); ``None`` at the core level.
        outlier: ``True`` when any frame-level score deviates beyond
            ``k*MAD`` from the group statistic (AC-QF-A4).
        outlier_reason: Comma-separated list of deviating metrics
            (``"snr"``, ``"fwhm"``, ``"star_count"``), or ``None``.
        double_rate: V1.5-9 (AC-SD-2): Fraction of stars classified as
            doubles/blends (0.0-1.0). ``None`` when fewer than
            ``min_stars`` stars were detected (AC-SD-3) or when
            double detection is disabled.
        elongation_ratio: V1.5-3 (AC-EL-1): x/y-FWHM-Ratio (min/max)
            of the brightest stars. ``None`` when elongation check is
            disabled, too few stars, or insufficient valid FWHM
            measurements.
        elongation_warning: V1.5-3 (AC-EL-2): ``True`` when
            ``elongation_ratio < elongation_warn_threshold`` (default
            0.8). ``False`` when check is disabled.
        elongation_unusable: V1.5-3 (AC-EL-3): ``True`` when
            ``elongation_ratio < elongation_unusable_threshold`` (default
            0.6). Frames marked unusable are excluded from registration.
        outlier_excluded: V1.5-8 (AC-OR-1): ``True`` when the frame
            was excluded from the stack due to outlier-rejection.
            ``False`` when rejection is disabled (default-off, AC-OR-2).
        outlier_reject_reason: V1.5-8 (AC-OR-3): Differenzierter Grund
            fuer den Ausschluss (``"star_count"``, ``"fwhm"``, ``"snr"``,
            ``"correlation"``, ``"double_rate"``, ``"elongation"``), oder
            ``None``.
        noise_sigma: V1.7-2 (AC-FSEL-A3): Rauschsigma 1.4826 * MAD des
            geclippten Bildes (Z.88-95). Additive Erweiterung, bisher
            internes Mass, jetzt exponiert.
    """

    frame: str | None = None
    snr: float = 0.0
    fwhm_median: float | None = None
    star_count: int = 0
    correlation: float | None = None
    outlier: bool = False
    outlier_reason: str | None = None
    double_rate: float | None = None
    # V1.5-3: Elongation
    elongation_ratio: float | None = None
    elongation_warning: bool = False
    elongation_unusable: bool = False
    # V1.5-8: Outlier-Rejection
    outlier_excluded: bool = False
    outlier_reject_reason: str | None = None
    # V1.7-2 FSEL-A (AC-FSEL-A3): internes Rauschmass exponiert.
    # Wert = 1.4826 * MAD des geclippten Bildes (Z.88-95), bisher nicht
    # exponiert. Additive Modellerweiterung, bestehende Felder/Aufrufer
    # bleiben unveraendert. None nur bei Legacy-Objekten ohne Neuberechnung.
    noise_sigma: float | None = None


def _clip_hot_pixels(image: NDArray[Any], k_hot: float) -> NDArray[Any]:
    """Return a copy of ``image`` with hot pixels replaced by background.

    Hot pixels are *small* outliers: ``|x - median| > k_hot * sigma``
    where ``sigma = 1.4826 * MAD`` (computed on the raw image; the MAD
    is robust enough for a first pass — the *noise* metric is then
    computed on the cleaned frame, AC-QF-A5). A candidate is only
    clipped when it has at most two further candidates inside its 3x3
    neighbourhood (single hot pixels, pairs, triples) — extended
    structures (star discs) survive, so the signal percentile
    (OQ-QF-2-A) and ``detect_stars`` still see the object component
    (AC-QF-A2). The MAD itself is computed on the cleaned frame.
    """
    flat = image.astype(np.float64).ravel()
    median = float(np.median(flat))
    mad = float(np.median(np.abs(flat - median)))
    sigma = 1.4826 * mad
    if sigma <= 1e-12:
        return np.array(image, copy=True)
    mask = np.abs(image - median) > k_hot * sigma
    if not np.any(mask):
        return np.array(image, copy=True)
    # Count candidates in the 3x3 neighbourhood (shifted copies are fine
    # for boundary pixels — a wrap artefact can only *keep* a hot pixel,
    # never clip a star). Clip candidates with at most two neighbours:
    # single hot pixels, pairs and triples. A real star disc has many
    # candidates around its core, so its pixels always survive.
    neighbourhood = mask.astype(np.int8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            neighbourhood = neighbourhood + np.roll(mask, (dy, dx), axis=(0, 1))
    clipped_mask = mask & (neighbourhood <= 3)
    if not np.any(clipped_mask):
        return np.array(image, copy=True)
    cleaned = np.array(image, copy=True)
    cleaned[clipped_mask] = median
    return cleaned


def detect_double_stars(
    stars: list[dict],
    *,
    radius_px: float = 5.0,
    flux_ratio_min: float = 0.5,
    flux_ratio_max: float = 2.0,
    min_stars: int = 10,
) -> float | None:
    """Detect blended/double stars and return the double rate (V1.5-9).

    For each star, check whether a second local maximum with similar flux
    exists within ``radius_px``.  Two stars form a "double" when their
    flux ratio ``min/max`` falls in ``[flux_ratio_min, flux_ratio_max]``.
    Each star is counted at most once (the first qualifying neighbor wins).

    The metric is **cluster-tolerant** (AC-SD-1): dense clusters (M3,
    NGC 6709) naturally produce many overlapping PSFs — the raw
    ``double_rate`` captures this; contextual interpretation (thresholding)
    is the responsibility of the outlier-rejection layer (V1.5-8).

    Args:
        stars: List of star dicts as returned by
            :func:`astro_process.core.pcc.detect_stars` (keys ``x``,
            ``y``, ``flux`` at minimum).
        radius_px: Maximum pixel distance for a neighbor to qualify
            (default 5 px, AC-SD-1).
        flux_ratio_min / flux_ratio_max: Acceptable flux ratio range
            (default 0.5–2.0, OQ-SD-1 Empfehlung A).
        min_stars: Minimum star count for a valid measurement.
            Below this threshold ``None`` is returned with a warning
            (AC-SD-3).

    Returns:
        ``double_rate`` (float 0.0–1.0) or ``None`` when the star count
        is below ``min_stars``.
    """
    if len(stars) < min_stars:
        logger.warning(
            "quality.double_too_few_stars",
            star_count=len(stars),
            min_stars=min_stars,
            action="double_rate=None",
        )
        return None

    if len(stars) < 2:
        return 0.0

    positions = np.array([(s["x"], s["y"]) for s in stars])

    try:
        from scipy.spatial import cKDTree
    except ImportError:
        # Fallback: O(N^2) brute-force when scipy is unavailable.
        # Production environments have scipy (via astroalign/sep).
        doubles = 0
        for i in range(len(stars)):
            for j in range(i + 1, len(stars)):
                dx = positions[i, 0] - positions[j, 0]
                dy = positions[i, 1] - positions[j, 1]
                if dx * dx + dy * dy > radius_px * radius_px:
                    continue
                flux_i = float(stars[i].get("flux", 0))
                flux_j = float(stars[j].get("flux", 0))
                if flux_i <= 0 or flux_j <= 0:
                    continue
                ratio = min(flux_i, flux_j) / max(flux_i, flux_j)
                if flux_ratio_min <= ratio <= flux_ratio_max:
                    doubles += 1
                    break  # each star counted at most once
        return doubles / len(stars)

    tree = cKDTree(positions)
    doubles = 0
    for i in range(len(stars)):
        neighbors = tree.query_ball_point(positions[i], radius_px)
        flux_i = float(stars[i].get("flux", 0))
        if flux_i <= 0:
            continue
        found_double = False
        for j in neighbors:
            if j <= i:
                continue
            flux_j = float(stars[j].get("flux", 0))
            if flux_j <= 0:
                continue
            ratio = min(flux_i, flux_j) / max(flux_i, flux_j)
            if flux_ratio_min <= ratio <= flux_ratio_max:
                doubles += 1
                found_double = True
                break  # each star counted at most once
        # avoid counting same pair from both sides — already handled by j > i

    return doubles / len(stars)


def _compute_elongation_ratio(
    image: NDArray[Any],
    stars: list[dict],
    *,
    min_stars: int = 10,
    warn_threshold: float = 0.8,
    unusable_threshold: float = 0.6,
) -> tuple[float | None, bool, bool]:
    """Compute the x/y FWHM elongation ratio for detected stars (V1.5-3).

    For each star, separate FWHM values along the x- and y-axes are
    computed from the star's segmented pixels (reuse of ``detect_stars``
    segments — AC-QF-A2, no second detection algorithm).  The
    elongation ratio is ``min(median_fwhm_x, median_fwhm_y) /
    max(median_fwhm_x, median_fwhm_y)`` across the ``min_stars``
    brightest stars with valid measurements (AC-EL-1).

    Args:
        image: 2D frame ``(H, W)`` (cleaned, hot-pixel-clipped).
        stars: List of star dicts from :func:`pcc.detect_stars`
            (keys ``x``, ``y``, ``flux``, ``fwhm_est`` at minimum).
        min_stars: Minimum number of stars with valid x/y FWHM
            measurements.  Below this threshold ``None`` is returned
            with a warning (AC-EL-5, consistent with AC-QF-A3).
        warn_threshold: Elongation ratio below which a warning is
            issued (default 0.8, OQ-EL-2 option B).
        unusable_threshold: Elongation ratio below which the frame
            is marked unusable (default 0.6, AC-EL-3).

    Returns:
        Tuple of ``(elongation_ratio, warning, unusable)``.
        ``elongation_ratio`` is ``None`` when the measurement cannot
        be performed (too few stars or insufficient valid measurements).
    """
    if len(stars) < min_stars:
        logger.warning(
            "quality.elongation_too_few_stars",
            star_count=len(stars),
            min_stars=min_stars,
            action="elongation_ratio=None",
        )
        return None, False, False

    sorted_stars = sorted(stars, key=lambda s: s.get("flux", 0), reverse=True)

    fwhm_x_vals: list[float] = []
    fwhm_y_vals: list[float] = []
    for star in sorted_stars:
        cx, cy = int(round(star["x"])), int(round(star["y"]))
        # Bounding box for the star segment (radius ~3*PSF, capped to image).
        r = max(int(round(star.get("fwhm_est", 2.0) * 1.5)), 3)
        y_min = max(0, cy - r)
        y_max = min(image.shape[0], cy + r + 1)
        x_min = max(0, cx - r)
        x_max = min(image.shape[1], cx + r + 1)
        if y_max <= y_min or x_max <= x_min:
            continue

        sub = image[y_min:y_max, x_min:x_max]
        if sub.size == 0:
            continue

        # FWHM-x: collapse y-axis → max along columns.
        prof_x = np.max(sub, axis=0)
        peak_x = float(np.max(prof_x))
        if peak_x <= 0:
            continue
        fwhm_x = float(np.sum(prof_x >= peak_x / 2.0))
        if fwhm_x <= 0:
            continue

        # FWHM-y: collapse x-axis → max along rows.
        prof_y = np.max(sub, axis=1)
        peak_y = float(np.max(prof_y))
        if peak_y <= 0:
            continue
        fwhm_y = float(np.sum(prof_y >= peak_y / 2.0))
        if fwhm_y <= 0:
            continue

        fwhm_x_vals.append(fwhm_x)
        fwhm_y_vals.append(fwhm_y)

    if len(fwhm_x_vals) < min_stars:
        logger.warning(
            "quality.elongation_insufficient_valid",
            valid_count=len(fwhm_x_vals),
            min_stars=min_stars,
            action="elongation_ratio=None",
        )
        return None, False, False

    median_fwhm_x = float(np.median(fwhm_x_vals))
    median_fwhm_y = float(np.median(fwhm_y_vals))
    min_fwhm = min(median_fwhm_x, median_fwhm_y)
    max_fwhm = max(median_fwhm_x, median_fwhm_y)

    if max_fwhm <= 1e-12:
        return None, False, False

    ratio = min_fwhm / max_fwhm
    warning = ratio < warn_threshold
    unusable = ratio < unusable_threshold

    logger.debug(
        "quality.elongation",
        elongation_ratio=round(ratio, 4),
        fwhm_x=round(median_fwhm_x, 2),
        fwhm_y=round(median_fwhm_y, 2),
        warning=warning,
        unusable=unusable,
    )
    return ratio, warning, unusable


def compute_frame_quality(
    image: NDArray[Any],
    *,
    min_stars: int = 5,
    signal_percentile: float = 95.0,
    hot_pixel_k: float = 5.0,
    detect_threshold: float = 5.0,
    min_area: int = 5,
    double_detection: bool = True,
    double_radius_px: float = 5.0,
    elongation_check: bool = False,
    elongation_min_stars: int = 10,
    elongation_warn_threshold: float = 0.8,
    elongation_unusable_threshold: float = 0.6,
    cfa_mode: bool = False,
    cfa_highpass_sigma: float = 30.0,
) -> FrameQuality:
    """Compute SNR, FWHM-Median, star count, double rate and elongation for one 2D frame.

    Args:
        image: 2D frame ``(H, W)``.
        min_stars: Below this star count ``fwhm_median`` becomes ``None``
            (AC-QF-A3).  Also the threshold below which ``double_rate``
            becomes ``None`` (AC-SD-3).
        signal_percentile: Percentile defining the object-part signal
            level (OQ-QF-2-A).
        hot_pixel_k: ``k`` for the hot-pixel clip (AC-QF-A5,
            ``k_hot * 1.4826 * MAD``).
        detect_threshold: Detection threshold (sigma) forwarded to
            :func:`pcc.detect_stars`.
        min_area: Minimum star pixel area forwarded to
            :func:`pcc.detect_stars`.
        double_detection: V1.5-9 (AC-SD-5): Enable star-double detection.
            ``False`` disables the metric (no overhead).
        double_radius_px: V1.5-9 (OQ-SD-2): Pixel radius for double-star
            neighborhood search (default 5 px).
        elongation_check: V1.5-3 (AC-EL-7): Enable x/y FWHM elongation
            measurement. ``False`` disables the metric (default, no
            overhead, byte-identical to v1.2).
        elongation_min_stars: V1.5-3 (AC-EL-5): Minimum stars for a
            valid elongation measurement (default 10).
        elongation_warn_threshold: V1.5-3 (AC-EL-2): Elongation ratio
            below which a warning is issued (default 0.8).
        elongation_unusable_threshold: V1.5-3 (AC-EL-3): Elongation
            ratio below which the frame is marked unusable (default 0.6).
        cfa_mode: V1.8-1 (CFA-Drizzle, DEF-004): Use a luminance high-pass
            on the CFA mono image before star detection.
        cfa_highpass_sigma: Sigma for the CFA high-pass filter
            (Default 30.0, matching the Subpixel-Registration high-pass).

    Returns:
        :class:`FrameQuality` with the computed metrics.

    V1.8-1 (CFA-Drizzle, DEF-004): When ``cfa_mode=True`` the star-detection
    image is pre-processed with a luminance high-pass
    (``image - gaussian_filter(image, sigma=cfa_highpass_sigma)``) so that
    star-detection works on un-debayered CFA raw data. SNR/noise remain
    computed on the original cleaned frame to stay interpretable. The caller
    supplies the CFA-specific ``min_stars`` (e.g. ``min_stars_cfa=3``).
    """
    image = np.asarray(image)
    if image.ndim != 2:
        raise ValueError(f"compute_frame_quality expects a 2D frame, got shape {image.shape}")

    cleaned = _clip_hot_pixels(image, k_hot=hot_pixel_k)

    flat = cleaned.astype(np.float64).ravel()
    bg_median = float(np.median(flat))
    noise = 1.4826 * float(np.median(np.abs(flat - bg_median)))
    signal = float(np.percentile(flat, signal_percentile)) - bg_median
    snr = float(signal / noise) if noise > 1e-12 else 0.0
    if not np.isfinite(snr) or snr < 0:
        snr = 0.0

    # V1.8-1 (CFA-Drizzle, DEF-004): high-pass on CFA mono for star detection.
    star_image = cleaned
    if cfa_mode:
        star_image = cleaned - gaussian_filter(cleaned, sigma=cfa_highpass_sigma)
        star_image = np.asarray(star_image, dtype=np.float64)

    stars = detect_stars(star_image, threshold=detect_threshold, min_area=min_area)
    star_count = len(stars)
    if star_count < min_stars:
        logger.warning(
            "quality.few_stars",
            star_count=star_count,
            min_stars=min_stars,
            action="fwhm_median=None",
        )
        fwhm_median: float | None = None
    else:
        fwhm_median = float(np.median([star["fwhm_est"] for star in stars]))

    # V1.5-9 (AC-SD-2/AC-SD-5): double_rate as additive metric.
    double_rate: float | None = None
    if double_detection and star_count >= min_stars:
        double_rate = detect_double_stars(stars, radius_px=double_radius_px, min_stars=min_stars)

    # V1.5-3 (AC-EL-1/AC-EL-7): elongation_ratio — only when enabled.
    elongation_ratio: float | None = None
    elongation_warning = False
    elongation_unusable = False
    if elongation_check and star_count >= elongation_min_stars:
        # Spec DEF-004: Hochpass nur fuer star detection, nicht fuer Elongation/SNR/noise.
        elongation_ratio, elongation_warning, elongation_unusable = _compute_elongation_ratio(
            cleaned,
            stars,
            min_stars=elongation_min_stars,
            warn_threshold=elongation_warn_threshold,
            unusable_threshold=elongation_unusable_threshold,
        )

    return FrameQuality(
        snr=snr,
        fwhm_median=fwhm_median,
        star_count=star_count,
        double_rate=double_rate,
        elongation_ratio=elongation_ratio,
        elongation_warning=elongation_warning,
        elongation_unusable=elongation_unusable,
        noise_sigma=float(noise) if np.isfinite(noise) else None,
    )


def flag_outliers(qualities: list[FrameQuality], *, k: float = 3.0) -> list[FrameQuality]:
    """Flag frames deviating from the group statistic (AC-QF-A4).

    For each metric with at least two values (``snr``, ``fwhm_median``,
    ``star_count``) the group median and MAD are computed; a frame is
    flagged when ``|value - median| > k * 1.4826 * MAD``. Frames are
    flagged, **not** removed (rejection is v1.3+). ``fwhm_median``
    values of ``None`` are skipped for the fwhm metric.

    Args:
        qualities: Frame quality metrics of one group (any order).
        k: Rejection factor in MAD-sigma units (default 3.0).

    Returns:
        A new list of :class:`FrameQuality` with ``outlier`` /
        ``outlier_reason`` filled; the input list is not mutated.
    """
    if k <= 0:
        raise ValueError(f"k must be > 0, got {k!r}")
    if not qualities:
        return []

    def _stat(values: list[float]) -> tuple[float, float] | None:
        if len(values) < 2:
            return None
        arr = np.asarray(values, dtype=np.float64)
        median = float(np.median(arr))
        mad = 1.4826 * float(np.median(np.abs(arr - median)))
        return median, mad

    metrics: dict[str, list[float]] = {"snr": [], "fwhm": [], "star_count": []}
    for q in qualities:
        metrics["snr"].append(float(q.snr))
        if q.fwhm_median is not None:
            metrics["fwhm"].append(float(q.fwhm_median))
        metrics["star_count"].append(float(q.star_count))

    thresholds: dict[str, tuple[float, float] | None] = {
        name: _stat(values) for name, values in metrics.items()
    }

    flagged: list[FrameQuality] = []
    for q in qualities:
        reasons: list[str] = []
        for metric, value in (
            ("snr", float(q.snr)),
            ("fwhm", q.fwhm_median),
            ("star_count", float(q.star_count)),
        ):
            if value is None:
                continue
            stat = thresholds[metric]
            if stat is None:
                continue
            median, mad = stat
            if mad <= 1e-12:
                continue
            if abs(value - median) > k * mad:
                reasons.append(metric)
        flagged.append(
            FrameQuality(
                frame=q.frame,
                snr=q.snr,
                fwhm_median=q.fwhm_median,
                star_count=q.star_count,
                correlation=q.correlation,
                double_rate=q.double_rate,
                elongation_ratio=q.elongation_ratio,
                elongation_warning=q.elongation_warning,
                elongation_unusable=q.elongation_unusable,
                noise_sigma=q.noise_sigma,
                outlier=bool(reasons),
                outlier_reason=",".join(reasons) if reasons else None,
            )
        )
    return flagged


def reject_outlier_frames(
    qualities: list[FrameQuality],
    *,
    thresholds: dict[str, tuple[float | None, float | None]] | None = None,
    elongation_unusable_enabled: bool = True,
) -> list[FrameQuality]:
    """Reject frames exceeding configurable per-metric thresholds (V1.5-8).

    Frames whose metric values exceed any configured threshold are marked
    ``outlier_excluded=True`` with the corresponding ``outlier_reject_reason``.
    This function is **default-off** (AC-OR-2): when called with no
    thresholds and ``elongation_unusable_enabled=False``, all frames
    pass through unmodified — the output is byte-identical to v1.2.

    Configurable thresholds (per AC-OR-4, default: all deactivated):

    - ``star_count``: ``(min, max)`` — exclude if count < min or count > max.
    - ``fwhm``: ``(min, max)`` — exclude if fwhm_median < min or fwhm_median > max.
    - ``snr``: ``(min, max)`` — exclude if snr < min or snr > max.
    - ``correlation``: ``(min, max)`` — exclude if correlation < min or correlation > max.
    - ``double_rate``: ``(min, max)`` — exclude if double_rate < min or double_rate > max.
    - ``elongation``: Frames with ``elongation_unusable=True`` are excluded
      when ``elongation_unusable_enabled=True`` (AC-OR-8, integrates V1.5-3).

    Args:
        qualities: Frame quality metrics of one group (any order).
        thresholds: Per-metric ``(min, max)`` bounds. ``None`` values
            mean no lower/upper bound. Empty dict or ``None`` = no
            rejection (default-off).
        elongation_unusable_enabled: When ``True`` (default), frames with
            ``elongation_unusable=True`` are excluded. Set to ``False``
            to decouple elongation from rejection.

    Returns:
        A new list of :class:`FrameQuality` with ``outlier_excluded`` /
        ``outlier_reject_reason`` filled; the input list is not mutated.
    """
    if not qualities:
        return []

    if not thresholds:
        thresholds = {}

    reject_map: dict[int, str] = {}  # index -> reject_reason

    for i, q in enumerate(qualities):
        reasons: list[str] = []

        # Elongation-based rejection (AC-OR-8, V1.5-3 integration).
        if elongation_unusable_enabled and q.elongation_unusable:
            reasons.append("elongation")

        # Per-metric threshold checks.
        metric_checks: list[tuple[str, float | None]] = [
            ("star_count", float(q.star_count)),
            ("fwhm", q.fwhm_median),
            ("snr", float(q.snr)),
            ("correlation", q.correlation),
            ("double_rate", q.double_rate),
        ]
        for metric_name, value in metric_checks:
            if value is None:
                continue
            bounds = thresholds.get(metric_name)
            if bounds is None:
                continue
            lo, hi = bounds
            if lo is not None and value < lo:
                reasons.append(metric_name)
            if hi is not None and value > hi:
                reasons.append(metric_name)

        if reasons:
            reject_map[i] = ",".join(reasons)

    if not reject_map:
        # No rejections — return copies with outlier_excluded=False.
        return [
            FrameQuality(
                frame=q.frame,
                snr=q.snr,
                fwhm_median=q.fwhm_median,
                star_count=q.star_count,
                correlation=q.correlation,
                outlier=q.outlier,
                outlier_reason=q.outlier_reason,
                double_rate=q.double_rate,
                elongation_ratio=q.elongation_ratio,
                elongation_warning=q.elongation_warning,
                elongation_unusable=q.elongation_unusable,
                noise_sigma=q.noise_sigma,
                outlier_excluded=False,
                outlier_reject_reason=None,
            )
            for q in qualities
        ]

    result: list[FrameQuality] = []
    for i, q in enumerate(qualities):
        is_rejected = i in reject_map
        result.append(
            FrameQuality(
                frame=q.frame,
                snr=q.snr,
                fwhm_median=q.fwhm_median,
                star_count=q.star_count,
                correlation=q.correlation,
                outlier=q.outlier,
                outlier_reason=q.outlier_reason,
                double_rate=q.double_rate,
                elongation_ratio=q.elongation_ratio,
                elongation_warning=q.elongation_warning,
                elongation_unusable=q.elongation_unusable,
                noise_sigma=q.noise_sigma,
                outlier_excluded=is_rejected,
                outlier_reject_reason=reject_map.get(i),
            )
        )

    n_rejected = len(reject_map)
    logger.info(
        "quality.outlier_rejection",
        total=len(qualities),
        rejected=n_rejected,
        rate=round(n_rejected / len(qualities), 4) if qualities else 0,
    )
    return result


# Refactor: moved from processing_agent.py (Cluster 4, 2026-08-14)
def qual_to_dict(q: FrameQuality) -> dict:
    """QF-B: FrameQuality -> serialisierbares dict (QF-A-Schema).

    Refactor: moved from ``ProcessingAgent._qual_to_dict`` in
    ``astro_process/agents/processing_agent.py`` (unveraendert, nur als
    Modul-Funktion statt @staticmethod).
    """
    return {
        "frame": q.frame,
        "snr": round(q.snr, 4),
        "fwhm_median": round(q.fwhm_median, 4) if q.fwhm_median is not None else None,
        "star_count": q.star_count,
        "correlation": round(q.correlation, 4) if q.correlation is not None else None,
        "double_rate": round(q.double_rate, 4) if q.double_rate is not None else None,
        "outlier": q.outlier,
        "outlier_reason": q.outlier_reason,
        # V1.5-3: Elongation (additive).
        "elongation_ratio": round(q.elongation_ratio, 4) if q.elongation_ratio is not None else None,
        "elongation_warning": q.elongation_warning,
        "elongation_unusable": q.elongation_unusable,
        # V1.5-8: Outlier-Rejection (additive).
        "outlier_excluded": q.outlier_excluded,
        "outlier_reject_reason": q.outlier_reject_reason,
        # V1.7-2 FSEL-A (AC-FSEL-A3): noise_sigma exponiert.
        "noise_sigma": round(q.noise_sigma, 4) if q.noise_sigma is not None else None,
    }


# Refactor: moved from processing_agent.py (Cluster 4, 2026-08-14)
def summarize_qualities(qualities: list[FrameQuality]) -> dict:
    """QF-B (AC-QF-B1): Gruppen-Stack-Zusammenfassung der Frame-Metriken.

    Median-FWHM, Median-SNR, Outlier-Rate, Elongation-Stats,
    Rejection-Rate — Grundlage fuer agent-log und merge_report
    (AC-QF-B1/B2).

    Refactor: moved from ``ProcessingAgent._summarize_qualities`` in
    ``astro_process/agents/processing_agent.py`` (unveraendert, nur als
    Modul-Funktion statt @staticmethod).
    """
    if not qualities:
        return {
            "frames": 0,
            "median_fwhm": None,
            "median_snr": None,
            "median_double_rate": None,
            "outlier_rate": None,
            # V1.5-3: Elongation stats.
            "median_elongation_ratio": None,
            "elongation_warning_count": 0,
            "elongation_unusable_count": 0,
            # V1.5-8: Rejection stats.
            "rejection_rate": None,
        }
    fwhms = [q.fwhm_median for q in qualities if q.fwhm_median is not None]
    snrs = [q.snr for q in qualities]
    doubles = [q.double_rate for q in qualities if q.double_rate is not None]
    outliers = [q for q in qualities if q.outlier]
    # V1.5-3: Elongation.
    elongations = [q.elongation_ratio for q in qualities if q.elongation_ratio is not None]
    el_warnings = sum(1 for q in qualities if q.elongation_warning)
    el_unusable = sum(1 for q in qualities if q.elongation_unusable)
    # V1.5-8: Rejection.
    rejected = [q for q in qualities if q.outlier_excluded]
    # V1.7-2 FSEL-A: noise_sigma.
    noises = [q.noise_sigma for q in qualities if q.noise_sigma is not None]
    return {
        "frames": len(qualities),
        "median_fwhm": round(float(np.median(fwhms)), 4) if fwhms else None,
        "median_snr": round(float(np.median(snrs)), 4) if snrs else None,
        "median_double_rate": round(float(np.median(doubles)), 4) if doubles else None,
        "outlier_rate": round(len(outliers) / len(qualities), 4),
        # V1.5-3: Elongation.
        "median_elongation_ratio": round(float(np.median(elongations)), 4) if elongations else None,
        "elongation_warning_count": el_warnings,
        "elongation_unusable_count": el_unusable,
        # V1.5-8: Rejection.
        "rejection_rate": round(len(rejected) / len(qualities), 4),
        # V1.7-2 FSEL-A: noise_sigma.
        "median_noise_sigma": round(float(np.median(noises)), 4) if noises else None,
    }


# ── V1.7-2 FSEL-A: Kompositer Score (DwarfLab-Pattern) ─────────────

# Richtungen: +1 = höher ist besser, -1 = niedriger ist besser.
# OQ-FSEL-1 A: noise_sigma NICHT im Default-Score (korreliert mit snr →
# Doppelstrafung), aber als Feld vorhanden. Gleichgewichtet (OQ-FSEL-1 A).
_FSEL_DEFAULT_METRICS: dict[str, int] = {
    "snr": +1,
    "star_count": +1,
    "fwhm_median": -1,  # schärfer ist besser
    # elongation_ratio: runder ist besser → höherer Ratio (1.0 = zirkulär)
    # Spec schreibt (−), runder ist besser. Ratio min/max: höher = besser,
    # daher +1. Kommentar hält Spec-Polarity fest (L4).
    "elongation_ratio": +1,
}

# Alternative: wenn Spec-Polarity wörtlich (−) für elongation_ratio
# gewünscht ist, Gewichte mit negativem Eintrag überschreiben.
# Default bleibt +1 (runder besser) — konfigurierbar via weights.


def compute_frame_score(
    qualities: list[FrameQuality],
    weights: dict[str, float] | None = None,
) -> list[float]:
    """FSEL-A (AC-FSEL-A1..A5): Kompositer Score je Frame ∈[0,1].

    Session-relativ Median/MAD-normalisiert (nicht min-max), robust gegen
    Ausreißer (AC-FSEL-A2). Beteiligte Metriken Default: snr (+),
    star_count (+), fwhm_median (−), elongation_ratio (−→+1, runder besser,
    L4-Kommentar) gleichgewichtet (OQ-FSEL-1 A, AC-FSEL-A4). noise_sigma wird
    NICHT in den Score einbezogen (OQ-FSEL-1 A), ist aber als Feld vorhanden
    (AC-FSEL-A3).

    Gewichte konfigurierbar (``weights``), Default Gleichverteilung über
    aktive Metriken (AC-FSEL-A4). Fehlende/NaN-Metrik → schlechtester Score
    (0.0 für diese Metrik, Ende sortieren, nicht crashen, AC-FSEL-A5).

    Normalisierung je Metrik:
      median = median(valid_values)
      mad = median(|x - median|)
      sigma = 1.4826 * mad
      z = (value - median) / sigma  (falls sigma > eps, sonst 0)
      effective_z = direction * z   (direction +1/−1)
      score_m = clip(0.5 + effective_z / 6.0, 0, 1)
      → 3σ über Median = 1.0, 3σ unter Median = 0.0, Median = 0.5.
      Robust: Ausreißer saturieren an 0/1 (nicht Hebel wie min-max).

    Finale Scores: gewichtetes Mittel über aktive Metriken, ∈[0,1].

    Config-Gewichte (L4): werden normalisiert (Summe 1), unbekannte Keys
    ignoriert (Warning), negative Gewichte auf 0 geklemmt.

    Args:
        qualities: FrameQuality-Liste einer Gruppe (beliebige Reihenfolge).
        weights: Mapping Metrik → Gewicht. None = Default gleichverteilt.
            Unterstützte Keys: snr, star_count, fwhm_median,
            elongation_ratio, noise_sigma (optional, falls gewünscht).

    Returns:
        Liste der Scores ∈[0,1] in Eingabereihenfolge (len == len(qualities)).
    """
    if not qualities:
        return []

    # Gewichte auflösen → aktive Metriken bestimmen.
    # Default: 4 Metriken gleichgewichtet.
    if weights is None:
        raw_weights: dict[str, float] = {k: 1.0 for k in _FSEL_DEFAULT_METRICS}
    else:
        # Kopie, unbekannte Keys filtern, negative auf 0.
        raw_weights = {}
        for k, v in weights.items():
            if k not in ("snr", "star_count", "fwhm_median", "elongation_ratio", "noise_sigma"):
                logger.warning("quality.frame_score_unknown_weight", metric=k, action="ignored")
                continue
            try:
                fv = float(v)
            except Exception:
                logger.warning("quality.frame_score_invalid_weight", metric=k, value=v, action="ignored")
                continue
            if not np.isfinite(fv) or fv < 0:
                logger.warning("quality.frame_score_negative_weight", metric=k, weight=v, action="clamped_to_0")
                fv = 0.0
            raw_weights[k] = fv
        if not raw_weights:
            # Fallback: Default, wenn alle Gewichte verworfen.
            raw_weights = {k: 1.0 for k in _FSEL_DEFAULT_METRICS}

    # Richtung für jede Metrik (noise_sigma: höheres Rauschen schlechter → −1)
    direction_map: dict[str, int] = {
        **_FSEL_DEFAULT_METRICS,
        "noise_sigma": -1,
    }

    # Aktive Metriken: nur solche mit mindestens einem validen Wert UND Gewicht >0.
    # Damit AC-FSEL-A4 "Gleichverteilung über aktive Metriken" erfüllt ist —
    # z.B. wenn elongation_ratio überall None (elongation_check off) → Metrik
    # inaktiv, Gewichte werden über verbleibende renormalisiert.
    def _valid_values(metric: str) -> list[float]:
        vals: list[float] = []
        for q in qualities:
            v: float | None
            if metric == "snr":
                v = float(q.snr)
            elif metric == "star_count":
                v = float(q.star_count)
            elif metric == "fwhm_median":
                v = q.fwhm_median
            elif metric == "elongation_ratio":
                v = q.elongation_ratio
            elif metric == "noise_sigma":
                v = q.noise_sigma
            else:
                v = None
            if v is None:
                continue
            try:
                fv = float(v)
            except Exception:
                continue
            if not np.isfinite(fv):
                continue
            vals.append(fv)
        return vals

    active_metrics: list[str] = []
    for m, w in raw_weights.items():
        if w <= 0:
            continue
        if _valid_values(m):
            active_metrics.append(m)

    # Falls keine aktive Metrik (alle None) → alle Scores 0.0 (worst) statt Crash.
    if not active_metrics:
        logger.warning("quality.frame_score_no_active_metric", weights=raw_weights, action="scores=0")
        return [0.0 for _ in qualities]

    # Gewichte über aktive Metriken renormalisieren (Gleichverteilung falls Default).
    total_w = sum(raw_weights[m] for m in active_metrics)
    if total_w <= 1e-12:
        # Fallback Gleichverteilung
        norm_weights = {m: 1.0 / len(active_metrics) for m in active_metrics}
    else:
        norm_weights = {m: raw_weights[m] / total_w for m in active_metrics}

    # Je aktiver Metrik Median/MAD/Sigma berechnen.
    stats: dict[str, tuple[float, float]] = {}
    for m in active_metrics:
        vals = _valid_values(m)
        # vals nicht leer (active check), aber robust gegen <2.
        if len(vals) < 2:
            # Kein MAD sinnvoll → sigma klein, alle z≈0 → score 0.5 neutral.
            median = float(np.median(vals)) if vals else 0.0
            sigma = 1.0  # Dummy, führt zu neutralen Scores
        else:
            arr = np.asarray(vals, dtype=np.float64)
            median = float(np.median(arr))
            mad = float(np.median(np.abs(arr - median)))
            sigma = 1.4826 * mad
            if sigma <= 1e-12:
                sigma = 1.0  # Konstante Metrik → neutral (z=0)
        stats[m] = (median, sigma)

    scores: list[float] = []
    for q in qualities:
        # AC-FSEL-A5: fehlende/NaN in irgendeiner aktiven Metrik → schlechtesten
        # Gesamt-Score (Ende sortieren, nicht crashen). Detektion vor Mittelung.
        missing_any = False
        for m in active_metrics:
            if m == "snr":
                is_missing = not np.isfinite(float(q.snr))
            elif m == "star_count":
                is_missing = not np.isfinite(float(q.star_count))
            elif m == "fwhm_median":
                is_missing = q.fwhm_median is None or not np.isfinite(float(q.fwhm_median))
            elif m == "elongation_ratio":
                is_missing = q.elongation_ratio is None or not np.isfinite(float(q.elongation_ratio))
            elif m == "noise_sigma":
                is_missing = q.noise_sigma is None or not np.isfinite(float(q.noise_sigma))
            else:
                is_missing = True
            if is_missing:
                missing_any = True
                break
        if missing_any:
            scores.append(0.0)
            continue

        weighted_sum = 0.0
        for m in active_metrics:
            median, sigma = stats[m]
            if m == "snr":
                raw = float(q.snr)
            elif m == "star_count":
                raw = float(q.star_count)
            elif m == "fwhm_median":
                raw = q.fwhm_median  # type: ignore[assignment]
            elif m == "elongation_ratio":
                raw = q.elongation_ratio  # type: ignore[assignment]
            elif m == "noise_sigma":
                raw = q.noise_sigma  # type: ignore[assignment]
            else:
                raw = None  # type: ignore[assignment]

            fv = float(raw)  # type: ignore[arg-type]
            direction = direction_map.get(m, +1)
            z = (fv - median) / sigma if sigma > 1e-12 else 0.0
            effective_z = direction * z
            # Clip z auf [-3,3] implizit via clip auf [0,1] mit /6
            score_m = float(np.clip(0.5 + effective_z / 6.0, 0.0, 1.0))
            if not np.isfinite(score_m):
                score_m = 0.0
            weighted_sum += norm_weights[m] * score_m

        final = float(np.clip(weighted_sum, 0.0, 1.0))
        if not np.isfinite(final):
            final = 0.0
        scores.append(final)

    return scores


__all__ = [
    "FrameQuality",
    "compute_frame_quality",
    "detect_double_stars",
    "flag_outliers",
    "reject_outlier_frames",
    "compute_frame_score",
    "qual_to_dict",
    "summarize_qualities",
    "_clip_hot_pixels",
    "_compute_elongation_ratio",
]
