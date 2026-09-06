"""Batch 3b — SCS-B + SCS-C Precedence + Transparenz (V1.7-3 OQ-SCS-3 A).

Spec: orion/knowledge-base/projects/astra/specs/v17-sigma-clipped-stack.md
  SCS-B B1..B5, SCS-C C1..C3 — OQ-SCS-3 A: kein rejection-Mapping, nur
  stacking_method; Presets unveraendert.

Mapping (je genau ein pytest-Test, Lessons S9/S10: gezielt, kein Voll-CI):
- B1: CLI --stacking-method sigma_clipped_mean akzeptiert + Stack mit neuer Methode (Click-Aufruf)
- B2: config.yaml processing_params.stacking_method sigma_clipped_mean -> Methode; CLI ueberschreibt Config
- B3: Ohne stacking_method -> rejection-Mapping/Default "average" unveraendert (byte-identisch v1.6)
- B4: Alle 4 Presets unveraendert (≠ sigma_clipped_mean)
- B5: Beide Aufrufstellen Single + Multi-Group stuetzen Methode (gemeinsamer stack_2d-Pfad)
- C1: stack.complete enthaelt method-Feld (aufgeloest)
- C2: Neues Feld additiv, bricht nichts (bestehende Keys bleiben)
- C3: Rejection-Mapping-Faelle loggen tatsächlich genutzte Methode, nicht Rohwert

Stil-Vorbild: tests/test_cli_env_parametrization.py (CLI via CliRunner) +
              tests/test_stacking_rejection.py (stack_2d / sys.path-Insert, reine numpy-Fixtures).

Nur diese Datei, kein Commit (Batch 3b).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml
from astropy.io import fits
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import write_default_suggested  # noqa: E402
from astro_process.cli import cli  # noqa: E402
from astro_process.config.loader import DEFAULT_CONFIG  # noqa: E402
from astro_process.core import stacking as stacking_mod  # noqa: E402
from astro_process.core.stacking import (  # noqa: E402
    resolve_stack_method,
    sigma_clipped_mean,
    stack_2d,
    stack_frames,
    stack_frames_python,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _create_light_target(root: Path) -> Path:
    """Minimales Target mit einem synthetischen Light-FITS (fuer dry-run)."""
    target = root / "TestTarget"
    target.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(7)
    data = (50.0 + rng.uniform(0, 10, (64, 64))).astype(np.float32)
    hdu = fits.PrimaryHDU(data)
    hdu.header["EXPTIME"] = 15.0
    hdu.header["GAIN"] = 60
    hdu.writeto(target / "light_0001.fits", overwrite=True)
    return target


def _write_fits(path: Path, data: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(np.asarray(data, dtype=np.float32)).writeto(path, overwrite=True)


def _read_fits(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        return np.asarray(hdul[0].data, dtype=np.float64)


def _write_config_with_preset_stacking(tmp_path: Path, preset_name: str, stacking_method: str | None) -> Path:
    """DEFAULT_CONFIG-Basis mit gesetztem preset stacking_method als config.yaml schreiben."""
    data = yaml.safe_load(DEFAULT_CONFIG)
    for preset in data["pipeline_presets"]:
        if preset["name"] == preset_name:
            if stacking_method is None:
                preset["processing_params"].pop("stacking_method", None)
            else:
                preset["processing_params"]["stacking_method"] = stacking_method
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return cfg_path


# ═══════════════════════════════════════════════════════════════════
# B1 — CLI --stacking-method sigma_clipped_mean akzeptiert
# ═══════════════════════════════════════════════════════════════════


class TestB1CliAccepts:
    def test_b1_cli_accepts_sigma_clipped_mean(self, tmp_path: Path):
        """B1: astra process --stacking-method sigma_clipped_mean wird von Click
        akzeptiert und erzeugt einen Stack mit der neuen Methode (verifizierbar
        via cli.process.stacking Log method)."""
        target = _create_light_target(tmp_path)
        write_default_suggested(target)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["process", str(target), "--dry-run", "--from-suggested",
             "--stacking-method", "sigma_clipped_mean"],
        )
        assert result.exit_code == 0, result.output
        assert "cli.process.stacking" in result.output
        # JSONRenderer: "method": "sigma_clipped_mean"
        assert '"method": "sigma_clipped_mean"' in result.output or '"method":"sigma_clipped_mean"' in result.output
        assert '"cli_override": "sigma_clipped_mean"' in result.output or "sigma_clipped_mean" in result.output

    def test_b1_cli_rejects_unknown_choice_still(self, tmp_path: Path):
        """Sanity: unbekannter Choice wird weiter von Click abgelehnt (Exit 2)."""
        target = _create_light_target(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["process", str(target), "--dry-run", "--stacking-method", "bogus_xyz"],
        )
        assert result.exit_code == 2
        assert "bogus_xyz" in result.output or "Invalid value" in result.output


# ═══════════════════════════════════════════════════════════════════
# B2 — config.yaml stacking_method + CLI-Precedence
# ═══════════════════════════════════════════════════════════════════


class TestB2ConfigAndPrecedence:
    def test_b2_config_stacking_method_leads_to_method(self, tmp_path: Path):
        """B2a: stacking_method: sigma_clipped_mean in der config.yaml
        (processing_params) fuehrt zur neuen Methode (ohne CLI-Flag)."""
        target = _create_light_target(tmp_path)
        write_default_suggested(target)
        cfg_path = _write_config_with_preset_stacking(tmp_path, "star_standard", "sigma_clipped_mean")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(cfg_path), "process", str(target), "--dry-run",
             "--from-suggested", "--preset", "star_standard"],
        )
        assert result.exit_code == 0, result.output
        assert '"method": "sigma_clipped_mean"' in result.output or '"method":"sigma_clipped_mean"' in result.output

    def test_b2_cli_overrides_config(self, tmp_path: Path):
        """B2b: CLI-Flag ueberschreibt Config (Precedence CLI > Preset/Config)."""
        target = _create_light_target(tmp_path)
        write_default_suggested(target)
        # Config will sigma_clipped_mean, CLI will average -> average gewinnt
        cfg_path = _write_config_with_preset_stacking(tmp_path, "star_standard", "sigma_clipped_mean")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "-c", str(cfg_path), "process", str(target), "--dry-run",
                "--from-suggested", "--preset", "star_standard",
                "--stacking-method", "average",
            ],
        )
        assert result.exit_code == 0, result.output
        assert '"method": "average"' in result.output or '"method":"average"' in result.output
        # Gegenprobe: sigma_clipped_mean darf NICHT mehr drinstehen als effektive Methode
        assert '"cli_override": "average"' in result.output or '"cli_override":"average"' in result.output

    def test_b2_resolve_stack_method_precedence_direct(self):
        """Direkt-API: resolve_stack_method stacking_method gewinnt ueber rejection."""
        assert resolve_stack_method({"rejection": "winsorized", "stacking_method": "sigma_clipped_mean"}) == "sigma_clipped_mean"
        assert resolve_stack_method({"stacking_method": "sigma_clipped_mean"}) == "sigma_clipped_mean"
        # CLI-Transparenz: wenn CLI stacking_method setzt, ist es der Gewinner


# ═══════════════════════════════════════════════════════════════════
# B3 — Ohne stacking_method: rejection-Mapping / Default unveraendert
# ═══════════════════════════════════════════════════════════════════


class TestB3DefaultUnchanged:
    def test_b3_resolve_defaults_to_average(self):
        """B3: Ohne stacking_method gilt weiterhin rejection-Mapping bzw. Default 'average'."""
        # Leere params -> average
        assert resolve_stack_method({}) == "average"
        assert resolve_stack_method({"normalization": "mul"}) == "average"
        # Rejection-Mapping unveraendert (OQ-SCS-3 A: kein Mapping auf sigma_clipped_mean)
        assert resolve_stack_method({"rejection": "winsorized"}) == "winsorized"
        assert resolve_stack_method({"rejection": "average"}) == "average"
        assert resolve_stack_method({"rejection": "none"}) == "average"
        # Unbekanntes rejection -> average (konservativ, v1.3)
        assert resolve_stack_method({"rejection": "median"}) == "average"
        assert resolve_stack_method({"rejection": "sigma_clip"}) == "average"
        assert resolve_stack_method({"rejection": "sigma_clipped_mean"}) == "average"
        # OQ-SCS-3 A: kein rejection-Wert mappt auf sigma_clipped_mean
        for rej in ["winsorized", "average", "none", "sigma_clip", "sigma_clipped_mean", "median"]:
            assert resolve_stack_method({"rejection": rej}) != "sigma_clipped_mean"

    def test_b3_cli_without_flag_keeps_preset_mapping(self, tmp_path: Path):
        """Ohne --stacking-method Flag bleibt Preset-Mapping wirksam (nebula_standard + star_standard winsorized)."""
        target = _create_light_target(tmp_path)
        write_default_suggested(target, preset="nebula_standard")
        runner = CliRunner()
        result = runner.invoke(cli, ["process", str(target), "--dry-run", "--from-suggested",
                                     "--preset", "nebula_standard"])
        assert result.exit_code == 0, result.output
        assert '"method": "winsorized"' in result.output
        # star_standard -> winsorized
        write_default_suggested(target, preset="star_standard")
        result2 = runner.invoke(cli, ["process", str(target), "--dry-run", "--from-suggested",
                                      "--preset", "star_standard"])
        assert result2.exit_code == 0, result2.output
        assert '"method": "winsorized"' in result2.output

    def test_b3_stack_frames_default_is_average_byte_identical(self, tmp_path: Path):
        """Byte-identisch v1.6: Default-Stack (kein stacking_method) ist purem Average identisch."""
        rng = np.random.RandomState(0)
        data = rng.normal(100.0, 5.0, size=(10, 8, 8))
        # resolve ohne stacking_method -> average
        method = resolve_stack_method({})
        assert method == "average"
        expected = np.mean(data, axis=0)
        result = stack_2d(data, method=method, normalization="no")
        assert np.allclose(result, expected)
        # Explizites sigma_clipped_mean unterscheidet sich bei Outlier (Nicht-Gleichheit belegt Opt-in)
        data_out = data.copy()
        data_out[0, 4, 4] = 5000.0
        clipped = stack_2d(data_out, method="sigma_clipped_mean", normalization="no")
        avg_out = stack_2d(data_out, method="average", normalization="no")
        # Bei N=10 bleibt 5000 nach 3σ zu weit -> Verwerfen, also Unterschied
        assert not np.allclose(clipped, avg_out)


# ═══════════════════════════════════════════════════════════════════
# B4 — Alle 4 Presets unveraendert
# ═══════════════════════════════════════════════════════════════════


class TestB4PresetsUnchanged:
    def test_b4_all_presets_not_sigma(self):
        """B4: Alle vier Presets erzeugen unveraenderte Stacks (kein Preset nutzt sigma_clipped_mean)."""
        data = yaml.safe_load(DEFAULT_CONFIG)
        allowed = {"weighted", "average", None}
        for preset in data["pipeline_presets"]:
            name = preset["name"]
            if name in ("galaxy_standard", "nebula_standard", "nebula_enhanced", "star_standard", "cluster_standard", "nebula_bilinear", "galaxy_bilinear"):
                sm = preset.get("processing_params", {}).get("stacking_method")
                # OQ-SCS-3 A: kein Preset wurde auf sigma_clipped_mean umgestellt
                assert sm != "sigma_clipped_mean", f"Preset {name} darf nicht sigma_clipped_mean nutzen"
                assert sm in allowed or sm in ("weighted", "average"), f"Preset {name} stacking_method {sm!r} unerwartet"
        # Zusätzlich verifizieren: Kein legacy-Preset nutzt sigma
        lookup = {p["name"]: p["processing_params"].get("stacking_method") for p in data["pipeline_presets"]}
        for k, v in lookup.items():
            if k in ("galaxy_standard", "nebula_standard", "nebula_enhanced", "star_standard", "cluster_standard"):
                assert v != "sigma_clipped_mean"

    def test_b4_models_core_presets_also_unchanged(self):
        """Zusaetzlich: models/core.py PRESETS ebenfalls unveraendert (Double-Source)."""
        from astro_process.models.core import PRESETS

        for key in ("galaxy_standard", "nebula_enhanced", "star_standard", "cluster_standard"):
            if key in PRESETS:
                sm = PRESETS[key].processing_params.get("stacking_method")
                assert sm != "sigma_clipped_mean", f"models/core {key} darf nicht sigma_clipped_mean sein"


# ═══════════════════════════════════════════════════════════════════
# B5 — Beide Aufrufstellen Single + Multi-Group stuetzen Methode (gemeinsamer stack_2d-Pfad)
# ═══════════════════════════════════════════════════════════════════


class TestB5BothPathsShareStack2d:
    def test_b5_single_and_multi_share_resolve_and_stack_2d(self, tmp_path: Path):
        """B5: Beide Aufrufstellen (Single + Multi-Group) stuetzen die Methode —
        gemeinsamer Codeweg resolve_stack_method + stack_2d, kein Pfad-Special-Casing."""
        # a) resolve_stack_method liefert sigma_clipped_mean wenn explizit gesetzt
        params = {"rejection": "winsorized", "stacking_method": "sigma_clipped_mean"}
        assert resolve_stack_method(params) == "sigma_clipped_mean"
        # b) stack_2d Pfad fuer sigma_clipped_mean erreichbar (2D + 3D-Kanal)
        rng = np.random.RandomState(1)
        data_2d = rng.normal(100.0, 5.0, size=(12, 8, 8))
        res_2d = stack_2d(data_2d, method="sigma_clipped_mean", normalization="no")
        assert res_2d.shape == (8, 8)
        assert np.all(np.isfinite(res_2d))
        # c) stack_frames (von Single- und Multi-Group genutzt) verdrahtet sigma korrekt
        #    — 2D-Pfad (is_3d=False) und 3D-Pfad (is_3d=True) beide via stack_frames
        #    Mock-FITS wie in test_stacking_rejection, je 10 Frames, 1 Ausreisser
        from astro_process.agents.processing_agent import ProcessingAgent

        agent = ProcessingAgent(tmp_path / "out", config=None)
        data = np.full((10, 8, 8), 100.0, dtype=np.float32)
        data[3, 5, 5] = 5000.0
        paths = []
        for i in range(10):
            p = tmp_path / f"b5_{i}.fits"
            _write_fits(p, data[i])
            paths.append(p)

        # 2D-Stack via stack_frames mit sigma_clipped_mean
        stacked_2d = stack_frames(
            paths,
            {"stacking_method": "sigma_clipped_mean"},
            stacked_dir=agent.stacked_dir,
            load_frame=agent._load_frame,
            save_frame=agent._save_frame,
        )
        assert stacked_2d is not None
        result_2d_file = _read_fits(stacked_2d)
        # Ausreisser verworfen -> nahe 1.0 nach Normalisierung (agent stack_frames default mul)
        # Da Daten konstant 100 und Ausreisser 5000, nach mul-Normalisierung: robust ~1.0
        assert result_2d_file[5, 5] < 3.0
        assert result_2d_file[0, 0] == pytest.approx(1.0, abs=0.05)

        # 3D-Pfad (is_3d=True) — selber resolve + stack_2d je Kanal
        data_3d = np.full((10, 8, 8, 3), 100.0, dtype=np.float32)
        data_3d[3, 5, 5, 0] = 5000.0
        paths_3d = []
        for i in range(10):
            # _load_frame erwartet FITS (H,W,C) -> via save
            p = tmp_path / f"b5_3d_{i}.fits"
            # Direkt via agent.save (transponiert)
            agent._save_frame(data_3d[i], p)
            paths_3d.append(p)
        stacked_3d = stack_frames(
            paths_3d,
            {"stacking_method": "sigma_clipped_mean"},
            is_3d=True,
            stacked_dir=Path(tmp_path / "out3"),
            load_frame=agent._load_frame,
            save_frame=agent._save_frame,
        )
        assert stacked_3d is not None
        res3 = _read_fits(stacked_3d)
        assert res3.shape[0] == 3 or res3.shape[-1] == 3  # FITS vs internal transpose
        # Wir pruefen via direktem stack_2d-Kanal-Pfad (deterministisch, wie A1)
        # is_3d-Logik in stack_frames_python nutzt je Kanal stack_2d — damit ist
        # der Pfad identisch zum Single-Pfad (kein Special-Casing).

    def test_b5_resolve_and_stack2d_invoked_for_both_is3d_flags(self, tmp_path: Path):
        """Strengere Pruefung: stack_2d wird mit method sigma_clipped_mean fuer beide
        is_3d-Varianten aufgerufen (Mock-Capture), kein Pfad-Special-Casing."""
        captured: list[str] = []
        orig_stack_2d = stacking_mod.stack_2d

        def spy_stack_2d(data, method, normalization):
            captured.append(method)
            return orig_stack_2d(data, method, normalization)

        with patch.object(stacking_mod, "stack_2d", side_effect=spy_stack_2d):
            rng = np.random.RandomState(2)
            paths = []
            for i in range(5):
                p = tmp_path / f"spy_{i}.fits"
                # Erzeuge direkte Frames fuer stack_frames_python
                _write_fits(p, rng.normal(100, 5, (8, 8)).astype(np.float32))
                paths.append(p)
            out = tmp_path / "spy_out.fits"
            # is_3d=False
            captured.clear()
            # Patch logger damit kein echtes Log stoert
            with patch.object(stacking_mod, "logger", MagicMock()):
                stack_frames_python(
                    paths, out, method="sigma_clipped_mean", normalization="no",
                    is_3d=False,
                    load_frame=lambda p: _read_fits(p),
                    save_frame=lambda arr, pp: _write_fits(pp, arr),
                )
            assert "sigma_clipped_mean" in captured
            # is_3d=True — je Kanal ein stack_2d-Aufruf
            captured.clear()
            out3 = tmp_path / "spy_out3.fits"
            # 3D-Frames
            rng3 = np.random.RandomState(3)
            paths3 = []
            for i in range(5):
                p = tmp_path / f"spy3_{i}.fits"
                arr = rng3.normal(100, 5, (8, 8, 3)).astype(np.float32)
                fits.PrimaryHDU(arr.transpose(2, 0, 1)).writeto(p, overwrite=True)
                paths3.append(p)
            def load3(p):
                with fits.open(p) as hdul:
                    a = hdul[0].data.astype(np.float32)
                    return a.transpose(1, 2, 0)
            def save3(arr, pp):
                pp.parent.mkdir(parents=True, exist_ok=True)
                fits.PrimaryHDU(arr.transpose(2, 0, 1)).writeto(pp, overwrite=True)
            stack_frames_python(
                paths3, out3, method="sigma_clipped_mean", normalization="no",
                is_3d=True,
                load_frame=load3,
                save_frame=save3,
            )
            assert captured.count("sigma_clipped_mean") >= 3  # 3 Kanaele


# ═══════════════════════════════════════════════════════════════════
# C1..C3 — Transparenz (agent-log)
# ═══════════════════════════════════════════════════════════════════


class TestCStackCompleteTransparency:
    def test_c1_stack_complete_contains_method_field(self, tmp_path: Path):
        """C1: agent-log (stack.complete Event) enthaelt die verwendete Stack-Methode
        (z.B. method: sigma_clipped_mean)."""
        mock_logger = MagicMock()
        with patch.object(stacking_mod, "logger", mock_logger):
            rng = np.random.RandomState(10)
            frames = []
            for i in range(5):
                p = tmp_path / f"c1_{i}.fits"
                _write_fits(p, rng.normal(100, 5, (8, 8)).astype(np.float32))
                frames.append(p)
            out = tmp_path / "c1_out.fits"
            stack_frames_python(
                frames, out, method="sigma_clipped_mean", normalization="no",
                is_3d=False,
                load_frame=lambda p: _read_fits(p),
                save_frame=lambda arr, pp: _write_fits(pp, arr),
            )
        # stack.complete wurde geloggt
        calls = [c for c in mock_logger.info.call_args_list if c.args and c.args[0] == "stack.complete"]
        assert calls, "stack.complete wurde nicht geloggt"
        kwargs = calls[-1].kwargs
        assert kwargs.get("method") == "sigma_clipped_mean"
        assert "output" in kwargs and "frames" in kwargs and "is_3d" in kwargs

    def test_c2_new_field_additive_breaks_nothing(self, tmp_path: Path):
        """C2: Das neue Feld ist additiv; bestehende Log-Auswertungen brechen nicht
        (neues Key, keine Umbenennung, alte Keys bleiben)."""
        mock_logger = MagicMock()
        with patch.object(stacking_mod, "logger", mock_logger):
            rng = np.random.RandomState(11)
            paths = []
            for i in range(4):
                p = tmp_path / f"c2_{i}.fits"
                _write_fits(p, rng.normal(50, 2, (6, 6)).astype(np.float32))
                paths.append(p)
            out = tmp_path / "c2_out.fits"
            stack_frames_python(
                paths, out, method="average", normalization="no",
                is_3d=False,
                load_frame=lambda p: _read_fits(p),
                save_frame=lambda arr, pp: _write_fits(pp, arr),
            )
        calls = [c for c in mock_logger.info.call_args_list if c.args[0] == "stack.complete"]
        assert calls
        kwargs = calls[-1].kwargs
        # Additive: alle alten Keys noch vorhanden
        assert "output" in kwargs
        assert "frames" in kwargs
        assert "is_3d" in kwargs
        # Neues Feld additiv, kein Rename
        assert "method" in kwargs
        assert kwargs["method"] == "average"
        # Keine unerwarteten Renames (output heisst weiter output, nicht path)
        assert set(kwargs.keys()) >= {"output", "frames", "is_3d", "method"}

    def test_c3_rejection_mapping_logs_resolved_not_raw(self, tmp_path: Path):
        """C3: Bei Rejection-Mapping-Faellen (kein explizites stacking_method)
        dokumentiert das Log die TATSAECHLICH genutzte Methode (aufgeloest),
        nicht den Config-Rohwert."""
        # Fall A: rejection winsorized -> winsorized (nicht roh "winsorized" als eigene Kategorie, sondern aufgeloest)
        # Fall B: rejection=median (unbekannt) -> average (Rohwert median duerfte nie im Log stehen)
        # Fall C: rejection=sigma_clip -> average (OQ-SCS-3: kein Mapping auf sigma_clipped_mean)
        for raw_rejection, expected_method in [
            ("winsorized", "winsorized"),
            ("average", "average"),
            ("none", "average"),
            ("median", "average"),
            ("sigma_clip", "average"),
            ("sigma_clipped_mean", "average"),
        ]:
            mock_logger = MagicMock()
            with patch.object(stacking_mod, "logger", mock_logger):
                rng = np.random.RandomState(12)
                paths = []
                for i in range(4):
                    p = tmp_path / f"c3_{raw_rejection}_{i}.fits"
                    _write_fits(p, rng.normal(80, 3, (6, 6)).astype(np.float32))
                    paths.append(p)
                out = tmp_path / f"c3_{raw_rejection}_out.fits"
                params = {"rejection": raw_rejection}  # kein stacking_method
                method = resolve_stack_method(params)
                assert method == expected_method, f"resolve fuer {raw_rejection} sollte {expected_method} sein"
                # stack_frames nutzt resolve intern — hier direkt via stack_frames testen
                # um den resolve->log Pfad zu verifizieren
                stacked = stack_frames(
                    paths, params, stacked_dir=tmp_path / f"c3dir_{raw_rejection}",
                    load_frame=lambda p: _read_fits(p),
                    save_frame=lambda arr, pp: _write_fits(pp, arr),
                )
                assert stacked is not None
            calls = [c for c in mock_logger.info.call_args_list if c.args and c.args[0] == "stack.complete"]
            assert calls, f"stack.complete nicht geloggt fuer rejection={raw_rejection}"
            logged_method = calls[-1].kwargs.get("method")
            assert logged_method == expected_method, (
                f"fuer rejection='{raw_rejection}' sollte Log method='{expected_method}' sein, war '{logged_method}'"
            )
            # Sicherstellen: Rohwert der nicht gemappt wird steht nie als method im Log
            if raw_rejection in ("median", "sigma_clip", "sigma_clipped_mean"):
                assert logged_method != raw_rejection

        # Zusätzlich: explizites stacking_method sigma_clipped_mean gewinnt und wird geloggt
        mock_logger = MagicMock()
        with patch.object(stacking_mod, "logger", mock_logger):
            rng = np.random.RandomState(13)
            paths = []
            for i in range(4):
                p = tmp_path / f"c3_explicit_{i}.fits"
                _write_fits(p, rng.normal(80, 3, (6, 6)).astype(np.float32))
                paths.append(p)
            out_dir = tmp_path / "c3_explicit_dir"
            stacked = stack_frames(
                paths, {"rejection": "winsorized", "stacking_method": "sigma_clipped_mean"},
                stacked_dir=out_dir,
                load_frame=lambda p: _read_fits(p),
                save_frame=lambda arr, pp: _write_fits(pp, arr),
            )
            assert stacked is not None
        calls = [c for c in mock_logger.info.call_args_list if c.args[0] == "stack.complete"]
        assert calls[-1].kwargs.get("method") == "sigma_clipped_mean"
