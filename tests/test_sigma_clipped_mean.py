"""Batch 3a — AC-SCS-A1..A6 fuer sigma_clipped_mean (V1.7-3 SCS-A, OQ-SCS-1 A + OQ-SCS-2 A).

Spec: orion/knowledge-base/projects/astra/specs/v17-sigma-clipped-stack.md Abschnitt SCS-A.
Nur diese Datei, kein B/C, kein Frame-Selection.

AC-Zuordnung (je genau ein pytest-Test):
- A1: stack_2d(..., method="sigma_clipped_mean") liefert (H,W) + per-channel 3D-Pfad (Z.194-202)
- A2: Outlier-Verwerfen: +100σ in 1/N Frames -> <1σ Verschiebung ggü. Stack-ohne-Frame (Verwerfen, nicht Klemmen)
- A3: Defaults low=3.0/high=3.0/iterations=5, abweichende Werte akzeptiert
- A4: All-masked Pixel -> Median-Fallback, kein NaN
- A5: 2-Frame-Fall terminiert, ≈ Average wenn kein 3σ-Verletzung
- A6: Unbekannte method -> Fallback average (Bestandsverhalten Z.280-281)

Stil-Vorbild: tests/test_stacking_rejection.py (sys.path-Insert, reine numpy-Fixtures,
keine Imports aus tests/synthetic.py, tmp_path fuer 3D-Integration).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.core.stacking import sigma_clipped_mean, stack_2d, stack_frames_python


# ── AC-SCS-A1 ────────────────────────────────────────────────────────────────


def test_ac_scs_a1_stack_2d_shape_and_per_channel_3d(tmp_path: Path):
    """AC-SCS-A1: stack_2d(..., method='sigma_clipped_mean') liefert (H,W);
    bei 3D-Frames wird je Kanal unabhaengig gestackt (Z.194-202, per-channel-Pfad)."""
    # 2D-Teil: (N,H,W) -> (H,W)
    rng = np.random.RandomState(42)
    data_2d = rng.normal(100.0, 5.0, size=(12, 8, 8))
    result_2d = stack_2d(data_2d, method="sigma_clipped_mean", normalization="no")
    assert result_2d.shape == (8, 8)
    assert np.all(np.isfinite(result_2d))

    # 3D-Teil: is_3d-Pfad in stack_frames_python (je Kanal sigma_clipped_mean).
    # 20 Frames (genug fuer 3σ-Rejection, vgl. Lessons SCS-A Risiko N<8) —
    # Outlier nur in Kanal 0, Kanaele 1/2 bleiben sauber -> Nachweis der
    # Kanal-Unabhaengigkeit.
    n_frames, h, w, c = 20, 8, 8, 3
    data_3d = np.full((n_frames, h, w, c), 100.0, dtype=np.float64)
    data_3d[0, 5, 5, 0] = 5000.0  # harter Ausreisser nur in Kanal 0

    captured: dict = {}

    def load_frame(p: Path) -> np.ndarray:
        idx = int(p.name.split("_")[1].split(".")[0])
        return data_3d[idx]

    def save_frame(arr: np.ndarray, path: Path) -> None:
        captured["arr"] = arr
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()

    paths = [Path(f"frame_{i}.fits") for i in range(n_frames)]
    out = tmp_path / "stacked.fits"
    stack_frames_python(
        paths,
        out,
        method="sigma_clipped_mean",
        normalization="no",
        is_3d=True,
        load_frame=load_frame,
        save_frame=save_frame,
    )

    result_3d = captured["arr"]
    assert result_3d.shape == (h, w, c)
    assert np.all(np.isfinite(result_3d))
    # Kanal 0: Outlier verworfen -> nahe 100 (nicht 5000, nicht 916 wie bei N=6)
    assert result_3d[5, 5, 0] == pytest.approx(100.0, abs=1e-6)
    # Kanaele 1/2: unberuehrt -> exakt 100
    assert result_3d[5, 5, 1] == pytest.approx(100.0, abs=1e-9)
    assert result_3d[5, 5, 2] == pytest.approx(100.0, abs=1e-9)
    # Kontrolle: Kanal 1 ohne Outlier bleibt auch an anderer Position sauber
    assert result_3d[0, 0, 1] == pytest.approx(100.0, abs=1e-9)


# ── AC-SCS-A2 ────────────────────────────────────────────────────────────────


def test_ac_scs_a2_outlier_rejection_not_clamping():
    """AC-SCS-A2: +100σ-Pixel in 1/N Frames ist im Ergebnis <1σ von
    Stack-ohne-Frame (Verwerfen, nicht Klemmen). Smoke-Probe formalisiert."""
    rng = np.random.RandomState(0)
    n, h, w = 20, 8, 8
    # Basis: normalverteiltes Rauschen um 100, σ≈5
    data = rng.normal(100.0, 5.0, size=(n, h, w))
    clean_data = data[1:]  # ohne Frame 0 (Referenz)
    clean_mean = np.mean(clean_data, axis=0)
    clean_std = np.std(clean_data, axis=0)

    outlier = data.copy()
    # +100σ Ausreisser (Satellitenpixel) in genau einem Frame
    # Nimm σ am Zielpixel aus clean_std, setze Wert weit ausserhalb 3σ.
    sigma_at_pixel = float(clean_std[5, 5])
    assert sigma_at_pixel > 1.0  # sanity: Streuung vorhanden
    outlier[0, 5, 5] = 100.0 + 100 * sigma_at_pixel  # ~600-800
    # Alternativ harter Wert 5000 — ebenfalls >3σ, beide muessen verworfen werden
    # Hier 5000 verwenden fuer robuste Rejection (N=20 reicht, siehe N=6-Nuance)
    outlier[0, 5, 5] = 5000.0

    result = sigma_clipped_mean(outlier, low_sigma=3.0, high_sigma=3.0, iterations=5)
    avg = np.mean(outlier, axis=0)

    # Verworfen: Ergebnis nahe am Clean-Mean (<1σ)
    diff_clipped = abs(float(result[5, 5] - clean_mean[5, 5]))
    assert diff_clipped < float(clean_std[5, 5]), (
        f"sigma_clipped_mean sollte Outlier verwerfen: diff {diff_clipped:.3f} >= σ {clean_std[5,5]:.3f}"
    )
    # Gegenprobe: Average waere deutlich verschoben (>1σ), Test nicht vakant
    diff_avg = abs(float(avg[5, 5] - clean_mean[5, 5]))
    assert diff_avg > float(clean_std[5, 5]), "Average-Gegenprobe muss flippen (Test nicht vakant)"
    # Zusaetzlich: Ergebnis weit unter Average (Klemmen wuerde Restanteil lassen)
    assert float(result[5, 5]) < float(avg[5, 5]) - float(clean_std[5, 5])


# ── AC-SCS-A3 ────────────────────────────────────────────────────────────────


def test_ac_scs_a3_defaults_and_custom_values_accepted():
    """AC-SCS-A3: Defaults low=3.0/high=3.0/iterations=5 (Backlog-Vorgabe);
    abweichende Werte werden akzeptiert."""
    sig = inspect.signature(sigma_clipped_mean)
    assert sig.parameters["low_sigma"].default == pytest.approx(3.0)
    assert sig.parameters["high_sigma"].default == pytest.approx(3.0)
    assert sig.parameters["iterations"].default == 5

    rng = np.random.RandomState(7)
    data = rng.normal(50.0, 3.0, size=(10, 4, 4))

    # Defaults liefern finites (H,W)
    res_default = sigma_clipped_mean(data)
    assert res_default.shape == (4, 4)
    assert np.all(np.isfinite(res_default))

    # Abweichende Werte akzeptiert und terminieren (kein TypeError)
    res_custom = sigma_clipped_mean(data, low_sigma=2.0, high_sigma=2.0, iterations=2)
    assert res_custom.shape == (4, 4)
    assert np.all(np.isfinite(res_custom))

    # Noch schwaecheres Clipping (1σ, 1 Iteration) ebenfalls ok
    res_weak = sigma_clipped_mean(data, low_sigma=1.0, high_sigma=1.0, iterations=1)
    assert np.all(np.isfinite(res_weak))

    # Asymmetrische low/high ebenfalls akzeptiert
    res_asym = sigma_clipped_mean(data, low_sigma=2.5, high_sigma=3.5, iterations=5)
    assert np.all(np.isfinite(res_asym))


# ── AC-SCS-A4 ────────────────────────────────────────────────────────────────


def test_ac_scs_a4_all_masked_median_fallback_no_nan():
    """AC-SCS-A4: Pixel mit ausschliesslich maskierten Werten -> Median-Fallback, kein NaN."""
    # Fall 1: Normalfall mit Defaults darf nie NaN liefern (auch bei Hotpixel)
    rng = np.random.RandomState(11)
    data = rng.normal(100.0, 5.0, size=(12, 6, 6))
    data[0, 2, 2] = 5000.0
    res = sigma_clipped_mean(data)
    assert np.all(np.isfinite(res)), "Defaults duerfen kein NaN liefern"
    assert not np.any(np.isnan(res))

    # Fall 2: Erzwungen all-masked via low=0/high=0 (nur exakter Median bleibt).
    # Bei (2,1,1) mit [0,10] ist Median 5, σ=5, low=high=5 -> beide Werte ausserhalb -> all-masked.
    data_all_masked = np.array([[[0.0]], [[10.0]]])  # shape (2,1,1)
    res_forced = sigma_clipped_mean(data_all_masked, low_sigma=0.0, high_sigma=0.0, iterations=5)
    assert np.all(np.isfinite(res_forced)), "All-masked muss via Median-Fallback finite sein"
    assert res_forced[0, 0] == pytest.approx(5.0, abs=1e-9), "Fallback ist Pixel-Median der Originaldaten"

    # Fall 3: Konstante Frames (σ=0) -> low==high==med, aber alle Werte == med -> kein all-masked, finite
    const = np.full((5, 4, 4), 42.0)
    res_const = sigma_clipped_mean(const)
    assert np.allclose(res_const, 42.0)
    assert np.all(np.isfinite(res_const))

    # stack_2d-Pfad ebenfalls kein NaN (Normalization no)
    res_via_stack2d = stack_2d(data_all_masked, method="sigma_clipped_mean", normalization="no")
    # data_all_masked via stack_2d mit Defaults wird nicht all-masked (3σ), aber muss finite sein
    assert np.all(np.isfinite(res_via_stack2d))


# ── AC-SCS-A5 ────────────────────────────────────────────────────────────────


def test_ac_scs_a5_two_frames_terminates_and_approx_average():
    """AC-SCS-A5: Bei 2 Frames (Minimum laut stack_frames Z.137) terminiert die
    Methode ohne Fehler; Ergebnis ≈ Average wenn kein Wert die 3σ-Grenze verletzt."""
    # 2 Frames mit kleiner Abweichung (<3σ): beide bleiben, Mean ≈ sigma_clipped_mean
    data = np.full((2, 8, 8), 100.0, dtype=np.float64)
    data[0, 3, 3] = 100.0
    data[1, 3, 3] = 102.0  # Δ=2, σ≈1 -> low≈98 high≈104 -> beide drin
    res = sigma_clipped_mean(data)
    avg = np.mean(data, axis=0)
    assert res.shape == (8, 8)
    assert np.all(np.isfinite(res))
    assert float(res[3, 3]) == pytest.approx(float(avg[3, 3]), abs=1e-9)

    # Via stack_2d ebenfalls terminiert und identisch
    res2 = stack_2d(data, method="sigma_clipped_mean", normalization="no")
    assert np.allclose(res2, avg)

    # Auch glatte 2-Frame-Konstanz terminiert
    const2 = np.full((2, 4, 4), 77.0)
    assert np.allclose(sigma_clipped_mean(const2), 77.0)


# ── AC-SCS-A6 ────────────────────────────────────────────────────────────────


def test_ac_scs_a6_unknown_method_fallback_to_average():
    """AC-SCS-A6: Unbekannte method-Strings fallen auf average zurueck (Z.280-281)."""
    rng = np.random.RandomState(99)
    data = rng.normal(20.0, 2.0, size=(8, 6, 6))
    expected = np.mean(data, axis=0)

    for bogus in ["bogus", "SIGMA", "unknown_method", ""]:
        result = stack_2d(data, method=bogus, normalization="no")
        assert result.shape == expected.shape
        assert np.allclose(result, expected), f"Fallback fuer '{bogus}' muss average sein"

    # Kontrolle: sigma_clipped_mean selbst unterscheidet sich bei Outlier vom Average
    # (N=20, damit 3σ-Rejection greift — bei N=8 wuerde σ-Inflation den Outlier
    # einschliessen: High ~ med+3·outlier/√N, N>9 noetig fuer Rejection)
    rng2 = np.random.RandomState(101)
    data_large = rng2.normal(20.0, 2.0, size=(20, 6, 6))
    data_large[0, 3, 3] = 5000.0
    clipped2 = stack_2d(data_large, method="sigma_clipped_mean", normalization="no")
    avg_large = np.mean(data_large, axis=0)
    assert not np.allclose(clipped2, avg_large), "sigma_clipped_mean muss sich bei hartem Outlier vom Average unterscheiden"
    # CLIppped muss naeher am Clean-Mean liegen als Average
    clean_large = np.mean(data_large[1:], axis=0)
    assert abs(float(clipped2[3, 3] - clean_large[3, 3])) < abs(float(avg_large[3, 3] - clean_large[3, 3]))
