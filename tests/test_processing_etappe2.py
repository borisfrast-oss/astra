"""Sprint-2 Etappe-2 Integrationstests: GR-C (S2-B3), QF-B (S2-B8), E1-Close (S2-B10).

Abgedeckt:
- S2-B3 / AC-GR-C1..C3: `_background_extraction` ersetzt den Placeholder
  (enabled -> Gradient entfernt In-Place; disabled -> v1.1-identisches Bild +
  Info-Log; GradientRemovalError -> Skip + Warning, Frame unveraendert).
- S2-B8 / AC-QF-B1..B3: `register_frames` sammelt `frame_quality` je Frame
  (frame + correlation vom Aufrufer gefuellt, outlier-geflaggt);
  `run()`/`ProcessingResult` exponieren frame_qualities + stack_quality;
  merge_report §5.3 `quality`-Block additiv; agent-log enthaelt
  frame_quality + stack_quality; kein Quality-Gate (nie Abbruch).
- S2-B10 / AC-GR-B4: `run()` warnt bei unbekanntem Preset-Step
  (`pipeline.step_unhandled`) statt stiller Ignoranz; extern behandelte
  Steps (create_master_dark, calibrate_lights) werden nicht gewarnt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import astropy.io.fits as fits
except ImportError:  # pragma: no cover - tests run from repo root
    fits = None  # type: ignore[assignment]

# Refactor 2026-08-14 (Cluster 3): registrations-Intra-Group-Tests rufen die
# core-Funktion ueber den gemeinsamen Helper (test_registration) — er setzt
# auch die _last_*-Attribute wie ProcessingAgent.run/process_multi_group.
from test_registration import (  # noqa: E402
    _make_agent,
    _register_frames,
    _write_2d_frame,
)

import astro_process.agents.archive as archive_mod  # noqa: E402

# V1.5-4 CD-Matrix-Semantik (ehemals test_v15_4_cd_matrix_semantik.py)
import astro_process.agents.multi_group_agent as multi_group_agent  # noqa: E402
import astro_process.agents.processing_agent as processing_agent_mod  # noqa: E402
import astro_process.core.registration as registration_mod  # noqa: E402
from astro_process.agents.archive import ArchiveAgent  # noqa: E402
from astro_process.agents.merge_agent import MergeAgent  # noqa: E402
from astro_process.agents.processing_agent import (  # noqa: E402
    ProcessingAgent,
    ProcessingResult,
)
from astro_process.config.loader import DEFAULT_CONFIG  # noqa: E402
from astro_process.config.models import (  # noqa: E402
    GradientRemovalConfig,
    MergeConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
)

SHAPE = (128, 128)
# Positiver degree-2-Gradient (Synthetik-Konvention: nie negativ auf
# [-1,1]^2, damit bg_truth == Bild + Gradient).
GRAD = (10.0, 8.0, 6.0, 4.0, 2.0, 3.0)


class _LogRecorder:
    """Minimaler structlog-Recorder (Muster aus test_registration.py)."""

    def __init__(self):
        self.records: list[tuple[str, dict]] = []

    def _record(self, name: str, **kwargs):
        self.records.append((name, kwargs))

    def info(self, name, **kwargs):
        self._record(name, **kwargs)

    def warning(self, name, **kwargs):
        self._record(name, **kwargs)

    def error(self, name, **kwargs):
        self._record(name, **kwargs)

    def debug(self, name, **kwargs):
        self._record(name, **kwargs)

    def events_named(self, name: str) -> list[tuple[str, dict]]:
        return [(n, k) for n, k in self.records if n == name]


# ── Bild-Helfer ───────────────────────────────────────────────────


def _poly2d_img(shape: tuple[int, int], coeffs: tuple[float, ...]) -> np.ndarray:
    height, width = shape
    y, x = np.ogrid[:height, :width]
    u = (x - (width - 1) / 2) / (width / 2)
    v = (y - (height - 1) / 2) / (height / 2)
    result = np.zeros((height, width), dtype=np.float64)
    k = 0
    for deg in range(3):
        for i in range(deg, -1, -1):
            j = deg - i
            if k < len(coeffs):
                result = result + coeffs[k] * (u**i) * (v**j)
                k += 1
    return result


def _gradient_rgb(
    seed: int = 42, *, channels: int = 3,
) -> np.ndarray:
    """(H, W, C) kalibriertes RGB-Frame (Background ~0) mit injiziertem
    degree-2-Gradient + wenigen Sternen + Noise."""
    rng = np.random.RandomState(seed)
    base = _poly2d_img(SHAPE, GRAD)
    img = np.zeros((*SHAPE, channels), dtype=np.float32)
    for c in range(channels):
        ch = base.copy()
        # Sterne (leicht versetzt pro Kanal, damit mono-Fit nicht verzerrt)
        for cy, cx, amp in [
            (40.0, 45.0, 60.0),
            (85.0, 30.0, 45.0),
            (100.0, 100.0, 55.0),
            (30.0, 95.0, 40.0),
            (75.0, 70.0, 50.0),
        ]:
            y, x = np.ogrid[: SHAPE[0], : SHAPE[1]]
            ch += amp * np.exp(
                -((y - (cy + c)) ** 2 + (x - (cx + c)) ** 2) / (2.0 * 2.0**2)
            )
        ch += rng.normal(0, 0.8, SHAPE)
        img[..., c] = ch
    return img


def _write_rgb_fits(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # (H, W, C) -> (C, H, W) FITS-Konvention (agent._save_frame-Muster)
    out = data.transpose(2, 0, 1)
    hdu = fits.PrimaryHDU(out.astype(np.float32))
    hdu.header["CTYPE3"] = "RGB"
    hdu.header["CUNIT3"] = "channel"
    hdu.writeto(path, overwrite=True)
    return path


def _read_fits(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        data = hdul[0].data
        if data.ndim == 3:
            data = data.transpose(1, 2, 0)
        return np.asarray(data, dtype=np.float32)


def _frame_edge_std(data: np.ndarray, width: int = 20) -> float:
    """Flachheitsmetrik: STD eines breiten Randrahmens (sternfrei)."""
    h, w = data.shape[:2]
    mono = np.mean(data, axis=-1) if data.ndim == 3 else data
    frame = np.zeros((h, w), dtype=bool)
    frame[:width, :] = True
    frame[-width:, :] = True
    frame[:, :width] = True
    frame[:, -width:] = True
    return float(np.std(mono[frame]))


# ═══════════════════════════════════════════════════════════════════
# S2-B3 — GR-C: _background_extraction (AC-GR-C1..C3)
# ═══════════════════════════════════════════════════════════════════


class TestGradientRemovalIntegration:
    def _agent_and_stack(self, tmp_path: Path) -> tuple[ProcessingAgent, Path]:
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        stack = tmp_path / "out" / "04_stacked" / "stacked.fits"
        _write_rgb_fits(stack, _gradient_rgb())
        return agent, stack

    def test_enabled_removes_gradient_in_place(self, tmp_path: Path):
        """AC-GR-C1: enabled=true -> Gradient aus stacked.fits entfernt,
        Ergebnis ersetzt den Stack (In-Place), Frame wird flacher."""
        agent, stack = self._agent_and_stack(tmp_path)
        before = _frame_edge_std(_read_fits(stack))
        assert before > 3.0  # Gradient-Spannweite dominiert den Rand

        agent._background_extraction(
            stack,
            {"gradient_removal": {
                "enabled": True, "degree": 2, "grid": [32, 32],
                "sigma_clip": 3.0, "min_samples": None,
            }},
        )

        after = _frame_edge_std(_read_fits(stack))
        # Dokumentierte Toleranz: Rest-Gradient deutlich unter Noise+Sterne-Niveau
        assert after < 1.5 * before * 0.5
        assert after < 3.0

    def test_enabled_reduces_mono_model_gradient(self, tmp_path: Path):
        """AC-GR-C2-Grundlage: injizierter polynominaler Gradient wird auf
        einen dokumentierten Rest reduziert (Rand-STD deutlich kleiner als der
        injizierte Niveau ~ 34 ADU)."""
        agent, stack = self._agent_and_stack(tmp_path)
        edge_std_before = _frame_edge_std(_read_fits(stack))
        agent._background_extraction(
            stack,
            {"gradient_removal": {
                "enabled": True, "degree": 2, "grid": [32, 32],
                "sigma_clip": 3.0, "min_samples": None,
            }},
        )
        edge_std_after = _frame_edge_std(_read_fits(stack))
        assert edge_std_before > 5.0
        assert edge_std_after < 2.0

    def test_disabled_leaves_frame_unchanged(self, tmp_path: Path, monkeypatch):
        """AC-GR-C3: enabled=false -> v1.1-identisches Bild (byte-gleich) und
        Info-Log `pipeline.gradient_removal_disabled` (nicht "not implemented")."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent, stack = self._agent_and_stack(tmp_path)
        raw = stack.read_bytes()

        agent._background_extraction(
            stack,
            {"gradient_removal": {
                "enabled": False, "degree": 2, "grid": [32, 32],
                "sigma_clip": 3.0, "min_samples": None,
            }},
        )

        assert stack.read_bytes() == raw  # kein Bild-Output bei disabled
        events = rec.events_named("pipeline.gradient_removal_disabled")
        assert len(events) == 1
        assert "not implemented" not in " ".join(n for n, _ in rec.records)

    def test_disabled_without_config_block(self, tmp_path: Path):
        """Kein gradient_removal-Block in params -> enabled false Default:
        Frame bleibt unveraendert (kein Absturz, kein "not implemented")."""
        agent, stack = self._agent_and_stack(tmp_path)
        raw = stack.read_bytes()
        agent._background_extraction(stack, {})
        assert stack.read_bytes() == raw

    def test_min_samples_error_skips_with_warning(self, tmp_path: Path, monkeypatch):
        """AC-GR-B3/E1: min_samples > verfuegbare Zellen -> Schritt
        uebersprungen + Warning `pipeline.gradient_removal_skipped`, Frame
        unveraendert, Pipeline laeuft weiter (kein Raise)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent, stack = self._agent_and_stack(tmp_path)
        raw = stack.read_bytes()

        # grid (8, 8) -> 64 Zellen < min_samples 600 -> GradientRemovalError
        agent._background_extraction(
            stack,
            {"gradient_removal": {
                "enabled": True, "degree": 2, "grid": [8, 8],
                "sigma_clip": 3.0, "min_samples": 600,
            }},
        )

        assert stack.read_bytes() == raw
        events = rec.events_named("pipeline.gradient_removal_skipped")
        assert len(events) == 1
        assert events[0][1]["reason"] == "gradient_removal_error"
        assert rec.events_named("pipeline.status")

    def test_non_rgb_frame_skipped_with_warning(self, tmp_path: Path, monkeypatch):
        """2D-Frame (kein RGB): Schritt uebersprungen + Warning, kein Crash."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        stack = tmp_path / "out" / "04_stacked" / "stacked.fits"
        stack.parent.mkdir(parents=True, exist_ok=True)
        fits.PrimaryHDU(_gradient_rgb()[..., 0].astype(np.float32)).writeto(
            stack, overwrite=True
        )
        raw = stack.read_bytes()

        agent._background_extraction(
            stack,
            {"gradient_removal": {"enabled": True, "degree": 2,
                                  "grid": [32, 32], "sigma_clip": 3.0,
                                  "min_samples": None}},
        )
        assert stack.read_bytes() == raw
        assert rec.events_named("pipeline.gradient_removal_skipped")


# ═══════════════════════════════════════════════════════════════════
# S2-B8 — QF-B: frame_quality im Registrations-Pass (AC-QF-B1..B3)
# ═══════════════════════════════════════════════════════════════════


class TestQualityIntegrationRegistration:
    def _agent_with_frames(self, tmp_path: Path) -> tuple[ProcessingAgent, list[Path]]:
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        frames = [
            _write_rgb_fits(tmp_path / "in" / "f0.fits", _gradient_rgb(seed=1)),
            _write_rgb_fits(tmp_path / "in" / "f1.fits", _gradient_rgb(seed=2)),
            _write_rgb_fits(tmp_path / "in" / "f2.fits", _gradient_rgb(seed=3)),
        ]
        return agent, frames

    def test_register_frames_fills_frame_qualities(self, tmp_path: Path):
        """AC-QF-B1: _register_frames sammelt je Frame (inkl. Referenz)
        frame_quality mit frame (Pfad) + correlation (corr_hp, post-shift);
        Outlier-Feld ist gefuellt (flaggen, nicht verwerfen)."""
        agent, frames = self._agent_with_frames(tmp_path)
        registered = _register_frames(
            agent,
            frames, {"registration": {"method": "fft", "max_control_points": None}},
            is_3d=True,
        )
        assert len(registered) == len(frames)

        qualities = agent._last_frame_qualities
        assert len(qualities) == len(frames)
        for q in qualities:
            assert q.frame is not None
            assert q.outlier in (True, False)
        # Referenz hat keine Shift-Metrik; Folge-Frames corr_hp post-shift
        assert qualities[0].correlation is None
        for q in qualities[1:]:
            assert q.correlation is not None
            assert -1.0 <= q.correlation <= 1.0

    def test_run_exposes_frame_qualities_and_stack_quality(self, tmp_path: Path):
        """AC-QF-B1: run() -> ProcessingResult.frame_qualities (dicts) +
        stack_quality (Median-FWHM/Median-SNR/Outlier-Rate)."""
        agent, frames = self._agent_with_frames(tmp_path)
        context = SimpleNamespace(
            target=SimpleNamespace(name="TestTarget", ra=0.0, dec=0.0),
            equipment=SimpleNamespace(focal_length_mm=0.0, pixel_size_um=0.0),
        )
        debayer_result = SimpleNamespace(debayered_frames=frames)
        calibration_result = SimpleNamespace(calibrated_lights=[])
        pipeline = PipelinePreset(
            name="test",
            target_types=["nebula"],
            steps=[
                PipelineStep(name="register_frames"),
                PipelineStep(name="stack_frames"),
            ],
            processing_params=ProcessingParams(),
        )

        result = agent.run(context, calibration_result, debayer_result, pipeline)

        assert isinstance(result, ProcessingResult)
        assert len(result.frame_qualities) == len(frames)
        assert result.frame_qualities[0]["frame"] is not None
        assert "snr" in result.frame_qualities[0]
        assert "outlier" in result.frame_qualities[0]
        assert result.stack_quality is not None
        assert "median_fwhm" in result.stack_quality
        assert "median_snr" in result.stack_quality
        assert "outlier_rate" in result.stack_quality

    def test_quality_never_aborts_on_bad_frame(self, tmp_path: Path, monkeypatch):
        """AC-QF-B3: Fehler in der Qualitaetsberechnung -> leere Metrik +
        Warning `quality.compute_failed`, Registration laeuft weiter (nie
        Abbruch — kein Quality-Gate)."""
        from unittest.mock import patch

        rec = _LogRecorder()
        monkeypatch.setattr(registration_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        frames = [
            _write_rgb_fits(tmp_path / "in" / "g.fits", _gradient_rgb(seed=1)),
            _write_rgb_fits(tmp_path / "in" / "g2.fits", _gradient_rgb(seed=2)),
        ]

        with patch.object(
            registration_mod, "compute_frame_quality",
            side_effect=ValueError("boom"),
        ):
            registered = _register_frames(
                agent, frames, {"registration": {"method": "fft"}}, is_3d=True
            )

        assert len(registered) == len(frames)  # Registration lief durch
        assert rec.events_named("quality.compute_failed")
        # Ersatz-Metriken: frame gefuellt, Rest Default
        assert len(agent._last_frame_qualities) == len(frames)
        assert agent._last_frame_qualities[0].frame is not None


# ═══════════════════════════════════════════════════════════════════
# S2-B8 — QF-B: Reports additiv (AC-QF-B1/B2)
# ═══════════════════════════════════════════════════════════════════


class TestQualityReports:
    def test_merge_report_quality_block_additive(self):
        """AC-QF-B2: merge_report §5.3 enthaelt quality-Block (per-Group-
        Zusammenfassung); bestehende Felder unveraendert (input_stacks etc.)."""
        group_metadata = {
            "g1": {
                "frame_count": 3,
                "exptime": 60.0,
                "gain": 40,
                "filter": None,
                "total_exposure": 180.0,
                "dark_source": "none",
                "pcc_status": "gaia_success",
                "quality": {
                    "frames": 3,
                    "median_fwhm": 3.2,
                    "median_snr": 12.4,
                    "outlier_rate": 0.0,
                },
            },
            "g2": {
                "frame_count": 2,
                "exptime": 15.0,
                "gain": 60,
                "filter": None,
                "total_exposure": 30.0,
                "dark_source": "none",
                "pcc_status": "gaia_success",
            },
        }
        merged = np.zeros((4, 4), dtype=np.float32)
        report = MergeAgent._build_merge_report(
            merge_config=MergeConfig(),
            ref_hash="g1",
            merged_path=Path("/tmp/x.fits"),
            merged=merged,
            group_stacks={"g1": Path("/tmp/a.fits"), "g2": Path("/tmp/b.fits")},
            group_metadata=group_metadata,
            stack_hashes=["g1", "g2"],
            weights=[3.0, 2.0],
            pcc_fallback_groups=[],
        )

        # Additiv: quality-Block vorhanden, bestehende Felder unveraendert
        assert "quality" in report
        assert "g1" in report["quality"]
        assert report["quality"]["g1"]["median_fwhm"] == 3.2
        assert report["quality"]["g1"]["outlier_rate"] == 0.0
        # Gruppe ohne quality-Daten (g2) erzeugt keinen Eintrag
        assert "g2" not in report["quality"]
        # Bestehende Felder weiterhin vorhanden
        assert report["method"] == "weighted_average"
        assert len(report["input_stacks"]) == 2
        assert report["input_stacks"][0]["metadata"]["frame_count"] == 3

    def test_merge_report_quality_block_contains_frame_quality(self):
        """QF-01: merge_report-quality-Block enthaelt Per-Frame-Qualitaet
        (frame + snr + fwhm_median + star_count + correlation + outlier)
        additiv — Zusammenfassung bleibt, Legacy-Gruppen unveraendert."""
        group_metadata = {
            "g1": {
                "frame_count": 2,
                "exptime": 60.0,
                "gain": 40,
                "filter": None,
                "total_exposure": 120.0,
                "dark_source": "none",
                "pcc_status": "gaia_success",
                "quality": {
                    "frames": 2,
                    "median_fwhm": 3.1,
                    "median_snr": 10.5,
                    "outlier_rate": 0.0,
                },
                "frame_quality": [
                    {"frame": "/tmp/r0.fits", "snr": 10.0, "fwhm_median": 3.1,
                     "star_count": 8, "correlation": 0.98, "outlier": False,
                     "outlier_reason": None},
                    {"frame": "/tmp/r1.fits", "snr": 11.0, "fwhm_median": 3.0,
                     "star_count": 9, "correlation": 0.99, "outlier": False,
                     "outlier_reason": None},
                ],
            },
            # Legacy: quality vorhanden, KEINE frame_quality-Daten
            "g2": {
                "frame_count": 2,
                "exptime": 15.0,
                "gain": 60,
                "filter": None,
                "total_exposure": 30.0,
                "dark_source": "none",
                "pcc_status": "gaia_success",
                "quality": {
                    "frames": 2,
                    "median_fwhm": 4.0,
                    "median_snr": 8.0,
                    "outlier_rate": 0.5,
                },
            },
        }
        merged = np.zeros((4, 4), dtype=np.float32)
        report = MergeAgent._build_merge_report(
            merge_config=MergeConfig(),
            ref_hash="g1",
            merged_path=Path("/tmp/x.fits"),
            merged=merged,
            group_stacks={"g1": Path("/tmp/a.fits"), "g2": Path("/tmp/b.fits")},
            group_metadata=group_metadata,
            stack_hashes=["g1", "g2"],
            weights=[2.0, 2.0],
            pcc_fallback_groups=[],
        )

        q1 = report["quality"]["g1"]
        # Zusammenfassung additiv unveraendert
        assert q1["median_fwhm"] == 3.1
        assert q1["median_snr"] == 10.5
        # Per-Frame-Daten additiv vorhanden (QF-A-Schema)
        assert len(q1["frame_quality"]) == 2
        assert q1["frame_quality"][0]["frame"] == "/tmp/r0.fits"
        assert q1["frame_quality"][0]["snr"] == 10.0
        assert q1["frame_quality"][0]["fwhm_median"] == 3.1
        assert q1["frame_quality"][0]["star_count"] == 8
        assert q1["frame_quality"][0]["correlation"] == 0.98
        assert q1["frame_quality"][1]["correlation"] == 0.99
        # Legacy-Gruppe ohne frame_quality bleibt unveraendert
        assert "frame_quality" not in report["quality"]["g2"]
        assert report["quality"]["g2"]["median_fwhm"] == 4.0

    def test_agent_log_contains_frame_quality(self, tmp_path: Path):
        """AC-QF-B1: agent-log.yaml enthaelt processing.frame_quality
        (je Frame) + processing.stack_quality (Zusammenfassung)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits"],
        )
        debayer_result = SimpleNamespace(debayered_frames=["a.fits", "b.fits"])
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits"), Path("/tmp/r1.fits")],
            stacked=Path("/tmp/stacked.fits"),
            exports=[Path("/tmp/out.fits")],
            multi_group_metadata=None,
            frame_qualities=[
                {"frame": "/tmp/r0.fits", "snr": 10.0, "fwhm_median": 3.1,
                 "star_count": 8, "correlation": None, "outlier": False,
                 "outlier_reason": None},
                {"frame": "/tmp/r1.fits", "snr": 11.0, "fwhm_median": 3.0,
                 "star_count": 9, "correlation": 0.99, "outlier": False,
                 "outlier_reason": None},
            ],
            stack_quality={"frames": 2, "median_fwhm": 3.05,
                           "median_snr": 10.5, "outlier_rate": 0.0},
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            debayer_result=debayer_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["frame_quality"][0]["frame"] == "/tmp/r0.fits"
        assert log["processing"]["frame_quality"][0]["snr"] == 10.0
        assert log["processing"]["stack_quality"]["median_fwhm"] == 3.05
        assert log["processing"]["stack_quality"]["outlier_rate"] == 0.0

    def test_agent_log_legacy_result_no_quality_fields(self, tmp_path: Path):
        """Ohne QF-Felder (alter proc_result/Mock) bleibt das agent-log
        valide (additiv, keine Bruchstelle)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=10.0,
            total_light_frames=1,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits"],
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
        )
        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["frame_quality"] == []
        assert log["processing"]["stack_quality"] == {}

    def test_agent_log_contains_registration_metrics(self, tmp_path: Path):
        """V1.3-3 (stella-Befund 4): agent-log.yaml enthaelt
        processing.registration_metrics (method_counts, zero_shift_count,
        rejected_count, frames, corr_hp-Verteilung, n_control_points-
        Median) — Frame-Qualitaets-Metriken erfassen Registrierungs-
        Qualitaet nicht, deshalb additiv im agent-log."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits"],
        )
        debayer_result = SimpleNamespace(debayered_frames=["a.fits", "b.fits"])
        reg_metrics = {
            "method_counts": {"fft": 40, "astroalign": 3},
            "zero_shift_count": 1,
            "rejected_count": 0,
            "frames_total": 44,
            "frames_registered": 43,
            "corr_hp": {
                "count": 42,
                "min": 0.31,
                "max": 0.98,
                "median": 0.72,
            },
            "n_control_points": {
                "count": 3,
                "median": 15.0,
            },
        }
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits"), Path("/tmp/r1.fits")],
            stacked=Path("/tmp/stacked.fits"),
            exports=[Path("/tmp/out.fits")],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
            registration_metrics=reg_metrics,
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            debayer_result=debayer_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["registration_metrics"] == reg_metrics
        assert log["processing"]["registration_metrics"]["method_counts"]["fft"] == 40
        assert log["processing"]["registration_metrics"]["method_counts"]["astroalign"] == 3
        assert log["processing"]["registration_metrics"]["corr_hp"]["median"] == 0.72
        assert log["processing"]["registration_metrics"]["n_control_points"]["median"] == 15.0

    def test_agent_log_registered_frames_from_registration_metrics(self, tmp_path: Path):
        """DEF-009 (b): agent-log.yaml processing.registered_frames muss aus
        registration_metrics.frames_registered kommen (Quelle der Wahrheit),
        nicht aus der reinen Laenge von proc_result.registered_frames."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=6,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits"] * 6,
        )
        debayer_result = SimpleNamespace(debayered_frames=["a.fits"] * 6)
        reg_metrics = {
            "method_counts": {"astroalign": 6},
            "frames_total": 6,
            "frames_registered": 6,
        }
        proc_result = SimpleNamespace(
            # registered_frames leer simuliert das beobachtete Symptom,
            # registration_metrics enthaelt aber die korrekte Anzahl.
            registered_frames=[],
            stacked=Path("/tmp/stacked.fits"),
            exports=[Path("/tmp/out.fits")],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
            registration_metrics=reg_metrics,
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            debayer_result=debayer_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["registered_frames"] == 6
        assert log["processing"]["registered_frames"] == reg_metrics["frames_registered"]

    def test_agent_log_registered_frames_multi_group_sum(self, tmp_path: Path):
        """DEF-009 (b): Multi-Group-Modus -> registered_frames ist die Summe
        ueber die Gruppen-Metriken, da top-level registration_metrics nur
        noch das aggregierte multi_group-Dict enthaelt."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=120.0,
            total_light_frames=10,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits"] * 10,
        )
        debayer_result = SimpleNamespace(debayered_frames=["a.fits"] * 10)
        multi_group_metadata = {
            "groups": {
                "60s40_Astro": {
                    "frame_count": 6,
                    "registration_metrics": {"frames_registered": 6},
                },
                "30s40_Astro": {
                    "frame_count": 4,
                    "registration_metrics": {"frames_registered": 4},
                },
            },
            "method": "weighted_average",
        }
        proc_result = SimpleNamespace(
            # Multi-Group: top-level registered_frames ist typischerweise leer.
            registered_frames=[],
            stacked=Path("/tmp/stacked.fits"),
            exports=[Path("/tmp/out.fits")],
            multi_group_metadata=multi_group_metadata,
            frame_qualities=[],
            stack_quality=None,
            # Top-level registration_metrics ist das aggregierte Multi-Group-Dict.
            registration_metrics={"mode": "multi_group", "groups": {}},
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            debayer_result=debayer_result,
            multi_group_metadata=multi_group_metadata,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["registered_frames"] == 10

    def test_agent_log_legacy_result_no_registration_metrics(self, tmp_path: Path):
        """V1.3-3: Ohne registration_metrics-Feld (alter proc_result/Mock)
        bleibt das agent-log valide: processing.registration_metrics == {}
        (additiv, keine Bruchstelle)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=10.0,
            total_light_frames=1,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits"],
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
        )
        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["registration_metrics"] == {}

    def test_agent_log_multi_group_processing_registration_metrics(self, tmp_path: Path):
        """V1.3-3 (stella-Befund 4): Bei Multi-Group-Ergebnissen enthaelt
        processing.registration_metrics das aggregierte dict (mode=
        "multi_group" + groups mit per-Group-Metriken) — additiv, ohne
        Verlust der multi_group-Sektion."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=45.0,
            total_light_frames=6,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits", "c.fits"],
        )
        debayer_result = SimpleNamespace(debayered_frames=["a.fits", "b.fits", "c.fits"])
        group_reg_metrics = {
            "method_counts": {"fft": 2, "astroalign": 0},
            "zero_shift_count": 0,
            "rejected_count": 0,
            "frames_total": 3,
            "frames_registered": 3,
            "corr_hp": {"count": 2, "min": 0.5, "max": 0.9, "median": 0.7},
            "n_control_points": {"count": 0, "median": None},
        }
        multi_group_metadata = {
            "groups": {
                "15s60": {
                    "frame_count": 3, "exptime": 15.0, "gain": 60,
                    "filter": None, "total_exposure": 45.0, "weight": 3.0,
                    "pcc_status": "gaia_success",
                    "registration_metrics": dict(group_reg_metrics),
                },
                "60s40": {
                    "frame_count": 3, "exptime": 60.0, "gain": 40,
                    "filter": None, "total_exposure": 180.0, "weight": 3.0,
                    "pcc_status": "gaia_success",
                    "registration_metrics": dict(group_reg_metrics),
                },
            },
            "method": "weighted_average",
            "weight_by": "frame_count",
            "reference_group": "60s40",
            "pcc_fallback_groups": [],
            "skipped_groups": [],
        }
        proc_result = SimpleNamespace(
            registered_frames=[],
            stacked=Path("/tmp/merged.fits"),
            exports=[Path("/tmp/merged.fits")],
            multi_group_metadata=multi_group_metadata,
            frame_qualities=[],
            stack_quality=None,
            registration_metrics={
                "mode": "multi_group",
                "groups": {
                    gh: dict(meta["registration_metrics"])
                    for gh, meta in multi_group_metadata["groups"].items()
                },
            },
        )
        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            debayer_result=debayer_result,
            multi_group_metadata=proc_result.multi_group_metadata,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        rm = log["processing"]["registration_metrics"]
        assert rm["mode"] == "multi_group"
        assert set(rm["groups"].keys()) == {"15s60", "60s40"}
        assert rm["groups"]["15s60"]["method_counts"]["fft"] == 2
        assert rm["groups"]["60s40"]["frames_registered"] == 3
        assert rm["groups"]["60s40"]["corr_hp"]["median"] == 0.7
        # multi_group-Sektion bleibt unveraendert (per-Group-Durchreichung)
        assert len(log["multi_group"]["groups"]) == 2
        assert log["multi_group"]["groups"][0]["registration_metrics"]["frames_registered"] == 3

    # ── P2-3 (ray-Review): Archive-Level recommendation-Sektion (RE-C) ──

    def test_agent_log_recommendation_section_with_rec(self, tmp_path: Path):
        """P2-3 (ray-Review): discovery_result.recommendation vorhanden ->
        agent-log enthaelt die additive `recommendation`-Sektion
        (method/suggested_cli/reason/eq_source + max_rotation_suggestion
        falls gesetzt); die uebrigen Sektionen bleiben unveraendert
        (R8/AC-RE-C2)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits"],
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
        )
        discovery_result = SimpleNamespace(recommendation={
            "method": "astroalign",
            "suggested_cli": "--registration-method astroalign --max-rotation 30",
            "reason": "Duo-Band + AZ (eq=false): Feldrotation möglich.",
            "eq_source": "shotsinfo",
            "max_rotation_suggestion": 30.0,
        })

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            discovery_result=discovery_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        rec = log["recommendation"]
        assert rec["method"] == "astroalign"
        assert rec["suggested_cli"] == "--registration-method astroalign --max-rotation 30"
        assert rec["eq_source"] == "shotsinfo"
        assert rec["max_rotation_suggestion"] == 30.0
        # Uebrige Sektionen unveraendert
        assert log["target"]["name"] == "TestTarget"
        assert log["processing"]["registered_frames"] == 1

    def test_agent_log_recommendation_section_omits_max_rotation_for_duo_eq(
        self, tmp_path: Path,
    ):
        """P2-3 + P2-4a: Empfehlung OHNE --max-rotation-Vorschlag
        (Duo+EQ) -> recommendation-Sektion OHNE `max_rotation_suggestion`."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits"],
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
        )
        discovery_result = SimpleNamespace(recommendation={
            "method": "astroalign",
            "suggested_cli": "--registration-method astroalign",
            "reason": "Duo-Band + EQ (eq=true): keine Feldrotation.",
            "eq_source": "shotsinfo",
        })

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            discovery_result=discovery_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["recommendation"]["method"] == "astroalign"
        assert "max_rotation_suggestion" not in log["recommendation"]

    def test_agent_log_no_recommendation_section_without_trigger(
        self, tmp_path: Path,
    ):
        """P2-3 (ray-Review): ohne Empfehlungs-Trigger (recommendation=None)
        -> KEINE recommendation-Sektion; das uebrige Schema ist identisch
        (R8/AC-RE-C2: keine Sektion, keine sonstige Schema-Aenderung)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits"],
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
        )
        discovery_result = SimpleNamespace(recommendation=None)

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            discovery_result=discovery_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert "recommendation" not in log
        # Schema sonst unveraendert (Kern-Sektionen vorhanden)
        for section in ("run", "target", "acquisition", "frames",
                        "calibration", "debayer", "processing", "outputs"):
            assert section in log, section

    # ── PCC-Status Persistierung (agent-log + run-info) ──────────

    def test_agent_log_pcc_status_single_group(self, tmp_path: Path):
        """agent-log.yaml enthaelt processing.pcc_status mit korrektem Wert
        (Single-Group-Pfad)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits"],
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=Path("/tmp/stacked.fits"),
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
            gradient_removal=None,
            registration_metrics=None,
            pcc_status="gaia_success",
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["pcc_status"] == "gaia_success"

    def test_agent_log_pcc_status_none_legacy(self, tmp_path: Path):
        """Legacy-ProcResult ohne pcc_status Feld -> pcc_status=None
        (additiv, kein Bruch)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=10.0,
            total_light_frames=1,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits"],
        )
        # Legacy-result: kein pcc_status Attribut
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["pcc_status"] is None

    def test_agent_log_pcc_status_multi_group_aggregated(self, tmp_path: Path):
        """Multi-Group: processing.pcc_status enthaelt aggregierten Wert
        (alle gleich -> ein Wert; gemischt -> 'mixed')."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=120.0,
            total_light_frames=4,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=["a.fits", "b.fits"],
        )
        # Alle Gruppen haben gaia_success -> aggregiert "gaia_success"
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=Path("/tmp/stacked.fits"),
            exports=[],
            multi_group_metadata={
                "groups": {
                    "15s60": {"pcc_status": "gaia_success"},
                    "60s40": {"pcc_status": "gaia_success"},
                },
            },
            frame_qualities=[],
            stack_quality=None,
            gradient_removal=None,
            registration_metrics=None,
            pcc_status="gaia_success",
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["pcc_status"] == "gaia_success"

    def test_run_info_pcc_status(self, tmp_path: Path):
        """run-info.json enthaelt pcc_status auf Top-Level."""
        import json

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=60.0,
            total_light_frames=2,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
            get_lights=SimpleNamespace(
                group_by_params=dict
            ),
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=Path("/tmp/stacked.fits"),
            exports=[],
            multi_group_metadata=None,
            frame_qualities=[],
            stack_quality=None,
            pcc_status="fallback_gray_world",
        )
        discovery_result = None

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        run_info_path = agent._write_run_info(
            output_dir, context,
            proc_result=proc_result,
            discovery_result=discovery_result,
        )
        assert run_info_path is not None
        data = json.loads(run_info_path.read_text(encoding="utf-8"))
        assert data["pcc_status"] == "fallback_gray_world"

    def test_run_info_pcc_status_none_legacy(self, tmp_path: Path):
        """Legacy-ProcResult ohne pcc_status -> pcc_status=None in
        run-info.json."""
        import json

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=10.0,
            total_light_frames=1,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
            get_lights=SimpleNamespace(
                group_by_params=dict
            ),
        )
        # Legacy: kein pcc_status
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=None,
            exports=[],
            multi_group_metadata=None,
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        run_info_path = agent._write_run_info(
            output_dir, context,
            proc_result=proc_result,
            discovery_result=None,
        )
        assert run_info_path is not None
        data = json.loads(run_info_path.read_text(encoding="utf-8"))
        assert data["pcc_status"] is None


# ═══════════════════════════════════════════════════════════════════
# S2-B10 — E1-Close: Unknown-Step-Validierung (AC-GR-B4)
# ═══════════════════════════════════════════════════════════════════


class TestUnknownStepValidation:
    def _run(self, tmp_path: Path, steps: list[str]):
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = SimpleNamespace(
            target=SimpleNamespace(name="TestTarget", ra=0.0, dec=0.0),
            equipment=SimpleNamespace(focal_length_mm=0.0, pixel_size_um=0.0),
        )
        pipeline = PipelinePreset(
            name="test",
            target_types=["nebula"],
            steps=[PipelineStep(name=s) for s in steps],
            processing_params=ProcessingParams(),
        )
        return agent, agent.run(
            context,
            SimpleNamespace(calibrated_lights=[]),
            SimpleNamespace(debayered_frames=[]),
            pipeline,
        )

    def test_unknown_step_warns_pipeline_step_unhandled(
        self, tmp_path: Path, monkeypatch,
    ):
        """AC-GR-B4: unbekannter Preset-Step -> Warning `pipeline.step_unhandled`
        statt stiller Ignoranz; Run bricht nicht ab (kein Quality-Gate)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent, result = self._run(tmp_path, ["mystery_processor"])

        events = rec.events_named("pipeline.step_unhandled")
        assert len(events) == 1
        assert events[0][1]["step"] == "mystery_processor"
        assert result is not None  # Pipeline lief durch

    def test_declared_but_unimplemented_step_warns(
        self, tmp_path: Path, monkeypatch,
    ):
        """Deklarierte, aber nicht implementierte Steps (z.B.
        stack_frames_per_channel aus nebula_narrowband) sind stille
        Ignorier-Faelle -> werden gewarnt (E1-Close). structure_enhancement
        hat seit v1.2 einen Plugin-Handler (AC-SE-B1) und gehoert NICHT
        mehr in diese Menge."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        self._run(tmp_path, ["stack_frames_per_channel"])

        events = rec.events_named("pipeline.step_unhandled")
        assert len(events) == 1
        assert events[0][1]["step"] == "stack_frames_per_channel"

    def test_externally_handled_steps_do_not_warn(
        self, tmp_path: Path, monkeypatch,
    ):
        """create_master_dark/calibrate_lights laufen in anderen Phasen
        (cli.py) -> keine `pipeline.step_unhandled`-Warning."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        self._run(
            tmp_path,
            ["create_master_dark", "calibrate_lights", "register_frames",
             "stack_frames", "export"],
        )

        assert rec.events_named("pipeline.step_unhandled") == []

    def test_standard_preset_steps_no_warning(self, tmp_path: Path, monkeypatch):
        """Alle Steps der Standard-Presets (aus DEFAULT_CONFIG) erzeugen fuer
        die run()-behandelten und extern behandelten keine Unhandled-Warning
        — nur die noch nicht implementierten (stack_frames_per_channel,
        channel_combination) tauchen auf."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        presets = [p["name"] for p in yaml_safe_load(DEFAULT_CONFIG)["pipeline_presets"]]
        assert "galaxy_standard" in presets

        galaxy_steps = [
            s["name"]
            for p in yaml_safe_load(DEFAULT_CONFIG)["pipeline_presets"]
            if p["name"] == "galaxy_standard"
            for s in p["steps"]
        ]
        self._run(tmp_path, galaxy_steps)

        # galaxy_standard: background_extraction ist jetzt behandelt (GR-C),
        # create_master_dark/calibrate_lights extern -> keine Warnings.
        # (structure_enhancement fehlt in galaxy_standard; es ist seit v1.2
        # ueber das Plugin-System behandelt — separat in
        # test_structure_enhancement.py::TestIntegrationRun abgedeckt.)
        assert rec.events_named("pipeline.step_unhandled") == []

    def test_gr_steps_wired_via_run(self, tmp_path: Path, monkeypatch):
        """S2-B3-Verdrahtung: run() verarbeitet background_extraction UND
        gradient_removal als echte Steps (kein stiller Ignorier-Fall)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        # Echte Frames mit Gradient + enabled GR -> Stack wird flacher
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        frames = [
            _write_rgb_fits(tmp_path / "in" / "f0.fits", _gradient_rgb(seed=1)),
            _write_rgb_fits(tmp_path / "in" / "f1.fits", _gradient_rgb(seed=2)),
        ]
        context = SimpleNamespace(
            target=SimpleNamespace(name="TestTarget", ra=0.0, dec=0.0),
            equipment=SimpleNamespace(focal_length_mm=0.0, pixel_size_um=0.0),
        )
        pipeline = PipelinePreset(
            name="test",
            target_types=["nebula"],
            steps=[
                PipelineStep(name="register_frames"),
                PipelineStep(name="stack_frames"),
                PipelineStep(name="background_extraction"),
                PipelineStep(name="gradient_removal"),
            ],
            processing_params=ProcessingParams(
                gradient_removal=GradientRemovalConfig(enabled=True),
            ),
        )

        result = agent.run(
            context,
            SimpleNamespace(calibrated_lights=[]),
            SimpleNamespace(debayered_frames=frames),
            pipeline,
        )
        assert result.stacked is not None
        assert result.stacked.exists()
        assert not rec.events_named("pipeline.step_unhandled")
        # Beide GR-Stufen wurden real verdrahtet -> completion-Log vorhanden
        assert rec.events_named("pipeline.gradient_removal_complete")

    def test_gr_enabled_without_step_warns_unhandled(
        self, tmp_path: Path, monkeypatch,
    ):
        """GR-01: gradient_removal.enabled=true (CLI/Config) aber Preset ohne
        GR-Step (z.B. star_standard) -> genau 1 Warning
        `pipeline.gradient_removal_unhandled`, Run laeuft durch (kein
        Abbruch), kein GR-Report."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = SimpleNamespace(
            target=SimpleNamespace(name="TestTarget", ra=0.0, dec=0.0),
            equipment=SimpleNamespace(focal_length_mm=0.0, pixel_size_um=0.0),
        )
        pipeline = PipelinePreset(
            name="test",
            target_types=["galaxy"],
            steps=[
                PipelineStep(name="register_frames"),
                PipelineStep(name="stack_frames"),
            ],
            processing_params=ProcessingParams(
                gradient_removal=GradientRemovalConfig(enabled=True),
            ),
        )

        result = agent.run(
            context,
            SimpleNamespace(calibrated_lights=[]),
            SimpleNamespace(debayered_frames=[]),
            pipeline,
        )

        events = rec.events_named("pipeline.gradient_removal_unhandled")
        assert len(events) == 1
        assert result is not None  # Pipeline lief durch
        assert result.gradient_removal is None

    def test_gr_enabled_with_step_no_unhandled_warning(
        self, tmp_path: Path, monkeypatch,
    ):
        """GR-01-Gegenprobe: enabled=true MIT GR-Step im Preset -> KEINE
        `pipeline.gradient_removal_unhandled`-Warning (normaler Pfad)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        context = SimpleNamespace(
            target=SimpleNamespace(name="TestTarget", ra=0.0, dec=0.0),
            equipment=SimpleNamespace(focal_length_mm=0.0, pixel_size_um=0.0),
        )
        pipeline = PipelinePreset(
            name="test",
            target_types=["nebula"],
            steps=[
                PipelineStep(name="register_frames"),
                PipelineStep(name="stack_frames"),
                PipelineStep(name="gradient_removal"),
            ],
            processing_params=ProcessingParams(
                gradient_removal=GradientRemovalConfig(enabled=True),
            ),
        )

        agent.run(
            context,
            SimpleNamespace(calibrated_lights=[]),
            SimpleNamespace(debayered_frames=[]),
            pipeline,
        )

        assert rec.events_named("pipeline.gradient_removal_unhandled") == []


def yaml_safe_load(text: str):
    import yaml
    return yaml.safe_load(text)


# ═══════════════════════════════════════════════════════════════════
# V1.5-4 / DADR-014 — CD-Matrix-Semantik (REG_ROT als separates Keyword)
# (ehemals test_v15_4_cd_matrix_semantik.py — integriert nach A1)
# ═══════════════════════════════════════════════════════════════════


def _write_2d_frame_with_wcs(
    path: Path, data: np.ndarray, cdelt: float = 0.000138889
) -> Path:
    """2D-Frame mit approximativem TAN-WCS (CDELT-Konvention wie
    annotate_export_header: CDELT1 negativ, CDELT2 positiv; 0.5 arcsec)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data.astype(np.float32))
    hdu.header["CRVAL1"] = 10.0
    hdu.header["CRVAL2"] = 20.0
    hdu.header["CRPIX1"] = data.shape[1] / 2.0
    hdu.header["CRPIX2"] = data.shape[0] / 2.0
    hdu.header["CDELT1"] = -cdelt
    hdu.header["CDELT2"] = cdelt
    hdu.header["CTYPE1"] = "RA---TAN"
    hdu.header["CTYPE2"] = "DEC--TAN"
    hdu.header["CUNIT1"] = "deg"
    hdu.header["CUNIT2"] = "deg"
    hdu.writeto(path, overwrite=True)
    return path


def _spike_starfield(size: int = 128) -> np.ndarray:
    """Small synthetic starfield with a few sharp spikes for testing."""
    img = np.zeros((size, size), dtype=np.float32)
    rng = np.random.default_rng(42)
    img += rng.normal(100, 5, img.shape).astype(np.float32)
    for y, x, flux in [(20, 30, 5000), (60, 80, 3000), (90, 50, 8000),
                        (40, 100, 2000), (70, 20, 4000)]:
        if y < size and x < size:
            img[max(0, y-1):y+2, max(0, x-1):x+2] += flux
    return img


class TestRegRotKeyword:
    """Tests fuer REG_ROT als separates FITS-Header-Keyword (DADR-014)."""

    def test_copy_wcs_headers_writes_reg_rot_on_rotation(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=10.0)

        header = fits.getheader(tgt)
        assert "REG_ROT" in header
        assert header["REG_ROT"] == pytest.approx(10.0, abs=1e-10)
        assert "CDELT1" in header
        assert "CDELT2" in header
        assert header["CDELT1"] == pytest.approx(-0.000138889, abs=1e-12)
        assert header["CDELT2"] == pytest.approx(0.000138889, abs=1e-12)
        assert "CD1_1" not in header
        assert "CD1_2" not in header
        assert "CD2_1" not in header
        assert "CD2_2" not in header

    def test_copy_wcs_headers_no_reg_rot_when_zero(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=0.0)

        header = fits.getheader(tgt)
        assert "REG_ROT" not in header
        assert "CDELT1" in header
        assert "CDELT2" in header
        assert "CD1_1" not in header

    def test_reg_rot_via_processing_agent_delegation(self, tmp_path: Path):
        agent = _make_agent(tmp_path / "out")
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        agent._copy_wcs_headers(src, tgt, rotation_deg=5.5)

        header = fits.getheader(tgt)
        assert header["REG_ROT"] == pytest.approx(5.5, abs=1e-10)
        assert "CDELT1" in header
        assert "CD1_1" not in header


class TestWcsCleanliness:
    """WCS bleibt CDELT-only — keine CD-Matrix, kein Rotation-Claim."""

    def test_cdelt_unchanged_with_rotation(self, tmp_path: Path):
        cdelt_val = 0.001
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32),
            cdelt=cdelt_val,
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=15.0)

        header = fits.getheader(tgt)
        assert header["CDELT1"] == pytest.approx(-cdelt_val, abs=1e-12)
        assert header["CDELT2"] == pytest.approx(cdelt_val, abs=1e-12)
        assert abs(header["CDELT2"]) == pytest.approx(cdelt_val, abs=1e-12)

    def test_no_cd_matrix_keys_on_rotation(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        for rot_deg in [0.5, 3.9, 10.0, 45.0, -7.3]:
            multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=rot_deg)
            header = fits.getheader(tgt)
            assert "CD1_1" not in header, f"CD1_1不应在 rotation={rot_deg} 时存在"
            assert "CD1_2" not in header, f"CD1_2不应在 rotation={rot_deg} 时存在"
            assert "CD2_1" not in header, f"CD2_1不应在 rotation={rot_deg} 时存在"
            assert "CD2_2" not in header, f"CD2_2不应在 rotation={rot_deg} 时存在"
            assert "CDELT1" in header, f"CDELT1 muss bei rotation={rot_deg} vorhanden sein"
            assert "CDELT2" in header, f"CDELT2 muss bei rotation={rot_deg} vorhanden sein"

    def test_wcs_basis_keys_preserved_with_rotation(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=12.0)

        header = fits.getheader(tgt)
        assert header["CRVAL1"] == 10.0
        assert header["CRVAL2"] == 20.0
        assert header["CRPIX1"] == 8.0
        assert header["CRPIX2"] == 8.0
        assert header["CTYPE1"] == "RA---TAN"
        assert header["CTYPE2"] == "DEC--TAN"
        assert header["CUNIT1"] == "deg"
        assert header["CUNIT2"] == "deg"


class TestNoBreakingChange:
    """Kein Breaking Change — aktuelle Real-Runs bleiben unveraendert."""

    def test_no_wcs_no_reg_rot(self, tmp_path: Path):
        src = _write_2d_frame(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=5.0)

        header = fits.getheader(tgt)
        assert "REG_ROT" in header
        assert header["REG_ROT"] == pytest.approx(5.0, abs=1e-10)
        assert "CDELT1" not in header
        assert "CDELT2" not in header
        assert "CD1_1" not in header

    def test_negative_rotation_sets_reg_rot(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=-7.3)

        header = fits.getheader(tgt)
        assert header["REG_ROT"] == pytest.approx(-7.3, abs=1e-10)
        assert "CDELT1" in header
        assert "CD1_1" not in header


class TestArchiveRegRot:
    """Archive-Agent liest REG_ROT aus dem Final-FITS fuer agent-log."""

    def test_read_reg_rot_from_fits_with_keyword(self, tmp_path: Path):
        fits_path = tmp_path / "test.fits"
        hdu = fits.PrimaryHDU(np.zeros((10, 10), dtype=np.float32))
        hdu.header["REG_ROT"] = 12.5
        hdu.writeto(fits_path, overwrite=True)

        result = ArchiveAgent._read_reg_rot_from_fits(fits_path)
        assert result == pytest.approx(12.5, abs=1e-10)

    def test_read_reg_rot_from_fits_without_keyword(self, tmp_path: Path):
        fits_path = tmp_path / "test.fits"
        hdu = fits.PrimaryHDU(np.zeros((10, 10), dtype=np.float32))
        hdu.writeto(fits_path, overwrite=True)

        result = ArchiveAgent._read_reg_rot_from_fits(fits_path)
        assert result is None

    def test_read_reg_rot_from_fits_none_path(self):
        assert ArchiveAgent._read_reg_rot_from_fits(None) is None

    def test_read_reg_rot_from_fits_nonexistent(self, tmp_path: Path):
        result = ArchiveAgent._read_reg_rot_from_fits(tmp_path / "nope.fits")
        assert result is None


class TestRegRotEdgeCases:
    """Edge Cases fuer REG_ROT Implementierung."""

    def test_very_small_rotation(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=0.001)

        header = fits.getheader(tgt)
        assert header["REG_ROT"] == pytest.approx(0.001, abs=1e-10)

    def test_large_rotation(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=180.0)

        header = fits.getheader(tgt)
        assert header["REG_ROT"] == pytest.approx(180.0, abs=1e-10)
        assert "CDELT1" in header
        assert "CD1_1" not in header

    def test_comment_added_on_rotation(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=10.0)

        header = fits.getheader(tgt)
        comments = []
        for card in header.cards:
            if card.keyword == "COMMENT":
                comments.append(str(card.value))
        assert any("DADR-014" in c for c in comments), \
            f"Kein DADR-014-Comment gefunden: {comments}"

    def test_existing_reg_rot_overwritten(self, tmp_path: Path):
        src = _write_2d_frame_with_wcs(
            tmp_path / "src.fits", np.zeros((16, 16), dtype=np.float32)
        )
        tgt = _write_2d_frame(
            tmp_path / "tgt.fits", np.zeros((16, 16), dtype=np.float32)
        )
        with fits.open(tgt, mode="update") as hdul:
            hdul[0].header["REG_ROT"] = 99.0
            hdul.flush()

        multi_group_agent.copy_wcs_headers(src, tgt, rotation_deg=5.0)

        header = fits.getheader(tgt)
        assert header["REG_ROT"] == pytest.approx(5.0, abs=1e-10)

