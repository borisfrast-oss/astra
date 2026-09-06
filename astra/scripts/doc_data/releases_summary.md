# Release Summary

## Version overview

| Version | Title | Key changes |
|---------|-------|-------------|
| v1.9 | 0€ Community Release (PyPI, 6 features, 15–17d) | .env + `config.example.yaml` (`${VAR:-default}`, `expandvars` before `yaml.safe_load`, `python-dotenv` CWD>pipeline_root, `doctor.env_missing`, `init --non-interactive`), Governance MIT Boris Frast + Disclaimer + `CONTRIBUTING`/`CODE_OF_CONDUCT`/`SECURITY`/`FUNDING.yml` (privacy grep 0), `astra-pipeline` PyPI OIDC Trusted Publisher + CI Ubuntu+Win/3.11 + curated `git-cliff` CHANGELOG (ADR-026, draft on demand only) + SemVer `v1.9.0-rc1`→`v1.9.0`, `dwarf_mini` (az, astroalign 15°, warn 45 s) + `dwarf3` deprecated alias + `detect_mount_type`/`detect_preferred_registration` + Priority Chain CLI>Profil>Auto>Config>hardcoded `fft` + `registration.fft_on_az_mount` `>=45s` Ghosting warn + per-group + Cross-Group `astroalign 20°`, CFA-Drizzle Auto Gate (`CFA_DEFAULTS` vs `DEBAYERED` star_count 20→1, snr 10→5, corr 0.3→0.1, fwhm 1.5-5.0→1.0-8.0, `mode auto\|cfa\|debayered`, 1 visible + 5 hidden CLI flags, precedence CLI>Config>CFA>Debayered, `cfa_drizzle.quality_gate_relaxed` warn), PCC Flag `--pcc/--no-pcc` (default None, CLI>Config>Preset, `deepcopy` batch-safe, insert fallback `background_extraction→stack_frames→len-2`, `pcc.enabled Optional[bool]=None` `model_fields_set` check). |
| v1.8 | High-Resolution Update | Malvar2004 debayer, CFA-Drizzle (2x), super-pixel default, preview/export pipeline, CLI wizard (`astra init`), `darks`/`target`/`status`/`doctor` subcommands, docs generator producing 12 SSOT files. |
| v1.6 | Architecture Release | FITS header as SSOT, bilinear debayer, asinh-stretch preview, fixed cross-group registration rotation bug, PCC fallback speed-up, device-independence (`telescope_export_root`), `environment.yaml`. |
| v1.5 | CI Gate + Quality Foundation | CI gate, PCC/GAIA gap docs, elongation check, CD-matrix semantics, top-level final FITS placement, dry-run factory, outlier rejection, star-double detector, `--az-mode`/`--eq-mode`, `--pixel-scale`, `--se-radius`/`--se-amount`, machine-readable warnings. |
| v1.2 | astroalign + Gradient Removal + Quality Foundation | Optional astroalign registration, gradient removal (default off), quality metrics, plugin interface, structure enhancement as first production plugin, effective pixel scale (`stack_scale_factor: 2.0`), input staging `00_input` breaking change. |
| v1.1 | CR-001 Multi-Group Fixes + Production Hardening | GAIA timeout with gray-world fallback, `--no-calib`, `astra doctor`, per-group darks with `dark_source`, improved error handling, synthetic test data. |
| v1.0 | Multi-Group Stacking | Auto-grouping, shared reference, PCC-aware merge, CLI. |

## Breaking changes

- **v1.9** — `pyproject.toml` name `astra` → `astra-pipeline` (install via `pip install astra-pipeline`, not `astra`); `config.yaml` `environment.yaml` replaced by `.env` + `config.example.yaml` (`${ASTRA_*:-default}` expandvars before `yaml.safe_load`); old hardcoded `config.yaml` still loads unchanged. New equipment profile `dwarf_mini` (az, astroalign 15°, warn 45 s); `dwarf3` kept as `deprecated: true alias_for: dwarf_mini` with `WARN equipment.profile_deprecated`. Warning `registration.fft_on_az_mount` at `fft` + AZ + `exptime >= 45s` (Ghosting detail + `Solution: --registration-method astroalign --max-rotation 15`); no hard error. No CLI breaking for defaults (PCC `--pcc/--no-pcc` default `None` = Preset/Config wins; CFA `--cfa-drizzle-quality-gate` default auto = Smart Default; `pcc.enabled` default `null` keeps Preset). CI now requires `Ubuntu+Win/3.11` (macOS/3.12 deferred, not a migration issue).
- **v1.2** — Pipeline reads only from `generated/<ts>/00_input/`; FITS files
  in the target root are ignored. Effective pixel scale default changed to
  `2.0` (super-pixel downscale). Structure Enhancement now runs automatically
  in the `nebula_standard` preset.
- **v1.6** — `dwarflab_root` renamed to `telescope_export_root` in
  `environment.yaml`; shotsInfo.json no longer drives pipeline logic, EQMODE
  header is primary.

## Known issues reflected in releases

- FITS-SSOT adoption means calibration frames must supply EXPTIME and GAIN
  either in the header or via filename fallback; missing metadata is a hard
  error.
- Bilinear debayer can introduce moire/ringing/false color; super-pixel
  remains the default and recommended method.
- GAIA TAP timeouts in narrow-band or star-poor fields fall back to VizieR,
  then to gray-world or skip based on config.

## Known issues (v1.9)

**Small, transparent list — v1.9 intentionally 0€ PyPI-only, heavier targets deferred.**

- **rotation_fft not Auto-Default for AZ** — only Fallback. AZ Smart Default is `astroalign` (robust, flux-sorted RANSAC). `rotation_fft` (log-polar FFT) is only used when `astroalign` extra is missing or when the Equipment profile explicitly sets `preferred_registration: rotation_fft`. Reason (OQ-REG-1, V1.4-2 experiment): less robust on star-poor fields. Workaround: `astra process --registration-method rotation_fft` for explicit log-polar, or install `astra[astroalign]`.
- **macOS + Python 3.12 CI deferred** — CI required matrix is `Ubuntu+Win/3.11` only. macOS and 3.12 are built manually / via `continue-on-error` and become required in v1.9.1 (see `v19-deferred-concept.md`).
- **Docker / PyInstaller deferred** — No `.exe` (unsigniert, 60 MB scipy/numpy, AV false-positive) and no GHCR image in v1.9.0. `pip install astra-pipeline==1.9.0` on `ubuntu-latest` + `windows-latest` verified (TestPyPI smoke). Docker → v1.10 (3–4d), PyInstaller → v1.9.1 (2–3d, unsigniert + README SmartScreen "More info → Run anyway").
- **DCO (signed commits) deferred** — unsigned project history preserved; `DCO Require signed commits` after `v1.9.0` (GitHub Settings) → v1.9.1 plus RTD/Lock/Scanning → v1.10.

**Fixed in v1.8–v1.8.8 (formerly known issues, now resolved — no longer present in v1.9):**

- **DEF-004 (Blocker, resolved 2026-08-29)** — M92 41×CFA frames all rejected by overly strict Quality Gate (`fwhm_median=None` → 100% outlier → no `01c_drizzle/`). Fixed via Luminanz-Hochpass `gaussian_filter σ=30` + `min_stars_cfa 3`, now subsumed by V1.9 CFA-Smart Defaults (`star_count 1`, `min_stars_cfa 1` when `is_cfa`) + warning.
- **DEF-005 (Major, resolved 2026-08-29)** — `min_frames_fallback` logged `fallback: malvar` but output stayed superpixel 960×540 (not materialized). Fixed: fallback materialized (malvar + `stack_scale_factor 1.0`).
- **DEF-006 / V1.8-8 (Major, resolved 2026-08-29)** — Ghosting M92 3× (8 catastrophically-registered frames with `corr_hp <0.01` averaged in `average` stacking despite flag). Fixed: `star_standard` `average` → `winsorized` + mandatory `corr_hp` gate `0.05` (`rejection_min_corr_hp`, analog V1.4-20) — V1.9 keeps this gate (configurable `0.05`, `null` disables).

## Release engineering (v1.9, 0€) — CHANGELOG & OIDC (B6)

- **`cliff.toml`** (git-cliff, Conventional Commits, `tag_pattern "v[0-9].*"`) supports the curated CHANGELOG (ADR-026). `CHANGELOG.md` is maintained manually; git-cliff is used only to produce an optional draft when needed. There is no automated regeneration step that must run before a tag.

  Optional draft (no v1.8 tag exists; use the v1.8 merge point as range anchor):
  ```bash
  cd astra && git cliff 42b2104..HEAD --tag v1.9.0 --strip header
  # preview unreleased commits without a tag:
  cd astra && git cliff --unreleased --strip header
  ```
  The release manager reviews the draft, edits the final section, and commits it as part of the release commit. Before-tag checklist: `python scripts/generate_docs.py all && python scripts/generate_docs.py check` (hash-stable, English-clean) → review/edit `CHANGELOG.md` → commit.
- **Trusted Publisher OIDC (split):** Prod **`.github/workflows/publish.yml`** = PyPI, env `pypi`, `push: tags ['v*.*.*', '!v*.*.*-*']` (final SemVer only, excludes pre-release) + job `if: !contains(github.ref, '-')`; TestPyPI **`.github/workflows/publish-testpypi.yml`** = env `testpypi`, `push: tags ['v*.*.*-rc*']` (rc only). Both via `pypa/gh-action-pypi-publish@release/v1` (`id-token: write`, no token). **Maintainer action before M5:** TestPyPI Trusted-Publisher-Eintrag auf `publish-testpypi.yml` + `testpypi` umkonfigurieren (Prod-TP bleibt `publish.yml` + `pypi`). `v1.9.0-rc1` dry-run → TestPyPI (M5), then prod `v1.9.0` → PyPI (M6). `hatchling` builds wheel+sdist. Local validation `pip install --index-url https://test.pypi.org/simple/ astra-pipeline==1.9.0rc1 && astra --help` must be green before final tag.
