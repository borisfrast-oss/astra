"""Tests for the QF-C generator injection (S1-A4).

Verifies the extended synthetic generator end to end:

- AC-QF-C1: explicit defaults reproduce the legacy byte-identical output
  and existing calls keep returning :class:`SyntheticDataset`.
- AC-QF-C2: gradient / shift / rotation / noise / hot-pixel / cosmic-ray
  injection is fully seed-deterministic.
- AC-QF-C3: the ground-truth scene API returns the injected parameters
  (shift / rotation / gradient coefficients / ...).
- AC-QF-C4 + AC-W9-C7: the M13 analog (81-119 point sources > 12*MAD per
  frame, 4 groups, translation + rotation) and the M27 analog
  (FILTER="Duo-Band", nebula structure, translation) are part of the suite
  and deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from scipy import ndimage

# ── Ensure the generator module is importable (same layout as T4) ──
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import synthetic

SIZE = (64, 64)
SAME_SEED = 42


def _read_data(path: Path) -> np.ndarray:
    """Read FITS data array from a file."""
    with fits.open(path) as hdul:
        return hdul[0].data


class TestLegacyBehavior:
    """AC-QF-C1: existing calls / defaults unchanged."""

    def test_plain_call_returns_synthetic_dataset(self, tmp_path: Path):
        dataset = synthetic.generate_dataset(tmp_path, size=SIZE)
        assert isinstance(dataset, synthetic.SyntheticDataset)
        assert dataset.lights
        assert dataset.group_map
        assert dataset.group_keys

    def test_explicit_defaults_are_byte_identical(self, tmp_path: Path):
        """All new parameters at their defaults == plain legacy call."""
        plain = synthetic.generate_dataset(tmp_path / "plain", size=SIZE, seed=7)
        explicit = synthetic.generate_dataset(
            tmp_path / "explicit",
            size=SIZE,
            seed=7,
            gradient=(),
            shifts=None,
            rotation_deg=None,
            noise_scale=1.0,
            hot_pixels=0,
            cosmic_rays=0,
            star_count=5,
            star_flux_range=(2.0, 6.0),
            filter_name=None,
            object_name=synthetic.DEFAULT_TARGET,
        )
        assert plain.lights
        assert explicit.lights
        for p1, p2 in zip(plain.lights, explicit.lights, strict=True):
            assert p1.read_bytes() == p2.read_bytes()

    def test_shift_length_mismatch_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="shifts length"):
            synthetic.generate_dataset(
                tmp_path, size=SIZE, n_lights_per_group=2, shifts=((0.0, 0.0),)
            )

    def test_rotation_length_mismatch_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="rotation_deg length"):
            synthetic.generate_dataset(
                tmp_path, size=SIZE, n_lights_per_group=2, rotation_deg=(0.0,)
            )


class TestInjectionGroundTruth:
    """AC-QF-C2/C3: injected parameters returned and applied."""

    def test_shift_injection_and_recovery(self, tmp_path: Path):
        shifts = ((0.0, 0.0), (1.5, -2.5))
        scene = synthetic.generate_scene(
            tmp_path,
            n_lights_per_group=2,
            exposures=(15,),
            gains=(60,),
            size=SIZE,
            channels=1,
            seed=SAME_SEED,
            noise=0.003,
            star_count=10,
            star_flux_range=(10.0, 20.0),
            shifts=shifts,
        )
        # Ground-truth API (AC-QF-C3).
        assert scene.shifts == shifts
        assert scene.group_shifts("15s60") == list(shifts)

        f0 = _read_data(scene.dataset.lights[0]).astype(np.float64)
        f1 = _read_data(scene.dataset.lights[1]).astype(np.float64)
        assert not np.array_equal(f0, f1)

        # Undoing the injected shift must re-align the frames: the crop
        # excludes the cval-0 border, the Pearson correlation of the
        # corrected frame must beat the uncorrected one by a clear margin.
        sy, sx = shifts[1]
        corrected = ndimage.shift(
            f1, shift=(-sy, -sx), order=1, mode="constant", cval=0.0
        )
        crop = np.s_[10:-10, 10:-10]
        corr_corrected = float(
            np.corrcoef(corrected[crop].ravel(), f0[crop].ravel())[0, 1]
        )
        corr_uncorrected = float(
            np.corrcoef(f1[crop].ravel(), f0[crop].ravel())[0, 1]
        )
        assert corr_corrected > corr_uncorrected + 0.03

    def test_rotation_injection_and_recovery(self, tmp_path: Path):
        rotation_deg = (0.0, 2.0)
        scene = synthetic.generate_scene(
            tmp_path,
            n_lights_per_group=2,
            exposures=(15,),
            gains=(60,),
            size=(128, 128),
            channels=1,
            seed=SAME_SEED,
            noise=0.003,
            star_count=12,
            star_flux_range=(10.0, 20.0),
            rotation_deg=rotation_deg,
        )
        assert scene.rotation_deg == rotation_deg
        assert scene.group_rotation_deg("15s60") == list(rotation_deg)

        f0 = _read_data(scene.dataset.lights[0]).astype(np.float64)
        f1 = _read_data(scene.dataset.lights[1]).astype(np.float64)
        assert not np.array_equal(f0, f1)

        corrected = ndimage.rotate(
            f1, angle=-rotation_deg[1], reshape=False, order=1,
            mode="constant", cval=0.0, prefilter=False,
        )
        crop = np.s_[20:-20, 20:-20]
        corr_corrected = float(
            np.corrcoef(corrected[crop].ravel(), f0[crop].ravel())[0, 1]
        )
        corr_uncorrected = float(
            np.corrcoef(f1[crop].ravel(), f0[crop].ravel())[0, 1]
        )
        assert corr_corrected > corr_uncorrected + 0.03

    def test_gradient_ground_truth(self, tmp_path: Path):
        gradient = (5.0, 1.0, -2.0)  # 5 + u - 2v in normalized coords
        scene = synthetic.generate_scene(
            tmp_path,
            n_lights_per_group=1,
            exposures=(15,),
            gains=(60,),
            size=SIZE,
            channels=1,
            seed=SAME_SEED,
            gradient=gradient,
        )
        assert scene.gradient == gradient
        img = _read_data(scene.dataset.lights[0]).astype(np.float64)
        # Corner (0,0): u = v = -1 -> gradient 5 - 1 + 2 = 6; background
        # 100 + even-row modulation 0.5 = 106.5 (stars stay in the central
        # quarter so the corner is star-free).
        assert abs(img[0, 0] - 106.5) < 2.5

    def test_noise_scale_changes_level(self, tmp_path: Path):
        quiet = synthetic.generate_scene(
            tmp_path / "q", n_lights_per_group=1, exposures=(15,), gains=(60,),
            size=SIZE, channels=1, seed=SAME_SEED, noise_scale=1.0,
        )
        loud = synthetic.generate_scene(
            tmp_path / "l", n_lights_per_group=1, exposures=(15,), gains=(60,),
            size=SIZE, channels=1, seed=SAME_SEED, noise_scale=4.0,
        )
        assert loud.noise_scale == 4.0
        corner = np.s_[0:8, 0:8]
        std_q = float(np.std(_read_data(quiet.dataset.lights[0])[corner]))
        std_l = float(np.std(_read_data(loud.dataset.lights[0])[corner]))
        assert std_l > 2.0 * std_q

    def test_hot_pixels_injected(self, tmp_path: Path):
        scene = synthetic.generate_scene(
            tmp_path, n_lights_per_group=1, exposures=(15,), gains=(60,),
            size=SIZE, channels=1, seed=SAME_SEED, hot_pixels=10,
        )
        assert scene.hot_pixels == 10
        img = _read_data(scene.dataset.lights[0])
        assert (img > 50000).sum() == 10

    def test_cosmic_rays_injected(self, tmp_path: Path):
        scene = synthetic.generate_scene(
            tmp_path, n_lights_per_group=1, exposures=(15,), gains=(60,),
            size=SIZE, channels=1, seed=SAME_SEED, cosmic_rays=5,
        )
        assert scene.cosmic_rays == 5
        img = _read_data(scene.dataset.lights[0])
        # Every ray's first pixel carries >= 200 ADU on top of background.
        assert (img > 150).sum() >= 5

    def test_star_count_and_flux_range(self, tmp_path: Path):
        scene = synthetic.generate_scene(
            tmp_path, n_lights_per_group=1, exposures=(15,), gains=(60,),
            size=SIZE, channels=1, seed=SAME_SEED,
            star_count=12, star_flux_range=(8.0, 12.0),
        )
        assert scene.star_count == 12
        assert scene.star_flux_range == (8.0, 12.0)
        img = _read_data(scene.dataset.lights[0])
        # Each star's center is background 100 + amp >= 8 (+0.5 even row).
        assert (img > 105.0).sum() >= 12

    def test_injection_seed_determinism(self, tmp_path: Path):
        """AC-QF-C2: same seed -> byte-identical injection output."""
        kwargs = dict(
            n_lights_per_group=2,
            exposures=(15, 60),
            gains=(60,),
            size=SIZE,
            channels=1,
            seed=SAME_SEED,
            noise=0.01,
            gradient=(3.0, 1.0, -1.0, -0.5),
            shifts=((0.0, 0.0), (1.2, -0.8)),
            rotation_deg=(0.0, 0.4),
            noise_scale=2.0,
            hot_pixels=4,
            cosmic_rays=2,
            star_count=8,
            star_flux_range=(5.0, 10.0),
            filter_name="Duo-Band",
        )
        a = synthetic.generate_scene(tmp_path / "a", **kwargs)
        b = synthetic.generate_scene(tmp_path / "b", **kwargs)
        assert a.dataset.lights
        assert b.dataset.lights
        for p1, p2 in zip(a.dataset.lights, b.dataset.lights, strict=True):
            assert p1.read_bytes() == p2.read_bytes()


class TestM13Analog:
    """AC-QF-C4 + AC-W9-C7: crowded-field analog."""

    def test_density_and_ground_truth(self, tmp_path: Path):
        scene = synthetic.generate_m13_analog(tmp_path, seed=SAME_SEED)

        # 4 groups with mixed exposures/gains.
        assert scene.dataset.group_keys == ["15s40", "15s60", "60s40", "60s60"]
        assert len(scene.dataset.lights) == 4 * 4

        # Ground truth: frame 0 is the reference, per-frame motion after it.
        assert scene.shifts == ((0.0, 0.0), (1.3, -2.1), (-0.8, 1.6), (2.1, 0.4))
        assert scene.rotation_deg == (0.0, 0.3, -0.25, 0.12)
        # S1-A9: 120 sources full-frame (consistent star field for star-based
        # registration); S1-A4 used 108 central sources.
        assert scene.star_count == 120

        # Density reference (stella diagnose): every frame yields 81-119
        # point sources > 12*MAD above the median.
        for paths in scene.dataset.group_map.values():
            for path in paths:
                img = _read_data(path)
                med = np.median(img)
                mad = np.median(np.abs(img - med))
                sources = ndimage.label(img > med + 12.0 * mad)[1]
                assert 81 <= sources <= 119, f"{path.name}: {sources} sources"

    def test_same_seed_is_byte_identical(self, tmp_path: Path):
        a = synthetic.generate_m13_analog(tmp_path / "a", seed=SAME_SEED)
        b = synthetic.generate_m13_analog(tmp_path / "b", seed=SAME_SEED)
        for p1, p2 in zip(a.dataset.lights, b.dataset.lights, strict=True):
            assert p1.read_bytes() == p2.read_bytes()


class TestM27Analog:
    """AC-QF-C4: Duo-Band nebula analog (S1-A1 metadata convention)."""

    def test_duo_band_metadata_and_structure(self, tmp_path: Path):
        scene = synthetic.generate_m27_analog(tmp_path, seed=SAME_SEED)

        assert scene.dataset.group_keys == ["30s40_Duo-Band"]
        assert scene.filter_name == "Duo-Band"
        assert scene.object_name == "M 27"

        img = _read_data(scene.dataset.lights[0]).astype(np.float64)
        with fits.open(scene.dataset.lights[0]) as hdul:
            header = hdul[0].header
            assert header["FILTER"] == "Duo-Band"
            assert header["OBJECT"] == "M 27"
            assert header["EXPTIME"] == 30.0
            assert header["GAIN"] == 40

        # Ground truth: translation only, frame 0 is the reference.
        assert scene.shifts == ((0.0, 0.0), (1.8, -0.7), (-1.2, 1.4), (0.5, -2.0))
        assert scene.rotation_deg == ()

        # Nebula structure: a soft emission region adds light over a
        # substantial area (gradient clipped at 0, corners stay at the
        # flat background ~100.5 with even-row modulation).
        assert 15.0 < (img > 108.0).mean() * 100.0 < 60.0
        assert np.percentile(img, 99.5) > 110.0
        assert abs(img[0, 0] - 100.5) < 2.5

    def test_same_seed_is_byte_identical(self, tmp_path: Path):
        a = synthetic.generate_m27_analog(tmp_path / "a", seed=SAME_SEED)
        b = synthetic.generate_m27_analog(tmp_path / "b", seed=SAME_SEED)
        for p1, p2 in zip(a.dataset.lights, b.dataset.lights, strict=True):
            assert p1.read_bytes() == p2.read_bytes()
