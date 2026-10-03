# Presets

> Auto-generated from `config.yaml` `pipeline_presets`

---

**Choosing a preset?** Run `astra suggest <TARGET>` to get offline recommendations based on object type (galaxy/nebula/star) from the handbook and target-cache. See Handbook Ch. 17 and `03-cli-reference.md suggest` for details.

## PCC Flag - Use Cases (V19-PCC-FLAG)

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

## M31 Mini-Example — Synthetic Wheel + Real Download (V1.12-STEP3)

Synthetic offline smoke + real-data reference for galaxy workflow (Handbook 05 §3/5 + 22 §3, `galaxy_standard`).

**Synthetic (Wheel, offline, <100 KB):** `astra/data/examples/M31` — 5 lights `lights/group_60s40_astro` 60s Gain 40 Filter Astro (32×32 superpixel, deterministic seed 42 via `tests/synthetic.py`, `OBJECT=M31` `EXPTIME=60` `GAIN=40` `FILTER=Astro`, `NAXIS 32×32`) + `suggested.yaml` `preset: galaxy_standard` (`handbook_ref: "22 §3 Galaxies + 05-Galaxies.md"`). Offline smoke: `astra process astra/data/examples/M31 --from-suggested astra/data/examples/M31/suggested.yaml --limit 5 --dry-run` → `discovery.limit_applied group_60s40_astro original=5 selected=5 limit=5` + `smoke_mode true` `frames_total=5` (V1.11-SUBSET `--limit 5` per-group, Darks/Bias/Flats complete, natural sort). Wheel: `hatch build --clean && tar tzf dist/*.whl | grep -E "examples/M31|suggested.yaml|target-cache.json"` — synthetic <100 KB (`du -sh astra/data/examples/M31` ~42 KiB), wheel ~409 KB (target-cache.json + examples). No hardcode: `grep -R "M31.*galaxy_standard" astra/src --include="*.py"` → 0 (`classify_and_cite` live, `Typ → Handbook → Preset`).

**Real (GitHub Release Asset, 10 FITS):** `astra download-example M31 --n 10` fetches 10 real M31 lights 90s Gain 40 Astro (1920×1080, `C:\Astra\M31 Andromeda\lights\group_90s40_astro` 45F source, first 10 natural sort, header `OBJECT=M31` `EXPTIME=90` `GAIN=40` `FILTER=Astro`) as `M31-example-10fits.tar.gz` (SHA256 manifest, idempotent skip unless `--force`, progress via `rich`, error Exit 2 `download.asset_not_found` on miss), extracts to `<output>/lights/group_90s40_astro/` + `<output>/suggested.yaml` (`galaxy_standard`, `Handbook 22 §3`). Fallback local copy when GitHub unreachable (offline). Example: `astra download-example M31 --n 10 --output C:/Astra/M31_B_test` (or default `C:/Astra/M31`), then Real-Gate: `astra process C:/Astra/M31_B_test --from-suggested C:/Astra/M31_B_test/suggested.yaml --limit 5 --dry-run` → `discovery.limit_applied 90s40_astro original=10 selected=5` + `smoke_mode true` `frames_total=10` `frames_considered=5` (proves pipeline without synthetic).

**Handbook refs:** 05 §3 (120–180s Gain 30–40, 60–120s for bright core, `M31 group_60s40_astro 5 synthetic smoke` + `M31 B 90s40 Astro 45F real`) + 05 §5 (30/50–100/150+ lights — 5 synthetic = **smoke only**, 50+ real needed → `download-example`) + 22 §3 Galaxy Workflow (No filter, Deep Sky Registration, Winsor Sigma, PCC) cites Mini-Example both paths + `--limit 5` gate. See `astra download-example --help` (EN §17) and `03-cli-reference.md` download-example.
