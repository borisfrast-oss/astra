# 22 – Siril Workflow Decision Tree

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Objective

This chapter serves as a practical decision guide:

**Which workflow do I use for which object?**

Not every object is processed the same way.

The most important decisions:

- Filter or no filter?
- short or long exposure?
- which calibration?
- which registration?
- which stack?
- which post-processing?

---

# 1. Basic Decision

After acquisition:

```

What am I photographing?
|
|
+----------------+
|                |
Deep Sky          Sun/Moon/Planet
|                |
|                |
Siril Deep Sky    Planetary Workflow

```

---

# 2. Deep Sky Decision Tree

```

Deep Sky Object

```
    |
    |
    +-- Galaxy?
    |
    +-- Nebula?
    |
    +-- Star cluster?
    |
    +-- Star field?
    |
    +-- Comet?
```

```

---

# 3. Galaxy Workflow

Examples:

- M31
- M33
- M51
- M81/M82

---

## Acquisition

```

Exposure:
120–180 seconds

Gain:
30–40

Lights:
100–300

```

---

## Filter

Standard:

```

No filter

```

---

Dual-band:

Only if:

- H-alpha regions are of interest

---

## Siril Workflow

```

Sequence

↓

Dark

↓

Flat optional

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma Stack

↓

Background Extraction

↓

PCC

↓

Green Noise Removal

↓

Stretch

```

---

## Special Processing

Important:

- Protect core
- Enhance outer regions

---

# 4. Emission Nebula Workflow

Examples:

- M42
- Heart Nebula
- Rosette Nebula
- North America Nebula

---

## Acquisition

```

Exposure:
120–180 seconds

Gain:
30–50

```

---

## Filter

Recommendation:

```

Dual-band

```

For:

- H-alpha
- OIII

---

## Siril Workflow

```

Sequence

↓

Dark

↓

Flat

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma Stack

↓

Background Extraction (careful)

↓

PCC

↓

Color correction

↓

Stretch

```

---

## Special Processing

Do not remove:

- Red H-alpha structures
- Blue/green OIII regions

---

# 5. Reflection Nebula Workflow

Examples:

- M45 Pleiades
- Iris Nebula

---

## Acquisition

```

Exposure:
60–180 seconds

Gain:
30–40

```

---

## Filter

Recommendation:

```

No filter

```

---

## Siril Workflow

```

Sequence

↓

Dark

↓

Flat

↓

Calibration

↓

Registration

↓

Stack

↓

Careful background extraction

↓

PCC

↓

Gentle stretch

```

---

## Special Processing

Important:

- Preserve blue
- Do not make background too dark

---

# 6. Star Cluster Workflow

Examples:

- M13
- M3
- M44

---

## Acquisition

```

Exposure:
30–120 seconds

Gain:
10–30

```

---

## Filter

```

No filter

```

---

## Siril Workflow

```

Calibration

↓

Deep Sky Registration

↓

Stack

↓

PCC

↓

Light color correction

↓

Stretch

```

---

## Special Processing

Important:

- Preserve star colors
- Do not enlarge stars

---

> **Note (V19):** For Duo-Band nebulae use `nebula_standard` (PCC off, SCNR on), not `star_standard` (otherwise pink, C19 R/G 1.6 — see Ch. 06/08).

# 7. Bright Stars / Double Stars Workflow

Examples:

- Arcturus
- Albireo
- Sirius

---

## Acquisition

```

Exposure:
0.5–10 seconds

Gain:
0–20

```

---

## Filter

```

No filter

```

---

## Siril Workflow

```

Sequence

↓

Registration

↓

Stack

↓

Light color correction

↓

Export

```

---

## Special Processing

Do not:

- Denoise heavily
- Sharpen heavily

---

# 8. Comet Workflow

---

Special feature:

Comet moves.

---

## Siril Workflow

Not just one stack.

Two variants:

---

## Star Stack

```

Align stars

↓

Stack

```

---

## Comet Stack

```

Comet registration

↓

Stack

```

---

Afterwards:

```

Combine in GIMP

```

---

# 9. Milky Way / Wide-Field Workflow

---

## Acquisition

```

Exposure:
10–60 seconds

Gain:
20–40

```

---

## Siril Workflow

```

Sequence

↓

Calibration

↓

Registration

↓

Stack

↓

Background Extraction

↓

PCC

↓

Stretch

```

---

Special feature:

Foreground may be processed separately.

---

# 10. Moon Workflow

Not deep sky.

---

## Acquisition

```

Very short exposure

Many frames

```

---

## Goal

- Sharpness
- Details
- Craters

---

Workflow:

```

Select best images

↓

Stack

↓

Sharpening

↓

Contrast

```

---

# 11. Planetary Workflow

Examples:

- Jupiter
- Saturn
- Mars

---

Not:

Classic deep sky stacking.

---

Workflow:

```

Record video

↓

Select best frames

↓

Stack

↓

Sharpen

↓

Color correction

```

---

# 12. Filter Decision

```

Which filter?
|
|
+-- Emission nebula?
|       |
|       +-- Dual-band possible
|
+-- Galaxy?
|       |
|       +-- No filter
|
+-- Star cluster?
|       |
|       +-- No filter
|
+-- Reflection nebula?
|
+-- No filter

```

---


| Mount | Method | max_rotation | Source |
|-------|---------|--------------|--------|
| AZ (EQMODE 0) | astroalign | 30° | V19 REG-SMART auto |
| EQ (1) | fft | 2° (default) | — |

# 13. Calibration Decision

```

Do I need flats?
|
|
+-- Heavy processing?
|       |
|       +-- YES
|
+-- Dwarf vignetting visible?
|
+-- YES

```

---

Recommendation:

| Object | Dark | Flat |
|---|---|---|
| Galaxy | Yes | Yes |
| Emission nebula | Yes | Yes |
| Reflection nebula | Yes | Yes |
| Star cluster | Yes | Optional |
| Stars | Optional | No |
| Moon | No | No |

---

# 14. Stack Decision

Standard:

```

Winsor Sigma

```

---

Exceptions:

## Few Images

```

Median

```

---

## Very Clean Data

```

Average

```

---

## Satellites / Aircraft

```

Winsor Sigma

```

---

# 15. Problem-Oriented Decisions

## Image Too Green

Order:

```

PCC

↓

Green Noise Removal

↓

Color correction

```

---

## Background Too Bright

Check:

```

Reduce stretch

↓

Background Extraction

↓

Check black point

```

---

## Nebula Disappears

Check:

```

GraXpert too strong?

↓

Stretch too aggressive?

↓

Denoising too strong?

```

---

## Stars Too Large

Check:

```

Reduce exposure

↓

Reduce stretch

↓

Star processing

```

---

# 16. Universal Dwarf Standard Workflow

When in doubt:

```

Create sequence

↓

Calibrate dark

↓

Apply flat

↓

Deep Sky Registration

↓

Winsor Sigma Stack

↓

Background Extraction

↓

PCC

↓

Green Noise Removal

↓

Asinh Stretch

↓

TIFF Export

↓

GIMP

---

# 16.5 Cross-Group Rotation Thresholds

When stacking multiple acquisition groups with the Target Advisor, **dithering** and **tracking drift** can introduce rotation misalignment. Understanding these thresholds prevents unexpected single-stack fallbacks.

**Key observations:**
- **Dithering <4°:** Normal variation expected; QC-gate typically passes.
- **Cross-group rotation >2–3°:** QC-gate applies exclusion; group is rejected for multi-group merge.
- **Persistent >30° rotation:** Indicates AZ tracking drift or severe dithering; consider separate processing runs.

**Design principle:** Merging groups with misaligned rotations degrades image quality. Single-stack fallback is **not a defect** — it's a quality-preserving design choice. With dithered acquisition data, achieving ~50% merge success rate is normal.

For details on rotation thresholds per mount type (AZ vs. EQ), see Handbook 22 §3 (Registration), and refer to `astra-v1.10-target-advisor-testanalysis.md` (Gate 2026-09-04, Proposal P-01).

---

# 17. Astra Pipeline (v1.10) vs Siril Workflow — Target Advisor

Astra includes **`astra suggest`**, an offline-first advisor that reads a target's properties (FITS header, target-cache, or SIMBAD) and recommends processing parameters. This section explains the workflow and integration with `astra process`.

### 17.1 The `astra suggest` Command

Purpose: Help users choose the right preset and registration method without reading multiple handbook chapters.

**Basic usage:**

```bash
astra suggest <TARGET>                                      # Interactive — suggests 1–2 options
astra suggest M31 --header /path/to/light_001.fits         # Read filter/exposure from FITS header
astra suggest M27 --output C:/Astra/M27/suggested.yaml     # Write parameters to file
astra suggest C19 --json                                   # Machine-readable output (JSON)
astra suggest M31 --output --json                          # Both file and JSON
```

**Data sources (priority, offline-first):**

1. **FITS Header (highest priority, local):** `OBJECT`, `FILTER`, `TELESCOP`, `EXPTIME` read via `astropy.io.fits.getheader`. Allows suggest to detect dwarf mount type (az/eq) and filter characteristics (broadband/dual-band/narrowband).
2. **Target-Cache (stella-maintained):** ~30+ known objects in `knowledge-base/agents/stella/target-cache.md` with preset, handbook reference, and type (galaxy/nebula/planetary/globular/star/etc.). Offline cache eliminates SIMBAD lookup for common targets.
3. **SIMBAD webfetch (cache-miss only):** When target not in cache and internet available, suggest queries SIMBAD to determine object type. Offline or rate-limited? Returns cache-only advice and a warning (`WARN suggest.simbad_unavailable`), then exits 0.
4. **Handbook (SSOT, no hard-coded tree):** Suggest output cites Handbook chapters (§3 Galaxies / §4 Emission Nebula / §6 Star Clusters / §14 Stack Decision) as reasoning, not as code logic.

**Example output (stdout, human-readable):**

```
Target: M31 Andromeda (M31, NGC 224) — Galaxy, spiral (cache: galaxy_standard, Handbook 05-Galaxies.md + 22 §3)
Header: TELESCOP=DWARF MINI (az), FILTER=Dual-Band, EXPTIME=60s (via --header light_001.fits)
Source: cache hit (knowledge-base/agents/stella/target-cache.md) — SIMBAD not queried (offline-first)

1) galaxy_standard + astroalign 30° (AZ, dwarf_mini)  [RECOMMENDED]
   Why: Handbook 22 §3 Galaxies + target-cache galaxy → galaxy_standard; AZ + 60s → astroalign 15-30° (V19-REG-SMART, fft would ghost); Duo-Band → PCC recommended
   CLI: astra process "C:/Astra/M31 Andromeda" --preset galaxy_standard --registration-method astroalign --max-rotation 30 --debayer-method superpixel --pcc
   Debayer: superpixel 960×540 fast (default), malvar 1920×1080 HQ alternative (no moiré), cfa-drizzle 3840×2160 if >50 dithered frames
   Darks: run `astra darks check "C:/Astra/M31 Andromeda"` for coverage (V19-DARKS-SYNC)

2) galaxy_standard + fft 2° (EQ fallback)  [if mount was EQ]
   Why: Handbook 22 §3 — EQ + short exposure → fft fast
   CLI: astra process "C:/Astra/M31 Andromeda" --preset galaxy_standard --registration-method fft --max-rotation 2 --pcc

Refs: Handbook 22-Siril-Workflow-Decision-Tree §3 + Ch. 17, astra/docs/05-presets.md, 07-registration.md
```

### 17.2 Suggested Parameters File Format

`suggest` can save recommendations to a YAML/JSON file (default location: `C:\Astra\<Target>\suggested.yaml`, the Target-Root next to Lights).

**(v1.11+) Note:** If the target directory does not exist, `suggest` will **not** create it. Instead, it prints a hint: `ERROR suggest: target directory not found. Create it or use an existing target path. (Hint: astra target add <NAME>)`. This prevents ghost directories and enforces explicit target management via `astra target add` or manual folder creation.

**File structure (YAML, version 1):**

```yaml
version: 1
target: M31
simbad_name: M31
type: galaxy                                    # galaxy | nebula | planetary | globular | open_cluster | star | dark_nebula | snr
handbook_ref: "22 §3 Galaxies + 05-Galaxies.md"  # Chapters cited in suggest output
source: cache                                   # cache | header | simbad | handbook_fallback — where recommendation came from

preset: galaxy_standard                         # galaxy_standard | nebula_standard | star_standard | nebula_narrowband
registration:
  method: astroalign                            # fft | astroalign | rotation_fft
  max_rotation_deg: 30                          # 2 (EQ fft) | 15 (dwarf_mini) | 30 (generic AZ)

debayer:
  method: superpixel                            # superpixel (960×540 fast) | malvar (1920×1080 HQ) | cfa-drizzle (3840×2160, v19 auto)

pcc:
  enabled: true                                 # true → --pcc | false → --no-pcc | null → preset wins

# Optional hints (for documentation, not processed by pipeline):
equipment_hint: dwarf_mini                      # from TELESCOP header
filter_hint: Duo-Band                           # from FILTER header
exptime_hint: 60                                # from EXPTIME header (seconds)
```

**JSON variant (`suggested.json`):** Identical structure, JSON syntax.

### 17.3 Integration with `astra process`

**(v1.11+) Mandatory Workflow:**

Starting with v1.11 (ENTSCHLACKUNG — "de-cluttering"), `suggest` → `process` is the canonical path. The `suggest` command now **always** writes a suggested file (default: `C:\Astra\<Target>\suggested.yaml`), and `--from-suggested` is **required** to load it; process will **Exit 2** if `suggest` output exists and `--from-suggested` is not provided.

```bash
# v1.11 mandatory flow:
astra suggest M31                                  # always writes C:\Astra\M31\suggested.yaml
astra process "C:\Astra\M31" --from-suggested    # REQUIRED in v1.11; --from-suggested alone loads default file
# OR
astra process "C:\Astra\M31" --from-suggested "C:\Astra\M31\suggested.yaml"  # explicit path
```

**Legacy (pre-v1.11) compatibility:** If `--from-suggested` is omitted and no suggested file exists, process proceeds with defaults (backward compatible for users without a suggest run).

**Precedence (CLI wins over all, then file, then config/preset):**

```
CLI Flag (highest priority)
  > suggested File (--from-suggested)
    > Config (config.yaml profile/pcc settings)
      > Preset (pipeline_presets definition)
        > Hardcoded Default (fft, superpixel)
```

**Example with CLI override:**

```bash
# File says galaxy_standard + astroalign 30°, but user wants fft:
astra process "C:\Astra\M31" --from-suggested "C:\Astra\M31\suggested.yaml" \
  --registration-method fft --max-rotation 2
# Result: fft 2° used (CLI wins), other params from file (preset=galaxy_standard, debayer=superpixel, pcc=true)
```

**No auto-discover:** Suggested file in the target folder is **never** read automatically. User must explicitly pass `--from-suggested` to load it. This prevents surprise overrides when multiple suggest runs exist.

### 17.4 Debayer Method Guide

Three options with different speed/quality tradeoffs:

| Method | Resultion | Speed | Use Case |
|--------|-----------|-------|----------|
| **superpixel** (default) | 960×540 (2× binned) | Fast | Quick preview, small nebulae, all objects as default |
| **malvar** (Malvar2004) | 1920×1080 (full HQ) | Moderate | Galaxy details, high-contrast features, no moiré |
| **cfa-drizzle** | 3840×2160 (2× sub-pixel) | Slow, v19 auto | Only if quality gate passes + >50 dithered frames (V19-CFA-GATE) |

`suggest` recommends **superpixel** as default, **malvar** for galaxies with fine structure, and notes **cfa-drizzle** only after quality checks. Pipeline final choice is determined automatically if `auto` is selected.

### 17.5 PCC (Photometric Color Calibration)

- **galaxy_standard preset:** PCC enabled by default (`--pcc` recommended). Use dual-band filters to improve color balance.
- **nebula_standard / star_standard presets:** PCC disabled by default (`--no-pcc`). Enable only if color accuracy is critical.
- **CLI override:** `--pcc` or `--no-pcc` always wins over preset and config (v1.11: semantics clarified — `pcc: false` now disables PCC entirely instead of a no-op; `true` enables it).
- **Config/suggested.yaml:** When `pcc.enabled: false` in config or `pcc: false` in suggested.yaml, PCC is skipped entirely (no longer a harmless no-op).

See Handbook Chapter 22 §14 (PCC Decision) for when to apply PCC per object type.

### 17.6 Smoke Testing with `--limit`

(v1.11+) The `--limit` flag reduces the number of light frames per group for quick testing:

```bash
astra process "C:\Astra\M31" --limit 5    # Use first 5 lights per group; darks/flats/bias complete
```

**Behavior:**
- Only the first N light frames per group are processed; discovery phase still finds all groups
- Darks, bias, flats remain complete (proper calibration still works)
- Output marked with integrity metadata: `smoke_mode: true`, `limit: 5`, `frames_considered: N`, `frames_total: M`
- Quality assessment and resume guards are active
- Incompatible with `--resume` (use `--limit` for fresh smoke runs only)

**Use case:** Quick pipeline validation on large datasets before full run.

### 17.7 Dark Calibration

`suggest` **does not** manage dark frames. Instead, use:

```bash
astra darks check "C:\Astra\<Target>"  # verify dark coverage (see Handbook §13 Calibration Decision)
```

This command reports which (EXPTIME, GAIN, TEMP) combinations are covered by the darks library. See `knowledge-base/projects/astra/docs/darks-sync-rule.md` for the complete dark-sync workflow.

### 17.8 Configuration: Optional Cache Path

If running Astra offline with a local target-cache mirror, set the path in `config.yaml`:

```yaml
suggest:
  target_cache_path: "C:/path/to/target-cache.md"  # optional; if unset, every target is a cache miss
```

Without a local cache, every target triggers either a SIMBAD query (if online, 5s timeout) or generic fallback advice with a warning — no crash, always Exit 0 (AC-SUG-4). For development or offline scenarios with a slow/unavailable network, point to your local `target-cache.md` to skip SIMBAD entirely.

### 17.9 Workflow Summary

**Typical session (galaxy M31):**

```bash
# 1. Inspect what you have
astra inspect "C:\Astra\M31"                    # shows FITS headers

# 2. Get advice
astra suggest M31 --header "C:\Astra\M31\light_001.fits" --output  # writes suggested.yaml

# 3. Review recommendations and copy the CLI command from suggest output

# 4. Process with recommended preset
astra process "C:\Astra\M31" --preset galaxy_standard --registration-method astroalign --max-rotation 30 --pcc

# 5. Check darks coverage
astra darks check "C:\Astra\M31"

# Alternative: load from file instead of typing flags
astra process "C:\Astra\M31" --from-suggested "C:\Astra\M31\suggested.yaml"
```

### References

- **Handbook Chapter 22 (this file):** Decision trees for object type (§2-6, §12-14), calibration, stacking.
- **Handbook Chapters 05–09:** Galaxy / Emission Nebula / Planetary Nebula / Globular Cluster workflows (handbook_ref field in suggested.yaml).
- **Target-Cache:** `knowledge-base/agents/stella/target-cache.md` — 30+ known objects, SIMBAD names, presets.
- **CLI Reference:** `astra/docs/03-cli-reference.md` — full command syntax.
- **Presets Documentation:** `astra/docs/05-presets.md` — preset definitions and their steps.
- **Registration Methods:** `astra/docs/07-registration.md` — FFT vs astroalign tradeoffs.
- **Dark Calibration:** `knowledge-base/projects/astra/docs/darks-sync-rule.md` — dark frame management.
- **Config Schema:** `astra/docs/04-configuration.md` — all configuration options including `suggest.target_cache_path`.


```
