"""DEF-006 V1.8-8 — Outlier-Rejection verwerfen statt flaggen (Average-Pfad, corr_hp <0.05).

Stella Empfehlung a+c kombiniert:
  (a) average-Pfad respektiert outlier_excluded==True (threshold-basiert)
  (c) corr_hp <0.05 Auto-Ausschluss analog V1.4-20 Cross-Group-Gate (Default 0.05)

Kombiniert: verwirft wenn outlier_excluded==True ODER corr_hp<0.05.
Muss auch bei rejection_enabled==False (Default V1.5-8) korrekt verwerfen
(mandatory Gate, nicht an Flag hängend). Superpixel-Fallback analog.

Abdeckung:
 - Outlier-Flag wird verworfen wenn outlier_excluded True (threshold)
 - Catastrophic corr_hp 0.004-0.01 wird verworfen (mandatory 0.05)
 - Kombiniert: beide Bedingungen ODER
 - Clean frames kein Loss (alle corr_hp >0.05, kein outlier)
 - Konfigurierbar: Schwelle 0.05 default, None deaktiviert, 0.1 strenger
 - Analog Superpixel-Pfad (Fallback): selbe Logik, da gleicher selection-Pfad
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.core.quality import FrameQuality
from astro_process.core.selection import (
    DEFAULT_MIN_CORR_HP,
    _apply_selection_and_rejection,
    _resolve_min_corr_hp_config,
)
from astro_process.config.models import AppConfig, FrameSelectionConfig, PipelinePreset, ProcessingParams


def _q(frame: str, corr: float | None = 0.9, snr: float = 10.0, outlier_excluded: bool = False) -> FrameQuality:
    # Helper: correlation == corr_hp (intra-group)
    q = FrameQuality(frame=frame, snr=snr, star_count=30, correlation=corr)
    q.outlier_excluded = outlier_excluded
    if outlier_excluded:
        q.outlier_reject_reason = "snr"
    return q


class TestDef006MandatoryCorrHp:
    """DEF-006 (c): corr_hp <0.05 verwirft, auch bei rejection_enabled=False."""

    def test_catastrophic_corr_hp_filtered_even_when_rejection_disabled(self):
        fs = FrameSelectionConfig(enabled=False)
        quals = [
            _q("light_0000.fits", corr=0.9),
            _q("light_0001.fits", corr=0.004),
            _q("light_0002.fits", corr=0.95),
            _q("light_0003.fits", corr=0.01),
            _q("light_0004.fits", corr=0.85),
        ]
        reg = [Path(q.frame) for q in quals]
        final, report = _apply_selection_and_rejection(
            reg, quals, fs, False, {}, True, "m92", mandatory_min_corr_hp=0.05
        )
        assert len(final) == 3
        assert report["mandatory_rejected"] == 2
        assert report["threshold_rejected"] == 2
        assert report["stacked"] == 3
        names = {p.name for p in final}
        assert "light_0001.fits" not in names
        assert "light_0003.fits" not in names
        # Decisions dokumentiert als threshold_rejected mit correlation Grund
        reasons = {r["frame"]: r["reason"] for r in report["frames"] if r["decision"] == "threshold_rejected"}
        assert any("correlation" in (reasons.get(Path(q.frame).as_posix()) or "") for q in quals if q.correlation and q.correlation < 0.05)

    def test_m92_ghosting_8_of_41_filtered(self):
        """M92 Lauf 2: 41 inkl. 8 katastrophaler 0.004-0.01 -> 33 bleiben, kein Ghosting."""
        fs = FrameSelectionConfig(enabled=False)
        quals = []
        for i in range(41):
            if i in (12, 13, 14, 15, 16, 32, 33, 34):  # 8 katastrophale (M92 Beleg)
                corr = 0.004 + (i % 3) * 0.002  # 0.004-0.008
            else:
                corr = 0.5 + (i % 5) * 0.05
            quals.append(_q(f"light_{i:04d}.fits", corr=corr))
        reg = [Path(q.frame) for q in quals]
        final, report = _apply_selection_and_rejection(
            reg, quals, fs, False, {}, True, "m92_41", mandatory_min_corr_hp=0.05
        )
        assert len(final) == 33
        assert report["mandatory_rejected"] == 8
        assert report["stacked"] == 33

    def test_clean_frames_no_loss(self):
        fs = FrameSelectionConfig(enabled=False)
        quals = [_q(f"light_{i:04d}.fits", corr=0.85) for i in range(10)]
        reg = [Path(q.frame) for q in quals]
        final, report = _apply_selection_and_rejection(
            reg, quals, fs, False, {}, True, "clean", mandatory_min_corr_hp=0.05
        )
        assert len(final) == 10
        assert report["mandatory_rejected"] == 0
        assert report["stacked"] == 10

    def test_threshold_configurable(self):
        fs = FrameSelectionConfig(enabled=False)
        quals = [_q("light_0000.fits", corr=0.07), _q("light_0001.fits", corr=0.04)]
        reg = [Path(q.frame) for q in quals]
        # Default 0.05 -> 1 filtered (0.04)
        _, rep_default = _apply_selection_and_rejection(reg, quals, fs, False, {}, True, "thr", mandatory_min_corr_hp=0.05)
        assert rep_default["mandatory_rejected"] == 1
        # Stricter 0.1 -> both filtered? 0.07 <0.1 yes, so 2
        _, rep_strict = _apply_selection_and_rejection(reg, quals, fs, False, {}, True, "thr", mandatory_min_corr_hp=0.1)
        assert rep_strict["mandatory_rejected"] == 2
        # Disabled None -> none filtered
        _, rep_off = _apply_selection_and_rejection(reg, quals, fs, False, {}, True, "thr", mandatory_min_corr_hp=None)
        assert rep_off["mandatory_rejected"] == 0
        assert len(rep_off["frames"])  # still report built but no filter
        assert rep_off["stacked"] == 2

    def test_reference_corr_none_never_filtered(self):
        """Referenz-Frame hat correlation None (keine Shift-Metrik) -> nie verworfen."""
        fs = FrameSelectionConfig(enabled=False)
        quals = [_q("light_0000.fits", corr=None), _q("light_0001.fits", corr=0.004)]
        reg = [Path(q.frame) for q in quals]
        final, _ = _apply_selection_and_rejection(reg, quals, fs, False, {}, True, "ref", mandatory_min_corr_hp=0.05)
        assert len(final) == 1
        assert final[0].name == "light_0000.fits"


class TestDef006OutlierExcluded:
    """DEF-006 (a): outlier_excluded==True wird verworfen, auch bei mandatory Gate."""

    def test_outlier_excluded_via_threshold_mandatory(self):
        fs = FrameSelectionConfig(enabled=False)
        # Threshold snr <5 -> light_0001 outlier
        quals = [
            _q("light_0000.fits", snr=10, corr=0.9),
            FrameQuality(frame="light_0001.fits", snr=2, star_count=30, correlation=0.9),
            _q("light_0002.fits", snr=11, corr=0.9),
        ]
        reg = [Path(q.frame) for q in quals]
        final, report = _apply_selection_and_rejection(
            reg, quals, fs, False, {"snr": (5.0, None)}, True, "outlier", mandatory_min_corr_hp=0.05
        )
        assert len(final) == 2
        assert report["mandatory_rejected"] == 1  # via outlier_excluded
        names = {p.name for p in final}
        assert "light_0001.fits" not in names

    def test_combined_outlier_and_corr(self):
        fs = FrameSelectionConfig(enabled=False)
        quals = [
            _q("light_0000.fits", corr=0.9, snr=10),
            FrameQuality(frame="light_0001.fits", snr=2, star_count=30, correlation=0.9),  # outlier
            _q("light_0002.fits", corr=0.01, snr=10),  # low corr
            _q("light_0003.fits", corr=0.95, snr=10),
        ]
        reg = [Path(q.frame) for q in quals]
        final, report = _apply_selection_and_rejection(
            reg, quals, fs, False, {"snr": (5.0, None)}, True, "comb", mandatory_min_corr_hp=0.05
        )
        assert len(final) == 2
        assert report["mandatory_rejected"] == 2
        assert {p.name for p in final} == {"light_0000.fits", "light_0003.fits"}


class TestDef006Config:
    """DEF-006 Config-Schwellwert Default 0.05, konfigurierbar, V1.4-20 Analog."""

    def test_default_is_0_05(self):
        assert DEFAULT_MIN_CORR_HP == pytest.approx(0.05)
        # Models default
        pp = ProcessingParams()
        assert pp.rejection_min_corr_hp == pytest.approx(0.05)
        # Loader resolver default
        from astro_process.config.loader import resolve_rejection_min_corr_hp
        cfg = AppConfig()
        preset = PipelinePreset(name="x", target_types=["*"], steps=[], processing_params=ProcessingParams())
        assert resolve_rejection_min_corr_hp(cfg, preset) == pytest.approx(0.05)
        # Selection resolver default
        assert _resolve_min_corr_hp_config({}, None) == pytest.approx(0.05)

    def test_config_overrides_preset(self):
        from astro_process.config.loader import resolve_rejection_min_corr_hp
        preset = PipelinePreset(name="x", target_types=["*"], steps=[], processing_params=ProcessingParams(rejection_min_corr_hp=0.07))
        cfg = AppConfig(rejection_min_corr_hp=0.02)
        # AppConfig field_set muss gesetzt sein, sonst fallback
        cfg2 = AppConfig.model_validate({"rejection_min_corr_hp": 0.02})
        assert resolve_rejection_min_corr_hp(cfg2, preset) == pytest.approx(0.02)

    def test_none_disables_gate(self):
        # Preset None -> deaktiviert
        assert _resolve_min_corr_hp_config({"rejection_min_corr_hp": None}, None) is None
        # Config null -> deaktiviert
        cfg = AppConfig.model_validate({"rejection_min_corr_hp": None})
        from astro_process.config.loader import resolve_rejection_min_corr_hp
        preset = PipelinePreset(name="x", target_types=["*"], steps=[], processing_params=ProcessingParams(rejection_min_corr_hp=0.05))
        assert resolve_rejection_min_corr_hp(cfg, preset) is None


class TestDef006MultiGroupIntegration:
    """Integration: Multi-Group-Agent nutzt mandatory Gate auch bei Default disabled."""

    def test_multi_group_mandatory_filters_even_when_both_disabled(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from astro_process.models.core import (
            FrameInfo, FrameSet, FrameType, FitsHeader, ObservationContext, ObservationTarget, EquipmentInfo, AcquisitionInfo, CalibrationStatus, GroupInfo, compute_group_hash
        )
        from astro_process.agents.processing_agent import ProcessingAgent
        from astro_process.config.models import MultiGroupConfig
        from astro_process.core.registration import RegisterFramesResult, RegistrationResult
        import numpy as np
        from astropy.io import fits
        from pathlib import Path

        # Minimal context with 1 group, 5 lights, 2 catastrophic corr
        def _make_fits(p, exptime=15.0, gain=60):
            data = np.ones((3, 10, 10), dtype=np.float32)
            hdu = fits.PrimaryHDU(data)
            hdu.header["EXPTIME"] = exptime
            hdu.header["GAIN"] = gain
            hdu.header["OBJECT"] = "M92"
            hdu.header["CCD-TEMP"] = -10
            hdu.header["CTYPE3"] = "RGB"
            p.parent.mkdir(parents=True, exist_ok=True)
            hdu.writeto(p, overwrite=True)
            return p
        # Build context: 5 lights same group
        lights_dir = tmp_path / "lights"
        lights_dir.mkdir()
        frame_infos = []
        for i in range(5):
            p = lights_dir / f"light_{i:04d}.fits"
            _make_fits(p)
            frame_infos.append(FrameInfo(path=p, frame_type=FrameType.LIGHT, header=FitsHeader(exptime=15.0, gain=60, filter_name=None), index=i, size_bytes=100, width=10, height=10))
        light_set = FrameSet(frame_type=FrameType.LIGHT, frames=frame_infos)
        ctx = ObservationContext(target=ObservationTarget(name="M92", ra=260, dec=40), frames={FrameType.LIGHT: light_set}, calibration=CalibrationStatus(dark_available=True), equipment=EquipmentInfo(focal_length_mm=150, pixel_size_um=2.9), acquisition=AcquisitionInfo(gain=60), source_path=lights_dir)
        agent = ProcessingAgent(working_dir=tmp_path / "work", config=None)
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()  # default rejection_min_corr_hp 0.05, rejection_enabled False
        pipeline.steps = []
        # Mock registration: 5 registered, qualities with 2 low corr
        quals = [
            FrameQuality(frame=str(lights_dir / f"light_{i:04d}.fits"), snr=10, star_count=30, correlation=0.9 if i not in (1,3) else 0.01)
            for i in range(5)
        ]
        # Need to set frame strings to match registered paths
        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
            mock_reg.return_value = RegisterFramesResult(registered=[p for p in [f.path for f in frame_infos]], last_frame_qualities=quals, last_frame_rejected=0, last_registration_metrics={})
            # capture stack_frames registered list
            captured = {}
            def fake_stack(reg, params, is_3d, stacked_dir, load_frame, save_frame):
                captured["reg"] = list(reg)
                # create dummy stacked file
                out = stacked_dir / "stacked.fits"
                out.parent.mkdir(parents=True, exist_ok=True)
                fits.PrimaryHDU(np.ones((3,10,10),dtype=np.float32)).writeto(out, overwrite=True)
                return out
            mock_stack.side_effect = fake_stack
            mock_cross.return_value = RegistrationResult(path=tmp_path/"aligned.fits", status="ok", corr_hp=0.9)
            mock_pcc.side_effect = lambda *a, **kw: (tmp_path/"pcc.fits", "gaia_success")
            # Need to actually create a valid stack file for ref? Use same mock
            # Run multi_group (will go through mandatory gate)
            result = agent.process_multi_group(ctx, MagicMock(calibrated_lights=[f.path for f in frame_infos]), MagicMock(debayered_frames=[]), pipeline, multi_group_config=MultiGroupConfig())
            # Check captured registered after selection was filtered (2 low corr removed -> 3)
            # Note: selection happens intra-group before stacking, so captured should be 3
            assert "reg" in captured
            assert len(captured["reg"]) == 3, f"expected 3 after mandatory filter, got {len(captured['reg'])}"
