# Registration

> Extracted from `src/astro_process/core/registration.py` — structural reference with English summaries.

> V19-REG-SMART: Smart Default + Decision Matrix + Ghosting (rotation_deg 0.0)

---

Registration adapters — FFT, astroalign, and rotation-FFT strategies with fallback.

| Symbol | Kind | Description |
| --- | --- | --- |
| `AstroalignResult` | class | — |
| `AstroalignUnavailableError` | class | — |
| `RegistrationTransform` | class | — |
| `RegistrationSanityError` | class | — |
| `RegistrationStrategy` | class | — |
| `FftGridRegistration` | class | FFT phase-correlation registration strategy. |
| `AstroalignRegistration` | class | Astroalign-based registration strategy (optional extra). |
| `RotationFftRegistration` | class | Log-polar FFT rotation strategy for AZ field rotation. |
| `get_astroalign` | function | — |
| `astroalign_register` | function | — |
| `create_registration` | function | — |
| `apply_rotation_shift` | function | — |
| `RegisterFramesResult` | class | — |
| `RegistrationResult` | class | — |
| `register_frames` | function | Register frames with adaptive channel selection. |
| `compute_shift` | function | Sub-pixel shift via phase correlation with a Hanning window. |
| `corr_grid_shift` | function | Correlation-based coarse-to-fine shift search on high-pass filtered data. |
| `select_registration_channel` | function | Select the best monochrome channel for registration. |
| `compute_shift_star_centroid` | function | — |

## Decision Matrix (Mount | Exposure | Method | Reasoning)

Smart Default chooses the registration method without CLI flags. `fft` = translation-only (fast), `astroalign` = feature-based with rotation/scale (robust), `rotation_fft` = log-polar FFT rotation (fallback when `astroalign` extra missing).

| Mount | Exposure | Recommended Method | Reasoning |
| --- | --- | --- | --- |
| EQ (polar aligned) | < 120 s | `fft` | Fast, precise, no rotation — Phase Correlation sufficient |
| EQ | > 120 s | `astroalign` | Drift correction, larger shift/scale |
| AZ (Dwarf Mini, Seestar, AZ) | any | `astroalign` | Feature-based, corrects field rotation (Smart Default `dwarf_mini`) |
| AZ | 30–120 s | `astroalign` (`rotation_fft` fallback) | Log-Polar FFT less robust with few stars — `astroalign` is default, `rotation_fft` only if extra missing |
| Planetary / Lucky | < 1 s | `fft` | Hundreds of frames, speed critical, negligible rotation |
| Unknown / Auto | any | Auto-Detect | Header analysis `EQUAT`/`MOUNT`/`TELESCOP` → AZ/EQ, else `eq` + `discovery.mount_unknown` warning |

## Ghosting — why `rotation_deg 0.0` is a red flag

**Symptom:** Stack shows double-star contours at the image border, `frame 27: method fft rotation_deg 0.0 shift_y 31 shift_x -44`. **Root cause:** `cv2.phaseCorrelate` / `FftGridRegistration` measures only X/Y translation, no rotation. The shift is `rotation_deg: 0.0` by construction — the image is only shifted, edge stars drift circularly due to field rotation and double when stacked.

**Solution:** `astra process ... --registration-method astroalign --max-rotation 15` (or set Equipment profile `preferred_registration: astroalign`, `max_rotation_deg: 15`). For `dwarf_mini` the default is already `astroalign 15°` — no flag needed. Warning `registration.fft_on_az_mount` is emitted when `fft` + `az` + `exptime >= 45 s` (threshold `max_exptime_fft_warn: 45`):

```text
WARN registration.fft_on_az_mount method=fft mount_type=az exptime=60 threshold=45
     detail="FFT on AZ with 60s — field rotation not correctable. Expected: Ghosting at borders.
     Solution: --registration-method astroalign --max-rotation 15
     or Equipment profile with preferred_registration: astroalign"
```

## Auto-Detect — Headers `EQUAT` / `MOUNT` / `TELESCOP`

```python
AZ_DEVICES = ["DWARF MINI", "DWARF II", "SEESTAR", "ZWO ASIAIR", "SMARTTELESCOPE"]

def detect_mount_type(header):
    equat = str(header.get("EQUAT","")).upper()   # AZ / ALTAZ / ALT-AZ → az
    mount = str(header.get("MOUNT","")).upper()   # same
    telescop = str(header.get("TELESCOP","")).upper()  # DWARF MINI → az
    # fallback: header without mount → eq + WARN discovery.mount_unknown
```

`detect_preferred_registration(header, exptimes)` (in `core/equipment.py` or `agents/discovery.py`): AZ → always `astroalign` (exptime 30/60 thresholds collapsed to `astroalign` per OQ-REG-1, `rotation_fft` only as explicit `preferred_registration` or when `astroalign` extra missing). EQ → `fft` if `max_exptime <= 120`, else `astroalign`. Threshold `max_exptime_fft_warn` per profile (default 45 s, `dwarf_mini: 45`).

## Priority Chain — `resolve_registration_config`

Precedence (highest wins): **1. CLI `--registration-method` / `--max-rotation` > 2. Equipment Profile (`mount_type`, `preferred_registration`, `max_rotation_deg`, `max_exptime_fft_warn`) > 3. Auto-Detect (`EQUAT`/`MOUNT`/`TELESCOP`, header + exptimes) > 4. Config Default (`config.yaml registration.method`) > 5. hardcoded `fft` (2.0° default).** CLI always wins. Implemented as new `resolve_registration_config(cfg, equipment, header, exptimes, cli_method)` extending (not replacing) existing `resolve_registration(cfg, pipeline, ...)` — avoids signature collision.

```yaml
# equipment_profiles in config.yaml
- name: "dwarf_mini"
  mount_type: "az"
  preferred_registration: "astroalign"
  max_rotation_deg: 15
  max_exptime_fft_warn: 45
- name: "dwarf3"
  deprecated: true
  alias_for: "dwarf_mini"  # WARN equipment.profile_deprecated
```

## Multi-Group — per group + Cross-Group always astroalign

`resolve_group_registration_configs(cfg, groups, cli_override, global_equipment)` resolves the registration config for each group individually: header + exptimes per `group_*/` → per-group `mount_type`/`method` via the same Priority Chain. Logged as `multi_group.group_registration_config` (`group`, `method`, `mount_type`, `max_exptime`).

**Cross-Group Registration (Merge Phase) always `astroalign 20°` (`max_scale_dev 0.05`)** — independent of intra-group method. Rationale: large rotation/shift across nights / meridian flip / mount mix; intra-group = small dither shifts, cross-group = large offsets → separate configs. Optional `config.yaml`: `multi_group.registration.intra_group: auto` + `cross_group: astroalign` (not yet enforced, convention).

```python
cross_group_config = {"method": "astroalign", "max_rotation_deg": 20.0, "max_scale_dev": 0.05}
```

Example: 2 groups (AZ 60 s + EQ 30 s, `cli_override=None`) → `{"group_az": {"method":"astroalign"}, "group_eq": {"method":"fft"}}`, both `logger.info multi_group.group_registration_config`.
