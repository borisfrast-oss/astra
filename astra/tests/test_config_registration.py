"""Tests for W9-B: Registrations-Methoden-Wahl (AC-W9-B1/B2/B4, ADR-019).

Deckt ab:
- Config-Modelle: `RegistrationConfig` Defaults, Parsing in `ProcessingParams`
  und `AppConfig` (Config-/Preset-Layering).
- Precedence CLI > Config > Preset > Default via `resolve_registration`
  (analog --weight-by/--merge-method).
- `astra init` schreibt den `registration:`-Block mit Kommentar (AC-W9-B2).
- End-to-End: `process --dry-run` verankert die effektive Config im Preset
  und loggt `cli.process.registration`.
- Spike-Befund 1 (null -> 50) ist in `test_registration_w9.py` als
  Spy-Test abgedeckt (Wrapper-Ebene); hier wird die Config-Seite belegt
  (resolve_registration null -> None -> Wrapper-50).
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
from astro_process.config import loader as config_loader  # noqa: E402
from astro_process.config.loader import (  # noqa: E402
    DEFAULT_CONFIG,
    load_config,
    resolve_registration,
)
from astro_process.config.models import (  # noqa: E402
    AppConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
    RegistrationConfig,
)
from astro_process.config.loader import resolve_registration_config  # noqa: E402
from conftest import write_default_suggested  # noqa: E402


def _preset(registration: RegistrationConfig | None = None) -> PipelinePreset:
    return PipelinePreset(
        name="test",
        target_types=["star"],
        steps=[PipelineStep(name="register_frames")],
        processing_params=ProcessingParams(registration=registration or RegistrationConfig()),
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
# Section: Config-Modelle AC-W9-B1/B4
# ═══════════════════════════════════════════════════════════════════


class TestRegistrationModels:
    def test_default_registration_config(self):
        """Default: method=fft (v1.1), max_control_points=None (null),
        SanityGuard-Schwellen max_rotation_deg=2.0 / max_scale_dev=0.02
        (= bisheriges Verhalten, keine Verhaltensaenderung),
        stack_scale_factor=2.0 (F-META-1.2, stella Punkt 5 — DWARF mini:
        nativ 2MP/2.9µm, nur 2x Superpixel-Debayer)."""
        cfg = RegistrationConfig()
        assert cfg.method == "fft"
        assert cfg.max_control_points is None
        assert cfg.max_rotation_deg == 2.0
        assert cfg.max_scale_dev == 0.02
        assert cfg.stack_scale_factor == 2.0

    def test_processing_params_default_embeds_registration(self):
        """ProcessingParams enthaelt registration mit Default-Werten
        (Preset-Layering)."""
        params = ProcessingParams()
        assert params.registration.method == "fft"
        assert params.registration.max_control_points is None
        assert params.registration.max_rotation_deg == 2.0
        assert params.registration.max_scale_dev == 0.02
        assert params.registration.stack_scale_factor == 2.0

    def test_processing_params_parses_registration(self):
        """ProcessingParams parst explizite registration-Werte (Preset)."""
        params = ProcessingParams(
            registration=RegistrationConfig(
                method="astroalign", max_control_points=10,
                max_rotation_deg=15.0, max_scale_dev=0.05,
                stack_scale_factor=3.0,
            )
        )
        assert params.registration.method == "astroalign"
        assert params.registration.max_control_points == 10
        assert params.registration.max_rotation_deg == 15.0
        assert params.registration.max_scale_dev == 0.05
        assert params.registration.stack_scale_factor == 3.0

    def test_pipeline_preset_parses_registration_yaml(self):
        """PipelinePreset parst verschachteltes registration aus YAML
        (pipeline_presets[].processing_params.registration)."""
        data = yaml.safe_load(
            """
            name: test
            target_types: [star]
            steps:
              - name: register_frames
            processing_params:
              rejection: winsorized
              registration:
                method: astroalign
                max_control_points: 30
                max_rotation_deg: 15
                max_scale_dev: 0.04
                stack_scale_factor: 5.0
            """
        )
        preset = PipelinePreset(**data)
        assert preset.processing_params.registration.method == "astroalign"
        assert preset.processing_params.registration.max_control_points == 30
        assert preset.processing_params.registration.max_rotation_deg == 15
        assert preset.processing_params.registration.max_scale_dev == 0.04
        assert preset.processing_params.registration.stack_scale_factor == 5.0

    def test_app_config_registration_default_none(self):
        """AppConfig ohne registration-Block: registration ist None
        (kein Config-Layer -> Preset/Default gilt)."""
        assert AppConfig().registration is None

    def test_app_config_parses_registration_block(self):
        """AppConfig parst den registration-Block (Config-Layer, AC-W9-B1)."""
        cfg = AppConfig(
            registration={"method": "astroalign", "max_control_points": 25,
                          "max_rotation_deg": 12.0, "max_scale_dev": 0.03,
                          "stack_scale_factor": 3.5}
        )
        assert cfg.registration is not None
        assert cfg.registration.method == "astroalign"
        assert cfg.registration.max_control_points == 25
        assert cfg.registration.max_rotation_deg == 12.0
        assert cfg.registration.max_scale_dev == 0.03
        assert cfg.registration.stack_scale_factor == 3.5

    def test_app_config_rejects_invalid_method(self):
        """method ist auf {fft, astroalign, rotation_fft} beschraenkt
        (Literal)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="method"):
            AppConfig(registration={"method": "pca"})

    # ── V1.9: max_exptime_fft_warn als echtes Pydantic-Feld ──

    def test_default_max_exptime_fft_warn(self):
        """RegistrationConfig enthaelt max_exptime_fft_warn mit Default 45.0
        (bisheriges Verhalten, wird vom Equipment-Profil/Resolver propagiert)."""
        cfg = RegistrationConfig()
        assert cfg.max_exptime_fft_warn == 45.0

    def test_override_max_exptime_fft_warn(self):
        """max_exptime_fft_warn ist uebersteuerbar (Preset/Config/Resolver)."""
        cfg = RegistrationConfig(max_exptime_fft_warn=30.0)
        assert cfg.max_exptime_fft_warn == 30.0

    def test_model_dump_contains_max_exptime_fft_warn(self):
        """model_dump/export enthaelt das Feld (kein dynamisches Attribut mehr)."""
        cfg = RegistrationConfig(max_exptime_fft_warn=60.0)
        data = cfg.model_dump()
        assert "max_exptime_fft_warn" in data
        assert data["max_exptime_fft_warn"] == 60.0


# ═══════════════════════════════════════════════════════════════════
# Precedence CLI > Config > Preset > Default (AC-W9-B1)
# ═══════════════════════════════════════════════════════════════════


class TestResolveRegistration:
    def test_default_only(self):
        """Default: fft / None / 2.0 / 0.02 / 2.0 (kein Preset-, Config- oder
        CLI-Override) — Default-Verhalten unveraendert (Punkt 5: Default-
        Faktor 2.0 greift ohne Config)."""
        result = resolve_registration(AppConfig(), _preset())
        assert result.method == "fft"
        assert result.max_control_points is None
        assert result.max_rotation_deg == 2.0
        assert result.max_scale_dev == 0.02
        assert result.stack_scale_factor == 2.0

    def test_preset_overrides_default(self):
        """Preset (processing_params.registration) gewinnt gegen Default."""
        preset = _preset(RegistrationConfig(method="astroalign"))
        result = resolve_registration(AppConfig(), preset)
        assert result.method == "astroalign"

    def test_config_overrides_preset(self):
        """Config (AppConfig.registration) gewinnt gegen Preset."""
        cfg = AppConfig(registration=RegistrationConfig(method="astroalign"))
        result = resolve_registration(cfg, _preset())
        assert result.method == "astroalign"

    def test_cli_overrides_config_and_preset(self):
        """CLI-Flag gewinnt gegen Config UND Preset."""
        cfg = AppConfig(registration=RegistrationConfig(method="astroalign"))
        preset = _preset(RegistrationConfig(method="astroalign"))
        result = resolve_registration(cfg, preset, cli_method="fft")
        assert result.method == "fft"

    def test_cli_astroalign_overrides_default(self):
        """CLI-Flag aktiviert astroalign ohne Config-/Preset-Block."""
        result = resolve_registration(AppConfig(), _preset(), cli_method="astroalign")
        assert result.method == "astroalign"

    def test_max_control_points_fieldwise(self):
        """max_control_points: feldweise Aufloesung, None = nicht gesetzt.

        - Config null (Default) + Preset 30 -> 30 (Config setzt Feld nicht).
        - Config 10 + Preset 30 -> 10 (Config setzt Feld explizit).
        """
        preset = _preset(RegistrationConfig(max_control_points=30))

        # Config-Block vorhanden, aber max_control_points nicht gesetzt (null)
        cfg_null = AppConfig(registration=RegistrationConfig(method="fft"))
        assert resolve_registration(cfg_null, preset).max_control_points == 30

        # Config-Block setzt max_control_points explizit
        cfg_10 = AppConfig(
            registration=RegistrationConfig(method="fft", max_control_points=10)
        )
        assert resolve_registration(cfg_10, preset).max_control_points == 10

    def test_null_stays_none_for_wrapper_translation(self):
        """Spike-Befund 1 (Config-Seite): resolve_registration(null) liefert
        None — die null->50-Uebersetzung passiert im Wrapper
        (astroalign_register), siehe test_registration_w9.py."""
        result = resolve_registration(AppConfig(), _preset())
        assert result.max_control_points is None
        assert result.method == "fft"

    def test_preset_overrides_default_thresholds(self):
        """Preset-Schwellen (max_rotation_deg/max_scale_dev) gewinnen gegen
        Default."""
        preset = _preset(RegistrationConfig(max_rotation_deg=15.0, max_scale_dev=0.05))
        result = resolve_registration(AppConfig(), preset)
        assert result.max_rotation_deg == 15.0
        assert result.max_scale_dev == 0.05

    def test_config_overrides_preset_thresholds(self):
        """Config-Schwellen gewinnen gegen Preset-Schwellen."""
        preset = _preset(RegistrationConfig(max_rotation_deg=15.0, max_scale_dev=0.05))
        cfg = AppConfig(
            registration=RegistrationConfig(max_rotation_deg=10.0, max_scale_dev=0.04)
        )
        result = resolve_registration(cfg, preset)
        assert result.max_rotation_deg == 10.0
        assert result.max_scale_dev == 0.04

    def test_cli_max_rotation_overrides_config_and_preset(self):
        """CLI --max-rotation gewinnt gegen Config UND Preset; max_scale_dev
        bleibt vom Config-Layer (nur Rotation ist CLI-ueberschreibbar)."""
        preset = _preset(RegistrationConfig(max_rotation_deg=15.0, max_scale_dev=0.05))
        cfg = AppConfig(
            registration=RegistrationConfig(max_rotation_deg=10.0, max_scale_dev=0.04)
        )
        result = resolve_registration(cfg, preset, cli_max_rotation=20.0)
        assert result.max_rotation_deg == 20.0
        assert result.max_scale_dev == 0.04

    def test_cli_max_rotation_defaults_unchanged_without_flag(self):
        """Ohne --max-rotation bleiben die Schwellen bei Preset/Config/Default
        (kein CLI-Einfluss bei None)."""
        preset = _preset(RegistrationConfig(max_rotation_deg=15.0, max_scale_dev=0.05))
        result = resolve_registration(AppConfig(), preset, cli_max_rotation=None)
        assert result.max_rotation_deg == 15.0
        assert result.max_scale_dev == 0.05

    def test_preset_overrides_default_stack_scale_factor(self):
        """stack_scale_factor: Preset gewinnt gegen Default 2.0."""
        preset = _preset(RegistrationConfig(stack_scale_factor=3.0))
        result = resolve_registration(AppConfig(), preset)
        assert result.stack_scale_factor == 3.0

    def test_config_overrides_preset_stack_scale_factor(self):
        """stack_scale_factor: Config (AppConfig.registration) gewinnt gegen
        Preset (Precedence Config > Preset > Default, kein CLI-Flag)."""
        preset = _preset(RegistrationConfig(stack_scale_factor=3.0))
        cfg = AppConfig(registration=RegistrationConfig(stack_scale_factor=5.0))
        result = resolve_registration(cfg, preset)
        assert result.stack_scale_factor == 5.0

    # ── P2-2 (ray-Review) + V19-FIX-12 P1 Mandatory Gate ──
    # Precedence analog zu den uebrigen Feldern: CLI > Config > Preset >
    # Default (0.05 / True). Default ohne Flags = V19-FIX-12 0.05 (V1.8-8
    # DEF-006, entkoppelt von frame_selection.enabled, P1 Mandatory Gate).

    def test_p2_default_zero_shift_threshold_and_fallback(self):
        """P2-2 + V19-FIX-12: Default ohne Flags — zero_shift_threshold=0.05
        (V19-FIX-12, entkoppelt von frame_selection.enabled, P1 Mandatory Gate
        0.05; V1.3-1 Regress der RE-F-Schwelle 0.3), zero_shift_fallback=True
        (v1.2-Default-Verhalten unveraendert, aber Guard nun aktiv)."""
        result = resolve_registration(AppConfig(), _preset())
        assert result.zero_shift_threshold == 0.05
        assert result.zero_shift_fallback is True

    def test_p2_preset_overrides_default_zero_shift(self):
        """P2-2: Preset (processing_params.registration) gewinnt gegen
        Default — Schwellenwert UND Fallback-Flag."""
        preset = _preset(
            RegistrationConfig(zero_shift_threshold=0.5, zero_shift_fallback=False)
        )
        result = resolve_registration(AppConfig(), preset)
        assert result.zero_shift_threshold == 0.5
        assert result.zero_shift_fallback is False

    def test_p2_config_overrides_preset_zero_shift(self):
        """P2-2: Config (AppConfig.registration) gewinnt gegen Preset."""
        preset = _preset(
            RegistrationConfig(zero_shift_threshold=0.5, zero_shift_fallback=False)
        )
        cfg = AppConfig(
            registration=RegistrationConfig(
                zero_shift_threshold=0.6, zero_shift_fallback=True
            )
        )
        result = resolve_registration(cfg, preset)
        assert result.zero_shift_threshold == 0.6
        assert result.zero_shift_fallback is True

    def test_p2_cli_zero_shift_threshold_overrides_config_and_preset(self):
        """P2-2: CLI --zero-shift-threshold gewinnt gegen Config UND Preset;
        zero_shift_fallback bleibt vom Config-Layer (nur Threshold ist
        CLI-ueberschreibbar, feldweise)."""
        preset = _preset(RegistrationConfig(zero_shift_threshold=0.5))
        cfg = AppConfig(registration=RegistrationConfig(zero_shift_threshold=0.4))
        result = resolve_registration(cfg, preset, cli_zero_shift_threshold=0.7)
        assert result.zero_shift_threshold == 0.7
        assert result.zero_shift_fallback is True  # unveraendert (kein Flag)

    def test_p2_cli_no_zero_shift_fallback_overrides_config_and_preset(self):
        """P2-2: CLI --no-zero-shift-fallback (False) gewinnt gegen Config
        UND Preset (True); threshold bleibt vom Config-Layer."""
        preset = _preset(RegistrationConfig(zero_shift_fallback=True))
        cfg = AppConfig(registration=RegistrationConfig(zero_shift_fallback=True))
        result = resolve_registration(cfg, preset, cli_zero_shift_fallback=False)
        assert result.zero_shift_fallback is False
        assert result.zero_shift_threshold == 0.05  # unveraendert (kein Flag, V19-FIX-12 0.05)

    def test_p2_cli_zero_shift_flags_none_leave_layers(self):
        """P2-2: Ohne CLI-Flags (None) bleiben die Werte bei
        Preset/Config/Default (kein CLI-Einfluss bei None) — Muster
        test_cli_max_rotation_defaults_unchanged_without_flag."""
        preset = _preset(RegistrationConfig(zero_shift_threshold=0.5))
        result = resolve_registration(
            AppConfig(), preset,
            cli_zero_shift_threshold=None, cli_zero_shift_fallback=None,
        )
        assert result.zero_shift_threshold == 0.5
        assert result.zero_shift_fallback is True


# ═══════════════════════════════════════════════════════════════════
# Loader / astra init (AC-W9-B2)
# ═══════════════════════════════════════════════════════════════════


class TestLoaderInit:
    def test_default_config_contains_registration_block(self):
        """DEFAULT_CONFIG enthaelt den registration-Block mit allen Feldern
        inkl. stack_scale_factor (F-META-1.2, stella Punkt 5)."""
        data = yaml.safe_load(DEFAULT_CONFIG)
        assert "registration" in data
        assert data["registration"]["method"] == "fft"
        assert data["registration"]["max_control_points"] is None
        assert data["registration"]["max_rotation_deg"] == 2.0
        assert data["registration"]["max_scale_dev"] == 0.02
        assert data["registration"]["stack_scale_factor"] == 2.0

    def test_init_writes_registration_block_with_comment(self):
        """`astra init` schreibt registration-Block + Kommentar (AC-W9-B2)."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0, result.output
            content = Path("config.yaml").read_text(encoding="utf-8")
            assert "registration:" in content
            assert 'method: "fft"' in content
            assert "max_control_points: null" in content
            assert "max_rotation_deg: 2.0" in content
            assert "max_scale_dev: 0.02" in content
            assert "stack_scale_factor: 2.0" in content
            # Kommentar: beide Felder erklaert (AC-W9-B2/B4)
            assert "W9-B" in content
            assert "astroalign" in content
            assert "max_control_points" in content
            assert "max_rotation_deg" in content
            assert "max_scale_dev" in content
            assert "stack_scale_factor" in content

    def test_load_config_parses_registration_block(self, tmp_path):
        """load_config parst Config-Datei mit registration-Override
        inkl. stack_scale_factor."""
        cfg_path = _write_default_based_config(
            tmp_path,
            {"registration": {"method": "astroalign", "max_control_points": 40,
                              "max_rotation_deg": 18.0, "max_scale_dev": 0.03,
                              "stack_scale_factor": 3.0}},
        )
        cfg = load_config(cfg_path)
        assert cfg.registration is not None
        assert cfg.registration.method == "astroalign"
        assert cfg.registration.max_control_points == 40
        assert cfg.registration.max_rotation_deg == 18.0
        assert cfg.registration.max_scale_dev == 0.03
        assert cfg.registration.stack_scale_factor == 3.0


# ═══════════════════════════════════════════════════════════════════
# End-to-End: CLI-Flag im process-Command (AC-W9-B1)
# ═══════════════════════════════════════════════════════════════════


class TestCliRegistrationFlag:
    @staticmethod
    def _create_light_target(root: Path) -> Path:
        """Minimales Target mit einem synthetischen Light-FITS (fuer dry-run).
        Discovery laeuft echt (liest Header), Pipeline wird nicht ausgefuehrt."""
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

    def test_cli_flag_appears_in_effective_registration(self, tmp_path):
        """CLI --registration-method astroalign (ohne Config-Block) -> effektive
        Config im Preset verankert, Log `cli.process.registration` zeigt
        method=astroalign (Precedence CLI > Default)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="astroalign")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested",
                  "--registration-method", "astroalign"]
        )
        assert result.exit_code == 0, result.output
        assert '"method": "astroalign"' in result.output
        assert "cli.process.registration" in result.output

    def test_cli_flag_overrides_config(self, tmp_path):
        """Precedence e2e: Config registration.astroalign + CLI fft -> fft
        gewinnt (CLI > Config); max_control_points aus der Config bleibt
        (nur method wird vom CLI ueberschrieben)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="astroalign")
        cfg_path = _write_default_based_config(
            tmp_path,
            {"registration": {"method": "astroalign", "max_control_points": 10}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(cfg_path), "process", str(target), "--dry-run",
             "--from-suggested", "--registration-method", "fft"],
        )
        assert result.exit_code == 0, result.output
        assert '"method": "fft"' in result.output
        assert '"max_control_points": 10' in result.output
        assert "cli.process.registration" in result.output

    def test_config_method_applies_without_cli_flag(self, tmp_path):
        """Config registration.astroalign wirkt ohne CLI-Flag (Config-Ebene
        erreicht die effektive Config). File liefert method=astroalign,
        Config bestätigt — OQ-ENTS-3 A: file null → Config; hier File hat method."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="astroalign")
        cfg_path = _write_default_based_config(
            tmp_path,
            {"registration": {"method": "astroalign"}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["-c", str(cfg_path), "process", str(target), "--dry-run", "--from-suggested"]
        )
        assert result.exit_code == 0, result.output
        assert '"method": "astroalign"' in result.output
        assert "cli.process.registration" in result.output

    def test_cli_max_rotation_appears_in_effective_registration(self, tmp_path):
        """CLI --max-rotation 15 (ohne Config-Block) -> effektive Config zeigt
        max_rotation_deg 15.0; Defaults sonst unveraendert (Precedence CLI >
        Default)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="astroalign")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested",
                  "--registration-method", "astroalign", "--max-rotation", "15"]
        )
        assert result.exit_code == 0, result.output
        assert '"max_rotation_deg": 15.0' in result.output
        assert '"max_scale_dev": 0.02' in result.output
        assert "cli.process.registration" in result.output

    def test_cli_max_rotation_overrides_config(self, tmp_path):
        """Precedence e2e: Config registration.max_rotation_deg 10 + CLI
        --max-rotation 20 -> 20 gewinnt (CLI > Config)."""
        target = self._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="astroalign")
        cfg_path = _write_default_based_config(
            tmp_path,
            {"registration": {"method": "astroalign", "max_rotation_deg": 10.0}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(cfg_path), "process", str(target), "--dry-run",
             "--from-suggested", "--registration-method", "astroalign", "--max-rotation", "20"],
        )
        assert result.exit_code == 0, result.output
        assert '"max_rotation_deg": 20.0' in result.output
        assert "cli.process.registration" in result.output

    def test_cli_default_thresholds_without_flag(self, tmp_path, monkeypatch):
        """Default-Test (Auftrag): OHNE --max-rotation bleiben die Schwellen
        bei 2.0 / 0.02 (keine Verhaltensaenderung fuer bestehende Laeufe).

        Isoliert von CWD/pipeline_root/user_config-Discovery (V19-Config-
        Discovery-Fix, Stella-Smoke 2026-09-04): ohne diese Isolation kann
        eine reale ``~/.config/astra/config.yaml`` (registration.max_rotation_deg)
        auf einem Dev-Rechner in dieses Default-Verhalten hineinregieren.
        """
        target = self._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="astroalign")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config_loader, "_user_config_dir", lambda: tmp_path / "nouser")
        monkeypatch.setattr(config_loader, "_pipeline_root", lambda: tmp_path / "noroot")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested",
                  "--registration-method", "astroalign"]
        )
        assert result.exit_code == 0, result.output
        assert '"max_rotation_deg": 2.0' in result.output
        assert '"max_scale_dev": 0.02' in result.output
        assert "cli.process.registration" in result.output


# ═══════════════════════════════════════════════════════════════════
# Section: rotation_fft (V1.4-2) — Config/CLI
# ═══════════════════════════════════════════════════════════════════


class TestApplyResolverResult:
    """V1.9: Resolver result is propagated onto the effective RegistrationConfig
    through a testable helper (no duplicated production logic in tests)."""

    def test_resolve_registration_config_propagates_equipment_threshold(self):
        """Equipment profile delivers max_exptime_fft_warn to the resolver."""
        equipment = {
            "name": "dwarf_mini",
            "mount_type": "az",
            "preferred_registration": "astroalign",
            "max_rotation_deg": 15.0,
            "max_exptime_fft_warn": 30.0,
        }
        result = resolve_registration_config(AppConfig(), equipment)
        assert result["max_exptime_fft_warn"] == 30.0



class TestRotationFftConfig:
    def test_processing_params_parses_rotation_fft(self):
        """ProcessingParams akzeptiert method=rotation_fft (Literal erweitert,
        Defaults unveraendert)."""
        params = ProcessingParams(
            registration=RegistrationConfig(method="rotation_fft")
        )
        assert params.registration.method == "rotation_fft"
        assert params.registration.max_rotation_deg == 2.0
        assert params.registration.max_scale_dev == 0.02

    def test_app_config_parses_rotation_fft_block(self):
        """AppConfig parst registration.method=rotation_fft aus dem
        Config-Block (V1.4-2-Config-Layer)."""
        cfg = AppConfig(
            registration={"method": "rotation_fft", "max_rotation_deg": 15.0}
        )
        assert cfg.registration is not None
        assert cfg.registration.method == "rotation_fft"
        assert cfg.registration.max_rotation_deg == 15.0

    def test_resolve_rotation_fft_config_overrides_preset(self):
        """resolve_registration: Config method=rotation_fft gewinnt gegen
        Preset (Precedence Config > Preset > Default)."""
        preset = _preset(RegistrationConfig(method="astroalign"))
        cfg = AppConfig(registration=RegistrationConfig(method="rotation_fft"))
        result = resolve_registration(cfg, preset)
        assert result.method == "rotation_fft"

    def test_resolve_cli_rotation_fft_overrides_config(self):
        """resolve_registration: CLI --registration-method rotation_fft gewinnt
        gegen Config UND Preset (Precedence CLI > Config)."""
        preset = _preset(RegistrationConfig(method="astroalign"))
        cfg = AppConfig(registration=RegistrationConfig(method="astroalign"))
        result = resolve_registration(cfg, preset, cli_method="rotation_fft")
        assert result.method == "rotation_fft"

    def test_resolve_cli_rotation_fft_overrides_default(self):
        """resolve_registration: CLI rotation_fft ohne Config-/Preset-Block ->
        Default-Layer wird ueberschrieben."""
        result = resolve_registration(AppConfig(), _preset(),
                                      cli_method="rotation_fft")
        assert result.method == "rotation_fft"

    def test_load_config_parses_rotation_fft(self, tmp_path):
        """load_config parst Config-Datei mit method=rotation_fft."""
        cfg_path = _write_default_based_config(
            tmp_path,
            {"registration": {"method": "rotation_fft",
                              "max_rotation_deg": 15.0}},
        )
        cfg = load_config(cfg_path)
        assert cfg.registration is not None
        assert cfg.registration.method == "rotation_fft"
        assert cfg.registration.max_rotation_deg == 15.0

    def test_cli_flag_rotation_fft_appears_in_effective_registration(
        self, tmp_path,
    ):
        """CLI --registration-method rotation_fft (ohne Config-Block) ->
        effektive Config im Preset verankert (Precedence CLI > Default)."""
        target = TestCliRegistrationFlag._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="rotation_fft")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested",
                  "--registration-method", "rotation_fft"]
        )
        assert result.exit_code == 0, result.output
        assert '"method": "rotation_fft"' in result.output
        assert "cli.process.registration" in result.output

    def test_cli_flag_rotation_fft_overrides_config(self, tmp_path):
        """Precedence e2e: Config registration.astroalign + CLI rotation_fft ->
        rotation_fft gewinnt (CLI > Config)."""
        target = TestCliRegistrationFlag._create_light_target(tmp_path)
        write_default_suggested(target, registration_method="astroalign")
        cfg_path = _write_default_based_config(
            tmp_path,
            {"registration": {"method": "astroalign"}},
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(cfg_path), "process", str(target), "--dry-run",
             "--from-suggested", "--registration-method", "rotation_fft"],
        )
        assert result.exit_code == 0, result.output
        assert '"method": "rotation_fft"' in result.output
        assert "cli.process.registration" in result.output
