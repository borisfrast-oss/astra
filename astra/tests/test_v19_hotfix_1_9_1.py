"""V19 Hotfix 1.9.1 — FIX-10..13 gezielte Tests (backy Single-Thread 1.15d).

Covers:
- FIX-10 REG per-Gruppe (0.5d, P0): resolve_group_registration_configs per-Gruppe
  AZ→astroalign 30°, EQ→fft, CLI gewinnt, dwarf_mini 15° vs generic AZ 30°.
- FIX-11 Gate Duo-Band (0.25d, P0): effective_min 0.05 für Duo-Band, low_corr_roh
  bei Duo-Band ignorieren (nur corr_hp werten), single_stack_fallback.
- FIX-12 Mandatory Gate (0.25d, P1): threshold 0.05 auch bei frame_selection false.
- FIX-13 PCC Rosa (0.15d, P1): nebula presets scnr:true via DEFAULT_CONFIG.

Sonst ray CHANGES_REQUIRED (S13/S14, L4/L6).
"""

from pathlib import Path
import tempfile
import yaml
import pytest
import numpy as np
from astropy.io import fits

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.config.loader import (
    DEFAULT_CONFIG,
    resolve_group_registration_configs,
    resolve_registration,
    load_config,
)
from astro_process.config.models import (
    AppConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
    RegistrationConfig,
)
from astro_process.agents.cross_group import apply_cross_group_skip_filter
from astro_process.agents.merge_agent import MergeAgent
from astro_process.core.selection import _apply_selection_and_rejection
from astro_process.core.quality import FrameQuality

# Helpers for FIX-10 FITS creation

def _write_fits_with_header(path: Path, header_dict: dict, exptime: float = 30.0):
    data = np.zeros((16, 16), dtype=np.float32)
    hdu = fits.PrimaryHDU(data)
    for k, v in header_dict.items():
        hdu.header[k] = v
    hdu.header["EXPTIME"] = exptime
    hdu.header["GAIN"] = 40
    hdu.header["FILTER"] = header_dict.get("FILTER", "Duo-Band")
    hdu.writeto(path, overwrite=True)


class TestFix10PerGroup:
    """FIX-10: per-Gruppe auflösen, 15° vs 30°, CLI gewinnt."""

    def test_resolve_group_registration_configs_per_group(self, tmp_path):
        """AZ generic 30° astroalign, EQ fft, CLI override gewinnt per Gruppe — AC-REG-5."""
        cfg = load_config(None)  # DEFAULT_CONFIG includes dwarf_mini profile
        # Create two groups: AZ generic (Seestar) and EQ (unknown)
        az_header = {"TELESCOP": "Seestar S50", "EQMODE": 0, "FILTER": "Duo-Band"}
        eq_header = {"TELESCOP": "Unknown", "EQMODE": 1, "FILTER": "Astro"}
        az_path = tmp_path / "az_60s.fits"
        eq_path = tmp_path / "eq_30s.fits"
        _write_fits_with_header(az_path, az_header, exptime=60)
        _write_fits_with_header(eq_path, eq_header, exptime=30)

        groups = {
            "60s40_Duo-Band": [az_path],
            "30s40_Astro": [eq_path],
        }
        # EQMODE majority per group (DEF-009)
        eqmode_by_group = {
            "60s40_Duo-Band": {"majority": 0, "consistent": True, "counts": {"0": 1, "1": 0, "None": 0}},
            "30s40_Astro": {"majority": 1, "consistent": True, "counts": {"0": 0, "1": 1, "None": 0}},
        }
        result = resolve_group_registration_configs(
            cfg=cfg, groups=groups, cli_override=None, global_equipment=None, eqmode_by_group=eqmode_by_group
        )
        # AZ generic -> astroalign 30°
        assert result["60s40_Duo-Band"]["method"] == "astroalign"
        assert result["60s40_Duo-Band"]["max_rotation_deg"] == 30.0
        # EQ -> fft (short exptime, EQ mount)
        assert result["30s40_Astro"]["method"] == "fft"
        # CLI gewinnt per Gruppe
        result_cli = resolve_group_registration_configs(
            cfg=cfg, groups=groups, cli_override="fft", global_equipment=None, eqmode_by_group=eqmode_by_group
        )
        assert result_cli["60s40_Duo-Band"]["method"] == "fft"
        assert result_cli["30s40_Astro"]["method"] == "fft"

    def test_dwarf_mini_stays_15(self, tmp_path):
        """dwarf_mini bleibt 15°, generic AZ 30° — FIX-10 spec."""
        cfg = load_config(None)
        dwarf_header = {"TELESCOP": "Dwarf Mini", "EQMODE": 0, "FILTER": "Duo-Band"}
        generic_header = {"TELESCOP": "Seestar S50", "EQMODE": 0, "FILTER": "Duo-Band"}
        dwarf_path = tmp_path / "dwarf.fits"
        generic_path = tmp_path / "generic.fits"
        _write_fits_with_header(dwarf_path, dwarf_header, exptime=60)
        _write_fits_with_header(generic_path, generic_header, exptime=60)
        groups = {"dwarf": [dwarf_path], "generic": [generic_path]}
        eqmode = {
            "dwarf": {"majority": 0, "consistent": True, "counts": {"0": 1, "1": 0, "None": 0}},
            "generic": {"majority": 0, "consistent": True, "counts": {"0": 1, "1": 0, "None": 0}},
        }
        res = resolve_group_registration_configs(cfg=cfg, groups=groups, eqmode_by_group=eqmode)
        assert res["dwarf"]["max_rotation_deg"] == 15.0
        assert res["generic"]["max_rotation_deg"] == 30.0


class TestFix11DuoBandGate:
    """FIX-11: Duo-Band low_corr_roh ignore + min 0.05 Pfad + single fallback."""

    def test_low_corr_roh_ignored_for_duo_band(self, tmp_path):
        # Two groups, reference has high corr, Duo-Band non-ref has low corr_roh but ok corr_hp 0.3 >0.05
        ref = tmp_path / "ref.fits"
        duo = tmp_path / "duo.fits"
        ref.touch(); duo.touch()
        aligned = {"ref": ref, "duo": duo}
        regs = [
            {"group": "duo", "corr_hp": 0.30, "corr_roh": 0.001, "n_control_points": 50, "rotation_deg": 0.2},
        ]
        meta = {
            "ref": {"frame_count": 10, "filter": "Astro"},
            "duo": {"frame_count": 10, "filter": "Duo-Band"},
        }
        kept, skipped = apply_cross_group_skip_filter(
            aligned, regs, ref_hash="ref", min_correlation=0.1,
            group_metadata=meta, group_eqmode={"ref": 1, "duo": 1}, group_avg_rotation=0.0
        )
        # Duo-Band low_corr_roh sollte NICHT skippen (nur corr_hp zählt)
        assert "duo" in kept
        assert not any(s["group"] == "duo" for s in skipped)

    def test_effective_min_0_05_for_duo(self, tmp_path):
        ref = tmp_path / "ref.fits"
        duo = tmp_path / "duo.fits"
        ref.touch(); duo.touch()
        aligned = {"ref": ref, "duo": duo}
        # Duo with corr_hp 0.06 (<0.1 but >0.05) should be kept for Duo, skipped for Astro
        regs_duo = [{"group": "duo", "corr_hp": 0.06, "corr_roh": 0.2, "n_control_points": 50, "rotation_deg": 0.0}]
        meta_duo = {"ref": {"frame_count": 10, "filter": "Astro"}, "duo": {"frame_count": 10, "filter": "Duo-Band"}}
        kept_duo, _ = apply_cross_group_skip_filter(aligned, regs_duo, "ref", 0.1, group_metadata=meta_duo)
        assert "duo" in kept_duo  # 0.06 >= 0.05 kept

        # Same corr for Astro should be skipped (0.06 < 0.1)
        meta_astro = {"ref": {"frame_count": 10, "filter": "Astro"}, "duo": {"frame_count": 10, "filter": "Astro"}}
        kept_astro, skipped_astro = apply_cross_group_skip_filter(aligned, regs_duo, "ref", 0.1, group_metadata=meta_astro)
        assert "duo" not in kept_astro
        assert any(s["group"] == "duo" for s in skipped_astro)

    def test_single_stack_fallback(self, tmp_path):
        work = tmp_path / "work"
        work.mkdir()
        ma = MergeAgent(work, config=None)
        # Create single stacked.fits
        single = work / "group_a_04" / "stacked.fits"
        single.parent.mkdir(parents=True)
        data = np.ones((8, 8, 3), dtype=np.float32) * 10
        hdu = fits.PrimaryHDU(data.transpose(2, 0, 1))
        hdu.writeto(single, overwrite=True)
        stacks = {"a": single}
        meta = {"a": {"frame_count": 10, "total_exposure": 100}}
        res = ma.run(stacks, meta, target_name="Test")
        # FIX-11: should not be error, should have merged_path via fallback
        assert res.merged_path is not None
        assert res.merged_path.exists()


class TestFix12MandatoryGate:
    """FIX-12: Mandatory Gate 0.05 auch bei frame_selection false."""

    def test_mandatory_gate_active_when_frame_selection_disabled(self):
        # frame_selection disabled but mandatory gate should still reject corr <0.05
        from astro_process.config.models import FrameSelectionConfig
        fs = FrameSelectionConfig(enabled=False, keep_percentile=92, min_frames=3)
        # 3 frames: reference None correlation, two with low corr
        p1 = Path("/tmp/reg_0001.fits")
        p2 = Path("/tmp/reg_0002.fits")
        p3 = Path("/tmp/reg_0003.fits")
        registered = [p1, p2, p3]
        q1 = FrameQuality(frame=str(p1), correlation=None, outlier_excluded=False)
        q2 = FrameQuality(frame=str(p2), correlation=0.02, outlier_excluded=False)
        q3 = FrameQuality(frame=str(p3), correlation=0.8, outlier_excluded=False)
        filtered, report = _apply_selection_and_rejection(
            registered, [q1, q2, q3], fs, rejection_enabled=False, rejection_thresholds={}, rejection_elongation=True, group_hash="test", mandatory_min_corr_hp=0.05
        )
        # p2 (0.02 <0.05) should be threshold_rejected via mandatory gate
        assert p2.as_posix() not in [p.as_posix() for p in filtered]
        assert report["threshold_rejected"] >= 1
        assert report["min_corr_hp"] == 0.05

    def test_models_default_0_05(self):
        cfg = RegistrationConfig()
        assert cfg.zero_shift_threshold == 0.05
        pp = ProcessingParams()
        assert pp.rejection_min_corr_hp == 0.05
        app = AppConfig()
        assert app.rejection_min_corr_hp == 0.05
        # resolve_registration default should be 0.05
        preset = PipelinePreset(name="x", target_types=["star"], steps=[], processing_params=ProcessingParams())
        res = resolve_registration(AppConfig(), preset)
        assert res.zero_shift_threshold == 0.05


class TestFix13PccRosa:
    """FIX-13: PCC Rosa — preview_export scnr:true für nebula presets."""

    def test_default_config_nebula_scnr_true(self):
        data = yaml.safe_load(DEFAULT_CONFIG)
        neb = next(p for p in data["pipeline_presets"] if p["name"] == "nebula_standard")
        assert neb["processing_params"]["preview_export"]["scnr"] is True
        nb = next(p for p in data["pipeline_presets"] if p["name"] == "nebula_narrowband")
        assert nb["processing_params"]["preview_export"]["scnr"] is True
        # star_standard has no scnr true requirement (but preview still there? check not required)
        # And ensure nebula presets have no PCC step (only star/galaxy have PCC)
        assert not any(s["name"] == "photometric_color_calibration" for s in neb["steps"])
        assert not any(s["name"] == "photometric_color_calibration" for s in nb["steps"])
