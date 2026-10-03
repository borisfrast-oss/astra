"""DEF-019: `process --preflight` muss Lights im ORG-X1-Group-Layout finden.

Regression: `_run_preflight_checks` nutzte flaches `glob("lights/*.fit*")`.
Nach V1.12-ORGANIZE liegen alle Lights in `lights/group_*/`, 0 Frames im
lights-Root -> faelschlich "No lights found (Abort)", obwohl
`organize --dry-run` READY meldet und die Pipeline (staging, group-aware)
die Frames sieht.

Faelle (synthetisch/deterministisch, keine Real-Daten):
  a) group-Layout (lights/group_*/ mit FITS, inkl. .FIT uppercase) -> kein Abort.
  b) flat-legacy (FITS direkt in lights/) -> weiterhin OK.
  c) leer (lights/ ohne FITS bzw. fehlendes lights/) -> Abort "No lights found".
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.cli import _run_preflight_checks  # noqa: E402
from astro_process.config import AppConfig  # noqa: E402


def _make_light_fits(path: Path, exptime: float = 15.0, gain: int = 60) -> Path:
    data = np.full((32, 32), 100.0, dtype=np.float32)
    hdu = fits.PrimaryHDU(data)
    hdu.header["EXPTIME"] = float(exptime)
    hdu.header["GAIN"] = int(gain)
    hdu.header["OBJECT"] = "TestTarget"
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def _make_cfg(tmp_path: Path) -> AppConfig:
    # Existierendes darks-Verzeichnis -> dark_ok True, Status spiegelt nur
    # die Light-Discovery wider (OK vs. Abort).
    darks = tmp_path / "_darks"
    darks.mkdir(parents=True, exist_ok=True)
    return AppConfig(darks_repository=darks)


class TestPreflightGroupDiscovery:
    """DEF-019: group-aware Light-Discovery im Preflight."""

    def test_group_layout_no_abort(self, tmp_path):
        """a) lights/group_15s60_astro/ mit FITS -> KEIN Abort."""
        target = tmp_path / "M57"
        group = target / "lights" / "group_15s60_astro"
        _make_light_fits(group / "light_0000.fits")
        _make_light_fits(group / "light_0001.fit")
        _make_light_fits(group / "light_0002.FIT")  # case-insensitiv (.FIT)

        result = _run_preflight_checks(target, _make_cfg(tmp_path))

        assert result["status"] != "Abort", f"Unerwarteter Abort: {result['checks']}"
        assert not any("No lights found" in c for c in result["checks"])
        assert result["status"] == "OK"

    def test_flat_legacy_still_ok(self, tmp_path):
        """b) flat-legacy: FITS direkt in lights/ -> weiterhin OK."""
        target = tmp_path / "M57flat"
        lights = target / "lights"
        for i in range(3):
            _make_light_fits(lights / f"light_{i:04d}.fits")

        result = _run_preflight_checks(target, _make_cfg(tmp_path))

        assert result["status"] == "OK", f"Flat-legacy brach: {result['checks']}"
        assert not any("No lights found" in c for c in result["checks"])

    def test_empty_lights_aborts(self, tmp_path):
        """c) leerer lights-Ordner -> Abort mit 'No lights found'."""
        target = tmp_path / "M57empty"
        (target / "lights").mkdir(parents=True, exist_ok=True)

        result = _run_preflight_checks(target, _make_cfg(tmp_path))

        assert result["status"] == "Abort"
        assert any("No lights found" in c for c in result["checks"])

    def test_missing_lights_dir_aborts(self, tmp_path):
        """c2) fehlender lights-Ordner -> Abort mit 'No lights found'."""
        target = tmp_path / "M57nolights"
        target.mkdir(parents=True, exist_ok=True)

        result = _run_preflight_checks(target, _make_cfg(tmp_path))

        assert result["status"] == "Abort"
        assert any("No lights found" in c for c in result["checks"])
