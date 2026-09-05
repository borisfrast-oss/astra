"""Tests for W9-C: Registration-Strategy-Interface + Arbitration (AC-W9-C1..C5, ADR-022).

Teststrategie (S1-A7, konsistent mit test_registration_w9.py):
- Unit-Tests mit Fake-Modulen pruefen das Strategy-Interface (Dispatcher,
  Mapping auf Pipeline-Konvention, Sanity-Guards, Apply-Helper).
- Agent-E2E-Tests pruefen die Compute-both-Arbitration in `register_frames`
  (astroalign-Gewinn, Downgrade, Fallback, Zero-Shift als letztes Netz,
  Transform-Log AC-W9-C2).
- structlog geht NICHT durch stdlib-Logging — `caplog` faengt Warnings nicht.
  Die Modul-Logger-Objekte werden durch `_LogRecorder` ersetzt und die
  Event-Namen direkt geprueft (Muster aus test_registration_w9.py).
- Ein Real-Synthetik-Test (nur wenn das Extra installiert ist) belegt den
  W9-Zweck auf dem M13-Analog (AC-W9-C7): fft verfehlt Subpixel+Rotation,
  astroalign gewinnt die Arbitration (Spike-Demo corr_hp 0.9993 vs 0.4784).
- Der Lazy-Import-Cache wird vor/nach jedem Test zurueckgesetzt (autouse).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from astropy.io import fits
from scipy.ndimage import rotate
from scipy.ndimage import shift as scipy_shift
from click.testing import CliRunner

# ── Ensure src + tests dir on the path ───────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astro_process.agents.multi_group_agent as multi_group_agent  # noqa: E402
import astro_process.agents.processing_agent as processing_agent  # noqa: E402
import astro_process.core.registration as registration  # noqa: E402
import astro_process.core.stacking as stacking  # noqa: E402
from astro_process.agents.processing_agent import ProcessingAgent  # noqa: E402
from astro_process.agents.merge_agent import MergeAgent  # noqa: E402
from astro_process.cli import cli  # noqa: E402
from astro_process.config.models import (  # noqa: E402
    MergeConfig,
    MultiGroupConfig,
    ProcessingParams,
)
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
    register_frames,
)
from astro_process.core.stacking import stack_frames  # noqa: E402

# V1.3-1 Registrations-Empfehlung (integriert aus test_v13_1_recommendation.py)
from astro_process.agents.discovery import (  # noqa: E402
    MAX_ROTATION_SUGGESTION_DEG,
    build_recommendation,
)

# Multi-Group-Helfer (gleiches Test-Paket, Muster test_registration_cross_group.py):
from test_multi_group import create_test_fits, make_sample_context  # noqa: E402


class _LogRecorder:
    """Ersetzt ein structlog-Modul-Logger-Objekt und sammelt warning/info."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    @property
    def names(self) -> list[str]:
        return [e for e, _ in self.events]

    def events_named(self, name: str) -> list[tuple[str, dict]]:
        return [e for e in self.events if e[0] == name]


@pytest.fixture(autouse=True)
def _reset_cache():
    registration._reset_astroalign_cache()
    yield
    registration._reset_astroalign_cache()


class _FakeSimilarityTransform:
    """Minimales skimage-SimilarityTransform-Ersatz (T.translation, T.rotation,
    T.scale) — Mapping-Semantik wie astroalign (x, y)."""

    def __init__(self, x: float = 0.0, y: float = 0.0,
                 rotation_deg: float = 0.0, scale: float = 1.0) -> None:
        self.translation = np.array([float(x), float(y)])
        self.rotation = np.radians(float(rotation_deg))
        self.scale = float(scale)


def _install_fake_module(monkeypatch: pytest.MonkeyPatch,
                         find_transform=None,
                         apply_transform=None) -> None:
    """Setzt den Lazy-Import-Cache direkt auf ein Fake-Modul (umgeht den
    echten `import astroalign`). Defaults: (0,0)-Transform + identische
    Anwendung."""
    if find_transform is None:
        def find_transform(source, target, **kwargs):
            return _FakeSimilarityTransform(), (list(range(5)), list(range(5)))
    if apply_transform is None:
        def apply_transform(transform, source, target,
                            fill_value=None, propagate_mask=False):
            return source, np.ones_like(source, dtype=bool)
    fake = SimpleNamespace(
        find_transform=find_transform,
        apply_transform=apply_transform,
        MaxIterError=type("MaxIterError", (RuntimeError,), {}),
    )
    monkeypatch.setattr(registration, "_astroalign_module", fake)
    monkeypatch.setattr(registration, "_astroalign_checked", True)
    monkeypatch.setattr(registration, "_astroalign_available", True)


# ═══════════════════════════════════════════════════════════════════
# Section: Strategy-API und Dispatcher (ADR-022, AC-W9-C1)
# ═══════════════════════════════════════════════════════════════════


def test_module_has_strategy_api():
    """ADR-022-Bausteine sind vorhanden: RegistrationTransform (frozen),
    RegistrationStrategy (Protocol), FftGridRegistration,
    AstroalignRegistration, RegistrationSanityError, create_registration,
    _apply_registration_transform."""
    assert registration.RegistrationTransform.__dataclass_fields__.keys() == {
        "method", "shift_y", "shift_x", "rotation_deg", "scale",
        "n_control_points", "status", "reason", "transform",
    }
    assert registration.RegistrationTransform.__dataclass_params__.frozen
    assert hasattr(registration, "RegistrationStrategy")
    assert hasattr(registration, "FftGridRegistration")
    assert hasattr(registration, "AstroalignRegistration")
    assert issubclass(registration.RegistrationSanityError, RuntimeError)
    assert callable(registration.create_registration)
    assert callable(registration._apply_registration_transform)


def test_create_registration_dispatcher():
    """Dispatcher: "fft" -> FftGridRegistration, "astroalign" ->
    AstroalignRegistration, unbekannt -> ValueError."""
    fft = registration.create_registration("fft")
    assert isinstance(fft, registration.FftGridRegistration)

    aa = registration.create_registration("astroalign", max_control_points=10)
    assert isinstance(aa, registration.AstroalignRegistration)
    assert aa._max_control_points == 10

    with pytest.raises(ValueError, match="Unbekannte"):
        registration.create_registration("mystery")


# ═══════════════════════════════════════════════════════════════════
# Section: FftGridRegistration kapselt grid_shift_fn (AC-W9-C5)
# ═══════════════════════════════════════════════════════════════════


def test_fft_strategy_calls_grid_shift_fn_unchanged():
    """AC-W9-C5: FftGridRegistration ruft die gebundene grid_shift_fn exakt
    mit (ref_hp, tgt_hp) und bildet das Ergebnis 1:1 auf den
    RegistrationTransform ab (shift_y/shift_x, rotation 0, scale 1,
    n_control_points None, transform None)."""
    calls: list[tuple] = []

    def _fake_grid(ref, tgt):
        calls.append((ref, tgt))
        return 0.7504, 5, 3

    strategy = registration.create_registration(
        "fft", grid_shift_fn=_fake_grid,
    )
    assert strategy.available() is True

    ref = np.zeros((16, 16), dtype=np.float32)
    tgt = np.zeros((16, 16), dtype=np.float32)
    t = strategy.compute(ref, tgt)

    assert len(calls) == 1
    assert calls[0] == (ref, tgt)
    assert t.method == "fft"
    assert t.shift_y == 5.0
    assert t.shift_x == 3.0
    assert t.rotation_deg == 0.0
    assert t.scale == 1.0
    assert t.n_control_points is None
    assert t.transform is None


# ═══════════════════════════════════════════════════════════════════
# Section: AstroalignRegistration Mapping (AC-W9-C1, ADR-020-Falle a)
# ═══════════════════════════════════════════════════════════════════


def test_astroalign_strategy_available_true_with_fake(monkeypatch: pytest.MonkeyPatch):
    """available() -> True, wenn das (Fake-)Modul installiert ist."""
    _install_fake_module(monkeypatch)
    strategy = registration.create_registration("astroalign")
    assert strategy.available() is True


def test_astroalign_strategy_available_false_warns_once(
    monkeypatch: pytest.MonkeyPatch,
):
    """available() -> False + genau EINE `registration.astroalign_unavailable`-
    Warning, wenn das Extra fehlt; zweiter Aufruf ohne neue Warning."""
    monkeypatch.setitem(sys.modules, "astroalign", None)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    strategy = registration.create_registration("astroalign")
    assert strategy.available() is False
    assert strategy.available() is False

    assert rec.names == ["registration.astroalign_unavailable"]


def test_astroalign_strategy_maps_pipeline_convention(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-C1/ADR-020-Falle (a): shift_y = T.translation[1],
    shift_x = T.translation[0] (astroalign (x,y)=(cols,rows) vs. Pipeline
    (rows,cols)); rotation_deg = degrees(T.rotation); scale = T.scale;
    n_control_points = len(source_pos); max_control_points wird an die API
    durchgereicht (None -> 50)."""
    seen: dict = {}

    def _fake_find(source, target, **kwargs):
        seen.update(kwargs)
        # injection: tgt hat Move rows=+2.3, cols=-1.7 von ref -> erwartet
        # (cols=+1.7002, rows=-2.3005) laut Spike-Befund §4
        return (_FakeSimilarityTransform(x=1.7002, y=-2.3005,
                                         rotation_deg=0.3, scale=1.0001),
                (list(range(4)), list(range(4))))

    _install_fake_module(monkeypatch, find_transform=_fake_find)
    strategy = registration.create_registration("astroalign")

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)
    t = strategy.compute(ref, tgt)

    assert seen == {"max_control_points": 50}
    assert t.method == "astroalign"
    assert t.shift_y == pytest.approx(-2.3005, abs=1e-4)
    assert t.shift_x == pytest.approx(1.7002, abs=1e-4)
    assert t.rotation_deg == pytest.approx(0.3, abs=1e-6)
    assert t.scale == pytest.approx(1.0001, abs=1e-6)
    assert t.n_control_points == 4
    assert t.status == "ok"
    assert t.transform is not None


# ═══════════════════════════════════════════════════════════════════
# Section: Sanity-Guards (S1-A7, Discard -> fft)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("scale", "rotation_deg"),
    [(1.05, 0.0), (0.95, 0.0), (1.0, 3.0), (1.02, 2.1), (0.98, -2.5)],
)
def test_astroalign_strategy_sanity_guards_reject(
    monkeypatch: pytest.MonkeyPatch, scale: float, rotation_deg: float,
):
    """|scale - 1| > 0.02 ODER |rotation| > 2 Grad -> RegistrationSanityError
    + `registration.astroalign_sanity_rejected`-Warning (Aufrufer: fft)."""
    def _fake_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=0.0, y=0.0,
                                         rotation_deg=rotation_deg,
                                         scale=scale),
                (list(range(3)), list(range(3))))

    _install_fake_module(monkeypatch, find_transform=_fake_find)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    strategy = registration.create_registration("astroalign")
    with pytest.raises(registration.RegistrationSanityError):
        strategy.compute(np.zeros((16, 16), np.float32),
                         np.zeros((16, 16), np.float32))

    assert rec.names == ["registration.astroalign_sanity_rejected"]
    assert "SanityGuard" in rec.events[0][1]["reason"]


def test_astroalign_strategy_sanity_boundary_ok(
    monkeypatch: pytest.MonkeyPatch,
):
    """Grenzwerte (scale 1.019, rotation 1.9 Grad) sind erlaubt -> kein
    Sanity-Fehler (Dither-Fall)."""
    def _fake_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=0.5, y=-0.25,
                                         rotation_deg=1.9, scale=1.019),
                (list(range(6)), list(range(6))))

    _install_fake_module(monkeypatch, find_transform=_fake_find)
    strategy = registration.create_registration("astroalign")
    t = strategy.compute(np.zeros((16, 16), np.float32),
                         np.zeros((16, 16), np.float32))
    assert t.rotation_deg == pytest.approx(1.9, abs=1e-6)
    assert t.scale == pytest.approx(1.019, abs=1e-6)


def test_astroalign_strategy_rotation_above_default_accepted_when_raised(
    monkeypatch: pytest.MonkeyPatch,
):
    """SanityGuard-Override (Auftrag, M27/AZ): Rotation > 2 Grad wird mit
    max_rotation_deg=15 AKZEPTIERT statt FFT-Fallback (Kriterium:
    `--max-rotation 15` registriert M27 ohne Sanity-Rejection)."""
    def _fake_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=1.0, y=-0.5,
                                         rotation_deg=7.0, scale=1.0),
                (list(range(4)), list(range(4))))

    _install_fake_module(monkeypatch, find_transform=_fake_find)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    strategy = registration.create_registration(
        "astroalign", max_rotation_deg=15.0,
    )
    t = strategy.compute(np.zeros((16, 16), np.float32),
                         np.zeros((16, 16), np.float32))

    assert t.rotation_deg == pytest.approx(7.0, abs=1e-6)
    assert t.status == "ok"
    assert rec.names == []  # keine sanity_rejected-Warning


def test_astroalign_strategy_scale_override_accepted(
    monkeypatch: pytest.MonkeyPatch,
):
    """max_scale_dev-Override: scale-Abweichung > 0.02 wird mit
    max_scale_dev=0.2 akzeptiert (Config/Preset-Ebene)."""
    def _fake_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=0.0, y=0.0,
                                         rotation_deg=0.5, scale=1.1),
                (list(range(3)), list(range(3))))

    _install_fake_module(monkeypatch, find_transform=_fake_find)
    strategy = registration.create_registration(
        "astroalign", max_scale_dev=0.2,
    )
    t = strategy.compute(np.zeros((16, 16), np.float32),
                         np.zeros((16, 16), np.float32))
    assert t.scale == pytest.approx(1.1, abs=1e-6)
    assert t.status == "ok"


def test_astroalign_strategy_sanity_reason_contains_thresholds(
    monkeypatch: pytest.MonkeyPatch,
):
    """Log/Error-Meldung behaelt den SanityGuard-Hinweis UND enthaelt die
    aktuellen Schwellwerte im reason (Auftrag)."""
    def _fake_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=0.0, y=0.0,
                                         rotation_deg=12.0, scale=1.0),
                (list(range(3)), list(range(3))))

    _install_fake_module(monkeypatch, find_transform=_fake_find)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    strategy = registration.create_registration(
        "astroalign", max_rotation_deg=5.0, max_scale_dev=0.04,
    )
    with pytest.raises(registration.RegistrationSanityError) as excinfo:
        strategy.compute(np.zeros((16, 16), np.float32),
                         np.zeros((16, 16), np.float32))

    assert rec.names == ["registration.astroalign_sanity_rejected"]
    reason = rec.events[0][1]["reason"]
    assert "SanityGuard" in reason
    assert "max_rotation_deg=5.0" in reason
    assert "max_scale_dev=0.04" in reason
    assert "max_rotation_deg=5.0" in str(excinfo.value)


def test_create_registration_passes_thresholds_to_strategy(
    monkeypatch: pytest.MonkeyPatch,
):
    """Dispatcher reicht max_rotation_deg/max_scale_dev an die Strategie
    durch (ProcessingAgent -> create_registration -> AstroalignRegistration)."""
    _install_fake_module(monkeypatch)
    strategy = registration.create_registration(
        "astroalign", max_control_points=10,
        max_rotation_deg=15.0, max_scale_dev=0.03,
    )
    assert isinstance(strategy, registration.AstroalignRegistration)
    assert strategy._max_control_points == 10
    assert strategy._max_rotation_deg == 15.0
    assert strategy._max_scale_dev == 0.03


def test_astroalign_strategy_default_thresholds_preserved(
    monkeypatch: pytest.MonkeyPatch,
):
    """Default-Test (Auftrag): ohne Override bleiben die Schwellen 2.0 / 0.02
    — das heutige Verhalten (Rotation > 2 Grad -> Rejection)."""
    def _fake_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=0.0, y=0.0,
                                         rotation_deg=3.0, scale=1.0),
                (list(range(3)), list(range(3))))

    _install_fake_module(monkeypatch, find_transform=_fake_find)
    strategy = registration.create_registration("astroalign")
    assert strategy._max_rotation_deg == 2.0
    assert strategy._max_scale_dev == 0.02
    with pytest.raises(registration.RegistrationSanityError):
        strategy.compute(np.zeros((16, 16), np.float32),
                         np.zeros((16, 16), np.float32))


# ═══════════════════════════════════════════════════════════════════
# Section: Apply-Helper _apply_registration_transform (ADR-020-b/c)
# ═══════════════════════════════════════════════════════════════════


def test_apply_transform_none_returns_data():
    """transform=None -> unveraenderte Daten (kein astroalign-Transform)."""
    data = np.zeros((16, 16, 3), dtype=np.float32)
    assert registration._apply_registration_transform(
        data, None, np.zeros((16, 16), np.float32),
    ) is data


def test_apply_transform_2d_calls_once_and_passes_fill_value(
    monkeypatch: pytest.MonkeyPatch,
):
    """2D: apply_transform wird genau einmal gerufen, fill_value=0.0
    (Intra-Semantik cval=0.0) wird durchgereicht; footprint wird
    destructuret (Spike-Befund 3)."""
    calls: list[tuple] = []

    def _fake_apply(transform, source, target,
                    fill_value=None, propagate_mask=False):
        calls.append((transform, source, target, fill_value))
        return source * 2.0, np.ones_like(source, dtype=bool)

    _install_fake_module(monkeypatch, apply_transform=_fake_apply)
    t = _FakeSimilarityTransform(x=1.0, y=-1.0)
    ref = np.ones((16, 16), dtype=np.float32)
    data = np.ones((16, 16), dtype=np.float32)

    aligned = registration._apply_registration_transform(data, t, ref)

    assert len(calls) == 1
    assert calls[0][0] is t
    assert calls[0][1] is data
    assert calls[0][2] is ref
    assert calls[0][3] == 0.0
    assert np.allclose(aligned, 2.0)


def test_apply_transform_rgb_per_channel(monkeypatch: pytest.MonkeyPatch):
    """3D (H, W, 3): pro Kanal anwenden (find_transform lief auf Mono),
    Kanaele werden wieder gestapelt (ADR-020-Falle c)."""
    calls: list[int] = []

    def _fake_apply(transform, source, target,
                    fill_value=None, propagate_mask=False):
        calls.append(int(np.unique(source)[0]))
        return source + 1.0, np.ones_like(source, dtype=bool)

    _install_fake_module(monkeypatch, apply_transform=_fake_apply)
    t = _FakeSimilarityTransform()
    ref = np.ones((8, 8), dtype=np.float32)
    data = np.stack([
        np.full((8, 8), 1, np.float32),
        np.full((8, 8), 2, np.float32),
        np.full((8, 8), 3, np.float32),
    ], axis=-1)

    aligned = registration._apply_registration_transform(data, t, ref)

    assert calls == [1, 2, 3]
    assert aligned.shape == (8, 8, 3)
    assert np.allclose(aligned[..., 0], 2.0)
    assert np.allclose(aligned[..., 1], 3.0)
    assert np.allclose(aligned[..., 2], 4.0)


# ═══════════════════════════════════════════════════════════════════
# Agent-E2E: Compute-both-Arbitration (AC-W9-C3)
# ═══════════════════════════════════════════════════════════════════


def _block_image(size: int = 64) -> np.ndarray:
    """Kantiges Testbild: fft findet (0,0) + corr 1.0 auf identischem Paar."""
    img = np.zeros((size, size), dtype=np.float32)
    img[10:54, 10:54] = 1.0
    return img


def _write_2d_frame(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(data.astype(np.float32)).writeto(path, overwrite=True)
    return path


def _make_agent(tmp_path: Path) -> ProcessingAgent:
    return ProcessingAgent(working_dir=tmp_path, config=None)


def _register_frames(agent: ProcessingAgent, frames, params, is_3d=False):
    """Refactor 2026-08-14 (Cluster 3): ruft die core-Funktion
    `register_frames` mit den Agent-Bindungen (registered_dir/load_frame/
    save_frame) und schreibt den Registrierungs-Zustand in die
    `_last_*`-Attribute (wie ProcessingAgent.run/process_multi_group)."""
    res = register_frames(
        frames, params, is_3d=is_3d,
        registered_dir=agent.registered_dir,
        load_frame=agent._load_frame,
        save_frame=agent._save_frame,
    )
    agent._last_frame_qualities = res.last_frame_qualities
    agent._last_frame_rejected = res.last_frame_rejected
    agent._last_registration_metrics = res.last_registration_metrics
    return res.registered


def _two_identical_frames(tmp_path: Path) -> list[Path]:
    img = _block_image()
    return [
        _write_2d_frame(tmp_path / "frame0.fits", img),
        _write_2d_frame(tmp_path / "frame1.fits", img),
    ]


def test_agent_arbitration_astroalign_wins_with_fake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-C3: Fake-astroalign liefert (0,0)-Transform auf identischem Paar
    -> corr_hp_aa (=1.0) >= corr_hp_fft (1.0) - 0.05 -> astroalign gewinnt.
    Transform-Log (AC-W9-C2) mit method/rotation/scale/shift/ncp."""
    _install_fake_module(monkeypatch)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    frames = _two_identical_frames(tmp_path / "in")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    transform_events = rec.events_named("registration.transform")
    assert transform_events, rec.names
    event, fields = transform_events[0]
    assert event == "registration.transform"
    assert fields["method"] == "astroalign"
    assert fields["rotation_deg"] == 0.0
    assert fields["scale"] == 1.0
    assert fields["shift_y"] == 0.0
    assert fields["shift_x"] == 0.0
    assert fields["n_control_points"] == 5
    # kein Downgrade, kein Zero-Shift
    assert "registration.astroalign_downgraded" not in rec.names
    assert "registration.zero_shift_fallback" not in rec.names


def test_agent_arbitration_fft_wins_and_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-C3: astroalign-Transform ist schlechter (grosse Translation auf
    identischem Paar) -> corr_hp_aa < corr_hp_fft - 0.05 -> fft gewinnt +
    `registration.astroalign_downgraded`-Warning; Transform-Log method='fft'
    mit tatsaechlich angewendeten (0,0)-Shifts."""
    def _bad_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=12.0, y=-8.0),
                (list(range(5)), list(range(5))))

    def _real_apply(transform, source, target,
                    fill_value=None, propagate_mask=False):
        sy, sx = float(transform.translation[1]), float(transform.translation[0])
        aligned = scipy_shift(
            source, (sy, sx), order=3, mode="constant",
            cval=fill_value if fill_value is not None else 0.0,
        )
        return aligned, np.ones_like(source, dtype=bool)

    _install_fake_module(monkeypatch, find_transform=_bad_find,
                         apply_transform=_real_apply)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    frames = _two_identical_frames(tmp_path / "in")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    downgraded = rec.events_named("registration.astroalign_downgraded")
    assert downgraded, rec.names
    assert downgraded[0][1]["corr_hp_fft"] == pytest.approx(1.0, abs=1e-6)
    assert downgraded[0][1]["corr_hp_aa"] < 0.95

    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"
    assert transform_event[1]["shift_y"] == 0.0
    assert transform_event[1]["shift_x"] == 0.0


def test_agent_astroalign_error_falls_back_to_fft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-C3: astroalign wirft ValueError (<3 Sterne) -> fft gewinnt, kein
    Abbruch; die `registration.astroalign_fallback`-Warning kommt aus der
    Strategie (registration-Modul-Logger), der Agent loggt kein Downgrade."""
    def _boom(source, target, **kwargs):
        raise ValueError(
            "Reference stars in source image are less than the minimum value (3)."
        )

    _install_fake_module(monkeypatch, find_transform=_boom)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    frames = _two_identical_frames(tmp_path / "in")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    # Refactor 2026-08-14 (Cluster 3): Strategie- UND register_frames-Events
    # liegen jetzt auf demselben Modul-Logger (core.registration.logger).
    assert "registration.astroalign_fallback" in rec.names
    fallback = rec.events_named("registration.astroalign_fallback")[0]
    assert "ValueError" in fallback[1]["reason"]
    assert "registration.astroalign_downgraded" not in rec.names
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"


def test_agent_zero_shift_guard_rejects_astroalign_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-RE-F1 (RE-F/V1.3-24): Zero-Shift-Guard ist methodenbewusst —
    astroalign-Gewinner mit corr_hp_aa < 0.3 (uniform -> 0.0) wird VERWORFEN
    statt zeroshift-gestapelt: kein (0,0)-Transform, kein
    zero_shift_fallback-Event, unterscheidbares Rejection-Event, kein
    Transform-Log fuer den verworfenen Frame. (Ersetzt die alte
    AC-W9-C3-Zero-Shift-Klausel-Erwartung, ray-Review M1.)"""
    _install_fake_module(monkeypatch)  # (0,0)-Transform -> corr_hp_aa = 0.0
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    img = np.zeros((64, 64), dtype=np.float32)  # uniform -> corr 0.0
    frames = [
        _write_2d_frame(tmp_path / "f0.fits", img),
        _write_2d_frame(tmp_path / "f1.fits", img),
    ]
    agent = _make_agent(tmp_path / "out")
    # explizit hohe Schwelle (Default seit V19-FIX-12: 0.05)
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None,
                               "zero_shift_threshold": 0.3}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    # Referenz bleibt registriert; der astroalign-Gewinner wird verworfen.
    assert len(registered) == 1
    assert "registration.frame_rejected" in rec.names
    assert "registration.zero_shift_fallback" not in rec.names
    rejected = rec.events_named("registration.frame_rejected")
    assert rejected[0][1]["corr_hp"] == pytest.approx(0.0, abs=1e-6)
    # kein fft/(0,0)-Apply -> kein Transform-Log fuer den verworfenen Frame
    assert rec.events_named("registration.transform") == []


def test_agent_zero_shift_fft_branch_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-RE-F2 (RE-F/V1.3-24): der fft-Zweig behaelt das v1.2-Verhalten —
    corr_hp < 0.3 -> Shift (0,0) + registration.zero_shift_fallback
    (AC-W11-2 unveraendert; die Zero-Shift-Klausel bleibt fuer den fft-Zweig
    gueltig)."""
    monkeypatch.setitem(sys.modules, "astroalign", None)  # method=fft: nie beruehren
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    img = np.zeros((64, 64), dtype=np.float32)  # uniform -> corr 0.0
    frames = [
        _write_2d_frame(tmp_path / "f0.fits", img),
        _write_2d_frame(tmp_path / "f1.fits", img),
    ]
    agent = _make_agent(tmp_path / "out")
    # explizit hohe Schwelle (Default seit V19-FIX-12: 0.05)
    params = {"registration": {"method": "fft", "max_control_points": None,
                               "zero_shift_threshold": 0.3}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    assert "registration.zero_shift_fallback" in rec.names
    assert "registration.frame_rejected" not in rec.names
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"
    assert transform_event[1]["shift_y"] == 0.0
    assert transform_event[1]["shift_x"] == 0.0
    # V1.3-3 (stella-Befund 4): der ausgeloeste Zero-Shift-Fallback wird
    # in den Registrierungs-Metriken gezaehlt (1 Nicht-Referenz-Frame).
    assert agent._last_registration_metrics["zero_shift_count"] == 1
    with fits.open(registered[1]) as hdul:
        data = hdul[0].data.astype(np.float32)
    assert np.array_equal(data, img)


def test_agent_zero_shift_threshold_zero_keeps_astroalign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-RE-F3 (RE-F/V1.3-24): --zero-shift-threshold 0.0 deaktiviert den
    Guard-Schwellen-Treffer (0.0 < 0.0 false) -> der astroalign-Transform
    wird angewendet (kein Reject, kein zero_shift_fallback)."""
    _install_fake_module(monkeypatch)  # (0,0)-Transform -> corr_hp_aa = 0.0
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    img = np.zeros((64, 64), dtype=np.float32)  # uniform -> corr 0.0
    frames = [
        _write_2d_frame(tmp_path / "f0.fits", img),
        _write_2d_frame(tmp_path / "f1.fits", img),
    ]
    agent = _make_agent(tmp_path / "out")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None,
                               "zero_shift_threshold": 0.0}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    assert "registration.frame_rejected" not in rec.names
    assert "registration.zero_shift_fallback" not in rec.names
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "astroalign"
    assert transform_event[1]["shift_y"] == 0.0
    assert transform_event[1]["shift_x"] == 0.0
    # V1.3-3 (stella-Befund 4): astroalign-Sieg-Metriken — method_counts
    # zaehlt den Sieg, n_control_points-Median ist gesetzt (Fake-Modul:
    # 5 Kontrollpunkte) statt None (fft-Signatur).
    metrics = agent._last_registration_metrics
    assert metrics["method_counts"]["astroalign"] >= 1
    assert metrics["n_control_points"]["median"] is not None


def test_agent_no_zero_shift_fallback_disables_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-RE-F3 (RE-F/V1.3-24): --no-zero-shift-fallback deaktiviert den
    W1-Guard komplett — weder Zero-Shift noch astroalign-Reject; der
    astroalign-Transform (0,0) wird angewendet (R2-Interpretation im Code)."""
    _install_fake_module(monkeypatch)  # (0,0)-Transform -> corr_hp_aa = 0.0
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    img = np.zeros((64, 64), dtype=np.float32)  # uniform -> corr 0.0
    frames = [
        _write_2d_frame(tmp_path / "f0.fits", img),
        _write_2d_frame(tmp_path / "f1.fits", img),
    ]
    agent = _make_agent(tmp_path / "out")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None,
                               "zero_shift_fallback": False}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    assert "registration.frame_rejected" not in rec.names
    assert "registration.zero_shift_fallback" not in rec.names
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "astroalign"


def test_agent_fft_method_never_touches_astroalign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-C5: bei method='fft' (Default) wird astroalign NIE beruehrt —
    selbst wenn das Paket fehlt (Import blockiert): keine astroalign-Events,
    keine astroalign-Warnings; fft-Ergebnis unveraendert (corr 1.0)."""
    monkeypatch.setitem(sys.modules, "astroalign", None)
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    frames = _two_identical_frames(tmp_path / "in")
    params = {"registration": {"method": "fft", "max_control_points": None}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    assert not any("astroalign" in name for name in rec.names)
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"
    assert transform_event[1]["rotation_deg"] == 0.0
    assert transform_event[1]["scale"] == 1.0
    assert transform_event[1]["n_control_points"] is None


def test_register_frames_populates_registration_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """V1.3-3 (stella-Befund 4): `register_frames` befuellt
    `_last_registration_metrics` (method_counts, frames, corr_hp-Verteilung,
    n_control_points, zero_shift/rejected-Zaehler). FFT-Zweig: identische
    Frames -> 1 fft-Sieg, corr_hp median float, rejected == 0."""
    monkeypatch.setitem(sys.modules, "astroalign", None)  # method=fft: nie beruehren
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    frames = _two_identical_frames(tmp_path / "in")
    params = {"registration": {"method": "fft", "max_control_points": None}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    metrics = agent._last_registration_metrics
    assert metrics["method_counts"]["fft"] >= 1
    assert metrics["method_counts"]["astroalign"] == 0
    assert metrics["frames_total"] == 2
    assert metrics["frames_registered"] == 2
    assert metrics["rejected_count"] == 0
    assert metrics["zero_shift_count"] == 0
    assert metrics["corr_hp"]["count"] >= 1
    assert isinstance(metrics["corr_hp"]["median"], float)
    assert isinstance(metrics["corr_hp"]["min"], float)
    assert isinstance(metrics["corr_hp"]["max"], float)
    assert metrics["n_control_points"]["count"] == 0
    assert metrics["n_control_points"]["median"] is None
    # registration.complete loggt die Metriken additiv
    completes = rec.events_named("registration.complete")
    assert completes and completes[0][1]["registration_metrics"] == metrics


# ═══════════════════════════════════════════════════════════════════
# Section: Real-Synthetik - AC-W9-C1/C3/C7 via importorskip
# ═══════════════════════════════════════════════════════════════════


def _spike_starfield(shape: tuple[int, int] = (256, 256),
                     n_stars: int = 60, seed: int = 42) -> np.ndarray:
    """Kontrollierte Sternfeld-Szene nach Spike-Vorbild (S1-A2): helle Sterne
    (Flux 300-1500) auf niedrigem Sky (50) — sep/astroalign-tauglich."""
    rng = np.random.default_rng(seed)
    ref = np.full(shape, 50.0, dtype=np.float64)
    xs = rng.uniform(20, shape[1] - 20, n_stars)
    ys = rng.uniform(20, shape[0] - 20, n_stars)
    fluxes = rng.uniform(300, 1500, n_stars)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    for x, y, f in zip(xs, ys, fluxes, strict=True):
        ref += f * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5**2))
    ref += rng.normal(0, 1.0, ref.shape)
    return ref.astype(np.float32)


def _shifted_rotated(ref: np.ndarray,
                     shift_yx: tuple[float, float] = (2.3, -1.7),
                     rot_deg: float = 0.3) -> np.ndarray:
    """Target: Rotation um Ursprung + Translation (Spike-Konvention)."""
    tgt = rotate(ref, -rot_deg, reshape=False, order=3,
                 mode="constant", cval=50.0)
    tgt = scipy_shift(tgt, (shift_yx[0], shift_yx[1]), order=3,
                      mode="constant", cval=50.0)
    return tgt.astype(np.float32)


def test_agent_arbitration_real_astroalign_wins_spike_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-C3 Real (nur mit Extra): QF-C-Paar (Shift (2.3,-1.7) px + Rotation
    0.3 Grad, Spike-Demo) — die Compute-both-Arbitration waehlt astroalign:
    fft (translation-only, Integer-Grid) verfehlt Subpixel+Rotation
    (Spike: corr_hp 0.4784), astroalign loest sie (Spike: 0.9993). Assertions
    toleranzbasiert (ADR-021 Nichtdeterminismus)."""
    pytest.importorskip("astroalign")
    ref = _spike_starfield()
    tgt = _shifted_rotated(ref)
    frames = [
        _write_2d_frame(tmp_path / "in" / "ref.fits", ref),
        _write_2d_frame(tmp_path / "in" / "tgt.fits", tgt),
    ]

    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)
    agent = _make_agent(tmp_path / "out")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": 50}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 2
    transform_events = rec.events_named("registration.transform")
    assert transform_events, rec.names
    event, fields = transform_events[0]
    assert event == "registration.transform"
    assert fields["method"] == "astroalign", rec.names
    # Injektion: tgt hat Move rows=+2.3, cols=-1.7 von ref -> Transform auf
    # tgt (gegen ref) muss ~(-2.3, +1.7) sein. Die Rotation um den Ursprung
    # koppelt die effektive Translation an die Sterngeometrie (RANSAC-
    # Kompromiss auf kleinen Szenen, S1-A7-Befund) -> toleranzbasiert:
    # Vorzeichen beweisen die Pipeline-Konvention (rows/cols, keine
    # 90-Grad-Vertauschung), die Magnitude die Subpixel-Aufloesung.
    assert fields["shift_y"] < 0.0, fields
    assert fields["shift_x"] > 0.0, fields
    assert fields["shift_y"] == pytest.approx(-2.3, abs=1.0)
    assert fields["shift_x"] == pytest.approx(1.7, abs=1.0)
    assert fields["rotation_deg"] == pytest.approx(-0.3, abs=0.2)
    assert fields["scale"] == pytest.approx(1.0, abs=0.002)
    assert isinstance(fields["n_control_points"], int)
    assert "registration.astroalign_downgraded" not in rec.names


def test_agent_m13_analog_runs_without_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-C7/C3: M13-Analog-Gruppe (Dichte-Referenz 81-119 Quellen) läuft
    mit method='astroalign' ohne Abbruch durch — unabhängig davon, ob
    astroalign die Arbitration gewinnt oder in die Fallback-Kette geht
    (S1-A7-Befund: auf der M13-Analog-Hochpass-Szene scheitert astroalign
    aktuell mit MaxIterError -> fft + Warning, kein Abbruch)."""
    pytest.importorskip("astroalign")
    import synthetic

    scene = synthetic.generate_m13_analog(tmp_path / "m13", seed=42)
    group = scene.dataset.group_map["60s40"]
    assert len(group) == 4

    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)
    agent = _make_agent(tmp_path / "out")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": 50}}
    registered = _register_frames(
        agent, [Path(f) for f in group], params, is_3d=False,
    )

    assert len(registered) == len(group)
    transform_events = rec.events_named("registration.transform")
    assert len(transform_events) == len(group) - 1
    # kein Abbruch: jede Zeile traegt ein Transform-Log (fft oder astroalign)
    assert all(e[1]["method"] in ("fft", "astroalign") for e in transform_events)


def test_agent_az_field_rotation_reject_at_0_5_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-RE-F1 Real (nur mit Extra): AZ-Feldrotations-Analog (UGC-10822,
    Duo-Band, Rotation 1.9 Grad, Subpixel-Shifts) — bei Default-Schwelle 0.05
    (V19-FIX-12) gewinnt astroalign die Arbitration normal (corr_hp_aa
    ~0.43-0.48, weiterhin > 0.05);
    bei `zero_shift_threshold=0.5` liegt corr_hp unter der Schwelle und JEDER
    Nicht-Referenz-Frame wird verworfen (`registration.frame_rejected`,
    len(registered) == 1 = nur Referenz). Das belegt den RE-F-Beleg:
    astroalign kann einen gueltigen Transform liefern, dessen G-Kanal-Hochpass-
    Korrelation trotzdem unter der Zero-Shift-Schwelle bleibt."""
    pytest.importorskip("astroalign")
    import synthetic

    scene = synthetic.generate_az_field_rotation_analog(
        tmp_path / "az", seed=42,
    )
    group = next(iter(scene.dataset.group_map.values()))
    assert len(group) == 4

    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)
    agent = _make_agent(tmp_path / "out")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": 50,
                               "zero_shift_threshold": 0.5}}
    registered = _register_frames(
        agent, [Path(f) for f in group], params, is_3d=False,
    )

    # Nur die Referenz bleibt registriert (kein aligned.fits fuer die
    # Nicht-Referenz-Frames — AC-RE-F1: verwerfen, nicht zeroshift-stapeln).
    assert len(registered) == 1, len(registered)
    assert registered[0].name == "reg_0000.fits"

    # Jeder der 3 Nicht-Referenz-Frames: frame_rejected mit corr_hp + Schwelle.
    rejects = rec.events_named("registration.frame_rejected")
    assert len(rejects) == 3, rec.names
    for _, fields in rejects:
        assert fields["corr_hp"] < 0.5
        assert fields["threshold"] == 0.5
        assert "astroalign winner below zero-shift threshold" in fields["reason"]

    # Kein (0,0)-Transform, kein Zero-Shift-Fallback, kein Transform-Log:
    # der astroalign-Gewinner wird verworfen statt fälschlich als fft geloggt.
    assert "registration.zero_shift_fallback" not in rec.names
    assert rec.events_named("registration.transform") == []


def test_agent_az_field_rotation_default_threshold_astroalign_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-RE-F1 Kontrolllauf: dieselbe AZ-Feldrotations-Szene mit Default-
    Schwelle 0.0 — astroalign gewinnt die Arbitration normal (corr_hp_aa
    ~0.43-0.48 >= 0.0), alle Frames registriert, KEINE Rejects. Beweist,
    dass der 0.5-Reject im Schwestertest am kalibrierten Schwellenwert liegt
    und nicht an einem defekten Transform."""
    pytest.importorskip("astroalign")
    import synthetic

    scene = synthetic.generate_az_field_rotation_analog(
        tmp_path / "az", seed=42,
    )
    group = next(iter(scene.dataset.group_map.values()))

    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)
    agent = _make_agent(tmp_path / "out")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": 50}}
    registered = _register_frames(
        agent, [Path(f) for f in group], params, is_3d=False,
    )

    assert len(registered) == len(group) == 4
    assert "registration.frame_rejected" not in rec.names
    assert "registration.zero_shift_fallback" not in rec.names
    transforms = rec.events_named("registration.transform")
    assert len(transforms) == 3
    assert all(e[1]["method"] == "astroalign" for e in transforms)
    # Rotation wird aufgeloest (Feldrotation ~1.9 Grad, SanityGuard ok).
    assert all(e[1]["rotation_deg"] != 0.0 for e in transforms)


# ═══════════════════════════════════════════════════════════════════
# P2-1 (ray-Review): R3-Randfall — alle Nicht-Referenz-Frames rejected
# ═══════════════════════════════════════════════════════════════════


def test_stack_frames_single_frame_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """P2-1: `stack_frames` mit nur dem Referenz-Frame (alle Nicht-Referenz-
    Frames per `registration.frame_rejected` verworfen) -> sauberer Skip:
    None + Warning `processing.stack_skipped` (reason="insufficient_frames")
    statt ValueError ("Need at least 2 frames to stack")."""
    rec = _LogRecorder()
    monkeypatch.setattr(stacking, "logger", rec)
    agent = _make_agent(tmp_path / "out")
    ref = _write_2d_frame(tmp_path / "ref.fits", _block_image())

    stacked = stack_frames(
        [ref], params={}, is_3d=False,
        stacked_dir=agent.stacked_dir,
        load_frame=agent._load_frame,
        save_frame=agent._save_frame,
    )

    assert stacked is None
    skips = rec.events_named("processing.stack_skipped")
    assert len(skips) == 1, rec.names
    assert skips[0][1]["reason"] == "insufficient_frames"
    assert skips[0][1]["frames"] == 1


def test_stack_frames_two_frames_stacks(tmp_path: Path):
    """P2-1 Kontrolllauf: >= 2 Frames -> Stack wird erzeugt (Default-Pfad
    unveraendert, kein `processing.stack_skipped`)."""
    agent = _make_agent(tmp_path / "out")
    img = np.full((64, 64), 10.0, dtype=np.float32)  # Median != 0 -> Norm ok
    img[10:54, 10:54] = 1.0
    f0 = _write_2d_frame(tmp_path / "f0.fits", img)
    f1 = _write_2d_frame(tmp_path / "f1.fits", img)

    stacked = stack_frames(
        [f0, f1], params={}, is_3d=False,
        stacked_dir=agent.stacked_dir,
        load_frame=agent._load_frame,
        save_frame=agent._save_frame,
    )

    assert stacked is not None
    assert stacked.exists()
    assert stacked.name == "stacked.fits"


def test_register_frames_counts_rejected_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """P2-1: `_last_frame_rejected` zaehlt die `registration.frame_rejected`-
    Ereignisse des aktuellen Passes (2 Nicht-Referenz-Frames unter der
    Zero-Shift-Schwelle -> Zaehler == 2); die Referenz bleibt registriert."""
    _install_fake_module(monkeypatch)  # (0,0)-Transform -> corr_hp_aa = 0.0
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)

    img = np.zeros((64, 64), dtype=np.float32)  # uniform -> corr 0.0
    frames = [
        _write_2d_frame(tmp_path / "f0.fits", img),
        _write_2d_frame(tmp_path / "f1.fits", img),
        _write_2d_frame(tmp_path / "f2.fits", img),
    ]
    agent = _make_agent(tmp_path / "out")
    # explizit hohe Schwelle (Default seit V19-FIX-12: 0.05)
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None,
                               "zero_shift_threshold": 0.3}}
    registered = _register_frames(agent, frames, params, is_3d=False)

    assert len(registered) == 1  # nur Referenz
    assert agent._last_frame_rejected == 2
    assert len(rec.events_named("registration.frame_rejected")) == 2
    # V1.3-3: Reject-Zaehler steckt auch in den Registrierungs-Metriken
    # (NICHT doppelt — uebernimmt den bestehenden _last_frame_rejected).
    metrics = agent._last_registration_metrics
    assert metrics["rejected_count"] == 2
    assert metrics["frames_registered"] == 1
    assert metrics["frames_total"] == 3
    # rejected Frames werden nicht registriert -> keine corr_hp-Werte
    assert metrics["corr_hp"]["count"] == 0


def test_multi_group_all_frames_rejected_skips_with_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """P2-1 (ray-Review, R3-Randfall): intra-group — eine Gruppe mit ALLEN
    verworfenen Nicht-Referenz-Frames (nur Referenz registriert, z.B.
    --zero-shift-threshold 0.5 auf der AZ-Szene) wird sauber geskippt:
    `multi_group.skip_group`-Warning + `skipped_groups`-Report-Eintrag mit
    frame_rejected-Zaehlung, KEIN ValueError ("Need at least 2 frames to
    stack"), `stack_frames` wird fuer die geskippte Gruppe NICHT aufgerufen.
    Die ueberlebende Gruppe (60s40) laeuft normal weiter."""
    agent = _make_agent(tmp_path / "out")
    context = make_sample_context(tmp_path, group_count=2, frames_per_group=3)
    pipeline = MagicMock()
    pipeline.processing_params = ProcessingParams()
    pipeline.steps = []

    lights = context.get_lights()
    cal_result = MagicMock()
    cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
    deb_result = MagicMock()
    deb_result.debayered_frames = []

    stack_fits = {
        "15s60": create_test_fits(tmp_path / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
        "60s40": create_test_fits(tmp_path / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
    }

    def fake_register(frames, params, is_3d=False, **kwargs):
        # Refactor 2026-08-14 (Cluster 3): process_multi_group erwartet ein
        # RegisterFramesResult (der Agent uebernimmt die _last_*-Attribute
        # aus dem Rueckgabe-Zustand).
        if "group_0" in str(frames[0]):
            # Gruppe 15s60 (group_0): ALLE Nicht-Referenz-Frames verworfen
            return RegisterFramesResult(
                registered=[tmp_path / "out" / "group_15s60" / "03_registered" / "reg_0000.fits"],
                last_frame_qualities=[],
                last_frame_rejected=2,
                last_registration_metrics={},
            )
        # Gruppe 60s40 (group_1): normal
        return RegisterFramesResult(
            registered=[Path(f) for f in frames],
            last_frame_qualities=[],
            last_frame_rejected=0,
            last_registration_metrics={},
        )

    pcc_counter = {"n": 0}

    def fake_pcc(stack_path, *args, **kwargs):
        pcc_counter["n"] += 1
        p = tmp_path / f"pcc_stack_{pcc_counter['n']}.fits"
        create_test_fits(p, exptime=60.0, gain=40, rng_seed=pcc_counter["n"])
        return (p, "gaia_success")

    rec = _LogRecorder()
    # multi_group.skip_group wird vom Agent (processing_agent.logger) geloggt
    monkeypatch.setattr(processing_agent, "logger", rec)

    with patch("astro_process.agents.multi_group_agent.register_frames", side_effect=fake_register), \
         patch("astro_process.agents.multi_group_agent.stack_frames", return_value=stack_fits["60s40"]) as mock_stack, \
         patch.object(agent, "_register_to_reference_stack") as mock_cross, \
         patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
        proc_result = agent.process_multi_group(
            context, cal_result, deb_result, pipeline,
            multi_group_config=MultiGroupConfig(),
            merge_agent=None,
        )

    assert proc_result is not None  # kein Crash
    # Geskippte Gruppe wurde nicht gestackt (stack_frames nur fuer 60s40)
    assert mock_stack.call_count == 1, mock_stack.call_count
    # Cross-Group-Registration: nur die Referenz ueberlebt -> nichts zu registrieren
    mock_cross.assert_not_called()
    # skip_group-Warning mit frame_rejected-Zaehlung
    skip_events = rec.events_named("multi_group.skip_group")
    assert skip_events, rec.names
    assert skip_events[0][1]["reason"] == "all_frames_rejected_below_zero_shift_threshold"
    assert skip_events[0][1]["frame_rejected"] == 2
    # Report-Eintrag additiv in skipped_groups
    skipped = proc_result.multi_group_metadata["skipped_groups"]
    assert any(
        e["reason"] == "all_frames_rejected_below_zero_shift_threshold"
        and e["frame_rejected"] == 2
        for e in skipped
    ), skipped


# ═══════════════════════════════════════════════════════════════════
# Section: rotation_fft-Strategie (V1.4-2, Log-Polar-FFT-Rotation)
# ═══════════════════════════════════════════════════════════════════


def _small_grid_shift(ref_hp, tgt_hp, radius=6):
    """Kleine Grid-Shift-Suche fuer rotation_fft-Unit-Tests (Translation nach
    Derotation). Die echte Pipeline bindet corr_grid_shift (Modul-Funktion
    in core.registration); hier reicht ein Integer-Grid um (0,0)."""
    best = (-1e9, 0, 0)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            a = scipy_shift(tgt_hp, (dy, dx), order=1, mode="nearest")
            c = float(np.corrcoef(a.ravel(), ref_hp.ravel())[0, 1])
            if c > best[0]:
                best = (c, dy, dx)
    return best


def test_module_has_rotation_fft_api():
    """V1.4-2-Bausteine sind vorhanden: RotationFftRegistration,
    apply_rotation_shift, _log_polar, _phase_corr; Dispatcher "rotation_fft"
    -> RotationFftRegistration (grid_shift_fn gebunden)."""
    assert hasattr(registration, "RotationFftRegistration")
    assert callable(registration.apply_rotation_shift)
    assert callable(registration._log_polar)
    assert callable(registration._phase_corr)
    strategy = registration.create_registration(
        "rotation_fft", grid_shift_fn=lambda a, b: (1.0, 0, 0),
        max_rotation_deg=15.0,
    )
    assert isinstance(strategy, registration.RotationFftRegistration)
    assert strategy.available() is True


def test_rotation_fft_strategy_pure_rotation_10deg():
    """V1.4-2: Reine Rotation 10 Grad (Spike-Sternfeld) -> rotation_deg exakt
    (Log-Polar-Phasenkorrelation; Task-Toleranz +-2 Grad), scale ~1.0
    (SanityGuard ok), Translation ~(0,0), status ok."""
    ref = _spike_starfield()
    tgt = rotate(ref, 10.0, reshape=False, order=3, mode="nearest")
    strategy = registration.create_registration(
        "rotation_fft", grid_shift_fn=_small_grid_shift, max_rotation_deg=15.0,
    )
    t = strategy.compute(ref, tgt)
    assert t.method == "rotation_fft"
    assert t.rotation_deg == pytest.approx(10.0, abs=2.0)
    assert abs(t.scale - 1.0) <= 0.02
    assert t.shift_y == pytest.approx(0.0, abs=1.0)
    assert t.shift_x == pytest.approx(0.0, abs=1.0)
    assert t.status == "ok"
    assert t.n_control_points is None
    assert t.transform is None


def test_rotation_fft_strategy_refinement_3deg():
    """V1.4-2: Reine Rotation 3 Grad -> das Pearson-Refinement korrigiert den
    coarse-Rasterfehler auf < 1 Grad (Task-Anforderung; Scratch: exakt 3.0)."""
    ref = _spike_starfield()
    tgt = rotate(ref, 3.0, reshape=False, order=3, mode="nearest")
    strategy = registration.create_registration(
        "rotation_fft", grid_shift_fn=_small_grid_shift, max_rotation_deg=15.0,
    )
    t = strategy.compute(ref, tgt)
    assert abs(t.rotation_deg - 3.0) < 1.0


def test_rotation_fft_strategy_rotation_and_translation():
    """V1.4-2: Rotation + Translation (Shift (2.3,-1.7)) -> rotation_deg
    innerhalb der Task-Toleranz (+-2 Grad um 10; Scratch: 9.0), Translation
    auf dem derotierten Bild gefunden (Vorzeichen = Shift, der tgt zurueck
    auf ref bringt)."""
    ref = _spike_starfield()
    tgt = scipy_shift(
        rotate(ref, 10.0, reshape=False, order=3, mode="nearest"),
        (2.3, -1.7), order=3, mode="nearest",
    )
    strategy = registration.create_registration(
        "rotation_fft", grid_shift_fn=_small_grid_shift, max_rotation_deg=15.0,
    )
    t = strategy.compute(ref, tgt)
    assert t.rotation_deg == pytest.approx(10.0, abs=2.0)
    assert t.shift_y == pytest.approx(-2.0, abs=1.0)
    assert t.shift_x == pytest.approx(2.0, abs=1.0)


def test_rotation_fft_sanity_guard_rejects_rotation(
    monkeypatch: pytest.MonkeyPatch,
):
    """V1.4-2: Sanity-Guard analog AstroalignRegistration — rotation_fft-
    Transform mit |rotation| > max_rotation_deg wird verworfen
    (RegistrationSanityError + `registration.rotation_fft_sanity_rejected`-
    Warning aus der Strategie)."""
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)
    ref = _spike_starfield()
    tgt = rotate(ref, 10.0, reshape=False, order=3, mode="nearest")
    strategy = registration.create_registration(
        "rotation_fft", grid_shift_fn=_small_grid_shift, max_rotation_deg=2.0,
    )
    with pytest.raises(registration.RegistrationSanityError):
        strategy.compute(ref, tgt)
    assert rec.names == ["registration.rotation_fft_sanity_rejected"]
    assert "SanityGuard" in rec.events[0][1]["reason"]


def test_rotation_fft_needs_grid_shift_fn():
    """V1.4-2: Ohne gebundene grid_shift_fn (kein Agent) -> ValueError mit
    klarer Meldung (die Translationssuche ist Teil der Strategie)."""
    ref = _spike_starfield(shape=(64, 64))
    strategy = registration.create_registration("rotation_fft")
    with pytest.raises(ValueError, match="grid_shift_fn"):
        strategy.compute(ref, ref)


def test_apply_rotation_shift_rgb_per_channel():
    """V1.4-2/ADR-020-Falle c: apply_rotation_shift wendet Rotation+Shift bei
    RGB pro Kanal an (die Strategie rechnete auf Mono) — jeder Kanal ist
    identisch zur 2D-Anwendung."""
    ref = _spike_starfield(shape=(64, 64))
    channels = [ref, ref * 0.5 + 5.0, ref * 0.25 - 3.0]
    # RGB-Target wird konsistent zur Implementierung pro Kanal erzeugt
    tgt_rgb = np.stack([
        scipy_shift(rotate(ch, 8.0, reshape=False, order=3, mode="nearest"),
                    (2.0, -1.0), order=3, mode="nearest")
        for ch in channels
    ], axis=-1)
    out = registration.apply_rotation_shift(tgt_rgb, 8.0, -2.0, 1.0)
    assert out.shape == tgt_rgb.shape
    assert out.ndim == 3
    assert out.shape[-1] == 3
    for c in range(3):
        expected = scipy_shift(
            rotate(tgt_rgb[..., c], -8.0, reshape=False, order=3,
                   mode="nearest"),
            (-2.0, 1.0), order=3, mode="nearest",
        )
        np.testing.assert_allclose(out[..., c], expected, atol=1e-5)


# ═══════════════════════════════════════════════════════════════════
# Section: V1.3-1 situationsabhaengige Registrations-Empfehlung
# (ehemals test_v13_1_recommendation.py — integriert nach A1)
# ═══════════════════════════════════════════════════════════════════


def _run_recommendation(filter_name, eq, eq_source="test", astroalign_available=True):
    return build_recommendation(
        filter_name=filter_name,
        eq=eq,
        eq_source=eq_source,
        astroalign_available=astroalign_available,
    )


class TestV13Recommendation:
    """V1.3-1 Registrations-Empfehlung — RE-A Situationstabelle + RE-B/RE-G."""

    # RE-A — Situationstabelle (6 Zeilen)
    def test_re_a_1_duo_az_astroalign_with_rotation(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=False)
        assert rec is not None
        assert rec["method"] == "astroalign"
        assert "--max-rotation 30" in rec["suggested_cli"]
        assert "Feldrotation" in rec["reason"]

    def test_re_a_2_duo_eq_astroalign_default_rotation(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=True)
        assert rec is not None
        assert rec["method"] == "astroalign"
        assert "max-rotation" not in rec["suggested_cli"]
        assert "keine Feldrotation" in rec["reason"]

    def test_re_a_3_duo_unknown_astroalign_with_rotation(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=None)
        assert rec is not None
        assert rec["method"] == "astroalign"
        assert "--max-rotation 30" in rec["suggested_cli"]
        assert "unbekannt" in rec["reason"]

    def test_re_a_4_broadband_eq_no_recommendation(self):
        assert _run_recommendation("OIII 6.5nm", eq=True) is None
        assert _run_recommendation("Baader UV/IR", eq=True) is None

    def test_re_a_5_broadband_az_astroalign_with_rotation(self):
        rec = _run_recommendation("OIII 6.5nm", eq=False)
        assert rec is not None
        assert rec["method"] == "astroalign"
        assert "--max-rotation 30" in rec["suggested_cli"]
        assert "FFT-Korrelation" in rec["reason"]

    def test_re_a_6_broadband_unknown_no_recommendation(self):
        assert _run_recommendation("OIII 6.5nm", eq=None) is None
        assert _run_recommendation(None, eq=None) is None

    def test_re_a_dual_substring_matches_dual_band(self):
        rec = _run_recommendation("dual-band filter", eq=False)
        assert rec is not None
        assert rec["method"] == "astroalign"

    def test_re_a_eq_source_passthrough(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=True, eq_source="shotsinfo")
        assert rec is not None
        assert rec["eq_source"] == "shotsinfo"
        rec_az = _run_recommendation("OIII 6.5nm", eq=False, eq_source="az_fallback")
        assert rec_az is not None
        assert rec_az["eq_source"] == "az_fallback"

    # RE-B — 30.0 Grad, nie der SanityGuard-Default (2.0)
    def test_re_b_rotation_suggestion_is_30_not_default(self):
        assert MAX_ROTATION_SUGGESTION_DEG == 30.0
        assert MAX_ROTATION_SUGGESTION_DEG != 2.0
        for filter_name, eq in [("DUO-BAND 7nm", False), ("DUO-BAND 7nm", None), ("OIII 6.5nm", False)]:
            rec = _run_recommendation(filter_name, eq=eq)
            assert rec is not None
            assert rec["max_rotation_suggestion"] == 30.0
            assert "--max-rotation 30" in rec["suggested_cli"]

    def test_re_b_no_rotation_suggestion_for_duo_eq(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=True)
        assert rec is not None
        assert "max-rotation" not in rec["suggested_cli"]
        assert "max_rotation_suggestion" not in rec

    # RE-G — Empfehlung unabhaengig vom Installationsstand
    def test_re_g_recommendation_also_without_astroalign(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=False, astroalign_available=False)
        assert rec is not None
        assert rec["method"] == "astroalign"
        assert "--registration-method astroalign" in rec["suggested_cli"]

    def test_re_g_install_hint_in_suggested_cli(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=False, astroalign_available=False)
        assert 'pip install "astra[astroalign]"' in rec["suggested_cli"]

    def test_re_g_install_hint_in_reason(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=False, astroalign_available=False)
        assert 'pip install "astra[astroalign]"' in rec["reason"]

    def test_re_g_no_hint_when_astroalign_installed(self):
        rec = _run_recommendation("DUO-BAND 7nm", eq=False, astroalign_available=True)
        assert 'pip install' not in rec["suggested_cli"]
        assert 'Installations-Hinweis' not in rec["reason"]

    def test_re_g_hint_only_for_recommendation_cases(self):
        assert _run_recommendation("OIII 6.5nm", eq=True, astroalign_available=False) is None
        assert _run_recommendation("OIII 6.5nm", eq=None, astroalign_available=False) is None

# ═══════════════════════════════════════════════════════════════════
# Section: W9-A — astroalign Dependency + Fallback
# (integriert aus test_registration_w9.py)
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def log_recorder(monkeypatch: pytest.MonkeyPatch) -> _LogRecorder:
    rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", rec)
    return rec


# ═══════════════════════════════════════════════════════════════════
# Section: Lazy-Import AC-W9-A2
# ═══════════════════════════════════════════════════════════════════


def test_module_has_public_api():
    """S1-A7-Bausteine sind vorhanden: get_astroalign, astroalign_register,
    AstroalignResult, AstroalignUnavailableError."""
    assert callable(registration.get_astroalign)
    assert callable(registration.astroalign_register)
    assert registration.AstroalignResult._fields == ("transform", "n_control_points")
    assert issubclass(registration.AstroalignUnavailableError, RuntimeError)


def test_get_astroalign_imports_real_module():
    """Lazy-Import: erster Aufruf laedt das echte astroalign-Modul (nur wenn
    das Extra installiert ist; sonst skip)."""
    pytest.importorskip("astroalign")
    aa = registration.get_astroalign()
    assert hasattr(aa, "find_transform")
    # Cache: zweiter Aufruf liefert dieselbe Referenz (kein Reimport)
    assert registration.get_astroalign() is aa


def test_unavailable_warns_once_then_caches(
    monkeypatch: pytest.MonkeyPatch, log_recorder: _LogRecorder,
):
    """AC-W9-A2: fehlendes astroalign -> genau EINE Warning
    `registration.astroalign_unavailable` pro Prozess (wird gecacht), danach
    dauerhaft AstroalignUnavailableError ohne weitere Warnings."""
    # Import blockieren: None in sys.modules -> der Import von astroalign
    # wirft dann einen ImportError (import halted).
    monkeypatch.setitem(sys.modules, "astroalign", None)

    with pytest.raises(registration.AstroalignUnavailableError):
        registration.get_astroalign()
    assert log_recorder.names == ["registration.astroalign_unavailable"]
    assert "pip install" in log_recorder.events[0][1]["detail"]

    # Zweiter Aufruf: gecachtes Fehlen, KEINE weitere Warning
    with pytest.raises(registration.AstroalignUnavailableError):
        registration.get_astroalign()
    assert log_recorder.names == ["registration.astroalign_unavailable"]

    # Neuer Prozesszustand (Cache-Reset) wuerde erneut warnen — hier nur
    # als Selbsttest des Resets: nach Reset + weiterhin blockiert -> 2. Warning
    registration._reset_astroalign_cache()
    with pytest.raises(registration.AstroalignUnavailableError):
        registration.get_astroalign()
    assert len(log_recorder.names) == 2


def test_astroalign_register_unavailable_raises_and_warns(
    monkeypatch: pytest.MonkeyPatch, log_recorder: _LogRecorder,
):
    """Wrapper bei fehlendem Extra: AstroalignUnavailableError (Aufrufer:
    fft-Fallback), die unavailable-Warning, ABER KEINE fallback-Warning
    (Fallback-Kette gilt nur fuer fehlgeschlagene astroalign-Aufrufe)."""
    monkeypatch.setitem(sys.modules, "astroalign", None)
    ref = np.zeros((16, 16), dtype=np.float32)
    tgt = np.zeros((16, 16), dtype=np.float32)

    with pytest.raises(registration.AstroalignUnavailableError):
        registration.astroalign_register(ref, tgt)

    assert log_recorder.names == ["registration.astroalign_unavailable"]


# ═══════════════════════════════════════════════════════════════════
# Wrapper-Aufruf + Fallback-Kette (AC-W9-C3, ADR-019)
# ═══════════════════════════════════════════════════════════════════


class _FakeTransform:
    pass


def _install_fake_module_w9(monkeypatch: pytest.MonkeyPatch, behavior: dict) -> None:
    """Setzt den Lazy-Import-Cache direkt auf ein Fake-Modul (umgeht den
    echten `import astroalign`)."""
    fake = SimpleNamespace(
        find_transform=behavior["find_transform"],
        MaxIterError=type("MaxIterError", (RuntimeError,), {}),
    )
    monkeypatch.setattr(registration, "_astroalign_module", fake)
    monkeypatch.setattr(registration, "_astroalign_checked", True)
    monkeypatch.setattr(registration, "_astroalign_available", True)


def test_wrapper_calls_find_transform_with_convention(
    monkeypatch: pytest.MonkeyPatch,
):
    """Aufruf-Konvention (S1-A6 `find_transform(src, ref)`): astroalign erhaelt
    (tgt_mono, ref_mono) in genau dieser Reihenfolge.

    Spike-Befund 1 (AC-W9-B4): `max_control_points=None` wird EXPLIZIT in 50
    uebersetzt — `null` wird NIE an die API durchgereicht (sonst
    `array[:None]` = ALLE Kontrollpunkte, M13-Risiko)."""
    calls: list[tuple] = []

    def _fake_find_transform(source, target, **kwargs):
        calls.append((source, target, kwargs))
        return _FakeTransform(), (list(range(4)), list(range(4)))

    _install_fake_module_w9(monkeypatch, {"find_transform": _fake_find_transform})

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)
    result = registration.astroalign_register(ref, tgt)

    assert len(calls) == 1
    source, target, kwargs = calls[0]
    assert source is tgt
    assert target is ref
    assert kwargs == {"max_control_points": 50}
    assert isinstance(result.transform, _FakeTransform)
    assert result.n_control_points == 4


def test_wrapper_null_translates_to_50_spy(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-B4 Spy: Config-Wert `null` (Wrapper-Parameter None) erreicht die
    API als 50 — der astroalign-Default, nicht `None`."""
    seen: dict = {}

    def _fake_find_transform(source, target, **kwargs):
        seen.update(kwargs)
        return _FakeTransform(), (list(range(3)), list(range(3)))

    _install_fake_module_w9(monkeypatch, {"find_transform": _fake_find_transform})

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)
    registration.astroalign_register(ref, tgt, max_control_points=None)

    assert seen == {"max_control_points": 50}


def test_wrapper_passes_explicit_value_spy(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-B4 Spy: expliziter Config-Wert (10) wird unveraendert an die API
    durchgereicht (kein 50-Ueberschreiben)."""
    seen: dict = {}

    def _fake_find_transform(source, target, **kwargs):
        seen.update(kwargs)
        return _FakeTransform(), (list(range(7)), list(range(7)))

    _install_fake_module_w9(monkeypatch, {"find_transform": _fake_find_transform})

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)
    registration.astroalign_register(ref, tgt, max_control_points=10)

    assert seen == {"max_control_points": 10}


def test_wrapper_passes_max_control_points_override(
    monkeypatch: pytest.MonkeyPatch,
):
    """max_control_points-Override (S1-A6: cfg oder Default 50) wird an
    astroalign durchgereicht."""
    seen: dict = {}

    def _fake_find_transform(source, target, **kwargs):
        seen.update(kwargs)
        return _FakeTransform(), (list(range(12)), list(range(12)))

    _install_fake_module_w9(monkeypatch, {"find_transform": _fake_find_transform})

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)
    registration.astroalign_register(ref, tgt, max_control_points=100)

    assert seen == {"max_control_points": 100}


@pytest.mark.parametrize(
    "exc_type",
    [ValueError, TypeError],
)
def test_fallback_on_error_classes(
    monkeypatch: pytest.MonkeyPatch, log_recorder: _LogRecorder,
    exc_type: type[BaseException],
):
    """AC-W9-C3/ADR-019: ValueError (<3 Sterne) und TypeError -> Warning
    `registration.astroalign_fallback` (reason) + erneutes Werfen."""
    def _boom(source, target, **kwargs):
        raise exc_type("kaputt")

    _install_fake_module_w9(monkeypatch, {"find_transform": _boom})

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)

    with pytest.raises(exc_type):
        registration.astroalign_register(ref, tgt)

    assert log_recorder.names == ["registration.astroalign_fallback"]
    event, kwargs = log_recorder.events[0]
    assert kwargs["method"] == "astroalign"
    assert exc_type.__name__ in kwargs["reason"]


def test_fallback_on_max_iter_error(
    monkeypatch: pytest.MonkeyPatch, log_recorder: _LogRecorder,
):
    """MaxIterError (astroalign-Klasse) wird dynamisch aus dem Modul gelesen
    und gehoert zur Fallback-Kette."""
    def _boom(source, target, **kwargs):
        raise RuntimeError("MaxIterError: no transform found")

    _install_fake_module_w9(monkeypatch, {"find_transform": _boom})

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)

    # MaxIterError ist ein RuntimeError-Subtyp im Fake -> generischer Zweig
    with pytest.raises(RuntimeError):
        registration.astroalign_register(ref, tgt)

    assert log_recorder.names == ["registration.astroalign_fallback"]
    assert "RuntimeError" in log_recorder.events[0][1]["reason"]


def test_fallback_on_unknown_error(
    monkeypatch: pytest.MonkeyPatch, log_recorder: _LogRecorder,
):
    """Unbekannte astroalign-Fehler (z.B. RuntimeError aus einer anderen
    Quellversion) -> generischer Zweig: Warning + erneutes Werfen. Kein
    stummer Lauf."""
    def _boom(source, target, **kwargs):
        raise RuntimeError("unexpected")

    _install_fake_module_w9(monkeypatch, {"find_transform": _boom})

    ref = np.zeros((32, 32), dtype=np.float32)
    tgt = np.zeros((32, 32), dtype=np.float32)

    with pytest.raises(RuntimeError, match="unexpected"):
        registration.astroalign_register(ref, tgt)

    assert log_recorder.names == ["registration.astroalign_fallback"]


# ═══════════════════════════════════════════════════════════════════
# Real-astroalign (nur wenn Extra installiert)
# ═══════════════════════════════════════════════════════════════════


def test_real_astroalign_register_synthetic_pair():
    """Real-Lauf: Wrapper verarbeitet ein synthetisches Sternfeld-Paar und
    liefert AstroalignResult(transform, n_control_points) — schwache Assertion
    (nur Typen), da RANSAC nicht seedbar ist (ADR-021 Nichtdeterminismus-
    Caveat; exakte Mapping-Mathematik prueft S1-A7)."""
    pytest.importorskip("astroalign")
    rng = np.random.RandomState(42)

    def _starfield(shape=(128, 128), n_stars=25, seed: int = 1):
        img = np.zeros(shape, dtype=np.float32)
        rr = np.random.RandomState(seed)
        ys = rr.randint(5, shape[0] - 5, n_stars)
        xs = rr.randint(5, shape[1] - 5, n_stars)
        yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
        for y0, x0 in zip(ys, xs, strict=True):
            img += 40.0 * np.exp(-((yy - y0) ** 2 + (xx - x0) ** 2) / 6.0)
        img += rng.normal(0, 1.0, shape).astype(np.float32)
        return img

    ref = _starfield(seed=1)
    tgt = _starfield(seed=1)
    # Bekannte Translation (5, 3): tgt gegen ref wird registriert
    tgt = np.roll(np.roll(tgt, 5, axis=0), 3, axis=1)

    result = registration.astroalign_register(ref, tgt)
    assert result.transform is not None
    assert isinstance(result.n_control_points, int)
    assert result.n_control_points > 0


# ═══════════════════════════════════════════════════════════════════
# doctor Check 3 (AC-W9-A3)
# ═══════════════════════════════════════════════════════════════════


def _write_default_config(tmp: Path) -> None:
    import yaml

    from astro_process.config.loader import DEFAULT_CONFIG

    data = yaml.safe_load(DEFAULT_CONFIG)
    data["data_root"] = "."
    (tmp / "config.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_doctor_lists_all_w9_deps_ok():
    """AC-W9-A3: doctor meldet alle drei W9-A-Dependencies als OK, wenn das
    Extra installiert ist (sonst skip)."""
    pytest.importorskip("astroalign")
    pytest.importorskip("sep")
    pytest.importorskip("skimage")

    runner = CliRunner()
    with runner.isolated_filesystem() as fs:
        _write_default_config(Path(fs))
        with patch("astro_process.cli._run_with_timeout", return_value=MagicMock()):
            result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])

    assert result.exit_code in (0, 1), result.output
    assert "[OK] astroalign importierbar" in result.output
    assert "[OK] sep importierbar" in result.output
    assert "[OK] scikit-image importierbar" in result.output


def test_doctor_warns_when_astroalign_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-A3: fehlendes astroalign -> WARN dep.astroalign (Exit 1) mit
    Installations-Hinweis — kein FAIL/kein Crash."""
    monkeypatch.setitem(sys.modules, "astroalign", None)

    runner = CliRunner()
    with runner.isolated_filesystem() as fs:
        _write_default_config(Path(fs))
        with patch("astro_process.cli._run_with_timeout", return_value=MagicMock()):
            result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])

    assert result.exit_code == 1, result.output
    assert "[WARN] astroalign fehlt" in result.output
    assert "astra[astroalign]" in result.output

# ═══════════════════════════════════════════════════════════════════
# Section: W9-D — Cross-Group-Registration
# (integriert aus test_registration_cross_group.py)
# ═══════════════════════════════════════════════════════════════════











# ═══════════════════════════════════════════════════════════════════
# Section: RegistrationResult + Default method="fft" (AC-W9-D2/D3/C5)
# ═══════════════════════════════════════════════════════════════════


def test_registration_result_w9d2_fields_defaults():
    """AC-W9-D2: RegistrationResult traegt method/rotation_deg/scale/
    n_control_points mit fft-Defaults — bestehende Aufrufer (ohne die neuen
    Felder) bleiben kompatibel."""
    res = RegistrationResult(path=Path("x.fits"))
    assert res.method == "fft"
    assert res.rotation_deg == 0.0
    assert res.scale == 1.0
    assert res.n_control_points is None

    res_aa = RegistrationResult(
        path=Path("y.fits"), method="astroalign",
        rotation_deg=-0.31, scale=1.0001, n_control_points=42,
    )
    assert res_aa.method == "astroalign"
    assert res_aa.rotation_deg == -0.31
    assert res_aa.n_control_points == 42


def test_cross_group_default_fft_never_touches_astroalign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-D3/C5: Default method='fft' (params=None) -> v1.1-Verhalten:
    astroalign wird NIE beruehrt (Import blockiert), Ergebnis method='fft',
    rotation 0 / scale 1 / ncp None, aligned.fits unter 04_stacked."""
    monkeypatch.setitem(sys.modules, "astroalign", None)
    rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    ref = _write_2d_frame(tmp_path / "ref.fits", _block_image())
    tgt = _write_2d_frame(tmp_path / "tgt.fits", _block_image())
    res = agent._register_to_reference_stack(
        tgt, ref, filter_name="", output_dir=tmp_path / "aligned",
    )

    assert res.method == "fft"
    assert res.rotation_deg == 0.0
    assert res.scale == 1.0
    assert res.n_control_points is None
    assert res.path.name == "aligned.fits"
    assert res.path.exists()
    # Kein astroalign-Event: keine unavailable/fallback/downgrade-Warning
    assert not rec.events_named("registration.astroalign_unavailable")
    assert not rec.events_named("registration.astroalign_fallback")
    assert not rec.events_named("registration.astroalign_downgraded")
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"
    assert transform_event[1]["rotation_deg"] == 0.0
    assert transform_event[1]["scale"] == 1.0


# ═══════════════════════════════════════════════════════════════════
# Section: Cross-Group-Arbitration (AC-W9-D4 = AC-W9-C3, Fake-Module)
# ═══════════════════════════════════════════════════════════════════


def test_cross_group_astroalign_unavailable_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-D4: method='astroalign' ohne installiertes Extra -> einmalige
    `registration.astroalign_unavailable`-Warning (Strategie-Logger) +
    fft-Fallback (method='fft')."""
    monkeypatch.setitem(sys.modules, "astroalign", None)
    reg_rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", reg_rec)
    agent_rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", agent_rec)

    agent = _make_agent(tmp_path / "out")
    ref = _write_2d_frame(tmp_path / "ref.fits", _block_image())
    tgt = _write_2d_frame(tmp_path / "tgt.fits", _block_image())
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None}}
    res = agent._register_to_reference_stack(
        tgt, ref, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "fft"
    assert reg_rec.names == ["registration.astroalign_unavailable"]
    assert "registration.astroalign_downgraded" not in agent_rec.names
    transform_event = agent_rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"


def test_cross_group_astroalign_wins_with_fake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-D1/D4: Fake-astroalign liefert (0,0)-Transform auf identischem
    Paar -> corr_hp_aa (=1.0) >= corr_hp_fft (1.0) - 0.05 -> astroalign
    gewinnt; Transform-Log (stack-Kontext) mit method/rotation/scale/ncp."""
    _install_fake_module(monkeypatch)
    rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    ref = _write_2d_frame(tmp_path / "ref.fits", _block_image())
    tgt = _write_2d_frame(tmp_path / "tgt.fits", _block_image())
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None}}
    res = agent._register_to_reference_stack(
        tgt, ref, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "astroalign"
    assert res.rotation_deg == 0.0
    assert res.scale == 1.0
    assert res.n_control_points == 5
    assert res.path.exists()
    transform_events = rec.events_named("registration.transform")
    assert transform_events, rec.names
    event, fields = transform_events[0]
    assert event == "registration.transform"
    assert fields["method"] == "astroalign"
    assert fields["rotation_deg"] == 0.0
    assert fields["scale"] == 1.0
    assert fields["n_control_points"] == 5
    # kein Downgrade, kein Zero-Shift
    assert "registration.astroalign_downgraded" not in rec.names
    assert "registration.zero_shift_fallback" not in rec.names


def test_cross_group_astroalign_downgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-D4: astroalign-Transform ist schlechter (grosse Translation auf
    identischem Paar) -> corr_hp_aa < corr_hp_fft - 0.05 -> fft gewinnt +
    `registration.astroalign_downgraded`-Warning; Transform-Log method='fft'
    mit tatsaechlich angewendeten Shifts."""
    def _bad_find(source, target, **kwargs):
        return (_FakeSimilarityTransform(x=12.0, y=-8.0),
                (list(range(5)), list(range(5))))

    def _real_apply(transform, source, target,
                    fill_value=None, propagate_mask=False):
        sy, sx = float(transform.translation[1]), float(transform.translation[0])
        aligned = scipy_shift(
            source, (sy, sx), order=3, mode="constant",
            cval=fill_value if fill_value is not None else 0.0,
        )
        return aligned, np.ones_like(source, dtype=bool)

    _install_fake_module(monkeypatch, find_transform=_bad_find,
                         apply_transform=_real_apply)
    rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    ref = _write_2d_frame(tmp_path / "ref.fits", _block_image())
    tgt = _write_2d_frame(tmp_path / "tgt.fits", _block_image())
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None}}
    res = agent._register_to_reference_stack(
        tgt, ref, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "fft"
    assert res.rotation_deg == 0.0
    assert res.scale == 1.0
    downgraded = rec.events_named("registration.astroalign_downgraded")
    assert downgraded, rec.names
    assert downgraded[0][1]["corr_hp_fft"] == pytest.approx(1.0, abs=1e-6)
    assert downgraded[0][1]["corr_hp_aa"] < 0.95

    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"


def test_cross_group_astroalign_error_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-D4: astroalign wirft ValueError (<3 Sterne) -> fft gewinnt, kein
    Abbruch; die `registration.astroalign_fallback`-Warning kommt aus der
    Strategie (registration-Modul-Logger), der Agent loggt kein Downgrade."""
    def _boom(source, target, **kwargs):
        raise ValueError(
            "Reference stars in source image are less than the minimum value (3)."
        )

    _install_fake_module(monkeypatch, find_transform=_boom)
    reg_rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", reg_rec)
    agent_rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", agent_rec)

    agent = _make_agent(tmp_path / "out")
    ref = _write_2d_frame(tmp_path / "ref.fits", _block_image())
    tgt = _write_2d_frame(tmp_path / "tgt.fits", _block_image())
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None}}
    res = agent._register_to_reference_stack(
        tgt, ref, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "fft"
    assert reg_rec.names == ["registration.astroalign_fallback"]
    assert "ValueError" in reg_rec.events[0][1]["reason"]
    assert "registration.astroalign_downgraded" not in agent_rec.names
    transform_event = agent_rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"


def test_cross_group_zero_shift_guard_rejects_astroalign_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-RE-F1 (RE-F/V1.3-24): Cross-Group analog zur Intra-Group —
    astroalign-Gewinner mit corr_hp_aa < 0.3 (uniform -> 0.0) wird VERWORFEN:
    status="rejected", kein (0,0)-Transform, kein zero_shift_fallback-Event,
    kein aligned.fits erzeugt. (Ersetzt die AC-W9-D4-Erwartung, ray-Review M1;
    R1-Semantik: Ausschluss aus dem Merge durch den Aufrufer.)"""
    _install_fake_module(monkeypatch)  # (0,0)-Transform -> corr_hp_aa = 0.0
    rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", rec)

    img = np.zeros((64, 64), dtype=np.float32)  # uniform -> corr 0.0
    ref = _write_2d_frame(tmp_path / "ref.fits", img)
    tgt = _write_2d_frame(tmp_path / "tgt.fits", img)
    agent = _make_agent(tmp_path / "out")
    # explizit hohe Schwelle (Default seit V19-FIX-12: 0.05)
    params = {"registration": {"method": "astroalign",
                               "max_control_points": None,
                               "zero_shift_threshold": 0.3}}
    res = agent._register_to_reference_stack(
        tgt, ref, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.status == "rejected"
    assert res.method == "astroalign"
    assert "registration.stack_rejected" in rec.names
    assert "registration.zero_shift_fallback" not in rec.names
    rejected = rec.events_named("registration.stack_rejected")
    assert rejected[0][1]["corr_hp"] == pytest.approx(0.0, abs=1e-6)
    # kein Zero-Shift-Stacking: aligned.fits wird nicht erzeugt
    assert not (tmp_path / "aligned" / "aligned.fits").exists()


# ═══════════════════════════════════════════════════════════════════
# Section: Kanalwahl filter-bewusst (AC9 / OQ-W9-6)
# ═══════════════════════════════════════════════════════════════════


def test_cross_group_channel_selection_filter_aware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC9/OQ-W9-6: Cross-Group nutzt `_select_registration_channel` OHNE
    force_g_channel=True (filter-bewusst: Duo-Band -> R, OIII -> G+B,
    Broadband -> Luminance) — der Filter wird durchgereicht. (Intra nutzt
    dagegen force_g_channel=True, W11/W12.)"""
    agent = _make_agent(tmp_path / "out")
    ref_path = create_test_fits(tmp_path / "ref3.fits", shape=(64, 64, 3),
                                add_stars=True, rng_seed=1)
    tgt_path = create_test_fits(tmp_path / "tgt3.fits", shape=(64, 64, 3),
                                add_stars=True, rng_seed=1)

    calls: list[tuple[str, bool]] = []

    def _spy(data, filter_name="", force_g_channel=False):
        calls.append((filter_name, force_g_channel))
        return np.zeros((64, 64), dtype=np.float32), "R"

    # Refactor 2026-08-14 (Cluster 6): Cross-Group-Registration liegt in
    # multi_group_agent — der Spy muss dort patchen (processing_agent
    # importiert select_registration_channel nicht mehr).
    monkeypatch.setattr(multi_group_agent, "select_registration_channel", _spy)
    agent._register_to_reference_stack(
        tgt_path, ref_path, filter_name="Duo-Band",
        output_dir=tmp_path / "aligned",
    )

    assert len(calls) == 2, calls  # stack + ref
    assert calls[0][0] == "Duo-Band"
    assert calls[1][0] == "Duo-Band"
    assert all(not force for _, force in calls), calls


# ═══════════════════════════════════════════════════════════════════
# Section: Report additiv (AC-W9-D2, OQ-W9-5)
# ═══════════════════════════════════════════════════════════════════


def test_cross_group_report_fields_additive(tmp_path: Path):
    """AC-W9-D2: `cross_group_registrations`-Eintraege tragen die neuen Felder
    method/rotation_deg/scale/n_control_points ZUSAETZLICH zu den bestehenden
    (group/reference/shift_y/shift_x/correlation/corr_roh/corr_hp/status) —
    keine Umbenennung, keine Entfernung."""
    agent = _make_agent(tmp_path / "out")
    context = make_sample_context(tmp_path, group_count=2, frames_per_group=3)
    mg_config = MultiGroupConfig()
    pipeline = MagicMock()
    pipeline.processing_params = ProcessingParams()
    pipeline.steps = []

    lights = context.get_lights()
    cal_result = MagicMock()
    cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
    deb_result = MagicMock()
    deb_result.debayered_frames = []

    merge_agent = MergeAgent(working_dir=tmp_path, config=None)

    stack_fits = {
        "15s60": create_test_fits(tmp_path / "stack_15s60.fits",
                                  exptime=15.0, gain=60, rng_seed=1),
        "60s40": create_test_fits(tmp_path / "stack_60s40.fits",
                                  exptime=60.0, gain=40, rng_seed=2),
    }

    pcc_counter = {"n": 0}

    def fake_pcc(stack_path, *args, **kwargs):
        pcc_counter["n"] += 1
        p = tmp_path / f"pcc_stack_{pcc_counter['n']}.fits"
        create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
        return (p, "gaia_success")

    with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
         patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
         patch.object(agent, "_register_to_reference_stack") as mock_cross, \
         patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
        mock_reg.return_value = RegisterFramesResult(
            registered=[], last_frame_qualities=[], last_frame_rejected=0,
            last_registration_metrics={},
        )
        mock_stack.return_value = stack_fits["15s60"]
        mock_cross.return_value = RegistrationResult(
            path=stack_fits["60s40"],
            shift_y=-5.0,
            shift_x=-3.0,
            correlation=0.5,
            corr_hp=0.72,
            status="ok",
            method="astroalign",
            rotation_deg=-0.31,
            scale=1.0001,
            n_control_points=42,
        )
        mock_pcc.side_effect = fake_pcc

        proc_result = agent.process_multi_group(
            context, cal_result, deb_result, pipeline,
            multi_group_config=mg_config, merge_agent=merge_agent,
        )

    report_path = tmp_path / "merged" / "merge_report.json"
    assert report_path.exists(), f"merge_report.json fehlt: {report_path}"
    report = json.loads(report_path.read_text())

    regs = report["cross_group_registrations"]
    assert len(regs) == 1
    entry = regs[0]
    # Bestehende Felder unveraendert (P3-B, W2)
    assert entry["reference"] == report["reference_group"]
    assert entry["group"] != entry["reference"]
    assert entry["shift_y"] == -5.0
    assert entry["shift_x"] == -3.0
    assert entry["correlation"] == 0.5
    assert entry["corr_roh"] == 0.5
    assert entry["corr_hp"] == 0.72
    assert entry["status"] == "ok"
    # Neue W9-D2-Felder
    assert entry["method"] == "astroalign"
    assert entry["rotation_deg"] == -0.31
    assert entry["scale"] == 1.0001
    assert entry["n_control_points"] == 42

    assert proc_result.stacked is not None
    assert proc_result.stacked.exists()


# ═══════════════════════════════════════════════════════════════════
# Section: Real-Synthetik - AC-W9-D1/D4 via importorskip
# ═══════════════════════════════════════════════════════════════════


def _stack_mono_fits(paths: list[Path], out_path: Path) -> Path:
    """Mittelt Mono-Lights (H, W) zu einem Gruppen-Stack-FITS."""
    frames = [np.asarray(fits.getdata(p), dtype=np.float32) for p in paths]
    stacked = np.mean(frames, axis=0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(stacked.astype(np.float32)).writeto(out_path, overwrite=True)
    return out_path


def test_cross_group_real_astroalign_wins_spike_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-D1 Real (nur mit Extra): Cross-Group auf einem hellen Sternfeld
    (Spike-Vorbild: Shift (2.3,-1.7) px + Rotation 0.3 Grad) — astroalign
    gewinnt die Arbitration: method='astroalign', rotation/scale im Result,
    aligned.fits existiert. Assertions toleranzbasiert (ADR-021
    RANSAC-Nichtdeterminismus; Rotation um den Ursprung koppelt die
    Translation an die Sterngeometrie)."""
    pytest.importorskip("astroalign")
    ref = _spike_starfield()
    tgt = _shifted_rotated(ref)
    ref_path = _write_2d_frame(tmp_path / "ref.fits", ref)
    tgt_path = _write_2d_frame(tmp_path / "tgt.fits", tgt)

    agent = _make_agent(tmp_path / "out")
    params = {"registration": {"method": "astroalign",
                               "max_control_points": 50}}
    res = agent._register_to_reference_stack(
        tgt_path, ref_path, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "astroalign"
    assert res.path.name == "aligned.fits"
    assert res.path.exists()
    # Injektion: tgt hat Move rows=+2.3, cols=-1.7 von ref -> Transform auf
    # tgt (gegen ref) muss ~(-2.3, +1.7) sein (Vorzeichen = Konvention).
    assert res.shift_y < 0.0, (res.shift_y, res.shift_x)
    assert res.shift_x > 0.0, (res.shift_y, res.shift_x)
    assert res.shift_y == pytest.approx(-2.3, abs=1.0)
    assert res.shift_x == pytest.approx(1.7, abs=1.0)
    assert res.rotation_deg == pytest.approx(-0.3, abs=0.2)
    assert res.scale == pytest.approx(1.0, abs=0.002)
    assert isinstance(res.n_control_points, int)


def test_cross_group_m13_analog_qf_c_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """AC-W9-D4 Real (nur mit Extra): M13-Analog-QF-C-Szene (Dichte-Referenz,
    multi-group) laeuft mit method='astroalign' in der Cross-Group-Phase ohne
    Abbruch durch. S1-A7/S1-A8-Befund: auf der schwach-Stern-Konfiguration
    (Flux 8-30 auf Sky 100, inkonsistentes Sternfeld) scheitert astroalign
    mit MaxIterError -> Fallback-Kette greift
    (registration.astroalign_fallback-Warning pro Gruppe), method='fft',
    rotation 0 / scale 1 — aligned.fits + Report-Metadaten bleiben korrekt.
    Die S1-A8-Konfiguration wird explizit erzeugt: der S1-A9-Default des
    M13-Analogs (konsistentes Sternfeld, Flux 60-250) ist astroalign-tauglich
    und wird in test_quality_foundation.py positiv geprueft.
    Referenz ist 60s40 (W14-Bezugsgruppe)."""
    pytest.importorskip("astroalign")
    import synthetic

    scene = synthetic.generate_m13_analog(
        tmp_path / "m13", seed=42,
        star_field_consistent=False,
        star_flux_range=(8.0, 30.0),
        motion_fill=0.0,
        motion_prefilter=False,
        motion_order=1,
    )
    group_map = scene.dataset.group_map
    assert len(group_map) == 4

    # Stacks je Gruppe (4 Mono-Lights mitteln)
    stacks: dict[str, Path] = {}
    for key, paths in group_map.items():
        assert len(paths) == 4
        stacks[key] = _stack_mono_fits(
            [Path(p) for p in paths], tmp_path / f"stack_{key}.fits",
        )

    reg_rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", reg_rec)
    agent_rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", agent_rec)

    agent = _make_agent(tmp_path / "out")
    ref_key = "60s40"
    params = {"registration": {"method": "astroalign",
                               "max_control_points": 50}}
    results: dict[str, RegistrationResult] = {}
    for key, stack_path in stacks.items():
        if key == ref_key:
            continue
        res = agent._register_to_reference_stack(
            stack_path, stacks[ref_key], filter_name="",
            output_dir=tmp_path / f"aligned_{key}", params=params,
        )
        results[key] = res

    assert set(results) == {"15s60", "15s40", "60s60"}
    for key, res in results.items():
        # Fallback-Befund: fft gewinnt (astroalign scheitert, kein Abbruch)
        assert res.method == "fft", (key, res.method)
        assert res.rotation_deg == 0.0
        assert res.scale == 1.0
        assert res.n_control_points is None
        assert res.path.exists()
        assert res.path.name == "aligned.fits"

    # Fallback-Warning pro Nicht-Referenz-Gruppe (MaxIterError)
    fallbacks = reg_rec.events_named("registration.astroalign_fallback")
    assert len(fallbacks) == 3, reg_rec.names
    assert all("MaxIterError" in e[1]["reason"] for e in fallbacks)

    # Transform-Log: genau 3 Zeilen (eine je Nicht-Referenz-Gruppe), alle fft
    transforms = agent_rec.events_named("registration.transform")
    assert len(transforms) == 3, agent_rec.names
    assert all(e[1]["method"] == "fft" for e in transforms)


# ═══════════════════════════════════════════════════════════════════
# P2-1 (ray-Review): Cross-Group-Teil — Referenz-only-Merge
# ═══════════════════════════════════════════════════════════════════


def test_merge_agent_reference_only_insufficient_stacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """P2-1 (ray-Review, Cross-Group-Teil): Referenz-only-Merge — nur der
    Referenz-Stack vorhanden (alle Nicht-Referenz-Stacks per
    `registration.stack_rejected`/RE-F ausgeschlossen) -> V1.9.1 FIX-11:
    merge.single_stack_fallback (Warnung statt hart Skip, merged aus 1 Stack)."""
    import astro_process.agents.merge_agent as merge_agent_module

    rec = _LogRecorder()
    monkeypatch.setattr(merge_agent_module, "logger", rec)
    stack = create_test_fits(tmp_path / "ref_stack.fits", exptime=60.0, gain=40, rng_seed=1)
    merge_agent = MergeAgent(working_dir=tmp_path, config=None)

    result = merge_agent.run(
        group_stacks={"60s40": stack},
        group_metadata={
            "60s40": {
                "frame_count": 3, "exptime": 60.0, "gain": 40, "filter": None,
                "total_exposure": 180.0, "dark_source": "none",
                "pcc_status": "gaia_success",
            }
        },
        target_name="TestTarget",
        merge_config=MergeConfig(),
    )

    assert result.merged_path is not None
    assert result.merged_path.exists()
    assert "error" not in result.merge_report
    assert "merge.single_stack_fallback" in rec.names


def test_multi_group_all_cross_group_rejected_reference_only_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """P2-1 (ray-Review, Cross-Group-Teil): alle Nicht-Referenz-Stacks per
    astroalign-Reject (RegistrationResult status="rejected", RE-F) aus dem
    Merge ausgeschlossen -> Referenz-only-Merge: kein Crash,
    skipped_groups-Report enthaelt den astroalign-Reject-Eintrag,
    merged_path None (MergeAgent-Guard "insufficient_stacks")."""
    agent = _make_agent(tmp_path / "out")
    context = make_sample_context(tmp_path, group_count=2, frames_per_group=3)
    pipeline = MagicMock()
    pipeline.processing_params = ProcessingParams()
    pipeline.steps = []

    lights = context.get_lights()
    cal_result = MagicMock()
    cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
    deb_result = MagicMock()
    deb_result.debayered_frames = []

    stack_fits = {
        "15s60": create_test_fits(tmp_path / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
        "60s40": create_test_fits(tmp_path / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
    }

    def fake_register(frames, params, is_3d=False, **kwargs):
        # Refactor 2026-08-14 (Cluster 3): process_multi_group erwartet ein
        # RegisterFramesResult (der Agent uebernimmt die _last_*-Attribute).
        return RegisterFramesResult(
            registered=[Path(f) for f in frames],
            last_frame_qualities=[],
            last_frame_rejected=0,
            last_registration_metrics={},
        )

    def fake_cross(stack_path, ref_stack_path, filter_name, stack_dir, params=None):
        # JEDER Nicht-Referenz-Stack: astroalign-Gewinner unter der Schwelle
        return RegistrationResult(
            path=stack_path, shift_y=0.0, shift_x=0.0,
            correlation=0.2, corr_hp=0.2, status="rejected",
            method="astroalign",
        )

    pcc_counter = {"n": 0}

    def fake_pcc(stack_path, *args, **kwargs):
        pcc_counter["n"] += 1
        p = tmp_path / f"pcc_stack_{pcc_counter['n']}.fits"
        create_test_fits(p, exptime=60.0, gain=40, rng_seed=pcc_counter["n"])
        return (p, "gaia_success")

    rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", rec)

    # Referenz deterministisch auf 60s40 (Hash-Strategie, AC-W14-1 manuelle
    # Uebersteuerung) — unabhaengig vom Signalmaß der Test-Stacks.
    mg_config = MultiGroupConfig(reference_group="60s40")

    with patch("astro_process.agents.multi_group_agent.register_frames", side_effect=fake_register), \
         patch("astro_process.agents.multi_group_agent.stack_frames", return_value=stack_fits["60s40"]) as mock_stack, \
         patch.object(agent, "_register_to_reference_stack", side_effect=fake_cross) as mock_cross, \
         patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
        proc_result = agent.process_multi_group(
            context, cal_result, deb_result, pipeline,
            multi_group_config=mg_config,
            merge_agent=MergeAgent(working_dir=tmp_path, config=None),
        )

    assert proc_result is not None  # kein Crash
    assert proc_result.stacked is not None  # V1.9.1 FIX-11: Referenz-only -> single_stack_fallback mit merged
    # Beide Gruppen registriert/gestackt; Cross-Group nur fuer die
    # Nicht-Referenz-Gruppe (15s60)
    assert mock_stack.call_count == 2, mock_stack.call_count
    assert mock_cross.call_count == 1, mock_cross.call_count
    # Report: astroalign-Reject additiv in skipped_groups
    skipped = proc_result.multi_group_metadata["skipped_groups"]
    assert any(
        e["group"] == "15s60"
        and e["reason"] == "astroalign_below_zero_shift_threshold"
        and e["corr_hp"] == 0.2
        for e in skipped
    ), skipped


# ═══════════════════════════════════════════════════════════════════
# Section: rotation_fft (V1.4-2) — Cross-Group-Arbitration + WCS
# ═══════════════════════════════════════════════════════════════════


def _write_2d_frame_with_wcs(path: Path, data: np.ndarray,
                             cdelt: float = 0.000138889) -> Path:
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


def test_cross_group_rotation_fft_wins_rotated_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """V1.4-2 + V1.5-4: method='rotation_fft' auf einem um 10 Grad rotierten +
    verschobenen Spike-Sternfeld -> Compute-both-Arbitration: corr_hp_rot
    (~0.79) deutlich >= corr_hp_fft + 0.02 -> rotation_fft gewinnt;
    rotation_deg im Result (9.0; Task-Toleranz +-2 um 10), aligned.fits
    existiert, Transform-Log method='rotation_fft'. Die Referenz traegt
    CDELT-WCS -> der aligned-Header bekommt REG_ROT (V1.5-4 / DADR-014)
    statt CD-Matrix; CDELT bleibt erhalten."""
    rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    ref = _spike_starfield()
    tgt = scipy_shift(
        rotate(ref, 10.0, reshape=False, order=3, mode="nearest"),
        (2.3, -1.7), order=3, mode="nearest",
    )
    ref_path = _write_2d_frame_with_wcs(tmp_path / "ref.fits", ref)
    tgt_path = _write_2d_frame(tmp_path / "tgt.fits", tgt)
    params = {"registration": {"method": "rotation_fft",
                               "max_rotation_deg": 15.0}}
    res = agent._register_to_reference_stack(
        tgt_path, ref_path, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "rotation_fft"
    assert res.rotation_deg == pytest.approx(10.0, abs=2.0)
    assert res.scale == pytest.approx(1.0, abs=0.02)
    assert res.status == "ok"
    assert res.path.name == "aligned.fits"
    assert res.path.exists()
    assert "registration.rotation_fft_downgraded" not in rec.names
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "rotation_fft"
    assert transform_event[1]["rotation_deg"] == pytest.approx(10.0, abs=2.0)
    # V1.5-4 / DADR-014: REG_ROT statt CD-Matrix (rotation != 0)
    header = fits.getheader(res.path)
    assert "REG_ROT" in header
    assert header["REG_ROT"] == pytest.approx(res.rotation_deg, abs=2.0)
    # CDELT bleibt erhalten (kein CD-Schreiben)
    assert "CDELT1" in header
    assert "CDELT2" in header
    assert "CD1_1" not in header
    assert "CD1_2" not in header


def test_cross_group_rotation_fft_identical_pair_stays_fft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """V1.4-2: method='rotation_fft' auf identischem Paar -> keine
    Verbesserung (corr_hp_rot 1.0 < corr_hp 1.0 + 0.02) -> fft gewinnt
    (sichere Baseline, Normal-Fall byte-stabil), Warning
    `registration.rotation_fft_downgraded`, Transform-Log method='fft'."""
    rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", rec)

    agent = _make_agent(tmp_path / "out")
    img = _spike_starfield()
    ref_path = _write_2d_frame(tmp_path / "ref.fits", img)
    tgt_path = _write_2d_frame(tmp_path / "tgt.fits", img)
    params = {"registration": {"method": "rotation_fft",
                               "max_rotation_deg": 15.0}}
    res = agent._register_to_reference_stack(
        tgt_path, ref_path, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "fft"
    assert res.rotation_deg == 0.0
    assert res.scale == 1.0
    downgraded = rec.events_named("registration.rotation_fft_downgraded")
    assert downgraded, rec.names
    assert downgraded[0][1]["corr_hp_rot"] == pytest.approx(1.0, abs=1e-6)
    assert downgraded[0][1]["corr_hp_fft"] == pytest.approx(1.0, abs=1e-6)
    transform_event = rec.events_named("registration.transform")[0]
    assert transform_event[1]["method"] == "fft"


def test_cross_group_astroalign_fallback_uses_rotation_fft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """V1.4-2: method='astroalign' mit scheiterndem astroalign (ValueError,
    <3 Sterne) auf einem rotierten Paar -> die zusaetzliche rotation_fft-
    Fallback-Stufe (V1.3-5-Hinweis) gewinnt statt Translation-only-fft:
    winner='rotation_fft', rotation_deg ~9 Grad. Die
    astroalign_fallback-Warning kommt aus der Strategie; kein
    astroalign_downgraded."""
    def _boom(source, target, **kwargs):
        raise ValueError(
            "Reference stars in source image are less than the minimum value (3)."
        )

    _install_fake_module(monkeypatch, find_transform=_boom)
    reg_rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", reg_rec)
    agent_rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", agent_rec)

    agent = _make_agent(tmp_path / "out")
    ref = _spike_starfield()
    tgt = scipy_shift(
        rotate(ref, 10.0, reshape=False, order=3, mode="nearest"),
        (2.3, -1.7), order=3, mode="nearest",
    )
    ref_path = _write_2d_frame(tmp_path / "ref.fits", ref)
    tgt_path = _write_2d_frame(tmp_path / "tgt.fits", tgt)
    params = {"registration": {"method": "astroalign",
                               "max_control_points": 50,
                               "max_rotation_deg": 15.0}}
    res = agent._register_to_reference_stack(
        tgt_path, ref_path, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "rotation_fft"
    assert res.rotation_deg == pytest.approx(10.0, abs=2.0)
    assert res.path.name == "aligned.fits"
    assert res.path.exists()
    assert reg_rec.names == ["registration.astroalign_fallback"]
    assert "registration.astroalign_downgraded" not in agent_rec.names


def test_cross_group_rotation_fft_sanity_rejected_falls_back_to_fft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """V1.4-2: Sanity-Guard-Verletzung (max_rotation_deg=2.0 auf 10-Grad-
    Paar) -> Registrierung faellt auf fft zurueck (winner='fft', rotation 0),
    `registration.rotation_fft_sanity_rejected`-Warning aus der Strategie,
    kein Abbruch."""
    reg_rec = _LogRecorder()
    monkeypatch.setattr(registration, "logger", reg_rec)
    agent_rec = _LogRecorder()
    monkeypatch.setattr(processing_agent, "logger", agent_rec)

    agent = _make_agent(tmp_path / "out")
    ref = _spike_starfield()
    tgt = rotate(ref, 10.0, reshape=False, order=3, mode="nearest")
    ref_path = _write_2d_frame(tmp_path / "ref.fits", ref)
    tgt_path = _write_2d_frame(tmp_path / "tgt.fits", tgt)
    params = {"registration": {"method": "rotation_fft",
                               "max_rotation_deg": 2.0}}
    res = agent._register_to_reference_stack(
        tgt_path, ref_path, filter_name="", output_dir=tmp_path / "aligned",
        params=params,
    )

    assert res.method == "fft"
    assert res.rotation_deg == 0.0
    assert res.path.exists()
    assert reg_rec.names == ["registration.rotation_fft_sanity_rejected"]
    assert "registration.rotation_fft_downgraded" not in agent_rec.names


def test_copy_wcs_headers_writes_reg_rot_on_rotation(tmp_path: Path):
    """V1.5-4 / DADR-014: _copy_wcs_headers mit rotation_deg=10 -> REG_ROT
    (Grad) als separates Keyword, CDELT bleibt erhalten, keine CD-Matrix.
    Basis-WCS-Keys (CRVAL/CRPIX/CTYPE/CUNIT) bleiben."""
    agent = _make_agent(tmp_path / "out")
    src = _write_2d_frame_with_wcs(tmp_path / "src.fits",
                                   np.zeros((16, 16), dtype=np.float32))
    tgt = _write_2d_frame(tmp_path / "tgt.fits",
                          np.zeros((16, 16), dtype=np.float32))

    agent._copy_wcs_headers(src, tgt, rotation_deg=10.0)

    header = fits.getheader(tgt)
    # V1.5-4: REG_ROT statt CD-Matrix
    assert "REG_ROT" in header
    assert header["REG_ROT"] == pytest.approx(10.0, abs=1e-10)
    # CDELT bleibt erhalten (kein Loeschen)
    assert "CDELT1" in header
    assert "CDELT2" in header
    assert header["CDELT1"] == pytest.approx(-0.000138889, abs=1e-12)
    assert header["CDELT2"] == pytest.approx(0.000138889, abs=1e-12)
    # Keine CD-Matrix
    assert "CD1_1" not in header
    assert "CD1_2" not in header
    assert "CD2_1" not in header
    assert "CD2_2" not in header
    assert header["CRVAL1"] == 10.0
    assert header["CRPIX1"] == 8.0
    assert header["CTYPE1"] == "RA---TAN"


def test_copy_wcs_headers_rotation_zero_keeps_cdelt(tmp_path: Path):
    """V1.4-2: rotation_deg=0 -> bisheriges Verhalten: CDELT-Kopie, keine
    CD-Keys (Test-Invariante aus der Task-Vorgabe: rotation=0 -> CDELT-
    Aequivalent)."""
    agent = _make_agent(tmp_path / "out")
    src = _write_2d_frame_with_wcs(tmp_path / "src.fits",
                                   np.zeros((16, 16), dtype=np.float32))
    tgt = _write_2d_frame(tmp_path / "tgt.fits",
                          np.zeros((16, 16), dtype=np.float32))

    agent._copy_wcs_headers(src, tgt, rotation_deg=0.0)

    header = fits.getheader(tgt)
    assert header["CDELT1"] == -0.000138889
    assert header["CDELT2"] == 0.000138889
    assert "CD1_1" not in header
    assert "CD1_2" not in header
