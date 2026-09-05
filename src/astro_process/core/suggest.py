"""V19-1.10-TARGET-ADVISOR — core logic for ``astra suggest``.

Spec: knowledge-base/projects/astra/specs/spec-v19-target-advisor.md
(owen, decided 2026-09-04; SUG-1..4). ``astra process --from-suggested``
(SUG-5) lives in ``cli.py`` (precedence wiring, analog V19-PCC-FLAG) and
only reads the file dict produced here (``to_file_dict``/``write_suggested_file``).

Design notes (backy):

- **Offline-first (hal):** ``target-cache.md`` wins always; SIMBAD
  (``query_simbad``) is only attempted on a cache miss and any failure
  (timeout/network/parse) degrades to the ``handbook_fallback`` source —
  never a crash, never a ``ClickException`` (AC-SUG-4, OQ-SUG-1).
- **No hardcoded target tree (OQ-SUG-2, AC-SUG-6):** the ``Astra-Preset``
  value is read verbatim from the (tolerant) cache-entry dict at runtime —
  there is no per-target ``if target == <name>: preset = <preset>`` rule
  anywhere for any specific object (verified by a repo-wide grep in
  tests/test_v19_suggest.py). ``classify_and_cite`` maps a *generic*
  object-class keyword (galaxy,
  planetary nebula, globular cluster, ...) to a Handbook chapter citation;
  this is the SUG-2 "Mapping" table from the spec, not a per-target rule.
- **PyPI-without-orion-KB (leo architecture note):** ``target-cache.md``
  is an orion-only file; the shipped package must work without it. The
  cache path is therefore an *optional* config field
  (``AppConfig.suggest.target_cache_path``, see ``config/models.py``) and
  the markdown parser (``parse_target_cache``) is tolerant — missing
  fields/files simply degrade to the SIMBAD/handbook-fallback path
  instead of raising.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

from .equipment import detect_mount_type

logger = structlog.get_logger(__name__)


class SuggestInputError(Exception):
    """Raised when neither TARGET, --header, nor --coords resolve a target.

    Caller (cli.py) turns this into a ``click.ClickException`` — a genuine
    usage error, distinct from the offline/cache-miss case (AC-SUG-4),
    which must stay Exit 0.
    """


# ── target-cache.md — tolerant markdown parser (SUG-2) ──────────────────

_HEADING_RE = re.compile(r"^###\s+(.+)$")
_FIELD_RE = re.compile(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.*?)\s*\|$")


def parse_target_cache(text: str) -> list[dict[str, str]]:
    """Tolerant parser for the stella ``target-cache.md`` schema.

    Every ``### <Heading>`` starts a new entry; ``| **Feld** | Wert |``
    table rows become dict fields (``_heading`` holds the raw heading).
    Unrelated markdown (front-matter, prose, non-bold table rows such as
    the "Keine Targets" system-folder table) is silently skipped — schema
    drift degrades gracefully instead of raising (Risiko-Mitigation
    plan.md Z.562: "Schema-Toleranz ... fehlende Felder -> WARN +
    generischer Fallback").
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            if current is not None:
                entries.append(current)
            current = {"_heading": heading_match.group(1).strip()}
            continue
        if current is None:
            continue
        field_match = _FIELD_RE.match(line)
        if field_match:
            key = field_match.group(1).strip()
            value = field_match.group(2).strip()
            current[key] = value
    if current is not None:
        entries.append(current)
    return entries


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


_CALDWELL_RE = re.compile(r"caldwell\s*(\d+)", re.IGNORECASE)


def _normalize_compact(s: str) -> str:
    """Alias/catalog-tolerant compact form (Stella-Smoke 2026-09-04, C19/C34
    Header-Miss): lowercase, ALL whitespace + hyphens removed, so
    ``"C 19"``, ``"C-19"`` and ``"C19"`` all collapse to the same key
    (``"c19"``). Used IN ADDITION to :func:`_normalize` in
    :func:`find_cache_entry` — never as a replacement, so exact
    spaced-form matches keep working unchanged.
    """
    return re.sub(r"[\s\-]+", "", (s or "")).strip().lower()


def _candidate_keys(entry: dict[str, str]) -> set[str]:
    """All strings under which TARGET may be looked up for this entry.

    Every candidate is added in both its spaced (:func:`_normalize`) and
    compact (:func:`_normalize_compact`) form so a header/CLI target like
    ``"C 19"`` matches a cache key stored as ``"C19"`` (and vice versa) —
    the FITS ``OBJECT`` keyword is not guaranteed to use the same spacing
    as ``target-cache.md`` (Stella-Smoke 2026-09-04 finding).
    """
    raw_candidates: set[str] = set()
    heading = entry.get("_heading", "")
    if heading:
        raw_candidates.add(heading)
        name_part = re.sub(r"\(.*?\)", "", heading).strip()
        if name_part:
            raw_candidates.add(name_part)
    catalog = entry.get("Katalognummer", "")
    if catalog:
        cat_main = catalog.split("(")[0].strip()
        if cat_main:
            raw_candidates.add(cat_main)
    simbad = entry.get("SIMBAD-Name", "")
    if simbad:
        raw_candidates.add(simbad)
    aliase = entry.get("Aliase", "")
    extra_compact: set[str] = set()
    for alias in aliase.split(","):
        alias = alias.strip()
        if alias and alias != "\u2014":  # em-dash "—" = "keine Aliase"
            raw_candidates.add(alias)
            # "Caldwell 19" -> also accept the short "C19"/"C 19" form used
            # in FITS headers (Caldwell-Katalog-Alias, Stella-Smoke NGC 6960).
            caldwell_match = _CALDWELL_RE.match(alias)
            if caldwell_match:
                extra_compact.add(f"c{caldwell_match.group(1)}")

    candidates: set[str] = set()
    for raw in raw_candidates:
        candidates.add(_normalize(raw))
        candidates.add(_normalize_compact(raw))
    candidates |= extra_compact
    return {c for c in candidates if c}


def find_cache_entry(target: str, entries: list[dict[str, str]]) -> dict[str, str] | None:
    """Find the cache entry matching TARGET (case-insensitive, tolerant).

    Matches against both the spaced (:func:`_normalize`) and compact
    (:func:`_normalize_compact`) form of TARGET (Stella-Smoke 2026-09-04:
    a FITS header ``OBJECT`` value like ``"C 19"`` must hit the same entry
    as a CLI target ``"C19"``).
    """
    normalized_target = _normalize(target)
    compact_target = _normalize_compact(target)
    if not normalized_target and not compact_target:
        return None
    for entry in entries:
        keys = _candidate_keys(entry)
        if normalized_target in keys or compact_target in keys:
            return entry
    return None


def load_target_cache(path: Path | str | None) -> list[dict[str, str]]:
    """Load + parse target-cache.md; missing/unset path -> empty list.

    A missing cache (PyPI install without the orion KB, or a not-yet
    configured ``suggest.target_cache_path``) degrades to "always a cache
    miss" -> SIMBAD/handbook-fallback path (never an error).
    """
    if not path:
        return []
    cache_path = Path(path)
    if not cache_path.is_file():
        return []
    try:
        text = cache_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_target_cache(text)


# ── Handbook citation (generic Typ -> Kapitel, SUG-2 Mapping-Tabelle) ────
# NICHT target-spezifisch (AC-SUG-6): der Schluessel ist eine generische
# Objektklasse (aus dem Cache-Feld "Typ" bzw. SIMBAD otype), niemals ein
# einzelnes Target-Name/Preset-Paar.

_PRESET_BY_TYPE_SLUG: dict[str, str] = {
    "galaxy": "galaxy_standard",
    "nebula": "nebula_standard",
    "planetary": "nebula_standard",
    "snr": "nebula_standard",
    "dark_nebula": "nebula_standard",
    "globular": "star_standard",
    "open_cluster": "star_standard",
    "star": "star_standard",
}


def classify_and_cite(typ_text: str) -> tuple[str, str]:
    """Generic object-class -> (type_slug, Handbook citation).

    Implements the SUG-2 "Mapping (Cache-Typ -> Preset, keine
    Code-Duplikation des Handbooks)" table from the spec verbatim — a
    keyword lookup on the *class* of object, not on the target name.
    """
    t = (typ_text or "").lower()
    if "galax" in t:
        return "galaxy", (
            "Handbook 22 \u00a73 Galaxies + 05-Galaxies.md: no filter, "
            "120-180s, PCC recommended"
        )
    if "planetar" in t:
        return "planetary", (
            "Handbook 22 \u00a74 + 08-Planetary-Nebulae.md: Planetary "
            "nebula, OIII-dominated \u2014 nebula_narrowband only with "
            "Filter=Narrowband/Duo-Band + OIII target, otherwise nebula_standard"
        )
    if "emission" in t and "reflect" in t:
        return "nebula", (
            "Handbook 22 \u00a74/\u00a75 + 06-Emission-Nebulae.md + "
            "07-Reflection-Nebulae.md: Emission/Reflection nebula, dualband "
            "recommended"
        )
    if "supernova" in t or "snr" in t:
        return "snr", (
            "Handbook 22 \u00a74 + 06-Emission-Nebulae.md: "
            "Supernova remnant (SNR), narrowband (OIII) recommended"
        )
    if "emission" in t:
        return "nebula", (
            "Handbook 22 \u00a74 Emission nebula + 06-Emission-Nebulae.md: "
            "Dualband, 120-180s"
        )
    if "dunkelnebel" in t or "dark nebula" in t:
        return "dark_nebula", (
            "Handbook 16 Dark nebula + 16-Dark-Nebulae.md: nebula_standard, "
            "DBE cautious"
        )
    if "globular" in t or "kugelsternhaufen" in t:
        return "globular", (
            "Handbook 22 \u00a76 Star clusters + 09-Globular-Clusters.md: "
            "short exposure, no filter, PCC optional"
        )
    if "open cluster" in t or "offener sternhaufen" in t:
        return "open_cluster", (
            "Handbook 22 \u00a76 Star clusters + Ch.10 Open clusters + "
            "10-Open-Clusters.md: short exposure, no filter, PCC optional"
        )
    if "stern" in t or "star" in t:
        return "star", (
            "Handbook 22 \u00a76 + 11-Stars-and-Star-Fields.md: short "
            "exposure, natural color, no PCC needed"
        )
    return "unknown", (
        "Handbook 22 \u2014 type unknown, generic fallback "
        "(check SIMBAD/cache, extend stella)"
    )


# ── SIMBAD webfetch (offline-first: only on cache miss, Timeout 5s) ─────

SIMBAD_URL_TEMPLATE = (
    "https://simbad.cds.unistra.fr/simbad/sim-id?Ident={}&output.format=ASCII"
)


def _parse_simbad_ascii(text: str, target: str) -> dict[str, str] | None:
    """Best-effort ASCII parse — never raises, None on no match."""
    otype_match = re.search(r"Object type:\s*(.+)", text)
    if not otype_match:
        return None
    name_match = re.search(r"^Object\s+(.+?)\s*---", text, re.MULTILINE)
    return {
        "simbad_name": name_match.group(1).strip() if name_match else target,
        "otype_text": otype_match.group(1).strip(),
    }


def query_simbad(target: str, timeout: float = 5.0) -> dict[str, str] | None:
    """Single best-effort SIMBAD lookup (stdlib only, no new dependency).

    Only called on a cache miss (offline-first, hal). Returns None on ANY
    failure (timeout, DNS, HTTP error, unparsable response) — the caller
    treats that identically to "offline" (AC-SUG-4, OQ-SUG-1). Monkeypatched
    in tests (no real network in the suite, S10).
    """
    url = SIMBAD_URL_TEMPLATE.format(urllib.parse.quote(target))
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            text = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    return _parse_simbad_ascii(text, target)


# ── FITS header (SUG-2, lokal, kein Cloud) ──────────────────────────────

HEADER_KEYS: tuple[str, ...] = ("OBJECT", "FILTER", "EXPTIME", "TELESCOP", "DET-TEMP")
REQUIRED_HEADER_KEYS: tuple[str, ...] = ("OBJECT", "FILTER", "EXPTIME", "TELESCOP")


def read_fits_header(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read OBJECT/FILTER/EXPTIME/TELESCOP/DET-TEMP from a local FITS header.

    Mandatory-Validation analog V1.6-1 SSOT: missing keys are collected
    (subset of ``REQUIRED_HEADER_KEYS``) but never raise — the caller logs
    ``suggest.header_incomplete`` and continues (SUG-2).
    """
    from astropy.io import fits

    header = fits.getheader(str(path))
    data: dict[str, Any] = {}
    missing: list[str] = []
    for key in HEADER_KEYS:
        value = header.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if key in REQUIRED_HEADER_KEYS:
                missing.append(key)
            continue
        data[key] = value
    return data, missing


def _resolve_mount_hint(header_data: dict[str, Any]) -> tuple[str, str | None]:
    """Mount type from a (possibly empty) header dict.

    Without ANY header/telescope info the mount is genuinely ambiguous —
    returns ``"unknown"`` rather than delegating to
    ``core.equipment.detect_mount_type``'s EQ-fallback (which is meant for
    the pipeline's discovery phase where "no info" -> conservative EQ;
    the advisor instead offers both options, SUG-3 "zweite nur bei
    ambigem Mount").
    """
    telescope = header_data.get("TELESCOP")
    if not telescope:
        return "unknown", None
    return detect_mount_type(header_data), telescope


def build_registration_options(
    mount_type: str, telescope: str | None, exptime: Any = None
) -> list[dict[str, Any]]:
    """Registration recommendation(s) (SUG-2 Heuristik, V19-REG-SMART-Zitat).

    - AZ (incl. dwarf_mini) -> astroalign, 15 deg (dwarf_mini) / 30 deg
      (generic AZ).
    - EQ -> fft (<120s) / astroalign (>120s).
    - Unknown mount (no header at all) -> ambiguous: offer BOTH (AZ-assumed
      recommended + EQ-alternative) instead of guessing (SUG-3: "zweite nur
      bei ambigem Mount").
    """
    telescope_lower = (telescope or "").lower()
    if mount_type == "az":
        is_dwarf_mini = "dwarf" in telescope_lower and "mini" in telescope_lower
        rotation = 15.0 if is_dwarf_mini else 30.0
        label = f"AZ, {telescope}" if telescope else "AZ"
        return [
            {
                "method": "astroalign",
                "max_rotation_deg": rotation,
                "mount_label": label,
                "recommended": True,
            }
        ]
    if mount_type == "eq":
        try:
            exptime_f = float(exptime) if exptime is not None else 0.0
        except (TypeError, ValueError):
            exptime_f = 0.0
        if exptime_f > 120:
            return [
                {
                    "method": "astroalign",
                    "max_rotation_deg": 30.0,
                    "mount_label": "EQ, long exposure",
                    "recommended": True,
                }
            ]
        return [
            {
                "method": "fft",
                "max_rotation_deg": 2.0,
                "mount_label": "EQ",
                "recommended": True,
            }
        ]
    # unknown -> ambiguous (no header/telescope info at all)
    return [
        {
            "method": "astroalign",
            "max_rotation_deg": 30.0,
            "mount_label": "AZ, assumed (no header)",
            "recommended": True,
        },
        {
            "method": "fft",
            "max_rotation_deg": 2.0,
            "mount_label": "EQ, alternative (if mount was EQ)",
            "recommended": False,
        },
    ]


def _build_cli(
    target: str, preset: str, method: str, max_rotation: float,
    debayer_method: str, pcc_enabled: bool,
) -> str:
    pcc_flag = "--pcc" if pcc_enabled else "--no-pcc"
    return (
        f'astra process "{target}" --preset {preset} '
        f"--registration-method {method} --max-rotation {max_rotation:g} "
        f"--debayer-method {debayer_method} {pcc_flag}"
    )


_FALLBACK_PRESET_PAIRS: tuple[tuple[str, bool], ...] = (
    ("nebula_standard", True),
    ("galaxy_standard", False),
)


def _build_fallback_options(
    target: str, mount_type: str, telescope: str | None, exptime: Any,
    debayer_method: str, citation: str,
) -> list[dict[str, Any]]:
    """Generic 2-option fallback (unknown target, cache miss, SIMBAD unavailable)."""
    reg_opts = build_registration_options(mount_type, telescope, exptime)
    primary = reg_opts[0]
    options: list[dict[str, Any]] = []
    for index, (preset_name, recommended) in enumerate(_FALLBACK_PRESET_PAIRS, start=1):
        pcc_enabled = preset_name == "galaxy_standard"
        options.append(
            {
                "index": index,
                "preset": preset_name,
                "registration_method": primary["method"],
                "max_rotation_deg": primary["max_rotation_deg"],
                "debayer_method": debayer_method,
                "pcc_enabled": pcc_enabled,
                "recommended": recommended,
                "why": (
                    f"{citation} \u2014 generic fallback (cache miss, SIMBAD "
                    "unavailable; check/extend stella target-cache.md)"
                ),
                "cli": _build_cli(
                    target, preset_name, primary["method"],
                    primary["max_rotation_deg"], debayer_method, pcc_enabled,
                ),
            }
        )
    return options


# ── Result ────────────────────────────────────────────────────────────


@dataclass
class SuggestResult:
    target: str
    simbad_name: str
    type_slug: str
    handbook_ref: str
    source: str  # cache | header | simbad | handbook_fallback
    cache_path: Path | None
    header: dict[str, Any]
    warnings: list[str]
    options: list[dict[str, Any]]
    debayer_method: str
    darks_hint: str
    top_level_preset: str


def build_result(
    target: str | None,
    header_path: Path | None = None,
    coords: tuple[float, float] | None = None,
    cache_path: Path | None = None,
) -> SuggestResult:
    """Assemble a full suggestion (SUG-1/2/3): Header > Cache > SIMBAD > Handbook.

    Never raises for offline/cache-miss (AC-SUG-4) — only raises
    ``SuggestInputError`` when TARGET/--header/--coords cannot resolve any
    target at all (genuine usage error, turned into a ``ClickException`` by
    the CLI command).
    """
    header_data: dict[str, Any] = {}
    warnings: list[str] = []

    if header_path is not None:
        header_data, missing = read_fits_header(header_path)
        if missing:
            warnings.append("suggest.header_incomplete")
            logger.warning(
                "suggest.header_incomplete", missing=missing, path=str(header_path)
            )

    header_object = header_data.get("OBJECT")
    effective_target = target
    if header_object:
        if target and _normalize(str(header_object)) != _normalize(str(target)):
            warnings.append("suggest.header_overrides_target")
            logger.warning(
                "suggest.header_overrides_target",
                target=target, header_object=header_object,
            )
            effective_target = str(header_object)
        elif not target:
            effective_target = str(header_object)

    if not effective_target and coords is not None:
        warnings.append("suggest.coords_fallback")
        logger.warning("suggest.coords_fallback", coords=coords)
        effective_target = f"RA{coords[0]:g}_DEC{coords[1]:g}"

    if not effective_target:
        raise SuggestInputError("TARGET, --header, or --coords is required")

    entries = load_target_cache(cache_path)
    entry = find_cache_entry(effective_target, entries)

    mount_type, telescope_name = _resolve_mount_hint(header_data)
    exptime_hint = header_data.get("EXPTIME")
    debayer_method = "superpixel"

    astra_preset: str | None
    if entry is not None:
        source = "cache"
        simbad_name = entry.get("SIMBAD-Name") or effective_target
        typ_text = entry.get("Typ", "")
        astra_preset = (entry.get("Astra-Preset") or "").strip("` ") or None
        type_slug, citation = classify_and_cite(typ_text)
        handbook_field = (entry.get("Handbook") or "").strip()
        handbook_ref = f"{citation} (cache: {handbook_field})" if handbook_field else citation
    else:
        simbad_data: dict[str, str] | None = None
        try:
            simbad_data = query_simbad(effective_target)
        except Exception:  # noqa: BLE001 - offline-first: nie abbruchbehaftet
            simbad_data = None
        if simbad_data:
            source = "simbad"
            simbad_name = simbad_data.get("simbad_name", effective_target)
            typ_text = simbad_data.get("otype_text", "")
            type_slug, citation = classify_and_cite(typ_text)
            astra_preset = _PRESET_BY_TYPE_SLUG.get(type_slug)
            handbook_ref = citation
        else:
            source = "handbook_fallback"
            warnings.append("suggest.simbad_unavailable")
            logger.warning(
                "suggest.simbad_unavailable",
                target=effective_target,
                detail="Offline \u2014 cache-only, SIMBAD unreachable",
            )
            simbad_name = effective_target
            astra_preset = None
            type_slug, citation = "unknown", classify_and_cite("")[1]
            handbook_ref = citation

    if astra_preset is None:
        options = _build_fallback_options(
            effective_target, mount_type, telescope_name, exptime_hint,
            debayer_method, citation,
        )
        top_level_preset = options[0]["preset"]
    else:
        pcc_enabled = astra_preset == "galaxy_standard"
        reg_opts = build_registration_options(mount_type, telescope_name, exptime_hint)
        options = []
        for index, reg_opt in enumerate(reg_opts, start=1):
            why = (
                f"{handbook_ref}; {reg_opt['mount_label']} -> "
                f"{reg_opt['method']} {reg_opt['max_rotation_deg']:g}\u00b0"
            )
            options.append(
                {
                    "index": index,
                    "preset": astra_preset,
                    "registration_method": reg_opt["method"],
                    "max_rotation_deg": reg_opt["max_rotation_deg"],
                    "debayer_method": debayer_method,
                    "pcc_enabled": pcc_enabled,
                    "recommended": reg_opt["recommended"],
                    "why": why,
                    "cli": _build_cli(
                        effective_target, astra_preset, reg_opt["method"],
                        reg_opt["max_rotation_deg"], debayer_method, pcc_enabled,
                    ),
                }
            )
        top_level_preset = astra_preset

    darks_hint = f'astra darks check "{effective_target}"'

    return SuggestResult(
        target=effective_target,
        simbad_name=simbad_name,
        type_slug=type_slug,
        handbook_ref=handbook_ref,
        source=source,
        cache_path=Path(cache_path) if cache_path else None,
        header=header_data,
        warnings=warnings,
        options=options,
        debayer_method=debayer_method,
        darks_hint=darks_hint,
        top_level_preset=top_level_preset,
    )


# ── Rendering ────────────────────────────────────────────────────────────


def _source_line(source: str, cache_path: Path | None) -> str:
    if source == "cache":
        location = str(cache_path) if cache_path else "target-cache.md"
        return f"Source: cache hit ({location}) \u2014 SIMBAD not queried (offline-first)"
    if source == "simbad":
        return "Source: simbad webfetch (cache miss, network available)"
    if source == "handbook_fallback":
        return "Source: cache miss, simbad unavailable \u2014 offline"
    return f"Source: {source}"


def render_human(result: SuggestResult) -> str:
    """Human-readable stdout (English, SUG-3, handbook-zitierend)."""
    lines: list[str] = [
        f"Target: {result.target} ({result.simbad_name}) \u2014 {result.type_slug} "
        f"(source: {result.source})"
    ]
    if result.header:
        parts = [f"{k}={v}" for k, v in result.header.items()]
        lines.append("Header: " + ", ".join(parts))
    lines.append(_source_line(result.source, result.cache_path))
    for warning in result.warnings:
        lines.append(f"[WARN] {warning}")
    lines.append("")
    for opt in result.options:
        marker = "  [RECOMMENDED]" if opt["recommended"] else ""
        lines.append(
            f"{opt['index']}) {opt['preset']} + {opt['registration_method']} "
            f"{opt['max_rotation_deg']:g}\u00b0{marker}"
        )
        lines.append(f"   Why: {opt['why']}")
        lines.append(f"   CLI: {opt['cli']}")
        lines.append(
            f"   Debayer: {opt['debayer_method']} (default), malvar (HQ "
            "alternative), cfa-drizzle (only after quality-gate pass + "
            ">50 dithered frames \u2014 pipeline decides, this is a hint only)"
        )
        lines.append(f"   Darks: run '{result.darks_hint}' for coverage (V19-DARKS-SYNC)")
        lines.append("")
    lines.append(f"Refs: {result.handbook_ref}")
    return "\n".join(lines)


def to_json_dict(result: SuggestResult) -> dict[str, Any]:
    """SUG-3/SUG-4 machine-readable schema (top-level = first/recommended option)."""
    primary = result.options[0]
    return {
        "target": result.target,
        "simbad_name": result.simbad_name,
        "type": result.type_slug,
        "handbook_ref": result.handbook_ref,
        "source": result.source,
        "preset": result.top_level_preset,
        "registration": {
            "method": primary["registration_method"],
            "max_rotation_deg": primary["max_rotation_deg"],
        },
        "debayer": {"method": result.debayer_method},
        "pcc": {"enabled": primary["pcc_enabled"]},
        "warnings": list(result.warnings),
        "options": result.options,
    }


def to_file_dict(result: SuggestResult) -> dict[str, Any]:
    """SUG-4 file schema (Version 1, extra="ignore"-tolerant).

    Adds the optional ``equipment_hint``/``filter_hint``/``exptime_hint``
    fields (Spec SUG-4, Handbook \u00a717.2, template
    ``templates/suggested_parameters.yaml``) derived from the FITS header
    (``--header``) when available. These hints are informational only \u2014
    ``process --from-suggested`` (SUG-5) never reads them, only
    preset/registration/debayer/pcc. ``None`` when no header was supplied
    (rendered as ``null`` in the template, never a stale placeholder).
    """
    data = to_json_dict(result)
    data["version"] = 1
    header = result.header or {}
    telescope = header.get("TELESCOP")
    data["equipment_hint"] = (
        str(telescope).strip().lower().replace(" ", "_") if telescope else None
    )
    filter_name = header.get("FILTER")
    data["filter_hint"] = str(filter_name) if filter_name else None
    exptime = header.get("EXPTIME")
    data["exptime_hint"] = exptime if exptime is not None else None
    return data


def default_output_path(target: str, data_root: Path | str = Path("C:/Astra")) -> Path:
    """Default ``--output`` target (SUG-1/4): ``<data_root>/<Target>/suggested.yaml``."""
    return Path(data_root) / target / "suggested.yaml"


# Repo template (paige-maintained comments, backy-filled values). Not shipped
# in the PyPI wheel (pyproject.toml `packages = ["src/astro_process"]` only)
# -- ``_render_from_template`` returns ``None`` when absent and the caller
# falls back to a plain ``yaml.safe_dump`` (same degrade-gracefully pattern
# as ``config/loader.py`` DEFAULT_CONFIG for a missing ``config.yaml``).
_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "templates" / "suggested_parameters.yaml"

_TEMPLATE_LINE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*):(?P<rest>.*)$")
_TEMPLATE_VALUE_RE = re.compile(
    r'^(?P<ws>\s*)(?P<value>"(?:[^"\\]|\\.)*"|\'[^\']*\'|[^\s#]+)?(?P<trailing>.*)$'
)


def _yaml_scalar_repr(value: Any) -> str:
    """Render a Python scalar as an inline YAML scalar (quoted when YAML needs it)."""
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True)
    if dumped.endswith("\n...\n"):
        dumped = dumped[: -len("\n...\n")]
    return dumped.rstrip("\n")


def _fill_template(text: str, values: dict[str, Any]) -> str:
    """Fill scalar values into the template text, preserving every comment
    and blank line verbatim.

    This is a line-based fill, NOT a full YAML round-trip: only lines whose
    key matches an entry in ``values`` are rewritten (dotted keys address
    one level of nesting, e.g. ``"registration.method"``); everything else
    (comments, block headers like ``registration:``, unknown/renamed keys)
    passes through untouched. That tolerance mirrors
    ``load_suggested_file``'s ``extra="ignore"`` spirit \u2014 a template edit
    that adds/removes a comment can never break this function (S17).
    """
    out_lines: list[str] = []
    parent: str | None = None
    for raw_line in text.splitlines():
        m = _TEMPLATE_LINE_RE.match(raw_line)
        if not m:
            out_lines.append(raw_line)
            continue
        indent, key, rest = m.group("indent"), m.group("key"), m.group("rest")
        is_block_header = rest.strip() == ""
        if indent == "":
            lookup_key = key
            parent = key if is_block_header else None
        else:
            lookup_key = f"{parent}.{key}" if parent else key
        if is_block_header or lookup_key not in values:
            out_lines.append(raw_line)
            continue
        vm = _TEMPLATE_VALUE_RE.match(rest)
        ws = (vm.group("ws") if vm else " ") or " "
        trailing = vm.group("trailing") if vm else ""
        out_lines.append(f"{indent}{key}:{ws}{_yaml_scalar_repr(values[lookup_key])}{trailing}")
    rendered = "\n".join(out_lines)
    return rendered if rendered.endswith("\n") else rendered + "\n"


def _render_from_template(data: dict[str, Any]) -> str | None:
    """Render ``data`` (SUG-4 file schema) into the repo template, keeping
    its comments (see ``templates/suggested_parameters.yaml``).

    Returns ``None`` when the template is not on disk so the caller can
    fall back to a plain ``yaml.safe_dump`` (PyPI wheel install, no repo
    checkout).
    """
    if not _TEMPLATE_PATH.is_file():
        return None
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    reg = data.get("registration") or {}
    deb = data.get("debayer") or {}
    pcc = data.get("pcc") or {}
    values: dict[str, Any] = {
        "version": data.get("version", 1),
        "target": data.get("target"),
        "simbad_name": data.get("simbad_name"),
        "type": data.get("type"),
        "handbook_ref": data.get("handbook_ref"),
        "source": data.get("source"),
        "preset": data.get("preset"),
        "registration.method": reg.get("method"),
        "registration.max_rotation_deg": reg.get("max_rotation_deg"),
        "debayer.method": deb.get("method"),
        "pcc.enabled": pcc.get("enabled"),
        # Always present (None -> "null") so a missing hint never leaves a
        # stale example placeholder (e.g. "dwarf_mini") in the output file.
        "equipment_hint": data.get("equipment_hint"),
        "filter_hint": data.get("filter_hint"),
        "exptime_hint": data.get("exptime_hint"),
    }
    return _fill_template(text, values)


def write_suggested_file(data: dict[str, Any], path: Path) -> None:
    """Write the suggested_parameters file (YAML default, JSON on ``.json`` suffix).

    Overwrite-Semantik: immer 1 Satz (SUG-4) \u2014 caller passes the target
    explicit path; this function always overwrites (no auto-history). YAML
    output is rendered from ``templates/suggested_parameters.yaml`` when
    that template is available (Spec SUG-4: "Basis ist Template
    ``astra/templates/suggested_parameters.yaml``"), falling back to a
    plain ``yaml.safe_dump`` otherwise (PyPI wheel install).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return
    rendered = _render_from_template(data)
    if rendered is None:
        rendered = yaml.safe_dump(data, sort_keys=False)
    path.write_text(rendered, encoding="utf-8")


def load_suggested_file(path: Path) -> dict[str, Any]:
    """Read a suggested_parameters file (YAML/JSON via suffix) for SUG-5.

    Tolerant (``extra="ignore"``-Geist, SUG-4): any dict is accepted,
    unknown keys are simply not looked at by the caller.
    """
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"--from-suggested: '{path}' does not contain a valid mapping")
    return data
