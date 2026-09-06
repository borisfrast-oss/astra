# 04 – Siril 1.4.4 Reference

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Overview

This chapter describes the most important Siril 1.4.4 functions and parameters.

Goal:

- Understand which options matter
- Know default values
- Recognize sensible changes
- Avoid typical errors

Topics covered:

- Directory structure
- Sequences
- Conversion
- Calibration
- Registration
- Stacking
- Normalization
- Color calibration
- Stretching
- Export

---

# 1. Working Directory

Siril always works with a current working directory.

Recommendation:

```

Project/

├── lights/

├── darks/

├── flats/

├── bias/

└── output/

```

---

# 2. Sequences

A sequence is a group of images.

Example:

```

m31_light_00001.fits
m31_light_00002.fits
m31_light_00003.fits

```

becomes:

```

m31_light_.seq

```

---

# Important

The `.seq` file contains references to the images.

If FITS files are moved:

Problem:

```

Sequence points to old path

```

Result:

```

File not found

```

Typical message:

```

m31_light_00001.fits.[File extension] not found

```

Solution:

Regenerate sequence.

---

# 3. Sequence Tab

The sequence tab is for managing the loaded image series.

Typical tasks:

- Open sequence
- Select images
- Check quality
- Mark images

---

# Recommendations

Before processing check:

- Are all images loaded?
- Are stars visible?
- Are there any bad frames?
- Are file paths correct?

---

# 4. Conversion

## Purpose

Conversion creates Siril-compatible sequences.

Typical sequence:

```

FITS images

↓

Siril sequence

```

---

# Parameters

## Output Format

Recommendation:

```

FITS

```

---

## Force 32-bit

Standard:

Off

Recommendation:

Leave off.

Reason:

The Dwarf already provides suitable FITS data.

32-bit can be useful for:

- Extreme dynamic ranges
- Special scientific workflows

---

# RGB Weighting

Standard:

Off

Recommendation:

Off

Reason:

With OSC cameras Siril handles color processing.

Do not manually influence before PCC is applied.

---

# 5. Calibration

Calibration removes known sensor errors.

Sequence:

```

Lights

*

Master Dark

*

(optional)
Master Flat

↓

Calibrated lights

```

---

# Create Master Dark

Multiple darks are combined.

Example:

```

dark_001

dark_002

dark_003

↓

Master Dark

```

---

# Dark-Stack Parameters

## Method

Recommendation:

```

Median

```

Why:

- Removes random errors
- Preserves hot pixel structure

---

## Normalization

Standard:

Depends on dialog

Recommendation:

Use default value.

Reason:

Darks usually have constant conditions.

---

# Master Flat

Only use if flats are available.

Flats require:

- Same optics
- Same camera
- Same configuration

---

# 6. Registration

## Purpose

All images are aligned precisely.

Siril detects stars and calculates the transformation.

---

# Selection

For deep sky:

```

General Deep Sky

```

Use this.

Suitable for:

- Galaxies
- Nebulae
- Star fields

---

# Transformation

## Homography

Standard:

Active

Recommendation:

Use it.

Can correct:

- Shift
- Rotation
- Scaling
- Slight distortion

---

# Minimum Star Pairs

Standard:

10

Recommendation:

10

Only increase if problems.

Example:

If Siril uses wrong stars.

---

# Use Luminance

Standard:

Active

Recommendation:

Leave active.

Reason:

Brightness information is more stable for star detection.

---

# Maximum Number of Stars

Standard:

500

Recommendation:

500

For very star-rich fields may reduce.

---

# Distortion Removal

Standard:

Off

Recommendation:

Off

Enable only for obvious distortions.

---

# 7. Stacking

After registration the images are combined.

Goals:

- Amplify signal
- Reduce noise
- Remove outliers

---

# Method

## Average

Standard:

Often available

Properties:

- Maximum signal quality
- Sensitive to outliers

---

## Median

Properties:

- Robust against outliers
- Less signal

Suitable:

- Few images

---

## Winsor Sigma

Recommendation:

Deep sky standard.

Suitable for:

- Galaxies
- Nebulae
- Long series

Removes:

- Satellites
- Airplanes
- Single hot pixels

---

# 8. Normalization During Stacking

Normalization equalizes differences.

---

## Additive

Changes the background.

Suitable:

- When only brightness differences exist

---

## Multiplicative

Changes scaling.

Suitable:

- When exposure varies

---

## Additive + Multiplicative

Combines both methods.

Suitable:

- Difficult datasets

---

# Recommendation Dwarf mini

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

For identical lights:

```

Additive

```

is usually sufficient.

---

# 9. RGB Weighting During Stacking

Standard:

Off

Recommendation:

Off

Reason:

PCC handles color correction later.

Enable only for special problems.

---

# 10. Stack Output

Typical result:

```

r_pp_m31_light_stacked.fits

```

This is a linear master image.

It appears:

- Dark
- Low contrast
- Unimpressive

This is normal.

---

# 11. Histogram and Stretch

A linear FITS looks dark.

Not because information is missing.

But because the display is not adjusted.

---

# Auto-Stretch

Recommendation:

Use for first check.

Advantage:

- Quick overview

Disadvantage:

- Not always optimal

---

# Manual Stretching

Principle:

Black point:

- Set background

Midtones:

- Make faint structures visible

White point:

- Limit bright areas

---

# 12. Photometric Color Calibration (PCC)

## Purpose

Corrects:

- Color cast
- Sensor deviation
- Atmospheric effects

---

# Prerequisites

Requires:

- Star fields
- Plate solving
- Known sky position

---

# Order

Correct:

```

Stack

↓

Background Extraction

↓

PCC

↓

Stretch

```

---

Wrong:

```

Stack

↓

Stretch

↓

PCC

```

---

# 13. Background Correction

Siril:

Background Extraction

or

GraXpert

---

# Recommendation

With Dwarf mini:

GraXpert often gives excellent results.

Workflow:

```

Stack

↓

GraXpert

↓

PCC

```

---

# 14. Export

For further processing:

Recommendation:

```

TIFF 16-bit

```

For archive:

```

Keep FITS

```

---

# 15. Siril Standard Workflow Dwarf mini

```

Import FITS

↓

Create sequence

↓

Master Dark

↓

Calibrate

↓

Register

↓

Stack

↓

GraXpert

↓

PCC

↓

Stretch

↓

Export

```

---

# 16. Common Errors

## Black TIFF

Cause:

Linear image exported.

Solution:

Stretch before export.

---

## All green

Cause:

OSC Bayer color processing.

Solution:

Perform PCC.

---

## Stars disappear

Cause:

Denoising too aggressive.

Solution:

Reduce denoise.

---

## Stack fails

Causes:

- Sequence paths wrong
- Files moved
- Corrupted FITS
- Wrong sequence

---

# 17. Siril 1.4.4 – Advanced Functions (Reference)

> These functions are not included in standard workflows (Ch. 15, 22, 36),
> but relevant for special problems or advanced processing.

---

## 17.1 Plate Solving / Astrometry

**Menu:** `Astrometry` → `Plate Solving`  
**Commands:** `solve-field`, `astrometry.net`, `catsearch`, `conesearch`

### Purpose
Determines exact sky position (WCS) of image. Prerequisite for:
- Photometry / PCC with Gaia catalog
- Object annotation (overlay catalogs)
- Mosaic stitching (overlap calculation)

### Prerequisites
- `astrometry.net` installed (external tool)
- Index files for focal length/sensor downloaded
- Star fields in image (at least ~20 stars)

### Workflow
```
Stack
↓
Plate Solving (solve-field / astrometry.net)
↓
WCS in header → PCC / Annotation / Mosaic
```

### Important Commands
| Command | Description |
|---------|--------------|
| `solve-field` | Internal solver (fast, less robust) |
| `astrometry.net` | External solver (robust, requires installation) |
| `catsearch` | Search object by name (SIMBAD) |
| `conesearch` | Display catalog stars in FoV (Gaia, Tycho2, PGC, etc.) |
| `disto` | Show distortion field (after Plate Solving) |

### Typical Parameters (`astrometry.net`)
- `--downsample 2` — faster, for large sensors
- `--scale-units degwidth` — scale in degrees
- `--scale-low 0.5 --scale-high 3.0` — expected FoV range
- `--cpulimit 60` — timeout in seconds

---

## 17.2 Photometry

**Menu:** `Analysis` → `Photometry`  
**Commands:** `findstar`, `psf`, `findcompstars`, `light_curve`

### Purpose
- Measure star magnitudes (instrumental)
- Find comparison stars for variable stars
- Create light curves
- Extract PSF parameters (FWHM, roundness, background)

### Workflow
```
Stack (Plate Solved)
↓
findstar (detect stars)
↓
psf (PSF fitting for precise photometry)
↓
findcompstars (comparison stars for variables)
↓
light_curve (create light curve)
```

### Important Parameters
| Parameter | Recommendation | Note |
|-----------|------------|---------|
| `-layer` | 0 (Mono/R), 1 (G), 2 (B) | Channel for detection |
| `-maxstars` | 500–1000 | Limit for performance |
| `-out` | CSV file | Export for external analysis |
| `psf` | after `findstar` | Fit model: Moffat/Gauss |

### Catalogs for `conesearch` / `catsearch`
| Catalog | Type | Limit Mag | Usage |
|---------|-----|-----------|---------|
| `gaia` / `localgaia` | Stars | 20 | PCC, Astrometry, Photometry |
| `tycho2` | Stars | 11 | Brighter stars, fast |
| `nomad` | Stars | 15 | All-Sky, good coverage |
| `apass` | Stars | 17 | Photometrically calibrated (B,V,g,r,i) |
| `pgc` | Galaxies | — | Deep-Sky objects |
| `solsys` | Solar system | — | Comets, asteroids, planets |
| `aavso_chart` | Variables | — | Comparison stars for AAVSO |

---

## 17.3 Deconvolution (Sharpening)

**Menu:** `Processing` → `Deconvolution`  
**Commands:** `deconv`, `rl` (Richardson-Lucy), `wiener`

### Purpose
Remove optical blur (seeing, focus, diffraction). **Only on linear data!**

### Methods
| Method | Parameters | Application |
|---------|-----------|----------------|
| `rl` (Richardson-Lucy) | Iterations (10–50), regularization | Standard for Deep Sky, preserves stars well |
| `wiener` | Noise power spectrum | When noise model known |
| `deconv` (GUI) | PSF model (star/file), iterations | Interactive, preview possible |

### Recommendation Dwarf mini
```
Stack (linear)
↓
PCC
↓
Deconvolution (RL, 15–25 iterations, star PSF)
↓
Stretch
```

**Warning:** Too many iterations → ring artifacts around stars, noise amplification.

---

## 17.4 Wavelets (Detail Enhancement)

**Menu:** `Processing` → `Wavelets`  
**Commands:** `wavelet`, `extract`, `wrecons`

### Purpose
Multi-scale decomposition for targeted sharpening/smoothing per scale.

### Workflow
```
wavelet layers [1-6]     → decompose into scales
extract layer            → edit individual scale
wrecons                  → reconstruct
```

### Typical Application
- **Scales 1-2:** Star sharpening (small structures)
- **Scales 3-4:** Nebula details (medium structures)
- **Scales 5-6:** Large-scale structures (usually leave untouched)

---

## 17.5 CLAHE (Local Contrast Enhancement)

**Command:** `clahe cliplimit tilesize`

### Purpose
Contrast-limited adaptive histogram equalization. Enhances local details without global overexposure.

### Parameters
| Parameter | Range | Recommendation |
|-----------|---------|------------|
| `cliplimit` | 1–10 | 2–4 (higher = stronger, more artifacts) |
| `tilesize` | 8–128 | 32–64 (smaller = more local, larger = more global) |

### Usage
After Stretch, before Export — for "pop" in nebula structures.

---

## 17.6 Cosmetic Correction (Hot/Cold Pixel)

**Menu:** `Calibration` → `Cosmetic Correction`  
**Commands:** `find_hot`, `find_cosme`, `cosme`, `cosme_cfa`, `seqcosme`

### Purpose
Remove remaining hot/cold pixels after calibration.

### Workflow
```
Create Master Dark
↓
find_hot master_dark.fits 3 3  → hot_pixels.lst (3σ hot, 3σ cold)
↓
cosme hot_pixels.lst           → apply to lights
```

### Parameters `find_hot`
| Parameter | Standard | Meaning |
|-----------|----------|-----------|
| `cold_sigma` | 3 | Cold-pixel threshold (σ below median) |
| `hot_sigma` | 3 | Hot-pixel threshold (σ above median) |

### Bad Pixel Map (BPM) Format
```
P x y [C|H]    # Single pixel (C=cold, H=hot)
C x 0          # Entire column x
L y 0          # Entire row y
```

---

## 17.7 Banding Removal

**Command:** `fixbanding amount sigma [-vertical]`

### Purpose
Remove horizontal/vertical stripes (sensor readout, electronics).

### Parameters
| Parameter | Range | Recommendation |
|-----------|---------|------------|
| `amount` | 0–4 | 1–2 (correction strength) |
| `sigma` | 0–5 | 1–2 (highlight protection, higher = more protection) |
| `-vertical` | Flag | Vertical instead of horizontal banding |

### When to Apply
After calibration, before registration — only if banding visible.

---

## 17.8 X-Trans Fix (Fuji Cameras)

**Command:** `fix_xtrans`

### Purpose
Remove quadratic pattern of phase-AF pixels in Dark/Bias frames for Fuji X-Trans sensors.

### Application
```
Create Master Dark
↓
fix_xtrans (apply to Master Dark)
↓
Calibration with corrected Master Dark
```

---

## 17.9 ICC Profile / Color Management

**Commands:** `icc_assign`, `icc_convert_to`, `icc_remove`

### Purpose
Color profile management for correct color reproduction.

| Command | Usage |
|--------|---------|
| `icc_assign sRGB` / `Rec2020` / `linear` / `working` / path | Assign profile (no conversion) |
| `icc_convert_to sRGB [perceptual\|relative\|saturation\|absolute]` | Convert to profile (rendering intent) |
| `icc_remove` | Remove profile |

### Recommendation
- Linear data: `icc_assign linear` (or none)
- Final export for web/sRGB: `icc_convert_to sRGB perceptual`
- For print: `icc_convert_to /path/to/profile.icc relative`

---

## 17.10 Statistics & QC (Quality Control)

**Commands:** `entropy`, `histo`, `bg`, `bgnoise`, `findstar -out`, `psf`

### Quick Image Assessment
| Command | Shows | Good For |
|--------|--------------|---------|
| `bg` | Background median | Exposure consistency |
| `bgnoise` | Background noise (MAD) | Noise comparison |
| `entropy` | Entropy (information content) | Detail richness, focus quality |
| `histo 0/1/2` | Histogram per channel | Set black/white point |
| `findstar -out stats.csv` | Star list with FWHM, roundness, SNR | Frame quality, culling |
| `psf` | PSF parameters of detected stars | Seeing, tracking quality |

### Frame-Culling Workflow
```
findstar -out all_frames.csv (per frame)
→ analyze CSV: FWHM, star count, background
→ mark bad frames (exclude)
→ stack only good frames
```

---

# Most Important Siril Rules

1. Never change FITS unnecessarily.

2. Calibration before registration.

3. Registration before stack.

4. PCC before aggressive color correction.

5. Denoise at the end.

6. Linear image always looks worse than final image.

7. **Plate Solving before PCC** (for Gaia catalog matching).

8. **Deconvolution/Wavelets only on linear data** (before Stretch).

9. **Cosmetic Correction after calibration** (on calibrated data).

10. **ICC Profiles at the end** (for export/web/print).
```
```
