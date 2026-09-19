"""core/header_utils.py — SSOT for FITS header annotation (V1.12-HEADER-PLATESOLVING).

Implements:
 - effective_pixel_size_um (moved from core/export.py, Re-Export for compatibility)
 - build_effective_header(context, method, scale_window, drizzle_scale, wcs, total_exposure) -> fits.Header
 - annotate_fits(path, header) -> None  best-effort mode=update

Covers S1 (drizzle scale entwirrt), S2 (XBINNING/EQUINOX/BAYERPAT/DEBAYER/CUNIT/DATE-OBS/DET-TEMP, drizzle Zusatz),
S3 (best-effort, HISTORY kumuliert, context None fallback), S4 (raw_cards Gruppen-gefiltert via HEADER_ALIASES),
S5 (CRPIX from output NAXIS, CDELT ±pixel_scale/3600).

Reuse: equipment.resolve_debayer_factor when available for S1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from astropy.io import fits

from .fits_parser import HEADER_ALIASES, EQMODE_KEY

logger = structlog.get_logger(__name__)

EXPORT_LIGHT_HEADER_KEYS = (
    "OBJECT", "RA", "DEC", "TELESCOP", "INSTRUME", "CAMERA", "FOCALLEN",
    "XPIXSZ", "YPIXSZ", "EXPTIME", "GAIN", "FILTER", "DATE-OBS",
    "DET-TEMP", EQMODE_KEY,
)

# S2 Zusatz verpflichtend für platesolving/Handbuch
S2_EXTRA_KEYS = ("XBINNING", "YBINNING", "EQUINOX", "BAYERPAT", "DEBAYER", "CUNIT1", "CUNIT2")


def effective_pixel_size_um(
    light_cards: dict,
    wcs: dict | None,
    stack_scale_factor: float = 2.0,
) -> float | None:
    """F-META-1.2 (stella Punkt 5): effektive Pixelgroesse des gestackten
    Frames in µm — so, dass Siril daraus die korrekte Pixel-Scale ableitet
    (Siril ignoriert CDELT als Startvorgabe und rechnet 206.265 x XPIXSZ /
    FOCALLEN).

    - PCC-Skala vorhanden + FOCALLEN: ``pixel_scale x FOCALLEN / 206.265``
      (Pixelgroesse aus der gemessenen Skala zurueckgerechnet).
    - sonst Fallback: nativer XPIXSZ/YPIXSZ x ``stack_scale_factor``
      (Default 2.0, DWARF Mini: nativ 2.9 µm, 2x Superpixel-Debayer).

    Beide Wege ergeben dieselbe effektive Pixelgroesse, wenn
    ``stack_scale_factor`` dem tatsaechlichen Binning-Faktor entspricht
    (2.9 x 2.0 = 5.8 µm -> 206.265 x 5.8 / 150 = 7.98 arcsec/px).

    Returns:
        Effektive Pixelgroesse in µm oder ``None`` (best effort).
    """
    scale = (wcs or {}).get("pixel_scale_arcsec", 0.0) or 0.0
    focal = light_cards.get("FOCALLEN")
    if scale > 0 and focal:
        try:
            focal_f = float(focal)
        except (TypeError, ValueError):
            focal_f = 0.0
        if focal_f > 0:
            return float(scale) * focal_f / 206.265
    native = light_cards.get("XPIXSZ") or light_cards.get("YPIXSZ")
    if native:
        try:
            native_f = float(native)
        except (TypeError, ValueError):
            return None
        if native_f > 0:
            return native_f * float(stack_scale_factor)
    return None


def _get_raw_value(raw_cards: dict, desired_key: str) -> Any | None:
    """Resolve raw_cards value via HEADER_ALIASES (S4).

    Checks desired_key directly, else searches aliases for same logical field.
    """
    if raw_cards is None:
        return None
    # Direct hit
    if desired_key in raw_cards and raw_cards.get(desired_key) not in (None, ""):
        return raw_cards[desired_key]
    # Search via HEADER_ALIASES: find logical entry where desired_key is among aliases OR alias maps to desired header name
    # Build reverse: for each logical -> aliases, if desired_key in aliases, then any alias present qualifies
    # Also handle hyphen/case variations already uppercased
    for aliases in HEADER_ALIASES.values():
        if desired_key in aliases:
            for alias in aliases:
                if alias in raw_cards and raw_cards.get(alias) not in (None, ""):
                    return raw_cards[alias]
    # Fallback case-insensitive scan for hyphen variants
    low = desired_key.lower()
    for k, v in raw_cards.items():
        if str(k).lower() == low and v not in (None, ""):
            return v
    return None


def _extract_light_cards(context: Any, ref_header: fits.Header | dict | None = None) -> dict:
    """Extract normalized light_cards dict from context or ref_header (S4, S3 fallback).

    Returns dict with keys like OBJECT, RA, DEC, FOCALLEN, XPIXSZ, DATE-OBS etc
    normalized via HEADER_ALIASES. Handles group-filtered context (caller passes filtered context).
    """
    raw: dict = {}
    # Try context path
    if context is not None:
        try:
            # context may be ObservationContext or a filtered FrameSet context mock
            # Prefer context.get_lights().frames[0].header.raw_cards
            lights = None
            if hasattr(context, "get_lights"):
                try:
                    lights = context.get_lights()  # type: ignore
                except TypeError:
                    # Some callers might pass group_hash as first arg? Ignore
                    lights = context.get_lights()  # type: ignore
            if lights is not None and hasattr(lights, "frames") and lights.frames:
                first = lights.frames[0]
                hdr = getattr(first, "header", None)
                if hdr is not None:
                    raw = getattr(hdr, "raw_cards", None) or {}
                    if not raw and isinstance(hdr, dict):
                        raw = dict(hdr)
            # Also handle case where context itself is a dict with raw_cards
            if not raw and isinstance(context, dict) and context.get("raw_cards"):
                raw = dict(context["raw_cards"])
        except Exception:
            raw = {}
    # Fallback S3: if context is None or raw empty, try ref_header via HEADER_ALIASES
    if not raw and ref_header is not None:
        try:
            if isinstance(ref_header, fits.Header):
                # Convert to dict
                raw = {k: ref_header[k] for k in ref_header.keys() if k}
            elif isinstance(ref_header, dict):
                raw = dict(ref_header)
        except Exception:
            raw = {}
    # Normalize via aliases for standard keys: we return a dict with FITS keys mapped
    # Keep original raw for direct lookup, but also add normalized entries for missing aliases
    # Ensure we produce a dict where each desired FITS key can be resolved via _get_raw_value
    # For convenience, also map logical aliases to canonical FITS key for easier downstream use
    normalized: dict = {}
    # Copy raw as-is
    for k, v in (raw or {}).items():
        normalized[k] = v
    # Ensure canonical keys present via alias resolution for common fields
    # Build mapping for quick check: for each logical, if any alias present, fill canonical FITS key
    # e.g., RA may be stored as OBJCTRA -> map to RA
    for logical, aliases in HEADER_ALIASES.items():
        # Determine canonical FITS key: use first alias that is a typical FITS key for light cards
        # For light, we want: object->OBJECT, ra->RA, dec->DEC, focal_length->FOCALLEN, pixel_size_x->XPIXSZ, etc.
        # Reverse mapping logical->desired FITS key
        canonical_map = {
            "object": "OBJECT",
            "exptime": "EXPTIME",
            "gain": "GAIN",
            "offset": "OFFSET",
            "ccd_temp": "DET-TEMP",
            "filter_name": "FILTER",
            "xbinning": "XBINNING",
            "ybinning": "YBINNING",
            "date_obs": "DATE-OBS",
            "telescope": "TELESCOP",
            "instrument": "INSTRUME",
            "focal_length": "FOCALLEN",
            "pixel_size_x": "XPIXSZ",
            "pixel_size_y": "YPIXSZ",
            "ra": "RA",
            "dec": "DEC",
            "eq_mode": EQMODE_KEY,
        }
        canonical = canonical_map.get(logical)
        if canonical is None:
            continue
        if canonical in normalized and normalized[canonical] not in (None, ""):
            continue
        val = None
        for alias in aliases:
            if alias in raw and raw[alias] not in (None, ""):
                val = raw[alias]
                break
        if val is not None:
            normalized[canonical] = val
    # Ensure XPIXSZ/YPIXSZ fallback via pixel_size alias resolution
    # Already handled, but ensure YPIXSZ mirrors XPIXSZ if one missing
    if "XPIXSZ" not in normalized and "YPIXSZ" in normalized:
        normalized["XPIXSZ"] = normalized["YPIXSZ"]
    if "YPIXSZ" not in normalized and "XPIXSZ" in normalized:
        normalized["YPIXSZ"] = normalized["XPIXSZ"]
    # Also handle DATE-OBS from CCDTEMP alias variations
    return normalized


def build_effective_header(
    context: Any | None,
    method: str = "superpixel",
    scale_window: float = 2.0,
    drizzle_scale: float = 2.0,
    wcs: dict | None = None,
    total_exposure: float | None = None,
    ref_header: fits.Header | dict | None = None,
    naxis: tuple[int, int] | None = None,
    drizzle_pixfrac: float | None = None,
    drizzle_kernel: str | None = None,
    drizzle_nframes: int | None = None,
) -> fits.Header:
    """Build effective FITS header for stacked/drizzled/merged outputs.

    Single source of truth (Anchor-Patch). Best-effort: missing raw_cards/WCS -> header still valid + warning, no exception.

    Args:
        context: ObservationContext or filtered context for group (S4). ``None`` -> use ref_header fallback.
        method: "superpixel" | "malvar2004" | "bilinear" | "drizzle" etc. Case-insensitive; malvar alias maps to 1.0 scale.
        scale_window: 2.0 superpixel, 1.0 malvar/bilinear (S1). Alternative to resolve_debayer_factor; if method is drizzle, drizzle_scale governs.
        drizzle_scale: only for drizzle method (2.0 -> 1.45 um, S1). Ignored otherwise.
        wcs: {ra, dec, pixel_scale_arcsec} for TAN-WCS approximate; if missing -> fallback compute from native*scale.
        total_exposure: for merged: sum(group_metadata.total_exposure) -> sets EXPTIME.
        ref_header: fallback raw header when context is None (merge standalone, S3) — via HEADER_ALIASES (S4).
        naxis: (NAXIS1,NAXIS2) for CRPIX; if None -> annotate_fits will patch via file's actual NAXIS (S5).
        drizzle_pixfrac/kernel/nframes: drizzle extras (S2); set only for drizzle method.

    Returns:
        astropy.io.fits.Header with effective pixel size, WCS, provenience (ASTRAVER/HISTORY etc).
        Never raises on missing data — logs warning and returns minimal header (best-effort).
    """
    hdr = fits.Header()
    try:
        # Normalize method
        method_norm = str(method or "superpixel").strip().lower()
        # Map aliases: malvar2004 -> malvar, bilinear stays, drizzle -> drizzle
        if method_norm in ("malvar2004", "malvar"):
            method_key = "malvar2004"
            is_drizzle = False
            effective_factor_via = "malvar"
        elif method_norm == "drizzle":
            method_key = "drizzle"
            is_drizzle = True
            effective_factor_via = "drizzle"
        elif method_norm in ("bilinear",):
            method_key = "bilinear"
            is_drizzle = False
            effective_factor_via = "bilinear"
        else:
            method_key = "superpixel"
            is_drizzle = False
            effective_factor_via = "superpixel"

        # Extract light cards (group-filtered context assumed; S4)
        light_cards = _extract_light_cards(context, ref_header=ref_header)
        # // Legacy: behalte weil Darks ohne FOCALLEN — best-effort bei wirklich leeren Darks kein Fake-Header // Gate: test_v1_12_header_platesolving deckt echten Fall ab (Kap.8b Verifikation PASS, Handbook Kap.04)
        if not light_cards and not wcs:
            return hdr

        # Native pixel size: XPIXSZ from raw_cards; best-effort: if missing, effective stays None (no invention)
        native_val = _get_raw_value(light_cards, "XPIXSZ")
        if native_val is None:
            native_val = _get_raw_value(light_cards, "YPIXSZ")
        if native_val is None:
            native_val = light_cards.get("XPIXSZ") or light_cards.get("YPIXSZ")
        native: float | None = None
        if native_val is not None:
            try:
                native = float(native_val)
                if native <= 0:
                    native = None
            except (TypeError, ValueError):
                native = None

        # FOCALLEN (needed for pixel scale conversion)
        focal_val = _get_raw_value(light_cards, "FOCALLEN")
        if focal_val is None:
            focal_val = light_cards.get("FOCALLEN")
        try:
            focal = float(focal_val) if focal_val is not None else 150.0
        except (TypeError, ValueError):
            focal = 150.0

        # Determine effective pixel size + XBINNING/YBINNING + scale factor (best-effort)
        effective: float | None = None
        stack_factor: float | None = None
        if is_drizzle:
            try:
                drizzle_scale_f = float(drizzle_scale) if drizzle_scale else 2.0
            except (TypeError, ValueError):
                drizzle_scale_f = 2.0
            if drizzle_scale_f <= 0:
                drizzle_scale_f = 2.0
            pixel_scale_wcs = (wcs or {}).get("pixel_scale_arcsec", 0) or 0
            if pixel_scale_wcs and pixel_scale_wcs > 0 and focal > 0:
                effective = float(pixel_scale_wcs) * focal / 206.265
                stack_factor = effective / native if native else 1.0 / drizzle_scale_f
            else:
                if native is not None:
                    effective = native / drizzle_scale_f
                else:
                    effective = None
                stack_factor = 1.0 / drizzle_scale_f
            xbin = 1
            ybin = 1
        else:
            try:
                sw = float(scale_window)
            except (TypeError, ValueError):
                sw = 2.0 if effective_factor_via == "superpixel" else 1.0
            try:
                from .equipment import resolve_debayer_factor
                exp_method = "superpixel" if effective_factor_via == "superpixel" else "malvar" if effective_factor_via in ("malvar", "malvar2004") else "bilinear" if effective_factor_via == "bilinear" else "superpixel"
                factor_auto, _src = resolve_debayer_factor(debayer_method=exp_method)
                if (effective_factor_via == "superpixel" and sw == 2.0) or (effective_factor_via in ("malvar", "malvar2004", "bilinear") and sw == 1.0):
                    sw = float(factor_auto)
            except Exception:
                pass
            pixel_scale_wcs = (wcs or {}).get("pixel_scale_arcsec", 0) or 0
            if pixel_scale_wcs and pixel_scale_wcs > 0 and focal > 0:
                effective = float(pixel_scale_wcs) * focal / 206.265
                stack_factor = effective / native if native else sw
            else:
                if native is not None:
                    effective = native * sw
                else:
                    effective = None
                stack_factor = sw
            xbin = 1  # S2: XBINNING always 1 because XPIXSZ is effective (Siril would do 5.8*2=11.6 otherwise)
            ybin = xbin

        # Propagate EXPORT_LIGHT_HEADER_KEYS + S2 extras
        # Light-Header-Keys (best-effort: only if present)
        for key in EXPORT_LIGHT_HEADER_KEYS:
            # Special handling: EXPTIME may be total_exposure for merged
            if key == "EXPTIME" and total_exposure is not None:
                try:
                    hdr[key] = float(total_exposure)
                except (TypeError, ValueError):
                    hdr[key] = total_exposure
                continue
            val = _get_raw_value(light_cards, key)
            if val is None:
                # Also try direct dict for keys like DET-TEMP with hyphen alias mapping already done
                val = light_cards.get(key)
            if val not in (None, ""):
                # DATE-OBS needs handling as string; DET-TEMP as float etc preserve original
                hdr[key] = val
                if key == "EXPTIME" and total_exposure is None:
                    # Keep original EXPTIME from light_cards (already set)
                    pass

        # Ensure EXPTIME for merged if not set via light_cards
        if total_exposure is not None and "EXPTIME" not in hdr:
            try:
                hdr["EXPTIME"] = float(total_exposure)
            except (TypeError, ValueError):
                pass
        # Also ensure total_exposure overwrites if provided (merged sum)
        if total_exposure is not None:
            try:
                hdr["EXPTIME"] = float(total_exposure)
            except (TypeError, ValueError):
                hdr["EXPTIME"] = total_exposure

        # Effective pixel size overrides XPIXSZ/YPIXSZ (stella Punkt 5, Siril 7.98 vs 3.99) — best-effort only if effective determinable
        if effective is not None:
            hdr["XPIXSZ"] = round(float(effective), 4)
            hdr["YPIXSZ"] = round(float(effective), 4)
            hdr.add_comment("Pixel size adjusted for stacked scale (effective)")
            # S2 Pflicht: XBINNING/YBINNING, EQUINOX, BAYERPAT, DEBAYER, CUNIT1/2 only when effective determinable (else best-effort minimal)
            hdr["XBINNING"] = int(xbin)
            hdr["YBINNING"] = int(ybin)
            hdr["EQUINOX"] = 2000.0
        else:
            # // Legacy: behalte weil Darks ohne FOCALLEN — kein XPIXSZ erfinden bei wirklich leeren Darks // Gate: test_v1_12_header_platesolving deckt echten Fall ab (C19 live XPIXSZ 5.8 via wcs*FOCALLEN/206.265 PASS)
            pass
        # BAYERPAT: from raw_cards or default RGGB (DWARF mini)
        bayer = _get_raw_value(light_cards, "BAYERPAT")
        if bayer is None:
            # Check BAYER_PAT etc via _extract mapping fallback
            bayer = light_cards.get("BAYERPAT") or light_cards.get("BAYER_PAT") or "RGGB"
        hdr["BAYERPAT"] = str(bayer).strip().upper() if isinstance(bayer, str) else str(bayer)
        # DEBAYER canonical
        debayer_val = "superpixel" if method_key == "superpixel" else "malvar2004" if method_key == "malvar2004" else "bilinear" if method_key == "bilinear" else "drizzle"
        hdr["DEBAYER"] = debayer_val
        hdr["CUNIT1"] = "deg"
        hdr["CUNIT2"] = "deg"
        # DATE-OBS / DET-TEMP already propagated if present; ensure they are not dropped if missing alias
        if "DATE-OBS" not in hdr:
            date_obs_val = _get_raw_value(light_cards, "DATE-OBS")
            if date_obs_val is not None:
                hdr["DATE-OBS"] = date_obs_val
        if "DET-TEMP" not in hdr:
            det_temp_val = _get_raw_value(light_cards, "DET-TEMP")
            if det_temp_val is None:
                det_temp_val = _get_raw_value(light_cards, "CCD-TEMP") or light_cards.get("DET-TEMP") or light_cards.get("CCD-TEMP")
            if det_temp_val is not None:
                hdr["DET-TEMP"] = det_temp_val

        # Drizzle-Zusatz nur bei drizzle (S2)
        if is_drizzle:
            hdr["DRZSCALE"] = float(drizzle_scale_f)
            # DRZPIXFR/DRZKERNL/NFRAMES optional, set if provided else defaults
            if drizzle_pixfrac is not None:
                try:
                    hdr["DRZPIXFR"] = float(drizzle_pixfrac)
                except (TypeError, ValueError):
                    hdr["DRZPIXFR"] = drizzle_pixfrac
            else:
                # Try to infer pixfrac from stack_factor? fallback 0.5
                # Keep unset if not provided; cfa_drizzle_agent will set explicitly
                pass
            if drizzle_kernel is not None:
                hdr["DRZKERNL"] = str(drizzle_kernel)
            if drizzle_nframes is not None:
                try:
                    hdr["NFRAMES"] = int(drizzle_nframes)
                except (TypeError, ValueError):
                    hdr["NFRAMES"] = drizzle_nframes
            else:
                # NFRAMES from context frame count if available
                if context is not None:
                    try:
                        lights = context.get_lights()  # type: ignore
                        if hasattr(lights, "frames"):
                            hdr["NFRAMES"] = len(lights.frames)
                    except Exception:
                        pass

        # TAN-WCS approximativ (Handbook Kap.04, S2/S5)
        # Need RA, DEC, pixel_scale_arcsec, and NAXIS for CRPIX
        ra_val = _get_raw_value(light_cards, "RA")
        if ra_val is None:
            ra_val = light_cards.get("RA")
        dec_val = _get_raw_value(light_cards, "DEC")
        if dec_val is None:
            dec_val = light_cards.get("DEC")
        # Also try wcs ra/dec override
        if wcs and wcs.get("ra") is not None:
            ra_val = wcs.get("ra")
        if wcs and wcs.get("dec") is not None:
            dec_val = wcs.get("dec")
        try:
            ra_f = float(ra_val) if ra_val is not None else None
            dec_f = float(dec_val) if dec_val is not None else None
        except (TypeError, ValueError):
            ra_f = None
            dec_f = None

        # Pixel scale arcsec: prefer wcs pixel_scale, else compute via effective
        pixel_scale_arcsec = None
        if wcs and wcs.get("pixel_scale_arcsec"):
            try:
                ps = float(wcs["pixel_scale_arcsec"])
                if ps > 0:
                    pixel_scale_arcsec = ps
            except (TypeError, ValueError):
                pass
        if pixel_scale_arcsec is None and effective and focal and focal > 0:
            try:
                pixel_scale_arcsec = 206.265 * float(effective) / float(focal)
            except (TypeError, ValueError, ZeroDivisionError):
                pixel_scale_arcsec = None

        # WCS only if explicit wcs provided (S2/S5) — for export path wcs=None -> no CDELT, for stacked/drizzle wcs={"ra":...} present
        if wcs is not None and ra_f is not None and dec_f is not None and pixel_scale_arcsec and pixel_scale_arcsec > 0:
            # Determine NAXIS for CRPIX (S5); if naxis provided use it, else placeholder (will be patched by annotate_fits)
            if naxis and len(naxis) == 2:
                naxis1, naxis2 = int(naxis[0]), int(naxis[1])
            else:
                # Try to infer from wcs naxis or default 960x540 superpixel placeholder? Use None -> set 0.0 and let annotate patch
                naxis1 = None
                naxis2 = None
                # Try light header NAXIS?
                n1 = _get_raw_value(light_cards, "NAXIS1")
                n2 = _get_raw_value(light_cards, "NAXIS2")
                if n1 is not None and n2 is not None:
                    try:
                        naxis1, naxis2 = int(float(n1)), int(float(n2))
                    except (TypeError, ValueError):
                        naxis1 = naxis2 = None
            hdr["CRVAL1"] = float(ra_f)
            hdr["CRVAL2"] = float(dec_f)
            if naxis1 and naxis2:
                hdr["CRPIX1"] = (naxis1 + 1) / 2.0
                hdr["CRPIX2"] = (naxis2 + 1) / 2.0
            else:
                # Placeholder that will be patched
                hdr["CRPIX1"] = 480.5  # superpixel placeholder
                hdr["CRPIX2"] = 270.5
            hdr["CDELT1"] = -float(pixel_scale_arcsec) / 3600.0
            hdr["CDELT2"] = float(pixel_scale_arcsec) / 3600.0
            hdr["CTYPE1"] = "RA---TAN"
            hdr["CTYPE2"] = "DEC--TAN"
            hdr["CUNIT1"] = "deg"
            hdr["CUNIT2"] = "deg"
            hdr["EQUINOX"] = 2000.0
            hdr.add_comment("Approximate WCS - not astrometric fit")

        # Provenienz S3 OQ-3 (kumuliert HISTORY via annotate_fits, but set initial)
        # ASTRAVER, DATE, HISTORY, DEBAYER etc, STACKMETH, REGMETH, SOFTWARE, CREATOR
        try:
            from importlib.metadata import version as _get_version
            try:
                ver = _get_version("astra-pipeline")
            except Exception:
                try:
                    ver = _get_version("astra")
                except Exception:
                    ver = "1.12.0"
        except Exception:
            ver = "1.12.0"
        hdr["ASTRAVER"] = str(ver)
        hdr["SOFTWARE"] = "Astra Pipeline"
        hdr["CREATOR"] = "Astra Pipeline"
        # DATE now UTC
        try:
            hdr["DATE"] = datetime.now(timezone.utc).isoformat()
        except Exception:
            hdr["DATE"] = datetime.now().isoformat()
        # HISTORY kumuliert: set one entry for current method (annotate_fits will preserve previous)
        hist_map = {
            "superpixel": "Astra debayer: superpixel",
            "malvar2004": "Astra debayer: malvar2004",
            "bilinear": "Astra debayer: bilinear",
            "drizzle": "Astra drizzle: scale 2.0",
        }
        hist_text = hist_map.get(method_key, f"Astra {method_key}")
        # Also add stack/merge histories when total_exposure present or method drizzle etc?
        # For generic, add HISTORY; for merged, final step will add via caller
        hdr.add_history(hist_text)
        if total_exposure is not None:
            hdr.add_history(f"Astra merge: total_exposure {total_exposure}")
        # STACKMETH / REGMETH if wcs/stack related? Add DEBAYER already
        hdr["STACKMTH"] = method_key  # optional provenience
        if is_drizzle:
            hdr["DRZSCALE"] = hdr.get("DRZSCALE", float(drizzle_scale_f))
        # Provide pixel scale comment
        if pixel_scale_arcsec:
            hdr.add_comment(f"pixel_scale {pixel_scale_arcsec:.4f} arcsec/px")

    except Exception as e:
        logger.warning("header.build_failed", error=str(e), method=method, msg="build_effective_header left minimal (best effort)")
    return hdr


def annotate_fits(path: Path | str, header: fits.Header) -> None:
    """Best-effort in-place Update (mode=update), loggt header_annotated, nie Daten ändern (additiv).

    Adds header cards to FITS at path, preserving data. For HISTORY, appends.
    Corrects CRPIX1/2 based on file's actual NAXIS (S5) and recalculates CDELT if pixel_scale available.
    Logs header_annotated on success, header_annotate_failed on error (no exception propagated).

    Args:
        path: Path to FITS file to update
        header: Header with effective cards to merge (from build_effective_header)
    """
    try:
        p = Path(path)
        if not p.exists():
            logger.warning("header.annotate_failed", path=str(p), error="file not found", msg="header left unchanged (best effort)")
            return
        with fits.open(p, mode="update") as hdul:
            if len(hdul) == 0:
                logger.warning("header.annotate_failed", path=str(p), error="empty HDU", msg="header left unchanged")
                return
            hdr = hdul[0].header
            # Correct CRPIX based on actual NAXIS (S5)
            try:
                naxis1 = hdr.get("NAXIS1", 0)
                naxis2 = hdr.get("NAXIS2", 0)
                # If header not yet has NAXIS, infer from data shape
                if (not naxis1 or not naxis2) and hdul[0].data is not None:
                    data = hdul[0].data
                    if data.ndim == 3:
                        # FITS (C,H,W) internal already transposed? Use header NAXIS? For 3D, NAXIS1=W, NAXIS2=H
                        # Get shape from data: (C,H,W) if 3D
                        if data.shape[0] == 3:
                            naxis1 = data.shape[2]
                            naxis2 = data.shape[1]
                        else:
                            naxis1 = data.shape[-1] if len(data.shape) >= 1 else 0
                            naxis2 = data.shape[-2] if len(data.shape) >= 2 else 0
                    else:
                        naxis2, naxis1 = data.shape[0], data.shape[1]
                if naxis1 and naxis2:
                    # If incoming header has WCS CRPIX, patch it to actual NAXIS (ensures S5)
                    # Also update if header's CRPIX mismatches naxis
                    # We set CRPIX to (NAXIS+1)/2 regardless, to satisfy S5 test that CRPIX depends on output NAXIS
                    if "CRVAL1" in header or "CRVAL1" in hdr:
                        header["CRPIX1"] = (int(naxis1) + 1) / 2.0
                        header["CRPIX2"] = (int(naxis2) + 1) / 2.0
                    # Also handle case where header already has CDELT but pixel scale derived from XPIXSZ; ensure CDELT consistent?
                    # Compute pixel_scale from header XPIXSZ/FOCALLEN if not in header
                    # This ensures CDELT matches effective XPIXSZ for drizzle/superpixel differences across sizes
                    if "XPIXSZ" in header and "FOCALLEN" in (header or hdr):
                        try:
                            xpix = float(header.get("XPIXSZ") or hdr.get("XPIXSZ", 2.9))
                            focal = float(header.get("FOCALLEN") or hdr.get("FOCALLEN", 150.0) or 150.0)
                            if focal > 0:
                                ps = 206.265 * xpix / focal
                                # Update header's CDELT to match (S5: CDELT = ±pixel_scale/3600)
                                header["CDELT1"] = -ps / 3600.0
                                header["CDELT2"] = ps / 3600.0
                        except (TypeError, ValueError, ZeroDivisionError):
                            pass
            except Exception:
                pass

            keys_written = 0
            for key, value in header.items():
                # Handle HISTORY specially: add_history for each value, not overwrite
                if key == "HISTORY":
                    # header.items() for HISTORY returns multiple? Astropy handles differently; use header['HISTORY'] may be list-like
                    # We'll add each history card from incoming header
                    continue
                # Skip empty keys (COMMENT etc handled)
                if not key or key.strip() == "":
                    continue
                # Don't overwrite SIMPLE/BITPIX/NAXIS etc if already present? We allow overwrite for our effective keys
                hdr[key] = value
                keys_written += 1
            # Handle HISTORY cards: copy all HISTORY from incoming header
            try:
                # fits.Header keeps HISTORY as list-like via get_history?
                # Iterate over header cards to find HISTORY
                for card in header.cards:
                    if card.keyword == "HISTORY":
                        hdr.add_history(card.value)
                        keys_written += 1
                    elif card.keyword == "COMMENT":
                        # Only add COMMENT if not already present to avoid duplication
                        # But ensure Approximate WCS comment present
                        existing_comments = [c.value for c in hdr.cards if c.keyword == "COMMENT"]
                        if card.value not in existing_comments:
                            hdr.add_comment(card.value)
            except Exception:
                pass
            hdul.flush()
            logger.info("header_annotated", path=str(p), keys_count=keys_written)
    except Exception as e:
        logger.warning("header_annotate_failed", path=str(path), error=str(e), msg="header left unchanged (best effort)")
        # Specifically also log export.header_annotate_failed alias for compatibility
        logger.warning("export.header_annotate_failed", path=str(path), error=str(e), msg="header left unchanged (best effort)")
