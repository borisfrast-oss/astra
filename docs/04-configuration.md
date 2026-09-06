# Configuration

> Auto-generated from `src/astro_process/config/models.py` + `config.yaml`

> Precedence: CLI > Config > Env > Default

---

## AppConfig (Root)

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `data_root` | <class 'pathlib.Path'> | C:/Astra | Root directory for all target data (e.g. C:/Astra). |
| `working_dir` | <class 'pathlib.Path'> | working | Relative working directory for intermediate pipeline files. |
| `output_dir` | <class 'pathlib.Path'> | output | Relative output directory for final pipeline products. |
| `config_dir` | <class 'pathlib.Path'> | config | Relative directory for configuration files. |
| `gimp_path` | <class 'pathlib.Path'> | gimp | Optional path to the GIMP executable (deprecated; Astra does not use GIMP). |
| `default_preset` | <class 'str'> | star_standard | Preset applied when a target does not specify one. |
| `cpu_threads` | <class 'int'> | 0 | Number of CPU threads for parallel tasks (0 = auto). |
| `gpu_acceleration` | <class 'bool'> | True | Enable GPU acceleration where supported. |
| `keep_working` | <class 'bool'> | False | Keep intermediate working directories after a successful run. |
| `quality_accept_threshold` | <class 'int'> | 80 | Minimum quality score for a frame to be accepted automatically. |
| `quality_review_threshold` | <class 'int'> | 60 | Minimum quality score for a frame to be flagged for review. |
| `plate_solve_enabled` | <class 'bool'> | False | Enable astrometric plate solving after stacking. |
| `astrometry_bin` | typing.Optional[pathlib.Path] |  | Path to the local astrometry.net solve-field binary. |
| `astrometry_index_dir` | typing.Optional[pathlib.Path] |  | Directory containing astrometry.net index files. |
| `multi_group` | typing.Optional[astro_process.config.mod |  | - |
| `registration` | typing.Optional[astro_process.config.mod |  | - |
| `gradient_removal` | typing.Optional[astro_process.config.mod |  | - |
| `double_detection` | typing.Optional[bool] |  | - |
| `double_radius_px` | typing.Optional[float] |  | - |
| `elongation_check` | typing.Optional[bool] |  | - |
| `elongation_warn_threshold` | typing.Optional[float] |  | - |
| `elongation_unusable_threshold` | typing.Optional[float] |  | - |
| `elongation_min_stars` | typing.Optional[int] |  | - |
| `rejection_enabled` | typing.Optional[bool] |  | - |
| `rejection_thresholds` | typing.Optional[dict[str, tuple[typing.O |  | - |
| `rejection_elongation` | typing.Optional[bool] |  | - |
| `rejection_min_corr_hp` | typing.Optional[float] | 0.05 | - |
| `frame_selection` | typing.Optional[astro_process.config.mod |  | - |
| `cosmetic_correction` | typing.Optional[astro_process.config.mod |  | - |
| `gaia_timeout` | <class 'float'> | 30.0 | Timeout in seconds for GAIA catalog queries. |
| `vizier_apass_timeout` | <class 'float'> | 30.0 | Timeout in seconds for APASS catalog queries. |
| `vizier_refcat2_timeout` | <class 'float'> | 30.0 | Timeout in seconds for REFCAT2 catalog queries. |
| `pcc` | <class 'astro_process.config.models.PCCC | PydanticUndefined | - |
| `suggest` | typing.Optional[astro_process.config.mod |  | - |
| `filename_patterns` | typing.Optional[astro_process.config.mod |  | - |
| `cfa_drizzle` | typing.Optional[astro_process.config.mod |  | - |
| `debayer_method` | typing.Optional[typing.Literal['superpix |  | Default debayer algorithm: superpixel, bilinear, or malvar. |
| `export` | typing.Optional[astro_process.config.mod |  | - |
| `use_flats` | <class 'bool'> | False | Apply flat-field calibration during preprocessing. |
| `use_bias` | <class 'bool'> | False | Apply bias-frame calibration during preprocessing. |
| `mandatory_fields` | list[str] | ['exptime', 'gain', 'object', 'ccd_temp' | FITS header fields required for a frame to be processed. |
| `no_calib` | <class 'bool'> | False | Skip all calibration steps (not recommended for science data). |
| `darks_repository` | typing.Optional[pathlib.Path] |  | Central darks library path (e.g. C:/Astra/_darks). |
| `dark_scale_mismatch_abs` | <class 'float'> | 5.0 | Absolute temperature mismatch tolerance for dark matching (°C). |
| `dark_scale_mismatch_frac` | <class 'float'> | 0.04 | Fractional exposure mismatch tolerance for dark matching. |
| `dark_scale_mismatch_low_frac` | <class 'float'> | 0.5 | Low-temperature fractional mismatch tolerance. |
| `equipment_profiles` | list[astro_process.config.models.Equipme | PydanticUndefined | - |
| `pipeline_presets` | list[astro_process.config.models.Pipelin | PydanticUndefined | - |

## ProcessingParams

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `rejection` | <class 'str'> | winsorized | Outlier rejection strategy for stacking. |
| `stacking_method` | typing.Optional[str] |  | Algorithm used to combine registered frames. |
| `normalization` | <class 'str'> | mul | Pixel normalization mode for stacking (mul, add, etc.). |
| `weight` | <class 'str'> | noise | Weighting strategy for stacking (noise, equal, etc.). |
| `stretch_method` | <class 'str'> | asinh | Preview stretch function (asinh, linear, etc.). |
| `stretch_factor` | <class 'float'> | 0.15 | Preview stretch scaling factor. |
| `scnr_amount` | <class 'float'> | 0.5 | Star Color Noise Reduction amount for OSC data. |
| `gaia_timeout` | <class 'float'> | 30.0 | Timeout in seconds for GAIA catalog queries. |
| `vizier_apass_timeout` | <class 'float'> | 30.0 | Timeout in seconds for APASS catalog queries. |
| `vizier_refcat2_timeout` | <class 'float'> | 30.0 | Timeout in seconds for REFCAT2 catalog queries. |
| `registration` | <class 'astro_process.config.models.Regi | PydanticUndefined | - |
| `gradient_removal` | <class 'astro_process.config.models.Grad | PydanticUndefined | - |
| `debayer_method` | typing.Literal['superpixel', 'bilinear', | superpixel | Debayer algorithm: superpixel, bilinear, or malvar. |
| `double_detection` | <class 'bool'> | True | Enable double-star detection and rejection. |
| `double_radius_px` | <class 'float'> | 5.0 | Search radius in pixels for double-star detection. |
| `elongation_check` | <class 'bool'> | False | Enable star-elongation quality checks. |
| `elongation_warn_threshold` | <class 'float'> | 0.8 | Elongation ratio that triggers a warning. |
| `elongation_unusable_threshold` | <class 'float'> | 0.6 | Elongation ratio that marks a frame unusable. |
| `elongation_min_stars` | <class 'int'> | 10 | Minimum number of stars needed for elongation stats. |
| `rejection_enabled` | <class 'bool'> | False | Enable statistical outlier rejection during stacking. |
| `rejection_thresholds` | dict[str, tuple[typing.Optional[float],  | PydanticUndefined | Per-metric lower/upper thresholds for rejection. |
| `rejection_elongation` | <class 'bool'> | True | Reject frames based on elongation metrics. |
| `rejection_min_corr_hp` | typing.Optional[float] | 0.05 | - |
| `frame_selection` | <class 'astro_process.config.models.Fram | PydanticUndefined | - |
| `preview_export` | <class 'astro_process.config.models.Prev | PydanticUndefined | - |

## MultiGroupConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `reference_group` | <class 'str'> | quality | Criterion for choosing the reference group (e.g. quality). |
| `pcc_fallback` | typing.Literal['gray_world', 'skip', 'fa | auto | Fallback strategy when PCC fails for a group. |
| `pcc_per_group` | <class 'bool'> | False | Apply PCC to each group stack before merging. |
| `merge` | <class 'astro_process.config.models.Merg | PydanticUndefined | Merge strategy configuration for combining group stacks. |
| `keep_group_working_dirs` | <class 'bool'> | True | Keep per-group working directories after the run. |

## MergeConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `method` | typing.Literal['weighted_average', 'aver | weighted_average | Pixel-combining method for merging group stacks. |
| `weight_by` | typing.Literal['frame_count', 'total_exp | frame_count | Weighting criterion for merging groups. |
| `min_correlation` | <class 'float'> | 0.1 | Minimum cross-group correlation for a frame to contribute. |
| `filters` | typing.Optional[list[str]] |  | Optional list of filter names to include in the merge. |

## RegistrationConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `method` | typing.Literal['fft', 'astroalign', 'rot | fft | Registration engine: astroalign, fft, or rotation_fft. |
| `max_control_points` | typing.Optional[int] |  | Maximum control points for astroalign registration. |
| `max_rotation_deg` | <class 'float'> | 2.0 | Sanity-guard maximum rotation in degrees. |
| `max_scale_dev` | <class 'float'> | 0.02 | Maximum allowed scale deviation for registration. |
| `stack_scale_factor` | <class 'float'> | 2.0 | Sub-pixel upsampling factor for shift measurement. |
| `zero_shift_threshold` | <class 'float'> | 0.05 | High-pass correlation threshold for zero-shift fallback. |
| `zero_shift_fallback` | <class 'bool'> | True | Fall back to zero shift when correlation is below threshold. |
| `max_exptime_fft_warn` | <class 'float'> | 45.0 | Threshold in seconds above which a warning is emitted for fft registration on AZ |

## GradientRemovalConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | <class 'bool'> | False | Enable gradient removal before stacking. |
| `degree` | <class 'int'> | 2 | Polynomial degree fit to the background gradient. |
| `grid` | tuple[int, int] | (16, 16) | Background sampling grid as (rows, cols). |
| `sigma_clip` | <class 'float'> | 3.0 | Sigma-clipping multiplier for rejecting bright samples. |
| `min_samples` | typing.Optional[int] |  | Minimum number of valid samples required for fit. |

## CosmeticCorrectionConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | <class 'bool'> | False | Enable cosmetic correction (hot/dead pixels). |
| `n_frames` | <class 'int'> | 3 | Minimum dark frames required for cosmetic correction. |
| `threshold` | <class 'float'> | 50.0 | Hot-pixel threshold in sigma above the master dark. |
| `dark_tolerance` | <class 'float'> | 20.0 | Temperature tolerance in °C for master-dark matching. |

## CFADrizzleConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | <class 'bool'> | False | Enable CFA drizzle up-sampling during integration. |
| `scale` | <class 'float'> | 2.0 | Output pixel scale factor (e.g. 2.0 = 2x). |
| `pixfrac_mode` | typing.Literal['auto', 'fixed'] | auto | Pixfrac mode: auto based on star count or fixed. |
| `pixfrac` | <class 'float'> | 0.5 | Pixel fraction (drop size) for drizzle kernel. |
| `kernel` | typing.Literal['lanczos3', 'gaussian', ' | lanczos3 | Drizzle kernel: lanczos3, gaussian, or tophat. |
| `quality_gate` | <class 'astro_process.config.models.CFAD | PydanticUndefined | Quality thresholds that must pass before drizzle is applied. |
| `min_frames` | <class 'int'> | 5 | Minimum frame count required to enable drizzle. |
| `fallback` | typing.Literal['malvar', 'superpixel', ' | malvar | Fallback debayer method if drizzle preconditions fail. |

## FrameSelectionConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | <class 'bool'> | False | Enable automatic frame selection by quality metrics. |
| `keep_percentile` | <class 'int'> | 92 | Percentile of frames to keep (1-100). |
| `weights` | typing.Optional[dict[str, float]] |  | Per-metric weights used to compute the quality score. |
| `min_frames` | <class 'int'> | 3 | Minimum number of frames that must remain after selection. |

## config.yaml (Defaults/Presets)

```yaml
data_root: ${ASTRA_DATA_ROOT:-C:/Astra}
working_dir: ./working
output_dir: ./output
config_dir: ./config
gimp_path: ${GIMP_PATH:-gimp}
default_preset: star_standard
cpu_threads: 0
gpu_acceleration: true
keep_working: false
quality_accept_threshold: 80
quality_review_threshold: 60
darks_repository: ${ASTRA_DARKS_ROOT:-C:/Astra/_darks}
registration:
  method: fft
  max_control_points: null
  max_rotation_deg: 2.0
  max_scale_dev: 0.02
  stack_scale_factor: 2.0
cfa_drizzle:
  enabled: false
  scale: 2.0
  pixfrac_mode: auto
  pixfrac: 0.5
  kernel: lanczos3
  quality_gate:
    mode: auto
    rejection_enabled: true
    thresholds:
      fwhm:
      - 1.5
      - 5.0
      snr:
      - 10
      - null
      star_count:
      - 20
      - null
      correlation:
      - 0.3
      - null
    elongation_unusable: true
    min_stars_cfa: 3
  min_frames: 5
  fallback: malvar
equipment_profiles:
- name: default
  telescope: Unknown
  aperture_mm: 0
  focal_length_mm: 0
  camera: Unknown
  pixel_size_um: 3.76
  gain: 100
  offset: 50
  default_temp_c: -10.0
- name: dwarf_mini
  telescope: Dwarf Mini
  aperture_mm: 0
  focal_length_mm: 150
  camera: Dwarf Mini
  pixel_size_um: 2.9
  gain: 60
  offset: 10
  default_temp_c: 27.0
  mount_type: az
  preferred_registration: astroalign
  max_rotation_deg: 15
  max_exptime_fft_warn: 45
- name: dwarf3
  deprecated: true
  alias_for: dwarf_mini

```

Presets defined: 3

## Precedence & ENV

- 1. CLI Flags (highest priority) — e.g. `--preset`, `--darks-path`, `--cosmetic-correction`
- 2. `config.yaml` (User Config) — `data_root`, `darks_repository`, `default_preset`
- 3. ENV Vars `ASTRA_*` — `ASTRA_DATA_ROOT`, `ASTRA_DARKS_REPOSITORY`, `ASTRA_DEFAULT_PRESET`
- 4. Pydantic Defaults (lowest) — see tables above

Validation: `astra config show --json` shows the merged view; `astra config set <key> <value>` validates via Pydantic, invalid values raise an error.

## Environment Variables & .env File (V19-ENV)

Astra supports cross-platform configuration via environment variables and `.env` files. `config.yaml` and `config.example.yaml` use `${VAR:-default}` placeholders that are resolved **before** `yaml.safe_load` via `os.path.expandvars` (manual regex, because Python 3.11 `expandvars` does not support `:-default`) + `Path.expanduser().resolve()`. After `astra init --non-interactive`, the generated `config.yaml` contains **resolved** absolute paths and no `${}`.

Precedence for `.env` loading: **Shell Env > CWD/.env > pipeline_root/.env**. `python-dotenv` is loaded with `override=False`, so an existing Shell variable is never overwritten by `.env`. CWD wins over `pipeline_root` (project root that contains `src/astro_process`). Every path field is passed through `Path(value).expanduser().resolve()` after expansion, so `~/Astra` and `${HOME}/Astra` both resolve correctly. A missing `.env` triggers `astra doctor` warning `doctor.env_missing` (Exit 0, using defaults).

References: `.env.example` and `config.example.yaml` in the repository root. Fresh users: `cp .env.example .env` → edit → `astra init --non-interactive` → `astra process`. Legacy `config.yaml` files with hardcoded paths (e.g. `C:/Users/<your-user>`) remain compatible — values without `${}` are left unchanged.

### 1. Windows (PowerShell, persistent)

```powershell
# PowerShell — persistent user env (new shell required afterwards)
[Environment]::SetEnvironmentVariable("ASTRA_DATA_ROOT", "C:\Astra", "User")
[Environment]::SetEnvironmentVariable("ASTRA_DARKS_REPOSITORY", "C:\Astra\_darks", "User")
[Environment]::SetEnvironmentVariable("GIMP_PATH", "gimp", "User")
# verify in new shell
Get-ChildItem Env:ASTRA_*
# alternative (cmd): setx ASTRA_DATA_ROOT "C:\Astra"
```

### 2. Linux / macOS (bash, zsh)

```bash
# bash / zsh — add to ~/.bashrc or ~/.zshrc for persistence
export ASTRA_DATA_ROOT="$HOME/Astra"
export ASTRA_DARKS_REPOSITORY="$HOME/Astra/_darks"
export GIMP_PATH="gimp"
# verify
env | grep ASTRA_
```

### 3. .env File (recommended, cross-platform)

```dotenv
# .env — copy from .env.example (do not commit secrets)
# cp .env.example .env
ASTRA_DATA_ROOT=C:/Astra
ASTRA_DARKS_REPOSITORY=C:/Astra/_darks
GIMP_PATH=gimp
ASTRA_DEFAULT_PRESET=star_standard
# HOME fallback example:
# ASTRA_DATA_ROOT=${HOME}/Astra
```

### config.example.yaml — ${VAR:-default} expansion

```yaml
data_root: "${ASTRA_DATA_ROOT:-C:/Astra}"
darks_repository: "${ASTRA_DARKS_ROOT:-C:/Astra/_darks}"
gimp_path: "${GIMP_PATH:-gimp}"
# also supported: ${HOME}/Astra, $VAR, ${VAR}
```

`loader.py` expands every string value recursively via `_expand_env_string` before `yaml.safe_load`. `${VAR:-default}` → `env[VAR]` if set and non-empty, otherwise `default`; `${VAR}` / `$VAR` → `env[VAR]` or `""` (empty, handled by `Path` guard so it does not resolve to CWD). Shell Env always wins over `.env`.

### astra init --non-interactive (CI)

`astra init --non-interactive` is the CI-friendly, non-interactive mode. It reads flags / env vars instead of prompting, writes `config.yaml` + `environment.yaml` (Pydantic-validated) with resolved absolute paths, and is safe for `CI Ubuntu+Win/3.11` (required check). Examples:

```bash
astra init --non-interactive --data-root "$ASTRA_DATA_ROOT" --darks-library "$ASTRA_DARKS_REPOSITORY" --preset star_standard
# or via .env only (no flags — env vars are read automatically)
cp .env.example .env  # edit paths
astra init --non-interactive
astra doctor          # warns WARN doctor.env_missing if .env absent, but pipeline uses defaults
```

`astra doctor` (read-only) checks: Python, dependencies, GAIA, `config.yaml`, disk, paths, and `.env` existence. `astra doctor --fix` can create a missing `.env` from `.env.example`. Precedence for config discovery: explicit `--config path` > `CWD/config.yaml` > `pipeline_root/config.yaml` > `DEFAULT_CONFIG` string (wheel fallback). Each discovery is logged as `config.loaded_from` (source, path).

### CFA-Drizzle Quality Gate — Precedence (hidden flags, advanced)

CFA-Drizzle auto selects locking thresholds based on input type. Precedence: **CLI > Config > CFA-Smart-Defaults > Debayered-Defaults**. Hidden flags are documented here (advanced, not in Quickstart) — see `11-troubleshooting.md` for the full list: `--cfa-drizzle-fallback`, `--cfa-drizzle-star-count-min`, `--cfa-drizzle-snr-min`, `--cfa-drizzle-correlation-min`, `--cfa-drizzle-fwhm-range`.
