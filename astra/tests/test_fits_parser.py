"""Tests for fits_parser.normalize_value and DEF-003 (2026-08-14).

DEF-003: `normalize_value` entfernte Einheiten-Suffixe auch aus String-Werten
("Duo-Band" -> "Duo-", "Astro" -> ""), wodurch compute_group_hash und
_collect_light_filters verfaelschte Filterwerte sahen (Gruppenname
`120s40_Duo-` statt `120s40_Duo-Band`).

Fix: Der Einheiten-Strip-Regex wird NUR noch auf numerische Zieltypen
(float/int) angewendet. String-Zieltypen (filter_name, OBJECT, ...) bleiben
unangetastet; numerische Werte mit Einheiten-Suffix ("30s", "-5C") werden
weiterhin korrekt konvertiert (Fallback-Semantik unveraendert).

Abdeckung:
- String-Werte: "Duo-Band"/"Astro" bleiben unveraendert (DEF-003-Kern).
- OBJECT-Nebeneffekt: "Veil Nebula" bleibt unangetastet (vorher "Veil Nebul").
- H6-Alt-Daten: "Duo-" bleibt "Duo-" (Suffix-Semantik).
- Whitespace-Strip fuer Strings bleibt erhalten.
- Numerische Einheiten-Suffixe werden weiterhin gestrippt (float/int).
- Gruppen-Hash behaelt den vollen Filter-Namen (120s40_Duo-Band, 30s40_Astro).
- End-to-End: FILTER-Header erreicht FitsHeader.filter_name unverfaelscht.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.core.fits_parser import (  # noqa: E402
    normalize_value,
    parse_fits_header,
)
from astro_process.models.core import compute_group_hash  # noqa: E402


class TestNormalizeValueDef003:
    """DEF-003: String-Werte duerfen nicht als Einheiten-Suffix verkuerzt werden."""

    def test_filter_name_duo_band_preserved(self):
        """'Duo-Band' bleibt 'Duo-Band' (vorher: 'Duo-')."""
        assert normalize_value("Duo-Band", str) == "Duo-Band"

    def test_filter_name_astro_preserved(self):
        """'Astro' bleibt 'Astro' (vorher: '')."""
        assert normalize_value("Astro", str) == "Astro"

    def test_whitespace_still_stripped_for_strings(self):
        """Whitespace-Strip bleibt fuer Strings erhalten (auch ohne Einheiten-Strip)."""
        assert normalize_value("  Duo-Band  ", str) == "Duo-Band"

    def test_numeric_unit_suffix_still_stripped_for_float(self):
        """Fallback-Semantik: Einheiten-Suffixe bei float bleiben gestrippt."""
        assert normalize_value("30s", float) == 30.0
        assert normalize_value("-5C", float) == -5.0
        assert normalize_value("15.5s", float) == 15.5

    def test_numeric_unit_suffix_still_stripped_for_int(self):
        """Fallback-Semantik: Einheiten-Suffixe bei int bleiben gestrippt."""
        assert normalize_value("60s", int) == 60

    def test_plain_number_float(self):
        """Plain number wird weiterhin konvertiert."""
        assert normalize_value("30", float) == 30.0

    def test_object_name_preserved(self):
        """OBJECT-Wert 'Veil Nebula' bleibt unangetastet (vorher 'Veil Nebul')."""
        assert normalize_value("Veil Nebula", str) == "Veil Nebula"

    def test_legacy_duo_suffix_preserved(self):
        """H6-Alt-Daten: 'Duo-' bleibt 'Duo-' (Suffix-Semantik auf Parser-Ebene)."""
        assert normalize_value("Duo-", str) == "Duo-"


class TestComputeGroupHashDef003:
    """DEF-003: Gruppen-Hashes behalten den vollen Filter-Namen."""

    def test_group_hash_duo_band(self):
        """(120, 40, 'Duo-Band') -> '120s40_Duo-Band' (vorher '120s40_Duo-')."""
        assert compute_group_hash(120, 40, "Duo-Band") == "120s40_Duo-Band"

    def test_group_hash_astro(self):
        """(30, 40, 'Astro') -> '30s40_Astro' (vorher '30s40')."""
        assert compute_group_hash(30, 40, "Astro") == "30s40_Astro"


class TestParseFitsHeaderDef003:
    """DEF-003 End-to-End: FILTER-Header erreicht FitsHeader unverfaelscht."""

    def test_filter_header_preserved(self, tmp_path: Path):
        """FILTER='Duo-Band' bleibt 'Duo-Band'; numerische Werte weiter ok."""
        path = tmp_path / "light.fits"
        hdu = fits.PrimaryHDU(np.zeros((16, 16), dtype=np.float32))
        hdu.header["FILTER"] = "Duo-Band"
        hdu.header["EXPTIME"] = 120
        hdu.header["GAIN"] = 40
        hdu.writeto(path, overwrite=True)

        header = parse_fits_header(path)
        assert header.filter_name == "Duo-Band"
        assert header.exptime == 120.0
        assert header.gain == 40
