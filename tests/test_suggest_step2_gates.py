"""Gate-Tests V1.12-STEP2 T5 — 4 Tests (AC-T5) + Budget 1:1.

Proposal: orion/_work/stella/2026-09-15-proposal-saubere-pipeline-ohne-cache-kuration.md
Backlog: knowledge-base/projects/astra/backlog.md V1.12-STEP2

- (1) Alias B144 offline Hit (Header leer, SIMBAD down, Cache Aliase[] Hit)
- (2) live Typ→Preset via classify_and_cite + grep M31==0 (kein Hardcode-Baum)
- (3) triple miss Exit 2 (kein SIMBAD, kein Header OBJECT, kein Cache)
- (4) Ghost-Guard lights\ nur bei TARGET ohne Header (Header-Pfad umgeht Guard)

Budget 1:1 — Legacy test_v19_suggest mit Astra-Preset/Größe/Handbook bleibt als Mock
tolerant, aber echter Preset kommt live via Typ (AC-T1, ray A2)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import yaml
from astropy.io import fits
from click.testing import CliRunner

from astro_process.cli import cli
from astro_process.config.loader import DEFAULT_CONFIG
from astro_process.core import suggest as suggest_mod


def _offline_simbad(*_args, **_kwargs):
    return None


def _make_astra_root(base: Path, *names: str) -> Path:
    root = base / "AstraRoot"
    for n in names:
        (root / n / "lights").mkdir(parents=True, exist_ok=True)
    return root


def _write_config(tmp_path: Path, data_root: Path) -> Path:
    data = yaml.safe_load(DEFAULT_CONFIG)
    data["data_root"] = str(data_root)
    # Do NOT set suggest.target_cache_path — use baked default (importlib.resources)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return cfg


# ── (1) Alias B144 offline Hit ────────────────────────────────────────

class TestGateAliasB144OfflineHit:
    def test_b144_offline_hit_via_baked_cache(self, tmp_path):
        # baked astra/data/target-cache.json contains Barnard 144 with Katalognummer B144
        # and Aliase includes B144. Offline + no header -> cache hit.
        astra_root = _make_astra_root(tmp_path, "B144")
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock:
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "B144"])
            mock.assert_not_called()  # cache hit, no SIMBAD
        assert result.exit_code == 0, result.output
        assert "Barnard 144" in result.output or "B144" in result.output
        assert "nebula_standard" in result.output  # Typ dark nebula -> nebula_standard live
        assert "Source: cache hit" in result.output
        assert "astra/data/target-cache.json" in result.output or "target-cache.json" in result.output
        # file written to default location
        out = astra_root / "B144" / "suggested.yaml"
        assert out.is_file()
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert data["preset"] == "nebula_standard"
        assert data["source"] == "cache"


# ── (2) live Typ→Preset via classify_and_cite + grep M31==0 ──────────

class TestGateLiveTypToPreset:
    def test_m31_galaxy_standard_via_typ_not_hardcode(self, tmp_path):
        astra_root = _make_astra_root(tmp_path, "M31")
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "M31"])
        assert result.exit_code == 0, result.output
        assert "galaxy_standard" in result.output
        # handbook citation comes from classify_and_cite, not cache field
        assert "Handbook 22" in result.output

    def test_no_hardcoded_m31_galaxy_standard_tree(self):
        src_dir = Path(__file__).resolve().parent.parent / "src" / "astro_process"
        pattern = re.compile(r"M31.*galaxy_standard")
        hits = []
        for py_file in src_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{py_file}:{lineno}: {line}")
        assert not hits, "Hardcoded M31->galaxy_standard tree found:\n" + "\n".join(hits)

    def test_suggest_py_has_no_astra_preset_field(self):
        suggest_path = Path(__file__).resolve().parent.parent / "src" / "astro_process" / "core" / "suggest.py"
        text = suggest_path.read_text(encoding="utf-8")
        # After T1, suggest.py must not read Astra-Preset field (ray A2)
        assert "Astra-Preset" not in text, "Astra-Preset still read in suggest.py (ray A2)"
        # Handbook field should also not be read as cache: fallback
        # (allow citation strings, but not entry.get("Handbook"))
        assert 'entry.get("Handbook")' not in text, "Handbook still read from cache (AC-T1)"

    def test_baked_json_has_only_minimal_keys(self):
        # AC-T1: astra/data/target-cache.json only has minimal keys (Amendment 0.2d: english)
        p = Path(__file__).resolve().parent.parent / "data" / "target-cache.json"
        assert p.is_file(), "baked cache missing"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(data, list) and len(data) >= 30
        allowed = {"catalog_number", "simbad_name", "type", "ra", "dec", "aliases"}
        for entry in data:
            assert set(entry.keys()) <= allowed, f"Leak keys in {entry}: {set(entry.keys()) - allowed}"
        # Ensure removed fields are gone (english only, no German keys)
        for entry in data:
            assert "Handbook" not in entry
            assert "Astra-Preset" not in entry
            assert "Sternbild" not in entry
            assert "Katalognummer" not in entry
            assert "SIMBAD-Name" not in entry
            assert "Typ" not in entry
        # Ensure type slugs are english, no German values like "Stern (K0IIIa Riese)"
        allowed_types = {"star", "open_cluster", "galaxy", "globular", "dark_nebula", "nebula", "planetary", "snr", "moon", "unknown"}
        for entry in data:
            assert entry.get("type") in allowed_types, f"German or unknown type leak: {entry}"
            assert "Stern (" not in str(entry.get("type", ""))


# ── (3) triple miss Exit 2 ────────────────────────────────────────────

class TestGateTripleMissExit2:
    def test_unknown_target_offline_triple_miss_exit2(self, tmp_path):
        astra_root = tmp_path / "AstraRoot"
        astra_root.mkdir(parents=True, exist_ok=True)
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock:
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "NGC 9999"])
            mock.assert_called_once()
        assert result.exit_code == 2, result.output
        assert "suggest.simbad_unavailable" in result.output
        assert "Traceback" not in result.output
        # no file written
        assert not (astra_root / "NGC 9999" / "suggested.yaml").exists()

    def test_triple_miss_no_header_and_no_cache(self, tmp_path):
        # Same but via process --from-suggested triple miss? Suggest is primary.
        # Ensure that unknown target without header and without lights also triple miss
        astra_root = _make_astra_root(tmp_path, "UnknownTarget")
        # Remove lights to test ghost-guard not masking triple miss
        # For suggest, triple miss should still be simbad_unavailable, not ghost
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "CompletelyUnknownXYZ"])
        assert result.exit_code == 2
        assert "suggest.simbad_unavailable" in result.output


# ── (4) Ghost-Guard lights\ nur bei TARGET ohne Header ────────────────

class TestGateGhostGuard:
    def test_ghost_guard_only_without_header(self, tmp_path):
        # TARGET without header + without lights/ -> should be blocked (ghost guard)
        # We use a known cache target "M31" but without lights folder -> ghost guard should fire
        astra_root = tmp_path / "AstraRoot"
        astra_root.mkdir(parents=True, exist_ok=True)
        # Do NOT create M31/lights
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "M31"])
        # Ghost guard should trigger: Target directory is missing
        assert result.exit_code == 2, result.output
        assert "Target directory is missing" in result.output

    def test_ghost_guard_bypassed_with_header(self, tmp_path):
        # Same TARGET without lights, but WITH header OBJECT=M31 -> should bypass guard and hit
        astra_root = tmp_path / "AstraRoot"
        astra_root.mkdir(parents=True, exist_ok=True)
        # No M31 folder, but header will win
        cfg = _write_config(tmp_path, astra_root)
        # Create a dummy FITS with OBJECT=M31
        fits_path = tmp_path / "m31.fits"
        hdu = fits.PrimaryHDU(np.zeros((4, 4), dtype=np.float32))
        hdu.header["OBJECT"] = "M31"
        hdu.header["FILTER"] = "Astro"
        hdu.header["TELESCOP"] = "DWARF MINI"
        hdu.header["EXPTIME"] = 60.0
        hdu.writeto(fits_path, overwrite=True)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock:
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "--header", str(fits_path)])
            # Header M31 hits cache, so no SIMBAD
            mock.assert_not_called()
        # Should succeed even though no lights folder, because header bypasses guard
        # However write_suggested_file still needs to write to default path based on header OBJECT=M31
        # That path would be astra_root/M31/suggested.yaml -> but M31 folder doesn't exist -> ghost guard
        # For header case, we bypass guard, so it should try to write and currently write_suggested_file
        # with header_path set will bypass its own guard and create parent dirs.
        # So we expect exit 0, and file created (mkdir parents).
        assert result.exit_code == 0, result.output
        assert "galaxy_standard" in result.output
        # file should have been created despite no prior lights? With header guard bypass, it will create.
        # Our write_suggested_file with header_path bypasses check and does mkdir parents, so file exists
        out = astra_root / "M31" / "suggested.yaml"
        assert out.is_file(), "Header bypass should have created file"

    def test_write_suggested_file_direct_ghost_guard(self, tmp_path):
        # Direct test of write_suggested_file guard
        from astro_process.core.suggest import write_suggested_file, SuggestInputError

        data = {
            "version": 1,
            "target": "M31",
            "preset": "galaxy_standard",
            "registration": {"method": "fft", "max_rotation_deg": 2},
            "debayer": {"method": "superpixel"},
            "pcc": {"enabled": True},
            "source": "cache",
        }
        # Without header, missing lights -> should raise
        out = tmp_path / "NoLights" / "suggested.yaml"
        with pytest.raises(SuggestInputError, match="Target directory missing"):
            write_suggested_file(data, out, header_path=None)
        # With header, should NOT raise (bypass)
        write_suggested_file(data, out, header_path=Path("dummy.fits"))
        assert out.is_file()


# ── C13-Alias-Drift: B144->Barnard144 / C34->NGC6960 offline ohne Header (Ghost Guard) ──

class TestGateAliasDriftGhostGuard:
    """C13-Major1: Alias-Drift nur synthetisch getestet — Negativ-Test B144/Barnard144 + C34/NGC6960
    offline ohne Header, Ghost Guard (lights\\ muss existieren), beweist Alias-Handling.

    Vor Fix: B144->Barnard144 compact (ohne Leerzeichen) würde bei fehlendem Header
    wegen _normalize vs _normalize_compact Drift nicht hitten bzw. Ghost blocken;
    Test erweitert test_suggest_step2_gates um r/b Echt-Beleg (offline, kein Header).
    """

    def test_barnard144_compact_offline_no_header_ghost_guard(self, tmp_path):
        # Variant A: "Barnard144" kompakt (ohne Leerzeichen) sollte B144-Eintrag hitten offline
        # und Ghost Guard muss passieren (lights\\ vorhanden, kein Header).
        astra_root = _make_astra_root(tmp_path, "Barnard144")
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock:
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "Barnard144"])
            mock.assert_not_called()  # compact alias hit, kein SIMBAD
        assert result.exit_code == 0, result.output
        assert "Barnard 144" in result.output or "B144" in result.output
        assert "Source: cache hit" in result.output
        out = astra_root / "Barnard144" / "suggested.yaml"
        assert out.is_file()
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        # dark_nebula -> nebula_standard live via Typ
        assert data["preset"] == "nebula_standard"

    def test_c34_offline_no_header_ghost_guard_hits_ngc6960(self, tmp_path):
        # Variant B: "C34" (kurz, alias fuer NGC 6960 Western Veil) offline ohne Header
        astra_root = _make_astra_root(tmp_path, "C34")
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock:
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "C34"])
            mock.assert_not_called()
        assert result.exit_code == 0, result.output
        assert "NGC 6960" in result.output or "C34" in result.output
        assert "snr" in result.output.lower() or "nebula_standard" in result.output
        assert "Source: cache hit" in result.output
        out = astra_root / "C34" / "suggested.yaml"
        assert out.is_file()
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        # SNR Typ -> nebula_standard
        assert data["preset"] == "nebula_standard"

    def test_c34_spaced_variant_offline_no_header(self, tmp_path):
        # Compact-Toleranz: "C 34" (mit Leerzeichen) muss gleich zu "C34" hiten
        astra_root = _make_astra_root(tmp_path, "C 34")
        cfg = _write_config(tmp_path, astra_root)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock:
            result = runner.invoke(cli, ["-c", str(cfg), "suggest", "C 34"])
            mock.assert_not_called()
        assert result.exit_code == 0, result.output
        assert "Source: cache hit" in result.output
