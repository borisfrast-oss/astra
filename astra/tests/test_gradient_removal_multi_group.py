"""Sprint-2 Etappe-3 Integrationstests: GR-D Multi-Group (S2-B5) + GR-E Reporting (S2-B6).

Abgedeckt:
- S2-B5 / AC-GR-D1..D2: `process_multi_group` wendet Gradient Removal pro
  Gruppen-Stack NACH dem Stacking (Pass 1) und VOR der Cross-Group-
  Registration (Pass 2, `_register_to_reference_stack`) an; die
  `group_*/04_stacked/`-Struktur bleibt unveraendert; der GR-Report landet
  pro Gruppe in group_metadata (und damit in merge_report/agent-log).
- S2-B6 / AC-GR-E1..E2: merge_report `gradient_removal`-Block additiv
  (applied + Modell-Parameter, nur Gruppen mit GR-Report); agent-log
  `gradient_removal` je Gruppe; Fehlerfall -> Skip + Warning, Gruppe laeuft
  weiter, Pipeline-Status success_with_warnings; Single-Group run()
  exponiert den Report (ProcessingResult + agent-log processing).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    import astropy.io.fits as fits
except ImportError:  # pragma: no cover - tests run from repo root
    fits = None  # type: ignore[assignment]

import astro_process.agents.archive as archive_mod  # noqa: E402
import astro_process.agents.processing_agent as processing_agent_mod  # noqa: E402
from astro_process.agents.merge_agent import MergeAgent  # noqa: E402
from astro_process.agents.processing_agent import (  # noqa: E402
    ProcessingAgent,
    ProcessingResult,
)
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
)
from astro_process.config.models import (  # noqa: E402
    GradientRemovalConfig,
    MergeConfig,
    MultiGroupConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
)
from astro_process.models.core import (  # noqa: E402
    AcquisitionInfo,
    CalibrationStatus,
    EquipmentInfo,
    FitsHeader,
    FrameInfo,
    FrameSet,
    FrameType,
    ObservationContext,
    ObservationTarget,
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


def _write_2d_fits(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data.astype(np.float32))
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


# ── Multi-Group-Kontext-Helfer ────────────────────────────────────


def _make_context(
    path: Path,
    group_count: int = 2,
    frames_per_group: int = 3,
) -> ObservationContext:
    """Synthetischer 2-Gruppen-Kontext (15s60 / 60s40), echte FITS-Frames
    mit Headern (Discovery braucht FitsHeader)."""
    params = [(15.0, 60, None), (60.0, 40, None)][:group_count]
    all_frames = []
    cal_status = CalibrationStatus(dark_available=True)

    for idx, (exptime, gain, filt) in enumerate(params):
        gp = path / f"group_{idx}"
        gp.mkdir(parents=True, exist_ok=True)
        for i in range(frames_per_group):
            fp = gp / f"light_{i:04d}.fits"
            _write_rgb_fits(fp, _gradient_rgb(seed=idx * 10 + i))
            all_frames.append(
                FrameInfo(
                    path=fp,
                    frame_type=FrameType.LIGHT,
                    header=FitsHeader(exptime=exptime, gain=gain, filter_name=filt),
                    index=i,
                    size_bytes=fp.stat().st_size,
                    width=SHAPE[0],
                    height=SHAPE[1],
                )
            )

    light_set = FrameSet(frame_type=FrameType.LIGHT, frames=all_frames)
    return ObservationContext(
        target=ObservationTarget(name="TestTarget", ra=180.0, dec=30.0),
        frames={FrameType.LIGHT: light_set},
        calibration=cal_status,
        equipment=EquipmentInfo(
            telescope="TestScope", focal_length_mm=200.0, pixel_size_um=3.76,
        ),
        acquisition=AcquisitionInfo(gain=100),
        source_path=path,
    )


def _make_pipeline(
    *, steps: list[str] | None = None,
    gr_enabled: bool = False,
    gr_degree: int = 2,
    gr_grid: tuple[int, int] = (16, 16),
    gr_sigma_clip: float = 3.0,
    gr_min_samples: int | None = None,
) -> PipelinePreset:
    if steps is None:
        steps = ["register_frames", "stack_frames", "gradient_removal"]
    return PipelinePreset(
        name="test",
        target_types=["nebula"],
        steps=[PipelineStep(name=s) for s in steps],
        processing_params=ProcessingParams(
            gradient_removal=GradientRemovalConfig(
                enabled=gr_enabled,
                degree=gr_degree,
                grid=gr_grid,
                sigma_clip=gr_sigma_clip,
                min_samples=gr_min_samples,
            ),
        ),
    )


def _run_multi_group(
    agent: ProcessingAgent,
    tmp_dir: Path,
    pipeline: PipelinePreset,
    *,
    stack_paths: dict[str, Path] | None = None,
    merge_agent=None,
    mg_config: MultiGroupConfig | None = None,
) -> tuple[ProcessingResult, list[float]]:
    """process_multi_group mit gemockten schweren Schritten
    (register/stack/cross/pcc). Die Gruppen-Stacks sind ECHTE FITS mit
    Gradient (un-normalisiert, wie _background_extraction es in Etappe 2
    verarbeitet) — GR laeuft real auf jedem Stack.

    Reihenfolge der Gruppen = Frame-Reihenfolge (group_by_params, siehe
    _make_context): "15s60" zuerst, dann "60s40".

    Returns:
        (result, edge_stds_beim_cross_call)
        edge_stds_beim_cross_call: Flachheit jedes Nicht-Referenz-Stacks zum
        Zeitpunkt von `_register_to_reference_stack` (GR-D-Reihenfolge-Beweis).
    """
    if mg_config is None:
        mg_config = MultiGroupConfig()
    if stack_paths is None:
        stack_paths = {
            "15s60": _write_rgb_fits(tmp_dir / "stack_15s60.fits", _gradient_rgb(seed=1)),
            "60s40": _write_rgb_fits(tmp_dir / "stack_60s40.fits", _gradient_rgb(seed=2)),
        }

    context = _make_context(tmp_dir)
    lights = context.get_lights()
    frame_paths = [f.path for f in lights.frames if f.path.exists()]
    cal_result = SimpleNamespace(calibrated_lights=frame_paths)
    deb_result = SimpleNamespace(debayered_frames=[])

    pcc_counter = {"n": 0}
    order = ["15s60", "60s40"]
    call_count = {"n": 0}

    def fake_pcc(stack_path, *args, **kwargs):
        pcc_counter["n"] += 1
        p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
        _write_rgb_fits(p, _gradient_rgb(seed=10 + pcc_counter["n"]))
        return (p, "gaia_success")

    def fake_stack(registered, params, **kwargs):
        gh = order[call_count["n"]]
        call_count["n"] += 1
        return stack_paths[gh]

    edge_stds: list[float] = []

    def fake_cross(stack_path, ref_stack_path, filter_name, stack_dir, **kwargs):
        # GR-D-Reihenfolge: zum Zeitpunkt der Cross-Group-Registration muss
        # der Stack bereits GR-behandelt sein (flacher Rand).
        edge_stds.append(_frame_edge_std(_read_fits(Path(stack_path))))
        return RegistrationResult(path=Path(stack_path), status="ok", corr_hp=0.9)

    def fake_register(frames, params, **kwargs):
        # Registrations-Pass ist nicht Gegenstand dieser Tests; Metriken-
        # Reset nachbilden, damit group_qualities keine Altlasten traegt.
        # Refactor 2026-08-14 (Cluster 3): process_multi_group erwartet ein
        # RegisterFramesResult (uebernimmt die _last_*-Attribute).
        return RegisterFramesResult(
            registered=list(frames),
            last_frame_qualities=[],
            last_frame_rejected=0,
            last_registration_metrics={},
        )

    with patch("astro_process.agents.multi_group_agent.register_frames", side_effect=fake_register), \
         patch("astro_process.agents.multi_group_agent.stack_frames", side_effect=fake_stack), \
         patch.object(agent, "_register_to_reference_stack", side_effect=fake_cross), \
         patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
        result = agent.process_multi_group(
            context, cal_result, deb_result, pipeline,
            multi_group_config=mg_config,
            merge_agent=merge_agent,
        )
    return result, edge_stds


# ═══════════════════════════════════════════════════════════════════
# S2-B5 — GR-D: Multi-Group (AC-GR-D1..D2, OQ-GR-5)
# ═══════════════════════════════════════════════════════════════════


class TestGradientRemovalMultiGroup:
    def test_gr_applied_to_each_group_stack_before_cross_registration(
        self, tmp_path: Path,
    ):
        """AC-GR-D1: Jeder Gruppen-Stack wird bei aktiviertem Schritt
        gradientenbereinigt, bevor PCC pro Gruppe läuft; die Cross-Group-
        Registration sieht bereits flache Stacks (GR VOR Pass 2)."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        stack_paths = {
            "15s60": _write_rgb_fits(tmp_path / "stack_15s60.fits", _gradient_rgb(seed=1)),
            "60s40": _write_rgb_fits(tmp_path / "stack_60s40.fits", _gradient_rgb(seed=2)),
        }
        # Voraussetzung: injizierter Gradient ist messbar (Etappe-2-Toleranz)
        for _gh, p in stack_paths.items():
            assert _frame_edge_std(_read_fits(p)) > 5.0

        result, edge_stds = _run_multi_group(
            agent, tmp_path, _make_pipeline(gr_enabled=True),
            stack_paths=stack_paths,
        )

        assert isinstance(result, ProcessingResult)
        # Beide Gruppen-Stacks wurden GR-behandelt: Rand-Flachheit beim
        # Cross-Call unter dem injizierten Niveau (before > 5.0).
        assert len(edge_stds) == 1  # nur die Nicht-Referenz-Gruppe
        assert all(es < 2.0 for es in edge_stds)

        # group_*/04_stacked/-Struktur unveraendert (nur Dateiinhalt ersetzt)
        groups = result.multi_group_metadata["groups"]
        assert set(groups.keys()) == {"15s60", "60s40"}
        for _gh, meta in groups.items():
            assert meta["gradient_removal"]["applied"] is True
            assert meta["gradient_removal"]["degree"] == 2
            assert meta["gradient_removal"]["grid"] == [16, 16]
            assert "n_samples" in meta["gradient_removal"]
            assert "residual_mad" in meta["gradient_removal"]
            assert "channel_scales" in meta["gradient_removal"]
            assert "coefficients" in meta["gradient_removal"]

    def test_gr_disabled_leaves_stacks_unchanged_and_no_report_block(
        self, tmp_path: Path, monkeypatch,
    ):
        """AC-GR-D2/Backward-Compat: enabled false -> Stacks byte-identisch
        (v1.1-identisch, AC-GR-C3 im Multi-Group-Pfad) und KEIN
        gradient_removal-Eintrag in group_metadata (additiv, Legacy-valide)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        stack_paths = {
            "15s60": _write_rgb_fits(tmp_path / "stack_15s60.fits", _gradient_rgb(seed=1)),
            "60s40": _write_rgb_fits(tmp_path / "stack_60s40.fits", _gradient_rgb(seed=2)),
        }
        raw = {gh: p.read_bytes() for gh, p in stack_paths.items()}

        result, _ = _run_multi_group(
            agent, tmp_path, _make_pipeline(gr_enabled=False),
            stack_paths=stack_paths,
        )

        # Stacks unveraendert durch GR (byte-identisch)
        assert stack_paths["15s60"].read_bytes() == raw["15s60"]
        assert stack_paths["60s40"].read_bytes() == raw["60s40"]

        groups = result.multi_group_metadata["groups"]
        for _gh, meta in groups.items():
            assert "gradient_removal" not in meta
        # disabled -> Info-Log, kein Completion
        assert rec.events_named("pipeline.gradient_removal_disabled")
        assert rec.events_named("pipeline.gradient_removal_complete") == []

    def test_2d_group_stack_skipped_but_group_continues(self, tmp_path: Path):
        """Guard: 2D-Stack (mono) -> GR Skip (applied false), Gruppe laeuft
        trotzdem weiter (wird registriert/gemergt)."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        stack_paths = {
            "15s60": _write_rgb_fits(
                tmp_path / "stack_15s60.fits", _gradient_rgb(seed=1),
            ),
            "60s40": _write_2d_fits(
                tmp_path / "stack_60s40_2d.fits", _gradient_rgb(seed=2)[..., 1],
            ),
        }

        result, _ = _run_multi_group(
            agent, tmp_path, _make_pipeline(gr_enabled=True),
            stack_paths=stack_paths,
        )

        groups = result.multi_group_metadata["groups"]
        assert "15s60" in groups  # kein Gruppenverlust
        assert "60s40" in groups  # kein Gruppenverlust
        assert groups["15s60"]["gradient_removal"]["applied"] is True
        assert groups["60s40"]["gradient_removal"]["applied"] is False
        assert "expected_3d_rgb" in groups["60s40"]["gradient_removal"]["skipped_reason"]

    def test_no_gr_step_preset_no_report_block(self, tmp_path: Path):
        """Preset ohne background_extraction/gradient_removal-Step -> kein
        GR-Attempt, kein Report-Block (additiv, Legacy-valide)."""
        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        pipeline = _make_pipeline(steps=["register_frames", "stack_frames"], gr_enabled=True)

        result, _ = _run_multi_group(agent, tmp_path, pipeline)

        groups = result.multi_group_metadata["groups"]
        assert "15s60" in groups
        assert "60s40" in groups
        for _gh, meta in groups.items():
            assert "gradient_removal" not in meta

    def test_gr_enabled_without_step_warns_unhandled_multi_group(
        self, tmp_path: Path, monkeypatch,
    ):
        """GR-01 (Multi-Group): gradient_removal.enabled=true (CLI/Config)
        aber Preset ohne GR-Step -> genau 1 Warning
        `pipeline.gradient_removal_unhandled` pro Lauf; Gruppen laufen
        durch (kein Abbruch, kein GR-Feld)."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        pipeline = _make_pipeline(steps=["register_frames", "stack_frames"], gr_enabled=True)

        result, _ = _run_multi_group(agent, tmp_path, pipeline)

        events = rec.events_named("pipeline.gradient_removal_unhandled")
        assert len(events) == 1  # genau EINE Warning pro Lauf (nicht je Gruppe)
        groups = result.multi_group_metadata["groups"]
        assert "15s60" in groups  # kein Abbruch
        assert "60s40" in groups  # kein Abbruch
        for _gh, meta in groups.items():
            assert "gradient_removal" not in meta


# ═══════════════════════════════════════════════════════════════════
# S2-B6 — GR-E: Reporting + Guards (AC-GR-E1..E2)
# ═══════════════════════════════════════════════════════════════════


class TestGradientRemovalReporting:
    def _mg_metadata_with_gr(self) -> dict:
        return {
            "groups": {
                "15s60": {
                    "frame_count": 3,
                    "exptime": 15.0,
                    "gain": 60,
                    "filter": None,
                    "total_exposure": 45.0,
                    "weight": 3.0,
                    "pcc_status": "gaia_success",
                    "gradient_removal": {
                        "applied": True,
                        "degree": 2,
                        "grid": [16, 16],
                        "sigma_clip": 3.0,
                        "n_samples": 900,
                        "n_rejected": 20,
                        "n_iterations": 3,
                        "residual_mad": 0.42,
                        "residual_max": 1.1,
                        "channel_scales": [1.0, 1.0, 1.0],
                        "coefficients": [5.0, -1.0, 0.5, 0.25, -0.3, 0.1],
                    },
                },
                "60s40": {
                    "frame_count": 2,
                    "exptime": 60.0,
                    "gain": 40,
                    "filter": None,
                    "total_exposure": 120.0,
                    "weight": 2.0,
                    "pcc_status": "gaia_success",
                },
            },
        }

    def test_merge_report_gradient_removal_block_additive(self):
        """AC-GR-E1/AC-GR-D2: merge_report enthaelt gradient_removal-Block
        (per-Group, applied + Modell-Parameter); Gruppe ohne GR-Report (g2)
        erzeugt keinen Eintrag; bestehende Felder unveraendert."""
        group_metadata = {
            "15s60": {
                "frame_count": 3,
                "exptime": 15.0,
                "gain": 60,
                "filter": None,
                "total_exposure": 45.0,
                "dark_source": "none",
                "pcc_status": "gaia_success",
                "gradient_removal": {
                    "applied": True,
                    "degree": 2,
                    "grid": [16, 16],
                    "sigma_clip": 3.0,
                    "n_samples": 900,
                    "n_rejected": 20,
                    "n_iterations": 3,
                    "residual_mad": 0.42,
                    "residual_max": 1.1,
                    "channel_scales": [1.0, 1.0, 1.0],
                    "coefficients": [5.0, -1.0, 0.5, 0.25, -0.3, 0.1],
                },
            },
            "60s40": {
                "frame_count": 2,
                "exptime": 60.0,
                "gain": 40,
                "filter": None,
                "total_exposure": 120.0,
                "dark_source": "none",
                "pcc_status": "gaia_success",
            },
        }
        merged = np.zeros((4, 4), dtype=np.float32)
        report = MergeAgent._build_merge_report(
            merge_config=MergeConfig(),
            ref_hash="15s60",
            merged_path=Path("/tmp/x.fits"),
            merged=merged,
            group_stacks={"15s60": Path("/tmp/a.fits"), "60s40": Path("/tmp/b.fits")},
            group_metadata=group_metadata,
            stack_hashes=["15s60", "60s40"],
            weights=[3.0, 2.0],
            pcc_fallback_groups=[],
        )

        assert "gradient_removal" in report
        assert report["gradient_removal"]["15s60"]["applied"] is True
        assert report["gradient_removal"]["15s60"]["n_samples"] == 900
        assert report["gradient_removal"]["15s60"]["residual_mad"] == 0.42
        assert report["gradient_removal"]["15s60"]["degree"] == 2
        # Gruppe ohne GR-Daten erzeugt keinen Eintrag (additiv)
        assert "60s40" not in report["gradient_removal"]
        # Bestehende Felder weiterhin vorhanden (kein Bruch)
        assert report["method"] == "weighted_average"
        assert len(report["input_stacks"]) == 2
        assert "quality" in report

    def test_merge_report_gr_block_from_multi_group_run(self, tmp_path: Path):
        """AC-GR-D2 (End-to-End): process_multi_group mit echtem MergeAgent
        -> merge_report.json enthaelt gradient_removal-Block je Gruppe."""
        import json

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        merge_agent = MergeAgent(working_dir=tmp_path / "out", config=None)

        result, _ = _run_multi_group(
            agent, tmp_path, _make_pipeline(gr_enabled=True),
            merge_agent=merge_agent,
        )

        assert result.stacked is not None
        assert result.stacked.exists()
        # Refactor 2026-08-21 (ray-major-3): result.stacked zeigt jetzt auf
        # den PCC-Hook-Return-Pfad, nicht mehr auf merged/pcc_applied.fits.
        # Der Report-Ort ist davon unabhaengig: immer {working_dir}/merged/.
        report_path = tmp_path / "out" / "merged" / "merge_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert "gradient_removal" in report
        for gh in result.multi_group_metadata["groups"]:
            assert gh in report["gradient_removal"]
            assert report["gradient_removal"][gh]["applied"] is True

    def test_agent_log_contains_gradient_removal_per_group(self, tmp_path: Path):
        """AC-GR-E1/AC-GR-D2: agent-log enthaelt gradient_removal je Gruppe
        (additiv, Legacy ohne GR-Feld bleibt valide)."""
        import yaml

        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            target=SimpleNamespace(
                name="TestTarget",
                target_type=SimpleNamespace(value="galaxy"),
            ),
            total_integration_time=165.0,
            total_light_frames=5,
            calibration=SimpleNamespace(
                dark_count=0, flat_count=0, bias_count=0
            ),
        )
        calibration_result = SimpleNamespace(
            master_dark=None, calibrated_lights=[],
        )
        proc_result = SimpleNamespace(
            registered_frames=[],
            stacked=None,
            exports=[],
            multi_group_metadata=self._mg_metadata_with_gr(),
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
            multi_group_metadata=self._mg_metadata_with_gr(),
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))

        groups = log["multi_group"]["groups"]
        by_hash = {g["hash"]: g for g in groups}
        assert by_hash["15s60"]["gradient_removal"]["applied"] is True
        assert by_hash["15s60"]["gradient_removal"]["n_samples"] == 900
        # Gruppe ohne GR-Report: leeres dict (Legacy-valide)
        assert by_hash["60s40"]["gradient_removal"] == {}
        # Bestehende Sektionen unveraendert
        assert log["processing"]["frame_quality"] == []

    def test_agent_log_single_group_processing_gradient_removal(self, tmp_path: Path):
        """AC-GR-E1 (Single-Group): agent-log processing.gradient_removal
        enthaelt den GR-Report; Legacy-Result ohne Feld -> leeres dict."""
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
            master_dark=None, calibrated_lights=[],
        )
        proc_result = SimpleNamespace(
            registered_frames=[Path("/tmp/r0.fits")],
            stacked=Path("/tmp/stacked.fits"),
            exports=[],
            multi_group_metadata=None,
            gradient_removal={
                "applied": True,
                "degree": 2,
                "grid": [16, 16],
                "sigma_clip": 3.0,
                "n_samples": 900,
                "n_rejected": 20,
                "n_iterations": 3,
                "residual_mad": 0.42,
                "residual_max": 1.1,
                "channel_scales": [1.0, 1.0, 1.0],
                "coefficients": [5.0, -1.0, 0.5, 0.25, -0.3, 0.1],
            },
        )

        agent = archive_mod.ArchiveAgent(output_root=output_dir, config=None)
        log_path = agent._create_agent_log(
            output_dir, context, proc_result, calibration_result,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert log["processing"]["gradient_removal"]["applied"] is True
        assert log["processing"]["gradient_removal"]["n_samples"] == 900

    def test_gr_error_skips_but_pipeline_continues(self, tmp_path: Path, monkeypatch):
        """AC-GR-E2: Fit scheitert (min_samples > Zellen) -> Skip + Warning,
        Report applied:false, Gruppen bleiben im Merge, kein Raise."""
        rec = _LogRecorder()
        monkeypatch.setattr(processing_agent_mod, "logger", rec)

        agent = ProcessingAgent(working_dir=tmp_path / "out", config=None)
        # grid (8, 8) -> 64 Zellen < min_samples 600 -> GradientRemovalError
        pipeline = _make_pipeline(
            gr_enabled=True, gr_grid=(8, 8), gr_min_samples=600,
        )

        result, _ = _run_multi_group(agent, tmp_path, pipeline)

        # Beide Gruppen vorhanden und mit Skip-Report (kein Gruppenverlust)
        groups = result.multi_group_metadata["groups"]
        assert set(groups.keys()) == {"15s60", "60s40"}
        for _gh, meta in groups.items():
            assert meta["gradient_removal"]["applied"] is False
            assert meta["gradient_removal"]["skipped_reason"] == "gradient_removal_error"
        assert rec.events_named("pipeline.gradient_removal_skipped")
        assert rec.events_named("pipeline.status")


# ═══════════════════════════════════════════════════════════════════
# GR-E Konsistenz — Single-Group run() exponiert den Report
# ═══════════════════════════════════════════════════════════════════


class TestGradientRemovalSingleGroupReport:
    def test_run_exposes_gradient_removal_report(self, tmp_path: Path):
        """run() -> ProcessingResult.gradient_removal (applied + Parameter)."""
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

        assert result.gradient_removal is not None
        assert result.gradient_removal["applied"] is True
        assert result.gradient_removal["degree"] == 2
        assert result.gradient_removal["grid"] == [16, 16]
        assert "n_samples" in result.gradient_removal
        assert "residual_mad" in result.gradient_removal

    def test_run_disabled_report_is_none(self, tmp_path: Path):
        """disabled -> ProcessingResult.gradient_removal bleibt None (kein
        Report-Block, Legacy-kompatibel)."""
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
                PipelineStep(name="gradient_removal"),
            ],
            processing_params=ProcessingParams(
                gradient_removal=GradientRemovalConfig(enabled=False),
            ),
        )

        result = agent.run(
            context,
            SimpleNamespace(calibrated_lights=[]),
            SimpleNamespace(debayered_frames=frames),
            pipeline,
        )

        assert result.gradient_removal is None
