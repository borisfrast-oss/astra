# Quickstart

> Auto-generated from `astra init --help`, `astra download-example --help`, `astra doctor --help`

Welcome to Astra! This guide gets you to your first stacked image using **real data** (M31 Andromeda).

## Installation

```bash
pip install -e .
astra --help
```

## Documentation location

Docs and handbook ship inside the wheel (run `pip show -f astra-pipeline` to locate `astro_process/docs/` with 12 files and `astro_process/handbook/` with 38 files), and are also available on GitHub: [github.com/borisfrast-oss/astra/blob/main/docs/](https://github.com/borisfrast-oss/astra/blob/main/docs/). This means you don't need to clone the repository — just start with this guide.

## Prerequisites check (recommended)

Before your first run, verify your environment:

```bash
astra doctor
```

Exit codes: 0 = OK, 1 = warnings, 2 = critical errors. Read-only — no files created.

## Fastest path: Real data example (M31 Andromeda)

Download 10 real M31 light frames (90s, Gain 40, Astro filter) and process them:

```bash
# 1. Download example dataset (idempotent, skips if exists)
astra download-example M31 --n 10
#    -> Extracts to C:/Astra/M31 Andromeda/lights/group_90s40_astro/ + suggested.yaml

# 2. Dry-run to verify pipeline plan (smoke test with 5 frames)
astra process "C:/Astra/M31 Andromeda" --from-suggested "C:/Astra/M31 Andromeda/suggested.yaml" --limit 5 --dry-run
#    -> discovery.limit_applied 90s40_astro original=10 selected=5 + smoke_mode true

# 3. Full run (all 10 frames)
astra process "C:/Astra/M31 Andromeda" --from-suggested "C:/Astra/M31 Andromeda/suggested.yaml"
```

Result: Stacked image in `C:/Astra/M31 Andromeda/generated/<timestamp>/merged/`

## Alternative: Your own data

1. Run `astra init` (interactive wizard: Data Root, Darks Library, Preset, Cosmetic).
2. Copy your light frames to `C:/Astra/YourTarget/lights/`.
3. Organize lights: `astra organize "C:/Astra/YourTarget"` (groups by EXPTIME/GAIN/FILTER/EQMODE from FITS headers).
4. Suggest registration & processing: `astra suggest YourTarget --header <path/to/light.fits>` (creates `suggested.yaml` from FITS header).
5. Process: `astra process "C:/Astra/YourTarget" --from-suggested` (reads from default `YourTarget/suggested.yaml`).
6. Check result in `C:/Astra/YourTarget/generated/<timestamp>/merged/`.

## Handbook orientation

You don't need the handbook for your first run — `suggest` picks preset and registration automatically. If you want to plan a custom session or have questions after your first processing run:

- **Decision Tree:** Handbook chapter **22** (object-type-agnostic decision flow)
- **Object-specific guides:** Handbook chapters **05** (Galaxies), **08** (Planetary Nebulae), **16** (Dark Nebulae) — pick the one matching your target
- **Troubleshooting:** Handbook chapter **35** if something doesn't look right

Start with the Decision Tree, then jump to your object type.

## Top-level commands (complete)

| Command | Description |
| --- | --- |
| `batch` | Process all subdirectories in data root. |
| `config` | Manage configuration (precedence: CLI > Config > Env > Default). |
| `darks` | Manage the Darks Library (sync/list/check/import). |
| `doctor` | Environment check: Python, dependencies, GAIA, config, disk, paths. Read-only. |
| `download-example` | Download a real-data example (10 M31 FITS as GitHub Release asset). |
| `init` | Initialize Astra configuration (Wizard). |
| `inspect` | Inspect FITS headers in target directory. |
| `merge` | Merge existing group stacks into a single FITS. |
| `organize` | Organize flat lights in C:\Astra\<Target>\lights\ into group folders. |
| `plugin` | Plugin management (v1.2, PL-C): pipeline-step plugins in the |
| `process` | Process a single target directory. |
| `qc` | Quality checker: measures flip/ghosting/color from generated/<ts>/. |
| `status` | Show system status (disk space, recent runs, darks library, config health, queue). |
| `suggest` | Suggest a preset/registration/debayer/PCC combination for TARGET. |
| `target` | Target management (list/add/show/update/remove). |

## Common flags for `astra process`

| Flag | Purpose |
| --- | --- |
| `--from-suggested` | Use suggested.yaml (preset + processing_params) — reads from default `<Target>/suggested.yaml` or explicit `PATH` |
| `--preset NAME` | Processing preset (e.g. `galaxy_standard`, `nebula_standard`, `star_standard`) |
| `--limit N` | Process only first N frames per group (smoke test) |
| `--dry-run` | Show plan without executing (preflight) |
| `--preflight` | Hot pixel / darks / cosmetic check only |
| `--no-pcc` | Skip Photometric Color Calibration (avoids GAIA timeout) |
| `--registration-method METHOD` | Override: `fft` \| `astroalign` \| `rotation_fft` — use `astroalign` for AZ mounts (install optional extra: `pip install "astra-pipeline[astroalign]"` |
| `--config PATH` | Global option, must precede subcommand: `astra --config config.yaml process ...` |

## Quality check

After processing, verify image quality:

```bash
# Check latest run
astra qc --latest
#    -> Reports flip, ghosting, and color balance from generated/<ts>/merged/
```

## Troubleshooting

- `astra doctor` shows warnings/errors — fix those first.
- `astra download-example` fails: check internet / GitHub rate limit; falls back to local copy if available.
- `astra process` stuck on PCC: use `--no-pcc` (GAIA timeout), or check `astra doctor` for GAIA connectivity.
- Ghosting/double stars at edges: AZ mount with long exposure — use `--registration-method astroalign --max-rotation 15` (or install optional extra: `pip install "astra-pipeline[astroalign]"`)
- No darks found: `astra darks check "C:/Astra/Target"` — sync library with `astra darks sync`.
- Logs: `C:/Astra/Target/generated/<timestamp>/astra.log` (structured JSON).

## Minimal Quickstart — 5 steps (≈5 minutes, no other docs needed)

**Getting your first stack:**

```bash
① pip install astra-pipeline
   # Optional for AZ/drift: pip install "astra-pipeline[astroalign]"

② astra doctor
   # Exit code 1 = warnings (OK), 2 = critical errors (fix first)

③ astra download-example M31
   # Or: astra init → copy lights → astra organize <target> → astra suggest <target> --header <light.fits>

④ astra process "C:/Astra/M31" --from-suggested --limit 5
   # Or: astra process "C:/Astra/YourTarget" --from-suggested

⑤ astra qc --latest
   # Result in C:/Astra/*/generated/<timestamp>/merged/
```

**You don't need to read anything else for your first run.** After processing:

- **Got errors?** → See `11-troubleshooting.md`
- **Want to understand flags?** → See `03-cli-reference.md`
- **Ready to plan a custom session?** → See handbook chapter **22** (Decision Tree) + your object type chapter
