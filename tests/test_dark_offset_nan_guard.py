"""Leo-Auftrag 2026-08-09: Dark-Offset-Abgleich + Dark-Sanity-Warnung
(calibration.py _apply_calibration) und NaN-Guard im Stacking
(core/stacking.py stack_2d / stack_frames_python).

Eigene minimale FITS-Fixtures (keine Imports aus tests/synthetic.py) —
Stil wie tests/test_darks_multi_group.py.

Abdeckung:
- Teil 1 (Offset-Abgleich): Dark zu hell (BG 210 vs Light-BG 200 + Signal)
  -> Hintergrund bleibt ~200 (nicht 0), Signal erhalten, keine NaN
  (Akzeptanzkriterium 1 der Auftragsquelle).
- Teil 1 (Neutralitaet): passender Dark (BG == Light) und zu dunkler Dark
  -> Ergebnis v1.2-identisch (M3/M13/M27-Schutzprinzip).
- Teil 2 (Sanity-Check): Warning calibration.dark_scale_mismatch bei
  Mismatch (delta > Schwelle) + Info calibration.dark_offset_adjusted;
  KEIN Abbruch — kalibriertes Light wird trotzdem erzeugt; passender Dark
  erzeugt KEINE Warnung. Schwellen-Gating (Warnung UND Offset-Abgleich
  greifen nur bei delta > Schwelle) siehe test_threshold_from_config.
- Teil 2b (M-1-Fix, Ray-Review): Low-Side-Check — Lokal-Dark-Szenario
  (dark_bg 10 vs light_bg 205) -> Warning calibration.dark_scale_mismatch_low
  (dark_bg/light_bg im Log), KEIN Abbruch; gesunder Dark (>= ~90 % von
  light_bg) -> KEINE Low-Warnung; Config-Override dark_scale_mismatch_low_frac
  flippt das Verhalten (identischer Testcode, andere Config-Werte).
- Teil 3 (NaN-Guard): Frames mit NaN oder Median 0 werden ausgeschlossen
  (Warning stack.non_finite_frame), Stack bleibt finite; alle Frames
  kaputt -> ValueError statt NaN-FITS; Final-Export-Guard lehnt ein
  NaN-Stack-Ergebnis ab (kein kaputtes FITS geschrieben).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from astropy.io import fits

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.agents.calibration import CalibrationAgent
from astro_process.agents.processing_agent import ProcessingAgent
from astro_process.config.models import AppConfig
from astro_process.core.stacking import stack_2d, stack_frames_python


def _write_fits(path: Path, data: np.ndarray) -> None:
    """Write a 2D FITS file (float32)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(np.asarray(data, dtype=np.float32)).writeto(path, overwrite=True)


def _make_light_with_signal(bg: float = 200.0, signal: float = 10.0) -> np.ndarray:
    """64x64 Light: konstanter Hintergrund + 4x4 Signal-Patch (signal DN ueber BG)."""
    light = np.full((64, 64), bg, dtype=np.float32)
    light[30:34, 30:34] = bg + signal
    return light


# ═══════════════════════════════════════════════════════════════════
# Teil 1+2 — Offset-Abgleich + Sanity-Warnung (calibration.py)
# ═══════════════════════════════════════════════════════════════════


class TestDarkOffsetAbgleich:
    """Teil 1+2: Dark-Offset-Abgleich + Dark-Sanity-Warnung."""

    @staticmethod
    def _agent(tmp_path: Path, config=None) -> CalibrationAgent:
        return CalibrationAgent(tmp_path / "working", config=config)

    def test_dark_too_bright_background_preserved_signal_kept(self, tmp_path: Path):
        """AK1: Light-BG 200 + Signal 10, Dark-BG 210 -> Hintergrund ~200
        (nicht 0), Signal ~210 erhalten, keine NaN."""
        agent = self._agent(tmp_path)
        light = _make_light_with_signal(bg=200.0, signal=10.0)
        dark = np.full((64, 64), 210.0, dtype=np.float32)

        calibrated = agent._apply_calibration(light, dark, None, None)

        assert np.all(np.isfinite(calibrated))
        # Hintergrund bleibt auf Light-Niveau (nicht auf 0 geklemmt)
        assert np.median(calibrated) == pytest.approx(200.0, abs=0.01)
        assert np.median(calibrated) > 100.0
        # Signal (+10 DN) bleibt erhalten
        assert calibrated[32, 32] == pytest.approx(210.0, abs=0.01)

    def test_matched_dark_neutral_plain_subtraction(self, tmp_path: Path):
        """Neutralitaet: Dark-BG == Light-BG -> v1.2-Verhalten (light - dark)."""
        agent = self._agent(tmp_path)
        light = _make_light_with_signal(bg=200.0, signal=10.0)
        dark = np.full((64, 64), 200.0, dtype=np.float32)

        calibrated = agent._apply_calibration(light, dark, None, None)

        assert np.all(np.isfinite(calibrated))
        assert np.median(calibrated) == pytest.approx(0.0, abs=0.01)
        assert calibrated[32, 32] == pytest.approx(10.0, abs=0.01)

    def test_too_dark_dark_neutral_plain_subtraction(self, tmp_path: Path):
        """Zu dunkler Dark (v1.2-Fall, float32-Dark): Plain-Subtraktion bleibt."""
        agent = self._agent(tmp_path)
        light = _make_light_with_signal(bg=200.0, signal=10.0)
        dark = np.full((64, 64), 5.0, dtype=np.float32)

        calibrated = agent._apply_calibration(light, dark, None, None)

        assert np.median(calibrated) == pytest.approx(195.0, abs=0.01)
        assert calibrated[32, 32] == pytest.approx(205.0, abs=0.01)

    def test_mismatch_logs_warning_and_offset_adjusted(self, tmp_path: Path):
        """Teil 2: Warning calibration.dark_scale_mismatch (delta, Schwelle)
        + Info calibration.dark_offset_adjusted — kein Abbruch."""
        agent = self._agent(tmp_path)
        light = _make_light_with_signal(bg=200.0, signal=10.0)
        dark = np.full((64, 64), 210.0, dtype=np.float32)

        with patch("astro_process.agents.calibration.logger") as mock_logger:
            calibrated = agent._apply_calibration(light, dark, None, None)

        assert mock_logger.warning.call_args.args[0] == "calibration.dark_scale_mismatch"
        warn_kw = mock_logger.warning.call_args.kwargs
        assert warn_kw["delta"] == pytest.approx(10.0, abs=0.01)
        assert warn_kw["threshold"] == pytest.approx(8.0, abs=0.01)  # max(5, 4%*200)
        assert warn_kw["dark_bg"] == pytest.approx(210.0, abs=0.01)
        assert warn_kw["light_bg"] == pytest.approx(200.0, abs=0.01)

        assert mock_logger.info.call_args.args[0] == "calibration.dark_offset_adjusted"
        assert mock_logger.info.call_args.kwargs["delta"] == pytest.approx(10.0, abs=0.01)

        # Weiterverarbeitung trotz Warnung (kein Abbruch)
        assert np.median(calibrated) == pytest.approx(200.0, abs=0.01)

    def test_matched_dark_no_warning(self, tmp_path: Path):
        """Neutralitaet: passender Dark -> KEINE dark_scale_mismatch-Warnung."""
        agent = self._agent(tmp_path)
        light = _make_light_with_signal(bg=200.0, signal=10.0)
        dark = np.full((64, 64), 200.0, dtype=np.float32)

        with patch("astro_process.agents.calibration.logger") as mock_logger:
            agent._apply_calibration(light, dark, None, None)

        mock_logger.warning.assert_not_called()

    def test_threshold_from_config(self, tmp_path: Path):
        """Konfig-Schwelle (dark_scale_mismatch_frac) entscheidet ueber
        Warnung UND Kalibrierung (Schwellen-Gating): bei Light-BG 1000 und
        Dark 1012 (delta 12):
        - 1 %-Config (Schwelle max(5, 10) = 10 < delta 12) -> Warnung
          calibration.dark_scale_mismatch + Offset-Abgleich
          (Hintergrund ~1000).
        - 4 %-Default (Schwelle max(5, 40) = 40 > delta 12) -> Plain-Pfad
          (v1.2-identisch): 0-Clip (Median ~0), KEINE High-Side-Warnung."""
        light = _make_light_with_signal(bg=1000.0, signal=10.0)
        dark = np.full((64, 64), 1012.0, dtype=np.float32)

        agent_default = self._agent(tmp_path, config=None)
        with patch("astro_process.agents.calibration.logger") as mock_logger:
            calibrated_default = agent_default._apply_calibration(light, dark, None, None)
        # 4 %-Default: Schwelle 40 > delta 12 -> Plain-Pfad (v1.2):
        # light - dark = -12 -> np.maximum -> 0-Clip (Median ~0), KEINE
        # High-Side-Warnung, KEIN Offset-Abgleich.
        events_default = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "calibration.dark_scale_mismatch" not in events_default
        assert np.median(calibrated_default) == pytest.approx(0.0, abs=0.01)

        agent_strict = self._agent(tmp_path, config=AppConfig(
            dark_scale_mismatch_abs=5.0,
            dark_scale_mismatch_frac=0.01,
        ))
        with patch("astro_process.agents.calibration.logger") as mock_logger:
            calibrated_strict = agent_strict._apply_calibration(light, dark, None, None)
        # 1 %-Config: Schwelle 10 < delta 12 -> High-Side-Warnung +
        # Offset-Abgleich (Hintergrund ~1000, Signal ~1010).
        strict_warns = [
            c for c in mock_logger.warning.call_args_list
            if c.args[0] == "calibration.dark_scale_mismatch"
        ]
        assert len(strict_warns) == 1
        assert strict_warns[0].kwargs["threshold"] == pytest.approx(10.0, abs=0.01)
        assert np.median(calibrated_strict) == pytest.approx(1000.0, abs=0.01)
        assert calibrated_strict[32, 32] == pytest.approx(1010.0, abs=0.01)

    def test_local_dark_too_low_logs_low_mismatch_warning(self, tmp_path: Path):
        """M-1-Fix (Ray-Review): Lokal-Dark-Szenario (dark_bg 10 vs light_bg
        205 -> C20-Fehlerklasse 2) -> Warning
        calibration.dark_scale_mismatch_low (dark_bg/light_bg im Log);
        KEIN Abbruch — Plain-Subtraktion bleibt (v1.2-neutral), kalibriertes
        Light wird trotzdem erzeugt. KEIN High-Side-Event."""
        agent = self._agent(tmp_path)
        light = _make_light_with_signal(bg=205.0, signal=10.0)
        dark = np.full((64, 64), 10.0, dtype=np.float32)

        with patch("astro_process.agents.calibration.logger") as mock_logger:
            calibrated = agent._apply_calibration(light, dark, None, None)

        low_warns = [
            c for c in mock_logger.warning.call_args_list
            if c.args[0] == "calibration.dark_scale_mismatch_low"
        ]
        assert len(low_warns) == 1
        assert low_warns[0].kwargs["dark_bg"] == pytest.approx(10.0, abs=0.01)
        assert low_warns[0].kwargs["light_bg"] == pytest.approx(205.0, abs=0.01)

        # KEIN High-Side-Event (das ist der jeweils andere Check)
        high_warns = [
            c for c in mock_logger.warning.call_args_list
            if c.args[0] == "calibration.dark_scale_mismatch"
        ]
        assert high_warns == []

        # Kein Abbruch: Plain-Subtraktion -> BG ~195 (205-10), Signal ~205
        assert np.all(np.isfinite(calibrated))
        assert np.median(calibrated) == pytest.approx(195.0, abs=0.01)
        assert calibrated[32, 32] == pytest.approx(205.0, abs=0.01)

    def test_healthy_dark_no_low_warning(self, tmp_path: Path):
        """M-1-Fix: gesunder Dark (dark_bg 195 >= ~90 % von light_bg 205)
        -> KEINE Low-Warnung (0.5 * 205 = 102.5 < 195)."""
        agent = self._agent(tmp_path)
        light = _make_light_with_signal(bg=205.0, signal=10.0)
        dark = np.full((64, 64), 195.0, dtype=np.float32)

        with patch("astro_process.agents.calibration.logger") as mock_logger:
            agent._apply_calibration(light, dark, None, None)

        events = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "calibration.dark_scale_mismatch_low" not in events

    def test_low_threshold_config_override(self, tmp_path: Path):
        """M-1-Fix: Config-Override der Low-Schwelle greift — identischer
        Testcode (dark_bg 10 vs light_bg 205), nur andere Config-Werte ->
        Verhalten flippt:
        - Override 0.01: 10 >= 0.01*205 = 2.05 -> KEINE Warnung (Default 0.5
          wuerde warnen, siehe test_local_dark_too_low...).
        - Override 0.99 beim gesunden Dark (195 vs 205): 195 < 0.99*205 =
          202.95 -> Warnung (Flip in die andere Richtung).
        """
        light = _make_light_with_signal(bg=205.0, signal=10.0)
        dark = np.full((64, 64), 10.0, dtype=np.float32)

        # Override niedrig: gleiche Daten, aber KEINE Low-Warnung
        agent_loose = self._agent(tmp_path, config=AppConfig(
            dark_scale_mismatch_low_frac=0.01,
        ))
        with patch("astro_process.agents.calibration.logger") as mock_logger:
            agent_loose._apply_calibration(light, dark, None, None)
        events_loose = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "calibration.dark_scale_mismatch_low" not in events_loose

        # Override hoch: gesunder Dark wird zur Low-Warnung
        light_healthy = _make_light_with_signal(bg=205.0, signal=10.0)
        dark_healthy = np.full((64, 64), 195.0, dtype=np.float32)
        agent_strict = self._agent(tmp_path, config=AppConfig(
            dark_scale_mismatch_low_frac=0.99,
        ))
        with patch("astro_process.agents.calibration.logger") as mock_logger:
            agent_strict._apply_calibration(light_healthy, dark_healthy, None, None)
        events_strict = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "calibration.dark_scale_mismatch_low" in events_strict


# ═══════════════════════════════════════════════════════════════════
# Teil 3 — NaN-Guard im Stacking (processing_agent.py)
# ═══════════════════════════════════════════════════════════════════


class TestNaNGuardStacking:
    """Teil 3: NaN-Guard in stack_2d + Final-Export-Guard."""

    @staticmethod
    def _agent(tmp_path: Path) -> ProcessingAgent:
        return ProcessingAgent(tmp_path / "working", config=None)

    def test_excludes_nan_and_zero_median_frames(self, tmp_path: Path):
        """Frames mit NaN oder Median 0 -> ausgeschlossen + Warning
        stack.non_finite_frame; Stack bleibt finite (kein divide-by-zero)."""
        data = np.zeros((4, 8, 8), dtype=np.float32)
        data[0] = 100.0
        data[1] = 100.0
        data[1, 0, 0] = np.nan          # NaN-Frame -> ausschliessen
        data[2] = 0.0                    # Median 0 -> ausschliessen (wuerde /0)
        data[3] = 100.0

        with patch("astro_process.core.stacking.logger") as mock_logger:
            result = stack_2d(data, method="average", normalization="mul")

        # Nur Frames 0 und 3 (Median 100) -> normalisiert auf 1.0 -> Mittel 1.0
        assert np.all(np.isfinite(result))
        assert np.allclose(result, 1.0)
        events = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert events == ["stack.non_finite_frame", "stack.non_finite_frame"]

    def test_all_frames_excluded_raises(self, tmp_path: Path):
        """Alle Frames Median 0 -> ValueError statt still ein kaputtes FITS."""
        data = np.zeros((3, 8, 8), dtype=np.float32)

        with pytest.raises(ValueError, match="stack.non_finite"):
            stack_2d(data, method="average", normalization="mul")

    def test_final_export_guard_rejects_nan_result(self, tmp_path: Path):
        """Final-Export-Guard: NaN im Stack-Ergebnis -> ValueError, kein FITS."""
        agent = self._agent(tmp_path)
        p1 = tmp_path / "f1.fits"
        p2 = tmp_path / "f2.fits"
        _write_fits(p1, np.full((8, 8), 100.0, dtype=np.float32))
        _write_fits(p2, np.full((8, 8), 100.0, dtype=np.float32))
        output = tmp_path / "stacked.fits"

        with patch(
            "astro_process.core.stacking.stack_2d",
            return_value=np.full((8, 8), np.nan, dtype=np.float32),
        ):
            with pytest.raises(ValueError, match="stack.non_finite_result"):
                stack_frames_python(
                    [p1, p2], output,
                    method="average", normalization="no",
                    load_frame=agent._load_frame,
                    save_frame=agent._save_frame,
                )
        assert not output.exists()
