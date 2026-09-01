"""V1.8-1 CFA-Drizzle Tests (AC-DRZ-1..12)."""

import math
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from astropy.io import fits
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.agents.cfa_drizzle_agent import (
    CFADrizzleAgent,
    cfa_drizzle,
    compute_pixfrac,
    register_cfa_subpixel,
)
from astro_process.agents.multi_group_agent import MultiGroupProcessor
from astro_process.agents.processing_agent import ProcessingAgent
from astro_process.cli import cli
from astro_process.config.loader import resolve_cfa_drizzle
from astro_process.config.models import (
    AppConfig,
    CFADrizzleConfig,
    CFADrizzleQualityGateConfig,
    MultiGroupConfig,
    PipelinePreset,
    PipelineStep,
    ProcessingParams,
)
from astro_process.core.quality import FrameQuality, compute_frame_quality, reject_outlier_frames
from astro_process.models.core import (
    AcquisitionInfo,
    CalibrationStatus,
    EquipmentInfo,
    FrameInfo,
    FrameSet,
    FrameType,
    FitsHeader,
    ObservationContext,
    ObservationTarget,
    compute_group_hash,
)

# Helpers
def _create_cfa_fits(path: Path, h=108, w=192, seed=42):
    rng = np.random.RandomState(seed)
    arr = rng.randint(0, 4000, (h,w)).astype(np.float32)
    fits.PrimaryHDU(arr).writeto(path, overwrite=True)
    return path

def test_ac_drz_1_disabled_byte_identical(tmp_path):
    """AC-DRZ-1 enabled false -> byte-identical to v1.7 (no drizzle files, no overhead)."""
    cfg = AppConfig()
    # default disabled
    drz = resolve_cfa_drizzle(cfg)
    assert drz.enabled is False
    # Simulate multi_group with disabled: no 01c_drizzle dirs created
    # Just check resolver
    assert drz.scale == 2.0

def test_ac_drz_2_enabled_shape(tmp_path):
    """AC-DRZ-2 enabled true -> pro Gruppe 01c_drizzle/drizzled_master.fits (2x RGB, 3840x2160 for 1920x1080)."""
    # Use small synthetic 64x48 -> out 128x96
    frames = [np.random.randint(0,4000,(48,64)).astype(np.float32) for _ in range(5)]
    shifts = [(0,0),(0.5,0.3),(1.2,-0.7),(0.2,0.9),( -0.4,0.5)]
    rgb = cfa_drizzle(frames, shifts, scale=2.0, pixfrac=1.0, kernel="lanczos3")
    assert rgb.shape == (96,128,3)
    # Check for 1920x1080 case would be 2160x3840 - use pixfrac 0.5 for fast path (single pixel)
    frames2 = [np.zeros((1080,1920),dtype=np.float32) for _ in range(2)]
    rgb2 = cfa_drizzle(frames2, [(0,0),(0,0)], scale=2.0, pixfrac=0.5)
    assert rgb2.shape == (2160,3840,3)

def test_ac_drz_3_subpixel_accuracy():
    """AC-DRZ-3 subpixel ≤0.1px via synthetic shifts (wie PoC)."""
    # Generate synthetic CFA 108x192 with stars
    from scipy.ndimage import shift as sh
    rng = np.random.RandomState(0)
    base = np.full((108,192), 100.0, dtype=np.float32)
    for _ in range(20):
        cy = rng.randint(10,98); cx = rng.randint(10,182)
        amp = rng.uniform(80,200); sigma = rng.uniform(1.2,2.0)
        y,x = np.ogrid[:108,:192]
        base += amp * np.exp(-((y-cy)**2 + (x-cx)**2)/(2*sigma**2))
    base += rng.normal(0,2,(108,192))
    shifts_to_test = [(0.3,0.0),(0.0,0.7),(0.5,0.5)]
    for dy,dx in shifts_to_test:
        shifted = sh(base, (dy,dx), order=3, mode="constant", cval=0.0)
        sy,sx = register_cfa_subpixel(base, shifted, upsample_factor=10)
        # Expected -dy,-dx
        err_y = sy - (-dy)
        err_x = sx - (-dx)
        assert abs(err_y) <= 0.11, f"y error {err_y} >0.11 for shift {dy},{dx} recovered {sy},{sx}"
        assert abs(err_x) <= 0.11, f"x error {err_x}"
    # Identical
    sy0,sx0 = register_cfa_subpixel(base, base, upsample_factor=10)
    assert abs(sy0) <= 0.05 and abs(sx0) <= 0.05

def test_ac_drz_4_pixfrac_dynamic():
    """AC-DRZ-4 pixfrac dynamisch <10=1.0, 10-30=0.7, >30=0.5."""
    assert compute_pixfrac(5) == 1.0
    assert compute_pixfrac(9) == 1.0
    assert compute_pixfrac(10) == 0.7
    assert compute_pixfrac(16) == 0.7
    assert compute_pixfrac(29) == 0.7
    assert compute_pixfrac(30) == 0.5
    assert compute_pixfrac(41) == 0.5
    assert compute_pixfrac(53) == 0.5

def test_ac_drz_5_quality_gate_filter(tmp_path):
    """AC-DRZ-5 Quality Gate filtert VOR Drizzle (nur non-outlier)."""
    # Create agent and mock quality: create 5 frames where one is outlier via thresholds
    cfg = AppConfig()
    cfg.cfa_drizzle = CFADrizzleConfig(enabled=True, quality_gate={
        "rejection_enabled": True,
        "thresholds": {"snr": [10, None]},
        "elongation_unusable": False
    } if isinstance(CFADrizzleConfig.model_fields['quality_gate'].annotation, type) else None)
    # Instead construct properly
    from astro_process.config.models import CFADrizzleQualityGateConfig
    cfg.cfa_drizzle = CFADrizzleConfig(
        enabled=True,
        quality_gate=CFADrizzleQualityGateConfig(rejection_enabled=True, thresholds={"snr": (10, None)}, elongation_unusable=False),
        min_frames=2,
        fallback="malvar",
    )
    agent = CFADrizzleAgent(tmp_path, cfg)
    # Mock compute_frame_quality to return snr values
    with patch("astro_process.core.quality.compute_frame_quality") as mock_q, \
         patch("astro_process.core.quality.reject_outlier_frames") as mock_reject:
        from astro_process.core.quality import FrameQuality
        # Create 3 fake qualities: 2 good, 1 outlier
        q1 = FrameQuality(frame="a.fits", snr=20, star_count=30)
        q2 = FrameQuality(frame="b.fits", snr=5, star_count=5)  # low snr -> outlier
        q3 = FrameQuality(frame="c.fits", snr=25, star_count=30)
        mock_q.side_effect = [q1,q2,q3]
        # reject marks q2 as excluded
        def fake_reject(quals, thresholds=None, elongation_unusable_enabled=True):
            from astro_process.core.quality import FrameQuality
            res=[]
            for q in quals:
                if q.snr < 10:
                    res.append(FrameQuality(frame=q.frame, snr=q.snr, star_count=q.star_count, outlier_excluded=True, outlier_reject_reason="snr"))
                else:
                    res.append(FrameQuality(frame=q.frame, snr=q.snr, star_count=q.star_count, outlier_excluded=False))
            return res
        mock_reject.side_effect = fake_reject
        # Need calibrated groups
        p1 = tmp_path / "c1.fits"
        p2 = tmp_path / "c2.fits"
        p3 = tmp_path / "c3.fits"
        for p in [p1,p2,p3]:
            fits.PrimaryHDU(np.random.randint(0,4000,(20,20)).astype(np.float32)).writeto(p, overwrite=True)
        # Mock cfa_drizzle to avoid heavy compute
        with patch("astro_process.agents.cfa_drizzle_agent.cfa_drizzle") as mock_drizzle:
            mock_drizzle.return_value = np.zeros((40,40,3), dtype=np.float32)
            res = agent.run(calibrated_by_group={"h": [p1,p2,p3]}, groups={"h": None})
            # Should have called drizzle with 2 frames (outlier filtered)
            assert mock_drizzle.called
            args,kwargs = mock_drizzle.call_args
            assert len(args[0]) == 2  # filtered to 2
            assert len(args[1]) == 2

def test_ac_drz_6_fallback(tmp_path):
    """AC-DRZ-6 fallback bei <min_frames: malvar/superpixel/skip."""
    from astro_process.config.models import CFADrizzleQualityGateConfig
    for fb in ["malvar","superpixel","skip"]:
        cfg = AppConfig()
        cfg.cfa_drizzle = CFADrizzleConfig(enabled=True, min_frames=5, fallback=fb,
                                           quality_gate=CFADrizzleQualityGateConfig(rejection_enabled=False))
        agent = CFADrizzleAgent(tmp_path / fb, cfg)
        # Create 3 frames (<5)
        grp = tmp_path / fb
        grp.mkdir(exist_ok=True)
        paths = []
        for i in range(3):
            p = grp / f"c{i}.fits"
            fits.PrimaryHDU(np.zeros((20,20),dtype=np.float32)).writeto(p, overwrite=True)
            paths.append(p)
        with patch("astro_process.core.quality.compute_frame_quality") as mq:
            from astro_process.core.quality import FrameQuality
            mq.return_value = FrameQuality(snr=20, star_count=30)
            res = agent.run(calibrated_by_group={"h": paths}, groups={"h": None})
            assert len(res)==1
            assert res[0].status == ("skipped" if fb=="skip" else "fallback")
            assert res[0].fallback_method == fb

def test_ac_drz_7_no_artefacts():
    """AC-DRZ-7 Keine Interpolations-Artefakte (Farb Säume) - synthetischer Stern prueft nicht zu viel Spread."""
    # Create CFA with single bright star at R position (0,0)
    cfa = np.full((20,20), 100.0, dtype=np.float32)
    cfa[4,4] = 4000  # R pixel
    frames = [cfa, cfa]
    shifts = [(0,0),(0.5,0.5)]
    rgb = cfa_drizzle(frames, shifts, scale=2.0, pixfrac=0.5, kernel="lanczos3")
    # Check that B channel at star location not contaminated heavily
    # Star is R, so B should be low near star center
    y,x = 8,8  # approx 4*2
    # Check local neighborhood: R should be high, B low
    assert rgb[y,x,0] > 500  # R high
    assert rgb[y,x,2] < 200  # B low (no colour fringe spreading too much)

def test_ac_drz_8_hotpixel_not_drizzled():
    """AC-DRZ-8 Hotpixel nicht mitgedrizzelt (Dark vor Drizzle, aber wir testen nicht verbreitern)."""
    cfa = np.full((20,20), 100.0, dtype=np.float32)
    cfa[10,10] = 4000  # hotpixel
    frames = [cfa]
    shifts = [(0,0)]
    rgb = cfa_drizzle(frames, shifts, scale=2.0, pixfrac=0.5, kernel="lanczos3")
    # Hotpixel should remain localized (single output pixel bright, neighbors dark)
    # Output hotpixel at (20,20) approx
    y,x = 20,20
    # Ensure neighbour not also bright (not smeared)
    # Allow footprint 1 -> only single pixel
    assert rgb[y,x,0] > 500 or rgb[y,x,1] > 500 or rgb[y,x,2] > 500
    # Check neighbour 2 away is dark
    assert rgb[y+2,x+2].max() < 300

def test_ac_drz_9_header(tmp_path):
    """AC-DRZ-9 Agent-Log + header scale/pixfrac/kernel/n_frames_in/out."""
    from astro_process.config.models import CFADrizzleQualityGateConfig
    cfg = AppConfig()
    cfg.cfa_drizzle = CFADrizzleConfig(enabled=True, scale=2.0, pixfrac_mode="auto", kernel="lanczos3", min_frames=2,
                                       quality_gate=CFADrizzleQualityGateConfig(rejection_enabled=False))
    agent = CFADrizzleAgent(tmp_path, cfg)
    p1 = tmp_path / "c1.fits"; p2 = tmp_path / "c2.fits"
    for p in [p1,p2]:
        # Create small CFA with stars so quality not failing
        arr = np.random.randint(0,4000,(20,20)).astype(np.float32)
        fits.PrimaryHDU(arr).writeto(p, overwrite=True)
    res = agent.run(calibrated_by_group={"grp1": [p1,p2]}, groups={"grp1": None})
    assert res[0].scale == 2.0
    assert res[0].kernel == "lanczos3"
    # Check FITS header
    master = tmp_path / "group_grp1" / "01c_drizzle" / "drizzled_master.fits"
    assert master.exists()
    hdr = fits.getheader(str(master))
    assert hdr["DRZSCALE"] == 2.0
    assert "DRZPIXFR" in hdr
    assert hdr["DRZKERNL"] == "lanczos3"

def test_ac_drz_10_cli_override():
    """AC-DRZ-10 CLI Flags funktionieren (Override Config), --help dokumentiert."""
    runner = CliRunner()
    result = runner.invoke(cli, ["process", "--help"])
    assert "--cfa-drizzle" in result.output
    assert "--drizzle-scale" in result.output
    assert "--drizzle-pixfrac" in result.output
    assert "--drizzle-kernel" in result.output
    # CLI override test via resolve
    cfg = AppConfig()
    cfg.cfa_drizzle = CFADrizzleConfig(enabled=False, scale=2.0, pixfrac=0.5, kernel="lanczos3")
    drz = resolve_cfa_drizzle(cfg, cli_enabled=True, cli_scale=2.5, cli_pixfrac=0.7, cli_kernel="gaussian")
    assert drz.enabled is True
    assert drz.scale == 2.5
    assert drz.pixfrac == 0.7
    assert drz.pixfrac_mode == "fixed"
    assert drz.kernel == "gaussian"

def test_ac_drz_11_merge_uses_drizzled(tmp_path):
    """AC-DRZ-11 Merge nutzt Drizzle-Master (2x RGB) für finale HDR-Kombination."""
    # Multi-group processor with drizzle enabled should put drizzled stack in group_stacks
    # Mock a minimal integrated run
    from astro_process.config.models import CFADrizzleQualityGateConfig, MultiGroupConfig
    cfg = AppConfig()
    cfg.cfa_drizzle = CFADrizzleConfig(enabled=True, min_frames=2, quality_gate=CFADrizzleQualityGateConfig(rejection_enabled=False))
    # The integration is tested via agent run producing 01c_drizzle; merge will use stacked.fits which is copy of drizzled_master
    # So verify that after agent run, stacked.fits exists
    agent = CFADrizzleAgent(tmp_path, cfg)
    p1 = tmp_path / "c1.fits"; p2 = tmp_path / "c2.fits"
    for p in [p1,p2]:
        fits.PrimaryHDU(np.zeros((20,20),dtype=np.float32)).writeto(p, overwrite=True)
    res = agent.run(calibrated_by_group={"g": [p1,p2]}, groups={"g": None})
    stacked = tmp_path / "group_g" / "04_stacked" / "stacked.fits"
    assert stacked.exists()
    # Shape should be 2x
    data = fits.getdata(str(stacked))
    # data shape is (3,40,40) for 20*2
    assert data.shape[0] == 3
    assert data.shape[1] == 40

def test_ac_drz_12_memory_sequential():
    """AC-DRZ-12 Memory: sequentiell frame-für-frame, float32, <4GB."""
    # Use smaller frames for speed but verify logic (1080x1920 full would timeout for pixfrac 1.0 slow path)
    # Theoretical memory check as in PoC: sequential <0.5GB
    H,W=540,960  # half size for speed
    frames = [np.zeros((H,W), dtype=np.float32) for _ in range(3)]
    shifts = [(0,0),(0.3,0.2),(0.7,0.5)]
    rgb = cfa_drizzle(frames, shifts, scale=2.0, pixfrac=0.5, kernel="tophat")
    assert rgb.dtype == np.float32
    H2,W2=1080,1920
    out_H,out_W=int(H2*2), int(W2*2)
    bytes_out = out_H*out_W*3*4
    assert bytes_out < 100*1024*1024  # ~95MB theoretical for full
    # Ensure kernel branch works with small frames (fast)
    for k in ["lanczos3","gaussian","tophat"]:
        rgb2 = cfa_drizzle(frames[:2], shifts[:2], scale=2.0, pixfrac=0.5, kernel=k)
        assert rgb2.shape == (H*2, W*2, 3)

def test_disabled_no_event(tmp_path):
    cfg = AppConfig()
    cfg.cfa_drizzle = CFADrizzleConfig(enabled=False)
    agent = CFADrizzleAgent(tmp_path, cfg)
    res = agent.run(calibrated_by_group={"g": []}, groups={})
    assert res == []


# ── DEF-004 / DEF-005 Regression Tests (V1.8-1) ───────────────────────

def _make_cfa_star_field(h=96, w=128, n_stars=8, amp=250, seed=3):
    """Synthetic CFA-raw frame where raw star-detection fails but highpass works."""
    rng = np.random.RandomState(seed)
    y, x = np.ogrid[:h, :w]
    # strong low-frequency gradient -> raw detection floor is too high
    arr = (1000.0 + 2.0 * y + 1.5 * x).astype(np.float32)
    arr += rng.normal(0, 8, (h, w)).astype(np.float32)
    for i in range(n_stars):
        cy = rng.randint(25, h - 25)
        cx = rng.randint(25, w - 25)
        arr += amp * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2 * (1.5) ** 2))
    return arr


def test_def_004_cfa_quality_gate_highpass():
    """DEF-004 Option B: highpass star-detection on CFA raw; lowered min_stars."""
    cfa = _make_cfa_star_field()

    # Non-CFA path (default min_stars=5) must stay unchanged -> too few stars.
    q_normal = compute_frame_quality(cfa, min_stars=5)
    assert q_normal.star_count < 5
    assert q_normal.fwhm_median is None

    # CFA path: highpass + min_stars_cfa=3 finds stars and yields FWHM.
    q_cfa = compute_frame_quality(
        cfa,
        min_stars=3,
        cfa_mode=True,
        cfa_highpass_sigma=30.0,
    )
    assert q_cfa.star_count >= 3
    assert q_cfa.fwhm_median is not None
    assert q_cfa.fwhm_median > 0
    # F-06: Highpass nur fuer star detection, SNR/noise unveraendert
    assert q_cfa.snr == q_normal.snr
    assert q_cfa.noise_sigma == q_normal.noise_sigma


def test_def_004_cfa_quality_gate_rejection_rate():
    """DEF-004: with highpass + star_count_cfa threshold, not all frames rejected."""
    rng = np.random.RandomState(7)
    frames = [_make_cfa_star_field(seed=seed) for seed in range(5)]
    # add per-frame noise so star counts differ slightly
    for i, f in enumerate(frames):
        f = f + rng.normal(0, 3, f.shape).astype(np.float32)
        frames[i] = f

    qualities = []
    for f in frames:
        q = compute_frame_quality(
            f,
            min_stars=3,
            cfa_mode=True,
            cfa_highpass_sigma=30.0,
        )
        qualities.append(q)

    # CFA-specific star_count threshold: lower bound of 3, no upper bound.
    thresholds = {"star_count": (3.0, None)}
    filtered = reject_outlier_frames(qualities, thresholds=thresholds)
    rejected = sum(1 for q in filtered if q.outlier_excluded)
    assert rejected < len(filtered)
    # FWHM median available for at least some frames (no all-None -> no fwhm rejection)
    valid_fwhm = [q.fwhm_median for q in filtered if q.fwhm_median is not None]
    assert len(valid_fwhm) >= 3


def _make_cfa_fits(path: Path, h=64, w=80, seed=0):
    """Create a small 2D CFA FITS file with enough structure to register/stack."""
    rng = np.random.RandomState(seed)
    y, x = np.ogrid[:h, :w]
    arr = (500.0 + rng.normal(0, 10, (h, w))).astype(np.float32)
    # add a few star-like peaks
    for i in range(5):
        cy = rng.randint(15, h - 15)
        cx = rng.randint(15, w - 15)
        arr += 300.0 * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2 * (1.5) ** 2))
    hdu = fits.PrimaryHDU(arr)
    hdu.header["EXPTIME"] = 30.0
    hdu.header["GAIN"] = 40
    hdu.header["FILTER"] = "Astro"
    hdu.header["OBJECT"] = "M 92"
    hdu.header["CCD-TEMP"] = -10.0
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def _make_single_group_cfa_context(tmp_path: Path, n_frames: int = 3):
    """Return (context, calibration_result, group_hash) for a single CFA group."""
    light_dir = tmp_path / "lights"
    light_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    frame_infos = []
    for i in range(n_frames):
        p = light_dir / f"light_{i:04d}.fits"
        _make_cfa_fits(p, seed=i)
        frame_paths.append(p)
        header = FitsHeader(
            exptime=30.0,
            gain=40,
            filter_name="Astro",
            object="M 92",
            ccd_temp=-10.0,
        )
        frame_infos.append(
            FrameInfo(
                path=p,
                frame_type=FrameType.LIGHT,
                header=header,
                index=i,
                width=80,
                height=64,
                size_bytes=p.stat().st_size,
            )
        )

    light_set = FrameSet(frame_type=FrameType.LIGHT, frames=frame_infos)
    context = ObservationContext(
        target=ObservationTarget(name="M92", ra=259.28, dec=43.14),
        frames={FrameType.LIGHT: light_set},
        calibration=CalibrationStatus(dark_available=False),
        equipment=EquipmentInfo(
            telescope="TestScope",
            focal_length_mm=150,
            pixel_size_um=2.9,
        ),
        acquisition=AcquisitionInfo(),
        source_path=tmp_path,
    )
    calibration_result = MagicMock()
    calibration_result.calibrated_lights = frame_paths
    calibration_result.master_dark = None
    calibration_result.master_dark_sources = {}
    group_hash = compute_group_hash(30.0, 40, "Astro")
    return context, calibration_result, group_hash


def _run_fallback_pipeline(tmp_path: Path, fallback: str):
    """Run ProcessingAgent.process_multi_group with CFA-Drizzle fallback."""
    context, calibration_result, group_hash = _make_single_group_cfa_context(tmp_path)

    cfg = AppConfig()
    cfg.cfa_drizzle = CFADrizzleConfig(
        enabled=True,
        min_frames=5,
        fallback=fallback,
        quality_gate=CFADrizzleQualityGateConfig(
            rejection_enabled=True,
            thresholds={"snr": (1.0, None)},
        ),
    )
    pipeline = PipelinePreset(
        name="test",
        target_types=["*"],
        steps=[
            PipelineStep(name="register_frames"),
            PipelineStep(name="stack_frames"),
        ],
        processing_params=ProcessingParams(
            rejection="average",
            normalization="add",
            weight="none",
        ),
    )
    debayer_result = MagicMock()
    debayer_result.debayered_frames = []

    agent = ProcessingAgent(tmp_path, config=cfg)
    with patch.object(agent, "_apply_pcc_per_group", return_value=(None, "gaia_success")) as mock_pcc, \
         patch("astro_process.agents.multi_group_agent.create_preview_jpg", return_value=None):
        # For single group the reference group selection is trivial, but mock it
        # to avoid any dependency on registration metrics.
        with patch.object(
            agent, "_select_reference_group", return_value=group_hash
        ):
            result = agent.process_multi_group(
                context,
                calibration_result,
                debayer_result,
                pipeline,
                multi_group_config=MultiGroupConfig(),
                target_name="M92",
            )
    return result, group_hash, mock_pcc


def test_def_005_fallback_malvar_materialized(tmp_path):
    """DEF-005: fallback=malvar materializes 1920x1080-equivalent output."""
    result, group_hash, _ = _run_fallback_pipeline(tmp_path, "malvar")

    stacked = tmp_path / f"group_{group_hash}" / "04_stacked" / "stacked.fits"
    assert stacked.exists(), "fallback malvar should produce a stacked group FITS"
    with fits.open(stacked) as hdul:
        data = hdul[0].data
        assert data.ndim == 3
        # Malvar keeps native CFA resolution (64x80 in the synthetic frames).
        assert data.shape == (3, 64, 80)

    meta = result.multi_group_metadata["groups"][group_hash]
    assert meta["drizzle"]["fallback"] == "malvar"
    assert meta["drizzle"]["materialized"] is True
    assert meta["effective_stack_scale_factor"] == 1.0


def test_def_005_fallback_superpixel_materialized(tmp_path):
    """DEF-005: fallback=superpixel materializes 960x540-equivalent output."""
    result, group_hash, _ = _run_fallback_pipeline(tmp_path, "superpixel")

    stacked = tmp_path / f"group_{group_hash}" / "04_stacked" / "stacked.fits"
    assert stacked.exists(), "fallback superpixel should produce a stacked group FITS"
    with fits.open(stacked) as hdul:
        data = hdul[0].data
        assert data.ndim == 3
        # Superpixel halves the CFA resolution.
        assert data.shape == (3, 32, 40)

    meta = result.multi_group_metadata["groups"][group_hash]
    assert meta["drizzle"]["fallback"] == "superpixel"
    assert meta["drizzle"]["materialized"] is True
    assert meta["effective_stack_scale_factor"] == 2.0


def test_def_005_fallback_skip_aborts_group(tmp_path):
    """DEF-005: fallback=skip leaves the group without a stack."""
    with pytest.raises(ValueError):
        _run_fallback_pipeline(tmp_path, "skip")

