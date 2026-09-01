# Migration Notes

## v1.8 -> v1.9 (v19) upgrade — The 0€ Community Release

> **Scope:** v1.9 is the first PyPI community release (6 features, 15–17d, 0€, PyPI-only). No Docker/PyInstaller in v1.9.0 — deferred to v1.9.1/v1.10. Upgrade is fast (5 min) and backward-compatible for existing `config.yaml` (hardcoded paths still load).

### Upgrade checklist (5 minutes)

1. **Install the renamed package** (name changed `astra` → `astra-pipeline`, `pip install` changes):
   ```bash
   pip install astra-pipeline==1.9.0
   # legacy `pip install astra` no longer works — use `astra-pipeline`
   astra --help
   ```
2. **Adopt `.env` (one-time)** — copy, edit, regenerate config:
   ```bash
   cp .env.example .env          # edit ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, GIMP_PATH
   astra init --non-interactive  # reads .env + flags, writes config.yaml with RESOLVED absolute paths (no ${})
   astra doctor                  # WARN doctor.env_missing if .env absent, Exit 0 (defaults used)
   ```
3. **Verify equipment profile** — new default `dwarf_mini` (AZ, astroalign 15°, warn 45 s); alias `dwarf3` still loads but logs `WARN equipment.profile_deprecated alias=dwarf_mini`:
   ```bash
   astra inspect "C:/Astra/M13"          # shows mount_type + preferred_registration per field + source
   astra config show --json | grep -A5 equipment_profiles
   ```
4. **Smoke without flags** — Smart Defaults do the right thing:
   ```bash
   astra process "C:/Astra/M13" --dry-run   # shows registration method + CFA gate decisions without executing
   ```
5. **Reproduce a known v1.8 run** (no new flags) → output byte-identical unless AZ long-exposure or CFA-Drizzle triggers the new Smart Defaults (see Breaking). Then opt in selectively:
   ```bash
   astra process "C:/Astra/M13"             # default run
   astra process "C:/Astra/M13" --registration-method astroalign --max-rotation 15  # if WARN appears
   astra process "C:/Astra/M13" --cfa-drizzle --cfa-drizzle-quality-gate            # try drizzle without config edit
   ```

### Breaking changes in v1.9

1. **`pyproject.toml` name `astra` → `astra-pipeline`** — PyPI name is now `astra-pipeline`. `pip install astra` (old) fails; use `pip install astra-pipeline`. Local `pip install -e .` still exposes console script `astra`. `authors` is now `Boris Frast <borisfrast@gmail.com>`, `urls` (Homepage/Repository/Issues/Changelog) complete, `classifiers` MIT + 3.11 + Science/Astronomy present.
2. **`.env` migration replaces `environment.yaml`** — `config.yaml` now ships `config.example.yaml` with `${VAR:-default}` placeholders (e.g. `data_root: "${ASTRA_DATA_ROOT:-C:/Astra}"`). Loader does `os.path.expandvars` (manual `:-default` regex, because Python 3.11 `expandvars` does not support it) **before** `yaml.safe_load`, then `Path.expanduser().resolve()` for `~/`. `.env` is loaded via `python-dotenv` (`override=False`, so Shell Env always wins over `.env`). Precedence for dotenv files: **CWD/.env > pipeline_root/.env > none**; for config files: **explicit --config > CWD/config.yaml > pipeline_root/config.yaml > DEFAULT_CONFIG**. Old `config.yaml` with hardcoded `C:/Users/...` still loads unchanged (values without `${}` are left untouched). `environment.yaml` is removed from the loader; only `config.yaml` + `.env` are read. (`astra init` still writes `environment.yaml` for backward compatibility; the loader no longer reads it in v1.9.) `astra doctor` warns `WARN doctor.env_missing` if `.env` not found (Exit 0).
3. **`equipment_profiles: dwarf_mini` (new) + `dwarf3` deprecated alias** — `dwarf_mini` is the correct Dwarf Mini profile (`mount_type: az`, `preferred_registration: astroalign`, `max_rotation_deg: 15`, `max_exptime_fft_warn: 45`, sensor IMX462, 2.9 um, 1920×1080, bayer RGGB, debayer_factor 2.0, focal 150 mm). `dwarf3` stays as `deprecated: true, alias_for: dwarf_mini` for backward compatibility (`model_config extra="ignore"` tolerates extra fields). Using `dwarf3` logs `WARN equipment.profile_deprecated`. Header `TELESCOP=DWARF MINI` maps to `dwarf_mini` via `TELESCOPE_PROFILE_MAP`.
4. **Registration Warning `registration.fft_on_az_mount` at `fft` + AZ + `exptime >= 45 s`** — FFT = translation-only (`rotation_deg: 0.0` by construction, `cv2.phaseCorrelate` measures only X/Y shift). On AZ mount with `exptime >= 45 s` (project decision: `>=45` not `>60`, threshold `max_exptime_fft_warn: 45`) field rotation is not correctable → Ghosting at borders (double-star contours, e.g. `frame 27: method fft rotation_deg 0.0 shift_y 31 shift_x -44`). The pipeline now emits:
   ```text
   WARN registration.fft_on_az_mount method=fft mount_type=az exptime=60 threshold=45
        detail="FFT on AZ with 60s — field rotation not correctable (Threshold: 45s).
        Expected: Ghosting at borders, star double contours (rotation_deg 0.0 is FFT artifact).
        Solution: --registration-method astroalign --max-rotation 15
        or Equipment profile with preferred_registration: astroalign"
   ```
   Fix: pass `--registration-method astroalign --max-rotation 15` or rely on the new default `dwarf_mini` (no flag needed). Not a hard error — the frame still registers, but the stack will ghost at the edges. No breaking change for EQ users (default stays `fft`, header without mount defaults to `eq` + `WARN discovery.mount_unknown`).

### New config blocks

```yaml
# .env → config.example.yaml (expandvars ${VAR:-default})
data_root: "${ASTRA_DATA_ROOT:-C:/Astra}"
darks_repository: "${ASTRA_DARKS_ROOT:-C:/Astra/_darks}"
gimp_path: "${GIMP_PATH:-gimp}"

# equipment_profiles (models.py EquipmentProfile, extra="ignore")
equipment_profiles:
  - name: "dwarf_mini"
    telescope: "Dwarf Mini"
    mount_type: "az"
    preferred_registration: "astroalign"
    max_rotation_deg: 15
    max_exptime_fft_warn: 45
    resolution: [1920, 1080]
    pixel_size_um: 2.9
    bayer_pattern: "RGGB"
    sensor: "IMX462"
  - name: "dwarf3"
    deprecated: true
    alias_for: "dwarf_mini"

# cfa_drizzle quality_gate mode (loader.py DEFAULT_CONFIG, models.py)
cfa_drizzle:
  enabled: false
  scale: 2.0
  pixfrac_mode: "auto"
  pixfrac: 0.5
  kernel: "lanczos3"
  quality_gate:
    mode: "auto"   # auto | cfa | debayered — auto = CFA when is_cfa=True
    rejection_enabled: true
    thresholds:
      fwhm: [1.5, 5.0]
      snr: [10, null]
      star_count: [20, null]
      correlation: [0.3, null]
    elongation_unusable: true
    min_stars_cfa: 3
  min_frames: 5
  fallback: "malvar"

# pcc.enabled optional (models.py PCCConfig.enabled Optional[bool]=None)
pcc:
  enabled: null   # null = Preset wins, true = always PCC, false = never PCC (CLI wins always)
  quality_gate:
    enabled: true
    min_factor: 0.5
    max_factor: 2.0
```

Precedence everywhere is **CLI > Config > Smart-Defaults/Debayered/Preset > hardcoded Default**. All new fields have safe defaults (`mode auto`, `pcc.enabled null`) → no migration required.

### CFA-Drizzle Auto Quality Gate (V19-CFA-GATE)

CFA-Drizzle (V1.8-1) runs on Bayer CFA raw (1 channel, 25 % pixels/color) with different statistics than debayered RGB (3 channels). Without the gate, M31 60/90/120 s Duo-Band → 100 % rejection → `fallback_materialized malvar` at 960×540 instead of `01c_drizzle/drizzled_master.fits` 3840×2160. The gate selects CFA-appropriate thresholds automatically.

| Metric | Debayered default | CFA-Smart default (auto when `is_cfa=True`) | Notes |
|--------|-------------------|---------------------------------------------|-------|
| `star_count` | `[20, null]` | `[1, null]` | Bayer has 1–2 stars detectable before debayer |
| `snr` | `[10, null]` | `[5, null]` | lower SNR per channel |
| `correlation` | `[0.3, null]` | `[0.1, null]` | 0.1–0.4 on Bayer vs 0.3+ debayered |
| `fwhm` | `[1.5, 5.0]` | `[1.0, 8.0]` | Bayer PSF broader |
| `min_stars_cfa` | `3` | `1` | separate field, not thresholds |

`resolve_cfa_drizzle_quality_gate(user_gate, is_cfa, cli_overrides)` merges thresholds **recursively** (`{**base["thresholds"], **user["thresholds"]}`) — internally reviewed: `deep_merge` shallow would overwrite `thresholds` entirely. Without `user_gate`/`cli_overrides` → directly `CFA_DEFAULTS` when `is_cfa=True`, else `DEBAYERED_DEFAULTS`.

- **Config `cfa_drizzle.quality_gate.mode: auto|cfa|debayered`** (Default `auto` → CFA when `is_cfa=True`, else debayered). `cfa`/`debayered` forces the base explicitly (debugging, power user).
- **CLI:** only **1 flag visible** in `astra process --help`: `--cfa-drizzle-quality-gate/--no-cfa-drizzle-quality-gate` (auto on/off) + `--cfa-drizzle-min-frames`. **5 hidden/advanced** (not in Quickstart, but in `04-configuration.md` + `11-troubleshooting.md`): `--cfa-drizzle-fallback` (malvar/superpixel/skip) + `--cfa-drizzle-star-count-min` + `--cfa-drizzle-snr-min` + `--cfa-drizzle-correlation-min` + `--cfa-drizzle-fwhm-range` ("1.0,8.0" → parsed). CLI always wins.
- **Precedence:** **CLI > Config > CFA-Smart-Defaults > Debayered-Defaults** (AC-CFA-4a/4b split tested).
- **Warning `_warn_if_overly_strict`:** stricter user thresholds (e.g. `star_count 10 > CFA 1`) trigger `WARN cfa_drizzle.quality_gate_relaxed detail="Quality Gate for CFA-Drizzle adjusted: star_count=10 > CFA 1. Bayer data has different stats."` — warning only, user value still wins (no silent override). Escape hatch `--no-cfa-drizzle-quality-gate` → `rejection_enabled=False` → all frames pass.

### PCC Flag `--pcc/--no-pcc` (V19-PCC-FLAG)

Use case: M31 Galaxy `galaxy_standard` includes PCC but has 6 min GAIA timeout (star-poor field). Without the flag you need a custom preset or `config.yaml` edit.

- **CLI:** `--pcc/--no-pcc` (default `None` → Preset/Config wins, no breaking change). Existing `--pcc-per-group/--no-pcc-per-group` stays independent (location: PCC per group vs on merged stack).
- **Precedence:** **CLI `--pcc/--no-pcc` > Config `pcc.enabled` > Preset Steps (contains/ not contains `photometric_color_calibration`) > Default (Preset decides)**.
- **Config `pcc.enabled: Optional[bool]=None`** (`models.py` `PCCConfig.enabled`, `loader.py` `DEFAULT_CONFIG` commented `enabled: null`). Checked via `"enabled" in cfg.pcc.model_fields_set` (Pydantic v2) — only explicit set overrides Preset, default `None` leaves `galaxy_standard` (has PCC) / `nebula/star_standard` (no PCC) unchanged.
- **Batch-safe mutation:** runtime mutates a `copy.deepcopy(preset)` per `process()` call, never `cfg.pipeline_presets` object (internally reviewed: next `batch` call would otherwise see wrong preset). `insert` case emits `logger.info pcc.cli_override enabled=True preset=galaxy_standard inserted_after=background_extraction/stack_frames/stack_frames_fallback`, `remove` case `enabled=False removed=photometric_color_calibration` (additively in `agent-log.yaml`).
- **Insert Fallback** (project decision: `star_standard` has `natural_color_processing→scnr`, no `background_extraction`): `background_extraction → stack_frames → len-2` (before stretch/export). `--pcc` on `nebula/star_standard` inserts exactly once after the first found anchor; `--no-pcc` on `galaxy_standard` removes the step.

```bash
astra process M31 --preset galaxy_standard --no-pcc              # fast, no 6 min block
astra process M42 --preset nebula_standard --pcc                 # force PCC
astra process M45 --preset star_standard --pcc                   # same insert after stack_frames
astra process M42 --preset nebula_standard --pcc --pcc-per-group # PCC per group (less S/N per group)
```

### Environment & .env (V19-ENV)

Cross-platform config without Shell-Env requirement. `config.yaml` / `config.example.yaml` placeholders `${VAR:-default}` resolved **before** `yaml.safe_load` via manual regex (`${VAR:-default}` → `env[VAR]` if set and non-empty else `default`; `${VAR}`/`$VAR` → `env[VAR]` or `""`). Every string value is recursed (`_expand_env_string` in `loader.py`), then `Path(value).expanduser().resolve()` so `~/Astra` and `${HOME}/Astra` both work; empty strings stay empty (not resolved to `CWD`). Shell Env always wins over `.env` (`python-dotenv` `load_dotenv(..., override=False)`). Dotenv load order: `CWD/.env` > `pipeline_root/.env` (directory containing `src/astro_process/`), each via `find_dotenv`. Missing `.env` → `astra doctor` emits `WARN doctor.env_missing` ("`.env` not found, using defaults", not a silent ignore) with Exit 0; `astra doctor --fix` can create it from `.env.example`. `astra init --non-interactive` reads flags/env vars instead of prompts (CI-friendly, also used on `ubuntu-latest` + `windows-latest` CI), writes `config.yaml` with **resolved** absolute paths and no `${}`.

```
Fresh: cp .env.example .env → edit → astra init --non-interactive → astra process
Legacy: old config.yaml without ${} loads unchanged — no force migration
```

**Env examples** (documented in `04-configuration.md` + `03-cli-reference.md`):

```powershell
# Windows PowerShell (persistent, new shell required)
[Environment]::SetEnvironmentVariable("ASTRA_DATA_ROOT", "C:\Astra", "User")
[Environment]::SetEnvironmentVariable("ASTRA_DARKS_REPOSITORY", "C:\Astra\_darks", "User")
# verify: Get-ChildItem Env:ASTRA_*
```
```bash
# Linux / macOS (bash/zsh, add to ~/.bashrc or ~/.zshrc)
export ASTRA_DATA_ROOT="$HOME/Astra"
export ASTRA_DARKS_REPOSITORY="$HOME/Astra/_darks"
export GIMP_PATH="gimp"
```
```dotenv
# .env (recommended, cross-platform, .env.example → .env)
ASTRA_DATA_ROOT=C:/Astra
ASTRA_DARKS_REPOSITORY=C:/Astra/_darks
GIMP_PATH=gimp
ASTRA_DEFAULT_PRESET=star_standard
```

### Governance (V19-GOV, 0€)

- **LICENSE:** MIT `Copyright (c) 2026 Boris Frast <borisfrast@gmail.com>` (was `previous project attribution`). `pyproject.toml` `license = {text="MIT"}` + `classifiers += "License :: OSI Approved :: MIT License"` + `authors = [{name="Boris Frast", email="borisfrast@gmail.com"}]`.
- **Disclaimer:** `README.md` header/footer: `**Disclaimer:** Astra is not affiliated with DwarfLab. DwarfLab is a trademark of its respective owner.` (OQ-GOV-3, 0€ without lawyer).
- **Privacy:** `git grep -i "boris\|C:\\\\Users\|C:/Users"` → 0 hits except `CONTRIBUTING.md`/`SECURITY.md` contact + `example.yaml` placeholder `C:/Astra` (not `C:/Users/<your-user>`). `gimp_path` in `loader.py DEFAULT_CONFIG` changed from `C:/Users/<your-user>/...` → `gimp` (PATH resolution); `config.example.yaml` uses `C:/Astra` generic.
- **Community files:** `CONTRIBUTING.md` (Fork→Branch→Conventional Commits→PR→CI→Review), `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1, Contact `borisfrast@gmail.com`), `SECURITY.md` (Supported ≥1.9.0, Reporting via GitHub Security Advisories / `borisfrast@gmail.com`).
- **Metadata:** `pyproject.toml` `urls` (Homepage/Repository/Issues/Changelog), `classifiers` complete, `keywords` cleaned, entry point `astra = "astro_process.cli:cli"`, `FUNDING.yml` (`.github/FUNDING.yml` `github: borisfrast` active; `ko_fi`/`paypal` are TODO — commented out until Boris provides handles, to avoid 404 links) and GitHub Topics `astrophotography, astronomy, fits, pipeline, python, scientific` (heart Sponsor button after merge).

### Release: PyPI OIDC, git-cliff CHANGELOG, SemVer

- **PyPI Trusted Publisher OIDC** (no token in repo) — split workflows:
  - **`.github/workflows/publish.yml`** = **Prod PyPI** only: `on: push: tags: ['v*.*.*', '!v*.*.*-*']` (final SemVer tags only; the `!v*.*.*-*` negative pattern excludes ALL pre-release suffixes like `v1.9.0-rc1`), `permissions: id-token: write`, `uses: pypa/gh-action-pypi-publish@release/v1` with `environment: pypi` (PyPI project `astra-pipeline` → Trusted Publisher → GitHub `borisfrast/astra` + `publish.yml` + `pypi` env), plus a defense-in-depth `if: ${{ !contains(github.ref, '-') }}` job guard.
  - **`.github/workflows/publish-testpypi.yml`** = **TestPyPI** only: `on: push: tags: ['v*.*.*-rc*']` (rc tags only), `environment: testpypi`.
  - **Trusted-Publisher-Binding (maintainer action before M5):** after the split the TestPyPI Trusted-Publisher entry must be reconfigured to point at `publish-testpypi.yml` + `testpypi` env; the Prod-TP entry stays `publish.yml` + `pypi`.
  - Fallback token only if OIDC blocked. `hatchling` builds `wheel` + `sdist` via `python -m build`. Registry check before tag: PyPI name `astra-pipeline` confirmed free.
- **CI Matrix** (slim, required check): `.github/workflows/ci.yml` `os: [ubuntu-latest, windows-latest]` × `python: ["3.11"]` (2 runners, not 6). Steps: checkout → setup-python 3.11 → `pip install -e .[dev]` → `pytest` → `astra --help` smoke → `python scripts/generate_docs.py check`. `macOS/3.12` deferred to v1.9.1 (manual/optional).
- **Tags:** `v1.9.0-rc1` → TestPyPI dry-run via `publish-testpypi.yml` (M5) → `v1.9.0` → PyPI prod via `publish.yml` (M6). `git tag -a v1.9.0 -m "v1.9.0" && git push origin v1.9.0`. `pyproject.toml` version bumps to `1.9.0` before tag.

### CHANGELOG curation via git-cliff (B6)

`CHANGELOG.md` is a **curated** changelog (ADR-026). `git-cliff` produces a
configurable draft from Conventional Commits; the release manager reviews,
edits, and commits the final section as part of the release commit. There is
no automated regeneration step that must run before a tag.

**Usage (draft generation only):**

```bash
# preview unreleased commits (draft, not a commit requirement)
cd astra && git cliff --unreleased --strip header

# generate a draft section anchored from the v1.8 merge point
# (no v1.8 tag exists; adjust the range if history was rewritten)
cd astra && git cliff 42b2104..HEAD --tag v1.9.0 --strip header
```

**Release version/tag semantics (ADR-025):**

- `v1.9.0-rc1` is created while `pyproject.toml` still reads `1.9.0rc1`
  (TestPyPI dry-run, M5).
- The version in `pyproject.toml` is bumped to `1.9.0` only at M6,
  immediately before the final `v1.9.0` tag and PyPI prod release.

**Pre-release checklist** (`[tool.astra].pre_release_steps` in `pyproject.toml`):
`python scripts/generate_docs.py all && python scripts/generate_docs.py check`
(hash-stable docs + English clean). CHANGELOG curation is a manual review step,
not an automated gate.

## v1.1 -> v1.2 (v12) upgrade

The v1.2 release added astroalign-based registration, Gradient Removal,
Quality Foundation reporting, and the first production plugin
(Structure Enhancement). Existing v1.1 configurations continue to work
because defaults are backward-compatible:

- Registration default remains `fft` (byte-identical to v1.1).
- Gradient Removal default is `enabled: false`.
- Report fields are strictly additive.

### New config blocks

```yaml
registration:
  method: "fft"
  max_control_points: null
  max_rotation_deg: 2.0
  max_scale_dev: 0.02
  stack_scale_factor: 2.0

gradient_removal:
  enabled: false
  degree: 2
  grid: [16, 16]
  sigma_clip: 3.0
  min_samples: null
```

Precedence for the new fields: **CLI > Config > Preset > Default**.

### Breaking changes in v1.2

1. **Input staging `00_input`**: The pipeline reads only from
   `generated/<ts>/00_input/`. FITS files in the target root or other
   folders are ignored. All targets already follow the `lights/` (+ optional
   `darks/`, `flats/`, `bias/`) structure, so no manual migration is needed.
2. **`stack_scale_factor` default is `2.0`**: The effective pixel size in the
   exported FITS header is now based on the actual superpixel downscale of
   the stack, not a 4× assumption. This fixes plate-solving in Siril.
3. **Structure Enhancement in `nebula_standard`**: The preset declares the
   `structure_enhancement` step, so it now runs automatically with
   conservative defaults (`radius 3.0`, `amount 0.2`). Presets without the
   step are unchanged.

### v1.2 upgrade checklist

1. Install optional extras if you want astroalign:
   `pip install "astra[astroalign]"`.
2. Run `astra doctor` and resolve any FAIL/WARN.
3. Back up the existing config; run `astra init` or add the new blocks
   manually.
4. Reproduce a known v1.1 run without new flags to confirm identical output.
5. Enable new features selectively:
   - astroalign: `--registration-method astroalign`
   - Gradient Removal: `--preset nebula_standard --gradient-removal-enabled`
   - Structure Enhancement: automatic in `nebula_standard`
6. Inspect the report and preview for plausibility.

## v1.0 -> v1.1

v1.1 introduced CR-001 Multi-Group fixes and production hardening:
GAIA timeout with gray-world fallback, `astra doctor`, `--no-calib`,
per-group darks with `dark_source`, and improved error handling.
