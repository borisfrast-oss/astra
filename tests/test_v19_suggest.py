"""Tests for V1.11-ENTSCHLACKUNG (`astra suggest` immer-Write +
`process --from-suggested` Pflicht).

Spec: orion/knowledge-base/projects/astra/specs/spec-v1.11-entschlackung.md
(owen, decided 2026-09-05) — AC-ENTS-1..6.
Plan: orion/knowledge-base/projects/astra/plan.md Z.532-542 (Test-Strategie).

S10 (Lessons): gezielte Tests je AC-ENTS, kein Voll-CI je Schritt — diese
Datei ist der komplette S10-Test-Umfang fuer V1.11-ENTSCHLACKUNG.

Die Tests nutzen einen MOCK-Target-Cache (dieser Datei), NICHT die
orion-KB (`knowledge-base/agents/stella/target-cache.md`) — astra ist ein
separates Repo und muss ohne die orion-KB testbar/lauffaehig sein
(PyPI-Architektur-Randbedingung, siehe core/suggest.py Docstring +
config/models.py SuggestConfig). SIMBAD-Webfetch wird per
`patch.object(suggest_mod, "query_simbad", ...)` gestubbt (offline, kein
echtes Netzwerk im Test-Suite, S10).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import yaml
from astropy.io import fits
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.cli import cli  # noqa: E402
from astro_process.config.loader import DEFAULT_CONFIG  # noqa: E402
from astro_process.core import suggest as suggest_mod  # noqa: E402

# ── Mock target-cache.md (stella-Schema, Subset M31/M27/C19/M13) ────────

MOCK_TARGET_CACHE_MD = """---
type: knowledge
scope: agent:stella
status: active
---

# Target-Cache — Mock (Test-Fixture, NICHT die orion-KB)

---

### M31 Andromeda (NGC 224)

| Feld | Wert |
|------|-------|
| **Ordner** | `C:\\Astra\\M31 Andromeda\\` |
| **Katalognummer** | M31 (= NGC 224) |
| **SIMBAD-Name** | M31 |
| **Typ** | Galaxie (spiral galaxy) |
| **Handbook** | 05-Galaxien.md |
| **Astra-Preset** | `galaxy_standard` |
| **Aliase** | Andromeda Galaxy, NGC 224 |

---

### M27 Hantelnebel (NGC 6853)

| Feld | Wert |
|------|-------|
| **Katalognummer** | M27 (= NGC 6853) |
| **SIMBAD-Name** | M27 |
| **Typ** | Planetarischer Nebel (planetary nebula) |
| **Handbook** | 08-Planetarische-Nebel.md |
| **Astra-Preset** | `nebula_standard` |
| **Aliase** | Dumbbell Nebula, NGC 6853 |

---

### C19 Kokonnebel (IC 5146)

| Feld | Wert |
|------|-------|
| **Katalognummer** | C19 (= IC 5146, Caldwell 19) |
| **SIMBAD-Name** | IC 5146 |
| **Typ** | Emissions-/Reflexionsnebel (emission/reflection nebula) |
| **Handbook** | 06-Emissionsnebel.md |
| **Astra-Preset** | `nebula_standard` |
| **Aliase** | Cocoon Nebula |

---

### M13 Hercules Cluster (NGC 6205)

| Feld | Wert |
|------|-------|
| **Katalognummer** | M13 (= NGC 6205) |
| **SIMBAD-Name** | M13 |
| **Typ** | Kugelsternhaufen (globular cluster) |
| **Handbook** | 09-Kugelsternhaufen.md |
| **Astra-Preset** | `star_standard` |
| **Aliase** | Great Hercules Cluster |

---

## Keine Targets (System-Ordner)

| Ordner | Grund |
|--------|-------|
| `C:\\Astra\\_darks\\` | Dark-Referenzbibliothek |
"""


def _write_mock_cache(tmp_path: Path) -> Path:
    p = tmp_path / "target-cache.md"
    p.write_text(MOCK_TARGET_CACHE_MD, encoding="utf-8")
    return p


def _make_astra_root(base: Path, *target_names: str) -> Path:
    """Legt <base>/AstraRoot/ + je Target <AstraRoot>/<name>/lights/ an.

    DEF-012-Guard (Ghost-Ordner-Fix): suggest schreibt nur in Ordner die
    bereits als Target existieren (Ordner + lights/ vorhanden). Tests die
    suggest ohne --output aufrufen, brauchen diese Struktur im tmp_path.
    """
    root = base / "AstraRoot"
    for name in target_names:
        (root / name / "lights").mkdir(parents=True, exist_ok=True)
    return root


def _write_config_with_cache(
    tmp_path: Path,
    cache_path: Path,
    name: str = "config.yaml",
    data_root: Path | None = None,
) -> Path:
    """DEFAULT_CONFIG + suggest.target_cache_path + optionaler data_root.

    data_root: wenn gesetzt, wird data_root im Config auf diesen Pfad
    umgebogen (noetig fuer Tests die suggest ohne --output aufrufen —
    DEF-012-Guard prueft Ordner-Existenz unter data_root/<Target>/lights/).
    """
    data = yaml.safe_load(DEFAULT_CONFIG)
    data["suggest"] = {"target_cache_path": str(cache_path)}
    if data_root is not None:
        data["data_root"] = str(data_root)
    cfg_path = tmp_path / name
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return cfg_path


def _offline_simbad(*_args, **_kwargs):
    """Stub fuer query_simbad: simuliert Timeout/Offline (AC-SUG-1/4, OQ-SUG-1)."""
    return None


def _create_light_target(root: Path, name: str = "TestTarget") -> Path:
    """Minimales Target mit einem synthetischen Light-FITS (fuer --dry-run).

    Stil-Vorbild: tests/test_sigma_clipped_cli_precedence.py::_create_light_target.
    """
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(7)
    data = (50.0 + rng.uniform(0, 10, (64, 64))).astype(np.float32)
    hdu = fits.PrimaryHDU(data)
    hdu.header["EXPTIME"] = 15.0
    hdu.header["GAIN"] = 60
    hdu.writeto(target / "light_0001.fits", overwrite=True)
    return target


def _last_json_line(output: str) -> dict:
    """Letzte nichtleere Zeile aus stdout als JSON parsen.

    `--json` gibt eine einzelne kompakte JSON-Zeile aus, aber structlog
    (JSONRenderer) schreibt vorangehende Log-Events ebenfalls als JSON nach
    stdout — die LETZTE Zeile ist eindeutig das Suggest-Ergebnis (kein Log
    danach, siehe cli.py suggest-Command).
    """
    lines = [line for line in output.strip().splitlines() if line.strip()]
    assert lines, "empty output"
    return json.loads(lines[-1])


# ═══════════════════════════════════════════════════════════════════════
# AC-SUG-1 — suggest stdout: 3 Targets, je 1-2 Optionen, offline, Exit 0
# ═══════════════════════════════════════════════════════════════════════


class TestAcSug1StdoutThreeTargets:
    def test_suggest_stdout_three_targets(self, tmp_path):
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: suggest schreibt Default <data_root>/<Target>/suggested.yaml
        # -> Ordner + lights/ muessen vorhanden sein.
        astra_root = _make_astra_root(tmp_path, "M31", "M27", "C19")
        cfg_path = _write_config_with_cache(tmp_path, cache, data_root=astra_root)
        runner = CliRunner()

        expectations = [
            ("M31", "galaxy_standard"),
            ("M27", "nebula_standard"),
            ("C19", "nebula_standard"),
        ]
        with patch.object(suggest_mod, "query_simbad") as mock_simbad:
            mock_simbad.side_effect = _offline_simbad
            for target, expected_preset in expectations:
                result = runner.invoke(cli, ["-c", str(cfg_path), "suggest", target])
                assert result.exit_code == 0, result.output
                assert result.exception is None
                assert f"Target: {target}" in result.output
                assert expected_preset in result.output
                assert "astroalign" in result.output
                assert "1)" in result.output
                assert "CLI: astra process" in result.output
                assert "--from-suggested" in result.output  # v1.11 F-1: Pflicht-Flag im Vorschlag
                assert "Handbook" in result.output
                assert "Source: cache hit" in result.output
            # Cache-Hits fragen SIMBAD nicht an (offline-first, hal)
            mock_simbad.assert_not_called()

        # C19 zusaetzlich: IC 5146 (SIMBAD-Name) + Emissions-Referenz
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result_c19 = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "C19"])
        assert "IC 5146" in result_c19.output

    def test_suggest_c19_with_space_same_cache_hit_as_c19_compact(self, tmp_path):
        """Stella-Smoke 2026-09-04: `suggest "C 19"` (Header-OBJECT-Schreibweise
        mit Space) muss denselben Cache-Hit liefern wie `suggest "C19"` —
        vorher fiel "C 19" auf den generischen handbook_fallback zurueck."""
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: "C 19" und "C19" brauchen je einen Ordner mit lights/
        astra_root = _make_astra_root(tmp_path, "C 19", "C19")
        cfg_path = _write_config_with_cache(tmp_path, cache, data_root=astra_root)
        runner = CliRunner()

        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock_simbad:
            result_spaced = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "C 19"])
            result_compact = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "C19"])
            mock_simbad.assert_not_called()  # beides Cache-Hits, kein SIMBAD-Fallback

        assert result_spaced.exit_code == 0, result_spaced.output
        assert result_compact.exit_code == 0, result_compact.output
        assert "Source: cache hit" in result_spaced.output
        assert "Source: cache hit" in result_compact.output
        assert "nebula_standard" in result_spaced.output
        assert "IC 5146" in result_spaced.output
        assert "IC 5146" in result_compact.output


# ═══════════════════════════════════════════════════════════════════════
# AC-SUG-2 — --header liest OBJECT/FILTER aus FITS, Header gewinnt ueber TARGET
# ═══════════════════════════════════════════════════════════════════════


class TestAcSug2HeaderReadsFits:
    def _write_dummy_fits(self, path: Path) -> None:
        hdu = fits.PrimaryHDU(np.zeros((4, 4), dtype=np.float32))
        hdu.header["OBJECT"] = "M27"
        hdu.header["FILTER"] = "Duo-Band"
        hdu.header["TELESCOP"] = "DWARF MINI"
        hdu.header["EXPTIME"] = 60.0
        hdu.writeto(path, overwrite=True)

    def test_suggest_header_reads_fits(self, tmp_path):
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: --header resolved OBJECT=M27 -> Default-Output <data_root>/M27/...
        # M31 wird auch getestet (Override), braucht daher ebenfalls einen Ordner.
        astra_root = _make_astra_root(tmp_path, "M27", "M31")
        cfg_path = _write_config_with_cache(tmp_path, cache, data_root=astra_root)
        fits_path = tmp_path / "M27_001.fits"
        self._write_dummy_fits(fits_path)
        runner = CliRunner()

        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            # Ohne TARGET: --header allein resolved via OBJECT=M27
            result_no_target = runner.invoke(
                cli, ["-c", str(cfg_path), "suggest", "--header", str(fits_path)]
            )
            assert result_no_target.exit_code == 0, result_no_target.output
            assert "OBJECT=M27" in result_no_target.output
            assert "FILTER=Duo-Band" in result_no_target.output
            assert "TELESCOP=DWARF MINI" in result_no_target.output
            assert "nebula_standard" in result_no_target.output
            # dwarf_mini AZ -> astroalign 15 deg (SUG-2 Heuristik)
            assert "astroalign 15" in result_no_target.output

            # Mit TARGET M31: Header-OBJECT=M27 gewinnt (Warnung)
            result_override = runner.invoke(
                cli, ["-c", str(cfg_path), "suggest", "M31", "--header", str(fits_path)]
            )
            assert result_override.exit_code == 0, result_override.output
            assert '"event": "suggest.header_overrides_target"' in result_override.output
            assert "nebula_standard" in result_override.output
            assert "galaxy_standard" not in result_override.output

    def test_suggest_header_incomplete_warns(self, tmp_path):
        """Fehlende Pflicht-Header-Keys -> WARN suggest.header_incomplete, kein Abbruch."""
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: OBJECT=M31 -> Default-Output <data_root>/M31/...
        astra_root = _make_astra_root(tmp_path, "M31")
        cfg_path = _write_config_with_cache(tmp_path, cache, data_root=astra_root)
        fits_path = tmp_path / "incomplete.fits"
        hdu = fits.PrimaryHDU(np.zeros((4, 4), dtype=np.float32))
        hdu.header["OBJECT"] = "M31"
        # FILTER/EXPTIME/TELESCOP fehlen bewusst
        hdu.writeto(fits_path, overwrite=True)
        runner = CliRunner()

        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = runner.invoke(
                cli, ["-c", str(cfg_path), "suggest", "--header", str(fits_path)]
            )
        assert result.exit_code == 0, result.output
        assert result.exception is None
        assert '"event": "suggest.header_incomplete"' in result.output
        assert "galaxy_standard" in result.output


# ═══════════════════════════════════════════════════════════════════════
# ray-review M4 — --coords happy path + error path (EN error message)
# ═══════════════════════════════════════════════════════════════════════


class TestCoordsFlag:
    def test_coords_happy_path_fallback_target(self, tmp_path):
        """No TARGET/--header: --coords resolves a fallback target
        (RA<deg>_DEC<deg>) for SIMBAD lookup/labeling
        (suggest.coords_fallback warning). Since ENTS-5: cache miss +
        offline → Exit 2 suggest.simbad_unavailable (no generic fallback).
        With SIMBAD available, should succeed. Here we test offline case."""
        cache = _write_mock_cache(tmp_path)
        cfg_path = _write_config_with_cache(tmp_path, cache)
        runner = CliRunner()

        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad) as mock_simbad:
            result = runner.invoke(
                cli, ["-c", str(cfg_path), "suggest", "--coords", "10.0", "20.0"]
            )
        # ENTS-5: unknown target (RA/DEC synthetic) + offline → Exit 2
        assert result.exit_code == 2, result.output
        assert '"event": "suggest.coords_fallback"' in result.output
        assert "suggest.simbad_unavailable" in result.output
        # SIMBAD was attempted once (cache miss for synthetic target)
        mock_simbad.assert_called_once()

    def test_coords_error_path_english_message(self, tmp_path):
        """Malformed --coords -> ClickException, EN message (ray M4: was DE),
        non-zero exit, no traceback/crash."""
        cache = _write_mock_cache(tmp_path)
        cfg_path = _write_config_with_cache(tmp_path, cache)
        runner = CliRunner()

        result = runner.invoke(
            cli, ["-c", str(cfg_path), "suggest", "--coords", "invalid", "abc"]
        )
        assert result.exit_code != 0
        assert "--coords expects two decimal-degree values" in result.output
        # EN-only guard (S17): no leftover German error text
        assert "erwartet" not in result.output
        assert "erhalten" not in result.output


# ═══════════════════════════════════════════════════════════════════════
# AC-SUG-3 — --json maschinenlesbar + --output schreibt valides YAML/JSON
# ═══════════════════════════════════════════════════════════════════════


class TestAcSug3JsonAndOutput:
    def test_suggest_json_and_output_yaml_valid(self, tmp_path):
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: alle suggest "M31"-Aufrufe (mit + ohne --output)
        # brauchen M31/lights/ im data_root. --output-Pfade liegen in tmp_path/M31/
        # -> ebenfalls lights/ benoetigt.
        astra_root = _make_astra_root(tmp_path, "M31")
        (tmp_path / "M31" / "lights").mkdir(parents=True, exist_ok=True)
        cfg_path = _write_config_with_cache(tmp_path, cache, data_root=astra_root)
        runner = CliRunner()

        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            # --json: stdout ist maschinenlesbares JSON mit den Pflicht-Keys
            result_json = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "M31", "--json"])
            assert result_json.exit_code == 0, result_json.output
            data = _last_json_line(result_json.output)
            for key in ("target", "preset", "registration", "debayer", "pcc", "source", "handbook_ref", "options"):
                assert key in data, f"key {key!r} missing in --json output"
            assert data["preset"] == "galaxy_standard"
            assert data["registration"]["method"] in ("astroalign", "fft")
            assert "max_rotation_deg" in data["registration"]
            assert data["debayer"]["method"] == "superpixel"
            assert data["pcc"]["enabled"] is True
            assert isinstance(data["options"], list) and len(data["options"]) >= 1

            # --output (kein --json): schreibt valides YAML, version:1 + Schema
            out_yaml = tmp_path / "M31" / "suggested.yaml"
            result_yaml = runner.invoke(
                cli, ["-c", str(cfg_path), "suggest", "M31", "--output", str(out_yaml)]
            )
            assert result_yaml.exit_code == 0, result_yaml.output
            assert out_yaml.is_file()
            file_data = yaml.safe_load(out_yaml.read_text(encoding="utf-8"))
            assert file_data["version"] == 1
            assert file_data["target"] == "M31"
            assert file_data["preset"] == "galaxy_standard"
            assert file_data["registration"]["method"] in ("astroalign", "fft")
            assert file_data["debayer"]["method"] == "superpixel"
            assert file_data["pcc"]["enabled"] is True

            # --output auf .json-Suffix + --json: File UND stdout beide JSON, konsistent
            out_json = tmp_path / "M31" / "suggested.json"
            result_json_file = runner.invoke(
                cli,
                ["-c", str(cfg_path), "suggest", "M31", "--output", str(out_json), "--json"],
            )
            assert result_json_file.exit_code == 0, result_json_file.output
            assert out_json.is_file()
            file_json_data = json.loads(out_json.read_text(encoding="utf-8"))
            stdout_data = _last_json_line(result_json_file.output)
            assert file_json_data["preset"] == stdout_data["preset"] == "galaxy_standard"
            assert file_json_data["registration"] == stdout_data["registration"]

    def test_suggest_always_writes_default(self, tmp_path):
        """AC-ENTS-1: `astra suggest M31` (ohne --output) schreibt immer
        <data_root>/M31/suggested.yaml (Target-Root-Default, ENTS-1)."""
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: M31/lights/ muss im AstraRoot vorhanden sein
        astra_root = tmp_path / "AstraRoot"
        (astra_root / "M31" / "lights").mkdir(parents=True, exist_ok=True)
        data = yaml.safe_load(DEFAULT_CONFIG)
        data["suggest"] = {"target_cache_path": str(cache)}
        data["data_root"] = str(astra_root)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        runner = CliRunner()

        # (a) Ohne --output -> schreibt Default <data_root>/M31/suggested.yaml
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "M31"])
        assert result.exit_code == 0, result.output
        expected_path = tmp_path / "AstraRoot" / "M31" / "suggested.yaml"
        assert expected_path.is_file(), result.output
        file_data = yaml.safe_load(expected_path.read_text(encoding="utf-8"))
        assert file_data["version"] == 1
        assert file_data["target"] == "M31"
        assert file_data["preset"] == "galaxy_standard"
        assert file_data["registration"]["method"] in ("astroalign", "fft")
        assert file_data["debayer"]["method"] == "superpixel"
        assert file_data["pcc"]["enabled"] is True
        assert '"event": "suggest.wrote_suggested"' in result.output

        # (b) Mit --output Pfad -> schreibt dort (Override)
        explicit_path = tmp_path / "AstraRoot" / "M31" / "suggested_20260905.yaml"
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result2 = runner.invoke(
                cli, ["-c", str(cfg_path), "suggest", "M31", "--output", str(explicit_path)]
            )
        assert result2.exit_code == 0, result2.output
        assert explicit_path.is_file()
        file_data2 = yaml.safe_load(explicit_path.read_text(encoding="utf-8"))
        assert file_data2["preset"] == "galaxy_standard"

        # (c) --json + .json Suffix -> valides JSON File + konsistentes stdout
        json_out = tmp_path / "AstraRoot" / "M31" / "suggested.json"
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result3 = runner.invoke(
                cli,
                ["-c", str(cfg_path), "suggest", "M31", "--output", str(json_out), "--json"],
            )
        assert result3.exit_code == 0, result3.output
        assert json_out.is_file()
        file_json = json.loads(json_out.read_text(encoding="utf-8"))
        stdout_json = _last_json_line(result3.output)
        assert file_json["preset"] == stdout_json["preset"] == "galaxy_standard"
        assert file_json["registration"] == stdout_json["registration"]


# ═══════════════════════════════════════════════════════════════════════
# AC-ENTS-4 — SIMBAD offline + unbekanntes Target -> Error Exit 2
#              (ENTS-5: kein generischer Fallback mehr)
# ═══════════════════════════════════════════════════════════════════════


class TestAcEnts4OfflineUnknownTargetFails:
    def test_suggest_offline_unknown_target_fails(self, tmp_path):
        """AC-ENTS-4: Cache-Miss + SIMBAD offline -> Exit 2
        suggest.simbad_unavailable, kein File geschrieben, kein Traceback."""
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: M31 (Cache-Hit) braucht Ordner+lights/, NGC 9999 scheitert
        # VOR dem Guard (suggest.simbad_unavailable) -> kein Ordner noetig.
        astra_root = tmp_path / "AstraRoot"
        (astra_root / "M31" / "lights").mkdir(parents=True, exist_ok=True)
        data = yaml.safe_load(DEFAULT_CONFIG)
        data["suggest"] = {"target_cache_path": str(cache)}
        data["data_root"] = str(astra_root)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        runner = CliRunner()

        with patch.object(suggest_mod, "query_simbad") as mock_simbad:
            mock_simbad.side_effect = _offline_simbad
            result_miss = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "NGC 9999"])
            # ENTS-5: Error Exit 2, kein generischer Fallback
            assert result_miss.exit_code == 2, result_miss.output
            assert "suggest.simbad_unavailable" in result_miss.output
            # kein Traceback (ClickException, sauber)
            assert "Traceback" not in result_miss.output
            # kein File geschrieben (raise passiert vor write)
            assert not (astra_root / "NGC 9999" / "suggested.yaml").exists()
            mock_simbad.assert_called_once()

        # Cache-Hit (M31) trotz Offline -> weiter Exit 0 (nur unbekanntes Target wird Error)
        with patch.object(suggest_mod, "query_simbad") as mock_simbad_hit:
            mock_simbad_hit.side_effect = AssertionError("SIMBAD darf bei Cache-Hit nicht aufgerufen werden")
            result_hit = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "M31"])
        assert result_hit.exit_code == 0, result_hit.output
        assert result_hit.exception is None
        assert "Source: cache hit" in result_hit.output
        assert "suggest.simbad_unavailable" not in result_hit.output

    def test_suggest_offline_unknown_no_traceback(self, tmp_path):
        """Explizit: kein Traceback bei Cache-Miss + Offline (ENTS-5, sauber Exit 2)."""
        cache = _write_mock_cache(tmp_path)
        cfg_path = _write_config_with_cache(tmp_path, cache)
        runner = CliRunner()
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "Completely Unknown Object"])
        assert result.exit_code == 2
        assert "Traceback" not in result.output
        assert "suggest.simbad_unavailable" in result.output


# ═══════════════════════════════════════════════════════════════════════
# AC-ENTS-3 — process --from-suggested: Pflicht; ohne Flag Error;
#             mit Flag+File Preset aus File; CLI gewinnt; OQ-ENTS-2 B
# ═══════════════════════════════════════════════════════════════════════


def _write_suggested_yaml(path: Path, **overrides) -> Path:
    data = {
        "version": 1,
        "target": "TestTarget",
        "preset": "galaxy_standard",
        "registration": {"method": "astroalign", "max_rotation_deg": 30},
        "debayer": {"method": "malvar"},
        "pcc": {"enabled": True},
        "source": "cache",
    }
    data.update(overrides)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


class TestAcEnts3ProcessRequiresFromSuggested:
    """AC-ENTS-3: --from-suggested Pflicht, CLI gewinnt, OQ-ENTS-2 B."""

    def test_process_requires_from_suggested_and_cli_wins(self, tmp_path):
        """Mit Flag+File -> effective-Werte + Log process.from_suggested;
        ohne Flag -> Exit 2 process.from_suggested.missing + Hint;
        CLI-Overrides gewinnen ueber File."""
        target = _create_light_target(tmp_path)
        suggested = _write_suggested_yaml(tmp_path / "suggested.yaml")
        runner = CliRunner()

        # (a) Mit Flag, keine CLI-Overrides -> effective_* aus File
        result_a = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested", str(suggested)]
        )
        assert result_a.exit_code == 0, result_a.output
        assert '"event": "process.from_suggested"' in result_a.output
        assert '"preset": "galaxy_standard"' in result_a.output
        assert '"method": "astroalign"' in result_a.output
        assert "Pipeline: galaxy_standard" in result_a.output
        assert '"max_rotation_deg": 30.0' in result_a.output
        assert '"method": "malvar"' in result_a.output  # cli.process.debayer
        # PCC aus File (enabled=True) greift
        assert '"event": "pcc.cli_override"' in result_a.output
        assert '"enabled": true' in result_a.output

        # (b) Ohne Flag -> Exit 2 process.from_suggested.missing + Hint
        result_b = runner.invoke(cli, ["process", str(target), "--dry-run"])
        assert result_b.exit_code == 2, result_b.output
        assert "process.from_suggested.missing" in result_b.output

        # (c) CLI gewinnt ueber File (alle 4 Felder ueberschrieben)
        result_c = runner.invoke(
            cli,
            [
                "process", str(target), "--dry-run",
                "--from-suggested", str(suggested),
                "--preset", "nebula_standard",
                "--registration-method", "fft",
                "--max-rotation", "2",
                "--no-pcc",
            ],
        )
        assert result_c.exit_code == 0, result_c.output
        assert "Pipeline: nebula_standard" in result_c.output
        assert '"method": "fft"' in result_c.output
        assert '"max_rotation_deg": 2.0' in result_c.output
        assert '"enabled": false' in result_c.output
        # File-Preset darf NICHT durchsickern
        assert "Pipeline: galaxy_standard" not in result_c.output

    def test_process_from_suggested_default_without_value(self, tmp_path):
        """OQ-ENTS-2 B: --from-suggested ohne Wert -> Default <Target>/suggested.yaml.
        Liegt File vor -> gleiches Ergebnis wie explizit;
        fehlt File -> Exit 2 process.from_suggested.not_found + Hint."""
        target = _create_light_target(tmp_path)
        runner = CliRunner()

        # (a2) Flag ohne Wert, aber suggested.yaml liegt im Target -> Default auflösen
        suggested = _write_suggested_yaml(target / "suggested.yaml")
        result_a2 = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested"]
        )
        assert result_a2.exit_code == 0, result_a2.output
        assert '"event": "process.from_suggested"' in result_a2.output
        assert "Pipeline: galaxy_standard" in result_a2.output

        # Vergleich mit explizitem Pfad -> gleiches Ergebnis
        result_explicit = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested", str(suggested)]
        )
        assert result_explicit.exit_code == 0, result_explicit.output

        # (not_found) Flag ohne Wert, suggested.yaml fehlt -> Exit 2 not_found
        target2 = _create_light_target(tmp_path, name="NoFileTarget")
        result_notfound = runner.invoke(
            cli, ["process", str(target2), "--dry-run", "--from-suggested"]
        )
        assert result_notfound.exit_code == 2, result_notfound.output
        assert "process.from_suggested.not_found" in result_notfound.output

    def test_process_from_suggested_file_wins_over_config(self, tmp_path):
        """OQ-ENTS-3 A: File > Config precedence — Config sets
        debayer_method=bilinear; suggested file requests malvar (wins)."""
        target = _create_light_target(tmp_path)
        data = yaml.safe_load(DEFAULT_CONFIG)
        data["debayer_method"] = "bilinear"
        data["pcc"] = {"enabled": False}
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        # Default _write_suggested_yaml carries debayer.method=malvar + pcc.enabled=True
        suggested = _write_suggested_yaml(tmp_path / "suggested_precedence.yaml")
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "-c", str(cfg_path), "process", str(target), "--dry-run",
                "--from-suggested", str(suggested),
            ],
        )
        assert result.exit_code == 0, result.output
        # File wins over Config: malvar (not bilinear)
        assert '"method": "malvar"' in result.output  # cli.process.debayer
        assert '"method": "bilinear"' not in result.output
        # pcc enabled=true (not the Config's false)
        pcc_override_lines = [
            line for line in result.output.splitlines() if '"event": "pcc.cli_override"' in line
        ]
        assert pcc_override_lines, result.output
        assert all('"enabled": true' in line for line in pcc_override_lines)
        assert all('"enabled": false' not in line for line in pcc_override_lines)

    def test_process_no_auto_discover_without_flag(self, tmp_path):
        """ENTS-3: suggested.yaml liegt im Target, OHNE --from-suggested
        -> Exit 2 process.from_suggested.missing (kein Auto-Discover, ENTS-3)."""
        target = _create_light_target(tmp_path)
        # suggested.yaml direkt IM Target-Ordner
        _write_suggested_yaml(target / "suggested.yaml")
        runner = CliRunner()

        result_without_flag = runner.invoke(cli, ["process", str(target), "--dry-run"])
        # ENTS-3: ohne Flag -> Pflicht-Error Exit 2 (kein byte-identisch mehr)
        assert result_without_flag.exit_code == 2, result_without_flag.output
        assert "process.from_suggested.missing" in result_without_flag.output


# ═══════════════════════════════════════════════════════════════════════
# AC-ENTS-5 — Keine Preset-Heuristik ohne File (Negativ-Greps + Error-Cases)
# ═══════════════════════════════════════════════════════════════════════


class TestAcEnts5NoPresetHeuristicsWithoutFile:
    """AC-ENTS-5: Negativ-Greps + Error-Cases fuer gestraffte Pipeline."""

    def test_no_default_preset_in_process_path(self):
        """Kein cfg.default_preset Fallback im process-Pfad von cli.py."""
        cli_path = Path(__file__).resolve().parent.parent / "src" / "astro_process" / "cli.py"
        text = cli_path.read_text(encoding="utf-8")
        # Finde process-Funktion und prüfe auf default_preset NICHT als Fallback
        # "preset = cfg.default_preset" ohne Guard darf nicht im process-Block vorkommen
        # (Ausnahmen: batch-Docstring, init/interactive Presets — ausserhalb des process-Pfads)
        process_start = text.find("def process(")
        # Ende des process-Blocks: naechste @cli.command() Deklaration
        next_command = text.find("@cli.command()", process_start + 1)
        process_block = text[process_start:next_command]
        # "preset = cfg.default_preset" als Fallback-Zuweisung darf nicht vorkommen
        assert "preset = cfg.default_preset" not in process_block, (
            "Gefunden: 'preset = cfg.default_preset' im process-Block (ENTS-6)"
        )

    def test_no_galaxy_standard_hardcode_in_cli_process(self):
        """Kein 'or \"galaxy_standard\"' im cli.py process-Pfad."""
        cli_path = Path(__file__).resolve().parent.parent / "src" / "astro_process" / "cli.py"
        text = cli_path.read_text(encoding="utf-8")
        process_start = text.find("def process(")
        next_command = text.find("@cli.command()", process_start + 1)
        process_block = text[process_start:next_command]
        assert 'or "galaxy_standard"' not in process_block, (
            "Gefunden: 'or \"galaxy_standard\"' im process-Block (ENTS-6)"
        )

    def test_no_superpixel_hardcode_in_cli_process(self):
        """Kein 'or \"superpixel\"' Fallback im cli.py process-Pfad (ENTS-4)."""
        cli_path = Path(__file__).resolve().parent.parent / "src" / "astro_process" / "cli.py"
        text = cli_path.read_text(encoding="utf-8")
        process_start = text.find("def process(")
        next_command = text.find("@cli.command()", process_start + 1)
        process_block = text[process_start:next_command]
        assert 'or "superpixel"' not in process_block, (
            "Gefunden: 'or \"superpixel\"' Hardcode im process-Block (ENTS-4)"
        )

    def test_no_fallback_code_in_suggest_core(self):
        """_FALLBACK_PRESET_PAIRS und _build_fallback_options wurden entfernt (ENTS-5)."""
        suggest_path = (
            Path(__file__).resolve().parent.parent
            / "src" / "astro_process" / "core" / "suggest.py"
        )
        text = suggest_path.read_text(encoding="utf-8")
        assert "_FALLBACK_PRESET_PAIRS" not in text, "_FALLBACK_PRESET_PAIRS noch vorhanden"
        assert "_build_fallback_options" not in text, "_build_fallback_options noch vorhanden"
        assert "handbook_fallback" not in text, "handbook_fallback noch vorhanden"

    def test_process_file_without_registration_errors(self, tmp_path):
        """File ohne `registration` + Config ohne registration -> Error
        process.registration_method.missing (OQ-ENTS-3 A: null→Config only
        when Config has a value; hier hat Config keinen registration-Block,
        kein silent fft Fallback, ENTS-4)."""
        target = _create_light_target(tmp_path)
        # Config OHNE registration-Block (kein Supplement-Fallback)
        data = yaml.safe_load(DEFAULT_CONFIG)
        data.pop("registration", None)  # registration-Block entfernen
        cfg_path = tmp_path / "config_no_reg.yaml"
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        # File ohne registration-Feld
        suggested_path = tmp_path / "suggested_no_reg.yaml"
        file_data = {
            "version": 1,
            "target": "TestTarget",
            "preset": "galaxy_standard",
            "debayer": {"method": "superpixel"},
            "pcc": {"enabled": False},
            "source": "cache",
        }
        suggested_path.write_text(yaml.safe_dump(file_data), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["-c", str(cfg_path), "process", str(target), "--dry-run",
                  "--from-suggested", str(suggested_path)]
        )
        assert result.exit_code == 2, result.output
        assert "process.registration_method.missing" in result.output

    def test_process_file_without_preset_errors(self, tmp_path):
        """File ohne `preset` -> Error Exit 2 process.preset.missing (ENTS-4)."""
        target = _create_light_target(tmp_path)
        suggested_path = tmp_path / "suggested_no_preset.yaml"
        data = {
            "version": 1,
            "target": "TestTarget",
            "registration": {"method": "fft", "max_rotation_deg": 2},
            "debayer": {"method": "superpixel"},
            "pcc": {"enabled": False},
            "source": "cache",
        }
        suggested_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--from-suggested", str(suggested_path)]
        )
        assert result.exit_code == 2, result.output
        assert "process.preset.missing" in result.output


# ═══════════════════════════════════════════════════════════════════════
# AC-SUG-6 / AC-ENTS-2 — Handbook-Zitat, kein hart-codierter Baum,
#                          Cache-Update ohne Deploy
# ═══════════════════════════════════════════════════════════════════════


class TestAcSug6HandbookCitationNoHardcodedTree:
    def test_suggest_handbook_citation_no_hardcoded_tree(self, tmp_path):
        cache = _write_mock_cache(tmp_path)
        # DEF-012-Guard: alle Targets brauchen Ordner+lights/ im data_root
        astra_root = _make_astra_root(tmp_path, "M31", "C19", "M13", "NGC 7000")
        cfg_path = _write_config_with_cache(tmp_path, cache, data_root=astra_root)
        runner = CliRunner()

        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            r_m31 = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "M31"])
            assert r_m31.exit_code == 0
            assert "Handbook 22" in r_m31.output
            assert "\u00a73" in r_m31.output or "05-Galaxies.md" in r_m31.output

            r_c19 = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "C19"])
            assert r_c19.exit_code == 0
            assert "\u00a74/\u00a75" in r_c19.output
            assert "06-Emission-Nebulae.md" in r_c19.output

            r_m13 = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "M13"])
            assert r_m13.exit_code == 0
            assert "\u00a76" in r_m13.output
            assert "09-Globular-Clusters.md" in r_m13.output

        # Integration: neuer Cache-Entry (NGC 7000) ohne Code-Deploy -> neuer Output
        extra_entry = (
            "\n\n---\n\n### NGC 7000 Test-Integration\n\n"
            "| Feld | Wert |\n|------|-------|\n"
            "| **Katalognummer** | NGC 7000 |\n"
            "| **SIMBAD-Name** | NGC 7000 |\n"
            "| **Typ** | Emissionsnebel (emission nebula) |\n"
            "| **Handbook** | 06-Emissionsnebel.md |\n"
            "| **Astra-Preset** | `nebula_standard` |\n"
        )
        cache.write_text(MOCK_TARGET_CACHE_MD + extra_entry, encoding="utf-8")
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            r_ngc = runner.invoke(cli, ["-c", str(cfg_path), "suggest", "NGC 7000"])
        assert r_ngc.exit_code == 0, r_ngc.output
        assert "nebula_standard" in r_ngc.output
        assert "Source: cache hit" in r_ngc.output

    def test_no_hardcoded_target_preset_tree_in_source(self):
        """AC-SUG-6 Pflicht-Nachweis: kein `M31.*galaxy_standard`-Baum im Code.

        Python-native Aequivalent zu
        `grep -R "M31.*galaxy_standard" astra/src/astro_process --include="*.py"`
        (portabel, kein Abhaengigkeit von einem installierten `grep` unter
        Windows-CI).
        """
        src_dir = Path(__file__).resolve().parent.parent / "src" / "astro_process"
        pattern = re.compile(r"M31.*galaxy_standard")
        hits: list[str] = []
        for py_file in src_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{py_file}:{lineno}: {line}")
        assert not hits, "Hardcoded M31->galaxy_standard tree found:\n" + "\n".join(hits)


# ═══════════════════════════════════════════════════════════════════════
# Zusatz — target-cache Parser (SUG-2, Schema-Toleranz, Risiko-Mitigation)
# ═══════════════════════════════════════════════════════════════════════


class TestTargetCacheParserTolerance:
    def test_parse_target_cache_tolerant_to_unrelated_markdown(self, tmp_path):
        """Der Parser darf an der 'Keine Targets'-Tabelle (keine ### Ueberschrift,
        keine **bold** Felder) nicht scheitern (Schema-Toleranz, plan.md Z.562)."""
        entries = suggest_mod.parse_target_cache(MOCK_TARGET_CACHE_MD)
        names = {e.get("_heading") for e in entries}
        assert any("M31" in n for n in names)
        assert any("C19" in n for n in names)
        assert len(entries) == 4  # M31, M27, C19, M13 — "Keine Targets" ist KEIN Entry

    def test_find_cache_entry_matches_aliases_and_catalog_numbers(self):
        entries = suggest_mod.parse_target_cache(MOCK_TARGET_CACHE_MD)
        assert suggest_mod.find_cache_entry("M31", entries) is not None
        assert suggest_mod.find_cache_entry("m31", entries) is not None  # case-insensitive
        assert suggest_mod.find_cache_entry("C19", entries) is not None
        assert suggest_mod.find_cache_entry("IC 5146", entries) is not None  # SIMBAD-Name
        assert suggest_mod.find_cache_entry("NGC 9999", entries) is None  # genuine miss

    def test_find_cache_entry_alias_normalization_space_tolerant(self):
        """Stella-Smoke 2026-09-04: FITS-Header OBJECT "C 19" (mit Space)
        muss denselben Cache-Eintrag treffen wie CLI-Target "C19" (ohne
        Space) — Katalognummer im Mock-Cache ist "C19 (= IC 5146, Caldwell
        19)"."""
        entries = suggest_mod.parse_target_cache(MOCK_TARGET_CACHE_MD)
        hit_spaced = suggest_mod.find_cache_entry("C 19", entries)
        hit_compact = suggest_mod.find_cache_entry("C19", entries)
        assert hit_spaced is not None
        assert hit_compact is not None
        assert hit_spaced is hit_compact  # gleicher Cache-Eintrag (Identity)
        assert hit_spaced.get("_heading", "").startswith("C19 Kokonnebel")

        # Caldwell-Alias-Bonus: "Caldwell 19" im Katalognummer-Feld -> "C 19"
        # (Header-Schreibweise mit Space) matcht ebenfalls.
        assert suggest_mod.find_cache_entry("c 19", entries) is not None
        # Case-insensitive + Bindestrich-tolerant
        assert suggest_mod.find_cache_entry("C-19", entries) is not None

    def test_missing_cache_file_degrades_to_empty_not_error(self, tmp_path):
        """PyPI-Architektur: fehlender Cache-Pfad -> [] (immer Cache-Miss), kein Crash."""
        assert suggest_mod.load_target_cache(None) == []
        assert suggest_mod.load_target_cache(tmp_path / "does_not_exist.md") == []


# ═══════════════════════════════════════════════════════════════════════
# ray-review M5 — write_suggested_file() uses the repo template + fills
# equipment_hint/filter_hint/exptime_hint (Spec SUG-4, Handbook §17.2)
# ═══════════════════════════════════════════════════════════════════════


class TestM5TemplateAndHints:
    def test_to_file_dict_adds_hints_from_header(self, tmp_path):
        hdu = fits.PrimaryHDU(np.zeros((4, 4), dtype=np.float32))
        hdu.header["OBJECT"] = "M27"
        hdu.header["FILTER"] = "Duo-Band"
        hdu.header["TELESCOP"] = "DWARF MINI"
        hdu.header["EXPTIME"] = 60.0
        fits_path = tmp_path / "M27_001.fits"
        hdu.writeto(fits_path, overwrite=True)
        # V1.11: build_result needs a cache (M27 must be in cache, otherwise
        # offline miss -> SuggestInputError ENTS-5).
        cache = _write_mock_cache(tmp_path)

        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = suggest_mod.build_result(target=None, header_path=fits_path, cache_path=cache)
        data = suggest_mod.to_file_dict(result)

        assert data["equipment_hint"] == "dwarf_mini"
        assert data["filter_hint"] == "Duo-Band"
        assert data["exptime_hint"] == 60.0

    def test_to_file_dict_hints_none_without_header(self, tmp_path):
        cache = _write_mock_cache(tmp_path)
        entries = suggest_mod.load_target_cache(cache)
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = suggest_mod.build_result(target="M31", cache_path=cache)
        assert entries  # sanity: fixture parsed
        data = suggest_mod.to_file_dict(result)
        assert data["equipment_hint"] is None
        assert data["filter_hint"] is None
        assert data["exptime_hint"] is None

    def test_write_suggested_file_uses_repo_template(self, tmp_path):
        """Written YAML is rendered from `templates/suggested_parameters.yaml`
        (Spec SUG-4: "Basis ist Template ..."), not a bare `yaml.safe_dump` —
        the template's explanatory comments must survive in the output."""
        cache = _write_mock_cache(tmp_path)
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = suggest_mod.build_result(target="M31", cache_path=cache)
        data = suggest_mod.to_file_dict(result)
        out_path = tmp_path / "suggested.yaml"
        # DEF-012-Guard: out_path.parent = tmp_path -> lights/ muss vorhanden sein
        (tmp_path / "lights").mkdir(exist_ok=True)

        suggest_mod.write_suggested_file(data, out_path)
        text = out_path.read_text(encoding="utf-8")

        # Template comment survives (proves the template was used, not a bare dump)
        assert "Template for `astra suggest --output`" in text
        assert "extra=\"ignore\"" in text
        # Real values were filled in (not the template's example placeholders)
        assert "target: M31" in text
        assert "preset: galaxy_standard" in text
        assert "type: galaxy" in text

        # Still valid, loadable YAML with the correct values (SUG-4 contract)
        loaded = yaml.safe_load(text)
        assert loaded["version"] == 1
        assert loaded["target"] == "M31"
        assert loaded["preset"] == "galaxy_standard"
        assert loaded["registration"]["method"] in ("astroalign", "fft")
        assert loaded["debayer"]["method"] == "superpixel"
        assert loaded["pcc"]["enabled"] is True
        assert loaded["equipment_hint"] is None  # no --header for this target lookup
        assert loaded["filter_hint"] is None
        assert loaded["exptime_hint"] is None

    def test_write_suggested_file_template_missing_falls_back_to_plain_dump(
        self, tmp_path, monkeypatch
    ):
        """PyPI wheel install without `templates/` on disk must still produce
        a valid file (graceful degrade, analog DEFAULT_CONFIG fallback)."""
        monkeypatch.setattr(
            suggest_mod, "_TEMPLATE_PATH", tmp_path / "does-not-exist.yaml"
        )
        cache = _write_mock_cache(tmp_path)
        with patch.object(suggest_mod, "query_simbad", side_effect=_offline_simbad):
            result = suggest_mod.build_result(target="M31", cache_path=cache)
        data = suggest_mod.to_file_dict(result)
        out_path = tmp_path / "suggested_fallback.yaml"
        # DEF-012-Guard: out_path.parent = tmp_path -> lights/ muss vorhanden sein
        (tmp_path / "lights").mkdir(exist_ok=True)

        suggest_mod.write_suggested_file(data, out_path)
        loaded = yaml.safe_load(out_path.read_text(encoding="utf-8"))
        assert loaded["target"] == "M31"
        assert loaded["preset"] == "galaxy_standard"

    def test_template_english_comments_only(self):
        """ray-review M5: template was 100% German — must be EN now (S17)."""
        template_path = (
            Path(__file__).resolve().parent.parent
            / "templates" / "suggested_parameters.yaml"
        )
        text = template_path.read_text(encoding="utf-8")
        umlaut_re = re.compile(r"[äöüßÄÖÜ]")
        hits = umlaut_re.findall(text)
        assert not hits, f"German umlauts found in template: {hits}"
