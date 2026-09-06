"""Tests fuer Input-Staging (Auftrag 2026-08-05, Punkt 3).

Die Pipeline liest NUR aus `generated/<ts>/00_input` — der Target-Root wird
ausschliesslich vom Staging-Schritt gelesen (explizite konventionelle
Input-Ordner lights/darks/flats/bias). Fremd-FITS im Root (App-Stacks wie
`stacked-16_*.fits`) und in Fremd-Ordnern (_siril, Thumbnail, cache)
tauchen NICHT im 00_input-Ordner auf und koennen daher nicht mehr als
Light/Dark missdeutet werden (M3: keine 780s40-Gruppe mehr).

Teststrategie: structlog geht NICHT durch stdlib-Logging — das Modul-Logger-
Objekt wird durch einen Recorder ersetzt (Muster test_registration_w9.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

# ── Ensure src on the path ────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import astro_process.agents.discovery as discovery  # noqa: E402
import astro_process.core.staging as staging  # noqa: E402
from astro_process.core.fits_parser import build_observation_context  # noqa: E402
from astro_process.core.staging import (  # noqa: E402
    STAGED_INPUT_SUBDIRS,
    stage_input,
)


def _write_fits(
    path: Path,
    exptime: float = 60.0,
    gain: int = 40,
    obj: str = "M 3",
) -> None:
    """Write a small FITS file with EXPTIME/GAIN/OBJECT header cards."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(np.zeros((16, 16), dtype=np.float32))
    hdu.header["EXPTIME"] = exptime
    hdu.header["GAIN"] = gain
    hdu.header["OBJECT"] = obj
    hdu.header["CCD-TEMP"] = -10
    hdu.writeto(path, overwrite=True)


class _LogRecorder:
    """Ersetzt das structlog-Modul-Logger-Objekt und sammelt events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def error(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    @property
    def names(self) -> list[str]:
        return [e for e, _ in self.events]

    def events_named(self, name: str) -> list[tuple[str, dict]]:
        return [e for e in self.events if e[0] == name]


@pytest.fixture
def log_recorder(monkeypatch: pytest.MonkeyPatch) -> _LogRecorder:
    rec = _LogRecorder()
    monkeypatch.setattr(staging, "logger", rec)
    return rec


@pytest.fixture
def discovery_recorder(monkeypatch: pytest.MonkeyPatch) -> _LogRecorder:
    rec = _LogRecorder()
    monkeypatch.setattr(discovery, "logger", rec)
    return rec


# ═══════════════════════════════════════════════════════════════════
# Section: Staging flow (lights darks flats bias)
# ═══════════════════════════════════════════════════════════════════


def test_stages_only_conventional_input_dirs(tmp_path):
    """Staging kopiert NUR lights/darks/flats/bias — Root-FITS und
    Fremd-Ordner (_siril, Thumbnail, cache) tauchen NICHT im 00_input-Ordner
    auf (waeren sonst als Light/Dark missdeutet)."""
    root = tmp_path / "target"
    _write_fits(root / "lights" / "light_0001.fits")
    _write_fits(root / "darks" / "dark_0001.fits", exptime=30, obj="DARK")
    _write_fits(root / "flats" / "flat_0001.fits", exptime=1, obj="FLAT")
    _write_fits(root / "bias" / "bias_0001.fits", exptime=0, obj="BIAS")
    # Fremd-Inhalt (ohne Staging als Light/Dark klassifiziert)
    _write_fits(root / "stacked-16_215935243.fits", exptime=780)
    _write_fits(root / "_siril" / "M27 Hantelnebel_stacked.fit", exptime=60)
    _write_fits(root / "_siril" / "darks_30s40_stacked.fit", exptime=30, obj="DARK")
    _write_fits(root / "Thumbnail" / "thumb.fits", exptime=5)
    _write_fits(root / "cache" / "cache_1.fits", exptime=5)

    input_dir = stage_input(root, tmp_path / "generated" / "20260805-120000")

    assert (input_dir / "lights" / "light_0001.fits").is_file()
    assert (input_dir / "darks" / "dark_0001.fits").is_file()
    assert (input_dir / "flats" / "flat_0001.fits").is_file()
    assert (input_dir / "bias" / "bias_0001.fits").is_file()
    # Nichts anderes darf in 00_input landen
    staged = sorted(p.relative_to(input_dir) for p in input_dir.rglob("*.fit*"))
    assert staged == [
        Path("bias/bias_0001.fits"),
        Path("darks/dark_0001.fits"),
        Path("flats/flat_0001.fits"),
        Path("lights/light_0001.fits"),
    ]


def test_build_observation_context_from_staged_input(tmp_path):
    """M3-Szenario: 13 Lights (60s40) + App-Stack im Root (780s40) -> nach
    Staging enthaelt der Context NUR die gestagten Lights, keine 780s40."""
    root = tmp_path / "M3 Kugelsternhaufen"
    for i in range(13):
        _write_fits(root / "lights" / f"light_{i:04d}.fits", exptime=60, gain=40, obj="M 3")
    # Dwarf3-App-Stack im Root (waere ohne Staging als Light 780s40 missdeutet)
    _write_fits(root / "stacked-16_215935243.fits", exptime=780, gain=40, obj="M 3")

    input_dir = stage_input(root, tmp_path / "generated" / "20260805-120000")
    context = build_observation_context(input_dir, target_name=root.name)

    assert context.total_light_frames == 13
    assert context.target.name == "M 3"
    exptimes = {f.header.exptime for f in context.get_lights().frames}
    assert exptimes == {60.0}
    assert all("00_input" in f.path.parts for f in context.get_lights().frames)


def test_missing_lights_warns_but_stages_rest(tmp_path, log_recorder):
    """lights-Ordner fehlt -> Warning `stage.input.missing_lights`; darks
    wird trotzdem gestagt, 00_input existiert (Abbruch passiert wie bisher
    in Discovery mit 'No light frames found')."""
    root = tmp_path / "target"
    _write_fits(root / "darks" / "dark_0001.fits", exptime=30, obj="DARK")

    input_dir = stage_input(root, tmp_path / "generated" / "ts")

    assert input_dir.exists()
    assert (input_dir / "darks" / "dark_0001.fits").is_file()
    missing = log_recorder.events_named("stage.input.missing_lights")
    assert len(missing) == 1
    assert str(missing[0][1]["source"]) == str(root / "lights")


def test_missing_darks_flats_bias_warn_but_continue(tmp_path, log_recorder):
    """darks/flats/bias fehlen -> Warnungen, lights laeuft normal weiter."""
    root = tmp_path / "target"
    _write_fits(root / "lights" / "light_0001.fits")

    input_dir = stage_input(root, tmp_path / "generated" / "ts")

    assert (input_dir / "lights" / "light_0001.fits").is_file()
    for name in ("missing_darks", "missing_flats", "missing_bias"):
        assert len(log_recorder.events_named(f"stage.input.{name}")) == 1
    assert "stage.input.missing_lights" not in log_recorder.names


def test_empty_darks_flats_bias_not_staged(tmp_path, log_recorder):
    """Leere darks/flats/bias-Ordner (0 FITS) -> NICHT gestagt (kein
    Warning, kein Kopieren); lights mit FITS -> normal gestagt. 00_input
    enthaelt nur lights/ (Input-Struktur-Konsolidierung)."""
    root = tmp_path / "target"
    _write_fits(root / "lights" / "light_0001.fits")
    (root / "darks").mkdir(parents=True, exist_ok=True)
    (root / "flats").mkdir(parents=True, exist_ok=True)
    (root / "bias").mkdir(parents=True, exist_ok=True)

    input_dir = stage_input(root, tmp_path / "generated" / "ts")

    assert (input_dir / "lights" / "light_0001.fits").is_file()
    # Leere Ordner wurden NICHT kopiert -> 00_input enthaelt nur lights/
    assert not (input_dir / "darks").exists()
    assert not (input_dir / "flats").exists()
    assert not (input_dir / "bias").exists()
    # Ordner existieren (nur leer) -> KEINE missing_-Warnungen
    for name in ("missing_darks", "missing_flats", "missing_bias"):
        assert len(log_recorder.events_named(f"stage.input.{name}")) == 0
    # Zaehlungen im complete-Log bleiben 0 (wie bei fehlenden Ordnern)
    complete = log_recorder.events_named("stage.input.complete")
    assert len(complete) == 1
    kw = complete[0][1]
    assert kw["lights"] == 1
    assert kw["darks"] == 0
    assert kw["flats"] == 0
    assert kw["bias"] == 0


def test_complete_log_counts_and_paths(tmp_path, log_recorder):
    """`stage.input.complete` mit Anzahl je Typ + Quell-/Zielpfad."""
    root = tmp_path / "target"
    _write_fits(root / "lights" / "a.fits")
    _write_fits(root / "lights" / "b.fits")
    _write_fits(root / "darks" / "d.fits", exptime=30, obj="DARK")

    input_dir = stage_input(root, tmp_path / "generated" / "ts")

    complete = log_recorder.events_named("stage.input.complete")
    assert len(complete) == 1
    kw = complete[0][1]
    assert kw["lights"] == 2
    assert kw["darks"] == 1
    assert kw["flats"] == 0
    assert kw["bias"] == 0
    assert str(kw["source"]) == str(root)
    assert str(kw["dest"]) == str(input_dir)


# ═══════════════════════════════════════════════════════════════════
# Section: Discovery Integration (00_input)
# V1.6-7:shotsInfo aus Pipeline entfernt — nur Context aus 00_input.
# ═══════════════════════════════════════════════════════════════════


def test_run_with_shots_root_uses_input(
    tmp_path, log_recorder, discovery_recorder
):
    """DiscoveryAgent.run(input_dir, shots_root=root): Context aus 00_input.
    V1.6-7:shotsInfo ist kein Pipeline-Step mehr —shots_root wird ignoriert."""
    root = tmp_path / "target"
    _write_fits(root / "lights" / "light_0001.fits", exptime=60, gain=40, obj="M 3")
    (root / "shotsInfo.json").write_text(
        json.dumps({"eq": True, "exp": "60", "gain": 40,
                    "shotsTaken": 13, "shotsToTake": 30, "target": "M 3"}),
        encoding="utf-8",
    )

    input_dir = stage_input(root, tmp_path / "generated" / "ts")
    result = discovery.DiscoveryAgent(config=None).run(input_dir, shots_root=root)

    # Context aus 00_input
    assert result.context.total_light_frames == 1
    assert all("00_input" in str(f.path) for f in result.context.get_lights().frames)
    # V1.6-7:shotsInfo wird nicht mehr in der Pipeline gelesen
    found = discovery_recorder.events_named("discovery.shotsinfo.found")
    assert len(found) == 0


def test_staged_input_subdirs_are_public():
    """Die gestagten Ordner sind exakt die konventionellen vier."""
    assert STAGED_INPUT_SUBDIRS == ("lights", "darks", "flats", "bias")
