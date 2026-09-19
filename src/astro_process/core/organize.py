"""V1.12-ORGANIZE — astra organize grouping (MOVE-semantics, FITS SSOT, FILTER/EQMODE, SOLL, AZ/EQ, Moon, duplicate, exclusivity).

Implements `astra organize <Target> [--dry-run] [--all]` per spec v2.

- Reads ONLY `lights/*.fit*` in root (non-recursive), FITS header SSOT via parse_fits_header
- FILTER normalized duo-band/astro, EQMODE split per folder (_eq0/_eq1/_eq_unknown only when split)
- Groups by (EXPTIME, GAIN, FILTER_norm, EQMODE) → physical MOVE via os.rename into lights/group_*/ 
- Duplicate cleanup (size+mtime), idempotent, <3 SKIPPED but still moved, warnings, SOLL, AZ/EQ mix, Moon, --dry-run table
- Lights-exclusivity guard: only inbox frames + group_* allowed, fremde Unterordner → warning + skipped
- Name resolution ORG-X2 (filesystem scan, exact/prefix/case-insensitive, did-you-mean)
- --all iterates data_root ignoring generated/_darks/_work/_foren/_sammlung/siril-scripts
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
from pathlib import Path
from typing import Optional

import structlog

from ..models.core import compute_group_hash

logger = structlog.get_logger(__name__)

FITS_SUFFIXES = (".fit", ".fits", ".fts")

IGNORED_ALL_DIRS = {
    "_darks",
    "generated",
    "_work",
    "_foren",
    "_sammlung",
    "siril-scripts",
    "_archive",
    ".git",
    "__pycache__",
    ".venv",
    "siril",
    "_lights",  # not real target
}

# ──────────────────────────────────────────────────────────────────────────
# FILTER normalization (OR 3, A4)
# ──────────────────────────────────────────────────────────────────────────

def normalize_filter(raw: str | None) -> str:
    """Normalize FILTER header value to astro/duo-band/unknown or generic lower.

    - Astro variants: Astro, ASTRO, L, luminance, clear → astro
    - Duo-Band variants: Duo-Band, duo-band, dual, duo, duoband → duo-band
    - None/empty → unknown
    - else → lower+trim (generic fallback)
    """
    if raw is None:
        return "unknown"
    s = str(raw).strip()
    if not s:
        return "unknown"
    low = s.lower().strip()
    # Normalize separators to hyphen for matching
    norm_key = re.sub(r"[\s_]+", "-", low)
    # Also collapse multiple hyphens? keep single
    norm_key = re.sub(r"-+", "-", norm_key)
    astro_set = {"astro", "l", "luminance", "clear"}
    duo_set = {"duo-band", "duo", "dual", "duoband"}
    # Check both low and norm_key
    if low in astro_set or norm_key in astro_set:
        return "astro"
    if low in duo_set or norm_key in duo_set:
        return "duo-band"
    # Handle duo-band variants like duo_band (now duo-band) and duo band
    if norm_key == "duo-band":
        return "duo-band"
    return low


def _exptime_label(exptime: float) -> str:
    """Format exptime for folder name: int if integer else g-format."""
    try:
        fv = float(exptime)
    except Exception:
        return str(exptime)
    if fv == int(fv):
        return str(int(fv))
    # Use g to avoid trailing zeros and python repr issues
    return format(fv, "g")


# ──────────────────────────────────────────────────────────────────────────
# ORG-X2: Name → Pfad Auflösung (exact/prefix case-insensitive, no cache)
# ──────────────────────────────────────────────────────────────────────────

def resolve_target_path(target_arg: str | Path, data_root: Path) -> Path:
    """Resolve <Target> argument to absolute target directory.

    - If target_arg is an existing directory (absolute or relative path with separator or existing), use directly
    - Else treat as name: scan data_root for exact case-insensitive match OR unique prefix
    - Multiple prefix hits → error with candidate list
    - No hit → did-you-mean via difflib, error
    """
    t_str = str(target_arg).strip()
    p = Path(t_str)
    # If absolute or contains separator or exists as path relative to cwd
    if p.is_absolute() or (os.sep in t_str or "/" in t_str or "\\" in t_str):
        # Try resolve if exists
        cand = p.resolve() if p.exists() else p
        # If it exists and is dir, use it
        if cand.exists() and cand.is_dir():
            return cand.resolve()
        # If data_root / t_str exists (e.g., relative name with slash)
        # Try data_root combined?
        # Still treat as path error if not exists
        if cand.exists():
            return cand.resolve()
        # If path-like but not existing → will be handled as not found later
        # Fall through to name matching if not containing sep? but we already detected sep
        # For path-like not existing, raise not found
        raise FileNotFoundError(f"organize.target_not_found: {cand} not found")
    # Check if target_arg directly exists as directory under data_root (exact)
    # Also handle case where t_str is absolute path string already handled, but name case
    data_root = Path(data_root).resolve()
    if not data_root.exists():
        raise FileNotFoundError(f"organize.target_not_found: data_root {data_root} not found")
    # List immediate subdirs
    try:
        entries = [d for d in data_root.iterdir() if d.is_dir()]
    except Exception as e:
        raise FileNotFoundError(f"organize.target_not_found: cannot scan data_root {data_root}: {e}") from e
    low = t_str.lower()
    # Exact case-insensitive
    exact = [d for d in entries if d.name.lower() == low]
    if len(exact) == 1:
        return exact[0].resolve()
    if len(exact) > 1:
        # Should not happen (duplicate names case-insensitive) → list
        names = ", ".join(sorted(d.name for d in exact))
        raise ValueError(f"organize.ambiguous_target: multiple exact matches for '{t_str}': {names}")
    # Prefix case-insensitive
    prefix = [d for d in entries if d.name.lower().startswith(low)]
    if len(prefix) == 1:
        return prefix[0].resolve()
    if len(prefix) > 1:
        names = ", ".join(sorted(d.name for d in prefix))
        raise ValueError(f"organize.ambiguous_target: multiple targets match prefix '{t_str}': {names} — be more specific")
    # No hit → did-you-mean
    all_names = [d.name for d in entries]
    # Use difflib get_close_matches
    suggestions = difflib.get_close_matches(t_str, all_names, n=3, cutoff=0.5)
    if suggestions:
        sug = ", ".join(suggestions)
        raise FileNotFoundError(f"organize.target_not_found: '{t_str}' not found — did you mean: {sug}?")
    raise FileNotFoundError(f"organize.target_not_found: '{t_str}' not found in {data_root}")


# ──────────────────────────────────────────────────────────────────────────
# GROUP-SELECT ORG-X2 reuse: Gruppen-Name-Matching (exact/Prefix/Did-you-mean)
# ──────────────────────────────────────────────────────────────────────────

def resolve_group_selection(requested: list[str], existing: list[str]) -> list[str]:
    """ORG-X2 Gruppen-Matching fuer V1.12-GROUP-SELECT (reuse via cli + staging).

    - Exakt case-insensitiv gewinnt (auch bei mehreren Prefix-Treffern)
    - Sonst eindeutiger Prefix (case-insensitiv) gewinnt
    - Sonst 0 Treffer -> Did-you-mean via difflib, Error "not found, existing: ..."
    - Sonst >1 Treffer -> Error "ambiguous, did you mean: G1, G2?"

    Args:
        requested: Vom User geforderte Gruppen-Namen (raw, kann Prefix sein).
        existing: Existierende Gruppenordner-Namen (voll, z.B. group_30s40_duo-band).

    Returns:
        Liste kanonischer Namen (je requested ein Treffer, Reihenfolge preserved).

    Raises:
        ValueError mit prefix "process.group_not_found" oder "process.group_ambiguous"
    """
    if not requested:
        return []
    resolved: list[str] = []
    existing_sorted = sorted(existing)
    for raw_req in requested:
        req = str(raw_req).strip()
        if not req:
            continue
        low = req.lower()
        candidates = [g for g in existing if g.lower().startswith(low)]
        if len(candidates) == 0:
            # Did-you-mean via difflib (cutoff 0.5, max 3) + volle Liste als Fallback
            suggestions = difflib.get_close_matches(req, existing_sorted, n=3, cutoff=0.5)
            hint = ", ".join(suggestions) if suggestions else ", ".join(existing_sorted)
            raise ValueError(f"process.group_not_found: {req}, existing: {', '.join(existing_sorted)}" + (f" — did you mean: {hint}?" if suggestions else ""))
        if len(candidates) > 1:
            exact = [g for g in candidates if g.lower() == low]
            if len(exact) == 1:
                resolved.append(exact[0])
                continue
            raise ValueError(f"process.group_ambiguous: {req}, did you mean: {', '.join(sorted(candidates))}?")
        resolved.append(candidates[0])
    return resolved


# ──────────────────────────────────────────────────────────────────────────
# SOLL parsing
# ──────────────────────────────────────────────────────────────────────────

def _parse_soll_file(target_dir: Path) -> Optional[set[tuple]]:
    """Parse SOLL triples from AUFNAHMELISTE_*.md in target_dir.

    Returns set of (exp, gain, filter_norm) or None if no file, or empty set if file exists but parsing yields nothing (treated as n/a).
    exp normalized: int if integer else float (same as grouping)
    """
    # Find AUFNAHMELISTE file
    candidates = list(target_dir.glob("AUFNAHMELISTE*.md"))
    # Also case-insensitive search
    if not candidates:
        for p in target_dir.iterdir():
            if p.is_file() and p.name.lower().startswith("aufnahmeliste"):
                candidates.append(p)
                break
    if not candidates:
        return None
    soll_path = candidates[0]
    try:
        text = soll_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()
    soll: set[tuple] = set()
    lines = text.splitlines()
    # First pass: structured Serie tables (Belichtung / Gain / Filter rows)
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.search(r"Belichtung", line, re.I):
            m_exp = re.search(r"(\d+(?:\.\d+)?)\s*s", line, re.I)
            if m_exp:
                try:
                    exp_val = float(m_exp.group(1))
                except Exception:
                    exp_val = None
                gain_val = None
                filter_val = None
                # look ahead 6 lines
                for j in range(i, min(i + 7, len(lines))):
                    if re.search(r"\bGain\b", lines[j], re.I):
                        m_g = re.search(r"(\d+)", lines[j])
                        if m_g:
                            try:
                                gain_val = int(m_g.group(1))
                            except Exception:
                                pass
                    if re.search(r"\bFilter\b", lines[j], re.I):
                        # Try to extract after | split
                        parts = [p.strip() for p in lines[j].split("|") if p.strip() and p.strip().lower() not in ("filter", "parameter", "wert")]
                        # Heuristic: last part that looks like filter name
                        cand = None
                        for p in parts:
                            if re.search(r"astro|duo|dual|luminance|clear|l\b", p, re.I):
                                cand = p
                                break
                        if cand is None and len(parts) >= 1:
                            # take the value column (second column) if exists
                            # lines like "| Filter | Astro |" → parts = ["Filter","Astro"] → pick last
                            cand = parts[-1] if parts else None
                        if cand:
                            filter_val = cand
                if exp_val is not None and gain_val is not None and filter_val is not None:
                    exp_norm = int(exp_val) if float(exp_val) == int(exp_val) else exp_val
                    filt_norm = normalize_filter(filter_val)
                    soll.add((exp_norm, gain_val, filt_norm))
        i += 1
    # Fallback global scan if still empty: search for patterns like "60s60" + filter nearby
    if not soll:
        # Global regex for "60s60 duo-band" or "60s 60 astro" patterns
        pat = re.compile(r"(\d+(?:\.\d+)?)\s*s\s*(\d+)\s*(?:_|\s)?\s*(astro|duo-band|duo|dual|luminance|clear|l)\b", re.I)
        for m in pat.finditer(text):
            try:
                exp_v = float(m.group(1))
                gain_v = int(m.group(2))
                filt_v = m.group(3)
                exp_n = int(exp_v) if float(exp_v) == int(exp_v) else exp_v
                soll.add((exp_n, gain_v, normalize_filter(filt_v)))
            except Exception:
                continue
        # Also scan for separate lines like "60s 40 Astro" in SOLL/IST tables
        # Search for lines containing filter name and numbers
        for line in lines:
            if re.search(r"astro|duo", line, re.I):
                # try to extract two numbers
                nums = re.findall(r"(\d+(?:\.\d+)?)", line)
                if len(nums) >= 2:
                    try:
                        # First is exptime (with s maybe), second is gain
                        # Check if line contains s
                        if "s" in line.lower():
                            exp_c = float(nums[0])
                            gain_c = int(float(nums[1]))
                            # filter from line
                            filt_c = "astro" if re.search(r"astro|luminance|clear", line, re.I) else "duo-band" if re.search(r"duo|dual", line, re.I) else None
                            if filt_c:
                                exp_n = int(exp_c) if float(exp_c)==int(exp_c) else exp_c
                                soll.add((exp_n, gain_c, filt_c))
                    except Exception:
                        continue
    return soll


# ──────────────────────────────────────────────────────────────────────────
# Core grouping
# ──────────────────────────────────────────────────────────────────────────

def _scan_lights_root(lights_dir: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Return (root_fits, group_dirs, unexpected_dirs)."""
    root_fits: list[Path] = []
    group_dirs: list[Path] = []
    unexpected_dirs: list[Path] = []
    try:
        for entry in lights_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() in FITS_SUFFIXES:
                root_fits.append(entry)
            elif entry.is_dir():
                if entry.name.lower().startswith("group_"):
                    group_dirs.append(entry)
                else:
                    unexpected_dirs.append(entry)
    except FileNotFoundError:
        return [], [], []
    return sorted(root_fits), sorted(group_dirs), sorted(unexpected_dirs)


def organize_target(target_dir: Path, dry_run: bool = False) -> dict:
    """Organize single target.

    Returns dict with keys: target, groups (list of dict), warnings, moved, duplicates_cleaned, status, etc.
    Raises FileNotFoundError for no_lights, ValueError for ambiguous etc.
    """
    target_dir = Path(target_dir).resolve()
    lights_dir = target_dir / "lights"
    # Guard: lights exists and not empty (or has groups)
    if not lights_dir.is_dir():
        raise FileNotFoundError(f"organize.no_lights: {target_dir.name}/lights not found or empty — place FITS in lights")
    root_fits, group_dirs, unexpected_dirs = _scan_lights_root(lights_dir)
    # Unexpected subfolders warning
    for ud in unexpected_dirs:
        try:
            cnt = sum(1 for _ in ud.rglob("*") if _.is_file())
        except Exception:
            cnt = 0
        logger.warning("organize.unexpected_subfolder", subfolder=ud.name, files=cnt, target=str(target_dir))
        # Also for stage_input: will be skipped
    # If no root fits and no groups? Check empty
    # But if there are group dirs and no root fits → nothing to organize (idempotent)
    # If absolutely empty (no root fits and no group dirs and no unexpected with fits) → no_lights error per spec (empty)
    total_existing_fits = len(root_fits) + sum(
        sum(1 for p in gd.rglob("*") if p.is_file() and p.suffix.lower() in FITS_SUFFIXES) for gd in group_dirs
    )
    if not root_fits and not group_dirs:
        # Check if lights dir is empty (no fits at all)
        # Might still have unexpected dirs with fits? Those are not counted as lights for organize, but for error we consider lights empty
        raise FileNotFoundError(f"organize.no_lights: {target_dir.name}/lights not found or empty — place FITS in lights")
    if not root_fits and group_dirs:
        # Nothing to organize (all already sorted)
        logger.info("organize.nothing_to_organize", target=str(target_dir))
        # Still need to produce groups table from existing groups for dry_run? For real run, return info
        # Build groups from existing group dirs? For dry_run we want to show existing groups.
        # For this function, if no root fits, we can still enumerate groups from group_dirs by parsing folder names? Or by scanning group dirs headers?
        # For idempotent case, we should still report groups.
        # We'll enumerate groups by scanning group_dirs FITS headers to build table (best effort).
        # If dry_run, we can still produce table.
        pass

    # Group root fits via FITS header SSOT
    # Import here to avoid circular
    from .fits_parser import parse_fits_header

    groups_by_key: dict[tuple, list[Path]] = {}
    skipped_header: list[Path] = []
    # For warnings: header_incomplete, filter_missing
    for fpath in root_fits:
        try:
            header = parse_fits_header(fpath)
        except Exception as e:
            logger.warning("organize.header_incomplete", file=str(fpath), reason=str(e))
            skipped_header.append(fpath)
            continue
        exptime = header.exptime
        gain = header.gain
        # Explicit None vs 0 distinction: gain 0 is valid, None is missing
        if exptime is None or gain is None:
            logger.warning("organize.header_incomplete", file=str(fpath), exptime=exptime, gain=gain)
            skipped_header.append(fpath)
            continue
        filter_norm = normalize_filter(header.filter_name)
        if filter_norm == "unknown":
            logger.warning("organize.filter_missing", file=str(fpath))
        eqmode = header.eq_mode  # 0/1/None
        # Normalize exptime for grouping: int if integer
        try:
            fv = float(exptime)
            exp_norm = int(fv) if fv == int(fv) else fv
        except Exception:
            exp_norm = exptime
        key = (exp_norm, int(gain), filter_norm, eqmode)
        groups_by_key.setdefault(key, []).append(fpath)

    # Determine need_suffix per (exp,gain,filter) triple
    triple_to_eqmodes: dict[tuple, set] = {}
    for (exp, gain, filt, eq), _files in groups_by_key.items():
        triple = (exp, gain, filt)
        triple_to_eqmodes.setdefault(triple, set()).add(eq)
    # Also need to consider existing group_dirs that already have suffix? For idempotent, we need to handle existing groups that already have correct naming.
    # But for table we will merge existing group info? The spec for organize says organize reads only lights root, not existing group_* double count. So grouping for dry-run should show groups from root + maybe existing groups? Actually for dry-run table after organizing, we want to show what would be created from root files. But also AC-ORG-X3 says organize --dry-run table lists root-frames + group-folder? Let's include both: if group_dirs exist, we should also enumerate those groups for completeness (maybe show existing groups as READY).
    # For simplicity, if no root fits but groups exist, we will enumerate existing groups for reporting.

    # Build group infos for table
    group_infos: list[dict] = []
    # Also collect for SOLL, AZ/EQ mix
    soll_set = _parse_soll_file(target_dir)
    # Build per-key folder name
    key_to_folder: dict[tuple, str] = {}
    for key, files in groups_by_key.items():
        exp, gain, filt, eq = key
        triple = (exp, gain, filt)
        need_suffix = len(triple_to_eqmodes.get(triple, set())) > 1
        base = f"group_{_exptime_label(exp)}s{gain}_{filt}"
        if need_suffix:
            if eq == 0:
                folder = base + "_eq0"
            elif eq == 1:
                folder = base + "_eq1"
            else:
                folder = base + "_eq_unknown"
        else:
            folder = base
        key_to_folder[key] = folder

    # Now build group_infos
    for key, files in sorted(groups_by_key.items()):
        exp, gain, filt, eq = key
        folder = key_to_folder[key]
        count = len(files)
        total_exp = float(exp) * count if isinstance(exp, (int, float)) else 0
        # EQMODE display
        if eq == 0:
            eq_display = "AZ(0)"
        elif eq == 1:
            eq_display = "EQ(1)"
        else:
            eq_display = "unknown"
        # Status
        if count < 3:
            status = "SKIPPED"
            # Warning structlog yellow
            logger.warning("organize.skipped_small_group", group=folder, frames=count)
        else:
            # Moon check: exptime <1s
            try:
                is_moon = float(exp) < 1.0
            except Exception:
                is_moon = False
            if is_moon:
                status = "READY (SIRIL — lucky imaging, no Astra preset)"
                logger.warning("organize.moon_group", group=folder, exptime=exp)
            else:
                status = "READY"
        # SOLL check
        soll_status = "n/a"
        if soll_set is not None:
            if soll_set == set():
                soll_status = "n/a"
            else:
                triple = (exp, gain, filt)
                # soll_set contains (exp,gain,filt) with same normalization
                if triple not in soll_set:
                    soll_status = "WARN not in SOLL"
                    logger.warning("organize.not_in_soll", group=folder, soll="AUFNAHMELISTE")
                else:
                    soll_status = "in SOLL"
        else:
            soll_status = "n/a"
        group_infos.append({
            "folder": folder,
            "key": key,
            "files": files,
            "count": count,
            "total_exp": total_exp,
            "exptime": exp,
            "gain": gain,
            "filter": filt,
            "eqmode": eq,
            "eq_display": eq_display,
            "status": status,
            "soll_status": soll_status,
        })

    # AZ/EQ mix warning across groups (different EQMODE between groups)
    eqmodes_present = set(k[3] for k in groups_by_key.keys())
    # Also consider triple mix? But spec says bei verschiedenen EQMODE-Werten zwischen Gruppen → Warnung
    if len(eqmodes_present) > 1:
        # Need to check if at least two different non-None? But spec says different EQMODE values between groups → warn
        # If we have 0 and 1, warn
        has_az = 0 in eqmodes_present
        has_eq = 1 in eqmodes_present
        has_unknown = None in eqmodes_present
        # Warn if at least two distinct values, especially AZ/EQ mix
        if (has_az and has_eq) or (has_unknown and (has_az or has_eq)):
            logger.warning("organize.azeq_mix_warning", target=str(target_dir), eqmodes=list(eqmodes_present), hint="separate runs recommended — GROUP-SELECT nutzen")
            # stdout warning will be added by caller (cli) as well?

    # Also need to consider existing groups enumeration for case where root_fits empty but groups exist (idempotent)
    # If group_infos empty and group_dirs present, build infos from existing group dirs for table
    if not group_infos and group_dirs:
        # Enumerate existing groups by scanning their FITS headers (best effort)
        # We will parse one file per group to get exp/gain/filter/eq
        for gd in group_dirs:
            fits_files = [p for p in gd.rglob("*") if p.is_file() and p.suffix.lower() in FITS_SUFFIXES]
            if not fits_files:
                continue
            # Take first file to infer group params
            try:
                from .fits_parser import parse_fits_header as _pfh
                hdr = _pfh(fits_files[0])
                exp_v = hdr.exptime if hdr.exptime is not None else 0
                gain_v = hdr.gain if hdr.gain is not None else 0
                filt_v = normalize_filter(hdr.filter_name)
                eq_v = hdr.eq_mode
                exp_norm = int(float(exp_v)) if float(exp_v)==int(float(exp_v)) else float(exp_v)
                count = len(fits_files)
                total_exp = float(exp_norm) * count if isinstance(exp_norm, (int,float)) else 0
                eq_display = "AZ(0)" if eq_v==0 else "EQ(1)" if eq_v==1 else "unknown"
                status = "SKIPPED" if count <3 else ("READY (SIRIL — lucky imaging, no Astra preset)" if float(exp_norm) <1 else "READY")
                # Use folder name as is
                folder = gd.name
                group_infos.append({
                    "folder": folder,
                    "key": (exp_norm, gain_v, filt_v, eq_v),
                    "files": [],
                    "count": count,
                    "total_exp": total_exp,
                    "exptime": exp_norm,
                    "gain": gain_v,
                    "filter": filt_v,
                    "eqmode": eq_v,
                    "eq_display": eq_display,
                    "status": status,
                    "soll_status": "n/a",
                })
            except Exception:
                # Fallback: folder name parsing
                continue
        # Sort
        group_infos = sorted(group_infos, key=lambda x: x["folder"])

    # Actual MOVE if not dry_run
    moved = 0
    duplicates_cleaned = 0
    idempotent_skipped = 0
    if not dry_run and groups_by_key:
        for key, files in groups_by_key.items():
            folder = key_to_folder[key]
            dest_dir = lights_dir / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            for src in files:
                dst = dest_dir / src.name
                if dst.exists():
                    # Check duplicate identical size+mtime
                    try:
                        same_size = dst.stat().st_size == src.stat().st_size
                        # Compare mtime with tolerance 2 seconds (filesystem granularity)
                        same_mtime = abs(dst.stat().st_mtime - src.stat().st_mtime) < 2
                        if same_size and same_mtime:
                            # Duplicate → remove src
                            src.unlink()
                            duplicates_cleaned += 1
                            logger.info("organize.duplicates_cleaned", group=folder, file=src.name)
                            continue
                        else:
                            # Already exists but not identical → idempotent skip (don't overwrite)
                            # Consider it already organized, but src still remains? For idempotent second run, src would not exist because already moved, so this path only for duplicate handling
                            # If dst exists and src still there but not identical, we should not overwrite; log skip and leave src?
                            # For now, treat as skip and do not move
                            logger.info("organize.idempotent_skip", group=folder, file=src.name)
                            idempotent_skipped += 1
                            continue
                    except Exception as e:
                        logger.warning("organize.move_failed", src=str(src), dst=str(dst), error=str(e))
                        continue
                try:
                    os.rename(str(src), str(dst))
                    moved += 1
                    logger.info("organize.move", src=str(src), dst=str(dst), group=folder)
                except Exception as e:
                    logger.warning("organize.move_failed", src=str(src), dst=str(dst), error=str(e))
                    continue
        # After moves, handle duplicates that were already in group and root (size+mtime identical) already cleaned
        # Also handle <3 groups: they were moved, but need warning already logged
        # Idempotent second run: if no files left, will be caught next run
    elif not dry_run and not groups_by_key and group_dirs and not root_fits:
        # Nothing to organize, idempotent
        logger.info("organize.idempotent_skip", target=str(target_dir), reason="already sorted")
    # Return result
    return {
        "target": str(target_dir),
        "target_name": target_dir.name,
        "lights_dir": str(lights_dir),
        "groups": group_infos,
        "root_fits": [str(p) for p in root_fits],
        "skipped_header": [str(p) for p in skipped_header],
        "unexpected_dirs": [(d.name, sum(1 for _ in d.rglob("*") if _.is_file())) for d in unexpected_dirs],
        "moved": moved,
        "duplicates_cleaned": duplicates_cleaned,
        "idempotent_skipped": idempotent_skipped,
        "dry_run": dry_run,
        "soll_set": soll_set,
        "eqmodes_present": eqmodes_present if 'eqmodes_present' in locals() else set(),
    }


def organize_all_targets(data_root: Path, dry_run: bool = False) -> list[dict]:
    """Organize all targets under data_root (ignoring IGNORED dirs)."""
    data_root = Path(data_root).resolve()
    results: list[dict] = []
    for entry in sorted(data_root.iterdir()):
        if not entry.is_dir():
            continue
        low = entry.name.lower()
        if low in IGNORED_ALL_DIRS:
            continue
        # Also ignore if name starts with _ or . ?
        if entry.name.startswith("_") or entry.name.startswith("."):
            # But _darks already ignored; also _work etc. For safety ignore any _xxx unless it's a real target with _? Real targets like M31 don't start with _. So skip.
            # However some targets like C33_NGC... start with C, not _
            if low not in ("_darks",):  # already handled
                # Check if lights exists: if not, it's not a target, skip
                if not (entry / "lights").is_dir():
                    continue
                # If lights exists but name starts with _, it's probably ignored system folder
                if entry.name.startswith("_"):
                    continue
        # Only consider dirs with lights\
        if not (entry / "lights").is_dir():
            continue
        try:
            res = organize_target(entry, dry_run=dry_run)
            results.append(res)
        except FileNotFoundError as e:
            # no_lights → log and continue with warning result (C6: relativ, nur Name, kein C:\ Leak)
            logger.warning("organize.no_lights", target=entry.name, error=str(e))
            results.append({"target": str(entry), "target_name": entry.name, "error": str(e), "groups": []})
        except Exception as e:
            logger.warning("organize.failed", target=str(entry), error=str(e))
            results.append({"target": str(entry), "target_name": entry.name, "error": str(e), "groups": []})
    return results


def format_organize_table(result: dict, show_soll: bool = True) -> str:
    """Format dry-run table for single target result (plain text)."""
    lines: list[str] = []
    target = result.get("target_name", result.get("target", "?"))
    lights_dir = result.get("lights_dir", "")
    groups = result.get("groups", [])
    # Header
    lines.append(f"Target: {target} ({result.get('target','')})")
    # Count FITS: total from groups + skipped?
    total_fits = sum(g["count"] for g in groups) + len(result.get("skipped_header", []))
    lines.append(f"Source: {lights_dir} — {total_fits} FITS (FITS-Header SSOT)")
    # Table header
    header = f"{'Group':<30} {'Frames':>6} {'Total-Exp':>12} {'EQMODE':>8} {'Status':<40}"
    if show_soll and any(g.get("soll_status") != "n/a" for g in groups):
        header += f" {'SOLL':<12}"
    lines.append(header)
    lines.append("-" * len(header))
    for g in sorted(groups, key=lambda x: x["folder"]):
        total_str = f"{int(g['total_exp'])}s ({int(g['total_exp']//60)}m)" if g["total_exp"] >= 60 else f"{int(g['total_exp'])}s"
        # More precise: spec shows 4050s (67m) — we do that
        if g["total_exp"] >= 60:
            total_str = f"{int(g['total_exp'])}s ({int(g['total_exp']//60)}m)"
        else:
            total_str = f"{int(g['total_exp'])}s"
        status = g["status"]
        eq = g["eq_display"]
        line = f"{g['folder']:<30} {g['count']:>6} {total_str:>12} {eq:>8} {status:<40}"
        if show_soll and any(x.get("soll_status") != "n/a" for x in groups):
            line += f" {g.get('soll_status','n/a'):<12}"
        lines.append(line)
        # Add note for SKIPPED <3
        # V1.12-ORGANIZE cp1252-Crash Fix (stella 08.09.2026): >= → ASCII "at least 3" (Windows cp1252 stdout)
        if g["status"] == "SKIPPED":
            lines.append(f"  Note: {g['folder']} has <3 frames — stacking requires at least 3. Review FITS headers (FILTER/EQMODE) for grouping.")
    if not groups:
        lines.append("  (no groups — check FITS headers)")
    # Notes
    lines.append(f"Command: astra organize \"{result.get('target','')}\"  -> MOVE Frames in group_* INSIDE lights\\")
    # Warnung SOLL mismatch already in group soll_status, but also extra warning line
    for g in groups:
        if g.get("soll_status") == "WARN not in SOLL":
            lines.append(f"[WARN] {g['folder']} not in SHOT LIST — unexpected series detected")
    # AZ/EQ mix warning
    eqs = result.get("eqmodes_present", set())
    if len(eqs) > 1 and (0 in eqs and 1 in eqs):
        lines.append("[WARN] AZ/EQ mix between groups — separate runs recommended — use GROUP-SELECT")
    # Unexpected subfolders
    for name, cnt in result.get("unexpected_dirs", []):
        lines.append(f"[WARN] organize.unexpected_subfolder: {name}, {cnt} files — not processed (skipped_subfolder)")
    # Skipped header
    if result.get("skipped_header"):
        for f in result["skipped_header"][:5]:
            lines.append(f"[WARN] organize.header_incomplete: {Path(f).name} — stays in lights\\Root")
    if result.get("duplicates_cleaned"):
        lines.append(f"Info: {result['duplicates_cleaned']} duplicates cleaned from root")
    if not result.get("dry_run") and result.get("moved") == 0 and not result.get("groups"):
        lines.append("Info: nothing to organize")
    # Also if dry_run and moved would be >0
    return "\n".join(lines)

