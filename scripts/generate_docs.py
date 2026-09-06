#!/usr/bin/env python3
"""
Astra Documentation Generator

Generates user-facing documentation from source code (SSOT).
Run: python scripts/generate_docs.py [subcommand]

Subcommands:
    cli         Generate CLI Reference (03-cli-reference.md)
    config      Generate Config Reference (04-configuration.md)
    presets     Generate Presets Doc (05-presets.md)
    arch        Generate Architecture Doc (02-pipeline-architecture.md)
    index       Generate Docs Index (INDEX.md)
    all         Generate all docs (default)
    check       Verify docs are up-to-date (CI hook)
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

# ─── Paths ──────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
SRC_DIR = REPO_ROOT / "src" / "astro_process"
DOCS_DIR = REPO_ROOT / "docs"
CONFIG_YAML = REPO_ROOT / "config.yaml"
DOC_DATA_DIR = Path(__file__).parent / "doc_data"

# ─── Deterministic English translation maps ─────────────────────────────
# cli.py help strings are German; the generator emits English by looking up
# the exact German source string here. Any missing string falls back to a
# generic English description built from the flag/command name.
CLI_HELP_EN: dict[str, str] = {
    # command help
    "Process a single target directory.\n\n    Hinweis (Docs regen 2026-08-11, B3): --config/-c ist eine GLOBALE\n    Option und muss vor dem Subcommand stehen, z.B.:\n        astro-process --config config.yaml process <target>\n    Ohne --config sucht die Pipeline automatisch nach config.yaml im\n    aktuellen Verzeichnis (CWD) bzw. im Projekt-Root.\n    ": "Process a single target directory. The global --config/-c option must be placed before the subcommand, e.g. `astra --config config.yaml process <target>`. Without --config the pipeline searches for config.yaml in the current working directory or project root.",
    "Process all subdirectories in data root.": "Process all subdirectories in the data root.",
    "Initialize Astra configuration (Wizard).\n\n    Interaktiv fragt der Wizard nach Astra Project Dir, Data Root (C:\\Astra),\n    Darks Library (C:\\Astra\\_darks), Default Preset und Cosmetic Default\n    und schreibt config.yaml + environment.yaml (Pydantic-validiert).\n\n    Mit --non-interactive werden Flags/Env-Vars verwendet (CI-fahig), ohne Prompts.\n    Env-Vars: ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, ASTRA_DEFAULT_PRESET.\n    ": "Initialize Astra configuration via an interactive wizard. The wizard asks for the project directory, data root, darks library, default preset, and cosmetic default, then writes config.yaml and environment.yaml (Pydantic-validated). With --non-interactive, flags and environment variables are used instead of prompts (CI-friendly). Env vars: ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, ASTRA_DEFAULT_PRESET.",
    "Konfiguration verwalten (Precedence CLI>Config>Env>Default).": "Manage configuration (precedence: CLI > Config > Env > Default).",
    "Zeigt gesamte Config (merged Default+User+Env) – Precedence CLI>Config>Env>Default.": "Show the fully merged configuration (defaults + user + env). Precedence: CLI > Config > Env > Default.",
    "Holt einzelnen Config-Wert via dot-notation (z.B. data_root, multi_group.merge.method).": "Get a single configuration value via dot-notation (e.g. data_root, multi_group.merge.method).",
    "Setzt Config-Wert (validiert via Pydantic, invalid -> Error) und speichert config.yaml.": "Set a configuration value (validated via Pydantic; invalid values raise an error) and save config.yaml.",
    "Setzt Key zurueck auf Default (entfernt aus config.yaml).": "Reset a key to its default and remove it from config.yaml.",
    "TUI Wizard fuer Config (interaktiv).": "Interactive TUI configuration wizard.",
    "Darks-Bibliothek verwalten (sync/list/check/import).": "Manage the Darks Library (sync/list/check/import).",
    "Sync DwarfLab Export -> Darks Library (nur TELE/cam_0, kein WIDE/cam_1).": "Sync DwarfLab export into the Darks Library (TELE/cam_0 only, never WIDE/cam_1).",
    "Listet Darks in Library.": "List dark frames in the library.",
    "Prueft Dark-Abdeckung fuer Target.": "Check dark-frame coverage for a target.",
    "Importiert Darks aus Pfad in Library.": "Import dark frames from a path into the library.",
    "Target-Verwaltung (list/add/show/update/remove).": "Target management (list/add/show/update/remove).",
    "Listet alle Targets + Fortschritt.": "List all targets and their progress.",
    "Legt neues Target an und erzeugt AUFNAHMELISTE_{Target}.md Template.": "Create a new target and generate an AUFNAHMELISTE_{Target}.md template.",
    "Zeigt Details zu Target.": "Show details for a target.",
    "Aktualisiert Target (z.B. Preset in AUFNAHMELISTE).": "Update a target (e.g. preset in AUFNAHMELISTE).",
    "Entfernt Target (optional).": "Remove a target (optional).",
    "Zeigt System-Status (Disk, letzte Runs, Darks Library, Config Health, Queue).": "Show system status (disk space, recent runs, darks library, config health, queue).",
    "Inspect FITS headers in target directory.\n\n    Zeigt Target-Info, Calibration-Status, Equipment, EQMODE und\n    (deprecated) shotsInfo.json-Inhalte an. Mit --json: maschinenlesbare\n    JSON-Ausgabe fuer automatisierte Nachbearbeitung.\n    ": "Inspect FITS headers in the target directory. Shows target info, calibration status, equipment, EQMODE, and deprecated shotsInfo.json contents. With --json: machine-readable JSON output for automated post-processing.",
    "Merge vorhandene Gruppen-Stacks in ein einzelnes FITS.\n\n    Durchsucht generated/{timestamp}/group_*/04_stacked/pcc_applied.fits,\n    extrahiert Metadaten aus FITS-Headern und merged alle Gruppen mit\n    der angegebenen Methode und Gewichtung.\n    ": "Merge existing group stacks into a single FITS. Scans generated/{timestamp}/group_*/04_stacked/pcc_applied.fits, extracts metadata from FITS headers, and merges all groups using the chosen method and weighting.",
    "Umgebungs-Check: Python, Dependencies, GAIA, Config, Disk, Pfade. Read-only.\n\n    Optional TARGET_PATH: prueft zusaetzlich die Equipment-Versorgung des\n    Targets (V1.7-4, AC-EQPT-D3) – welche Header-Werte vorhanden sind,\n    welches Config-Profil greifen wuerde und welche Felder komplett fehlen.\n\n    Exit-Codes: 0 = OK, 1 = Warnungen, 2 = kritische Fehler.\n    Der Command ist read-only – es werden KEINE Verzeichnisse/Dateien\n    angelegt oder veraendert.\n    ": "Environment check: Python, dependencies, GAIA, config, disk, paths. Read-only. Optional TARGET_PATH also checks target equipment supply (which header values are present, which config profile would apply, and which fields are completely missing). Exit codes: 0 = OK, 1 = warnings, 2 = critical errors. The command is read-only — no directories or files are created or modified.",
    "Plugin-Verwaltung (v1.2, PL-C): Pipeline-Step-Plugins der\n    Entry-Point-Gruppe ``astra.plugins``.": "Plugin management (v1.2, PL-C): pipeline-step plugins in the ``astra.plugins`` entry-point group.",
    "Listet registrierte Pipeline-Step-Plugins (PL-C).\n\n    Exit-Codes: 0 = OK (auch ohne installierte Plugins), 1 = Discovery-Fehler.\n    ": "List registered pipeline-step plugins (PL-C). Exit codes: 0 = OK (even with no plugins installed), 1 = discovery error.",
    # flag help
    "Processing preset": "Processing preset",
    "Output directory": "Output directory",
    "Show plan without executing": "Show plan without executing",
    "Preserve working directory": "Preserve working directory",
    "Gruppen-Dirs behalten/aufraeumen (Default: aus Config, sonst true)": "Keep or clean up group working directories (default from config, otherwise true)",
    "Resume from last checkpoint": "Resume from last checkpoint",
    "Deprecated No-op (v1.7): Multi-Group ist immer aktiv": "Deprecated no-op (v1.7): Multi-Group is always active",
    "Merge-Schritt aktivieren/deaktivieren (Standard: aktiv)": "Enable or disable the merge step (default: enabled)",
    "Gewichtung fuers Merge (ueberschreibt Config)": "Merge weighting method (overrides config)",
    "Merge-Methode (ueberschreibt Config)": "Merge method (overrides config)",
    "Filter-Auswahl fuer Merge (wiederholbar, case-insensitive getrimmt, z.B. --merge-filter Astro --merge-filter \"Duo-Band\"; ueberschreibt Config)": "Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro --merge-filter \"Duo-Band\"; overrides config)",
    "PCC pro Gruppe (Default: false = PCC auf merged Stack, max S/N)": "Apply PCC per group (default: false = PCC on merged stack for maximum S/N)",
    "Stacking-Methode (ueberschreibt Preset/Config; sonst Mapping aus rejection; sigma_clipped_mean = robustes Sigma-Clipping)": "Stacking method (overrides preset/config; otherwise mapped from rejection; sigma_clipped_mean = robust sigma-clipping)",
    "Registrations-Methode (ueberschreibt Config/Preset)": "Registration method (overrides config/preset)",
    "SanityGuard: max. Rotation in Grad fuer astroalign/rotation_fft (Default 2.0, Feldrotation z.B. 15)": "Sanity guard: maximum rotation in degrees for astroalign/rotation_fft (default 2.0, e.g. 15 for field rotation)",
    "W1-Guard: corr_hp-Schwelle (Default 0.0). fft-Zweig -> Zero-Shift Fallback; astroalign-Gewinner unter Schwelle -> Frame verwerfen": "W1 guard: corr_hp threshold (default 0.0). FFT path falls back to zero-shift; astroalign winner below threshold is rejected.",
    "W1-Guard komplett deaktivieren (weder Zero-Shift-Fallback noch astroalign-Reject unter der Schwelle)": "Completely disable the W1 guard (no zero-shift fallback and no astroalign rejection below threshold)",
    "EQMODE-Override: AZ-Modus erzwingen (ueberschreibt EQMODE-Header)": "EQMODE override: force AZ mode (overrides EQMODE header)",
    "EQMODE-Override: EQ-Modus erzwingen (ueberschreibt EQMODE-Header)": "EQMODE override: force EQ mode (overrides EQMODE header)",
    "Pixel-Skala (arcsec/px) direkt ueberschreiben (ueberschreibt Equipment-Header)": "Override pixel scale (arcsec/px) directly (overrides equipment header)",
    "Structure-Enhancement Radius (Default 3.0 aus Preset-Step)": "Structure-enhancement radius (default 3.0 from preset step)",
    "Structure-Enhancement Amount (Default 0.2 aus Preset-Step)": "Structure-enhancement amount (default 0.2 from preset step)",
    "Gradient Removal aktivieren/deaktivieren (ueberschreibt Config/Preset)": "Enable or disable gradient removal (overrides config/preset)",
    "GR-Polynom-Grad (ueberschreibt Config/Preset)": "Gradient-removal polynomial degree (overrides config/preset)",
    "GR-Sampling-Grid als 'rows,cols' z.B. 16,16 (ueberschreibt Config/Preset)": "Gradient-removal sampling grid as 'rows,cols', e.g. 16,16 (overrides config/preset)",
    "GR-Sigma-Clipping k in k*MAD (ueberschreibt Config/Preset)": "Gradient-removal sigma-clipping k in k*MAD (overrides config/preset)",
    "GR-Mindest-Sample-Zellen fuer den Fit (ueberschreibt Config/Preset)": "Gradient-removal minimum sample cells for the fit (overrides config/preset)",
    "Pfad zur zentralen Darks-Bibliothek (ueberschreibt Config: darks_repository)": "Path to the central Darks Library (overrides config: darks_repository)",
    "Cosmetic Correction aktivieren/deaktivieren (ueberschreibt Config)": "Enable or disable cosmetic correction (overrides config)",
    "Debayer-Methode: superpixel (Default, DADR-003) oder malvar (1920x1080, High-Quality, Malvar2004) oder bilinear (deprecated, use malvar or superpixel, volle Auflösung)": "Debayer method: superpixel (default, DADR-003), malvar (1920x1080 high-quality Malvar2004), or bilinear (deprecated; use malvar or superpixel, full resolution)",
    "Frame-Selection (Perzentil, DwarfLab-Pattern) aktivieren/deaktivieren (ueberschreibt Config/Preset, Default aus)": "Enable or disable frame selection (percentile, DwarfLab pattern; overrides config/preset)",
    "Keep-Perzentil fuer Frame-Selection (1-100, Default 92, nur wenn --frame-selection)": "Keep percentile for frame selection (1-100, default 92, only with --frame-selection)",
    "CFA-Drizzle aktivieren/deaktivieren (2x, nutzt Dwarf Mini Dithering, Default aus)": "Enable or disable CFA drizzle (2x, uses Dwarf Mini dithering)",
    "Drizzle Scale (Default 2.0, 2x = 3840x2160)": "Drizzle scale (default 2.0, 2x = 3840x2160)",
    "Drizzle Pixfrac (0.5-1.0, bei fixed mode, Default auto: <10=1.0, 10-30=0.7, >30=0.5)": "Drizzle pixfrac (0.5-1.0; in fixed mode default auto: <10=1.0, 10-30=0.7, >30=0.5)",
    "Drizzle Kernel (Default lanczos3, gaussian/tophat als Option)": "Drizzle kernel (default lanczos3, gaussian/tophat optional)",
    "Nur Pre-Flight Checks (Hot Pixel Scan, Dark-Passung, Cosmetic Empfehlung) – kein Pipeline-Start": "Run pre-flight checks only (hot-pixel scan, dark matching, cosmetic recommendation) — do not start the pipeline",
    "Bei --preflight: bei OK direkt Pipeline starten": "With --preflight: start the pipeline immediately if checks pass",
    "Kalibrationsphase ueberspringen (vor-kalibrierte Lights). Hinweis: Lights muessen CFA/2D (Bayer-Rohdaten) sein – bereits debayerte 3D-RGB-Lights fuehren beim Debayer-Schritt zu einem Fehler.": "Skip calibration phase (pre-calibrated lights). Note: lights must be CFA/2D Bayer raw data; already-debayered 3D RGB lights will cause an error in the debayer step.",
    "Default preset for all targets": "Default preset for all targets",
    "Nicht-interaktiv: via Flags/Env-Vars, keine Prompts (CI-fahig)": "Non-interactive: use flags/env vars, no prompts (CI-friendly)",
    "Astra Project Dir (Default: aktuelles Verzeichnis)": "Astra project directory (default: current directory)",
    "Data Root (Default: C:/Astra)": "Data root (default: C:/Astra)",
    "Darks Library (Default: C:/Astra/_darks)": "Darks library (default: C:/Astra/_darks)",
    "Default Preset": "Default preset",
    "Cosmetic Default aktivieren/deaktivieren": "Enable or disable cosmetic correction default",
    "Ziel fur config.yaml (Default: ./config.yaml)": "Destination for config.yaml (default: ./config.yaml)",
    "Maschinenlesbare Ausgabe (JSON)": "Machine-readable output (JSON)",
    "Nur EQMODE anzeigen": "Show EQMODE only",
    "Frames detailliert anzeigen": "Show frames in detail",
    "QF-Metriken (Quality Foundation) anzeigen": "Show Quality Foundation metrics",
    "Zeigt was kopiert wuerde, ohne zu kopieren": "Show what would be copied without copying",
    "Quelle (Default: C:/Dwarflab/CALI_FRAME/dark/cam_0)": "Source (default: C:/Dwarflab/CALI_FRAME/dark/cam_0)",
    "Ziel (Default: C:/Astra/_darks)": "Destination (default: C:/Astra/_darks)",
    "Dry-run": "Dry-run",
    "Preset": "Preset",
    "Nicht-interaktiv": "Non-interactive",
    "Neues Preset": "New preset",
    "Ohne Rueckfrage loeschen": "Delete without confirmation",
    "Auto-fixt fehlende Dir, Config-Defaults, Dark-Struktur": "Auto-fix missing directories, config defaults, and dark structure",
    "Merge-Methode": "Merge method",
    "Gewichtungsmethode": "Weighting method",
    "Filter-Auswahl fuer Merge (wiederholbar, case-insensitive getrimmt, z.B. --merge-filter Astro)": "Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro)",
    "Output-Verzeichnis (sonst generated/{timestamp}/merged/)": "Output directory (default: generated/{timestamp}/merged/)",
    "Gruppen anzeigen ohne zu mergen": "Show groups without merging",
    "Config-Datei (global, muss VOR dem Subcommand stehen, z.B. --config config.yaml process <target>). Ohne --config sucht die Pipeline automatisch config.yaml im aktuellen Verzeichnis bzw. im Projekt-Root.": "Config file (global, must be placed BEFORE the subcommand, e.g. --config config.yaml process <target>). Without --config the pipeline automatically searches for config.yaml in the current directory or project root.",
    "Verbose output": "Verbose output",
    # V19-CFA-GATE + V19-PCC-FLAG (hidden/visible)
    "Quality Gate fuer CFA-Drizzle: Auto (Default), AN, AUS (alle Frames durchlassen)": "Quality gate for CFA-Drizzle: auto (default), on, off (let all frames pass)",
    "Mindest-Frames fuer Drizzle (Default: 5, CFA-Smart: 5)": "Minimum frames for drizzle (default: 5, CFA-Smart: 5)",
    "Fallback-Methode bei Quality Gate Fail (Default: malvar) [advanced]": "Fallback method on quality-gate failure (default: malvar) [advanced]",
    "Min Star Count (Default: 20 debayered, CFA-Smart: 1) [advanced]": "Min star count (default: 20 debayered, CFA-Smart: 1) [advanced]",
    "Min SNR (Default: 10, CFA-Smart: 5) [advanced]": "Min SNR (default: 10, CFA-Smart: 5) [advanced]",
    "Min Correlation (Default: 0.3, CFA-Smart: 0.1) [advanced]": "Min correlation (default: 0.3, CFA-Smart: 0.1) [advanced]",
    "FWHM Range als 'min,max' (Default: 1.5,5.0, CFA-Smart: 1.0,8.0) [advanced]": "FWHM range as 'min,max' (default: 1.5,5.0, CFA-Smart: 1.0,8.0) [advanced]",
     "Photometric Color Calibration aktivieren/deaktivieren (ueberschreibt Preset/Config; Default: Preset/Config gewinnt)": "Enable or disable photometric color calibration (overrides preset/config; default: preset/config wins)",
    # SUG-1 flag helps
    "Read OBJECT/FILTER/EXPTIME/TELESCOP/DET-TEMP from a local FITS header (local only, no cloud). OBJECT wins over TARGET when both are given (suggest.header_overrides_target warning).": "Read OBJECT, FILTER, EXPTIME, TELESCOP, DET-TEMP from a local FITS file header (local only, no cloud). If both --header and TARGET are given, OBJECT from the header takes precedence over TARGET.",
    "Fallback RA/DEC (decimal degrees) when TARGET/--header do not resolve a cache hit. Used only for SIMBAD lookup / labeling; suggest never plate-solves.": "Fallback right ascension and declination (RA DEC in decimal degrees) when target name or FITS OBJECT header do not resolve a cache hit. Coordinates are used only for SIMBAD lookup and result labeling; suggest never performs plate-solving.",
    "Print the machine-readable JSON suggestion to stdout instead of the human-readable text.": "Print the machine-readable JSON suggestion to stdout (in addition to or instead of human-readable text).",
    # New helps from backy v1.11
    "Load preset/registration/debayer/pcc from a suggested_parameters YAML/JSON file (written by 'astra suggest'). Required since v1.11 — run 'astra suggest <TARGET>' first to generate the file (default: C:/Astra/<Target>/suggested.yaml). If flag given without value, defaults to <Target>/suggested.yaml (derived from the TARGET argument). CLI flags win over file values. No auto-discover; only TARGET-arg-derived default when flag has no value.": "Load preset, registration method, debayer method, and PCC settings from a suggested_parameters YAML/JSON file (written by 'astra suggest', default C:/Astra/<Target>/suggested.yaml). Required since v1.11; run 'astra suggest <TARGET>' first to generate the file. If flag given without value, defaults to <Target>/suggested.yaml (derived from the TARGET argument). CLI flags win over file values. No auto-discover; only TARGET-arg-derived default when flag has no value.",
    "Override the output path for the suggested_parameters file (YAML default, JSON on .json suffix). Without --output the file is always written to C:/Astra/<Target>/suggested.yaml (Target-Root, next to Lights). Always overwrites (no auto-history).": "Write suggested_parameters to a file as YAML (default format) or JSON (if path ends with .json). Without --output, always writes to default C:/Astra/<Target>/suggested.yaml (Target-Root, next to Lights directory). --output path is a pure path override. Always overwrites (1 write per suggest, no auto-history; use explicit filenames for timestamped records).",
    "Suggest a preset/registration/debayer/PCC combination for TARGET.\n\n    Offline-first advisor (Header > target-cache > SIMBAD > Handbook 22):\n    the local target-cache always wins; SIMBAD is only queried on a cache\n    miss and only if the network is reachable (5s timeout, 1 query). On\n    cache miss + SIMBAD unreachable for an unknown target: Error Exit 2\n    (suggest.simbad_unavailable); add the entry in stella target-cache.md.\n\n    Always writes suggested.yaml to <data_root>/<Target>/suggested.yaml\n    (Target-Root) unless --output overrides the path. 'astra process'\n    requires --from-suggested (run 'astra suggest <TARGET>' first).\n\n    Examples:\n        astra suggest M31\n        astra suggest M31 --output C:/Astra/M31/suggested_20260905.yaml\n        astra suggest M27 --header C:/Astra/M27/light_0001.fits\n        astra suggest C19 --json --output C:/Astra/C19/suggested.yaml\n    ": "Suggest a preset, registration method, debayer method, and PCC settings for a target. Offline-first advisor (Header > target-cache > SIMBAD > Handbook): HEADER wins over TARGET; target-cache (stella-maintained) always wins over SIMBAD; SIMBAD only queried on cache miss if network available (5s timeout). On unknown target + cache miss + offline: Error Exit 2 `suggest.simbad_unavailable` (no file written; add entry to target-cache.md or run with known target). Always writes suggested.yaml to default location C:/Astra/<Target>/suggested.yaml or --output override. Output also writes to stdout (human-readable) or --json (machine-readable). This command is an ADVISOR; `astra process` requires `--from-suggested` flag (mandatory since v1.11). Examples: `astra suggest M31`; `astra suggest M31 --output C:/Astra/M31/suggested_20260905.yaml`; `astra suggest M27 --header C:/Astra/M27/light_0001.fits --json`",
    "Preset override for all targets (default: from per-target suggested.yaml)": "Default preset for all targets (default: from per-target suggested.yaml)",
    "Process all subdirectories in data root.\n\n    Each target directory must have a suggested.yaml (run 'astra suggest\n    <TARGET>' first). The per-target suggested.yaml is passed via\n    --from-suggested (Target-Root default). Missing file -> Error (ENTS-1).\n    ": "Process all subdirectories in the data root. Each target directory must have a suggested.yaml (run 'astra suggest <TARGET>' first). The per-target suggested.yaml is passed via --from-suggested (Target-Root default). Missing file → Error.",
    # V1.11-SUBSET: --limit flag for smoke testing
    "Limit number of light frames per group for quick smoke testing (discovery processes all groups, but uses only first N lights per group; darks, bias, flats remain complete for proper calibration). Default: no limit (process all frames). Example: --limit 5 (use first 5 lights per group; output marked as smoke_mode=true). Combination: incompatible with --resume (use --limit for fresh runs only). [English §17]": "Limit number of light frames per group for quick smoke testing (discovery processes all groups, but uses only first N lights per group; darks, bias, flats remain complete for proper calibration). Default: no limit (process all frames). Example: --limit 5 (use first 5 lights per group; output marked as smoke_mode=true). Combination: incompatible with --resume (use --limit for fresh runs only).",
    "Limit number of light frames per group for smoke testing - applied uniformly to every target in the batch (N >= 1). See 'astra process --help' for details.": "Limit number of light frames per group for smoke testing - applied uniformly to every target in the batch (N >= 1). See 'astra process --help' for details.",
    # Global flag
    "Show the version and exit.": "Show the version and exit.",
}

# English summaries for source symbols rendered in architecture / feature docs.
# Key format: "module_filename.symbol_name" for functions/classes, "module_filename" for modules.
SYMBOL_DOC_EN: dict[str, str] = {
    # modules
    "cosmetic": "Cosmetic correction — bad-pixel map and interpolation before debayering.",
    "debayer": "Debayering — convert Bayer CFA 2D data to RGB 3D (super-pixel / bilinear / Malvar2004).",
    "equipment": "Equipment auto-detection from FITS headers and config profiles.",
    "export": "Export — FITS copy, header enrichment, preview generation, and Siril-compatible .seq files.",
    "fits_parser": "FITS header parser with alias handling and filename-based metadata fallback.",
    "gradient_removal": "Gradient removal — polynomial background modelling for stacked frames.",
    "pcc": "Photometric color calibration — star detection, GAIA/VizieR catalog matching, gray-world fallback.",
    "plugins": "Plugin interface for optional pipeline steps loaded via entry points.",
    "preview": "Auto-stretched JPG preview generation for quick visual inspection.",
    "quality": "Frame quality metrics — SNR, FWHM, outlier flagging, and double-star detection.",
    "registration": "Registration adapters — FFT, astroalign, and rotation-FFT strategies with fallback.",
    "selection": "Frame selection and outlier rejection pipeline.",
    "seq_file": "Siril-compatible sequence file helper.",
    "stacking": "Frame stacking — rejection mapping, winsorized sigma-clip, sigma-clipped mean.",
    "staging": "Input staging — copy conventional input folders into generated/<ts>/00_input.",
    "multi_group_agent": "Multi-group processing — per-group stacks, cross-group registration, merge.",
    "calibration": "Calibration — master dark/bias/flat creation and application to lights.",
    "archive": "Archive — agent-log.yaml, run-info.json, and final output resolution.",
    # cosmetic
    "cosmetic.detect_bad_pixels": "Derive a bad-pixel map from calibrated lights (CFA, before debayer).",
    "cosmetic.interpolate_bad_pixels": "Replace defective pixels with the median of same-color neighbors.",
    # debayer
    "debayer.debayer_superpixel": "Convert Bayer CFA to RGB 3D using the super-pixel method.",
    "debayer.debayer_bilinear": "Convert Bayer CFA to RGB 3D using bilinear interpolation.",
    "debayer.debayer_malvar2004": "Convert Bayer CFA to RGB 3D using the Malvar2004 demosaicing algorithm.",
    # equipment
    "equipment.resolve_equipment": "Resolve equipment parameters from FITS headers and config.",
    "equipment.match_equipment_profile": "Select the equipment profile according to the header/config priority.",
    # export
    "export.annotate_export_header": "Enrich the export FITS header with best-effort metadata.",
    "export.export_stretched_fits": "Write a stretched FITS for display purposes.",
    # fits_parser
    "fits_parser.parse_filename_metadata": "Extract metadata from filename when FITS header is incomplete.",
    "fits_parser.parse_fits_header": "Parse a FITS file header into the standardized FitsHeader model.",
    "fits_parser.scan_directory": "Scan a directory for FITS files and categorize them by frame type.",
    "fits_parser.build_observation_context": "Build a complete ObservationContext from a directory scan.",
    # gradient_removal
    "gradient_removal.fit_background": "Fit a polynomial background model with iterative rejection.",
    "gradient_removal.remove_gradient": "Remove a smooth background gradient from a 2D or RGB frame.",
    "gradient_removal.background_extraction": "Apply gradient removal to the stacked frame.",
    # pcc
    "pcc.apply_pcc": "Apply photometric color calibration (VizieR primary, GAIA fallback since v1.6).",
    "pcc.gray_world_white_balance": "Simple gray-world white balance using bright star regions.",
    "pcc.apply_scnr": "Remove green cast via SCNR (subtract chromatic noise from RGB).",
    "pcc.photometric_color_calibration": "Apply PCC to the stacked frame (in-place overwrite).",
    # plugins
    "plugins.Plugin": "Abstract base class for pipeline-step plugins.",
    "plugins.PluginRegistry": "Registry for pipeline-step plugins loaded from entry points.",
    "plugins.resolve_step": "Resolve the first plugin that handles a given step name.",
    # preview
    "preview.create_preview_jpg": "Create an auto-stretched JPG preview from a linear FITS file.",
    # quality
    "quality.compute_frame_quality": "Compute SNR, FWHM median, star count, double rate, and elongation for one frame.",
    "quality.reject_outlier_frames": "Reject frames exceeding configurable per-metric thresholds.",
    "quality.summarize_qualities": "Group-level summary of frame quality metrics.",
    # registration
    "registration.AstroalignRegistration": "Astroalign-based registration strategy (optional extra).",
    "registration.FftGridRegistration": "FFT phase-correlation registration strategy.",
    "registration.RotationFftRegistration": "Log-polar FFT rotation strategy for AZ field rotation.",
    "registration.register_frames": "Register frames with adaptive channel selection.",
    "registration.corr_grid_shift": "Correlation-based coarse-to-fine shift search on high-pass filtered data.",
    "registration.select_registration_channel": "Select the best monochrome channel for registration.",
    "registration.compute_shift": "Sub-pixel shift via phase correlation with a Hanning window.",
    # stacking
    "stacking.stack_frames": "Stack registered frames; per-channel for 3D RGB data.",
    "stacking.winsorized_sigma_clip": "Siril-style winsorized sigma clipping along the stack axis.",
    "stacking.sigma_clipped_mean": "Sigma-clipped mean along the stack axis (reject, not clamp).",
    # multi_group_agent
    "multi_group_agent.MultiGroupProcessor": "Core multi-group stacking logic (phase 2).",
    "multi_group_agent.build_reference_selection": "Choose and document the reference group for cross-group registration.",
    # calibration
    "calibration.CalibrationAgent": "Handles calibration frame stacking and light-frame calibration.",
    "calibration.CalibrationResult": "Result of the calibration workflow.",
    "calibration._find_darks_for_group": "Find dark frames for a specific (EXPTIME, GAIN) group. Matching order: local target darks, library exact match, library nearest temperature, none.",
    # archive
    "archive.ArchiveAgent": "Creates agent-log.yaml summarizing the pipeline run.",
    "archive.ArchiveResult": "Paths to final FITS, agent log, and run-info JSON.",
}

# English descriptions for Pydantic config fields whose model_fields lack
# a description attribute. Key format: "ModelName.field_name".
CONFIG_FIELD_EN: dict[str, str] = {
    # AppConfig
    "AppConfig.data_root": "Root directory for all target data (e.g. C:/Astra).",
    "AppConfig.working_dir": "Relative working directory for intermediate pipeline files.",
    "AppConfig.output_dir": "Relative output directory for final pipeline products.",
    "AppConfig.config_dir": "Relative directory for configuration files.",
    "AppConfig.gimp_path": "Optional path to the GIMP executable (deprecated; Astra does not use GIMP).",
    "AppConfig.default_preset": "Preset applied when a target does not specify one.",
    "AppConfig.cpu_threads": "Number of CPU threads for parallel tasks (0 = auto).",
    "AppConfig.gpu_acceleration": "Enable GPU acceleration where supported.",
    "AppConfig.keep_working": "Keep intermediate working directories after a successful run.",
    "AppConfig.quality_accept_threshold": "Minimum quality score for a frame to be accepted automatically.",
    "AppConfig.quality_review_threshold": "Minimum quality score for a frame to be flagged for review.",
    "AppConfig.plate_solve_enabled": "Enable astrometric plate solving after stacking.",
    "AppConfig.astrometry_bin": "Path to the local astrometry.net solve-field binary.",
    "AppConfig.astrometry_index_dir": "Directory containing astrometry.net index files.",
    "AppConfig.darks_repository": "Central darks library path (e.g. C:/Astra/_darks).",
    "AppConfig.dark_scale_mismatch_abs": "Absolute temperature mismatch tolerance for dark matching (°C).",
    "AppConfig.dark_scale_mismatch_frac": "Fractional exposure mismatch tolerance for dark matching.",
    "AppConfig.dark_scale_mismatch_low_frac": "Low-temperature fractional mismatch tolerance.",
    "AppConfig.gaia_timeout": "Timeout in seconds for GAIA catalog queries.",
    "AppConfig.vizier_apass_timeout": "Timeout in seconds for APASS catalog queries.",
    "AppConfig.vizier_refcat2_timeout": "Timeout in seconds for REFCAT2 catalog queries.",
    "AppConfig.use_flats": "Apply flat-field calibration during preprocessing.",
    "AppConfig.use_bias": "Apply bias-frame calibration during preprocessing.",
    "AppConfig.mandatory_fields": "FITS header fields required for a frame to be processed.",
    "AppConfig.no_calib": "Skip all calibration steps (not recommended for science data).",
    "AppConfig.debayer_method": "Default debayer algorithm: superpixel, bilinear, or malvar.",
    # ProcessingParams
    "ProcessingParams.rejection": "Outlier rejection strategy for stacking.",
    "ProcessingParams.stacking_method": "Algorithm used to combine registered frames.",
    "ProcessingParams.normalization": "Pixel normalization mode for stacking (mul, add, etc.).",
    "ProcessingParams.weight": "Weighting strategy for stacking (noise, equal, etc.).",
    "ProcessingParams.stretch_method": "Preview stretch function (asinh, linear, etc.).",
    "ProcessingParams.stretch_factor": "Preview stretch scaling factor.",
    "ProcessingParams.scnr_amount": "Star Color Noise Reduction amount for OSC data.",
    "ProcessingParams.gaia_timeout": "Timeout in seconds for GAIA catalog queries.",
    "ProcessingParams.vizier_apass_timeout": "Timeout in seconds for APASS catalog queries.",
    "ProcessingParams.vizier_refcat2_timeout": "Timeout in seconds for REFCAT2 catalog queries.",
    "ProcessingParams.debayer_method": "Debayer algorithm: superpixel, bilinear, or malvar.",
    "ProcessingParams.double_detection": "Enable double-star detection and rejection.",
    "ProcessingParams.double_radius_px": "Search radius in pixels for double-star detection.",
    "ProcessingParams.elongation_check": "Enable star-elongation quality checks.",
    "ProcessingParams.elongation_warn_threshold": "Elongation ratio that triggers a warning.",
    "ProcessingParams.elongation_unusable_threshold": "Elongation ratio that marks a frame unusable.",
    "ProcessingParams.elongation_min_stars": "Minimum number of stars needed for elongation stats.",
    "ProcessingParams.rejection_enabled": "Enable statistical outlier rejection during stacking.",
    "ProcessingParams.rejection_thresholds": "Per-metric lower/upper thresholds for rejection.",
    "ProcessingParams.rejection_elongation": "Reject frames based on elongation metrics.",
    # MultiGroupConfig
    "MultiGroupConfig.enabled": "Enable multi-group stacking when multiple filter groups are present.",
    "MultiGroupConfig.reference_group": "Criterion for choosing the reference group (e.g. quality).",
    "MultiGroupConfig.pcc_fallback": "Fallback strategy when PCC fails for a group.",
    "MultiGroupConfig.pcc_per_group": "Apply PCC to each group stack before merging.",
    "MultiGroupConfig.merge": "Merge strategy configuration for combining group stacks.",
    "MultiGroupConfig.keep_group_working_dirs": "Keep per-group working directories after the run.",
    # MergeConfig
    "MergeConfig.method": "Pixel-combining method for merging group stacks.",
    "MergeConfig.weight_by": "Weighting criterion for merging groups.",
    "MergeConfig.min_correlation": "Minimum cross-group correlation for a frame to contribute.",
    "MergeConfig.filters": "Optional list of filter names to include in the merge.",
    # RegistrationConfig
    "RegistrationConfig.method": "Registration engine: astroalign, fft, or rotation_fft.",
    "RegistrationConfig.max_control_points": "Maximum control points for astroalign registration.",
    "RegistrationConfig.max_rotation_deg": "Sanity-guard maximum rotation in degrees.",
    "RegistrationConfig.max_scale_dev": "Maximum allowed scale deviation for registration.",
    "RegistrationConfig.stack_scale_factor": "Sub-pixel upsampling factor for shift measurement.",
    "RegistrationConfig.zero_shift_threshold": "High-pass correlation threshold for zero-shift fallback.",
    "RegistrationConfig.zero_shift_fallback": "Fall back to zero shift when correlation is below threshold.",
    "RegistrationConfig.max_exptime_fft_warn": "Threshold in seconds above which a warning is emitted for fft registration on AZ mounts.",
    # GradientRemovalConfig
    "GradientRemovalConfig.enabled": "Enable gradient removal before stacking.",
    "GradientRemovalConfig.degree": "Polynomial degree fit to the background gradient.",
    "GradientRemovalConfig.grid": "Background sampling grid as (rows, cols).",
    "GradientRemovalConfig.sigma_clip": "Sigma-clipping multiplier for rejecting bright samples.",
    "GradientRemovalConfig.min_samples": "Minimum number of valid samples required for fit.",
    # CosmeticCorrectionConfig
    "CosmeticCorrectionConfig.enabled": "Enable cosmetic correction (hot/dead pixels).",
    "CosmeticCorrectionConfig.n_frames": "Minimum dark frames required for cosmetic correction.",
    "CosmeticCorrectionConfig.threshold": "Hot-pixel threshold in sigma above the master dark.",
    "CosmeticCorrectionConfig.dark_tolerance": "Temperature tolerance in °C for master-dark matching.",
    # CFADrizzleConfig
    "CFADrizzleConfig.enabled": "Enable CFA drizzle up-sampling during integration.",
    "CFADrizzleConfig.scale": "Output pixel scale factor (e.g. 2.0 = 2x).",
    "CFADrizzleConfig.pixfrac_mode": "Pixfrac mode: auto based on star count or fixed.",
    "CFADrizzleConfig.pixfrac": "Pixel fraction (drop size) for drizzle kernel.",
    "CFADrizzleConfig.kernel": "Drizzle kernel: lanczos3, gaussian, or tophat.",
    "CFADrizzleConfig.quality_gate": "Quality thresholds that must pass before drizzle is applied.",
    "CFADrizzleConfig.min_frames": "Minimum frame count required to enable drizzle.",
    "CFADrizzleConfig.fallback": "Fallback debayer method if drizzle preconditions fail.",
    # FrameSelectionConfig
    "FrameSelectionConfig.enabled": "Enable automatic frame selection by quality metrics.",
    "FrameSelectionConfig.keep_percentile": "Percentile of frames to keep (1-100).",
    "FrameSelectionConfig.weights": "Per-metric weights used to compute the quality score.",
     "FrameSelectionConfig.min_frames": "Minimum number of frames that must remain after selection.",
    # SuggestConfig (V19-TARGET-ADVISOR SUG-6)
    "SuggestConfig.target_cache_path": "Optional path to a local target-cache.md file (e.g., knowledge-base/agents/stella/target-cache.md). If not set, every target is a cache miss: suggest queries SIMBAD (if online) or falls back to generic preset advice with a warning; no crash, always Exit 0 (AC-SUG-4). Used offline to resolve target names to presets without requiring network access.",
}


def _norm_help_key(s: str) -> str:
    """Normalize a German help string for fuzzy, drift-tolerant lookup.

    Handles mojibake replacement characters, umlaut transliteration,
    unicode normalization, case folding and whitespace collapse so
    source strings with encoding drift still match their map entries.
    """
    s = unicodedata.normalize("NFC", s)
    # Drop U+FFFD replacement characters generated by source encoding issues.
    s = s.replace("\ufffd", "")
    # Transliterate umlauts to ASCII so ö/oe/ö-mojibake all collapse.
    for a, b in (
        ("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss"),
        ("Ä", "A"), ("Ö", "O"), ("Ü", "U"),
    ):
        s = s.replace(a, b)
    # em dash / en dash -> hyphen for robustness
    s = s.replace("\u2014", "-").replace("\u2013", "-")
    s = s.casefold()
    s = " ".join(s.split())
    return s.strip()


def _en_help(german: str, context: str = "") -> str:
    """Return English help text for a German cli.py help string.

    Warns to stderr when no translation is found, so silent German
    bleed-through cannot ship.
    """
    if not german:
        return ""
    normalized = _norm_help_key(german)
    if not normalized:
        return ""
    # Build normalized stripped-key lookup lazily (deterministic, same process).
    if not hasattr(_en_help, "_lookup"):
        _en_help._lookup = {  # type: ignore
            _norm_help_key(k): v for k, v in CLI_HELP_EN.items()
        }
    translated = _en_help._lookup.get(normalized)  # type: ignore
    if translated is not None:
        return translated
    # No translation hit -> warn loudly, then emit a genericized English fallback.
    label = f" [{context}]" if context else ""
    print(
        f"[WARN] Untranslated CLI help{label}: {german[:120]!r}",
        file=sys.stderr,
    )
    # Derive a useful English fallback from the first sentence / first line.
    return german.strip()


def _en_symbol(module: str, symbol: str) -> Optional[str]:
    """Return English summary for a specific source symbol if available."""
    if not symbol:
        return None
    return SYMBOL_DOC_EN.get(f"{module}.{symbol}")


def _en_module_summary(module: str) -> Optional[str]:
    """Return English summary for a module if available."""
    return SYMBOL_DOC_EN.get(module)


def _redact_local_paths(text: str) -> str:
    """Redact user-specific Windows home paths from generated docs."""
    if not text:
        return text
    # Redact C:\Users\<any-user>\... or C:/Users/<any-user>/...
    text = re.sub(
        r"C:\\Users\\[^\\\s\)\]\>\"\'\,]+(\\[^\s\)\]\>\"\'\,]*)?",
        r"C:\\Users\\<user>\\...",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"C:/Users/[^/\s\)\]\>\"\'\,]+(/[^\s\)\]\>\"\'\,]*)?",
        r"C:/Users/<user>/...",
        text,
        flags=re.IGNORECASE,
    )
    return text


# ─── Shared Utilities ───────────────────────────────────────────────────

class DocWriter:
    """Helper to write markdown files with consistent formatting."""
    
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.lines: list[str] = []
    
    def h1(self, text: str) -> "DocWriter":
        self.lines.append(f"# {text}\n")
        return self
    
    def h2(self, text: str) -> "DocWriter":
        self.lines.append(f"## {text}\n")
        return self
    
    def h3(self, text: str) -> "DocWriter":
        self.lines.append(f"### {text}\n")
        return self
    
    def h4(self, text: str) -> "DocWriter":
        self.lines.append(f"#### {text}\n")
        return self
    
    def p(self, text: str) -> "DocWriter":
        self.lines.append(f"{text}\n")
        return self
    
    def code(self, text: str, lang: str = "") -> "DocWriter":
        self.lines.append(f"```{lang}\n{text}\n```\n")
        return self
    
    def table(self, headers: list[str], rows: list[list[str]]) -> "DocWriter":
        self.lines.append("| " + " | ".join(headers) + " |")
        self.lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            self.lines.append("| " + " | ".join(row) + " |")
        self.lines.append("")
        return self
    
    def ul(self, items: list[str]) -> "DocWriter":
        for item in items:
            self.lines.append(f"- {item}")
        self.lines.append("")
        return self
    
    def ol(self, items: list[str]) -> "DocWriter":
        for i, item in enumerate(items, 1):
            self.lines.append(f"{i}. {item}")
        self.lines.append("")
        return self
    
    def hr(self) -> "DocWriter":
        self.lines.append("---\n")
        return self
    
    def write(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(self.lines)
        self.output_path.write_text(content, encoding="utf-8", newline="\n")
        print(f"  [OK] Generated: {self.output_path.relative_to(REPO_ROOT)}")


def _read_normalised(path: Path) -> bytes:
    """Read a file with EOL normalisation (CRLF→LF) for deterministic hashing.

    Falls back to raw bytes for non-UTF-8 files (e.g. .pyc binaries), which
    have no line-ending issues and are hashed as-is.
    """
    try:
        return path.read_text(encoding="utf-8").encode("utf-8")
    except UnicodeDecodeError:
        return path.read_bytes()


def file_hash(path: Path) -> str:
    """SHA256 hash of file or directory content for change detection.

    Uses EOL-normalised content (CRLF→LF via universal newlines) so that
    Windows working-trees (autocrlf=true, CRLF) and Linux runners / ZIP-
    expanded trees (LF) produce identical hashes.  Binary files that cannot
    be decoded as UTF-8 are hashed from raw bytes (no EOL issue there).
    """
    if not path.exists():
        return ""
    if path.is_file():
        return hashlib.sha256(_read_normalised(path)).hexdigest()[:16]
    hasher = hashlib.sha256()
    for file_path in sorted(path.rglob("*")):
        if file_path.is_file():
            hasher.update(_read_normalised(file_path))
    return hasher.hexdigest()[:16]


def load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _filter_log_lines(text: str) -> str:
    """Remove structlog JSON log lines from captured CLI output."""
    return "\n".join(
        line for line in text.splitlines()
        if not re.match(r'^\{.*"event"', line)
    )


def _normalize_cli_usage(text: str) -> str:
    """Replace CliRunner's function name 'cli' with the installed console script name 'astra'."""
    return re.sub(r"^Usage: cli\b", "Usage: astra", text, flags=re.MULTILINE)


def _translate_help_dump(text: str) -> str:
    """Translate German help strings inside a raw --help text dump.

    Handles both single-line option help and multi-line command/option
    description blocks by accumulating indented continuation lines.
    """
    lines = text.splitlines()
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped in CLI_HELP_EN:
            out_lines.append(line.replace(stripped, CLI_HELP_EN[stripped]))
            i += 1
            continue

        # Detect an option or command entry line:
        #   "  --flag TYPE  German help text..."
        #   "  cmdname      German help text..."
        m = re.match(r"^(\s{2,})(-\S.*?|\S+)\s{2,}(.+)$", line)
        if m:
            prefix, opts, help_text = m.groups()
            block_lines = [help_text]
            continuation_indent = len(prefix) + 4
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                next_stripped = next_line.strip()
                if not next_stripped:
                    # Preserve blank line inside block only if next real line
                    # is still indented deeper.
                    peek = j + 1
                    while peek < len(lines) and not lines[peek].strip():
                        peek += 1
                    if peek < len(lines):
                        peek_indent = len(lines[peek]) - len(lines[peek].lstrip())
                        if peek_indent >= continuation_indent:
                            block_lines.append("")
                            j = peek
                            continue
                    break
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent >= continuation_indent:
                    block_lines.append(next_stripped)
                    j += 1
                else:
                    break
            full = "\n".join(block_lines)
            en = _en_help(full)
            normalized_full = _normalize_for_lookup(full)
            if en != normalized_full:
                first, *rest = en.split("\n")
                out_lines.append(f"{prefix}{opts}  {first}")
                for r in rest:
                    if r:
                        out_lines.append(f"{prefix}    {r}")
                    else:
                        out_lines.append("")
                i = j
                continue
        out_lines.append(line)
        i += 1
    return "\n".join(out_lines)


def _truncate_at_word(text: str, max_len: int) -> str:
    """Truncate text at or before max_len, preferring word boundaries."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > max_len * 0.5:
        return truncated[:last_space]
    return truncated


def _read_doc_data(name: str) -> str:
    path = DOC_DATA_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


# ─── Generator Registry ─────────────────────────────────────────────────

GeneratorFunc = Callable[[], None]
GENERATORS: dict[str, GeneratorFunc] = {}


def generator(name: str) -> Callable[[GeneratorFunc], GeneratorFunc]:
    def decorator(func: GeneratorFunc) -> GeneratorFunc:
        GENERATORS[name] = func
        return func
    return decorator


# ─── Helpers for CLI introspection ──────────────────────────────────────

def _walk_click_commands(cli_group):
    """Walk click group to collect commands and params."""
    import click
    commands = {}
    for name, cmd in cli_group.commands.items():
        params = []
        for p in cmd.params:
            p_type = getattr(p.type, "name", str(type(p.type).__name__))
            if hasattr(p.type, "choices"):
                try:
                    choices = list(p.type.choices)  # type: ignore
                    if choices:
                        p_type = f"Choice({','.join(map(str, choices))})"
                except Exception:
                    pass
            params.append({
                "name": ", ".join(p.opts) if hasattr(p, "opts") else p.name,
                "type": p_type,
                "default": _redact_local_paths(str(p.default)) if p.default is not None else "",
                "help": _en_help(getattr(p, "help", "") or "", context=f"flag {p.opts}"),
                "required": getattr(p, "required", False),
            })
        help_text = _en_help(getattr(cmd, "help", "") or getattr(cmd, "short_help", "") or "", context=f"command {name}")
        sub = {}
        if hasattr(cmd, "commands"):
            for sub_name, sub_cmd in cmd.commands.items():
                sub_params = []
                for sp in sub_cmd.params:
                    st = getattr(sp.type, "name", str(type(sp.type).__name__))
                    if hasattr(sp.type, "choices"):
                        try:
                            ch = list(sp.type.choices)  # type: ignore
                            if ch:
                                st = f"Choice({','.join(map(str,ch))})"
                        except Exception:
                            pass
                    sub_params.append({
                        "name": ", ".join(sp.opts) if hasattr(sp, "opts") else sp.name,
                        "type": st,
                        "default": _redact_local_paths(str(sp.default)) if sp.default is not None else "",
                        "help": _en_help(getattr(sp, "help", "") or "", context=f"flag {sp.opts}"),
                    })
                sub[sub_name] = {"help": _en_help(getattr(sub_cmd, "help", "") or "", context=f"subcommand {sub_name}"), "params": sub_params}
        commands[name] = {"help": help_text, "params": params, "subcommands": sub}
    return commands


def _extract_module_docstring(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
        import ast
        tree = ast.parse(text)
        doc = ast.get_docstring(tree)
        return doc or ""
    except Exception:
        return ""


def _extract_top_level_symbols(path: Path) -> list[tuple[str, str, Optional[str]]]:
    """Return top-level classes/functions: (kind, name, first_line_of_doc)."""
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    results = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node) or ""
            first = doc.split("\n")[0].strip() if doc else ""
            results.append(("class" if isinstance(node, ast.ClassDef) else "function", node.name, first))
    return results


# ─── Generators ─────────────────────────────────────────────────────────

@generator("quickstart")
def gen_quickstart() -> None:
    writer = DocWriter(DOCS_DIR / "01-quickstart.md")
    writer.h1("Quickstart")
    writer.p("> Auto-generated — Template + `astra init --help`")
    writer.p("Welcome to Astra! This guide gets you to your first stacked image in 5 minutes.")
    writer.h2("Installation")
    writer.code("pip install -e .\nastra --help", lang="bash")
    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from astro_process.cli import cli as astra_cli
        commands = _walk_click_commands(astra_cli)
        writer.h2("Top-level commands")
        rows = []
        for name, info in sorted(commands.items()):
            desc = _truncate_at_word((info["help"] or "").split("\n")[0].replace("|", "/"), 70)
            rows.append([f"`{name}`", desc or "-"])
        writer.table(["Command", "Description"], rows)
    except Exception as e:
        writer.code(f"Help extraction failed: {e}", lang="text")
    writer.h2("First run")
    writer.ol([
        "Run `astra init` (wizard: Data Root, Darks Library, Preset, Cosmetic).",
        "Add a target: `astra target add M13 --preset star_standard`.",
        "Pre-flight: `astra process M13 --preflight` (Hot Pixel, Darks, Cosmetic).",
        "Pipeline: `astra process C:/Astra/M13 --preset star_standard`.",
        "Check result in `C:/Astra/M13/generated/<ts>/merged/`.",
        "Status: `astra status --json`.",
    ])
    writer.write()


@generator("arch")
def gen_architecture_doc() -> None:
    writer = DocWriter(DOCS_DIR / "02-pipeline-architecture.md")
    writer.h1("Pipeline Architecture")
    writer.p("> Auto-generated from `src/astro_process/core/` module structure + `doc_data/architecture.md`.")
    writer.hr()

    fragment = _read_doc_data("architecture.md")
    if fragment:
        writer.lines.extend(fragment.splitlines())
        writer.p("")

    writer.h2("Core modules")
    core_dir = SRC_DIR / "core"
    modules = sorted(core_dir.glob("*.py")) if core_dir.exists() else []
    for mod in modules:
        summary = _en_module_summary(mod.stem)
        if not summary:
            # fall back to first line only if it looks English
            first = _extract_module_docstring(mod).split("\n")[0].strip()
            if first and not any(c in first for c in "äöüÄÖÜß"):
                summary = first
        writer.h3(mod.stem)
        if summary:
            writer.p(summary)
        symbols = _extract_top_level_symbols(mod)
        public = [(kind, name) for kind, name, _ in symbols if not name.startswith("_")]
        if public:
            rows = []
            for kind, name in public[:12]:
                en = _en_symbol(mod.stem, name)
                rows.append([f"`{name}`", kind, _truncate_at_word(en, 80) if en is not None else "—"])
            writer.table(["Symbol", "Kind", "Description"], rows)

    writer.h2("Key agents")
    for agent_file in ["calibration.py", "archive.py"]:
        p = SRC_DIR / "agents" / agent_file
        if p.exists():
            summary = _en_module_summary(p.stem)
            writer.h3(p.stem)
            if summary:
                writer.p(summary)
            symbols = _extract_top_level_symbols(p)
            public = [(kind, name) for kind, name, _ in symbols if not name.startswith("_")]
            if public:
                rows = []
                for kind, name in public[:6]:
                    en = _en_symbol(p.stem, name)
                    rows.append([f"`{name}`", kind, _truncate_at_word(en, 80) if en is not None else "—"])
                writer.table(["Symbol", "Kind", "Description"], rows)

    writer.write()


@generator("cli")
def gen_cli_reference() -> None:
    writer = DocWriter(DOCS_DIR / "03-cli-reference.md")
    writer.h1("CLI Reference")
    writer.p("> Auto-generated from `src/astro_process/cli.py` — **do not edit manually**.")
    writer.p("> Generator: `python scripts/generate_docs.py cli`")
    writer.p("> Precedence: CLI > Config > Env > Default (see `04-configuration.md`)")
    writer.hr()
    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from astro_process.cli import cli as astra_cli
        commands = _walk_click_commands(astra_cli)
        writer.h2("Subcommands")
        rows = []
        for name, info in sorted(commands.items()):
            desc = _truncate_at_word((info["help"] or "").split("\n")[0].replace("|", "/"), 100)
            flag_str = ", ".join([p["name"].split(",")[0].strip() for p in info["params"][:4]])
            rows.append([f"`{name}`", desc or "-", flag_str or "-"])
            for sub_name, sub_info in info.get("subcommands", {}).items():
                sdesc = _truncate_at_word((sub_info["help"] or "").split("\n")[0].replace("|", "/"), 80)
                rows.append([f"`{name} {sub_name}`", sdesc or "-", "-"])
        writer.table(["Command", "Description", "Flags"], rows)

        writer.h2("Global Flags")
        global_params = getattr(astra_cli, "params", [])
        if global_params:
            grows = []
            for p in global_params:
                pname = ", ".join(p.opts) if hasattr(p, "opts") else str(p.name)
                ptype = getattr(p.type, "name", str(type(p.type).__name__))
                grows.append([
                    f"`{pname}`",
                    ptype,
                    _redact_local_paths(str(p.default)) if p.default is not None else "",
                    _truncate_at_word(_en_help((getattr(p, "help", "") or ""), context=f"global flag {pname}"), 80),
                ])
            writer.table(["Flag", "Type", "Default", "Description"], grows)

        for name, info in sorted(commands.items()):
            writer.h2(f"`{name}`")
            if info["help"]:
                writer.p(_truncate_at_word(info["help"], 800))
            if info["params"]:
                rows = [[f"`{p['name']}`", p["type"], _redact_local_paths(p["default"])[:60], _truncate_at_word(p["help"], 80)] for p in info["params"]]
                writer.table(["Flag", "Type", "Default", "Description"], rows)
            for sub_name, sub_info in info.get("subcommands", {}).items():
                writer.h3(f"`{name} {sub_name}`")
                if sub_info["help"]:
                    writer.p(_truncate_at_word(sub_info["help"], 800))
                if sub_info["params"]:
                    rows = [[f"`{p['name']}`", p["type"], _redact_local_paths(p["default"])[:60], _truncate_at_word(p["help"], 80)] for p in sub_info["params"]]
                    writer.table(["Flag", "Type", "Default", "Description"], rows)

    except Exception as e:
        writer.p(f"**Error during Click introspection:** {e}")
        writer.code(str(e), lang="text")

    # ── V19-ENV + V19-PCC-FLAG supplemental sections (survive regeneration) ──
    writer.h2("astra init --non-interactive (CI, V19-ENV)")
    writer.p("Non-interactive, CI-friendly init. Reads flags / env vars, no prompts. Env vars: `ASTRA_DATA_ROOT`, `ASTRA_DARKS_REPOSITORY`, `ASTRA_DEFAULT_PRESET` (and `GIMP_PATH`). Writes `config.yaml` with **resolved** absolute paths (no `${}`).")
    writer.code('cp .env.example .env  # edit paths\nastra init --non-interactive --data-root "$ASTRA_DATA_ROOT" --darks-library "$ASTRA_DARKS_REPOSITORY"\nastra doctor          # WARN doctor.env_missing if .env absent, Exit 0', lang="bash")
    writer.p("Precedence for `init`/`load_config`: explicit `--config` > `CWD/config.yaml` > `pipeline_root/config.yaml` > `DEFAULT_CONFIG`. `.env` precedence: `Shell Env > CWD/.env > pipeline_root/.env` (`Path.expanduser().resolve()` after `expandvars`).")
    writer.p("ACI: `astra init --non-interactive` is required for AC-ENV-4 and CI `Ubuntu+Win/3.11`.")
    writer.h2("PCC Flag — Use Cases (V19-PCC-FLAG)")
    writer.p("Precedence: **CLI `--pcc/--no-pcc` > Config `pcc.enabled` > Preset Steps > Default**. `default None` = no breaking change. Existing `--pcc-per-group/--no-pcc-per-group` stays independent (location: PCC per group vs. on merged stack).")
    writer.table(["Scenario", "Command"], [
    ["M31 Galaxy, skip PCC (fast, avoid 6 min GAIA timeout)", "`astra process ... --preset galaxy_standard --no-pcc`"],
    ["Star cluster, force PCC", "`astra process ... --preset star_standard --pcc`"],
    ["Nebula, force PCC (preset has none)", "`astra process ... --preset nebula_standard --pcc`"],
    ["Multi-Group, PCC only on merged (default)", "`astra process ... --no-pcc-per-group`"],
    ["Multi-Group, PCC per group", "`astra process ... --pcc --pcc-per-group`"],
    ["Config fallback (no CLI)", "`pcc.enabled: false` in `config.yaml` + no CLI flag → Preset overridden"],
    ])
    writer.p("Runtime mutation: `--pcc` inserts `photometric_color_calibration` after `background_extraction` (fallback: after `stack_frames`, then `len-2` before stretch/export). `--no-pcc` removes the step. Batch-safe via `copy.deepcopy` (in-memory, no file write). Log: `pcc.cli_override` with `enabled`, `preset`, `inserted_after`/`removed`. Config `pcc.enabled` is `Optional[bool]=None` (`null` = Preset wins, only explicit set via `model_fields_set` overrides).")
    writer.p("Quick debug: `astra process --help` shows `--pcc/--no-pcc` (visible) and `--pcc-per-group` (visible); CFA hidden flags are documented in `11-troubleshooting.md` (advanced).")

    writer.h2("Smoke Testing (Subset Mode, V1.11-SUBSET)")
    writer.p("For quick validation on full production data without waiting for complete processing:")
    writer.code("astra process C:\\Astra\\M31 --from-suggested --limit 5 --dry-run", lang="bash")
    writer.ul([
    "Processes first 5 light frames per observation group (darks/bias/flats remain complete for proper calibration)",
    "Marked in run-info.json: `smoke_mode=true`, `limit=5`, `frames_considered=5`, `frames_total=247` (example with 247-frame full dataset)",
    "Useful after data migration (e.g., consolidate C:\\AstraTest into C:\\Astra) for quick smoke-test verification on real production data",
    "Fully deterministic: repeat with same `--limit` yields identical frame selection (natural sort, deterministic order)",
    "Incompatible with `--resume` (use `--limit` for fresh discovery + calibration runs only)",
    "Batch-compatible: `astra batch C:\\Astra --limit 3` applies 3-frame limit uniformly to every target",
    ])

    writer.write()


@generator("config")
def gen_config_reference() -> None:
    writer = DocWriter(DOCS_DIR / "04-configuration.md")
    writer.h1("Configuration")
    writer.p("> Auto-generated from `src/astro_process/config/models.py` + `config.yaml`")
    writer.p("> Precedence: CLI > Config > Env > Default")
    writer.hr()
    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from astro_process.config.models import AppConfig, ProcessingParams, MultiGroupConfig, MergeConfig, RegistrationConfig, GradientRemovalConfig, CosmeticCorrectionConfig, CFADrizzleConfig, FrameSelectionConfig
        import yaml
        cfg_yaml = load_yaml(CONFIG_YAML)
        models = [
            ("AppConfig (Root)", AppConfig),
            ("ProcessingParams", ProcessingParams),
            ("MultiGroupConfig", MultiGroupConfig),
            ("MergeConfig", MergeConfig),
            ("RegistrationConfig", RegistrationConfig),
            ("GradientRemovalConfig", GradientRemovalConfig),
            ("CosmeticCorrectionConfig", CosmeticCorrectionConfig),
            ("CFADrizzleConfig", CFADrizzleConfig),
            ("FrameSelectionConfig", FrameSelectionConfig),
        ]
        for title, model in models:
            writer.h2(title)
            try:
                fields = getattr(model, "model_fields", {})
                model_name = model.__name__
                rows = []
                for fname, finfo in fields.items():
                    ftype = str(finfo.annotation)[:60].replace("|", "/")
                    default_raw = str(finfo.default)[:40] if finfo.default is not None else ""
                    default = _redact_local_paths(default_raw)
                    desc = getattr(finfo, "description", "") or ""
                    if not desc:
                        desc = CONFIG_FIELD_EN.get(f"{model_name}.{fname}", "")
                    if not desc:
                        desc = "-"
                    rows.append([f"`{fname}`", ftype[:40], default, desc[:80]])
                if rows:
                    writer.table(["Field", "Type", "Default", "Description"], rows)
            except Exception as e:
                writer.p(f"Error in {title}: {e}")
        writer.h2("config.yaml (Defaults/Presets)")
        if cfg_yaml:
            yaml_block = yaml.safe_dump({k: v for k, v in cfg_yaml.items() if k != "pipeline_presets"}, sort_keys=False)[:3000]
            writer.code(_redact_local_paths(yaml_block), lang="yaml")
            writer.p(f"Presets defined: {len(cfg_yaml.get('pipeline_presets', []))}")
        writer.h2("Precedence & ENV")
        writer.ul([
            "1. CLI Flags (highest priority) — e.g. `--preset`, `--darks-path`, `--cosmetic-correction`",
            "2. `config.yaml` (User Config) — `data_root`, `darks_repository`, `default_preset`",
            "3. ENV Vars `ASTRA_*` — `ASTRA_DATA_ROOT`, `ASTRA_DARKS_REPOSITORY`, `ASTRA_DEFAULT_PRESET`",
            "4. Pydantic Defaults (lowest) — see tables above",
        ])
        writer.p("Validation: `astra config show --json` shows the merged view; `astra config set <key> <value>` validates via Pydantic, invalid values raise an error.")
        writer.h2("Environment Variables & .env File (V19-ENV)")
        writer.p("Astra supports cross-platform configuration via environment variables and `.env` files. `config.yaml` and `config.example.yaml` use `${VAR:-default}` placeholders that are resolved **before** `yaml.safe_load` via `os.path.expandvars` (manual regex, because Python 3.11 `expandvars` does not support `:-default`) + `Path.expanduser().resolve()`. After `astra init --non-interactive`, the generated `config.yaml` contains **resolved** absolute paths and no `${}`.")
        writer.p("Precedence for `.env` loading: **Shell Env > CWD/.env > pipeline_root/.env**. `python-dotenv` is loaded with `override=False`, so an existing Shell variable is never overwritten by `.env`. CWD wins over `pipeline_root` (project root that contains `src/astro_process`). Every path field is passed through `Path(value).expanduser().resolve()` after expansion, so `~/Astra` and `${HOME}/Astra` both resolve correctly. A missing `.env` triggers `astra doctor` warning `doctor.env_missing` (Exit 0, using defaults).")
        writer.p("References: `.env.example` and `config.example.yaml` in the repository root. Fresh users: `cp .env.example .env` → edit → `astra init --non-interactive` → `astra process`. Legacy `config.yaml` files with hardcoded paths (e.g. `C:/Users/<your-user>`) remain compatible — values without `${}` are left unchanged.")
        writer.h3("1. Windows (PowerShell, persistent)")
        writer.code('# PowerShell — persistent user env (new shell required afterwards)\n[Environment]::SetEnvironmentVariable("ASTRA_DATA_ROOT", "C:\\Astra", "User")\n[Environment]::SetEnvironmentVariable("ASTRA_DARKS_REPOSITORY", "C:\\Astra\\_darks", "User")\n[Environment]::SetEnvironmentVariable("GIMP_PATH", "gimp", "User")\n# verify in new shell\nGet-ChildItem Env:ASTRA_*\n# alternative (cmd): setx ASTRA_DATA_ROOT "C:\\Astra"', lang="powershell")
        writer.h3("2. Linux / macOS (bash, zsh)")
        writer.code('# bash / zsh — add to ~/.bashrc or ~/.zshrc for persistence\nexport ASTRA_DATA_ROOT="$HOME/Astra"\nexport ASTRA_DARKS_REPOSITORY="$HOME/Astra/_darks"\nexport GIMP_PATH="gimp"\n# verify\nenv | grep ASTRA_', lang="bash")
        writer.h3("3. .env File (recommended, cross-platform)")
        writer.code('# .env — copy from .env.example (do not commit secrets)\n# cp .env.example .env\nASTRA_DATA_ROOT=C:/Astra\nASTRA_DARKS_REPOSITORY=C:/Astra/_darks\nGIMP_PATH=gimp\nASTRA_DEFAULT_PRESET=star_standard\n# HOME fallback example:\n# ASTRA_DATA_ROOT=${HOME}/Astra', lang="dotenv")
        writer.h3("config.example.yaml — ${VAR:-default} expansion")
        writer.code('data_root: "${ASTRA_DATA_ROOT:-C:/Astra}"\ndarks_repository: "${ASTRA_DARKS_ROOT:-C:/Astra/_darks}"\ngimp_path: "${GIMP_PATH:-gimp}"\n# also supported: ${HOME}/Astra, $VAR, ${VAR}', lang="yaml")
        writer.p("`loader.py` expands every string value recursively via `_expand_env_string` before `yaml.safe_load`. `${VAR:-default}` → `env[VAR]` if set and non-empty, otherwise `default`; `${VAR}` / `$VAR` → `env[VAR]` or `\"\"` (empty, handled by `Path` guard so it does not resolve to CWD). Shell Env always wins over `.env`.")
        writer.h3("astra init --non-interactive (CI)")
        writer.p("`astra init --non-interactive` is the CI-friendly, non-interactive mode. It reads flags / env vars instead of prompting, writes `config.yaml` + `environment.yaml` (Pydantic-validated) with resolved absolute paths, and is safe for `CI Ubuntu+Win/3.11` (required check). Examples:")
        writer.code('astra init --non-interactive --data-root "$ASTRA_DATA_ROOT" --darks-library "$ASTRA_DARKS_REPOSITORY" --preset star_standard\n# or via .env only (no flags — env vars are read automatically)\ncp .env.example .env  # edit paths\nastra init --non-interactive\nastra doctor          # warns WARN doctor.env_missing if .env absent, but pipeline uses defaults', lang="bash")
        writer.p("`astra doctor` (read-only) checks: Python, dependencies, GAIA, `config.yaml`, disk, paths, and `.env` existence. `astra doctor --fix` can create a missing `.env` from `.env.example`. Precedence for config discovery: explicit `--config path` > `CWD/config.yaml` > `pipeline_root/config.yaml` > `DEFAULT_CONFIG` string (wheel fallback). Each discovery is logged as `config.loaded_from` (source, path).")
        writer.h3("CFA-Drizzle Quality Gate — Precedence (hidden flags, advanced)")
        writer.p("CFA-Drizzle auto selects locking thresholds based on input type. Precedence: **CLI > Config > CFA-Smart-Defaults > Debayered-Defaults**. Hidden flags are documented here (advanced, not in Quickstart) — see `11-troubleshooting.md` for the full list: `--cfa-drizzle-fallback`, `--cfa-drizzle-star-count-min`, `--cfa-drizzle-snr-min`, `--cfa-drizzle-correlation-min`, `--cfa-drizzle-fwhm-range`.")
    except Exception as e:
        writer.p(f"**Error during model extraction:** {e}")
        import traceback; writer.code(traceback.format_exc(), lang="text")
    writer.write()


@generator("presets")
def gen_presets_doc() -> None:
    writer = DocWriter(DOCS_DIR / "05-presets.md")
    writer.h1("Presets")
    writer.p("> Auto-generated from `config.yaml` `pipeline_presets`")
    writer.hr()
    writer.p("**Choosing a preset?** Run `astra suggest <TARGET>` to get offline recommendations based on object type (galaxy/nebula/star) from the handbook and target-cache. See Handbook Ch. 17 and `03-cli-reference.md suggest` for details.")
    data = load_yaml(CONFIG_YAML)
    presets = data.get("pipeline_presets", [])
    for preset in presets:
        writer.h2(preset.get("name", "unknown"))
        writer.p(f"**Target Types:** {', '.join(preset.get('target_types', []))}")
        steps = preset.get("steps", [])
        if steps:
            rows = [[s.get("name", ""), str(s.get("params", ""))[:60] or "-"] for s in steps]
            writer.table(["Step", "Params"], rows)
        pp = preset.get("processing_params", {})
        if pp:
            rows = [[k, str(v)[:60]] for k, v in pp.items()]
            writer.table(["Param", "Value"], rows)
        if preset.get("description"):
            writer.p(preset["description"])
    # ── V19-PCC-FLAG: Use Cases + --pcc-per-group ─────────────────────────
    writer.h2("PCC Flag — Use Cases (V19-PCC-FLAG)")
    writer.p("PCC = Photometric Color Calibration (star detection + GAIA/VizieR matching + gray_world fallback). Timeout 30 s × retry can accumulate to 6 min on star-poor fields (M31). CLI `--pcc/--no-pcc` (default `None` = Preset/Config wins, no breaking change) mutates preset steps in-memory (see `03-cli-reference.md`). Precedence: **CLI `--pcc/--no-pcc` > Config `pcc.enabled` > Preset Steps > Default**.")
    writer.table(["Use Case", "Command", "Effect"], [
        ["Galaxy (M31), PCC skip (fast, avoid timeout)", "`astra process M31 --preset galaxy_standard --no-pcc`", "Removes `photometric_color_calibration` — fast, no 6 min GAIA block"],
        ["Nebula, force PCC", "`astra process M42 --preset nebula_standard --pcc`", "Inserts PCC after `background_extraction` (exactly once)"],
        ["Star cluster, force PCC", "`astra process M45 --preset star_standard --pcc`", "Same insertion — `star_standard` has none by default"],
        ["Nebula default (preset has none, no flag)", "`astra process M42 --preset nebula_standard`", "No PCC (Preset wins)"],
        ["Galaxy default (preset has PCC, no flag)", "`astra process M31 --preset galaxy_standard`", "PCC runs (Preset wins)"],
        ["Config fallback", "`pcc.enabled: true/false` in `config.yaml` (no CLI)", "Overrides Preset when CLI `None` (checked via `model_fields_set`)"],
    ])
    writer.h2("`--pcc-per-group` Interaction")
    writer.p("`--pcc-per-group/--no-pcc-per-group` (default `None` → `false` = PCC on merged stack for max S/N) is **independent** of `--pcc/--no-pcc` (which turns PCC on/off). Both flags compose:")
    writer.table(["`--pcc`", "`--pcc-per-group`", "Behavior"], [
        ["`--pcc`", "`--pcc-per-group`", "PCC runs per group (each `group_*/04_stacked/pcc_applied.fits`) *before* merge — less S/N per group, more groups"],
        ["`--pcc`", "`--no-pcc-per-group` (default)", "PCC runs **once on merged stack** (default, max S/N)"],
        ["`--no-pcc`", "either", "No PCC at all (per-group flag is moot)"],
        ["`None` + `pcc.enabled`**", "either", "Config `pcc.enabled` decides on/off; `--pcc-per-group` decides where"],
    ])
    writer.p("Insertion log: `pcc.cli_override` (`enabled`, `preset`, `inserted_after`=`background_extraction`/`stack_frames`/`stack_frames_fallback` or `removed`). Mutation is `copy.deepcopy` per call, never persisted to `config.yaml`.")
    writer.write()


@generator("multigroup")
def gen_multi_group_doc() -> None:
    writer = DocWriter(DOCS_DIR / "06-multi-group.md")
    writer.h1("Multi-Group")
    writer.p("> Auto-generated from `doc_data/multi_group.md`, `src/astro_process/cli.py` merge flags, and `src/astro_process/agents/multi_group_agent.py`.")
    writer.hr()

    fragment = _read_doc_data("multi_group.md")
    if fragment:
        writer.lines.extend(fragment.splitlines())
        writer.p("")

    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from astro_process.cli import cli as astra_cli
        merge_cmd = astra_cli.commands.get("merge")
        if merge_cmd is not None:
            writer.h2("Merge subcommand (`astra merge`)")
            help_text = _en_help(getattr(merge_cmd, "help", "") or getattr(merge_cmd, "short_help", "") or "", context="command merge")
            writer.p(_truncate_at_word(help_text, 600))
            rows = []
            for p in merge_cmd.params:
                pname = ", ".join(p.opts) if hasattr(p, "opts") else str(p.name)
                ptype = getattr(p.type, "name", str(type(p.type).__name__))
                if hasattr(p.type, "choices"):
                    try:
                        ch = list(p.type.choices)  # type: ignore
                        if ch:
                            ptype = f"Choice({','.join(map(str, ch))})"
                    except Exception:
                        pass
                rows.append([
                    f"`{pname}`",
                    ptype,
                    _redact_local_paths(str(p.default)) if p.default is not None else "",
                    _truncate_at_word(_en_help(getattr(p, "help", "") or "", context=f"flag {pname}"), 80),
                ])
            if rows:
                writer.table(["Flag", "Type", "Default", "Description"], rows)
    except Exception as e:
        writer.p(f"Error introspecting merge command: {e}")

    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from astro_process.cli import cli as astra_cli
        process_cmd = astra_cli.commands.get("process")
        merge_flags = []
        if process_cmd is not None:
            for p in process_cmd.params:
                pname = ", ".join(p.opts) if hasattr(p, "opts") else str(p.name)
                if any(k in pname for k in ("--merge", "--weight-by", "--merge-method", "--merge-filter")):
                    ptype = getattr(p.type, "name", str(type(p.type).__name__))
                    if hasattr(p.type, "choices"):
                        try:
                            ch = list(p.type.choices)  # type: ignore
                            if ch:
                                ptype = f"Choice({','.join(map(str, ch))})"
                        except Exception:
                            pass
                    merge_flags.append([
                        f"`{pname}`",
                        ptype,
                        _redact_local_paths(str(p.default)) if p.default is not None else "",
                        _truncate_at_word(_en_help(getattr(p, "help", "") or "", context=f"flag {pname}"), 100),
                    ])
        if merge_flags:
            writer.h2("`process` merge flags")
            writer.table(["Flag", "Type", "Default", "Description"], merge_flags)
    except Exception as e:
        writer.p(f"Error introspecting process merge flags: {e}")

    p = SRC_DIR / "agents" / "multi_group_agent.py"
    if p.exists():
        summary = _en_module_summary(p.stem)
        if summary:
            writer.h2("Source: multi_group_agent.py")
            writer.p(summary)
        symbols = _extract_top_level_symbols(p)
        public = [(kind, name) for kind, name, _ in symbols if not name.startswith("_")]
        if public:
            rows = []
            for kind, name in public[:8]:
                en = _en_symbol(p.stem, name)
                rows.append([f"`{name}`", kind, _truncate_at_word(en, 80) if en is not None else "—"])
            if rows:
                writer.table(["Symbol", "Kind", "Description"], rows)

    writer.write()


@generator("registration")
def gen_registration_doc() -> None:
    writer = DocWriter(DOCS_DIR / "07-registration.md")
    writer.h1("Registration")
    writer.p("> Extracted from `src/astro_process/core/registration.py` — structural reference with English summaries.")
    writer.p("> V19-REG-SMART: Smart Default + Decision Matrix + Ghosting (rotation_deg 0.0)")
    writer.hr()
    p = SRC_DIR / "core" / "registration.py"
    summary = _en_module_summary(p.stem)
    if summary:
        writer.p(summary)
    if p.exists():
        symbols = _extract_top_level_symbols(p)
        public = [(kind, name) for kind, name, _ in symbols if not name.startswith("_")]
        if public:
            rows = []
            for kind, name in public:
                en = _en_symbol(p.stem, name)
                rows.append([f"`{name}`", kind, _truncate_at_word(en, 80) if en is not None else "—"])
            writer.table(["Symbol", "Kind", "Description"], rows)
    # ── V19-REG-SMART Decision Matrix + Ghosting ──────────────────────────
    writer.h2("Decision Matrix (Mount | Exposure | Method | Reasoning)")
    writer.p("Smart Default chooses the registration method without CLI flags. `fft` = translation-only (fast), `astroalign` = feature-based with rotation/scale (robust), `rotation_fft` = log-polar FFT rotation (fallback when `astroalign` extra missing).")
    writer.table(["Mount", "Exposure", "Recommended Method", "Reasoning"], [
        ["EQ (polar aligned)", "< 120 s", "`fft`", "Fast, precise, no rotation — Phase Correlation sufficient"],
        ["EQ", "> 120 s", "`astroalign`", "Drift correction, larger shift/scale"],
        ["AZ (Dwarf Mini, Seestar, AZ)", "any", "`astroalign`", "Feature-based, corrects field rotation (Smart Default `dwarf_mini`)"],
        ["AZ", "30–120 s", "`astroalign` (`rotation_fft` fallback)", "Log-Polar FFT less robust with few stars — `astroalign` is default, `rotation_fft` only if extra missing"],
        ["Planetary / Lucky", "< 1 s", "`fft`", "Hundreds of frames, speed critical, negligible rotation"],
        ["Unknown / Auto", "any", "Auto-Detect", "Header analysis `EQUAT`/`MOUNT`/`TELESCOP` → AZ/EQ, else `eq` + `discovery.mount_unknown` warning"],
    ])
    writer.h2("Ghosting — why `rotation_deg 0.0` is a red flag")
    writer.p("**Symptom:** Stack shows double-star contours at the image border, `frame 27: method fft rotation_deg 0.0 shift_y 31 shift_x -44`. **Root cause:** `cv2.phaseCorrelate` / `FftGridRegistration` measures only X/Y translation, no rotation. The shift is `rotation_deg: 0.0` by construction — the image is only shifted, edge stars drift circularly due to field rotation and double when stacked.")
    writer.p("**Solution:** `astra process ... --registration-method astroalign --max-rotation 15` (or set Equipment profile `preferred_registration: astroalign`, `max_rotation_deg: 15`). For `dwarf_mini` the default is already `astroalign 15°` — no flag needed. Warning `registration.fft_on_az_mount` is emitted when `fft` + `az` + `exptime >= 45 s` (threshold `max_exptime_fft_warn: 45`):")
    writer.code('WARN registration.fft_on_az_mount method=fft mount_type=az exptime=60 threshold=45\n     detail="FFT on AZ with 60s — field rotation not correctable. Expected: Ghosting at borders.\n     Solution: --registration-method astroalign --max-rotation 15\n     or Equipment profile with preferred_registration: astroalign"', lang="text")
    writer.h2("Auto-Detect — Headers `EQUAT` / `MOUNT` / `TELESCOP`")
    writer.code('AZ_DEVICES = ["DWARF MINI", "DWARF II", "SEESTAR", "ZWO ASIAIR", "SMARTTELESCOPE"]\n\ndef detect_mount_type(header):\n    equat = str(header.get("EQUAT","")).upper()   # AZ / ALTAZ / ALT-AZ → az\n    mount = str(header.get("MOUNT","")).upper()   # same\n    telescop = str(header.get("TELESCOP","")).upper()  # DWARF MINI → az\n    # fallback: header without mount → eq + WARN discovery.mount_unknown', lang="python")
    writer.p("`detect_preferred_registration(header, exptimes)` (in `core/equipment.py` or `agents/discovery.py`): AZ → always `astroalign` (exptime 30/60 thresholds collapsed to `astroalign` per OQ-REG-1, `rotation_fft` only as explicit `preferred_registration` or when `astroalign` extra missing). EQ → `fft` if `max_exptime <= 120`, else `astroalign`. Threshold `max_exptime_fft_warn` per profile (default 45 s, `dwarf_mini: 45`).")
    writer.h2("Priority Chain — `resolve_registration_config`")
    writer.p("Precedence (highest wins): **1. CLI `--registration-method` / `--max-rotation` > 2. Equipment Profile (`mount_type`, `preferred_registration`, `max_rotation_deg`, `max_exptime_fft_warn`) > 3. Auto-Detect (`EQUAT`/`MOUNT`/`TELESCOP`, header + exptimes) > 4. Config Default (`config.yaml registration.method`) > 5. hardcoded `fft` (2.0° default).** CLI always wins. Implemented as new `resolve_registration_config(cfg, equipment, header, exptimes, cli_method)` extending (not replacing) existing `resolve_registration(cfg, pipeline, ...)` — avoids signature collision.")
    writer.code('# equipment_profiles in config.yaml\n- name: "dwarf_mini"\n  mount_type: "az"\n  preferred_registration: "astroalign"\n  max_rotation_deg: 15\n  max_exptime_fft_warn: 45\n- name: "dwarf3"\n  deprecated: true\n  alias_for: "dwarf_mini"  # WARN equipment.profile_deprecated', lang="yaml")
    writer.h2("Multi-Group — per group + Cross-Group always astroalign")
    writer.p("`resolve_group_registration_configs(cfg, groups, cli_override, global_equipment)` resolves the registration config for each group individually: header + exptimes per `group_*/` → per-group `mount_type`/`method` via the same Priority Chain. Logged as `multi_group.group_registration_config` (`group`, `method`, `mount_type`, `max_exptime`).")
    writer.p("**Cross-Group Registration (Merge Phase) always `astroalign 20°` (`max_scale_dev 0.05`)** — independent of intra-group method. Rationale: large rotation/shift across nights / meridian flip / mount mix; intra-group = small dither shifts, cross-group = large offsets → separate configs. Optional `config.yaml`: `multi_group.registration.intra_group: auto` + `cross_group: astroalign` (not yet enforced, convention).")
    writer.code('cross_group_config = {"method": "astroalign", "max_rotation_deg": 20.0, "max_scale_dev": 0.05}', lang="python")
    writer.p("Example: 2 groups (AZ 60 s + EQ 30 s, `cli_override=None`) → `{\"group_az\": {\"method\":\"astroalign\"}, \"group_eq\": {\"method\":\"fft\"}}`, both `logger.info multi_group.group_registration_config`.")
    writer.write()


@generator("gradient")
def gen_gradient_doc() -> None:
    writer = DocWriter(DOCS_DIR / "08-gradient-removal.md")
    writer.h1("Gradient Removal")
    writer.p("> Extracted from `src/astro_process/core/gradient_removal.py` and `config/models.py GradientRemovalConfig`.")
    writer.hr()
    p = SRC_DIR / "core" / "gradient_removal.py"
    summary = _en_module_summary(p.stem)
    if summary:
        writer.p(summary)
    if p.exists():
        symbols = _extract_top_level_symbols(p)
        public = [(kind, name) for kind, name, _ in symbols if not name.startswith("_")]
        if public:
            rows = []
            for kind, name in public:
                en = _en_symbol(p.stem, name)
                rows.append([f"`{name}`", kind, _truncate_at_word(en, 80) if en is not None else "—"])
            writer.table(["Symbol", "Kind", "Description"], rows)
    try:

        sys.path.insert(0, str(REPO_ROOT / "src"))
        from astro_process.config.models import GradientRemovalConfig
        writer.h2("GradientRemovalConfig")
        for fname, finfo in getattr(GradientRemovalConfig, "model_fields", {}).items():
            writer.p(f"- `{fname}`: default={finfo.default} type={finfo.annotation}")
    except Exception:
        pass
    writer.write()


@generator("darks")
def gen_darks_doc() -> None:
    writer = DocWriter(DOCS_DIR / "09-darks-library.md")
    writer.h1("Darks Library")
    writer.p("> Auto-generated from `doc_data/darks.md`, `astra darks` Click introspection, and `src/astro_process/agents/calibration.py`.")
    writer.hr()

    fragment = _read_doc_data("darks.md")
    if fragment:
        writer.lines.extend(fragment.splitlines())
        writer.p("")

    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from astro_process.cli import cli as astra_cli
        darks_group = astra_cli.commands.get("darks")
        if darks_group is not None and hasattr(darks_group, "commands"):
            writer.h2("`astra darks` subcommands")
            rows = []
            for sub_name, sub_cmd in sorted(darks_group.commands.items()):
                help_text = _en_help(getattr(sub_cmd, "help", "") or getattr(sub_cmd, "short_help", "") or "", context=f"darks {sub_name}")
                rows.append([f"`astra darks {sub_name}`", _truncate_at_word(help_text, 100)])
            if rows:
                writer.table(["Command", "Description"], rows)

            for sub_name, sub_cmd in sorted(darks_group.commands.items()):
                writer.h3(f"`astra darks {sub_name}`")
                help_text = _en_help(getattr(sub_cmd, "help", "") or getattr(sub_cmd, "short_help", "") or "", context=f"darks {sub_name}")
                writer.p(_truncate_at_word(help_text, 600))
                if sub_cmd.params:
                    rows = []
                    for p in sub_cmd.params:
                        pname = ", ".join(p.opts) if hasattr(p, "opts") else str(p.name)
                        ptype = getattr(p.type, "name", str(type(p.type).__name__))
                        if hasattr(p.type, "choices"):
                            try:
                                ch = list(p.type.choices)  # type: ignore
                                if ch:
                                    ptype = f"Choice({','.join(map(str, ch))})"
                            except Exception:
                                pass
                        rows.append([
                            f"`{pname}`",
                            ptype,
                            _redact_local_paths(str(p.default)) if p.default is not None else "",
                            _truncate_at_word(_en_help(getattr(p, "help", "") or "", context=f"flag {pname}"), 80),
                        ])
                    if rows:
                        writer.table(["Flag", "Type", "Default", "Description"], rows)
    except Exception as e:
        writer.p(f"Error introspecting darks commands: {e}")

    p = SRC_DIR / "agents" / "calibration.py"
    if p.exists():
        writer.h2("Source: `_find_darks_for_group` matching order")
        en = _en_symbol(p.stem, "_find_darks_for_group")
        if en:
            writer.p(en)
        writer.ol([
            "**local** — darks in the target's own `darks/` folder.",
            "**library_exact** — darks from the library with matching exposure/gain (temperature matched when possible).",
            "**library_nearest** — nearest-temperature dark in the same `(exp, gain)` bucket (tolerance up to 10 °C).",
            "**none** — no dark available; the group remains uncalibrated but the run continues with a warning.",
        ])

    writer.write()


@generator("output")
def gen_output_doc() -> None:
    writer = DocWriter(DOCS_DIR / "10-output-structure.md")
    writer.h1("Output Structure")
    writer.p("> Auto-generated from `src/astro_process/agents/archive.py`, `src/astro_process/core/fits_parser.py` `OUTPUT_SUBDIRS`, and source-extracted constants.")
    writer.hr()

    p = SRC_DIR / "agents" / "archive.py"
    if p.exists():
        summary = _en_module_summary(p.stem)
        if summary:
            writer.h2("Archive Agent")
            writer.p(summary)

    fp = SRC_DIR / "core" / "fits_parser.py"
    if fp.exists():
        import ast
        try:
            tree = ast.parse(fp.read_text(encoding="utf-8"))
            subdirs: list[str] = []
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "OUTPUT_SUBDIRS":
                            if isinstance(node.value, (ast.Set, ast.List, ast.Tuple)):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        subdirs.append(elt.value)
            if subdirs:
                writer.h2("Output subdirectories skipped during scan (`OUTPUT_SUBDIRS`)")
                writer.ul(sorted(subdirs))
        except Exception:
            pass

    writer.h2("Run directory layout")
    writer.code("""generated/<timestamp>/
├── 00_input/
│   └── master/
│       ├── master_dark_{group_hash}.fits
│       ├── master_flat_*.fits
│       └── ...
├── 01_calibrated/
├── 02_debayered/
├── group_{hash}/
│   ├── 03_registered/
│   └── 04_stacked/
│       ├── stacked.fits
│       ├── aligned.fits
│       ├── pcc_applied.fits
│       └── preview_{hash}.jpg
├── merged/
│   ├── <Target>_merged.fits
│   ├── <Target>_merged_preview.jpg
│   └── merge_report.json
├── agent-log.yaml
└── run-info.json""", lang="text")

    writer.h2("Final output resolution")
    writer.p("The Archive Agent resolves the final FITS in the following order:")
    writer.ol([
        "`merged/<Target>_merged.fits` (canonical since v1.3-6)",
        "Legacy top-level `<Target>_final.fits` (only from direct API use)",
    ])
    writer.p("External tools should always point to the `merged/` path.")

    writer.write()


@generator("troubleshooting")
def gen_troubleshooting_doc() -> None:
    writer = DocWriter(DOCS_DIR / "11-troubleshooting.md")
    writer.h1("Troubleshooting")
    writer.p("> Auto-generated from `doc_data/troubleshooting.md`, `src/astro_process/cli.py` exit codes, and `doc_data/releases_summary.md`.")
    writer.hr()

    fragment = _read_doc_data("troubleshooting.md")
    if fragment:
        writer.lines.extend(fragment.splitlines())
        writer.p("")

    writer.h2("CLI exit codes (source-extracted)")
    try:
        cli_text = (SRC_DIR / "cli.py").read_text(encoding="utf-8")
        exits: list[tuple[str, str]] = []
        for m in re.finditer(r'sys\.exit\((\d+)\)', cli_text):
            line_no = cli_text[:m.start()].count("\n") + 1
            exits.append((m.group(1), f"src/astro_process/cli.py:{line_no}"))
        for m in re.finditer(r'ctx\.exit\((\d+)\)', cli_text):
            line_no = cli_text[:m.start()].count("\n") + 1
            exits.append((m.group(1), f"src/astro_process/cli.py:{line_no}"))
        if exits:
            writer.table(
                ["Exit code", "Location"],
                [[code, loc] for code, loc in sorted(set(exits))],
            )
        else:
            writer.p("No explicit `sys.exit` / `ctx.exit` calls found.")
    except Exception as e:
        writer.p(f"Error extracting exit codes: {e}")

    releases_summary = _read_doc_data("releases_summary.md")
    if releases_summary:
        writer.h2("Known issues reflected in releases")
        # Use only the known-issues section (last header before EOF)
        lines = releases_summary.splitlines()
        capture = False
        for line in lines:
            if line.strip().startswith("## Known issues"):
                capture = True
                continue
            if capture:
                if line.startswith("#"):
                    break
                writer.lines.append(line)
        writer.p("")

    writer.write()


@generator("migration")
def gen_migration_doc() -> None:
    writer = DocWriter(DOCS_DIR / "12-migration.md")
    writer.h1("Migration")
    writer.p("> Auto-generated from `doc_data/migration.md` and `doc_data/releases_summary.md`.")
    writer.hr()

    fragment = _read_doc_data("migration.md")
    if fragment:
        writer.lines.extend(fragment.splitlines())
        writer.p("")

    releases_summary = _read_doc_data("releases_summary.md")
    if releases_summary:
        lines = releases_summary.splitlines()

        def _capture_section(start_prefix: str, stop_prefixes: list[str]) -> list[str]:
            """Capture lines between start header and the next stop header, excluding both."""
            result: list[str] = []
            capture = False
            for line in lines:
                if line.strip().startswith(start_prefix):
                    capture = True
                    continue
                if capture:
                    if any(line.strip().startswith(p) for p in stop_prefixes):
                        break
                    result.append(line)
            return result

        version_lines = _capture_section("## Version overview", ["## Breaking", "## Known"])
        if version_lines:
            writer.h2("Release overview")
            writer.lines.extend(version_lines)
            writer.p("")

        breaking_lines = _capture_section("## Breaking", ["## Known"])
        if breaking_lines:
            writer.h2("Breaking changes")
            writer.lines.extend(breaking_lines)
            writer.p("")

    writer.write()


@generator("docs_readme")
def gen_docs_readme() -> None:
    """Generate English docs/README.md landing page."""
    writer = DocWriter(DOCS_DIR / "README.md")
    writer.h1("Astra Pipeline — Technical Documentation")
    writer.p("> **Audience:** Users of the `astro_process` pipeline (CLI, config, presets, output).")
    writer.p("> **Not here:** Astrophotography basics, Siril workflows, GIMP/GraXpert → see `../handbook/`.")
    writer.hr()
    writer.h2("Document overview")
    writer.p("The `docs/` folder contains the user-facing, auto-generated documentation for Astra.")
    writer.table(
        ["File", "Topic"],
        [
            ["`01-quickstart.md`", "Installation, first `astra process` run, dry-run"],
            ["`02-pipeline-architecture.md`", "Pipeline phases, agents, data model, working directories"],
            ["`03-cli-reference.md`", "All subcommands, flags, precedence, wizard"],
            ["`04-configuration.md`", "Layered config, `config.yaml`, env vars, `AppConfig`"],
            ["`05-presets.md`", "Presets, steps, `processing_params`"],
            ["`06-multi-group.md`", "Multi-group stacking, cross-group registration, merge"],
            ["`07-registration.md`", "Registration methods (fft/astroalign/rotation_fft), SanityGuard"],
            ["`08-gradient-removal.md`", "Gradient removal"],
            ["`09-darks-library.md`", "Darks library, `astra darks sync`, TELE/WIDE rule"],
            ["`10-output-structure.md`", "Output structure (`generated/`, `group_*`, `merged/`, logs)"],
            ["`11-troubleshooting.md`", "Troubleshooting (error codes, known limitations, FAQ)"],
            ["`12-migration.md`", "Migration (v1.1→v1.2→v1.3, breaking changes)"],
            ["`INDEX.md`", "Auto-generated navigation"],
        ],
    )
    writer.h2("handbook/ vs docs/")
    writer.table(
        ["", "`handbook/`", "`docs/`"],
        [
            ["**Focus**", "Learn astrophotography & use Siril", "Operate the `astro_process` pipeline"],
            ["**Tools**", "Dwarf3, Siril 1.4.4, GraXpert, GIMP", "Python, `astra-process`, FITS, config"],
            ["**Content**", "37 chapters: acquisition, calibration, stacking, object classes", "12 chapters: pipeline phases, CLI, config, presets, output"],
        ],
    )
    writer.p("Both folders are independent.")
    writer.h2("Generation (for developers)")
    writer.p("Contents are **not copied manually**; they are generated from source:")
    writer.ul([
        "`03-cli-reference.md` ← `src/astro_process/cli.py`",
        "`04-configuration.md` ← `src/astro_process/config/models.py` + `config.yaml`",
        "`05-presets.md` ← `config.yaml` `pipeline_presets`",
        "`02-pipeline-architecture.md` ← `src/astro_process/core/` module structure",
    ])
    writer.code("""# Generate all docs
python scripts/generate_docs.py all

# Individual generators
python scripts/generate_docs.py cli
python scripts/generate_docs.py config
python scripts/generate_docs.py presets
python scripts/generate_docs.py arch
python scripts/generate_docs.py index

# CI check: are docs up to date?
python scripts/generate_docs.py check""", lang="bash")
    writer.p("> **INDEX.md** and this README are auto-generated — **do not edit manually**. Run `python scripts/generate_docs.py all` after changes.")
    writer.write()


@generator("index")
def gen_index_doc() -> None:
    """Generate INDEX.md as navigation/table of contents for docs."""
    writer = DocWriter(DOCS_DIR / "INDEX.md")
    writer.h1("Astra Pipeline — Documentation Index")
    writer.p("> Auto-generated from `docs/` — **do not edit manually**")
    writer.p("> Generator: `python scripts/generate_docs.py index`")
    writer.hr()
    doc_files = sorted(DOCS_DIR.glob("[0-9][0-9]-*.md"))
    writer.h2("Documentation")
    writer.p("")
    for doc_file in doc_files:
        name = doc_file.stem
        content = doc_file.read_text(encoding="utf-8")
        title = name.replace("-", " ").title()
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break
        writer.p(f"- [{title}]({doc_file.name})")
    writer.hr()
    writer.p("> Auto-generated — run `python scripts/generate_docs.py index` after changes")
    writer.write()


@generator("all")
def generate_all() -> None:
    """Generate all documentation files."""
    print("Generating all documentation...")
    order = [
        "quickstart", "arch", "cli", "config", "presets",
        "multigroup", "registration", "gradient", "darks", "output",
        "troubleshooting", "migration", "docs_readme", "index",
    ]
    for name in order:
        if name in GENERATORS:
            print(f"  -> {name}")
            GENERATORS[name]()
    hash_file = DOCS_DIR / ".doc_hashes.json"
    current_hashes = {
        "cli.py": file_hash(SRC_DIR / "cli.py"),
        "models.py": file_hash(SRC_DIR / "config" / "models.py"),
        "config.yaml": file_hash(CONFIG_YAML),
        "core/": file_hash(SRC_DIR / "core"),
    }
    hash_file.write_text(json.dumps(current_hashes, indent=2), encoding="utf-8", newline="\n")
    print(f"  [OK] Hash file written: {hash_file.relative_to(REPO_ROOT)}")
    print("Done.")


def _scan_docs_for_german() -> dict[str, list[str]]:
    """Return per-file German/umlaut hits for generated docs."""
    umlaut_re = re.compile(r"[äöüßÄÖÜ]")
    prose_re = re.compile(
        r"\b(oder|Methode|der|die|das|und|nicht|ist|mit|auf|fuer|ueber|wird|sonst|"
        r"Standard|Schritt|Architektur|Doku|vorhandene|vorhanden|Durchsucht|durchsucht|"
        r"extrahiert|ueberschreibt|aktiv|deaktivieren|Ausgelagert|Verhaltensaenderung|"
        r"Verschoben|Generierung|Dokumenten|Zielgruppe|Vollst|kein|Keine|"
        r"Standardmaessig|sonstige)\b",
        re.IGNORECASE,
    )
    hits: dict[str, list[str]] = {}
    for path in sorted(DOCS_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        problems: list[str] = []
        for m in umlaut_re.finditer(content):
            # report first few umlaut hits with context
            problems.append(f"umlaut:{m.group()}")
            if len(problems) >= 5:
                break
        for m in prose_re.finditer(content):
            # §17 false-positive guard: "MIT" license (all caps) is English, not German "mit"
            if m.group() == "MIT":
                continue
            problems.append(f"german:{m.group()}")
            if len(problems) >= 10:
                break
        if problems:
            hits[path.name] = problems
    return hits


@generator("check")
def check_docs_up_to_date() -> int:
    hash_file = DOCS_DIR / ".doc_hashes.json"
    current_hashes = {
        "cli.py": file_hash(SRC_DIR / "cli.py"),
        "models.py": file_hash(SRC_DIR / "config" / "models.py"),
        "config.yaml": file_hash(CONFIG_YAML),
        "core/": file_hash(SRC_DIR / "core"),
    }
    if not hash_file.exists():
        print("  [INFO] No hash file found -- run 'generate_docs.py all' first")
        return 1
    stored = load_json(hash_file)
    outdated = [k for k, v in current_hashes.items() if stored.get(k) != v]
    if outdated:
        print(f"  [FAIL] Outdated sources: {', '.join(outdated)}")
        print("  -> Run: python scripts/generate_docs.py all")
        return 1
    german_hits = _scan_docs_for_german()
    if german_hits:
        print("  [FAIL] Generated docs contain German prose/umlauts:")
        for fname, problems in german_hits.items():
            print(f"    {fname}: {', '.join(problems[:8])}")
        return 1
    print("  [OK] All docs up to date and English-clean")
    return 0


# ─── Main ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Astra Documentation Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/generate_docs.py all       # Generate all docs
  python scripts/generate_docs.py cli       # Only CLI reference
  python scripts/generate_docs.py check     # CI check (exit 1 if outdated)
        """
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=list(GENERATORS.keys()) + ["check"],
        help="Generator to run (default: all)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()
    if args.command == "check":
        return check_docs_up_to_date()
    if args.command in GENERATORS:
        GENERATORS[args.command]()
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
