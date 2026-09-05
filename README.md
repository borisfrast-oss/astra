# Astra — Agentic Astrophotography Processing Pipeline

Astra is an autonomous, **Python-native** astrophotography processing pipeline
built for the **DWARFLab Dwarf Mini** smart telescope. It processes raw FITS
frames through a series of specialized agents that handle calibration,
registration, stacking, and post-processing — entirely on your own machine.

In contrast to the official Dwarflab cloud, Astra runs **100% locally**
(offline-first): your data never leaves your computer, and you keep full
mathematical control over every step of your image data.

- **Platform-independent** — runs on Windows, macOS, and Linux
- **No external tools required** — no Siril, GraXpert, GIMP, or PixInsight
  installation needed; everything runs in Python
- **Deterministic & CI-testable** — every step is reproducible from raw FITS to
  final image

> **Disclaimer:** Astra is not affiliated with DwarfLab. DwarfLab is a trademark of its respective owner.

## Features

- **Automated Pipeline**: End-to-end processing from raw FITS to final images
- **Always Multi-Group Stacking**: Automatically groups light frames by exposure
  time, gain, and filter, processes each group independently, and merges them into
  a single calibrated result — in one command (Multi-Group is always active since
  v1.7; the old `--multi-group` flag is a deprecated no-op)
- **Debayering**: Super-Pixel (default), Bilinear, and Malvar2004 — high-quality
  demosaicing with configurable method
- **CFA-Drizzle (optional)**: Sub-pixel drizzle on CFA raws (Scale 2.0) for
  undersampled data, with Lanczos3 kernel and adaptive pixfrac
- **Photometric Color Calibration (PCC)**: GAIA DR3-based color calibration with
  gray-world fallback
- **Preview/Export-Pipeline**: Background neutralization → SCNR → asinh-stretch →
  saturation → JPG, each step optional and backward-compatible
- **Optional Asinh-Stretch FITS**: Additional display-stretched FITS (`_stretched`)
  for Lightroom/Photoshop users, alongside the canonical linear FITS
- **Quality Assessment**: Automated quality scoring and frame selection
- **Reproducibility**: Complete processing logs (`agent-log.yaml`) and intermediate
  products preserved
- **Rich CLI**: `astra init` wizard, `config`/`darks`/`target`/`status`/`doctor`
  subcommands, `--preflight`, `inspect` extensions

## Installation

```bash
# Users: install from PyPI
pip install astra-pipeline

# Contributors: editable install from source
pip install -e .
```

## Quick Start

```bash
# 1) Env setup (choose one — .env file is recommended, cross-platform)
cp .env.example .env   # edit ASTRA_DATA_ROOT, ASTRA_DARKS_REPOSITORY, GIMP_PATH
# Windows (PowerShell, persistent): [Environment]::SetEnvironmentVariable("ASTRA_DATA_ROOT","C:\Astra","User")
# Linux/macOS: export ASTRA_DATA_ROOT="$HOME/Astra"

# 2) Init (wizard or CI)
astra init                                    # interactive wizard
astra init --non-interactive                   # CI: reads .env / flags, no prompts, writes config.yaml with resolved paths
astra doctor                                  # checks env, config, disk; WARN doctor.env_missing if .env absent

# Process a single target (Multi-Group is always active)
astra process "C:\Astra\M13" --preset star_standard

# Galaxies: disable PCC (star-based color calibration) for better results
astra process "C:\Astra\M81" --preset galaxy_standard --no-pcc

# Dry run to see what would be done
astra process "C:\Astra\Target" --dry-run

# Process all targets in a directory
astra batch "C:\Astra"

# Inspect a target (read-only FITS analysis)
astra inspect "C:\Astra\M13" --quality
```

> Full quick-start guide: see [`docs/01-quickstart.md`](docs/01-quickstart.md).

## Documentation

Astra ships two documentation sets:

| Directory | Purpose |
|-----------|---------|
| **`docs/`** | **Pipeline documentation (SSOT)** — how to operate the pipeline. 12 files generated from source via `scripts/generate_docs.py`. Start with `docs/01-quickstart.md`. |
| **`handbook/`** | Dwarf mini + Siril **tutorial** — learn the astrophotography craft (Siril workflow, image acquisition). Not pipeline-operation docs. |

Key `docs/` files:

- `docs/02-pipeline-architecture.md` — 5 phases, agents, data model, working dirs
- `docs/03-cli-reference.md` — CLI reference (subcommands, flags, precedence)
- `docs/04-configuration.md` — layered config, fields, env vars
- `docs/06-multi-group.md` — Multi-Group stacking, cross-group, merge
- `docs/11-troubleshooting.md` — error codes, known limitations, FAQ

## Configuration

Configuration is layered (Precedence: **CLI > Config > Env > Default**):

1. Defaults (built-in, Pydantic-validated)
2. User config (`config.yaml`, created by `astra init`)
3. Environment variables
4. CLI overrides

```bash
astra config show            # show merged config
astra config show --json     # machine-readable
astra config set <key> <val> # set + validate
```

See `docs/04-configuration.md` for all options.

## Multi-Group Stacking

Astra automatically groups light frames by acquisition parameters
(`EXPTIME`, `GAIN`, `FILTER`), processes each group independently, then merges
the results into a single final image.

```bash
# Auto-detect groups, process each, merge into one result (default behaviour)
astra process "C:\Astra\M13" --preset star_standard

# Merge separately with configurable weighting
astra merge "C:\Astra\M13" --method weighted_average --weight-by frame_count
```

> The `--multi-group`/`--auto-group` flags are **deprecated no-ops** since v1.7
> (Multi-Group is always active) and emit a warning. See `docs/06-multi-group.md`.

## Pipeline Presets

| Preset | Target Types | Key Steps |
|--------|--------------|-----------|
| `galaxy_standard` | Galaxy | Dark → Calibrate → Register → Stack → BG Extraction → PCC → Stretch |
| `nebula_standard` | Nebula | + Gradient Removal, Structure Enhancement |
| `star_standard` | Star/Cluster | Natural color, no aggressive NR, no PCC |
| `nebula_narrowband` | SHO/Hubble | Per-channel processing, channel combination |

## Regenerating Docs

Docs in `docs/` are generated from source. Regenerate before releases:

```bash
python scripts/generate_docs.py all     # regenerate all 12 docs
python scripts/generate_docs.py check   # CI: fail if docs are outdated
# or: make docs && make check-docs
```

## Requirements

- Python 3.11+
- Optional: `astroquery` (GAIA PCC), `sep` (star detection), `colour-demosaicing`
  (bilinear/Malvar debayer)

> Astra is **Python-native** — no Siril, GIMP, or GraXpert installation required.

## Support the Project

Astra is free, open source, and runs **entirely offline** — it is ad-free and
never touches the cloud. Building the calibration, drizzle, and processing
algorithms takes a lot of time (and coffee). If Astra improves your astrophotos,
saves you from cloud dependence, or simply saves you time, a small contribution
would mean the world.

- [Sponsor on GitHub](https://github.com/sponsors/borisfrast-oss)

Thank you for your support — and clear skies!

## License

MIT License
