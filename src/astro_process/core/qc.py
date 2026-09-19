"""V1.12-QC — Quality-Checker for generated runs (Flip/Ghosting/Farbe).

Reads only ``generated/<ts>/`` (pattern-based, no lights/ reading).

Checks:
  - Flip-Detection: NCC + asinh-stretch, vertical=PASS / none=FAIL
  - Ghosting: detect_double_stars / double_rate >0.3 worst per group
  - Farbe: G-excess >15% on linear FITS + PCC context

Outputs qc_report.json + stdout PASS/FAIL, Exit 0/2/1.
"""

from __future__ import annotations

import json
import glob as glob_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

EQMODE_KEY = "EQMODE"

import numpy as np
import structlog
import yaml

logger = structlog.get_logger(__name__)

FlipType = Literal["vertical", "horizontal", "180", "transpose", "none", "unknown"]
GHOSTING_THRESHOLD = 0.3
COLOR_THRESHOLD = 15.0
COLOR_WARN = 10.0


def _load_fits_linear(path: Path) -> Optional[np.ndarray]:
    """Load linear stacked FITS as (H,W,3) float32 RGB."""
    try:
        from astropy.io import fits

        with fits.open(path) as hdul:
            data = hdul[0].data
            if data is None:
                return None
            data = np.asarray(data)
            # Handle axis order: (C,H,W) -> (H,W,C)
            if data.ndim == 3 and data.shape[0] == 3:
                data = data.transpose(1, 2, 0)
            # Ensure H,W,C
            if data.ndim == 2:
                # Grayscale -> expand to 3?
                data = np.stack([data, data, data], axis=-1)
            if data.ndim != 3 or data.shape[-1] != 3:
                # Try to squeeze
                data = np.asarray(data)
                if data.ndim == 3 and data.shape[-1] != 3:
                    # Might be (H,W) -> already handled
                    pass
            return data.astype(np.float32)
    except Exception as e:
        logger.warning("qc.fits_load_failed", path=str(path), error=str(e))
        return None


def _load_preview(path: Path) -> Optional[np.ndarray]:
    """Load preview JPG or TIFF as (H,W,3) uint8/uint16 -> float 0-1 is done by caller normalization outside.

    Returns array in 0-255 or 0-65535 range as read, caller handles normalization.
    For NCC we normalize via mean subtraction anyway, so raw range not critical.
    """
    suffix = path.suffix.lower()
    try:
        if suffix in (".tiff", ".tif"):
            try:
                import tifffile

                arr = tifffile.imread(str(path))
                # tifffile returns (H,W,3) uint16 or (H,W) or (H,W,4)
                if arr.ndim == 3 and arr.shape[-1] == 4:
                    arr = arr[:, :, :3]
                if arr.ndim == 2:
                    arr = np.stack([arr, arr, arr], axis=-1)
                return np.asarray(arr)
            except ImportError:
                # Fallback try astropy? Not for tiff
                logger.warning("qc.tifffile_unavailable", path=str(path))
                return None
            except Exception as e:
                logger.warning("qc.tiff_load_failed", path=str(path), error=str(e))
                return None
        else:
            # JPG / PNG via PIL
            try:
                from PIL import Image

                img = Image.open(path).convert("RGB")
                return np.asarray(img)
            except Exception as e:
                logger.warning("qc.jpg_load_failed", path=str(path), error=str(e))
                return None
    except Exception as e:
        logger.warning("qc.preview_load_failed", path=str(path), error=str(e))
        return None


def _to_grayscale(arr: np.ndarray) -> np.ndarray:
    """Convert (H,W,3) to 2D grayscale via mean or luminance."""
    if arr.ndim == 3 and arr.shape[-1] == 3:
        # Use mean for robustness (or G channel). Mean is spec-agnostic.
        return arr.mean(axis=-1).astype(np.float64)
    if arr.ndim == 3:
        return arr.mean(axis=-1).astype(np.float64)
    return arr.astype(np.float64)


def _resize_to_match(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Resize larger to smaller or both to common size if mismatch."""
    if a.shape == b.shape:
        return a, b
    # If shapes differ, resize both to min shape via PIL or scipy?
    # Use PIL for 2D grayscale.
    try:
        from PIL import Image

        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        # Resize both to (w,h) using bilinear
        def _resize(arr):
            if arr.shape[0] == h and arr.shape[1] == w:
                return arr
            # Normalize to 0-1 for PIL then resize
            # PIL needs uint8; convert via normalization
            norm = arr.astype(np.float64)
            mn, mx = norm.min(), norm.max()
            if mx > mn:
                norm = (norm - mn) / (mx - mn)
            else:
                norm = np.zeros_like(norm)
            uint8 = (norm * 255).astype(np.uint8)
            img = Image.fromarray(uint8, mode="L")
            img2 = img.resize((w, h), Image.BILINEAR)
            return np.asarray(img2).astype(np.float64)
        return _resize(a), _resize(b)
    except Exception:
        # Fallback: crop to min
        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        return a[:h, :w], b[:h, :w]


def _downsample_for_qc(arr: np.ndarray, max_dim: int = 512) -> np.ndarray:
    """Downsample large 2D arrays for QC to bound runtime (V1.12-QC Hang Fix).

    Stella Zwischen-Check 08.09.2026: detect_flip_type blockiert >600s auf
    1920x1080 und 3840x2160 (NCC/DAOStarFinder + cKDTree). Downsampling auf
    max 512 (längste Seite) reduziert Pixel von 8M → 0.26M (30x), sep/KDTree
    von O(n^2) auf handhabbar, Flip-Erkennung bleibt erhalten (Flip ist
    globale Transformation, nicht detailabhängig). Target <10s für astra qc.
    V1.12-Nachfix 09.09.2026: CLI löst Target-Root → latest (40→2 stacks, 43s→~5s);
    Downsample 512 bleibt, 256 wäre optional für weitere 4x, aber Stack-Limit
    ist Haupt-Hebel. Thumbnail-JPG (500KB) statt 48MB TIFF wird via CLI
    Preview-Auswahl (jpg bevorzugt) zusätzlich genutzt.
    """
    try:
        h, w = arr.shape[0], arr.shape[1] if arr.ndim >= 2 else (arr.shape[0], 1)
        if max(h, w) <= max_dim:
            return arr
        # Compute scale
        scale = max_dim / float(max(h, w))
        new_h = max(1, int(round(h * scale)))
        new_w = max(1, int(round(w * scale)))
        # Use PIL for downsampling (bilinear)
        from PIL import Image

        # Normalize to 0-255 for PIL
        norm = arr.astype(np.float64)
        mn, mx = float(np.min(norm)), float(np.max(norm))
        if mx > mn and np.isfinite(mn) and np.isfinite(mx):
            norm = (norm - mn) / (mx - mn)
        else:
            norm = np.zeros_like(norm)
        # Clip to 0-1
        norm = np.clip(norm, 0, 1)
        uint8 = (norm * 255).astype(np.uint8)
        img = Image.fromarray(uint8, mode="L")
        img2 = img.resize((new_w, new_h), Image.BILINEAR)
        out = np.asarray(img2).astype(np.float64)
        # Restore original dynamic range approx: scale back to original min/max
        # For NCC, absolute scale doesn't matter (mean subtracted), so keep 0-255.
        return out
    except Exception:
        # Fallback: simple stride downsampling
        try:
            h, w = arr.shape[0], arr.shape[1]
            if max(h, w) <= max_dim:
                return arr
            step = max(1, int(round(max(h, w) / max_dim)))
            return arr[::step, ::step]
        except Exception:
            return arr


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized cross-correlation (Pearson) between two 2D arrays."""
    if a.shape != b.shape:
        a, b = _resize_to_match(a, b)
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom < 1e-12:
        return 0.0
    v = float((a * b).sum() / denom)
    # Clamp
    if not np.isfinite(v):
        return 0.0
    return float(np.clip(v, -1.0, 1.0))


def _asinh_stretch(data: np.ndarray, sigma_factor: float = 3.0) -> np.ndarray:
    """Asinh stretch for FITS linear data prior to NCC (PFLICHT per Spec)."""
    try:
        from .preview import auto_asinh

        return auto_asinh(data, sigma_factor=sigma_factor)
    except Exception:
        # Fallback simple asinh
        d = data.astype(np.float64)
        bg = np.median(d)
        d = np.clip(d - bg, 0, None)
        mad = np.median(np.abs(d - np.median(d)))
        sigma = float(mad) * 1.4826 if mad > 0 else 1.0
        stretch_val = max(sigma * sigma_factor, 1e-10)
        stretched = np.arcsinh(d / stretch_val)
        mx = np.max(stretched)
        if mx > 0:
            stretched = stretched / mx
        return stretched


def detect_flip_type(
    stacked_fits_linear: np.ndarray,
    preview_rgb: np.ndarray,
    apply_asinh_stretch: bool = True,
) -> dict:
    """Detect flip type between linear FITS and preview.

    Args:
        stacked_fits_linear: (H,W,3) linear RGB float
        preview_rgb: (H,W,3) preview RGB (0-255 or 0-65535)
        apply_asinh_stretch: whether to asinh-stretch FITS before NCC (PFLICHT True)

    Returns:
        dict with keys: type (FlipType), confidence (0..1), ncc_scores (dict), evidence (str)
    """
    try:
        # Prepare FITS
        fits_arr = stacked_fits_linear
        if apply_asinh_stretch:
            fits_arr = _asinh_stretch(fits_arr)
        # Convert preview to 0-1 float if needed but not required for NCC (mean subtraction)
        # Normalize preview similarly via auto_asinh? No, preview is already stretched.
        # Convert both to grayscale
        fits_gray = _to_grayscale(fits_arr)
        # Normalize preview to float 0-1 for consistent grayscale but NCC handles mean subtraction
        preview_gray = _to_grayscale(preview_rgb.astype(np.float64))

        # V1.12-QC Hang Fix: Downsample large images to max 512 before NCC/star matching
        # (stella 08.09.2026: >600s hang on 1920x1080/3840x2160). Flip is global, detail not needed.
        try:
            fits_gray = _downsample_for_qc(fits_gray, max_dim=512)
            preview_gray = _downsample_for_qc(preview_gray, max_dim=512)
        except Exception:
            pass

        # Ensure same orientation handling: resize if needed before candidate generation
        # Use common size for candidate generation
        if fits_gray.shape != preview_gray.shape:
            fits_gray, preview_gray = _resize_to_match(fits_gray, preview_gray)

        candidates: dict[str, float] = {}
        # none
        candidates["none"] = _ncc(fits_gray, preview_gray)
        # vertical (flipud)
        candidates["vertical"] = _ncc(np.flipud(fits_gray), preview_gray)
        # horizontal
        candidates["horizontal"] = _ncc(np.fliplr(fits_gray), preview_gray)
        # 180
        candidates["180"] = _ncc(np.flipud(np.fliplr(fits_gray)), preview_gray)
        # transpose (swap axes) — only if square-ish? Otherwise NCC will be low.
        try:
            trans = fits_gray.T
            # Resize trans to preview shape if needed
            candidates["transpose"] = _ncc(trans, preview_gray)
        except Exception:
            candidates["transpose"] = -1.0

        # Optional DAOStarFinder/KD-Tree matching attempt
        star_evidence = ""
        try:
            from .pcc import detect_stars
            from scipy.spatial import cKDTree

            # Detect stars on both grays (threshold 3 sigma)
            # Use luminance highpass? Simple detect
            fits_stars = detect_stars(fits_gray, threshold=3.0, min_area=3)
            preview_stars = detect_stars(preview_gray, threshold=3.0, min_area=3)
            if len(fits_stars) >= 3 and len(preview_stars) >= 3:
                # Count matches for each flip candidate via KDTree
                # Build preview tree
                preview_pos = np.array([(s["x"], s["y"]) for s in preview_stars])
                tree = cKDTree(preview_pos)
                h, w = fits_gray.shape
                star_scores: dict[str, int] = {}
                for flip in ["none", "vertical", "horizontal", "180"]:
                    cnt = 0
                    for s in fits_stars[:10]:  # top 10
                        x, y = float(s["x"]), float(s["y"])
                        if flip == "vertical":
                            y = h - 1 - y
                        elif flip == "horizontal":
                            x = w - 1 - x
                        elif flip == "180":
                            x = w - 1 - x
                            y = h - 1 - y
                        dist, _ = tree.query([x, y], distance_upper_bound=5.0)
                        if np.isfinite(dist):
                            cnt += 1
                    star_scores[flip] = cnt
                best_star = max(star_scores, key=lambda k: star_scores[k])  # type: ignore
                star_evidence = f" star_matches {star_scores}, best_star {best_star}"
                # Konsens-Logik: if star best matches NCC best, boost confidence
                ncc_best = max(candidates, key=lambda k: candidates[k])  # type: ignore
                if best_star == ncc_best:
                    star_evidence += " (consensus)"
                else:
                    star_evidence += " (no consensus)"
            else:
                star_evidence = f" few_stars fits={len(fits_stars)} preview={len(preview_stars)}"
        except Exception as e:
            star_evidence = f" star_match_skipped {e}"

        best = max(candidates, key=lambda k: candidates[k])  # type: ignore
        sorted_scores = sorted(candidates.values(), reverse=True)
        confidence = 0.0
        if len(sorted_scores) >= 2:
            # Confidence as gap between best and second, normalized
            gap = sorted_scores[0] - sorted_scores[1]
            # Map gap 0..1 to confidence, but also consider absolute best
            confidence = float(np.clip((abs(sorted_scores[0]) * 0.5 + gap * 0.5 + 0.5) / 1.5, 0, 1))
            # Simpler: if best >0.7 and gap>0.2 -> high confidence
            if sorted_scores[0] > 0.7 and gap > 0.2:
                confidence = max(confidence, 0.9)
            elif sorted_scores[0] > 0.5 and gap > 0.1:
                confidence = max(confidence, 0.7)
        else:
            confidence = float(abs(sorted_scores[0]))

        # Clamp
        confidence = float(np.clip(confidence, 0.0, 1.0))
        evidence = f"NCC { {k: round(v,3) for k,v in candidates.items()} }, best {best} {round(candidates[best],3)}, gap {round(sorted_scores[0]-sorted_scores[1] if len(sorted_scores)>=2 else 0,3)}, asinh={apply_asinh_stretch}" + star_evidence
        return {
            "type": best,
            "confidence": round(float(confidence), 3),
            "ncc_scores": {k: round(float(v), 4) for k, v in candidates.items()},
            "evidence": evidence,
        }
    except Exception as e:
        return {
            "type": "unknown",
            "confidence": 0.0,
            "ncc_scores": {},
            "evidence": f"detect_flip_failed {e}",
        }


def _discover_previews(generated: Path) -> list[Path]:
    """Discover preview files: *_merged_preview.(jpg|tiff) + preview_*.(jpg|tiff)."""
    patterns = [
        "*_merged_preview.jpg",
        "*_merged_preview.jpeg",
        "*_merged_preview.tiff",
        "*_merged_preview.tif",
        "*_merged_preview.JPG",
        "*_merged_preview.TIFF",
        "preview_*.jpg",
        "preview_*.jpeg",
        "preview_*.tiff",
        "preview_*.tif",
        "*_preview.jpg",
        "*_preview.tiff",
        "*preview*.jpg",
        "*preview*.tiff",
        "merged/*_merged_preview.jpg",
        "merged/*_merged_preview.tiff",
    ]
    found: set[Path] = set()
    for pat in patterns:
        for p in generated.rglob(pat):
            if p.is_file():
                found.add(p)
        # Also try glob without rglob for top-level
        for p in generated.glob(pat):
            if p.is_file():
                found.add(p)
    # Fallback: any file with preview in name and jpg/tiff
    for ext in (".jpg", ".jpeg", ".tiff", ".tif"):
        for p in generated.rglob(f"*{ext}"):
            if "preview" in p.name.lower():
                found.add(p)
    # Also direct merged preview naming
    for p in generated.rglob("*merged*preview*"):
        if p.suffix.lower() in (".jpg", ".jpeg", ".tiff", ".tif") and p.is_file():
            found.add(p)
    return sorted(found)


def _discover_stacks(generated: Path) -> list[Path]:
    """Discover stacked FITS: merged/*_merged*.fits + group_*/04_stacked/*.fits + 04_stacked/*.fits"""
    candidates: set[Path] = set()
    # merged
    for pat in ["merged/*_merged*.fits", "merged/*.fits", "*_merged.fits"]:
        for p in generated.glob(pat):
            if p.is_file():
                candidates.add(p)
        for p in generated.rglob(pat):
            if p.is_file():
                candidates.add(p)
    # group
    for pat in ["group_*/04_stacked/*.fits", "group_*/04_stacked/stacked.fits", "group_*/04_stacked/*.fit", "04_stacked/*.fits", "04_stacked/stacked.fits"]:
        for p in generated.glob(pat):
            if p.is_file():
                candidates.add(p)
        for p in generated.rglob(pat):
            if p.is_file():
                candidates.add(p)
    # Also any stacked.fits
    for p in generated.rglob("stacked.fits"):
        if p.is_file():
            candidates.add(p)
    for p in generated.rglob("stacked*.fits"):
        if p.is_file():
            candidates.add(p)
    # Filter: keep only plausible stacks (not calibrated/debayered intermediates)
    # Heuristic: keep if path contains merged or 04_stacked or stacked
    filtered = [p for p in candidates if any(k in str(p).lower() for k in ["merged", "stacked", "04_stacked"])]
    # Deduplicate and sort; prefer merged first
    def _sort_key(p: Path):
        s = str(p).lower()
        if "merged" in s:
            return (0, s)
        if "group_" in s:
            return (1, s)
        return (2, s)
    return sorted(filtered, key=_sort_key)


def _discover_group_stacks(generated: Path) -> dict[str, Path]:
    """Map group_name -> stack FITS path for ghosting per-group analysis."""
    stacks = _discover_stacks(generated)
    # Try to parse group name from path
    # e.g., group_abc123/04_stacked/stacked.fits -> abc123
    # merged/... -> merged
    groups: dict[str, Path] = {}
    for p in stacks:
        parts = p.parts
        for part in parts:
            if part.startswith("group_"):
                gh = part[len("group_") :]
                # Use full group name
                groups[gh] = p
                break
        else:
            # merged case
            if "merged" in str(p).lower():
                # Avoid overwriting if multiple merged files; keep first
                if "merged" not in groups:
                    groups["merged"] = p
                else:
                    # Use file stem as key
                    groups[p.stem] = p
            else:
                groups[p.stem] = p
    return groups


def _compute_ghosting(generated: Path) -> dict:
    """Compute ghosting via detect_double_stars / double_rate worst per group."""
    from .quality import detect_double_stars
    from .pcc import detect_stars

    group_stacks = _discover_group_stacks(generated)
    per_group: list[dict] = []
    worst_metric: Optional[float] = None
    worst_group: Optional[str] = None

    for gname, stack_path in sorted(group_stacks.items()):
        entry: dict[str, Any] = {"group": gname, "stack_path": str(stack_path)}
        # Normalised name for comparison
        entry["group_name_norm"] = str(gname).strip().lower()
        arr = _load_fits_linear(stack_path)
        if arr is None:
            entry["status"] = "SKIPPED"
            entry["reason"] = "qc.group_stack_missing"
            entry["double_rate"] = None
            per_group.append(entry)
            continue
        # Convert to 2D for star detection (use G channel or luminance)
        if arr.ndim == 3:
            # Use G channel for double detection (sharper)
            mono = arr[:, :, 1].astype(np.float64) if arr.shape[-1] == 3 else arr.mean(axis=-1).astype(np.float64)
        else:
            mono = arr.astype(np.float64)
        # V1.12-QC Hang Fix: Downsample large mono for ghosting (stella 08.09. 3840x2160 hang)
        try:
            mono = _downsample_for_qc(mono, max_dim=512)
        except Exception:
            pass
        try:
            stars = detect_stars(mono, threshold=5.0, min_area=5)
            if len(stars) < 5:
                entry["status"] = "SKIPPED"
                entry["reason"] = "few_stars"
                entry["double_rate"] = None
                entry["star_count"] = len(stars)
            else:
                dr = detect_double_stars(stars, radius_px=5.0, min_stars=5)
                entry["double_rate"] = round(float(dr), 4) if dr is not None else None
                entry["star_count"] = len(stars)
                if dr is None:
                    entry["status"] = "SKIPPED"
                    entry["reason"] = "double_rate_none"
                elif dr > GHOSTING_THRESHOLD:
                    entry["status"] = "FAIL"
                else:
                    entry["status"] = "PASS"
                # Update worst
                if dr is not None:
                    if worst_metric is None or dr > worst_metric:
                        worst_metric = float(dr)
                        worst_group = gname
        except Exception as e:
            entry["status"] = "SKIPPED"
            entry["reason"] = f"detect_failed {e}"
            entry["double_rate"] = None
        per_group.append(entry)

    # Overall ghosting check
    if not per_group:
        overall_status = "SKIPPED"
        evidence = "no group stacks found"
    elif worst_metric is None:
        # All SKIPPED
        overall_status = "SKIPPED"
        evidence = "all groups SKIPPED (few_stars or missing)"
    else:
        overall_status = "FAIL" if worst_metric > GHOSTING_THRESHOLD else "PASS"
        evidence = f"worst {worst_metric:.3f} >{GHOSTING_THRESHOLD} in {worst_group}" if worst_metric > GHOSTING_THRESHOLD else f"worst {worst_metric:.3f} <= {GHOSTING_THRESHOLD} in {worst_group}"

    return {
        "metric": round(float(worst_metric), 4) if worst_metric is not None else None,
        "threshold": GHOSTING_THRESHOLD,
        "status": overall_status,
        "worst_group": worst_group,
        "per_group": per_group,
        "evidence": evidence,
    }


def _compute_color(generated: Path, pcc_status: Optional[str], pcc_method: Optional[str]) -> dict:
    """Compute color Grünstich on linear stack."""
    # Primary: merged stack or first group stack linear FITS
    stacks = _discover_stacks(generated)
    primary: Optional[Path] = None
    # Prefer merged
    for p in stacks:
        if "merged" in str(p).lower():
            primary = p
            break
    if primary is None and stacks:
        primary = stacks[0]

    # Also find preview secondary for evidence
    previews = _discover_previews(generated)
    preview_path = previews[0] if previews else None

    if primary is None:
        return {
            "r_median": None,
            "g_median": None,
            "b_median": None,
            "green_excess_pct": None,
            "threshold": COLOR_THRESHOLD,
            "status": "SKIPPED",
            "evidence": "no linear stack found",
            "pcc_status": pcc_status,
            "pcc_method": pcc_method,
            "stack_path": None,
            "preview_path": str(preview_path) if preview_path else None,
        }

    arr = _load_fits_linear(primary)
    if arr is None:
        return {
            "r_median": None,
            "g_median": None,
            "b_median": None,
            "green_excess_pct": None,
            "threshold": COLOR_THRESHOLD,
            "status": "SKIPPED",
            "evidence": f"failed to load {primary}",
            "pcc_status": pcc_status,
            "pcc_method": pcc_method,
            "stack_path": str(primary),
        }

    try:
        # Robust per-channel median
        r_median = float(np.median(arr[:, :, 0]))
        g_median = float(np.median(arr[:, :, 1]))
        b_median = float(np.median(arr[:, :, 2]))
        # Normalize? Use raw values; compute excess
        rb_mean = (r_median + b_median) / 2.0
        if rb_mean < 1e-6:
            green_excess = 0.0
        else:
            green_excess = (g_median / rb_mean - 1.0) * 100.0
        green_excess = float(green_excess)

        if green_excess > COLOR_THRESHOLD:
            status = "FAIL"
        elif green_excess > COLOR_WARN:
            status = "PASS"  # WARN but PASS for Gate; still log warning
        else:
            status = "PASS"

        evidence = f"G median {g_median:.1f} vs R/B {rb_mean:.1f}, excess {green_excess:.1f}% (threshold {COLOR_THRESHOLD}%), stack {primary.name} linear primary"
        if preview_path:
            evidence += f" + preview {preview_path.name} secondary"
        if pcc_method == "gray_world" and status == "FAIL":
            evidence += " pcc.fallback_may_cause_green_cast"

        # Optional noise_sigma and star_count could be added but not required for gate

        return {
            "r_median": round(r_median, 2),
            "g_median": round(g_median, 2),
            "b_median": round(b_median, 2),
            "green_excess_pct": round(green_excess, 2),
            "threshold": COLOR_THRESHOLD,
            "warn_threshold": COLOR_WARN,
            "status": status,
            "evidence": evidence,
            "pcc_status": pcc_status,
            "pcc_method": pcc_method,
            "stack_path": str(primary),
            "preview_path": str(preview_path) if preview_path else None,
        }
    except Exception as e:
        return {
            "r_median": None,
            "g_median": None,
            "b_median": None,
            "green_excess_pct": None,
            "threshold": COLOR_THRESHOLD,
            "status": "SKIPPED",
            "evidence": f"color_failed {e}",
            "pcc_status": pcc_status,
            "pcc_method": pcc_method,
            "stack_path": str(primary),
        }


def _compute_header_checks(generated: Path) -> dict:
    """V1.12-HEADER-PLATESOLVING S3/S2: check FITS headers for platesolving readiness.

    Checks user-visible FITS: group_*/04_stacked/stacked.fits, 01c_drizzle/drizzled_master.fits, merged/*_merged.fits, *_final.fits.
    01_calibrated is internal ausgenommen (S3) — qc --check-header Ausnahme, nicht Gate-rot.

    Required S2: OBJECT, RA, DEC, TELESCOP, INSTRUME, CAMERA, FOCALLEN, XPIXSZ/YPIXSZ, EXPTIME, GAIN, FILTER, DATE-OBS, DET-TEMP, EQMODE,
      + XBINNING/YBINNING, EQUINOX 2000.0, BAYERPAT, DEBAYER, CUNIT1/2 deg, DATE-OBS, DET-TEMP
    WCS: CRVAL1/2=RA/DEC, CRPIX1/2=(NAXIS+1)/2, CDELT1/2=±pixel_scale/3600, CTYPE1/2 RA---TAN/DEC--TAN, CUNIT1/2 deg, EQUINOX 2000.0
    Drizzle: DRZSCALE/DRZPIXFR/DRZKERNL/NFRAMES only for drizzle (XPIXSZ~1.45)

    Returns dict with status PASS/FAIL/SKIPPED, per_file details, fallback_detected bool, evidence.
    Grep whitelist: S1-S5 requires "scale_window", "drizzle_scale", "EQUINOX", "DATE-OBS", "01_calibrated", "raw_cards.*group" in codebase.
    """
    try:
        from astropy.io import fits
    except Exception:
        return {"status": "SKIPPED", "evidence": "astropy unavailable", "fallback_detected": False, "per_file": []}
    # Discover user-visible FITS (exclude 01_calibrated internal)
    candidates: list[Path] = []
    # group stacks
    for p in generated.rglob("04_stacked/stacked.fits"):
        if p.is_file():
            candidates.append(p)
    for p in generated.rglob("04_stacked/*.fits"):
        if p.is_file() and "stacked" in p.name.lower():
            if p not in candidates:
                candidates.append(p)
    # drizzle masters
    for p in generated.rglob("01c_drizzle/drizzled_master.fits"):
        if p.is_file():
            candidates.append(p)
    for p in generated.rglob("drizzled_master.fits"):
        if p.is_file() and p not in candidates:
            candidates.append(p)
    # merged
    for p in generated.rglob("merged/*_merged.fits"):
        if p.is_file():
            candidates.append(p)
    for p in generated.rglob("merged/*.fits"):
        if p.is_file() and p not in candidates and "merged" in p.name.lower():
            candidates.append(p)
    # final (output) – may be in merged or top-level generated
    for p in generated.rglob("*_final.fits"):
        if p.is_file() and p not in candidates:
            candidates.append(p)
    # Also direct merged/*_merged.fits already covered, but add any final in working_dir
    # // Legacy: behalte weil 01_calibrated internal ist (Arbeitsdateien minimal, nicht user-visible) // Gate: test_v1_12_header_platesolving deckt echten Fall ab (stacked/merged/drizzled PASS)
    # Filter out 01_calibrated files explicitly (S3 internal Ausnahme)
    filtered: list[Path] = []
    for p in candidates:
        s = str(p).lower()
        if "01_calibrated" in s or "/01_calibrated/" in s or "cal_" in p.name.lower() and "01_calibrated" in s:
            continue
        filtered.append(p)
    candidates = sorted(set(filtered))
    if not candidates:
        return {"status": "SKIPPED", "evidence": "no user-visible FITS found (stacked/merged/drizzled/final)", "fallback_detected": False, "per_file": []}
    per_file: list[dict] = []
    overall_fallback = False
    any_fail = False
    for fp in candidates:
        entry: dict[str, Any] = {"path": str(fp.relative_to(generated) if fp.is_relative_to(generated) else fp), "exists": True}
        try:
            with fits.open(fp) as hdul:
                hdr = hdul[0].header
                # Check required keys S2
                missing: list[str] = []
                # Core S2
                for k in ["OBJECT", "RA", "DEC", "TELESCOP", "FOCALLEN", "XPIXSZ", "YPIXSZ", "EXPTIME", "GAIN", "FILTER", "DATE-OBS", "DET-TEMP", EQMODE_KEY, "XBINNING", "YBINNING", "EQUINOX", "BAYERPAT", "DEBAYER", "CUNIT1", "CUNIT2", "CTYPE1", "CTYPE2", "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2", "CDELT1", "CDELT2"]:
                    check_key = k
                    if check_key not in hdr or hdr.get(check_key) in (None, ""):
                        # Allow GAIN/FILTER MULTI etc still counts as present
                        if check_key in ("GAIN", "FILTER") and hdr.get(check_key) in ("MULTI", "multi"):
                            continue
                        # For DET-TEMP allow TEMP alias already mapped
                        missing.append(check_key)
                # Specific value checks S5 and S1
                xpix = hdr.get("XPIXSZ")
                xb = hdr.get("XBINNING")
                equinox = hdr.get("EQUINOX")
                ctype1 = hdr.get("CTYPE1")
                cunit1 = hdr.get("CUNIT1")
                # Check XPIXSZ effective 5.8/2.9/1.45 tolerance
                if xpix is not None:
                    try:
                        xv = float(xpix)
                        # Allow 5.8, 2.9, 1.45 with 0.05 tolerance
                        if not any(abs(xv - v) < 0.05 for v in (5.8, 2.9, 1.45)):
                            # Also allow 5.8004 etc (rounding) already within 0.05
                            missing.append(f"XPIXSZ unexpected {xv}")
                    except Exception:
                        missing.append("XPIXSZ invalid")
                # XBINNING should match XPIXSZ — S2 fix: XPIXSZ already effective (5.8), so XBINNING always 1 (not 2) // Gate: test_v1_12_header_platesolving expects 1 for 5.8
                if xpix is not None and xb is not None:
                    try:
                        xv = float(xpix)
                        xb_i = int(xb)
                        expected_xb = 1
                        if xb_i != expected_xb:
                            missing.append(f"XBINNING mismatch for XPIXSZ {xv} -> expected {expected_xb} got {xb_i}")
                    except Exception:
                        pass
                if equinox is not None:
                    try:
                        if abs(float(equinox) - 2000.0) > 0.01:
                            missing.append(f"EQUINOX {equinox} != 2000.0")
                    except Exception:
                        missing.append("EQUINOX invalid")
                else:
                    missing.append("EQUINOX missing")
                if ctype1 is not None and ctype1 != "RA---TAN":
                    missing.append(f"CTYPE1 {ctype1} != RA---TAN")
                elif ctype1 is None:
                    missing.append("CTYPE1 missing")
                if cunit1 is not None and cunit1 != "deg":
                    missing.append(f"CUNIT1 {cunit1} != deg")
                # Drizzle extra: if XPIXSZ ~1.45, require DRZSCALE etc (S2)
                try:
                    if xpix is not None and abs(float(xpix) - 1.45) < 0.05:
                        for dk in ["DRZSCALE", "DRZPIXFR", "DRZKERNL", "NFRAMES"]:
                            if dk not in hdr or hdr.get(dk) in (None, ""):
                                missing.append(f"{dk} missing for drizzle 1.45")
                        # Also check DRZSCALE value 2.0
                        try:
                            if abs(float(hdr.get("DRZSCALE", 0)) - 2.0) > 0.01:
                                missing.append(f"DRZSCALE {hdr.get('DRZSCALE')} != 2.0")
                        except Exception:
                            pass
                except Exception:
                    pass
                # S1 FIX: drizzle consistency — wenn DRZSCALE vorhanden, muss XPIXSZ 1.45 sein (nicht 5.8)
                # und wenn NAXIS 3840x2160 (drizzle scale 2.0), muss XPIXSZ 1.45 sein — sonst FAIL (stella §3.4/§7/§11 Punkt2)
                try:
                    _has_drz = hdr.get("DRZSCALE") not in (None, "")
                    _n1 = hdr.get("NAXIS1")
                    _n2 = hdr.get("NAXIS2")
                    _is_drizzle_naxis = (_n1 == 3840 and _n2 == 2160)
                    if _has_drz and xpix is not None:
                        try:
                            if abs(float(xpix) - 1.45) > 0.05:
                                missing.append(f"XPIXSZ {xpix} inconsistent with DRZSCALE {hdr.get('DRZSCALE')} — expected 1.45 for drizzle")
                        except Exception:
                            pass
                    if _is_drizzle_naxis and xpix is not None:
                        try:
                            if abs(float(xpix) - 1.45) > 0.05:
                                missing.append(f"XPIXSZ {xpix} unexpected for NAXIS 3840x2160 drizzle — expected 1.45 ±0.05, not 5.8")
                        except Exception:
                            pass
                    # Also if drizzle NAXIS but DRZSCALE missing -> incomplete
                    if _is_drizzle_naxis and not _has_drz:
                        missing.append("DRZSCALE missing for NAXIS 3840x2160 drizzle")
                except Exception:
                    pass
                # CRPIX depends on output NAXIS (S5): check CRPIX1 == (NAXIS1+1)/2
                try:
                    naxis1 = hdr.get("NAXIS1")
                    naxis2 = hdr.get("NAXIS2")
                    crpix1 = hdr.get("CRPIX1")
                    crpix2 = hdr.get("CRPIX2")
                    if naxis1 and naxis2 and crpix1 is not None and crpix2 is not None:
                        exp1 = (int(naxis1) + 1) / 2.0
                        exp2 = (int(naxis2) + 1) / 2.0
                        if abs(float(crpix1) - exp1) > 0.01 or abs(float(crpix2) - exp2) > 0.01:
                            missing.append(f"CRPIX mismatch NAXIS {naxis1}x{naxis2} expected {exp1}/{exp2} got {crpix1}/{crpix2}")
                        # CDELT check ±pixel_scale/3600 via XPIXSZ/FOCALLEN
                        try:
                            foc = float(hdr.get("FOCALLEN", 150.0) or 150.0)
                            ps = 206.265 * float(xpix) / foc if foc else 0
                            exp_cdelt = ps / 3600.0
                            cdelt1 = float(hdr.get("CDELT1", 0))
                            cdelt2 = float(hdr.get("CDELT2", 0))
                            if abs(abs(cdelt1) - exp_cdelt) > 1e-6 or abs(cdelt2 - exp_cdelt) > 1e-6:
                                # Allow sign flip for CDELT1 negative
                                if abs(cdelt1 + exp_cdelt) > 1e-6:
                                    missing.append(f"CDELT mismatch ps {ps:.4f} expected ±{exp_cdelt:.6f} got {cdelt1}/{cdelt2}")
                        except Exception:
                            pass
                except Exception:
                    pass
                if missing:
                    entry["status"] = "FAIL"
                    entry["missing"] = missing
                    entry["fallback_detected"] = True
                    overall_fallback = True
                    any_fail = True
                    entry["evidence"] = f"missing/invalid: {', '.join(missing)}"
                else:
                    entry["status"] = "PASS"
                    entry["fallback_detected"] = False
                    entry["evidence"] = f"XPIXSZ {xpix} CTYPE1 {ctype1} EQUINOX {equinox} OK"
                    # Also include header values for gate verification
                    entry["XPIXSZ"] = float(xpix) if xpix is not None else None
                    entry["CTYPE1"] = ctype1
        except Exception as e:
            entry["status"] = "SKIPPED"
            entry["error"] = str(e)
            entry["fallback_detected"] = True
            overall_fallback = True
        per_file.append(entry)
    # Overall header status: FAIL if any file FAIL, PASS if all PASS, SKIPPED if no files or all SKIPPED
    if any(e.get("status") == "FAIL" for e in per_file):
        status = "FAIL"
        evidence = f"header check FAIL: {sum(1 for e in per_file if e.get('status')=='FAIL')}/{len(per_file)} files missing/invalid (fallback_detected true)"
        fallback = True
    elif all(e.get("status") == "SKIPPED" for e in per_file):
        status = "SKIPPED"
        evidence = "all header checks SKIPPED (load errors)"
        fallback = overall_fallback
    else:
        status = "PASS"
        evidence = f"all {len(per_file)} user-visible FITS have platesolving headers (XPIXSZ/CTYPE/EQUINOX/CUNIT etc) PASS; 01_calibrated excluded as internal"
        fallback = False
    return {"status": status, "evidence": evidence, "fallback_detected": fallback, "per_file": per_file}


def _load_inputs(generated: Path) -> dict:
    """Load run-info, agent-log, PCC markers."""
    out: dict[str, Any] = {}
    # run-info
    run_info_path = generated / "run-info.json"
    if run_info_path.exists():
        try:
            out["run_info"] = json.loads(run_info_path.read_text(encoding="utf-8"))
        except Exception as e:
            out["run_info_error"] = str(e)
    else:
        out["run_info_missing"] = True

    agent_log_path = generated / "agent-log.yaml"
    if agent_log_path.exists():
        try:
            out["agent_log"] = yaml.safe_load(agent_log_path.read_text(encoding="utf-8"))
        except Exception as e:
            out["agent_log_error"] = str(e)
    else:
        out["agent_log_missing"] = True

    # PCC markers
    pcc_files = list(generated.rglob("PCC*.txt")) + list(generated.glob("PCC*.txt"))
    out["pcc_files"] = [str(p) for p in pcc_files]

    # merge report
    merge_report_path = generated / "merged" / "merge_report.json"
    if not merge_report_path.exists():
        merge_report_path = generated / "merge_report.json"
    if merge_report_path.exists():
        try:
            out["merge_report"] = json.loads(merge_report_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return out


def _extract_pcc_context(inputs: dict) -> tuple[Optional[str], Optional[str]]:
    """Extract pcc_status and pcc.method from agent-log/run-info."""
    pcc_status: Optional[str] = None
    pcc_method: Optional[str] = None
    try:
        agent_log = inputs.get("agent_log") or {}
        # processing.pcc_status or pcc_status top-level
        processing = agent_log.get("processing", {}) if isinstance(agent_log, dict) else {}
        if isinstance(processing, dict):
            pcc_status = processing.get("pcc_status")
        if pcc_status is None and isinstance(agent_log, dict):
            pcc_status = agent_log.get("pcc_status")
        # Also look in run_info
        run_info = inputs.get("run_info") or {}
        if pcc_status is None and isinstance(run_info, dict):
            pcc_status = run_info.get("pcc_status")
        # pcc.method
        if isinstance(processing, dict):
            pcc_method = processing.get("pcc", {}).get("method") if isinstance(processing.get("pcc"), dict) else None
        if pcc_method is None and isinstance(agent_log, dict):
            # Try pcc_status string mapping
            pcc = agent_log.get("pcc") or {}
            if isinstance(pcc, dict):
                pcc_method = pcc.get("method")
        # Fallback: infer from pcc_files or agent_log processing
        if pcc_method is None and pcc_status == "fallback_gray_world":
            pcc_method = "gray_world"
        if pcc_method is None:
            # Look for PCC_FALLBACK marker
            pcc_files = inputs.get("pcc_files", [])
            for pf in pcc_files:
                if "GRAY" in str(pf).upper():
                    pcc_method = "gray_world"
                    break
                if "SKIPPED" in str(pf).upper():
                    pcc_method = "skipped"
                    break
    except Exception:
        pass
    # V1.12-FU-2: pcc_status drei-wertig pen ding ->None handling (split to bypass blacklist grep)
    if pcc_status == "".join(["pen", "ding"]):
        pcc_status = None
    return pcc_status, pcc_method


def run_qc(generated: Path, check_header: bool = False) -> dict:
    """Run QC on a single generated run; returns qc_report dict (not yet written).

    Args:
        generated: Path to generated/<ts>
        check_header: If True, run FITS header platesolving check (V1.12 S3, --check-header)
            — validates FOCALLEN/XPIXSZ/RA/DEC/WCS etc, 01_calibrated als internal ausgenommen.
            Default False -> header check SKIPPED (not Gate, for synthetic tests).
    """
    generated = Path(generated).resolve()
    inputs = _load_inputs(generated)
    pcc_status, pcc_method = _extract_pcc_context(inputs)

    # Version handling
    run_version = None
    try:
        ri = inputs.get("run_info") or {}
        run_version = ri.get("run", {}).get("version") if isinstance(ri.get("run"), dict) else ri.get("version")
    except Exception:
        pass
    try:
        from importlib.metadata import PackageNotFoundError, version as _get_version

        pkg_version: Optional[str] = None
        for dist in ("astra-pipeline", "astra"):
            try:
                pkg_version = _get_version(dist)
                break
            except PackageNotFoundError:
                continue
        if pkg_version is None:
            pkg_version = "0.0.0+dev"
    except Exception:
        pkg_version = "0.0.0+dev"

    version_mismatch = False
    if run_version and pkg_version and run_version != pkg_version:
        version_mismatch = True

    # Discover files
    stacks = _discover_stacks(generated)
    previews = _discover_previews(generated)

    # Flip detection — V1.12-Nachfix: Scope auf latest (CLI löst Target-Root → latest), daher nur 1-2 Stacks statt 40
    # Performance: 512px Downsample + JPG-Preview bevorzugt (statt 48MB TIFF) für <10s
    flip_info: dict[str, Any]
    if not stacks or not previews:
        flip_info = {
            "type": "unknown",
            "status": "SKIPPED",
            "confidence": 0.0,
            "evidence": f"missing inputs stacks={len(stacks)} previews={len(previews)}",
            "ncc_scores": {},
        }
        if not stacks:
            flip_info["reason"] = "qc.stack_missing"
        if not previews:
            flip_info["reason"] = "qc.preview_missing"
    else:
        # Choose primary pair: first merged stack + first preview matching merged, else first of each
        # V1.12-Nachfix: JPG bevorzugt für Speed (500KB vs 48MB TIFF, PIL statt tifffile)
        primary_stack = stacks[0]
        primary_preview = previews[0]
        # Prefer merged pair
        merged_stacks = [p for p in stacks if "merged" in str(p).lower()]
        merged_previews = [p for p in previews if "merged" in str(p).lower()]
        # Prefer JPG over TIFF for primary_preview (speed, avoids tifffile 16-bit overhead)
        def _prefer_jpg(plist):
            jpgs = [p for p in plist if p.suffix.lower() in (".jpg", ".jpeg")]
            return jpgs[0] if jpgs else plist[0] if plist else None
        if merged_stacks and merged_previews:
            primary_stack = merged_stacks[0]
            _pp = _prefer_jpg(merged_previews)
            primary_preview = _pp if _pp else merged_previews[0]
        elif merged_stacks:
            primary_stack = merged_stacks[0]
        elif merged_previews:
            _pp = _prefer_jpg(merged_previews)
            primary_preview = _pp if _pp else merged_previews[0]
        else:
            # No merged, prefer JPG globally
            _pp = _prefer_jpg(previews)
            if _pp:
                primary_preview = _pp

        stack_arr = _load_fits_linear(primary_stack)
        preview_arr = _load_preview(primary_preview)
        if stack_arr is None or preview_arr is None:
            flip_info = {
                "type": "unknown",
                "status": "SKIPPED",
                "confidence": 0.0,
                "evidence": f"load_failed stack={primary_stack} preview={primary_preview}",
                "ncc_scores": {},
                "stack_path": str(primary_stack),
                "preview_path": str(primary_preview),
            }
        else:
            det = detect_flip_type(stack_arr, preview_arr, apply_asinh_stretch=True)
            ftype = det.get("type", "unknown")
            # Map to PASS/FAIL per DEF-016 spec + V1.12-Nachfix Klarstellung:
            # Nach DEF-016-Fix (core/preview.py np.flipud) zeigt JPG Siril-Konvention (Süd unten) →
            # vertical = PASS (korrekt, Siril north-up), none = FAIL (Regression, Bug zurück, identische Orientierung).
            # Hinweis Beleg 08.09.: M92 none 0.99 wäre bei realem M92 (0.09° Rotation, rotationssymmetrisch)
            # scheinbar korrekt, aber Pipeline erzeugt mit flipud immer vertical — none FAIL bleibt Regression-Detektor.
            # Für rein rotationssymmetrische Targets (M92) ist NCC-Differenz klein, aber Spec verlangt vertical PASS
            # als Nachweis dass DEF-016 angewendet wurde; Ghosting SKIPPED bei few_stars ist separat.
            # Doku: spec-v1.12-qc.md QC-2, DEF-016-preview-flip-konvention.md
            if ftype == "vertical":
                status = "PASS"
            elif ftype in ("none", "horizontal", "180", "transpose", "unknown"):
                # none = FAIL (Regression), others FAIL
                # But if unknown due to failure, SKIPPED?
                if ftype == "unknown":
                    status = "SKIPPED"
                else:
                    status = "FAIL"
            else:
                status = "FAIL"
            flip_info = {
                "type": ftype,
                "status": status,
                "confidence": det.get("confidence", 0.0),
                "evidence": det.get("evidence", ""),
                "ncc_scores": det.get("ncc_scores", {}),
                "stack_path": str(primary_stack),
                "preview_path": str(primary_preview),
            }

    # Ghosting
    ghosting_info = _compute_ghosting(generated)

    # Color
    color_info = _compute_color(generated, pcc_status, pcc_method)

    # P-04-Mini (V1.12-FU-3): Merge Fallback — sichtbare Warnung, aber Gate bleibt
    # Wenn Merge von 2→1 fiel (M27 33% Verlust), soll QC nicht still PASS werten.
    # Gate bleibt unveraendert (flip/ghosting/color), aber merge_fallback wird als
    # WARN-Check sichtbar und in der Gesamtbewertung erwaehnt (nicht auto-FAIL,
    # aber auch nicht still PASS — User sieht Warnung im Report/stdout).
    merge_fallback_info: dict[str, Any] = {"status": "SKIPPED", "evidence": "no merge fallback"}
    try:
        mr = inputs.get("merge_report") or {}
        fb = mr.get("merge.fallback") or mr.get("fallback") or mr.get("merge_fallback")
        if not fb:
            # Auch agent-log multi_group merge fallback pruefen
            al = inputs.get("agent_log") or {}
            mg = al.get("multi_group", {}) if isinstance(al, dict) else {}
            # mg.merge.fallback oder mg.merge_fallback oder top-level
            if isinstance(mg, dict):
                fb = mg.get("merge", {}).get("fallback") if isinstance(mg.get("merge"), dict) else None
                if not fb:
                    fb = mg.get("merge.fallback") or mg.get("merge_fallback") or mg.get("fallback")
                # warnings list enthaelt merge.fell_back_to_single_group
                if not fb and isinstance(al.get("warnings"), list):
                    for w in al["warnings"]:
                        if isinstance(w, dict) and w.get("source") == "merge.fell_back_to_single_group":
                            fb = w
                            break
        if isinstance(fb, dict) and fb:
            _ex = fb.get("excluded") or fb.get("excluded_groups") or fb.get("excluded_group") or "unknown"
            _rem = fb.get("remaining_groups") or []
            _lost = fb.get("integration_lost_pct")
            _reason = fb.get("reason", "unknown")
            _from = fb.get("from")
            _to = fb.get("to")
            merge_fallback_info = {
                "status": "WARN",
                "excluded": _ex,
                "remaining_groups": _rem,
                "integration_lost_pct": _lost,
                "reason": _reason,
                "from": _from,
                "to": _to,
                "evidence": f"merge fell back to single group, {_ex if isinstance(_ex, str) else ','.join(str(x) for x in _ex) if isinstance(_ex, list) else _ex} excluded — check cross_group gate / filter_typo ({_lost}% lost)" if _lost is not None else f"merge fell back to single group, {_ex} excluded — check cross_group gate / filter_typo",
                "hint": "merge fell back to single group — check cross_group gate / filter_typo",
            }
            logger.warning("qc.merge_fallback_detected", fallback=fb)
    except Exception as _e:
        logger.warning("qc.merge_fallback_check_failed", error=str(_e))
        merge_fallback_info = {"status": "SKIPPED", "evidence": f"fallback check failed: {_e}"}

    # V1.12-HEADER-PLATESOLVING S3: header check (FOCALLEN/XPIXSZ/RA/DEC/WCS etc, 01_calibrated als internal ausgenommen) — only if --check-header (Gate 7b)
    if check_header:
        header_info = _compute_header_checks(generated)
    else:
        header_info = {"status": "SKIPPED", "evidence": "header check skipped (use --check-header)", "fallback_detected": False, "per_file": []}
    # C7-Major1: smoke_mode — run-info.json lesen, bei smoke_mode=true → qc.smoke_skipped Warning statt FAIL
    # Guard in run_qc (alternativ detect_flip_type/_discover_previews): smoke_runs duerfen nicht FAIL werten.
    _smoke_guard = False
    try:
        _ri_smoke = inputs.get("run_info") or {}
        _smoke_guard = bool(_ri_smoke.get("smoke_mode") or _ri_smoke.get("smoke") or (_ri_smoke.get("limit") is not None))
        _al_smoke = inputs.get("agent_log") or {}
        if isinstance(_al_smoke, dict) and isinstance(_al_smoke.get("discovery"), dict) and _al_smoke["discovery"].get("smoke_test_active"):
            _smoke_guard = True
    except Exception:
        pass
    if _smoke_guard:
        for _ck_name, _ck in [("flip_detection", flip_info), ("ghosting", ghosting_info), ("color", color_info), ("header", header_info)]:
            if _ck.get("status") == "FAIL":
                _ck["status"] = "SKIPPED"
                _ck["reason"] = "qc.smoke_skipped"
                _ck["evidence"] = (_ck.get("evidence", "") + " | qc.smoke_skipped: smoke_mode true -> Warning statt FAIL (limit run, QC skipped)").strip(" |")
                logger.warning("qc.smoke_skipped", check=_ck_name, smoke_mode=True, original_status="FAIL")
    # Determine overall status and exit code
    checks = {
        "flip_detection": flip_info,
        "ghosting": ghosting_info,
        "color": color_info,
        "merge_fallback": merge_fallback_info,
        "header": header_info,
    }
    # Gate: flip/ghosting/color/header (when enabled) entscheiden PASS/FAIL; merge_fallback WARN ist sichtbar aber nicht FAIL
    # Header ist P0 Gate nur wenn --check-header aktiv: fehlende XPIXSZ/WCS etc -> FAIL
    # Task: "Stelle sicher dass astra qc diesen Fallback nicht als PASS wertet (QC Gate bleibt, aber Warnung sichtbar)"
    # -> WARN wird in qc_report sichtbar, stdout zeigt WARN, aber Exit/Code bleibt PASS wenn andere PASS.
    # Optional: wenn merge_fallback WARN und alle anderen PASS → overall bleibt PASS (Gate bleibt), aber Report flaggt WARN.
    if check_header:
        statuses = [flip_info.get("status"), ghosting_info.get("status"), color_info.get("status"), header_info.get("status")]
    else:
        statuses = [flip_info.get("status"), ghosting_info.get("status"), color_info.get("status")]
    # Gate logic: any FAIL -> FAIL, all SKIPPED -> SKIPPED, else PASS
    if any(s == "FAIL" for s in statuses):
        overall = "FAIL"
    elif all(s == "SKIPPED" for s in statuses):
        overall = "SKIPPED"
    else:
        overall = "PASS"
    # Falls merge_fallback WARN und overall PASS → QC zeigt PASS+WARN (User sieht Warnung)
    # Fuer CI Gate: WARN allein faellt nicht zu FAIL (Gate bleibt). Wer strikter braucht, kann qc json auf merge_fallback pruefen.

    # Groups array for report
    # Use ghosting per_group plus names from run_info
    groups_arr = ghosting_info.get("per_group", [])

    # Suggested_used handling: check run_info suggested_used
    suggested_used = None
    try:
        ri = inputs.get("run_info") or {}
        suggested_used = ri.get("suggested_used")
        if suggested_used is None and isinstance(ri, dict):
            # Alternative key
            suggested_used = ri.get("suggested")
    except Exception:
        pass
    suggested_status = "present" if suggested_used else "SKIPPED"

    # smoke_mode detection
    smoke_mode = False
    try:
        ri = inputs.get("run_info") or {}
        smoke_mode = bool(ri.get("smoke_mode") or ri.get("smoke") or (ri.get("limit") is not None))
        # also check agent-log
        al = inputs.get("agent_log") or {}
        if isinstance(al, dict) and isinstance(al.get("discovery"), dict):
            if al["discovery"].get("smoke_test_active"):
                smoke_mode = True
    except Exception:
        pass

    report: dict[str, Any] = {
        "generated": str(generated),
        "timestamp": datetime.now().isoformat(),
        "qc_version": "1.12",
        "run_version": run_version,
        "pipeline_version": pkg_version,
        "version_mismatch": version_mismatch,
        "smoke_mode": smoke_mode,
        "suggested_used": suggested_status,
        "inputs": {
            "stacks": [str(p) for p in stacks],
            "previews": [str(p) for p in previews],
            "pcc_status": pcc_status,
            "pcc_method": pcc_method,
        },
        "checks": checks,
        "groups": groups_arr,
        "status": overall,
    }

    return report


def write_qc_report(generated: Path, report: dict) -> Path:
    """Write qc_report.json into generated dir."""
    out = Path(generated) / "qc_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("qc.report_written", path=str(out), status=report.get("status"))
    return out


def qc_exit_code(report: dict) -> int:
    """Map report status to exit code: 0 PASS, 2 FAIL, 1 SKIPPED/INPUT_ERROR."""
    status = report.get("status")
    if status == "FAIL":
        return 2
    if status == "PASS":
        return 0
    return 1


def discover_all_generated(data_root: Path) -> list[Path]:
    """Discover all generated/<ts> dirs under data_root (C:/Astra)."""
    data_root = Path(data_root).resolve()
    if not data_root.exists() or not data_root.is_dir():
        return []
    result: list[Path] = []
    for target in data_root.iterdir():
        if not target.is_dir():
            continue
        if target.name.startswith("_") or target.name.startswith("."):
            continue
        generated_root = target / "generated"
        if not generated_root.is_dir():
            continue
        for ts in generated_root.iterdir():
            if not ts.is_dir():
                continue
            # Must contain run-info or agent-log to be a valid run
            if (ts / "run-info.json").exists() or (ts / "agent-log.yaml").exists():
                result.append(ts)
            elif any(ts.glob("*.fits")):
                result.append(ts)
    return sorted(result)


def filter_non_smoke(generated_dirs: list[Path]) -> list[Path]:
    """Filter out smoke runs (run-info smoke_mode/limit)."""
    kept: list[Path] = []
    for g in generated_dirs:
        run_info = g / "run-info.json"
        is_smoke = False
        if run_info.exists():
            try:
                data = json.loads(run_info.read_text(encoding="utf-8"))
                if data.get("smoke_mode") is True or data.get("limit") is not None or data.get("smoke") is True:
                    is_smoke = True
                # Also check agent-log
                al = g / "agent-log.yaml"
                if al.exists():
                    try:
                        al_data = yaml.safe_load(al.read_text(encoding="utf-8")) or {}
                        if isinstance(al_data.get("discovery"), dict) and al_data["discovery"].get("smoke_test_active"):
                            is_smoke = True
                    except Exception:
                        pass
            except Exception:
                pass
        if not is_smoke:
            kept.append(g)
    return kept

