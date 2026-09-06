# CLI Reference

> Auto-generated from `src/astro_process/cli.py` — **do not edit manually**.

> Generator: `python scripts/generate_docs.py cli`

> Precedence: CLI > Config > Env > Default (see `04-configuration.md`)

---

## Subcommands

| Command | Description | Flags |
| --- | --- | --- |
| `batch` | Process all subdirectories in the data root. Each target directory must have a suggested.yaml (run | data_root, --preset, --dry-run, --limit |
| `config` | Manage configuration (precedence: CLI > Config > Env > Default). | - |
| `config show` | Show the fully merged configuration (defaults + user + env). Precedence: CLI > | - |
| `config get` | Get a single configuration value via dot-notation (e.g. data_root, | - |
| `config set` | Set a configuration value (validated via Pydantic; invalid values raise an | - |
| `config reset` | Reset a key to its default and remove it from config.yaml. | - |
| `config wizard` | Interactive TUI configuration wizard. | - |
| `darks` | Manage the Darks Library (sync/list/check/import). | - |
| `darks sync` | Sync DwarfLab export into the Darks Library (TELE/cam_0 only, never WIDE/cam_1). | - |
| `darks list` | List dark frames in the library. | - |
| `darks check` | Check dark-frame coverage for a target. | - |
| `darks import` | Import dark frames from a path into the library. | - |
| `doctor` | Environment check: Python, dependencies, GAIA, config, disk, paths. Read-only. Optional TARGET_PATH | target_path, --fix |
| `init` | Initialize Astra configuration via an interactive wizard. The wizard asks for the project | --non-interactive, --project-dir, --data-root, --darks-library |
| `inspect` | Inspect FITS headers in the target directory. Shows target info, calibration status, equipment, | target_path, --json, --eqmode, --frames |
| `merge` | Merge existing group stacks into a single FITS. Scans | target_path, --method, --weight-by, --merge-filter |
| `plugin` | Plugin management (v1.2, PL-C): pipeline-step plugins in the ``astra.plugins`` entry-point group. | - |
| `plugin list` | List registered pipeline-step plugins (PL-C). Exit codes: 0 = OK (even with no | - |
| `process` | Process a single target directory. The global --config/-c option must be placed before the | target_path, --preset, --output, --dry-run |
| `status` | Show system status (disk space, recent runs, darks library, config health, queue). | --json |
| `suggest` | Suggest a preset, registration method, debayer method, and PCC settings for a target. Offline-first | target, --header, --coords, --output |
| `target` | Target management (list/add/show/update/remove). | - |
| `target list` | List all targets and their progress. | - |
| `target add` | Create a new target and generate an AUFNAHMELISTE_{Target}.md template. | - |
| `target show` | Show details for a target. | - |
| `target update` | Update a target (e.g. preset in AUFNAHMELISTE). | - |
| `target remove` | Remove a target (optional). | - |

## Global Flags

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--config, -c` | path | Sentinel.UNSET | Config file (global, must be placed BEFORE the subcommand, e.g. --config |
| `--verbose, -v` | boolean | False | Verbose output |
| `--version` | boolean | False | Show the version and exit. |

## `batch`

Process all subdirectories in the data root. Each target directory must have a suggested.yaml (run 'astra suggest <TARGET>' first). The per-target suggested.yaml is passed via --from-suggested (Target-Root default). Missing file → Error.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `data_root` | path | Sentinel.UNSET |  |
| `--preset, -p` | text |  | Default preset for all targets (default: from per-target suggested.yaml) |
| `--dry-run` | boolean | False |  |
| `--limit` | integer |  | Limit number of light frames per group for smoke testing - applied uniformly to |

## `config`

Manage configuration (precedence: CLI > Config > Env > Default).

### `config show`

Show the fully merged configuration (defaults + user + env). Precedence: CLI > Config > Env > Default.

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

Environment check: Python, dependencies, GAIA, config, disk, paths. Read-only. Optional TARGET_PATH also checks target equipment supply (which header values are present, which config profile would apply, and which fields are completely missing). Exit codes: 0 = OK, 1 = warnings, 2 = critical errors. The command is read-only — no directories or files are created or modified.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--fix` | boolean | False | Auto-fix missing directories, config defaults, and dark structure |

## `init`

Initialize Astra configuration via an interactive wizard. The wizard asks for the project directory, data root, darks library, default preset, and cosmetic default, then writes config.yaml and environment.yaml (Pydantic-validated). With --non-interactive, flags and environment variables are used instead of prompts (CI-friendly). Env vars: ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, ASTRA_DEFAULT_PRESET.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--non-interactive` | boolean | False | Non-interactive: use flags/env vars, no prompts (CI-friendly) |
| `--project-dir` | path | Sentinel.UNSET | Astra project directory (default: current directory) |
| `--data-root` | path | Sentinel.UNSET | Data root (default: C:/Astra) |
| `--darks-library` | path | Sentinel.UNSET | Darks library (default: C:/Astra/_darks) |
| `--preset` | Choice(galaxy_standard,nebula_standard,star_standard,nebula_narrowband) | Sentinel.UNSET | Default preset |
| `--cosmetic` | boolean |  | Enable or disable cosmetic correction default |
| `--config-output` | path | Sentinel.UNSET | Destination for config.yaml (default: ./config.yaml) |

## `inspect`

Inspect FITS headers in the target directory. Shows target info, calibration status, equipment, EQMODE, and deprecated shotsInfo.json contents. With --json: machine-readable JSON output for automated post-processing.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--json` | boolean | False | Machine-readable output (JSON) |
| `--eqmode` | boolean | False | Show EQMODE only |
| `--frames` | boolean | False | Show frames in detail |
| `--quality` | boolean | False | Show Quality Foundation metrics |

## `merge`

Merge existing group stacks into a single FITS. Scans generated/{timestamp}/group_*/04_stacked/pcc_applied.fits, extracts metadata from FITS headers, and merges all groups using the chosen method and weighting.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--method` | Choice(weighted_average,average,median) | weighted_average | Merge method |
| `--weight-by` | Choice(frame_count,total_exposure) | frame_count | Weighting method |
| `--merge-filter` | text | Sentinel.UNSET | Filter selection for merge (repeatable, case-insensitive trimmed, e.g. |
| `--output, -o` | path | Sentinel.UNSET | Output directory (default: generated/{timestamp}/merged/) |
| `--dry-run` | boolean | False | Show groups without merging |

## `plugin`

Plugin management (v1.2, PL-C): pipeline-step plugins in the ``astra.plugins`` entry-point group.

### `plugin list`

List registered pipeline-step plugins (PL-C). Exit codes: 0 = OK (even with no plugins installed), 1 = discovery error.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--json` | boolean | False | Machine-readable output (JSON) |

## `process`

Process a single target directory. The global --config/-c option must be placed before the subcommand, e.g. `astra --config config.yaml process <target>`. Without --config the pipeline searches for config.yaml in the current working directory or project root.

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--preset, -p` | Choice(galaxy_standard,nebula_standard,star_standard,nebula_narrowband) | Sentinel.UNSET | Processing preset |
| `--output, -o` | path | Sentinel.UNSET | Output directory |
| `--dry-run` | boolean | False | Show plan without executing |
| `--keep-working` | boolean | False | Preserve working directory |
| `--keep-groups` | boolean |  | Keep or clean up group working directories (default from config, otherwise true) |
| `--resume` | boolean | False | Resume from last checkpoint |
| `--multi-group` | boolean | False | Deprecated no-op (v1.7): Multi-Group is always active |
| `--auto-group` | boolean | False | Deprecated no-op (v1.7): Multi-Group is always active |
| `--merge` | boolean |  | Enable or disable the merge step (default: enabled) |
| `--weight-by` | Choice(frame_count,total_exposure) | Sentinel.UNSET | Merge weighting method (overrides config) |
| `--merge-method` | Choice(weighted_average,average,median) | Sentinel.UNSET | Merge method (overrides config) |
| `--merge-filter` | text | Sentinel.UNSET | Filter selection for merge (repeatable, case-insensitive trimmed, e.g. |
| `--pcc-per-group` | boolean |  | Apply PCC per group (default: false = PCC on merged stack for maximum S/N) |
| `--stacking-method` | Choice(average,median,winsorized,weighted,sigma_clipped_mean) | Sentinel.UNSET | Stacking method (overrides preset/config; otherwise mapped from rejection; |
| `--registration-method` | Choice(fft,astroalign,rotation_fft) | Sentinel.UNSET | Registration method (overrides config/preset) |
| `--max-rotation` | float |  | Sanity guard: maximum rotation in degrees for astroalign/rotation_fft (default |
| `--zero-shift-threshold` | float |  | W1 guard: corr_hp threshold (default 0.0). FFT path falls back to zero-shift; |
| `--no-zero-shift-fallback` | boolean | False | Completely disable the W1 guard (no zero-shift fallback and no astroalign |
| `--az-mode` | text |  | EQMODE override: force AZ mode (overrides EQMODE header) |
| `--eq-mode` | text |  | EQMODE override: force EQ mode (overrides EQMODE header) |
| `--pixel-scale` | float |  | Override pixel scale (arcsec/px) directly (overrides equipment header) |
| `--se-radius` | float |  | Structure-enhancement radius (default 3.0 from preset step) |
| `--se-amount` | float |  | Structure-enhancement amount (default 0.2 from preset step) |
| `--gradient-removal-enabled` | boolean |  | Enable or disable gradient removal (overrides config/preset) |
| `--gradient-removal-degree` | integer |  | Gradient-removal polynomial degree (overrides config/preset) |
| `--gradient-removal-grid` | text |  | Gradient-removal sampling grid as 'rows,cols', e.g. 16,16 (overrides |
| `--gradient-removal-sigma-clip` | float |  | Gradient-removal sigma-clipping k in k*MAD (overrides config/preset) |
| `--gradient-removal-min-samples` | integer |  | Gradient-removal minimum sample cells for the fit (overrides config/preset) |
| `--darks-path` | path | Sentinel.UNSET | Path to the central Darks Library (overrides config: darks_repository) |
| `--cosmetic-correction` | boolean |  | Enable or disable cosmetic correction (overrides config) |
| `--debayer-method` | Choice(superpixel,bilinear,malvar) |  | Debayer method: superpixel (default, DADR-003), malvar (1920x1080 high-quality |
| `--frame-selection` | boolean |  | Enable or disable frame selection (percentile, DwarfLab pattern; overrides |
| `--keep-percentile` | integer range |  | Keep percentile for frame selection (1-100, default 92, only with |
| `--cfa-drizzle` | boolean |  | Enable or disable CFA drizzle (2x, uses Dwarf Mini dithering) |
| `--drizzle-scale` | float |  | Drizzle scale (default 2.0, 2x = 3840x2160) |
| `--drizzle-pixfrac` | float |  | Drizzle pixfrac (0.5-1.0; in fixed mode default auto: <10=1.0, 10-30=0.7, |
| `--drizzle-kernel` | Choice(lanczos3,gaussian,tophat) |  | Drizzle kernel (default lanczos3, gaussian/tophat optional) |
| `--cfa-drizzle-quality-gate` | boolean |  | Quality gate for CFA-Drizzle: auto (default), on, off (let all frames pass) |
| `--cfa-drizzle-min-frames` | integer |  | Minimum frames for drizzle (default: 5, CFA-Smart: 5) |
| `--cfa-drizzle-fallback` | Choice(malvar,superpixel,skip) |  | Fallback method on quality-gate failure (default: malvar) [advanced] |
| `--cfa-drizzle-star-count-min` | integer |  | Min star count (default: 20 debayered, CFA-Smart: 1) [advanced] |
| `--cfa-drizzle-snr-min` | float |  | Min SNR (default: 10, CFA-Smart: 5) [advanced] |
| `--cfa-drizzle-correlation-min` | float |  | Min correlation (default: 0.3, CFA-Smart: 0.1) [advanced] |
| `--cfa-drizzle-fwhm-range` | text |  | FWHM range as 'min,max' (default: 1.5,5.0, CFA-Smart: 1.0,8.0) [advanced] |
| `--pcc` | boolean |  | Enable or disable photometric color calibration (overrides preset/config; |
| `--preflight` | boolean | False | Run pre-flight checks only (hot-pixel scan, dark matching, cosmetic |
| `--yes` | boolean | False | With --preflight: start the pipeline immediately if checks pass |
| `--no-calib` | boolean |  | Skip calibration phase (pre-calibrated lights). Note: lights must be CFA/2D |
| `--from-suggested` | file |  | Load preset, registration method, debayer method, and PCC settings from a |
| `--limit` | integer |  | Limit number of light frames per group for quick smoke testing (discovery |

## `status`

Show system status (disk space, recent runs, darks library, config health, queue).

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--json` | boolean | False | Machine-readable output (JSON) |

## `suggest`

Suggest a preset, registration method, debayer method, and PCC settings for a target. Offline-first advisor (Header > target-cache > SIMBAD > Handbook): HEADER wins over TARGET; target-cache (stella-maintained) always wins over SIMBAD; SIMBAD only queried on cache miss if network available (5s timeout). On unknown target + cache miss + offline: Error Exit 2 `suggest.simbad_unavailable` (no file written; add entry to target-cache.md or run with known target). Always writes suggested.yaml to default location C:/Astra/<Target>/suggested.yaml or --output override. Output also writes to stdout (human-readable) or --json (machine-readable). This command is an ADVISOR; `astra process` requires `--from-suggested` flag (mandatory since v1.11). Examples: `astra suggest M31`; `astra suggest M31

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target` | text | Sentinel.UNSET |  |
| `--header` | file |  | Read OBJECT, FILTER, EXPTIME, TELESCOP, DET-TEMP from a local FITS file header |
| `--coords` | text |  | Fallback right ascension and declination (RA DEC in decimal degrees) when |
| `--output` | path |  | Write suggested_parameters to a file as YAML (default format) or JSON (if path |
| `--json` | boolean | False | Print the machine-readable JSON suggestion to stdout (in addition to or instead |

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
cp .env.example .env  # edit paths
astra init --non-interactive --data-root "$ASTRA_DATA_ROOT" --darks-library "$ASTRA_DARKS_REPOSITORY"
astra doctor          # WARN doctor.env_missing if .env absent, Exit 0
```

Precedence for `init`/`load_config`: explicit `--config` > `CWD/config.yaml` > `pipeline_root/config.yaml` > `DEFAULT_CONFIG`. `.env` precedence: `Shell Env > CWD/.env > pipeline_root/.env` (`Path.expanduser().resolve()` after `expandvars`).

ACI: `astra init --non-interactive` is required for AC-ENV-4 and CI `Ubuntu+Win/3.11`.

## PCC Flag — Use Cases (V19-PCC-FLAG)

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
