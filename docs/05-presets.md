# Presets

> Auto-generated from `config.yaml` `pipeline_presets`

---

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

| Param | Value |
| --- | --- |
| rejection | winsorized |
| normalization | mul |
| weight | noise |
| stretch_method | asinh |
| stretch_factor | 0.15 |

## nebula_standard

**Target Types:** nebula, emission_nebula, reflection_nebula, dark_nebula, planetary_nebula

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

| Param | Value |
| --- | --- |
| rejection | winsorized |
| normalization | mul |
| weight | noise |
| stretch_method | asinh |
| stretch_factor | 0.12 |

## star_standard

**Target Types:** star, star_cluster, globular_cluster, open_cluster

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

| Param | Value |
| --- | --- |
| rejection | winsorized |
| normalization | add |
| weight | none |
| stretch_method | histogram |
| stretch_factor | 0.1 |

## nebula_narrowband

**Target Types:** nebula_sh2, nebula_hoo, nebula_sh

| Step | Params |
| --- | --- |
| create_master_dark | - |
| calibrate_lights | - |
| register_frames | - |
| stack_frames_per_channel | - |
| channel_combination | - |
| gradient_removal | - |
| stretch | - |
| export | - |

| Param | Value |
| --- | --- |
| rejection | winsorized |
| normalization | mul |
| weight | noise |

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
