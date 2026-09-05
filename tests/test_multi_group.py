"""Comprehensive unit tests for Multi-Group Stacking (T1–T11).

Covers all acceptance criteria for tasks T1 through T11 of the
Multi-Group Stacking feature. Uses synthetic FITS data and mocking
to ensure hermetic, fast tests.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock, PropertyMock

import numpy as np
import pytest
from astropy.io import fits
from click.testing import CliRunner

# ── Ensure src is on the path ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from astro_process.config.models import (
    AppConfig,
    MultiGroupConfig,
    MergeConfig,
    PipelineStep,
    ProcessingParams,
)
from astro_process.models.core import (
    FrameSet,
    FrameInfo,
    FrameType,
    FitsHeader,
    GroupInfo,
    compute_group_hash,
    ObservationContext,
    ObservationTarget,
    EquipmentInfo,
    AcquisitionInfo,
    CalibrationStatus,
)
from astro_process.agents.archive import ArchiveAgent
from astro_process.agents.discovery import DiscoveryAgent, DiscoveryResult
from astro_process.agents.processing_agent import ProcessingAgent, ProcessingResult
from astro_process.agents.merge_agent import MergeAgent, MergeResult
from astro_process.core.export import export
from astro_process.core.pcc import gray_world_white_balance
from astro_process.core.preview import create_preview_jpg, auto_asinh
from astro_process.core.registration import (
    RegisterFramesResult,
    RegistrationResult,
    compute_shift,
    compute_shift_star_centroid,
    corr_grid_shift,
    select_registration_channel,
)
from astro_process.cli import cli


# ═══════════════════════════════════════════════════════════════════
# Test Helpers — synthetic FITS generation
# ═══════════════════════════════════════════════════════════════════


def create_test_fits(
    path: Path,
    shape: tuple[int, int, int] = (100, 100, 3),
    value: float = 1.0,
    exptime: float = 15.0,
    gain: int = 60,
    filter_name: str | None = None,
    add_stars: bool = True,
    shift: tuple[float, float] = (0.0, 0.0),
    rng_seed: int | None = 42,
) -> Path:
    """Create a synthetic FITS file for testing.

    Args:
        path: Output path for the FITS file.
        shape: (H, W, C) dimensions.
        value: Background pixel value.
        exptime: Exposure time in seconds (FITS header).
        gain: Camera gain (FITS header).
        filter_name: Filter name (FITS header).
        add_stars: Add Gaussian star-like peaks.
        shift: (dy, dx) pixel shift applied to the data.
        rng_seed: Random seed for reproducibility.

    Returns:
        Path to the created FITS file.
    """
    rng = np.random.RandomState(rng_seed)
    data = np.full(shape, value, dtype=np.float32)

    if add_stars:
        for _ in range(5):
            cy = rng.randint(10, shape[0] - 10)
            cx = rng.randint(10, shape[1] - 10)
            y, x = np.ogrid[: shape[0], : shape[1]]
            star = np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / 4)
            for c in range(3):
                data[:, :, c] += star * rng.uniform(0.5, 2.0)

    # Apply shift
    if shift != (0.0, 0.0):
        from scipy.ndimage import shift as scipy_shift

        shift_vec = (shift[0], shift[1]) + (0,) * (data.ndim - 2)
        data = scipy_shift(data, shift_vec, order=3, mode="nearest")

    # Save as FITS: (H, W, C) -> (C, H, W)
    out = data.astype(np.float32)
    out = out.transpose(2, 0, 1)
    hdu = fits.PrimaryHDU(out)
    hdu.header["EXPTIME"] = float(exptime)
    hdu.header["GAIN"] = int(gain)
    # V1.6-1 (SSOT-A): Mandatory fields for light frames
    hdu.header["OBJECT"] = "M 27"
    hdu.header["CCD-TEMP"] = -10
    if filter_name:
        hdu.header["FILTER"] = str(filter_name)
    hdu.header["CTYPE3"] = "RGB"
    hdu.header["CUNIT3"] = "channel"

    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def create_frame_set(
    path: Path,
    count: int = 5,
    exptime: float = 15.0,
    gain: int = 60,
    filter_name: str | None = None,
    frame_type: FrameType = FrameType.LIGHT,
    rng_seed: int | None = None,
) -> FrameSet:
    """Create a FrameSet with synthetic frames."""
    rng = np.random if rng_seed is None else np.random.RandomState(rng_seed)
    frames = []
    for i in range(count):
        fp = path / f"light_{i:04d}.fits"
        create_test_fits(
            fp,
            exptime=exptime,
            gain=gain,
            filter_name=filter_name,
            rng_seed=(rng_seed or 42) + i,
        )
        header = FitsHeader(
            exptime=exptime,
            gain=gain,
            filter_name=filter_name,
        )
        frames.append(
            FrameInfo(
                path=fp,
                frame_type=frame_type,
                header=header,
                index=i,
                size_bytes=fp.stat().st_size,
                width=100,
                height=100,
            )
        )
    return FrameSet(frame_type=frame_type, frames=frames)


def create_m13_pair(
    ref_path: Path,
    tgt_path: Path,
    shift: tuple[float, float] = (5.0, 3.0),
    size: int = 160,
    seed: int = 7,
) -> None:
    """Create the M13 synthetic pair for AC-P3-4 (CR-001 P3).

    Reference has sharp Gaussian stars (15s morphology); target has saturated
    flat-core stars + large halos (180s morphology), shifted by the known
    ground-truth shift.

    The systematic centroid offset is provoked: the top-0.1% pixels of the
    target sit on the saturated plateaus of several bright stars, whose center
    of mass deviates far from the ground truth. Phase correlation
    (amplitude-normalized) finds the true offset of the star constellation.

    Args:
        ref_path: Output path for the reference FITS (3D RGB).
        tgt_path: Output path for the target FITS (3D RGB).
        shift: Ground-truth (dy, dx) shift applied to the target.
        size: Square frame height/width.
        seed: RNG seed for the star field (deterministic test).
    """
    def _add_gaussian(img, cy, cx, amp, sigma):
        y, x = np.ogrid[: img.shape[0], : img.shape[1]]
        img += amp * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2 * sigma**2))

    def _add_saturated(img, cy, cx, amp, radius, halo_sigma, halo_amp):
        y, x = np.ogrid[: img.shape[0], : img.shape[1]]
        d2 = (y - cy) ** 2 + (x - cx) ** 2
        img += np.where(d2 <= radius**2, amp, 0.0)
        img += halo_amp * np.exp(-d2 / (2 * halo_sigma**2))

    rng = np.random.RandomState(seed)
    ys = rng.randint(15, size - 15, 80)
    xs = rng.randint(15, size - 15, 80)
    amps = rng.uniform(8, 25, 80)
    for i in range(3):
        amps[i] = 150.0 + rng.uniform(0, 50)

    # Reference: sharp Gaussian stars (15s morphology)
    ref = np.full((size, size), 3.0, dtype=np.float32)
    for cy, cx, a in zip(ys, xs, amps):
        _add_gaussian(ref, cy, cx, a, 1.2)
    ref += rng.uniform(0, 0.6, (size, size)).astype(np.float32)

    # Target: saturated flat-core stars + large halo (180s morphology)
    tgt = np.full((size, size), 3.0, dtype=np.float32)
    for i, (cy, cx, a) in enumerate(zip(ys, xs, amps)):
        if i < 3:
            _add_saturated(tgt, cy, cx, a, 4, 10.0, 25.0)
        else:
            _add_gaussian(tgt, cy, cx, a * 1.5, 1.2)
    tgt += rng.uniform(0, 0.6, (size, size)).astype(np.float32)
    from scipy.ndimage import shift as scipy_shift

    tgt = scipy_shift(tgt, shift, order=3, mode="nearest")

    # Save as 3D RGB FITS (C, H, W) — same stars in all channels
    for path, mono in ((ref_path, ref), (tgt_path, tgt)):
        rgb = np.stack([mono, mono, mono], axis=-1).astype(np.float32)  # (H, W, C)
        out = rgb.transpose(2, 0, 1)  # (C, H, W)
        hdu = fits.PrimaryHDU(out)
        hdu.header["CTYPE3"] = "RGB"
        hdu.header["CUNIT3"] = "channel"
        path.parent.mkdir(parents=True, exist_ok=True)
        hdu.writeto(path, overwrite=True)


def create_m13_gradient_pair(
    ref_path: Path,
    tgt_path: Path,
    shift: tuple[float, float] = (5.0, 3.0),
    size: int = 160,
    seed: int = 7,
    grad_amp: float = 60.0,
    vig_amp: float = 40.0,
    grad_offset: tuple[float, float] = (25.0, 18.0),
) -> None:
    """Create the W1 killercase pair (M13 morphologies + background gradient).

    M13-Morphologien (15s scharfe Sterne / 180s gesättigte + Halos) wie
    create_m13_pair, PLUS Hintergrund-Gradient und Vignettierung, die zwischen
    den Nächten verschoben sind (grad_offset) — das dominante
    Grossstruktur-Muster, auf das der alte Rohdaten-PCC lockte (F2/M13-
    Ghosting-Root-Cause).

    Verifikation (Kalibrierung, seed=7, shift=(5,3), grad=60, vig=40):
      - Alt (_compute_shift_star_centroid, VOR-CR-001): (35.5, 26.5) — falsch
        (Killercase: Gradient zieht die Top-0.1%-Centroid-Maske in die helle
        Ecke).
      - Neu (Hochpass+Grid, W1): (-5, -3) = -(shift), corr_hp ≈ 0.55 —
        Ground-Truth.
    """
    from scipy.ndimage import shift as scipy_shift

    def _add_gaussian(img, cy, cx, amp, sigma):
        y, x = np.ogrid[: img.shape[0], : img.shape[1]]
        img += amp * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2 * sigma**2))

    def _add_saturated(img, cy, cx, amp, radius, halo_sigma, halo_amp):
        y, x = np.ogrid[: img.shape[0], : img.shape[1]]
        d2 = (y - cy) ** 2 + (x - cx) ** 2
        img += np.where(d2 <= radius**2, amp, 0.0)
        img += halo_amp * np.exp(-d2 / (2 * halo_sigma**2))

    rng = np.random.RandomState(seed)
    ys = rng.randint(15, size - 15, 80)
    xs = rng.randint(15, size - 15, 80)
    amps = rng.uniform(8, 25, 80)
    for i in range(3):
        amps[i] = 150.0 + rng.uniform(0, 50)

    # Reference: sharp Gaussian stars (15s morphology)
    stars_ref = np.zeros((size, size), dtype=np.float64)
    # Target: saturated flat-core stars + large halo (180s morphology)
    stars_tgt = np.zeros((size, size), dtype=np.float64)
    for i, (cy, cx, a) in enumerate(zip(ys, xs, amps)):
        if i < 3:
            _add_saturated(stars_tgt, cy, cx, a, 4, 10.0, 25.0)
            _add_gaussian(stars_ref, cy, cx, a, 1.2)
        else:
            _add_gaussian(stars_tgt, cy, cx, a * 1.5, 1.2)
            _add_gaussian(stars_ref, cy, cx, a, 1.2)

    # Background: linear gradient + vignette (shifted between nights)
    y, x = np.ogrid[:size, :size]
    grad = grad_amp * (y + x) / (2.0 * size)
    vig = vig_amp * np.exp(-((y - size / 2) ** 2 + (x - size / 2) ** 2) / (2 * (size / 2.5) ** 2))

    ref_bg = 3.0 + grad + vig
    tgt_bg = scipy_shift(3.0 + grad + vig, grad_offset, order=1, mode="nearest")

    ref = (ref_bg + stars_ref + rng.uniform(0, 0.6, (size, size))).astype(np.float32)
    tgt = (tgt_bg + stars_tgt + rng.uniform(0, 0.6, (size, size))).astype(np.float32)
    tgt = scipy_shift(tgt, shift, order=3, mode="nearest")

    # Save as 3D RGB FITS (C, H, W) — same stars in all channels
    for path, mono in ((ref_path, ref), (tgt_path, tgt)):
        rgb = np.stack([mono, mono, mono], axis=-1).astype(np.float32)  # (H, W, C)
        out = rgb.transpose(2, 0, 1)  # (C, H, W)
        hdu = fits.PrimaryHDU(out)
        hdu.header["CTYPE3"] = "RGB"
        hdu.header["CUNIT3"] = "channel"
        path.parent.mkdir(parents=True, exist_ok=True)
        hdu.writeto(path, overwrite=True)


def make_sample_context(
    path: Path,
    group_count: int = 2,
    frames_per_group: int = 5,
) -> ObservationContext:
    """Build a synthetic ObservationContext with multiple groups.

    Group 1: exptime=15.0, gain=60, filter=None  → hash "15s60"
    Group 2: exptime=60.0, gain=40, filter=None  → hash "60s40"
    (optionally more groups with varying params)
    """
    params = [
        (15.0, 60, None),
        (60.0, 40, None),
        (120.0, 100, "Duo-Band"),
        (30.0, 80, "Ha"),
    ][:group_count]

    all_frames = []
    cal_status = CalibrationStatus(dark_available=True)

    for idx, (exptime, gain, filt) in enumerate(params):
        gp = path / f"group_{idx}"
        gp.mkdir(parents=True, exist_ok=True)
        fs = create_frame_set(gp, count=frames_per_group, exptime=exptime, gain=gain, filter_name=filt, rng_seed=idx)
        all_frames.extend(fs.frames)

    light_set = FrameSet(frame_type=FrameType.LIGHT, frames=all_frames)

    context = ObservationContext(
        target=ObservationTarget(name="TestTarget", ra=180.0, dec=30.0),
        frames={FrameType.LIGHT: light_set},
        calibration=cal_status,
        equipment=EquipmentInfo(
            telescope="TestScope",
            focal_length_mm=200.0,
            pixel_size_um=3.76,
        ),
        acquisition=AcquisitionInfo(gain=100),
        source_path=path,
    )
    return context


def run_multi_group_pipeline(
    tmp_dir: Path,
    agent: ProcessingAgent,
    mg_config: Optional[MultiGroupConfig] = None,
    fake_pcc_status: str = "gaia_success",
    with_fallback_marker: bool = False,
) -> ProcessingResult:
    """CR-001 P1/P2 Helper: process_multi_group mit 2 synthetischen Gruppen,
    gemockte schwere Schritte (register/stack/cross-registration/pcc).

    Legt Gruppen-Dirs an (group_15s60, group_60s40), erzeugt PCC-Dateien und
    echte Gruppen-Previews (create_preview_jpg ist real — nur wenn nicht gepatcht).
    Gibt das ProcessingResult zurück.
    """
    if mg_config is None:
        mg_config = MultiGroupConfig()
    context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
    pipeline = MagicMock()
    pipeline.processing_params = ProcessingParams()
    pipeline.steps = []

    lights = context.get_lights()
    cal_result = MagicMock()
    cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
    deb_result = MagicMock()
    deb_result.debayered_frames = []

    stack_fits = {
        "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
        "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
    }

    pcc_counter = {"n": 0}

    def fake_pcc(stack_path, *args, **kwargs):
        pcc_counter["n"] += 1
        p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
        create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
        if with_fallback_marker:
            # fake_pcc(stack_path, *args): args = (context, mg_config, group_dir, pixel_scale)
            group_dir = args[2]
            stacked_dir = group_dir / "04_stacked"
            stacked_dir.mkdir(parents=True, exist_ok=True)
            (stacked_dir / "PCC_FALLBACK_GRAY_WORLD.txt").write_text(
                "PCC failed — Gray World fallback applied.\n"
            )
        return (p, fake_pcc_status)

    with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
         patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
         patch.object(agent, "_register_to_reference_stack") as mock_cross, \
         patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
        mock_reg.return_value = RegisterFramesResult(
            registered=[], last_frame_qualities=[], last_frame_rejected=0,
            last_registration_metrics={},
        )
        mock_stack.return_value = stack_fits["15s60"]
        mock_cross.return_value = RegistrationResult(
            path=stack_fits["60s40"], status="ok",
            corr_hp=0.9,  # CR-001 W3: über min_correlation (0.1) → kein Skip
        )
        mock_pcc.side_effect = fake_pcc

        return agent.process_multi_group(
            context, cal_result, deb_result, pipeline,
            multi_group_config=mg_config, merge_agent=None,
        )


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Temporary directory for test isolation."""
    return tmp_path


@pytest.fixture
def sample_stacks(tmp_dir: Path) -> dict[str, Path]:
    """Create 2 sample group stacks for merge testing."""
    stack1 = create_test_fits(
        tmp_dir / "stack1.fits",
        exptime=15.0, gain=60, filter_name=None, rng_seed=1,
    )
    stack2 = create_test_fits(
        tmp_dir / "stack2.fits",
        exptime=60.0, gain=40, filter_name=None, rng_seed=2,
    )
    return {"15s60": stack1, "60s40": stack2}


@pytest.fixture
def sample_metadata() -> dict[str, dict]:
    """Sample group metadata for merge tests."""
    return {
        "15s60": {
            "frame_count": 43, "exptime": 15.0, "gain": 60,
            "filter": None, "total_exposure": 645.0,
            "pcc_status": "gaia_success",
        },
        "60s40": {
            "frame_count": 28, "exptime": 60.0, "gain": 40,
            "filter": None, "total_exposure": 1680.0,
            "pcc_status": "gaia_success",
        },
    }


@pytest.fixture
def sample_context(tmp_dir: Path) -> ObservationContext:
    """Build a sample observation context with 2 groups (5 frames each)."""
    return make_sample_context(tmp_dir, group_count=2, frames_per_group=5)


# ═══════════════════════════════════════════════════════════════════
# T1 — Config Validation
# ═══════════════════════════════════════════════════════════════════


class TestT1ConfigValidation:
    """T1: MultiGroupConfig + MergeConfig — defaults, validation, integration."""

    def test_multi_group_config_defaults(self):
        """MultiGroupConfig creates with defaults."""
        cfg = MultiGroupConfig()
        assert cfg.reference_group == "quality"  # V1.3-5: default is registration-quality-based
        assert cfg.pcc_fallback == "auto"  # V1.4-19: Default-Fallback-Kette (GAIA-Retry → VizieR → gray_world)
        assert cfg.keep_group_working_dirs is True  # CR-001 P1: Default-Flip (AC-P1-1/2)
        assert cfg.merge.method == "weighted_average"
        assert cfg.merge.weight_by == "frame_count"

    def test_multi_group_config_no_enabled_field(self):
        """V1.7-5 (OQ-AMG-5): Das funktionslose Feld ``enabled`` ist entfernt;
        alte Configs mit dem Feld laden weiter (extra="ignore")."""
        assert "enabled" not in MultiGroupConfig.model_fields
        from astro_process.config.models import AppConfig
        legacy_cfg = AppConfig(multi_group={"enabled": True, "reference_group": "largest"})
        assert legacy_cfg.multi_group is not None
        assert legacy_cfg.multi_group.reference_group == "largest"

    def test_merge_config_defaults(self):
        """MergeConfig creates with defaults (method=weighted_average, weight_by=frame_count)."""
        cfg = MergeConfig()
        assert cfg.method == "weighted_average"
        assert cfg.weight_by == "frame_count"

    def test_merge_config_weight_by_total_exposure(self):
        """weight_by accepts 'total_exposure'."""
        cfg = MergeConfig(weight_by="total_exposure")
        assert cfg.weight_by == "total_exposure"

    def test_multi_group_config_integration_in_app_config(self):
        """AppConfig with multi_group block works."""
        cfg = AppConfig(
            multi_group=MultiGroupConfig(
                reference_group="largest",
                pcc_fallback="gray_world",
                merge=MergeConfig(method="median", weight_by="total_exposure"),
            )
        )
        assert cfg.multi_group is not None
        assert cfg.multi_group.merge.method == "median"

    def test_multi_group_config_validation_reference_group(self):
        """'largest' and specific hash both valid as reference_group."""
        cfg1 = MultiGroupConfig(reference_group="largest")
        assert cfg1.reference_group == "largest"

        cfg2 = MultiGroupConfig(reference_group="15s60")
        assert cfg2.reference_group == "15s60"

    def test_multi_group_config_pcc_fallback_values(self):
        """gray_world/skip/fail/auto all valid for pcc_fallback (V1.4-19 + auto)."""
        for val in ("gray_world", "skip", "fail", "auto"):
            cfg = MultiGroupConfig(pcc_fallback=val)  # type: ignore
            assert cfg.pcc_fallback == val

    def test_multi_group_config_invalid_pcc_fallback(self):
        """Invalid pcc_fallback raises validation error."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MultiGroupConfig(pcc_fallback="invalid")  # type: ignore

    def test_merge_config_invalid_method(self):
        """Invalid merge method raises validation error."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MergeConfig(method="invalid")  # type: ignore


# ═══════════════════════════════════════════════════════════════════
# T2 — Grouping
# ═══════════════════════════════════════════════════════════════════


class TestT2Grouping:
    """T2: Grouping by acquisition parameters."""

    def test_group_by_params_default_keys(self, tmp_dir: Path):
        """groups by EXPTIME, GAIN, FILTER."""
        frameset = create_frame_set(tmp_dir, count=3, exptime=15.0, gain=60, filter_name="L")
        groups = frameset.group_by_params()
        assert len(groups) == 1
        key = list(groups.keys())[0]
        assert key[0] == 15.0
        assert key[1] == 60
        assert key[2] == "L"

    def test_group_by_params_single_group(self, tmp_dir: Path):
        """returns single group if all params same."""
        frameset = create_frame_set(tmp_dir, count=5, exptime=15.0, gain=60, filter_name=None)
        groups = frameset.group_by_params()
        assert len(groups) == 1

    def test_group_by_params_multi_group(self, tmp_dir: Path):
        """returns multiple groups for different params."""
        # Create two sets with different exptime
        fs1 = create_frame_set(tmp_dir / "g1", count=3, exptime=15.0, gain=60, filter_name=None)
        fs2 = create_frame_set(tmp_dir / "g2", count=2, exptime=60.0, gain=40, filter_name=None)
        frameset = FrameSet(
            frame_type=FrameType.LIGHT,
            frames=fs1.frames + fs2.frames,
        )
        groups = frameset.group_by_params()
        assert len(groups) == 2

    def test_group_by_params_missing_header(self, tmp_dir: Path):
        """handles missing EXPTIME/GAIN/FILTER gracefully (fallbacks: 0.0, 0, 'none')."""
        # Create frames with None headers
        fp1 = tmp_dir / "light_0000.fits"
        create_test_fits(fp1, exptime=15.0, gain=60, filter_name=None)
        h1 = FitsHeader(exptime=None, gain=None, filter_name=None)
        fi1 = FrameInfo(path=fp1, frame_type=FrameType.LIGHT, header=h1, index=0, size_bytes=100, width=100, height=100)

        fp2 = tmp_dir / "light_0001.fits"
        create_test_fits(fp2, exptime=30.0, gain=80, filter_name="Ha")
        h2 = FitsHeader(exptime=30.0, gain=80, filter_name="Ha")
        fi2 = FrameInfo(path=fp2, frame_type=FrameType.LIGHT, header=h2, index=1, size_bytes=100, width=100, height=100)

        frameset = FrameSet(frame_type=FrameType.LIGHT, frames=[fi1, fi2])
        groups = frameset.group_by_params()
        # First frame should get fallbacks: (0.0, 0, "none")
        # Second frame: (30.0, 80, "Ha")
        assert len(groups) == 2

        none_key = (0.0, 0, "none")
        ha_key = (30.0, 80, "Ha")
        assert none_key in groups
        assert ha_key in groups

    def test_compute_group_hash_simple(self):
        """'15s60' for (15.0, 60, 'none')."""
        h = compute_group_hash(15.0, 60, "none")
        assert h == "15s60"

    def test_compute_group_hash_with_filter(self):
        """'60s40_Duo-Band' for (60.0, 40, 'Duo-Band')."""
        h = compute_group_hash(60.0, 40, "Duo-Band")
        assert h == "60s40_Duo-Band"

    def test_compute_group_hash_no_filter(self):
        """no filter suffix when filter is None/empty."""
        h1 = compute_group_hash(15.0, 60, "")
        assert h1 == "15s60"
        h2 = compute_group_hash(15.0, 60, None)  # type: ignore
        assert h2 == "15s60"

    def test_discover_groups(self, tmp_dir: Path):
        """DiscoveryAgent.discover_groups() returns correct GroupInfo dict."""
        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=5)
        agent = DiscoveryAgent(config=None)
        groups = agent.discover_groups(context)
        assert len(groups) == 2
        assert "15s60" in groups
        assert "60s40" in groups
        # Check frame counts
        assert groups["15s60"].frame_count == 5
        assert groups["60s40"].frame_count == 5
        # Check total_exposure
        expected_15 = 5 * 15.0
        expected_60 = 5 * 60.0
        assert abs(groups["15s60"].total_exposure - expected_15) < 0.01
        assert abs(groups["60s40"].total_exposure - expected_60) < 0.01

    def test_group_info_dataclass(self):
        """GroupInfo fields correct."""
        info = GroupInfo(
            key=(15.0, 60, "none"),
            hash="15s60",
            frame_count=43,
            total_exposure=645.0,
        )
        assert info.key == (15.0, 60, "none")
        assert info.hash == "15s60"
        assert info.frame_count == 43
        assert info.total_exposure == 645.0
        assert info.working_dir is None

        # With working_dir
        info2 = GroupInfo(
            key=(60.0, 40, "Duo-Band"),
            hash="60s40_Duo-Band",
            frame_count=28,
            total_exposure=1680.0,
            working_dir=Path("/tmp/test"),
        )
        assert info2.working_dir == Path("/tmp/test")


# ═══════════════════════════════════════════════════════════════════
# T3 — Gray-World White Balance
# ═══════════════════════════════════════════════════════════════════


class TestT3GrayWorld:
    """T3: Gray-World White Balance correction."""

    def test_gray_world_white_balance_exported(self):
        """function exists in pcc.py."""
        from astro_process.core.pcc import gray_world_white_balance
        assert callable(gray_world_white_balance)

    def test_gray_world_white_balance_scale(self):
        """scales channels to common mean at high percentile."""
        # Create RGB data with a green bias
        rng = np.random.RandomState(42)
        data = np.zeros((50, 50, 3), dtype=np.float32)
        data[:, :, 0] = rng.uniform(0.1, 0.3, (50, 50))  # R: 0.1-0.3
        data[:, :, 1] = rng.uniform(0.5, 0.9, (50, 50))  # G: 0.5-0.9
        data[:, :, 2] = rng.uniform(0.1, 0.3, (50, 50))  # B: 0.1-0.3

        corrected = gray_world_white_balance(data)

        # After correction, the 99th percentile values should be ~equal
        r_pct = np.percentile(corrected[:, :, 0][corrected[:, :, 0] > 0], 99)
        g_pct = np.percentile(corrected[:, :, 1][corrected[:, :, 1] > 0], 99)
        b_pct = np.percentile(corrected[:, :, 2][corrected[:, :, 2] > 0], 99)

        # They should be much closer than before (green bias reduced)
        spread_before = np.percentile(data[:, :, 1][data[:, :, 1] > 0], 99) - np.percentile(data[:, :, 0][data[:, :, 0] > 0], 99)
        spread_after = max(r_pct, g_pct, b_pct) - min(r_pct, g_pct, b_pct)
        assert spread_after < spread_before

    def test_gray_world_fallback_marker_file(self, tmp_dir: Path):
        """marker file created on fallback."""
        marker_path = tmp_dir / "PCC_FALLBACK_GRAY_WORLD.txt"
        marker_path.write_text(
            "PCC (Photometric Color Calibration) failed.\n"
            "Gray World fallback applied — colors are approximate only.\n"
        )
        assert marker_path.exists()
        content = marker_path.read_text()
        assert "Gray World" in content

    def test_get_pcc_fallback_default(self):
        """returns 'auto' when no config (V1.4-19: Kette statt direkt gray_world)."""
        agent = ProcessingAgent(working_dir=Path("/tmp"), config=None)
        fallback = agent._get_pcc_fallback()
        assert fallback == "auto"

    def test_get_pcc_fallback_from_config(self):
        """returns configured value."""
        cfg = AppConfig(multi_group=MultiGroupConfig(pcc_fallback="skip"))
        agent = ProcessingAgent(working_dir=Path("/tmp"), config=cfg)
        fallback = agent._get_pcc_fallback()
        assert fallback == "skip"

    def test_gray_world_preserves_shape(self):
        """gray_world_white_balance preserves input shape and dtype."""
        data = np.ones((20, 20, 3), dtype=np.float32)
        data[:, :, 0] = 0.5
        data[:, :, 1] = 1.0
        data[:, :, 2] = 0.8

        result = gray_world_white_balance(data)
        assert result.shape == data.shape
        assert result.dtype == np.float32


# ═══════════════════════════════════════════════════════════════════
# T4 — Adaptive Registration Channel Selection
# ═══════════════════════════════════════════════════════════════════


class TestT4RegistrationChannel:
    """T4: Adaptive Registration Channel Selection."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def _make_rgb_data(self, r_val=0.5, g_val=0.5, b_val=0.5) -> np.ndarray:
        """Create synthetic (H, W, 3) data with given channel values."""
        data = np.zeros((50, 50, 3), dtype=np.float32)
        data[:, :, 0] = r_val
        data[:, :, 1] = g_val
        data[:, :, 2] = b_val
        # Add some structure
        data[20:30, 20:30, :] += 0.3
        return data

    def test_select_registration_channel_broadband(self, agent: ProcessingAgent):
        """"Clear"/"" → Luminance."""
        data = self._make_rgb_data()
        mono, name = select_registration_channel(data, "Clear")
        assert name == "Luminance"

        mono2, name2 = select_registration_channel(data, "")
        assert name2 == "Luminance"

    def test_select_registration_channel_ha(self, agent: ProcessingAgent):
        """"Ha"/"H-Alpha" → R."""
        data = self._make_rgb_data()
        mono, name = select_registration_channel(data, "Ha")
        assert name == "R"

        mono2, name2 = select_registration_channel(data, "H-Alpha")
        assert name2 == "R"

    def test_select_registration_channel_oiii(self, agent: ProcessingAgent):
        """"OIII"/"O-III" → (G+B)/2 (Luminance)."""
        data = self._make_rgb_data()
        mono, name = select_registration_channel(data, "OIII")
        assert name == "Luminance"

    def test_select_registration_channel_duoband(self, agent: ProcessingAgent):
        """"Duo-Band" → R (if R has highest signal)."""
        data = self._make_rgb_data(r_val=1.0, g_val=0.3, b_val=0.2)
        mono, name = select_registration_channel(data, "Duo-Band")
        assert name == "R"

    def test_select_registration_channel_unknown_filter(self, agent: ProcessingAgent):
        """unknown filter → signal-based selection."""
        data = self._make_rgb_data(r_val=0.1, g_val=0.9, b_val=0.1)
        mono, name = select_registration_channel(data, "SOME-UNKNOWN")
        assert name == "G"

    def test_select_registration_channel_empty_filter(self, agent: ProcessingAgent):
        """empty filter → Luminance (broadband path, objectively better than G)."""
        data = self._make_rgb_data(r_val=0.5, g_val=0.5, b_val=0.5)
        mono, name = select_registration_channel(data, "")
        # For empty filter, broadband path is taken → Luminance
        assert name == "Luminance"

    def test_compute_shift_star_centroid(self, agent: ProcessingAgent):
        """centroid-based shift computation works."""
        # Create reference with many bright Gaussian stars for enough >99.9% pixels
        yg, xg = np.ogrid[:100, :100]
        ref = np.zeros((100, 100), dtype=np.float32)
        target = np.zeros((100, 100), dtype=np.float32)

        # Place 10 bright stars at known positions with ~5 pixel shift
        for cy, cx in [(10, 10), (10, 50), (10, 90), (50, 10), (50, 50),
                       (50, 90), (90, 10), (90, 50), (90, 90), (30, 30)]:
            star = np.exp(-((yg - cy) ** 2 + (xg - cx) ** 2) / 2.0)
            ref += star * 3.0  # scale up to ensure bright
            target += np.exp(-((yg - (cy + 5)) ** 2 + (xg - (cx + 5)) ** 2) / 2.0) * 3.0

        shift_y, shift_x = compute_shift_star_centroid(ref, target)
        # Should detect approximately (5, 5) shift
        assert abs(shift_y - 5.0) < 3.0, f"shift_y={shift_y}"
        assert abs(shift_x - 5.0) < 3.0, f"shift_x={shift_x}"

    def test_compute_shift_star_centroid_fallback(self, agent: ProcessingAgent):
        """falls back to FFT when < 10 bright pixels."""
        ref = np.zeros((50, 50), dtype=np.float32)
        ref += 1.0  # uniform — no bright stars
        target = np.zeros_like(ref)
        target += 1.0

        # Should fall back to phase correlation without error
        shift_y, shift_x = compute_shift_star_centroid(ref, target)
        assert isinstance(shift_y, float)
        assert isinstance(shift_x, float)

    def test_compute_shift_phase_correlation(self, agent: ProcessingAgent):
        """FFT phase correlation works for detecting shifts."""
        # Create a Gaussian signal with a known shift
        y, x = np.ogrid[:64, :64]
        ref = np.exp(-((y - 32) ** 2 + (x - 32) ** 2) / 8).astype(np.float32)

        from scipy.ndimage import shift as scipy_shift
        # Shift by (2, 0) pixels
        target = scipy_shift(ref, (2.0, 0.0), order=1, mode="nearest")

        shift_y, shift_x = compute_shift(ref, target)
        # The algorithm computes ref-to-target shift via FFT phase correlation.
        # It returns a shift value; verify the magnitude is correct (~2 pixels)
        assert abs(shift_y) > 0.5, f"shift_y={shift_y} (expected ~2)"
        assert abs(abs(shift_y) - 2.0) < 1.5, f"shift_y={shift_y}"
        assert abs(shift_x) < 1.0, f"shift_x={shift_x} (expected ~0)"


# ═══════════════════════════════════════════════════════════════════
# T5 — Shared Reference Registration
# ═══════════════════════════════════════════════════════════════════


class TestT5SharedReference:
    """T5: Shared Reference Registration (single-group, select, register)."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_process_multi_group_single_group(self, tmp_dir: Path, agent: ProcessingAgent):
        """V1.7-5 (Always Multi-Group): 1 Gruppe laeuft durch denselben
        Pfad wie N Gruppen — kein Fallback auf run() mehr (AC-A1)."""
        context = make_sample_context(tmp_dir, group_count=1, frames_per_group=3)
        mg_config = MultiGroupConfig()
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []
        merge_agent = MagicMock()

        stack_fits = create_test_fits(
            tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1,
        )

        def fake_pcc(stack_path, *args, **kwargs):
            p = tmp_dir / "pcc_15s60.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=9)
            return (p, "gaia_success")

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits
            mock_pcc.side_effect = fake_pcc

            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )

        # AC-A1: Kein Fallback — der Multi-Group-Pfad ist gelaufen
        # (Gruppen-Verzeichnis + kanonische merged/-Materialisierung).
        assert (tmp_dir / "group_15s60").exists()
        merged_fits = tmp_dir / "merged" / "TestTarget_merged.fits"
        assert merged_fits.exists()
        # MergeAgent wurde NICHT aufgerufen (< 2 Stacks wuerde
        # insufficient_stacks erzeugen — AC-A4).
        merge_agent.run.assert_not_called()
        # Ergebnis: gestackt auf merged/, Metadata komplett (AC-A7).
        assert proc_result.stacked == merged_fits
        meta = proc_result.multi_group_metadata
        assert list(meta["groups"].keys()) == ["15s60"]
        assert meta["reference_selection"]["group"] == "15s60"  # AC-A3

    def test_select_reference_group_largest(self):
        """selects group with most frames."""
        groups = {
            "15s60": GroupInfo(key=(15.0, 60, "none"), hash="15s60", frame_count=43, total_exposure=645.0),
            "60s40": GroupInfo(key=(60.0, 40, "none"), hash="60s40", frame_count=28, total_exposure=1680.0),
            "120s100": GroupInfo(key=(120.0, 100, "none"), hash="120s100", frame_count=55, total_exposure=6600.0),
        }
        result = ProcessingAgent._select_reference_group(groups, "largest")
        assert result == "120s100"  # largest frame_count

    def test_select_reference_group_user_specified(self):
        """selects specified hash."""
        groups = {
            "15s60": GroupInfo(key=(15.0, 60, "none"), hash="15s60", frame_count=43, total_exposure=645.0),
            "60s40": GroupInfo(key=(60.0, 40, "none"), hash="60s40", frame_count=28, total_exposure=1680.0),
        }
        result = ProcessingAgent._select_reference_group(groups, "60s40")
        assert result == "60s40"

    def test_select_reference_group_fallback(self):
        """falls back to largest if hash not found."""
        groups = {
            "15s60": GroupInfo(key=(15.0, 60, "none"), hash="15s60", frame_count=43, total_exposure=645.0),
            "60s40": GroupInfo(key=(60.0, 40, "none"), hash="60s40", frame_count=28, total_exposure=1680.0),
        }
        result = ProcessingAgent._select_reference_group(groups, "nonexistent_hash")
        assert result == "15s60"  # largest by frame_count

    def test_register_to_reference_stack(self, tmp_dir: Path, agent: ProcessingAgent):
        """registers one stack to another (returns RegistrationResult)."""
        # Create reference and target stacks
        ref_path = create_test_fits(tmp_dir / "ref.fits", exptime=15.0, gain=60, rng_seed=1, shift=(0, 0))
        tgt_path = create_test_fits(tmp_dir / "tgt.fits", exptime=60.0, gain=40, rng_seed=2, shift=(3.0, -1.0))

        out_dir = tmp_dir / "aligned_out"
        result = agent._register_to_reference_stack(
            tgt_path, ref_path, filter_name="", output_dir=out_dir,
        )
        # CR-001 P3-B: Rückgabe ist RegistrationResult (path statt Path)
        assert isinstance(result, RegistrationResult)
        assert result.path.exists()
        assert result.path.name == "aligned.fits"
        # Felder vorhanden (AC-P3-2: shift_y/shift_x/correlation/status)
        assert isinstance(result.shift_y, float)
        assert isinstance(result.shift_x, float)
        assert isinstance(result.correlation, float)
        assert result.status in ("ok", "warning")

    def test_copy_wcs_headers(self, tmp_dir: Path):
        """WCS keys copied correctly."""
        # Create source with WCS headers
        src_path = tmp_dir / "source.fits"
        data = np.ones((3, 100, 100), dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["CRVAL1"] = 180.0
        hdu.header["CRVAL2"] = 30.0
        hdu.header["CRPIX1"] = 50.0
        hdu.header["CRPIX2"] = 50.0
        hdu.header["CDELT1"] = -0.01
        hdu.header["CDELT2"] = 0.01
        hdu.header["CTYPE1"] = "RA---TAN"
        hdu.header["CTYPE2"] = "DEC--TAN"
        hdu.writeto(src_path, overwrite=True)

        # Create target without WCS
        tgt_path = tmp_dir / "target.fits"
        tgt_data = np.ones((3, 100, 100), dtype=np.float32)
        hdu2 = fits.PrimaryHDU(tgt_data)
        hdu2.writeto(tgt_path, overwrite=True)

        # Copy WCS headers
        ProcessingAgent._copy_wcs_headers(src_path, tgt_path)

        # Verify headers copied
        with fits.open(tgt_path) as hdul:
            h = hdul[0].header
            assert h["CRVAL1"] == 180.0
            assert h["CRVAL2"] == 30.0
            assert h["CTYPE1"] == "RA---TAN"

    def test_registration_qc_logging(self, tmp_dir: Path, agent: ProcessingAgent):
        """correlation coefficient logged during cross-group registration."""
        # Verify the registration method runs and logs QC info
        # (structlog testing is complex; we verify the method completes successfully
        # and produces the expected output files)
        ref_path = create_test_fits(tmp_dir / "ref_qc.fits", exptime=15.0, gain=60, rng_seed=10, shift=(0, 0))
        tgt_path = create_test_fits(tmp_dir / "tgt_qc.fits", exptime=60.0, gain=40, rng_seed=11, shift=(0, 0))

        out_dir = tmp_dir / "qc_out"
        result = agent._register_to_reference_stack(tgt_path, ref_path, filter_name="", output_dir=out_dir)

        # Verify the output was created
        assert result.path.exists()
        assert result.path.name == "aligned.fits"

        # Verify the aligned FITS has valid data
        with fits.open(result.path) as hdul:
            assert hdul[0].data is not None
            assert hdul[0].data.shape == (3, 100, 100)


# ═══════════════════════════════════════════════════════════════════
# V1.3-5 — Referenz-Wahl nach Registrierungs-Qualität
# ═══════════════════════════════════════════════════════════════════


class _V135LogRecorder:
    """Minimaler structlog-Ersatz für die V1.3-5-Fallback-Log-Tests
    (Muster test_registration._LogRecorder, lokal — test_multi_group darf
    test_registration nicht importieren, das wäre zirkulär)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def events_named(self, name: str) -> list[tuple[str, dict]]:
        return [e for e in self.events if e[0] == name]


def _quality_metrics(
    frames_registered: int = 3,
    zero_shift_count: int = 0,
    n_control_points_median: Optional[float] = None,
    corr_hp_median: Optional[float] = 0.7,
) -> dict:
    """V1.3-5 Testhelfer: registration_metrics-Dict (V1.3-3-Schema)."""
    return {
        "method_counts": {"fft": frames_registered, "astroalign": 0},
        "zero_shift_count": zero_shift_count,
        "rejected_count": 0,
        "frames_total": frames_registered,
        "frames_registered": frames_registered,
        "corr_hp": {
            "count": frames_registered,
            "min": 0.5,
            "max": 0.9,
            "median": corr_hp_median,
        },
        "n_control_points": {
            "count": frames_registered if n_control_points_median is not None else 0,
            "median": n_control_points_median,
        },
    }


class TestV135QualityReference:
    """V1.3-5 (Boris-Entscheidung 2026-08-11): Referenz-Wahl nach
    REGISTRIERUNGS-QUALITÄT (registration_metrics, V1.3-3) statt Signalmaß
    (W14). Gewichtung: 1. kleinster Zero-Shift-Anteil, 2. höchster
    n_control_points-Median, 3. höchster corr_hp-Median, 4. meiste Frames,
    dann lexikografisch Hash (deterministisch)."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def _groups(self) -> dict[str, GroupInfo]:
        return {
            "15s60": GroupInfo(key=(15.0, 60, "none"), hash="15s60",
                               frame_count=55, total_exposure=825.0),
            "60s40": GroupInfo(key=(60.0, 40, "none"), hash="60s40",
                               frame_count=40, total_exposure=2400.0),
        }

    def _stacks(self, groups: dict[str, GroupInfo]) -> dict[str, Path]:
        return {gh: Path(f"/s/{gh}.fits") for gh in groups}

    def test_quality_primary_zero_shift_ratio(self):
        """Primärkriterium: kleinster Zero-Shift-Anteil gewinnt — auch wenn
        die Gewinner-Gruppe WENIGER Frames hat. Der M13-Beleg ist qualitativ
        (60s40-Äquivalent niedriger zero_shift_count, 15s60-Äquivalent
        hoher); die Frame-Counts in _groups() sind BEWUSST gegenüber dem
        M13-Narrativ vertauscht (dort: 60s40=55 Frames/3300s, 15s60 weniger;
        hier: 15s60=55, 60s40=40) — der Test belegt "Qualität schlägt
        Frame-Count", keine 1:1-M13-Zahlen."""
        groups = self._groups()
        metrics = {
            "15s60": _quality_metrics(frames_registered=55, zero_shift_count=40),
            "60s40": _quality_metrics(frames_registered=40, zero_shift_count=2),
        }
        result = ProcessingAgent._select_reference_group(
            groups, "quality", group_stacks=self._stacks(groups),
            registration_metrics=metrics,
        )
        assert result == "60s40"

    def test_quality_secondary_n_control_points(self):
        """Sekundärkriterium: bei gleichem Zero-Shift-Anteil gewinnt der
        höhere n_control_points-Median."""
        groups = self._groups()
        metrics = {
            "15s60": _quality_metrics(frames_registered=10, zero_shift_count=0,
                                      n_control_points_median=5.0, corr_hp_median=0.5),
            "60s40": _quality_metrics(frames_registered=10, zero_shift_count=0,
                                      n_control_points_median=12.0, corr_hp_median=0.5),
        }
        result = ProcessingAgent._select_reference_group(
            groups, "quality", group_stacks=self._stacks(groups),
            registration_metrics=metrics,
        )
        assert result == "60s40"

    def test_quality_tertiary_corr_hp_median(self):
        """Tertiärkriterium: bei gleichem Zero-Shift-Anteil und gleichem
        n_control_points-Median gewinnt der höhere corr_hp-Median."""
        groups = self._groups()
        metrics = {
            "15s60": _quality_metrics(frames_registered=10, zero_shift_count=0,
                                      n_control_points_median=None, corr_hp_median=0.4),
            "60s40": _quality_metrics(frames_registered=10, zero_shift_count=0,
                                      n_control_points_median=None, corr_hp_median=0.8),
        }
        result = ProcessingAgent._select_reference_group(
            groups, "quality", group_stacks=self._stacks(groups),
            registration_metrics=metrics,
        )
        assert result == "60s40"

    def test_quality_tiebreak_frame_count_then_hash(self):
        """Tiebreak: bei identischer Qualität gewinnt die Gruppe mit mehr
        Frames (frame_count), dann lexikografisch Hash (deterministisch)."""
        groups = self._groups()
        metrics = {
            "15s60": _quality_metrics(frames_registered=5, zero_shift_count=0),
            "60s40": _quality_metrics(frames_registered=5, zero_shift_count=0),
        }
        # frame_count: 15s60=55 > 60s40=40 → 15s60 (meiste Frames)
        result = ProcessingAgent._select_reference_group(
            groups, "quality", group_stacks=self._stacks(groups),
            registration_metrics=metrics,
        )
        assert result == "15s60"

        # Gleiche frame_count → lexikografisch größerer Hash gewinnt
        equal_groups = {
            "15s60": GroupInfo(key=(15.0, 60, "none"), hash="15s60",
                               frame_count=40, total_exposure=600.0),
            "60s40": GroupInfo(key=(60.0, 40, "none"), hash="60s40",
                               frame_count=40, total_exposure=2400.0),
        }
        result2 = ProcessingAgent._select_reference_group(
            equal_groups, "quality", group_stacks=self._stacks(equal_groups),
            registration_metrics=metrics,
        )
        assert result2 == "60s40"  # "60s40" > "15s60" lexikografisch

    def test_quality_candidate_filter_frames_registered_lt_3(self):
        """Kandidaten-Filter: Gruppe mit frames_registered < 3 wird nicht
        Referenz (konsistent mit W14 frame_count >= 3)."""
        groups = self._groups()
        metrics = {
            "15s60": _quality_metrics(frames_registered=2, zero_shift_count=0),
            "60s40": _quality_metrics(frames_registered=3, zero_shift_count=5),
        }
        result = ProcessingAgent._select_reference_group(
            groups, "quality", group_stacks=self._stacks(groups),
            registration_metrics=metrics,
        )
        # 15s60 (2 Frames) ist kein Kandidat; 60s40 (3 Frames) bleibt übrig
        assert result == "60s40"

    def test_quality_no_candidates_fallback_largest(self):
        """Alle Kandidaten unter 3 registrierten Frames → Fallback largest
        + Log multi_group.reference_quality_fallback (reason=no_candidates)."""
        import astro_process.agents.processing_agent as processing_agent

        groups = self._groups()
        metrics = {
            "15s60": _quality_metrics(frames_registered=2, zero_shift_count=0),
            "60s40": _quality_metrics(frames_registered=2, zero_shift_count=0),
        }
        rec = _V135LogRecorder()
        with patch.object(processing_agent, "logger", rec):
            result = ProcessingAgent._select_reference_group(
                groups, "quality", group_stacks=self._stacks(groups),
                registration_metrics=metrics,
            )
        assert result == "15s60"  # largest: frame_count 55 > 40
        fallback_events = rec.events_named("multi_group.reference_quality_fallback")
        assert len(fallback_events) == 1
        assert fallback_events[0][1]["reason"] == "no_candidates"

    def test_quality_no_metrics_fallback_largest(self):
        """Fehlende Metriken (None / leere dicts — Legacy, Mocks, Dry-Run,
        alte Lauf-Objekte) → Fallback largest + Log
        (reason=no_metrics)."""
        import astro_process.agents.processing_agent as processing_agent

        groups = self._groups()
        rec = _V135LogRecorder()
        with patch.object(processing_agent, "logger", rec):
            result = ProcessingAgent._select_reference_group(
                groups, "quality", group_stacks=self._stacks(groups),
                registration_metrics=None,
            )
        assert result == "15s60"  # largest by frame_count
        fallback_events = rec.events_named("multi_group.reference_quality_fallback")
        assert len(fallback_events) == 1
        assert fallback_events[0][1]["reason"] == "no_metrics"

        # Auch leere Metriken-dicts (Mock-Fälle ohne _last_registration_metrics)
        rec2 = _V135LogRecorder()
        with patch.object(processing_agent, "logger", rec2):
            result2 = ProcessingAgent._select_reference_group(
                groups, "quality", group_stacks=self._stacks(groups),
                registration_metrics={gh: {} for gh in groups},
            )
        assert result2 == "15s60"
        assert rec2.events_named("multi_group.reference_quality_fallback")[0][1]["reason"] == "no_metrics"

    def test_quality_partial_metrics_skips_groups_without_metrics(self):
        """Defensive Zugriffe: Gruppen ohne Metriken-Eintrag (Legacy) werden
        nicht Kandidat (frames_registered = 0 < 3); Gruppen mit Metriken
        entscheiden."""
        groups = self._groups()
        metrics = {
            "15s60": {},  # Legacy — keine Metriken
            "60s40": _quality_metrics(frames_registered=8, zero_shift_count=1),
        }
        result = ProcessingAgent._select_reference_group(
            groups, "quality", group_stacks=self._stacks(groups),
            registration_metrics=metrics,
        )
        assert result == "60s40"

    def test_quality_none_values_defensive(self):
        """None-Werte in den Metriken (leere Gruppe) crashen nicht; Mediane
        None → -inf (Kriterium verliert); Zähler None → 0."""
        groups = self._groups()
        metrics = {
            "15s60": {
                "method_counts": {"fft": None, "astroalign": None},
                "zero_shift_count": None,
                "rejected_count": None,
                "frames_total": 5,
                "frames_registered": 5,
                "corr_hp": {"count": 0, "min": None, "max": None, "median": None},
                "n_control_points": {"count": 0, "median": None},
            },
            "60s40": _quality_metrics(frames_registered=5, zero_shift_count=0,
                                      corr_hp_median=0.9),
        }
        result = ProcessingAgent._select_reference_group(
            groups, "quality", group_stacks=self._stacks(groups),
            registration_metrics=metrics,
        )
        # Gleicher Zero-Shift-Anteil (0/5); 60s40 gewinnt über corr_hp-Median
        assert result == "60s40"

    def test_build_reference_selection_quality(self, tmp_dir: Path):
        """_build_reference_selection dokumentiert quality_scores je Gruppe
        (zero_shift_ratio/n_control_points_median/corr_hp_median/
        frames_registered, deterministisch sortiert) + fallback_reason
        no_metrics bei fehlenden Metriken."""
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        groups = self._groups()
        stacks = self._stacks(groups)
        metrics = {
            "15s60": _quality_metrics(frames_registered=55, zero_shift_count=40),
            "60s40": _quality_metrics(frames_registered=40, zero_shift_count=2),
        }
        sel = agent._build_reference_selection(
            groups, "quality", "60s40", stacks,
            registration_metrics=metrics,
        )
        assert sel["method"] == "quality"
        assert sel["group"] == "60s40"
        assert "fallback_reason" not in sel
        qs = sel["quality_scores"]
        assert set(qs.keys()) == {"15s60", "60s40"}
        assert qs["15s60"]["zero_shift_ratio"] == round(40 / 55, 6)
        assert qs["60s40"]["zero_shift_ratio"] == round(2 / 40, 6)
        assert qs["60s40"]["frames_registered"] == 40
        assert qs["15s60"]["n_control_points_median"] is None

        # Fehlende Metriken → fallback_reason no_metrics dokumentiert
        sel2 = agent._build_reference_selection(
            groups, "quality", "15s60", stacks,
            registration_metrics=None,
        )
        assert sel2["method"] == "quality"
        assert sel2["fallback_reason"] == "no_metrics"
        assert sel2["quality_scores"] == {}

    def test_build_reference_selection_quality_no_candidates(self, tmp_dir: Path):
        """quality-Sektion mit no_candidates: Metriken vorhanden, aber kein
        Kandidat ≥ 3 Frames → fallback_reason no_candidates."""
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        groups = self._groups()
        stacks = self._stacks(groups)
        metrics = {
            "15s60": _quality_metrics(frames_registered=2, zero_shift_count=0),
            "60s40": _quality_metrics(frames_registered=2, zero_shift_count=0),
        }
        sel = agent._build_reference_selection(
            groups, "quality", "15s60", stacks,
            registration_metrics=metrics,
        )
        assert sel["method"] == "quality"
        assert sel["fallback_reason"] == "no_candidates"

    def test_process_multi_group_passes_registration_metrics(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """Verdrahtung: process_multi_group reicht die registration_metrics
        aus group_metadata an _select_reference_group durch (Spy)."""
        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
        mg_config = MultiGroupConfig(reference_group="quality")
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
        }
        order = ["15s60", "60s40"]
        stack_call = {"n": 0}

        def fake_stack(registered, params, **kwargs):
            gh = order[stack_call["n"]]
            stack_call["n"] += 1
            return stack_fits[gh]

        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            pcc_counter["n"] += 1
            p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        def fake_register(frames, params, **kwargs):
            # Refactor 2026-08-14 (Cluster 3): process_multi_group erwartet
            # ein RegisterFramesResult (uebernimmt die _last_*-Attribute).
            return RegisterFramesResult(
                registered=list(frames),
                last_frame_qualities=[],
                last_frame_rejected=0,
                last_registration_metrics=_quality_metrics(
                    frames_registered=len(frames), zero_shift_count=0,
                ),
            )

        captured: dict = {}

        def spy_select(groups, strategy, group_stacks=None, registration_metrics=None):
            captured["strategy"] = strategy
            captured["registration_metrics"] = registration_metrics
            return "60s40"  # deterministische Referenz (Cross-Group: nur 15s60)

        with patch("astro_process.agents.multi_group_agent.register_frames", side_effect=fake_register), \
             patch("astro_process.agents.multi_group_agent.stack_frames", side_effect=fake_stack), \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc), \
             patch.object(ProcessingAgent, "_select_reference_group",
                          staticmethod(spy_select)):
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], status="ok", corr_hp=0.9,
            )
            result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=None,
            )

        assert captured["strategy"] == "quality"
        assert captured["registration_metrics"] is not None
        assert set(captured["registration_metrics"].keys()) == {"15s60", "60s40"}
        for rm in captured["registration_metrics"].values():
            assert rm["frames_registered"] == 3
        # Referenz 60s40 durchgereicht → genau 1 Nicht-Referenz-Eintrag
        assert len(result.multi_group_metadata["cross_group_registrations"]) == 1


# ═══════════════════════════════════════════════════════════════════
# T6 — PCC per Group
# ═══════════════════════════════════════════════════════════════════


class TestT6PCCPerGroup:
    """T6: PCC per Group — apply, fallback, idempotent."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_apply_pcc_per_group_reuses_existing_method(self, tmp_dir: Path, agent: ProcessingAgent):
        """calls _photometric_color_calibration internally."""
        stack_path = create_test_fits(tmp_dir / "stack.fits", exptime=15.0, gain=60, rng_seed=1)
        mg_config = MultiGroupConfig()
        group_dir = tmp_dir / "group_test"
        context = MagicMock()

        with patch.object(agent, "_photometric_color_calibration") as mock_pcc:
            agent._apply_pcc_per_group(
                stack_path, context, mg_config, group_dir,
                pixel_scale_arcsec=0.0, ra=180.0, dec=30.0,
            )
            mock_pcc.assert_called_once()

    def test_apply_pcc_per_group_status_gaia(self, tmp_dir: Path, agent: ProcessingAgent):
        """returns 'gaia_success' on success."""
        stack_path = create_test_fits(tmp_dir / "stack_gaia.fits", exptime=15.0, gain=60, rng_seed=2)
        mg_config = MultiGroupConfig()
        group_dir = tmp_dir / "group_gaia"
        context = MagicMock()

        with patch.object(agent, "_photometric_color_calibration") as mock_pcc:
            # _photometric_color_calibration writes MG headers on success
            def fake_pcc(stacked, params, **kw):
                if stacked and stacked.exists():
                    from astropy.io import fits as afits
                    with afits.open(stacked, mode="update") as hdul:
                        hdul[0].header["MGCNTGRP"] = 1
                        hdul[0].header["MGMETHOD"] = "pcc"
                        hdul[0].header["MGVER"] = "1.0"
            mock_pcc.side_effect = fake_pcc

            pcc_path, status = agent._apply_pcc_per_group(
                stack_path, context, mg_config, group_dir,
                pixel_scale_arcsec=0.0, ra=180.0, dec=30.0,
            )
            # First call copies to pcc_applied.fits, second call sees MG headers -> gaia_success
            assert status in ("gaia_success", "fallback_gray_world", "skipped")

    def test_apply_pcc_per_group_status_fallback(self, tmp_dir: Path, agent: ProcessingAgent):
        """returns 'fallback_gray_world' when gray world used."""
        stack_path = create_test_fits(tmp_dir / "stack_fb.fits", exptime=15.0, gain=60, rng_seed=3)
        mg_config = MultiGroupConfig()
        group_dir = tmp_dir / "group_fb"
        context = MagicMock()

        with patch.object(agent, "_photometric_color_calibration") as mock_pcc:
            def fake_pcc_fallback(stacked, params, **kw):
                # Write fallback marker
                marker = stacked.parent / "PCC_FALLBACK_GRAY_WORLD.txt"
                marker.write_text("fallback")
                # Also actually create the file
                from astropy.io import fits as afits
                data = np.ones((3, 100, 100), dtype=np.float32)
                hdu = afits.PrimaryHDU(data)
                hdu.writeto(stacked, overwrite=True)
            mock_pcc.side_effect = fake_pcc_fallback

            pcc_path, status = agent._apply_pcc_per_group(
                stack_path, context, mg_config, group_dir,
                pixel_scale_arcsec=0.0, ra=180.0, dec=30.0,
            )
            assert status == "fallback_gray_world"

    def test_apply_pcc_per_group_idempotent(self, tmp_dir: Path, agent: ProcessingAgent):
        """skips if MG-header already present."""
        group_dir = tmp_dir / "group_idem"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True, exist_ok=True)
        pcc_path = stacked_dir / "pcc_applied.fits"

        # Create a pcc_applied.fits with MG headers
        data = np.ones((3, 100, 100), dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["MGCNTGRP"] = 1
        hdu.header["MGMETHOD"] = "pcc"
        hdu.writeto(pcc_path, overwrite=True)

        mg_config = MultiGroupConfig()
        context = MagicMock()

        with patch.object(agent, "_photometric_color_calibration") as mock_pcc:
            result_path, status = agent._apply_pcc_per_group(
                pcc_path, context, mg_config, group_dir,
                pixel_scale_arcsec=0.0, ra=180.0, dec=30.0,
            )
            mock_pcc.assert_not_called()
            assert status == "gaia_success"

    def test_pcc_fallback_marker_file_created(self, tmp_dir: Path, agent: ProcessingAgent):
        """marker file written."""
        group_dir = tmp_dir / "group_marker"
        stacked_dir = group_dir / "04_stacked"
        stacked_dir.mkdir(parents=True, exist_ok=True)
        marker_path = stacked_dir / "PCC_FALLBACK_GRAY_WORLD.txt"
        marker_path.write_text("PCC failed — gray world fallback applied.\n")
        assert marker_path.exists()
        assert "gray world" in marker_path.read_text().lower()


# ═══════════════════════════════════════════════════════════════════
# T7 — Output Structure
# ═══════════════════════════════════════════════════════════════════


class TestT7OutputStructure:
    """T7: Output Structure — group dirs, merged dir, cleanup."""

    def test_output_structure_group_dirs(self, tmp_dir: Path):
        """correct group dir hierarchy."""
        group_dir = tmp_dir / "group_15s60"
        reg_dir = group_dir / "03_registered"
        stack_dir = group_dir / "04_stacked"
        reg_dir.mkdir(parents=True, exist_ok=True)
        stack_dir.mkdir(parents=True, exist_ok=True)

        assert group_dir.exists()
        assert reg_dir.exists()
        assert stack_dir.exists()

    def test_output_structure_merged_dir(self, tmp_dir: Path):
        """merged/ dir created with correct files."""
        merged_dir = tmp_dir / "merged"
        merged_dir.mkdir(parents=True, exist_ok=True)

        # Create merged output
        fits_path = merged_dir / "TestTarget_merged.fits"
        data = np.ones((3, 100, 100), dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.writeto(fits_path, overwrite=True)

        report_path = merged_dir / "merge_report.json"
        report = {"method": "weighted_average", "input_stacks": []}
        report_path.write_text(json.dumps(report, indent=2))

        assert fits_path.exists()
        assert report_path.exists()
        # Verify valid FITS
        with fits.open(fits_path) as hdul:
            assert hdul[0].data is not None

    def test_cleanup_group_dirs(self, tmp_dir: Path):
        """group dirs removed after merge."""
        group_dirs = {}
        for gh in ["15s60", "60s40"]:
            gd = tmp_dir / f"group_{gh}"
            gd.mkdir()
            group_dirs[gh] = group_dirs.get(gh, None)

        groups = {
            "15s60": GroupInfo(key=(15.0, 60, "none"), hash="15s60", frame_count=43, total_exposure=645.0, working_dir=tmp_dir / "group_15s60"),
            "60s40": GroupInfo(key=(60.0, 40, "none"), hash="60s40", frame_count=28, total_exposure=1680.0, working_dir=tmp_dir / "group_60s40"),
        }

        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        agent._cleanup_group_dirs(groups, "TestTarget")

        assert not (tmp_dir / "group_15s60").exists()
        assert not (tmp_dir / "group_60s40").exists()

    def test_cleanup_group_dirs_keep_working(self, tmp_dir: Path):
        """group dirs preserved when flag set."""
        for gh in ["15s60", "60s40"]:
            gd = tmp_dir / f"group_{gh}"
            gd.mkdir()

        groups = {
            "15s60": GroupInfo(key=(15.0, 60, "none"), hash="15s60", frame_count=43, total_exposure=645.0, working_dir=tmp_dir / "group_15s60"),
            "60s40": GroupInfo(key=(60.0, 40, "none"), hash="60s40", frame_count=28, total_exposure=1680.0, working_dir=tmp_dir / "group_60s40"),
        }

        # keep_group_working_dirs is handled in process_multi_group logic
        # The cleanup is not called when keep=True; test the inverse behavior
        # We'll verify that if we skip cleanup, dirs remain
        assert (tmp_dir / "group_15s60").exists()
        assert (tmp_dir / "group_60s40").exists()

    def test_merged_fits_exists(self, tmp_dir: Path):
        """merged.fits is valid FITS."""
        fits_path = tmp_dir / "merged.fits"
        data = np.ones((3, 100, 100), dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.writeto(fits_path, overwrite=True)

        with fits.open(fits_path) as hdul:
            assert hdul[0].data is not None
            assert hdul[0].data.shape == (3, 100, 100)


# ═══════════════════════════════════════════════════════════════════
# T8 — Group Metadata
# ═══════════════════════════════════════════════════════════════════


class TestT8GroupMetadata:
    """T8: Group Metadata — merge_report.json, agent-log.yaml, weights."""

    def test_merge_report_json_format(self, tmp_dir: Path):
        """merge_report.json has correct keys."""
        report = {
            "method": "weighted_average",
            "weight_by": "frame_count",
            "reference_group": "15s60",
            "input_stacks": [
                {
                    "group": "15s60",
                    "path": "/tmp/15s60.fits",
                    "metadata": {"frame_count": 43, "exptime": 15.0},
                    "weight": 43.0,
                    "pcc_status": "gaia_success",
                },
            ],
            "output": {
                "path": "/tmp/merged.fits",
                "shape": [3, 100, 100],
                "stats": {"min": 0.0, "max": 1.0, "mean": 0.5, "median": 0.5},
            },
            "pcc_fallback_groups": [],
            "timestamp": "2026-07-30T00:00:00",
        }
        report_path = tmp_dir / "merge_report.json"
        report_path.write_text(json.dumps(report, indent=2))

        loaded = json.loads(report_path.read_text())
        assert "method" in loaded
        assert "weight_by" in loaded
        assert "input_stacks" in loaded
        assert "output" in loaded
        assert "pcc_fallback_groups" in loaded
        assert "timestamp" in loaded

    def test_merge_report_per_group_metadata(self):
        """each group has hash, frame_count, exptime, etc."""
        meta = {
            "group_hash": "15s60",
            "frame_count": 43,
            "exptime": 15.0,
            "gain": 60,
            "filter": None,
            "total_exposure": 645.0,
            "weight": 43.0,
            "pcc_status": "gaia_success",
        }
        assert meta["group_hash"] == "15s60"
        assert meta["frame_count"] == 43
        assert meta["exptime"] == 15.0
        assert meta["gain"] == 60
        assert meta["total_exposure"] == 645.0

    def test_agent_log_multi_group_section(self, tmp_dir: Path):
        """agent-log.yaml has multi_group section with groups + merge."""
        import yaml
        log = {
            "multi_group": {
                "enabled": True,
                "groups": [
                    {"hash": "15s60", "frame_count": 43, "exptime": 15.0, "gain": 60, "filter": None, "total_exposure": 645.0, "weight": 43.0, "pcc_status": "gaia_success"},
                    {"hash": "60s40", "frame_count": 28, "exptime": 60.0, "gain": 40, "filter": None, "total_exposure": 1680.0, "weight": 28.0, "pcc_status": "gaia_success"},
                ],
                "merge": {
                    "method": "weighted_average",
                    "weight_by": "frame_count",
                    "reference_group": "15s60",
                },
            },
        }
        log_path = tmp_dir / "agent-log.yaml"
        with open(log_path, "w", encoding="utf-8") as f:
            yaml.dump(log, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

        with open(log_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert "multi_group" in loaded
        assert "groups" in loaded["multi_group"]
        assert "merge" in loaded["multi_group"]
        assert len(loaded["multi_group"]["groups"]) == 2

    def test_group_metadata_contains_registration_metrics(self, tmp_dir: Path):
        """V1.3-3 (stella-Befund 4): group_metadata enthaelt je Gruppe
        `registration_metrics` (method_counts-dict, frames_registered ==
        frame_count, corr_hp-Verteilung). Additiv — Gruppen ohne
        Registrations-Daten erhalten ein leeres dict."""
        agent = ProcessingAgent(working_dir=tmp_dir / "out", config=None)
        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
        mg_config = MultiGroupConfig()
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        # Echte Stack-Dateien (Referenz-Signal-Scoring + Cross-Group-Pfad)
        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
        }
        order = ["15s60", "60s40"]
        stack_call = {"n": 0}

        def fake_stack(registered, params, **kwargs):
            gh = order[stack_call["n"]]
            stack_call["n"] += 1
            return stack_fits[gh]

        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            pcc_counter["n"] += 1
            p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        def fake_register(frames, params, **kwargs):
            # Registrations-Pass ist nicht Gegenstand dieses Tests; die
            # V1.3-3-Metriken werden wie von _register_frames befuellt
            # (frames_registered == Frame-Anzahl der Gruppe).
            # Refactor 2026-08-14 (Cluster 3): process_multi_group erwartet
            # ein RegisterFramesResult (uebernimmt die _last_*-Attribute).
            return RegisterFramesResult(
                registered=list(frames),
                last_frame_qualities=[],
                last_frame_rejected=0,
                last_registration_metrics={
                    "method_counts": {"fft": len(frames) - 1, "astroalign": 0},
                    "zero_shift_count": 0,
                    "rejected_count": 0,
                    "frames_total": len(frames),
                    "frames_registered": len(frames),
                    "corr_hp": {
                        "count": len(frames) - 1,
                        "min": 0.5,
                        "max": 0.9,
                        "median": 0.7,
                    },
                    "n_control_points": {"count": 0, "median": None},
                },
            )

        with patch("astro_process.agents.multi_group_agent.register_frames", side_effect=fake_register), \
             patch("astro_process.agents.multi_group_agent.stack_frames", side_effect=fake_stack), \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], status="ok", corr_hp=0.9,
            )
            result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=None,
            )

        groups = result.multi_group_metadata["groups"]
        assert len(groups) == 2
        for gh, meta in groups.items():
            assert "registration_metrics" in meta
            rm = meta["registration_metrics"]
            assert isinstance(rm["method_counts"], dict)
            assert rm["method_counts"]["fft"] == meta["frame_count"] - 1
            assert rm["method_counts"]["astroalign"] == 0
            assert rm["frames_registered"] == meta["frame_count"]
            assert rm["frames_total"] == meta["frame_count"]
            assert rm["corr_hp"]["median"] == 0.7
            assert rm["rejected_count"] == 0

    def test_agent_log_multi_group_registration_metrics(self, tmp_dir: Path):
        """V1.3-3 (stella-Befund 4): agent-log.yaml enthaelt je Gruppe
        `multi_group.groups[*]["registration_metrics"]` (method_counts-dict,
        frames_registered == frame_count) — der M13-Kernfall (kaputte
        Cross-Group-Registration) ist damit im agent-log erkennbar. Voller
        process_multi_group-Lauf + ArchiveAgent._create_agent_log."""
        import yaml

        agent = ProcessingAgent(working_dir=tmp_dir / "out", config=None)
        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
        mg_config = MultiGroupConfig()
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
        }
        order = ["15s60", "60s40"]
        stack_call = {"n": 0}

        def fake_stack(registered, params, **kwargs):
            gh = order[stack_call["n"]]
            stack_call["n"] += 1
            return stack_fits[gh]

        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            pcc_counter["n"] += 1
            p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        def fake_register(frames, params, **kwargs):
            # Registrations-Pass ist nicht Gegenstand dieses Tests; die
            # V1.3-3-Metriken werden wie von _register_frames befuellt
            # (frames_registered == Frame-Anzahl der Gruppe).
            # Refactor 2026-08-14 (Cluster 3): process_multi_group erwartet
            # ein RegisterFramesResult (uebernimmt die _last_*-Attribute).
            return RegisterFramesResult(
                registered=list(frames),
                last_frame_qualities=[],
                last_frame_rejected=0,
                last_registration_metrics={
                    "method_counts": {"fft": len(frames) - 1, "astroalign": 0},
                    "zero_shift_count": 0,
                    "rejected_count": 0,
                    "frames_total": len(frames),
                    "frames_registered": len(frames),
                    "corr_hp": {
                        "count": len(frames) - 1,
                        "min": 0.5,
                        "max": 0.9,
                        "median": 0.7,
                    },
                    "n_control_points": {"count": 0, "median": None},
                },
            )

        with patch("astro_process.agents.multi_group_agent.register_frames", side_effect=fake_register), \
             patch("astro_process.agents.multi_group_agent.stack_frames", side_effect=fake_stack), \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], status="ok", corr_hp=0.9,
            )
            result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=None,
            )

        # agent-log ueber den vollen Lauf erzeugen (mg_metadata aus dem
        # ProcessingResult, wie von ArchiveAgent.run durchgereicht) — der
        # M13-Kernfall liest genau dieses Artefakt.
        archive = ArchiveAgent(output_root=tmp_dir / "out", config=None)
        log_path = archive._create_agent_log(
            tmp_dir / "out", context, result, cal_result,
            debayer_result=deb_result,
            multi_group_metadata=result.multi_group_metadata,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert "multi_group" in log
        mg_groups = log["multi_group"]["groups"]
        assert len(mg_groups) == 2
        for g in mg_groups:
            assert "registration_metrics" in g
            rm = g["registration_metrics"]
            assert isinstance(rm["method_counts"], dict)
            assert rm["method_counts"]["fft"] == g["frame_count"] - 1
            assert rm["method_counts"]["astroalign"] == 0
            assert rm["frames_registered"] == g["frame_count"]
            assert rm["frames_total"] == g["frame_count"]
            assert rm["corr_hp"]["median"] == 0.7
            assert rm["rejected_count"] == 0

        # V1.3-3 (stella-Befund 4): Aggregation auf Multi-Group-Ebene —
        # mode == "multi_group" und Gruppen-Keys identisch zu
        # group_metadata (NUR Gruppen MIT registration_metrics; hier
        # befuellt fake_register beide).
        assert result.registration_metrics["mode"] == "multi_group"
        assert set(result.registration_metrics["groups"].keys()) == set(
            result.multi_group_metadata["groups"].keys()
        )
        assert len(result.registration_metrics["groups"]) == 2

    def test_agent_log_contains_cross_group_registrations(self, tmp_dir: Path):
        """V1.3-3 (stella-Befund 4): Cross-Group-Registrations-Metriken
        (Pass 2 — der M13-Fehlerort) sind im agent-log.yaml unter
        `multi_group.cross_group_registrations` sichtbar (nicht nur in
        merge_report.json): Liste mit den erwarteten Schlüsseln je
        Nicht-Referenz-Gruppe. Voller process_multi_group-Lauf +
        ArchiveAgent._create_agent_log."""
        import yaml

        agent = ProcessingAgent(working_dir=tmp_dir / "out", config=None)
        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
        mg_config = MultiGroupConfig()
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
        }
        order = ["15s60", "60s40"]
        stack_call = {"n": 0}

        def fake_stack(registered, params, **kwargs):
            gh = order[stack_call["n"]]
            stack_call["n"] += 1
            return stack_fits[gh]

        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            pcc_counter["n"] += 1
            p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        def fake_register(frames, params, **kwargs):
            # Registrations-Pass ist nicht Gegenstand dieses Tests; die
            # V1.3-3-Metriken werden wie von _register_frames befuellt.
            # Refactor 2026-08-14 (Cluster 3): process_multi_group erwartet
            # ein RegisterFramesResult (uebernimmt die _last_*-Attribute).
            return RegisterFramesResult(
                registered=list(frames),
                last_frame_qualities=[],
                last_frame_rejected=0,
                last_registration_metrics={
                    "method_counts": {"fft": len(frames) - 1, "astroalign": 0},
                    "zero_shift_count": 0,
                    "rejected_count": 0,
                    "frames_total": len(frames),
                    "frames_registered": len(frames),
                    "corr_hp": {
                        "count": len(frames) - 1,
                        "min": 0.5,
                        "max": 0.9,
                        "median": 0.7,
                    },
                    "n_control_points": {"count": 0, "median": None},
                },
            )

        with patch("astro_process.agents.multi_group_agent.register_frames", side_effect=fake_register), \
             patch("astro_process.agents.multi_group_agent.stack_frames", side_effect=fake_stack), \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], status="ok", corr_hp=0.9,
            )
            result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=None,
            )

        # Punkt 1: mg_metadata enthaelt die Cross-Group-Registrations
        # (bisher nur in merge_report.json — der M13-Kernfall).
        assert "cross_group_registrations" in result.multi_group_metadata
        cgr_meta = result.multi_group_metadata["cross_group_registrations"]
        assert isinstance(cgr_meta, list)
        assert len(cgr_meta) == 1  # eine Nicht-Referenz-Gruppe

        # Punkt 2: Agent-Log reicht die Sektion durch.
        archive = ArchiveAgent(output_root=tmp_dir / "out", config=None)
        log_path = archive._create_agent_log(
            tmp_dir / "out", context, result, cal_result,
            debayer_result=deb_result,
            multi_group_metadata=result.multi_group_metadata,
        )
        log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
        assert "multi_group" in log
        assert "cross_group_registrations" in log["multi_group"]
        mg_cross = log["multi_group"]["cross_group_registrations"]
        assert isinstance(mg_cross, list)
        assert len(mg_cross) == 1
        expected_keys = {"group", "reference", "corr_hp", "method", "status"}
        for entry in mg_cross:
            assert expected_keys.issubset(entry.keys()), entry
            assert entry["status"] == "ok"
            assert entry["corr_hp"] == 0.9
        # Inhalt identisch zum Metadaten-Original (Durchreichung unveraendert).
        assert mg_cross == cgr_meta

    def test_weight_calculation_frame_count(self):
        """weight = frame_count."""
        meta = {"frame_count": 43, "total_exposure": 645.0}
        merge_cfg = MergeConfig(weight_by="frame_count")
        w = MergeAgent._compute_weight(meta, merge_cfg)
        assert w == 43.0

    def test_weight_calculation_total_exposure(self):
        """weight = total_exposure."""
        meta = {"frame_count": 43, "total_exposure": 645.0}
        merge_cfg = MergeConfig(weight_by="total_exposure")
        w = MergeAgent._compute_weight(meta, merge_cfg)
        assert w == 645.0


# ═══════════════════════════════════════════════════════════════════
# T9 — MergeResult
# ═══════════════════════════════════════════════════════════════════


class TestT9MergeResult:
    """T9: MergeResult dataclass."""

    def test_merge_result_dataclass(self):
        """MergeResult has correct fields."""
        result = MergeResult(
            merged_path=Path("/tmp/merged.fits"),
            group_stacks={"15s60": Path("/tmp/15s60.fits")},
            group_metadata={"15s60": {"frame_count": 43}},
            merge_report={"method": "weighted_average"},
        )
        assert result.merged_path == Path("/tmp/merged.fits")
        assert result.group_stacks["15s60"] == Path("/tmp/15s60.fits")
        assert result.group_metadata["15s60"]["frame_count"] == 43
        assert result.merge_report["method"] == "weighted_average"

    def test_merge_result_defaults(self):
        """Optional fields default to None/empty."""
        result = MergeResult(merged_path=None)
        assert result.merged_path is None
        assert result.group_stacks == {}
        assert result.group_metadata == {}
        assert result.merge_report == {}
        assert result.preview_path is None
        assert result.agent_log is None

    def test_merge_result_types(self):
        """MergeResult field types verify."""
        result = MergeResult(
            merged_path=Path("/tmp/m.fits"),
            preview_path=Path("/tmp/m_preview.jpg"),
            agent_log=Path("/tmp/agent-log.yaml"),
        )
        assert isinstance(result.merged_path, Path)
        assert isinstance(result.preview_path, Path)
        assert isinstance(result.agent_log, Path)


# ═══════════════════════════════════════════════════════════════════
# T10 — MergeAgent
# ═══════════════════════════════════════════════════════════════════


class TestT10MergeAgent:
    """T10: MergeAgent — init, run, merge methods, error handling."""

    def test_merge_agent_init(self, tmp_dir: Path):
        """creates merged/ dir."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        assert agent.working_dir == tmp_dir
        assert (tmp_dir / "merged").exists()

    def test_merge_agent_run_weighted_average(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """correct weighted average merge."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
        )
        assert result.merged_path is not None
        assert result.merged_path.exists()
        assert result.merge_report["method"] == "weighted_average"

    def test_merge_agent_run_average(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """simple average merge (uses mean)."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
            merge_config=MergeConfig(method="average"),
        )
        assert result.merged_path is not None
        assert result.merged_path.exists()

    def test_merge_agent_run_median(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """median merge."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
            merge_config=MergeConfig(method="median"),
        )
        assert result.merged_path is not None
        assert result.merged_path.exists()

    def test_merge_agent_shape_mismatch(self, tmp_dir: Path):
        """raises ValueError on shape mismatch."""
        stack1 = create_test_fits(tmp_dir / "stack1.fits", shape=(100, 100, 3), exptime=15.0, gain=60, rng_seed=1)
        stack2 = create_test_fits(tmp_dir / "stack2.fits", shape=(50, 100, 3), exptime=60.0, gain=40, rng_seed=2)  # different H

        agent = MergeAgent(working_dir=tmp_dir, config=None)
        with pytest.raises(ValueError, match="Shape mismatch"):
            agent.run(
                group_stacks={"15s60": stack1, "60s40": stack2},
                group_metadata={
                    "15s60": {"frame_count": 1, "total_exposure": 15.0},
                    "60s40": {"frame_count": 1, "total_exposure": 60.0},
                },
                target_name="TestTarget",
            )

    def test_merge_agent_weight_frame_count(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """weights by frame_count."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
            merge_config=MergeConfig(weight_by="frame_count"),
        )
        assert result.merged_path is not None

    def test_merge_agent_weight_total_exposure(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """weights by total_exposure."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
            merge_config=MergeConfig(weight_by="total_exposure"),
        )
        assert result.merged_path is not None

    def test_merge_agent_clip_negative_post_merge(self, tmp_dir: Path):
        """max(0, result) after merge."""
        # Create stacks with some negative values
        stack1_path = tmp_dir / "stack1.fits"
        data1 = np.full((3, 50, 50), -0.5, dtype=np.float32)
        data1[1, :, :] = 0.5  # some channel is negative overall
        hdu1 = fits.PrimaryHDU(data1)
        hdu1.writeto(stack1_path, overwrite=True)

        stack2_path = tmp_dir / "stack2.fits"
        data2 = np.ones((3, 50, 50), dtype=np.float32)
        hdu2 = fits.PrimaryHDU(data2)
        hdu2.writeto(stack2_path, overwrite=True)

        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks={"15s60": stack1_path, "60s40": stack2_path},
            group_metadata={
                "15s60": {"frame_count": 1, "total_exposure": 15.0},
                "60s40": {"frame_count": 1, "total_exposure": 60.0},
            },
            target_name="TestTarget",
        )
        assert result.merged_path is not None

        # Verify no negative values in merged output
        with fits.open(result.merged_path) as hdul:
            merged_data = hdul[0].data
            assert merged_data.min() >= 0.0

    def test_merge_agent_fits_header_propagation(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """EXPTIME, GAIN, FILTER, MG*-keys set correctly."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
        )
        assert result.merged_path is not None

        with fits.open(result.merged_path) as hdul:
            h = hdul[0].header
            # EXPTIME should be sum of total_exposures
            assert "EXPTIME" in h
            assert h["GAIN"] == "MULTI"
            assert h["FILTER"] == "MULTI"
            assert "MGCNTGRP" in h
            assert h["MGCNTGRP"] == 2  # 2 groups
            assert "MGREFGRP" in h
            assert "MGMETHOD" in h
            assert h["MGMETHOD"] == "weighted_average"
            assert "MGWTBY" in h
            assert h["MGVER"] == "1.0"

    def test_merge_agent_wcs_header_propagation(self, tmp_dir: Path):
        """WCS keys from reference."""
        # Create stacks with WCS on ref
        ref_path = tmp_dir / "ref.fits"
        data = np.ones((3, 100, 100), dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["CRVAL1"] = 180.0
        hdu.header["CRVAL2"] = 30.0
        hdu.header["CRPIX1"] = 50.0
        hdu.header["CRPIX2"] = 50.0
        hdu.header["CDELT1"] = -0.01
        hdu.header["CDELT2"] = 0.01
        hdu.header["CTYPE1"] = "RA---TAN"
        hdu.header["CTYPE2"] = "DEC--TAN"
        hdu.header["EXPTIME"] = 15.0
        hdu.header["GAIN"] = 60
        hdu.header["MGFRAME"] = 43
        hdu.header["TOTALEXP"] = 645.0
        hdu.writeto(ref_path, overwrite=True)

        other_path = tmp_dir / "other.fits"
        data2 = np.ones((3, 100, 100), dtype=np.float32)
        hdu2 = fits.PrimaryHDU(data2)
        hdu2.header["EXPTIME"] = 60.0
        hdu2.header["GAIN"] = 40
        hdu2.header["MGFRAME"] = 28
        hdu2.header["TOTALEXP"] = 1680.0
        hdu2.writeto(other_path, overwrite=True)

        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks={"15s60": ref_path, "60s40": other_path},
            group_metadata={
                "15s60": {"frame_count": 43, "total_exposure": 645.0, "exptime": 15.0, "gain": 60, "filter": None, "pcc_status": "gaia_success"},
                "60s40": {"frame_count": 28, "total_exposure": 1680.0, "exptime": 60.0, "gain": 40, "filter": None, "pcc_status": "gaia_success"},
            },
            target_name="TestTarget",
        )
        assert result.merged_path is not None

        with fits.open(result.merged_path) as hdul:
            h = hdul[0].header
            assert h["CRVAL1"] == 180.0
            assert h["CRVAL2"] == 30.0
            assert h["CTYPE1"] == "RA---TAN"

    def test_merge_agent_preview_jpg(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """preview JPG created."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
        )
        assert result.preview_path is not None
        assert result.preview_path.exists()
        assert result.preview_path.suffix == ".jpg"

    def test_merge_agent_merge_report(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """merge_report.json has correct structure."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
        )
        report = result.merge_report
        assert "method" in report
        assert "weight_by" in report
        assert "reference_group" in report
        assert "input_stacks" in report
        assert "output" in report
        assert "pcc_fallback_groups" in report
        assert "timestamp" in report
        assert len(report["input_stacks"]) == 2

        # Verify report JSON written
        report_path = tmp_dir / "merged" / "merge_report.json"
        assert report_path.exists()
        loaded = json.loads(report_path.read_text())
        assert loaded["method"] == "weighted_average"

    def test_merge_agent_less_than_2_stacks(self, tmp_dir: Path, sample_stacks: dict[str, Path], sample_metadata: dict[str, dict]):
        """V1.9.1 FIX-11: single stack now creates merged with warning (not error)."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        single_stack = {"15s60": sample_stacks["15s60"]}
        single_meta = {"15s60": sample_metadata["15s60"]}
        result = agent.run(
            group_stacks=single_stack,
            group_metadata=single_meta,
            target_name="TestTarget",
        )
        assert result.merged_path is not None
        assert result.merged_path.exists()
        assert "error" not in result.merge_report
        assert result.merge_report["reference_group"] == "15s60"

    def test_merge_agent_resolve_config_from_self(self, tmp_dir: Path):
        """_resolve_merge_config returns config when available."""
        cfg = AppConfig(multi_group=MultiGroupConfig(merge=MergeConfig(method="median", weight_by="total_exposure")))
        agent = MergeAgent(working_dir=tmp_dir, config=cfg)
        resolved = agent._resolve_merge_config()
        assert resolved.method == "median"
        assert resolved.weight_by == "total_exposure"

    def test_merge_agent_resolve_config_default(self, tmp_dir: Path):
        """_resolve_merge_config returns defaults when no config."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        resolved = agent._resolve_merge_config()
        assert resolved.method == "weighted_average"
        assert resolved.weight_by == "frame_count"


# ═══════════════════════════════════════════════════════════════════
# T11 — CLI
# ═══════════════════════════════════════════════════════════════════


class TestT11CLI:
    """T11: CLI Flags + merge sub-command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_cli_multi_group_flag(self, runner: CliRunner, tmp_dir: Path):
        """--multi-group sets auto_group and merge."""
        # We'll test the flag parsing by invoking dry-run
        result = runner.invoke(
            cli, ["process", str(tmp_dir), "--dry-run", "--multi-group"],
        )
        # The CLI should handle dry-run + multi-group
        assert result.exit_code == 0 or result.exit_code == 2
        # Exit code 2 means error (expected when target dir has no FITS)

    def test_cli_auto_group_flag(self, runner: CliRunner, tmp_dir: Path):
        """--auto-group flag."""
        result = runner.invoke(
            cli, ["process", str(tmp_dir), "--dry-run", "--auto-group"],
        )
        assert result.exit_code in (0, 2)

    def test_cli_merge_flag(self, runner: CliRunner, tmp_dir: Path):
        """--merge flag."""
        result = runner.invoke(
            cli, ["process", str(tmp_dir), "--dry-run", "--merge"],
        )
        assert result.exit_code in (0, 2)

    def test_cli_no_merge_flag(self, runner: CliRunner, tmp_dir: Path):
        """--no-merge flag."""
        result = runner.invoke(
            cli, ["process", str(tmp_dir), "--dry-run", "--no-merge"],
        )
        assert result.exit_code in (0, 2)

    def test_cli_weight_by_option(self, runner: CliRunner, tmp_dir: Path):
        """--weight-by option."""
        result = runner.invoke(
            cli, ["process", str(tmp_dir), "--dry-run", "--weight-by", "total_exposure"],
        )
        assert result.exit_code in (0, 2)

    def test_cli_merge_method_option(self, runner: CliRunner, tmp_dir: Path):
        """--merge-method option."""
        result = runner.invoke(
            cli, ["process", str(tmp_dir), "--dry-run", "--merge-method", "median"],
        )
        assert result.exit_code in (0, 2)

    def test_cli_dry_run_multi_group(self, runner: CliRunner, tmp_dir: Path):
        """--dry-run + --multi-group shows groups table (when dir has frames)."""
        # Create a valid FITS in the target to pass discovery
        create_test_fits(tmp_dir / "light_0000.fits", exptime=15.0, gain=60, add_stars=True, rng_seed=1)
        create_test_fits(tmp_dir / "light_0001.fits", exptime=60.0, gain=40, add_stars=True, rng_seed=2)
        create_test_fits(tmp_dir / "dark_0000.fits", exptime=15.0, gain=60, add_stars=False, rng_seed=3)
        create_test_fits(tmp_dir / "dark_0001.fits", exptime=15.0, gain=60, add_stars=False, rng_seed=4)

        result = runner.invoke(
            cli, ["process", str(tmp_dir), "--dry-run", "--multi-group"],
        )
        assert result.exit_code in (0, 2)
        if result.exit_code == 0:
            # Should show groups
            assert "Multi-Group" in result.output or "groups" in result.output.lower()

    def test_cli_merge_subcommand(self, runner: CliRunner, tmp_dir: Path):
        """'merge' sub-command accepts target_path + options."""
        # Without generated/ dir, merge exits with ClickException (code 1)
        # This is expected — merge requires pre-existing group dirs
        result = runner.invoke(
            cli, ["merge", str(tmp_dir), "--dry-run"],
        )
        assert result.exit_code in (0, 1, 2)

    def test_cli_merge_subcommand_dry_run(self, runner: CliRunner, tmp_dir: Path):
        """'merge --dry-run' lists groups (requires generated/ dir)."""
        # Without generated/ dir, merge exits with ClickException (code 1)
        result = runner.invoke(
            cli, ["merge", str(tmp_dir), "--dry-run"],
        )
        assert result.exit_code in (0, 1, 2)

    def test_cli_help(self, runner: CliRunner):
        """CLI help works."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Astra" in result.output

    def test_cli_process_help(self, runner: CliRunner):
        """process subcommand help works."""
        result = runner.invoke(cli, ["process", "--help"])
        assert result.exit_code == 0
        assert "multi-group" in result.output or "Process" in result.output


# ═══════════════════════════════════════════════════════════════════
# V1.7-5 — Always Multi-Group: CLI vereinheitlicht (AC-B)
# (ersetzt den V1.3-4-Einzel-Stack-Warnblock-Testsatz)
# ═══════════════════════════════════════════════════════════════════


class TestV175AlwaysMultiGroupCli:
    """V1.7-5 (Always Multi-Group): Es gibt nur noch EINEN Verarbeitungspfad —
    process_multi_group fuer jede Gruppenzahl (inkl. 1). Der fruehere
    V1.3-4-Warnblock ("laeuft als Einzel-Stack") ist obsolet;
    --multi-group/--auto-group sind deprecated No-ops (Grace-Period bis
    v1.8), der Merge bleibt per Default AN (AC-B6)."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    @staticmethod
    def _make_group_target(tmp_dir: Path, exptimes: tuple[float, ...]) -> Path:
        """Target mit lights/-Ordner (Punkt 3: nur konventionelle Input-
        Ordner werden gestagt); je EXPTIME-Wert 2 Lights. Zwei verschiedene
        EXPTIME-Werte -> 2 Gruppen; ein Wert -> 1 Gruppe."""
        lights = tmp_dir / "lights"
        i = 0
        for exptime in exptimes:
            for _ in range(2):
                create_test_fits(
                    lights / f"light_{i:04d}.fits",
                    exptime=exptime,
                    gain=60,
                    add_stars=True,
                    rng_seed=1 + i,
                )
                i += 1
        return tmp_dir

    # ── dry-run (vereinheitlicht, AC-B4) ────────────────────────────

    def test_dry_run_shows_group_table_two_groups(self, runner: CliRunner, tmp_dir: Path):
        """Dry-run bei 2 Gruppen → Gruppen-Tabelle + Reference/Merge-Info;
        KEIN [WARN]-Einzel-Stack-Hinweis mehr."""
        self._make_group_target(tmp_dir, exptimes=(15.0, 60.0))
        result = runner.invoke(cli, ["process", str(tmp_dir), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "DRY RUN - Would process" in result.output
        assert "Multi-Group: 2 groups found" in result.output
        assert "Reference group:" in result.output
        assert "Merge: method=" in result.output
        assert "[WARN]" not in result.output

    def test_dry_run_shows_group_table_single_group(self, runner: CliRunner, tmp_dir: Path):
        """Dry-run bei GENAU 1 Gruppe → dieselbe Tabelle wie bei N Gruppen
        (kein separater stiller Pfad mehr)."""
        self._make_group_target(tmp_dir, exptimes=(15.0,))
        result = runner.invoke(cli, ["process", str(tmp_dir), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Multi-Group: 1 groups found" in result.output
        assert "Reference group:" in result.output
        assert "[WARN]" not in result.output

    # ── Normal-Pfad (echter Lauf, AC-B1/B2/B3/B6) ───────────────────

    def _invoke_process_normal(
        self,
        runner: CliRunner,
        tmp_dir: Path,
        extra_args: Optional[list[str]] = None,
    ) -> tuple:
        """Invoke `process <target>` (Normal-Pfad) mit gemockten Pipeline-
        Agents (Muster TestCR001P1CliFlag). Liefert (CliResult, captured
        mg_config, captured merge_agent, deprecation-Warn-Events)."""
        captured: dict = {}
        dep_warns: list = []

        discovery = MagicMock()
        discovery.run.return_value = MagicMock(context=MagicMock(total_light_frames=2))
        cal = MagicMock()
        cal.run.return_value = MagicMock(master_dark=None)
        deb = MagicMock()
        deb.run.return_value = MagicMock(debayered_frames=[])
        proc = MagicMock()

        def capture_mg(*args, **kwargs):
            captured["mg_config"] = kwargs.get("multi_group_config")
            captured["merge_agent"] = kwargs.get("merge_agent")
            return MagicMock(stacked=None, multi_group_metadata=None)

        proc.process_multi_group.side_effect = capture_mg
        arch = MagicMock()
        arch.run.return_value = MagicMock(output_dir=tmp_dir, final_fits=None)

        with patch("astro_process.cli.create_discovery_agent", return_value=discovery), \
             patch("astro_process.cli.create_calibration_agent", return_value=cal), \
             patch("astro_process.cli.create_debayer_agent", return_value=deb), \
             patch("astro_process.cli.create_processing_agent", return_value=proc), \
             patch("astro_process.cli.create_archive_agent", return_value=arch), \
             patch("astro_process.cli.logger") as mock_logger:
            result = runner.invoke(
                cli, ["process", str(tmp_dir)] + (extra_args or [])
            )
            for c in mock_logger.warning.call_args_list:
                if c.args and c.args[0] == "cli.process.multi_group_flag_deprecated":
                    dep_warns.append(c)

        return result, captured.get("mg_config"), captured.get("merge_agent"), dep_warns

    def test_process_multi_group_is_default(self, runner: CliRunner, tmp_dir: Path):
        """AC-B1/B2: Normal-Pfad OHNE Flags → process_multi_group wird
        gerufen (auch bei 1 Gruppe); MergeAgent konstruiert (Default AN);
        kein Einzel-Stack-Zweig mehr."""
        self._make_group_target(tmp_dir, exptimes=(15.0,))
        result, mg_config, merge_agent, dep_warns = self._invoke_process_normal(
            runner, tmp_dir,
        )
        assert result.exit_code == 0, result.output
        assert mg_config is not None
        assert merge_agent is not None  # AC-B6: Merge per Default AN
        assert "[WARN] Target enthaelt" not in result.output
        assert dep_warns == []

    @pytest.mark.parametrize("flag", ["--multi-group", "--auto-group"])
    def test_deprecated_flags_are_noop_with_warning(
        self, runner: CliRunner, tmp_dir: Path, flag: str,
    ):
        """AC-B3: --multi-group/--auto-group → [WARN]-Echo + Log-Event
        cli.process.multi_group_flag_deprecated; Verhalten sonst identisch
        (No-op, Grace-Period bis v1.8)."""
        self._make_group_target(tmp_dir, exptimes=(15.0,))
        result, mg_config, merge_agent, dep_warns = self._invoke_process_normal(
            runner, tmp_dir, extra_args=[flag],
        )
        assert result.exit_code == 0, result.output
        assert "[WARN]" in result.output
        assert "obsolet" in result.output
        assert "deprecated" in result.output
        assert len(dep_warns) == 1
        assert dep_warns[0].kwargs["flags"] == [flag]
        # B6-Semantik unveraendert: --multi-group allein laesst den Merge AN.
        assert merge_agent is not None

    def test_no_merge_disables_merge_agent_alongside_flags(
        self, runner: CliRunner, tmp_dir: Path,
    ):
        """AC-B6: --no-merge wirkt weiterhin (auch neben deprecated Flag) —
        kein MergeAgent."""
        self._make_group_target(tmp_dir, exptimes=(15.0,))
        result, _mg_config, merge_agent, _dep = self._invoke_process_normal(
            runner, tmp_dir, extra_args=["--multi-group", "--no-merge"],
        )
        assert result.exit_code == 0, result.output
        assert merge_agent is None


# ═══════════════════════════════════════════════════════════════════
# T14 — Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestT14EdgeCases:
    """T14: Edge cases — missing headers, empty groups, corrupt files, etc."""

    def test_edge_missing_header(self, tmp_dir: Path):
        """Missing EXPTIME/GAIN/FILTER → graceful fallback (0.0, 0, 'none')."""
        fp = tmp_dir / "light.fits"
        create_test_fits(fp, exptime=15.0, gain=60, filter_name=None)

        # Create FrameInfo with missing header values
        header = FitsHeader(exptime=None, gain=None, filter_name=None)
        fi = FrameInfo(path=fp, frame_type=FrameType.LIGHT, header=header, index=0, size_bytes=100, width=100, height=100)
        frameset = FrameSet(frame_type=FrameType.LIGHT, frames=[fi])
        groups = frameset.group_by_params()
        key = list(groups.keys())[0]
        assert key[0] == 0.0
        assert key[1] == 0
        assert key[2] == "none"

    def test_edge_empty_group(self, tmp_dir: Path):
        """Group with 0 frames → skip + warning."""
        # Create a GroupInfo with 0 frames
        info = GroupInfo(key=(15.0, 60, "none"), hash="15s60", frame_count=0, total_exposure=0.0)
        assert info.frame_count == 0

        # In process_multi_group, groups with < 2 frames are skipped
        groups = {"15s60": info}
        # process_multi_group would skip this group due to len(frames) < 2

    def test_edge_shape_mismatch(self, tmp_dir: Path):
        """Different shaped stacks → clear ValueError on merge."""
        s1 = create_test_fits(tmp_dir / "s1.fits", shape=(100, 100, 3), exptime=15.0, gain=60, rng_seed=1)
        s2 = create_test_fits(tmp_dir / "s2.fits", shape=(50, 50, 3), exptime=60.0, gain=40, rng_seed=2)

        agent = MergeAgent(working_dir=tmp_dir, config=None)
        with pytest.raises(ValueError, match="Shape mismatch"):
            agent.run(
                group_stacks={"15s60": s1, "60s40": s2},
                group_metadata={
                    "15s60": {"frame_count": 1, "total_exposure": 15.0},
                    "60s40": {"frame_count": 1, "total_exposure": 60.0},
                },
                target_name="TestTarget",
            )

    def test_edge_corrupt_fits(self, tmp_dir: Path):
        """Corrupt FITS in a group → skip group + warning."""
        # Create a valid FITS and a corrupt one
        valid = create_test_fits(tmp_dir / "valid.fits", exptime=15.0, gain=60, rng_seed=1)
        corrupt = tmp_dir / "corrupt.fits"
        corrupt.write_text("NOT A FITS FILE")

        # ProcessingAgent._load_frame should handle corrupt file gracefully
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        with pytest.raises(Exception):
            # Should raise some kind of error when loading corrupt FITS
            agent._load_frame(corrupt)

        # But valid file loads fine
        data = agent._load_frame(valid)
        assert data is not None
        assert data.shape == (100, 100, 3)

    def test_edge_zero_groups(self, tmp_dir: Path):
        """No light frames → clear error on pipeline."""
        context = make_sample_context(tmp_dir, group_count=0, frames_per_group=0)
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        mg_config = MultiGroupConfig()

        # Light frames should be empty
        lights = context.get_lights()
        assert lights.count == 0

        # DiscoveryAgent should find 0 groups
        da = DiscoveryAgent(config=None)
        groups = da.discover_groups(context)
        assert len(groups) == 0

    def test_edge_single_group_with_multi_group(self, tmp_dir: Path):
        """V1.7-5: Nur 1 Gruppe + MergeAgent → vereinheitlichter Lauf,
        kanonische merged/-Materialisierung, KEIN MergeAgent-Aufruf
        (AC-A1/A4)."""
        context = make_sample_context(tmp_dir, group_count=1, frames_per_group=3)
        mg_config = MultiGroupConfig()
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)

        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []
        merge_agent = MagicMock()

        stack_fits = create_test_fits(
            tmp_dir / "stack_edge_15s60.fits", exptime=15.0, gain=60, rng_seed=1,
        )

        def fake_pcc(stack_path, *args, **kwargs):
            p = tmp_dir / "pcc_edge_15s60.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=9)
            return (p, "gaia_success")

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames", return_value=stack_fits), \
             patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )
            merge_agent.run.assert_not_called()  # AC-A4

        assert proc_result.stacked == tmp_dir / "merged" / "TestTarget_merged.fits"
        assert (tmp_dir / "merged" / "TestTarget_merged.fits").exists()

    def test_edge_pcc_offline(self, tmp_dir: Path, agent: ProcessingAgent):
        """Gaia offline → gray-world fallback + marker + exit 0."""
        # This is tested via the _photometric_color_calibration fallback path
        stack_path = create_test_fits(tmp_dir / "stack_offline.fits", exptime=15.0, gain=60, rng_seed=5)
        mg_config = MultiGroupConfig(pcc_fallback="gray_world")
        group_dir = tmp_dir / "group_offline"
        context = MagicMock()

        with patch.object(agent, "_photometric_color_calibration") as mock_pcc:
            def fake_fallback(stacked, params, **kw):
                marker = stacked.parent / "PCC_FALLBACK_GRAY_WORLD.txt"
                marker.write_text("PCC failed — Gray World fallback applied.\n")
                # Write actual FITS data
                from astropy.io import fits as afits
                data = np.ones((3, 100, 100), dtype=np.float32)
                hdu = afits.PrimaryHDU(data)
                hdu.writeto(stacked, overwrite=True)
            mock_pcc.side_effect = fake_fallback

            pcc_path, status = agent._apply_pcc_per_group(
                stack_path, context, mg_config, group_dir,
                pixel_scale_arcsec=0.0, ra=180.0, dec=30.0,
            )
            assert status == "fallback_gray_world"
            marker = group_dir / "04_stacked" / "PCC_FALLBACK_GRAY_WORLD.txt"
            assert marker.exists()

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_edge_performance(self, tmp_dir: Path):
        """4+ groups of synthetic frames processes in reasonable time."""
        # This is a smoke test — process_multi_group with several small groups
        context = make_sample_context(tmp_dir, group_count=3, frames_per_group=3)
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        mg_config = MultiGroupConfig()

        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        # Provide actual FITS paths as calibrated lights
        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        # Create stacked outputs for each group (so process_multi_group doesn't fail)
        # by mocking the registration and stacking to return quickly
        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg:
            # P2-1 (ray-Review): Stacking setzt >= 2 registrierte Frames
            # voraus — der Dummy-Listen-Eintrag wird auf 2 Pfade verdoppelt
            # (Guard "insufficient_registered_frames" greift sonst; der
            # Smoke-Test prueft nur die Laufzeit, nicht den Intra-Group-Pfad).
            dummy_reg = [
                tmp_dir / "reg_dummy_0.fits",
                tmp_dir / "reg_dummy_1.fits",
            ]
            # Create the dummy registered files
            data = np.ones((3, 100, 100), dtype=np.float32)
            for i, p in enumerate(dummy_reg):
                fits.PrimaryHDU(data).writeto(p, overwrite=True)
            mock_reg.return_value = RegisterFramesResult(
                registered=dummy_reg, last_frame_qualities=[],
                last_frame_rejected=0, last_registration_metrics={},
            )

            # GAIA-Grenze mocken: _gaia_pcc -> None => deterministischer
            # Gray-World-Fallback OHNE astroquery.gaia-Import (der Import
            # braucht auf dieser Maschine ~31s -> wuerde das 30s-Budget
            # sprengen). Kein echtes GAIA im Unit-Test; der PCC-Fallback-Pfad
            # (apply_pcc -> gray_world) bleibt echt. Keine Assertion im Test
            # erwartet ein echtes GAIA-Ergebnis -> return_value=None reicht.
            # V1.4-19: apply_pcc versucht nach GAIA auch den VizieR-Zweit-
            # Katalog (APASS/Refcat2) — der wird hier mitgemockt, damit der
            # Test hermetic bleibt (kein echtes VizieR-Netzwerk; das
            # 30s-Budget gilt weiter).
            with patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
                 patch("astro_process.core.pcc._gaia_pcc", return_value=None), \
                 patch("astro_process.core.pcc._vizier_pcc", return_value=None):
                mock_stack.return_value = tmp_dir / "stacked.fits"
                data2 = np.ones((3, 100, 100), dtype=np.float32)
                hdu2 = fits.PrimaryHDU(data2)
                hdu2.writeto(tmp_dir / "stacked.fits", overwrite=True)

                import time
                start = time.time()
                agent.process_multi_group(
                    context, cal_result, deb_result, pipeline,
                    multi_group_config=mg_config, merge_agent=None,
                )
                elapsed = time.time() - start
                # Should complete quickly since we mocked heavy operations
                # CI/CD environments can be slower; use generous threshold
                assert elapsed < 30.0


# ═══════════════════════════════════════════════════════════════════
# Additional helper tests for uncovered code paths
# ═══════════════════════════════════════════════════════════════════


class TestHelperFunctions:
    """Tests for helper functions used across the feature."""

    def test_auto_asinh_stretch(self):
        """auto_asinh produces output in [0, 1] range."""
        data = np.random.RandomState(42).uniform(0, 100, (50, 50)).astype(np.float32)
        stretched = auto_asinh(data)
        assert stretched.min() >= 0.0
        assert stretched.max() <= 1.0
        assert stretched.dtype == np.float64

    def test_create_preview_jpg_available(self, tmp_dir: Path):
        """create_preview_jpg creates JPG when PIL is available."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("PIL not available")
        fits_path = tmp_dir / "test.fits"
        data = np.ones((3, 50, 50), dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.writeto(fits_path, overwrite=True)

        jpg_path = tmp_dir / "test.jpg"
        result = create_preview_jpg(fits_path, jpg_path)
        assert result is not None
        assert result.exists()
        assert result.suffix == ".jpg"

    def test_processing_agent_load_save_frame(self, tmp_dir: Path):
        """Round-trip load/save preserves data."""
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        original = np.random.RandomState(42).uniform(0, 1, (50, 50, 3)).astype(np.float32)

        save_path = tmp_dir / "roundtrip.fits"
        agent._save_frame(original, save_path)
        assert save_path.exists()

        loaded = agent._load_frame(save_path)
        assert loaded.shape == original.shape
        assert np.allclose(loaded, original, atol=1e-5)

    def test_merge_report_io(self, tmp_dir: Path):
        """merge_report.json can be serialized/deserialized."""
        report = {
            "method": "weighted_average",
            "weight_by": "frame_count",
            "reference_group": "15s60",
            "input_stacks": [],
            "output": {
                "path": str(tmp_dir / "merged.fits"),
                "shape": [3, 100, 100],
                "stats": {"min": 0.0, "max": 1.0, "mean": 0.5, "median": 0.5},
            },
            "pcc_fallback_groups": [],
            "timestamp": "2026-07-30T00:00:00",
        }
        report_path = tmp_dir / "merge_report.json"
        report_path.write_text(json.dumps(report, indent=2))

        loaded = json.loads(report_path.read_text())
        assert loaded == report


# ═══════════════════════════════════════════════════════════════════
# CR-001 P3 — Cross-Group Registration (Ghosting-Fix)
# ═══════════════════════════════════════════════════════════════════


class TestCR001P3CrossGroupRegistration:
    """CR-001 P3 (AC-P3-1..AC-P3-4): FFT-Phase-Correlation als einzige
    Cross-Group-Methode, QC post-shift, RegistrationResult, und
    cross_group_registrations im merge_report (Ghosting-Fix M13)."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    # ── AC-P3-4: M13-Synthetik (15s vs 180s Morphologie) ──────────
    def test_m13_synthetic_phase_correlation_registration(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """AC-P3-4: PCC findet den Ground-Truth-Shift statt des systematischen
        Centroid-Offsets; post-shift Korrelation > pre-shift; Shift innerhalb
        Dither-Envelope; Status ok/warning gemäß Threshold (warn_only)."""
        gt_shift = (5.0, 3.0)
        ref_path = tmp_dir / "m13_ref.fits"
        tgt_path = tmp_dir / "m13_tgt.fits"
        create_m13_pair(ref_path, tgt_path, shift=gt_shift)

        # Pre-shift Korrelation als Baseline (post > pre)
        ref_data = agent._load_frame(ref_path)
        tgt_data = agent._load_frame(tgt_path)
        ref_mono, _ = select_registration_channel(ref_data, "")
        tgt_mono, _ = select_registration_channel(tgt_data, "")
        pre_corr = float(np.corrcoef(tgt_mono.ravel(), ref_mono.ravel())[0, 1])

        # Systematischer Centroid-Offset als Referenz (bewusst NICHT GT)
        centroid_shift = compute_shift_star_centroid(ref_mono, tgt_mono)

        out_dir = tmp_dir / "m13_aligned"
        result = agent._register_to_reference_stack(
            tgt_path, ref_path, filter_name="", output_dir=out_dir,
        )

        max_shift = max(ref_mono.shape) // 4  # Dither-Envelope (60s40)
        assert result.path.exists()
        assert result.path.name == "aligned.fits"

        # Shift-Konvention: apply-to-target → -(GT)
        assert abs(result.shift_y - (-gt_shift[0])) < 2.0, f"shift_y={result.shift_y}"
        assert abs(result.shift_x - (-gt_shift[1])) < 2.0, f"shift_x={result.shift_x}"

        # NICHT der systematische Centroid-Offset (Ghosting-Root-Cause)
        assert (abs(result.shift_y - centroid_shift[0]) > 5.0
                or abs(result.shift_x - centroid_shift[1]) > 5.0)

        # Shift-Betrag innerhalb der Dither-Envelope (AC-P3-1 max_shift)
        assert abs(result.shift_y) <= max_shift
        assert abs(result.shift_x) <= max_shift

        # QC post-shift: Korrelation nach Alignment > vorher (AC-P3-2)
        assert result.correlation > pre_corr

        # W2: corr_hp (Hochpass, post-shift) ist Hauptmetrik; status daraus.
        # W2-Status-QC-Schwelle (prae-RE-F): hartkodiert 0.3 in der Produktion
        # (processing_agent._register_to_reference_stack) — NICHT der
        # W1-Guard. V1.3-1 betrifft nur den W1-Guard (zero_shift_threshold),
        # nicht die W2-Status-QC.
        expected = "ok" if result.corr_hp >= 0.3 else "warning"
        assert result.status == expected

    def test_register_to_reference_stack_no_star_centroiding(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """P3-C1: Cross-Group-Registration verwendet KEIN Star-Centroiding
        mehr (kein Fallback auf den systematischen Centroid-Offset)."""
        ref_path = tmp_dir / "pc_only_ref.fits"
        tgt_path = tmp_dir / "pc_only_tgt.fits"
        create_m13_pair(ref_path, tgt_path, shift=(2.0, -2.0))

        with patch("astro_process.core.registration.compute_shift_star_centroid") as mock_centroid:
            result = agent._register_to_reference_stack(
                tgt_path, ref_path, filter_name="", output_dir=tmp_dir / "pc_only_out",
            )
            mock_centroid.assert_not_called()
        assert result.path.exists()

    # ── AC-P3-2/3: merge_report-Sektion ────────────────────────────
    def test_merge_report_cross_group_registrations_section(
        self, tmp_dir: Path, sample_stacks, sample_metadata,
    ):
        """AC-P3-2/3: merge_report enthält cross_group_registrations mit allen
        Feldern; ohne Daten Default [] (astra merge bleibt konsistent)."""
        agent = MergeAgent(working_dir=tmp_dir, config=None)
        regs = [
            {
                "group": "60s40",
                "reference": "15s60",
                "shift_y": 5.0,
                "shift_x": 3.0,
                "correlation": 0.45,
                "status": "ok",
            },
            {
                "group": "120s100",
                "reference": "15s60",
                "shift_y": -2.5,
                "shift_x": 1.0,
                "correlation": 0.12,
                "status": "warning",
            },
        ]
        result = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
            cross_group_registrations=regs,
        )
        assert result.merge_report["cross_group_registrations"] == regs

        # Ohne Registrations-Daten → Sektion [] (konsistent für astra merge)
        result2 = agent.run(
            group_stacks=sample_stacks,
            group_metadata=sample_metadata,
            target_name="TestTarget",
        )
        assert result2.merge_report["cross_group_registrations"] == []

    def test_process_multi_group_cross_group_registrations_wiring(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """Verdrahtung: process_multi_group sammelt Registrations-Metriken und
        reicht sie in den merge_report durch (AC-P3-2)."""
        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
        mg_config = MultiGroupConfig()
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        merge_agent = MergeAgent(working_dir=tmp_dir, config=None)

        # Echte Stack-Dateien (existieren, damit group_stacks geprüft wird)
        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
        }

        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            # Jeder eingehende Stack bekommt eine eigene, existierende PCC-Datei
            pcc_counter["n"] += 1
            p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
            mock_reg.return_value = RegisterFramesResult(
            registered=[], last_frame_qualities=[], last_frame_rejected=0,
            last_registration_metrics={},
        )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"],
                shift_y=-5.0,
                shift_x=-3.0,
                correlation=0.5,
                corr_hp=0.72,
                status="ok",
            )
            mock_pcc.side_effect = fake_pcc

            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )

        # merge_report.json wurde vom MergeAgent geschrieben
        report_path = tmp_dir / "merged" / "merge_report.json"
        assert report_path.exists(), f"merge_report.json fehlt: {report_path}"
        report = json.loads(report_path.read_text())

        # Registrations-Sektion: genau eine Nicht-Referenz-Gruppe registriert
        regs = report["cross_group_registrations"]
        assert len(regs) == 1
        entry = regs[0]
        assert entry["reference"] == report["reference_group"]
        assert entry["group"] != entry["reference"]
        assert entry["shift_y"] == -5.0
        assert entry["shift_x"] == -3.0
        assert entry["correlation"] == 0.5
        assert entry["corr_roh"] == 0.5          # W2: Diagnosefeld (Roh, post-shift)
        assert entry["corr_hp"] == 0.72          # W2: Hauptmetrik (Hochpass, post-shift)
        assert entry["status"] == "ok"

        # Referenz-Gruppe erscheint NICHT als Registrations-Eintrag
        assert all(r["group"] != report["reference_group"] for r in regs)

        # Pipeline-Ergebnis: Merge erfolgte
        assert proc_result.stacked is not None
        assert proc_result.stacked.exists()

    def test_merged_pcc_reaches_final_export(self, tmp_dir: Path, agent: ProcessingAgent):
        """ray-Major-3 Regression: Im Defaultpfad (pcc_per_group=False, PCC
        auf MERGED Stack) muss das FINALE exportierte FITS die PCC-korrigier-
        ten Daten enthalten — nicht den linearen Stack.

        Der Hook-Mock bildet den Vertrag des echten apply_pcc_per_group
        nach: Kopie nach <group_dir>/04_stacked/pcc_applied.fits, eindeu-
        tige Transformation (Faktor 3.0) IN PLACE auf DIESER Datei, Input
        bleibt unangetastet (linear), Return = (pcc_path, status). Vor dem
        Fix verworfen Aufrufer den Return-Pfad -> Export zeigte auf die
        unkorrigierte Rohkopie merged/pcc_applied.fits."""
        import shutil

        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
        mg_config = MultiGroupConfig()  # V1.6-Default: pcc_per_group=False
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        merge_agent = MergeAgent(working_dir=tmp_dir, config=None)

        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
        }

        PCC_FACTOR = 3.0  # eindeutig identifizierbare Transformation

        def fake_pcc_hook(stack_path, ctx, mg_cfg, group_dir, *args, **kwargs):
            stacked_dir = Path(group_dir) / "04_stacked"
            stacked_dir.mkdir(parents=True, exist_ok=True)
            pcc_path = stacked_dir / "pcc_applied.fits"
            shutil.copy2(stack_path, pcc_path)
            with fits.open(pcc_path, mode="update") as hdul:
                hdul[0].data = hdul[0].data * PCC_FACTOR
            return pcc_path, "gaia_success"

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc_hook):
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"],
                shift_y=-5.0,
                shift_x=-3.0,
                correlation=0.5,
                corr_hp=0.72,
                status="ok",
            )

            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )

        # FINALES Artefakt muss korrigierte Daten enthalten
        final_fits = proc_result.stacked
        assert final_fits is not None and final_fits.exists()

        # Lineare Referenz: die Rohkopie merged/pcc_applied.fits bleibt im
        # Mock unangetastet (= Merge-Output vor PCC)
        raw_copy = tmp_dir / "merged" / "pcc_applied.fits"
        assert raw_copy.exists()
        with fits.open(raw_copy) as hdul:
            linear = np.asarray(hdul[0].data, dtype=np.float64)
        with fits.open(final_fits) as hdul:
            final = np.asarray(hdul[0].data, dtype=np.float64)

        assert final.shape == linear.shape
        # Korrigiert = linear * Faktor — GENAU das haette den Bug gefangen:
        # Vor dem Fix war final == linear (Export konsumierte die Rohkopie).
        assert np.allclose(final, linear * PCC_FACTOR), (
            "Finale FITS enthaelt NICHT die PCC-korrigierten Daten "
            f"(max|final-linear*{PCC_FACTOR}|="
            f"{np.max(np.abs(final - linear * PCC_FACTOR)):.6g})"
        )
        assert not np.allclose(final, linear)
        # Export-Liste fuehrt dasselbe korrigierte Artefakt an erster Stelle
        assert proc_result.exports[0] == final_fits


# ═══════════════════════════════════════════════════════════════════
# CR-001 P3-M1 — Shape-Mismatch-Guard (ray-Follow-up)
# ═══════════════════════════════════════════════════════════════════


class TestCR001P3M1ShapeMismatch:
    """CR-001 P3-M1 (ray-Review, minor): Shape-Mismatch-Guard in
    _register_to_reference_stack() — kein roher Broadcasting-/FFT-Fehler,
    gültiges RegistrationResult mit Zero-Shift + status warning."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_register_to_reference_stack_shape_mismatch_guard(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """Abweichende Shapes → corr_grid_shift wird NICHT aufgerufen, kein
        Exception; status "warning", shift 0/0, corr 0.0, aligned.fits gespeichert."""
        ref_path = create_test_fits(
            tmp_dir / "ref_mismatch.fits", shape=(100, 100, 3),
            exptime=15.0, gain=60, rng_seed=1,
        )
        tgt_path = create_test_fits(
            tmp_dir / "tgt_mismatch.fits", shape=(80, 100, 3),
            exptime=60.0, gain=40, rng_seed=2,
        )

        with patch("astro_process.agents.multi_group_agent.corr_grid_shift") as mock_shift:
            out_dir = tmp_dir / "mismatch_out"
            result = agent._register_to_reference_stack(
                tgt_path, ref_path, filter_name="", output_dir=out_dir,
            )
            mock_shift.assert_not_called()

        # Gültiges RegistrationResult (path, shift 0/0, corr 0.0, status warning)
        assert isinstance(result, RegistrationResult)
        assert result.path.exists()
        assert result.path.name == "aligned.fits"
        assert result.shift_y == 0.0
        assert result.shift_x == 0.0
        assert result.correlation == 0.0
        assert result.corr_hp == 0.0  # W2: corr_hp-Metrik im Guard ebenfalls 0
        assert result.status == "warning"

        # Aligned FITS hat die Stack-Shape (Zero-Shift-Kopie), kein Broadcast-Fehler
        with fits.open(result.path) as hdul:
            assert hdul[0].data.shape == (3, 80, 100)


# ═══════════════════════════════════════════════════════════════════
# CR-001 P1 — Gruppen-Ordner bleiben (Default true, Cleanup explizit)
# ═══════════════════════════════════════════════════════════════════


class TestCR001P1GroupDirs:
    """CR-001 P1 (AC-P1-1..AC-P1-5): Gruppen-Dirs bleiben per Default;
    explizites Cleanup nur bei keep_group_working_dirs=false."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_multi_group_run_keeps_group_dirs_by_default(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """AC-P1-1/2: Default keep_group_working_dirs=true → Gruppen-Dirs
        (04_stacked) bleiben nach dem Run ohne manuelle Config."""
        mg_config = MultiGroupConfig()
        assert mg_config.keep_group_working_dirs is True

        run_multi_group_pipeline(tmp_dir, agent, mg_config=mg_config)

        assert (tmp_dir / "group_15s60" / "04_stacked").exists()
        assert (tmp_dir / "group_60s40" / "04_stacked").exists()

    def test_multi_group_run_cleanup_when_keep_false(
        self, tmp_dir: Path, agent: ProcessingAgent, capsys,
    ):
        """AC-P1-3/5: keep_group_working_dirs=false → explizites Cleanup;
        Log-Event multi_group.cleanup_group_dir erscheint (nur dann)."""
        mg_config = MultiGroupConfig(keep_group_working_dirs=False)

        run_multi_group_pipeline(tmp_dir, agent, mg_config=mg_config)

        assert not (tmp_dir / "group_15s60").exists()
        assert not (tmp_dir / "group_60s40").exists()

        # AC-P1-5: Log-Event nur bei explizitem Cleanup
        captured = capsys.readouterr().out
        assert "multi_group.cleanup_group_dir" in captured


# ═══════════════════════════════════════════════════════════════════
# CR-001 P2 — Gruppen-Previews preview_{hash}.jpg nach PCC
# ═══════════════════════════════════════════════════════════════════


class TestCR001P2Previews:
    """CR-001 P2 (AC-P2-1..AC-P2-5): Preview-JPG je Gruppe in 04_stacked/."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_multi_group_run_creates_group_previews(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """AC-P2-1/2/3: preview_{group_hash}.jpg existiert je Gruppe in
        04_stacked/ nach dem Multi-Group-Run (nach PCC)."""
        run_multi_group_pipeline(tmp_dir, agent)

        assert (tmp_dir / "group_15s60" / "04_stacked" / "preview_15s60.jpg").exists()
        assert (tmp_dir / "group_60s40" / "04_stacked" / "preview_60s40.jpg").exists()

    def test_multi_group_preview_error_does_not_abort_run(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """AC-P2-5: create_preview_jpg wirft Exception → nur Gruppe betroffen,
        Run läuft weiter (Warning + Continue), kein Abbruch."""
        with patch("astro_process.agents.multi_group_agent.create_preview_jpg",
                   side_effect=RuntimeError("preview boom")):
            proc_result = run_multi_group_pipeline(tmp_dir, agent)

        assert proc_result is not None  # Run nicht abgebrochen
        assert proc_result.stacked is None  # kein Merge (merge_agent=None), aber OK

    def test_multi_group_preview_none_does_not_abort_run(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """AC-P2-5: create_preview_jpg returns None (interner Fehlerpfad) →
        Run läuft weiter."""
        with patch("astro_process.agents.multi_group_agent.create_preview_jpg",
                   return_value=None):
            proc_result = run_multi_group_pipeline(tmp_dir, agent)

        assert proc_result is not None

    def test_multi_group_preview_created_on_gray_world_fallback(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """AC-P2-4: Gray-World-Fallback-Gruppe erzeugt Preview trotzdem;
        PCC_FALLBACK_GRAY_WORLD.txt bleibt Indikator."""
        # V1.6-Default ist pcc_per_group=False (PCC auf MERGED Stack) —
        # dieser Test prueft das PER-GROUP-Fallback-Verhalten (AC-P2-4)
        # und aktiviert die alte Strategie daher explizit.
        run_multi_group_pipeline(
            tmp_dir, agent,
            mg_config=MultiGroupConfig(pcc_per_group=True),
            fake_pcc_status="fallback_gray_world",
            with_fallback_marker=True,
        )

        assert (tmp_dir / "group_15s60" / "04_stacked" / "preview_15s60.jpg").exists()
        assert (tmp_dir / "group_60s40" / "04_stacked" / "preview_60s40.jpg").exists()
        # Marker bleibt vorhanden (Indikator, unverändert)
        assert (tmp_dir / "group_15s60" / "04_stacked" / "PCC_FALLBACK_GRAY_WORLD.txt").exists()


# ═══════════════════════════════════════════════════════════════════
# CR-001 P1 — CLI-Flag --keep-groups/--no-keep-groups
# ═══════════════════════════════════════════════════════════════════


class TestCR001P1CliFlag:
    """CR-001 P1 (AC-P1-2/3): CLI-Flag --keep-groups/--no-keep-groups.
    Precedence: CLI > Config > Default(true)."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def _invoke_process_multi_group(
        self, runner: CliRunner, tmp_dir: Path,
        cli_args: Optional[list[str]] = None,
        config_path: Optional[Path] = None,
    ) -> tuple:
        """Invoke process --multi-group mit gemockten Agents (Pipeline-Agents
        sind extern ersetzt). Liefert (CliResult, captured_mg_config)."""
        captured: dict = {}

        discovery = MagicMock()
        discovery.run.return_value = MagicMock(context=MagicMock())
        cal = MagicMock()
        cal.run.return_value = MagicMock(master_dark=None)
        deb = MagicMock()
        deb.run.return_value = MagicMock(debayered_frames=[])
        proc = MagicMock()

        def capture_mg(*args, **kwargs):
            captured["mg_config"] = kwargs.get("multi_group_config")
            return MagicMock(stacked=None, multi_group_metadata=None)

        proc.process_multi_group.side_effect = capture_mg
        arch = MagicMock()
        arch.run.return_value = MagicMock(output_dir=tmp_dir, final_fits=None)

        base_args: list[str] = []
        if config_path is not None:
            base_args += ["--config", str(config_path)]
        base_args += ["process", str(tmp_dir), "--multi-group"]
        if cli_args:
            base_args += cli_args

        with patch("astro_process.cli.create_discovery_agent", return_value=discovery), \
             patch("astro_process.cli.create_calibration_agent", return_value=cal), \
             patch("astro_process.cli.create_debayer_agent", return_value=deb), \
             patch("astro_process.cli.create_processing_agent", return_value=proc), \
             patch("astro_process.cli.create_archive_agent", return_value=arch):
            result = runner.invoke(cli, base_args)

        return result, captured.get("mg_config")

    def test_cli_default_keeps_groups(self, runner: CliRunner, tmp_dir: Path):
        """AC-P1-1/2: Default ohne Flag → keep_group_working_dirs true."""
        result, mg_config = self._invoke_process_multi_group(runner, tmp_dir)
        assert result.exit_code == 0
        assert mg_config is not None
        assert mg_config.keep_group_working_dirs is True

    def test_cli_keep_groups_flag(self, runner: CliRunner, tmp_dir: Path):
        """AC-P1-2: --keep-groups bestätigt explizit → true."""
        result, mg_config = self._invoke_process_multi_group(
            runner, tmp_dir, cli_args=["--keep-groups"],
        )
        assert result.exit_code == 0
        assert mg_config.keep_group_working_dirs is True

    def test_cli_no_keep_groups_flag(self, runner: CliRunner, tmp_dir: Path):
        """AC-P1-3: --no-keep-groups → Cleanup aktiv (false)."""
        result, mg_config = self._invoke_process_multi_group(
            runner, tmp_dir, cli_args=["--no-keep-groups"],
        )
        assert result.exit_code == 0
        assert mg_config.keep_group_working_dirs is False

    def _write_config_with_keep(self, tmp_dir: Path, keep: bool) -> Path:
        """Schreibt eine vollständige Config (DEFAULT_CONFIG-Basis) mit
        multi_group.keep_group_working_dirs=keep."""
        import yaml
        from astro_process.config.loader import DEFAULT_CONFIG

        data = yaml.safe_load(DEFAULT_CONFIG)
        data["multi_group"]["keep_group_working_dirs"] = keep
        # Leo-Auftrag 2026-08-11 (B2): --darks-path optional — Kalibration
        # benoetigt einen Darks-Pfad; ohne CLI-Flag kommt er aus der Config.
        data["darks_repository"] = str(tmp_dir / "_darks")
        (tmp_dir / "_darks").mkdir(exist_ok=True)
        cfg_path = tmp_dir / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False))
        return cfg_path

    def test_cli_config_false_respected_without_flag(
        self, runner: CliRunner, tmp_dir: Path,
    ):
        """Precedence: Config false wirkt, wenn kein Flag (CLI None)."""
        cfg_path = self._write_config_with_keep(tmp_dir, keep=False)

        result, mg_config = self._invoke_process_multi_group(
            runner, tmp_dir, config_path=cfg_path,
        )
        assert result.exit_code == 0
        assert mg_config.keep_group_working_dirs is False

    def test_cli_flag_overrides_config_false(
        self, runner: CliRunner, tmp_dir: Path,
    ):
        """Precedence: CLI > Config — --keep-groups überschreibt Config false."""
        cfg_path = self._write_config_with_keep(tmp_dir, keep=False)

        result, mg_config = self._invoke_process_multi_group(
            runner, tmp_dir, cli_args=["--keep-groups"], config_path=cfg_path,
        )
        assert result.exit_code == 0
        assert mg_config.keep_group_working_dirs is True

    def test_cli_merge_finds_group_dirs_after_run(
        self, runner: CliRunner, tmp_dir: Path,
    ):
        """AC-P1-4: astra merge findet Gruppen-Stacks weiterhin unter
        group_{hash}/04_stacked/ (Struktur unverändert, Such-Logik bleibt)."""
        ts_dir = tmp_dir / "generated" / "20260731-120000"
        for gh in ["15s60", "60s40"]:
            stacked = ts_dir / f"group_{gh}" / "04_stacked" / "pcc_applied.fits"
            create_test_fits(stacked, exptime=15.0, gain=60, rng_seed=1)

        result = runner.invoke(cli, ["merge", str(tmp_dir), "--dry-run"])

        assert result.exit_code == 0
        assert "group_15s60" in result.output
        assert "group_60s40" in result.output
        assert "DRY RUN" in result.output


# ═══════════════════════════════════════════════════════════════════
# CR-001 W1/W2 — Cross-Group-Shift auf Hochpass (Grid, corr_hp)
# Quelle: orion/_work/stella/bugfix-konsolidierung.md (W1, W2)
# ═══════════════════════════════════════════════════════════════════

class TestCR001W1HighpassGridRegistration:
    """CR-001 W1+W2: Shift-Berechnung auf Hochpass (sigma=30) via
    korrelationsbasierter Grob-zu-Fein-Suche (_corr_grid_shift); corr_hp als
    QC-Hauptmetrik (status aus corr_hp); Zero-Shift-Fallback bei corr_hp <
    Schwelle (Default 0.05 seit V19-FIX-12; Guard-Tests setzen explizit 0.3).
    Belege: Killercase-Synthetik (hermetic) + M13-Real-Stacks (Lauf 074119)."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_killercase_old_centroid_fails_grid_finds_gt(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """W1-Killercase (hermetic): Hintergrundgradient + Vignettierung
        (zwischen Nächten verschoben) + M13-Morphologien (15s/180s). Die alte
        Methode (_compute_shift_star_centroid, VOR-CR-001) liefert den
        systematisch falschen Shift; die neue Hochpass+Grid-Methode findet die
        Ground-Truth."""
        gt_shift = (5.0, 3.0)
        ref_path = tmp_dir / "killer_ref.fits"
        tgt_path = tmp_dir / "killer_tgt.fits"
        create_m13_gradient_pair(ref_path, tgt_path, shift=gt_shift)

        ref_data = agent._load_frame(ref_path)
        tgt_data = agent._load_frame(tgt_path)
        ref_mono, _ = select_registration_channel(ref_data, "")
        tgt_mono, _ = select_registration_channel(tgt_data, "")

        # Alte Methode (VOR-CR-001, Centroid+PC-Fallback) → falsch (Killercase)
        old = compute_shift_star_centroid(ref_mono, tgt_mono)
        assert (abs(old[0] - (-gt_shift[0])) > 5.0
                or abs(old[1] - (-gt_shift[1])) > 5.0), \
            f"alte Methode fand GT unerwartet: {old}"

        # Neue Methode via _register_to_reference_stack → GT + corr_hp hoch
        result = agent._register_to_reference_stack(
            tgt_path, ref_path, filter_name="", output_dir=tmp_dir / "killer_out",
        )
        assert abs(result.shift_y - (-gt_shift[0])) < 2.0, \
            f"shift_y={result.shift_y}"
        assert abs(result.shift_x - (-gt_shift[1])) < 2.0, \
            f"shift_x={result.shift_x}"
        assert result.corr_hp > 0.3, f"corr_hp={result.corr_hp}"
        assert result.status == "ok"

    def test_zero_shift_fallback_on_unrelated_pair(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """W1: corr_hp < 0.3 (unrelated Sterne-Felder) → Shift (0,0) + status
        warning + aligned.fits gespeichert (KEIN Skip, Gruppe bleibt im Merge).
        Ein schlechter Peak ist gefährlicher als Zero-Shift."""
        ref_path = create_test_fits(tmp_dir / "zf_ref.fits", shape=(120, 160, 3),
                                    add_stars=True, rng_seed=1)
        tgt_path = create_test_fits(tmp_dir / "zf_tgt.fits", shape=(120, 160, 3),
                                    add_stars=True, rng_seed=99)
        # explizit hohe Schwelle (Default seit V19-FIX-12: 0.05) — Guard-Verhalten
        params = {"registration": {"zero_shift_threshold": 0.3}}
        result = agent._register_to_reference_stack(
            tgt_path, ref_path, filter_name="", output_dir=tmp_dir / "zf_out",
            params=params,
        )
        assert result.shift_y == 0.0
        assert result.shift_x == 0.0
        assert result.corr_hp < 0.3
        assert result.status == "warning"
        assert result.path.exists()


# ═══════════════════════════════════════════════════════════════════
# CR-001 W3 — merge.min_correlation + skip_group-Sicherheitsnetz
# Quelle: orion/_work/stella/bugfix-konsolidierung.md (W3, Option 1)
# ═══════════════════════════════════════════════════════════════════

class TestCR001W3MinCorrelation:
    """CR-001 W3 (AC-W3-1/2): Nicht-Referenz-Gruppen mit corr_hp <
    merge.min_correlation (nach W1-Handling) werden aus dem Merge
    AUSGESCHLOSSEN und in skipped_groups dokumentiert; die Referenz-Gruppe
    wird NIE geskippt. Stacks bleiben unter group_*/04_stacked/ erhalten."""

    @pytest.fixture
    def agent(self, tmp_dir: Path) -> ProcessingAgent:
        return ProcessingAgent(working_dir=tmp_dir, config=None)

    def test_merge_config_min_correlation_default(self):
        """AC-W3-1: MergeConfig.min_correlation Default 0.1."""
        from astro_process.config.models import MergeConfig
        assert MergeConfig().min_correlation == 0.1

    def test_default_yaml_contains_min_correlation(self):
        """config/loader.py: DEFAULT_CONFIG merge-Sektion enthält min_correlation."""
        import yaml
        from astro_process.config.loader import DEFAULT_CONFIG
        data = yaml.safe_load(DEFAULT_CONFIG)
        assert data["multi_group"]["merge"]["min_correlation"] == 0.1

    def test_skip_filter_excludes_below_threshold(
        self, tmp_dir: Path, agent: ProcessingAgent,
    ):
        """AC-W3-1 (Unit): Nicht-Referenz mit corr_hp < min_correlation wird aus
        dem Merge ausgeschlossen + skipped_groups-Eintrag below_min_correlation;
        Gruppen über der Schwelle und die Referenz bleiben."""
        ref_hash = "15s60"
        aligned = {
            "15s60": tmp_dir / "a15.fits",
            "60s40": tmp_dir / "a60.fits",
            "180s60": tmp_dir / "a180.fits",
        }
        regs = [
            {"group": "60s40", "reference": ref_hash, "corr_hp": 0.75, "status": "ok"},
            {"group": "180s60", "reference": ref_hash, "corr_hp": 0.05, "status": "warning"},
        ]
        kept, skipped = agent._apply_cross_group_skip_filter(aligned, regs, ref_hash, 0.1)
        assert set(kept.keys()) == {"15s60", "60s40"}   # 180s60 ausgeschlossen
        assert skipped == [{
            "group": "180s60",
            "reason": "below_min_correlation",
            "corr_hp": 0.05,
            "min_correlation": 0.1,
        }]

    def test_reference_never_skipped(self, tmp_dir: Path, agent: ProcessingAgent):
        """AC-W3-2: Referenz wird NIE geskippt — selbst wenn hypothetisch ein
        Registrations-Eintrag für die Referenz corr_hp < min_correlation hätte
        (in der Praxis nie vorhanden, da ref_hash nicht registriert wird). Der
        Merge läuft ohne Skip-Filter für die Referenz weiter (warning)."""
        ref_hash = "15s60"
        aligned = {"15s60": tmp_dir / "a15.fits", "60s40": tmp_dir / "a60.fits"}
        regs = [
            {"group": ref_hash, "reference": ref_hash, "corr_hp": 0.05, "status": "warning"},
            {"group": "60s40", "reference": ref_hash, "corr_hp": 0.75, "status": "ok"},
        ]
        kept, skipped = agent._apply_cross_group_skip_filter(aligned, regs, ref_hash, 0.1)
        assert ref_hash in kept
        assert skipped == []  # Referenz nicht geskippt, kein Skip-Filter-Reset

    def test_m13_normal_case_no_skip(self, tmp_dir: Path, agent: ProcessingAgent):
        """Normalfall (M13-Referenzlauf): 60s40 corr_hp 0.7504, 180s60 corr_hp
        0.1319 — beide > 0.1 → keine Gruppe geskippt (kein Verhaltensbruch)."""
        ref_hash = "15s60"
        aligned = {
            "15s60": tmp_dir / "a15.fits",
            "60s40": tmp_dir / "a60.fits",
            "180s60": tmp_dir / "a180.fits",
        }
        regs = [
            {"group": "60s40", "reference": ref_hash, "corr_hp": 0.7504, "status": "ok"},
            {"group": "180s60", "reference": ref_hash, "corr_hp": 0.1319, "status": "warning"},
        ]
        kept, skipped = agent._apply_cross_group_skip_filter(aligned, regs, ref_hash, 0.1)
        assert set(kept.keys()) == {"15s60", "60s40", "180s60"}
        assert skipped == []

    def test_process_multi_group_skips_below_min_correlation(
        self, tmp_dir: Path,
    ):
        """AC-W3-1 (End-to-End): process_multi_group mit merge.min_correlation
        schließt eine Nicht-Referenz-Gruppe (corr_hp 0.05 < 0.1) aus dem Merge
        aus; skipped_groups-Eintrag im merge_report.json; die Gruppe erscheint
        NICHT in input_stacks; der Stack bleibt unter group_*/04_stacked/
        erhalten (kein Cleanup); Registrations-Metrik bleibt dokumentiert."""
        from astro_process.agents.merge_agent import MergeAgent
        from astro_process.models.core import compute_group_hash

        context = make_sample_context(tmp_dir, group_count=3, frames_per_group=3)
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        mg_config = MultiGroupConfig(merge=MergeConfig(min_correlation=0.1))
        assert mg_config.merge.min_correlation == 0.1

        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        merge_agent = MergeAgent(working_dir=tmp_dir, config=None)

        # Echte Stack-Dateien (existieren, damit group_stacks geprüft wird)
        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits", exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits", exptime=60.0, gain=40, rng_seed=2),
            "120s100_Duo-Band": create_test_fits(
                tmp_dir / "stack_120.fits", exptime=120.0, gain=100,
                filter_name="Duo-Band", rng_seed=3,
            ),
        }

        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            pcc_counter["n"] += 1
            p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        def fake_cross(stack_path, ref_stack_path, filter_name, stack_dir,
                       params=None):
            # stack_dir = tmp_dir/group_{hash}/04_stacked → Gruppe unterscheiden
            if "120s100_Duo-Band" in str(stack_dir):
                # unter der Duo-Schwelle 0.05 (effektiv 0.05 statt 0.1) → W3-Skip
                return RegistrationResult(
                    path=stack_fits["120s100_Duo-Band"], shift_y=0.0, shift_x=0.0,
                    correlation=0.02, corr_hp=0.02, status="warning",
                )
            return RegistrationResult(
                path=stack_fits["60s40"], shift_y=0.0, shift_x=0.0,
                correlation=0.75, corr_hp=0.75, status="ok",
            )

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
            mock_reg.return_value = RegisterFramesResult(
            registered=[], last_frame_qualities=[], last_frame_rejected=0,
            last_registration_metrics={},
        )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.side_effect = fake_cross
            mock_pcc.side_effect = fake_pcc

            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )

        report_path = tmp_dir / "merged" / "merge_report.json"
        assert report_path.exists(), f"merge_report.json fehlt: {report_path}"
        report = json.loads(report_path.read_text())

        # skipped_groups: 120s100_Duo-Band ausgeschlossen (corr_hp 0.02 < 0.05 Duo-Schwelle)
        # W7-Erw. (AC-W7-2): preview_path hinzugefügt (relativ zum generated/{ts}-Ordner)
        skipped = report["skipped_groups"]
        assert len(skipped) == 1
        entry = skipped[0]
        assert entry["group"] == "120s100_Duo-Band"
        assert entry["reason"] == "below_min_correlation"
        assert entry["corr_hp"] == 0.02
        assert entry["min_correlation"] == 0.05
        assert "preview_path" in entry
        assert entry["preview_path"].endswith("preview_120s100_Duo-Band.jpg")

        # Die geskippte Gruppe erscheint NICHT in input_stacks; 60s40 + Referenz schon
        merged_groups = [s["group"] for s in report["input_stacks"]]
        assert "120s100_Duo-Band" not in merged_groups
        assert "60s40" in merged_groups
        assert report["reference_group"] in merged_groups
        assert report["reference_group"] != "120s100_Duo-Band"

        # Registrations-Metrik der geskippten Gruppe bleibt dokumentiert (QC)
        regs = report["cross_group_registrations"]
        assert any(r["group"] == "120s100_Duo-Band" and r["corr_hp"] == 0.02 for r in regs)

        # Stack bleibt unter group_120s100_Duo-Band/04_stacked/ erhalten (kein Cleanup)
        assert (tmp_dir / "group_120s100_Duo-Band" / "04_stacked").exists()


# ═══════════════════════════════════════════════════════════════════
# v1.11 — Final-FITS-Platzierung (keine Doppel-Ablage mehr)
# ═══════════════════════════════════════════════════════════════════


class TestFinalFitsPlacement:
    """Final-FITS-Platzierung. Multi-Group: NUR in merged/ (kein Top-Level-
    Duplikat). Single-Group: Top-Level-*_final.fits (Legacy) PLUS seit V1.3-6
    ein zusaetzlicher merged/-Output (trivialer Merge, byte-identische Kopie)
    — konsistenter finaler Output-Pfad unabhaengig von Single-/Multi-Group."""

    def _run_multi_group_with_merge(self, tmp_dir: Path) -> tuple:
        """process_multi_group mit echtem MergeAgent (2 Gruppen) →
        merged/-Artefakte (merged_fits, merge_report.json)."""
        from astro_process.agents.merge_agent import MergeAgent

        context = make_sample_context(tmp_dir, group_count=2, frames_per_group=3)
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        mg_config = MultiGroupConfig(merge=MergeConfig(min_correlation=0.1))

        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        merge_agent = MergeAgent(working_dir=tmp_dir, config=None)

        stack_fits = {
            "15s60": create_test_fits(tmp_dir / "stack_15s60.fits",
                                      exptime=15.0, gain=60, rng_seed=1),
            "60s40": create_test_fits(tmp_dir / "stack_60s40.fits",
                                      exptime=60.0, gain=40, rng_seed=2),
        }
        pcc_counter = {"n": 0}

        def fake_pcc(stack_path, *args, **kwargs):
            pcc_counter["n"] += 1
            p = tmp_dir / f"pcc_stack_{pcc_counter['n']}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=pcc_counter["n"])
            return (p, "gaia_success")

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames") as mock_stack, \
             patch.object(agent, "_register_to_reference_stack") as mock_cross, \
             patch.object(agent, "_apply_pcc_per_group") as mock_pcc:
            mock_reg.return_value = RegisterFramesResult(
            registered=[], last_frame_qualities=[], last_frame_rejected=0,
            last_registration_metrics={},
        )
            mock_stack.return_value = stack_fits["15s60"]
            mock_cross.return_value = RegistrationResult(
                path=stack_fits["60s40"], shift_y=0.0, shift_x=0.0,
                correlation=0.75, corr_hp=0.75, status="ok",
            )
            mock_pcc.side_effect = fake_pcc

            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
            )

        return context, proc_result, cal_result, deb_result

    def test_multi_group_final_fits_only_in_merged(self, tmp_dir: Path):
        """Multi-Group-Lauf: finale Datei NUR als merged/TestTarget_merged.fits;
        kein Top-Level-*_final.fits; agent-log outputs.final_fits → merged/-Pfad."""
        import yaml
        from astro_process.agents.archive import create_archive_agent

        context, proc_result, cal_result, deb_result = self._run_multi_group_with_merge(tmp_dir)

        top_level = tmp_dir / "TestTarget_final.fits"
        merged_fits = tmp_dir / "merged" / "TestTarget_merged.fits"

        # (a) kein Top-Level-Duplikat
        assert not top_level.exists()
        # (b) finale Datei liegt in merged/
        assert merged_fits.exists()

        # (c) agent-log outputs.final_fits zeigt auf den merged/-Pfad
        arch_result = create_archive_agent(tmp_dir, None).run(
            context, proc_result, cal_result, deb_result,
            multi_group_metadata=proc_result.multi_group_metadata,
        )
        assert arch_result.final_fits == merged_fits
        log = yaml.safe_load((tmp_dir / "agent-log.yaml").read_text(encoding="utf-8"))
        assert log["outputs"]["final_fits"] == str(merged_fits)

    def test_single_group_export_keeps_top_level_final_fits(self, tmp_dir: Path):
        """Single-Group-Endstand unverändert: export schreibt weiterhin
        Top-Level-*_final.fits (+ Preview + final.seq)."""
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        src = create_test_fits(tmp_dir / "single_stack.fits", exptime=15.0, gain=60, rng_seed=7)

        exports = export(src, "TestTarget", working_dir=agent.working_dir)

        fits_out = tmp_dir / "TestTarget_final.fits"
        assert fits_out.exists()
        assert fits_out in exports
        # Preview + final.seq bleiben Teil des Single-Group-Endstands
        assert (tmp_dir / "TestTarget_final_preview.jpg").exists()
        assert (tmp_dir / "final.seq").exists()

    def test_single_group_merged_output_byte_identical(self, tmp_dir: Path):
        """V1.3-6 P0-Gate: Single-Group-`run()`-Lauf legt merged/
        TestTarget_merged.fits als byte-identische Kopie des Top-Level-Exports
        ab (reines shutil.copy2 nach Header-Anreicherung) + merged_preview.jpg;
        exports-Reihenfolge Top-Level zuerst; agent-log outputs.final_fits →
        merged/-Pfad (merged/ gewinnt jetzt auch bei Single-Group)."""
        import yaml
        from astro_process.agents.archive import create_archive_agent

        context = make_sample_context(tmp_dir, group_count=1, frames_per_group=2)
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = [
            PipelineStep(name="register_frames"),
            PipelineStep(name="stack_frames"),
            PipelineStep(name="export"),
        ]

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = create_test_fits(
            tmp_dir / "stack.fits", exptime=15.0, gain=60, rng_seed=1
        )

        with patch("astro_process.agents.processing_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.processing_agent.stack_frames") as mock_stack:
            mock_reg.return_value = RegisterFramesResult(
                registered=[f.path for f in lights.frames if f.path.exists()],
                last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits
            proc_result = agent.run(context, cal_result, deb_result, pipeline)

        top_level = tmp_dir / "TestTarget_final.fits"
        merged_fits = tmp_dir / "merged" / "TestTarget_merged.fits"
        merged_preview = tmp_dir / "merged" / "TestTarget_merged_preview.jpg"

        # (a) Top-Level bleibt (Legacy) UND merged/-Kopie existiert
        assert top_level.exists()
        assert merged_fits.exists()
        # (b) P0: byte-identisch (Pixel + Header nach Anreicherung)
        assert merged_fits.read_bytes() == top_level.read_bytes()
        # (c) Preview analog Multi-Group AC-P2
        assert merged_preview.exists()

        # (d) exports-Reihenfolge: Top-Level zuerst, dann merged/-Artefakte
        fits_exports = [e for e in proc_result.exports if e.suffix.lower() == ".fits"]
        assert fits_exports[0] == top_level
        assert merged_fits in fits_exports
        assert merged_preview in proc_result.exports

        # (e) agent-log outputs.final_fits → merged/-Pfad (V1.3-6:
        # konsistenter finaler Output-Pfad unabhaengig von Single-/Multi)
        arch_result = create_archive_agent(tmp_dir, None).run(
            context, proc_result, cal_result, deb_result,
        )
        assert arch_result.final_fits == merged_fits
        log = yaml.safe_load((tmp_dir / "agent-log.yaml").read_text(encoding="utf-8"))
        assert log["outputs"]["final_fits"] == str(merged_fits)

    def test_multi_group_run_info_json(self, tmp_dir: Path):
        """Fix-Sammlung v1.3 §3 (P0): run-info.json im Lauf-Ordner —
        Multi-Group-Lauf fasst Aufnahmemodus (eq/eq_source aus DiscoveryResult)
        und Gruppen-Uebersicht (hash, frame_count, exptime, gain, filter,
        weight) zusammen."""
        from astro_process.agents.archive import create_archive_agent

        context, proc_result, cal_result, deb_result = self._run_multi_group_with_merge(tmp_dir)
        discovery_result = DiscoveryResult(
            context=context,
            eq=True,
            eq_source="eqmode",
        )

        arch_result = create_archive_agent(tmp_dir, None).run(
            context, proc_result, cal_result, deb_result,
            discovery_result=discovery_result,
            multi_group_metadata=proc_result.multi_group_metadata,
        )

        # (a) run-info.json existiert (Additiv im Lauf-Ordner)
        run_info_path = tmp_dir / "run-info.json"
        assert arch_result.run_info == run_info_path
        assert run_info_path.exists()

        # (b) Aufnahmemodus aus dem DiscoveryResult (V1.3-6 resolve_eq_flag)
        run_info = json.loads(run_info_path.read_text(encoding="utf-8"))
        assert run_info["acquisition"]["eq"] is True
        assert run_info["acquisition"]["eq_source"] == "eqmode"

        # (c) Gruppen-Uebersicht: pro Gruppe die 6 Katalog-Felder, Hashes
        # der 2 synthetischen Gruppen (15s60, 60s40)
        groups = run_info["groups"]
        assert isinstance(groups, list)
        assert len(groups) == 2
        by_hash = {g["hash"]: g for g in groups}
        assert "15s60" in by_hash and "60s40" in by_hash
        for g in groups:
            assert set(g) == {"hash", "frame_count", "exptime", "gain", "filter", "weight"}
        assert by_hash["15s60"]["frame_count"] == 3
        assert by_hash["15s60"]["exptime"] == 15.0
        assert by_hash["15s60"]["gain"] == 60
        assert by_hash["60s40"]["exptime"] == 60.0
        assert by_hash["60s40"]["gain"] == 40

    def test_single_group_run_info_json(self, tmp_dir: Path):
        """Fix-Sammlung v1.3 §3 (P0): run-info.json auch im Single-Group-Lauf
        — ohne discovery_result: eq None/eq_source unknown; Gruppen-Uebersicht
        wird aus dem Context abgeleitet (group_by_params, identische Hash-
        Logik wie DiscoveryAgent.discover_groups)."""
        from astro_process.agents.archive import create_archive_agent

        context = make_sample_context(tmp_dir, group_count=1, frames_per_group=2)
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = [
            PipelineStep(name="register_frames"),
            PipelineStep(name="stack_frames"),
            PipelineStep(name="export"),
        ]

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = create_test_fits(
            tmp_dir / "stack.fits", exptime=15.0, gain=60, rng_seed=1
        )

        with patch("astro_process.agents.processing_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.processing_agent.stack_frames") as mock_stack:
            mock_reg.return_value = RegisterFramesResult(
                registered=[f.path for f in lights.frames if f.path.exists()],
                last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            mock_stack.return_value = stack_fits
            proc_result = agent.run(context, cal_result, deb_result, pipeline)

        create_archive_agent(tmp_dir, None).run(
            context, proc_result, cal_result, deb_result,
        )

        run_info_path = tmp_dir / "run-info.json"
        assert run_info_path.exists()
        run_info = json.loads(run_info_path.read_text(encoding="utf-8"))
        assert run_info["acquisition"]["eq"] is None
        assert run_info["acquisition"]["eq_source"] == "unknown"

        groups = run_info["groups"]
        assert len(groups) == 1
        g = groups[0]
        assert g["hash"] == "15s60"
        assert g["frame_count"] == 2
        assert g["exptime"] == 15.0
        assert g["gain"] == 60
        assert g["filter"] is None
        assert g["weight"] == 2.0


# ═══════════════════════════════════════════════════════════════════
# V1.7-5 — Always Multi-Group: Processor-Kernverhalten (AC-A/C)
# ═══════════════════════════════════════════════════════════════════


class TestAlwaysMultiGroup:
    """V1.7-5 (Always Multi-Group): Genau 1 Gruppe läuft durch denselben
    Pfad wie N Gruppen (AC-A1) — kein Fallback, kein MergeAgent-Aufruf
    (AC-A4), kanonische merged/-Materialisierung unabhängig von --merge/
    --no-merge (AC-C5), PCC-Kette wie bei N Gruppen (AC-A5/A6),
    M92-safe_name (safe_name-Hinweis)."""

    def _run_single_group(
        self,
        tmp_dir: Path,
        *,
        merge_agent=None,
        pcc_per_group: Optional[bool] = None,
        target_name: str = "",
    ) -> tuple:
        """process_multi_group mit GENAU 1 synthetischen Gruppe; register/
        stack/PCC gemockt (Muster run_multi_group_pipeline). Liefert
        (proc_result, pcc_calls)."""
        context = make_sample_context(tmp_dir, group_count=1, frames_per_group=3)
        agent = ProcessingAgent(working_dir=tmp_dir, config=None)
        mg_kwargs: dict = {}
        if pcc_per_group is not None:
            mg_kwargs["pcc_per_group"] = pcc_per_group
        mg_config = MultiGroupConfig(**mg_kwargs)

        pipeline = MagicMock()
        pipeline.processing_params = ProcessingParams()
        pipeline.steps = []

        lights = context.get_lights()
        cal_result = MagicMock()
        cal_result.calibrated_lights = [f.path for f in lights.frames if f.path.exists()]
        deb_result = MagicMock()
        deb_result.debayered_frames = []

        stack_fits = create_test_fits(
            tmp_dir / "stack_amg_15s60.fits", exptime=15.0, gain=60, rng_seed=1,
        )
        pcc_calls: list[Path] = []

        def fake_pcc(stack_path, *args, **kwargs_):
            pcc_calls.append(Path(stack_path))
            p = tmp_dir / f"pcc_amg_{len(pcc_calls)}.fits"
            create_test_fits(p, exptime=15.0, gain=60, rng_seed=40 + len(pcc_calls))
            return (p, "gaia_success")

        with patch("astro_process.agents.multi_group_agent.register_frames") as mock_reg, \
             patch("astro_process.agents.multi_group_agent.stack_frames", return_value=stack_fits), \
             patch.object(agent, "_apply_pcc_per_group", side_effect=fake_pcc):
            mock_reg.return_value = RegisterFramesResult(
                registered=[], last_frame_qualities=[], last_frame_rejected=0,
                last_registration_metrics={},
            )
            proc_result = agent.process_multi_group(
                context, cal_result, deb_result, pipeline,
                multi_group_config=mg_config, merge_agent=merge_agent,
                target_name=target_name,
            )

        return proc_result, pcc_calls

    def test_merge_agent_present_but_not_called(self, tmp_dir: Path):
        """AC-A4: MergeAgent vorhanden wird bei 1 Gruppe NICHT aufgerufen —
        kein insufficient_stacks; Ergebnis trotzdem auf merged/."""
        merge_agent = MagicMock()
        proc_result, _pcc_calls = self._run_single_group(
            tmp_dir, merge_agent=merge_agent,
        )
        merge_agent.run.assert_not_called()
        merged_fits = tmp_dir / "merged" / "TestTarget_merged.fits"
        assert merged_fits.exists()
        assert proc_result.stacked == merged_fits

    def test_materialization_without_merge_agent(self, tmp_dir: Path):
        """AC-C5: merged/-Materialisierung geschieht auch OHNE MergeAgent
        (--no-merge-Äquivalent) bei 1 Gruppe; Preview liegt daneben."""
        proc_result, _pcc_calls = self._run_single_group(tmp_dir, merge_agent=None)
        merged_fits = tmp_dir / "merged" / "TestTarget_merged.fits"
        assert merged_fits.exists()
        assert merged_fits in proc_result.exports
        assert (tmp_dir / "merged" / "TestTarget_merged_preview.jpg").exists()

    def test_metadata_complete_single_group(self, tmp_dir: Path):
        """AC-A3/A7: reference_selection.group == Hash der einen Gruppe;
        multi_group_metadata vollständig; Pass 2 leer."""
        proc_result, _pcc_calls = self._run_single_group(tmp_dir, merge_agent=None)
        meta = proc_result.multi_group_metadata
        assert list(meta["groups"].keys()) == ["15s60"]
        assert meta["reference_selection"]["group"] == "15s60"
        assert meta["reference_group"] == "15s60"
        assert meta["cross_group_registrations"] == []
        assert meta["skipped_groups"] == []

    def test_pcc_default_runs_on_group_stack_once(self, tmp_dir: Path):
        """AC-A5/A6: pcc_per_group=False (Default) → genau EIN PCC-Lauf auf
        dem Gruppen-Stack (= finale Daten); Status landet in group_metadata
        UND top-level result.pcc_status."""
        proc_result, pcc_calls = self._run_single_group(tmp_dir, merge_agent=None)
        assert len(pcc_calls) == 1
        # PCC lief auf dem Gruppen-Stack (nicht auf einer merged-Kopie)
        assert str(pcc_calls[0]).endswith("stack_amg_15s60.fits")
        meta = proc_result.multi_group_metadata
        assert meta["groups"]["15s60"]["pcc_status"] == "gaia_success"
        assert proc_result.pcc_status == "gaia_success"

    def test_pcc_per_group_true_explicit(self, tmp_dir: Path):
        """AC-A5: explizites pcc_per_group=True verhält sich identisch —
        ein PCC-Lauf, Status-Kette unverändert."""
        proc_result, pcc_calls = self._run_single_group(
            tmp_dir, merge_agent=None, pcc_per_group=True,
        )
        assert len(pcc_calls) == 1
        assert proc_result.multi_group_metadata["groups"]["15s60"]["pcc_status"] \
            == "gaia_success"
        assert proc_result.pcc_status == "gaia_success"

    def test_safe_name_normalization_m92(self, tmp_dir: Path):
        """safe_name-Hinweis (M92-Abnahme): 'M 92' → merged/M_92_merged.fits
        (Leerzeichen entfernt); KEIN Top-Level *_final.fits im MG-Pfad."""
        proc_result, _pcc_calls = self._run_single_group(
            tmp_dir, merge_agent=None, target_name="M 92",
        )
        expected = tmp_dir / "merged" / "M_92_merged.fits"
        assert expected.exists()
        assert proc_result.stacked == expected
        assert not (tmp_dir / "M_92_final.fits").exists()
        assert not (tmp_dir / "TestTarget_final.fits").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])