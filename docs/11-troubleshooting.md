# Troubleshooting

> Auto-generated from `doc_data/troubleshooting.md`, `src/astro_process/cli.py` exit codes, and `doc_data/releases_summary.md`.

---

# Troubleshooting

## Error codes and common log messages

| Symptom / exit code | Meaning | What to do |
|---------------------|---------|------------|
| `EXIT 2` — "No light frames" | The target contains no usable light frames. | Check the target folder, ensure `lights/` exists and contains valid FITS files; run `astra inspect <target>`. |
| "No dark path set" / calibration abort | `darks_repository` is missing and no `--darks-path` was given. | Set `darks_repository` in `config.yaml` or pass `--darks-path C:/Astra/_darks`. |
| `GAIA not reachable` / `pcc.gaia_timeout` | GAIA TAP query timed out after retries. | PCC falls back to VizieR, then to gray-world; check `astra doctor` for network status. |
| `Disk < 1 GB` | `astra doctor` reports insufficient disk space. | Free space on `data_root` or change the data root. |
| `Mandatory-Validation ERROR` | Required FITS header fields are missing. | Run `astra inspect <target> --frames` to see missing headers. |

## Known limitations

- **Rotation FFT refinement radius** is fixed to ±0.75° around the coarse
  angle. Noisy or star-poor fields can fall outside this window; the
  sanity guard (`max_rotation_deg=2.0°`) falls back to FFT/zero-shift.
- **rotation_fft takes 20–60 s once** per cross-group pair. This is a
  one-time cost per run, acceptable for overnight batch processing.
- **Bilinear debayer** can show moire, ringing, and false color. It is an
  opt-in alternative; **superpixel** remains the default and recommended
  method for visual end products.
- **PCC few_stars**: fewer than five detected stars causes catalog matching
  to skip. Narrow fields may fall back to gray-world.
- **GAIA timeout** on slow or unreachable TAP service: retry with exponential
  backoff (30/60/90 s), then VizieR, then the configured fallback.

## Known issues (v1.9) — transparent, minimal

v1.9 is the 0€ PyPI-only community release (15–17d). Heavier distribution targets are intentionally deferred — the following are **not bugs**, but documented limitations that still require attention:

| Issue | Status | Detail / workaround |
|-------|--------|---------------------|
| `rotation_fft` not Auto-Default for AZ | Deferred (fallback only) | AZ Smart Default is `astroalign` (robust, flux-sorted RANSAC). `rotation_fft` (log-polar FFT) runs only when `astroalign` extra is missing or profile sets `preferred_registration: rotation_fft` explicitly (OQ-REG-1, V1.4-2 experiment — less robust on star-poor fields). Workaround: `astra process --registration-method rotation_fft`. |
| macOS / Python 3.12 CI | Deferred → v1.9.1 | Required CI `ubuntu-latest` + `windows-latest` × `python 3.11` only; macOS + 3.12 built manually / `continue-on-error` optional. Becomes required in v1.9.1. |
| Docker GHCR image | Deferred → v1.10 | No Docker in v1.9.0 (3–4d Multi-stage, <500 MB, org name). `pip install astra-pipeline==1.9.0` verified on Ubuntu+Win; Docker → v1.10. |
| PyInstaller Win `.exe` (unsigniert) | Deferred → v1.9.1 | No `.exe` in v1.9.0 (2–3d, ~60 MB scipy/numpy, AV false-positive). `sdist`+`wheel` via `hatchling` is sufficient; v1.9.1 adds unsigniert `.exe` + README SmartScreen hint ("More info → Run anyway"). |
| DCO Require signed commits | Deferred → v1.9.1 | Unsigned history preserved for `v1.9.0`; DCO enforcement (GitHub Settings → Require signed commits) after `v1.9.0` → v1.9.1. |

**Resolved in v1.8–v1.8.8 — previously known issues, now fixed (no longer present in v1.9):**

- **DEF-004 (Blocker, 2026-08-27, fixed 2026-08-29 — Luminanz-Hochpass `gaussian_filter σ=30` + `min_stars_cfa 3`)** — CFA-Drizzle Quality Gate rejected all 41 CFA frames (star detection on Bayer raw found <5 stars → `fwhm_median=None` → all outlier → 100% rejection → `min_frames_fallback` → no `01c_drizzle/`). Now subsumed by V1.9 CFA-Smart Defaults (`star_count 1` vs 20, `min_stars_cfa 1` when `is_cfa`, warning `cfa_drizzle.quality_gate_relaxed` when stricter).
- **DEF-005 (Major, fixed 2026-08-29)** — `min_frames_fallback` logged `fallback: malvar` but output stayed superpixel 960×540 (not materialized). Fixed: fallback correctly materialized (malvar + `stack_scale_factor 1.0`, resolution parity).
- **DEF-006 / V1.8-8 (Major, fixed 2026-08-29 — `star_standard` → `winsorized` + mandatory `corr_hp` gate `0.05`)** — Ghosting M92 3× (17 flagged outlier frames still averaged in `average` path, 8 with `corr_hp <0.01` catastrophically misregistered → double stars). Fixed: `outlier_excluded` respected + mandatory `corr_hp <0.05` auto-exclude (analog V1.4-20 `MergeConfig.min_correlation 0.1`). V1.9 keeps `rejection_min_corr_hp: 0.05` (configurable, `null` disables) in `config.yaml` / `processing_params`.

## Final FITS checks

The canonical final stack is written to `merged/<Target>_merged.fits`. Verify
that the header contains the expected metadata:

| Header key | Purpose |
|------------|---------|
| `XPIXSZ` / `YPIXSZ` | Effective pixel size after stack downscale. Default factor is `2.0` for the DWARF mini superpixel pipeline. |
| `FOCALLEN` | Focal length copied from light frames (best effort). |
| `FILTER` | Filter name; may be empty for unfiltered acquisitions. |
| `MGFRAME` | Number of frames contributing to the group stack. |

A `_preview.jpg` is produced alongside the FITS as an auto-stretched preview.

## PCC / GAIA gaps

If photometric color calibration fails, the pipeline follows a fallback chain:

1. GAIA DR3 (TAP) with three retries and exponential backoff.
2. VizieR secondary catalog (APASS DR9, then ATLAS Refcat2).
3. Configured fallback:
   - `auto` / `gray_world` → gray-world white balance.
   - `skip` → leave the frame unchanged.
   - `fail` → hard error.

Marker files in the group directory record the outcome:
`PCC_FALLBACK_GRAY_WORLD.txt`, `PCC_SKIPPED.txt`, `PCC_REJECTED_FACTORS.txt`.

## PCC Flag — use with `--pcc-per-group` (V19-PCC-FLAG)

- `--pcc/--no-pcc` (default `None` = Preset/Config wins) turns PCC **on/off**; `--pcc-per-group/--no-pcc-per-group` (default `None` → `false` = PCC on merged stack, max S/N) chooses **where** it runs. They compose: `--pcc --pcc-per-group` → PCC per `group_*/04_stacked/` (before merge, less S/N per group); `--pcc --no-pcc-per-group` (default) → PCC once on merged stack; `--no-pcc` → no PCC regardless of per-group flag. `config.yaml pcc.enabled: true/false` overrides Preset when CLI `None` (checked via `model_fields_set`); insert position `background_extraction → stack_frames → len-2` (exactly once, `copy.deepcopy` batch-safe, no file write, log `pcc.cli_override`).

See `03-cli-reference.md` (PCC Flag — Use Cases) + `05-presets.md` (PCC Flag — Use Cases) for full tables.

## Duo-Band light-pattern bug (v1.5 fix)

Earlier versions parsed only filenames containing `Astro`, so `Duo-Band`
lights were missed and temperature could not be extracted. The filename
regex now accepts `Astro|Duo-Band` (and is configurable). If you maintain
legacy scripts that build filenames, ensure the filter token is present so
metadata extraction works.

## Registration Ghosting (V19-REG-SMART) — quick debug

AZ + `fft` + `exptime >= 45 s` → `WARN registration.fft_on_az_mount` + Ghosting at borders (`rotation_deg 0.0` — FFT measures only translation, no rotation). Fix: `astra process --registration-method astroalign --max-rotation 15` (or Equipment profile `dwarf_mini` — no flag needed). Header analysis `EQUAT`/`MOUNT`/`TELESCOP` → AZ (`DWARF MINI`, `SEESTAR`), else `eq` + `WARN discovery.mount_unknown`. Priority Chain **CLI > Profile > Auto-Detect > Config Default > hardcoded `fft`** (`resolve_registration_config`). Cross-Group always `astroalign 20°`, logged per group `multi_group.group_registration_config`. See `07-registration.md` (Decision Matrix + Ghosting).

## CFA-Drizzle Quality Gate — hidden flags (advanced, not in Quickstart)

CFA-Drizzle (V1.8-1) runs on Bayer CFA raw (1 channel, 25% pixels/color) with
different statistics than debayered RGB. The auto gate selects **CFA-Smart-Defaults**
vs. **Debayered-Defaults** without config edit. Visible flags: `--cfa-drizzle-quality-gate`
/ `--no-cfa-drizzle-quality-gate` and `--cfa-drizzle-min-frames`. The following
are **hidden** (`hidden=True` in `cli.py`, not in `astra process --help` or
Quickstart, but documented here):

| Flag | Default (debayered) | CFA-Smart | Description |
|------|---------------------|-----------|-------------|
| `--cfa-drizzle-fallback` | `malvar` | `malvar` | Fallback debayer if gate fails / `min_frames` not met |
| `--cfa-drizzle-star-count-min` | `20` | `1` | Min `star_count` — Bayer needs 1-2, debayered 20+ |
| `--cfa-drizzle-snr-min` | `10` | `5` | Min `snr` — Bayer 5-8, debayered 10+ |
| `--cfa-drizzle-correlation-min` | `0.3` | `0.1` | Min `correlation` — Bayer 0.1-0.4, debayered 0.3+ |
| `--cfa-drizzle-fwhm-range` | `1.5,5.0` | `1.0,8.0` | FWHM range `min,max` — Bayer PSF broader |

**Precedence:** **CLI > Config (`cfa_drizzle.quality_gate`) > CFA-Smart-Defaults > Debayered-Defaults**.
`mode: auto|cfa|debayered` (Default `auto` → CFA when `is_cfa=True`) forces the base.
Thresholds are merged **recursively** (`thresholds` dict), not shallow — setting `star_count`
keeps `correlation` at CFA `0.1`. Stricter user thresholds trigger `WARN cfa_drizzle.quality_gate_relaxed`
(warning, no silent override); user value still wins.

```yaml
cfa_drizzle:
  enabled: true
  quality_gate:
    mode: "auto"
    thresholds:
      star_count: [1, null]   # >1 triggers WARN if is_cfa, but still effective
```

## FAQ

- **Where is the final stack?** Always in `generated/<ts>/merged/`. A legacy
  top-level `<Target>_final.fits` may exist from programmatic API calls but
  the CLI no longer produces it.
- **Can I rerun merge without reprocessing?** Yes: `astra merge <target>`
  scans the latest `generated/<ts>/group_*/04_stacked/pcc_applied.fits` files.
- **How do I keep group working directories?** The default is to keep them.
  Pass `--no-keep-groups` to delete them after a successful merge.


## CLI exit codes (source-extracted)

| Exit code | Location |
| --- | --- |
| 0 | src/astro_process/cli.py:3177 |
| 0 | src/astro_process/cli.py:3181 |
| 0 | src/astro_process/cli.py:3186 |
| 1 | src/astro_process/cli.py:3159 |
| 2 | src/astro_process/cli.py:1213 |
| 2 | src/astro_process/cli.py:605 |

## Known issues reflected in releases


- FITS-SSOT adoption means calibration frames must supply EXPTIME and GAIN
  either in the header or via filename fallback; missing metadata is a hard
  error.
- Bilinear debayer can introduce moire/ringing/false color; super-pixel
  remains the default and recommended method.
- GAIA TAP timeouts in narrow-band or star-poor fields fall back to VizieR,
  then to gray-world or skip based on config.


**Small, transparent list — v1.9 intentionally 0€ PyPI-only, heavier targets deferred.**

- **rotation_fft not Auto-Default for AZ** — only Fallback. AZ Smart Default is `astroalign` (robust, flux-sorted RANSAC). `rotation_fft` (log-polar FFT) is only used when `astroalign` extra is missing or when the Equipment profile explicitly sets `preferred_registration: rotation_fft`. Reason (OQ-REG-1, V1.4-2 experiment): less robust on star-poor fields. Workaround: `astra process --registration-method rotation_fft` for explicit log-polar, or install `astra[astroalign]`.
- **macOS + Python 3.12 CI deferred** — CI required matrix is `Ubuntu+Win/3.11` only. macOS and 3.12 are built manually / via `continue-on-error` and become required in v1.9.1 (see `v19-deferred-concept.md`).
- **Docker / PyInstaller deferred** — No `.exe` (unsigniert, 60 MB scipy/numpy, AV false-positive) and no GHCR image in v1.9.0. `pip install astra-pipeline==1.9.0` on `ubuntu-latest` + `windows-latest` verified (TestPyPI smoke). Docker → v1.10 (3–4d), PyInstaller → v1.9.1 (2–3d, unsigniert + README SmartScreen "More info → Run anyway").
- **DCO (signed commits) deferred** — unsigned project history preserved; `DCO Require signed commits` after `v1.9.0` (GitHub Settings) → v1.9.1 plus RTD/Lock/Scanning → v1.10.

**Fixed in v1.8–v1.8.8 (formerly known issues, now resolved — no longer present in v1.9):**

- **DEF-004 (Blocker, resolved 2026-08-29)** — M92 41×CFA frames all rejected by overly strict Quality Gate (`fwhm_median=None` → 100% outlier → no `01c_drizzle/`). Fixed via Luminanz-Hochpass `gaussian_filter σ=30` + `min_stars_cfa 3`, now subsumed by V1.9 CFA-Smart Defaults (`star_count 1`, `min_stars_cfa 1` when `is_cfa`) + warning.
- **DEF-005 (Major, resolved 2026-08-29)** — `min_frames_fallback` logged `fallback: malvar` but output stayed superpixel 960×540 (not materialized). Fixed: fallback materialized (malvar + `stack_scale_factor 1.0`).
- **DEF-006 / V1.8-8 (Major, resolved 2026-08-29)** — Ghosting M92 3× (8 catastrophically-registered frames with `corr_hp <0.01` averaged in `average` stacking despite flag). Fixed: `star_standard` `average` → `winsorized` + mandatory `corr_hp` gate `0.05` (`rejection_min_corr_hp`, analog V1.4-20) — V1.9 keeps this gate (configurable `0.05`, `null` disables).


