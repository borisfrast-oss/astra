# Changelog

All notable changes to **Astra** are documented here. Format oriented on
[Keep a Changelog](https://keepachangelog.com/). Release audit details are
maintained separately and are not shipped in this repository.

## [1.9.0] - 2026-09-01

### Highlights

- **Environment & Configuration** — Cross-platform `.env` support with `${VAR:-default}` expansion, non-interactive initialization, and `astra doctor` environment checks.
- **Governance & Community** — MIT license, clear DwarfLab disclaimer, contribution guidelines, code of conduct, security policy, and GitHub sponsorship support.
- **Release Engineering** — PyPI Trusted Publisher OIDC workflows, curated CHANGELOG via `git-cliff`, and CI matrix on Ubuntu + Windows with Python 3.11.
- **Smart Registration Defaults** — Added `dwarf_mini` profile and `dwarf3` alias, automatic mount-type detection, and priority chain (CLI > Equipment Profile > Auto-Detect > Config > Default). FFT registration on AZ mounts now warns for exposures above the configurable `max_exptime_fft_warn` threshold (default 45 s).
- **CFA Quality Gate** — Automatic selection between raw-CFA and debayered defaults for quality checks, configurable via `mode auto|cfa|debayered`.
- **PCC Toggle** — Added `--pcc/--no-pcc` CLI flags to override Photometric Color Calibration per run.

### Upgrade (short)

```bash
pip install astra-pipeline==1.9.0
cp .env.example .env  # edit ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY
astra init --non-interactive
astra doctor
```

### Breaking (short)

- Package install name changed from `astra` to `astra-pipeline`.
- `environment.yaml` is replaced by `.env` (`config.example.yaml` supports `${VAR:-default}`).
- `dwarf_mini` profile added; `dwarf3` is now a deprecated alias.
- `fft` registration on an AZ mount with exposures `>= 45 s` emits `WARN registration.fft_on_az_mount`.

See `docs/12-migration.md` (full upgrade guide v1.8→v1.9) and `docs/11-troubleshooting.md` (known issues and resolved defects).

## [v1.8] — 2026-08-27

**The High-Resolution Update.** This release brings major architectural
improvements to raw-data processing for the Dwarf Mini, introducing
state-of-the-art algorithms to beat the Dwarflab cloud locally: **Malvar2004**
high-quality debayering, **CFA-Drizzle** (Scale 2.0) for true sub-pixel detail,
and **Super-Pixel** as the new default debayer method.

### Added
- **V1.8-0 — Malvar2004 Debayer**: high-quality edge-preserving demosaicing
  (`debayer.method: malvar2004`), via `colour-demosaicing`. Bilinear deprecated.
- **V1.8-1 — CFA-Drizzle (Scale 2.0)**: optional sub-pixel drizzle on CFA raws
  (before debayer), Lanczos3 kernel, adaptive pixfrac, quality-gated, fallback
  malvar. `--cfa-drizzle`, `cfa_drizzle:` config. PoC ≤0.1px sub-pixel accuracy
  (M92, 41 frames).
- **V1.8-2 — Preview/Export-Pipeline**: `export.preview` config — background
  neutralization → SCNR → asinh → saturation → JPG (OQ-PEX-1 order),
  each step optional, byte-identical to v1.6 when block absent.
- **V1.8-3 — Asinh-Stretch FITS-Export**: optional `export.stretched_fits: true`
  produces an additional display-stretched FITS (`*_stretched.fits`, header
  `STRETCH=asinh`) for Lightroom/Photoshop. Linear FITS stays default/canonical.
  Platesolve-isolated (Discovery skips `_stretched`).
- **V1.8-4 — CLI + Docs Release**: `astra init` wizard (Non-TTY autofallback),
  `config`/`darks`/`target`/`status`/`doctor` subcommands, `process --preflight`,
  `inspect --quality`, `doctor --fix`. Docs-Generator `scripts/generate_docs.py`
  producing 12 `docs/` files from source. `rich`/`prompt-toolkit` deps.
- **V1.8-5 — Test-Suite Cleanup**: consolidated 7 test files (51 → 44 test
  files) with no test-loss; 1050 passed + 2 skipped.
- **V1.8-6 — Pipeline-Docs Migration**: `docs/` (12 files) becomes SSOT;
  KB docs deprecated to placeholders; `project.md` trimmed; `README.md` fixed;
  `CHANGELOG.md` added; `Makefile` (`docs`/`check-docs`); pre-release hook wiring.
  **V1.8-6-FF (finalization)**: finalized AC-DOCS-A2/D1 — all 12 docs generated
  hash-stably via `generate_docs.py` and written in English per §17.
- **V1.8-7 — Debayer-Superpixel Validation**: 1:1 validation of bilinear vs
  superpixel vs malvar methods, pattern-aware, with reviewed extensions
  (color-fringe <10%, moiré-FFT, flux <2%; M92 visually documented-skip).
  Test-only.

### Test status
- 1050 passed, 2 skipped, 0 failed (after V1.8-5/V1.8-7, internal review).

## [v1.7] — Always Multi-Group + Quality-Boost + Equipment Auto-Detection

### Added
- **V1.7-5 — Always Multi-Group**: unified processing path — `astra process`
  always runs Multi-Group logic (`group_{hash}/` structure even for 1 group);
  `--multi-group`/`--auto-group` deprecated to no-op with warning.
- **V1.7-2 — Frame-Selection / Quality-Scoring**: per-group relative score
  (Median/MAD, SNR/star_count/FWHM/elongation), keep-percentile (default 92%),
  opt-in, transparent via agent-log/inspect/doctor.
- **V1.7-3 — Sigma-Clipped Mean Stack**: 5th stacking method (iterative 3σ,
  max 5 iterations, early-stop), opt-in via `stacking_method`.
- **V1.7-4 — Equipment Auto-Detection**: equipment params from Light FITS
  headers (majority) > config profile > none+warning; `astra inspect`/`doctor`
  show source per field.
- **V1.7-1 — Filter-Selection Merge**: `--merge-filter` / `merge.filters` to
  merge only selected filters (e.g. Astro, exclude Duo-Band); excluded groups
  kept as separate stacks, documented in merge_report.

### Teststand
- 930 passed (Branch v1.7).

## [v1.6] — Architektur-Release: FITS-SSOT + Bilinear Debayer + Device-Independence — 2026-08-20

### Added
- **V1.6-1 — FITS-Header als SSOT**: mandatory validation, generic filename patterns.
- **V1.6-2 — Bilinear Debayer**: full resolution 1920×1080, `debayer.method` config.
- **V1.6-3 — Asinh-Stretch Preview-JPG** (DwarfLab-compatible).
- **V1.6-4 — Registration-Bug fix** ("unexpected_rotation" in cross-group).
- **V1.6-5 — PCC Fallback-Speed** (VizieR primary, GAIA fallback).
- **V1.6-6..9 — Device-Independence**: generalized comments, shotsInfo removed
  from pipeline logic (EQMODE header primary), FITS-header aliases documented,
  `environment.yaml` (`telescope_export_root`).

### Changed
- Architecture: FITS-SSOT for lights, filename-fallback only for dark/flat/bias.

### Teststand
- 814 passed.

## [v1.5] — CI-Gate + Quality Foundation + CLI-Comfort + Doku — 2026-08-19

### Added
- V1.5-1 CI-Gate; V1.5-2 PCC/GAIA-Lücken-Doku; V1.5-3 Elongations-Check;
  V1.5-4 CD-Matrix-Semantik; V1.5-5 Top-Level `final.fits`; V1.5-6 dry-run factory;
  V1.5-7 Doku-Limitationen; V1.5-8 Outlier-Rejection; V1.5-9 Star-Double-Detektor;
  V1.5-10 inspect EQMODE/shotsInfo; V1.5-11 `--az-mode`/`--eq-mode`;
  V1.5-12 `--pixel-scale`; V1.5-13 `--se-radius`/`--se-amount`;
  V1.5-14 Warnings maschinenlesbar; F-RY-MINOR-V11 fixes.

### Teststand
- 818 passed. 3× internally approved.

## [v1.2] — astroalign + Gradient Removal + Quality Foundation + Plugin-Interface — 2026-08-06

### Added
- **W9 astroalign-Integration** (registration method, default fft, fallback chain).
- **Gradient Removal** (default off, grid 16×16, halo/nebulosity protection).
- **Quality Foundation** (SNR/FWHM/outlier flagging, Golden Master M13/M27).
- **Plugin-Interface** (`astra.plugins` + `astra plugin list`).
- **Structure Enhancement** (first production plugin, `nebula_standard`).
- **F-META-1.2 Header-Metadaten-Export** (light keys + PCC WCS + effective pixel
  scale, `stack_scale_factor` 2.0) — fixes Siril platesolve.
- **Internal request**: SanityGuard configurable (`--max-rotation`), shotsInfo.json
  integration, input staging `00_input` (**breaking**: pipeline reads only
  `generated/<ts>/00_input`).

### Teststand
- 449 passed + 1 skipped. Final internal sign-off.

## [v1.1] — CR-001 Multi-Group Fixes + Production Hardening — 2026-08-03

### Added
- CR-001 sign-off (W1–W14 + W7 extension); Hardening T1–T5: GAIA timeout (30s) +
  gray-world fallback, `--no-calib`, `astra doctor`, error-handling E1,
  synthetic test data, per-group master-darks + `dark_source`, FITS duplicate fix.

### Teststand
- 169 passed. Internal sign-off with condition (condition fulfilled).

## [v1.0] — Multi-Group Stacking — 2026-07-30

### Added
- Multi-Group Stacking (auto-grouping by EXPTIME/GAIN/FILTER, shared-reference
  registration, PCC-aware merge, CLI). Phases 1–4 complete. M13 integration test green.
