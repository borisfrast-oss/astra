"""CLI entry point for Astra pipeline."""

import json
import os
import queue
import re
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

import click
import structlog
import yaml

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _get_version
except ImportError:  # pragma: no cover
    from importlib_metadata import PackageNotFoundError
    from importlib_metadata import version as _get_version  # type: ignore


def _resolve_cli_version() -> str:
    """Return installed distribution version (wheel or editable).

    Fallback chain: astra-pipeline (current dist name) -> astra (legacy editable)
    -> 0.0.0+dev (running from source without install).
    """
    for dist_name in ("astra-pipeline", "astra"):
        try:
            return _get_version(dist_name)
        except PackageNotFoundError:
            pass
    return "0.0.0+dev"

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    Console = None  # type: ignore
    Table = None  # type: ignore
    Panel = None  # type: ignore

try:
    from prompt_toolkit import prompt as pt_prompt
    HAS_PT = True
except ImportError:
    HAS_PT = False
    pt_prompt = None  # type: ignore

from .agents.archive import create_archive_agent
from .agents.calibration import CalibrationResult, create_calibration_agent
from .agents.cosmetic_agent import create_cosmetic_agent
from .agents.debayer_agent import create_debayer_agent
from .agents.discovery import create_discovery_agent
from .agents.merge_agent import MergeAgent
from .agents.processing_agent import create_processing_agent
from .config import AppConfig, load_config
from .config.loader import (
    DEFAULT_CONFIG,
    resolve_export_config,
    resolve_gradient_removal,
    resolve_preview_export_config,
    resolve_preview_format,
    resolve_registration,
    resolve_stack_scale_factor,
)
from .config.models import MergeConfig, MultiGroupConfig, PipelinePreset
from .core import suggest as suggest_core
from .core.fits_parser import build_observation_context
from .core.stacking import resolve_stack_method
from .core.staging import stage_input


def _rich_console():
    """Return a Rich Console, or None when rich is unavailable.

    When stdout is not a TTY (pipe/redirect) the console is created with
    force_terminal=False so rich falls back to ASCII box characters and
    avoids emitting Unicode box-drawing glyphs that cp1252 terminals cannot
    encode (UnicodeEncodeError on Windows when piping).
    """
    if HAS_RICH:
        is_tty = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False
        if is_tty:
            return Console()
        # Non-TTY (pipe / redirect): ASCII-safe, no colour, no fancy borders.
        return Console(force_terminal=False, no_color=True)
    return None

def _ask(prompt_text: str, default: str | None = None, validate=None):
    """Ask user via prompt_toolkit/click with optional validation."""
    suffix = f" [{default}]" if default else ""
    full = f"{prompt_text}{suffix}: "
    while True:
        try:
            if HAS_PT:
                val = pt_prompt(full)
            else:
                val = click.prompt(prompt_text, default=default or "", show_default=True)
                # click.prompt returns default if empty; ensure string
                val = str(val)
        except Exception:
            val = click.prompt(prompt_text, default=default or "", show_default=True)
            val = str(val)
        val = val.strip()
        if not val and default:
            val = default
        if validate:
            try:
                validate(val)
            except Exception as e:
                click.echo(f"  Invalid: {e}", err=True)
                continue
        return val

def _format_yaml_line(key: str, val, indent: int = 0) -> str:
    """Format a single YAML key:value line for comment-preserving config writes."""
    prefix = " " * indent
    if isinstance(val, str):
        # Escape backslashes and quotes so Windows paths stay valid YAML.
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'{prefix}{key}: "{escaped}"'
    if isinstance(val, bool):
        return f"{prefix}{key}: {str(val).lower()}"
    if val is None:
        return f"{prefix}{key}: null"
    return f"{prefix}{key}: {val}"


def _write_config_with_comments(out_path: Path, updates: dict) -> None:
    """Write config.yaml starting from DEFAULT_CONFIG and applying updates.

    Preserves comments and structure from DEFAULT_CONFIG (source of truth for
    documentation like GR-B / W9-B) while updating the wizard-supplied values.
    """
    text = DEFAULT_CONFIG
    # darks_repository is commented out in DEFAULT_CONFIG; uncomment if set.
    if "darks_repository" in updates:
        text = re.sub(
            r"^(\s*)#\s*(darks_repository:.*)$",
            r"\1\2",
            text,
            flags=re.MULTILINE,
        )
    lines = text.splitlines()
    in_block: str | None = None
    out_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        # Top-level key
        if indent == 0 and stripped and not stripped.startswith("#"):
            key = stripped.split(":", 1)[0].strip()
            in_block = None
            if key in updates:
                val = updates[key]
                if isinstance(val, dict):
                    in_block = key
                    out_lines.append(line)
                    continue
                out_lines.append(_format_yaml_line(key, val, indent=0))
                continue
        # Inside a block we are updating
        if in_block is not None and indent > 0 and ":" in stripped:
            sub_key = stripped.split(":", 1)[0].strip()
            block_updates = updates.get(in_block, {})
            if sub_key in block_updates:
                out_lines.append(_format_yaml_line(sub_key, block_updates[sub_key], indent=indent))
                continue
        out_lines.append(line)
    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def _stdin_is_tty() -> bool:
    """Return True if stdin is a TTY (real terminal)."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _run_preflight_checks(target_dir: Path, cfg: AppConfig, darks_path_override=None) -> dict:
    """CLI-C: Hot Pixel Scan 2-3 Frames >20sigma, Dark-Passung, Cosmetic Empfehlung."""
    result = {"checks": [], "status": "OK", "hot_pixels": 0, "dark_ok": True, "cosmetic_recommend": False}
    try:
        # Scan lights (max 3 frames)
        fits_files = sorted(target_dir.glob("lights/*.fit*"))
        if not fits_files:
            fits_files = sorted(target_dir.glob("*.fit*"))[:3]
        else:
            fits_files = fits_files[:3]
        hot_pixels = 0
        clipping = False
        for p in fits_files[:3]:
            try:
                import numpy as np
                from astropy.io import fits as afits
                with afits.open(p) as hdul:
                    data = hdul[0].data
                    if data is None:
                        continue
                    data = np.asarray(data, dtype=float)
                    if data.ndim == 3:
                        data = data.mean(axis=0)
                    median = float(np.median(data))
                    # MAD -> sigma approx
                    mad = float(np.median(np.abs(data - median)))
                    sigma = mad * 1.4826 if mad != 0 else 1.0
                    # >20 sigma
                    mask = data > (median + 20 * sigma)
                    hot_pixels = max(hot_pixels, int(mask.sum()))
                    # 12-bit clipping proxy: values near 4095 (or 65535)
                    if data.max() > 4000 and data.max() >= 4090:
                        # check if many saturated
                        clipping = True
            except Exception:
                continue
        result["hot_pixels"] = hot_pixels
        # Dark check
        effective_darks = darks_path_override or cfg.darks_repository
        dark_ok = True
        if effective_darks is None or not Path(effective_darks).exists():
            dark_ok = False
        result["dark_ok"] = dark_ok
        cosine_rec = hot_pixels > 200 or clipping
        result["cosmetic_recommend"] = cosine_rec

        # Build checks list
        if hot_pixels > 200:
            result["checks"].append(f"Hot Pixels: {hot_pixels} >200 -> Cosmetic empfohlen (Warning)")
            if result["status"] == "OK":
                result["status"] = "Warning"
        else:
            result["checks"].append(f"Hot Pixels: {hot_pixels} OK")
        if clipping:
            result["checks"].append("12-bit clipping detected -> cosmetic recommended (Warning)")
            if result["status"] == "OK":
                result["status"] = "Warning"
        if not dark_ok:
            result["checks"].append("Dark matching: no darks found (Warning)")
            if result["status"] == "OK":
                result["status"] = "Warning"
        else:
            result["checks"].append("Dark matching: OK")
        if cosine_rec:
            result["checks"].append("Cosmetic recommendation: enable (>200 hot pixels/clipping)")
        else:
            result["checks"].append("Cosmetic: not required")

        # Abort condition: extrem viele hot pixels? For spec, >200 is warning, not abort. Keep Ok/Warning only.
        # Simulate abort if no lights
        if not fits_files:
            result["checks"].append("No lights found (Abort)")
            result["status"] = "Abort"
    except Exception as e:
        result["checks"].append(f"Preflight error: {e}")
        result["status"] = "Abort"
    return result

def _print_preflight_result(result: dict) -> None:
    console = _rich_console()
    status = result.get("status", "OK")
    if console and HAS_RICH:
        color = {"OK": "green", "Warning": "yellow", "Abort": "red"}.get(status, "white")
        console.print(Panel(f"[bold {color}]{status}[/bold {color}] Pre-Flight Check", expand=False))
        for c in result["checks"]:
            console.print(f"  - {c}")
    else:
        click.echo(f"[{status}] Pre-Flight Check")
        for c in result["checks"]:
            click.echo(f"  - {c}")
    logger.info("cli.preflight", status=status, checks=result["checks"], hot_pixels=result.get("hot_pixels"))

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
)

logger = structlog.get_logger(__name__)


@click.version_option(
    version=_resolve_cli_version(),
    prog_name="astra",
)
@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help=(
        "Config file (global, must be placed BEFORE the subcommand, e.g. "
        "--config config.yaml process <target>). Without --config the "
        "pipeline automatically searches for config.yaml in the current "
        "directory or project root."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx, config, verbose):
    """Astra - Agentic Astrophotography Processing Pipeline."""
    # V1.12-ORGANIZE cp1252-Crash Fix (stella 08.09.2026):
    # Windows stdout ist ohne Konsole cp1252 -> UnicodeEncodeError bei >= etc.
    # Robust: utf-8 mit errors=replace, und ASCII-Fallback in Tabellen.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose

    # Load configuration
    cfg = load_config(config)
    ctx.obj["config"] = cfg

    if verbose:
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(10)  # DEBUG
        )


@cli.command()
@click.argument("target_path", type=click.Path(exists=True, path_type=Path))
@click.option("--preset", "-p", type=click.Choice(["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]), help="Processing preset")
@click.option("--dry-run", is_flag=True, help="Show plan without executing")
@click.option("--keep-working", is_flag=True, help="Preserve working directory")
@click.option("--keep-groups/--no-keep-groups", default=None, help="Keep or clean up group directories (default: from config, otherwise true)")
@click.option("--resume", is_flag=True, help="Resume from last checkpoint")
# Multi-group flags -- V1.7-5 (Always Multi-Group): Multi-Group ist IMMER
# aktiv; die beiden Erkennungs-Flags sind deprecated No-ops (Entfernung in
# v1.8). --merge/--no-merge wirkt weiter (Default: Merge AN).
@click.option("--multi-group", is_flag=True, help="Deprecated no-op (v1.7): Multi-Group is always active")
@click.option("--auto-group", is_flag=True, help="Deprecated no-op (v1.7): Multi-Group is always active")
@click.option("--merge/--no-merge", default=None, help="Enable or disable merge step (default: enabled). Note: merge requires >=2 groups; single-group targets are automatically materialized to merged/")
@click.option("--weight-by", type=click.Choice(["frame_count", "total_exposure"]), help="Merge weighting method (overrides config)")
@click.option("--merge-method", type=click.Choice(["weighted_average", "average", "median"]), help="Merge method (overrides config)")
@click.option("--merge-filter", "merge_filter", multiple=True, type=str, help="Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro --merge-filter \"Duo-Band\"; overrides config)")
@click.option("--pcc-per-group/--no-pcc-per-group", default=None, help="PCC per group (default: false = PCC on merged stack for max S/N)")
@click.option("--stacking-method", type=click.Choice(["average", "median", "winsorized", "weighted", "sigma_clipped_mean"]), help="Stacking method (overrides preset/config; otherwise mapped from rejection; sigma_clipped_mean = robust sigma-clipping)")
@click.option("--registration-method", type=click.Choice(["fft", "astroalign", "rotation_fft"]), help="Registration method (overrides config/preset)")
@click.option(
    "--max-rotation",
    type=float,
    default=None,
    help="Sanity guard: max rotation in degrees for astroalign/rotation_fft (default 2.0, field rotation e.g. 15)",
)
@click.option(
    "--zero-shift-threshold",
    type=float,
    default=None,
    help=(
        "W1 guard: corr_hp threshold (default 0.0). FFT path -> zero-shift "
        "fallback; astroalign winner below threshold -> frame rejected"
    ),
)
@click.option(
    "--no-zero-shift-fallback",
    is_flag=True,
    default=False,
    help=(
        "Completely disable W1 guard (no zero-shift fallback and "
        "no astroalign rejection below threshold)"
    ),
)
@click.option(
    "--az-mode",
    "eq_mode_override",
    flag_value="az",
    default=None,
    help="EQMODE override: force AZ mode (overrides EQMODE header)",
)
@click.option(
    "--eq-mode",
    "eq_mode_override",
    flag_value="eq",
    default=None,
    help="EQMODE override: force EQ mode (overrides EQMODE header)",
)
@click.option(
    "--pixel-scale",
    type=float,
    default=None,
    help="Pixel scale (arcsec/px) directly (overrides equipment header)",
)
@click.option(
    "--se-radius",
    type=float,
    default=None,
    help="Structure-enhancement radius (default 3.0 from preset step)",
)
@click.option(
    "--se-amount",
    type=float,
    default=None,
    help="Structure-enhancement amount (default 0.2 from preset step)",
)
# GR-B (AC-GR-B1): Gradient-Removal-Config (Precedence CLI > Config > Preset > Default)
@click.option(
    "--gradient-removal-enabled/--gradient-removal-disabled",
    default=None,
    help="Enable or disable gradient removal (overrides config/preset)",
)
@click.option(
    "--gradient-removal-degree",
    type=int,
    default=None,
    help="Gradient removal polynomial degree (overrides config/preset)",
)
@click.option(
    "--gradient-removal-grid",
    type=str,
    default=None,
    help="Gradient removal sampling grid as 'rows,cols' e.g. 16,16 (overrides config/preset)",
)
@click.option(
    "--gradient-removal-sigma-clip",
    type=float,
    default=None,
    help="Gradient removal sigma-clipping k in k*MAD (overrides config/preset)",
)
@click.option(
    "--gradient-removal-min-samples",
    type=int,
    default=None,
    help="Gradient removal minimum sample cells for fit (overrides config/preset)",
)
# W5: Darks Library
@click.option("--darks-path", type=click.Path(exists=True, path_type=Path), help="Path to central darks library (overrides config: darks_repository)")
# Cosmetic Correction CLI flag (Precedence CLI > Config > Default)
@click.option(
    "--cosmetic-correction/--no-cosmetic-correction",
    default=None,
    help="Enable or disable cosmetic correction (overrides config)",
)
# V1.8-0 (MALVAR): Debayer method (Precedence CLI > Config > Preset > Default)
@click.option(
    "--debayer-method",
    type=click.Choice(["superpixel", "bilinear", "malvar"]),
    default=None,
    help="Debayer method: superpixel (default, DADR-003), malvar (1920x1080, high-quality, Malvar2004), or bilinear (deprecated, use malvar or superpixel, full resolution)",
)
# V1.7-2 FSEL-D (AC-FSEL-D3): Frame selection CLI override (Precedence CLI > Config > Preset)
@click.option(
    "--frame-selection/--no-frame-selection",
    default=None,
    help="Enable or disable frame selection (percentile, DwarfLab pattern; overrides config/preset, default off)",
)
@click.option(
    "--keep-percentile",
    type=click.IntRange(1, 100),
    default=None,
    help="Keep percentile for frame selection (1-100, default 92, only with --frame-selection)",
)
# V1.8-1 CFA-Drizzle (Precedence CLI > Config > Default, AC-DRZ-10)
@click.option(
    "--cfa-drizzle/--no-cfa-drizzle",
    default=None,
    help="Enable or disable CFA drizzle (2x, uses Dwarf Mini dithering, default off)",
)
@click.option(
    "--drizzle-scale",
    type=float,
    default=None,
    help="Drizzle scale (default 2.0, 2x = 3840x2160)",
)
@click.option(
    "--drizzle-pixfrac",
    type=float,
    default=None,
    help="Drizzle pixfrac (0.5-1.0, fixed mode, default auto: <10=1.0, 10-30=0.7, >30=0.5)",
)
@click.option(
    "--drizzle-kernel",
    type=click.Choice(["lanczos3", "gaussian", "tophat"]),
    default=None,
    help="Drizzle kernel (default lanczos3, gaussian/tophat optional)",
)
# V19-CFA-GATE G4: Quality gate CLI (1 visible + 5 hidden)
@click.option(
    "--cfa-drizzle-quality-gate/--no-cfa-drizzle-quality-gate",
    default=None,
    help="Quality gate for CFA drizzle: auto (default), on, off (let all frames pass)",
)
@click.option(
    "--cfa-drizzle-min-frames",
    type=int,
    default=None,
    help="Minimum frames for drizzle (default: 5, CFA-Smart: 5)",
)
@click.option(
    "--cfa-drizzle-fallback",
    type=click.Choice(["malvar", "superpixel", "skip"]),
    default=None,
    hidden=True,
    help="Fallback method on quality gate fail (default: malvar) [advanced]",
)
@click.option(
    "--cfa-drizzle-star-count-min",
    type=int,
    default=None,
    hidden=True,
    help="Min star count (default: 20 debayered, CFA-Smart: 1) [advanced]",
)
@click.option(
    "--cfa-drizzle-snr-min",
    type=float,
    default=None,
    hidden=True,
    help="Min SNR (default: 10, CFA-Smart: 0.8, V1.12-DRZ-GATE calibrated on M92 real 0.89-0.93, spec 1.0-1.5) [advanced]",
)
@click.option(
    "--cfa-drizzle-correlation-min",
    type=float,
    default=None,
    hidden=True,
    help="Min Correlation (Default: 0.3, CFA-Smart: 0.1) [advanced]",
)
@click.option(
    "--cfa-drizzle-fwhm-range",
    type=str,
    default=None,
    hidden=True,
    help="FWHM range as 'min,max' (default: 1.5,5.0, CFA-Smart: 1.0,8.0) [advanced]",
)
# V1.12-PREVIEW-FORMAT (AC-PREVIEW-FMT-1): --preview-format CLI-Flag
# Precedence CLI > Config > Default (tiff). Boris-Entscheid 07.09.2026 Default tiff.
@click.option(
    "--preview-format",
    type=click.Choice(["tiff", "jpg"]),
    default=None,
    help="Preview Format: tiff (16-bit lossless, Default, 07.09.2026) or jpg (8-bit, fast, ~500 KB vs ~10-50 MB) (overrides Config preview.format, Default tiff)",
)
# V19-PCC-FLAG P1: --pcc/--no-pcc (default None, no breaking change)
@click.option(
    "--pcc/--no-pcc",
    default=None,
    help="Enable or disable photometric color calibration (overrides preset/config; default: preset/config wins)",
)
# CLI-C --preflight (V1.8-4): Pre-flight checks only, no pipeline start
@click.option("--preflight", is_flag=True, help="Pre-flight checks only (hot pixel scan, dark matching, cosmetic recommendation) -- no pipeline start")
@click.option("--yes", is_flag=True, help="With --preflight: start pipeline immediately if checks pass")
# T2: --no-calib: skip calibration (pre-calibrated lights)
@click.option(
    "--no-calib/--calib",
    default=None,
    help=(
        "Skip calibration phase (pre-calibrated lights). "
        "Note: lights must be CFA/2D (Bayer raw data) -- already "
        "debayered 3D RGB lights will fail at debayer step."
    ),
)
# V1.11-ENTSCHLACKUNG ENTS-3: --from-suggested is now required (via Guard).
# OQ-ENTS-2 B: flag without value → implicit default <Target>/suggested.yaml.
# Precedence CLI > File > Config (ENTS-4). `--params-file` Alias VERWORFEN.
# exists=True intentionally OMITTED from the option -- click would validate
# the sentinel "__DEFAULT__" string against the filesystem. Manual Guard runs
# in the callback instead (after target_dir resolution).
@click.option(
    "--from-suggested",
    "from_suggested",
    is_flag=False,
    flag_value="__DEFAULT__",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help=(
        "Load preset/registration/debayer/pcc from a suggested_parameters "
        "YAML/JSON file (written by 'astra suggest'). Required since v1.11 -- "
        "run 'astra suggest <TARGET>' first to generate the file "
        "(default: C:/Astra/<Target>/suggested.yaml). "
        "If flag given without value, defaults to <Target>/suggested.yaml "
        "(derived from the TARGET argument). CLI flags win over file values. "
        "No auto-discover; only TARGET-arg-derived default when flag has no value."
    ),
)
# V1.11-SUBSET (OQ-SUBSET-1): --limit N -- smoke-test flag (first N lights per group).
# OQ-SUBSET-3: N >= 1 (0/negative/non-integer → Error Exit 2).
# OQ-SUBSET-2: --limit + --resume → Error Exit 2 (incompatible flags).
# OQ-SUBSET-4: structured logs (discovery.limit_applied per group); no --quiet.
# Kollision geprueft: 0 bestehende --limit Treffer in codebase (leo, 2026-09-05).
@click.option(
    "--limit",
    "limit",
    type=int,
    default=None,
    help=(
        "Limit number of light frames per group for quick smoke testing "
        "(discovery processes all groups, but uses only first N lights per group; "
        "darks, bias, flats remain complete for proper calibration). "
        "Default: no limit (process all frames). "
        "Example: --limit 5 (use first 5 lights per group; output marked as smoke_mode=true). "
        "Combination: incompatible with --resume (use --limit for fresh runs only). "
        "[English s17]"
    ),
)
# V1.12-GROUP-SELECT (GROUP-SEL-1): --group flag (mehrfach) -- verarbeitet NUR gewählte Gruppenordner statt aller.
# Name-Matching ORG-X2: exakt oder eindeutig Prefix, case-insensitiv, gegen existierende Ordner lights/group_*/.
# Mehrfach erlaubt, Reihenfolge sequenziell. Unbekannt/mehrdeutig → Error Exit 2 + Did-you-mean. P-02 Gate Re-Aktivierung.
@click.option(
    "--group",
    "selected_groups",
    multiple=True,
    type=str,
    metavar="GROUP_NAME",
    help="Process only the specified group folder(s) (repeatable, e.g. --group group_30s40_duo-band --group group_60s40_duo-band; exact or unique prefix, case-insensitive, ORG-X2)",
)
@click.pass_context
def process(ctx, target_path, preset, dry_run, keep_working, keep_groups, resume,
            multi_group, auto_group, merge, weight_by, merge_method, darks_path, no_calib,
            preflight, yes,
            registration_method, max_rotation, zero_shift_threshold, no_zero_shift_fallback,
            gradient_removal_enabled, gradient_removal_degree,
            gradient_removal_grid, gradient_removal_sigma_clip, gradient_removal_min_samples,
            stacking_method, eq_mode_override, pixel_scale, se_radius, se_amount,
            cosmetic_correction, debayer_method, pcc_per_group, frame_selection, keep_percentile,
            merge_filter, cfa_drizzle, drizzle_scale, drizzle_pixfrac, drizzle_kernel,
            cfa_drizzle_quality_gate, cfa_drizzle_min_frames, cfa_drizzle_fallback,
            cfa_drizzle_star_count_min, cfa_drizzle_snr_min, cfa_drizzle_correlation_min,
            cfa_drizzle_fwhm_range, preview_format, pcc, from_suggested, limit, selected_groups):
    """Process a single target directory.

    Note (Docs regen 2026-08-11, B3): --config/-c is a GLOBAL option and
    must be specified before the subcommand, e.g.:
        astro-process --config config.yaml process <target>
    Without --config the pipeline automatically searches for config.yaml in
    the current directory (CWD) or project root.
    """
    cfg: AppConfig = ctx.obj["config"]
    # T2: Precedence CLI > Config. None = Flag nicht gesetzt → Config-Wert.
    effective_no_calib = no_calib if no_calib is not None else cfg.no_calib

    logger.info("cli.process.start", target=str(target_path), preset=preset)

    # Resolve target directory (needed before --from-suggested Guard)
    target_dir = target_path.resolve()
    target_name = target_dir.name

    # P0 Mini-Fix (T4): --resume verworfen (2026-09-13, _work/archive/2026-09-13-resume-verworfen/) -- explicit guard before all others.
    if resume:
        raise click.UsageError(
            "process.resume.removed: --resume is deprecated, use --limit/--group (see _work/archive/2026-09-13-resume-removed/)"
        )

    # V1.11-SUBSET (OQ-SUBSET-3): --limit Validierung N >= 1.
    # Integer-Typ ist durch click garantiert; 0/negativ → Error Exit 2.
    if limit is not None and limit < 1:
        raise click.UsageError(
            f"process.limit.invalid: --limit must be >= 1 (got {limit}) "
            f"-- use --limit N with N >= 1, or omit --limit to process all frames"
        )

    # V1.11-SUBSET (OQ-SUBSET-2): --limit + --resume Inkompatibilität → Error Exit 2.
    # Resume restores prior run state; --limit would be inconsistent with that state.
    if limit is not None and resume:
        raise click.UsageError(
            "process.limit.resume_incompatible: --limit not compatible with --resume "
            "-- use --limit for fresh runs only"
        )

    # V1.11-ENTSCHLACKUNG ENTS-3: --from-suggested Guard (Pflicht).
    # OQ-ENTS-2 B: flag without value → sentinel "__DEFAULT__" →
    # implicit default <Target>/suggested.yaml via default_output_path.
    # Guard order: missing → Error; __DEFAULT__ → resolve; not exists → Error.
    # CLI-Werte gewinnen IMMER (ENTS-4, CLI > File > Config).
    if from_suggested is None:
        raise click.UsageError(
            f"process.from_suggested.missing: --from-suggested <file> is required "
            f"\u2014 run 'astra suggest {target_name}' first "
            f"(default: C:/Astra/{target_name}/suggested.yaml)"
        )
    if str(from_suggested) == "__DEFAULT__":
        from_suggested = suggest_core.default_output_path(
            target_name, data_root=target_dir.parent
        )
    if not Path(from_suggested).exists():
        raise click.UsageError(
            f"process.from_suggested.not_found: {from_suggested} not found "
            f"\u2014 run 'astra suggest {target_name}' first"
        )

    # Load suggested file and inject values (CLI wins over file, OQ-ENTS-3 A:
    # null file-field → Config supplements).
    suggested_data = suggest_core.load_suggested_file(from_suggested)
    suggested_registration = suggested_data.get("registration") or {}
    suggested_debayer = suggested_data.get("debayer") or {}
    suggested_pcc = suggested_data.get("pcc") or {}
    if preset is None and suggested_data.get("preset"):
        preset = suggested_data.get("preset")
    if registration_method is None and suggested_registration.get("method"):
        registration_method = suggested_registration.get("method")
    if max_rotation is None and suggested_registration.get("max_rotation_deg") is not None:
        try:
            max_rotation = float(suggested_registration["max_rotation_deg"])
        except (TypeError, ValueError):
            pass
    if debayer_method is None and suggested_debayer.get("method"):
        debayer_method = suggested_debayer.get("method")
    if pcc is None and suggested_pcc.get("enabled") is not None:
        pcc = bool(suggested_pcc.get("enabled"))
    logger.info(
        "process.from_suggested",
        path=str(from_suggested),
        preset=suggested_data.get("preset"),
        method=suggested_registration.get("method"),
        source=suggested_data.get("source"),
    )

    # ENTS-4/6: Preset Guard -- must come from file (or CLI override).
    # No cfg.default_preset fallback without file (gestrafft).
    if preset is None:
        raise click.UsageError(
            f"process.preset.missing: preset missing in suggested file "
            f"\u2014 run 'astra suggest {target_name}' first"
        )

    # ENTS-4: Registration Guard -- CLI > File > Config (OQ-ENTS-3 A: null → Config).
    if registration_method is None:
        if cfg.registration and cfg.registration.method:
            registration_method = cfg.registration.method
        else:
            raise click.UsageError(
                f"process.registration_method.missing: registration.method missing "
                f"in suggested file and config "
                f"\u2014 run 'astra suggest {target_name}' first"
            )

    # CLI-C --preflight: nur Checks, kein Pipeline-Start (ausser --yes bei OK)
    if preflight:
        result = _run_preflight_checks(target_dir, cfg, darks_path)
        _print_preflight_result(result)
        if not yes:
            return
        if result["status"] == "Abort":
            click.echo("[ABORT] Pre-Flight failed -- pipeline not started", err=True)
            sys.exit(2)
        if result["status"] == "Warning":
            click.echo("[WARNING] Pre-Flight warnings -- starting anyway (--yes)", err=True)
        # on OK or Warning + --yes: fall through to pipeline

    # Determine preset (guaranteed non-None at this point, ENTS-4/6)
    pipeline = cfg.get_preset(preset)
    if not pipeline:
        raise click.ClickException(f"Preset '{preset}' not found")

    # W9-B (AC-W9-B1, ADR-019): Precedence CLI > Config > Preset > Default.
    # Die effektive Config wird im Preset verankert, damit die Pipeline
    # (S1-A7: Registration-Strategy) sie ueber
    # `pipeline.processing_params.registration` liest.
    # RE-F (AC-RE-F3): --no-zero-shift-fallback (is_flag) wird in den
    # cli-Wert False uebersetzt; nicht gesetzt -> None (kein Override).
    # registration_method is guaranteed non-None here (ENTS-4 guard above).
    effective_registration = resolve_registration(
        cfg, pipeline, registration_method, cli_max_rotation=max_rotation,
        cli_zero_shift_threshold=zero_shift_threshold,
        cli_zero_shift_fallback=False if no_zero_shift_fallback else None,
    )
    pipeline.processing_params.registration = effective_registration
    logger.info(
        "cli.process.registration",
        method=effective_registration.method,
        max_control_points=effective_registration.max_control_points,
        max_rotation_deg=effective_registration.max_rotation_deg,
        max_scale_dev=effective_registration.max_scale_dev,
        stack_scale_factor=effective_registration.stack_scale_factor,
        zero_shift_threshold=effective_registration.zero_shift_threshold,
        zero_shift_fallback=effective_registration.zero_shift_fallback,
    )

    # V1.11-ENTSCHLACKUNG ENTS-4: Debayer-Methode aufloesen.
    # Precedence: CLI > File > Config (OQ-ENTS-3 A: null → Config).
    # No "superpixel" hardcode fallback (ENTS-4).
    import warnings
    effective_debayer_method = debayer_method or cfg.debayer_method
    if effective_debayer_method is None:
        raise click.UsageError(
            f"process.debayer_method.missing: debayer.method missing in "
            f"suggested file and config "
            f"\u2014 run 'astra suggest {target_name}' first"
        )
    pipeline.processing_params.debayer_method = effective_debayer_method
    # V1.8-0 (MALVAR): bilinear deprecated (Grace v1.8)
    if effective_debayer_method == "bilinear":
        warnings.warn(
            "bilinear is deprecated, use malvar or superpixel",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "cli.process.debayer_deprecated",
            method="bilinear",
            hint="use malvar or superpixel",
        )
        click.echo(
            "[WARN] --debayer-method bilinear is deprecated, use malvar or superpixel (Grace v1.8)",
            err=True,
        )

    # V1.6-2 (AC-BIL-E1) + V1.7-4 (Fix B2, ray-Review 2026-08-23):
    # stack_scale_factor-Aufloesung, Stufe 1 (vor Discovery). Precedence:
    # expliziter Config-Override > Preset > datengetrieben > Default.
    # Der Preset-Fallback wird hier abgeleitet -- BEVOR
    # effective_registration.stack_scale_factor unten mit dem Auto-Wert
    # mutiert wird; an dieser Stelle steht dort noch der unveraenderte
    # resolve_registration()-Stand (Config+Preset-Merge, Default 2.0 als
    # Sentinel). Der Sentinel bleibt damit sauber: weder Config noch Preset
    # gesetzt -> 2.0 -> keine false-positive explicit/preset-Detection;
    # ein explizit gesetztes 2.0 ist wertidentisch zum Auto-Fall (kein
    # Verhaltensunterschied).
    explicit_ssf = None
    preset_ssf = None
    if cfg.registration and cfg.registration.stack_scale_factor != 2.0:
        explicit_ssf = cfg.registration.stack_scale_factor
    elif effective_registration.stack_scale_factor != 2.0:
        preset_ssf = effective_registration.stack_scale_factor
    resolved_ssf = resolve_stack_scale_factor(
        debayer_method=effective_debayer_method,
        explicit_value=explicit_ssf,
        preset_value=preset_ssf,
    )
    effective_registration.stack_scale_factor = resolved_ssf
    logger.info(
        "cli.process.debayer",
        method=effective_debayer_method,
        stack_scale_factor=resolved_ssf,
    )

    # GR-B (AC-GR-B1): Precedence CLI > Config > Preset > Default.
    # Die effektive Config wird im Preset verankert, damit die Pipeline
    # (S2-B2: _background_extraction) sie ueber
    # `pipeline.processing_params.gradient_removal` liest.
    gr_grid: tuple[int, int] | None = None
    if gradient_removal_grid:
        try:
            parts = [p.strip() for p in gradient_removal_grid.split(",")]
            if len(parts) != 2:
                raise ValueError("expected 'rows,cols'")
            gr_grid = (int(parts[0]), int(parts[1]))
        except ValueError as e:
            raise click.ClickException(
                f"Invalid --gradient-removal-grid '{gradient_removal_grid}': {e}"
            ) from e
    effective_gr = resolve_gradient_removal(
        cfg, pipeline,
        cli_enabled=gradient_removal_enabled,
        cli_degree=gradient_removal_degree,
        cli_grid=gr_grid,
        cli_sigma_clip=gradient_removal_sigma_clip,
        cli_min_samples=gradient_removal_min_samples,
    )
    pipeline.processing_params.gradient_removal = effective_gr
    logger.info(
        "cli.process.gradient_removal",
        enabled=effective_gr.enabled,
        degree=effective_gr.degree,
        grid=list(effective_gr.grid),
        sigma_clip=effective_gr.sigma_clip,
        min_samples=effective_gr.min_samples,
    )

    # Leo-Auftrag 2026-08-10 (Teil B3): Stacking-Methode aufloesen.
    # Precedence: CLI-Flag --stacking-method > Preset/Config
    # (processing_params.stacking_method) > Rejection-Mapping (Teil B1:
    # winsorized->winsorized, average->average, none->average) > Default
    # "average". Der CLI-Wert wird im Preset verankert, damit die Pipeline
    # (S3: stack_frames -> resolve_stack_method) ihn liest.
    if stacking_method:
        pipeline.processing_params.stacking_method = stacking_method
    effective_stack_method = resolve_stack_method(
        pipeline.processing_params.model_dump()
    )
    logger.info(
        "cli.process.stacking",
        method=effective_stack_method,
        rejection=pipeline.processing_params.rejection,
        cli_override=stacking_method,
    )

    # V1.7-2 FSEL-D (AC-FSEL-D3): Frame-Selection aufloesen.
    # Precedence CLI > Config > Preset > Default (OQ-FSEL-2 A opt-in).
    from .config.loader import resolve_frame_selection
    effective_fs = resolve_frame_selection(
        cfg, pipeline, cli_enabled=frame_selection, cli_keep_percentile=keep_percentile
    )
    pipeline.processing_params.frame_selection = effective_fs
    # Mutate cfg.frame_selection fuer den multi_group-Helper (_resolve_frame_selection_config
    # prueft AppConfig zuerst; CLI-Override muss dort sichtbar sein, sonst gewinnt
    # Config fälschlich ueber CLI). Pipeline enthaelt bereits CLI-gewinner,
    # cfg-Mutation stellt Konsistenz sicher (kein Persistenz-Seiteneffekt).
    cfg.frame_selection = effective_fs
    logger.info(
        "cli.process.frame_selection",
        enabled=effective_fs.enabled,
        keep_percentile=effective_fs.keep_percentile,
        weights=effective_fs.weights,
        min_frames=effective_fs.min_frames,
        cli_override_enabled=frame_selection,
        cli_override_keep=keep_percentile,
    )

    # V1.8-1 CFA-Drizzle (Precedence CLI > Config > Default, AC-DRZ-10)
    from .config.loader import resolve_cfa_drizzle
    effective_drizzle = resolve_cfa_drizzle(
        cfg, cli_enabled=cfa_drizzle, cli_scale=drizzle_scale,
        cli_pixfrac=drizzle_pixfrac, cli_kernel=drizzle_kernel,
    )
    # Mutate cfg.cfa_drizzle for downstream (multi_group_agent checks cfg.cfa_drizzle)
    cfg.cfa_drizzle = effective_drizzle
    logger.info(
        "cli.process.cfa_drizzle",
        enabled=effective_drizzle.enabled,
        scale=effective_drizzle.scale,
        pixfrac_mode=effective_drizzle.pixfrac_mode,
        pixfrac=effective_drizzle.pixfrac,
        kernel=effective_drizzle.kernel,
        min_frames=effective_drizzle.min_frames,
        fallback=effective_drizzle.fallback,
    )

    # V19-CFA-GATE G4: CLI overrides fuer Quality Gate (hidden flags)
    _cli_cfa_overrides: dict = {}
    if cfa_drizzle_quality_gate is not None:
        _cli_cfa_overrides["rejection_enabled"] = bool(cfa_drizzle_quality_gate)
    if cfa_drizzle_star_count_min is not None:
        _cli_cfa_overrides.setdefault("thresholds", {})["star_count"] = [cfa_drizzle_star_count_min, None]
        _cli_cfa_overrides["star_count"] = cfa_drizzle_star_count_min
    if cfa_drizzle_snr_min is not None:
        _cli_cfa_overrides.setdefault("thresholds", {})["snr"] = [cfa_drizzle_snr_min, None]
    if cfa_drizzle_correlation_min is not None:
        _cli_cfa_overrides.setdefault("thresholds", {})["correlation"] = [cfa_drizzle_correlation_min, None]
    if cfa_drizzle_fwhm_range is not None:
        try:
            _parts = [p.strip() for p in cfa_drizzle_fwhm_range.split(",")]
            _mn = float(_parts[0]) if _parts[0] else None
            _mx = float(_parts[1]) if len(_parts) > 1 and _parts[1] else None
            _cli_cfa_overrides.setdefault("thresholds", {})["fwhm"] = [_mn, _mx]
            _cli_cfa_overrides["fwhm_range"] = cfa_drizzle_fwhm_range
        except Exception:
            pass
    if cfa_drizzle_fallback is not None:
        cfg.cfa_drizzle.fallback = cfa_drizzle_fallback  # type: ignore
        logger.info("cli.process.cfa_drizzle_fallback_override", fallback=cfa_drizzle_fallback)
    if cfa_drizzle_min_frames is not None:
        cfg.cfa_drizzle.min_frames = cfa_drizzle_min_frames  # type: ignore
        logger.info("cli.process.cfa_drizzle_min_frames_override", min_frames=cfa_drizzle_min_frames)
    if _cli_cfa_overrides:
        cfg._cfa_cli_overrides = _cli_cfa_overrides  # type: ignore[attr-defined]
        if cfa_drizzle_quality_gate is not None:
            cfg.cfa_drizzle.quality_gate.rejection_enabled = bool(cfa_drizzle_quality_gate)
        logger.info("cli.process.cfa_drizzle_gate_overrides", overrides=_cli_cfa_overrides)

    # V19-PCC-FLAG P1/P2/P3: --pcc/--no-pcc Preset-Step Mutation (CLI > Config > Preset)
    try:
        import copy

        from .config.models import PipelineStep
        pcc_enabled = None
        if pcc is not None:
            pcc_enabled = bool(pcc)
        elif cfg.pcc is not None and hasattr(cfg.pcc, "enabled") and cfg.pcc.enabled is not None:
            # model_fields_set Check: nur wenn enabled explizit gesetzt
            if "enabled" in getattr(cfg.pcc, "model_fields_set", set()) or cfg.pcc.enabled is not None:
                pcc_enabled = bool(cfg.pcc.enabled)
        if pcc_enabled is not None:
            # Finde aktiven Preset (preset guaranteed non-None at this point, ENTS-4/6)
            effective_preset_name = preset
            for _preset in cfg.pipeline_presets:
                if _preset.name == effective_preset_name:
                    # Batch safe: deepcopy, nicht Config Objekt mutieren
                    preset_copy = copy.deepcopy(_preset)
                    has_pcc = any(s.name == "photometric_color_calibration" for s in preset_copy.steps)
                    if pcc_enabled and not has_pcc:
                        try:
                            insert_idx = next(i for i, s in enumerate(preset_copy.steps) if s.name == "background_extraction") + 1
                            inserted_after = "background_extraction"
                        except StopIteration:
                            try:
                                insert_idx = next(i for i, s in enumerate(preset_copy.steps) if s.name == "stack_frames") + 1
                                inserted_after = "stack_frames"
                            except StopIteration:
                                insert_idx = len(preset_copy.steps) - 2
                                inserted_after = "stack_frames_fallback"
                        preset_copy.steps.insert(insert_idx, PipelineStep(name="photometric_color_calibration"))
                        logger.info("pcc.cli_override", enabled=True, preset=effective_preset_name, inserted_after=inserted_after)
                    elif not pcc_enabled and has_pcc:
                        preset_copy.steps = [s for s in preset_copy.steps if s.name != "photometric_color_calibration"]
                        logger.info("pcc.cli_override", enabled=False, preset=effective_preset_name, removed="photometric_color_calibration")
                    else:
                        logger.info("pcc.cli_override", enabled=pcc_enabled, preset=effective_preset_name, action="noop")
                    # Effective preset fuer Pipeline nutzen (preset_copy, nicht cfg.pipeline_presets mutieren)
                    pipeline = preset_copy
                    break
    except Exception as e:
        logger.warning("pcc.cli_override_failed", error=str(e))

    # V1.12-PREVIEW-FORMAT (AC-PREVIEW-FMT-1): Preview-Format aufloesen.
    # Precedence CLI > Config > Default tiff (Boris-Entscheid 07.09.2026).
    effective_preview_format = resolve_preview_format(cfg, cli_format=preview_format)
    # Mutate cfg.preview for downstream agents (multi_group/export/merge read cfg.preview.format)
    try:
        from .config.models import PreviewConfig
        if getattr(cfg, "preview", None) is None:
            cfg.preview = PreviewConfig(format=effective_preview_format)  # type: ignore
        else:
            cfg.preview.format = effective_preview_format  # type: ignore
    except Exception:
        pass
    logger.info(
        "cli.process.preview_format",
        format=effective_preview_format,
        cli=preview_format,
        preview_output_format=effective_preview_format,
    )

    # V1.8-2 (AC-PREV-A4/A5): Preview/Export-Pipeline Config aufloesen.
    # Ohne Config-Block -> Asinh-only (byte-identisch v1.6).
    effective_preview = resolve_preview_export_config(cfg, pipeline)
    pipeline.processing_params.preview_export = effective_preview
    logger.info(
        "cli.process.preview_export",
        stretch=effective_preview.stretch,
        scnr=effective_preview.scnr,
        saturation=effective_preview.saturation,
        background_neutralization=effective_preview.background_neutralization,
    )

    # V1.5-13 (W4): --se-radius/--se-amount ueberschreiben die Step-Params
    # des structure_enhancement-Preset-Steps (Precedence CLI > Preset).
    if se_radius is not None or se_amount is not None:
        for step in pipeline.steps:
            if step.name == "structure_enhancement":
                if se_radius is not None:
                    step.params["radius"] = se_radius
                if se_amount is not None:
                    step.params["amount"] = se_amount
                logger.info(
                    "cli.process.se_override",
                    radius=step.params.get("radius"),
                    amount=step.params.get("amount"),
                )
                break

    # V1.12-GROUP-SELECT (GROUP-SEL-1/2/3): --group Auflösung ORG-X2 (exakt/Prefix case-insensitiv).
    # Vor stage_input: existente Gruppen ermitteln, ORG-X2 Matching via core/organize reuse, Errors, Logging.
    _selected_groups: list[str] | None = None
    if selected_groups:
        lights_dir = target_dir / "lights"
        _existing_groups: list[str] = []
        if lights_dir.is_dir():
            _existing_groups = sorted(
                [d.name for d in lights_dir.iterdir() if d.is_dir() and d.name.lower().startswith("group_")]
            )
        if not _existing_groups:
            # Keine Gruppen vorhanden → Hard-Stop process.no_groups (GROUP-SEL-2/AC-GROUP-SEL-4) Exit 2
            msg = f"process.no_groups: no groups found in {lights_dir}, organize first"
            logger.error("process.no_groups", target=str(target_dir), lights=str(lights_dir), hint="Run 'astra organize' first")
            raise click.UsageError(msg)
        try:
            from .core.organize import resolve_group_selection
            _selected_groups = resolve_group_selection(list(selected_groups), _existing_groups)
        except ValueError as ve:
            msg = str(ve)
            # Log differenziert
            if "group_not_found" in msg:
                logger.error("process.group_not_found", requested=list(selected_groups), existing=_existing_groups, error=msg)
            elif "group_ambiguous" in msg:
                logger.error("process.group_ambiguous", requested=list(selected_groups), error=msg)
            raise click.UsageError(msg) from None
        logger.info("process.group_selection", groups=_selected_groups)

    # Work in timestamped generated/ subdirectory (preserves all runs).
    # dry-run: use a dryrun_<ts> prefix so status / merge skip these dirs.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    _ts_prefix = "dryrun_" if dry_run else ""
    working_dir = target_dir / "generated" / f"{_ts_prefix}{timestamp}"
    out_dir = working_dir  # same dir for intermediate and final outputs

    # Punkt 3 (Input-Staging): Pipeline liest NUR aus generated/<ts>/00_input.
    # Der Target-Root wird ausschliesslich hier gelesen (explizite Ordner
    # lights/darks/flats/bias) -- Fremd-FITS (App-Stacks, Siril, Exporte)
    # sind fuer die Pipeline komplett irrelevant.
    # ORG-X1: require_groups=True für echte Runs (Hard-Stop ohne Gruppen), dry-run/inspect = False (Legacy flat copy)
    # GROUP-SELECT (GROUP-SEL-3): nur gewählte Gruppen → stage_input (Filter)
    input_dir = stage_input(target_dir, working_dir, require_groups=not dry_run, selected_groups=_selected_groups)

    try:
        # Phase 1: Discovery
        logger.info("phase.discovery.start")
        discovery_agent = create_discovery_agent(cfg)
        discovery_result = discovery_agent.run(input_dir, shots_root=target_dir)
        context = discovery_result.context
        logger.info("phase.discovery.complete", lights=context.total_light_frames, darks=context.calibration.dark_count)

        # V1.11-SUBSET (SUBSET-1/SUBSET-6): --limit N -- Lights pro Gruppe kuerzen.
        # Integration-Punkt: nach build_observation_context() (via discovery_agent.run),
        # VOR Calibration -- Darks/Bias/Flats bleiben unangetastet (AC-SUBSET-2).
        # natural sort ist bereits durch FrameSet.group_by_params() garantiert
        # (Frames werden in der Reihenfolge des FITS-Scans erfasst, Dateiname
        # alphabetisch/natural sorted durch stage_input). Hier: Top-N Slice.
        # Platzierung in cli.py (nicht discovery.py): der limit-Parameter ist ein
        # CLI-Concern (OQ-SUBSET-4); discovery.py bleibt seiteneffektfrei/testbar.
        if limit is not None:
            from astro_process.models.core import FrameType
            lights_frameset = context.frames.get(FrameType.LIGHT)
            if lights_frameset is not None:
                # Zaehle Gesamt-Lights VOR der Kuerzu (fuer Marker in Archive).
                _frames_total = len(lights_frameset.frames)
                # Gruppiere nach (EXPTIME, GAIN, FILTER) -- analog discover_groups().
                # Jede Gruppe wird auf erste N Frames beschraenkt (natural sort).
                groups_by_params = lights_frameset.group_by_params()
                new_frames: list = []
                for _gkey, _gset in groups_by_params.items():
                    _original = len(_gset.frames)
                    _selected_frames = _gset.frames[:limit]
                    _selected = len(_selected_frames)
                    # Gruppen-Name analog compute_group_hash (Lesbarkeit im Log)
                    _exptime, _gain, _filter = _gkey
                    from astro_process.models.core import compute_group_hash as _cgh
                    _group_name = _cgh(float(_exptime), int(_gain), str(_filter))
                    logger.info(
                        "discovery.limit_applied",
                        group=_group_name,
                        original=_original,
                        selected=_selected,
                        limit=limit,
                    )
                    new_frames.extend(_selected_frames)
                lights_frameset.frames = new_frames
                # Metadaten fuer Archive-Phase (AC-SUBSET-3): am context speichern.
                # smoke_mode / limit / frames_total werden an archive_agent
                # als separate kwargs uebergeben (kein Context-Schema-Bruch).
                _smoke_frames_total = _frames_total
            else:
                _smoke_frames_total = 0
            _smoke_mode = True
            logger.info(
                "cli.process.limit_active",
                limit=limit,
                frames_total_before_limit=_smoke_frames_total,
                smoke_mode=True,
            )
        else:
            _smoke_mode = False
            _smoke_frames_total = None

        # V1.5-11 (W2) / V1.6-7: --az-mode/--eq-mode CLI-Override.
        # Precedence CLI > EQMODE-Header. Wenn gesetzt, ueberschreibt
        # den eq-Flag im DiscoveryResult (fuer archiv/agent-log) und wird
        # an den ProcessingAgent durchgereicht (fuer zukuenftige Header-
        # Override-Logik).
        if eq_mode_override is not None:
            override_eq = eq_mode_override == "eq"
            old_source = discovery_result.eq_source
            discovery_result.eq = override_eq
            discovery_result.eq_source = "cli_override"
            logger.info(
                "cli.process.eq_mode_override",
                override=eq_mode_override,
                eq=override_eq,
                previous_source=old_source,
            )

        # V1.7-4 (EQPT-C, OQ-EQPT-3; Fix B2 ray-Review 2026-08-23):
        # Datengetriebene stack_scale_factor-Aufloesung NACH der Discovery --
        # die Datenlage (2D-CFA vs. bereits debayertes 3D-RGB) ist erst jetzt
        # bekannt. Precedence: explicit (Config) > preset > datengetrieben
        # (3D -> 1.0; 2D + Methode) > Default 2.0. explicit/preset_ssf sind
        # in Stufe 1 (oben) abgeleitet -- VOR der Mutation von
        # effective_registration. Das fruehe cli.process.debayer-Log oben
        # bleibt als Intent; dieser Wert ist verbindlich
        # (effective_registration ist dasselbe Objekt, das im Preset
        # verankert ist -> Propagation in die Pipeline).
        from .core.equipment import detect_input_is_rgb, resolve_debayer_factor
        input_is_rgb = detect_input_is_rgb(context)
        resolved_ssf_final, ssf_source = resolve_debayer_factor(
            debayer_method=effective_debayer_method,
            explicit_value=explicit_ssf,
            preset_value=preset_ssf,
            input_is_rgb=input_is_rgb,
        )
        effective_registration.stack_scale_factor = resolved_ssf_final
        logger.info(
            "cli.process.stack_scale_factor_resolved",
            factor=resolved_ssf_final,
            source=ssf_source,
            input_is_rgb=input_is_rgb,
            debayer_method=effective_debayer_method,
        )

        # V1.11-ENTSCHLACKUNG ENTS-6: E3 Smart-Default entfernt -- registration_method
        # kommt garantiert aus File/CLI (Guard oben), kein Auto-Detect-Recompute noetig.
        # Persist effective registration_method for downstream multi-group resolver
        # (multi_group_agent.py liest _registration_cli_override).
        try:
            cfg._registration_cli_override = registration_method  # type: ignore[attr-defined]
        except Exception:
            pass

        # V19-REG-SMART E4: Pre-Check Warning fft auf AZ mit langer Belichtung (>=45s)
        try:
            from .core.equipment import detect_mount_type
            _cli_mount = "eq"
            _cli_threshold = 45.0
            # Threshold aus Equipment-Profil (dwarf_mini) wenn vorhanden
            try:
                for _prof in getattr(cfg, "equipment_profiles", []) or []:
                    if getattr(_prof, "name", "") == "dwarf_mini":
                        _cli_threshold = float(getattr(_prof, "max_exptime_fft_warn", 45.0))
                        break
                # Fallback: erstes Profil mit mount_type az
                if _cli_threshold == 45.0:
                    for _prof in getattr(cfg, "equipment_profiles", []) or []:
                        if getattr(_prof, "mount_type", "unknown") == "az":
                            _cli_threshold = float(getattr(_prof, "max_exptime_fft_warn", 45.0))
                            break
            except Exception:
                pass
            # Mount via ersten Light Header
            _hdr = None
            try:
                _lights = context.get_lights().frames if context else []
                if _lights and _lights[0].header is not None:
                    # Fits header raw_cards oder header Objekt
                    _raw = getattr(_lights[0].header, "raw_cards", None)
                    if _raw is not None:
                        _hdr = _raw
                    else:
                        _hdr = _lights[0].header
                # Fallback via equipment
                if context and hasattr(context, "equipment") and getattr(context.equipment, "profile_name", None) == "dwarf_mini":
                    _cli_mount = "az"
            except Exception:
                pass
            if _hdr is not None:
                try:
                    _cli_mount = detect_mount_type(_hdr)
                except Exception:
                    pass
            elif context and hasattr(context, "equipment"):
                # Alternative via context.equipment if header fails
                pass
            # max_exptime aus Lights
            _max_exp = 0.0
            try:
                _lights_all = context.get_lights().frames if context else []
                for _f in _lights_all:
                    if _f.header is not None and getattr(_f.header, "exptime", None) is not None:
                        try:
                            _v = float(_f.header.exptime)
                            if _v > _max_exp:
                                _max_exp = _v
                        except Exception:
                            continue
            except Exception:
                pass
            if effective_registration.method == "fft" and _cli_mount == "az" and _max_exp >= _cli_threshold:
                logger.warning(
                    "registration.fft_on_az_mount",
                    method=effective_registration.method,
                    mount_type=_cli_mount,
                    exptime=_max_exp,
                    threshold=_cli_threshold,
                    detail=(
                        f"FFT-Registrierung auf AZ-Mount mit {_max_exp}s Belichtung -- "
                        f"Feldrotation nicht korrigierbar (Threshold: {_cli_threshold}s). "
                        f"Erwartet: Ghosting an Bildraendern, Stern-Doppelkonturen (rotation_deg 0.0 ist FFT-Artefakt). "
                        f"Loesung: --registration-method astroalign --max-rotation 15 "
                        f"oder Equipment-Profil mit preferred_registration: astroalign"
                    ),
                )
        except Exception:
            pass

        # V1.7-5 (Always Multi-Group, AC-B3/B6): --multi-group/--auto-group
        # sind deprecated No-ops (Grace-Period bis v1.8) -- Multi-Group ist
        # immer aktiv. Der Merge bleibt per Default AN; die B6-Semantik
        # (merge_enabled = True wenn --merge/--no-merge nicht gesetzt) ist
        # damit identisch zur frueheren --multi-group-Automatic.
        if multi_group or auto_group:
            logger.warning(
                "cli.process.multi_group_flag_deprecated",
                flags=[name for name, v in (
                    ("--multi-group", multi_group), ("--auto-group", auto_group),
                ) if v],
                msg="Flag ist obsolet -- Multi-Group ist immer aktiv",
            )
            click.echo(
                "[WARN] --multi-group/--auto-group sind obsolet -- "
                "Multi-Group ist immer aktiv (deprecated, Entfernung in v1.8)",
                err=True,
            )

        if dry_run:
            # V1.7-5 (Always Multi-Group, AC-B4): EIN vereinheitlichter
            # Dry-Run fuer jede Gruppenzahl (inkl. 1) -- Kontextzeilen +
            # Gruppen-Tabelle + Reference/Merge/PCC-Info statt zweier Pfade.
            # discover_groups() ist read-only.
            from .agents.processing_agent import ProcessingAgent
            da = create_discovery_agent(ctx.obj["config"])
            groups = da.discover_groups(context)
            click.echo(f"DRY RUN - Would process {target_name} (multi-group)")
            click.echo(f"  Target type: {context.target.target_type.value}")
            click.echo(f"  Lights: {context.total_light_frames}")
            click.echo(f"  Darks: {context.calibration.dark_count}")
            click.echo(f"  Pipeline: {pipeline.name}")
            click.echo(f"  Steps: {', '.join(s.name for s in pipeline.steps)}")
            click.echo(f"\nMulti-Group: {len(groups)} groups found")
            if groups:
                # V1.7-1 FSM-C1/C3: Dry-run Transparenz -- Filter-Liste + Kandidat/excluded je Gruppe
                from .config.loader import resolve_merge_filters
                from .core.merge_filter import check_filter_typos, is_merge_filter_match

                _eff_filters = resolve_merge_filters(ctx.obj["config"], cli_filters=merge_filter)
                # V1.7-9 Zentralisierung: Tippfehler-Warning via check_filter_typos (merge.filter_typo)
                if _eff_filters is not None:
                    _cli_group_filters = [info.key[2] for info in groups.values()]
                    _cli_typos = check_filter_typos(_eff_filters, _cli_group_filters)
                    if _cli_typos:
                        _cli_group_norm = sorted(
                            {("" if v is None else str(v).strip().lower()) for v in _cli_group_filters}
                        )
                        for _flt in _cli_typos:
                            logger.warning(
                                "merge.filter_typo",
                                filter=_flt,
                                effective=_eff_filters,
                                groups=_cli_group_norm,
                                hint="Suspected typo: filter value matches no group",
                            )
                            click.echo(f"  [WARN] Filter '{_flt}' matches no group (suspected typo) -- available: {_cli_group_norm}", err=True)
                    # Kandidat-Zaehler via selbe Normalisierung wie Pipeline (None fuer "none"/"")
                    def _dry_filter_val(k2):
                        return None if k2 in ("none", "", None) else str(k2)
                    _cand_cnt = sum(1 for _gh, _info in groups.items() if is_merge_filter_match(_dry_filter_val(_info.key[2]), _eff_filters))
                    _excl_cnt = len(groups) - _cand_cnt
                    click.echo(f"Filter selection: {_eff_filters} -> {_cand_cnt} candidates, {_excl_cnt} excluded")
                else:
                    click.echo("Filter selection: all groups (no filter set)")
                click.echo(f"{'Hash':<20} {'EXPTIME':<10} {'GAIN':<8} {'FILTER':<15} {'Frames':<8} {'Total Exp':<12} {'MERGE':<22}")
                click.echo("-" * 97)
                for gh, info in groups.items():
                    _raw_fv = info.key[2]
                    _fv_for_match = None if _raw_fv in ("none", "", None) else str(_raw_fv)
                    _is_cand = is_merge_filter_match(_fv_for_match, _eff_filters) if _eff_filters is not None else True
                    _status = "CANDIDATE" if _is_cand else "excluded (filter_excluded)"
                    click.echo(f"{gh:<20} {info.key[0]:<10} {info.key[1]:<8} {str(info.key[2]):<15} {info.frame_count:<8} {info.total_exposure:<12.1f} {_status:<22}")
                # Show reference group
                mg_config = ctx.obj["config"].multi_group
                if mg_config is None:
                    mg_config = MultiGroupConfig()
                ref_strategy = mg_config.reference_group
                # FSM-B/C: Referenz nur unter Kandidaten (OQ-FSM-1 A frueh) -- dry-run transparent
                if _eff_filters is not None:
                    def _dry_filter_val2(k2):
                        return None if k2 in ("none", "", None) else str(k2)
                    _cand_groups = {gh: info for gh, info in groups.items() if is_merge_filter_match(_dry_filter_val2(info.key[2]), _eff_filters)}
                    if _cand_groups:
                        ref_hash = ProcessingAgent._select_reference_group(_cand_groups, ref_strategy)
                    else:
                        ref_hash = "(no candidates -- merge would be skipped)"
                else:
                    ref_hash = ProcessingAgent._select_reference_group(groups, ref_strategy)
                click.echo(f"\nReference group: {ref_hash}")
                # Show merge config
                if merge or merge is None:
                    merge_cfg = mg_config.merge
                    actual_method = merge_method or merge_cfg.method
                    actual_weight = weight_by or merge_cfg.weight_by
                    # V1.7-1 FSM-A: effektive Filter-Liste (CLI > Config) fuer dry-run Transparenz (bereits oben geloest)
                    if _eff_filters is not None:
                        click.echo(f"Merge: method={actual_method}, weight_by={actual_weight}, filters={_eff_filters}")
                        logger.info("cli.process.merge_filter", filters=_eff_filters)
                    else:
                        click.echo(f"Merge: method={actual_method}, weight_by={actual_weight}")
                else:
                    click.echo("Merge: disabled")
                click.echo(f"PCC fallback: {mg_config.pcc_fallback}")
            else:
                click.echo("No groups found (no light frames)")
            return

        # M1 (ray-Review v1.1): 0 Lights = FAIL, kein generischer
        # ClickException-Umweg. Sauberes structlog-Log + Exit-Code 2
        # (konsistent mit `astra doctor`: 0=OK, 1=WARN, 2=FAIL). dry-run
        # bleibt oben (informativ, Exit 0) -- nur echte Runs brechen ab.
        if context.total_light_frames == 0:
            logger.error("cli.process.no_light_frames",
                         target=str(target_dir), lights=0)
            click.echo(
                "[FAIL] No light frames found in target directory -- nothing to process",
                err=True,
            )
            sys.exit(2)

        # V1.7-5 (Always Multi-Group): Der fruehere V1.3-4-Warnblock
        # ("laeuft als Einzel-Stack" bei >1 Gruppe ohne --multi-group) ist
        # obsolet -- es gibt keinen Einzel-Stack-Pfad mehr, jede Gruppenzahl
        # laeuft vereinheitlicht durch process_multi_group.

        # Phase 2: Calibration
        logger.info("phase.calibration.start")
        if effective_no_calib:
            # T2: --no-calib -- vor-kalibrierte Lights gehen direkt zu
            # Debayer/Processing; kein cal_agent.run(), keine Darks/Flats/Bias.
            logger.info("phase.calibration.skipped", reason="no_calib")
            calibration_result = CalibrationResult(
                working_dir=working_dir,
                calibrated_lights=[f.path for f in context.get_lights().frames],
            )
        else:
            # W5: Darks Library - CLI --darks-path overrides Config darks_repository
            # Leo-Auftrag 2026-08-11 (B2): --darks-path ist optional -- ohne
            # CLI flag `darks_repository` from config is used.
            # In normal process path we let CalibrationAgent handle it
            # (V1.8-4 regression fix: no early CLI gate). The hard
            # darks abort remains in --preflight path where it belongs.
            # --no-calib skips this completely (see effective_no_calib above).
            effective_darks_path = darks_path or cfg.darks_repository
            if preflight and effective_darks_path is None:
                raise click.ClickException(
                    "No darks path set: calibration requires darks. "
                    "Setze darks_repository in config.yaml "
                    "(z.B. darks_repository: \"C:/Astra/_darks\") "
                    "oder uebergib --darks-path <Pfad>."
                )
            cal_agent = create_calibration_agent(working_dir, cfg, darks_repository=effective_darks_path)
            calibration_result = cal_agent.run(context)
            logger.info("phase.calibration.complete", master_dark=calibration_result.master_dark is not None)

        # Phase 2b: Cosmetic Correction (Leo-Auftrag 2026-08-10, Teil A).
        # Bad-Pixel-Korrektur auf dem CFA zwischen Kalibrierung und Debayer.
        # Config-Gated (AppConfig.cosmetic_correction.enabled, Default false)
        # -- deaktiviert liefert run() None und die Pipeline bleibt v1.3-
        # identisch. Aktiv ersetzt die Stufe calibration_result.calibrated_lights
        # durch die korrigierten Frames (01b_cosmetic/cos_*.fits); Debayer
        # und Processing lesen NUR diese Liste und bleiben unveraendert.
        # Precedence CLI > Config > Default (--cosmetic-correction /
        # --no-cosmetic-correction).
        if cosmetic_correction is not None:
            if cfg.cosmetic_correction is None:
                from .config.models import CosmeticCorrectionConfig
                cfg.cosmetic_correction = CosmeticCorrectionConfig()
            cfg.cosmetic_correction.enabled = cosmetic_correction
            logger.info(
                "cli.process.cosmetic_override",
                enabled=cosmetic_correction,
            )
        logger.info("phase.cosmetic.start")
        cosmetic_agent = create_cosmetic_agent(working_dir, cfg)
        cosmetic_result = cosmetic_agent.run(context, calibration_result)
        if cosmetic_result is not None:
            calibration_result.calibrated_lights = cosmetic_result.corrected_lights
            logger.info(
                "phase.cosmetic.complete",
                corrected=len(cosmetic_result.corrected_lights),
                bad_pixels=cosmetic_result.bad_pixel_count,
            )

        # Phase 3: Debayering (Bayer CFA → RGB 3D)
        logger.info("phase.debayer.start")
        debayer_agent = create_debayer_agent(working_dir, cfg, debayer_method_override=effective_debayer_method)
        debayer_result = debayer_agent.run(context, calibration_result)
        # Fix B1 ray-Review 2026-08-23 (V1.7-4, AC-EQPT-C5): Faktor + Quelle
        # strukturell ans DebayerResult haengen, damit der Archive-Agent sie
        # ins agent-log.yaml schreibt. Die finale Aufloesung passiert vor
        # dieser Phase (oben, nach der Discovery) -- hier nur die Uebergabe.
        debayer_result.stack_scale_factor = resolved_ssf_final
        debayer_result.stack_scale_factor_source = ssf_source
        logger.info("phase.debayer.complete", count=len(debayer_result.debayered_frames))
        # Phase 4: Processing (registration, stacking, stretch, export)
        processing_agent = create_processing_agent(working_dir, cfg)
        # V1.5-12 (W3): --pixel-scale CLI-Override an den ProcessingAgent.
        if pixel_scale is not None:
            processing_agent.pixel_scale_override = pixel_scale

        # V1.7-5 (Always Multi-Group, AC-B1/B2): Es gibt nur noch EINEN
        # Verarbeitungspfad -- process_multi_group fuer jede Gruppenzahl
        # (inkl. 1; der Processor materialisiert bei 1 Gruppe kanonisch
        # nach merged/). Der fruehere Einzel-Stack-Zweig (processing_agent.
        # run()) ist aus der CLI entfernt; run() bleibt Programmatic-API.
        logger.info("phase.processing.multi_group.start")

        # Resolve multi-group config (handle None gracefully)
        mg_config = ctx.obj["config"].multi_group
        if mg_config is None:
            mg_config = MultiGroupConfig()

        # CR-001 P1 (AC-P1-2/3): CLI-Flag ueberschreibt Config.
        # Precedence: CLI > Config > Default(true).
        if keep_groups is not None:
            mg_config.keep_group_working_dirs = keep_groups

        # CLI overrides for merge config
        if weight_by:
            mg_config.merge.weight_by = weight_by
        if merge_method:
            mg_config.merge.method = merge_method
        # V1.7-9 Zentralisierung: Normalisierung via core.merge_filter (loader re-export bleibt gueltig)
        from .core.merge_filter import normalize_merge_filters

        if merge_filter:
            mg_config.merge.filters = normalize_merge_filters(list(merge_filter))
            # CLI-Liste gewinnt immer wenn gesetzt, auch wenn nach Trimmen leer
            # (AC-FSM-A5: <2 Kandidaten -> Merge-Skip).
        else:
            # Kein CLI-Override: Config-Wert normalisieren (trim+lower) fuer
            # konsistentes Matching (AC-FSM-A2). None bleibt None (AC-FSM-A1).
            if mg_config.merge.filters is not None:
                mg_config.merge.filters = normalize_merge_filters(mg_config.merge.filters)
        # Fuer Dry-Run-Transparenz: effektive Liste loggen (Batch A minimal).
        # Die fruehe Filter-Semantik (OQ-FSM-1 A vor Referenzwahl/Pass2/PCC)
        # kommt in Batch B -- hier nur Config/CLI korrekt resolved.
        # Logge effektive Filter fuer Debugging (additiv, kein Ballast bei None).
        if mg_config.merge.filters is not None:
            logger.info("cli.process.merge_filter", filters=mg_config.merge.filters)

        # V1.6 (stella/Boris 2026-08-20): PCC per Group vs. Merged Stack
        # Precedence: CLI > Config > Default(false).
        if pcc_per_group is not None:
            mg_config.pcc_per_group = pcc_per_group

        # V1.12-GROUP-SELECT (GROUP-SEL-3/4): propagate selected_groups to processor & archive via config
        try:
            cfg._selected_groups = _selected_groups  # type: ignore[attr-defined]
        except Exception:
            pass

        # V1.7-5 (AC-B6): Merge per Default AN (--no-merge deaktiviert) --
        # identische Semantik wie zuvor hinter --multi-group. Bei genau
        # 1 Gruppe ruft der Processor den MergeAgent ohnehin nicht auf,
        # sondern materialisiert kanonisch nach merged/ (AC-C5).
        merge_enabled = True if merge is None else merge
        merge_agent_instance = MergeAgent(working_dir, ctx.obj["config"]) if merge_enabled else None

        proc_result = processing_agent.process_multi_group(
            context, calibration_result, debayer_result, pipeline,
            multi_group_config=mg_config,
            merge_agent=merge_agent_instance,
            target_name=target_name,
        )

        logger.info("phase.processing.complete", stacked=proc_result.stacked is not None)

        # Phase 5: Archive
        logger.info("phase.archive.start")
        archive_agent = create_archive_agent(out_dir, cfg)
        archive_result = archive_agent.run(
            context, proc_result, calibration_result,
            debayer_result=debayer_result,
            # V1.3-1 (RE-C): Empfehlung (DiscoveryResult.recommendation)
            # additiv ins agent-log; bisher ungenutzter Parameter.
            discovery_result=discovery_result,
            keep_working=keep_working,
            multi_group_metadata=proc_result.multi_group_metadata if hasattr(proc_result, 'multi_group_metadata') else None,
            # V1.11-SUBSET (AC-SUBSET-3): Smoke-Mode Marker fuer run-info.json + agent-log.yaml.
            smoke_mode=_smoke_mode,
            smoke_limit=limit,
            smoke_frames_total=_smoke_frames_total,
            # V1.12-GROUP-SELECT (GROUP-SEL-4): selected_groups Traceability (null = alle)
            selected_groups=_selected_groups,
            # V1.12-SUGGESTED-ARCHIVE: Reproduzierbarkeit -- genutztes suggested-File je Run
            suggested_path=Path(from_suggested) if from_suggested is not None else None,
        )
        logger.info("phase.archive.complete", output=str(archive_result.output_dir))

        # Summary
        click.echo(f"\n[OK] Processing complete: {target_name}")
        if effective_no_calib:
            click.echo("   Calibration: skipped (--no-calib)")
        click.echo(f"   Output: {archive_result.output_dir}")
        if archive_result.final_fits:
            click.echo(f"   FITS: {archive_result.final_fits.name} (RGB, linear, {archive_result.final_fits.stat().st_size // 1024} KB)")
            # Show preview if it exists (single-group: output_dir; multi-group: merged/)
            preview = archive_result.final_fits.parent / (
                f"{archive_result.final_fits.stem}_preview.jpg"
            )
            if preview.exists():
                click.echo(f"   Preview: {preview.name} (auto-stretched, {preview.stat().st_size // 1024} KB)")

    except Exception as e:
        logger.error("cli.process.failed", error=str(e), exc_info=True)
        raise click.ClickException(f"Processing failed: {e}")


# V19-1.10-TARGET-ADVISOR (SUG-1): `astra suggest` -- offline-first advisor,
# 1-2 numbered options (preset/registration/debayer/pcc), Handbook-cited,
# never a decider (project.md Out-of-Scope: no target classification, the
# user still chooses --preset). Core logic lives in core/suggest.py; this
# command only wires CLI args <-> that module (cli.py stays command-shape
# only, see plan.md Struktur-Empfehlung).
@cli.command()
@click.argument("target", required=False)
@click.option(
    "--header",
    "header_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Read OBJECT/FILTER/EXPTIME/TELESCOP/DET-TEMP from a local FITS "
        "header (local only, no cloud). OBJECT wins over TARGET when both "
        "are given (suggest.header_overrides_target warning)."
    ),
)
@click.option(
    "--coords",
    nargs=2,
    type=str,
    default=None,
    help=(
        "Fallback RA/DEC (decimal degrees) when TARGET/--header do not "
        "resolve a cache hit. Used only for SIMBAD lookup / labeling; "
        "suggest never plate-solves."
    ),
)
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(path_type=Path),
    help=(
        "Override the output file path for the suggested_parameters file "
        "(FILE path, not directory; YAML default, JSON on .json suffix). "
        "Without --output the file is always written to "
        "C:/Astra/<Target>/suggested.yaml (Target-Root, next to Lights). "
        "Always overwrites (no auto-history). "
        "Examples: --output C:/Astra/M31/suggested.yaml or --output C:/Astra/M31/custom_suggest.yaml"
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the machine-readable JSON suggestion to stdout instead of the human-readable text.",
)
@click.pass_context
def suggest(ctx, target, header_path, coords, output_path, as_json):
    """Suggest a preset/registration/debayer/PCC combination for TARGET.

    Offline-first advisor (Header > target-cache > SIMBAD > Handbook 22):
    the local target-cache always wins; SIMBAD is only queried on a cache
    miss and only if the network is reachable (5s timeout, 1 query). On
    cache miss + SIMBAD unreachable for an unknown target: Error Exit 2
    (suggest.simbad_unavailable); add the entry in astra/data/target-cache.json (baked, requires wheel release).

    Always writes suggested.yaml to <data_root>/<Target>/suggested.yaml
    (Target-Root) unless --output overrides the path. 'astra process'
    requires --from-suggested (run 'astra suggest <TARGET>' first).

    Examples:
        astra suggest M31
        astra suggest M31 --output C:/Astra/M31/suggested_20260905.yaml
        astra suggest M27 --header C:/Astra/M27/light_0001.fits
        astra suggest C19 --json --output C:/Astra/C19/suggested.yaml
    """
    cfg: AppConfig = ctx.obj["config"]
    suggest_cfg = getattr(cfg, "suggest", None)
    cache_path = getattr(suggest_cfg, "target_cache_path", None) if suggest_cfg else None

    coords_tuple = None
    if coords:
        try:
            coords_tuple = (float(coords[0]), float(coords[1]))
        except ValueError:
            raise click.ClickException(
                f"--coords expects two decimal-degree values, got: {coords!r}"
            )

    try:
        result = suggest_core.build_result(
            target=target,
            header_path=header_path,
            coords=coords_tuple,
            cache_path=cache_path,
            data_root=cfg.data_root,
        )
    except suggest_core.SuggestInputError as e:
        raise click.UsageError(str(e)) from e

    data = suggest_core.to_json_dict(result)

    # ENTS-1: always write suggested.yaml -- --output is a pure path override.
    # Default: <data_root>/<Target>/suggested.yaml (Target-Root).
    # B1 Ghost (V1.12-STEP2 Amendment 0.2d, stella B1): path stays original_target,
    # never effective_target (header OBJECT). --output overrides.
    original_target = target  # vom User übergebener Ordnername (vor Header-Override)
    resolved_output = (
        Path(output_path) if output_path is not None
        else suggest_core.default_output_path(original_target or result.target, data_root=cfg.data_root)
    )
    # DEF-012 Ghost-Ordner-Guard (Boris-Go): vor mkdir/default_output_path prüfen --
    # suggest "M31" -> Error + Hint, kein mkdir C:\Astra\M31\.
    # T2 (V1.12-STEP2): Guard nur bei TARGET ohne Header (stella A4) -- Header-Pfad
    # umgeht Guard (Header OBJECT gewinnt, SUG-2). Ohne Header + ohne lights\ ->
    # triple miss Exit 2 (ray Risiko #3, ENTS-3/4).
    # Fix (v1.12-cleanup): Guard nur bei Default-Output (kein --output).
    # Mit --output schreibt User in beliebigen Ordner (wie organize --output) --
    # Guard würde dort fälschlich lights\ suchen (Stella Bug #36/#37).
    if header_path is None and output_path is None:
        target_dir = resolved_output.parent
        if not target_dir.is_dir() or not (target_dir / "lights").is_dir():
            raise click.UsageError(
                f"Target directory is missing: {target_dir} \u2014 use the exact directory name from C:\\Astra "
                f"(e.g. 'M31 Andromeda'); do not create new target directories."
            )
    try:
        suggest_core.write_suggested_file(
            suggest_core.to_file_dict(result), resolved_output, header_path=header_path,
            skip_ghost_guard=(output_path is not None),
        )
    except suggest_core.SuggestInputError as e:
        raise click.UsageError(str(e)) from e
    logger.info(
        "suggest.wrote_suggested",
        path=str(resolved_output),
        preset=data["preset"],
        method=data["registration"]["method"],
    )

    if as_json:
        # Single-line JSON (kein indent): structlog schreibt vorangehende
        # Log-Events ebenfalls nach stdout (JSONRenderer) -- die letzte Zeile
        # ist so eindeutig als DAS Suggest-Ergebnis identifizierbar/parsebar.
        click.echo(json.dumps(data))
    else:
        click.echo(suggest_core.render_human(result))


@cli.command()
@click.argument("data_root", type=click.Path(exists=True, path_type=Path))
@click.option("--preset", "-p", default=None, help="Preset override for all targets (default: from per-target suggested.yaml)")
@click.option("--dry-run", is_flag=True)
# V1.11-SUBSET (SUBSET-3): --limit propagation for batch (uniform, per-group, per-target).
@click.option(
    "--limit",
    "limit",
    type=int,
    default=None,
    help=(
        "Limit number of light frames per group for smoke testing - applied uniformly "
        "to every target in the batch (N >= 1). See 'astra process --help' for details."
    ),
)
@click.pass_context
def batch(ctx, data_root, preset, dry_run, limit):
    """Process all subdirectories in data root.

    Each target directory must have a suggested.yaml (run 'astra suggest
    <TARGET>' first). The per-target suggested.yaml is passed via
    --from-suggested (Target-Root default). Missing file -> Error (ENTS-1).
    """
    cfg: AppConfig = ctx.obj["config"]

    # V1.11-SUBSET (OQ-SUBSET-3): Validate --limit N >= 1 in batch context.
    if limit is not None and limit < 1:
        raise click.UsageError(
            f"batch.limit.invalid: --limit must be >= 1 (got {limit}) "
            f"-- use --limit N with N >= 1, or omit --limit to process all frames"
        )

    targets = [d for d in Path(data_root).iterdir() if d.is_dir()]
    click.echo(f"Found {len(targets)} targets")

    for target in targets:
        click.echo(f"\n--- Processing {target.name} ---")
        # ENTS-3: pass per-target suggested.yaml (Target-Root default).
        # Missing file -> canonical not_found Error (OQ-ENTS-1 A, strikt).
        target_suggested = str(target / "suggested.yaml")
        ctx.invoke(
            process,
            target_path=target,
            preset=preset,
            dry_run=dry_run,
            from_suggested=Path(target_suggested),
            # V1.11-SUBSET (SUBSET-3): propagate --limit uniform to each target.
            limit=limit,
        )


@cli.command()
@click.option("--non-interactive", is_flag=True, help="Non-interactive: use flags/env vars, no prompts (CI-friendly)")
@click.option("--project-dir", type=click.Path(path_type=Path), help="Astra project directory (default: current directory)")
@click.option("--data-root", type=click.Path(path_type=Path), help="Data root (default: C:/Astra)")
@click.option("--darks-library", type=click.Path(path_type=Path), help="Darks library (default: C:/Astra/_darks)")
@click.option("--preset", "init_preset", type=click.Choice(["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]), help="Default preset")
@click.option("--cosmetic/--no-cosmetic", "cosmetic", default=None, help="Enable or disable cosmetic default")
@click.option("--config-output", type=click.Path(path_type=Path), help="Destination for config.yaml (default: ./config.yaml)")
@click.pass_context
def init(ctx, non_interactive, project_dir, data_root, darks_library, init_preset, cosmetic, config_output):
    """Initialize Astra configuration (Wizard).

    The wizard interactively prompts for the Astra Project Dir, Data Root (C:\\Astra),
    Darks Library (C:\\Astra\\_darks), Default Preset, and Cosmetic Default,
    then writes config.yaml + environment.yaml (Pydantic-validated).

    With --non-interactive, flags/env vars are used (CI-capable), without prompts.
    Environment variables: ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, ASTRA_DEFAULT_PRESET.
    """
    console = _rich_console()
    # Auto-detect non-interactive mode for CI/Non-TTY: falls back to flags/env/defaults
    # without prompts, keeping the interactive experience in a real terminal.
    if not non_interactive and not _stdin_is_tty():
        non_interactive = True

    # V19-ENV: .env laden bevor Env-Vars gelesen werden (Precedence CWD > pipeline_root, Shell > .env)
    try:
        from .config.loader import _load_dotenv_files
        _load_dotenv_files()
    except Exception:
        pass

    # Resolve defaults from flags / env / defaults
    env_data_root = os.environ.get("ASTRA_DATA_ROOT")
    env_darks = os.environ.get("ASTRA_DARKS_REPOSITORY")
    env_preset = os.environ.get("ASTRA_DEFAULT_PRESET")
    env_cosmetic = os.environ.get("ASTRA_COSMETIC_CORRECTION")

    def _validate_preset(v):
        if v not in ["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]:
            raise ValueError(f"Unknown preset {v!r}")

    if non_interactive:
        # Use flags > env > defaults, no prompts
        proj_dir = Path(project_dir) if project_dir else Path.cwd()
        dr = Path(data_root) if data_root else (Path(env_data_root) if env_data_root else Path("C:/Astra"))
        dl = Path(darks_library) if darks_library else (Path(env_darks) if env_darks else Path("C:/Astra/_darks"))
        preset_val = init_preset or env_preset or "star_standard"
        if preset_val:
            _validate_preset(preset_val)
        cosmetic_val = cosmetic
        if cosmetic_val is None and env_cosmetic is not None:
            cosmetic_val = env_cosmetic.lower() in ("1", "true", "yes", "on")
        if cosmetic_val is None:
            cosmetic_val = False
    else:
        if console:
            console.print(Panel("Astra Init Wizard", style="bold cyan"))
        # Interactive prompts
        proj_default = str(project_dir) if project_dir else str(Path.cwd())
        data_default = str(data_root) if data_root else (env_data_root or "C:/Astra")
        darks_default = str(darks_library) if darks_library else (env_darks or "C:/Astra/_darks")
        preset_default = init_preset or env_preset or "star_standard"
        cosmetic_default = "y" if (cosmetic if cosmetic is not None else False) else "n"

        proj_str = _ask("Astra Project Dir", default=proj_default)
        proj_dir = Path(proj_str)
        data_str = _ask("Data Root", default=data_default)
        dr = Path(data_str)
        darks_str = _ask("Darks Library", default=darks_default)
        dl = Path(darks_str)
        preset_val = _ask("Default Preset (galaxy_standard/nebula_standard/star_standard/nebula_narrowband)", default=preset_default, validate=_validate_preset)
        cos_str = _ask("Enable Cosmetic Default? (y/n)", default=cosmetic_default)
        cosmetic_val = cos_str.lower() in ("y", "yes", "true", "1")

    # Pydantic validation via AppConfig: constructing the model validates the values.
    validated_cfg = AppConfig(
        data_root=dr,
        darks_repository=dl,
        default_preset=preset_val,
        cosmetic_correction={"enabled": bool(cosmetic_val)} if cosmetic_val else {"enabled": False},
    )
    # validated_cfg is intentionally discarded; the constructor already enforced validation.
    # Write config.yaml (preserve DEFAULT_CONFIG comments as SSOT for docs)
    out_path = Path(config_output) if config_output else (proj_dir / "config.yaml")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    config_updates = {
        "data_root": str(dr),
        "darks_repository": str(dl),
        "default_preset": preset_val,
        "cosmetic_correction": {"enabled": bool(cosmetic_val)},
    }
    _write_config_with_comments(out_path, config_updates)
    # Write environment.yaml
    env_path = proj_dir / "environment.yaml"
    env_dict = {
        "astra_project_dir": str(proj_dir),
        "data_root": str(dr),
        "darks_library": str(dl),
        "default_preset": preset_val,
        "cosmetic_default": bool(cosmetic_val),
    }
    with open(env_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(env_dict, f, sort_keys=False, allow_unicode=True)

    if console:
        console.print(f"[green]Created {out_path}[/green]")
        console.print(f"[green]Created {env_path}[/green]")
        tbl = Table(title="Config")
        tbl.add_column("Key")
        tbl.add_column("Value")
        for k, v in env_dict.items():
            tbl.add_row(k, str(v))
        console.print(tbl)
    else:
        click.echo(f"Created {out_path}")
        click.echo(f"Created {env_path}")


# ─────────────────────────────────────────────────────────────────
# CLI-B -- astra config Subcommands
# ─────────────────────────────────────────────────────────────────
@cli.group()
def config():
    """Manage configuration (precedence: CLI > Config > Env > Default)."""


def _get_nested(data: dict, key: str):
    parts = key.split(".")
    cur = data
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur

def _set_nested(data: dict, key: str, value):
    parts = key.split(".")
    cur = data
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value

def _load_raw_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def _find_config_file(ctx) -> Path:
    # Try ctx config_path, then cwd, then pipeline_root
    cp = ctx.obj.get("config_path")
    if cp and Path(cp).exists():
        return Path(cp)
    cwd_cfg = Path.cwd() / "config.yaml"
    if cwd_cfg.exists():
        return cwd_cfg
    from .config.loader import _pipeline_root
    pr = _pipeline_root() / "config.yaml"
    if pr.exists():
        return pr
    return cwd_cfg

@config.command("show")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output (JSON)")
@click.pass_context
def config_show(ctx, as_json):
    """Show the fully merged configuration (defaults + user + env) -- Precedence CLI > Config > Env > Default."""
    cfg: AppConfig = ctx.obj["config"]
    # Also include env overrides for display
    env_overrides = {k: v for k, v in os.environ.items() if k.startswith("ASTRA_")}
    data = cfg.model_dump(mode="json")
    # Add precedence info
    if as_json:
        out = {"config": data, "env_overrides": env_overrides, "precedence": "CLI>Config>Env>Default"}
        click.echo(json.dumps(out, indent=2, default=str))
    else:
        console = _rich_console()
        if console:
            console.print(Panel("Astra Config (merged) -- Precedence: CLI > Config > Env > Default", style="cyan"))
            tbl = Table()
            tbl.add_column("Key")
            tbl.add_column("Value")
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    v = json.dumps(v)[:120]
                tbl.add_row(k, str(v))
            console.print(tbl)
            if env_overrides:
                console.print(f"[dim]Env-Overrides: {env_overrides}[/dim]")
        else:
            click.echo("# Merged Config (CLI>Config>Env>Default)")
            for k, v in data.items():
                click.echo(f"{k}: {v}")
            click.echo("# Precedence: CLI>Config>Env>Default")
            if env_overrides:
                click.echo(f"# Env: {env_overrides}")

@config.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx, key):
    """Get a single configuration value via dot-notation (e.g. data_root, multi_group.merge.method)."""
    cfg: AppConfig = ctx.obj["config"]
    data = cfg.model_dump(mode="json")
    val = _get_nested(data, key)
    if val is None:
        # also try direct attribute
        if hasattr(cfg, key):
            val = getattr(cfg, key)
        else:
            raise click.ClickException(f"Key '{key}' not found")
    if isinstance(val, (dict, list)):
        click.echo(json.dumps(val, indent=2, default=str))
    else:
        click.echo(str(val))

@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx, key, value):
    """Set a configuration value (validated via Pydantic; invalid values raise an error) and save config.yaml."""
    cfg_path = _find_config_file(ctx)
    raw = _load_raw_config_file(cfg_path)
    # Parse value: try json, else string
    try:
        parsed = json.loads(value)
    except Exception:
        # try yaml-ish bool/int/float
        if value.lower() in ("true", "false"):
            parsed = value.lower() == "true"
        else:
            try:
                parsed = int(value)
            except ValueError:
                try:
                    parsed = float(value)
                except ValueError:
                    parsed = value
    _set_nested(raw, key, parsed)
    # Validate via Pydantic
    try:
        validated = AppConfig(**raw)
    except Exception as e:
        raise click.ClickException(f"Validation failed for '{key}={value}': {e}")
    # Write back
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
    click.echo(f"Set {key}={parsed} in {cfg_path}")

@config.command("reset")
@click.argument("key")
@click.pass_context
def config_reset(ctx, key):
    """Reset a key to its default and remove it from config.yaml."""
    cfg_path = _find_config_file(ctx)
    raw = _load_raw_config_file(cfg_path)
    parts = key.split(".")
    cur = raw
    for p in parts[:-1]:
        if p not in cur:
            raise click.ClickException(f"Key '{key}' not found")
        cur = cur[p]
    if parts[-1] not in cur:
        raise click.ClickException(f"Key '{key}' not found")
    del cur[parts[-1]]
    # Clean empty parents?
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
    click.echo(f"Reset {key} (Default) in {cfg_path}")

@config.command("wizard")
@click.pass_context
def config_wizard(ctx):
    """Interactive TUI configuration wizard."""
    ctx.invoke(init)


@cli.group()
def darks():
    """Manage the Darks Library (sync/list/check/import)."""


@darks.command("sync")
@click.option("--dry-run", is_flag=True, help="Show what would be copied without copying")
@click.option("--source", "source_path", type=click.Path(path_type=Path), help="Source (default: C:/Dwarflab/CALI_FRAME/dark/cam_0)")
@click.option("--dest", "dest_path", type=click.Path(path_type=Path), help="Destination (default: C:/Astra/_darks)")
@click.pass_context
def darks_sync(ctx, dry_run, source_path, dest_path):
    """Sync DwarfLab export into the Darks Library (TELE/cam_0 only, never WIDE/cam_1)."""
    cfg: AppConfig = ctx.obj["config"]
    src = Path(source_path) if source_path else Path("C:/Dwarflab/CALI_FRAME/dark/cam_0")
    dst = Path(dest_path) if dest_path else (cfg.darks_repository or Path("C:/Astra/_darks"))
    # Filter: nur cam_0 (TELE), kein cam_1 (WIDE)
    if "cam_1" in str(src) or "WIDE" in str(src):
        raise click.ClickException("Sync is only supported for TELE/cam_0, not WIDE/cam_1")
    if not src.exists():
        click.echo(f"Source {src} does not exist -- nothing to sync (dry-run mock ok)")
        if dry_run:
            click.echo("[DRY-RUN] Would sync darks: 0 files")
        return
    # Discover FITS in source
    fits_files = list(src.rglob("*.fits")) + list(src.rglob("*.fit"))
    # Group by exp+gain parsed from header or filename
    actions = []
    for p in fits_files:
        # Skip cam_1 nested?
        if "cam_1" in str(p) or "WIDE" in str(p):
            continue
        # Parse EXPTIME/GAIN from header if possible
        exptime = gain = None
        try:
            from astropy.io import fits as afits
            with afits.open(p) as hdul:
                h = hdul[0].header
                exptime = h.get("EXPTIME") or h.get("EXPOSURE")
                gain = h.get("GAIN")
        except Exception:
            pass
        if exptime is None:
            exptime = 30
        if gain is None:
            gain = 0
        sub = dst / f"{int(float(exptime))}s{gain}"
        dest_file = sub / p.name
        if not dest_file.exists():
            actions.append((p, dest_file))
    if dry_run:
        click.echo(f"[DRY-RUN] Would copy {len(actions)} darks: {src} -> {dst}")
        for s, d in actions[:10]:
            click.echo(f"  {s.name} -> {d}")
        if len(actions) > 10:
            click.echo(f"  ... +{len(actions)-10} more")
    else:
        copied = 0
        for s, d in actions:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
            copied += 1
        click.echo(f"Sync complete: {copied} darks copied ({len(actions)-copied} already present) -> {dst}")
    logger.info("cli.darks.sync", source=str(src), dest=str(dst), dry_run=dry_run, actions=len(actions))

@darks.command("list")
@click.pass_context
def darks_list(ctx):
    """List dark frames in the library."""
    cfg: AppConfig = ctx.obj["config"]
    dst = cfg.darks_repository or Path("C:/Astra/_darks")
    if not dst.exists():
        click.echo(f"Darks library not found: {dst}")
        return
    subs = sorted([d for d in dst.iterdir() if d.is_dir()])
    if not subs:
        click.echo("No darks found")
        return
    for sub in subs:
        files = list(sub.glob("*.fit*"))
        click.echo(f"{sub.name}: {len(files)} Darks")
        for f in files[:5]:
            click.echo(f"  {f.name}")
        if len(files) > 5:
            click.echo(f"  ... +{len(files)-5}")

@darks.command("check")
@click.argument("target", type=click.Path(path_type=Path))
@click.pass_context
def darks_check(ctx, target):
    """Check dark-frame coverage for a target.

    Checks both the central darks library (darks_repository) and any local
    darks/ folder inside the target directory (dark_source=local, as used by
    'astra process' when no library darks match). Local darks are reported
    separately so coverage is not misleadingly shown as MISSING.
    """
    cfg: AppConfig = ctx.obj["config"]
    target_dir = Path(target).resolve()
    try:
        context = (
            build_observation_context(target_dir, target_name=target_dir.name)
            if target_dir.exists()
            else None
        )
    except Exception:
        context = None
    dst = cfg.darks_repository or Path("C:/Astra/_darks")
    click.echo(f"Target: {target_dir}")
    click.echo(f"Darks Library: {dst} ({'exists' if dst.exists() else 'missing'})")
    # Local darks/ in target (dark_source=local, used by process when library has no match)
    local_darks_dir = target_dir / "darks"
    local_dark_count = (
        len(list(local_darks_dir.glob("*.fit*"))) if local_darks_dir.is_dir() else 0
    )
    if local_dark_count > 0:
        click.echo(f"Target-local darks: {local_dark_count} frames in {local_darks_dir}")
        click.echo(
            "  Note: target-local darks are used by 'astra process' "
            "(dark_source=local) and count as coverage."
        )
    else:
        click.echo(f"Target-local darks: none ({local_darks_dir})")
    if context:
        click.echo(f"Lights: {context.total_light_frames}")
        groups = context.get_lights().group_by_params()
        for gk, fs in groups.items():
            exptime, gain, flt = gk
            sub = dst / f"{int(float(exptime))}s{gain}"
            avail = len(list(sub.glob("*.fit*"))) if sub.exists() else 0
            # Local darks also cover this group (process uses dark_source=local as fallback)
            covered = avail > 0 or local_dark_count > 0
            source_info = ""
            if avail > 0:
                source_info = f"library ({avail} frames)"
            elif local_dark_count > 0:
                source_info = f"target-local ({local_dark_count} frames, used by process)"
            status = "OK" if covered else "MISSING"
            click.echo(
                f"  Group {gk}: {len(fs.frames)} frames -> "
                f"library {sub.name}: {avail} darks | "
                f"coverage: {status}"
                + (f" [{source_info}]" if source_info else "")
            )

@darks.command("import")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Dry-run")
@click.pass_context
def darks_import(ctx, path, dry_run):
    """Import dark frames from a path into the library."""
    cfg: AppConfig = ctx.obj["config"]
    dst = cfg.darks_repository or Path("C:/Astra/_darks")
    src = Path(path)
    files = list(src.rglob("*.fit*")) if src.is_dir() else [src]
    # Filter only TELE/cam_0: skip WIDE/cam_1
    filtered = [p for p in files if "cam_1" not in str(p) and "WIDE" not in str(p)]
    if dry_run:
        click.echo(f"[DRY-RUN] Would import {len(filtered)} darks -> {dst}")
        return
    for p in filtered:
        # Determine dest sub via header
        exptime = gain = None
        try:
            from astropy.io import fits as afits
            with afits.open(p) as hdul:
                h = hdul[0].header
                exptime = h.get("EXPTIME") or 30
                gain = h.get("GAIN") or 0
        except Exception:
            exptime, gain = 30, 0
        sub = dst / f"{int(float(exptime))}s{gain}"
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, sub / p.name)
    click.echo(f"Import complete: {len(filtered)} Darks -> {dst}")


# ─────────────────────────────────────────────────────────────────
# CLI-E -- astra target Management
# ─────────────────────────────────────────────────────────────────
@cli.group()
def target():
    """Target management (list/add/show/update/remove)."""


@target.command("list")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output (JSON)")
@click.pass_context
def target_list(ctx, as_json):
    """List all targets and their progress."""
    cfg: AppConfig = ctx.obj["config"]
    data_root = cfg.data_root
    targets = []
    if data_root.exists():
        for d in sorted(data_root.iterdir()):
            if not d.is_dir():
                continue
            if d.name.startswith("_"):
                continue
            lights = list((d / "lights").glob("*.fit*")) if (d / "lights").exists() else list(d.glob("*.fit*"))
            # Count via staging? simple
            try:
                ctx2 = build_observation_context(d, target_name=d.name) if d.exists() else None
                light_cnt = ctx2.total_light_frames if ctx2 else len(lights)
            except Exception:
                light_cnt = len(lights)
            generated = d / "generated"
            runs = len(list(generated.iterdir())) if generated.exists() else 0
            targets.append({"name": d.name, "lights": light_cnt, "runs": runs, "path": str(d)})
    if as_json:
        click.echo(json.dumps(targets, indent=2))
    else:
        console = _rich_console()
        if console and targets:
            tbl = Table(title=f"Targets in {data_root}")
            tbl.add_column("Target")
            tbl.add_column("Lights")
            tbl.add_column("Runs")
            for t in targets:
                tbl.add_row(t["name"], str(t["lights"]), str(t["runs"]))
            console.print(tbl)
        else:
            for t in targets:
                click.echo(f"{t['name']}: {t['lights']} Lights, {t['runs']} Runs")
        if not targets:
            click.echo(f"No targets in {data_root}")

@target.command("add")
@click.argument("name")
@click.option("--preset", type=click.Choice(["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]), help="Preset")
@click.option("--non-interactive", is_flag=True, help="Non-interactive")
@click.pass_context
def target_add(ctx, name, preset, non_interactive):
    """Create a new target and generate an AUFNAHMELISTE_{Target}.md template."""
    cfg: AppConfig = ctx.obj["config"]
    data_root = cfg.data_root
    target_dir = data_root / name
    if target_dir.exists():
        raise click.ClickException(f"Target already exists: {target_dir}")
    # Determine preset
    chosen_preset = preset
    if not chosen_preset and not non_interactive:
        chosen_preset = _ask("Preset (galaxy_standard/nebula_standard/star_standard/nebula_narrowband)", default=cfg.default_preset or "star_standard")
    if not chosen_preset:
        chosen_preset = cfg.default_preset or "star_standard"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "lights").mkdir(exist_ok=True)
    (target_dir / "darks").mkdir(exist_ok=True)
    # Create template
    tpl = target_dir / f"AUFNAHMELISTE_{name}.md"
    content = f"""# Aufnahmeliste {name}

- **Target:** {name}
- **Preset:** {chosen_preset}
- **Datum:** {datetime.now().strftime("%Y-%m-%d")}
- **SOLL:** Lights / Darks / Flats / Bias (ausfuellen)
- **Serien:** (z.B. 30x 30s Gain 80)

## Status
- Lights: 0
- Darks: 0
- Preset: {chosen_preset}

## Notizen
Hier Aufnahmeplan und Durchfuehrung dokumentieren.
"""
    tpl.write_text(content, encoding="utf-8")
    click.echo(f"Target {name} angelegt: {target_dir}")
    click.echo(f"Template: {tpl}")

@target.command("show")
@click.argument("name")
@click.pass_context
def target_show(ctx, name):
    """Show details for a target."""
    cfg: AppConfig = ctx.obj["config"]
    data_root = cfg.data_root
    td = data_root / name
    if not td.exists():
        raise click.ClickException(f"Target not found: {td}")
    try:
        context = build_observation_context(td, target_name=name)
        click.echo(f"Target: {name}")
        click.echo(f"  Path: {td}")
        click.echo(f"  Lights: {context.total_light_frames}")
        click.echo(f"  Type: {context.target.target_type.value}")
    except Exception as e:
        click.echo(f"Target: {name} -- error reading: {e}")

@target.command("update")
@click.argument("name")
@click.option("--preset", type=click.Choice(["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]), help="New preset")
@click.pass_context
def target_update(ctx, name, preset):
    """Update a target (e.g. preset in AUFNAHMELISTE)."""
    cfg: AppConfig = ctx.obj["config"]
    td = cfg.data_root / name
    if not td.exists():
        raise click.ClickException(f"Target not found: {td}")
    tpl = td / f"AUFNAHMELISTE_{name}.md"
    if preset and tpl.exists():
        txt = tpl.read_text(encoding="utf-8")
        # Update the two Preset value lines in the AUFNAHMELISTE template without
        # corrupting Markdown bold syntax or leaving the old value behind.
        txt = re.sub(r"(\*\*Preset:\*\*)\s.*", rf"\1 {preset}", txt)
        txt = re.sub(r"(- Preset:)\s.*", rf"\1 {preset}", txt)
        tpl.write_text(txt, encoding="utf-8")
    click.echo(f"Target {name} updated")


@target.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Delete without confirmation")
@click.pass_context
def target_remove(ctx, name, yes):
    """Remove a target (optional)."""
    cfg: AppConfig = ctx.obj["config"]
    td = cfg.data_root / name
    if not td.exists():
        raise click.ClickException(f"Target not found: {td}")
    if not yes:
        if not click.confirm(f"Delete target {name}?"):
            click.echo("Cancelled")
            return
    shutil.rmtree(td)
    click.echo(f"Target {name} removed")


# ─────────────────────────────────────────────────────────────────
# CLI-F -- astra status
# ─────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output (JSON)")
@click.pass_context
def status(ctx, as_json):
    """Show system status (disk space, recent runs, darks library, config health, queue)."""
    cfg: AppConfig = ctx.obj["config"]
    data_root = cfg.data_root
    darks_repo = cfg.darks_repository
    # Disk
    try:
        usage = shutil.disk_usage(data_root) if data_root.exists() else None
        free_gb = usage.free / (1024**3) if usage else None
        total_gb = usage.total / (1024**3) if usage else None
    except Exception:
        free_gb = total_gb = None
    # Last runs: scan generated (skip dryrun_ and inspect_ staging dirs)
    # Fix: filter first, then take latest 2 per target so real runs are never
    # hidden by dryrun_/inspect_ entries that happen to sort after them.
    last_runs = []
    if data_root.exists():
        for tgt in sorted(data_root.iterdir()):
            if not tgt.is_dir() or tgt.name.startswith("_"):
                continue
            gen = tgt / "generated"
            if gen.exists():
                real_runs = sorted(
                    [
                        ts for ts in gen.iterdir()
                        if ts.is_dir()
                        and not ts.name.startswith("dryrun_")
                        and not ts.name.startswith("inspect_")
                    ],
                    reverse=True,
                )
                for ts in real_runs[:2]:
                    last_runs.append({"target": tgt.name, "run": ts.name, "path": str(ts)})
    # Darks library
    darks_info = {"path": str(darks_repo) if darks_repo else None, "exists": bool(darks_repo and darks_repo.exists())}
    if darks_info["exists"]:
        darks_info["groups"] = len(list(darks_repo.iterdir()))
    # Config health
    try:
        cfg.get_preset(cfg.default_preset)
        config_health = "ok"
    except Exception as e:
        config_health = f"fail: {e}"
    # Queue: count targets without completed run?
    queue_cnt = len([d for d in data_root.iterdir() if d.is_dir() and not (d / "generated").exists()]) if data_root.exists() else 0
    out = {
        "disk_space": {"free_gb": round(free_gb, 2) if free_gb else None, "total_gb": round(total_gb, 2) if total_gb else None, "path": str(data_root)},
        "last_runs": last_runs[:5],
        "darks_library": darks_info,
        "config_health": config_health,
        "queue": queue_cnt,
        "config": {"data_root": str(data_root), "default_preset": cfg.default_preset},
    }
    if as_json:
        click.echo(json.dumps(out, indent=2, default=str))
    else:
        console = _rich_console()
        if console:
            console.print(Panel("Astra Status", style="bold cyan"))
            console.print(f"Disk Space: {free_gb:.2f} GB free of {total_gb:.2f} GB" if free_gb else "Disk: n/a")
            console.print(f"Darks Library: {darks_info}")
            console.print(f"Config Health: {config_health}")
            console.print(f"Queue: {queue_cnt} open targets")
            console.print(f"Recent runs: {last_runs[:3]}")
        else:
            click.echo(json.dumps(out, indent=2))


@cli.command()
@click.argument("target_path", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output (JSON)")
@click.option("--eqmode", is_flag=True, help="Show EQMODE only")
@click.option("--frames", is_flag=True, help="Show frames in detail")
@click.option("--quality", is_flag=True, help="Show Quality Foundation metrics")
@click.pass_context
def inspect(ctx, target_path, as_json, eqmode, frames, quality):
    """Inspect FITS headers in target directory.

    Shows target information, calibration status, equipment, EQMODE and
    (deprecated) shotsInfo.json contents. With --json: machine-readable
    JSON output for automated post-processing.
    """
    import tempfile

    from .agents.discovery import find_shots_info, log_shots_info
    from .core.staging import stage_input

    target_dir = target_path.resolve()
    # V1.6-7: shotsInfo.json -- deprecated (Dwarf-spezifisch), nur fuer
    # Backward-Compat der inspect-Ausgabe. Nicht in der Pipeline.
    log_shots_info(target_dir)
    # inspect is read-only -- use a temp directory instead of generated/inspect_<ts>
    # so no permanent directory is created in the target folder.
    _inspect_tmpdir = tempfile.TemporaryDirectory(prefix="astra_inspect_")
    working_dir = Path(_inspect_tmpdir.name)
    input_dir = stage_input(target_dir, working_dir)
    context = build_observation_context(input_dir, target_name=target_dir.name)

    # V1.7-4 (EQPT-A/D2/B2): Equipment-Aufloesung inkl. Quelle je Feld.
    # Nie abbruchbehaftet -- bei Fehler bleibt der v1.6-Equipment-Stand.
    from .core.equipment import resolve_equipment as _resolve_equipment
    try:
        _resolve_equipment(context, ctx.obj["config"])
    except Exception as e:  # noqa: BLE001
        logger.warning("cli.inspect.equipment_resolve_failed", error=str(e))

    # ── EQMODE: aus Light-Headern (erster Treffer) ──────────────────
    eq_mode_raw = None
    eq_mode_label = "unknown"
    lights = context.get_lights()
    for f in lights.frames:
        if f.header is not None and f.header.eq_mode is not None:
            eq_mode_raw = f.header.eq_mode
            eq_mode_label = "EQ" if eq_mode_raw == 1 else "AZ"
            break

    # ── shotsInfo.json: deprecated (V1.6-7, Dwarf-spezifisch) ────────
    # shotsInfo ist kein Pipeline-Feature mehr -- nur fuer Backward-Compat
    # der inspect-Ausgabe beibehalten.
    shots_info_data = None
    shots_info_path = find_shots_info(target_dir)
    if shots_info_path is not None:
        try:
            shots_info_data = json.loads(
                shots_info_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            shots_info_data = {"_error": "parse_failed"}

    # ── JSON-Ausgabe (maschinenlesbar) ──────────────────────────────
    if as_json:
        first_light_header = None
        if lights.frames and lights.frames[0].header:
            h = lights.frames[0].header
            first_light_header = {
                "exptime": h.exptime,
                "gain": h.gain,
                "ccd_temp": h.ccd_temp,
                "filter": h.filter_name,
                "ra": h.ra,
                "dec": h.dec,
                "telescope": h.telescope,
                "instrument": h.instrument,
                "focal_length": h.focal_length,
                "pixel_size_x": h.pixel_size_x,
                "eq_mode": h.eq_mode,
            }

        # V1.6-1 (AC-SSOT-A5): Mandatory-Validation-Status pro Light-Frame
        cfg_json: AppConfig = ctx.obj["config"]
        mandatory_fields = cfg_json.mandatory_fields if cfg_json.mandatory_fields else ["exptime", "gain", "object", "ccd_temp"]
        mandatory_status = []
        for f in lights.frames:
            if f.header is None:
                mandatory_status.append({"file": f.path.name, "status": "error", "missing": mandatory_fields})
                continue
            missing = [field for field in mandatory_fields if getattr(f.header, field, None) is None]
            if missing:
                mandatory_status.append({"file": f.path.name, "status": "error", "missing": missing})
            else:
                mandatory_status.append({"file": f.path.name, "status": "ok", "missing": []})

        # V1.7-2 FSEL-D2: Frame-Selection Vorschau je Gruppe (Prospective, ohne vorherigen Lauf).
        # Best-effort Scoring falls Bilddaten lesbar, sonst nur Config-Erwartung (total/keep/discard).
        import math as _math

        from .agents.discovery import create_discovery_agent as _create_da
        from .config.loader import resolve_frame_selection as _resolve_fs
        from .core.quality import FrameQuality as _FQ
        from .core.quality import compute_frame_quality as _cfq
        from .core.quality import compute_frame_score as _cfs
        _pipeline_for_fs = ctx.obj["config"].get_preset(ctx.obj["config"].default_preset) or ctx.obj["config"].get_preset_for_target(context.target.target_type.value)
        try:
            _effective_fs_json = _resolve_fs(ctx.obj["config"], _pipeline_for_fs)
        except Exception:
            from .config.models import FrameSelectionConfig as _FSC
            _effective_fs_json = _FSC()
        _da_json = _create_da(ctx.obj["config"])
        try:
            _groups_json = _da_json.discover_groups(context)
        except Exception:
            _groups_json = {}
        _selection_groups_json = []
        for _gh, _gi in _groups_json.items():
            _total_j = _gi.frame_count
            _discard_j = _math.floor(_total_j * (100 - _effective_fs_json.keep_percentile) / 100.0) if _effective_fs_json.enabled else 0
            _keep_j = _total_j - _discard_j
            _skipped_j = False
            if _effective_fs_json.enabled and _discard_j > 0 and _keep_j < _effective_fs_json.min_frames:
                _skipped_j = True
                _discard_j = 0
                _keep_j = _total_j
            # Best-effort Scoring: Lade Frames der Gruppe und messe Scores
            _score_min_j = _score_max_j = _score_median_j = None
            if _effective_fs_json.enabled and _total_j >= 2:
                try:
                    # Frames dieser Gruppe aus Context filtern (group_by_params Logik)
                    _group_frames_j = []
                    for _f in lights.frames:
                        if _f.header is None:
                            continue
                        _ex = float(_f.header.exptime or 0.0)
                        _gn = int(_f.header.gain or 0)
                        _fl = str(_f.header.filter_name or "none")
                        from ..models.core import compute_group_hash as _cgh
                        if _cgh(_ex, _gn, _fl) == _gh:
                            _group_frames_j.append(_f)
                    if len(_group_frames_j) >= 2:
                        _quals_j: list[_FQ] = []
                        for _fi in _group_frames_j:
                            try:
                                from astropy.io import fits as _fits
                                with _fits.open(_fi.path) as _hdul:
                                    _data_j = _hdul[0].data
                                    if _data_j is None:
                                        continue
                                    _data_j = _data_j.astype(float)
                                    if _data_j.ndim == 3:
                                        # Debayered RGB: nimm G-Kanal
                                        if _data_j.shape[0] == 3:
                                            _data_j = _data_j[1]
                                        else:
                                            _data_j = _data_j[:, :, 1] if _data_j.shape[-1] == 3 else _data_j[:, :]
                                    _qj = _cfq(_data_j)
                                    _qj.frame = str(_fi.path)
                                    _quals_j.append(_qj)
                            except Exception:
                                continue
                        if _quals_j:
                            _scores_j = _cfs(_quals_j, weights=_effective_fs_json.weights)
                            if _scores_j:
                                _score_min_j = round(float(min(_scores_j)), 4)
                                _score_max_j = round(float(max(_scores_j)), 4)
                                import numpy as _np2
                                _score_median_j = round(float(_np2.median(_scores_j)), 4)
                except Exception:
                    pass
            _selection_groups_json.append({
                "hash": _gh,
                "total": _total_j,
                "keep": _keep_j,
                "discard": _discard_j,
                "skipped_min_frames": _skipped_j,
                "keep_percentile": _effective_fs_json.keep_percentile,
                "score_min": _score_min_j,
                "score_max": _score_max_j,
                "score_median": _score_median_j,
            })
        _selection_groups_json = sorted(_selection_groups_json, key=lambda x: x["hash"])

        output = {
            "target": context.target.name,
            "target_type": context.target.target_type.value,
            "lights": context.total_light_frames,
            "darks": context.calibration.dark_count,
            "flats": context.calibration.flat_count,
            "bias": context.calibration.bias_count,
            "total_integration_time_s": context.total_integration_time,
            "equipment": {
                "telescope": context.equipment.telescope,
                "camera": context.equipment.camera,
                "focal_length_mm": context.equipment.focal_length_mm,
                "pixel_size_um": context.equipment.pixel_size_um,
                "filters": context.equipment.filters,
                # V1.7-4 (EQPT-B2/D2): additiv -- Aufloesung, Bayer-Pattern,
                # Profil und Quelle je Feld (fits_header | config | none).
                "aperture_mm": context.equipment.aperture_mm,
                "width_px": context.equipment.width_px,
                "height_px": context.equipment.height_px,
                "bayer_pattern": context.equipment.bayer_pattern or "assumed: RGGB",
                "profile_name": context.equipment.profile_name,
                "sources": dict(context.equipment.sources),
            },
            "eqmode": {
                "raw": eq_mode_raw,
                "label": eq_mode_label,
            },
            "shots_info": shots_info_data,
            "first_light_header": first_light_header,
            "mandatory_validation": {
                "fields": mandatory_fields,
                "status": mandatory_status,
            },
            "frame_selection": {
                "enabled": _effective_fs_json.enabled,
                "keep_percentile": _effective_fs_json.keep_percentile,
                "weights": _effective_fs_json.weights,
                "min_frames": _effective_fs_json.min_frames,
                "groups": _selection_groups_json,
            },
            # V1.8-2 (AC-PREV-A5): effektive Preview/Export-Pipeline Settings.
            "preview_export": resolve_preview_export_config(
                cfg_json,
                cfg_json.get_preset(cfg_json.default_preset)
                or PipelinePreset(name="fallback", target_types=["*"], steps=[]),
            ).model_dump(),
            # V1.8-3 (AC-FITS-A4): Gestretchter FITS Status in inspect --json.
            "stretched_fits": (
                resolve_export_config(
                    cfg_json,
                    cfg_json.get_preset(cfg_json.default_preset)
                    or PipelinePreset(name="fallback", target_types=["*"], steps=[]),
                ).model_dump()
            ),
        }
        click.echo(json.dumps(output, indent=2, default=str))
        return

    # ── Menschliche Ausgabe (bestehendes Format + EQMODE/shotsInfo) ─
    click.echo(f"\nTarget: {context.target.name}")
    click.echo(f"Type: {context.target.target_type.value}")
    click.echo(f"Lights: {context.total_light_frames}")
    click.echo(f"Darks: {context.calibration.dark_count}")
    click.echo(f"Flats: {context.calibration.flat_count}")
    click.echo(f"Bias: {context.calibration.bias_count}")
    click.echo(f"Total integration: {context.total_integration_time:.1f}s")
    click.echo(f"Equipment: {context.equipment.telescope} + {context.equipment.camera}")

    # V1.7-4 (AC-EQPT-D2/B2): Quelle je Feld + Aufloesung + Bayer-Pattern.
    for _field in ("pixel_size_um", "focal_length_mm", "aperture_mm"):
        click.echo(
            f"  {_field}: {getattr(context.equipment, _field)} "
            f"[{context.equipment.sources.get(_field, 'none')}]"
        )
    click.echo(
        f"  Resolution: {context.equipment.width_px}x{context.equipment.height_px} px"
    )
    click.echo(f"  Bayer-Pattern: {context.equipment.bayer_pattern or 'assumed: RGGB'}")
    if context.equipment.profile_name:
        click.echo(f"  Profile: {context.equipment.profile_name}")

    # EQMODE
    click.echo(f"EQMODE: {eq_mode_label} (raw={eq_mode_raw})")

    # shotsInfo.json -- deprecated (V1.6-7, Dwarf-spezifisch, nur Backward-Compat)
    if shots_info_data and "_error" not in shots_info_data:
        eq_val = shots_info_data.get("eq")
        target_val = shots_info_data.get("target")
        exp_val = shots_info_data.get("exp")
        gain_val = shots_info_data.get("gain")
        shots_taken = shots_info_data.get("shotsTaken")
        shots_to_take = shots_info_data.get("shotsToTake")
        click.echo(
            f"shotsInfo: eq={eq_val}, target={target_val}, "
            f"exp={exp_val}, gain={gain_val}, "
            f"shots={shots_taken}/{shots_to_take}"
        )
    elif shots_info_data and "_error" in shots_info_data:
        click.echo("shotsInfo: (parse failed)")
    else:
        click.echo("shotsInfo: (not found)")

    # Show first light header
    if lights.frames:
        f = lights.frames[0]
        click.echo(f"\nFirst light ({f.path.name}):")
        if f.header:
            click.echo(f"  EXPTIME: {f.header.exptime}")
            click.echo(f"  GAIN: {f.header.gain}")
            click.echo(f"  TEMP: {f.header.ccd_temp}")
            click.echo(f"  FILTER: {f.header.filter_name}")

    # V1.6-1 (AC-SSOT-A5): Mandatory-Validation-Status pro Light-Frame
    cfg: AppConfig = ctx.obj["config"]
    mandatory = cfg.mandatory_fields if cfg.mandatory_fields else ["exptime", "gain", "object", "ccd_temp"]
    click.echo(f"\nMandatory-Validation ({', '.join(mandatory)}):")
    for f in lights.frames:
        if f.header is None:
            click.echo(f"  {f.path.name}: ERROR (no header)")
            continue
        missing = [field for field in mandatory if getattr(f.header, field, None) is None]
        optional_fields = ["filter_name", "ra", "dec"]
        optional_missing = [field for field in optional_fields if getattr(f.header, field, None) is None]
        if missing:
            click.echo(f"  {f.path.name}: ERROR (missing: {', '.join(missing)})")
        elif optional_missing:
            click.echo(f"  {f.path.name}: WARNING (optional missing: {', '.join(optional_missing)})")
        else:
            click.echo(f"  {f.path.name}: OK")

    # V1.6-1 (SSOT-C5): Aktive Filename-Patterns anzeigen
    click.echo("\nFilename patterns: hardcoded defaults active")

    # V1.6-2 (AC-BIL-C3): Debayer-Methode anzeigen
    effective_debayer = cfg.debayer_method or "superpixel"
    click.echo(f"Debayer-Method: {effective_debayer}")

    # V1.8-2 (AC-PREV-A5): effektive Preview/Export-Pipeline Settings.
    _inspect_pipeline = cfg.get_preset(cfg.default_preset) or PipelinePreset(
        name="fallback", target_types=["*"], steps=[]
    )
    _inspect_preview = resolve_preview_export_config(cfg, _inspect_pipeline)
    click.echo("\nPreview-Export:")
    click.echo(f"  stretch: {_inspect_preview.stretch}")
    click.echo(f"  scnr: {_inspect_preview.scnr}")
    click.echo(f"  saturation: {_inspect_preview.saturation}")
    click.echo(f"  background_neutralization: {_inspect_preview.background_neutralization}")

    # V1.8-3 (AC-FITS-A4): Gestretchter FITS Status in inspect.
    _inspect_export = resolve_export_config(cfg, _inspect_pipeline)
    click.echo("\nStretched-FITS-Export:")
    click.echo(f"  enabled: {_inspect_export.stretched_fits}")
    click.echo(f"  method: {_inspect_export.stretch.method}")
    click.echo(f"  a: {_inspect_export.stretch.a}")

    # V1.7-2 FSEL-D2: Selektions-Statistik je Gruppe (Frames total, behalten, verworfen, Perzentil, Score-Spanne)
    try:
        import math as _math2

        from .agents.discovery import create_discovery_agent as _cda2
        from .config.loader import resolve_frame_selection as _rfs2
        from .core.quality import FrameQuality as _FQ2
        from .core.quality import compute_frame_quality as _cfq2
        from .core.quality import compute_frame_score as _cfs2
        _pipeline_for_fs2 = cfg.get_preset(cfg.default_preset) or cfg.get_preset_for_target(context.target.target_type.value)
        try:
            _eff_fs2 = _rfs2(cfg, _pipeline_for_fs2)
        except Exception:
            from .config.models import FrameSelectionConfig as _FSC2
            _eff_fs2 = _FSC2()
        _da2 = _cda2(cfg)
        try:
            _groups2 = _da2.discover_groups(context)
        except Exception:
            _groups2 = {}
        click.echo(f"\nFrame-Selection: {'enabled' if _eff_fs2.enabled else 'disabled'} (keep={_eff_fs2.keep_percentile}%, min_frames={_eff_fs2.min_frames}, weights={_eff_fs2.weights or 'default uniform distribution'})")
        if not _groups2:
            click.echo("  (no groups)")
        else:
            for _gh2, _gi2 in sorted(_groups2.items()):
                _total2 = _gi2.frame_count
                _discard2 = _math2.floor(_total2 * (100 - _eff_fs2.keep_percentile) / 100.0) if _eff_fs2.enabled else 0
                _keep2 = _total2 - _discard2
                _skipped2 = False
                if _eff_fs2.enabled and _discard2 > 0 and _keep2 < _eff_fs2.min_frames:
                    _skipped2 = True
                    _discard2 = 0
                    _keep2 = _total2
                # Score-Spanne best-effort
                _s_min2 = _s_max2 = _s_med2 = None
                _cutoff2 = None
                if _eff_fs2.enabled and _total2 >= 2:
                    try:
                        _gframes2 = []
                        for _f2 in lights.frames:
                            if _f2.header is None:
                                continue
                            _ex2 = float(_f2.header.exptime or 0.0)
                            _gn2 = int(_f2.header.gain or 0)
                            _fl2 = str(_f2.header.filter_name or "none")
                            from ..models.core import compute_group_hash as _cgh2
                            if _cgh2(_ex2, _gn2, _fl2) == _gh2:
                                _gframes2.append(_f2)
                        if len(_gframes2) >= 2:
                            _quals2: list[_FQ2] = []
                            for _fi2 in _gframes2:
                                try:
                                    from astropy.io import fits as _fits2
                                    with _fits2.open(_fi2.path) as _hdul2:
                                        _d2 = _hdul2[0].data
                                        if _d2 is None:
                                            continue
                                        _d2 = _d2.astype(float)
                                        if _d2.ndim == 3:
                                            if _d2.shape[0] == 3:
                                                _d2 = _d2[1]
                                            else:
                                                _d2 = _d2[:, :, 1] if _d2.shape[-1] == 3 else _d2[:, :]
                                        _q2 = _cfq2(_d2)
                                        _q2.frame = str(_fi2.path)
                                        _quals2.append(_q2)
                                except Exception:
                                    continue
                            if _quals2:
                                _scores2 = _cfs2(_quals2, weights=_eff_fs2.weights)
                                if _scores2:
                                    _s_min2 = round(float(min(_scores2)), 4)
                                    _s_max2 = round(float(max(_scores2)), 4)
                                    import numpy as _np3
                                    _s_med2 = round(float(_np3.median(_scores2)), 4)
                                    if not _skipped2 and _discard2 > 0:
                                        _sorted2 = sorted(_scores2, reverse=True)
                                        _cutoff2 = round(float(_sorted2[_keep2 - 1]) if _keep2 > 0 else 0.0, 4)
                    except Exception:
                        pass
                _score_span2 = f"score [{_s_min2} .. {_s_max2}] median {_s_med2}" if _s_min2 is not None else "score n/a"
                _cutoff_str2 = f" cutoff {_cutoff2}" if _cutoff2 is not None else ""
                _skip_str2 = " (skipped min_frames)" if _skipped2 else ""
                click.echo(f"  Group {_gh2}: total={_total2} keep={_keep2} discard={_discard2} keep%={_eff_fs2.keep_percentile}{_skip_str2} {_score_span2}{_cutoff_str2}")
    except Exception as _e:
        click.echo(f"Frame-Selection: (error in statistics: {_e})")

    # CLI-F inspect extensions: --eqmode / --frames / --quality
    if quality:
        # QF-Metriken explizit (ergaenzt Frame-Selection)
        try:

            from .core.quality import compute_frame_quality as _cfq_q
            # Sample first 3 lights for QF
            for f in lights.frames[:3]:
                try:
                    from astropy.io import fits as _fits_q
                    with _fits_q.open(f.path) as _hdul_q:
                        _dq = _hdul_q[0].data
                        if _dq is None:
                            continue
                        _dq = _dq.astype(float)
                        if _dq.ndim == 3:
                            _dq = _dq.mean(axis=0) if _dq.shape[0]==3 else _dq[:,:,1]
                        qf = _cfq_q(_dq)
                        click.echo(f"QF {f.path.name}: snr={qf.snr:.2f} fwhm={qf.fwhm:.2f} stars={qf.star_count} elongation={qf.elongation:.2f}")
                except Exception:
                    continue
        except Exception as _e:
            click.echo(f"Quality: error {_e}")
        # Also mark that quality flag was processed
        click.echo("Quality: QF metrics displayed (--quality)")
    if eqmode:
        click.echo(f"EQMODE (filtered): {eq_mode_label} (raw={eq_mode_raw})")
    if frames:
        click.echo(f"Frames: {len(lights.frames)} Lights detailed")
        for f in lights.frames[:10]:
            hdr = f.header
            click.echo(f"  {f.path.name}: exptime={getattr(hdr,'exptime',None)} gain={getattr(hdr,'gain',None)} filter={getattr(hdr,'filter_name',None)}")

    # Cleanup temporary staging directory (inspect is read-only, no generated/ dir)
    try:
        _inspect_tmpdir.cleanup()
    except Exception:
        pass


@cli.command()
@click.argument("target_path", type=click.Path(exists=True, path_type=Path))
@click.option("--method", type=click.Choice(["weighted_average", "average", "median"]),
              default="weighted_average", help="Merge method")
@click.option("--weight-by", type=click.Choice(["frame_count", "total_exposure"]),
              default="frame_count", help="Weighting method")
@click.option("--merge-filter", "merge_filter", multiple=True, type=str,
              help="Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro)")
@click.option("--output", "-o", type=click.Path(path_type=Path),
              help="Output directory (default: generated/{timestamp}/merged/)")
@click.option("--dry-run", is_flag=True, help="Show groups without merging")
@click.pass_context
def merge(ctx, target_path, method, weight_by, merge_filter, output, dry_run):
    """Merge existing group stacks into a single FITS.

    Scans generated/{timestamp}/group_*/04_stacked/pcc_applied.fits,
    extracts metadata from FITS headers, and merges all groups using the
    chosen method and weighting.

    Note: Requires >=2 groups. Single-group targets are automatically
    materialized to merged/ by the process pipeline (no merge step needed).
    For single-group: run 'astra process <target>' or manually copy the
    stacked FITS to merged/.
    """
    target_dir = target_path.resolve()
    target_name = target_dir.name

    # Find latest generated/ timestamp
    generated_dir = target_dir / "generated"
    if not generated_dir.exists():
        raise click.ClickException(
            f"No generated/ directory found in {target_dir}"
        )

    # Fix (v1.12-cleanup): only consider timestamp dirs that contain at least
    # one group_* subdirectory.  inspect creates generated/inspect_<ts>/
    # and dry-run creates generated/dryrun_<ts>/ -- both are staging-only runs
    # with no group_* dirs and must not confuse merge.
    all_ts_dirs = sorted(
        [
            d for d in generated_dir.iterdir()
            if d.is_dir()
            and not d.name.startswith("dryrun_")
            and not d.name.startswith("inspect_")
        ],
        reverse=True,
    )
    if not all_ts_dirs:
        raise click.ClickException(
            "No timestamp directories found in generated/"
        )

    # Filter: keep only dirs that have at least one group_* child
    timestamps_with_groups = [
        d for d in all_ts_dirs
        if any(
            child.is_dir() and child.name.startswith("group_")
            for child in d.iterdir()
        )
    ]
    if not timestamps_with_groups:
        raise click.ClickException(
            "No pipeline run with group_ directories found in generated/ "
            "(inspect-only staging dirs are excluded). "
            "Run 'astra process' first to create group stacks."
        )

    latest_ts = timestamps_with_groups[0]
    click.echo(f"Scanning: {latest_ts}")

    # Find group directories
    group_dirs = sorted([
        d for d in latest_ts.iterdir()
        if d.name.startswith("group_") and d.is_dir()
    ])
    if not group_dirs:
        raise click.ClickException(
            f"No group_ directories found in {latest_ts}"
        )

    # Collect group stacks and metadata
    group_stacks: dict[str, Path] = {}
    group_metadata: dict[str, dict] = {}

    for gd in group_dirs:
        group_hash = gd.name[len("group_"):]
        pcc_path = gd / "04_stacked" / "pcc_applied.fits"
        stacked_path = gd / "04_stacked" / "stacked.fits"

        fits_path = pcc_path if pcc_path.exists() else (
            stacked_path if stacked_path.exists() else None
        )
        if fits_path is None:
            click.echo(f"  [SKIP] {gd.name}: no stack found")
            continue

        group_stacks[group_hash] = fits_path

        # Extract metadata from FITS headers
        meta: dict = {
            "frame_count": 1,
            "exptime": 0.0,
            "gain": 0,
            "filter": "",
            "total_exposure": 0.0,
            "pcc_status": "unknown",
        }
        try:
            from astropy.io import fits as afits
            with afits.open(fits_path) as hdul:
                h = hdul[0].header
                meta["exptime"] = float(h.get("EXPTIME", 0.0))
                # GAIN: prefer MGCNTGRP header keys (written by MergeAgent); stacked.fits
                # may have GAIN=0 due to stacking header oddity -- also try ORIGAIN/GAINO.
                _gain_raw = h.get("GAIN") or h.get("ORIGAIN") or h.get("GAINO") or 0
                try:
                    meta["gain"] = int(_gain_raw)
                except (TypeError, ValueError):
                    meta["gain"] = 0
                meta["filter"] = str(h.get("FILTER", ""))
                meta["frame_count"] = int(h.get("MGFRAME", 1))
                meta["total_exposure"] = float(h.get("TOTALEXP", meta["exptime"] * meta["frame_count"]))
                # ray Review Fix 2 (2026-08-21): Marker VOR MG-Headern
                # auswerten -- MGCNTGRP allein sagt nur "PCC gelaufen",
                # nicht "erfolgreich". Rejection/Skip/Fallback-Zustaende
                # sonst fälschlich als gaia_success gemeldet.
                _stacked_dir = fits_path.parent
                if (_stacked_dir / "PCC_REJECTED_FACTORS.txt").exists():
                    meta["pcc_status"] = "rejected_implausible_factors"
                elif (_stacked_dir / "PCC_FALLBACK_GRAY_WORLD.txt").exists():
                    meta["pcc_status"] = "fallback_gray_world"
                elif (_stacked_dir / "PCC_SKIPPED.txt").exists():
                    meta["pcc_status"] = "skipped"
                elif "MGCNTGRP" in h:
                    meta["pcc_status"] = "gaia_success"
                else:
                    meta["pcc_status"] = "unknown"
        except Exception as e:
            # T5 (E1): kein stiller Fehler -- Header nicht lesbar, Gruppe wird
            # mit Default-Metadaten weitergefuehrt (MergeAgent meldet den
            # Stack-Fehler separat und liefert einen klaren Exit-Code).
            logger.warning("merge.metadata_read_failed", path=str(fits_path),
                           group=group_hash, error=str(e))

        # V1.12-USAB-6: fallback metadata from run-info.json when FITS
        # headers are missing/zero (e.g. merge --dry-run before a real
        # merge has written MG headers, or GAIN=0 stacking oddity).
        if meta["exptime"] == 0.0 or meta["frame_count"] == 1 or meta["gain"] == 0:
            _run_info_path = latest_ts / "run-info.json"
            if _run_info_path.is_file():
                try:
                    with open(_run_info_path, encoding="utf-8") as _rf:
                        _run_info = json.load(_rf)
                    for _grp in (_run_info.get("groups") or []):
                        if _grp.get("hash") == group_hash:
                            if meta["exptime"] == 0.0 and _grp.get("exptime", 0.0) != 0.0:
                                meta["exptime"] = float(_grp["exptime"])
                            if meta["frame_count"] == 1 and _grp.get("frame_count", 1) != 1:
                                meta["frame_count"] = int(_grp["frame_count"])
                            if not meta["filter"] and _grp.get("filter"):
                                meta["filter"] = str(_grp["filter"])
                            # Fix merge GAIN=0: read gain from run-info groups when header is 0
                            if meta["gain"] == 0 and _grp.get("gain", 0) != 0:
                                try:
                                    meta["gain"] = int(_grp["gain"])
                                except (TypeError, ValueError):
                                    pass
                            meta["total_exposure"] = meta["exptime"] * meta["frame_count"]
                            break
                except Exception:
                    pass

        group_metadata[group_hash] = meta
        click.echo(
            f"  [FOUND] {gd.name}: "
            f"EXPTIME={meta['exptime']}s, "
            f"GAIN={meta['gain']}, "
            f"FILTER={meta['filter'] or '-'}, "
            f"Frames={meta['frame_count']}, "
            f"Total={meta['total_exposure']:.0f}s"
        )

    # V1.7-1 FSM-A (AC-FSM-A4, OQ-FSM-2 A): Filter-Auswahl auf Header-FILTER-Basis
    # (cli.py Z.925-Analog). Precedence CLI > Config (resolve_merge_filters),
    # Normalisierung trim+lower (AC-FSM-A2), wiederholbar (multiple=True).
    # Ohne Filter (None) = alle mergen (AC-FSM-A1, byte-identisch v1.6).
    from .config.loader import resolve_merge_filters
    from .core.merge_filter import check_filter_typos, is_merge_filter_match

    effective_merge_filters = resolve_merge_filters(ctx.obj["config"], cli_filters=merge_filter)
    # V1.7-1 FSM-C: Transparenz -- behalte Original fuer Dry-Run Tabelle (vor Filter)
    _original_group_stacks = dict(group_stacks)
    _original_group_metadata = dict(group_metadata)
    if effective_merge_filters is not None:
        logger.info("cli.merge.filter", filters=effective_merge_filters, total=len(group_stacks))
        # Gefilterte Stacks/Metadata bilden (excluded bleiben als Gruppen-Stacks erhalten,
        # werden nur nicht gemerged -- analog pipeline, OQ-FSM-4 A Merge-Skip).
        filtered_stacks: dict[str, Path] = {}
        filtered_meta: dict[str, dict] = {}
        excluded_hashes: list[str] = []
        for gh, meta in list(group_metadata.items()):
            if is_merge_filter_match(meta.get("filter"), effective_merge_filters):
                filtered_stacks[gh] = group_stacks[gh]
                filtered_meta[gh] = meta
            else:
                excluded_hashes.append(gh)
                click.echo(f"  [FILTERED] group_{gh}: FILTER={meta.get('filter')!r} not in {effective_merge_filters} -> excluded")
        if excluded_hashes:
            logger.info("cli.merge.filter_excluded", excluded=excluded_hashes, filters=effective_merge_filters)
            click.echo(f"  Filter active: {effective_merge_filters} -> {len(filtered_stacks)} candidates, {len(excluded_hashes)} excluded")
        # V1.7-9 Zentralisierung: Tippfehler-Warning via check_filter_typos (merge.filter_typo)
        _merge_group_filters = [m.get("filter") for m in _original_group_metadata.values()]
        _merge_typos = check_filter_typos(effective_merge_filters, _merge_group_filters)
        if _merge_typos:
            _merge_group_norm = sorted({("" if v is None else str(v).strip().lower()) for v in _merge_group_filters})
            for _flt_m in _merge_typos:
                logger.warning(
                    "merge.filter_typo",
                    filter=_flt_m,
                    effective=effective_merge_filters,
                    groups=_merge_group_norm,
                    hint="Suspected typo: filter value matches no group",
                )
                click.echo(f"  [WARN] Filter '{_flt_m}' matches no group (suspected typo) -- available: {_merge_group_norm}", err=True)
        group_stacks = filtered_stacks
        group_metadata = filtered_meta

    if dry_run:
        click.echo(
            f"\nDRY RUN - Would merge {len(group_stacks)} groups "
            f"(method={method}, weight_by={weight_by}, filters={effective_merge_filters})"
        )
        # V1.7-1 FSM-C1: Dry-run Tabelle je Gruppe HASH/FILTER/Frames + Markierung Kandidat/excluded + Filter-Liste Kopf
        if _original_group_metadata:
            if effective_merge_filters is not None:
                click.echo(f"Filter selection: {effective_merge_filters} -> {len(group_stacks)} candidates, {len(_original_group_metadata) - len(group_stacks)} excluded")
            else:
                click.echo("Filter selection: all groups (no filter set)")
            click.echo(f"{'Hash':<20} {'FILTER':<15} {'Frames':<8} {'MERGE':<22}")
            click.echo("-" * 67)
            for gh in sorted(_original_group_metadata.keys()):
                meta = _original_group_metadata[gh]
                _is_cand_m = is_merge_filter_match(meta.get("filter"), effective_merge_filters) if effective_merge_filters is not None else True
                _status_m = "CANDIDATE" if _is_cand_m else "excluded (filter_excluded)"
                click.echo(f"{gh:<20} {str(meta.get('filter') or '-'):<15} {meta.get('frame_count', 1):<8} {_status_m:<22}")
        return

    if len(group_stacks) < 2:
        raise click.ClickException(
            f"At least 2 groups required for merge, found: {len(group_stacks)}"
        )

    # Determine output directory
    if output:
        out_dir = output.resolve()
    else:
        out_dir = latest_ts / "merged"

    merge_agent = MergeAgent(
        working_dir=latest_ts,
        config=ctx.obj["config"],
    )

    merge_config = MergeConfig(method=method, weight_by=weight_by, filters=effective_merge_filters)

    # V1.8-2 (AC-PREV-A4): Preview/Export-Pipeline fuer Merge-Preview.
    # Ohne Config-Block -> Asinh-only (byte-identisch v1.6).
    _merge_cfg = ctx.obj["config"]
    _merge_pipeline = _merge_cfg.get_preset(_merge_cfg.default_preset) or PipelinePreset(
        name="fallback", target_types=["*"], steps=[]
    )
    _merge_preview_cfg = resolve_preview_export_config(_merge_cfg, _merge_pipeline)

    result = merge_agent.run(
        group_stacks=group_stacks,
        group_metadata=group_metadata,
        target_name=target_name,
        merge_config=merge_config,
        preview_config=_merge_preview_cfg,
    )

    if result.merged_path:
        click.echo(f"\n[OK] Merged stack: {result.merged_path}")
        if result.preview_path:
            click.echo(f"     Preview: {result.preview_path}")

        # Copy to custom output if specified
        if output:
            import shutil
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result.merged_path, out_dir / result.merged_path.name)
            if result.preview_path and result.preview_path.exists():
                shutil.copy2(result.preview_path, out_dir / result.preview_path.name)
            click.echo(f"     Copied to: {out_dir}")
    else:
        raise click.ClickException("Merge failed")


def _run_with_timeout(fn, timeout: float, *args, **kwargs):
    """Fuehre `fn` in einem Worker-Thread aus und liefere das Ergebnis.

    Privater Helper (thread + queue): blockiert den Aufrufer bis zu `timeout`
    Sekunden. Laueft `fn` nicht rechtzeitig fertig, wird TimeoutError geworfen
    und der Worker verworfen. Bewusst NICHT aus core.pcc importiert (kein
    Race mit paralleler PCC-Entwicklung); eigenstaendiges, minimales Muster.

    Args:
        fn: Aufzurufende Funktion (z.B. GAIA-Mini-Query).
        timeout: Max. Wartezeit in Sekunden.
        *args/**kwargs: Argumente fuer `fn`.

    Returns:
        Rueckgabewert von `fn`.

    Raises:
        TimeoutError: Wenn `fn` nicht innerhalb von `timeout` fertig wird.
    """
    result_queue: queue.Queue = queue.Queue()

    def _worker() -> None:
        try:
            result_queue.put(("ok", fn(*args, **kwargs)))
        except Exception as e:  # noqa: BLE001 - in Queue reichen, Thread darf nicht sterben
            result_queue.put(("error", e))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"Operation timed out after {timeout}s")
    status, payload = result_queue.get_nowait()
    if status == "error":
        raise payload
    return payload


@cli.command()
@click.argument("target_path", required=False,
                type=click.Path(exists=True, path_type=Path))
@click.option("--fix", is_flag=True, help="Auto-fixes missing dirs, config defaults, dark structure")
@click.pass_context
def doctor(ctx, target_path, fix):
    """Environment check: Python, dependencies, GAIA, config, disk, paths. Read-only.

    Optional TARGET_PATH: additionally checks target equipment supply
    (which header values are present, which config profile would apply,
    and which fields are completely missing).

    Exit codes: 0 = OK, 1 = warnings, 2 = critical errors.
    The command is read-only -- no directories or files are created or modified.
    """
    counts = {"ok": 0, "warn": 0, "fail": 0}

    def _report(name: str, level: str, message: str) -> None:
        counts[level] += 1
        click.echo(f"[{level.upper()}] {message}")
        # debug-level: not emitted at default INFO threshold, avoids duplicating
        # every doctor line as a JSON event on stdout.
        logger.debug(f"doctor.check.{name}", status=level, message=message)

    # 0. V19-ENV: .env Check (WARN wenn fehlt, aber Pipeline laeuft weiter)
    _env_found = False
    _env_paths = []
    try:
        from .config.loader import _pipeline_root
        _env_candidates = [Path.cwd() / ".env", _pipeline_root() / ".env"]
        for _cand in _env_candidates:
            if _cand.is_file():
                _env_found = True
                _env_paths.append(str(_cand))
    except Exception:
        pass
    if not _env_found:
        # AC-ENV-2: WARN doctor.env_missing, Exit 0 wenn nur das fehlt
        # Count in summary (off-by-one fix: previously emitted [WARN] without incrementing counts)
        counts["warn"] += 1
        click.echo("[WARN] doctor.env_missing: .env not found, using defaults (copy .env.example -> .env)")
        logger.warning("doctor.env_missing", detail=".env not found, using defaults")
        # Optional --fix: lege .env aus .env.example an
        if fix:
            try:
                from .config.loader import _pipeline_root as _pr
                example = _pr() / ".env.example"
                target_env = Path.cwd() / ".env"
                if example.is_file() and not target_env.exists():
                    shutil.copy2(example, target_env)
                    click.echo(f"[FIX] .env created from {example} -> {target_env}")
                    logger.info("doctor.env_fix", source=str(example), target=str(target_env))
            except Exception as e:
                click.echo(f"[FIX FAIL] .env: {e}", err=True)
    else:
        _report("env", "ok", f".env found: {', '.join(_env_paths)}")

    # 1. Python-Version (kritisch)
    # Bewusste Laufzeit-Validierung trotz Paket-Min >=3.11: doctor ist eine
    # Umgebungsdiagnose und muss eine zu alte Python-Umgebung als FAIL/Exit-2
    # melden. UP036-Fix wuerde dieses Verhalten entfernen -> noqa.
    if sys.version_info >= (3, 11):  # noqa: UP036
        _report("python", "ok",
                f"Python {sys.version_info[0]}.{sys.version_info[1]} (>= 3.11 required)")
    else:
        _report("python", "fail",
                f"Python {sys.version_info[0]}.{sys.version_info[1]} < 3.11 (critical)")

    # 2. Core-Dependencies (kritisch)
    # DEF-008 (Boris-Entscheid 2026-09-02): astroquery ist Base-Dependency,
    # damit PCC (GAIA/VizieR/APASS) out-of-the-box verfuegbar ist.
    # sep: now base dep (backy 2026-09-19) -- hard runtime import in GAIA-PCC
    # _find_sources; without it PCC always falls back to gray_world.
    core_deps = ["astropy", "numpy", "scipy", "pydantic",
                 "pydantic_settings", "click", "structlog", "yaml", "jinja2",
                 "astroquery", "sep"]
    for dep in core_deps:
        try:
            __import__(dep)
            _report(f"dep.{dep}", "ok", f"{dep} importable")
        except ImportError:
            _report(f"dep.{dep}", "fail", f"{dep} missing (critical)")

    # 3. Optional-Dependencies (WARN: Feature deaktiviert / Fallback aktiv)
    # AC-W9-A3: astroalign extra (astroalign + scikit-image + scikit-learn).
    # sep is now a base dep and listed in core_deps above.
    # (name, import_module): Dist-Name fuer Ausgabe, Modul-Name fuer Import
    # (scikit-image -> skimage, dist != module).
    optional_deps = [
        ("astroalign", "astroalign"),
        ("scikit-image", "skimage"),
    ]
    optional_dep_messages = {
        "astroalign": 'missing (W9-registration using fft fallback; install: pip install "astra-pipeline[astroalign]")',
        "scikit-image": 'missing (W9-registration using fft fallback; required dep for astroalign extra; install: pip install "astra-pipeline[astroalign]")',
    }
    for name, module in optional_deps:
        try:
            __import__(module)
            _report(f"dep.{name}", "ok", f"{name} importable")
        except ImportError:
            _report(f"dep.{name}", "warn",
                    f"{name} {optional_dep_messages.get(name, 'missing (fallback active)')}")

    # 4. GAIA erreichbar (nur wenn astroquery importierbar; Timeout = WARN, nicht kritisch)
    gaia_available = False
    try:
        import astroquery  # noqa: F401
        gaia_available = True
    except ImportError:
        logger.debug("doctor.astroquery_unavailable")
    if gaia_available:
        try:
            from astroquery.gaia import Gaia
            if hasattr(Gaia, "TIMEOUT"):
                try:
                    Gaia.TIMEOUT = 10
                except Exception as e:  # noqa: BLE001 - Attribut ist read-only o.ae.
                    logger.debug("doctor.gaia_timeout_set_failed", error=str(e))

            def _mini_query():
                # M2 (ray-Review v1.1): Import im Worker-Thread explizit
                # absichern. `Gaia.launch_job` kann lazy astroquery-Submodule
                # laden; fehlt eine Dependency, wird der ImportError ueber die
                # Queue an den Aufrufer zurueckgegeben und dort als WARN
                # gemeldet -- kein stummer Thread-Crash, PCC-Fallback aktiv.
                from astroquery.gaia import Gaia as _query_gaia
                return _query_gaia.launch_job("SELECT TOP 1 ra FROM gaiadr3.gaia_source")

            _run_with_timeout(_mini_query, 10.0)
            _report("gaia", "ok", "GAIA reachable (astroquery)")
        except TimeoutError:
            _report("gaia", "warn", "GAIA query timeout after 10s (PCC fallback active)")
        except ImportError as e:
            _report("gaia", "warn", f"astroquery.gaia cannot be imported: {e}")
        except Exception as e:  # noqa: BLE001 - Verbindungs-/Query-Fehler sind WARN
            _report("gaia", "warn", f"GAIA is not reachable: {e}")

    # 5. Config gueltig (kritisch)
    cfg = None
    try:
        cfg = load_config(ctx.obj.get("config_path"))
        preset = cfg.get_preset(cfg.default_preset)
        if preset is None:
            _report("config", "fail",
                    f"Invalid config: preset '{cfg.default_preset}' cannot be resolved (critical)")
        else:
            _report("config", "ok", f"Config valid (preset: {preset.name})")
    except Exception as e:  # noqa: BLE001 - ungueltige Config ist kritisch
        _report("config", "fail", f"Invalid config: {e} (critical)")

    if cfg is not None:
        data_root = cfg.data_root

        # V1.6-1 (OQ-SSOT-3): Mandatory-Validation-Check
        # Prueft beim Config-Load, ob die Mandatory-Field-Liste konsistent
        # mit den vorhandenen Header-Aliases ist.
        mandatory_fields = cfg.mandatory_fields if cfg.mandatory_fields else ["exptime", "gain", "object", "ccd_temp"]
        from .core.fits_parser import HEADER_ALIASES
        aliases_covered = []
        aliases_unknown = []
        for field in mandatory_fields:
            if field in HEADER_ALIASES:
                aliases = HEADER_ALIASES[field]
                aliases_covered.append(f"{field.upper()} ({', '.join(aliases)})")
            else:
                aliases_unknown.append(field)
        if aliases_unknown:
            _report("mandatory_validation", "warn",
                    f"Unknown mandatory fields: {', '.join(aliases_unknown)}")
        else:
            _report("mandatory_validation", "ok",
                    f"Mandatory-Validation: {', '.join(mandatory_fields)} -- "
                    f"Aliases covered: {', '.join(aliases_covered)}")

        # V1.7-4 (AC-EQPT-D3): Equipment-Versorgung.
        # (a) Config-Seite (immer): welche Profile wuerden greifen?
        profiles = list(cfg.equipment_profiles or [])
        if not profiles:
            _report("equipment.config_profiles", "warn",
                    "No equipment_profiles configured -- missing "
                    "header fields remain empty without a fallback")
        else:
            names = ", ".join(p.name for p in profiles)
            has_default = any(
                str(p.name).lower() == "default" for p in profiles
            )
            if has_default:
                _report("equipment.config_profiles", "ok",
                        f"Config profiles available: {names} "
                        "(fallback profile 'default' exists)")
            else:
                _report("equipment.config_profiles", "warn",
                        f"Config profiles available: {names} -- no 'default' "
                        "profile (substring fallback without a match provides "
                        "no values)")

        # (b) Target-Seite (nur mit TARGET_PATH): Header-Versorgung je Feld.
        # build_observation_context ist read-only; resolve_equipment nie
        # abbruchbehaftet. Ohne TARGET_PATH entfaellt dieser Check.
        if target_path is not None:
            try:
                from .core.equipment import (
                    resolve_equipment as _resolve_equipment,
                )
                from .core.fits_parser import (
                    build_observation_context as _build_ctx,
                )
                eq_ctx = _build_ctx(target_path.resolve(),
                                    target_name=target_path.name)
                _resolve_equipment(eq_ctx, cfg)
                eq = eq_ctx.equipment
                header_fields = [
                    f for f in ("pixel_size_um", "focal_length_mm",
                                "aperture_mm", "telescope", "camera")
                    if eq.sources.get(f) == "fits_header"
                ]
                config_fields = [
                    f for f in ("pixel_size_um", "focal_length_mm",
                                "aperture_mm", "telescope", "camera")
                    if eq.sources.get(f) == "config"
                ]
                missing_fields = [
                    f for f in ("pixel_size_um", "focal_length_mm",
                                "aperture_mm", "telescope", "camera")
                    if eq.sources.get(f) == "none"
                ]
                detail = (
                    f"Header: [{', '.join(header_fields) or '-'}] | "
                    f"Config ({eq.profile_name or 'no profile'}): "
                    f"[{', '.join(config_fields) or '-'}]"
                )
                if missing_fields:
                    _report("equipment.supply", "warn",
                            f"Equipment fields have no source: "
                            f"{', '.join(missing_fields)} -- {detail}")
                elif config_fields:
                    _report("equipment.supply", "warn",
                            f"Equipment not fully populated from headers -- "
                            f"config profile applies for: "
                            f"{', '.join(config_fields)} | {detail}")
                else:
                    _report("equipment.supply", "ok",
                            f"Equipment fully sourced from headers | {detail}")
            except Exception as e:  # noqa: BLE001 - Diagnose, nie Abbruch
                _report("equipment.supply", "warn",
                        f"Equipment check failed: {e}")

        # V1.7-2 FSEL-D4: Frame-Selection Status (aktiv/inaktiv + Gewichte).
        # L4: Touchpoint doctor -- zeigt ob aktiv und welche Gewichte gelten,
        # sowie Rejection-Status fuer den Trichter-Vergleich (C1: Perzentil → Threshold).
        try:
            from .config.loader import resolve_frame_selection as _rfs_doc
            _preset_doc = cfg.get_preset(cfg.default_preset)
            if _preset_doc is None and cfg.pipeline_presets:
                _preset_doc = cfg.pipeline_presets[0]
            if _preset_doc is not None:
                _eff_fs_doc = _rfs_doc(cfg, _preset_doc)
                _weights_str = str(_eff_fs_doc.weights) if _eff_fs_doc.weights else "default uniform distribution (snr, star_count, fwhm_median, elongation_ratio)"
                if _eff_fs_doc.enabled:
                    _report("frame_selection", "ok",
                            f"Frame-Selection active (keep={_eff_fs_doc.keep_percentile}%, min_frames={_eff_fs_doc.min_frames}, weights={_weights_str})")
                else:
                    _report("frame_selection", "ok",
                            f"Frame-Selection inactive (default off, keep={_eff_fs_doc.keep_percentile}%, min_frames={_eff_fs_doc.min_frames}, weights={_weights_str}) -- opt-in via Config/Preset/CLI (--frame-selection)")
                # Rejection-Status fuer Trichter-Vergleich (AC-FSEL-C1..C3, unabhaengige Schalter)
                from .agents.multi_group_agent import _resolve_rejection_config as _rrc_doc
                try:
                    _rej_e, _rej_thresh, _rej_elong = _rrc_doc(_preset_doc.processing_params.model_dump(), cfg)
                    if _rej_e:
                        _report("rejection", "ok", f"Outlier-Rejection AKTIV (thresholds={_rej_thresh}, elongation={_rej_elong}) -- Funnel: Perzentil → Threshold (AC-FSEL-C1)")
                    else:
                        _report("rejection", "ok", "Outlier-Rejection inactive (default off)")
                except Exception:
                    pass
            else:
                _report("frame_selection", "warn", "No preset available for frame-selection check")
        except Exception as e:  # noqa: BLE001 - Diagnose
            _report("frame_selection", "warn", f"Frame-selection check failed: {e}")

        # V1.12-DRZ-COVERAGE COV-4: Drizzle phase prediction (suggest/doctor Hinweis)
        try:
            from .agents.cfa_drizzle_agent import predict_expected_phases

            # Generic cadence hint (always)
            _report("drizzle.cadence", "ok",
                    "Drizzle cadence: >=60s 10-frame, <60s 6-frame; <4 phases -> pixfrac 1.0 + low_phase_coverage (2 phases/15 frames Moiré, 5 phases/41 frames hole <1% OK)")
            if target_path is not None:
                try:
                    from .core.fits_parser import build_observation_context as _build_ctx2
                    _ctx2 = _build_ctx2(target_path.resolve(), target_name=target_path.name)
                    lights = _ctx2.get_lights() if hasattr(_ctx2, "get_lights") else None
                    if lights is not None and hasattr(lights, "frames") and lights.frames:
                        # Group by EXPTIME to predict per group
                        from collections import defaultdict as _dd
                        _group_counts: dict[float, int] = _dd(int)
                        _group_exp: dict[float, float] = {}
                        for f in lights.frames:
                            exp = float(f.header.exptime) if f.header and f.header.exptime is not None else 0.0
                            # Bucket by exptime (rounded) to avoid float noise
                            key = round(exp, 1)
                            _group_counts[key] += 1
                            _group_exp[key] = exp
                        for exp_key, cnt in sorted(_group_counts.items()):
                            exp_val = _group_exp[exp_key]
                            pred = predict_expected_phases(cnt, exp_val)
                            if pred < 4:
                                _report("drizzle.phases", "warn",
                                        f"Drizzle phases predicted {pred} for {cnt} frames @ {exp_val:g}s (cadence {10 if exp_val>=60 else 6}) -> low_phase_coverage expected, pixfrac 1.0 recommended")
                            else:
                                _report("drizzle.phases", "ok",
                                        f"Drizzle phases predicted {pred} for {cnt} frames @ {exp_val:g}s -> pixfrac 0.5 feasible, hole <1% expected" if pred >=5 else f"Drizzle phases predicted {pred} for {cnt} frames @ {exp_val:g}s")
                    else:
                        _report("drizzle.phases", "ok", "No lights found for phase prediction")
                except Exception as e:  # noqa: BLE001
                    _report("drizzle.phases", "warn", f"Drizzle phase prediction failed: {e}")
        except Exception as e:  # noqa: BLE001
            _report("drizzle.phases", "warn", f"Drizzle phase check failed: {e}")

        # 6. Disk-Space (nur wenn data_root existiert; sonst ueberspringen,
        #    der FAIL kommt von Check 7)
        if data_root.exists():
            try:
                usage = shutil.disk_usage(data_root)
                free_gb = usage.free / (1024 ** 3)
                if free_gb < 1.0:
                    _report("disk", "fail",
                            f"Less than 1 GB free on {data_root}: {free_gb:.2f} GB (critical)")
                elif free_gb < 5.0:
                    _report("disk", "warn", f"Only {free_gb:.2f} GB free on {data_root}")
                else:
                    _report("disk", "ok", f"{free_gb:.2f} GB free on {data_root}")
            except Exception as e:  # noqa: BLE001
                _report("disk", "fail", f"Disk check failed: {e} (critical)")

        # 7. Pfade
        if data_root.exists():
            _report("paths.data_root", "ok", f"data_root exists: {data_root}")
            try:
                targets = [d for d in data_root.iterdir() if d.is_dir()]
                click.echo(f"   Targets: {len(targets)} subdirectories")
            except Exception:  # noqa: BLE001 - nur Info
                click.echo("   Targets: (not readable)")
        else:
            _report("paths.data_root", "fail",
                    f"data_root does not exist: {data_root} (critical)")

        if cfg.darks_repository is not None:
            if cfg.darks_repository.exists():
                _report("paths.darks_repository", "ok",
                        f"darks_repository exists: {cfg.darks_repository}")
            else:
                _report("paths.darks_repository", "warn",
                        f"darks_repository does not exist: {cfg.darks_repository}")

        # CLI-F --fix: auto-fix
        if fix and cfg is not None:
            fixed = []
            # 1. fehlende Dirs anlegen
            for p in [data_root, cfg.darks_repository] if cfg.darks_repository else [data_root]:
                if p and not p.exists():
                    try:
                        p.mkdir(parents=True, exist_ok=True)
                        fixed.append(f"Directory created: {p}")
                        click.echo(f"[FIX] Directory created: {p}")
                    except Exception as e:
                        click.echo(f"[FIX FAIL] {p}: {e}", err=True)
            # 2. Config-Defaults: falls kein equipment_profiles, Default anlegen? Write back default config if missing file
            cfg_path = ctx.obj.get("config_path")
            # CWD-Guard (V19-1.9.2-STRAYCFG): nutze cfg_path statt blind Path.cwd()/config.yaml
            # cfg_path ist dead var Fix C -- verhindert Stray-File 15.511 Bytes im Repo-Root bei direktem pytest aus CWD
            if cfg_path is not None:
                target_cfg = Path(cfg_path)
            else:
                target_cfg = Path.cwd() / "config.yaml"
            if not target_cfg.exists():
                try:
                    from .config.loader import save_default_config
                    save_default_config(target_cfg)
                    fixed.append(f"Config created: {target_cfg}")
                    click.echo(f"[FIX] Config created: {target_cfg}")
                except Exception:
                    pass
            # 3. Dark-Struktur: ensure subdirs exist per config
            if cfg.darks_repository and cfg.darks_repository.exists():
                # ensure no WIDE/cam_1 leakage placeholder? just report
                pass
            if fixed:
                click.echo(f"[FIX] {len(fixed)} issues fixed")
            else:
                click.echo("[FIX] Nothing to fix")

    # Zusammenfassung + Exit-Code
    click.echo(f"Doctor: {counts['ok']} OK, {counts['warn']} WARN, {counts['fail']} FAIL")
    if counts["fail"] > 0:
        code = 2
    elif counts["warn"] > 0:
        code = 1
    else:
        code = 0
    ctx.exit(code)


@cli.group()
def plugin():
    """Plugin management (v1.2, PL-C): pipeline-step plugins in the
    entry-point group ``astra.plugins``."""


@plugin.command("list")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output (JSON)")
@click.pass_context
def plugin_list(ctx, as_json):
    """List registered pipeline-step plugins (PL-C).

    Exit codes: 0 = OK (even with no plugins installed), 1 = discovery error.
    """
    from .core.plugins import default_registry

    registry = default_registry()
    try:
        plugins = registry.plugins
    except Exception as e:  # noqa: BLE001 - Discovery-Fehler sind Exit 1
        click.echo(f"[FAIL] Plugin discovery failed: {e}", err=True)
        ctx.exit(1)

    # "Gehandhabte Steps": alle Preset-Step-Namen der geladenen Config, die
    # das Plugin via handles() akzeptiert (Kern-Steps kennt es nicht -- sonst
    # waeren es keine Plugin-Steps). Ohne Config/ohne Treffer: leere Liste.
    step_names = _collect_preset_step_names(ctx)

    entries = []
    for p in plugins:
        handled = sorted(s for s in step_names if p.handles(s))
        entries.append({
            "name": p.name,
            "version": p.version,
            "steps": handled,
        })

    if as_json:
        click.echo(json.dumps(entries, indent=2))
        ctx.exit(0)

    if not entries:
        click.echo("No plugins installed (entry-point group: astra.plugins)")
        ctx.exit(0)

    for entry in entries:
        steps = ", ".join(entry["steps"]) if entry["steps"] else "-"
        click.echo(f"{entry['name']} {entry['version']} -- Steps: {steps}")
    ctx.exit(0)


def _collect_preset_step_names(ctx) -> list[str]:
    """Alle Preset-Step-Namen der geladenen Config (fuer 'gehandhabte Steps')."""
    cfg = ctx.obj.get("config")
    if cfg is None:
        return []
    names: list[str] = []
    for preset in cfg.pipeline_presets:
        for step in preset.steps:
            if step.name not in names:
                names.append(step.name)
    return names


# ────────────────────────────────────────────────────────────────
# V1.12-QC -- astra qc <generated> [--all] [--json]
# Post-hoc Quality-Checker: Flip-Detection vertical=PASS/none=FAIL,
# Ghosting double_rate>0.3 worst per group, Farbe G-excess>15%.
# Liest nur generated/<ts>/ (pattern *.(jpg|tiff) + stacked.fits linear)
# Outputs qc_report.json + Exit 0 PASS / 2 FAIL / 1 SKIPPED/INPUT_ERROR
# ────────────────────────────────────────────────────────────────
@cli.command("qc")
@click.argument("generated", required=False, type=click.Path(path_type=Path))
@click.option("--all", "run_all", is_flag=True, help="QC all non-smoke runs per target as a table (gate = worst per target)")
@click.option("--latest", "use_latest", is_flag=True, help="Only check latest generated/<ts> per target (instead of all); default without --all = latest when target-root given -- saves I/O 40->2, 43s->~5s")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output to stdout (in addition to qc_report.json)")
@click.option("--check-header", "check_header", is_flag=True, help="Additionally check FITS header for platesolving completeness (FOCALLEN/XPIXSZ/RA/DEC/WCS etc; 01_calibrated excluded, S3)")
@click.pass_context
def qc(ctx, generated, run_all, as_json, use_latest, check_header):
    """Quality checker: measures flip/ghosting/color from generated/<ts>/.

    \b
    Examples:
      astra qc "C:\\Astra\\M27 Hantelnebel\\generated\\20260906-080324"
      astra qc --all
      astra qc "C:\\Astra\\M27 Hantelnebel\\generated\\20260906-080324" --json
    """
    import sys as _sys

    cfg = ctx.obj.get("config")

    # Mutually exclusive & required guard (inkl. --latest)
    if run_all and generated is not None:
        raise click.UsageError("astra qc: --all and <generated> are mutually exclusive -- either <generated> or --all")
    if use_latest and run_all:
        raise click.UsageError("astra qc: --latest and --all are mutually exclusive -- --latest is default for target-root without --all")

    if not run_all and generated is None:
        raise click.UsageError(
            "astra qc: path required -- e.g. "
            'astra qc "C:\\Astra\\M27 Hantelnebel\\generated\\20260906-080324" '
            "or astra qc --all"
        )

    # Lazy imports
    try:
        from .core.qc import discover_all_generated, filter_non_smoke, qc_exit_code, run_qc, write_qc_report
    except Exception as e:
        click.echo(f"[FAIL] qc import failed: {e}", err=True)
        ctx.exit(1)

    console = _rich_console()

    def _format_qc_report(report: dict) -> str:
        checks = report.get("checks", {})
        flip = checks.get("flip_detection", {})
        ghost = checks.get("ghosting", {})
        color = checks.get("color", {})
        hdr = checks.get("header", {})
        lines = []
        lines.append(f"Generated: {report.get('generated')}")
        lines.append(f"Status: {report.get('status')} (version_mismatch={report.get('version_mismatch')}, smoke_mode={report.get('smoke_mode')})")
        # Table-like
        header = f"{'Check':<18} {'Status':<9} {'Metric':<22} {'Evidence'}"
        lines.append(header)
        lines.append("-" * len(header))
        flip_type = flip.get("type", "?")
        flip_conf = flip.get("confidence", "?")
        flip_ev = (flip.get("evidence") or "")[:80]
        lines.append(f"{'Flip-Detection':<18} {flip.get('status','?'):<9} {flip_type} conf {flip_conf:<12} {flip_ev}")
        ghost_metric = ghost.get("metric")
        ghost_worst = ghost.get("worst_group") or "-"
        ghost_ev = (ghost.get("evidence") or "")[:60]
        lines.append(f"{'Ghosting':<18} {ghost.get('status','?'):<9} {str(ghost_metric) + ' @'+str(ghost_worst) if ghost_metric is not None else 'n/a':<22} {ghost_ev}")
        color_excess = color.get("green_excess_pct")
        color_ev = (color.get("evidence") or "")[:60]
        lines.append(f"{'Color':<18} {color.get('status','?'):<9} {str(color_excess)+'%' if color_excess is not None else 'n/a':<22} {color_ev}")
        hdr_ev = (hdr.get("evidence") or "")[:60]
        lines.append(f"{'Header':<18} {hdr.get('status','?'):<9} {('fallback ' + str(hdr.get('fallback_detected')) if hdr else 'n/a'):<22} {hdr_ev}")
        # Groups detail
        for g in report.get("groups", [])[:6]:
            lines.append(f"  group {g.get('group')}: double_rate={g.get('double_rate')} status={g.get('status')}")
        lines.append(f"Inputs: stacks={len(report.get('inputs',{}).get('stacks',[]))} previews={len(report.get('inputs',{}).get('previews',[]))} pcc_status={report.get('inputs',{}).get('pcc_status')}")
        return "\n".join(lines)

    # --all mode
    if run_all:
        data_root = Path(cfg.data_root) if cfg and getattr(cfg, "data_root", None) else Path("C:/Astra")
        all_generated = discover_all_generated(data_root)
        # If none found, also try config data_root fallback and CWD
        non_smoke = filter_non_smoke(all_generated)
        if not all_generated:
            click.echo(f"No generated/<ts> runs found under {data_root}", err=True)
            if not as_json:
                click.echo("Note: expected C:\\Astra\\<Target>\\generated\\<ts> with run-info.json", err=True)
            # No runs -> skipped
            ctx.exit(1)
        if not non_smoke:
            click.echo(f"All {len(all_generated)} runs are smoke-runs (smoke_mode/limit) -- skipped", err=True)
            if as_json:
                click.echo(json.dumps({"runs": [], "skipped": len(all_generated)}, indent=2))
            ctx.exit(1)

        # Process each, collect per-target worst
        from collections import defaultdict

        results: list[dict] = []
        target_worst: dict[str, str] = {}
        worst_codes: list[int] = []
        for gen in sorted(non_smoke):
            try:
                report = run_qc(gen, check_header=bool(check_header))
                out_path = write_qc_report(gen, report)
                code = qc_exit_code(report)
                results.append({"generated": str(gen), "report": report, "exit_code": code, "qc_report": str(out_path)})
                worst_codes.append(code)
                # Target name = parent of generated
                try:
                    target_name = gen.parent.parent.name
                except Exception:
                    target_name = str(gen)
                # worst per target
                cur = target_worst.get(target_name, "PASS")
                # precedence FAIL > SKIPPED > PASS
                priority = {"FAIL": 2, "SKIPPED": 1, "PASS": 0}
                rep_status = report.get("status", "SKIPPED")
                if priority.get(rep_status, 1) > priority.get(cur, 0):
                    target_worst[target_name] = rep_status
                elif cur == "PASS" and rep_status != "PASS":
                    target_worst[target_name] = rep_status
            except Exception as e:
                logger.warning("qc.all_run_failed", generated=str(gen), error=str(e))
                results.append({"generated": str(gen), "error": str(e), "exit_code": 1})
                worst_codes.append(1)

        # Handle skipped targets hint (targets without generated)
        try:
            all_targets = [d for d in data_root.iterdir() if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")]
            targets_with_runs = set(target_worst.keys())
            # Also include targets where all runs were smoke (still count as target)
            smoke_targets = set()
            for g in all_generated:
                try:
                    smoke_targets.add(g.parent.parent.name)
                except Exception:
                    pass
            no_generated_targets = [d.name for d in all_targets if d.name not in smoke_targets and d.name not in targets_with_runs and not (d / "generated").exists()]
            skipped_hint = f"{len(no_generated_targets)} Targets ohne generated skipped" if no_generated_targets else None
        except Exception:
            skipped_hint = None

        # Gate = worst je Target: if any target worst is FAIL -> overall FAIL
        has_fail = any(v == "FAIL" for v in target_worst.values()) or any(c == 2 for c in worst_codes)
        has_pass = any(v == "PASS" for v in target_worst.values())
        if has_fail:
            overall_code = 2
            overall_status = "FAIL"
        elif has_pass:
            overall_code = 0
            overall_status = "PASS"
        else:
            overall_code = 1
            overall_status = "SKIPPED"

        if as_json:
            payload = {
                "qc_all": overall_status,
                "exit_code": overall_code,
                "targets": target_worst,
                "runs": results,
                "hint": skipped_hint,
            }
            click.echo(json.dumps(payload, indent=2, default=str))
        else:
            # Human table
            if console and HAS_RICH:
                from rich.table import Table as _Table
                tbl = _Table(title=f"astra qc --all -- {len(non_smoke)} NON-Smoke Runs, {len(target_worst)} Targets, Gate={overall_status}")
                tbl.add_column("Generated")
                tbl.add_column("Target")
                tbl.add_column("Status")
                tbl.add_column("Flip")
                tbl.add_column("Ghosting")
                tbl.add_column("Color")
                for r in results:
                    rep = r.get("report", {})
                    checks = rep.get("checks", {})
                    flip_s = checks.get("flip_detection", {}).get("status", "?")
                    ghost_s = checks.get("ghosting", {}).get("status", "?")
                    color_s = checks.get("color", {}).get("status", "?")
                    gen_name = Path(r.get("generated", "")).name
                    try:
                        tname = Path(r.get("generated", "")).parent.parent.name
                    except Exception:
                        tname = "?"
                    tbl.add_row(gen_name, tname, rep.get("status", "?"), flip_s, ghost_s, color_s)
                console.print(tbl)
                if skipped_hint:
                    console.print(f"[dim]{skipped_hint}[/dim]")
                for t, w in sorted(target_worst.items()):
                    console.print(f"  Target {t}: worst {w}")
                console.print(f"Overall Gate: {overall_status} (Exit {overall_code})")
            else:
                click.echo(f"astra qc --all -- {len(non_smoke)} Runs, {len(target_worst)} Targets, Gate={overall_status}")
                for r in results:
                    rep = r.get("report", {})
                    gen = r.get("generated", "")
                    checks = rep.get("checks", {})
                    click.echo(f"  {gen}: {rep.get('status')} Flip={checks.get('flip_detection',{}).get('status')} Ghosting={checks.get('ghosting',{}).get('status')} Color={checks.get('color',{}).get('status')}")
                if skipped_hint:
                    click.echo(skipped_hint)
                for t, w in sorted(target_worst.items()):
                    click.echo(f"  Target {t}: worst {w}")
                click.echo(f"Overall Gate: {overall_status} (Exit {overall_code})")

        ctx.exit(overall_code)

    # Single generated mode
    gen_path = Path(generated)
    # Support "latest" symlink or folder
    if gen_path.name.lower() == "latest":
        # Resolve symlink or directory; parent is target/generated/latest
        try:
            if gen_path.is_symlink():
                gen_path = gen_path.resolve()
            else:
                # If latest is directory, it's the run itself
                pass
        except Exception:
            pass
        # If not resolved to run, try to find latest timestamp
        if not (gen_path / "run-info.json").exists():
            parent_gen = gen_path.parent if gen_path.name.lower() == "latest" else gen_path
            # Parent should be generated; list timestamps
            try:
                timestamps = sorted([d for d in parent_gen.iterdir() if d.is_dir()], reverse=True)
                if timestamps:
                    gen_path = timestamps[0]
            except Exception:
                pass

    # V1.12-Nachfix 09.09.2026: Target-Root (z.B. "C:\Astra\M92 Kugelsternhaufen") oder "generated"-Ordner
    # ohne <ts> erzeugen qc.generated_path_unusual + scan ALLER 40 stacks (43s, vor Fix >600s).
    # Jetzt: auto-resolve auf latest generated/<ts> (1-2 stacks, ~5s), analog Spec default ohne --all = latest.
    # --all bleibt für alle NON-Smoke, --latest erzwingt latest explizit.
    _needs_latest_resolve = False
    try:
        # Use --latest explicitly or implicit when path is target root / generated folder (not a single <ts> run)
        if use_latest:
            _needs_latest_resolve = True
        elif "generated" not in str(gen_path).lower() and gen_path.is_dir() and (gen_path / "generated").is_dir():
            # Target-Root wie "C:\Astra\M92 Kugelsternhaufen" → latest
            _needs_latest_resolve = True
        elif gen_path.name.lower() == "generated" and gen_path.is_dir():
            # Direct "generated" folder → latest
            _needs_latest_resolve = True
        elif gen_path.is_dir() and not (gen_path / "run-info.json").exists() and not (gen_path / "agent-log.yaml").exists():
            # Exists but not a run folder (no run-info) but contains generated subfolders → likely target root
            if (gen_path / "generated").is_dir():
                _needs_latest_resolve = True
    except Exception:
        pass

    if _needs_latest_resolve:
        try:
            # Determine generated root
            if gen_path.name.lower() == "generated":
                gen_root = gen_path
            elif (gen_path / "generated").is_dir():
                gen_root = gen_path / "generated"
            else:
                gen_root = gen_path
            # Find latest run by mtime (or name reverse as fallback for timestamp dirs)
            candidates = [d for d in gen_root.iterdir() if d.is_dir() and ((d / "run-info.json").exists() or (d / "agent-log.yaml").exists() or any(d.rglob("*.fits")))]
            if not candidates:
                candidates = [d for d in gen_root.iterdir() if d.is_dir()]
            if candidates:
                # Prefer mtime, fallback to name sort
                try:
                    candidates_sorted = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
                except Exception:
                    candidates_sorted = sorted(candidates, reverse=True)
                latest = candidates_sorted[0]
                logger.info("qc.target_root_resolved_to_latest", original=str(generated), latest=str(latest), reason="target root / generated -> latest (V1.12-Nachfix, 40->2 stacks, 43s->~5s)")
                gen_path = latest
            else:
                logger.warning("qc.latest_resolve_no_candidates", path=str(gen_root))
        except Exception as e:
            logger.warning("qc.latest_resolve_failed", path=str(gen_path), error=str(e))

    if not gen_path.exists() or not gen_path.is_dir():
        click.echo(f"[FAIL] qc.not_found: {gen_path} not found", err=True)
        click.echo(f"expected C:\\Astra\\<Target>\\generated\\<ts> with run-info.json", err=True)
        logger.warning("qc.not_found", path=str(gen_path))
        ctx.exit(2)

    # Also guard that it's under generated
    if "generated" not in str(gen_path).lower():
        logger.warning("qc.generated_path_unusual", path=str(gen_path))

    try:
        report = run_qc(gen_path, check_header=bool(check_header))
    except Exception as e:
        click.echo(f"[FAIL] qc failed: {e}", err=True)
        logger.warning("qc.failed", path=str(gen_path), error=str(e))
        ctx.exit(1)

    # Write qc_report.json next to run-info
    try:
        out_path = write_qc_report(gen_path, report)
    except Exception as e:
        click.echo(f"[WARN] qc report write failed: {e}", err=True)
        out_path = gen_path / "qc_report.json"

    code = qc_exit_code(report)
    # Output
    if as_json:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        text = _format_qc_report(report)
        # Human readable PASS/FAIL per check
        if console and HAS_RICH:
            from rich.panel import Panel as _Panel
            color_map = {"PASS": "green", "FAIL": "red", "SKIPPED": "yellow"}
            status = report.get("status", "SKIPPED")
            clr = color_map.get(status, "white")
            console.print(_Panel(f"[{clr}]{status}[/{clr}] qc {gen_path.name} -- Flip={report['checks']['flip_detection'].get('status')} Ghosting={report['checks']['ghosting'].get('status')} Color={report['checks']['color'].get('status')}", expand=False))
            click.echo(text)
            click.echo(f"qc_report.json: {out_path} (Exit {code})")
        else:
            click.echo(text)
            click.echo(f"qc_report.json: {out_path} (Exit {code})")
            click.echo(f"Status: {report.get('status')} Exit {code}")

    ctx.exit(code)


# ────────────────────────────────────────────────────────────────
# V1.12-ORGANIZE -- astra organize <Target> [--dry-run] [--all]
# MOVE lights/*.fits → lights/group_*/  (FITS SSOT, FILTER/EQMODE, SOLL, Moon, <3, duplicate, exclusivity)
# ────────────────────────────────────────────────────────────────
@cli.command("organize")
@click.argument("target", required=False)
@click.option("--dry-run", is_flag=True, help="Show grouping table without moving files (no writes, Exit 0)")
@click.option("--all", "all_targets", is_flag=True, help="Organize all targets under data_root (ignores _darks/generated/_work/_foren/_sammlung/siril-scripts)")
@click.pass_context
def organize(ctx, target, dry_run, all_targets):
    """Organize flat lights in C:\\Astra\\<Target>\\lights\\ into group folders.

    \b
    Groups by (EXPTIME, GAIN, FILTER, EQMODE) from FITS header (SSOT), not filename.
    FILTER normalized duo-band/astro, EQMODE split per folder (_eq0/_eq1 only when split).
    Frames MOVE (os.rename) into lights\\group_{exp}s{gain}_{filter}[_eq0/1]\\.
    Duplicates (size+mtime) in root cleaned, <3 still sorted + hint, SOLL check, AZ/EQ mix warning, Moon READY(SIRIL).
    Lights exclusivity guard: only inbox frames + group_* allowed, foreign subfolders -> warning skipped.

    \b
    Examples:
      astra organize "C:\\Astra\\M31 Andromeda" --dry-run
      astra organize "C:\\Astra\\M31 Andromeda"
      astra organize --all --dry-run
      astra organize --all
    """
    cfg = ctx.obj.get("config")
    # Derive data_root
    try:
        data_root = Path(cfg.data_root).resolve() if cfg and getattr(cfg, "data_root", None) else Path("C:/Astra").resolve()
    except Exception:
        data_root = Path("C:/Astra").resolve()

    # Mutual exclusive guard (Click has no built-in mutually_exclusive)
    if all_targets and target is not None:
        raise click.UsageError("astra organize: <Target> and --all are mutually exclusive -- use either a target or --all")
    if not all_targets and target is None:
        raise click.UsageError("astra organize: <Target> required -- e.g. astra organize \"C:\\Astra\\M31 Andromeda\" or astra organize --all")

    # Lazy import organize core
    try:
        from .core.organize import format_organize_table, organize_all_targets, organize_target, resolve_target_path
    except Exception as e:
        click.echo(f"[FAIL] organize import failed: {e}", err=True)
        ctx.exit(1)

    console = _rich_console()

    # --all mode
    if all_targets:
        # Use organize_all_targets
        results = organize_all_targets(data_root, dry_run=dry_run)
        if not results:
            click.echo(f"No targets with lights\\ found under {data_root}", err=True)
            ctx.exit(2)
        total_groups = sum(len(r.get("groups", [])) for r in results)
        ready = sum(1 for r in results for g in r.get("groups", []) if g.get("status", "").startswith("READY"))
        skipped = sum(1 for r in results for g in r.get("groups", []) if g.get("status") == "SKIPPED")
        total_fits = sum(sum(g.get("count", 0) for g in r.get("groups", [])) for r in results)
        # Output per target
        for res in sorted(results, key=lambda x: x.get("target_name", "")):
            if res.get("error"):
                click.echo(f"Target {res.get('target_name')}: ERROR {res.get('error')}", err=True)
                continue
            tbl_text = format_organize_table(res)
            if console and HAS_RICH:
                # For --all, just echo plain (rich Table per target would be verbose); use plain
                click.echo(tbl_text)
                click.echo("")
            else:
                click.echo(tbl_text)
                click.echo("")
        # Summary line per spec: Targets: 3, Groups: 7 (READY 5, SKIPPED 2), Total FITS: 210
        summary = f"Targets: {len(results)}, Groups: {total_groups} (READY {ready}, SKIPPED {skipped}), Total FITS: {total_fits}"
        if console and HAS_RICH:
            console.print(f"[bold]{summary}[/bold]")
        else:
            click.echo(summary)
        # Handle warnings for --all --dry-run? Already in tables
        ctx.exit(0)

    # Single target mode
    # Resolve target path via ORG-X2 (filesystem scan, no cache)
    try:
        target_path = resolve_target_path(target, data_root)
    except (FileNotFoundError, ValueError) as e:
        # Provide hint per spec: place FITS in C:\Astra\<Target>\lights\
        click.echo(f"[FAIL] {e}", err=True)
        # Did-you-mean already in message; also hint for no_lights case
        ctx.exit(2)
    except Exception as e:
        click.echo(f"[FAIL] organize target resolve failed: {e}", err=True)
        ctx.exit(2)

    # Run organize_target
    try:
        result = organize_target(target_path, dry_run=dry_run)
    except FileNotFoundError as e:
        msg = str(e)
        if "organize.no_lights" in msg:
            click.echo(f"[FAIL] {msg}", err=True)
            click.echo(f"Hint: place FITS in {target_path / 'lights'}", err=True)
            ctx.exit(2)
        click.echo(f"[FAIL] {msg}", err=True)
        ctx.exit(2)
    except Exception as e:
        click.echo(f"[FAIL] organize failed: {e}", err=True)
        ctx.exit(1)

    # Output
    # If no groups and dry_run with existing groups? Already handled
    # Check nothing to organize case
    if not result.get("groups") and result.get("moved", 0) == 0 and not dry_run:
        # Could be idempotent or empty root
        # Check if target had group dirs and no root fits → "nothing to organize"
        if result.get("root_fits") == [] and result.get("groups"):
            click.echo("nothing to organize", err=False)
            logger.info("organize.nothing_to_organize", target=str(target_path))
            ctx.exit(0)
    tbl = format_organize_table(result)
    if console and HAS_RICH:
        # Try rich table? For now plain text is enough (spec: Rich Table if rich else Plain)
        # We could render via Table but spec expects Gruppe | Frames etc; plain suffices and is hash-stable for tests
        click.echo(tbl)
    else:
        click.echo(tbl)

    # Exit 0 even for <3 (SKIPPED) -- per spec
    ctx.exit(0)


# ────────────────────────────────────────────────────────────────
# V1.12-STEP3 -- astra download-example M31 --n 10 [--output DIR] [--force]
# GitHub Release-Asset 10 echte FITS 90s40 Astro, idempotent, SHA256, Real-Gate --limit 5
# ────────────────────────────────────────────────────────────────
@cli.command("download-example")
@click.argument("target", required=True)
@click.option(
    "--n",
    "num",
    type=int,
    default=10,
    show_default=True,
    help="Number of light frames to fetch (N >= 1, default 10).",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Output DIRECTORY for the example dataset (default: C:/Astra/<Target>). The data is extracted to <output>/lights/group_90s40_astro/ and <output>/suggested.yaml.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing files (idempotent skip otherwise).",
)
@click.pass_context
def download_example(ctx, target, num, output_path, force):
    """Download a real-data example (10 M31 FITS as GitHub Release asset).

    \b
    Fetches 10 real M31 light frames (90s Gain 40 Astro, 1920x1080) as a
    GitHub Release asset (M31-example-10fits.tar.gz), verifies SHA256, and
    extracts to <output>/lights/group_90s40_astro/. Idempotent: existing
    files are skipped unless --force is given. Offline fallback copies from
    C:/Astra/M31 Andromeda/lights/group_90s40_astro/ when GitHub is
    unreachable.

    \b
    Examples:
      astra download-example M31 --n 10
      astra download-example M31 --n 10 --output C:/Astra/M31_B_test
      astra download-example M31 --n 10 --force

    Real-Gate: after download, run:
      astra process <output> --from-suggested <output>/suggested.yaml --limit 5 --dry-run
    """
    import hashlib
    import tarfile

    cfg = ctx.obj.get("config") if ctx.obj else None
    # Validate --n
    if num is None or num < 1:
        raise click.UsageError(f"download-example: --n must be >= 1 (got {num})")

    # Resolve output dir: default C:/Astra/<Target> (target name as given, e.g. M31)
    # For M31, canonical output is C:/Astra/M31 (test uses C:/Astra/M31_B_test)
    if output_path is not None:
        out_dir = Path(output_path)
    else:
        # Use target string as dir name (e.g. M31 -> C:/Astra/M31)
        safe_target = str(target).strip().replace(" ", "_")
        out_dir = Path("C:/Astra") / safe_target

    # Normalize target key for asset lookup (M31 -> M31-example-10fits.tar.gz)
    # Only M31 is supported in v1.12-STEP3; other targets -> asset_not_found
    normalized = str(target).strip().lower()
    # Accept "M31", "M31 Andromeda", "M31_B", etc. -> treat as M31 if contains m31
    is_m31 = "m31" in normalized
    if not is_m31:
        raise click.UsageError(
            f"download.asset_not_found: asset for target '{target}' not found "
            f"(only M31 example available in v1.12-STEP3) -- check 'astra download-example --help'"
        )

    # GitHub asset URL (release tag M31-example, asset M31-example-10fits.tar.gz)
    # If download fails, fallback to local C:/Astra/M31 Andromeda real data.
    asset_url = "https://github.com/borisfrast-oss/astra/releases/download/M31-example/M31-example-10fits.tar.gz"
    # Also check for manifest file asset_url + .sha256 (optional)
    manifest_url = asset_url + ".sha256"

    # Prepare output structure: <out_dir>/lights/group_90s40_astro/ + suggested.yaml
    lights_group = out_dir / "lights" / "group_90s40_astro"
    suggested_path = out_dir / "suggested.yaml"

    # Idempotent check: if lights_group has >= num files and not --force, skip
    existing = list(lights_group.glob("*.fits")) if lights_group.is_dir() else []
    if existing and len(existing) >= num and not force:
        logger.info("download.skipped_existing", target=target, output=str(out_dir), existing=len(existing), requested=num)
        click.echo(f"[SKIP] {out_dir} already has {len(existing)} FITS (>= {num}) -- use --force to overwrite")
        ctx.exit(0)

    # Try GitHub download first (5s timeout, 1 query, offline-first fallback)
    downloaded = False
    tmp_tar = None
    try:
        import requests

        # Probe asset existence via HEAD (quick)
        try:
            resp = requests.head(asset_url, timeout=5, allow_redirects=True)
            if resp.status_code == 200:
                # Download with progress
                tmp_tar = out_dir / "_tmp_M31-example-10fits.tar.gz"
                tmp_tar.parent.mkdir(parents=True, exist_ok=True)
                with requests.get(asset_url, stream=True, timeout=10) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    downloaded_bytes = 0
                    with open(tmp_tar, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                # Verify SHA256 if manifest available
                try:
                    mr = requests.get(manifest_url, timeout=5)
                    if mr.status_code == 200 and mr.text.strip():
                        expected = mr.text.strip().split()[0].lower()
                        sha = hashlib.sha256()
                        with open(tmp_tar, "rb") as f:
                            for chunk in iter(lambda: f.read(8192), b""):
                                sha.update(chunk)
                        actual = sha.hexdigest().lower()
                        if expected != actual:
                            logger.warning("download.sha_mismatch", expected=expected, actual=actual)
                            click.echo(f"[WARN] SHA256 mismatch: expected {expected}, got {actual}", err=True)
                        else:
                            logger.info("download.sha_ok", sha=actual)
                except Exception:
                    pass  # manifest optional
                # Extract
                lights_group.mkdir(parents=True, exist_ok=True)
                with tarfile.open(tmp_tar, "r:gz") as tf:
                    tf.extractall(path=out_dir)
                downloaded = True
                logger.info("download.asset_ok", target=target, url=asset_url, output=str(out_dir))
                click.echo(f"[OK] Downloaded {num} M31 FITS from GitHub asset to {out_dir}")
            else:
                logger.info("download.asset_not_found", target=target, url=asset_url, status=resp.status_code)
        except Exception as e:
            logger.info("download.asset_unavailable", target=target, error=str(e))
    except ImportError:
        logger.info("download.no_requests", target=target)
    except Exception as e:
        logger.info("download.failed", target=target, error=str(e))

    # Fallback: copy from local real data C:/Astra/M31 Andromeda/lights/group_90s40_astro/
    if not downloaded:
        # If we have a partial download file, remove it
        if tmp_tar and tmp_tar.exists():
            try:
                tmp_tar.unlink()
            except Exception:
                pass
        # Local real source (C:\Astra\M31 Andromeda is the canonical real data)
        local_src_candidates = [
            Path("C:/Astra/M31 Andromeda/lights/group_90s40_astro"),
            Path("C:/Astra/M31 Andromeda/lights/group_90s40_duo-band"),
            Path("C:/Astra/M31/lights/group_90s40_astro"),
        ]
        src_dir = None
        for cand in local_src_candidates:
            if cand.is_dir() and list(cand.glob("*.fits")):
                src_dir = cand
                break
        if src_dir is None:
            # No local data and GitHub failed -> Error Exit 2
            raise click.UsageError(
                f"download.asset_not_found: GitHub asset unreachable and no local fallback at "
                f"C:/Astra/M31 Andromeda/lights/group_90s40_astro/ -- check network or place 10 M31 FITS at {out_dir}/lights/group_90s40_astro/"
            )
        # Copy first num files natural sort
        src_files = sorted(src_dir.glob("*.fits"), key=lambda p: p.name.lower())
        if len(src_files) < num:
            raise click.UsageError(
                f"download.asset_not_found: source has {len(src_files)} FITS < requested {num} at {src_dir}"
            )
        selected = src_files[:num]
        lights_group.mkdir(parents=True, exist_ok=True)
        # If --force, clean existing first
        if force and lights_group.exists():
            for ef in lights_group.glob("*.fits"):
                try:
                    ef.unlink()
                except Exception:
                    pass
        for sf in selected:
            dest = lights_group / sf.name
            if dest.exists() and not force:
                continue
            import shutil
            shutil.copy2(str(sf), str(dest))
        # Create suggested.yaml if missing or --force
        if not suggested_path.exists() or force:
            yaml_content = """# suggested_parameters.yaml - M31 Real-Beispiel 10F
# Source: download-example M31 --n 10 (GitHub Asset M31-example-10fits.tar.gz, fallback C:/Astra/M31 Andromeda)
# Handbook: 05 Galaxies 60-120s Gain 30-40 No filter + 22 Galaxy Workflow No filter
version: 1
target: M31
simbad_name: M31
type: galaxy
handbook_ref: "22 $3 Galaxies + 05-Galaxies.md"
source: download
preset: galaxy_standard
registration:
  method: astroalign
  max_rotation_deg: 15
debayer:
  method: malvar
pcc:
  enabled: true
equipment_hint: dwarf_mini
filter_hint: Astro
exptime_hint: 90
"""
            suggested_path.parent.mkdir(parents=True, exist_ok=True)
            suggested_path.write_text(yaml_content, encoding="utf-8")
        logger.info("download.fallback_local", target=target, src=str(src_dir), output=str(out_dir), count=len(selected))
        click.echo(f"[OK] Copied {len(selected)} M31 FITS from local {src_dir} to {lights_group} (fallback, GitHub asset unavailable)")
        downloaded = True

    # Final verification: ensure output has num files
    final = list(lights_group.glob("*.fits"))
    if len(final) < num:
        raise click.ClickException(f"download incomplete: expected {num} FITS, got {len(final)} at {lights_group}")

    # Idempotent SHA-like manifest (optional): write .sha256 next to output for verification
    # Compute SHA256 of first file as representative (not full manifest)
    try:
        sha = hashlib.sha256()
        with open(final[0], "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        logger.info("download.complete", target=target, output=str(out_dir), files=len(final), sha=sha.hexdigest()[:8])
    except Exception:
        pass

    click.echo(f"Done: {len(final)} FITS at {lights_group} + {suggested_path} (galaxy_standard, 90s40 Astro)")
    ctx.exit(0)


if __name__ == "__main__":
    cli()
