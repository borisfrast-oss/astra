"""Tests fuer V1.3-6 eq-Flag-Quelle (Auftrag 2026-08-09).

V1.6-7: shotsInfo aus Pipeline entfernt (Device-Independence).
Neue Prioritaets-Kette: EQMODE-Header → AZ-Fallback (≤60s) → unknown.

Deckt ab (Spec v13-6-eq-flag-quelle.md):
- EQ-A1: EQMODE als zentrale Konstante (Header-Export + Discovery referenzieren
  dieselbe Quelle; AC-EQ-A1).
- EQ-B1/B2: `parse_fits_header` liest EQMODE best effort (1->1, 0->0,
  fehlend/unlesbar -> None, nie ein Crash).
- EQ-C1/C4: `resolve_eq_flag`-Prioritaets-Kette
  (EQMODE > az_fallback > unknown) — V1.6-7: shotsInfo entfernt.
- EQ-D1/D2/D4/D5: az_fallback nur bei exptime <= 60 s; Header-EXPTIME vor
  Dateinamen-Parsing; unbestimmbar -> unknown.
- EQ-E1/E2: KEINE EXPTIME-Heuristik (EQMODE=1 + 30 s bleibt EQ).
- End-to-End: DiscoveryAgent.run auf Target mit Light-Frames -> eq/eq_source
  im DiscoveryResult (AC-EQ-B3).

Teststrategie: structlog geht NICHT durch stdlib-Logging — das Modul-Logger-
Objekt wird durch einen Recorder ersetzt (Muster test_discovery_shotsinfo.py).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# ── Ensure src on the path ────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import astro_process.agents.discovery as discovery  # noqa: E402
from astro_process.agents.discovery import (  # noqa: E402
    DiscoveryAgent,
    _resolve_exptime_from_frame,
    resolve_eq_flag,
)
from astro_process.core.fits_parser import (  # noqa: E402
    EQMODE_KEY,
    HEADER_ALIASES,
    parse_fits_header,
)
from astro_process.core.export import EXPORT_LIGHT_HEADER_KEYS  # noqa: E402


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
    monkeypatch.setattr(discovery, "logger", rec)
    return rec


def _write_light_fits(
    tmp_path: Path, name: str, *, eqmode=None, exptime=None
) -> Path:
    """Schreibt einen minimalen Light-FITS (16x16) mit optionalem Header."""
    from astropy.io import fits  # noqa: PLC0415 - lokal fuer FITS-Erzeugung
    import numpy as np  # noqa: PLC0415

    hdr = fits.Header()
    # V1.6-1 (SSOT-A): Mandatory fields for light frames
    hdr["EXPTIME"] = exptime if exptime is not None else 30.0
    hdr["GAIN"] = 40
    hdr["OBJECT"] = "M 27"
    hdr["CCD-TEMP"] = -10
    if eqmode is not None:
        hdr["EQMODE"] = eqmode
    data = np.zeros((16, 16), dtype=np.float32)
    path = tmp_path / name
    fits.PrimaryHDU(data=data, header=hdr).writeto(path, overwrite=True)
    return path


# ═══════════════════════════════════════════════════════════════════
# Section: EQ-A1 — zentrale Konstante
# ═══════════════════════════════════════════════════════════════════


def test_eqmode_central_constant_aliases_and_export_agree():
    """EQMODE_KEY ist die eine Quelle: Alias-Tabelle und Export-Header-Keys
    referenzieren dieselbe Konstante (AC-EQ-A1)."""
    assert HEADER_ALIASES["eq_mode"] == [EQMODE_KEY]
    assert EQMODE_KEY in EXPORT_LIGHT_HEADER_KEYS


# ═══════════════════════════════════════════════════════════════════
# Section: EQ-B1/B2 — Header-Parsing best effort
# ═══════════════════════════════════════════════════════════════════


def test_parse_fits_header_eqmode_1(tmp_path):
    """EQMODE=1 -> eq_mode == 1."""
    path = _write_light_fits(tmp_path, "light_0001.fits", eqmode=1)
    header = parse_fits_header(path)
    assert header.eq_mode == 1


def test_parse_fits_header_eqmode_0(tmp_path):
    """EQMODE=0 -> eq_mode == 0 (Rohwert bleibt, Mapping in resolve_eq_flag)."""
    path = _write_light_fits(tmp_path, "light_0001.fits", eqmode=0)
    header = parse_fits_header(path)
    assert header.eq_mode == 0


def test_parse_fits_header_eqmode_missing(tmp_path):
    """Kein EQMODE im Header -> eq_mode is None (kein Crash)."""
    path = _write_light_fits(tmp_path, "light_0001.fits")
    header = parse_fits_header(path)
    assert header.eq_mode is None


def test_parse_fits_header_eqmode_unreadable(tmp_path):
    """EQMODE unlesbar (z.B. 'AZ') -> None, kein Crash (AC-EQ-B2)."""
    from astropy.io import fits  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    hdr = fits.Header()
    hdr["EQMODE"] = "AZ"
    data = np.zeros((16, 16), dtype=np.float32)
    path = tmp_path / "light_0001.fits"
    fits.PrimaryHDU(data=data, header=hdr).writeto(path, overwrite=True)

    header = parse_fits_header(path)
    assert header.eq_mode is None


# ═══════════════════════════════════════════════════════════════════
# Section: EQ-C1/C4 — Prioritaets-Kette (Unit) — V1.6-7: ohne shotsInfo
# ═══════════════════════════════════════════════════════════════════


def test_resolve_eq_flag_eqmode_1_is_eq():
    """EQMODE=1 -> EQ (True, 'eqmode')."""
    assert resolve_eq_flag(1, None) == (True, "eqmode")


def test_resolve_eq_flag_eqmode_0_is_az():
    """EQMODE=0 -> AZ (False, 'eqmode')."""
    assert resolve_eq_flag(0, None) == (False, "eqmode")


def test_resolve_eq_flag_az_fallback_only_when_eqmode_missing():
    """Nur wenn kein EQMODE: az_fallback bei exptime <= 60 (AC-EQ-D1)."""
    assert resolve_eq_flag(None, 30.0) == (False, "az_fallback")
    assert resolve_eq_flag(None, 60.0) == (False, "az_fallback")


def test_resolve_eq_flag_exptime_gt_60_unknown():
    """exptime > 60 s -> unbekannt (AC-EQ-D2), kein az_fallback."""
    assert resolve_eq_flag(None, 60.1) == (None, "unknown")
    assert resolve_eq_flag(None, 120.0) == (None, "unknown")


def test_resolve_eq_flag_exptime_unbestimmbar_unknown():
    """Belichtung unbestimmbar (None) -> unbekannt (AC-EQ-D4)."""
    assert resolve_eq_flag(None, None) == (None, "unknown")


def test_resolve_eq_flag_no_exptime_heuristic_eqmode_1():
    """EQMODE=1 + 30 s -> EQ (AC-EQ-E1): KEINE EXPTIME-Heuristik,
    EQMODE gewinnt gegen den az_fallback."""
    assert resolve_eq_flag(1, 30.0) == (True, "eqmode")


def test_resolve_eq_flag_no_exptime_heuristic_eqmode_0():
    """EQMODE=0 + 30 s -> AZ (AC-EQ-E2): M27-Problemfall bleibt AZ, obwohl
    die Belichtung im az_fallback-Bereich liegt."""
    assert resolve_eq_flag(0, 30.0) == (False, "eqmode")


# ═══════════════════════════════════════════════════════════════════
# Section: EQ-D5 — Belichtungs-Precedence (Header vor Dateiname)
# ═══════════════════════════════════════════════════════════════════


def test_resolve_exptime_from_frame_header_wins(tmp_path):
    """Header-EXPTIME gewinnt gegen Dateinamen-Parsing (AC-EQ-D5)."""
    path = _write_light_fits(tmp_path, "light_30s.fits", exptime=120.0)
    frame = SimpleNamespace(
        header=SimpleNamespace(exptime=120.0, eq_mode=None),
        path=path,
    )
    assert _resolve_exptime_from_frame(frame) == 120.0


def test_resolve_exptime_from_frame_header_missing_uses_filename(tmp_path):
    """Ohne Header-EXPTIME -> Dateinamen-Parsing als Fallback (AC-EQ-D5).
    Nutzt das echte Astro-light-Schema (M 3_30s60_Astro_..._33C.fits), das
    `parse_filename_metadata` aufloesen kann."""
    path = _write_light_fits(
        tmp_path, "M 3_30s60_Astro_20260717-231509939_33C.fits"
    )
    frame = SimpleNamespace(header=SimpleNamespace(exptime=None, eq_mode=None), path=path)
    assert _resolve_exptime_from_frame(frame) == 30.0


def test_resolve_exptime_from_frame_unbestimmbar(tmp_path):
    """Weder Header noch Dateiname -> None (AC-EQ-D4, kein Crash)."""
    path = _write_light_fits(tmp_path, "light_0001.fits")
    frame = SimpleNamespace(header=SimpleNamespace(exptime=None, eq_mode=None), path=path)
    assert _resolve_exptime_from_frame(frame) is None


# ═══════════════════════════════════════════════════════════════════
# Section: End-to-End — eq/eq_source im DiscoveryResult (AC-EQ-B3)
# V1.6-7: shotsInfo entfernt aus Pipeline — Priority-Chain:
# EQMODE-Header → AZ-Fallback (≤60s) → unknown
# ═══════════════════════════════════════════════════════════════════


def test_discovery_run_eq_from_header_eqmode_1(tmp_path):
    """Light-Frame mit EQMODE=1 -> eq=True, source eqmode."""
    _write_light_fits(tmp_path, "light_0001.fits", eqmode=1)

    result = DiscoveryAgent(config=None).run(tmp_path)

    assert result is not None
    assert result.eq is True
    assert result.eq_source == "eqmode"


def test_discovery_run_eq_from_header_eqmode_0(tmp_path):
    """Light-Frame mit EQMODE=0 -> eq=False, source eqmode."""
    _write_light_fits(tmp_path, "light_0001.fits", eqmode=0)

    result = DiscoveryAgent(config=None).run(tmp_path)

    assert result is not None
    assert result.eq is False
    assert result.eq_source == "eqmode"


def test_discovery_run_az_fallback_from_exptime(tmp_path):
    """Kein EQMODE, EXPTIME=30 -> az_fallback (EQ-D1)."""
    _write_light_fits(tmp_path, "light_0001.fits", exptime=30.0)

    result = DiscoveryAgent(config=None).run(tmp_path)

    assert result is not None
    assert result.eq is False
    assert result.eq_source == "az_fallback"


def test_discovery_run_unknown_without_sources(tmp_path):
    """Kein EQMODE, EXPTIME=120 -> unbekannt (EQ-D2)."""
    _write_light_fits(tmp_path, "light_0001.fits", exptime=120.0)

    result = DiscoveryAgent(config=None).run(tmp_path)

    assert result is not None
    assert result.eq is None
    assert result.eq_source == "unknown"
