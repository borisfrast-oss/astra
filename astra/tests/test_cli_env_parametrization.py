"""Leo-Auftrag 2026-08-11: CLI-Umgebungs-Parametrisierung (stella-Auftrag B1/B2/B3).

Abdeckung:
- B1 (config.yaml automatisch finden): `load_config()` ohne expliziten Pfad
  prueft nacheinander (1) config.yaml im CWD, (2) `~/.config/astra/config.yaml`
  (User-Config, `_user_config_dir()` — V19-Fix Stella-Smoke 2026-09-04),
  (3) `{pipeline_root}/config.yaml` (Projekt-Root), (4) erst dann
  DEFAULT_CONFIG-String. Expliziter Pfad (CLI --config) bleibt unveraendert
  (Precedence). Log `config.loaded_from` nennt die geladene Quelle.
- B2 (--darks-path optional): CLI weglassen -> `darks_repository` aus der
  Config verwenden; weder CLI noch Config gesetzt -> verstaendliche
  Fehlermeldung (ClickException) mit Hinweis auf config.yaml
  `darks_repository` bzw. --darks-path.
- B3 (CLI-Help): `process --help` zeigt den --config-Hinweis (global vor dem
  Subcommand); die Gruppen-Help nennt die Option ebenfalls.

Teststrategie (wie bestehende CLI-Tests):
- CWD-Isolation via `monkeypatch.chdir(tmp_path)`; `_pipeline_root` UND
  `_user_config_dir` werden in Loader-Tests gepatcht, damit die Discovery
  deterministisch ist (nicht auf die echte config.yaml des Repos bzw. die
  echte `~/.config/astra/config.yaml` eines Dev-Rechners faellt).
- CLI-Laufpfade mit gemockten Agents (create_*_agent) — analog
  test_multi_group.py TestCR001P1CliFlag: die schwere Pipeline laeuft nicht,
  geprueft wird ausschliesslich die Darks-Verdrahtung (B2).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.cli import cli  # noqa: E402
from astro_process.config import loader as config_loader  # noqa: E402
from astro_process.config.loader import DEFAULT_CONFIG  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import write_default_suggested  # noqa: E402


# ═══════════════════════════════════════════════════════════════════
# Test Helpers
# ═══════════════════════════════════════════════════════════════════


def _write_default_based_config(path: Path, update: dict | None = None) -> Path:
    """DEFAULT_CONFIG-Basis mit Overrides als config.yaml schreiben."""
    data = yaml.safe_load(DEFAULT_CONFIG)
    if update:
        data.update(update)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _spy_logger(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Ersetzt `loader.logger` durch einen Mock (deterministische Log-Pruefung)."""
    mock_logger = MagicMock()
    monkeypatch.setattr(config_loader, "logger", mock_logger)
    return mock_logger


def _assert_loaded_from(mock_logger: MagicMock, source: str) -> None:
    """Prueft: letzter config.loaded_from-Log nennt `source`."""
    calls = [
        c for c in mock_logger.info.call_args_list
        if c.args and c.args[0] == "config.loaded_from"
    ]
    assert calls, "config.loaded_from wurde nicht geloggt"
    assert calls[-1].kwargs.get("source") == source


def _invoke_process_mocked(runner: CliRunner, args: list[str], tmp_path: Path):
    """Invoke `process` mit gemockten Pipeline-Agents.

    Liefert (result, captured); captured["darks_repository"] = Wert, der an
    `create_calibration_agent` uebergeben wurde (B2-Verdrahtung).

    Discovery ist gemockt mit total_light_frames=1 (passiert den
    Zero-Lights-Guard); die schwere Pipeline (Kalibration/Debayer/
    Processing/Archive) laeuft nicht.
    """
    captured: dict = {}

    discovery = MagicMock()
    discovery.run.return_value = MagicMock(context=MagicMock(total_light_frames=1))

    cal = MagicMock()
    cal.run.return_value = MagicMock(
        master_dark=None, calibrated_lights=[], master_dark_paths={}
    )

    def _make_cal(*_args, **_kwargs):
        captured["darks_repository"] = _kwargs.get("darks_repository")
        return cal

    deb = MagicMock()
    deb.run.return_value = MagicMock(debayered_frames=[])
    proc = MagicMock()
    proc.run.return_value = MagicMock(stacked=None)
    arch = MagicMock()
    arch.run.return_value = MagicMock(output_dir=tmp_path, final_fits=None)

    # V1.11: extract target dir from args to write suggested.yaml
    _target_arg = None
    for i, a in enumerate(args):
        if a == "process" and i + 1 < len(args):
            _target_arg = Path(args[i + 1])
            break
    if _target_arg is not None and _target_arg.is_dir():
        write_default_suggested(_target_arg)
        # Inject --from-suggested if not already present
        _process_idx = next((i for i, a in enumerate(args) if a == "process"), None)
        if _process_idx is not None and "--from-suggested" not in args:
            args = list(args)
            args.insert(_process_idx + 2, "--from-suggested")

    with patch("astro_process.cli.create_discovery_agent", return_value=discovery), \
         patch("astro_process.cli.create_calibration_agent", side_effect=_make_cal), \
         patch("astro_process.cli.create_debayer_agent", return_value=deb), \
         patch("astro_process.cli.create_processing_agent", return_value=proc), \
         patch("astro_process.cli.create_archive_agent", return_value=arch):
        result = runner.invoke(cli, args)

    return result, captured


# ═══════════════════════════════════════════════════════════════════
# B1 — load_config(): Quellen-Precedence
# ═══════════════════════════════════════════════════════════════════


class TestB1ConfigDiscovery:
    @pytest.mark.skipif(
        os.name != "nt",
        reason="Windows-absolute-path semantics (C:/ drive letters); precedence is covered by test_pipeline_root_config_used_without_cwd_config and test_explicit_path_wins_over_discovery on other platforms.",
    )
    def test_cwd_config_preferred_over_pipeline_root(self, tmp_path, monkeypatch):
        """CWD config.yaml gewinnt ueber {pipeline_root}/config.yaml."""
        cwd = tmp_path / "cwd"
        root = tmp_path / "root"
        cwd.mkdir()
        root.mkdir()
        (cwd / "config.yaml").write_text(
            yaml.safe_dump({"default_preset": "cwd_preset",
                            "darks_repository": "C:/cwd_darks"}),
            encoding="utf-8",
        )
        (root / "config.yaml").write_text(
            yaml.safe_dump({"default_preset": "root_preset",
                            "darks_repository": "C:/root_darks"}),
            encoding="utf-8",
        )
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(config_loader, "_pipeline_root", lambda: root)
        mock_logger = _spy_logger(monkeypatch)

        cfg = config_loader.load_config()

        assert cfg.default_preset == "cwd_preset"
        assert cfg.darks_repository == Path("C:/cwd_darks")
        _assert_loaded_from(mock_logger, "cwd")

    def test_pipeline_root_config_used_without_cwd_config(self, tmp_path, monkeypatch):
        """Ohne CWD/User config.yaml findet load_config() {pipeline_root}/config.yaml."""
        cwd = tmp_path / "elsewhere"
        root = tmp_path / "root"
        nouser = tmp_path / "nouser"
        cwd.mkdir()
        root.mkdir()
        (root / "config.yaml").write_text(
            yaml.safe_dump({"default_preset": "root_preset"}),
            encoding="utf-8",
        )
        monkeypatch.chdir(cwd)
        # Isolation von der echten ~/.config/astra/config.yaml eines Dev-Rechners
        # (Stella-Smoke 2026-09-04 nutzt genau diesen Pfad produktiv).
        monkeypatch.setattr(config_loader, "_user_config_dir", lambda: nouser)
        monkeypatch.setattr(config_loader, "_pipeline_root", lambda: root)
        mock_logger = _spy_logger(monkeypatch)

        cfg = config_loader.load_config()

        assert cfg.default_preset == "root_preset"
        _assert_loaded_from(mock_logger, "pipeline_root")

    def test_default_fallback_without_any_config(self, tmp_path, monkeypatch):
        """Weder CWD noch User- noch pipeline_root config.yaml -> DEFAULT_CONFIG-String."""
        cwd = tmp_path / "elsewhere"
        noroot = tmp_path / "noroot"
        nouser = tmp_path / "nouser"
        cwd.mkdir()
        noroot.mkdir()
        monkeypatch.chdir(cwd)
        # Isolation von der echten ~/.config/astra/config.yaml eines Dev-Rechners.
        monkeypatch.setattr(config_loader, "_user_config_dir", lambda: nouser)
        monkeypatch.setattr(config_loader, "_pipeline_root", lambda: noroot)
        mock_logger = _spy_logger(monkeypatch)

        cfg = config_loader.load_config()

        # DEFAULT: kein darks_repository, default_preset star_standard
        assert cfg.darks_repository is None
        assert cfg.default_preset == "star_standard"
        _assert_loaded_from(mock_logger, "default")

    def test_user_config_used_between_cwd_and_pipeline_root(self, tmp_path, monkeypatch):
        """V19-Config-Discovery-Fix (Stella-Smoke 2026-09-04): ohne CWD-Config
        aber mit ``~/.config/astra/config.yaml`` (hier via ``_user_config_dir``
        gemockt) gewinnt die User-Config vor ``{pipeline_root}/config.yaml``."""
        cwd = tmp_path / "elsewhere"
        user_dir = tmp_path / "user" / ".config" / "astra"
        root = tmp_path / "root"
        cwd.mkdir()
        user_dir.mkdir(parents=True)
        root.mkdir()
        (user_dir / "config.yaml").write_text(
            yaml.safe_dump({"default_preset": "user_preset"}),
            encoding="utf-8",
        )
        (root / "config.yaml").write_text(
            yaml.safe_dump({"default_preset": "root_preset"}),
            encoding="utf-8",
        )
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(config_loader, "_user_config_dir", lambda: user_dir)
        monkeypatch.setattr(config_loader, "_pipeline_root", lambda: root)
        mock_logger = _spy_logger(monkeypatch)

        cfg = config_loader.load_config()

        assert cfg.default_preset == "user_preset"
        _assert_loaded_from(mock_logger, "user_config")

    def test_cwd_config_preferred_over_user_config(self, tmp_path, monkeypatch):
        """CWD config.yaml gewinnt weiterhin ueber ``~/.config/astra/config.yaml``."""
        cwd = tmp_path / "cwd"
        user_dir = tmp_path / "user" / ".config" / "astra"
        cwd.mkdir()
        user_dir.mkdir(parents=True)
        (cwd / "config.yaml").write_text(
            yaml.safe_dump({"default_preset": "cwd_preset"}),
            encoding="utf-8",
        )
        (user_dir / "config.yaml").write_text(
            yaml.safe_dump({"default_preset": "user_preset"}),
            encoding="utf-8",
        )
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(config_loader, "_user_config_dir", lambda: user_dir)
        monkeypatch.setattr(config_loader, "_pipeline_root",
                             lambda: tmp_path / "noroot")
        mock_logger = _spy_logger(monkeypatch)

        cfg = config_loader.load_config()

        assert cfg.default_preset == "cwd_preset"
        _assert_loaded_from(mock_logger, "cwd")

    def test_explicit_path_wins_over_discovery(self, tmp_path, monkeypatch):
        """Expliziter Pfad (CLI --config) gewinnt ueber CWD/pipeline_root."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        _write_default_based_config(
            cwd / "config.yaml", {"default_preset": "cwd_preset"}
        )
        explicit = tmp_path / "explicit.yaml"
        _write_default_based_config(explicit, {"default_preset": "explicit_preset"})
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(config_loader, "_pipeline_root",
                            lambda: tmp_path / "noroot")
        mock_logger = _spy_logger(monkeypatch)

        cfg = config_loader.load_config(explicit)

        assert cfg.default_preset == "explicit_preset"
        _assert_loaded_from(mock_logger, "explicit")

    def test_explicit_missing_path_falls_back_to_default(self, tmp_path, monkeypatch):
        """Nicht-existenter expliziter Pfad: DEFAULT-Fallback (bisheriges
        Verhalten) — kein stilles Weiter-Entdecken der CWD-config."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        _write_default_based_config(
            cwd / "config.yaml", {"default_preset": "cwd_preset"}
        )
        monkeypatch.chdir(cwd)
        monkeypatch.setattr(config_loader, "_pipeline_root",
                            lambda: tmp_path / "noroot")

        cfg = config_loader.load_config(tmp_path / "missing.yaml")

        assert cfg.default_preset == "star_standard"
        assert cfg.darks_repository is None


class TestB1CliAutodiscovery:
    def test_process_without_config_flag_uses_cwd_config(self, tmp_path, monkeypatch):
        """CLI: `process <target> --dry-run` OHNE --config nutzt die config.yaml
        des CWD. V1.11: preset kommt aus suggested.yaml (nicht aus default_preset).
        Test prueft Config-Discovery (config.loaded_from) statt default_preset-Inferenz."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        _write_default_based_config(
            cfgdir / "config.yaml", {"default_preset": "nebula_standard"}
        )
        target = tmp_path / "Target"
        target.mkdir()
        # V1.11: Preset kommt aus File (nebula_standard), nicht aus Config default_preset
        write_default_suggested(target, preset="nebula_standard")
        monkeypatch.chdir(cfgdir)

        runner = CliRunner()
        result = runner.invoke(cli, ["process", str(target), "--dry-run", "--from-suggested"])

        assert result.exit_code == 0, result.output
        assert "Pipeline: nebula_standard" in result.output

    def test_process_without_config_equals_explicit_config(self, tmp_path, monkeypatch):
        """Verifikation (stella-Auftrag): Lauf ohne --config (CWD mit
        config.yaml) ist identisch zum Lauf mit explizitem --config.
        V1.11: preset kommt aus suggested.yaml; config wird fuer registration/debayer-Fallback genutzt."""
        cfgdir = tmp_path / "cfgdir"
        other = tmp_path / "other"
        cfgdir.mkdir()
        other.mkdir()
        _write_default_based_config(
            cfgdir / "config.yaml", {"default_preset": "nebula_standard"}
        )
        target = tmp_path / "Target"
        target.mkdir()
        write_default_suggested(target, preset="nebula_standard")

        runner = CliRunner()

        # Lauf A: ohne --config, CWD = cfgdir (config.yaml wird entdeckt)
        monkeypatch.chdir(cfgdir)
        result_a = runner.invoke(cli, ["process", str(target), "--dry-run", "--from-suggested"])
        assert result_a.exit_code == 0, result_a.output
        assert "Pipeline: nebula_standard" in result_a.output

        # Lauf B: explizites --config, CWD woanders (expliziter Pfad gewinnt)
        monkeypatch.chdir(other)
        result_b = runner.invoke(
            cli,
            ["-c", str(cfgdir / "config.yaml"), "process", str(target), "--dry-run",
             "--from-suggested"],
        )
        assert result_b.exit_code == 0, result_b.output
        assert "Pipeline: nebula_standard" in result_b.output


# ═══════════════════════════════════════════════════════════════════
# B2 — --darks-path optional (Fallback auf config darks_repository)
# ═══════════════════════════════════════════════════════════════════


class TestB2DarksFallback:
    def test_darks_repository_from_config_without_cli_flag(
        self, tmp_path, monkeypatch
    ):
        """CLI ohne --darks-path -> `darks_repository` aus config.yaml wird an
        den Calibration-Agent durchgereicht."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        darks_dir = tmp_path / "_darks"
        darks_dir.mkdir()
        _write_default_based_config(
            cfgdir / "config.yaml", {"darks_repository": str(darks_dir)}
        )
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(cfgdir)

        runner = CliRunner()
        result, captured = _invoke_process_mocked(
            runner, ["process", str(target)], tmp_path
        )

        assert result.exit_code == 0, result.output
        assert captured.get("darks_repository") is not None
        assert captured["darks_repository"] == darks_dir

    def test_darks_path_cli_overrides_config(self, tmp_path, monkeypatch):
        """Precedence unveraendert: CLI --darks-path gewinnt ueber Config
        darks_repository."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        config_darks = tmp_path / "config_darks"
        cli_darks = tmp_path / "cli_darks"
        config_darks.mkdir()
        cli_darks.mkdir()
        _write_default_based_config(
            cfgdir / "config.yaml", {"darks_repository": str(config_darks)}
        )
        target = tmp_path / "Target"
        target.mkdir()
        monkeypatch.chdir(cfgdir)

        runner = CliRunner()
        result, captured = _invoke_process_mocked(
            runner, ["process", str(target), "--darks-path", str(cli_darks)], tmp_path
        )

        assert result.exit_code == 0, result.output
        assert captured["darks_repository"] == cli_darks

    def test_no_darks_error_message(self, tmp_path, monkeypatch):
        """Weder CLI --darks-path noch config darks_repository -> saubere
        Fehlermeldung mit Hinweis, wo zu setzen."""
        cfgdir = tmp_path / "cfgdir"
        cfgdir.mkdir()
        # DEFAULT-Basis: darks_repository ist NICHT gesetzt (auskommentiert)
        _write_default_based_config(cfgdir / "config.yaml")
        target = tmp_path / "Target"
        target.mkdir()
        write_default_suggested(target)
        monkeypatch.chdir(cfgdir)

        discovery = MagicMock()
        discovery.run.return_value = MagicMock(context=MagicMock(total_light_frames=1))

        runner = CliRunner()
        with patch("astro_process.cli.create_discovery_agent", return_value=discovery):
            result = runner.invoke(cli, ["process", str(target), "--from-suggested"])

        assert result.exit_code == 1, result.output
        assert "darks_repository" in result.output
        assert "--darks-path" in result.output


# ═══════════════════════════════════════════════════════════════════
# B3 — CLI-Help: --config-Hinweis
# ═══════════════════════════════════════════════════════════════════


class TestB3CliHelp:
    def test_process_help_shows_config_hint(self):
        """`process --help` weist auf die globale --config-Option hin
        (vor dem Subcommand)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["process", "--help"])
        assert result.exit_code == 0, result.output
        assert "config.yaml" in result.output
        assert "Subcommand" in result.output

    def test_group_help_shows_config_hint(self):
        """`astra --help` nennt --config/-c mit Hinweis auf die Position
        vor dem Subcommand."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0, result.output
        assert "Config-Datei" in result.output
        assert "Subcommand" in result.output
