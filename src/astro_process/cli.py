"""CLI entry point for Astra pipeline."""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime
import queue
import re
import shutil
import sys
import threading
import click
import structlog
import yaml

try:
    from importlib.metadata import version as _get_version, PackageNotFoundError
except ImportError:  # pragma: no cover
    from importlib_metadata import version as _get_version, PackageNotFoundError  # type: ignore


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


def _apply_resolver_result(effective_registration, resolver_result: dict) -> None:
    """Propagate resolver-derived registration fields onto the effective config.

    Mirrors the assignment logic used when a smart default overrides the
    config/preset default. Extracted for testability (no false coverage).
    """
    if resolver_result.get("method") is not None:
        effective_registration.method = resolver_result["method"]
    if resolver_result.get("max_rotation_deg") is not None:
        effective_registration.max_rotation_deg = float(resolver_result["max_rotation_deg"])
    if resolver_result.get("max_exptime_fft_warn") is not None:
        effective_registration.max_exptime_fft_warn = float(resolver_result["max_exptime_fft_warn"])

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
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

from .config import AppConfig, load_config, save_default_config
from .config.loader import (
    DEFAULT_CONFIG,
    resolve_export_config,
    resolve_gradient_removal,
    resolve_preview_export_config,
    resolve_registration,
    resolve_stack_scale_factor,
)
from .config.models import MultiGroupConfig, MergeConfig, PipelinePreset
from .models.core import ObservationContext, PipelineConfig, PhaseStatus
from .core.fits_parser import build_observation_context
from .core.staging import stage_input
from .agents.discovery import create_discovery_agent
from .agents.calibration import create_calibration_agent, CalibrationResult
from .agents.debayer_agent import create_debayer_agent
from .agents.cosmetic_agent import create_cosmetic_agent
from .agents.processing_agent import create_processing_agent
from .core.stacking import resolve_stack_method
from .agents.archive import create_archive_agent
from .agents.merge_agent import MergeAgent

def _rich_console():
    if HAS_RICH:
        return Console()
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
                click.echo(f"  Ungueltig: {e}", err=True)
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
                from astropy.io import fits as afits
                import numpy as np
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
            result["checks"].append("12-bit Clipping erkannt -> Cosmetic empfohlen (Warning)")
            if result["status"] == "OK":
                result["status"] = "Warning"
        if not dark_ok:
            result["checks"].append("Dark-Passung: keine Darks gefunden (Warning)")
            if result["status"] == "OK":
                result["status"] = "Warning"
        else:
            result["checks"].append("Dark-Passung: OK")
        if cosine_rec:
            result["checks"].append("Cosmetic Empfehlung: aktivieren (>200 Hot Pixels/Clipping)")
        else:
            result["checks"].append("Cosmetic: nicht erforderlich")

        # Abort condition: extrem viele hot pixels? For spec, >200 is warning, not abort. Keep Ok/Warning only.
        # Simulate abort if no lights
        if not fits_files:
            result["checks"].append("Keine Lights gefunden (Abort)")
            result["status"] = "Abort"
    except Exception as e:
        result["checks"].append(f"Preflight Fehler: {e}")
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
        "Config-Datei (global, muss VOR dem Subcommand stehen, z.B. "
        "--config config.yaml process <target>). Ohne --config sucht die "
        "Pipeline automatisch config.yaml im aktuellen Verzeichnis bzw. "
        "im Projekt-Root."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx, config, verbose):
    """Astra - Agentic Astrophotography Processing Pipeline."""
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
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Output directory")
@click.option("--dry-run", is_flag=True, help="Show plan without executing")
@click.option("--keep-working", is_flag=True, help="Preserve working directory")
@click.option("--keep-groups/--no-keep-groups", default=None, help="Gruppen-Dirs behalten/aufraeumen (Default: aus Config, sonst true)")
@click.option("--resume", is_flag=True, help="Resume from last checkpoint")
# Multi-group flags — V1.7-5 (Always Multi-Group): Multi-Group ist IMMER
# aktiv; die beiden Erkennungs-Flags sind deprecated No-ops (Entfernung in
# v1.8). --merge/--no-merge wirkt weiter (Default: Merge AN).
@click.option("--multi-group", is_flag=True, help="Deprecated No-op (v1.7): Multi-Group ist immer aktiv")
@click.option("--auto-group", is_flag=True, help="Deprecated No-op (v1.7): Multi-Group ist immer aktiv")
@click.option("--merge/--no-merge", default=None, help="Merge-Schritt aktivieren/deaktivieren (Standard: aktiv)")
@click.option("--weight-by", type=click.Choice(["frame_count", "total_exposure"]), help="Gewichtung fuers Merge (ueberschreibt Config)")
@click.option("--merge-method", type=click.Choice(["weighted_average", "average", "median"]), help="Merge-Methode (ueberschreibt Config)")
# V1.7-1 FSM-A (AC-FSM-A3/A4, OQ-FSM-2 A): Filter-Auswahl fuer Merge (Precedence CLI > Config, analog --weight-by/--merge-method).
# Wiederholbar: --merge-filter "Astro" --merge-filter "Duo-Band" akkumuliert Liste; case-insensitive getrimmt (AC-FSM-A2).
@click.option("--merge-filter", "merge_filter", multiple=True, type=str, help="Filter-Auswahl fuer Merge (wiederholbar, case-insensitive getrimmt, z.B. --merge-filter Astro --merge-filter \"Duo-Band\"; ueberschreibt Config)")
@click.option("--pcc-per-group/--no-pcc-per-group", default=None, help="PCC pro Gruppe (Default: false = PCC auf merged Stack, max S/N)")
# Leo-Auftrag 2026-08-10 (Teil B3): Stacking-Methode (analog --merge-method).
# Precedence CLI > Preset/Config (processing_params.stacking_method) >
# Rejection-Mapping (Teil B1) > Default "average".
# V1.7-3 (AC-SCS-B1): sigma_clipped_mean als zusaetzliche Stacking-Methode.
@click.option("--stacking-method", type=click.Choice(["average", "median", "winsorized", "weighted", "sigma_clipped_mean"]), help="Stacking-Methode (ueberschreibt Preset/Config; sonst Mapping aus rejection; sigma_clipped_mean = robustes Sigma-Clipping)")
# W9-B (AC-W9-B1): Registrations-Methode (Precedence CLI > Config > Preset > Default)
# V1.4-2: "rotation_fft" = Log-Polar-FFT-Rotation (AZ-Feldrotation).
@click.option("--registration-method", type=click.Choice(["fft", "astroalign", "rotation_fft"]), help="Registrations-Methode (ueberschreibt Config/Preset)")
# SanityGuard (S1-A7): max. |Rotation| in Grad (Precedence CLI > Config > Preset > Default)
@click.option(
    "--max-rotation",
    type=float,
    default=None,
    help="SanityGuard: max. Rotation in Grad fuer astroalign/rotation_fft (Default 2.0, Feldrotation z.B. 15)",
)
# RE-F (V1.3-24, AC-RE-F3): W1-Zero-Shift-Guard — Schwelle konfigurierbar /
# Guard deaktivierbar (Precedence CLI > Config > Preset > Default 0.0/true).
@click.option(
    "--zero-shift-threshold",
    type=float,
    default=None,
    help=(
        "W1-Guard: corr_hp-Schwelle (Default 0.0). fft-Zweig -> Zero-Shift "
        "Fallback; astroalign-Gewinner unter Schwelle -> Frame verwerfen"
    ),
)
@click.option(
    "--no-zero-shift-fallback",
    is_flag=True,
    default=False,
    help=(
        "W1-Guard komplett deaktivieren (weder Zero-Shift-Fallback noch "
        "astroalign-Reject unter der Schwelle)"
    ),
)
# V1.5-11 (W2): EQMODE-Override-Flags (V1.6-7: shotsInfo entfernt aus Pipeline).
# Precedence CLI > EQMODE-Header. None = kein Override.
@click.option(
    "--az-mode",
    "eq_mode_override",
    flag_value="az",
    default=None,
    help="EQMODE-Override: AZ-Modus erzwingen (ueberschreibt EQMODE-Header)",
)
@click.option(
    "--eq-mode",
    "eq_mode_override",
    flag_value="eq",
    default=None,
    help="EQMODE-Override: EQ-Modus erzwingen (ueberschreibt EQMODE-Header)",
)
# V1.5-12 (W3): Pixel-Skala direkt per CLI ueberschreiben.
# Precedence CLI > Equipment-Header > Config/Preset.
@click.option(
    "--pixel-scale",
    type=float,
    default=None,
    help="Pixel-Skala (arcsec/px) direkt ueberschreiben (ueberschreibt Equipment-Header)",
)
# V1.5-13 (W4): Structure-Enhancement-Parameter per CLI ueberschreiben.
# Precedence CLI > Preset-Step-Params.
@click.option(
    "--se-radius",
    type=float,
    default=None,
    help="Structure-Enhancement Radius (Default 3.0 aus Preset-Step)",
)
@click.option(
    "--se-amount",
    type=float,
    default=None,
    help="Structure-Enhancement Amount (Default 0.2 aus Preset-Step)",
)
# GR-B (AC-GR-B1): Gradient-Removal-Config (Precedence CLI > Config > Preset > Default)
@click.option(
    "--gradient-removal-enabled/--gradient-removal-disabled",
    default=None,
    help="Gradient Removal aktivieren/deaktivieren (ueberschreibt Config/Preset)",
)
@click.option(
    "--gradient-removal-degree",
    type=int,
    default=None,
    help="GR-Polynom-Grad (ueberschreibt Config/Preset)",
)
@click.option(
    "--gradient-removal-grid",
    type=str,
    default=None,
    help="GR-Sampling-Grid als 'rows,cols' z.B. 16,16 (ueberschreibt Config/Preset)",
)
@click.option(
    "--gradient-removal-sigma-clip",
    type=float,
    default=None,
    help="GR-Sigma-Clipping k in k*MAD (ueberschreibt Config/Preset)",
)
@click.option(
    "--gradient-removal-min-samples",
    type=int,
    default=None,
    help="GR-Mindest-Sample-Zellen fuer den Fit (ueberschreibt Config/Preset)",
)
# W5: Darks Library
@click.option("--darks-path", type=click.Path(exists=True, path_type=Path), help="Pfad zur zentralen Darks-Bibliothek (ueberschreibt Config: darks_repository)")
# Cosmetic Correction CLI-Flag (Precedence CLI > Config > Default)
@click.option(
    "--cosmetic-correction/--no-cosmetic-correction",
    default=None,
    help="Cosmetic Correction aktivieren/deaktivieren (ueberschreibt Config)",
)
# V1.8-0 (MALVAR): Debayer-Methode (Precedence CLI > Config > Preset > Default)
@click.option(
    "--debayer-method",
    type=click.Choice(["superpixel", "bilinear", "malvar"]),
    default=None,
    help="Debayer-Methode: superpixel (Default, DADR-003) oder malvar (1920x1080, High-Quality, Malvar2004) oder bilinear (deprecated, use malvar or superpixel, volle Auflösung)",
)
# V1.7-2 FSEL-D (AC-FSEL-D3): Frame-Selection CLI-Override (Precedence CLI > Config > Preset)
@click.option(
    "--frame-selection/--no-frame-selection",
    default=None,
    help="Frame-Selection (Perzentil, DwarfLab-Pattern) aktivieren/deaktivieren (ueberschreibt Config/Preset, Default aus)",
)
@click.option(
    "--keep-percentile",
    type=click.IntRange(1, 100),
    default=None,
    help="Keep-Perzentil fuer Frame-Selection (1-100, Default 92, nur wenn --frame-selection)",
)
# V1.8-1 CFA-Drizzle (Precedence CLI > Config > Default, AC-DRZ-10)
@click.option(
    "--cfa-drizzle/--no-cfa-drizzle",
    default=None,
    help="CFA-Drizzle aktivieren/deaktivieren (2x, nutzt Dwarf Mini Dithering, Default aus)",
)
@click.option(
    "--drizzle-scale",
    type=float,
    default=None,
    help="Drizzle Scale (Default 2.0, 2x = 3840x2160)",
)
@click.option(
    "--drizzle-pixfrac",
    type=float,
    default=None,
    help="Drizzle Pixfrac (0.5-1.0, bei fixed mode, Default auto: <10=1.0, 10-30=0.7, >30=0.5)",
)
@click.option(
    "--drizzle-kernel",
    type=click.Choice(["lanczos3", "gaussian", "tophat"]),
    default=None,
    help="Drizzle Kernel (Default lanczos3, gaussian/tophat als Option)",
)
# V19-CFA-GATE G4: Quality Gate CLI (1 sichtbar + 5 hidden)
@click.option(
    "--cfa-drizzle-quality-gate/--no-cfa-drizzle-quality-gate",
    default=None,
    help="Quality Gate fuer CFA-Drizzle: Auto (Default), AN, AUS (alle Frames durchlassen)",
)
@click.option(
    "--cfa-drizzle-min-frames",
    type=int,
    default=None,
    help="Mindest-Frames fuer Drizzle (Default: 5, CFA-Smart: 5)",
)
@click.option(
    "--cfa-drizzle-fallback",
    type=click.Choice(["malvar", "superpixel", "skip"]),
    default=None,
    hidden=True,
    help="Fallback-Methode bei Quality Gate Fail (Default: malvar) [advanced]",
)
@click.option(
    "--cfa-drizzle-star-count-min",
    type=int,
    default=None,
    hidden=True,
    help="Min Star Count (Default: 20 debayered, CFA-Smart: 1) [advanced]",
)
@click.option(
    "--cfa-drizzle-snr-min",
    type=float,
    default=None,
    hidden=True,
    help="Min SNR (Default: 10, CFA-Smart: 5) [advanced]",
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
    help="FWHM Range als 'min,max' (Default: 1.5,5.0, CFA-Smart: 1.0,8.0) [advanced]",
)
# V19-PCC-FLAG P1: --pcc/--no-pcc (default None, kein Breaking)
@click.option(
    "--pcc/--no-pcc",
    default=None,
    help="Photometric Color Calibration aktivieren/deaktivieren (ueberschreibt Preset/Config; Default: Preset/Config gewinnt)",
)
# CLI-C --preflight (V1.8-4): Nur Pre-Flight Checks ohne Pipeline-Start
@click.option("--preflight", is_flag=True, help="Nur Pre-Flight Checks (Hot Pixel Scan, Dark-Passung, Cosmetic Empfehlung) — kein Pipeline-Start")
@click.option("--yes", is_flag=True, help="Bei --preflight: bei OK direkt Pipeline starten")
# T2: --no-calib: Kalibration ueberspringen (vor-kalibrierte Lights)
@click.option(
    "--no-calib/--calib",
    default=None,
    help=(
        "Kalibrationsphase ueberspringen (vor-kalibrierte Lights). "
        "Hinweis: Lights muessen CFA/2D (Bayer-Rohdaten) sein — bereits "
        "debayerte 3D-RGB-Lights fuehren beim Debayer-Schritt zu einem Fehler."
    ),
)
@click.pass_context
def process(ctx, target_path, preset, output, dry_run, keep_working, keep_groups, resume,
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
            cfa_drizzle_fwhm_range, pcc):
    """Process a single target directory.

    Hinweis (Docs regen 2026-08-11, B3): --config/-c ist eine GLOBALE
    Option und muss vor dem Subcommand stehen, z.B.:
        astro-process --config config.yaml process <target>
    Ohne --config sucht die Pipeline automatisch nach config.yaml im
    aktuellen Verzeichnis (CWD) bzw. im Projekt-Root.
    """
    cfg: AppConfig = ctx.obj["config"]
    # T2: Precedence CLI > Config. None = Flag nicht gesetzt → Config-Wert.
    effective_no_calib = no_calib if no_calib is not None else cfg.no_calib
    
    logger.info("cli.process.start", target=str(target_path), preset=preset)
    
    # Resolve target directory
    target_dir = target_path.resolve()
    target_name = target_dir.name

    # CLI-C --preflight: nur Checks, kein Pipeline-Start (ausser --yes bei OK)
    if preflight:
        result = _run_preflight_checks(target_dir, cfg, darks_path)
        _print_preflight_result(result)
        if not yes:
            return
        if result["status"] == "Abort":
            click.echo("[ABORT] Pre-Flight fehlgeschlagen — Pipeline nicht gestartet", err=True)
            sys.exit(2)
        if result["status"] == "Warning":
            click.echo("[WARNING] Pre-Flight Warnungen — starte trotzdem (--yes)", err=True)
        # bei OK oder Warning + --yes: faellt durch zur Pipeline
    
    # Determine preset
    if not preset:
        # Try to infer from target name
        preset = cfg.default_preset
    pipeline = cfg.get_preset(preset)
    if not pipeline:
        raise click.ClickException(f"Preset '{preset}' not found")

    # W9-B (AC-W9-B1, ADR-019): Precedence CLI > Config > Preset > Default.
    # Die effektive Config wird im Preset verankert, damit die Pipeline
    # (S1-A7: Registration-Strategy) sie ueber
    # `pipeline.processing_params.registration` liest.
    # RE-F (AC-RE-F3): --no-zero-shift-fallback (is_flag) wird in den
    # cli-Wert False uebersetzt; nicht gesetzt -> None (kein Override).
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

    # V1.8-0 (MALVAR): Debayer-Methode aufloesen.
    # Precedence: CLI > Config > Default "superpixel".
    from .config.loader import resolve_stack_scale_factor
    import warnings
    effective_debayer_method = debayer_method or cfg.debayer_method or "superpixel"
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
    # Der Preset-Fallback wird hier abgeleitet — BEVOR
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
                f"Ungueltiges --gradient-removal-grid '{gradient_removal_grid}': {e}"
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
            # Finde aktiven Preset
            effective_preset_name = preset or cfg.default_preset
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
    
    # Work in timestamped generated/ subdirectory (preserves all runs)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    working_dir = target_dir / "generated" / timestamp
    out_dir = working_dir  # same dir for intermediate and final outputs

    # Punkt 3 (Input-Staging): Pipeline liest NUR aus generated/<ts>/00_input.
    # Der Target-Root wird ausschliesslich hier gelesen (explizite Ordner
    # lights/darks/flats/bias) — Fremd-FITS (App-Stacks, Siril, Exporte)
    # sind fuer die Pipeline komplett irrelevant.
    input_dir = stage_input(target_dir, working_dir)

    try:
        # Phase 1: Discovery
        logger.info("phase.discovery.start")
        discovery_agent = create_discovery_agent(cfg)
        discovery_result = discovery_agent.run(input_dir, shots_root=target_dir)
        context = discovery_result.context
        logger.info("phase.discovery.complete", lights=context.total_light_frames, darks=context.calibration.dark_count)

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
        # Datengetriebene stack_scale_factor-Aufloesung NACH der Discovery —
        # die Datenlage (2D-CFA vs. bereits debayertes 3D-RGB) ist erst jetzt
        # bekannt. Precedence: explicit (Config) > preset > datengetrieben
        # (3D -> 1.0; 2D + Methode) > Default 2.0. explicit/preset_ssf sind
        # in Stufe 1 (oben) abgeleitet — VOR der Mutation von
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

        # V19-REG-SMART E3: Priority Chain recompute after Discovery (header available)
        # Resolve registration via new 5-param resolver (CLI > Profil > Auto-Detect > Config > fft hardcode)
        try:
            from .config.loader import resolve_registration_config, _detect_equipment_from_header  # type: ignore
            from .core.equipment import detect_mount_type as _dt_for_e3  # type: ignore
            _e3_header = None
            _e3_exptimes: list[float] = []
            try:
                _lights_e3 = context.get_lights().frames if context else []
                if _lights_e3 and _lights_e3[0].header is not None:
                    _raw_e3 = getattr(_lights_e3[0].header, "raw_cards", None)
                    _e3_header = _raw_e3 if _raw_e3 is not None else _lights_e3[0].header
                    # Also handle header as object with get method; raw_cards is dict-like
                    if not hasattr(_e3_header, "get") and isinstance(_e3_header, dict):
                        pass
                for _f in _lights_e3:
                    try:
                        if _f.header is not None and getattr(_f.header, "exptime", None) is not None:
                            _e3_exptimes.append(float(_f.header.exptime))  # type: ignore
                    except Exception:
                        continue
            except Exception:
                pass
            _e3_equipment = {}
            try:
                _e3_equipment = _detect_equipment_from_header(_e3_header, cfg) or {}
            except Exception:
                _e3_equipment = {}
            # Also inject mount_type via detect_mount_type for logging (Spec cli.py:531)
            _e3_mount = "eq"
            try:
                if _e3_header is not None:
                    _e3_mount = _dt_for_e3(_e3_header)
                elif _e3_equipment.get("mount_type"):
                    _e3_mount = str(_e3_equipment.get("mount_type"))
            except Exception:
                pass
            _e3_result = resolve_registration_config(
                cfg=cfg,
                equipment=_e3_equipment if _e3_equipment else None,
                header=_e3_header,
                exptimes=_e3_exptimes if _e3_exptimes else None,
                cli_method=registration_method,
            )
            # Apply smart default if CLI not set and result differs (equipment/auto wins over config default)
            if registration_method is None and _e3_result.get("method") != effective_registration.method:
                old_m = effective_registration.method
                _apply_resolver_result(effective_registration, _e3_result)
                pipeline.processing_params.registration = effective_registration
                logger.info(
                    "registration.smart_default_applied",
                    old_method=old_m,
                    new_method=effective_registration.method,
                    mount_type=_e3_mount,
                    max_exptime=max(_e3_exptimes) if _e3_exptimes else 0,
                    source="equipment" if _e3_equipment else "auto_detect",
                )
            # Persist CLI override for downstream multi-group per-group resolver
            try:
                cfg._registration_cli_override = registration_method  # type: ignore[attr-defined]
            except Exception:
                pass
            # Also log mount_type injection (Spec cli.py:531)
            logger.info("registration.mount_type_injected", mount_type=_e3_mount, equipment=_e3_equipment.get("name") if _e3_equipment else None)
        except Exception as _e3_exc:
            logger.warning("registration.smart_default_failed", error=str(_e3_exc))

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
                        f"FFT-Registrierung auf AZ-Mount mit {_max_exp}s Belichtung — "
                        f"Feldrotation nicht korrigierbar (Threshold: {_cli_threshold}s). "
                        f"Erwartet: Ghosting an Bildraendern, Stern-Doppelkonturen (rotation_deg 0.0 ist FFT-Artefakt). "
                        f"Loesung: --registration-method astroalign --max-rotation 15 "
                        f"oder Equipment-Profil mit preferred_registration: astroalign"
                    ),
                )
        except Exception:
            pass

        # V1.7-5 (Always Multi-Group, AC-B3/B6): --multi-group/--auto-group
        # sind deprecated No-ops (Grace-Period bis v1.8) — Multi-Group ist
        # immer aktiv. Der Merge bleibt per Default AN; die B6-Semantik
        # (merge_enabled = True wenn --merge/--no-merge nicht gesetzt) ist
        # damit identisch zur frueheren --multi-group-Automatic.
        if multi_group or auto_group:
            logger.warning(
                "cli.process.multi_group_flag_deprecated",
                flags=[name for name, v in (
                    ("--multi-group", multi_group), ("--auto-group", auto_group),
                ) if v],
                msg="Flag ist obsolet — Multi-Group ist immer aktiv",
            )
            click.echo(
                "[WARN] --multi-group/--auto-group sind obsolet — "
                "Multi-Group ist immer aktiv (deprecated, Entfernung in v1.8)",
                err=True,
            )

        if dry_run:
            # V1.7-5 (Always Multi-Group, AC-B4): EIN vereinheitlichter
            # Dry-Run fuer jede Gruppenzahl (inkl. 1) — Kontextzeilen +
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
                # V1.7-1 FSM-C1/C3: Dry-run Transparenz — Filter-Liste + Kandidat/excluded je Gruppe
                from .config.loader import resolve_merge_filters, is_merge_filter_match
                _eff_filters = resolve_merge_filters(ctx.obj["config"], cli_filters=merge_filter)
                # Tippfehler-Warning (AC-C3) — Filterwert matcht keine Gruppe
                if _eff_filters is not None:
                    _group_norm_filters = set()
                    for _gh2, _info2 in groups.items():
                        _raw_fv2 = _info2.key[2]
                        if _raw_fv2 in ("none", "", None):
                            _fv2 = ""
                        else:
                            _fv2 = str(_raw_fv2)
                        _group_norm_filters.add(_fv2.strip().lower())
                    for _flt in set(_eff_filters):
                        if _flt not in _group_norm_filters:
                            logger.warning(
                                "cli.process.merge_filter_no_match",
                                filter=_flt,
                                effective=_eff_filters,
                                groups=sorted(_group_norm_filters),
                                hint="Verdacht Tippfehler: Filter-Wert passt zu keiner Gruppe",
                            )
                            click.echo(f"  [WARN] Filter '{_flt}' passt zu keiner Gruppe (Verdacht Tippfehler) — verfuegbar: {sorted(_group_norm_filters)}", err=True)
                    # Kandidat-Zaehler via selbe Normalisierung wie Pipeline (None fuer "none"/"")
                    def _dry_filter_val(k2):
                        return None if k2 in ("none", "", None) else str(k2)
                    _cand_cnt = sum(1 for _gh, _info in groups.items() if is_merge_filter_match(_dry_filter_val(_info.key[2]), _eff_filters))
                    _excl_cnt = len(groups) - _cand_cnt
                    click.echo(f"Filter-Auswahl: {_eff_filters} -> {_cand_cnt} Kandidaten, {_excl_cnt} excluded")
                else:
                    click.echo("Filter-Auswahl: alle Gruppen (kein Filter gesetzt)")
                click.echo(f"{'Hash':<20} {'EXPTIME':<10} {'GAIN':<8} {'FILTER':<15} {'Frames':<8} {'Total Exp':<12} {'MERGE':<22}")
                click.echo("-" * 97)
                for gh, info in groups.items():
                    _raw_fv = info.key[2]
                    _fv_for_match = None if _raw_fv in ("none", "", None) else str(_raw_fv)
                    _is_cand = is_merge_filter_match(_fv_for_match, _eff_filters) if _eff_filters is not None else True
                    _status = "KANDIDAT" if _is_cand else "excluded (filter_excluded)"
                    click.echo(f"{gh:<20} {info.key[0]:<10} {info.key[1]:<8} {str(info.key[2]):<15} {info.frame_count:<8} {info.total_exposure:<12.1f} {_status:<22}")
                # Show reference group
                mg_config = ctx.obj["config"].multi_group
                if mg_config is None:
                    mg_config = MultiGroupConfig()
                ref_strategy = mg_config.reference_group
                # FSM-B/C: Referenz nur unter Kandidaten (OQ-FSM-1 A frueh) — dry-run transparent
                if _eff_filters is not None:
                    def _dry_filter_val2(k2):
                        return None if k2 in ("none", "", None) else str(k2)
                    _cand_groups = {gh: info for gh, info in groups.items() if is_merge_filter_match(_dry_filter_val2(info.key[2]), _eff_filters)}
                    if _cand_groups:
                        ref_hash = ProcessingAgent._select_reference_group(_cand_groups, ref_strategy)
                    else:
                        ref_hash = "(keine Kandidaten — Merge wuerde geskippt)"
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
        # bleibt oben (informativ, Exit 0) — nur echte Runs brechen ab.
        if context.total_light_frames == 0:
            logger.error("cli.process.no_light_frames",
                         target=str(target_dir), lights=0)
            click.echo(
                "[FAIL] No light frames found in target directory — nothing to process",
                err=True,
            )
            sys.exit(2)

        # V1.7-5 (Always Multi-Group): Der fruehere V1.3-4-Warnblock
        # ("laeuft als Einzel-Stack" bei >1 Gruppe ohne --multi-group) ist
        # obsolet — es gibt keinen Einzel-Stack-Pfad mehr, jede Gruppenzahl
        # laeuft vereinheitlicht durch process_multi_group.

        # Phase 2: Calibration
        logger.info("phase.calibration.start")
        if effective_no_calib:
            # T2: --no-calib — vor-kalibrierte Lights gehen direkt zu
            # Debayer/Processing; kein cal_agent.run(), keine Darks/Flats/Bias.
            logger.info("phase.calibration.skipped", reason="no_calib")
            calibration_result = CalibrationResult(
                working_dir=working_dir,
                calibrated_lights=[f.path for f in context.get_lights().frames],
            )
        else:
            # W5: Darks Library - CLI --darks-path overrides Config darks_repository
            # Leo-Auftrag 2026-08-11 (B2): --darks-path ist optional — ohne
            # CLI-Flag wird `darks_repository` aus der Config verwendet.
            # Im normalen process-Pfad laesst wir das dem CalibrationAgent
            # (V1.8-4 Regression-Fix: kein fruehes CLI-Gate). Der harte
            # Darks-Abort bleibt im --preflight-Pfad erhalten, wo er als
            # Pre-Flight-Check fachlich korrekt ist. --no-calib ueberspringt
            # diesen komplett (siehe effective_no_calib oben).
            effective_darks_path = darks_path or cfg.darks_repository
            if preflight and effective_darks_path is None:
                raise click.ClickException(
                    "Kein Darks-Pfad gesetzt: Kalibration benoetigt Darks. "
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
        # — deaktiviert liefert run() None und die Pipeline bleibt v1.3-
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
        # dieser Phase (oben, nach der Discovery) — hier nur die Uebergabe.
        debayer_result.stack_scale_factor = resolved_ssf_final
        debayer_result.stack_scale_factor_source = ssf_source
        logger.info("phase.debayer.complete", count=len(debayer_result.debayered_frames))
        # Phase 4: Processing (registration, stacking, stretch, export)
        processing_agent = create_processing_agent(working_dir, cfg)
        # V1.5-12 (W3): --pixel-scale CLI-Override an den ProcessingAgent.
        if pixel_scale is not None:
            processing_agent.pixel_scale_override = pixel_scale

        # V1.7-5 (Always Multi-Group, AC-B1/B2): Es gibt nur noch EINEN
        # Verarbeitungspfad — process_multi_group fuer jede Gruppenzahl
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
        # V1.7-1 FSM-A (AC-FSM-A2/A3, OQ-FSM-2 A): CLI --merge-filter (wiederholbar,
        # case-insensitive getrimmt) gewinnt gegen Config (Precedence CLI > Config).
        # Normalisierung zentral in normalize_merge_filters (loader) — ein Ort.
        from .config.loader import normalize_merge_filters
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
        # kommt in Batch B — hier nur Config/CLI korrekt resolved.
        # Logge effektive Filter fuer Debugging (additiv, kein Ballast bei None).
        if mg_config.merge.filters is not None:
            logger.info("cli.process.merge_filter", filters=mg_config.merge.filters)

        # V1.6 (stella/Boris 2026-08-20): PCC per Group vs. Merged Stack
        # Precedence: CLI > Config > Default(false).
        if pcc_per_group is not None:
            mg_config.pcc_per_group = pcc_per_group

        # V1.7-5 (AC-B6): Merge per Default AN (--no-merge deaktiviert) —
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


@cli.command()
@click.argument("data_root", type=click.Path(exists=True, path_type=Path))
@click.option("--preset", "-p", default="star_standard", help="Default preset for all targets")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def batch(ctx, data_root, preset, dry_run):
    """Process all subdirectories in data root."""
    cfg: AppConfig = ctx.obj["config"]
    
    targets = [d for d in Path(data_root).iterdir() if d.is_dir()]
    click.echo(f"Found {len(targets)} targets")
    
    for target in targets:
        click.echo(f"\n--- Processing {target.name} ---")
        ctx.invoke(process, target_path=target, preset=preset, dry_run=dry_run)


@cli.command()
@click.option("--non-interactive", is_flag=True, help="Nicht-interaktiv: via Flags/Env-Vars, keine Prompts (CI-fahig)")
@click.option("--project-dir", type=click.Path(path_type=Path), help="Astra Project Dir (Default: aktuelles Verzeichnis)")
@click.option("--data-root", type=click.Path(path_type=Path), help="Data Root (Default: C:/Astra)")
@click.option("--darks-library", type=click.Path(path_type=Path), help="Darks Library (Default: C:/Astra/_darks)")
@click.option("--preset", "init_preset", type=click.Choice(["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]), help="Default Preset")
@click.option("--cosmetic/--no-cosmetic", "cosmetic", default=None, help="Cosmetic Default aktivieren/deaktivieren")
@click.option("--config-output", type=click.Path(path_type=Path), help="Ziel fur config.yaml (Default: ./config.yaml)")
@click.pass_context
def init(ctx, non_interactive, project_dir, data_root, darks_library, init_preset, cosmetic, config_output):
    """Initialize Astra configuration (Wizard).

    Interaktiv fragt der Wizard nach Astra Project Dir, Data Root (C:\\Astra),
    Darks Library (C:\\Astra\\_darks), Default Preset und Cosmetic Default
    und schreibt config.yaml + environment.yaml (Pydantic-validiert).

    Mit --non-interactive werden Flags/Env-Vars verwendet (CI-fahig), ohne Prompts.
    Env-Vars: ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, ASTRA_DEFAULT_PRESET.
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
            raise ValueError(f"Preset {v!r} unbekannt")

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
        cos_str = _ask("Cosmetic Default aktivieren? (y/n)", default=cosmetic_default)
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
# CLI-B — astra config Subcommands
# ─────────────────────────────────────────────────────────────────
@cli.group()
def config():
    """Konfiguration verwalten (Precedence CLI>Config>Env>Default)."""


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
@click.option("--json", "as_json", is_flag=True, help="Maschinenlesbare Ausgabe (JSON)")
@click.pass_context
def config_show(ctx, as_json):
    """Zeigt gesamte Config (merged Default+User+Env) — Precedence CLI>Config>Env>Default."""
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
            console.print(Panel("Astra Config (merged) — Precedence: CLI > Config > Env > Default", style="cyan"))
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
    """Holt einzelnen Config-Wert via dot-notation (z.B. data_root, multi_group.merge.method)."""
    cfg: AppConfig = ctx.obj["config"]
    data = cfg.model_dump(mode="json")
    val = _get_nested(data, key)
    if val is None:
        # also try direct attribute
        if hasattr(cfg, key):
            val = getattr(cfg, key)
        else:
            raise click.ClickException(f"Key '{key}' nicht gefunden")
    if isinstance(val, (dict, list)):
        click.echo(json.dumps(val, indent=2, default=str))
    else:
        click.echo(str(val))

@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx, key, value):
    """Setzt Config-Wert (validiert via Pydantic, invalid -> Error) und speichert config.yaml."""
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
        raise click.ClickException(f"Validierung fehlgeschlagen fur '{key}={value}': {e}")
    # Write back
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
    click.echo(f"Set {key}={parsed} in {cfg_path}")

@config.command("reset")
@click.argument("key")
@click.pass_context
def config_reset(ctx, key):
    """Setzt Key zurueck auf Default (entfernt aus config.yaml)."""
    cfg_path = _find_config_file(ctx)
    raw = _load_raw_config_file(cfg_path)
    parts = key.split(".")
    cur = raw
    for p in parts[:-1]:
        if p not in cur:
            raise click.ClickException(f"Key '{key}' nicht gefunden")
        cur = cur[p]
    if parts[-1] not in cur:
        raise click.ClickException(f"Key '{key}' nicht gefunden")
    del cur[parts[-1]]
    # Clean empty parents?
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
    click.echo(f"Reset {key} (Default) in {cfg_path}")

@config.command("wizard")
@click.pass_context
def config_wizard(ctx):
    """TUI Wizard fuer Config (interaktiv)."""
    ctx.invoke(init)


# ─────────────────────────────────────────────────────────────────
# CLI-D — astra darks Management
# ─────────────────────────────────────────────────────────────────
@cli.group()
def darks():
    """Darks-Bibliothek verwalten (sync/list/check/import)."""


@darks.command("sync")
@click.option("--dry-run", is_flag=True, help="Zeigt was kopiert wuerde, ohne zu kopieren")
@click.option("--source", "source_path", type=click.Path(path_type=Path), help="Quelle (Default: C:/Dwarflab/CALI_FRAME/dark/cam_0)")
@click.option("--dest", "dest_path", type=click.Path(path_type=Path), help="Ziel (Default: C:/Astra/_darks)")
@click.pass_context
def darks_sync(ctx, dry_run, source_path, dest_path):
    """Sync DwarfLab Export -> Darks Library (nur TELE/cam_0, kein WIDE/cam_1)."""
    cfg: AppConfig = ctx.obj["config"]
    src = Path(source_path) if source_path else Path("C:/Dwarflab/CALI_FRAME/dark/cam_0")
    dst = Path(dest_path) if dest_path else (cfg.darks_repository or Path("C:/Astra/_darks"))
    # Filter: nur cam_0 (TELE), kein cam_1 (WIDE)
    if "cam_1" in str(src) or "WIDE" in str(src):
        raise click.ClickException("Sync nur fur TELE/cam_0, nicht WIDE/cam_1")
    if not src.exists():
        click.echo(f"Quelle {src} existiert nicht — nichts zu syncen (dry-run Mock ok)")
        if dry_run:
            click.echo("[DRY-RUN] Wuerde Darks syncen: 0 Dateien")
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
        click.echo(f"[DRY-RUN] Wuerde {len(actions)} Darks kopieren: {src} -> {dst}")
        for s, d in actions[:10]:
            click.echo(f"  {s.name} -> {d}")
        if len(actions) > 10:
            click.echo(f"  ... +{len(actions)-10} weitere")
    else:
        copied = 0
        for s, d in actions:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
            copied += 1
        click.echo(f"Sync complete: {copied} Darks kopiert ({len(actions)-copied} bereits vorhanden) -> {dst}")
    logger.info("cli.darks.sync", source=str(src), dest=str(dst), dry_run=dry_run, actions=len(actions))

@darks.command("list")
@click.pass_context
def darks_list(ctx):
    """Listet Darks in Library."""
    cfg: AppConfig = ctx.obj["config"]
    dst = cfg.darks_repository or Path("C:/Astra/_darks")
    if not dst.exists():
        click.echo(f"Darks Library nicht gefunden: {dst}")
        return
    subs = sorted([d for d in dst.iterdir() if d.is_dir()])
    if not subs:
        click.echo("Keine Darks gefunden")
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
    """Prueft Dark-Abdeckung fuer Target."""
    cfg: AppConfig = ctx.obj["config"]
    target_dir = Path(target).resolve()
    try:
        context = build_observation_context(target_dir, target_name=target_dir.name) if target_dir.exists() else None
    except Exception:
        context = None
    dst = cfg.darks_repository or Path("C:/Astra/_darks")
    click.echo(f"Target: {target_dir}")
    click.echo(f"Darks Library: {dst} ({'exists' if dst.exists() else 'missing'})")
    if context:
        click.echo(f"Lights: {context.total_light_frames}")
        groups = context.get_lights().group_by_params()
        for gk, fs in groups.items():
            exptime, gain, flt = gk
            sub = dst / f"{int(float(exptime))}s{gain}"
            avail = len(list(sub.glob("*.fit*"))) if sub.exists() else 0
            click.echo(f"  Group {gk}: {fs.frames.__len__()} frames -> {sub.name}: {avail} Darks {'OK' if avail else 'MISSING'}")

@darks.command("import")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Dry-run")
@click.pass_context
def darks_import(ctx, path, dry_run):
    """Importiert Darks aus Pfad in Library."""
    cfg: AppConfig = ctx.obj["config"]
    dst = cfg.darks_repository or Path("C:/Astra/_darks")
    src = Path(path)
    files = list(src.rglob("*.fit*")) if src.is_dir() else [src]
    # Filter only TELE/cam_0: skip WIDE/cam_1
    filtered = [p for p in files if "cam_1" not in str(p) and "WIDE" not in str(p)]
    if dry_run:
        click.echo(f"[DRY-RUN] Wuerde {len(filtered)} Darks importieren -> {dst}")
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
# CLI-E — astra target Management
# ─────────────────────────────────────────────────────────────────
@cli.group()
def target():
    """Target-Verwaltung (list/add/show/update/remove)."""


@target.command("list")
@click.option("--json", "as_json", is_flag=True, help="Maschinenlesbare Ausgabe (JSON)")
@click.pass_context
def target_list(ctx, as_json):
    """Listet alle Targets + Fortschritt."""
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
            click.echo(f"Keine Targets in {data_root}")

@target.command("add")
@click.argument("name")
@click.option("--preset", type=click.Choice(["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]), help="Preset")
@click.option("--non-interactive", is_flag=True, help="Nicht-interaktiv")
@click.pass_context
def target_add(ctx, name, preset, non_interactive):
    """Legt neues Target an und erzeugt AUFNAHMELISTE_{Target}.md Template."""
    cfg: AppConfig = ctx.obj["config"]
    data_root = cfg.data_root
    target_dir = data_root / name
    if target_dir.exists():
        raise click.ClickException(f"Target existiert bereits: {target_dir}")
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
    """Zeigt Details zu Target."""
    cfg: AppConfig = ctx.obj["config"]
    data_root = cfg.data_root
    td = data_root / name
    if not td.exists():
        raise click.ClickException(f"Target nicht gefunden: {td}")
    try:
        context = build_observation_context(td, target_name=name)
        click.echo(f"Target: {name}")
        click.echo(f"  Path: {td}")
        click.echo(f"  Lights: {context.total_light_frames}")
        click.echo(f"  Type: {context.target.target_type.value}")
    except Exception as e:
        click.echo(f"Target: {name} — Fehler beim Lesen: {e}")

@target.command("update")
@click.argument("name")
@click.option("--preset", type=click.Choice(["galaxy_standard", "nebula_standard", "star_standard", "nebula_narrowband"]), help="Neues Preset")
@click.pass_context
def target_update(ctx, name, preset):
    """Aktualisiert Target (z.B. Preset in AUFNAHMELISTE)."""
    cfg: AppConfig = ctx.obj["config"]
    td = cfg.data_root / name
    if not td.exists():
        raise click.ClickException(f"Target nicht gefunden: {td}")
    tpl = td / f"AUFNAHMELISTE_{name}.md"
    if preset and tpl.exists():
        txt = tpl.read_text(encoding="utf-8")
        # Update the two Preset value lines in the AUFNAHMELISTE template without
        # corrupting Markdown bold syntax or leaving the old value behind.
        txt = re.sub(r"(\*\*Preset:\*\*)\s.*", rf"\1 {preset}", txt)
        txt = re.sub(r"(- Preset:)\s.*", rf"\1 {preset}", txt)
        tpl.write_text(txt, encoding="utf-8")
    click.echo(f"Target {name} aktualisiert")

@target.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Ohne Rueckfrage loeschen")
@click.pass_context
def target_remove(ctx, name, yes):
    """Entfernt Target (optional)."""
    cfg: AppConfig = ctx.obj["config"]
    td = cfg.data_root / name
    if not td.exists():
        raise click.ClickException(f"Target nicht gefunden: {td}")
    if not yes:
        if not click.confirm(f"Target {name} wirklich entfernen?"):
            click.echo("Abgebrochen")
            return
    shutil.rmtree(td)
    click.echo(f"Target {name} entfernt")


# ─────────────────────────────────────────────────────────────────
# CLI-F — astra status
# ─────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Maschinenlesbare Ausgabe (JSON)")
@click.pass_context
def status(ctx, as_json):
    """Zeigt System-Status (Disk, letzte Runs, Darks Library, Config Health, Queue)."""
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
    # Last runs: scan generated
    last_runs = []
    if data_root.exists():
        for tgt in data_root.iterdir():
            if not tgt.is_dir() or tgt.name.startswith("_"):
                continue
            gen = tgt / "generated"
            if gen.exists():
                for ts in sorted(gen.iterdir(), reverse=True)[:2]:
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
            console.print(f"Disk Space: {free_gb:.2f} GB frei von {total_gb:.2f} GB" if free_gb else "Disk: n/a")
            console.print(f"Darks Library: {darks_info}")
            console.print(f"Config Health: {config_health}")
            console.print(f"Queue: {queue_cnt} offene Targets")
            console.print(f"Letzte Runs: {last_runs[:3]}")
        else:
            click.echo(json.dumps(out, indent=2))


@cli.command()
@click.argument("target_path", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True,
              help="Maschinenlesbare Ausgabe (JSON)")
@click.option("--eqmode", is_flag=True, help="Nur EQMODE anzeigen")
@click.option("--frames", is_flag=True, help="Frames detailliert anzeigen")
@click.option("--quality", is_flag=True, help="QF-Metriken (Quality Foundation) anzeigen")
@click.pass_context
def inspect(ctx, target_path, as_json, eqmode, frames, quality):
    """Inspect FITS headers in target directory.

    Zeigt Target-Info, Calibration-Status, Equipment, EQMODE und
    (deprecated) shotsInfo.json-Inhalte an. Mit --json: maschinenlesbare
    JSON-Ausgabe fuer automatisierte Nachbearbeitung.
    """
    from .agents.discovery import find_shots_info, log_shots_info
    from .core.staging import stage_input

    target_dir = target_path.resolve()
    # V1.6-7: shotsInfo.json — deprecated (Dwarf-spezifisch), nur fuer
    # Backward-Compat der inspect-Ausgabe. Nicht in der Pipeline.
    log_shots_info(target_dir)
    # Punkt 3 (Input-Staging): Context NUR aus generated/<ts>/00_input —
    # der Target-Root wird ausschliesslich vom Staging-Schritt gelesen.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    working_dir = target_dir / "generated" / timestamp
    input_dir = stage_input(target_dir, working_dir)
    context = build_observation_context(input_dir, target_name=target_dir.name)

    # V1.7-4 (EQPT-A/D2/B2): Equipment-Aufloesung inkl. Quelle je Feld.
    # Nie abbruchbehaftet — bei Fehler bleibt der v1.6-Equipment-Stand.
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
    # shotsInfo ist kein Pipeline-Feature mehr — nur fuer Backward-Compat
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
        from .agents.discovery import create_discovery_agent as _create_da
        from .config.loader import resolve_frame_selection as _resolve_fs
        from .core.quality import FrameQuality as _FQ, compute_frame_score as _cfs, compute_frame_quality as _cfq
        import math as _math
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
                    import numpy as _np
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
                # V1.7-4 (EQPT-B2/D2): additiv — Aufloesung, Bayer-Pattern,
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

    # shotsInfo.json — deprecated (V1.6-7, Dwarf-spezifisch, nur Backward-Compat)
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
            click.echo(f"  {f.path.name}: ERROR (kein Header)")
            continue
        missing = [field for field in mandatory if getattr(f.header, field, None) is None]
        optional_fields = ["filter_name", "ra", "dec"]
        optional_missing = [field for field in optional_fields if getattr(f.header, field, None) is None]
        if missing:
            click.echo(f"  {f.path.name}: ERROR (fehlt: {', '.join(missing)})")
        elif optional_missing:
            click.echo(f"  {f.path.name}: WARNING (optional fehlt: {', '.join(optional_missing)})")
        else:
            click.echo(f"  {f.path.name}: OK")

    # V1.6-1 (SSOT-C5): Aktive Filename-Patterns anzeigen
    click.echo(f"\nFilename-Patterns: hardcoded Defaults aktiv")

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
        from .agents.discovery import create_discovery_agent as _cda2
        from .config.loader import resolve_frame_selection as _rfs2
        from .core.quality import compute_frame_quality as _cfq2, compute_frame_score as _cfs2, FrameQuality as _FQ2
        import math as _math2
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
        click.echo(f"\nFrame-Selection: {'enabled' if _eff_fs2.enabled else 'disabled'} (keep={_eff_fs2.keep_percentile}%, min_frames={_eff_fs2.min_frames}, weights={_eff_fs2.weights or 'default Gleichverteilung'})")
        if not _groups2:
            click.echo("  (keine Gruppen)")
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
        click.echo(f"Frame-Selection: (Fehler bei Statistik: {_e})")

    # CLI-F inspect extensions: --eqmode / --frames / --quality
    if quality:
        # QF-Metriken explizit (ergaenzt Frame-Selection)
        try:
            from .core.quality import compute_frame_quality as _cfq_q
            import numpy as _np
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
            click.echo(f"Quality: Fehler {_e}")
        # Also mark that quality flag was processed
        click.echo("Quality: QF-Metriken angezeigt (--quality)")
    if eqmode:
        click.echo(f"EQMODE (filtered): {eq_mode_label} (raw={eq_mode_raw})")
    if frames:
        click.echo(f"Frames: {len(lights.frames)} Lights detailliert")
        for f in lights.frames[:10]:
            hdr = f.header
            click.echo(f"  {f.path.name}: exptime={getattr(hdr,'exptime',None)} gain={getattr(hdr,'gain',None)} filter={getattr(hdr,'filter_name',None)}")


@cli.command()
@click.argument("target_path", type=click.Path(exists=True, path_type=Path))
@click.option("--method", type=click.Choice(["weighted_average", "average", "median"]),
              default="weighted_average", help="Merge-Methode")
@click.option("--weight-by", type=click.Choice(["frame_count", "total_exposure"]),
              default="frame_count", help="Gewichtungsmethode")
# V1.7-1 FSM-A (AC-FSM-A4, OQ-FSM-2 A): gleiche Filter-Auswahl im Subcommand
# (Filter-Auswahl auf Header-FILTER-Basis, cli.py Z.925). Wiederholbar,
# gleiche Normalisierung (trim+lower) wie im process-Command.
@click.option("--merge-filter", "merge_filter", multiple=True, type=str,
              help="Filter-Auswahl fuer Merge (wiederholbar, case-insensitive getrimmt, z.B. --merge-filter Astro)")
@click.option("--output", "-o", type=click.Path(path_type=Path),
              help="Output-Verzeichnis (sonst generated/{timestamp}/merged/)")
@click.option("--dry-run", is_flag=True, help="Gruppen anzeigen ohne zu mergen")
@click.pass_context
def merge(ctx, target_path, method, weight_by, merge_filter, output, dry_run):
    """Merge vorhandene Gruppen-Stacks in ein einzelnes FITS.

    Durchsucht generated/{timestamp}/group_*/04_stacked/pcc_applied.fits,
    extrahiert Metadaten aus FITS-Headern und merged alle Gruppen mit
    der angegebenen Methode und Gewichtung.
    """
    target_dir = target_path.resolve()
    target_name = target_dir.name

    # Find latest generated/ timestamp
    generated_dir = target_dir / "generated"
    if not generated_dir.exists():
        raise click.ClickException(
            f"Kein generated/-Verzeichnis gefunden in {target_dir}"
        )

    timestamps = sorted(
        [d for d in generated_dir.iterdir() if d.is_dir()],
        reverse=True,
    )
    if not timestamps:
        raise click.ClickException(
            "Keine Zeitstempel-Verzeichnisse in generated/ gefunden"
        )

    latest_ts = timestamps[0]
    click.echo(f"Scanne: {latest_ts}")

    # Find group directories
    group_dirs = sorted([
        d for d in latest_ts.iterdir()
        if d.name.startswith("group_") and d.is_dir()
    ])
    if not group_dirs:
        raise click.ClickException(
            f"Keine group_-Verzeichnisse gefunden in {latest_ts}"
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
            click.echo(f"  [SKIP] {gd.name}: kein Stack gefunden")
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
                meta["gain"] = h.get("GAIN", 0)
                meta["filter"] = str(h.get("FILTER", ""))
                meta["frame_count"] = int(h.get("MGFRAME", 1))
                meta["total_exposure"] = float(h.get("TOTALEXP", meta["exptime"] * meta["frame_count"]))
                # ray Review Fix 2 (2026-08-21): Marker VOR MG-Headern
                # auswerten — MGCNTGRP allein sagt nur "PCC gelaufen",
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
            # T5 (E1): kein stiller Fehler — Header nicht lesbar, Gruppe wird
            # mit Default-Metadaten weitergefuehrt (MergeAgent meldet den
            # Stack-Fehler separat und liefert einen klaren Exit-Code).
            logger.warning("merge.metadata_read_failed", path=str(fits_path),
                           group=group_hash, error=str(e))

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
    from .config.loader import is_merge_filter_match, resolve_merge_filters
    effective_merge_filters = resolve_merge_filters(ctx.obj["config"], cli_filters=merge_filter)
    # V1.7-1 FSM-C: Transparenz — behalte Original fuer Dry-Run Tabelle (vor Filter)
    _original_group_stacks = dict(group_stacks)
    _original_group_metadata = dict(group_metadata)
    if effective_merge_filters is not None:
        logger.info("cli.merge.filter", filters=effective_merge_filters, total=len(group_stacks))
        # Gefilterte Stacks/Metadata bilden (excluded bleiben als Gruppen-Stacks erhalten,
        # werden nur nicht gemerged — analog pipeline, OQ-FSM-4 A Merge-Skip).
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
            click.echo(f"  Filter aktiv: {effective_merge_filters} -> {len(filtered_stacks)} Kandidaten, {len(excluded_hashes)} excluded")
        # V1.7-1 FSM-C3: Tippfehler-Warning — Filterwert matcht keine Gruppe
        _group_norm_filters_merge = set()
        for _meta_m in _original_group_metadata.values():
            _fv_m = _meta_m.get("filter")
            _cand_m = "" if _fv_m is None else str(_fv_m).strip().lower()
            _group_norm_filters_merge.add(_cand_m)
        for _flt_m in set(effective_merge_filters):
            if _flt_m not in _group_norm_filters_merge:
                logger.warning(
                    "cli.merge.merge_filter_no_match",
                    filter=_flt_m,
                    effective=effective_merge_filters,
                    groups=sorted(_group_norm_filters_merge),
                    hint="Verdacht Tippfehler: Filter-Wert passt zu keiner Gruppe",
                )
                click.echo(f"  [WARN] Filter '{_flt_m}' passt zu keiner Gruppe (Verdacht Tippfehler) — verfuegbar: {sorted(_group_norm_filters_merge)}", err=True)
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
                click.echo(f"Filter-Auswahl: {effective_merge_filters} -> {len(group_stacks)} Kandidaten, {len(_original_group_metadata) - len(group_stacks)} excluded")
            else:
                click.echo("Filter-Auswahl: alle Gruppen (kein Filter gesetzt)")
            click.echo(f"{'Hash':<20} {'FILTER':<15} {'Frames':<8} {'MERGE':<22}")
            click.echo("-" * 67)
            for gh in sorted(_original_group_metadata.keys()):
                meta = _original_group_metadata[gh]
                _is_cand_m = is_merge_filter_match(meta.get("filter"), effective_merge_filters) if effective_merge_filters is not None else True
                _status_m = "KANDIDAT" if _is_cand_m else "excluded (filter_excluded)"
                click.echo(f"{gh:<20} {str(meta.get('filter') or '-'):<15} {meta.get('frame_count', 1):<8} {_status_m:<22}")
        return

    if len(group_stacks) < 2:
        raise click.ClickException(
            f"Mindestens 2 Gruppen fuer Merge benoetigt, gefunden: {len(group_stacks)}"
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
            click.echo(f"     Kopiert nach: {out_dir}")
    else:
        raise click.ClickException("Merge fehlgeschlagen")


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
@click.option("--fix", is_flag=True, help="Auto-fixt fehlende Dir, Config-Defaults, Dark-Struktur")
@click.pass_context
def doctor(ctx, target_path, fix):
    """Umgebungs-Check: Python, Dependencies, GAIA, Config, Disk, Pfade. Read-only.

    Optional TARGET_PATH: prueft zusaetzlich die Equipment-Versorgung des
    Targets (V1.7-4, AC-EQPT-D3) — welche Header-Werte vorhanden sind,
    welches Config-Profil greifen wuerde und welche Felder komplett fehlen.

    Exit-Codes: 0 = OK, 1 = Warnungen, 2 = kritische Fehler.
    Der Command ist read-only — es werden KEINE Verzeichnisse/Dateien
    angelegt oder veraendert.
    """
    counts = {"ok": 0, "warn": 0, "fail": 0}

    def _report(name: str, level: str, message: str) -> None:
        counts[level] += 1
        click.echo(f"[{level.upper()}] {message}")
        logger.info(f"doctor.check.{name}", status=level, message=message)

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
        # Wir loggen WARN aber zaehlen nicht als fail; Output enthaelt WARN
        click.echo("[WARN] doctor.env_missing: .env not found, using defaults (kopiere .env.example -> .env)")
        logger.warning("doctor.env_missing", detail=".env not found, using defaults")
        # Optional --fix: lege .env aus .env.example an
        if fix:
            try:
                from .config.loader import _pipeline_root as _pr
                example = _pr() / ".env.example"
                target_env = Path.cwd() / ".env"
                if example.is_file() and not target_env.exists():
                    shutil.copy2(example, target_env)
                    click.echo(f"[FIX] .env erstellt aus {example} -> {target_env}")
                    logger.info("doctor.env_fix", source=str(example), target=str(target_env))
            except Exception as e:
                click.echo(f"[FIX FAIL] .env: {e}", err=True)
    else:
        _report("env", "ok", f".env gefunden: {', '.join(_env_paths)}")

    # 1. Python-Version (kritisch)
    # Bewusste Laufzeit-Validierung trotz Paket-Min >=3.11: doctor ist eine
    # Umgebungsdiagnose und muss eine zu alte Python-Umgebung als FAIL/Exit-2
    # melden. UP036-Fix wuerde dieses Verhalten entfernen -> noqa.
    if sys.version_info >= (3, 11):  # noqa: UP036
        _report("python", "ok",
                f"Python {sys.version_info[0]}.{sys.version_info[1]} (>= 3.11 noetig)")
    else:
        _report("python", "fail",
                f"Python {sys.version_info[0]}.{sys.version_info[1]} < 3.11 (kritisch)")

    # 2. Core-Dependencies (kritisch)
    core_deps = ["astropy", "numpy", "scipy", "pydantic",
                 "pydantic_settings", "click", "structlog", "yaml", "jinja2"]
    for dep in core_deps:
        try:
            __import__(dep)
            _report(f"dep.{dep}", "ok", f"{dep} importierbar")
        except ImportError:
            _report(f"dep.{dep}", "fail", f"{dep} fehlt (kritisch)")

    # 3. Optional-Dependencies (WARN: Feature deaktiviert / Fallback aktiv)
    # AC-W9-A3: listet ALLE drei W9-A-Dependencies (astroalign, sep,
    # scikit-image) — nur astroalign zu melden wuerde den Check taeuschen.
    # (name, import_module): Dist-Name fuer Ausgabe, Modul-Name fuer Import
    # (scikit-image -> skimage, dist != module).
    optional_deps = [
        ("astroquery", "astroquery"),
        ("sep", "sep"),
        ("astroalign", "astroalign"),
        ("scikit-image", "skimage"),
    ]
    optional_dep_messages = {
        "astroquery": "fehlt (GAIA-PCC deaktiviert / Gray-World-Fallback)",
        "sep": "fehlt (astroalign-Stern-Detection deaktiviert; GAIA-PCC/Gray-World-Fallback aktiv)",
        "astroalign": 'fehlt (W9-Registration im fft-Fallback; Extra: "astra[astroalign]")',
        "scikit-image": "fehlt (W9-Registration im fft-Fallback; Pflicht-Dep astroalign-Extra)",
    }
    for name, module in optional_deps:
        try:
            __import__(module)
            _report(f"dep.{name}", "ok", f"{name} importierbar")
        except ImportError:
            _report(f"dep.{name}", "warn",
                    f"{name} {optional_dep_messages.get(name, 'fehlt (Fallback aktiv)')}")

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
                # gemeldet — kein stummer Thread-Crash, PCC-Fallback aktiv.
                from astroquery.gaia import Gaia as _query_gaia
                return _query_gaia.launch_job("SELECT TOP 1 ra FROM gaiadr3.gaia_source")

            _run_with_timeout(_mini_query, 10.0)
            _report("gaia", "ok", "GAIA erreichbar (astroquery)")
        except TimeoutError:
            _report("gaia", "warn", "GAIA Query Timeout nach 10s (PCC-Fallback aktiv)")
        except ImportError as e:
            _report("gaia", "warn", f"astroquery.gaia nicht importierbar: {e}")
        except Exception as e:  # noqa: BLE001 - Verbindungs-/Query-Fehler sind WARN
            _report("gaia", "warn", f"GAIA nicht erreichbar: {e}")

    # 5. Config gueltig (kritisch)
    cfg = None
    try:
        cfg = load_config(ctx.obj.get("config_path"))
        preset = cfg.get_preset(cfg.default_preset)
        if preset is None:
            _report("config", "fail",
                    f"Config ungueltig: Preset '{cfg.default_preset}' nicht aufloesbar (kritisch)")
        else:
            _report("config", "ok", f"Config gueltig (Preset: {preset.name})")
    except Exception as e:  # noqa: BLE001 - ungueltige Config ist kritisch
        _report("config", "fail", f"Config ungueltig: {e} (kritisch)")

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
                    f"Mandatory-Fields unbekannt: {', '.join(aliases_unknown)}")
        else:
            _report("mandatory_validation", "ok",
                    f"Mandatory-Validation: {', '.join(mandatory_fields)} — "
                    f"Aliases abgedeckt: {', '.join(aliases_covered)}")

        # V1.7-4 (AC-EQPT-D3): Equipment-Versorgung.
        # (a) Config-Seite (immer): welche Profile wuerden greifen?
        profiles = list(cfg.equipment_profiles or [])
        if not profiles:
            _report("equipment.config_profiles", "warn",
                    "Keine equipment_profiles konfiguriert — fehlende "
                    "Header-Felder bleiben ohne Fallback leer")
        else:
            names = ", ".join(p.name for p in profiles)
            has_default = any(
                str(p.name).lower() == "default" for p in profiles
            )
            if has_default:
                _report("equipment.config_profiles", "ok",
                        f"Config-Profile vorhanden: {names} "
                        "(Fallback-Profil 'default' existiert)")
            else:
                _report("equipment.config_profiles", "warn",
                        f"Config-Profile vorhanden: {names} — kein Profil "
                        "'default' (Substring-Fallback ohne Match liefert "
                        "keine Werte)")

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
                    f"Config ({eq.profile_name or 'kein Profil'}): "
                    f"[{', '.join(config_fields) or '-'}]"
                )
                if missing_fields:
                    _report("equipment.supply", "warn",
                            f"Equipment-Felder komplett ohne Quelle: "
                            f"{', '.join(missing_fields)} — {detail}")
                elif config_fields:
                    _report("equipment.supply", "warn",
                            f"Equipment nicht vollstaendig aus Headern — "
                            f"Config-Profil greift fuer: "
                            f"{', '.join(config_fields)} | {detail}")
                else:
                    _report("equipment.supply", "ok",
                            f"Equipment vollstaendig aus Headern | {detail}")
            except Exception as e:  # noqa: BLE001 - Diagnose, nie Abbruch
                _report("equipment.supply", "warn",
                        f"Equipment-Check fehlgeschlagen: {e}")

        # V1.7-2 FSEL-D4: Frame-Selection Status (aktiv/inaktiv + Gewichte).
        # L4: Touchpoint doctor — zeigt ob aktiv und welche Gewichte gelten,
        # sowie Rejection-Status fuer den Trichter-Vergleich (C1: Perzentil → Threshold).
        try:
            from .config.loader import resolve_frame_selection as _rfs_doc
            from .config.models import FrameSelectionConfig as _FSC_doc
            _preset_doc = cfg.get_preset(cfg.default_preset)
            if _preset_doc is None and cfg.pipeline_presets:
                _preset_doc = cfg.pipeline_presets[0]
            if _preset_doc is not None:
                _eff_fs_doc = _rfs_doc(cfg, _preset_doc)
                _weights_str = str(_eff_fs_doc.weights) if _eff_fs_doc.weights else "default Gleichverteilung (snr, star_count, fwhm_median, elongation_ratio)"
                if _eff_fs_doc.enabled:
                    _report("frame_selection", "ok",
                            f"Frame-Selection AKTIV (keep={_eff_fs_doc.keep_percentile}%, min_frames={_eff_fs_doc.min_frames}, weights={_weights_str})")
                else:
                    _report("frame_selection", "ok",
                            f"Frame-Selection inaktiv (Default aus, keep={_eff_fs_doc.keep_percentile}%, min_frames={_eff_fs_doc.min_frames}, weights={_weights_str}) — opt-in via Config/Preset/CLI (--frame-selection)")
                # Rejection-Status fuer Trichter-Vergleich (AC-FSEL-C1..C3, unabhaengige Schalter)
                from .agents.multi_group_agent import _resolve_rejection_config as _rrc_doc
                try:
                    _rej_e, _rej_thresh, _rej_elong = _rrc_doc(_preset_doc.processing_params.model_dump(), cfg)
                    if _rej_e:
                        _report("rejection", "ok", f"Outlier-Rejection AKTIV (thresholds={_rej_thresh}, elongation={_rej_elong}) — Funnel: Perzentil → Threshold (AC-FSEL-C1)")
                    else:
                        _report("rejection", "ok", "Outlier-Rejection inaktiv (Default aus)")
                except Exception:
                    pass
            else:
                _report("frame_selection", "warn", "Kein Preset fuer Frame-Selection-Check verfuegbar")
        except Exception as e:  # noqa: BLE001 - Diagnose
            _report("frame_selection", "warn", f"Frame-Selection-Check fehlgeschlagen: {e}")

        # 6. Disk-Space (nur wenn data_root existiert; sonst ueberspringen,
        #    der FAIL kommt von Check 7)
        if data_root.exists():
            try:
                usage = shutil.disk_usage(data_root)
                free_gb = usage.free / (1024 ** 3)
                if free_gb < 1.0:
                    _report("disk", "fail",
                            f"Weniger als 1 GB frei auf {data_root}: {free_gb:.2f} GB (kritisch)")
                elif free_gb < 5.0:
                    _report("disk", "warn", f"Nur {free_gb:.2f} GB frei auf {data_root}")
                else:
                    _report("disk", "ok", f"{free_gb:.2f} GB frei auf {data_root}")
            except Exception as e:  # noqa: BLE001
                _report("disk", "fail", f"Disk-Check fehlgeschlagen: {e} (kritisch)")

        # 7. Pfade
        if data_root.exists():
            _report("paths.data_root", "ok", f"data_root existiert: {data_root}")
            try:
                targets = [d for d in data_root.iterdir() if d.is_dir()]
                click.echo(f"   Targets: {len(targets)} Unterverzeichnisse")
            except Exception:  # noqa: BLE001 - nur Info
                click.echo("   Targets: (nicht lesbar)")
        else:
            _report("paths.data_root", "fail",
                    f"data_root existiert nicht: {data_root} (kritisch)")

        if cfg.darks_repository is not None:
            if cfg.darks_repository.exists():
                _report("paths.darks_repository", "ok",
                        f"darks_repository existiert: {cfg.darks_repository}")
            else:
                _report("paths.darks_repository", "warn",
                        f"darks_repository existiert nicht: {cfg.darks_repository}")

        # CLI-F --fix: auto-fix
        if fix and cfg is not None:
            fixed = []
            # 1. fehlende Dirs anlegen
            for p in [data_root, cfg.darks_repository] if cfg.darks_repository else [data_root]:
                if p and not p.exists():
                    try:
                        p.mkdir(parents=True, exist_ok=True)
                        fixed.append(f"Dir erstellt: {p}")
                        click.echo(f"[FIX] Dir erstellt: {p}")
                    except Exception as e:
                        click.echo(f"[FIX FAIL] {p}: {e}", err=True)
            # 2. Config-Defaults: falls kein equipment_profiles, Default anlegen? Write back default config if missing file
            cfg_path = ctx.obj.get("config_path")
            # try cwd config
            cwd_cfg = Path.cwd() / "config.yaml"
            if not cwd_cfg.exists():
                try:
                    from .config.loader import save_default_config
                    save_default_config(cwd_cfg)
                    fixed.append(f"Config erstellt: {cwd_cfg}")
                    click.echo(f"[FIX] Config erstellt: {cwd_cfg}")
                except Exception:
                    pass
            # 3. Dark-Struktur: ensure subdirs exist per config
            if cfg.darks_repository and cfg.darks_repository.exists():
                # ensure no WIDE/cam_1 leakage placeholder? just report
                pass
            if fixed:
                click.echo(f"[FIX] {len(fixed)} Probleme behoben")
            else:
                click.echo("[FIX] Nichts zu fixen")

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
    """Plugin-Verwaltung (v1.2, PL-C): Pipeline-Step-Plugins der
    Entry-Point-Gruppe ``astra.plugins``."""


@plugin.command("list")
@click.option("--json", "as_json", is_flag=True,
              help="Maschinenlesbare Ausgabe (JSON)")
@click.pass_context
def plugin_list(ctx, as_json):
    """Listet registrierte Pipeline-Step-Plugins (PL-C).

    Exit-Codes: 0 = OK (auch ohne installierte Plugins), 1 = Discovery-Fehler.
    """
    from .core.plugins import default_registry

    registry = default_registry()
    try:
        plugins = registry.plugins
    except Exception as e:  # noqa: BLE001 - Discovery-Fehler sind Exit 1
        click.echo(f"[FAIL] Plugin-Discovery fehlgeschlagen: {e}", err=True)
        ctx.exit(1)

    # "Gehandhabte Steps": alle Preset-Step-Namen der geladenen Config, die
    # das Plugin via handles() akzeptiert (Kern-Steps kennt es nicht — sonst
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
        click.echo("Keine Plugins installiert (Entry-Point-Gruppe: astra.plugins)")
        ctx.exit(0)

    for entry in entries:
        steps = ", ".join(entry["steps"]) if entry["steps"] else "-"
        click.echo(f"{entry['name']} {entry['version']} — Steps: {steps}")
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


if __name__ == "__main__":
    cli()
