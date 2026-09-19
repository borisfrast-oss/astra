# Astra — Agentic Astrophotography Processing Pipeline

Astra is an autonomous, **Python-native** astrophotography processing pipeline.
It processes raw FITS frames through a series of specialized agents that handle
calibration, registration, stacking, and post-processing — entirely on your own
machine.

In contrast to the official Dwarflab cloud, Astra runs **locally** on your
machine (**offline-first**): your data never leaves your computer, and you keep
full mathematical control over every step of your image data. The pipeline
(Calibration → Debayer → Registration → Stacking → PCC → Export) runs fully
offline. Only SIMBAD queries for target metadata (on cache miss) need internet;
baked target cache covers common targets.

- **Device-independent** — designed around standard FITS headers (V1.6
  Device-Independence); validated on the **DWARFLab Dwarf Mini**. Feedback from
  other devices (e.g. Dwarf 3, Seestar) welcome via
  [GitHub Issues](https://github.com/borisfrast-oss/astra/issues).
- **Platform-independent** — runs on Windows, macOS, and Linux
- **No external tools required** — no Siril, GraXpert, GIMP, or PixInsight
  installation needed; everything runs in Python
- **Deterministic & CI-testable** — every step is reproducible from raw FITS to
  final image

> **Disclaimer:** Astra is not affiliated with DwarfLab. DwarfLab is a trademark of its respective owner.

## Project Status

**Astra is in active development (Alpha).** Core functionality is stable and production-ready for astrophotography workflows, but features and behavior may change before v1.0 release. The CLI currently reports version 1.12.0 (current release). See [CHANGELOG.md](CHANGELOG.md#1120) for details.

## Features

- **Automated Pipeline**: End-to-end processing from raw FITS to final images
- **Always Multi-Group Stacking**: Automatically groups light frames by exposure
  time, gain, and filter, processes each group independently, and merges them into
  a single calibrated result — in one command (Multi-Group is always active since
  v1.7; the old `--multi-group` flag is a deprecated no-op)
- **Target Organization**: `astra organize` moves loose `lights/*.fits` into
  `lights/group_*/` (header-based, filter splitting) and `astra process --group`
  for selective group processing
- **Debayering**: Super-Pixel (default), Bilinear, and Malvar2004 — high-quality
  demosaicing with configurable method
- **CFA-Drizzle (optional, revived in 1.12)**: Sub-pixel drizzle on CFA raws (Scale
  2.0) for undersampled data, with Lanczos3 kernel, phase-based pixfrac and
  coverage diagnostics
- **Photometric Color Calibration (PCC)**: GAIA DR3-based color calibration with
  gray-world fallback
- **Preview/Export Pipeline**: Background neutralization → SCNR → asinh-stretch →
  saturation → JPG/TIFF, each step optional and backward-compatible
- **Preview Overhaul (v1.12)**: 16-bit TIFF is now the default preview (lossless,
  GIMP/Lightroom-ready), `--preview-format tiff|jpg` (CLI > Config > Default) and
  corrected vertical flip (right-side-up)
- **Optional Asinh-Stretch FITS**: Additional display-stretched FITS (`_stretched`)
  for Lightroom/Photoshop users, alongside the canonical linear FITS
- **Quality Checker**: `astra qc <generated>` validates flip, ghosting and color
  after processing (writes `qc_report.json`, exit codes 0/2/1)
- **Header & Platesolving**: Centralized header handling (SSOT) via `header_utils`,
  binning-aware drizzle scale 1.45 for correct platesolving
- **Quality Assessment**: Automated quality scoring and frame selection
- **Reproducibility**: Complete processing logs (`agent-log.yaml`) and intermediate
  products preserved
- **Rich CLI**: `astra init` wizard, `config`/`darks`/`target`/`status`/`doctor`
  subcommands, `--preflight`, `inspect` extensions, plus `suggest`/`organize`/`qc`

## Installation

```bash
# Users: install from PyPI (base, FFT registration)
pip install astra-pipeline

# With optional extras (astroalign, GraXpert, astrometry.net)
pip install "astra-pipeline[astroalign]"     # AZ mount support (Dwarf Mini, Seestar) — recommended
pip install "astra-pipeline[graxpert]"       # Background/gradient removal
pip install "astra-pipeline[astro]"          # Blind plate solving

# Contributors: editable install from source (includes all extras)
pip install -e ".[dev]"
```

The **structure_enhancement** plugin (v1.0.0) is included with all installations.

## Quick Start

```bash
# 1) Initialize configuration (interactive wizard or CI mode)
astra init                                    # interactive wizard: prompts for data root, darks library, preset
astra init --non-interactive                  # CI: reads env/flags, no prompts, writes config.yaml with resolved paths
astra doctor                                  # checks env, config, disk (read-only, no files created)

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

# Recommended workflow (v1.11+): astra suggest → astra organize → astra process --from-suggested [--group]; verify with astra qc
# e.g. astra suggest "C:\Astra\M13" && astra organize "C:\Astra\M13" && astra process "C:\Astra\M13" --from-suggested && astra qc "C:\Astra\M13\generated\<ts>"
```

> Full quick-start guide: see [`docs/01-quickstart.md`](docs/01-quickstart.md).

## Preview Images

Example images in the repository and documentation are **quick-look previews only**. They are asinh-stretched JPG exports, often generated from smoke-test runs with limited frames (and thus noisy). Colors may be uncalibrated (e.g., green cast without photometric calibration). These previews are intended to show processing capability, not final image products. For publication-quality results, use the canonical linear FITS output with your own post-processing workflow (Lightroom, Photoshop, Pixinsight, etc.).

## Documentation

Documentation is available both **shipped inside the wheel** and on GitHub:

| Source | Purpose |
|--------|---------|
| **Wheel (shipped with `pip install astra-pipeline`)** | `docs/` and `handbook/` are included in the installed package. Find them: `python -c "import astro_process; import os; print(os.path.dirname(astro_process.__file__))"` → locate `docs/` and `handbook/` subdirectories. Also accessible via `pip show -f astra-pipeline` and filtering for `docs/` and `handbook/` paths. |
| **[GitHub `docs/`](https://github.com/borisfrast-oss/astra/tree/main/docs)** | **Pipeline documentation (SSOT)** — how to operate the pipeline. 12 files generated from source via `scripts/generate_docs.py`. Start with [`docs/01-quickstart.md`](https://github.com/borisfrast-oss/astra/blob/main/docs/01-quickstart.md). |
| **[GitHub `handbook/`](https://github.com/borisfrast-oss/astra/tree/main/handbook)** | Dwarf mini + Siril **tutorial** — learn the astrophotography craft (Siril workflow, image acquisition). Not pipeline-operation docs. |

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

Astra is free, open source, and runs **offline-first** — the pipeline runs
entirely locally, only SIMBAD queries (on cache miss) need internet. It is ad-free and
never touches the cloud. Building the calibration, drizzle, and processing
algorithms takes a lot of time (and coffee). If Astra improves your astrophotos,
saves you from cloud dependence, or simply saves you time, a small contribution
would mean the world.

- [Sponsor on GitHub](https://github.com/sponsors/borisfrast-oss)

Thank you for your support — and clear skies!

## License

MIT License
