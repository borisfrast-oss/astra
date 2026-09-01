"""Tests for the deterministic synthetic FITS generator (T4).

Verifies file layout, byte-level determinism, astra header conventions and
that the generated lights group exactly like real astra data
(``astro_process.models.core.FrameSet.group_by_params``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

# ── Ensure the generator module is importable (no conftest.py, T4) ──
sys.path.insert(0, str(Path(__file__).resolve().parent))
# ── Ensure src is on the path for the astro_process grouping smoke check ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import synthetic

from astro_process.core.fits_parser import build_observation_context

SIZE = (32, 32)
EXPECTED_DEFAULT_GROUPS = [
    (15.0, 60, "15s60"),
    (60.0, 60, "60s60"),
]


def _read_data(path: Path) -> np.ndarray:
    """Read FITS data array from a file."""
    with fits.open(path) as hdul:
        return hdul[0].data


class TestSyntheticGenerator:
    """T4: deterministic synthetic FITS generator."""

    def test_generate_dataset_creates_files(self, tmp_path: Path):
        """subdirs exist and file counts match astra conventions."""
        dataset = synthetic.generate_dataset(tmp_path, size=SIZE)

        assert (tmp_path / "lights").is_dir()
        assert (tmp_path / "darks").is_dir()
        assert (tmp_path / "flats").is_dir()
        assert (tmp_path / "bias").is_dir()

        n_groups = len(EXPECTED_DEFAULT_GROUPS)
        assert len(dataset.lights) == n_groups * 3
        assert len(dataset.darks) == n_groups
        assert len(dataset.flats) == 1
        assert len(dataset.bias) == 1

        for path in dataset.lights + dataset.darks + dataset.flats + dataset.bias:
            assert path.exists()
            assert path.suffix == ".fits"

    def test_deterministic_same_seed(self, tmp_path: Path):
        """same seed -> byte-identical light files."""
        ds1 = synthetic.generate_dataset(tmp_path / "a", size=SIZE, seed=42)
        ds2 = synthetic.generate_dataset(tmp_path / "b", size=SIZE, seed=42)

        assert ds1.lights
        assert ds2.lights
        for p1, p2 in zip(ds1.lights, ds2.lights, strict=True):
            assert p1.read_bytes() == p2.read_bytes()
            assert np.array_equal(_read_data(p1), _read_data(p2))

    def test_different_seed_differs(self, tmp_path: Path):
        """different seed -> files differ."""
        ds1 = synthetic.generate_dataset(tmp_path / "a", size=SIZE, seed=42)
        ds2 = synthetic.generate_dataset(tmp_path / "b", size=SIZE, seed=43)

        assert ds1.lights
        assert ds2.lights
        differing = sum(
            not np.array_equal(_read_data(p1), _read_data(p2))
            for p1, p2 in zip(ds1.lights, ds2.lights, strict=True)
        )
        assert differing > 0

    def test_headers_match_astra_conventions(self, tmp_path: Path):
        """lights carry the exact header keys astra groups on (EXPTIME/GAIN)."""
        dataset = synthetic.generate_dataset(
            tmp_path, exposures=(15, 60), gains=(60,), size=SIZE
        )

        for exptime, gain, key in EXPECTED_DEFAULT_GROUPS:
            paths = dataset.group_map[key]
            assert paths, f"no lights for group {key}"
            for path in paths:
                with fits.open(path) as hdul:
                    header = hdul[0].header
                    assert "EXPTIME" in header
                    assert "GAIN" in header
                    assert header["EXPTIME"] == exptime
                    assert header["GAIN"] == gain
                    # Extra keys the pipeline reads (fits_parser aliases).
                    assert "CCD-TEMP" in header
                    assert "OBJECT" in header
                    assert "DATE-OBS" in header

    def test_group_map_matches_grouping(self, tmp_path: Path):
        """group_map equals the astro_process grouping of generated lights."""
        exposures = (15, 60)
        gains = (60,)
        dataset = synthetic.generate_dataset(
            tmp_path, n_lights_per_group=3, exposures=exposures, gains=gains, size=SIZE
        )

        expected_keys = {
            synthetic.group_key(float(e), int(g)) for e in exposures for g in gains
        }
        assert set(dataset.group_map) == expected_keys
        assert all(len(paths) == 3 for paths in dataset.group_map.values())

        # Smoke check against the real astra grouping API.
        context = build_observation_context(tmp_path)
        groups = context.get_lights().group_by_params()
        astra_keys = {
            synthetic.group_key(float(exptime), int(gain))
            for exptime, gain, _filter in groups
        }
        assert astra_keys == expected_keys
        assert all(group.count == 3 for group in groups.values())

        # The paths astra discovered are exactly the ones in group_map.
        for (exptime, gain, _filter), frame_set in groups.items():
            key = synthetic.group_key(float(exptime), int(gain))
            astra_paths = sorted(frame.path.resolve() for frame in frame_set.frames)
            gen_paths = sorted(p.resolve() for p in dataset.group_map[key])
            assert astra_paths == gen_paths

    def test_group_key_format(self):
        """group_key matches astra's compute_group_hash format."""
        assert synthetic.group_key(15.0, 60) == "15s60"
        assert synthetic.group_key(60, 60) == "60s60"
        assert synthetic.group_key(60.0, 40, "Duo-Band") == "60s40_Duo-Band"
        assert synthetic.group_key(15.0, 60, "none") == "15s60"
