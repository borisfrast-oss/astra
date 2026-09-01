# Quickstart

> Auto-generated — Template + `astra init --help`

Welcome to Astra! This guide gets you to your first stacked image in 5 minutes.

## Installation

```bash
pip install -e .
astra --help
```

## Top-level commands

| Command | Description |
| --- | --- |
| `batch` | Process all subdirectories in the data root. |
| `config` | Manage configuration (precedence: CLI > Config > Env > Default). |
| `darks` | Manage the Darks Library (sync/list/check/import). |
| `doctor` | Environment check: Python, dependencies, GAIA, config, disk, paths. |
| `init` | Initialize Astra configuration via an interactive wizard. The wizard |
| `inspect` | Inspect FITS headers in the target directory. Shows target info, |
| `merge` | Merge existing group stacks into a single FITS. Scans |
| `plugin` | Plugin management (v1.2, PL-C): pipeline-step plugins in the |
| `process` | Process a single target directory. The global --config/-c option must |
| `status` | Show system status (disk space, recent runs, darks library, config |
| `target` | Target management (list/add/show/update/remove). |

## First run

1. Run `astra init` (wizard: Data Root, Darks Library, Preset, Cosmetic).
2. Add a target: `astra target add M13 --preset star_standard`.
3. Pre-flight: `astra process M13 --preflight` (Hot Pixel, Darks, Cosmetic).
4. Pipeline: `astra process C:/Astra/M13 --preset star_standard`.
5. Check result in `C:/Astra/M13/generated/<ts>/merged/`.
6. Status: `astra status --json`.
