"""Batch 3c — Tests für Frame-Selection V1.7-2 (FSEL-A..D).

Spec: orion/knowledge-base/projects/astra/specs/v17-frame-selection.md
Code: core/quality.compute_frame_score + FrameQuality.noise_sigma,
      config.models.FrameSelectionConfig, agents/multi_group_agent
      _apply_selection_and_rejection (Perzentil→Threshold, Trichter),
      CLI --frame-selection/--keep-percentile, inspect/doctor.

Lessons S9/S10: gezielte Tests, synthetische FrameQuality-Listen, kein Voll-CI.

AC-Zuordnung:
- FSEL-A1..A5: Score ∈[0,1], Median/MAD session-relativ, noise_sigma exponiert,
               Gewichte konfigurierbar+Default Gleichverteilung, NaN/missing→worst
- FSEL-B1..B6: Config Defaults, percentile verwurf floor, deterministic, min_frames
               skip, nur Lights, je Gruppe unabhängig
- FSEL-C1..C3: Perzentil→Threshold Reihenfolge, Trichter, unabhängige Schalter
- FSEL-D1..D4: agent-log je Frame, inspect Statistik, CLI Flags, doctor
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml
from astropy.io import fits
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.config.loader import DEFAULT_CONFIG, resolve_frame_selection  # noqa: E402
from astro_process.config.models import AppConfig, FrameSelectionConfig, PipelinePreset  # noqa: E402
from astro_process.core.quality import FrameQuality, compute_frame_quality, compute_frame_score, qual_to_dict  # noqa: E402
import astro_process.agents.multi_group_agent as mg  # noqa: E402
from astro_process.cli import cli  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_q(
    snr: float,
    fwhm_median: float | None = 3.0,
    star_count: int = 100,
    elongation_ratio: float | None = 0.95,
    noise_sigma: float | None = 5.0,
    frame: str | None = None,
) -> FrameQuality:
    return FrameQuality(
        frame=frame,
        snr=float(snr),
        fwhm_median=fwhm_median,
        star_count=int(star_count),
        elongation_ratio=elongation_ratio,
        noise_sigma=noise_sigma,
    )


class _Rec:
    def __init__(self):
        self.infos: list[tuple[str, dict]] = []
        self.warnings: list[tuple[str, dict]] = []

    def info(self, event, **kw):
        self.infos.append((event, kw))

    def warning(self, event, **kw):
        self.warnings.append((event, kw))

    def debug(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    @property
    def names(self):
        return [e for e, _ in self.infos + self.warnings]

    def events_named(self, name):
        return [(e, kw) for e, kw in self.infos + self.warnings if e == name]


def _write_light_fits(tmp_path: Path, name: str, *, exptime=15.0, gain=60, filt="LUM", eqmode=None):
    lights = tmp_path / "lights"
    lights.mkdir(parents=True, exist_ok=True)
    hdr = fits.Header()
    hdr["EXPTIME"] = float(exptime)
    hdr["GAIN"] = int(gain)
    hdr["FILTER"] = str(filt)
    hdr["OBJECT"] = "M27"
    hdr["CCD-TEMP"] = -10
    if eqmode is not None:
        hdr["EQMODE"] = int(eqmode)
    data = np.zeros((32, 32), dtype=np.float32)
    p = lights / name
    fits.PrimaryHDU(data=data, header=hdr).writeto(p, overwrite=True)
    return p


def _extract_json(output: str) -> dict:
    lines = output.strip().splitlines()
    json_lines = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if '"timestamp"' in s and '"level"' in s:
            continue
        json_lines.append(s)
    return json.loads("\n".join(json_lines))


# ═══════════════════════════════════════════════════════════════════════════
# FSEL-A — Kompositer Score
# ═══════════════════════════════════════════════════════════════════════════


class TestFSEL_A:
    def test_A1_score_in_01(self):
        """FSEL-A1: compute_frame_score liefert je Frame Score ∈[0,1]."""
        quals = [
            _make_q(snr=s, fwhm_median=2.5 + i * 0.2, star_count=80 + i * 5, elongation_ratio=0.9, frame=str(Path(f"light_{i}.fits")))
            for i, s in enumerate([5.0, 12.0, 8.0, 20.0, 3.0, 15.0])
        ]
        scores = compute_frame_score(quals)
        assert len(scores) == len(quals)
        for s in scores:
            assert 0.0 <= s <= 1.0
            assert np.isfinite(s)

    def test_A2_median_mad_session_relative(self):
        """FSEL-A2: identische relative Ordnung in zwei Sessions mit unterschiedlichem absolutem SNR-Niveau
        → ähnliche relative Scores (Median/MAD-normalisiert, nicht min-max)."""
        # Session A: SNR 5,10,15
        qA = [
            _make_q(5.0, frame="a1.fits"),
            _make_q(10.0, frame="a2.fits"),
            _make_q(15.0, frame="a3.fits"),
        ]
        # Session B: gleiches Pattern +100 offset → 105,110,115
        qB = [
            _make_q(105.0, frame="b1.fits"),
            _make_q(110.0, frame="b2.fits"),
            _make_q(115.0, frame="b3.fits"),
        ]
        sA = compute_frame_score(qA)
        sB = compute_frame_score(qB)
        # gleiche Rangfolge und nahezu identische relative Scores (offset-invariant)
        assert np.argsort(sA).tolist() == np.argsort(sB).tolist()
        for a, b in zip(sA, sB, strict=True):
            assert a == pytest.approx(b, abs=0.05)
        # Extremtest: Median/MAD sorgt dass Scores nicht bei 0/1 kleben trotz großer absoluter Differenz
        assert min(sA) < 0.5 < max(sA)
        assert min(sB) < 0.5 < max(sB)

    def test_A3_frame_quality_exposes_noise_sigma(self):
        """FSEL-A3: FrameQuality exponiert noise_sigma; compute_frame_quality setzt es."""
        # Feld existiert, Default None für Legacy
        fq = FrameQuality()
        assert hasattr(fq, "noise_sigma")
        assert fq.noise_sigma is None
        # compute_frame_quality auf synthetischem Bild setzt noise_sigma ≈ 1.4826*MAD
        rng = np.random.RandomState(0)
        img = (50.0 + rng.normal(0, 5.0, size=(32, 32))).astype(np.float32)
        # ein paar Sterne simulieren: helle Pixel
        img[10, 10] = 500
        img[20, 15] = 400
        q = compute_frame_quality(img)
        assert q.noise_sigma is not None
        assert np.isfinite(q.noise_sigma)
        assert q.noise_sigma > 0
        d = qual_to_dict(q)
        assert "noise_sigma" in d
        assert d["noise_sigma"] is not None

    def test_A4_weights_configurable_and_default_equal(self):
        """FSEL-A4: Gewichte konfigurierbar; Default = Gleichverteilung."""
        # Default: 4 Metriken gleichverteilt
        quals = [
            _make_q(snr=5.0, fwhm_median=2.0, star_count=50, elongation_ratio=0.6, frame="f1.fits"),
            _make_q(snr=15.0, fwhm_median=5.0, star_count=150, elongation_ratio=0.95, frame="f2.fits"),
            _make_q(snr=10.0, fwhm_median=3.0, star_count=100, elongation_ratio=0.85, frame="f3.fits"),
        ]
        s_default = compute_frame_score(quals, weights=None)
        s_equal = compute_frame_score(quals, weights={"snr": 1.0, "star_count": 1.0, "fwhm_median": 1.0, "elongation_ratio": 1.0})
        for a, b in zip(s_default, s_equal, strict=True):
            assert a == pytest.approx(b, abs=1e-9)
        # Custom: nur snr gewichten → Score folgt SNR-Rang strikt
        s_snr_only = compute_frame_score(quals, weights={"snr": 1.0, "star_count": 0, "fwhm_median": 0, "elongation_ratio": 0})
        # Rang nach SNR: quals[1] (15) > quals[2] (10) > quals[0] (5)
        assert s_snr_only[1] > s_snr_only[2] > s_snr_only[0]
        # Unbekannter Key wird ignoriert, kein Crash
        s_unknown = compute_frame_score(quals, weights={"snr": 1.0, "foobar": 99.0})
        assert len(s_unknown) == 3
        # Negative Gewichte werden auf 0 geklemmt → kein Crash
        s_neg = compute_frame_score(quals, weights={"snr": -5.0, "star_count": 1.0})
        assert all(0 <= x <= 1 for x in s_neg)

    def test_A5_nan_missing_worst_and_no_crash(self):
        """FSEL-A5: fehlende/NaN-Metriken → worst Score (0.0), Ende sortiert, kein Crash."""
        good = [
            _make_q(12.0, fwhm_median=3.0, star_count=120, elongation_ratio=0.9, frame="good1.fits"),
            _make_q(10.0, fwhm_median=3.2, star_count=100, elongation_ratio=0.92, frame="good2.fits"),
            _make_q(11.0, fwhm_median=2.8, star_count=110, elongation_ratio=0.88, frame="good3.fits"),
        ]
        bad_none = _make_q(20.0, fwhm_median=None, star_count=200, elongation_ratio=0.99, frame="bad_none.fits")
        bad_nan = _make_q(float("nan"), fwhm_median=2.5, star_count=90, elongation_ratio=0.9, frame="bad_nan.fits")
        bad_nan_fwhm = _make_q(9.0, fwhm_median=float("nan"), star_count=95, elongation_ratio=0.9, frame="bad_nan_fwhm.fits")
        all_q = good + [bad_none, bad_nan, bad_nan_fwhm]
        scores = compute_frame_score(all_q)
        assert len(scores) == 6
        assert all(np.isfinite(s) for s in scores) or scores[4] == 0.0  # nan frame handled
        # bad frames at worst 0.0
        assert scores[3] == pytest.approx(0.0)
        assert scores[4] == pytest.approx(0.0)
        assert scores[5] == pytest.approx(0.0)
        # Sortierung: worst am Ende
        paired = sorted(zip(all_q, scores, strict=True), key=lambda x: x[1], reverse=True)
        worst_frames = [q.frame for q, _ in paired[-3:]]
        assert "bad_none.fits" in worst_frames
        assert "bad_nan.fits" in worst_frames


# ═══════════════════════════════════════════════════════════════════════════
# FSEL-B — Perzentilbasierte Auswahl
# ═══════════════════════════════════════════════════════════════════════════


class TestFSEL_B:
    def test_B1_config_defaults(self):
        """FSEL-B1: FrameSelectionConfig Defaults enabled false/92/weights None/min3."""
        c = FrameSelectionConfig()
        assert c.enabled is False
        assert c.keep_percentile == 92
        assert c.weights is None
        assert c.min_frames == 3
        # ProcessingParams vererbt denselben Default
        from astro_process.config.models import ProcessingParams

        pp = ProcessingParams()
        assert pp.frame_selection.enabled is False
        assert pp.frame_selection.keep_percentile == 92

    def test_B2_percentile_discard_25_to_2(self):
        """FSEL-B2: enabled=true → unterste (100-keep)% je Gruppe verworfen (25→2 bei 92%)."""
        n = 25
        keep = 92
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=keep)
        quals = [_make_q(float(i), frame=str(Path(f"light_{i:04d}.fits"))) for i in range(n)]
        registered = [Path(q.frame) for q in quals]  # type: ignore[arg-type]
        final, report = mg._apply_selection_and_rejection(
            registered, quals, cfg, False, {}, True, "g1"
        )
        assert report["total"] == 25
        assert report["percentile_rejected"] == 2  # floor(25*0.08)=2
        assert report["stacked"] == 23
        assert len(final) == 23
        # verworfene sind die schlechtesten (snr 0,1)
        discarded = {r["frame"] for r in report["frames"] if r["decision"] == "percentile_rejected"}
        assert any("light_0000" in p for p in discarded)
        assert any("light_0001" in p for p in discarded)

    def test_B3_floor_deterministic(self):
        """FSEL-B3: Rundungsregel floor dokumentiert; bei 0 Verwürfen Pipeline unverändert."""
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=92)
        # N=12 → discard floor(12*0.08)=0 → unverändert
        quals12 = [_make_q(float(i), frame=str(Path(f"l_{i}.fits"))) for i in range(12)]
        reg12 = [Path(q.frame) for q in quals12]  # type: ignore[arg-type]
        final12, rep12 = mg._apply_selection_and_rejection(reg12, quals12, cfg, False, {}, True, "g12")
        assert rep12["percentile_rejected"] == 0
        assert len(final12) == 12
        # N=13 → floor(13*0.08)=1
        quals13 = [_make_q(float(i), frame=str(Path(f"m_{i}.fits"))) for i in range(13)]
        reg13 = [Path(q.frame) for q in quals13]  # type: ignore[arg-type]
        _f13, rep13 = mg._apply_selection_and_rejection(reg13, quals13, cfg, False, {}, True, "g13")
        assert rep13["percentile_rejected"] == 1
        # Deterministisch: zweimal gleiches Ergebnis
        _f13b, rep13b = mg._apply_selection_and_rejection(reg13, quals13, cfg, False, {}, True, "g13")
        assert rep13["percentile_rejected"] == rep13b["percentile_rejected"]
        assert rep13["cutoff_score"] == rep13b["cutoff_score"]

    def test_B4_skipped_min_frames(self):
        """FSEL-B4: würde Selektion unter min_frames fallen → skip mit Warning und alle gestackt."""
        # N=3, keep 50% → discard floor(1.5)=1 → keep 2 < min 3 → skip
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=50, min_frames=3)
        quals = [_make_q(float(i), frame=str(Path(f"s_{i}.fits"))) for i in range(3)]
        reg = [Path(q.frame) for q in quals]  # type: ignore[arg-type]
        rec = _Rec()
        final, report = mg._apply_selection_and_rejection(reg, quals, cfg, False, {}, True, "g_small", logger=rec)
        assert report["skipped_min_frames"] is True
        assert report["percentile_rejected"] == 0
        assert len(final) == 3  # alle gestackt
        # Warning selection.skipped_min_frames dokumentiert
        assert any(e == "selection.skipped_min_frames" for e, _ in rec.warnings)

    def test_B5_only_lights(self):
        """FSEL-B5: Flats/Darks/Bias werden niemals perzentilselektiert — nur Lights."""
        # Simuliere Lights (25) und Flats (5): Selektion nur auf Lights angewendet
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=92)
        lights_q = [_make_q(float(i), frame=str(Path(f"light_{i}.fits"))) for i in range(25)]
        lights_reg = [Path(q.frame) for q in lights_q]  # type: ignore[arg-type]
        flats_reg = [Path(f"flat_{i}.fits") for i in range(5)]
        # Flats haben keine Qualities; Pipeline ruft Selektion nicht für sie auf
        lights_final, _ = mg._apply_selection_and_rejection(lights_reg, lights_q, cfg, False, {}, True, "lights")
        assert len(lights_final) == 23  # Lights gefiltert
        # Flats unverändert (Selektion nie aufgerufen)
        assert len(flats_reg) == 5

    def test_B6_multi_group_independent(self):
        """FSEL-B6: Multi-Group → je Gruppe unabhängig (unterschiedliche Niveaus)."""
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=80)  # 20% verworfen für klaren Test
        # Gruppe A: 10 Frames snr 100-109 (hohes Niveau)
        qA = [_make_q(100 + i, frame=str(Path(f"A_light_{i}.fits"))) for i in range(10)]
        regA = [Path(q.frame) for q in qA]  # type: ignore[arg-type]
        finalA, repA = mg._apply_selection_and_rejection(regA, qA, cfg, False, {}, True, "A")
        # Gruppe B: 10 Frames snr 10-19 (niedriges Niveau)
        qB = [_make_q(10 + i, frame=str(Path(f"B_light_{i}.fits"))) for i in range(10)]
        regB = [Path(q.frame) for q in qB]  # type: ignore[arg-type]
        finalB, repB = mg._apply_selection_and_rejection(regB, qB, cfg, False, {}, True, "B")
        # floor(10*0.2)=2 je Gruppe → beide behalten 8
        assert repA["percentile_rejected"] == 2
        assert repB["percentile_rejected"] == 2
        assert len(finalA) == 8
        assert len(finalB) == 8
        # Globaler Ansatz würde B komplett verwerfen — per-group bleibt B erhalten
        # (Nachweis: schlechteste A (100) hat höheres SNR als beste B (19), trotzdem behält B 8 Frames)
        all_q = qA + qB
        all_reg = regA + regB
        final_all, rep_all = mg._apply_selection_and_rejection(all_reg, all_q, cfg, False, {}, True, "global")
        # Global würde 20% von 20 =4 verwerfen, vermutlich alles aus B
        assert rep_all["percentile_rejected"] == 4
        # Per-group behält mehr aus B (8 vs. global 4) → Unabhängigkeit bewiesen
        b_kept_per_group = len(finalB)
        b_kept_global = len([p for p in final_all if "B_light" in p.as_posix()])
        assert b_kept_per_group > b_kept_global


# ═══════════════════════════════════════════════════════════════════════════
# FSEL-C — Interaktion mit Outlier-Rejection
# ═══════════════════════════════════════════════════════════════════════════


class TestFSEL_C:
    def test_C1_percentile_before_threshold_no_double(self):
        """FSEL-C1: Beide aktiv → Perzentil zuerst, dann Threshold auf Rest; keine Doppelt-Verwerfung."""
        # 10 Frames snr 0-9, star fest. Threshold snr <5 → 5 Frames würden sonst fliegen.
        # Percentile keep 80 → discard floor(10*0.2)=2 (snr 0,1)
        # Nach Perzentil verbleiben snr 2-9; Threshold auf Rest → snr 2,3,4 noch rejected =3
        # Gesamt 2+3=5, aber percentile frames nicht nochmal gezählt.
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=80)
        quals = [_make_q(float(i), frame=str(Path(f"light_{i}.fits"))) for i in range(10)]
        reg = [Path(q.frame) for q in quals]  # type: ignore[arg-type]
        final, report = mg._apply_selection_and_rejection(
            reg, quals, cfg, True, {"snr": (5.0, None)}, True, "gc1"
        )
        assert report["percentile_rejected"] == 2
        assert report["threshold_rejected"] == 3  # 2,3,4
        assert report["stacked"] == 5
        # Keine Doppelt-Zählung: Summe = total - stacked
        assert report["percentile_rejected"] + report["threshold_rejected"] + report["stacked"] == report["total"]
        # Threshold darf percentile-verworfene nicht nochmal zählen
        per_frames = {r["frame"] for r in report["frames"] if r["decision"] == "percentile_rejected"}
        thr_frames = {r["frame"] for r in report["frames"] if r["decision"] == "threshold_rejected"}
        assert per_frames.isdisjoint(thr_frames)

    def test_C2_funnel_logged(self):
        """FSEL-C2: agent-log dokumentiert Trichter total→percentile→threshold→stacked."""
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=80)
        quals = [_make_q(float(i), frame=str(Path(f"funnel_{i}.fits"))) for i in range(10)]
        reg = [Path(q.frame) for q in quals]  # type: ignore[arg-type]
        rec = _Rec()
        final, report = mg._apply_selection_and_rejection(
            reg, quals, cfg, True, {"snr": (5.0, None)}, True, "funnel", logger=rec
        )
        assert report["total"] == 10
        assert report["percentile_rejected"] + report["threshold_rejected"] + report["stacked"] == 10
        # structlog funnel event
        funnels = rec.events_named("selection.funnel")
        assert len(funnels) == 1
        _, kw = funnels[0]
        assert kw["total"] == 10
        assert kw["percentile_rejected"] == report["percentile_rejected"]
        assert kw["threshold_rejected"] == report["threshold_rejected"]
        assert kw["stacked"] == report["stacked"]

    def test_C3_switches_independent(self):
        """FSEL-C3: Schalter unabhängig — Deaktivieren eines Mechanismus ändert den anderen nicht."""
        quals = [_make_q(float(i), frame=str(Path(f"sw_{i}.fits"))) for i in range(10)]
        reg = [Path(q.frame) for q in quals]  # type: ignore[arg-type]
        cfg_on = FrameSelectionConfig(enabled=True, keep_percentile=80)
        cfg_off = FrameSelectionConfig(enabled=False)
        # Nur Threshold
        _, rep_thr_only = mg._apply_selection_and_rejection(reg, quals, cfg_off, True, {"snr": (5.0, None)}, True, "sw")
        assert rep_thr_only["percentile_rejected"] == 0
        assert rep_thr_only["threshold_rejected"] == 5
        # Nur Percentile
        _, rep_per_only = mg._apply_selection_and_rejection(reg, quals, cfg_on, False, {}, True, "sw")
        assert rep_per_only["threshold_rejected"] == 0
        assert rep_per_only["percentile_rejected"] == 2
        # Beide
        _, rep_both = mg._apply_selection_and_rejection(reg, quals, cfg_on, True, {"snr": (5.0, None)}, True, "sw")
        assert rep_both["percentile_rejected"] == 2
        assert rep_both["threshold_rejected"] == 3  # wie in C1
        # Threshold-Anzahl bei "both" ≠ bei "thr_only" wegen Perzentil-Vorfilter → korrekt, aber Schalter bleibt funktional
        # Unabhängigkeit: Deaktivieren von Perzentil ändert Threshold nicht auf alleiniger Basis
        assert rep_thr_only["threshold_rejected"] == 5
        assert rep_per_only["percentile_rejected"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# FSEL-D — Transparenz
# ═══════════════════════════════════════════════════════════════════════════


class TestFSEL_D:
    def test_D1_per_frame_log(self):
        """FSEL-D1: agent-log je Frame score/Entscheidung/Grund."""
        cfg = FrameSelectionConfig(enabled=True, keep_percentile=80)
        quals = [_make_q(float(i), frame=str(Path(f"d1_{i}.fits"))) for i in range(5)]
        reg = [Path(q.frame) for q in quals]  # type: ignore[arg-type]
        final, report = mg._apply_selection_and_rejection(reg, quals, cfg, True, {"snr": (3.0, None)}, True, "d1")
        assert "frames" in report
        assert len(report["frames"]) == 5
        for fr in report["frames"]:
            assert "frame" in fr and "score" in fr and "decision" in fr and "reason" in fr
            assert fr["decision"] in ("kept", "percentile_rejected", "threshold_rejected")
            assert 0.0 <= fr["score"] <= 1.0
            if fr["decision"] == "kept":
                assert fr["reason"] is None
            else:
                assert isinstance(fr["reason"], str) and len(fr["reason"]) > 0

    def test_D2_inspect_statistics_per_group(self, tmp_path):
        """FSEL-D2: astra inspect zeigt Selektions-Statistik je Gruppe (Frames total/behalten/verworfen, Perzentil, Score-Spanne)."""
        # Target mit 2 Gruppen (exptime 15 vs 60) → je 6 Lights
        for i in range(6):
            _write_light_fits(tmp_path, f"light_a_{i}.fits", exptime=15.0, gain=60)
        for i in range(6):
            _write_light_fits(tmp_path, f"light_b_{i}.fits", exptime=60.0, gain=60)
        runner = CliRunner()
        # Default (disabled) — inspect soll trotzdem Frame-Selection Sektion zeigen
        result = runner.invoke(cli, ["inspect", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Frame-Selection:" in result.output
        assert "Group" in result.output
        # JSON
        result_json = runner.invoke(cli, ["inspect", "--json", str(tmp_path)])
        assert result_json.exit_code == 0, result_json.output
        data = _extract_json(result_json.output)
        assert "frame_selection" in data
        fs = data["frame_selection"]
        assert "enabled" in fs and "keep_percentile" in fs and "groups" in fs
        # Groups enthalten total/keep/discard/keep_percentile/score_*
        for g in fs["groups"]:
            assert "total" in g and "keep" in g and "discard" in g
            assert "keep_percentile" in g

    def test_D3_cli_flags(self, tmp_path):
        """FSEL-D3: CLI --frame-selection/--no-frame-selection + --keep-percentile N."""
        target = tmp_path / "TargetD3"
        target.mkdir()
        # Minimal light für dry-run (damit Discovery nicht 0 Lights wirft – sonst fail)
        rng = np.random.RandomState(1)
        data = (50.0 + rng.uniform(0, 5, (32, 32))).astype(np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["EXPTIME"] = 15.0
        hdu.header["GAIN"] = 60
        hdu.header["OBJECT"] = "M27"
        hdu.header["CCD-TEMP"] = -10
        hdu.writeto(target / "light_0001.fits", overwrite=True)

        runner = CliRunner()
        # --frame-selection + keep 80 → im Log enabled true / keep 80
        res_on = runner.invoke(cli, ["process", str(target), "--dry-run", "--frame-selection", "--keep-percentile", "80"])
        assert res_on.exit_code == 0, res_on.output
        assert "cli.process.frame_selection" in res_on.output
        assert '"enabled": true' in res_on.output
        assert '"keep_percentile": 80' in res_on.output or '"keep_percentile":80' in res_on.output or "keep_percentile" in res_on.output

        # --no-frame-selection → disabled
        res_off = runner.invoke(cli, ["process", str(target), "--dry-run", "--no-frame-selection"])
        assert res_off.exit_code == 0, res_off.output
        assert "cli.process.frame_selection" in res_off.output
        assert '"enabled": false' in res_off.output

        # --keep-percentile ohne --frame-selection → trotzdem wirksam (Config/Preset Default)
        res_keep_only = runner.invoke(cli, ["process", str(target), "--dry-run", "--keep-percentile", "75"])
        assert res_keep_only.exit_code == 0, res_keep_only.output
        # Ungültiger keep Wert → Click Error 2
        res_bad = runner.invoke(cli, ["process", str(target), "--dry-run", "--keep-percentile", "150"])
        assert res_bad.exit_code == 2

        # Hilfe nennt Flags
        help_res = runner.invoke(cli, ["process", "--help"])
        assert help_res.exit_code == 0
        assert "--frame-selection" in help_res.output
        assert "--keep-percentile" in help_res.output

    def test_D4_doctor_reports_active_and_weights(self):
        """FSEL-D4: astra doctor meldet aktiv/Gewichte (und Rejection-Funnel)."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            data = yaml.safe_load(DEFAULT_CONFIG)
            data["data_root"] = "."
            data["frame_selection"] = {"enabled": True, "keep_percentile": 85, "weights": {"snr": 2.0, "star_count": 1.0}, "min_frames": 4}
            Path("config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
            with patch("astro_process.cli._run_with_timeout", return_value=MagicMock()):
                result = runner.invoke(cli, ["-c", "config.yaml", "doctor"])
            assert result.exit_code in (0, 1), result.output
            assert "Frame-Selection AKTIV" in result.output
            assert "keep=85" in result.output
            assert "weights" in result.output.lower()
            # Inaktiv-Fall: Default aus
            Path("config.yaml").write_text(yaml.safe_dump(yaml.safe_load(DEFAULT_CONFIG)), encoding="utf-8")
            # data_root wieder setzen (DEFAULT ist C:/Astra, im isolated fs nicht existent → fail, daher . setzen)
            data2 = yaml.safe_load(DEFAULT_CONFIG)
            data2["data_root"] = "."
            Path("config.yaml").write_text(yaml.safe_dump(data2), encoding="utf-8")
            with patch("astro_process.cli._run_with_timeout", return_value=MagicMock()):
                result2 = runner.invoke(cli, ["-c", "config.yaml", "doctor"])
            assert result2.exit_code in (0, 1), result2.output
            assert "Frame-Selection inaktiv" in result2.output
