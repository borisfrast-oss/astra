# Astra Pipeline — Technical Documentation

> **Audience:** Users of the `astro_process` pipeline (CLI, config, presets, output).

> **Not here:** Astrophotography basics, Siril workflows, GIMP/GraXpert → see `../handbook/`.

---

## Document overview

The `docs/` folder contains the user-facing, auto-generated documentation for Astra.

| File | Topic |
| --- | --- |
| `01-quickstart.md` | Installation, first `astra process` run, dry-run |
| `02-pipeline-architecture.md` | Pipeline phases, agents, data model, working directories |
| `03-cli-reference.md` | All subcommands, flags, precedence, wizard |
| `04-configuration.md` | Layered config, `config.yaml`, env vars, `AppConfig` |
| `05-presets.md` | Presets, steps, `processing_params` |
| `06-multi-group.md` | Multi-group stacking, cross-group registration, merge |
| `07-registration.md` | Registration methods (fft/astroalign/rotation_fft), SanityGuard |
| `08-gradient-removal.md` | Gradient removal |
| `09-darks-library.md` | Darks library, `astra darks sync`, TELE/WIDE rule |
| `10-output-structure.md` | Output structure (`generated/`, `group_*`, `merged/`, logs) |
| `11-troubleshooting.md` | Troubleshooting (error codes, known limitations, FAQ) |
| `12-migration.md` | Migration (v1.1→v1.2→v1.3, breaking changes) |
| `INDEX.md` | Auto-generated navigation |

## handbook/ vs docs/

|  | `handbook/` | `docs/` |
| --- | --- | --- |
| **Focus** | Learn astrophotography & use Siril | Operate the `astro_process` pipeline |
| **Tools** | Dwarf3, Siril 1.4.4, GraXpert, GIMP | Python, `astra-process`, FITS, config |
| **Content** | 37 chapters: acquisition, calibration, stacking, object classes | 12 chapters: pipeline phases, CLI, config, presets, output |

Both folders are independent.

## Generation (for developers)

Contents are **not copied manually**; they are generated from source:

- `03-cli-reference.md` ← `src/astro_process/cli.py`
- `04-configuration.md` ← `src/astro_process/config/models.py` + `config.yaml`
- `05-presets.md` ← `config.yaml` `pipeline_presets`
- `02-pipeline-architecture.md` ← `src/astro_process/core/` module structure

```bash
# Generate all docs
python scripts/generate_docs.py all

# Individual generators
python scripts/generate_docs.py cli
python scripts/generate_docs.py config
python scripts/generate_docs.py presets
python scripts/generate_docs.py arch
python scripts/generate_docs.py index

# CI check: are docs up to date?
python scripts/generate_docs.py check
```

> **INDEX.md** and this README are auto-generated — **do not edit manually**. Run `python scripts/generate_docs.py all` after changes.
