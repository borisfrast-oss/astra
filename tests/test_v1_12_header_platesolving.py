"""Tests for V1.12-HEADER-PLATESOLVING (S1-S5, Gate 7b) — 8 Tests per Spec REQ-5."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from astro_process.core.header_utils import build_effective_header, annotate_fits
from astro_process.models.core import FrameInfo, FrameSet, FrameType, FitsHeader, ObservationContext, ObservationTarget, EquipmentInfo, AcquisitionInfo, CalibrationStatus


def _make_light_header(raw_overrides: dict | None = None) -> FitsHeader:
    base = {
        "OBJECT": "C 19",
        "RA": 328.35,
        "DEC": 47.2667,
        "TELESCOP": "DWARF mini",
        "INSTRUME": "DWARF mini",
        "CAMERA": "DWARF mini",
        "FOCALLEN": 150.0,
        "XPIXSZ": 2.9,
        "YPIXSZ": 2.9,
        "EXPTIME": 90.0,
        "GAIN": 40,
        "FILTER": "Astro",
        "DATE-OBS": "2026-09-10T05:00:47",
        "DET-TEMP": -5.0,
        "EQMODE": 1,
        "BAYERPAT": "RGGB",
        "NAXIS1": 1920,
        "NAXIS2": 1080,
        "XBINNING": 1,
        "YBINNING": 1,
    }
    if raw_overrides:
        base.update(raw_overrides)
    hdr = FitsHeader(
        object=base.get("OBJECT"),
        exptime=base.get("EXPTIME"),
        gain=base.get("GAIN"),
        filter_name=base.get("FILTER"),
        ccd_temp=base.get("DET-TEMP"),
        telescope=base.get("TELESCOP"),
        instrument=base.get("INSTRUME"),
        focal_length=base.get("FOCALLEN"),
        pixel_size_x=base.get("XPIXSZ"),
        pixel_size_y=base.get("YPIXSZ"),
        ra=base.get("RA"),
        dec=base.get("DEC"),
        eq_mode=base.get("EQMODE"),
        raw_cards=dict(base),
        date_obs=None,
    )
    return hdr


def _make_context(light_hdr: FitsHeader | None = None, extra_lights: list[FitsHeader] | None = None) -> ObservationContext:
    hdr = light_hdr or _make_light_header()
    frames = []
    for idx, h in enumerate([hdr] + (extra_lights or [])):
        fi = FrameInfo(path=Path(f"/tmp/light_{idx}.fits"), frame_type=FrameType.LIGHT, header=h, index=idx, width=1920, height=1080)
        frames.append(fi)
    fs = FrameSet(frame_type=FrameType.LIGHT, frames=frames)
    target = ObservationTarget(name="C 19", ra=328.35, dec=47.2667)
    equip = EquipmentInfo(telescope="DWARF mini", focal_length_mm=150, pixel_size_um=2.9)
    return ObservationContext(target=target, frames={FrameType.LIGHT: fs}, calibration=CalibrationStatus(), equipment=equip, acquisition=AcquisitionInfo(), source_path=Path("/tmp"))


def _temp_fits(path: Path, shape: tuple[int, int] = (540, 960), naxis3: bool = False):
    # shape H,W ; for 3D RGB add channel
    if naxis3:
        data = np.zeros((3, shape[0], shape[1]), dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["CTYPE3"] = "RGB"
        hdu.header["NAXIS1"] = shape[1]
        hdu.header["NAXIS2"] = shape[0]
        hdu.header["NAXIS3"] = 3
    else:
        data = np.zeros(shape, dtype=np.float32)
        hdu = fits.PrimaryHDU(data)
        hdu.header["NAXIS1"] = shape[1]
        hdu.header["NAXIS2"] = shape[0]
    hdu.writeto(path, overwrite=True)
    return path


def test_header_debayer_superpixel_sets_5_8():
    ctx = _make_context()
    # S1: superpixel -> 5.8, S2: XBINNING 2, EQUINOX 2000.0, CUNIT deg etc
    hdr = build_effective_header(ctx, method="superpixel", scale_window=2.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 7.98}, naxis=(960, 540))
    assert abs(float(hdr["XPIXSZ"]) - 5.8) < 0.01
    assert hdr["XBINNING"] == 1  # S2 fix: XPIXSZ already effective (5.8), Siril would do 5.8*2=11.6 otherwise (C19 20260911-050327)
    assert hdr["YBINNING"] == 1
    assert hdr["EQUINOX"] == 2000.0
    assert hdr["DEBAYER"] == "superpixel"
    assert hdr["BAYERPAT"] == "RGGB"
    assert hdr["CUNIT1"] == "deg"
    assert hdr["CUNIT2"] == "deg"
    assert hdr["CTYPE1"] == "RA---TAN"
    # DATE-OBS and DET-TEMP present via raw_cards
    assert "DATE-OBS" in hdr or "DATE-OBS" in str(hdr)
    # Annotate to file and verify S5 CRPIX
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "deb_super.fits"
        _temp_fits(p, shape=(540, 960), naxis3=True)
        annotate_fits(p, hdr)
        h = fits.getheader(p)
        assert abs(float(h["XPIXSZ"]) - 5.8) < 0.01
        assert h["CTYPE1"] == "RA---TAN"
        # CRPIX should be (960+1)/2 = 480.5, (540+1)/2 = 270.5
        assert abs(float(h["CRPIX1"]) - 480.5) < 0.01
        assert abs(float(h["CRPIX2"]) - 270.5) < 0.01


def test_header_debayer_malvar_keeps_2_9():
    ctx = _make_context()
    hdr = build_effective_header(ctx, method="malvar2004", scale_window=1.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 3.99}, naxis=(1920, 1080))
    assert abs(float(hdr["XPIXSZ"]) - 2.9) < 0.01
    assert hdr["XBINNING"] == 1
    assert hdr["YBINNING"] == 1
    assert hdr["DEBAYER"] == "malvar2004"


def test_header_drizzle_1_45():
    ctx = _make_context()
    hdr = build_effective_header(ctx, method="drizzle", scale_window=1.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 1.99}, naxis=(3840, 2160), drizzle_pixfrac=0.5, drizzle_kernel="lanczos3", drizzle_nframes=15)
    assert abs(float(hdr["XPIXSZ"]) - 1.45) < 0.02
    assert hdr["DRZSCALE"] == 2.0
    assert "DRZPIXFR" in hdr
    assert "DRZKERNL" in hdr
    assert "NFRAMES" in hdr
    assert hdr["CUNIT1"] == "deg"
    assert hdr["CUNIT2"] == "deg"
    # Check CDELT ~ -1.99/3600
    assert abs(float(hdr["CDELT1"]) + 1.99/3600.0) < 1e-6


def test_header_merged_inherits_effective():
    # merged inherits 5.8 from ref superpixel
    ctx = _make_context()
    # Simulate ref header via context first light (superpixel -> 5.8)
    # Build merged header with total_exposure sum
    hdr = build_effective_header(ctx, method="superpixel", scale_window=2.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 7.98}, total_exposure=4110.0, naxis=(960, 540))
    # Simulate MG* added by merge_agent (tested via annotate)
    hdr["MGCNTGRP"] = 2
    hdr["MGREFGRP"] = "15s40_astro"
    hdr["MGMETHOD"] = "weighted_average"
    assert abs(float(hdr["XPIXSZ"]) - 5.8) < 0.01
    assert float(hdr["EXPTIME"]) == 4110.0
    assert hdr["CTYPE1"] == "RA---TAN"
    # MULTI handling would be in merge_agent, but build itself should have MULTI placeholder if needed
    # Ensure WCS present
    assert "CRVAL1" in hdr


def test_header_stacked_has_wcs_and_object():
    ctx = _make_context()
    hdr = build_effective_header(ctx, method="superpixel", scale_window=2.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 7.98}, naxis=(960, 540))
    assert hdr["OBJECT"] == "C 19"
    assert abs(float(hdr["RA"]) - 328.35) < 0.001
    assert abs(float(hdr["DEC"]) - 47.2667) < 0.001
    assert hdr["CRVAL1"] == 328.35
    assert hdr["CRVAL2"] == 47.2667
    assert abs(float(hdr["CRPIX1"]) - 480.5) < 0.01
    assert abs(float(hdr["CDELT1"]) + 7.98/3600.0) < 1e-6
    assert hdr["CTYPE1"] == "RA---TAN"
    assert hdr["CUNIT1"] == "deg"
    assert hdr["EQUINOX"] == 2000.0
    assert "DATE-OBS" in hdr
    assert "DET-TEMP" in hdr
    assert "BAYERPAT" in hdr
    assert "DEBAYER" in hdr
    assert "CUNIT1" in hdr


def test_01_calibrated_still_min_headers():
    # 01_calibrated internal markiert oder annotiert; qc --check-header Ausnahme, nicht Gate-rot
    # Simulate calibrated file annotation: scale 1.0 -> 2.9, internal HISTORY
    ctx = _make_context()
    hdr = build_effective_header(ctx, method="superpixel", scale_window=1.0, drizzle_scale=2.0, wcs=None, naxis=(1920, 1080))
    # Mark internal
    hdr.remove("HISTORY", remove_all=True)
    hdr.add_history("Astra calibration: internal")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cal_test.fits"
        _temp_fits(p, shape=(1080, 1920))
        annotate_fits(p, hdr)
        h = fits.getheader(p)
        # After our fix, 01_calibrated not 6 keys leer: has at least XPIXSZ, FOCALLEN etc plus internal marker
        assert "XPIXSZ" in h
        assert "FOCALLEN" in h
        # Check that header has internal history (q.c. will treat as pass via exception)
        hist = [c.value for c in h.cards if c.keyword == "HISTORY"]
        assert any("calibration" in str(v).lower() and "internal" in str(v).lower() for v in hist)
        # Simulate qc header check skipping 01_calibrated: qc _compute_header_checks ignores 01_calibrated path
        from astro_process.core.qc import _compute_header_checks
        # Create fake generated dir with 01_calibrated file (should be skipped)
        gen = Path(td) / "generated"
        gen.mkdir()
        cal_dir = gen / "01_calibrated"
        cal_dir.mkdir()
        # Copy file there
        import shutil
        shutil.copy2(p, cal_dir / "cal_test.fits")
        res = _compute_header_checks(gen)
        # Since only 01_calibrated exists, no user-visible FITS -> SKIPPED, not FAIL (Ausnahme)
        assert res["status"] in ("SKIPPED", "PASS")


def test_merge_without_context_uses_ref_header():
    # context is None -> raw_cards aus ref_header via HEADER_ALIASES
    # Use alias keys: OBJNAME instead of OBJECT, OBJCTRA instead of RA etc via HEADER_ALIASES mapping
    ref_hdr_dict = {
        "OBJNAME": "C 19",  # alias for OBJECT
        "OBJCTRA": 328.35,  # alias for RA
        "OBJCTDEC": 47.2667,  # alias for DEC (note OBJCTDEC in aliases)
        "TELESCOP": "DWARF mini",
        "FOCALLEN": 150.0,
        "XPIXSZ": 2.9,
        "BAYERPAT": "RGGB",
        "DATE-OBS": "2026-09-10T05:00:47",
        "DET-TEMP": -5.0,
        EQMODE_KEY if 'EQMODE_KEY' in globals() else "EQMODE": 1,
    }
    # Actually HEADER_ALIASES for dec includes OBJCTDEC, so this tests alias normalization
    # Build merged header with context None and ref_header fallback
    # Need to pass ref_header as fits.Header
    ref_fits_hdr = fits.Header()
    for k, v in ref_hdr_dict.items():
        ref_fits_hdr[k] = v
    hdr = build_effective_header(None, method="superpixel", scale_window=2.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 7.98}, total_exposure=1800.0, ref_header=ref_fits_hdr, naxis=(960, 540))
    assert abs(float(hdr["XPIXSZ"]) - 5.8) < 0.01
    assert hdr["OBJECT"] == "C 19"
    assert abs(float(hdr["RA"]) - 328.35) < 0.001
    assert abs(float(hdr["DEC"]) - 47.2667) < 0.001


def test_wcs_crpix_depends_on_output_naxis():
    ctx = _make_context()
    # 960x540 -> 480.5/270.5
    hdr_small = build_effective_header(ctx, method="superpixel", scale_window=2.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 7.98}, naxis=(960, 540))
    assert abs(float(hdr_small["CRPIX1"]) - 480.5) < 0.01
    assert abs(float(hdr_small["CRPIX2"]) - 270.5) < 0.01
    assert abs(float(hdr_small["CDELT1"]) + 7.98/3600.0) < 1e-6
    # 3840x2160 -> 1920.5/1080.5 via drizzle 1.45
    hdr_big = build_effective_header(ctx, method="drizzle", scale_window=1.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 1.99}, naxis=(3840, 2160), drizzle_pixfrac=0.5, drizzle_kernel="lanczos3", drizzle_nframes=10)
    assert abs(float(hdr_big["CRPIX1"]) - 1920.5) < 0.01
    assert abs(float(hdr_big["CRPIX2"]) - 1080.5) < 0.01
    assert abs(float(hdr_big["CDELT1"]) + 1.99/3600.0) < 1e-6
    # Also test annotate_fits corrects CRPIX based on file NAXIS even if header built with wrong naxis
    with tempfile.TemporaryDirectory() as td:
        p_small = Path(td) / "small.fits"
        _temp_fits(p_small, shape=(540, 960), naxis3=True)  # NAXIS1 960 NAXIS2 540
        # Build with big naxis, annotate small file -> should correct to small's CRPIX
        hdr_wrong = build_effective_header(ctx, method="superpixel", scale_window=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 7.98}, naxis=(3840, 2160))
        annotate_fits(p_small, hdr_wrong)
        h_small = fits.getheader(p_small)
        assert abs(float(h_small["CRPIX1"]) - 480.5) < 0.01  # corrected
        assert abs(float(h_small["CRPIX2"]) - 270.5) < 0.01
