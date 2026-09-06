"""Tests for V1.4-20 (Cross-Group-Qualitäts-Gate mehrdimensional) + V1.4-21
(AZ/EQ-Mix-Erkennung) — Fix-Sammlung v1.3 §4 (LDN 935, M13).

Teststrategie:
- `consolidate_eqmode_values`: Unit — EQMODE-Konsolidierung pro Gruppe
  (majority/consistent/counts; konservativ bei unbekannt/Gleichstand).
- `apply_cross_group_skip_filter`: Mehrmesswert-Gate (LDN-935-Werte:
  corr_hp 0.538 über Schwelle, aber corr_roh 0.005, n_CP 23,
  Rotation 2.26° bei EQ → Ausschluss mit Gruenden); eq_mix_az_eq
  (M13: AZ-Gruppe gegen EQ-Referenz); Regression (ohne EQMODE-Info /
  gute Metriken → kein zusaetzlicher Skip); corr_hp-Pfad bleibt
  below_min_correlation; W13 (frame_count < 3) schuetzt auch das
  Mehrmesswert-Gate.
- `register_to_reference_stack`: status_reasons (V1.4-20, additiv) —
  low_corr_roh bei unaehnlichen Bildern (LDN-935-Mechanismus auf
  Real-Synthetik).
- End-to-End `process_multi_group`: eqmode_mix-Warnung VOR dem Lauf,
  eq_mix_az_eq-Ausschluss im Merge-Report, reference_selection.eqmode-
  Doku — ohne EQMODE-Header-Infos bleibt das Verhalten unveraendert.

Hermetik: keine Netzwerk-/Katalog-Aufrufe; schwere Schritte
(register/stack/cross-registration/pcc) sind gemockt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from astropy.io import fits

# ── Ensure src + tests dir on the path ───────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_multi_group import create_test_fits  # noqa: E402

import astro_process.agents.multi_group_agent as multi_group_agent  # noqa: E402
from astro_process.agents.multi_group_agent import (  # noqa: E402
    apply_cross_group_skip_filter,
    consolidate_eqmode_values,
)
from astro_process.agents.merge_agent import MergeAgent  # noqa: E402
from astro_process.agents.processing_agent import ProcessingAgent  # noqa: E402
from astro_process.config.models import (  # noqa: E402
    MergeConfig,
    MultiGroupConfig,
    ProcessingParams,
)
from astro_process.core.registration import (  # noqa: E402
    RegisterFramesResult,
    RegistrationResult,
)
from astro_process.models.core import (  # noqa: E402
    AcquisitionInfo,
    CalibrationStatus,
    EquipmentInfo,
    FitsHeader,
    FrameInfo,
    FrameSet,
    FrameType,
    ObservationContext,
    ObservationTarget,
)


# ═══════════════════════════════════════════════════════════════════
# V1.4-21: consolidate_eqmode_values (Unit)
# ═══════════════════════════════════════════════════════════════════


class TestConsolidateEqmodeValues:
    """EQMODE-Konsolidierung pro Gruppe (M13-Fundament)."""

    def test_all_eq(self):
        d = consolidate_eqmode_values([1, 1, 1])
        assert d["majority"] == 1
        assert d["consistent"] is True
        assert d["counts"] == {"0": 0, "1": 3, "None": 0}

    def test_all_az(self):
        d = consolidate_eqmode_values([0, 0, 0])
        assert d["majority"] == 0
        assert d["consistent"] is True
        assert d["counts"] == {"0": 3, "1": 0, "None": 0}

    def test_mixed_known_inconsistent(self):
        # M13-Analog: 55× EQ, 43× AZ in verschiedenen Gruppen — hier
        # eine Gruppe mit 1/0/1 → Modus 1 gewinnt, Gruppe inkonsistent.
        d = consolidate_eqmode_values([1, 0, 1])
        assert d["majority"] == 1
        assert d["consistent"] is False
        assert d["counts"] == {"0": 1, "1": 2, "None": 0}

    def test_all_unknown(self):
        # Keine EQMODE-Header (best effort) → keine Mix-Aussage.
        d = consolidate_eqmode_values([None, None])
        assert d["majority"] is None
        assert d["consistent"] is True
        assert d["counts"] == {"0": 0, "1": 0, "None": 2}

    def test_unknown_values_do_not_break_consistency(self):
        # Bekannte Werte identisch; unbekannte zaehlen nicht als Widerspruch.
        d = consolidate_eqmode_values([1, 1, None])
        assert d["majority"] == 1
        assert d["consistent"] is True
        assert d["counts"] == {"0": 0, "1": 2, "None": 1}

    def test_tie_is_conservative(self):
        # Gleichstand 0 vs. 1 → Modus unklar (keine falsche Mix-Aussage).
        d = consolidate_eqmode_values([0, 1])
        assert d["majority"] is None
        assert d["consistent"] is False
        assert d["counts"] == {"0": 1, "1": 1, "None": 0}


# ═══════════════════════════════════════════════════════════════════
# V1.4-20 + V1.4-21: apply_cross_group_skip_filter (Mehrmesswert-Gate)
# ═══════════════════════════════════════════════════════════════════


def _aligned(tmp: Path, hashes: list[str]) -> dict[str, Path]:
    return {h: tmp / f"aligned_{h}.fits" for h in hashes}


class TestCrossGroupQualityGate:
    """W3-Skip-Filter mehrdimensional (V1.4-20/21)."""

    def test_ldn935_multidimensional_skip(self, tmp_path: Path):
        """LDN-935-Fall: corr_hp 0.5377 ueber min_correlation 0.1, aber
        corr_roh 0.005, n_CP 23, Rotation 2.26° bei EQ → Ausschluss mit
        allen drei Gruenden (eigener Stack bleibt)."""
        aligned = _aligned(tmp_path, ["15s40_Duo-Band", "180s60_Duo-Band"])
        regs = [{
            "group": "15s40_Duo-Band",
            "reference": "180s60_Duo-Band",
            "corr_hp": 0.5377,
            "corr_roh": 0.005,
            "correlation": 0.005,
            "status": "ok",
            "method": "rotation_fft",
            "rotation_deg": 2.26,
            "n_control_points": 23,
        }]
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="180s60_Duo-Band", min_correlation=0.1,
            group_eqmode={"15s40_Duo-Band": 1, "180s60_Duo-Band": 1},
        )
        assert "15s40_Duo-Band" not in kept
        assert "180s60_Duo-Band" in kept  # Referenz nie geskippt
        assert len(skipped) == 1
        entry = skipped[0]
        assert entry["group"] == "15s40_Duo-Band"
        assert entry["reason"] == "cross_group_quality_gate"
        assert set(entry["reasons"]) == {
            "low_corr_roh", "few_control_points", "unexpected_rotation",
        }
        assert entry["corr_hp"] == 0.5377
        assert entry["corr_roh"] == 0.005
        assert entry["n_control_points"] == 23
        assert entry["rotation_deg"] == 2.26

    def test_eq_mix_az_eq_skip(self, tmp_path: Path):
        """M13-Fall: AZ-Gruppe (EQMODE 0) gegen EQ-Referenz (EQMODE 1) —
        sonst gute Metriken (corr_roh 0.6, n_CP 40, Rotation 0) →
        Ausschluss mit Grund eq_mix_az_eq."""
        aligned = _aligned(tmp_path, ["15s60", "60s40"])
        regs = [{
            "group": "15s60",
            "reference": "60s40",
            "corr_hp": 0.75,
            "corr_roh": 0.6,
            "correlation": 0.6,
            "status": "ok",
            "method": "astroalign",
            "rotation_deg": 0.0,
            "n_control_points": 40,
        }]
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="60s40", min_correlation=0.1,
            group_eqmode={"15s60": 0, "60s40": 1},
        )
        assert "15s60" not in kept
        assert skipped[0]["reason"] == "cross_group_quality_gate"
        assert skipped[0]["reasons"] == ["eq_mix_az_eq"]

    def test_same_eqmode_no_mix_skip(self, tmp_path: Path):
        """Gleicher Modus (beide EQ) + gute Metriken → kein Skip."""
        aligned = _aligned(tmp_path, ["180s60", "60s40"])
        regs = [{
            "group": "180s60",
            "reference": "60s40",
            "corr_hp": 0.75,
            "corr_roh": 0.6,
            "correlation": 0.6,
            "status": "ok",
            "method": "astroalign",
            "rotation_deg": 0.0,
            "n_control_points": 40,
        }]
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="60s40", min_correlation=0.1,
            group_eqmode={"180s60": 1, "60s40": 1},
        )
        assert set(kept.keys()) == {"180s60", "60s40"}
        assert skipped == []

    def test_no_eqmode_info_keeps_legacy_behavior(self, tmp_path: Path):
        """Ohne EQMODE-Infos (best effort, None) + gute Metriken →
        unveraendertes Verhalten (kein zusaetzlicher Skip)."""
        aligned = _aligned(tmp_path, ["180s60", "60s40"])
        regs = [{
            "group": "180s60",
            "reference": "60s40",
            "corr_hp": 0.75,
            "corr_roh": 0.6,
            "correlation": 0.6,
            "status": "ok",
            "method": "astroalign",
            "rotation_deg": 0.0,
            "n_control_points": 40,
        }]
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="60s40", min_correlation=0.1,
            group_eqmode={"180s60": None, "60s40": None},
        )
        assert set(kept.keys()) == {"180s60", "60s40"}
        assert skipped == []

    def test_corr_hp_below_min_correlation_still_first(self, tmp_path: Path):
        """corr_hp < min_correlation → bestehender Grund
        below_min_correlation (auch wenn zusaetzliche Qualitaetsgruende
        vorlaege — kein Doppel-Eintrag)."""
        aligned = _aligned(tmp_path, ["15s40_Duo-Band", "180s60_Duo-Band"])
        regs = [{
            "group": "15s40_Duo-Band",
            "reference": "180s60_Duo-Band",
            "corr_hp": 0.05,
            "corr_roh": 0.005,
            "correlation": 0.005,
            "status": "warning",
            "method": "fft",
            "rotation_deg": 0.0,
            "n_control_points": None,
        }]
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="180s60_Duo-Band", min_correlation=0.1,
        )
        assert "15s40_Duo-Band" not in kept
        assert skipped[0]["reason"] == "below_min_correlation"

    def test_frame_count_lt_3_never_skipped_by_quality_gate(
        self, tmp_path: Path,
    ):
        """W13: frame_count < 3 → NIE skippen (auch nicht durch das
        Mehrmesswert-Gate) — nur warning (Konsistenz AC-W13-1/2)."""
        aligned = _aligned(tmp_path, ["15s40_Duo-Band", "180s60_Duo-Band"])
        regs = [{
            "group": "15s40_Duo-Band",
            "reference": "180s60_Duo-Band",
            "corr_hp": 0.5377,
            "corr_roh": 0.005,
            "correlation": 0.005,
            "status": "ok",
            "method": "rotation_fft",
            "rotation_deg": 2.26,
            "n_control_points": 23,
        }]
        group_metadata = {"15s40_Duo-Band": {"frame_count": 2}}
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="180s60_Duo-Band", min_correlation=0.1,
            group_metadata=group_metadata,
            group_eqmode={"15s40_Duo-Band": 1, "180s60_Duo-Band": 1},
        )
        assert "15s40_Duo-Band" in kept
        assert skipped == []

    def test_unexpected_rotation_only_for_eq(self, tmp_path: Path):
        """unexpected_rotation NUR bei EQ-Gruppe — AZ hat Feldrotation
        (bis ~13°), Rotation ist dort erwartet."""
        aligned = _aligned(tmp_path, ["15s60", "60s40"])
        regs = [{
            "group": "15s60",
            "reference": "60s40",
            "corr_hp": 0.75,
            "corr_roh": 0.6,
            "correlation": 0.6,
            "status": "ok",
            "method": "astroalign",
            "rotation_deg": 5.0,
            "n_control_points": 40,
        }]
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="60s40", min_correlation=0.1,
            group_eqmode={"15s60": 0, "60s40": 1},
        )
        # AZ-Gruppe mit 5° Rotation: kein unexpected_rotation (nur Mix-Grund)
        assert skipped[0]["reasons"] == ["eq_mix_az_eq"]


# ═══════════════════════════════════════════════════════════════════
# V1.4-20: register_to_reference_stack status_reasons (Real-Synthetik)
# ═══════════════════════════════════════════════════════════════════


class TestRegisterStatusReasons:
    """status_reasons (V1.4-20, additiv) — corr_hp allein kann eine
    falsche Transformation durchlassen (LDN-935-Mechanismus)."""

    def test_low_corr_roh_reason_on_dissimilar_stacks(self, tmp_path: Path):
        """Zwei sehr unterschiedliche Sternfelder → Roh-Korrelation niedrig
        (corr_roh < 0.05) → status_reasons enthaelt low_corr_roh. Der
        status bleibt corr_hp-basiert (rueckwaertskompatibel)."""
        agent = ProcessingAgent(working_dir=tmp_path, config=None)
        ref_path = create_test_fits(
            tmp_path / "ref.fits", exptime=15.0, gain=60,
            rng_seed=1, shift=(0, 0),
        )
        # Anderes Sternfeld (anderer Seed) + kein Shift — strukturell
        # unaehnlich zur Referenz → corr_roh klein.
        tgt_path = create_test_fits(
            tmp_path / "tgt.fits", exptime=60.0, gain=40,
            rng_seed=99, shift=(0, 0),
        )

        out_dir = tmp_path / "aligned_out"
        result = agent._register_to_reference_stack(
            tgt_path, ref_path, filter_name="", output_dir=out_dir,
        )

        assert isinstance(result, RegistrationResult)
        assert result.status in ("ok", "warning")
        assert isinstance(result.status_reasons, list)
        # corr_roh der dissimilar Stacks ist (deterministisch) < 0.05 —
        # der Mechanismus (Diagnose-Grund) muss greifen.
        assert result.correlation < 0.05
        assert "low_corr_roh" in result.status_reasons

    def test_status_reasons_default_empty(self):
        """RegistrationResult-Default: status_reasons leer (bestehende
        Aufrufer ohne das Feld bleiben kompatibel)."""
        r = RegistrationResult(path=Path("x.fits"))
        assert r.status_reasons == []


# ═══════════════════════════════════════════════════════════════════
# V1.4-21: End-to-End process_multi_group — AZ/EQ-Mix
# ═══════════════════════════════════════════════════════════════════


def _make_eq_context(
    path: Path,
    groups: list[tuple[float, int, str | None, int | None, int]],
) -> ObservationContext:
    """Context mit EQMODE-Header-Infos pro Gruppe.

    groups: [(exptime, gain, filter, eq_mode, count), ...] — eq_mode
    wird sowohl in den FITS-Header (EQMODE, fits_parser-Konsistenz) als
    auch in das FitsHeader-Objekt (FrameInfo.header, von
    process_multi_group gelesen) gesetzt.
    """
    all_frames = []
    for gi, (exptime, gain, filt, eq_mode, count) in enumerate(groups):
        gp = path / f"group_{gi}"
        gp.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            fp = gp / f"light_{i:04d}.fits"
            create_test_fits(
                fp, exptime=exptime, gain=gain, filter_name=filt,
                rng_seed=gi * 100 + i,
            )
            if eq_mode is not None:
                with fits.open(fp, mode="update") as hdul:
                    hdul[0].header["EQMODE"] = int(eq_mode)
            all_frames.append(FrameInfo(
                path=fp,
                frame_type=FrameType.LIGHT,
                header=FitsHeader(
                    exptime=exptime, gain=gain, filter_name=filt,
                    eq_mode=eq_mode,
                ),
                index=i,
                size_bytes=fp.stat().st_size,
                width=100,
                height=100,
            ))
    return ObservationContext(
        target=ObservationTarget(name="TestTarget", ra=180.0, dec=30.0),
        frames={FrameType.LIGHT: FrameSet(
            frame_type=FrameType.LIGHT, frames=all_frames,
        )},
        calibration=CalibrationStatus(dark_available=True),
        equipment=EquipmentInfo(
            telescope="TestScope", focal_length_mm=200.0,
            pixel_size_um=3.76,
        ),
        acquisition=AcquisitionInfo(gain=100),
        source_path=path,
    )


class TestProcessMultiGroupEqmodeMix:
    """V1.4-21: eqmode_mix-Warnung vor dem Lauf + eq_mix_az_eq-Gate +
    reference_selection.eqmode-Doku (M13-Fall, 3 Gruppen)."""

    def test_eqmode_mix_warning_and_gate(self, tmp_path: Path):
        import astro_process.agents.processing_agent as processing_agent

        # 3 Gruppen: 15s60=AZ(0), 60s40=EQ(1, Referenz), 180s60=EQ(1)
        context = _make_eq_context(tmp_path, [
            (15.0, 60, None, 0, 3),
            (60.0, 40, None, 1, 3),
            (180.0, 60, None, 1, 3),
        ])
        agent = ProcessingAgent(working_dir=tmp_path, config=None)
        mock_logger = MagicMock()
        mg_config = MultiGroupConfig(
            merge=MergeConfig(min_correlation=0.1),
            reference_group="60s40",
        )

        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        merge_agent = MergeAgent(working_dir=tmp_path, config=None)

        stack_fits = {
            "15s60": create_test_fits(tmp_path / "stack_15s60.fits",
                                      exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_path / "stack_60s40.fits",
                                      exptime=60.0, gain=40, rng_seed=2),
            "180s60": create_test_fits(tmp_path / "stack_180s60.fits",
                                       exptime=180.0, gain=60, rng_seed=3),
        }

        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            pcc_counter["n"] += 1
            p = tmp_path / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        def fake_cross(stack_path, ref_stack_path, filter_name, stack_dir,
                       params=None, **kwargs):
            # Sonst gute Metriken — der Ausschluss muss allein aus dem
            # Modus-Mix (eq_mix_az_eq) kommen.
            return RegistrationResult(
                path=stack_path, shift_y=0.0, shift_x=0.0,
                correlation=0.6, corr_hp=0.75, status="ok",
                method="astroalign", rotation_deg=0.0,
                n_control_points=40,
            )

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc, \
             patch.object(processing_agent, "logger", mock_logger):
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[],
                last_frame_rejected=0, last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.side_effect = fake_cross
            mock_pcc.side_effect = fake_pcc

            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )

        # 1) Warnung VOR dem Lauf (multi_group.eqmode_mix)
        warn_events = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "multi_group.eqmode_mix" in warn_events

        # 2) eq_mix_az_eq-Ausschluss im Merge-Report (skipped_groups)
        report_path = tmp_path / "merged" / "merge_report.json"
        assert report_path.exists(), f"merge_report.json fehlt: {report_path}"
        report = json.loads(report_path.read_text())
        skipped = report["skipped_groups"]
        assert any(
            e["group"] == "15s60"
            and e["reason"] == "cross_group_quality_gate"
            and "eq_mix_az_eq" in e["reasons"]
            for e in skipped
        )

        # 3) 15s60 (AZ) nicht im Merge; EQ-Gruppe 180s60 + Referenz drin
        merged_groups = [s["group"] for s in report["input_stacks"]]
        assert "15s60" not in merged_groups
        assert "180s60" in merged_groups
        assert report["reference_group"] == "60s40"
        assert "60s40" in merged_groups

        # 4) reference_selection.eqmode-Doku (Mix nachvollziehbar)
        ref_sel = report["reference_selection"]
        assert ref_sel["eqmode"]["ref_group_majority"] == 1
        assert ref_sel["eqmode"]["majority_by_group"] == {
            "15s60": 0, "60s40": 1, "180s60": 1,
        }
        assert ref_sel["eqmode"]["mix_detected"] is True

        # 5) Registrations-Eintrag traegt die Diagnose (additiv)
        regs = report["cross_group_registrations"]
        assert any(
            r["group"] == "15s60"
            and r["eqmode_majority"] == 0
            and r["ref_eqmode_majority"] == 1
            for r in regs
        )

        # 6) Stack der ausgeschlossenen Gruppe bleibt erhalten (kein Cleanup)
        assert (tmp_path / "group_15s60" / "04_stacked").exists()

    def test_no_eqmode_headers_no_mix_warning(self, tmp_path: Path):
        """Ohne EQMODE-Header-Infos (alle None) → keine Mix-Warnung,
        keine eq_mix_az_eq-Skips (best effort; Regression)."""
        import astro_process.agents.processing_agent as processing_agent

        context = _make_eq_context(tmp_path, [
            (15.0, 60, None, None, 3),
            (60.0, 40, None, None, 3),
        ])
        agent = ProcessingAgent(working_dir=tmp_path, config=None)
        mock_logger = MagicMock()
        mg_config = MultiGroupConfig(
            merge=MergeConfig(min_correlation=0.1),
            reference_group="60s40",
        )

        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        merge_agent = MergeAgent(working_dir=tmp_path, config=None)

        stack_fits = {
            "15s60": create_test_fits(tmp_path / "stack_15s60.fits",
                                      exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_path / "stack_60s40.fits",
                                      exptime=60.0, gain=40, rng_seed=2),
        }

        def fake_pcc(stack_path, *args, **kwargs):
            p = tmp_path / "pcc_stack_1.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=1)
            return (p, "gaia_success")

        def fake_cross(stack_path, ref_stack_path, filter_name, stack_dir,
                       params=None, **kwargs):
            return RegistrationResult(
                path=stack_path, shift_y=0.0, shift_x=0.0,
                correlation=0.6, corr_hp=0.75, status="ok",
                method="astroalign", rotation_deg=0.0,
                n_control_points=40,
            )

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc, \
             patch.object(processing_agent, "logger", mock_logger):
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[],
                last_frame_rejected=0, last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.side_effect = fake_cross
            mock_pcc.side_effect = fake_pcc

            agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )

        warn_events = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "multi_group.eqmode_mix" not in warn_events

        report_path = tmp_path / "merged" / "merge_report.json"
        report = json.loads(report_path.read_text())
        assert report["skipped_groups"] == []
        # Beide Gruppen im Merge (kein Mix-Ausschluss)
        merged_groups = [s["group"] for s in report["input_stacks"]]
        assert "15s60" in merged_groups
        assert "60s40" in merged_groups
        # eqmode-Doku: majority None, kein Mix
        ref_sel = report["reference_selection"]
        assert ref_sel["eqmode"]["ref_group_majority"] is None
        assert ref_sel["eqmode"]["mix_detected"] is False
