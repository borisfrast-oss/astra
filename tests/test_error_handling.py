"""T5: Error-Handling Basics — keine stillen Fehler (E1).

Testet die per-Agent-Strategien aus der T5-Aufgabe auf den bekannten
stillen Fehlerstellen:

- fits_parser: kein ``print(...)`` mehr, sondern structlog
  (``discovery.frame_skip``); korrupte Lights werden uebersprungen.
- discovery: einzelnes korruptes Light -> Rest-Scan laeuft weiter; wenn
  ALLE Lights einer Gruppe unlesbar sind -> ``discovery.group_empty``.
- calibration: Master-Build (Stacking) einer Gruppe schlaegt fehl ->
  ``calibration.master_build_failed`` + dark_source "none", Rest laeuft.
- debayer: korrupter Frame -> ``debayer.frame_failed`` + Ueberspringen;
  alle Frames fehlgeschlagen -> ``debayer.empty_result`` + ValueError.
- cli merge: kein silent except mehr (klare Fehlermeldung, Exit-Code != 0).

Teststrategie: synthetische Fixtures aus ``tests/synthetic.py`` (T4, fertig)
in kleiner Aufloesung (32x32) fuer Geschwindigkeit; korrupte Dateien werden
durch Ueberschreiben mit Muellbytes erzeugt. Fuer deterministisch schwer
erzeugbare Pfade (Stacking-Fehler) wird der Handler direkt angesprochen
bzw. die Logger-Aufrufe via ``unittest.mock.patch`` verifiziert (kein
Netzwerk, kein GAIA).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from astropy.io import fits
from click.testing import CliRunner

# ── Ensure the generator module is importable (T4, fertig) ─────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
# ── Ensure src is on the path ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from conftest import write_default_suggested  # noqa: E402

import synthetic

from astro_process.agents.archive import ArchiveAgent
from astro_process.agents.calibration import CalibrationAgent, CalibrationResult
from astro_process.agents.debayer_agent import DebayerAgent
from astro_process.cli import cli
from astro_process.core.fits_parser import build_observation_context
from astro_process.core.pcc import _run_with_timeout, GAIA_QUERY_TIMEOUT_SECONDS
from astro_process.models.core import ObservationContext, ObservationTarget


def _make_light_context(dataset) -> ObservationContext:
    """Minimaler ObservationContext (Debayer nutzt nur target.name)."""
    return ObservationContext(
        target=ObservationTarget(name="TestTarget"),
        source_path=dataset.root,
    )


class TestErrorHandling:
    """T5: keine stillen Fehler — skip/fallback/abort mit structlog-Kontext."""

    # ═══════════════════════════════════════════════════════════════
    # fits_parser: print -> structlog
    # ═══════════════════════════════════════════════════════════════

    def test_fits_parser_no_print(self, tmp_path, monkeypatch):
        """Korruptes FITS: kein print()-Aufruf, sondern discovery.frame_skip."""
        dataset = synthetic.generate_dataset(
            tmp_path,
            n_lights_per_group=2, exposures=(15,), gains=(60,),
            size=(32, 32), channels=1, seed=42,
        )
        bad = dataset.lights[0]
        bad.write_bytes(b"not-a-fits-file")

        def _no_print(*args, **kwargs):
            raise AssertionError(
                "print() wurde aufgerufen — fits_parser muss structlog nutzen"
            )

        monkeypatch.setattr("builtins.print", _no_print)

        with patch("astro_process.core.fits_parser.logger") as mock_logger:
            context = build_observation_context(dataset.root)

        # Rest-Scan laeuft weiter: 2 Lights, 1 korrupt -> 1 verbleibt
        assert context.total_light_frames == 1

        # Strukturierter Log-Aufruf statt stillem Schlucken
        mock_logger.warning.assert_called_once()
        event, kwargs = (
            mock_logger.warning.call_args.args[0],
            mock_logger.warning.call_args.kwargs,
        )
        assert event == "discovery.frame_skip"
        assert str(kwargs["path"]) == str(bad)
        assert "reason" in kwargs

    def test_fits_parser_happy_path_no_print(self, tmp_path, monkeypatch):
        """Auch im Happy Path (alle Frames gueltig) kein print()."""
        dataset = synthetic.generate_dataset(
            tmp_path,
            n_lights_per_group=2, exposures=(15,), gains=(60,),
            size=(32, 32), channels=1, seed=42,
        )

        def _no_print(*args, **kwargs):
            raise AssertionError("print() wurde aufgerufen")

        monkeypatch.setattr("builtins.print", _no_print)

        context = build_observation_context(dataset.root)

        assert context.total_light_frames == 2
        assert len(context.get_lights().frames) == 2

    # ═══════════════════════════════════════════════════════════════
    # discovery: korrupte Lights ueberspringen, group_empty
    # ═══════════════════════════════════════════════════════════════

    def test_discovery_skips_corrupt_light(self, tmp_path):
        """Ein korruptes Light -> die anderen Lights bleiben enthalten, kein Crash."""
        dataset = synthetic.generate_dataset(
            tmp_path,
            n_lights_per_group=3, exposures=(15,), gains=(60,),
            size=(32, 32), channels=1, seed=42,
        )
        bad = dataset.lights[0]
        bad.write_bytes(b"corrupt-garbage-not-fits")

        with patch("astro_process.core.fits_parser.logger") as mock_logger:
            context = build_observation_context(dataset.root)

        lights = context.get_lights()
        assert len(lights.frames) == 2
        assert bad not in [f.path for f in lights.frames]
        assert context.total_light_frames == 2

        # Warnung mit Kontext statt stillem Schlucken
        warns = [
            c for c in mock_logger.warning.call_args_list
            if c.args and c.args[0] == "discovery.frame_skip"
        ]
        assert len(warns) == 1
        assert str(warns[0].kwargs["path"]) == str(bad)

    def test_discovery_group_empty_all_frames_unreadable(self, tmp_path):
        """ALLE Lights einer Gruppe unlesbar -> discovery.group_empty, kein Crash."""
        root = tmp_path / "target"
        root.mkdir()
        # Dateinamen im Dwarf3/M13-Schema, damit die Gruppe aus dem Namen
        # ableitbar ist (Header ist unlesbar).
        for stem in ("15s60", "60s60"):
            (root / f"Corrupt_{stem}_Astro_20260717-231509939_33C.fits").write_bytes(
                b"garbage-not-fits"
            )

        with patch("astro_process.core.fits_parser.logger") as mock_logger:
            context = build_observation_context(root)

        assert context.total_light_frames == 0
        error_calls = [
            c for c in mock_logger.error.call_args_list
            if c.args and c.args[0] == "discovery.group_empty"
        ]
        assert len(error_calls) == 2
        assert {c.kwargs["group"] for c in error_calls} == {"15s60", "60s60"}
        assert all(c.kwargs["failed"] == 1 for c in error_calls)

    # ═══════════════════════════════════════════════════════════════
    # calibration: Master-Build-Fehler -> dark_source "none", Rest laeuft
    # ═══════════════════════════════════════════════════════════════

    def test_calibration_group_master_failed_sets_none(self, tmp_path):
        """Muellbytes-Darks einer Gruppe -> dark_source 'none', andere Gruppe ok."""
        dataset = synthetic.generate_dataset(
            tmp_path,
            n_lights_per_group=2, exposures=(15, 60), gains=(60,),
            size=(32, 32), channels=1, seed=42,
            include_darks=True, include_flats=False, include_bias=False,
        )
        # dark_15s60.fits korrumpieren (erster Dark der Gruppe 15s60)
        dataset.darks[0].write_bytes(b"corrupt-garbage-not-fits")

        context = build_observation_context(dataset.root)
        agent = CalibrationAgent(working_dir=tmp_path / "working")
        result = agent.run(context)

        assert result.master_dark_sources == {"15s60": "none", "60s60": "local"}
        assert result.dark_sources == {"15s60": "none", "60s60": "local"}
        masters = tmp_path / "working" / "00_input" / "master"
        assert (masters / "master_dark_60s60.fits").exists()
        assert not (masters / "master_dark_15s60.fits").exists()
        # Alle 4 Lights werden weiterhin kalibriert (15s60 ohne Dark-Abzug)
        assert len(result.calibrated_lights) == 4

    def test_calibration_master_stack_failure_sets_none(self, tmp_path):
        """Stacking-Fehler (Shape-Mismatch) -> master_build_failed + 'none'."""
        dataset = synthetic.generate_dataset(
            tmp_path,
            n_lights_per_group=2, exposures=(15, 60), gains=(60,),
            size=(32, 32), channels=1, seed=42,
            include_darks=True, include_flats=False, include_bias=False,
        )
        # Zweiter Dark (16x16) fuer 15s60: beide parsen, np.stack schlaegt fehl
        extra = dataset.root / "darks" / "dark_15s60_extra.fits"
        hdu = fits.PrimaryHDU(np.zeros((16, 16), dtype=np.float32))
        hdu.header["EXPTIME"] = 15.0
        hdu.header["GAIN"] = 60
        hdu.header["CCD-TEMP"] = -10.0
        hdu.header["FILTER"] = "none"
        hdu.writeto(extra, overwrite=True)

        context = build_observation_context(dataset.root)
        agent = CalibrationAgent(working_dir=tmp_path / "working")

        with patch("astro_process.agents.calibration.logger") as mock_logger:
            result = agent.run(context)

        warnings = [
            c for c in mock_logger.warning.call_args_list
            if c.args and c.args[0] == "calibration.master_build_failed"
        ]
        assert len(warnings) == 1
        assert warnings[0].kwargs["group"] == "15s60"
        assert "error" in warnings[0].kwargs

        assert result.master_dark_sources == {"15s60": "none", "60s60": "local"}
        masters = tmp_path / "working" / "00_input" / "master"
        assert not (masters / "master_dark_15s60.fits").exists()
        assert (masters / "master_dark_60s60.fits").exists()

    # ═══════════════════════════════════════════════════════════════
    # debayer: korrupter Frame ueberspringen, empty_result -> ValueError
    # ═══════════════════════════════════════════════════════════════

    def test_debayer_skips_bad_frame(self, tmp_path):
        """Ein korrupter Frame -> Debayer liefert den Rest, kein Crash."""
        dataset = synthetic.generate_dataset(
            tmp_path,
            n_lights_per_group=2, exposures=(15,), gains=(60,),
            size=(32, 32), channels=1, seed=42,
        )
        bad = dataset.lights[0]
        bad.write_bytes(b"corrupt-garbage-not-fits")

        context = _make_light_context(dataset)
        cal = CalibrationResult(
            working_dir=tmp_path / "working",
            calibrated_lights=list(dataset.lights),  # enthaelt den korrupten Frame
        )
        agent = DebayerAgent(working_dir=tmp_path / "working")
        result = agent.run(context, cal)

        assert len(result.debayered_frames) == 1
        assert result.debayered_frames[0].exists()
        assert result.seq_path is not None
        assert result.seq_path.exists()

    def test_debayer_empty_result_raises(self, tmp_path):
        """ALLE Frames fehlgeschlagen -> debayer.empty_result + ValueError."""
        dataset = synthetic.generate_dataset(
            tmp_path,
            n_lights_per_group=2, exposures=(15,), gains=(60,),
            size=(32, 32), channels=1, seed=42,
        )
        for p in dataset.lights:
            p.write_bytes(b"corrupt-garbage-not-fits")

        context = _make_light_context(dataset)
        cal = CalibrationResult(
            working_dir=tmp_path / "working",
            calibrated_lights=list(dataset.lights),
        )
        agent = DebayerAgent(working_dir=tmp_path / "working")

        with pytest.raises(ValueError, match="Debayer failed for all"):
            agent.run(context, cal)

    # ═══════════════════════════════════════════════════════════════
    # cli merge: kein silent except mehr
    # ═══════════════════════════════════════════════════════════════

    def test_cli_no_silent_except(self, tmp_path):
        """merge mit korrupten Gruppen-Stacks -> klare Meldung, Exit-Code != 0."""
        target = tmp_path / "target"
        ts = target / "generated" / "20260717-000001"
        for group in ("group_a", "group_b"):
            stack_dir = ts / group / "04_stacked"
            stack_dir.mkdir(parents=True, exist_ok=True)
            (stack_dir / "pcc_applied.fits").write_bytes(b"corrupt-not-fits")

        runner = CliRunner()
        result = runner.invoke(cli, ["merge", str(target)])

        assert result.exit_code != 0
        assert "Error" in result.output
        # Kein stilles Schlucken: die Header-Lesefehler werden geloggt
        assert "metadata_read_failed" in result.output

    # ═══════════════════════════════════════════════════════════════
    # M1 (ray-Review v1.1): 0 Lights -> sauberer Exit-Code 2 (FAIL)
    # ═══════════════════════════════════════════════════════════════

    def test_cli_zero_lights_exits_fail(self, tmp_path):
        """Target ohne Light-Frames -> cli.process.no_light_frames + Exit 2.

        Konsistent mit `astra doctor` (0=OK, 1=WARN, 2=FAIL): 0 Lights ist
        ein FAIL, kein generischer ClickException-Umweg und kein stiller
        "[OK] Processing complete" mit leerem Ergebnis.
        """
        target = tmp_path / "EmptyTarget"
        target.mkdir()
        write_default_suggested(target)

        runner = CliRunner()
        with patch("astro_process.cli.logger") as mock_logger:
            result = runner.invoke(cli, ["process", str(target), "--from-suggested"])

        assert result.exit_code == 2, result.output
        assert "[FAIL]" in result.output
        assert "No light frames found" in result.output

        # Strukturiertes Log statt ungefangener Exception
        error_calls = [
            c for c in mock_logger.error.call_args_list
            if c.args and c.args[0] == "cli.process.no_light_frames"
        ]
        assert len(error_calls) == 1
        assert error_calls[0].kwargs["lights"] == 0

    def test_cli_zero_lights_multi_group_exits_fail(self, tmp_path):
        """0 Lights im Multi-Group-Modus -> ebenfalls Exit 2 (kein ValueError-Crash)."""
        target = tmp_path / "EmptyTarget"
        target.mkdir()
        write_default_suggested(target)

        runner = CliRunner()
        result = runner.invoke(cli, ["process", str(target), "--from-suggested", "--multi-group"])

        assert result.exit_code == 2, result.output
        assert "[FAIL]" in result.output

    def test_cli_zero_lights_dry_run_informative(self, tmp_path):
        """dry-run mit 0 Lights bleibt informativ (Exit 0, 'Lights: 0')."""
        target = tmp_path / "EmptyTarget"
        target.mkdir()
        write_default_suggested(target)

        runner = CliRunner()
        result = runner.invoke(cli, ["process", str(target), "--from-suggested", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Lights: 0" in result.output


# ═══════════════════════════════════════════════════════════════════
# V1.1-Hardening (m5, m6, m7) — integriert aus test_v11_hardening.py
# ═══════════════════════════════════════════════════════════════════


def _make_fits(path: Path, shape=(32, 32), value=100.0, seed=42) -> Path:
    """Minimal synthetic FITS file."""
    rng = np.random.RandomState(seed)
    data = (rng.random(shape) * value + value).astype(np.float32)
    fits.PrimaryHDU(data).writeto(path, overwrite=True)
    return path


class TestM5AgentLogRuntimeError:
    """m5: _create_agent_log wirft RuntimeError bei Schreibfehlern (E1)."""

    def test_create_agent_log_raises_on_yaml_write_failure(self, tmp_path):
        context = ObservationContext(
            target=ObservationTarget(name="TestTarget"),
            source_path=tmp_path,
        )

        import builtins
        original_open = builtins.open

        def failing_open(*args, **kwargs):
            if args and "agent-log" in str(args[0]):
                raise OSError("disk full")
            return original_open(*args, **kwargs)

        agent = ArchiveAgent(output_root=tmp_path)

        class FakeProcResult:
            registered_frames = []
            stacked = None
            exports = []
            frame_qualities = None
            stack_quality = None
            gradient_removal = None
            registration_metrics = None
            pcc_status = None

        class FakeCalResult:
            master_dark = None
            calibrated_lights = []

        with patch("builtins.open", side_effect=failing_open):
            with pytest.raises(RuntimeError, match="Archive failed"):
                agent._create_agent_log(
                    tmp_path, context, FakeProcResult(), FakeCalResult()
                )


class TestM6StackSingleFrame:
    """m6: _stack_frames_python crasht nicht bei 1 Frame (Bias/Flat/Flat)."""

    def test_stack_single_frame_copies_directly(self, tmp_path):
        fits1 = _make_fits(tmp_path / "bias_001.fits", value=50.0, seed=1)
        output = tmp_path / "master_bias.fits"

        agent = CalibrationAgent(working_dir=tmp_path, config=None)
        agent.masters_dir = tmp_path

        agent._stack_frames_python([fits1], output, method="average")

        assert output.exists()
        with fits.open(output) as hdul:
            result_data = hdul[0].data
        with fits.open(fits1) as hdul:
            original_data = hdul[0].data
        np.testing.assert_array_equal(result_data, original_data)

    def test_stack_single_frame_median(self, tmp_path):
        fits1 = _make_fits(tmp_path / "flat_001.fits", value=200.0, seed=2)
        output = tmp_path / "master_flat.fits"

        agent = CalibrationAgent(working_dir=tmp_path, config=None)
        agent.masters_dir = tmp_path

        agent._stack_frames_python([fits1], output, method="median")

        assert output.exists()
        with fits.open(output) as hdul:
            result_data = hdul[0].data
        with fits.open(fits1) as hdul:
            original_data = hdul[0].data
        np.testing.assert_array_equal(result_data, original_data)

    def test_stack_zero_frames_raises(self, tmp_path):
        output = tmp_path / "master.fits"
        agent = CalibrationAgent(working_dir=tmp_path, config=None)
        agent.masters_dir = tmp_path

        with pytest.raises(ValueError, match="at least 1"):
            agent._stack_frames_python([], output, method="average")


class TestM7RunWithTimeoutSemantics:
    """m7: _run_with_timeout wirft TimeoutError (konsistent mit cli)."""

    def test_timeout_raises_timeout_error(self):
        with pytest.raises(TimeoutError, match="timed out"):
            _run_with_timeout(lambda: time.sleep(5), timeout=0.1)

    def test_success_returns_value(self):
        assert _run_with_timeout(lambda: 42, timeout=1.0) == 42

    def test_exception_propagates(self):
        def boom():
            raise ValueError("test-error")

        with pytest.raises(ValueError, match="test-error"):
            _run_with_timeout(boom, timeout=1.0)

    def test_timeout_is_raised_not_returned(self):
        result = None
        raised = False
        try:
            _run_with_timeout(lambda: time.sleep(5), timeout=0.1)
        except TimeoutError:
            raised = True
        assert raised, "Expected TimeoutError to be raised, not None return"

