"""V1.12-SUGGESTED-ARCHIVE — suggested_used.* je Run (Reproduzierbarkeit).

Spec: process kopiert genutztes suggested-File nach generated/<ts>/suggested_used.*
(yaml/json) fuer Reproduzierbarkeit; kleiner Fix archive.py + 1 Test.
Aufbauend auf FU-2+FLIP+FORMAT+QC+ORGANIZE+GROUP-SELECT dirty.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _make_minimal_context(tmp_path: Path):
    from astro_process.models.core import AcquisitionInfo, CalibrationStatus, EquipmentInfo, ObservationContext, ObservationTarget

    target = ObservationTarget(name="TestTarget")
    ctx = ObservationContext(
        target=target,
        source_path=tmp_path,
        equipment=EquipmentInfo(),
        acquisition=AcquisitionInfo(),
        calibration=CalibrationStatus(),
    )
    return ctx


def _make_minimal_proc():
    from astro_process.agents.processing_agent import ProcessingResult

    return ProcessingResult(pcc_status=None, stacked=None, exports=[])


def _make_minimal_cal():
    from types import SimpleNamespace

    return SimpleNamespace(master_dark=None, calibrated_lights=[])


class TestSuggestedArchive:
    """V1.12-SUGGESTED-ARCHIVE: archive.py kopiert suggested.yaml/json je Run."""

    def test_suggested_archive_with_yaml(self, tmp_path):
        """Mit suggested.yaml -> Kopie vorhanden, Inhalt identisch, run-info geloggt."""
        from astro_process.agents.archive import ArchiveAgent

        # Quelle suggested.yaml
        src = tmp_path / "suggested.yaml"
        data = {
            "version": 1,
            "target": "M31",
            "preset": "galaxy_standard",
            "registration": {"method": "astroalign", "max_rotation_deg": 15.0},
            "debayer": {"method": "superpixel"},
            "pcc": {"enabled": True},
        }
        src.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        out = tmp_path / "out_yaml"
        out.mkdir(parents=True)

        ctx = _make_minimal_context(tmp_path)
        proc = _make_minimal_proc()
        cal = _make_minimal_cal()

        agent = ArchiveAgent(out, config=None)
        result = agent.run(ctx, proc, cal, suggested_path=src)

        # Kopie vorhanden
        dest = out / "suggested_used.yaml"
        assert dest.is_file(), "suggested_used.yaml should exist when source provided"
        assert result.suggested_used == dest
        # Inhalt identisch
        assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
        # run-info.json loggt Pfad
        run_info_path = out / "run-info.json"
        assert run_info_path.is_file()
        run_info = json.loads(run_info_path.read_text(encoding="utf-8"))
        assert "suggested_used" in run_info
        assert run_info["suggested_used"] is not None
        assert run_info["suggested_used"].endswith("suggested_used.yaml")
        # AgentResult Pfad stimmt mit run-info überein
        assert run_info["suggested_used"] == str(dest)

    def test_suggested_archive_with_json(self, tmp_path):
        """Mit suggested.json -> .json erhalten, Inhalt identisch."""
        from astro_process.agents.archive import ArchiveAgent

        src = tmp_path / "suggested.json"
        data = {"version": 1, "target": "M31", "preset": "star_standard"}
        src.write_text(json.dumps(data, indent=2), encoding="utf-8")

        out = tmp_path / "out_json"
        out.mkdir(parents=True)

        ctx = _make_minimal_context(tmp_path)
        proc = _make_minimal_proc()
        cal = _make_minimal_cal()

        agent = ArchiveAgent(out, config=None)
        result = agent.run(ctx, proc, cal, suggested_path=src)

        dest = out / "suggested_used.json"
        assert dest.is_file(), "suggested_used.json should exist for json source"
        assert result.suggested_used == dest
        assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
        run_info = json.loads((out / "run-info.json").read_text(encoding="utf-8"))
        assert run_info["suggested_used"] is not None
        assert run_info["suggested_used"].endswith("suggested_used.json")

    def test_suggested_archive_without_suggested(self, tmp_path):
        """Ohne suggested (None) -> kein File, kein Fehler, run-info null."""
        from astro_process.agents.archive import ArchiveAgent

        out = tmp_path / "out_none"
        out.mkdir(parents=True)

        ctx = _make_minimal_context(tmp_path)
        proc = _make_minimal_proc()
        cal = _make_minimal_cal()

        agent = ArchiveAgent(out, config=None)
        # Ohne suggested_path (None)
        result = agent.run(ctx, proc, cal, suggested_path=None)

        assert result.suggested_used is None
        assert not (out / "suggested_used.yaml").exists()
        assert not (out / "suggested_used.json").exists()
        run_info = json.loads((out / "run-info.json").read_text(encoding="utf-8"))
        assert run_info["suggested_used"] is None

        # Auch bei nicht-existierendem Pfad: skip ohne Fehler
        fake = tmp_path / "does_not_exist.yaml"
        result2 = agent.run(ctx, proc, cal, suggested_path=fake)
        assert result2.suggested_used is None
        # Kein Crash, run-info bleibt null
        run_info2 = json.loads((out / "run-info.json").read_text(encoding="utf-8"))
        assert run_info2["suggested_used"] is None

    def test_suggested_archive_via_cli_process(self, tmp_path):
        """CLI-Integration: astra process --from-suggested kopiert nach generated/<ts>."""
        from click.testing import CliRunner

        from astro_process.cli import cli
        from conftest import write_default_suggested

        # Minimal target with lights/group_* (ORG-X1)
        target = tmp_path / "M31 Andromeda"
        lights_group = target / "lights" / "group_15s60"
        lights_group.mkdir(parents=True)
        from test_multi_group import create_test_fits

        create_test_fits(lights_group / "light_0001.fits", exptime=15.0, gain=60, add_stars=True)

        suggested = write_default_suggested(target)

        runner = CliRunner()
        from unittest.mock import MagicMock, patch

        # Let discovery run REAL (so it finds the 1 light), mock only heavy phases
        with patch("astro_process.cli.create_calibration_agent") as mock_cal, \
             patch("astro_process.cli.create_cosmetic_agent") as mock_cos, \
             patch("astro_process.cli.create_debayer_agent") as mock_deb, \
             patch("astro_process.cli.create_processing_agent") as mock_proc:

            fake_cal_result = MagicMock()
            fake_cal_result.master_dark = None
            fake_cal_result.calibrated_lights = []
            mock_cal.return_value.run.return_value = fake_cal_result
            mock_cos.return_value.run.return_value = None

            fake_deb_result = MagicMock()
            fake_deb_result.debayered_frames = []
            fake_deb_result.method = "superpixel"
            fake_deb_result.stack_scale_factor = 2.0
            fake_deb_result.stack_scale_factor_source = "default"
            mock_deb.return_value.run.return_value = fake_deb_result

            fake_proc_result = MagicMock()
            fake_proc_result.stacked = None
            fake_proc_result.exports = []
            fake_proc_result.pcc_status = None
            fake_proc_result.frame_qualities = []
            fake_proc_result.stack_quality = {}
            fake_proc_result.registration_metrics = {}
            fake_proc_result.gradient_removal = {}
            fake_proc_result.preview_export = {}
            fake_proc_result.stretched_fits = None
            fake_proc_result.multi_group_metadata = None
            mock_proc.return_value.process_multi_group.return_value = fake_proc_result

            result = runner.invoke(
                cli,
                ["process", str(target), "--from-suggested", str(suggested)],
                catch_exceptions=False,
            )
            assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"

            generated = target / "generated"
            assert generated.exists()
            ts_dirs = sorted([d for d in generated.iterdir() if d.is_dir()])
            assert len(ts_dirs) >= 1
            latest = ts_dirs[-1]
            yaml_copy = latest / "suggested_used.yaml"
            json_copy = latest / "suggested_used.json"
            assert yaml_copy.exists() or json_copy.exists(), f"Neither yaml nor json copy found in {latest}, contents: {list(latest.iterdir())}"
            src_text = suggested.read_text(encoding="utf-8")
            if yaml_copy.exists():
                assert yaml_copy.read_text(encoding="utf-8") == src_text
                run_info = json.loads((latest / "run-info.json").read_text(encoding="utf-8"))
                assert run_info.get("suggested_used") is not None
                assert "suggested_used.yaml" in run_info["suggested_used"]
            else:
                assert json_copy.read_text(encoding="utf-8") == src_text
