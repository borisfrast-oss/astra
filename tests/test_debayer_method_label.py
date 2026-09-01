"""Tests: Debayer-Methoden-Label im agent-log (Fix 2026-08-21).

Log-Oddität Lauf 171059: agent-log sagte `method: superpixel_rggb`,
Output hatte aber volle Auflösung (3×1080×1920 statt 540×960) — real lief
bilinear (V1.6-2). Root-Cause: archive.py hardcodete das Label;
DebayerResult trug die Methode nicht. Fix: Methode ins Ergebnis, Label
ehrlich ausweisen ("<method>_rggb", Legacy → "unknown").
"""

from __future__ import annotations

import sys
import yaml
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import warnings

import numpy as np
import pytest

from astro_process.agents.debayer_agent import DebayerAgent
from astro_process.config.models import AppConfig, ProcessingParams
from astro_process.core.debayer import debayer_bilinear, debayer_fits, debayer_malvar2004
from astro_process.core.equipment import resolve_debayer_factor
from astro_process.config.loader import resolve_stack_scale_factor


def _context_with_one_light(tmp_path: Path):
    import numpy as np
    from astropy.io import fits as afits
    from astro_process.models.core import ObservationContext, ObservationTarget

    light = tmp_path / "light.fits"
    # 4x4 CFA (RGGB), gerade Dimensionen fuer Superpixel.
    afits.PrimaryHDU(np.ones((4, 4), dtype=np.uint16)).writeto(light)

    return ObservationContext(
        target=ObservationTarget(name="TestTarget"),
        source_path=tmp_path,
    )


class TestDebayerResultCarriesMethod:
    """DebayerResult.method reflektiert die aufgeloeste Methode."""

    def test_default_superpixel(self, tmp_path: Path):
        context = _context_with_one_light(tmp_path)
        cal = SimpleNamespace(
            working_dir=tmp_path, calibrated_lights=[next(tmp_path.glob("light.fits"))]
        )
        result = DebayerAgent(working_dir=tmp_path / "working").run(context, cal)
        assert result.method == "superpixel"

    def test_override_bilinear(self, tmp_path: Path):
        context = _context_with_one_light(tmp_path)
        cal = SimpleNamespace(
            working_dir=tmp_path, calibrated_lights=[next(tmp_path.glob("light.fits"))]
        )
        agent = DebayerAgent(working_dir=tmp_path / "working",
                             debayer_method_override="bilinear")
        result = agent.run(context, cal)
        assert result.method == "bilinear"


class TestArchiveDebayerMethodLabel:
    """agent-log.yaml debayer.method stammt aus DebayerResult (nicht hardcodet)."""

    @staticmethod
    def _write_agent_log(tmp_path: Path, debayer_result) -> dict:
        from astro_process.agents.archive import ArchiveAgent

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="M92",
                target_type=SimpleNamespace(value="globular_cluster"),
            ),
            total_integration_time=60.0,
            total_light_frames=1,
            calibration=SimpleNamespace(dark_count=0, flat_count=0, bias_count=0),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits"],
        )
        proc_result = SimpleNamespace(
            registered_frames=[],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
            gradient_removal=None,
            registration_metrics=None,
            pcc_status=None,
        )
        agent = ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            debayer_result=debayer_result,
        )
        return yaml.safe_load(log_path.read_text(encoding="utf-8"))

    def test_bilinear_run_labeled_bilinear(self, tmp_path: Path):
        """Bilinear-Lauf -> 'bilinear_rggb' (vorher faelschlich
        'superpixel_rggb')."""
        debayer_result = SimpleNamespace(
            debayered_frames=[Path("/tmp/deb_0000.fits")], method="bilinear",
        )
        log = self._write_agent_log(tmp_path, debayer_result)
        assert log["debayer"]["method"] == "bilinear_rggb"

    def test_superpixel_run_labeled_superpixel(self, tmp_path: Path):
        debayer_result = SimpleNamespace(
            debayered_frames=[Path("/tmp/deb_0000.fits")], method="superpixel",
        )
        log = self._write_agent_log(tmp_path, debayer_result)
        assert log["debayer"]["method"] == "superpixel_rggb"

    def test_legacy_result_without_method_unknown(self, tmp_path: Path):
        """Legacy-Ergebnis ohne method-Feld -> 'unknown' statt falscher
        superpixel-Behauptung."""
        debayer_result = SimpleNamespace(
            debayered_frames=[Path("/tmp/deb_0000.fits")],
        )
        log = self._write_agent_log(tmp_path, debayer_result)
        assert log["debayer"]["method"] == "unknown"

    def test_malvar_run_labeled_malvar(self, tmp_path: Path):
        debayer_result = SimpleNamespace(
            debayered_frames=[Path("/tmp/deb_0000.fits")], method="malvar",
        )
        log = self._write_agent_log(tmp_path, debayer_result)
        assert log["debayer"]["method"] == "malvar_rggb"


# V1.8-0 (MALVAR): zusaetzliche Tests fuer malvar + deprecation
class TestMalvarDebayer:
    """Malvar produziert volle Aufloesung, kein Downscale."""

    def test_malvar_produces_full_resolution(self):
        data = np.ones((10, 12), dtype=np.uint16) * 1000
        rgb = debayer_malvar2004(data)
        assert rgb.shape == (10, 12, 3)
        assert rgb.dtype == np.float32

    def test_malvar_no_color_fringe_constant_input(self):
        # Konstantes Bayer -> alle Kanaele aehnlich (keine Farbsaeume)
        data = np.full((6, 6), 1000, dtype=np.uint16)
        rgb = debayer_malvar2004(data)
        # Bei konstantem Input sollte max Abweichung zwischen Kanaelen gering sein
        assert np.allclose(rgb[:, :, 0], rgb[:, :, 1], atol=1e-3)
        assert np.allclose(rgb[:, :, 1], rgb[:, :, 2], atol=1e-3)

    def test_malvar_invalid_dimensions_raises(self):
        with pytest.raises(ValueError, match="at least 3x3"):
            debayer_malvar2004(np.ones((2, 6), dtype=np.uint16))

    def test_malvar_unsupported_pattern_raises(self):
        with pytest.raises(ValueError, match="Unsupported Bayer pattern"):
            debayer_malvar2004(np.ones((6, 6), dtype=np.uint16), pattern="XXXX")

    def test_stack_scale_factor_malvar_is_1(self):
        factor, source = resolve_debayer_factor(debayer_method="malvar")
        assert factor == 1.0
        assert source == "auto_data"
        # Loader-Delegation ebenfalls
        assert resolve_stack_scale_factor(debayer_method="malvar") == 1.0

    def test_debayer_fits_malvar_full_resolution(self, tmp_path: Path):
        from astropy.io import fits as afits

        data = (np.ones((6, 6), dtype=np.uint16) * 1000).astype(np.float32)
        inp = tmp_path / "in.fits"
        out = tmp_path / "out.fits"
        afits.PrimaryHDU(data).writeto(inp, overwrite=True)
        rgb = debayer_fits(inp, out, method="malvar")
        assert rgb.shape == (6, 6, 3)
        # FITS Output: (C, H, W) = (3, 6, 6)
        with afits.open(out) as hdul:
            assert hdul[0].data.shape == (3, 6, 6)


class TestBilinearDeprecation:
    def test_bilinear_shows_deprecation_warning(self):
        data = np.ones((6, 6), dtype=np.float32) * 100
        with pytest.warns(DeprecationWarning, match="deprecated"):
            debayer_bilinear(data)

    def test_debayer_fits_bilinear_warns(self, tmp_path: Path):
        from astropy.io import fits as afits

        data = np.ones((6, 6), dtype=np.float32)
        inp = tmp_path / "in.fits"
        out = tmp_path / "out.fits"
        afits.PrimaryHDU(data).writeto(inp, overwrite=True)
        with pytest.warns(DeprecationWarning, match="deprecated"):
            debayer_fits(inp, out, method="bilinear")


class TestConfigDefaultUnchanged:
    def test_processing_params_default_superpixel(self):
        assert ProcessingParams().debayer_method == "superpixel"

    def test_appconfig_default_none(self):
        assert AppConfig().debayer_method is None


class TestCliMalvarAccepted:
    def test_cli_help_contains_malvar(self):
        from click.testing import CliRunner
        from astro_process.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["process", "--help"])
        assert result.exit_code == 0
        assert "malvar" in result.output
        assert "superpixel" in result.output

    def test_cli_malvar_dry_run(self, tmp_path: Path):
        # Minimal Target mit lights/darks fuer dry-run
        from click.testing import CliRunner
        from astro_process.cli import cli
        import numpy as np
        from astropy.io import fits as afits

        # Erstelle minimales Target (lights + darks Struktur ist egal fuer --help path,
        # aber dry-run braucht echte Frames)
        light_dir = tmp_path / "lights"
        light_dir.mkdir(parents=True)
        # Dummy light
        for i in range(1):
            afits.PrimaryHDU(np.ones((4, 4), dtype=np.uint16)).writeto(light_dir / f"light_{i}.fits", overwrite=True)
        runner = CliRunner()
        # --help already tested; teste dass --debayer-method malvar akzeptiert wird (dry-run)
        result = runner.invoke(cli, ["process", str(tmp_path), "--debayer-method", "malvar", "--dry-run"])
        # Dry-run sollte nicht an fehlenden Darks scheitern bevor debayer-method validiert ist;
        # Wichtig ist dass kein "No such option" oder "invalid choice" Fehler kommt.
        # Bei fehlender Config/Discovery kann Exit 1 sein, aber nicht wegen falscher Choice.
        assert "invalid choice" not in result.output.lower()
        assert "No such option" not in result.output
