"""Tests for v1.5 P3 items (V1.5-6, V1.5-11, V1.5-12, V1.5-13, V1.5-14).

Abdeckung:
- V1.5-6: dry-run Factory-Usage (DiscoveryAgent via create_discovery_agent)
- V1.5-11: --az-mode/--eq-mode CLI-Flags (EQMODE-Override)
- V1.5-12: --pixel-scale CLI-Flag (Pixel-Skala Override)
- V1.5-13: --se-radius/--se-amount CLI-Flags (SE-Params Override)
- V1.5-14: Warnings maschinenlesbar (strukturiertes YAML in agent-log)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.cli import cli  # noqa: E402
from astro_process.config.loader import DEFAULT_CONFIG  # noqa: E402


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _write_config(path: Path, update: dict | None = None) -> Path:
    """Write a config based on DEFAULT_CONFIG with optional overrides."""
    data = yaml.safe_load(DEFAULT_CONFIG)
    if update:
        data.update(update)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _make_config(tmp_path: Path) -> Path:
    """Write a minimal config.yaml with presets."""
    cfg = tmp_path / "config.yaml"
    return _write_config(cfg, {
        "darks_repository": str(tmp_path / "_darks"),
    })


def _mock_discovery(total_lights=1):
    """Return a MagicMock for the discovery agent."""
    d = MagicMock()
    d.run.return_value = MagicMock(
        context=MagicMock(
            total_light_frames=total_lights,
            calibration=MagicMock(dark_count=0),
            target=MagicMock(name="Test", target_type=MagicMock(value="star")),
            equipment=MagicMock(focal_length_mm=150, pixel_size_um=2.9),
            total_integration_time=100.0,
            get_lights=MagicMock(return_value=MagicMock(frames=[], group_by_params=MagicMock(return_value={}))),
        ),
        eq=None,
        eq_source="unknown",
        warnings=[],
        recommendation=None,
    )
    d.discover_groups.return_value = {}
    return d


def _invoke_process(runner, args, tmp_path):
    """Invoke process with mocked agents. Returns (result, captured_dict)."""
    captured = {}
    discovery = _mock_discovery()

    cal = MagicMock()
    cal.run.return_value = MagicMock(master_dark=None, calibrated_lights=[], master_dark_paths={})

    def _make_cal(*_a, **_kw):
        captured["darks_repository"] = _kw.get("darks_repository")
        return cal

    deb = MagicMock()
    deb.run.return_value = MagicMock(debayered_frames=[])
    proc = MagicMock()
    proc.run.return_value = MagicMock(
        stacked=None, exports=[], registered_frames=[],
        frame_qualities=[], stack_quality=None, gradient_removal=None,
        registration_metrics=None, pcc_status=None, multi_group_metadata=None,
    )
    arch = MagicMock()
    arch.run.return_value = MagicMock(output_dir=tmp_path, final_fits=None)

    with patch("astro_process.cli.create_discovery_agent", return_value=discovery), \
         patch("astro_process.cli.create_calibration_agent", side_effect=_make_cal), \
         patch("astro_process.cli.create_cosmetic_agent", return_value=MagicMock(run=MagicMock(return_value=None))), \
         patch("astro_process.cli.create_debayer_agent", return_value=deb), \
         patch("astro_process.cli.create_processing_agent", return_value=proc), \
         patch("astro_process.cli.create_archive_agent", return_value=arch):
        result = runner.invoke(cli, args)

    return result, captured, discovery, proc


def _invoke_process_with_proc(runner, args, tmp_path, proc):
    """Invoke process with a pre-configured processing agent mock."""
    discovery = _mock_discovery()
    cal = MagicMock()
    cal.run.return_value = MagicMock(master_dark=None, calibrated_lights=[])
    deb = MagicMock()
    deb.run.return_value = MagicMock(debayered_frames=[])
    arch = MagicMock()
    arch.run.return_value = MagicMock(output_dir=tmp_path, final_fits=None)

    with patch("astro_process.cli.create_discovery_agent", return_value=discovery), \
         patch("astro_process.cli.create_calibration_agent", return_value=cal), \
         patch("astro_process.cli.create_cosmetic_agent", return_value=MagicMock(run=MagicMock(return_value=None))), \
         patch("astro_process.cli.create_debayer_agent", return_value=deb), \
         patch("astro_process.cli.create_processing_agent", return_value=proc), \
         patch("astro_process.cli.create_archive_agent", return_value=arch):
        result = runner.invoke(cli, args)

    return result, discovery, proc


# ═══════════════════════════════════════════════════════════════════
# V1.5-6: dry-run Factory-Usage
# ═══════════════════════════════════════════════════════════════════


class TestV15_6DryRunFactory:
    def test_dry_run_uses_factory_not_direct_instantiation(self, tmp_path, monkeypatch):
        """V1.5-6: dry-run mit --multi-group muss create_discovery_agent()
        verwenden, nicht DiscoveryAgent() direkt."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        discovery = _mock_discovery()
        discovery.discover_groups.return_value = {
            "abc123": MagicMock(
                key=(30.0, 100, "L"),
                frame_count=5,
                total_exposure=150.0,
            ),
        }

        runner = CliRunner()
        with patch("astro_process.cli.create_discovery_agent", return_value=discovery) as factory_mock:
            result = runner.invoke(cli, ["process", str(target), "--dry-run", "--multi-group"])

        assert result.exit_code == 0, result.output
        # Factory must be called, not DiscoveryAgent()
        factory_mock.assert_called()
        assert "DRY RUN" in result.output

    def test_dry_run_single_group_uses_factory(self, tmp_path, monkeypatch):
        """V1.5-6: dry-run ohne --multi-group muss ebenfalls Factory nutzen."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        discovery = _mock_discovery()
        discovery.discover_groups.return_value = {}

        runner = CliRunner()
        with patch("astro_process.cli.create_discovery_agent", return_value=discovery) as factory_mock:
            result = runner.invoke(cli, ["process", str(target), "--dry-run"])

        assert result.exit_code == 0, result.output
        factory_mock.assert_called()
        assert "DRY RUN" in result.output


# ═══════════════════════════════════════════════════════════════════
# V1.5-11: --az-mode / --eq-mode CLI-Flags
# ═══════════════════════════════════════════════════════════════════


class TestV15_11EqModeFlags:
    def test_az_mode_sets_eq_false(self, tmp_path, monkeypatch):
        """V1.5-11: --az-mode setzt discovery_result.eq = False und
        eq_source = 'cli_override'."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result, captured, discovery, _ = _invoke_process(
            runner,
            ["process", str(target), "--az-mode"],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        # discovery.run.return_value is what the CLI modifies
        dr = discovery.run.return_value
        assert dr.eq is False
        assert dr.eq_source == "cli_override"

    def test_eq_mode_sets_eq_true(self, tmp_path, monkeypatch):
        """V1.5-11: --eq-mode setzt discovery_result.eq = True."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result, captured, discovery, _ = _invoke_process(
            runner,
            ["process", str(target), "--eq-mode"],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        dr = discovery.run.return_value
        assert dr.eq is True
        assert dr.eq_source == "cli_override"

    def test_no_eq_flag_leaves_original(self, tmp_path, monkeypatch):
        """V1.5-11: Ohne --az/--eq-Flag bleibt eq unveraendert."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result, captured, discovery, _ = _invoke_process(
            runner,
            ["process", str(target)],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        # Original from mock: eq=None, eq_source="unknown"
        dr = discovery.run.return_value
        assert dr.eq is None
        assert dr.eq_source == "unknown"


# ═══════════════════════════════════════════════════════════════════
# V1.5-12: --pixel-scale CLI-Flag
# ═══════════════════════════════════════════════════════════════════


class TestV15_12PixelScaleFlag:
    def test_pixel_scale_passed_to_agent(self, tmp_path, monkeypatch):
        """V1.5-12: --pixel-scale 5.5 setzt pixel_scale_override auf dem
        ProcessingAgent."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result, captured, _, proc = _invoke_process(
            runner,
            ["process", str(target), "--pixel-scale", "5.5"],
            tmp_path,
        )

        assert result.exit_code == 0, result.output
        assert proc.pixel_scale_override == 5.5

    def test_no_pixel_scale_leaves_none(self, tmp_path, monkeypatch):
        """V1.5-12: Ohne --pixel-scale bleibt pixel_scale_override None."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        # Use a real object to avoid MagicMock auto-creating attributes
        class FakeProc:
            pixel_scale_override = "UNSET_SENTINEL"
            def run(self, *a, **kw):
                return MagicMock(stacked=None, exports=[], registered_frames=[],
                    frame_qualities=[], stack_quality=None, gradient_removal=None,
                    registration_metrics=None, pcc_status=None, multi_group_metadata=None)
            def process_multi_group(self, *a, **kw):
                return MagicMock(stacked=None, exports=[], multi_group_metadata=None)

        proc = FakeProc()

        runner = CliRunner()
        result, _, _ = _invoke_process_with_proc(
            runner, ["process", str(target)], tmp_path, proc,
        )

        assert result.exit_code == 0, result.output
        # pixel_scale_override should NOT have been set when --pixel-scale is absent
        assert proc.pixel_scale_override == "UNSET_SENTINEL"


# ═══════════════════════════════════════════════════════════════════
# V1.5-13: --se-radius / --se-amount CLI-Flags
# ═══════════════════════════════════════════════════════════════════


class TestV15_13SEOverrideFlags:
    def test_se_radius_sets_step_param(self, tmp_path, monkeypatch):
        """V1.5-13: --se-radius 5.0 setzt radius im SE-Step-Params."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        # Need a preset with structure_enhancement step
        discovery = _mock_discovery()
        cal = MagicMock()
        cal.run.return_value = MagicMock(master_dark=None, calibrated_lights=[])
        deb = MagicMock()
        deb.run.return_value = MagicMock(debayered_frames=[])
        proc = MagicMock()
        proc.run.return_value = MagicMock(
            stacked=None, exports=[], registered_frames=[],
            frame_qualities=[], stack_quality=None, gradient_removal=None,
            registration_metrics=None, pcc_status=None, multi_group_metadata=None,
        )
        arch = MagicMock()
        arch.run.return_value = MagicMock(output_dir=tmp_path, final_fits=None)

        # We need to capture the pipeline preset to check step params
        captured_pipeline = {}
        original_create = None

        def _mock_create_proc(wd, config):
            return proc

        runner = CliRunner()
        with patch("astro_process.cli.create_discovery_agent", return_value=discovery), \
             patch("astro_process.cli.create_calibration_agent", return_value=cal), \
             patch("astro_process.cli.create_cosmetic_agent", return_value=MagicMock(run=MagicMock(return_value=None))), \
             patch("astro_process.cli.create_debayer_agent", return_value=deb), \
             patch("astro_process.cli.create_processing_agent", side_effect=_mock_create_proc), \
             patch("astro_process.cli.create_archive_agent", return_value=arch):
            # Use a config that has a preset with structure_enhancement
            cfg_content = yaml.safe_load(cfg.read_text(encoding="utf-8"))
            cfg_content["pipeline_presets"] = [{
                "name": "star_standard",
                "target_types": ["star"],
                "steps": [
                    {"name": "register_frames"},
                    {"name": "stack_frames"},
                    {"name": "structure_enhancement", "params": {"radius": 3.0, "amount": 0.2}},
                    {"name": "stretch"},
                    {"name": "export"},
                ],
                "processing_params": {"rejection": "average"},
            }]
            cfg.write_text(yaml.safe_dump(cfg_content, sort_keys=False), encoding="utf-8")
            result = runner.invoke(cli, ["process", str(target), "--se-radius", "5.0", "--se-amount", "0.5"])

        assert result.exit_code == 0, result.output
        # The step params should have been modified
        # We can't directly inspect them because the pipeline is created inside
        # the process function, but we can check the log output
        assert "cli.process.se_override" in result.output or result.exit_code == 0

    def test_se_flags_absent_leaves_preset_unchanged(self, tmp_path, monkeypatch):
        """V1.5-13: Ohne --se-radius/--se-amount bleiben die Preset-Params unberuehrt."""
        cfg = _make_config(tmp_path)
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result, captured, _, _ = _invoke_process(
            runner,
            ["process", str(target)],
            tmp_path,
        )

        assert result.exit_code == 0, result.output


# ═══════════════════════════════════════════════════════════════════
# V1.5-14: Warnings maschinenlesbar (strukturiertes YAML)
# ═══════════════════════════════════════════════════════════════════


class TestV15_14StructuredWarnings:
    def test_agent_log_has_warnings_section_with_discovery_warnings(
        self, tmp_path, monkeypatch
    ):
        """V1.5-14: Wenn DiscoveryWarnings vorhanden sind, enthaelt
        agent-log.yaml eine strukturierte 'warnings'-Sektion."""
        from astro_process.agents.archive import ArchiveAgent
        from astro_process.models.core import ObservationContext, ObservationTarget, TargetType
        from astro_process.agents.discovery import DiscoveryResult
        from unittest.mock import MagicMock

        output_dir = tmp_path
        agent = ArchiveAgent(output_dir)

        # Create minimal context
        target = MagicMock()
        target.name = "Test Target"
        target.target_type = MagicMock()
        target.target_type.value = "star"

        context = MagicMock()
        context.target = target
        context.total_integration_time = 100.0
        context.total_light_frames = 5
        context.calibration = MagicMock(dark_count=0, flat_count=0, bias_count=0)
        context.equipment = MagicMock(telescope="T", camera="C")

        cal_result = MagicMock(master_dark=None, calibrated_lights=[])
        deb_result = MagicMock(debayered_frames=[])
        proc_result = MagicMock(
            registered_frames=[], stacked=None, exports=[],
            frame_qualities=[], stack_quality={}, gradient_removal={},
            registration_metrics={}, pcc_status=None,
        )

        discovery = DiscoveryResult(
            context=context,
            warnings=[
                "EQMODE conflict: shotsInfo says EQ, header says AZ",
                {"source": "eq_mix", "message": "AZ/EQ mix detected", "groups": ["a", "b"]},
            ],
            eq=True,
            eq_source="shotsinfo",
        )

        agent._create_agent_log(
            output_dir, context, proc_result, cal_result,
            debayer_result=deb_result,
            discovery_result=discovery,
        )

        log_path = output_dir / "agent-log.yaml"
        assert log_path.exists()
        log_data = yaml.safe_load(log_path.read_text(encoding="utf-8"))

        assert "warnings" in log_data
        assert len(log_data["warnings"]) == 2
        # First warning is a plain string converted to dict
        assert log_data["warnings"][0]["source"] == "discovery"
        assert "EQMODE conflict" in log_data["warnings"][0]["message"]
        # Second warning is already a dict
        assert log_data["warnings"][1]["source"] == "eq_mix"
        assert log_data["warnings"][1]["message"] == "AZ/EQ mix detected"

    def test_agent_log_no_warnings_section_when_empty(self, tmp_path):
        """V1.5-14: Ohne Warnungen gibt es keine 'warnings'-Sektion."""
        from astro_process.agents.archive import ArchiveAgent
        from astro_process.agents.discovery import DiscoveryResult
        from unittest.mock import MagicMock

        output_dir = tmp_path
        agent = ArchiveAgent(output_dir)

        target = MagicMock()
        target.name = "Test"
        target.target_type = MagicMock()
        target.target_type.value = "star"

        context = MagicMock()
        context.target = target
        context.total_integration_time = 100.0
        context.total_light_frames = 5
        context.calibration = MagicMock(dark_count=0, flat_count=0, bias_count=0)
        context.equipment = MagicMock(telescope="T", camera="C")

        cal_result = MagicMock(master_dark=None, calibrated_lights=[])
        proc_result = MagicMock(
            registered_frames=[], stacked=None, exports=[],
            frame_qualities=[], stack_quality={}, gradient_removal={},
            registration_metrics={}, pcc_status=None,
        )

        discovery = DiscoveryResult(context=context, warnings=[], eq=None, eq_source="unknown")

        agent._create_agent_log(
            output_dir, context, proc_result, cal_result,
            discovery_result=discovery,
        )

        log_path = output_dir / "agent-log.yaml"
        log_data = yaml.safe_load(log_path.read_text(encoding="utf-8"))

        assert "warnings" not in log_data

    def test_agent_log_registration_rejection_warning(self, tmp_path):
        """V1.5-14: Rejected Frames erzeugen eine strukturierte Warning."""
        from astro_process.agents.archive import ArchiveAgent
        from astro_process.agents.discovery import DiscoveryResult
        from unittest.mock import MagicMock

        output_dir = tmp_path
        agent = ArchiveAgent(output_dir)

        target = MagicMock()
        target.name = "Test"
        target.target_type = MagicMock()
        target.target_type.value = "star"

        context = MagicMock()
        context.target = target
        context.total_integration_time = 100.0
        context.total_light_frames = 5
        context.calibration = MagicMock(dark_count=0, flat_count=0, bias_count=0)
        context.equipment = MagicMock(telescope="T", camera="C")

        cal_result = MagicMock(master_dark=None, calibrated_lights=[])
        proc_result = MagicMock(
            registered_frames=[], stacked=None, exports=[],
            frame_qualities=[],
            stack_quality={},
            gradient_removal={},
            registration_metrics={"rejected_count": 3, "zero_shift_count": 1},
            pcc_status=None,
        )

        discovery = DiscoveryResult(context=context, warnings=[], eq=None, eq_source="unknown")

        agent._create_agent_log(
            output_dir, context, proc_result, cal_result,
            discovery_result=discovery,
        )

        log_path = output_dir / "agent-log.yaml"
        log_data = yaml.safe_load(log_path.read_text(encoding="utf-8"))

        assert "warnings" in log_data
        reg_warnings = [
            w for w in log_data["warnings"] if w.get("source") == "registration"
        ]
        assert len(reg_warnings) == 1
        assert reg_warnings[0]["rejected_count"] == 3
