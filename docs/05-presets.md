# Presets

> Auto-generated from `config.yaml` `pipeline_presets`

---

**Choosing a preset?** Run `astra suggest <TARGET>` to get offline recommendations based on object type (galaxy/nebula/star) from the handbook and target-cache. See Handbook Ch. 17 and `03-cli-reference.md suggest` for details.

## galaxy_standard

**Target Types:** galaxy

| Step | Params |
| --- | --- |
| create_master_dark | - |
| calibrate_lights | - |
| register_frames | - |
| stack_frames | - |
| background_extraction | - |
| photometric_color_calibration | - |
| scnr | - |
| stretch | - |
| export | - |

## nebula_standard

**Target Types:** nebula

| Step | Params |
| --- | --- |
| create_master_dark | - |
| calibrate_lights | - |
| register_frames | - |
| stack_frames | - |
| gradient_removal | - |
| background_extraction | - |
| structure_enhancement | - |
| stretch | - |
| export | - |

## star_standard

**Target Types:** star

| Step | Params |
| --- | --- |
| create_master_dark | - |
| calibrate_lights | - |
| register_frames | - |
| stack_frames | - |
| natural_color_processing | - |
| scnr | - |
| stretch | - |
| export | - |

## PCC Flag — Use Cases (V19-PCC-FLAG)

PCC = Photometric Color Calibration (star detection + GAIA/VizieR matching + gray_world fallback). Timeout 30 s × retry can accumulate to 6 min on star-poor fields (M31). CLI `--pcc/--no-pcc` (default `None` = Preset/Config wins, no breaking change) mutates preset steps in-memory (see `03-cli-reference.md`). Precedence: **CLI `--pcc/--no-pcc` > Config `pcc.enabled` > Preset Steps > Default**.

| Use Case | Command | Effect |
| --- | --- | --- |
| Galaxy (M31), PCC skip (fast, avoid timeout) | `astra process M31 --preset galaxy_standard --no-pcc` | Removes `photometric_color_calibration` — fast, no 6 min GAIA block |
| Nebula, force PCC | `astra process M42 --preset nebula_standard --pcc` | Inserts PCC after `background_extraction` (exactly once) |
| Star cluster, force PCC | `astra process M45 --preset star_standard --pcc` | Same insertion — `star_standard` has none by default |
| Nebula default (preset has none, no flag) | `astra process M42 --preset nebula_standard` | No PCC (Preset wins) |
| Galaxy default (preset has PCC, no flag) | `astra process M31 --preset galaxy_standard` | PCC runs (Preset wins) |
| Config fallback | `pcc.enabled: true/false` in `config.yaml` (no CLI) | Overrides Preset when CLI `None` (checked via `model_fields_set`) |

## `--pcc-per-group` Interaction

`--pcc-per-group/--no-pcc-per-group` (default `None` → `false` = PCC on merged stack for max S/N) is **independent** of `--pcc/--no-pcc` (which turns PCC on/off). Both flags compose:

| `--pcc` | `--pcc-per-group` | Behavior |
| --- | --- | --- |
| `--pcc` | `--pcc-per-group` | PCC runs per group (each `group_*/04_stacked/pcc_applied.fits`) *before* merge — less S/N per group, more groups |
| `--pcc` | `--no-pcc-per-group` (default) | PCC runs **once on merged stack** (default, max S/N) |
| `--no-pcc` | either | No PCC at all (per-group flag is moot) |
| `None` + `pcc.enabled`** | either | Config `pcc.enabled` decides on/off; `--pcc-per-group` decides where |

Insertion log: `pcc.cli_override` (`enabled`, `preset`, `inserted_after`=`background_extraction`/`stack_frames`/`stack_frames_fallback` or `removed`). Mutation is `copy.deepcopy` per call, never persisted to `config.yaml`.
