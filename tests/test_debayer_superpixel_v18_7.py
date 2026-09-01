"""V1.8-7: Superpixel-Debayer-Pipeline 1:1 validieren.

Diese Test-Datei ergaenzt test_debayer_method_label.py um dedizierte
Regressionstests fuer die Superpixel-Pipeline gegen bilinear/malvar:
Shape/Dtype, PCC-Skala (stack_scale_factor), visuelle/metrische Qualitaet
auf synthetischen Sternen, sowie dokumentierte M92-Skip-Tests.

AC-DEB-A1..A3, B1..B3, C1..C2 + stella-Erweiterung (Farbsaum, Moire,
Flux-Erhalt). Keine Production-Code-Aenderung.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.config.loader import resolve_stack_scale_factor
from astro_process.core.debayer import (
    debayer_bilinear,
    debayer_malvar2004,
    debayer_superpixel,
)
from astro_process.core.equipment import resolve_debayer_factor
from astro_process.core.pcc import compute_pixel_scale


# ── Helpers ─────────────────────────────────────────────────────────────

PATTERNS = ("RGGB", "BGGR", "GBRG", "GRBG")


def _rgb_to_bayer(rgb: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    """Erzeuge CFA aus einem vollen RGB-Bild nach dem angegebenen Pattern.

    rgb: (H, W, 3) float32/uint16.
    Returns: (H, W) array mit nur einem Kanal pro Pixel.
    """
    pattern_upper = pattern.upper()
    if pattern_upper == "RGGB":
        r_off, g1_off, g2_off, b_off = (0, 0), (0, 1), (1, 0), (1, 1)
    elif pattern_upper == "BGGR":
        r_off, g1_off, g2_off, b_off = (1, 1), (0, 1), (1, 0), (0, 0)
    elif pattern_upper == "GBRG":
        r_off, g1_off, g2_off, b_off = (0, 1), (0, 0), (1, 1), (1, 0)
    elif pattern_upper == "GRBG":
        r_off, g1_off, g2_off, b_off = (1, 0), (0, 0), (1, 1), (0, 1)
    else:
        raise ValueError(f"Unsupported Bayer pattern: {pattern}")

    h, w, _ = rgb.shape
    cfa = np.zeros((h, w), dtype=rgb.dtype)
    cfa[r_off[0]::2, r_off[1]::2] = rgb[r_off[0]::2, r_off[1]::2, 0]
    cfa[g1_off[0]::2, g1_off[1]::2] = rgb[g1_off[0]::2, g1_off[1]::2, 1]
    cfa[g2_off[0]::2, g2_off[1]::2] = rgb[g2_off[0]::2, g2_off[1]::2, 1]
    cfa[b_off[0]::2, b_off[1]::2] = rgb[b_off[0]::2, b_off[1]::2, 2]
    return cfa


def _gaussian_star_rgb(
    shape: tuple[int, int],
    center: tuple[float, float] | None = None,
    sigma: float = 1.5,
    peak: float = 10000.0,
    background: float = 100.0,
) -> np.ndarray:
    """Erzeuge ein weisses (R=G=B) Gauss-Stern-Bild in voller Aufloesung."""
    h, w = shape
    y, x = np.ogrid[:h, :w]
    if center is None:
        cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    else:
        cy, cx = center
    r2 = (y - cy) ** 2 + (x - cx) ** 2
    star = background + peak * np.exp(-r2 / (2.0 * sigma**2))
    rgb = np.stack([star, star, star], axis=-1).astype(np.float32)
    return rgb


def _circular_aperture_sum(
    image: np.ndarray, cy: float, cx: float, radius: float
) -> float:
    """Einfache kreisfoermige Apertur-Summe (ohne partielle Pixel)."""
    y, x = np.ogrid[: image.shape[0], : image.shape[1]]
    mask = (y - cy) ** 2 + (x - cx) ** 2 <= radius**2
    return float(image[mask].sum())


def _fft_peak_at_period(
    image: np.ndarray, period_px: float, direction: str = "both"
) -> float:
    """Maximale Amplitude der 2D-FFT bei einer bestimmten Periodizitaet (Pixel).

    direction: "horizontal" (vertikale Frequenzachse -> horizontale Muster),
               "vertical"   (horizontale Frequenzachse -> vertikale Muster),
               "both".
    """
    f = np.fft.fft2(image.astype(np.float64))
    fshift = np.fft.fftshift(f)
    magnitude = np.abs(fshift)
    h, w = image.shape

    # Frequenzindex k entspricht Periode N/k; positive Frequenz -> k = N/p
    ky = max(1, int(np.round(h / period_px)))
    kx = max(1, int(np.round(w / period_px)))

    peaks: list[float] = []
    if direction in ("horizontal", "both"):
        for dx in (-kx, kx):
            ix = (dx + w // 2) % w
            peaks.append(float(magnitude[h // 2, ix]))
    if direction in ("vertical", "both"):
        for dy in (-ky, ky):
            iy = (dy + h // 2) % h
            peaks.append(float(magnitude[iy, w // 2]))
    return max(peaks)


# ── AC-DEB-A: Shape/Dtype ───────────────────────────────────────────────


class TestSuperpixelShapeDtype:
    """AC-DEB-A1 + A3: Superpixel liefert (H/2, W/2, 3) float32 ohne NaN/Inf."""

    @pytest.mark.parametrize("pattern", PATTERNS)
    def test_superpixel_shape_uint16(self, pattern: str):
        data = np.ones((8, 12), dtype=np.uint16) * 1000
        rgb = debayer_superpixel(data, pattern=pattern)
        assert rgb.shape == (4, 6, 3)
        assert rgb.dtype == np.float32

    @pytest.mark.parametrize("pattern", PATTERNS)
    def test_superpixel_shape_float32(self, pattern: str):
        data = np.ones((8, 12), dtype=np.float32) * 1000.0
        rgb = debayer_superpixel(data, pattern=pattern)
        assert rgb.shape == (4, 6, 3)
        assert rgb.dtype == np.float32

    def test_superpixel_no_nan_inf_uint16(self):
        data = np.random.default_rng(42).integers(
            0, 65535, size=(16, 16), dtype=np.uint16
        )
        rgb = debayer_superpixel(data)
        assert np.isfinite(rgb).all()

    def test_superpixel_no_nan_inf_float32(self):
        rng = np.random.default_rng(42)
        data = rng.random((16, 16), dtype=np.float32) * 65535.0
        rgb = debayer_superpixel(data)
        assert np.isfinite(rgb).all()


class TestBilinearMalvarShapeDtype:
    """AC-DEB-A2 + A3: bilinear/malvar liefern (H, W, 3) float32 ohne NaN/Inf."""

    @pytest.mark.parametrize("pattern", PATTERNS)
    def test_bilinear_shape_uint16(self, pattern: str):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            data = np.ones((8, 12), dtype=np.uint16) * 1000
            rgb = debayer_bilinear(data, pattern=pattern)
        assert rgb.shape == (8, 12, 3)
        assert rgb.dtype == np.float32
        assert np.isfinite(rgb).all()

    @pytest.mark.parametrize("pattern", PATTERNS)
    def test_malvar_shape_uint16(self, pattern: str):
        data = np.ones((8, 12), dtype=np.uint16) * 1000
        rgb = debayer_malvar2004(data, pattern=pattern)
        assert rgb.shape == (8, 12, 3)
        assert rgb.dtype == np.float32
        assert np.isfinite(rgb).all()

    @pytest.mark.parametrize("pattern", PATTERNS)
    def test_bilinear_shape_float32(self, pattern: str):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            data = np.ones((8, 12), dtype=np.float32) * 1000.0
            rgb = debayer_bilinear(data, pattern=pattern)
        assert rgb.shape == (8, 12, 3)
        assert rgb.dtype == np.float32

    @pytest.mark.parametrize("pattern", PATTERNS)
    def test_malvar_shape_float32(self, pattern: str):
        data = np.ones((8, 12), dtype=np.float32) * 1000.0
        rgb = debayer_malvar2004(data, pattern=pattern)
        assert rgb.shape == (8, 12, 3)
        assert rgb.dtype == np.float32


# ── AC-DEB-B: stack_scale_factor ────────────────────────────────────────


class TestStackScaleFactorResolution:
    """AC-DEB-B1..B3: Auto-Werte und Precedence fuer stack_scale_factor."""

    def test_auto_superpixel_is_2(self):
        assert resolve_stack_scale_factor("superpixel", None) == 2.0
        factor, source = resolve_debayer_factor("superpixel")
        assert factor == 2.0
        assert source == "auto_data"

    def test_auto_bilinear_is_1(self):
        assert resolve_stack_scale_factor("bilinear", None) == 1.0
        factor, source = resolve_debayer_factor("bilinear")
        assert factor == 1.0
        assert source == "auto_data"

    def test_auto_malvar_is_1(self):
        assert resolve_stack_scale_factor("malvar", None) == 1.0
        factor, source = resolve_debayer_factor("malvar")
        assert factor == 1.0
        assert source == "auto_data"

    def test_explicit_override_wins(self):
        assert resolve_stack_scale_factor("superpixel", explicit_value=1.5) == 1.5
        assert resolve_stack_scale_factor("bilinear", explicit_value=1.5) == 1.5
        assert resolve_stack_scale_factor("malvar", explicit_value=1.5) == 1.5

    def test_preset_between_explicit_and_auto(self):
        # explicit > preset > auto
        assert resolve_stack_scale_factor("superpixel", preset_value=3.0) == 3.0
        assert (
            resolve_stack_scale_factor(
                "superpixel", explicit_value=1.5, preset_value=3.0
            )
            == 1.5
        )

    def test_input_is_rgb_overrides_method(self):
        # 3D Input -> 1.0 unabhaengig von Methode
        assert resolve_stack_scale_factor("superpixel", input_is_rgb=True) == 1.0
        assert resolve_stack_scale_factor("bilinear", input_is_rgb=True) == 1.0

    def test_pixel_scale_with_binning(self):
        """PCC-Skala: 206.265 * pixel_um * binning / focal."""
        focal, pixel_um = 150.0, 2.9
        assert compute_pixel_scale(focal, pixel_um, binning=2.0) == pytest.approx(
            206.265 * 2.9 * 2.0 / 150.0, rel=1e-9
        )
        assert compute_pixel_scale(focal, pixel_um, binning=1.0) == pytest.approx(
            206.265 * 2.9 * 1.0 / 150.0, rel=1e-9
        )


# ── stella-Erweiterung: Qualitaetsmetriken ──────────────────────────────


class TestDebayerQualityMetrics:
    """stella-Erweiterung: Farbsaum, Moire, Flux-Erhalt auf synthetischen Sternen."""

    def _make_white_star_bayer(
        self,
        shape: tuple[int, int] = (64, 64),
        center: tuple[float, float] | None = None,
        sigma: float = 1.5,
        peak: float = 10000.0,
        pattern: str = "RGGB",
    ) -> np.ndarray:
        rgb = _gaussian_star_rgb(shape, center=center, sigma=sigma, peak=peak)
        return _rgb_to_bayer(rgb, pattern=pattern)

    def test_color_fringe_white_star_r_b_delta(self):
        """Farbsaum: R/B-Flux-Differenz an einem weissen Stern klein."""
        pattern = "RGGB"
        cfa = self._make_white_star_bayer(
            shape=(64, 64),
            center=(31.5, 31.5),
            sigma=2.0,
            peak=20000.0,
            pattern=pattern,
        )
        rgb_sp = debayer_superpixel(cfa, pattern=pattern)
        rgb_mv = debayer_malvar2004(cfa, pattern=pattern)

        # Aperture in output coords; superpixel is half resolution
        cy_sp, cx_sp = 31.5 / 2, 31.5 / 2
        cy_mv, cx_mv = 31.5, 31.5
        r_sp = 5.0
        r_mv = 10.0

        def _rb_delta(rgb, cy, cx, radius):
            r = _circular_aperture_sum(rgb[:, :, 0], cy, cx, radius)
            b = _circular_aperture_sum(rgb[:, :, 2], cy, cx, radius)
            return abs(r - b) / max((r + b) / 2.0, 1.0)

        delta_sp = _rb_delta(rgb_sp, cy_sp, cx_sp, r_sp)
        delta_mv = _rb_delta(rgb_mv, cy_mv, cx_mv, r_mv)
        # For a white star, R and B should be similar; allow some sampling noise
        assert delta_sp < 0.10, f"superpixel R/B delta {delta_sp:.3f}"
        assert delta_mv < 0.10, f"malvar R/B delta {delta_mv:.3f}"

    def test_flux_conservation_superpixel_vs_malvar(self):
        """Flux-Erhalt: Apertur-Photometrie superpixel vs malvar < 2%."""
        pattern = "RGGB"
        cfa = self._make_white_star_bayer(
            shape=(64, 64),
            center=(31.5, 31.5),
            sigma=2.0,
            peak=20000.0,
            pattern=pattern,
        )
        rgb_sp = debayer_superpixel(cfa, pattern=pattern)
        rgb_mv = debayer_malvar2004(cfa, pattern=pattern)

        cy_sp, cx_sp = 31.5 / 2, 31.5 / 2
        cy_mv, cx_mv = 31.5, 31.5
        r_sp = 5.0
        r_mv = 10.0

        total_sp = _circular_aperture_sum(
            rgb_sp.sum(axis=-1), cy_sp, cx_sp, r_sp
        )
        total_mv = _circular_aperture_sum(
            rgb_mv.sum(axis=-1), cy_mv, cx_mv, r_mv
        )
        # Superpixel output pixels cover 4 input pixels each; scale sum to
        # input-pixel-equivalent flux for a fair comparison.
        total_sp_input_units = total_sp * 4.0
        diff = abs(total_sp_input_units - total_mv) / max(total_mv, 1.0)
        assert diff < 0.02, (
            f"flux difference superpixel vs malvar: {diff:.3%}"
        )

    def test_moire_superpixel_grid_no_strong_periodic_artifact(self):
        """Moire/60px-Raster: FFT zeigt keinen starken Peak am Superpixel-Grid."""
        h, w = 120, 120
        y, x = np.ogrid[:h, :w]
        # Sinusoidal pattern with 60px period (horizontal + vertical)
        period = 60.0
        pattern = np.sin(2.0 * np.pi * y / period) + np.sin(
            2.0 * np.pi * x / period
        )
        pattern = (pattern - pattern.min()) / (pattern.max() - pattern.min())
        pattern = (pattern * 10000.0 + 1000.0).astype(np.float32)

        cfa = _rgb_to_bayer(
            np.stack([pattern, pattern, pattern], axis=-1), pattern="RGGB"
        )

        rgb_sp = debayer_superpixel(cfa, pattern="RGGB")
        # Use green channel (most stable) for FFT
        mono_sp = rgb_sp[:, :, 1]

        # The 60px input period becomes 30px after 2x superpixel downscale.
        signal_peak = _fft_peak_at_period(mono_sp, period_px=30.0, direction="both")
        # A strong period-2 peak would indicate Bayer-phase aliasing / moire.
        artifact_peak = _fft_peak_at_period(mono_sp, period_px=2.0, direction="both")
        assert artifact_peak < 0.5 * signal_peak, (
            f"superpixel moire peak {artifact_peak:.1f} not small vs "
            f"signal {signal_peak:.1f}"
        )

    def test_moire_malvar_bilinear_no_strong_periodic_artifact(self):
        """bilinear/malvar erzeugen ebenfalls keinen starken 2px-Grid-Peak."""
        h, w = 120, 120
        y, x = np.ogrid[:h, :w]
        period = 60.0
        pattern = np.sin(2.0 * np.pi * y / period) + np.sin(
            2.0 * np.pi * x / period
        )
        pattern = (pattern - pattern.min()) / (pattern.max() - pattern.min())
        pattern = (pattern * 10000.0 + 1000.0).astype(np.float32)
        cfa = _rgb_to_bayer(
            np.stack([pattern, pattern, pattern], axis=-1), pattern="RGGB"
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            rgb_bi = debayer_bilinear(cfa, pattern="RGGB")
        rgb_mv = debayer_malvar2004(cfa, pattern="RGGB")

        peak_bi = _fft_peak_at_period(
            rgb_bi[:, :, 1], period_px=2.0, direction="both"
        )
        peak_mv = _fft_peak_at_period(
            rgb_mv[:, :, 1], period_px=2.0, direction="both"
        )
        # Full-resolution methods should not produce a strong Nyquist/period-2
        # peak from a smooth 60px pattern. Threshold chosen well above numeric
        # noise but below any real aliasing artifact.
        assert peak_bi < 1e6, (
            f"bilinear moire peak unexpectedly high: {peak_bi:.1f}"
        )
        assert peak_mv < 1e6, (
            f"malvar moire peak unexpectedly high: {peak_mv:.1f}"
        )


# ── AC-DEB-C: M92 visuell (dokumentiert, nicht CI-blocking) ──────────────


class TestM92VisualDocumentation:
    """AC-DEB-C1/C2: M92 Erwartungsmatrix als dokumentierter Platzhalter."""

    @pytest.mark.skip(
        reason=(
            "M92 manuell visuell, siehe Spec AC-DEB-C; "
            "Baseline-FWHM notiert in Spec; kein Auto-Fail"
        )
    )
    def test_m92_superpixel_baseline_fwhm(self):
        """AC-DEB-C1: M92 superpixel Stack FWHM (Baseline).

        Erwartungsmatrix:
        - Target: M92 (41x 60s @ Astro)
        - Debayer: superpixel (Default)
        - Baseline FWHM: ~3.5--5.0 px am gestackten Output (zu verifizieren)
        - Akzeptanz: Sterne rund/kompakt, kein 60px-Raster
        """
        pass

    @pytest.mark.skip(
        reason=(
            "M92 manuell visuell, siehe Spec AC-DEB-C; "
            "Vergleich superpixel vs bilinear/malvar; kein Auto-Fail"
        )
    )
    def test_m92_bilinear_malvar_visual_comparison(self):
        """AC-DEB-C2: Bilinear/Malvar visuell gegen Superpixel vergleichen.

        Erwartungsmatrix:
        - superpixel: photometrisch erhalten, keine Interpolationsartefakte
        - bilinear: volle Aufloesung, aber Farbsaeume/Moire moeglich
        - malvar: volle Aufloesung, kantenerhaltend, weniger Farbsaeume
        - Akzeptanz: subjektiv vergleichbare FWHM, keine massiven Farbsaeume
        """
        pass
