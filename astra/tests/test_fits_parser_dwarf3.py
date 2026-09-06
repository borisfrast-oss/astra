"""Tests for the Dwarf3/M13 dark filename pattern (dark_dwarf3) in fits_parser.

CR-001 v1.1 (P2-Polish): neues Dateinamen-Pattern dark_15s_60g_30C_1.fits.
Metadaten werden aus dem Dateinamen gewonnen, wenn der FITS-Header leer ist
(Dwarf3: Header oft leer).

Abdeckung:
- Standard-Pattern: dark_15s_60g_30C_1.fits -> exptime 15, gain 60, temp 30
- Abweichung 1: andere C-Werte + anderes _N-Suffix -> dark_30s_100g_35C_2.fits
- Abweichung 2: negativer C-Wert, kein _N-Suffix -> dark_5s_120g_-5C.fits
- GR-03 (QG4-Close): scan_directory ignoriert _siril/ + generated/ (Skip-Ordner)
- Punkt 3 (Input-Staging): Staging holt NUR lights/darks/flats/bias in
  den 00_input-Ordner — Fremd-FITS (Siril, App-Stacks im Root) erreichen
  die Pipeline nicht mehr
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.core.fits_parser import (
    OUTPUT_SUBDIRS,
    build_observation_context,
    parse_filename_metadata,
    scan_directory,
)
from astro_process.core.staging import stage_input
from astro_process.models.core import FrameType


def _write_fits(path: Path, data: np.ndarray, header: dict | None = None) -> None:
    """Write a small FITS file with optional header cards."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(np.asarray(data, dtype=np.float32))
    if header:
        for k, v in header.items():
            hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


class TestDarkDwarf3Pattern:
    """dark_dwarf3-Pattern: Dateinamen-Metadaten (Header oft leer)."""

    def test_standard_pattern(self):
        """dark_15s_60g_30C_1.fits -> exptime 15, gain 60, temp 30, stack 1."""
        meta = parse_filename_metadata(Path("dark_15s_60g_30C_1.fits"))
        assert meta["exptime"] == "15"
        assert meta["gain"] == "60"
        assert meta["temp"] == "30"
        assert meta["stack"] == "1"

    def test_different_temp_and_stack_suffix(self):
        """Abweichung: andere C-Werte + _2-Suffix werden erkannt."""
        meta = parse_filename_metadata(Path("dark_30s_100g_35C_2.fits"))
        assert meta["exptime"] == "30"
        assert meta["gain"] == "100"
        assert meta["temp"] == "35"
        assert meta["stack"] == "2"

    def test_negative_temp_without_stack_suffix(self):
        """Abweichung: negativer C-Wert, kein _N-Suffix -> stack ist None."""
        meta = parse_filename_metadata(Path("dark_5s_120g_-5C.fits"))
        assert meta["exptime"] == "5"
        assert meta["gain"] == "120"
        assert meta["temp"] == "-5"
        assert meta["stack"] is None


class TestCompactDarkPattern:
    """Kompaktes {n}s{gain}-Muster (C20-Fall: Dark_30s40.fits, header-los).

    Bug 2026-08-09 (stella): Dark_30s40.fits wurde bisher NICHT geparst
    (exptime/gain None) -> Crash in get_for_calibration. Der Fix ergaenzt
    das Muster NACH dark/dark_dwarf3 (die liefern mehr Metadaten), mit
    dark|bias|flat|offset-Praefix (keine Kollision mit {name}s{name}).
    """

    def test_compact_dark_parses_exptime_gain(self):
        """Dark_30s40.fits -> exptime 30, gain 40."""
        meta = parse_filename_metadata(Path("Dark_30s40.fits"))
        assert meta["exptime"] == "30"
        assert meta["gain"] == "40"

    def test_compact_dark_lowercase_and_other_prefixes(self):
        """Klein geschrieben + bias/flat-Praefixe (konsistent zum dark-Pattern)."""
        meta = parse_filename_metadata(Path("dark_60s40.fits"))
        assert meta["exptime"] == "60"
        assert meta["gain"] == "40"
        meta_bias = parse_filename_metadata(Path("bias_10s50.fits"))
        assert meta_bias["exptime"] == "10"
        assert meta_bias["gain"] == "50"

    def test_library_dark_pattern_unchanged(self):
        """Gegenprobe: Library-Namen weiterhin voll geparst (temp/stack bleiben)."""
        meta = parse_filename_metadata(
            Path("dark_exp_30.000000_gain_40_bin_1_37C_stack_6.fits")
        )
        assert meta["exptime"] == "30.000000"
        assert meta["gain"] == "40"
        assert meta["temp"] == "37"
        assert meta["stack"] == "6"

    def test_dwarf3_pattern_unchanged(self):
        """Gegenprobe: dwarf3-Pattern gewinnt weiterhin (temp/stack nicht verloren)."""
        meta = parse_filename_metadata(Path("dark_15s_60g_30C_1.fits"))
        assert meta["exptime"] == "15"
        assert meta["gain"] == "60"
        assert meta["temp"] == "30"
        assert meta["stack"] == "1"

    def test_name_s_name_without_digits_no_match(self):
        """Gegenprobe: {name}s{name} ohne Ziffern vor/nach 's' matcht nicht."""
        meta = parse_filename_metadata(Path("dark_sample_something.fits"))
        assert meta == {}


class TestScanDirectorySkipsWorkingDirs:
    """Staging (Punkt 3): Fremd-FITS (Siril, App-Stacks) erreichen die
    Pipeline nicht — der Context wird aus dem 00_input-Ordner gebaut."""

    def test_siril_and_root_fits_not_staged(self, tmp_path: Path):
        """`_siril/`-Inhalt und Root-FITS (App-Stacks) werden NICHT gestagt —
        auch wenn ihr Name als Light/Dark erkennbar waere (M27-Fall:
        49/13 statt 47/12-Fehldeutung ist damit ausgeschlossen)."""
        root = tmp_path / "target"
        data = np.zeros((32, 32), dtype=np.float32)
        # Echte Lights (gewollter Scan — via 00_input)
        _write_fits(root / "lights" / "light_0001.fits", data, {"EXPTIME": 60, "GAIN": 40})
        _write_fits(root / "lights" / "light_0002.fits", data, {"EXPTIME": 60, "GAIN": 40})
        # Siril-Produkte + App-Stack im Root (waeren ohne Staging als Light/Dark klassifiziert)
        _write_fits(root / "_siril" / "M27 Hantelnebel_stacked.fit", data)
        _write_fits(root / "_siril" / "darks_30s40_stacked.fit", data)
        _write_fits(root / "_siril" / "_GraXpert.fits", data)
        _write_fits(root / "stacked-16_215935243.fits", data, {"EXPTIME": 780, "GAIN": 40})

        input_dir = stage_input(root, tmp_path / "generated" / "ts")
        context = build_observation_context(input_dir, target_name=root.name)

        lights = context.get_lights()
        assert len(lights.frames) == 2
        assert len(lights.group_by_params()) == 1  # keine 780s40-Gruppe
        assert context.calibration.dark_count == 0
        for f in lights.frames:
            assert "_siril" not in f.path.parts
            assert "00_input" in f.path.parts

    def test_generated_and_output_subdirs_not_scanned(self, tmp_path: Path):
        """Pipeline-Output-Ordner bleiben geskippt — auch Master-Darks:
        neue Struktur 00_input/master UND alte 00_masters (Backward-Compat)."""
        root = tmp_path / "target"
        data = np.zeros((32, 32), dtype=np.float32)
        _write_fits(root / "lights" / "light_0001.fits", data)
        _write_fits(root / "generated" / "20260804-210455" / "stacked.fits", data)
        _write_fits(root / "00_input" / "master" / "master_dark_30s40.fits", data)
        _write_fits(root / "00_masters" / "master_dark_30s40.fits", data)

        result = scan_directory(root, recursive=True)

        assert len(result[FrameType.LIGHT].frames) == 1
        assert len(result[FrameType.DARK].frames) == 0

    def test_master_subdir_not_scanned_when_root_is_00_input(self, tmp_path: Path):
        """Pipeline-Szenario: Scan-Root ist 00_input — master/ wird NICHT
        als Darks klassifiziert (echter Guard fuer OUTPUT_SUBDIRS['master'])."""
        input_dir = tmp_path / "00_input"
        data = np.zeros((32, 32), dtype=np.float32)
        _write_fits(input_dir / "lights" / "light_0001.fits", data)
        _write_fits(input_dir / "master" / "master_dark_30s40.fits", data)
        result = scan_directory(input_dir, recursive=True)
        assert len(result[FrameType.LIGHT].frames) == 1
        assert len(result[FrameType.DARK].frames) == 0

    def test_siril_is_in_output_subdirs(self):
        """`_siril` ist Bestandteil der Skip-Ordner-Liste (GR-03)."""
        assert "_siril" in OUTPUT_SUBDIRS
