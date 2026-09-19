"""V1.12-QC — tests for flip/ghosting/color, pattern, exit codes."""

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
from astropy.io import fits
from click.testing import CliRunner

from astro_process.cli import cli
from astro_process.core.preview import create_preview
from astro_process.core.qc import detect_flip_type, run_qc, _load_fits_linear, _load_preview, _compute_header_checks


# // Legacy: behalten weil Flip/Ghosting-Synthetik minimalen Header nutzt (kein Platesolving) // Gate: test_v1_12_header_platesolving deckt echten DWARF-Header ab (5.8/2.9/1.45)
def _make_fits(path: Path, arr: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(arr.transpose(2, 0, 1).astype(np.float32))
    hdu.writeto(path, overwrite=True)


def _make_header_fits(path: Path, arr: np.ndarray, *, header_valid: bool = True):
    """Helper fuer header.fallback_detected Gate — erzeugt FITS mit/ohne platesolving-Header (V1.12 Kap.8b)."""
    from astro_process.core.header_utils import build_effective_header, annotate_fits
    from astro_process.models.core import FrameInfo, FrameSet, FrameType, FitsHeader, ObservationContext, ObservationTarget, EquipmentInfo, AcquisitionInfo, CalibrationStatus

    path.parent.mkdir(parents=True, exist_ok=True)
    # Base FITS mit NAXIS
    hdu = fits.PrimaryHDU(arr.transpose(2, 0, 1).astype(np.float32))
    hdu.header["NAXIS1"] = arr.shape[1]
    hdu.header["NAXIS2"] = arr.shape[0]
    hdu.header["CTYPE3"] = "RGB"
    hdu.header["CUNIT3"] = "channel"
    hdu.writeto(path, overwrite=True)

    if not header_valid:
        # Minimaler Header — nur CTYPE3, bewusst ohne XPIXSZ/WCS -> fallback_detected true
        return path

    # Gueltiger DWARF-mini Header via header_utils SSOT (wie C19 live): FOCALLEN 150/XPIXSZ 2.9 -> effektive 5.8
    raw = {
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
    }
    hdr_obj = FitsHeader(
        object=raw["OBJECT"], exptime=raw["EXPTIME"], gain=raw["GAIN"], filter_name=raw["FILTER"],
        telescope=raw["TELESCOP"], focal_length=raw["FOCALLEN"], pixel_size_x=raw["XPIXSZ"], pixel_size_y=raw["YPIXSZ"],
        ra=raw["RA"], dec=raw["DEC"], eq_mode=raw["EQMODE"], raw_cards=dict(raw),
    )
    ctx = ObservationContext(
        target=ObservationTarget(name="C 19", ra=328.35, dec=47.2667),
        frames={FrameType.LIGHT: FrameSet(frame_type=FrameType.LIGHT, frames=[FrameInfo(path=path, frame_type=FrameType.LIGHT, header=hdr_obj, index=0, width=arr.shape[1], height=arr.shape[0])])},
        calibration=CalibrationStatus(), equipment=EquipmentInfo(telescope="DWARF mini", focal_length_mm=150, pixel_size_um=2.9),
        acquisition=AcquisitionInfo(), source_path=path.parent,
    )
    hdr = build_effective_header(ctx, method="superpixel", scale_window=2.0, drizzle_scale=2.0, wcs={"ra": 328.35, "dec": 47.2667, "pixel_scale_arcsec": 7.98}, naxis=(arr.shape[1], arr.shape[0]))
    annotate_fits(path, hdr)
    return path


def _minimal_run_info(p: Path, smoke: bool = False):
    (p / "run-info.json").write_text(json.dumps({"run": {"version": "1.12.0"}, "smoke_mode": smoke}, indent=2), encoding="utf-8")
    (p / "agent-log.yaml").write_text("processing:\n  pcc_status: null\n", encoding="utf-8")


def test_detect_flip_vertical_pass_and_none_fail():
    h, w = 80, 80
    rng = np.random.default_rng(42)
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[5:15, 5:15, :] += 3000
    arr[20:30, 60:70, :] += 1500
    for x, y in [(30, 40), (70, 20)]:
        yy, xx = np.ogrid[:h, :w]
        arr[:, :, 0] += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 4) * 1000
        arr[:, :, 1] += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 4) * 1000
        arr[:, :, 2] += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 4) * 1000

    tmp = Path(tempfile.mkdtemp())
    fits_path = tmp / "stack.fits"
    _make_fits(fits_path, arr)
    stack_arr = _load_fits_linear(fits_path)

    # Correct preview (with flipud) -> vertical PASS
    preview_ok = tmp / "preview_ok.tiff"
    create_preview(fits_path, preview_ok, format="tiff", apply_flipud=True)
    preview_arr_ok = _load_preview(preview_ok)
    det_ok = detect_flip_type(stack_arr, preview_arr_ok, apply_asinh_stretch=True)
    assert det_ok["type"] == "vertical", det_ok
    # Simulate status mapping like run_qc
    assert det_ok["type"] == "vertical"

    # Bug preview (no flip) -> none FAIL
    preview_bug = tmp / "preview_bug.jpg"
    create_preview(fits_path, preview_bug, format="jpg", apply_flipud=False)
    preview_arr_bug = _load_preview(preview_bug)
    det_bug = detect_flip_type(stack_arr, preview_arr_bug, apply_asinh_stretch=True)
    assert det_bug["type"] == "none", det_bug


def test_qc_pattern_both_formats():
    tmp = Path(tempfile.mkdtemp()) / "gen" / "20260906-080324"
    tmp.mkdir(parents=True)
    h, w = 40, 40
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[5:15, 5:15, :] += 2000
    arr += 50
    fits_path = tmp / "stack.fits"
    _make_fits(fits_path, arr)
    merged = tmp / "merged"
    merged.mkdir()
    shutil.copy(fits_path, merged / "M27_merged.fits")
    # Create both jpg and tiff previews
    p_jpg = merged / "M27_merged_preview.jpg"
    p_tiff = merged / "M27_merged_preview.tiff"
    create_preview(fits_path, p_jpg, format="jpg", apply_flipud=True)
    create_preview(fits_path, p_tiff, format="tiff", apply_flipud=True)
    assert p_jpg.exists()
    assert p_tiff.exists()
    _minimal_run_info(tmp)
    report = run_qc(tmp)
    # Should find both previews
    assert len(report["inputs"]["previews"]) >= 2
    assert report["checks"]["flip_detection"]["status"] == "PASS"


def test_qc_color_green_excess_fail():
    tmp = Path(tempfile.mkdtemp()) / "gen" / "20260906-080400"
    tmp.mkdir(parents=True)
    h, w = 30, 30
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:, :, 0] = 120
    arr[:, :, 1] = 145  # 18% excess
    arr[:, :, 2] = 118
    arr[5:10, 5:10, :] += 300
    fits_path = tmp / "stack.fits"
    _make_fits(fits_path, arr)
    merged = tmp / "merged"
    merged.mkdir()
    shutil.copy(fits_path, merged / "M_merged.fits")
    create_preview(fits_path, merged / "M_merged_preview.tiff", format="tiff", apply_flipud=True)
    _minimal_run_info(tmp)
    report = run_qc(tmp)
    assert report["checks"]["color"]["status"] == "FAIL"
    assert report["checks"]["color"]["green_excess_pct"] > 15
    assert report["status"] == "FAIL"


def test_qc_exit_codes():
    runner = CliRunner()
    # PASS case
    tmp_pass = Path(tempfile.mkdtemp()) / "gen" / "20260906-080401"
    tmp_pass.mkdir(parents=True)
    h, w = 40, 40
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:, :, 0] = 100
    arr[:, :, 1] = 100
    arr[:, :, 2] = 100
    arr[5:15, 5:15, :] += 2000
    fp = tmp_pass / "s.fits"
    _make_fits(fp, arr)
    merged = tmp_pass / "merged"
    merged.mkdir()
    shutil.copy(fp, merged / "M_merged.fits")
    create_preview(fp, merged / "M_merged_preview.tiff", format="tiff", apply_flipud=True)
    _minimal_run_info(tmp_pass)
    res = runner.invoke(cli, ["qc", str(tmp_pass)])
    assert res.exit_code == 0, res.output

    # FAIL case (green)
    tmp_fail = Path(tempfile.mkdtemp()) / "gen" / "20260906-080402"
    tmp_fail.mkdir(parents=True)
    arr2 = np.zeros((h, w, 3), dtype=np.float32)
    arr2[:, :, 0] = 120
    arr2[:, :, 1] = 145
    arr2[:, :, 2] = 118
    arr2[5:10, 5:10, :] += 300
    fp2 = tmp_fail / "s.fits"
    _make_fits(fp2, arr2)
    merged2 = tmp_fail / "merged"
    merged2.mkdir()
    shutil.copy(fp2, merged2 / "M_merged.fits")
    create_preview(fp2, merged2 / "M_merged_preview.tiff", format="tiff", apply_flipud=True)
    _minimal_run_info(tmp_fail)
    res2 = runner.invoke(cli, ["qc", str(tmp_fail)])
    assert res2.exit_code == 2, res2.output

    # SKIPPED case (no stacks)
    tmp_skip = Path(tempfile.mkdtemp()) / "gen" / "20260906-080403"
    tmp_skip.mkdir(parents=True)
    _minimal_run_info(tmp_skip)
    res3 = runner.invoke(cli, ["qc", str(tmp_skip)])
    assert res3.exit_code == 1, res3.output


def test_qc_tifffile_not_pil():
    # Ensure TIFF 16-bit is read via tifffile, not PIL downscaled
    tmp = Path(tempfile.mkdtemp())
    fits_path = tmp / "stack.fits"
    h, w = 20, 20
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:, :, :] = 1000
    arr[2:5, 2:5, :] = 3000
    _make_fits(fits_path, arr)
    tiff_path = tmp / "preview.tiff"
    create_preview(fits_path, tiff_path, format="tiff", apply_flipud=True)
    # Read via our loader -> should be uint16
    loaded = _load_preview(tiff_path)
    assert loaded.dtype == np.uint16
    assert loaded.max() > 1000  # 16-bit range preserved


# // updated 2026-09-11: Handbook Kap.04 verlangt Header — header.fallback_detected Gate vgl. core/qc.py:674 Kap.8b
def test_qc_header_fallback_detected_gate():
    """Header-Gate Kap.8b: 01_calibrated SKIPPED, stacked PASS ohne fallback, leerer Header FAIL mit fallback true."""
    # Fall 1: nur 01_calibrated -> SKIPPED als internal (S3 Ausnahme)
    tmp_only_cal = Path(tempfile.mkdtemp()) / "gen" / "20260911-cal-only"
    tmp_only_cal.mkdir(parents=True)
    _minimal_run_info(tmp_only_cal)
    cal_dir = tmp_only_cal / "01_calibrated"
    cal_dir.mkdir(parents=True)
    arr = np.zeros((50, 50, 3), dtype=np.float32) + 10
    _make_header_fits(cal_dir / "cal_0000.fits", arr, header_valid=False)
    res_cal = _compute_header_checks(tmp_only_cal)
    assert res_cal["status"] == "SKIPPED", res_cal  # 01_calibrated ausgenommen, kein Gate-ROT
    assert res_cal["fallback_detected"] is False

    # Fall 2: 04_stacked mit korrektem DWARF-mini Header (FOCALLEN 150/XPIXSZ 2.9 -> 5.8, WCS RA---TAN, EQUINOX 2000) -> PASS fallback false
    tmp_pass = Path(tempfile.mkdtemp()) / "gen" / "20260911-header-pass"
    tmp_pass.mkdir(parents=True)
    _minimal_run_info(tmp_pass)
    stacked_dir = tmp_pass / "group_15s40" / "04_stacked"
    stacked_dir.mkdir(parents=True)
    arr2 = np.zeros((50, 50, 3), dtype=np.float32) + 100
    arr2[10:15, 10:15, :] += 500
    _make_header_fits(stacked_dir / "stacked.fits", arr2, header_valid=True)
    res_pass = _compute_header_checks(tmp_pass)
    assert res_pass["status"] == "PASS", res_pass
    assert res_pass["fallback_detected"] is False
    # Gate-Kriterium Handbook Kap.04: XPIXSZ 5.8 und CTYPE1 RA---TAN vorhanden (S1/S2)
    pf = res_pass["per_file"][0]
    assert pf["status"] == "PASS"
    assert pf["fallback_detected"] is False
    assert "XPIXSZ 5.8" in pf["evidence"] or "5.8" in str(pf.get("XPIXSZ", ""))

    # Fall 3: 04_stacked mit leerem Header (nur CTYPE3) -> FAIL fallback true, missing EXPTIME/GAIN/FILTER etc.
    tmp_fail = Path(tempfile.mkdtemp()) / "gen" / "20260911-header-fail"
    tmp_fail.mkdir(parents=True)
    _minimal_run_info(tmp_fail)
    stacked_dir2 = tmp_fail / "group_15s40" / "04_stacked"
    stacked_dir2.mkdir(parents=True)
    _make_header_fits(stacked_dir2 / "stacked.fits", arr2, header_valid=False)
    res_fail = _compute_header_checks(tmp_fail)
    assert res_fail["status"] == "FAIL", res_fail
    assert res_fail["fallback_detected"] is True
    pf2 = res_fail["per_file"][0]
    assert pf2["status"] == "FAIL"
    assert pf2["fallback_detected"] is True
    # run_qc mit --check-header muss header.fallback_detected exposen und Gate FAIL liefern
    report_pass = run_qc(tmp_pass, check_header=True)
    assert report_pass["checks"]["header"]["status"] == "PASS"
    assert report_pass["checks"]["header"]["fallback_detected"] is False
    report_fail = run_qc(tmp_fail, check_header=True)
    assert report_fail["checks"]["header"]["status"] == "FAIL"
    assert report_fail["checks"]["header"]["fallback_detected"] is True


# C7-Major2: Drizzle-NCC 3840x2160 vs 960x540 — gleiche Methode, 512 Downsample vertretbar
def test_drizzle_ncc_3840_downsample_calibrated():
    """C7-Major2: Drzzle-NCC bei 3840x2160 Faktor 7.5 (512) nicht kalibriert — synthetischer Nachweis.

    SP (960x540) vs Drizzle (3840x2160) beide Ebenen gleiche detect_flip_type Methode;
    512-Downsample muss Flip-Erkennung (vertical PASS) bei beiden Aufloesungen erhalten.
    Falls Code nicht aendert, ist Test Nachweis dass 512 vertretbar (per Review-Anforderung).
    """
    from astro_process.core.qc import _downsample_for_qc, _ncc, _to_grayscale

    # Small SP Level 960x540
    h_s, w_s = 540, 960
    # Large Drizzle Level 3840x2160 = 4x SP (scale 2.0 per axis *2)
    h_l, w_l = 2160, 3840

    def _make_pattern(h, w, seed=7):
        rng = np.random.default_rng(seed)
        arr = np.zeros((h, w, 3), dtype=np.float32)
        # Add few bright spots asymmetrisch (so flip erkennbar)
        arr[h // 4 : h // 4 + h // 20, w // 4 : w // 4 + w // 20, :] += 3000
        arr[3 * h // 4 : 3 * h // 4 + h // 20, 3 * w // 4 : 3 * w // 4 + w // 20, :] += 1500
        # Add star field (two Gaussians)
        for x, y in [(w // 3, h // 3), (2 * w // 3, h // 5)]:
            yy, xx = np.ogrid[:h, :w]
            amp = 900
            arr[:, :, 0] += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (w * 0.02) ** 2) * amp
            arr[:, :, 1] += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (w * 0.02) ** 2) * amp
            arr[:, :, 2] += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (w * 0.02) ** 2) * amp
        # Add background
        arr += 80 + rng.random((h, w, 3)).astype(np.float32) * 5
        return arr

    for h, w in [(h_s, w_s), (h_l, w_l)]:
        fits_arr = _make_pattern(h, w)
        # Simulate preview correctly flipped (vertical = np.flipud)
        preview_arr = np.flipud(fits_arr).copy()
        # Add slight 8-bit quantization like JPG/TIFF pipeline
        preview_arr = np.clip(preview_arr / preview_arr.max() * 255, 0, 255).astype(np.uint8)
        # Convert preview to expected input dtype for detect_flip_type (uint8 RGB)
        # Need to reconstruct as uint8 RGB; detect_flip_type handles conversion internally
        det = detect_flip_type(fits_arr, preview_arr, apply_asinh_stretch=True)
        assert det["type"] == "vertical", f"{h}x{w} expected vertical, got {det}"
        # NCC best should be vertical with high score (>0.5)
        assert det["ncc_scores"]["vertical"] > 0.5, det["ncc_scores"]
        # Explicit downsample check: 3840 large reduces to max 512
        gray_l = _to_grayscale(fits_arr)
        down = _downsample_for_qc(gray_l, max_dim=512)
        assert max(down.shape) <= 512, f"downsample failed {down.shape} for {h}x{w}"
        # NCC after downsample should still differentiate: vertical > none
        # Build grayscale preview
        preview_gray = _to_grayscale(preview_arr.astype(np.float64))
        down_prev = _downsample_for_qc(preview_gray, max_dim=512)
        # Need matching shapes: _ncc handles resize
        ncc_vert = _ncc(np.flipud(down), down_prev) if h == h_l else _ncc(_downsample_for_qc(np.flipud(gray_l)), down_prev)
        # Simpler: compare both downsized versions with flip vs none
        # Expect vertical higher than none after downsample
        ncc_none = _ncc(down, down_prev)
        # For large drizzle, vertical should beat none by gap >0.1
        assert ncc_vert > ncc_none, f"512 downsample degraded NCC at {h}x{w}: vert {ncc_vert:.3f} vs none {ncc_none:.3f}"


def test_qc_smoke_skipped_instead_of_fail():
    """C7-Major1: smoke_mode=true -> qc.smoke_skipped Warning statt FAIL."""
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "gen" / "20260917-smoke"
    tmp.mkdir(parents=True)
    h, w = 40, 40
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:, :, 0] = 120
    arr[:, :, 1] = 145  # green excess -> normally FAIL
    arr[:, :, 2] = 118
    arr[5:10, 5:10, :] += 300
    fits_path = tmp / "stack.fits"
    _make_fits(fits_path, arr)
    merged = tmp / "merged"
    merged.mkdir()
    shutil.copy(fits_path, merged / "M_merged.fits")
    create_preview(fits_path, merged / "M_merged_preview.tiff", format="tiff", apply_flipud=True)
    # smoke_mode true -> run-info with smoke_mode
    (tmp / "run-info.json").write_text(json.dumps({"run": {"version": "1.12.0"}, "smoke_mode": True}, indent=2), encoding="utf-8")
    (tmp / "agent-log.yaml").write_text("processing:\n  pcc_status: null\n", encoding="utf-8")
    report = run_qc(tmp)
    assert report["smoke_mode"] is True
    # Color would be FAIL (18% >15%) but smoke should downgrade to SKIPPED with qc.smoke_skipped
    assert report["checks"]["color"]["status"] == "SKIPPED", report["checks"]["color"]
    assert report["checks"]["color"]["reason"] == "qc.smoke_skipped"
    assert "qc.smoke_skipped" in report["checks"]["color"]["evidence"]
    # Overall should NOT be FAIL despite green excess
    assert report["status"] != "FAIL", report
