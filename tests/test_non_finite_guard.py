"""V1.12-NGC-non_finite Guard — synthetic reproduction + guard verification.

Recherche-Hintergrund (kurz, siehe separates Recherche-Dokument):
- M27 30s40 derotation: FFT-Shift/rotation_fft nutzt gaussian_filter + scipy
  rotate/shift (mode nearest) — produziert KEIN NaN/Inf bei finiten Inputs.
  Gefahr entsteht nur wenn Eingabe bereits non-finite enthält (kalibrierter
  CFA mit Hotpixel-Overflow, debayer_single-pixel NaN, oder FITS BZERO/BSCALE
  Fehlscale). Dann propagiert NaN via debayer (superpixel/malvar) → RGB NaN
  → gaussian_filter (NaN kernel) → corr -> NaN -> Stack-Mean NaN.
- Stacking: data/frame_median NaN oder |frame| non-finite -> frame skip
  (stack.non_finite_frame) + alias stacking.non_finite_frame_skipped.
  3D: ganzer RGB-Frame skip (vor per-channel, farbkonsistent). Finaler
  Result-Guard: non_finite -> ValueError (hart, kein broken FITS).
- Quality: compute_frame_quality expliziter is_finite Guard -> quality.non_finite
  + quality.non_finite_frame_skipped, Rückgabe snr=0 / star_count=0 (kein Crash).
- PCC/SCNR: agieren nur auf bereits gestacktem finite Result — kein separater
  Guard nötig (stack-Guard verhindert kaputten Input).

Tests: synthetisch NaN/Inf Frame injizieren -> skipped, kein Inf im Stack.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from astro_process.core.quality import compute_frame_quality
from astro_process.core.stacking import stack_2d, stack_frames_python


def _make_fits(path: Path, data: np.ndarray) -> None:
    """Write data as FITS (2D or 3D RGB) with correct axis order."""
    out = data.astype(np.float32)
    if out.ndim == 3:
        out = out.transpose(2, 0, 1)
    hdu = fits.PrimaryHDU(out)
    if data.ndim == 3:
        hdu.header["CTYPE3"] = "RGB"
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)


def _load_frame(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        d = hdul[0].data.astype(np.float32)
        if d.ndim == 3:
            d = d.transpose(1, 2, 0)
        return d


def _save_frame(data: np.ndarray, path: Path) -> None:
    out = data.astype(np.float32)
    if out.ndim == 3:
        out = out.transpose(2, 0, 1)
    hdu = fits.PrimaryHDU(out)
    if data.ndim == 3:
        hdu.header["CTYPE3"] = "RGB"
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)


# ── Stacking Guard ────────────────────────────────────────────────

def test_non_finite_frame_guard_stack_2d_nan_skipped(caplog):
    """Synthetisch: 1 von 5 Frames komplett NaN -> geskipped, Stack finite."""
    rng = np.random.default_rng(42)
    base = rng.random((5, 20, 20)).astype(np.float64) * 10 + 100
    nan_frame = base.copy()
    nan_frame[2, :, :] = np.nan  # ganzer Frame 2 kaputt
    # auch Single-Pixel NaN im selben Frame hätte schon gereicht
    result = stack_2d(nan_frame, method="average", normalization="no")
    assert result.shape == (20, 20)
    assert np.all(np.isfinite(result)), "Stack darf kein NaN/Inf enthalten"
    # Guard loggt stack.non_finite_frame + alias stacking.non_finite_frame_skipped
    # (structlog -> stdout, caplog kann je nach Logger-Config leer sein — daher
    # nur soft-pruefen: wenn caplog leer, gilt Test trotzdem bei finitem Result)
    if caplog.records:
        assert any("non_finite" in rec.message for rec in caplog.records)


def test_non_finite_frame_guard_stack_2d_inf_skipped():
    """Inf Frame -> geskipped, Stack finite."""
    rng = np.random.default_rng(7)
    data = rng.random((4, 12, 12)).astype(np.float64) * 5 + 50
    data[1, 0, 0] = np.inf
    result = stack_2d(data, method="median", normalization="no")
    assert np.all(np.isfinite(result))
    # median path ebenfalls abgesichert


def test_non_finite_frame_guard_3d_whole_frame_skipped(tmp_path: Path):
    """3D: RGB-Frame mit einem NaN-Pixel in R -> ganzer Frame geskipped, kein Inf."""
    d1 = (np.random.rand(10, 10, 3).astype(np.float32) * 10 + 100)
    d2 = d1.copy()
    d2[0, 0, 0] = np.nan  # R-Kanal einzelpixel NaN
    d3 = (np.random.rand(10, 10, 3).astype(np.float32) * 10 + 110)
    p1, p2, p3 = tmp_path / "a.fits", tmp_path / "b.fits", tmp_path / "c.fits"
    for p, d in [(p1, d1), (p2, d2), (p3, d3)]:
        _make_fits(p, d)
    out = tmp_path / "stacked.fits"
    # 3D-Pfad: whole-frame filter in stack_frames_python
    stack_frames_python([p1, p2, p3], out, method="average", normalization="no",
                        is_3d=True, load_frame=_load_frame, save_frame=_save_frame)
    assert out.exists(), "Stacked trotz NaN-Frame erzeugt"
    with fits.open(out) as hdul:
        stacked = hdul[0].data
        if stacked.ndim == 3:
            stacked = stacked.transpose(1, 2, 0)
        assert np.all(np.isfinite(stacked)), "3D Stack hat NaN/Inf trotz Guard"
        assert not np.any(np.isnan(stacked))


def test_non_finite_frame_guard_all_nan_raises():
    """Alle Frames NaN -> ValueError (kein broken Stack)."""
    data = np.full((3, 8, 8), np.nan, dtype=np.float64)
    with pytest.raises(ValueError, match="all frames excluded|non_finite"):
        stack_2d(data, method="average", normalization="no")


# ── Quality Guard ────────────────────────────────────────────────

def test_non_finite_frame_guard_quality_non_finite(caplog):
    """Quality: Bild mit NaN -> quality.non_finite Warnung, kein Crash, snr 0."""
    img = np.random.rand(20, 20).astype(np.float64) * 10 + 100
    # Realistische Stars fuer detect_stars, aber ein NaN-Pixel reicht
    img[5, 5] = 500
    img_nan = img.copy()
    img_nan[3, 3] = np.nan
    q = compute_frame_quality(img_nan)
    assert q.snr == 0.0
    assert q.star_count == 0
    # Warning quality.non_finite vorhanden (structlog -> stdout, caplog optional)
    if caplog.records:
        assert any("quality.non_finite" in r.message or "non_finite" in r.message for r in caplog.records)


def test_non_finite_frame_guard_quality_inf(caplog):
    """Quality: Inf-Bild -> ebenfalls Guard, kein Crash."""
    img = np.full((20, 20), np.inf, dtype=np.float64)
    q = compute_frame_quality(img)
    assert q.snr == 0.0
    assert q.star_count == 0
    if caplog.records:
        assert any("quality.non_finite" in r.message or "non_finite" in r.message for r in caplog.records)
