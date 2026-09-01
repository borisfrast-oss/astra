"""Tests for T2: --no-calib flag (T2a) and `astra doctor` command (T2b).

Teststrategie (robuster Weg, dokumentiert):
- Die synthetischen Light-FITS sind bewusst 2D (H×W, gerade) und NICHT 3D-RGB:
  `astro_process.core.debayer.batch_debayer` debayert echte Bayer-CFA-Daten via
  Superpixel (2D → 3D); 3D-RGB-Eingaben wuerden dort mit ValueError scheitern.
- `ProcessingAgent.run` wird gepatcht (MagicMock → ProcessingResult()), damit
  die schwere Pipeline (Registration/Stacking/PCC mit GAIA-Netzwerk) im
  Unit-Test nicht laeuft. Geprueft wird ausschliesslich der Calibration-Skip.
- `CalibrationAgent.run` wird mit einem Mock gepatcht, der AssertionError
  wirft, wenn er dennoch aufgerufen wird → beweist den Skip (--no-calib).
- `--dry-run` wird bewusst NICHT genutzt (skippt die Pipeline vor Calibration).
- Im doctor-Test wird `astro_process.cli._run_with_timeout` gemockt, damit
  kein echtes GAIA-Netzwerk im Unit-Test laeuft (deterministisch, schnell).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import yaml
from astropy.io import fits
from click.testing import CliRunner

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.cli import cli
from astro_process.config.models import AppConfig
from astro_process.config.loader import DEFAULT_CONFIG
from astro_process.agents.calibration import CalibrationAgent, CalibrationResult
from astro_process.agents.processing_agent import ProcessingAgent, ProcessingResult


# ═══════════════════════════════════════════════════════════════════
# Test Helpers
# ═══════════════════════════════════════════════════════════════════


def _create_light_fits(path: Path, shape=(64, 64), value=50.0,
                       exptime: float = 15.0, gain: int = 60, seed: int = 7) -> Path:
    """Minimales synthetisches 2D-Light-FITS (Bayer-CFA-artig).

    Bewusst 2D und mit geraden Dimensionen: batch_debayer (Superpixel) kann
    echte 2D-Bayer-Daten verarbeiten — im Gegensatz zu 3D-RGB-FITS.
    """
    rng = np.random.RandomState(seed)
    data = (value + rng.uniform(0, 10, shape)).astype(np.float32)
    hdu = fits.PrimaryHDU(data)
    hdu.header["EXPTIME"] = float(exptime)
    hdu.header["GAIN"] = int(gain)
    # V1.6-1 (SSOT-A): Mandatory fields for light frames
    hdu.header["OBJECT"] = "M 27"
    hdu.header["CCD-TEMP"] = -10
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def _build_light_target(root: Path, name: str = "TestTarget",
                        count: int = 3, shape=(64, 64)) -> Path:
    """Target mit Lights (konventionell im lights-Ordner), OHNE Darks/Flats/Bias.

    Punkt 3 (Input-Staging): Die Pipeline liest NUR die konventionellen
    Input-Ordner — FITS direkt im Target-Root werden nicht mehr erkannt.
    """
    target = root / name
    for i in range(count):
        _create_light_fits(
            target / "lights" / f"light_{i:04d}.fits", shape=shape, seed=7 + i
        )
    return target


def _default_config_yaml(data_root: str = ".") -> str:
    """DEFAULT_CONFIG mit ueberschriebenem data_root (fuer doctor-Tests)."""
    data = yaml.safe_load(DEFAULT_CONFIG)
    data["data_root"] = data_root
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


# ═══════════════════════════════════════════════════════════════════
# T2a — --no-calib Flag
# ═══════════════════════════════════════════════════════════════════


class TestNoCalibFlag:
    def test_no_calib_config_default_false(self):
        """AppConfig-Default: no_calib ist False (Top-Level neben use_flats/use_bias)."""
        assert AppConfig().no_calib is False

    def test_init_output_contains_no_calib(self):
        """`astra init` erzeugt config.yaml mit dem no_calib-Block.

        Hinweis: init gibt auf stdout nur "Created config.yaml" aus; der
        no_calib-Block steckt in der erzeugten Datei (Default-Konfiguration,
        Aequivalent der Init-Ausgabe) — genau das wird hier geprueft.
        """
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
            config_path = Path("config.yaml")
            assert config_path.exists()
            content = config_path.read_text(encoding="utf-8")
            assert "no_calib" in content
            assert "no_calib: false" in content

    def test_no_calib_skips_calibration(self, tmp_path):
        """--no-calib ueberspringt die Kalibrationsphase vollstaendig.

        Robust: CalibrationAgent.run wirft AssertionError, wenn er dennoch
        aufgerufen wird (Sicherheitsnetz); ProcessingAgent.run ist abgekuerzt
        (sonst liefe PCC/GAIA-Netzwerk). Debayer laeuft ECHT auf den
        synthetischen 2D-Lights (klein, schnell) — beweist, dass die
        Raw-Lights direkt zu Debayer gehen.
        """
        target = _build_light_target(tmp_path)
        runner = CliRunner()

        def _fail(*args, **kwargs):
            raise AssertionError("CalibrationAgent.run darf mit --no-calib nicht laufen")

        with patch.object(CalibrationAgent, "run", side_effect=_fail) as mock_cal, \
             patch.object(ProcessingAgent, "run", return_value=ProcessingResult()):
            result = runner.invoke(cli, ["process", str(target), "--no-calib"])

        assert result.exit_code == 0, result.output
        mock_cal.assert_not_called()
        assert "Calibration: skipped" in result.output

    def test_no_calib_with_darks_not_required(self, tmp_path):
        """Target OHNE Darks/Flats/Bias + --no-calib → kein Fehler."""
        target = _build_light_target(tmp_path)
        runner = CliRunner()
        with patch.object(ProcessingAgent, "run", return_value=ProcessingResult()):
            result = runner.invoke(cli, ["process", str(target), "--no-calib"])
        assert result.exit_code == 0, result.output
        assert "Calibration: skipped" in result.output

    def test_no_calib_flag_overrides_config(self, tmp_path):
        """CLI --calib gewinnt gegen Config no_calib: true → Calibration laeuft."""
        target = _build_light_target(tmp_path)
        config_path = tmp_path / "config.yaml"
        data = yaml.safe_load(DEFAULT_CONFIG)
        data["no_calib"] = True
        # Leo-Auftrag 2026-08-11 (B2): --darks-path optional — Kalibration
        # benoetigt einen Darks-Pfad; ohne CLI-Flag kommt er aus der Config.
        data["darks_repository"] = str(tmp_path / "_darks")
        (tmp_path / "_darks").mkdir(exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        runner = CliRunner()

        cal_result = CalibrationResult(
            working_dir=target / "generated",
            calibrated_lights=sorted((target / "lights").glob("light_*.fits")),
        )
        with patch.object(CalibrationAgent, "run", return_value=cal_result) as mock_cal, \
             patch.object(ProcessingAgent, "run", return_value=ProcessingResult()):
            result = runner.invoke(cli, ["-c", str(config_path), "process", str(target), "--calib"])

        assert result.exit_code == 0, result.output
        mock_cal.assert_called_once()
        assert "Calibration: skipped" not in result.output


# ═══════════════════════════════════════════════════════════════════
# T2b — astra doctor
# ═══════════════════════════════════════════════════════════════════


class TestDoctorCommand:
    def test_doctor_runs_ok(self):
        """Doctor laeuft durch: Exit 0 (alle OK) oder 1 (nur WARN).

        GAIA-Netzwerkzugriff wird via _run_with_timeout-Mock umgangen
        (deterministisch, kein echtes Netzwerk im Unit-Test). data_root zeigt
        auf das isolierte cwd → Disk/Pfad-Checks sind gueltig.
        """
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("config.yaml").write_text(
                _default_config_yaml("."), encoding="utf-8")
            with patch("astro_process.cli._run_with_timeout", return_value=MagicMock()):
                result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])

        assert result.exit_code in (0, 1), result.output
        assert any(p in result.output for p in ("[OK]", "[WARN]", "[FAIL]"))
        assert "Doctor:" in result.output

    def test_doctor_critical_failure_exit_2(self):
        """Python < 3.11 (gepatcht) → kritischer FAIL → Exit-Code 2."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("config.yaml").write_text(
                _default_config_yaml("."), encoding="utf-8")
            with patch("astro_process.cli._run_with_timeout", return_value=MagicMock()), \
                 patch("astro_process.cli.sys.version_info", (3, 9)):
                result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])

        assert result.exit_code == 2, result.output
        assert "[FAIL]" in result.output

    def test_doctor_read_only(self):
        """Doctor erzeugt keine Pipeline-Artefakte (kein generated/, kein agent-log)."""
        runner = CliRunner()
        with runner.isolated_filesystem() as fs:
            Path("config.yaml").write_text(
                _default_config_yaml("."), encoding="utf-8")
            with patch("astro_process.cli._run_with_timeout", return_value=MagicMock()):
                result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])
            assert result.exit_code in (0, 1), result.output

            fs_path = Path(fs)
            generated_dirs = [p for p in fs_path.rglob("generated") if p.is_dir()]
            assert generated_dirs == []
            assert not (fs_path / "agent-log.yaml").exists()

    # ═══════════════════════════════════════════════════════════════
    # M2 (ray-Review v1.1): ImportError aus dem GAIA-Query-Thread -> WARN
    # ═══════════════════════════════════════════════════════════════

    def test_doctor_gaia_import_error_in_thread_is_warn(self):
        """ImportError (fehlendes astroquery-Submodul) im GAIA-Thread -> WARN, Exit 1.

        Simuliert den M2-Fall: Der Worker-Thread von _run_with_timeout wirft
        einen ImportError (lazy astroquery-Submodul fehlt). Doctor darf NICHT
        crashen, sondern meldet die GAIA-Diagnose als WARN — konsistent mit
        der Optional-Dependency-Philosophie (PCC-Fallback aktiv).
        """
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("config.yaml").write_text(
                _default_config_yaml("."), encoding="utf-8")
            with patch("astro_process.cli._run_with_timeout",
                       side_effect=ImportError("No module named 'astroquery.utils.tap'")):
                result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])

        assert result.exit_code == 1, result.output
        assert "[WARN]" in result.output
        assert "gaia" in result.output.lower()

    # ═══════════════════════════════════════════════════════════════
    # M9 (ray-Review v1.1): doctor-Timeout-Präzisierung
    # ═══════════════════════════════════════════════════════════════

    def test_doctor_timeout_message_clarifies_query_only(self):
        """Timeout-Meldung im doctor-Befehl praecisiert 'Query Timeout'."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            config_path = Path("config.yaml")
            config_path.write_text(_default_config_yaml("."), encoding="utf-8")

            def timeout_fn(*args, **kwargs):
                raise TimeoutError("simulated timeout")

            with patch("astro_process.cli._run_with_timeout", side_effect=timeout_fn):
                result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])

        assert "Query Timeout" in result.output
        assert "GAIA Timeout nach 10s" not in result.output

