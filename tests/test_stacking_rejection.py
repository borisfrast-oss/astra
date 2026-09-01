"""Leo-Auftrag 2026-08-10 (Bad-Pixel-Korrektur, Teil B): Rejection-Mapping +
Winsor-Sigma (Siril-Stil) + CLI-Flag --stacking-method.

Eigene minimale FITS-Fixtures (keine Imports aus tests/synthetic.py) —
Stil wie tests/test_dark_offset_nan_guard.py.

Abdeckung:
- Rejection-Mapping (resolve_stack_method): winsorized->winsorized,
  average->average, none->average, Default->average; explizites
  stacking_method (Preset/Config/CLI) gewinnt ueber das Mapping
  (stella-Diagnose C20: rejection wurde nirgends verarbeitet, der Stack
  lief mit purem Average).
- Winsor-Sigma (winsorized_sigma_clip + stack_2d "winsorized"):
  transiente Ausreisser (Satellit/Flugzeug/einzelner Hotpixel) werden
  winsorisiert, echte Werte bleiben; Flip-Garantie (Ray-Lesson 9):
  Wert ausserhalb des gemessenen Bereichs flippt nachweislich — die
  Gegenprobe mit average flippt, d.h. der Test ist nicht vakant
  (false green); iterativ staerker als der fruehere Perzentil-Clip
  5/95 + Mean (stella Z. 62-63: "nicht nur Perzentil-Clip").
- CLI-Flag --stacking-method (analog --merge-method): Precedence
  CLI > Preset/Config > Rejection-Mapping (Dry-Run-Log
  cli.process.stacking, Muster wie tests/test_config_registration.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from click.testing import CliRunner

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.agents.processing_agent import ProcessingAgent
from astro_process.core.stacking import (
    resolve_stack_method,
    stack_2d,
    stack_frames,
    winsorized_sigma_clip,
)
from astro_process.cli import cli


def _write_fits(path: Path, data: np.ndarray) -> None:
    """Write a 2D FITS file (float32)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(np.asarray(data, dtype=np.float32)).writeto(path, overwrite=True)


def _read_fits(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        return np.asarray(hdul[0].data, dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════
# Teil B1 — Rejection-Mapping (resolve_stack_method + stack_frames)
# ═══════════════════════════════════════════════════════════════════


class TestRejectionMapping:
    """Teil B1: `rejection` aus Preset/Config auf die `stack_2d`-Methode
    mappen (stella-Vorgabe: winsorized->winsorized, average->average,
    none->average)."""

    def test_winsorized_rejection_maps_to_winsorized(self):
        """nebula_standard-Fall (stella-Diagnose C20): rejection
        "winsorized" -> Methode winsorized (vorher: Average)."""
        assert resolve_stack_method({"rejection": "winsorized"}) == "winsorized"

    def test_average_rejection_maps_to_average(self):
        assert resolve_stack_method({"rejection": "average"}) == "average"

    def test_none_rejection_maps_to_average(self):
        assert resolve_stack_method({"rejection": "none"}) == "average"

    def test_missing_params_default_to_average(self):
        """Ohne rejection/stacking_method bleibt das bisherige
        Fallback-Verhalten (Average)."""
        assert resolve_stack_method({}) == "average"
        assert resolve_stack_method({"normalization": "mul"}) == "average"

    def test_unknown_rejection_defaults_to_average(self):
        """Unbekannter rejection-Wert -> Average (konservativ, v1.3)."""
        assert resolve_stack_method({"rejection": "median"}) == "average"

    def test_explicit_stacking_method_beats_rejection(self):
        """Explizites stacking_method (Preset/Config/CLI --stacking-method)
        gewinnt ueber das Rejection-Mapping (Precedence CLI > Preset/Config
        > Mapping)."""
        assert resolve_stack_method(
            {"rejection": "winsorized", "stacking_method": "median"}
        ) == "median"
        assert resolve_stack_method(
            {"rejection": "winsorized", "stacking_method": "weighted"}
        ) == "weighted"
        assert resolve_stack_method(
            {"rejection": "winsorized", "stacking_method": "average"}
        ) == "average"

    def test_stack_frames_wires_rejection_to_method(self, tmp_path: Path):
        """End-to-End-Verdrahtung: `stack_frames` mit params
        {"rejection": "winsorized"} (Preset-Mapping) -> der Stack ist ein
        Winsor-Sigma-Stack (transienter Ausreisser winsorisiert), nicht
        Average. 10 Frames, 1 Frame mit 5000-DN-Ausreisser bei (5,5):
        Average ~5.9 (normalisiert), Winsor ~1.5 -> Ergebnis deutlich
        unter 3.0 belegt die Verdrahtung."""
        agent = ProcessingAgent(tmp_path / "out", config=None)
        data = np.full((10, 8, 8), 100.0, dtype=np.float32)
        data[3, 5, 5] = 5000.0  # transiente Ausreisser (Satellit/HP)
        frames = []
        for i in range(10):
            p = tmp_path / f"f{i}.fits"
            _write_fits(p, data[i])
            frames.append(p)

        stacked = stack_frames(
            frames, {"rejection": "winsorized"},
            stacked_dir=agent.stacked_dir,
            load_frame=agent._load_frame,
            save_frame=agent._save_frame,
        )

        assert stacked is not None
        result = _read_fits(stacked)
        # Ausreisser-Pixel: winsorisiert (nahe robustem Wert ~1.5 nach
        # Normalisierung), nicht Average (~5.9)
        assert result[5, 5] < 3.0
        assert result[5, 5] > 0.5
        # Pixel ohne Ausreisser: echte Werte bleiben (~1.0 nach Norm)
        assert result[0, 0] == pytest.approx(1.0, abs=1e-3)


# ═══════════════════════════════════════════════════════════════════
# Teil B2 — Winsor-Sigma (iterativ, Siril-Stil)
# ═══════════════════════════════════════════════════════════════════


class TestWinsorSigma:
    """Teil B2: echtes iteratives Winsor-Sigma (nicht Perzentil-Clip 5/95
    + Mean). Entfernt transiente Ausreisser, echte Werte bleiben."""

    def test_transient_outlier_winsorized_real_values_kept(self):
        """Satellit/Flugzeug/einzelner Hotpixel: 1 von 20 Frames hat bei
        (5,5) einen 5000-DN-Ausreisser -> Winsor-Sigma-Ergebnis nahe dem
        echten Wert (100), Average wird deutlich verfaelscht (345)."""
        data = np.full((20, 8, 8), 100.0)
        data[19, 5, 5] = 5000.0

        result = winsorized_sigma_clip(data)
        average = np.mean(data, axis=0)

        # Ausreisser-Pixel: nahe dem echten Wert, weit unter Average
        assert result[5, 5] < 120.0
        assert result[5, 5] > 95.0
        assert average[5, 5] > 300.0  # Gegenprobe: Average flippt
        # Pixel ohne Ausreisser: echte Werte bleiben (identische Frames
        # -> sigma 0 -> exakt 100)
        assert result[0, 0] == pytest.approx(100.0, abs=1e-9)

    def test_flip_guarantee_outside_measured_range(self):
        """Ray-Lesson 9 (Flip-Garantie): der Ausreisser-Wert liegt
        AUSSERHALB des gemessenen Bereichs der guten Frames
        ([100, 100]) und flippt nachweislich — das Ergebnis liegt
        nahe am Messbereich, nicht am Ausreisser. Die Average-
        Gegenprobe verfehlt den Messbereich klar (Test ist nicht
        vakant / false green)."""
        good = np.full((19, 8, 8), 100.0)
        measured_min, measured_max = 100.0, 100.0
        outlier_frame = np.full((1, 8, 8), 100.0)
        outlier_value = 5000.0  # > measured_max: ausserhalb des Bereichs
        outlier_frame[0, 5, 5] = outlier_value
        data = np.concatenate([good, outlier_frame], axis=0)

        result = winsorized_sigma_clip(data)
        average = np.mean(data, axis=0)

        # Flip-Garantie: Ausreisser taucht NICHT im Ergebnis auf
        assert result[5, 5] != pytest.approx(outlier_value, abs=1.0)
        assert result[5, 5] < outlier_value / 10.0
        # Ergebnis nahe am gemessenen Bereich (Toleranz dokumentiert die
        # Winsorisierung; reine Rejection/Median waeren exakt 100)
        assert abs(result[5, 5] - measured_max) < 10.0
        # Gegenprobe: Average bliebe weit ausserhalb des Messbereichs
        assert average[5, 5] > 300.0

    def test_winsorized_stronger_than_percentile_clip(self):
        """Qualitaet (stella Z. 62-63): der fruehere Perzentil-Clip 5/95 +
        Mean klemmt den 150er-Wert nur auf p95 (~127.5) und liefert
        ~102.75; das iterative Winsor-Sigma zieht ihn ueber 5 Iterationen
        weiter Richtung Median (~100.5). Winsor < Perzentil-Clip belegt
        die iterative Wirksamkeit."""
        values = [100.0] * 9 + [150.0]
        data = np.full((10, 4, 4), 100.0)
        data[9] = 150.0  # ein Frame komplett +50 (moderat, aber Ausreisser)

        result = winsorized_sigma_clip(data)

        # Referenz: alte Perzentil-Clip-Implementierung (nur Doku)
        p5, p95 = np.percentile(data, [5, 95], axis=0)
        clipped = np.clip(data, p5, p95)
        percentile_result = np.mean(clipped, axis=0)

        average_result = np.mean(data, axis=0)

        # Winsor-Sigma naeher am robusten Wert als Perzentil-Clip und
        # Average; der Pixelwert (alle 4 Pixel identisch) ist aussagekraeftig
        assert result[0, 0] < percentile_result[0, 0]
        assert result[0, 0] < average_result[0, 0]
        assert abs(result[0, 0] - 100.0) < abs(average_result[0, 0] - 100.0)
        # konkrete Zahlen (siehe Doku oben): ~100.5 < ~102.75 < 105.0
        assert result[0, 0] < 101.5
        assert percentile_result[0, 0] > 102.5
        assert average_result[0, 0] == pytest.approx(105.0, abs=1e-9)

    def test_winsorized_through_stack_2d(self):
        """`stack_2d(data, "winsorized", ...)` ist erreichbar (stella:
        "nicht erreichbar" Problem) und entspricht dem Winsor-Sigma-Stack."""
        data = np.full((20, 8, 8), 100.0)
        data[19, 5, 5] = 5000.0

        result = stack_2d(data, method="winsorized", normalization="no")
        expected = winsorized_sigma_clip(data)

        assert np.allclose(result, expected)
        assert result[5, 5] < 120.0

    def test_winsorized_constant_frames_finite(self):
        """Edge: alle Frames identisch (sigma 0) -> Ergebnis exakt der
        Wert, finite (Final-Export-Guard bleibt gruen)."""
        data = np.full((5, 8, 8), 42.0)
        result = winsorized_sigma_clip(data)
        assert np.all(np.isfinite(result))
        assert np.allclose(result, 42.0)


# ═══════════════════════════════════════════════════════════════════
# Teil B3 — CLI-Flag --stacking-method (Precedence CLI > Preset/Config)
# ═══════════════════════════════════════════════════════════════════


class TestCliStackingFlag:
    """Teil B3: --stacking-method (analog --merge-method). Precedence
    CLI > Preset/Config > Rejection-Mapping (Dry-Run-Log
    cli.process.stacking, Muster wie test_config_registration.py)."""

    @staticmethod
    def _create_light_target(root: Path) -> Path:
        """Minimales Target mit einem synthetischen Light-FITS (fuer
        dry-run). Discovery laeuft echt (liest Header), die Pipeline wird
        nicht ausgefuehrt."""
        target = root / "TestTarget"
        target.mkdir(parents=True, exist_ok=True)
        rng = np.random.RandomState(7)
        data = (50.0 + rng.uniform(0, 10, (64, 64))).astype(np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["EXPTIME"] = 15.0
        hdu.header["GAIN"] = 60
        hdu.writeto(target / "light_0001.fits", overwrite=True)
        return target

    def test_cli_preset_rejection_maps_without_flag(self, tmp_path):
        """Kern-Akzeptanz (stella-Diagnose C20): nebula_standard
        (rejection "winsorized") OHNE Flag -> effektive Methode
        winsorized (vorher lief der Preset mit purem Average)."""
        target = self._create_light_target(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--preset", "nebula_standard"]
        )
        assert result.exit_code == 0, result.output
        assert "cli.process.stacking" in result.output
        assert '"method": "winsorized"' in result.output

    def test_cli_flag_overrides_preset_rejection(self, tmp_path):
        """Precedence e2e: nebula_standard (rejection winsorized) + CLI
        --stacking-method median -> median gewinnt (CLI > Preset/Mapping);
        rejection bleibt im Log sichtbar (nicht veraendert)."""
        target = self._create_light_target(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["process", str(target), "--dry-run", "--preset", "nebula_standard",
             "--stacking-method", "median"],
        )
        assert result.exit_code == 0, result.output
        assert "cli.process.stacking" in result.output
        assert '"method": "median"' in result.output
        assert '"rejection": "winsorized"' in result.output

    def test_cli_flag_overrides_config_stacking_method(self, tmp_path):
        """Precedence e2e: Config/Preset stacking_method "weighted" + CLI
        --stacking-method average -> average gewinnt (CLI > Config)."""
        import yaml

        from astro_process.config.loader import DEFAULT_CONFIG

        data = yaml.safe_load(DEFAULT_CONFIG)
        for preset in data["pipeline_presets"]:
            if preset["name"] == "star_standard":
                preset["processing_params"]["stacking_method"] = "weighted"
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        target = self._create_light_target(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["-c", str(cfg_path), "process", str(target), "--dry-run",
             "--preset", "star_standard", "--stacking-method", "average"],
        )
        assert result.exit_code == 0, result.output
        assert "cli.process.stacking" in result.output
        assert '"method": "average"' in result.output

    def test_cli_flag_invalid_choice_rejected(self, tmp_path):
        """Ungueltiger --stacking-method-Wert -> Click-Validation (Exit 2),
        kein stiller Fallback."""
        target = self._create_light_target(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["process", str(target), "--dry-run", "--stacking-method", "bogus"]
        )
        assert result.exit_code == 2
        assert "bogus" in result.output
