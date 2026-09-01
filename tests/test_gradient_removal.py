"""GR-A Kern-Modul Tests (AC-GR-A1..A6) — core/gradient_removal.py.

Dokumentierte Toleranzen (kalibriert 2026-08-04, Sprint-2-Etappe-1,
fester Seed — OQ-QF-6-A: nach erstem gruenem Lauf eingefroren):

- AC-GR-A1: Sampling + Sigma-Clipping + 2D-Polynom-Fit + Subtraktion
  (nur numpy/scipy); Modell-Felder fuellen das GR-E-Report-Schema.
- AC-GR-A2 (Sterne bleiben erhalten): Stern-Signal (5-sigma-Apertur
  ueber dem wahren Hintergrund) nach Removal im Bereich
  **[0.95, 1.10]** des Signals vorher; Rest-Gradient
  |modell - wahrer_Hintergrund| < **2.0 ADU** (< 6% des injizierten
  Niveaus von bis zu ~35 ADU). Der Background selbst wird durch die
  ``np.maximum(result, 0)``-Konvention auf ~0 gesetzt (Siril-
  AutoGradientRemoval-aequivalent; kein negativer Artefakt).
- AC-GR-A3 (Determinismus): gleiche Eingabe -> byte-identisches
  Ergebnis (image + Koeffizienten).
- AC-GR-A4 (E1, keine stillen Fehler): bei zu wenigen Sample-Punkten
  wirft das Modul :class:`GradientRemovalError` (Aufrufer skippt mit
  Warning); falsche Shapes -> ValueError.
- AC-GR-A5 (Galaxien-Halo, M31-artig): Flux-Erhalt der Quelle
  **>= 0.90** (1-sigma-Region) bzw. **>= 0.85** (2-sigma-Region);
  Rest-Gradient ausserhalb < 2.0 ADU.
- AC-GR-A6 (Nebulositaet vs. Gradient): Flux-Erhalt der
  Emissionsregion **>= 0.85** (1-sigma) bzw. **>= 0.80** (2-sigma).
- OQ-GR-2 (Mono-Fit, kanalweise Subtraktion): Kanal-Skalierungsfaktor
  nahe dem Kanal-Median-Verhaeltnis; Farbverhaeltnisse bleiben.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from astro_process.core.gradient_removal import (
    GradientModel,
    GradientRemovalError,
    fit_background,
    remove_gradient,
)

try:
    import astropy.io.fits as fits
    import synthetic
except ImportError:  # pragma: no cover - tests run from repo root
    synthetic = None  # type: ignore[assignment]
    fits = None  # type: ignore[assignment]

SHAPE = (256, 256)
GRAD = (0.0, 20.0, -10.0, 15.0, 5.0, -20.0)  # degree-2, peak ~35 ADU
# Positiv auf ganz [-1,1]^2 (min ~4.5, peak ~34) — tests/synthetic
# clippt den Gradient auf >= 0, deshalb darf der injizierte Gradient
# nirgends negativ werden, sonst weicht bg_truth vom Bild ab.
GRAD_GEN = (10.0, 8.0, 6.0, 4.0, 2.0, 3.0)

# Dokumentierte AC-GR-A2-Toleranzen.
STAR_SIGNAL_MIN = 0.95
STAR_SIGNAL_MAX = 1.10
RESIDUAL_GRADIENT_MAX = 2.0

# Dokumentierte AC-GR-A5/A6-Toleranzen.
GALAXY_FLUX_MIN_1SIG = 0.90
GALAXY_FLUX_MIN_2SIG = 0.85
NEBULA_FLUX_MIN_1SIG = 0.85
NEBULA_FLUX_MIN_2SIG = 0.80


def _poly2d_img(shape: tuple[int, int], coeffs: tuple[float, ...]) -> np.ndarray:
    """Evaluate a degree-2 polynomial in normalized coords (QF-C parity)."""
    height, width = shape
    y, x = np.ogrid[:height, :width]
    u = (x - (width - 1) / 2) / (width / 2)
    v = (y - (height - 1) / 2) / (height / 2)
    result = np.zeros((height, width), dtype=np.float64)
    k = 0
    for deg in range(3):
        for i in range(deg, -1, -1):
            j = deg - i
            if k < len(coeffs):
                result = result + coeffs[k] * (u**i) * (v**j)
                k += 1
    return result


def _gauss(shape: tuple[int, int], cy: float, cx: float, amp: float, sig: float) -> np.ndarray:
    y, x = np.ogrid[: shape[0], : shape[1]]
    return amp * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2.0 * sig**2))


def _star_gradient_image(
    seed: int = 1234,
    *,
    stars: bool = True,
    galaxy: bool = False,
    nebula: bool = False,
    noise: float = 0.8,
) -> np.ndarray:
    """Background 100 + injected degree-2 gradient + optional sources."""
    img = np.full(SHAPE, 100.0) + _poly2d_img(SHAPE, GRAD)
    if stars:
        for cy, cx, amp, sig in [
            (60.0, 80.0, 40.0, 1.8),
            (100.0, 50.0, 60.0, 1.4),
            (150.0, 210.0, 30.0, 2.0),
            (200.0, 120.0, 50.0, 1.6),
            (90.0, 180.0, 45.0, 1.5),
            (170.0, 40.0, 35.0, 1.7),
        ]:
            img += _gauss(SHAPE, cy, cx, amp, sig)
    if galaxy:
        img += _gauss(SHAPE, 128.0, 128.0, 40.0, 28.0)
    if nebula:
        img += _gauss(SHAPE, 140.0, 90.0, 12.0, 34.0)
    rng = np.random.RandomState(seed)
    img += rng.normal(0, noise, SHAPE)
    return img


class TestGRA1SamplingFitSubtraction:
    """AC-GR-A1: Kern-API — Sampling + Clipping + Fit + Subtraktion."""

    def test_model_fields_and_background_removed(self) -> None:
        img = _star_gradient_image(stars=False, noise=0.8)
        res = remove_gradient(img, degree=2, grid=(32, 32))

        assert res.image.shape == SHAPE
        model = res.model
        assert isinstance(model, GradientModel)
        assert model.degree == 2
        assert model.grid == (32, 32)
        assert model.n_cells == 32 * 32
        assert model.coefficients.shape == (6,)
        assert model.n_samples > 500
        assert model.n_rejected >= 0
        assert model.n_iterations >= 1
        assert model.residual_mad >= 0.0

        # Konvention np.maximum(result, 0): Background ~ 0, flach.
        flat = res.image.ravel()
        assert np.median(flat) < 1.0
        assert 1.4826 * np.median(np.abs(flat - np.median(flat))) < 2.0

    def test_2d_and_3d_inputs(self) -> None:
        mono = _star_gradient_image(stars=False, noise=0.8)
        rgb = np.stack([mono * 0.95, mono, mono * 1.05], axis=-1)
        res2 = remove_gradient(mono, grid=(16, 16))
        res3 = remove_gradient(rgb, grid=(16, 16))
        assert res2.image.ndim == 2
        assert res3.image.ndim == 3
        assert res3.image.shape == rgb.shape


class TestGRA2StarsPreserved:
    """AC-GR-A2: Fit ignoriert Sterne — Positionen/Fluxe bleiben erhalten."""

    STARS = [
        (60.0, 80.0, 40.0, 1.8),
        (100.0, 50.0, 60.0, 1.4),
        (150.0, 210.0, 30.0, 2.0),
        (200.0, 120.0, 50.0, 1.6),
        (90.0, 180.0, 45.0, 1.5),
        (170.0, 40.0, 35.0, 1.7),
    ]

    def test_star_signals_preserved(self) -> None:
        img = _star_gradient_image(stars=True, noise=0.8)
        bg_truth = np.full(SHAPE, 100.0) + _poly2d_img(SHAPE, GRAD)
        res = remove_gradient(img, degree=2, grid=(32, 32))
        model = res.model

        # Sterne wurden nicht als Gradient modelliert: Rest-Gradient
        # ausserhalb der Stern-Aperturen klein (dokumentiert < 2 ADU).
        star_mask = np.zeros(SHAPE, dtype=bool)
        for cy, cx, _amp, sig in self.STARS:
            y, x = np.ogrid[: SHAPE[0], : SHAPE[1]]
            star_mask |= (y - cy) ** 2 + (x - cx) ** 2 < (8 * sig) ** 2
        bg_fit = model.evaluate(SHAPE)
        rest = np.abs(bg_fit - bg_truth)[~star_mask]
        assert rest.max() < RESIDUAL_GRADIENT_MAX

        # Stern-Signal (5-sigma-Apertur) bleibt innerhalb [0.95, 1.10].
        for cy, cx, _amp, sig in self.STARS:
            y, x = np.ogrid[: SHAPE[0], : SHAPE[1]]
            ap = (y - cy) ** 2 + (x - cx) ** 2 < (5 * sig) ** 2
            before = (img - bg_truth)[ap].sum()
            after = res.image[ap].sum()
            assert before > 0
            ratio = after / before
            assert STAR_SIGNAL_MIN <= ratio <= STAR_SIGNAL_MAX, (
                f"star at ({cy}, {cx}) signal ratio {ratio:.3f}"
            )


class TestGRA3Deterministic:
    """AC-GR-A3: gleiche Eingabe -> gleiches Ergebnis (kein RNG)."""

    def test_deterministic(self) -> None:
        img = _star_gradient_image(stars=True, noise=0.8)
        a = remove_gradient(img, degree=2, grid=(32, 32))
        b = remove_gradient(img, degree=2, grid=(32, 32))
        assert np.array_equal(a.image, b.image)
        assert np.array_equal(a.model.coefficients, b.model.coefficients)


class TestGRA4NoSilentErrors:
    """AC-GR-A4 (E1): Fehler -> Exception statt korruptem Modell."""

    def test_min_samples_error(self) -> None:
        img = _star_gradient_image(stars=False, noise=0.8)
        with pytest.raises(GradientRemovalError):
            # min_samples hoeher als Zellen des 2x2-Grids (4).
            fit_background(img, degree=2, grid=(2, 2), min_samples=10)

    def test_grid_too_coarse_for_degree(self) -> None:
        img = np.full((64, 64), 100.0)
        with pytest.raises(GradientRemovalError):
            remove_gradient(img, degree=2, grid=(2, 2))

    def test_invalid_inputs(self) -> None:
        with pytest.raises(ValueError, match="expects a 2D image"):
            fit_background(np.zeros((64, 64, 3)))  # 3D nicht fuer fit
        with pytest.raises(ValueError, match="degree must be"):
            fit_background(np.zeros((64, 64)), degree=-1)
        with pytest.raises(ValueError, match="grid must be"):
            fit_background(np.zeros((64, 64)), grid=(1, 1))


class TestGRA5GalaxyHalo:
    """AC-GR-A5: M31-artige weiche Quelle wird nicht als Gradient entfernt."""

    def test_galaxy_flux_preserved(self) -> None:
        img = _star_gradient_image(stars=False, galaxy=True, noise=0.8)
        bg_truth = np.full(SHAPE, 100.0) + _poly2d_img(SHAPE, GRAD)
        res = remove_gradient(img, degree=2, grid=(32, 32))
        model = res.model

        y, x = np.ogrid[: SHAPE[0], : SHAPE[1]]
        source = img - bg_truth
        for radius_mult, min_flux in [
            (1.0, GALAXY_FLUX_MIN_1SIG),
            (2.0, GALAXY_FLUX_MIN_2SIG),
        ]:
            region = (y - 128.0) ** 2 + (x - 128.0) ** 2 < (radius_mult * 28.0) ** 2
            before = source[region].sum()
            after = res.image[region].sum()
            assert before > 0
            ratio = after / before
            assert ratio >= min_flux, (
                f"galaxy {radius_mult}sigma flux ratio {ratio:.3f} < {min_flux}"
            )

        # Der echte Gradient wurde trotzdem entfernt.
        outside = ~((y - 128.0) ** 2 + (x - 128.0) ** 2 < (2.0 * 28.0) ** 2)
        rest = np.abs(model.evaluate(SHAPE) - bg_truth)[outside]
        assert rest.max() < RESIDUAL_GRADIENT_MAX


class TestGRA6Nebula:
    """AC-GR-A6: Emissionsregion (Nebel) wird nicht als Gradient entfernt."""

    def test_nebula_flux_preserved(self) -> None:
        img = _star_gradient_image(stars=False, nebula=True, noise=0.8)
        bg_truth = np.full(SHAPE, 100.0) + _poly2d_img(SHAPE, GRAD)
        res = remove_gradient(img, degree=2, grid=(32, 32))
        model = res.model

        y, x = np.ogrid[: SHAPE[0], : SHAPE[1]]
        source = img - bg_truth
        for radius_mult, min_flux in [
            (1.0, NEBULA_FLUX_MIN_1SIG),
            (2.0, NEBULA_FLUX_MIN_2SIG),
        ]:
            region = (y - 140.0) ** 2 + (x - 90.0) ** 2 < (radius_mult * 34.0) ** 2
            before = source[region].sum()
            after = res.image[region].sum()
            assert before > 0
            ratio = after / before
            assert ratio >= min_flux, (
                f"nebula {radius_mult}sigma flux ratio {ratio:.3f} < {min_flux}"
            )

        outside = ~((y - 140.0) ** 2 + (x - 90.0) ** 2 < (2.0 * 34.0) ** 2)
        rest = np.abs(model.evaluate(SHAPE) - bg_truth)[outside]
        assert rest.max() < RESIDUAL_GRADIENT_MAX


class TestGRChannelScaling:
    """OQ-GR-2: Mono-Fit, kanalweise Subtraktion erhaelt Farbverhaeltnisse."""

    def test_rgb_channel_scales(self) -> None:
        mono = _star_gradient_image(stars=False, noise=0.8)
        factors = [0.95, 1.0, 1.05]
        rgb = np.stack([mono * f for f in factors], axis=-1)
        res = remove_gradient(rgb, degree=2, grid=(16, 16))

        assert len(res.channel_scales) == 3
        for scale, factor in zip(res.channel_scales, factors, strict=True):
            assert scale == pytest.approx(factor, abs=0.02)

        # Farbverhaeltnisse bleiben: Kanal-Mittel-Ratios nachher ~ vorher.
        before = [float(np.median(rgb[..., c])) for c in range(3)]
        after = [float(np.median(res.image[..., c])) for c in range(3)]
        for c in range(3):
            assert after[c] / after[1] == pytest.approx(before[c] / before[1], abs=0.02)


class TestGRSyntheticIntegration:
    """AC-GR-A2 + QF-C: injizierter Gradient (tests/synthetic) wird reduziert."""

    def test_generated_gradient_removed(self, tmp_path: Path) -> None:
        pytest.importorskip("synthetic")
        scene = synthetic.generate_scene(
            tmp_path / "gr_scene",
            n_lights_per_group=1,
            exposures=(15,),
            gains=(40,),
            size=(128, 128),
            channels=1,
            seed=42,
            noise=0.004,
            gradient=GRAD_GEN,
            star_count=8,
            star_flux_range=(30.0, 120.0),
        )
        frame = fits.getdata(scene.dataset.group_map["15s40"][0]).astype(np.float64)
        bg_truth = np.full(frame.shape, 100.0) + _poly2d_img(frame.shape, GRAD_GEN)
        res = remove_gradient(frame, degree=2, grid=(16, 16))

        rest = np.abs(res.model.evaluate(frame.shape) - bg_truth)
        # Injektion identisch modellierbar -> Rest deutlich unter 2 ADU.
        assert rest.max() < RESIDUAL_GRADIENT_MAX
