"""Tests for GR-B: Gradient-Removal-Config + Step-Verdrahtung (AC-GR-B1..B4).

Deckt ab:
- Config-Modelle: `GradientRemovalConfig` Defaults, Parsing in
  `ProcessingParams` und `AppConfig` (Config-/Preset-Layering).
- Precedence CLI > Config > Preset > Default via `resolve_gradient_removal`
  (analog `resolve_registration`, AC-GR-B1).
- `astra init` schreibt den `gradient_removal:`-Block mit Kommentar.
- End-to-End: `process --dry-run` verankert die effektive Config im Preset
  und loggt `cli.process.gradient_removal`.
- S2-B10 (AC-GR-B4): `run()`-Logik wird in der Integrationstest-Datei
  (test_processing_etappe2.py) abgedeckt — hier liegt die Config-Seite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.cli import cli  # noqa: E402
from astro_process.config.loader import (  # noqa: E402
    DEFAULT_CONFIG,
    load_config,
    resolve_gradient_removal,
)
from astro_process.config.models import (  # noqa: E402
    AppConfig,
    GradientRemovalConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
)
from conftest import write_default_suggested  # noqa: E402


def _preset(gr: GradientRemovalConfig | None = None) -> PipelinePreset:
    return PipelinePreset(
        name="test",
        target_types=["nebula"],
        steps=[PipelineStep(name="gradient_removal")],
        processing_params=ProcessingParams(
            gradient_removal=gr or GradientRemovalConfig()
        ),
    )


def _write_config(tmp: Path, data: dict) -> Path:
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return cfg_path


def _write_default_based_config(tmp: Path, update: dict) -> Path:
    data = yaml.safe_load(DEFAULT_CONFIG)
    data.update(update)
    return _write_config(tmp, data)


# ═══════════════════════════════════════════════════════════════════
# Section: Config-Modelle AC-GR-B1
# ═══════════════════════════════════════════════════════════════════


class TestGradientRemovalModels:
    def test_default_gradient_removal_config(self):
        """Default: enabled false, degree 2, grid (16, 16), sigma_clip 3.0,
        min_samples None (OQ-GR-1-A / OQ-GR-3; Grid-Flip AC-GR-C4,
        M13-Validierung: 16x16 besser als 32x32)."""
        cfg = GradientRemovalConfig()
        assert cfg.enabled is False
        assert cfg.degree == 2
        assert cfg.grid == (16, 16)
        assert cfg.sigma_clip == 3.0
        assert cfg.min_samples is None

    def test_processing_params_default_embeds_gradient_removal(self):
        """ProcessingParams enthaelt gradient_removal mit Default-Werten
        (Preset-Layering)."""
        params = ProcessingParams()
        assert params.gradient_removal.enabled is False
        assert params.gradient_removal.degree == 2

    def test_processing_params_parses_gradient_removal(self):
        """ProcessingParams parst explizite gradient_removal-Werte (Preset)."""
        params = ProcessingParams(
            gradient_removal=GradientRemovalConfig(
                enabled=True, degree=1, grid=(16, 16), sigma_clip=4.0,
                min_samples=20,
            )
        )
        gr = params.gradient_removal
        assert gr.enabled is True
        assert gr.degree == 1
        assert gr.grid == (16, 16)
        assert gr.sigma_clip == 4.0
        assert gr.min_samples == 20

    def test_pipeline_preset_parses_gradient_removal_yaml(self):
        """PipelinePreset parst verschachteltes gradient_removal aus YAML
        (pipeline_presets[].processing_params.gradient_removal)."""
        data = yaml.safe_load(
            """
            name: test
            target_types: [nebula]
            steps:
              - name: gradient_removal
            processing_params:
              rejection: winsorized
              gradient_removal:
                enabled: true
                degree: 3
                grid: [16, 16]
                sigma_clip: 2.5
                min_samples: 15
            """
        )
        preset = PipelinePreset(**data)
        gr = preset.processing_params.gradient_removal
        assert gr.enabled is True
        assert gr.degree == 3
        assert gr.grid == (16, 16)
        assert gr.sigma_clip == 2.5
        assert gr.min_samples == 15

    def test_app_config_gradient_removal_default_none(self):
        """AppConfig ohne gradient_removal-Block: Feld ist None
        (kein Config-Layer -> Preset/Default gilt)."""
        assert AppConfig().gradient_removal is None

    def test_app_config_parses_gradient_removal_block(self):
        """AppConfig parst den gradient_removal-Block (Config-Layer, AC-GR-B1)."""
        cfg = AppConfig(
            gradient_removal={
                "enabled": True,
                "degree": 2,
                "grid": [32, 32],
                "sigma_clip": 3.5,
                "min_samples": 40,
            }
        )
        assert cfg.gradient_removal is not None
        assert cfg.gradient_removal.enabled is True
        assert cfg.gradient_removal.grid == (32, 32)
        assert cfg.gradient_removal.min_samples == 40

    def test_app_config_rejects_bad_grid(self):
        """grid muss ein 2-Tupel aus positiven Ints sein (Config-Validierung)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="grid"):
            AppConfig(gradient_removal={"grid": [32]})


# ═══════════════════════════════════════════════════════════════════
# Precedence CLI > Config > Preset > Default (AC-GR-B1)
# ═══════════════════════════════════════════════════════════════════


class TestResolveGradientRemoval:
    def test_default_only(self):
        """Default: enabled false / degree 2 / grid (16,16) / sigma 3.0 /
        min_samples None (kein Preset-, Config- oder CLI-Override)."""
        result = resolve_gradient_removal(AppConfig(), _preset())
        assert result.enabled is False
        assert result.degree == 2
        assert result.grid == (16, 16)
        assert result.sigma_clip == 3.0
        assert result.min_samples is None

    def test_preset_overrides_default(self):
        """Preset (processing_params.gradient_removal) gewinnt gegen Default."""
        preset = _preset(GradientRemovalConfig(enabled=True, degree=3))
        result = resolve_gradient_removal(AppConfig(), preset)
        assert result.enabled is True
        assert result.degree == 3

    def test_config_overrides_preset(self):
        """Config (AppConfig.gradient_removal) gewinnt gegen Preset."""
        cfg = AppConfig(gradient_removal=GradientRemovalConfig(enabled=True))
        result = resolve_gradient_removal(cfg, _preset())
        assert result.enabled is True

    def test_cli_enabled_overrides_config_and_preset(self):
        """CLI-Flag --gradient-removal-enabled gewinnt gegen Config UND Preset."""
        cfg = AppConfig(gradient_removal=GradientRemovalConfig(enabled=True))
        preset = _preset(GradientRemovalConfig(enabled=True))
        result = resolve_gradient_removal(cfg, preset, cli_enabled=False)
        assert result.enabled is False

    def test_cli_enabled_overrides_default(self):
        """CLI-Flag aktiviert ohne Config-/Preset-Block."""
        result = resolve_gradient_removal(AppConfig(), _preset(), cli_enabled=True)
        assert result.enabled is True

    def test_fieldwise_degree_grid_sigma(self):
        """degree/grid/sigma_clip: vorhandener Config-Block setzt alle
        nicht-None-Felder (Pydantic-Defaults inklusive — konsistent mit
        ``registration.method`` bei ``resolve_registration``); CLI gewinnt
        immer. Nur None-tolerante Felder (min_samples) sind wirklich
        "nicht gesetzt" (siehe test_min_samples_none_default).
        """
        preset = _preset(GradientRemovalConfig(degree=1))

        # Config-Block OHNE degree-Angabe -> Pydantic-Default 2 gilt
        # (Config-Block existiert und setzt das Feld auf den Default).
        cfg_default = AppConfig(gradient_removal=GradientRemovalConfig(enabled=True))
        assert resolve_gradient_removal(cfg_default, preset).degree == 2

        # Config degree 4 + Preset degree 1 -> 4 (Config setzt Feld explizit)
        cfg_4 = AppConfig(
            gradient_removal=GradientRemovalConfig(enabled=True, degree=4)
        )
        assert resolve_gradient_removal(cfg_4, preset).degree == 4

        # CLI degree 1 gewinnt gegen beides
        result = resolve_gradient_removal(cfg_4, preset, cli_degree=1)
        assert result.degree == 1

        # grid/sigma_clip: CLI > Config > Preset > Default
        preset_grid = _preset(
            GradientRemovalConfig(degree=1, grid=(8, 8), sigma_clip=5.0)
        )
        assert resolve_gradient_removal(AppConfig(), preset_grid).grid == (8, 8)
        assert resolve_gradient_removal(AppConfig(), preset_grid).sigma_clip == 5.0
        cfg_grid = AppConfig(
            gradient_removal=GradientRemovalConfig(enabled=True, grid=(16, 16))
        )
        assert resolve_gradient_removal(cfg_grid, preset_grid).grid == (16, 16)
        cli_result = resolve_gradient_removal(
            cfg_grid, preset_grid, cli_grid=(4, 4), cli_sigma_clip=2.0
        )
        assert cli_result.grid == (4, 4)
        assert cli_result.sigma_clip == 2.0

    def test_cli_grid_parsed_tuple(self):
        """CLI-Grid als (rows, cols)-Tupel uebergeben -> im Resultat."""
        result = resolve_gradient_removal(
            AppConfig(), _preset(), cli_grid=(16, 16)
        )
        assert result.grid == (16, 16)

    def test_min_samples_none_default(self):
        """min_samples: None bleibt None (Wrapper nutzt Polynom-Terme)."""
        result = resolve_gradient_removal(AppConfig(), _preset())
        assert result.min_samples is None
        result2 = resolve_gradient_removal(
            AppConfig(), _preset(), cli_min_samples=10
        )
        assert result2.min_samples == 10


# ═══════════════════════════════════════════════════════════════════
# Loader / astra init (AC-GR-B1)
# ═══════════════════════════════════════════════════════════════════


class TestLoaderInit:
    def test_default_config_contains_gradient_removal_block(self):
        """DEFAULT_CONFIG enthaelt den gradient_removal-Block mit allen Feldern."""
        data = yaml.safe_load(DEFAULT_CONFIG)
        assert "gradient_removal" in data
        gr = data["gradient_removal"]
        assert gr["enabled"] is False
        assert gr["degree"] == 2
        assert gr["grid"] == [16, 16]
        assert gr["sigma_clip"] == 3.0
        assert gr["min_samples"] is None

    def test_init_writes_gradient_removal_block_with_comment(self):
        """`astra init` schreibt gradient_removal-Block + Kommentar (AC-GR-B1)."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0, result.output
            content = Path("config.yaml").read_text(encoding="utf-8")
            assert "gradient_removal:" in content
            assert "enabled: false" in content
            assert "degree: 2" in content
            assert "grid: [16, 16]" in content
            assert "sigma_clip: 3.0" in content
            assert "min_samples: null" in content
            # Kommentar: Felder erklaert (AC-GR-B1)
            assert "GR-B" in content
            assert "min_samples" in content
            assert "16x16" in content

    def test_load_config_parses_gradient_removal_block(self, tmp_path):
        """load_config parst Config-Datei mit gradient_removal-Override."""
        cfg_path = _write_default_based_config(
            tmp_path,
            {"gradient_removal": {
                "enabled": True, "degree": 1, "grid": [16, 16],
                "sigma_clip": 2.0, "min_samples": 12,
            }},
        )
        cfg = load_config(cfg_path)
        assert cfg.gradient_removal is not None
        assert cfg.gradient_removal.enabled is True
        assert cfg.gradient_removal.grid == (16, 16)
        assert cfg.gradient_removal.min_samples == 12


# ═══════════════════════════════════════════════════════════════════
# End-to-End: CLI-Flags im process-Command (AC-GR-B1)
# ═══════════════════════════════════════════════════════════════════


class TestCliGradientRemovalFlags:
    @staticmethod
    def _create_light_target(root: Path) -> Path:
        """Minimales Target mit einem synthetischen Light-FITS (fuer dry-run)."""
        import numpy as np
        from astropy.io import fits

        target = root / "TestTarget"
        target.mkdir(parents=True, exist_ok=True)
        rng = np.random.RandomState(7)
        data = (50.0 + rng.uniform(0, 10, (64, 64))).astype(np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["EXPTIME"] = 15.0
        hdu.header["GAIN"] = 60
        hdu.writeto(target / "light_0001.fits", overwrite=True)
        return target

    def test_cli_flag_appears_in_effective_gradient_removal(self, tmp_path):
        """CLI --gradient-removal-enabled (ohne Config-Block) -> effektive
        Config im Preset verankert, Log `cli.process.gradient_removal` zeigt
        enabled=true (Precedence CLI > Default)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested",
                  "--gradient-removal-enabled"]
        )
        assert result.exit_code == 0, result.output
        assert '"enabled": true' in result.output
        assert "cli.process.gradient_removal" in result.output

    def test_cli_flags_override_config(self, tmp_path):
        """Precedence e2e: Config enabled=true + CLI --gradient-removal-disabled
        -> enabled false gewinnt (CLI > Config); degree/grid aus der Config
        bleiben (nur enabled wird vom CLI ueberschrieben)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target)
        cfg_path = _write_default_based_config(
            tmp_path,
            {"gradient_removal": {
                "enabled": True, "degree": 3, "grid": [16, 16],
                "sigma_clip": 2.0, "min_samples": 20,
            }},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(cfg_path), "process", str(target), "--dry-run",
             "--from-suggested", "--gradient-removal-disabled"],
        )
        assert result.exit_code == 0, result.output
        assert '"enabled": false' in result.output
        assert '"degree": 3' in result.output
        assert '"grid": [16, 16]' in result.output
        assert "cli.process.gradient_removal" in result.output

    def test_cli_grid_flag(self, tmp_path):
        """--gradient-removal-grid '16,16' -> grid (16, 16) im effektiven
        Ergebnis (CLI > Default)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested",
                  "--gradient-removal-grid", "16,16"]
        )
        assert result.exit_code == 0, result.output
        assert '"grid": [16, 16]' in result.output

    def test_cli_grid_invalid(self, tmp_path):
        """Ungueltiges --gradient-removal-grid -> ClickException, Exit != 0."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested",
                  "--gradient-removal-grid", "nope"]
        )
        assert result.exit_code != 0
        assert "Ungueltiges --gradient-removal-grid" in result.output

    def test_config_enabled_applies_without_cli_flag(self, tmp_path):
        """Config gradient_removal.enabled=true wirkt ohne CLI-Flag
        (Config-Ebene erreicht die effektive Config)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target)
        cfg_path = _write_default_based_config(
            tmp_path,
            {"gradient_removal": {"enabled": True}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["-c", str(cfg_path), "process", str(target), "--dry-run",
                  "--from-suggested"]
        )
        assert result.exit_code == 0, result.output
        assert '"enabled": true' in result.output
        assert "cli.process.gradient_removal" in result.output
