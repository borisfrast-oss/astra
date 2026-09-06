"""V1.7-4 — Equipment Auto-Detection aus FITS-Headern.

Spec: knowledge-base/projects/astra/specs/v17-equipment-auto-detection.md
(decided; OQ-EQPT-1..4 durch Boris resolved 2026-08-21).

Kern (EQPT-A): ``resolve_equipment(context, config)`` fuellt
``context.equipment`` entlang einer Prioritaets-Kette je Feld:

1. FITS-Header der Light-Frames — Majority-Wert ueber ALLE Lights,
   nicht nur den ersten Frame (AC-EQPT-A2).
2. Config-Equipment-Profil (``AppConfig.equipment_profiles``) — Profil-
   Matching ueber INSTRUME/TELESCOP gegen ``name``/``camera``/``telescope``;
   exakter Match vor Substring, laengster Match gewinnt; Fallback Profil
   ``default`` (OQ-EQPT-1, Beschluss Boris 2026-08-21).
3. unbekannt (None) + Warning (AC-EQPT-A4).

Bei Header/Config-Widerspruch gewinnt der Header (SSOT-Linie V1.6-1) und
es wird eine Warning ``discovery.equipment.header_config_mismatch``
geloggt (OQ-EQPT-4) — Datenanhang: 99 Frames XPIXSZ 2.9 µm real vs.
3.76 µm Config-Profil → Fallback waere falsch gewesen.

Diese Erkennung liest NUR native Light-Header. Annotierte Exporte werden
beim Scan uebersprungen (OUTPUT_SUBDIRS); die effektive Export-XPIXSZ
bleibt Sache des Exports (F-META-1.2, unveraendert).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from ..config.models import AppConfig
    from ..models.core import ObservationContext

logger = structlog.get_logger(__name__)

# EQPT-A: aufgeloeste Felder -> FitsHeader-Attribut(e). pixel_size_um nutzt
# primaer XPIXSZ (pixel_size_x); YPIXSZ dient als expliziter Fallback
# (quadratische Pixel: identisch, aber nicht jede Firmware schreibt beide).
EQUIPMENT_FIELD_HEADERS: dict[str, tuple[str, ...]] = {
    "pixel_size_um": ("pixel_size_x", "pixel_size_y"),
    "focal_length_mm": ("focal_length",),
    "aperture_mm": ("aperture",),
    "telescope": ("telescope",),
    "camera": ("instrument",),
}

# EQPT-C: Bayer-Pattern Header-Keys (best effort, AC-EQPT-C4). Kein Treffer
# -> RGGB-Annahme (heutiges Verhalten, debayer_superpixel ist layout-fix).
BAYER_PATTERN_HEADER_KEYS: tuple[str, ...] = (
    "BAYERPAT", "BAYER_PAT", "CFA_PATTERN",
)

# OQ-EQPT-1: Profil-Fallback-Name, wenn weder exakter Match noch Substring.
DEFAULT_PROFILE_NAME = "default"

_EQUIPMENT_FIELDS = tuple(EQUIPMENT_FIELD_HEADERS.keys())

# ── V19-REG-SMART R2 — Mount & Registration Auto-Detect ────────────────

AZ_DEVICES = ["DWARF MINI", "DWARF II", "SEESTAR", "ZWO ASIAIR", "SMARTTELESCOPE"]


def detect_mount_type(header: Any) -> str:
    """V19-REG-SMART R2 + DEF-009: Mount-Typ aus FITS-Header ableiten.

    EQMODE hat Vorrang (0=AZ, 1=EQ), da es die zentrale, frame-eigene
    Aufnahmemodus-Quelle ist (v13-6-eq-flag-quelle.md). Erst wenn EQMODE
    fehlt, wird EQUAT/MOUNT/TELESCOP auf AZ-Signale geprueft. Liefert "az"
    bei Treffer, sonst "eq" (Fallback) + Warning `discovery.mount_unknown`
    (OQ-REG-3, konservativ) — aber nur wenn auch EQMODE fehlt.
    """
    # DEF-009: EQMODE gewinnt gegen Profil-/TELESCOP-Heuristik.
    eq_mode = None
    if header is not None:
        try:
            eq_mode = header.get("EQMODE", None)
            if eq_mode is not None:
                eq_mode = int(eq_mode)
        except Exception:
            eq_mode = None
    if eq_mode == 0:
        return "az"
    if eq_mode == 1:
        return "eq"

    try:
        equat = str(header.get("EQUAT", "") if header is not None else "").upper()
    except Exception:
        equat = ""
    try:
        mount = str(header.get("MOUNT", "") if header is not None else "").upper()
    except Exception:
        mount = ""
    try:
        telescop = str(header.get("TELESCOP", "") if header is not None else "").upper()
    except Exception:
        telescop = ""
    if any(k in equat for k in ["AZ", "ALTAZ", "ALT-AZ"]):
        return "az"
    if any(k in mount for k in ["AZ", "ALTAZ", "ALT-AZ"]):
        return "az"
    if any(dev in telescop for dev in AZ_DEVICES):
        return "az"
    if "DWARF" in telescop and "MINI" in telescop:
        return "az"
    if telescop.strip() == "":
        logger.warning(
            "discovery.mount_unknown",
            detail="Mount-Type unbekannt, Default EQ angenommen; Profil setzen empfohlen",
        )
    return "eq"


def detect_preferred_registration(
    header: Any, exptimes: list[float] | None, mount_type: str | None = None
) -> str:
    """V19-REG-SMART R2: Bevorzugte Registrations-Methode aus Header + Belichtung.

    Spec-Code (stella OQ-REG-1): AZ immer astroalign (robust), EQ >120s
    astroalign sonst fft. rotation_fft bleibt waehlbar via Profil, aber nicht
    Auto-Default.

    DEF-009: Optionaler mount_type-Override verhindert, dass die Methode
    erneut aus dem Header abgeleitet werden muss, wenn EQMODE bereits
    bekannt ist (vermeidet doppelte discovery.mount_unknown-Warnungen).
    """
    if mount_type is None:
        mount_type = detect_mount_type(header)
    max_exptime = max(exptimes) if exptimes else 0
    try:
        max_exptime = float(max_exptime)
    except Exception:
        max_exptime = 0
    if mount_type == "az":
        # OQ-REG-1: astroalign Default fuer AZ (robust, bewaehrt)
        # rotation_fft nur Fallback wenn astroalign nicht verfuegbar (Extra fehlt)
        if max_exptime > 60:
            return "astroalign"
        elif max_exptime > 30:
            return "astroalign"  # konservativ; rotation_fft optional via Config
        else:
            return "astroalign"
    # EQ
    if max_exptime > 120:
        return "astroalign"
    return "fft"


# ── Majority ueber alle Lights (AC-EQPT-A2) ─────────────────────────────


def _majority(values: list) -> tuple[Any | None, bool]:
    """Mehrheitswert aus einer Wertliste (None-Werte ignoriert).

    Deterministisch: meisten Vorkommen gewinnt; Tie-Break = erste
    Occurrence in Frame-Reihenfolge.

    Returns:
        (majority_value | None, inconsistent) mit inconsistent=True,
        wenn >= 2 distincte Nicht-None-Werte vorhanden sind.
    """
    non_none = [v for v in values if v is not None]
    if not non_none:
        return None, False
    counts: Counter = Counter(non_none)
    best = min(counts.keys(), key=lambda v: (-counts[v], non_none.index(v)))
    return best, len(counts) > 1


def _collect_header_values(context: ObservationContext) -> dict[str, dict]:
    """Sammelt je Equipment-Feld den Majority-Wert ueber alle Light-Headers."""
    lights = context.get_lights().frames
    result: dict[str, dict] = {}
    for field, header_attrs in EQUIPMENT_FIELD_HEADERS.items():
        for attr in header_attrs:
            values = [
                getattr(f.header, attr, None)
                for f in lights if f.header is not None
            ]
            value, inconsistent = _majority(values)
            if value is not None or attr == header_attrs[0]:
                result[field] = {
                    "value": value,
                    "consistent": not inconsistent,
                    "n_frames": len([v for v in values if v is not None]),
                }
            # YPIXSZ-Fallback nur, wenn die Primaer-Achse nichts liefert.
            if value is not None:
                break
    return result


# ── Config-Profil-Matching (OQ-EQPT-1 Option A) ──────────────────────────


def _profile_value(profile: Any, field: str) -> Any | None:
    """Config-Profilwert oder None bei Platzhalter-Defaults.

    EquipmentProfile definiert Defaults fuer JEDES Feld (telescope="Unknown",
    camera="Unknown", aperture_mm=0, focal_length_mm=0, pixel_size_um=3.76).
    Diese Defaults bedeuten "nicht gepflegt" und duerfen NICHT als
    Config-Quelle gelten (sonst wuerde z.B. telescope=None -> "Unknown").
    """
    raw = getattr(profile, field, None)
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw or raw.lower() == "unknown":
            return None
        return raw
    try:
        if float(raw) == 0.0:
            return None
    except (TypeError, ValueError):
        return None
    return raw


def match_equipment_profile(
    context: ObservationContext,
    config: AppConfig | None,
) -> tuple[Any | None, str | None]:
    """Waehlt das Config-Equipment-Profil nach OQ-EQPT-1 (Option A).

    Matching ueber INSTRUME (instrument/camera) und TELESCOP der Light-
    Headers gegen ``EquipmentProfile.name`` / ``camera`` / ``telescope``:

    - exakter Match (case-insensitive) vor Substring-Match,
    - innerhalb derselben Klasse gewinnt der LAENGSTE Match (z.B.
      "DWARF mini" vor "DWARF 3" bzw. vor einem nackten "DWARF"),
    - kein Treffer -> Profil namens ``default`` (falls konfiguriert),
    - keine Profile konfiguriert -> (None, None).

    Returns:
        (profile | None, matched_pattern | None). matched_pattern ist der
        profilseitige String, der gematcht hat (None beim default-Fallback
        bzw. ohne Match).
    """
    profiles = list(getattr(config, "equipment_profiles", None) or []) if config else []
    if not profiles:
        return None, None

    header_strings: list[str] = []
    for f in context.get_lights().frames:
        if f.header is None:
            continue
        for attr in ("instrument", "telescope"):
            v = getattr(f.header, attr, None)
            if isinstance(v, str):
                v = v.strip()
                if v and v not in header_strings:
                    header_strings.append(v)

    best: tuple[tuple[int, int], Any, str] | None = None
    for s in header_strings:
        s_lower = s.lower()
        for profile in profiles:
            for attr in ("name", "camera", "telescope"):
                pattern = getattr(profile, attr, None)
                if not isinstance(pattern, str) or not pattern.strip():
                    continue
                p_stripped = pattern.strip()
                # Platzhalter-Defaults ("Unknown") nehmen NICHT am Matching
                # teil — sonst wuerde z.B. ein Profil-Telescope "Unknown"
                # jeden Header-String mit Substring "unknown" matchen.
                if p_stripped.lower() == "unknown":
                    continue
                p_lower = p_stripped.lower()
                if p_lower == s_lower:
                    rank = 0  # exakter Match
                elif p_lower in s_lower:
                    rank = 1  # Substring-Match
                else:
                    continue
                key = (rank, -len(p_lower))  # exakt > substring; laenger > kuerzer
                if best is None or key < best[0]:
                    best = (key, profile, p_stripped)
        # Exakter Match auf einem Header-String beendet die Suche sofort
        # (deterministisch; kein spaeterer Substring kann ihn schlagen).
        if best is not None and best[0][0] == 0:
            break

    if best is not None:
        return best[1], best[2]

    # Fallback: Profil "default" (OQ-EQPT-1 Beschluss).
    for profile in profiles:
        if str(getattr(profile, "name", "")).lower() == DEFAULT_PROFILE_NAME:
            return profile, None
    return None, None


def _values_differ(header_val: Any, config_val: Any) -> bool:
    """Header/Config-Widerspruch? Numerik mit Toleranz (Float-Rauschen)."""
    if isinstance(header_val, (int, float)) and isinstance(config_val, (int, float)):
        return abs(float(header_val) - float(config_val)) > 1e-9
    return header_val != config_val


# ── EQPT-B/C: Resolution + Bayer-Pattern ────────────────────────────────


def _resolve_resolution(context: ObservationContext) -> dict[str, int | None]:
    """EQPT-B: Aufloesung aus NAXIS1/NAXIS2 des ersten Light-Frames.

    FrameInfo.width/height sind bereits die Bildachsen (scan_directory
    nutzt data.shape[-2:] — bei 3D-Daten ohne Kanalachse). Rein
    dokumentarisch (OQ-EQPT-2): KEINE Verhaltenssteuerung.
    """
    lights = context.get_lights().frames
    first = lights[0] if lights else None
    width = getattr(first, "width", None) if first else None
    height = getattr(first, "height", None) if first else None
    return {
        "width_px": int(width) if width else None,
        "height_px": int(height) if height else None,
    }


def detect_bayer_pattern(
    context: ObservationContext,
) -> tuple[str | None, str]:
    """EQPT-C (AC-EQPT-C4): Bayer-Pattern best effort aus dem Header.

    Durchsucht die Raw-Cards der Light-Headers (erster Treffer) nach
    BAYERPAT o.ae. Kein Treffer -> (None, "assumed") = RGGB-Annahme.

    Returns:
        (pattern | None, source) mit source in {"fits_header", "assumed"}.
    """
    for f in context.get_lights().frames:
        if f.header is None:
            continue
        raw_cards = getattr(f.header, "raw_cards", None) or {}
        for key in BAYER_PATTERN_HEADER_KEYS:
            if key in raw_cards:
                value = raw_cards.get(key)
                if isinstance(value, str) and value.strip():
                    normalized = value.strip().upper()
                    logger.debug(
                        "discovery.equipment.bayer_pattern_raw",
                        path=str(f.path), key=key, value=normalized,
                    )
                    return normalized, "fits_header"
    return None, "assumed"


def detect_input_is_rgb(context: ObservationContext) -> bool:
    """True, wenn die Lights bereits RGB (NAXIS=3) sind (z.B. --no-calib
    mit debayerten Lights). Best effort ueber die NAXIS-Rohkarten."""
    for f in context.get_lights().frames:
        if f.header is None:
            continue
        raw_cards = getattr(f.header, "raw_cards", None) or {}
        naxis = raw_cards.get("NAXIS")
        try:
            if naxis is not None and int(float(str(naxis))) == 3:
                return True
        except (TypeError, ValueError):
            continue
    return False


# ── EQPT-C: Datengetriebener Debayer-Faktor (OQ-EQPT-3 Option A) ────────


def resolve_debayer_factor(
    debayer_method: str = "superpixel",
    explicit_value: float | None = None,
    preset_value: float | None = None,
    input_is_rgb: bool = False,
) -> tuple[float, str]:
    """Debayer-/Stack-Skalierungs-Faktor mit finaler Precedence.

    OQ-EQPT-3 (Beschluss Boris, Option A; Fix B2 ray-Review 2026-08-23):
      explicit (Config) > preset > datengetrieben (3D-RGB -> 1.0;
      2D-CFA + superpixel -> 2.0; 2D-CFA + bilinear/malvar -> 1.0)
      > Default 2.0.

    AC-EQPT-C1: 2D-CFA folgt der V1.6-2/V1.8-0-Methoden-Semantik.
    AC-EQPT-C2: bereits debayerter 3D-Input -> 1.0, unabhaengig von der
      Methode (keine doppelte Herunterskalierung).
    AC-EQPT-C3: expliziter Override gewinnt IMMER (auch ueber Preset).

    V1.8-0 (MALVAR): malvar = volle Auflösung (1920x1080) wie bilinear -> 1.0.

    Returns:
        (factor, source) mit source in {"explicit", "preset", "auto_data",
        "default"} (AC-EQPT-C5, analog AC-BIL-E4). "default" ist nur fuer
        unbekannte debayer_method erreichbar (superpixel/bilinear/malvar sind
        die validen Methoden).
    """
    if explicit_value is not None:
        return float(explicit_value), "explicit"
    if preset_value is not None:
        return float(preset_value), "preset"
    if input_is_rgb:
        # Datenlage schlaegt die Methoden-Annahme (3D braucht keinen Debayer).
        return 1.0, "auto_data"
    if debayer_method in ("bilinear", "malvar"):
        return 1.0, "auto_data"
    if debayer_method == "superpixel":
        return 2.0, "auto_data"
    return 2.0, "default"


# ── EQPT-A/D: zentrale Equipment-Aufloesung ──────────────────────────────


def resolve_equipment(
    context: ObservationContext,
    config: AppConfig | None,
) -> dict:
    """Fuellt ``context.equipment`` nach der Prioritaets-Kette je Feld.

    Reihenfolge (EQPT-A): Header-Majority ueber alle Lights > Config-
    Equipment-Profil > None + Warning. Bei beidseitigen Werten mit
    Abweichung gewinnt der Header und es wird eine Warning
    ``discovery.equipment.header_config_mismatch`` geloggt (OQ-EQPT-4).

    Zusaetzlich (EQPT-B/C): ``width_px``/``height_px`` aus dem ersten
    Light-Frame (rein dokumentarisch) und Bayer-Pattern best effort.

    Die Funktion ist nie abbruchbehaftet: Fehler werden als Warning
    geloggt, der Lauf laeuft weiter (Spec-Annahme 4).

    Returns:
        Report-Dict fuer agent-log/inspect/Tests::

            {
              "fields": {field: {"value": ..., "source": ...}},   # EQPT-D1
              "profile": <Profilname | None>,
              "matched_pattern": <Match-String | None>,
              "bayer_pattern": <str | None>,
              "bayer_pattern_source": "fits_header" | "assumed",
              "resolution": {"width_px": ..., "height_px": ...},
              "warnings": [<kurze Meldungen fuer DiscoveryResult.warnings>],
            }
    """
    equipment = context.equipment
    report: dict = {
        "fields": {},
        "profile": None,
        "matched_pattern": None,
        "bayer_pattern": None,
        "bayer_pattern_source": "assumed",
        "resolution": {},
        "warnings": [],
    }
    try:
        profile, matched_pattern = match_equipment_profile(context, config)
        header_values = _collect_header_values(context)

        for field in _EQUIPMENT_FIELDS:
            header_entry = header_values.get(field, {})
            hval = header_entry.get("value")
            cval = _profile_value(profile, field) if profile is not None else None

            if not header_entry.get("consistent", True):
                logger.warning(
                    "discovery.equipment.inconsistent_header",
                    field=field,
                    msg=(
                        f"Equipment-Feld {field}: abweichende Header-Werte "
                        f"ueber die Lights — Majority gewinnt"
                    ),
                )
                report["warnings"].append(
                    f"equipment: inkonsistente Header-Werte fuer {field} "
                    f"— Majority gewinnt ({hval})"
                )

            if hval is not None:
                value, source = hval, "fits_header"
                if cval is not None and _values_differ(hval, cval):
                    logger.warning(
                        "discovery.equipment.header_config_mismatch",
                        field=field,
                        header=hval,
                        config=cval,
                        profile=getattr(profile, "name", None),
                        msg=(
                            f"Header und Config-Profil liefern unterschiedliche "
                            f"Werte fuer {field} — Header gewinnt (SSOT)"
                        ),
                    )
                    report["warnings"].append(
                        f"equipment: {field} Header/Config-Widerspruch "
                        f"(Header {hval} vs. Profil "
                        f"{getattr(profile, 'name', '?')}: {cval}) — Header gewinnt"
                    )
            elif cval is not None:
                logger.warning(
                    "discovery.equipment.config_fallback",
                    field=field,
                    profile=getattr(profile, "name", None),
                    value=cval,
                    source="config",
                    msg=(
                        f"Equipment-Feld {field} fehlt im Light-Header — "
                        f"Config-Profil greift"
                    ),
                )
                report["warnings"].append(
                    f"equipment: {field} aus Config-Profil "
                    f"'{getattr(profile, 'name', '?')}' (Fallback, fehlt im Header)"
                )
                value, source = cval, "config"
            else:
                logger.warning(
                    "discovery.equipment.unknown_field",
                    field=field,
                    msg=(
                        f"Equipment-Feld {field} weder im Header noch per "
                        f"Config-Profil verfuegbar — bleibt None"
                    ),
                )
                report["warnings"].append(
                    f"equipment: {field} unbekannt (weder Header noch Config-Profil)"
                )
                value, source = None, "none"

            # Feldtypen bewahren (focal_length_mm/aperture_mm sind int,
            # konsistent zum bisherigen build_observation_context-Cast).
            if field in ("focal_length_mm", "aperture_mm") and value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = None
                    source = "none"

            setattr(equipment, field, value)
            equipment.sources[field] = source
            report["fields"][field] = {"value": value, "source": source}

        # EQPT-B: Aufloesung dokumentarisch (OQ-EQPT-2: kein Verhalten).
        resolution = _resolve_resolution(context)
        equipment.width_px = resolution["width_px"]
        equipment.height_px = resolution["height_px"]
        report["resolution"] = resolution

        # EQPT-C: Bayer-Pattern best effort (AC-EQPT-C4).
        bayer_pattern, bayer_source = detect_bayer_pattern(context)
        equipment.bayer_pattern = bayer_pattern
        report["bayer_pattern"] = bayer_pattern
        report["bayer_pattern_source"] = bayer_source
        logger.info(
            "discovery.equipment.bayer_pattern",
            pattern=bayer_pattern or "assumed: RGGB",
            source=bayer_source,
        )

        equipment.profile_name = getattr(profile, "name", None) if profile else None
        report["profile"] = equipment.profile_name
        report["matched_pattern"] = matched_pattern

        logger.info(
            "discovery.equipment.resolved",
            profile=equipment.profile_name,
            matched_pattern=matched_pattern,
            sources={k: v["source"] for k, v in report["fields"].items()},
            width_px=equipment.width_px,
            height_px=equipment.height_px,
            bayer_pattern=bayer_pattern or "assumed: RGGB",
        )
    except Exception as e:  # noqa: BLE001 - Equipment nie abbruchbehaftet
        logger.warning(
            "discovery.equipment.resolve_failed",
            error=str(e),
            msg="Equipment-Aufloesung fehlgeschlagen — Pipeline laeuft weiter",
        )
        report["warnings"].append(f"equipment: Aufloesung fehlgeschlagen ({e})")
    return report
