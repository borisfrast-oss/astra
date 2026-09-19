# CLI Reference

> Auto-generated from `src/astro_process/cli.py` — **do not edit manually**.

> Generator: `python scripts/generate_docs.py cli`

> Precedence: CLI > Config > Env > Default (see `04-configuration.md`)

---

## Subcommands

| Command | Description | Flags |
| --- | --- | --- |
| `batch` | Process all subdirectories in data root. | data_root, --preset, --dry-run, --limit |
| `config` | Manage configuration (precedence: CLI > Config > Env > Default). | - |
| `config show` | Show the fully merged configuration (defaults + user + env) -- Precedence CLI > Config > Env > Default. | - |
| `config get` | Get a single configuration value via dot-notation (e.g. data_root, multi_group.merge.method). | - |
| `config set` | Set a configuration value (validated via Pydantic; invalid values raise an error) and save config.yaml. | - |
| `config reset` | Reset a key to its default and remove it from config.yaml. | - |
| `config wizard` | Interactive TUI configuration wizard. | - |
| `darks` | Manage the Darks Library (sync/list/check/import). | - |
| `darks sync` | Sync DwarfLab export into the Darks Library (TELE/cam_0 only, never WIDE/cam_1). | - |
| `darks list` | List dark frames in the library. | - |
| `darks check` | Check dark-frame coverage for a target. | - |
| `darks import` | Import dark frames from a path into the library. | - |
| `doctor` | Environment check: Python, dependencies, GAIA, config, disk, paths. Read-only. | target_path, --fix |
| `download-example` | Download a real-data example (10 M31 FITS as GitHub Release asset). | target, --n, --output, --force |
| `init` | Initialize Astra configuration (Wizard). | --non-interactive, --project-dir, --data-root, --darks-library |
| `inspect` | Inspect FITS headers in target directory. | target_path, --json, --eqmode, --frames |
| `merge` | Merge existing group stacks into a single FITS. | target_path, --method, --weight-by, --merge-filter |
| `organize` | Organize flat lights in C:\Astra\<Target>\lights\ into group folders. | target, --dry-run, --all |
| `plugin` | Plugin management (v1.2, PL-C): pipeline-step plugins in the | - |
| `plugin list` | List registered pipeline-step plugins (PL-C). | - |
| `process` | Process a single target directory. | target_path, --preset, --dry-run, --keep-working |
| `qc` | Quality checker: measures flip/ghosting/color from generated/<ts>/. | generated, --all, --latest, --json |
| `status` | Show system status (disk space, recent runs, darks library, config health, queue). | --json |
| `suggest` | Suggest a preset/registration/debayer/PCC combination for TARGET. | target, --header, --coords, --output |
| `target` | Target management (list/add/show/update/remove). | - |
| `target list` | List all targets and their progress. | - |
| `target add` | Create a new target and generate an AUFNAHMELISTE_{Target}.md template. | - |
| `target show` | Show details for a target. | - |
| `target update` | Update a target (e.g. preset in AUFNAHMELISTE). | - |
| `target remove` | Remove a target (optional). | - |

## Global Flags

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--config, -c` | path | Sentinel.UNSET | Config file (global, must be placed BEFORE the subcommand, e.g. --config config.yaml process <target>). Without --config the pipeline automatically searches for config.yaml in the current directory or project root. |
| `--verbose, -v` | boolean | False | Verbose output |
| `--version` | boolean | False | Show the version and exit. |

## `batch`

Process all subdirectories in data root.

    Each target directory must have a suggested.yaml (run 'astra suggest
    <TARGET>' first). The per-target suggested.yaml is passed via
    --from-suggested (Target-Root default). Missing file -> Error (ENTS-1).
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `data_root` | path | Sentinel.UNSET |  |
| `--preset, -p` | text |  | Preset override for all targets (default: from per-target suggested.yaml) |
| `--dry-run` | boolean | False |  |
| `--limit` | integer |  | Limit number of light frames per group for smoke testing - applied uniformly to every target in the batch (N >= 1). See 'astra process --help' for details. |

## `config`

Manage configuration (precedence: CLI > Config > Env > Default).

### `config show`

Show the fully merged configuration (defaults + user + env) -- Precedence CLI > Config > Env > Default.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--json` | boolean | False | Machine-readable output (JSON) |

### `config get`

Get a single configuration value via dot-notation (e.g. data_root, multi_group.merge.method).

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `key` | text | Sentinel.UNSET |  |

### `config set`

Set a configuration value (validated via Pydantic; invalid values raise an error) and save config.yaml.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `key` | text | Sentinel.UNSET |  |
| `value` | text | Sentinel.UNSET |  |

### `config reset`

Reset a key to its default and remove it from config.yaml.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `key` | text | Sentinel.UNSET |  |

### `config wizard`

Interactive TUI configuration wizard.

## `darks`

Manage the Darks Library (sync/list/check/import).

### `darks sync`

Sync DwarfLab export into the Darks Library (TELE/cam_0 only, never WIDE/cam_1).

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--dry-run` | boolean | False | Show what would be copied without copying |
| `--source` | path | Sentinel.UNSET | Source (default: C:/Dwarflab/CALI_FRAME/dark/cam_0) |
| `--dest` | path | Sentinel.UNSET | Destination (default: C:/Astra/_darks) |

### `darks list`

List dark frames in the library.

### `darks check`

Check dark-frame coverage for a target.

    Checks both the central darks library (darks_repository) and any local
    darks/ folder inside the target directory (dark_source=local, as used by
    'astra process' when no library darks match). Local darks are reported
    separately so coverage is not misleadingly shown as MISSING.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target` | path | Sentinel.UNSET |  |

### `darks import`

Import dark frames from a path into the library.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `path` | path | Sentinel.UNSET |  |
| `--dry-run` | boolean | False | Dry-run |

## `doctor`

Environment check: Python, dependencies, GAIA, config, disk, paths. Read-only.

    Optional TARGET_PATH: additionally checks target equipment supply
    (which header values are present, which config profile would apply,
    and which fields are completely missing).

    Exit codes: 0 = OK, 1 = warnings, 2 = critical errors.
    The command is read-only -- no directories or files are created or modified.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--fix` | boolean | False | Auto-fixes missing dirs, config defaults, dark structure |

## `download-example`

Download a real-data example (10 M31 FITS as GitHub Release asset).

    
    Fetches 10 real M31 light frames (90s Gain 40 Astro, 1920x1080) as a
    GitHub Release asset (M31-example-10fits.tar.gz), verifies SHA256, and
    extracts to <output>/lights/group_90s40_astro/. Idempotent: existing
    files are skipped unless --force is given. Offline fallback copies from
    C:/Astra/M31 Andromeda/lights/group_90s40_astro/ when GitHub is
    unreachable.

    
    Examples:
      astra download-example M31 --n 10
      astra download-example M31 --n 10 --output C:/Astra/M31_B_test
      astra download-example M31 --n 10 --force

    Real-Gate: after download, run:
      astra process <output> --from-suggested <output>/suggested.yaml --limit 5 --dry-run
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target` | text | Sentinel.UNSET |  |
| `--n` | integer | 10 | Number of light frames to fetch (N >= 1, default 10). |
| `--output` | path |  | Output DIRECTORY for the example dataset (default: C:/Astra/<Target>). The data is extracted to <output>/lights/group_90s40_astro/ and <output>/suggested.yaml. |
| `--force` | boolean | False | Overwrite existing files (idempotent skip otherwise). |

## `init`

Initialize Astra configuration (Wizard).

    The wizard interactively prompts for the Astra Project Dir, Data Root (C:\Astra),
    Darks Library (C:\Astra\_darks), Default Preset, and Cosmetic Default,
    then writes config.yaml + environment.yaml (Pydantic-validated).

    With --non-interactive, flags/env vars are used (CI-capable), without prompts.
    Environment variables: ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, ASTRA_DEFAULT_PRESET.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--non-interactive` | boolean | False | Non-interactive: use flags/env vars, no prompts (CI-friendly) |
| `--project-dir` | path | Sentinel.UNSET | Astra project directory (default: current directory) |
| `--data-root` | path | Sentinel.UNSET | Data root (default: C:/Astra) |
| `--darks-library` | path | Sentinel.UNSET | Darks library (default: C:/Astra/_darks) |
| `--preset` | Choice(galaxy_standard,nebula_standard,star_standard,nebula_narrowband) | Sentinel.UNSET | Default preset |
| `--cosmetic` | boolean |  | Enable or disable cosmetic default |
| `--config-output` | path | Sentinel.UNSET | Destination for config.yaml (default: ./config.yaml) |

## `inspect`

Inspect FITS headers in target directory.

    Shows target information, calibration status, equipment, EQMODE and
    (deprecated) shotsInfo.json contents. With --json: machine-readable
    JSON output for automated post-processing.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--json` | boolean | False | Machine-readable output (JSON) |
| `--eqmode` | boolean | False | Show EQMODE only |
| `--frames` | boolean | False | Show frames in detail |
| `--quality` | boolean | False | Show Quality Foundation metrics |

## `merge`

Merge existing group stacks into a single FITS.

    Scans generated/{timestamp}/group_*/04_stacked/pcc_applied.fits,
    extracts metadata from FITS headers, and merges all groups using the
    chosen method and weighting.

    Note: Requires >=2 groups. Single-group targets are automatically
    materialized to merged/ by the process pipeline (no merge step needed).
    For single-group: run 'astra process <target>' or manually copy the
    stacked FITS to merged/.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--method` | Choice(weighted_average,average,median) | weighted_average | Merge method |
| `--weight-by` | Choice(frame_count,total_exposure) | frame_count | Weighting method |
| `--merge-filter` | text | Sentinel.UNSET | Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro) |
| `--output, -o` | path | Sentinel.UNSET | Output directory (default: generated/{timestamp}/merged/) |
| `--dry-run` | boolean | False | Show groups without merging |

## `organize`

Organize flat lights in C:\Astra\<Target>\lights\ into group folders.

    
    Groups by (EXPTIME, GAIN, FILTER, EQMODE) from FITS header (SSOT), not filename.
    FILTER normalized duo-band/astro, EQMODE split per folder (_eq0/_eq1 only when split).
    Frames MOVE (os.rename) into lights\group_{exp}s{gain}_{filter}[_eq0/1]\.
    Duplicates (size+mtime) in root cleaned, <3 still sorted + hint, SOLL check, AZ/EQ mix warning, Moon READY(SIRIL).
    Lights exclusivity guard: only inbox frames + group_* allowed, foreign subfolders -> warning skipped.

    
    Examples:
      astra organize "C:\Astra\M31 Andromeda" --dry-run
      astra organize "C:\Astra\M31 Andromeda"
      astra organize --all --dry-run
      astra organize --all
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target` | text | Sentinel.UNSET |  |
| `--dry-run` | boolean | False | Show grouping table without moving files (no writes, Exit 0) |
| `--all` | boolean | False | Organize all targets under data_root (ignores _darks/generated/_work/_foren/_sammlung/siril-scripts) |

## `plugin`

Plugin management (v1.2, PL-C): pipeline-step plugins in the
    entry-point group ``astra.plugins``.

### `plugin list`

List registered pipeline-step plugins (PL-C).

    Exit codes: 0 = OK (even with no plugins installed), 1 = discovery error.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--json` | boolean | False | Machine-readable output (JSON) |

## `process`

Process a single target directory.

    Note (Docs regen 2026-08-11, B3): --config/-c is a GLOBAL option and
    must be specified before the subcommand, e.g.:
        astro-process --config config.yaml process <target>
    Without --config the pipeline automatically searches for config.yaml in
    the current directory (CWD) or project root.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--preset, -p` | Choice(galaxy_standard,nebula_standard,star_standard,nebula_narrowband) | Sentinel.UNSET | Processing preset |
| `--dry-run` | boolean | False | Show plan without executing |
| `--keep-working` | boolean | False | Preserve working directory |
| `--keep-groups` | boolean |  | Keep or clean up group directories (default: from config, otherwise true) |
| `--resume` | boolean | False | Resume from last checkpoint |
| `--multi-group` | boolean | False | Deprecated no-op (v1.7): Multi-Group is always active |
| `--auto-group` | boolean | False | Deprecated no-op (v1.7): Multi-Group is always active |
| `--merge` | boolean |  | Enable or disable merge step (default: enabled). Note: merge requires >=2 groups; single-group targets are automatically materialized to merged/ |
| `--weight-by` | Choice(frame_count,total_exposure) | Sentinel.UNSET | Merge weighting method (overrides config) |
| `--merge-method` | Choice(weighted_average,average,median) | Sentinel.UNSET | Merge method (overrides config) |
| `--merge-filter` | text | Sentinel.UNSET | Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro --merge-filter "Duo-Band"; overrides config) |
| `--pcc-per-group` | boolean |  | PCC per group (default: false = PCC on merged stack for max S/N) |
| `--stacking-method` | Choice(average,median,winsorized,weighted,sigma_clipped_mean) | Sentinel.UNSET | Stacking method (overrides preset/config; otherwise mapped from rejection; sigma_clipped_mean = robust sigma-clipping) |
| `--registration-method` | Choice(fft,astroalign,rotation_fft) | Sentinel.UNSET | Registration method (overrides config/preset) |
| `--max-rotation` | float |  | Sanity guard: max rotation in degrees for astroalign/rotation_fft (default 2.0, field rotation e.g. 15) |
| `--zero-shift-threshold` | float |  | W1 guard: corr_hp threshold (default 0.0). FFT path -> zero-shift fallback; astroalign winner below threshold -> frame rejected |
| `--no-zero-shift-fallback` | boolean | False | Completely disable W1 guard (no zero-shift fallback and no astroalign rejection below threshold) |
| `--az-mode` | text |  | EQMODE override: force AZ mode (overrides EQMODE header) |
| `--eq-mode` | text |  | EQMODE override: force EQ mode (overrides EQMODE header) |
| `--pixel-scale` | float |  | Pixel scale (arcsec/px) directly (overrides equipment header) |
| `--se-radius` | float |  | Structure-enhancement radius (default 3.0 from preset step) |
| `--se-amount` | float |  | Structure-enhancement amount (default 0.2 from preset step) |
| `--gradient-removal-enabled` | boolean |  | Enable or disable gradient removal (overrides config/preset) |
| `--gradient-removal-degree` | integer |  | Gradient removal polynomial degree (overrides config/preset) |
| `--gradient-removal-grid` | text |  | Gradient removal sampling grid as 'rows,cols' e.g. 16,16 (overrides config/preset) |
| `--gradient-removal-sigma-clip` | float |  | Gradient removal sigma-clipping k in k*MAD (overrides config/preset) |
| `--gradient-removal-min-samples` | integer |  | Gradient removal minimum sample cells for fit (overrides config/preset) |
| `--darks-path` | path | Sentinel.UNSET | Path to central darks library (overrides config: darks_repository) |
| `--cosmetic-correction` | boolean |  | Enable or disable cosmetic correction (overrides config) |
| `--debayer-method` | Choice(superpixel,bilinear,malvar) |  | Debayer method: superpixel (default, DADR-003), malvar (1920x1080, high-quality, Malvar2004), or bilinear (deprecated, use malvar or superpixel, full resolution) |
| `--frame-selection` | boolean |  | Enable or disable frame selection (percentile, DwarfLab pattern; overrides config/preset, default off) |
| `--keep-percentile` | integer range |  | Keep percentile for frame selection (1-100, default 92, only with --frame-selection) |
| `--cfa-drizzle` | boolean |  | Enable or disable CFA drizzle (2x, uses Dwarf Mini dithering, default off) |
| `--drizzle-scale` | float |  | Drizzle scale (default 2.0, 2x = 3840x2160) |
| `--drizzle-pixfrac` | float |  | Drizzle pixfrac (0.5-1.0, fixed mode, default auto: <10=1.0, 10-30=0.7, >30=0.5) |
| `--drizzle-kernel` | Choice(lanczos3,gaussian,tophat) |  | Drizzle kernel (default lanczos3, gaussian/tophat optional) |
| `--cfa-drizzle-quality-gate` | boolean |  | Quality gate for CFA drizzle: auto (default), on, off (let all frames pass) |
| `--cfa-drizzle-min-frames` | integer |  | Minimum frames for drizzle (default: 5, CFA-Smart: 5) |
| `--cfa-drizzle-fallback` | Choice(malvar,superpixel,skip) |  | Fallback method on quality gate fail (default: malvar) [advanced] |
| `--cfa-drizzle-star-count-min` | integer |  | Min star count (default: 20 debayered, CFA-Smart: 1) [advanced] |
| `--cfa-drizzle-snr-min` | float |  | Min SNR (default: 10, CFA-Smart: 0.8, V1.12-DRZ-GATE calibrated on M92 real 0.89-0.93, spec 1.0-1.5) [advanced] |
| `--cfa-drizzle-correlation-min` | float |  | Min Correlation (Default: 0.3, CFA-Smart: 0.1) [advanced] |
| `--cfa-drizzle-fwhm-range` | text |  | FWHM range as 'min,max' (default: 1.5,5.0, CFA-Smart: 1.0,8.0) [advanced] |
| `--preview-format` | Choice(tiff,jpg) |  | Preview Format: tiff (16-bit lossless, Default, 07.09.2026) or jpg (8-bit, fast, ~500 KB vs ~10-50 MB) (overrides Config preview.format, Default tiff) |
| `--pcc` | boolean |  | Enable or disable photometric color calibration (overrides preset/config; default: preset/config wins) |
| `--preflight` | boolean | False | Pre-flight checks only (hot pixel scan, dark matching, cosmetic recommendation) -- no pipeline start |
| `--yes` | boolean | False | With --preflight: start pipeline immediately if checks pass |
| `--no-calib` | boolean |  | Skip calibration phase (pre-calibrated lights). Note: lights must be CFA/2D (Bayer raw data) -- already debayered 3D RGB lights will fail at debayer step. |
| `--from-suggested` | file |  | Load preset/registration/debayer/pcc from a suggested_parameters YAML/JSON file (written by 'astra suggest'). Required since v1.11 -- run 'astra suggest <TARGET>' first to generate the file (default: C:/Astra/<Target>/suggested.yaml). If flag given without value, defaults to <Target>/suggested.yaml (derived from the TARGET argument). CLI flags win over file values. No auto-discover; only TARGET-arg-derived default when flag has no value. |
| `--limit` | integer |  | Limit number of light frames per group for quick smoke testing (discovery processes all groups, but uses only first N lights per group; darks, bias, flats remain complete for proper calibration). Default: no limit (process all frames). Example: --limit 5 (use first 5 lights per group; output marked as smoke_mode=true). Combination: incompatible with --resume (use --limit for fresh runs only). [English s17] |
| `--group` | text | Sentinel.UNSET | Process only the specified group folder(s) (repeatable, e.g. --group group_30s40_duo-band --group group_60s40_duo-band; exact or unique prefix, case-insensitive, ORG-X2) |

## `qc`

Quality checker: measures flip/ghosting/color from generated/<ts>/.

    
    Examples:
      astra qc "C:\Astra\M27 Hantelnebel\generated\20260906-080324"
      astra qc --all
      astra qc "C:\Astra\M27 Hantelnebel\generated\20260906-080324" --json
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `generated` | path | Sentinel.UNSET |  |
| `--all` | boolean | False | QC all non-smoke runs per target as a table (gate = worst per target) |
| `--latest` | boolean | False | Only check latest generated/<ts> per target (instead of all); default without --all = latest when target-root given -- saves I/O 40->2, 43s->~5s |
| `--json` | boolean | False | Machine-readable JSON output to stdout (in addition to qc_report.json) |
| `--check-header` | boolean | False | Additionally check FITS header for platesolving completeness (FOCALLEN/XPIXSZ/RA/DEC/WCS etc; 01_calibrated excluded, S3) |

## `status`

Show system status (disk space, recent runs, darks library, config health, queue).

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--json` | boolean | False | Machine-readable output (JSON) |

## `suggest`

Suggest a preset/registration/debayer/PCC combination for TARGET.

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
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target` | text | Sentinel.UNSET |  |
| `--header` | file |  | Read OBJECT/FILTER/EXPTIME/TELESCOP/DET-TEMP from a local FITS header (local only, no cloud). OBJECT wins over TARGET when both are given (suggest.header_overrides_target warning). |
| `--coords` | text |  | Fallback RA/DEC (decimal degrees) when TARGET/--header do not resolve a cache hit. Used only for SIMBAD lookup / labeling; suggest never plate-solves. |
| `--output` | path |  | Override the output file path for the suggested_parameters file (FILE path, not directory; YAML default, JSON on .json suffix). Without --output the file is always written to C:/Astra/<Target>/suggested.yaml (Target-Root, next to Lights). Always overwrites (no auto-history). Examples: --output C:/Astra/M31/suggested.yaml or --output C:/Astra/M31/custom_suggest.yaml |
| `--json` | boolean | False | Print the machine-readable JSON suggestion to stdout instead of the human-readable text. |

## `target`

Target management (list/add/show/update/remove).

### `target list`

List all targets and their progress.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--json` | boolean | False | Machine-readable output (JSON) |

### `target add`

Create a new target and generate an AUFNAHMELISTE_{Target}.md template.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | text | Sentinel.UNSET |  |
| `--preset` | Choice(galaxy_standard,nebula_standard,star_standard,nebula_narrowband) | Sentinel.UNSET | Preset |
| `--non-interactive` | boolean | False | Non-interactive |

### `target show`

Show details for a target.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | text | Sentinel.UNSET |  |

### `target update`

Update a target (e.g. preset in AUFNAHMELISTE).

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | text | Sentinel.UNSET |  |
| `--preset` | Choice(galaxy_standard,nebula_standard,star_standard,nebula_narrowband) | Sentinel.UNSET | New preset |

### `target remove`

Remove a target (optional).

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | text | Sentinel.UNSET |  |
| `--yes` | boolean | False | Delete without confirmation |

## astra init --non-interactive (CI, V19-ENV)

Non-interactive, CI-friendly init. Reads flags / env vars, no prompts. Env vars: `ASTRA_DATA_ROOT`, `ASTRA_DARKS_REPOSITORY`, `ASTRA_DEFAULT_PRESET` (and `GIMP_PATH`). Writes `config.yaml` with **resolved** absolute paths (no `${}`).

```bash
astra init --non-interactive --data-root "$ASTRA_DATA_ROOT" --darks-library "$ASTRA_DARKS_REPOSITORY"
astra doctor          # WARN doctor.env_missing if .env absent, Exit 0
```

Precedence for `init`/`load_config`: explicit `--config` > `CWD/config.yaml` > `pipeline_root/config.yaml` > `DEFAULT_CONFIG`. `.env` precedence: `Shell Env > CWD/.env > pipeline_root/.env` (`Path.expanduser().resolve()` after `expandvars`).

ACI: `astra init --non-interactive` is required for AC-ENV-4 and CI `Ubuntu+Win/3.11`.

## PCC Flag - Use Cases (V19-PCC-FLAG)

Precedence: **CLI `--pcc/--no-pcc` > Config `pcc.enabled` > Preset Steps > Default**. `default None` = no breaking change. Existing `--pcc-per-group/--no-pcc-per-group` stays independent (location: PCC per group vs. on merged stack).

| Scenario | Command |
| --- | --- |
| M31 Galaxy, skip PCC (fast, avoid 6 min GAIA timeout) | `astra process ... --preset galaxy_standard --no-pcc` |
| Star cluster, force PCC | `astra process ... --preset star_standard --pcc` |
| Nebula, force PCC (preset has none) | `astra process ... --preset nebula_standard --pcc` |
| Multi-Group, PCC only on merged (default) | `astra process ... --no-pcc-per-group` |
| Multi-Group, PCC per group | `astra process ... --pcc --pcc-per-group` |
| Config fallback (no CLI) | `pcc.enabled: false` in `config.yaml` + no CLI flag → Preset overridden |

Runtime mutation: `--pcc` inserts `photometric_color_calibration` after `background_extraction` (fallback: after `stack_frames`, then `len-2` before stretch/export). `--no-pcc` removes the step. Batch-safe via `copy.deepcopy` (in-memory, no file write). Log: `pcc.cli_override` with `enabled`, `preset`, `inserted_after`/`removed`. Config `pcc.enabled` is `Optional[bool]=None` (`null` = Preset wins, only explicit set via `model_fields_set` overrides).

Quick debug: `astra process --help` shows `--pcc/--no-pcc` (visible) and `--pcc-per-group` (visible); CFA hidden flags are documented in `11-troubleshooting.md` (advanced).

## Smoke Testing (Subset Mode, V1.11-SUBSET)

For quick validation on full production data without waiting for complete processing:

```bash
astra process C:\Astra\M31 --from-suggested --limit 5 --dry-run
```

- Processes first 5 light frames per observation group (darks/bias/flats remain complete for proper calibration)
- Marked in run-info.json: `smoke_mode=true`, `limit=5`, `frames_considered=5`, `frames_total=247` (example with 247-frame full dataset)
- Useful after data migration (e.g., consolidate C:\AstraTest into C:\Astra) for quick smoke-test verification on real production data
- Fully deterministic: repeat with same `--limit` yields identical frame selection (natural sort, deterministic order)
- Incompatible with `--resume` (use `--limit` for fresh discovery + calibration runs only)
- Batch-compatible: `astra batch C:\Astra --limit 3` applies 3-frame limit uniformly to every target
