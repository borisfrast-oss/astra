# 02 – Fundamentals

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Overview

This chapter explains the technical foundations needed to understand Siril workflows.

Topics covered:

- FITS files
- RAW data
- Bayer matrix
- Debayering
- Sequences
- Calibration
- Registration
- Normalization
- Stacking
- linear and nonlinear data
- Histogram
- Color spaces

---

# 1. FITS Files

## What Is FITS?

FITS stands for:

**Flexible Image Transport System**

It is the standard format of professional astronomy.

A FITS file contains:

- image pixels
- metadata
- acquisition settings
- camera information

---

## Difference from JPEG or PNG

| Format | Property |
|---|---|
| JPEG | compressed, lossy |
| PNG | lossless but for finished images |
| TIFF | image editing |
| FITS | astronomical raw data |

---

## Why FITS?

Astrophotography requires:

- high dynamic range
- linear data
- unmodified sensor data

A JPEG would already be:

- automatically brightened
- color-corrected
- compressed

Important information would be lost.

---

# 2. Image Data in FITS

A FITS image consists of pixel values.

Example:

```

Pixel value 100

Pixel value 250

Pixel value 5000

```

These values are not directly brightness values like in a normal image.

They represent:

- measured electrons
- light intensity
- sensor response

---

# 3. Linear Workflow

Astrophotography always begins linear.

This means:

The pixel values have not yet been changed.

Example:

```

Original:

10
20
30
40
50

```

After stretch:

```

10
40
120
220
255

```

The differences are emphasized.

---

# 4. Bayer Matrix

The Dwarf mini uses a color sensor.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

However, one sensor pixel measures only one color.

The camera therefore uses a Bayer matrix.

Typical pattern:

```

G R

B G

```

This means:

- twice as many green pixels
- half as many red pixels
- half as many blue pixels

Why green?

The human eye is particularly sensitive to green.

---

# 5. Debayering

Debayering means:

From individual color pixels, a color image is created.

Before:

```

R G R G

G B G B

R G R G

```

After:

```

RGB pixel
RGB pixel
RGB pixel

```

---

## Important

Debayering should occur only once.

Incorrect multiple debayering can cause:

- color casts
- artifacts
- detail loss

---

# 6. Sequences in Siril

A sequence is a collection of related images.

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

## Why Sequences?

Siril does not work directly with individual files.

The sequence enables:

- Registration
- Calibration
- Rating
- Stacking

---

# 7. Folder Structure

Recommended structure:

```

M31/

├── lights/

│   ├── m31_light_00001.fits
│   ├── m31_light_00002.fits

├── darks/

│   ├── m31_dark_00001.fits
│   ├── m31_dark_00002.fits

├── siril/

│   └── Sequences

```

---

## Important

Sequence files must be able to find the images.

If FITS files are moved:

Problem:

```

.seq

↓

points to old path

```

Result:

```

File not found

```

Typical error message:

```

[File extension] not found

```

---

# 8. Calibration

Calibration removes known errors.

It occurs before stacking.

Typical sequence:

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

# 9. Master Dark

A single dark is noisy.

Therefore multiple darks are combined.

Example:

```

Dark 1
Dark 2
Dark 3
Dark 4

↓

Master Dark

```

The master dark contains:

- stable sensor pattern
- less random noise

---

# 10. Registration

The camera moves slightly during acquisition.

Even with tracking there is:

- small shifts
- rotation
- optical differences

Registration aligns the stars.

Example:

Before:

```

Image 1:

```
*
```

Image 2:

```
   *
```

```

After:

```

```
*
*
```

```

---

# 11. Siril Registration

For deep sky:

Recommendation:

```

General:
Deep Sky

```

Suitable for:

- Galaxies
- Nebulae
- Star fields

---

# 12. Transformations

Registration can use different mathematical models.

## Translation

Only shift.

Suitable:

- very stable systems

---

## Affine

Can:

- Shift
- Rotation
- Scaling

compensate.

---

## Homography

Can additionally:

- Perspective distortions

correct.

For deep sky usually the standard choice.

---

# 13. Normalization

Normalization equalizes brightness differences between images.

Why?

Individual images can differ due to:

- slight transparency changes
- background changes
- sensor changes

---

# 14. Stacking

When stacking, multiple images are combined.

Goals:

- Reduce noise
- Increase signal
- Remove outliers

---

# 15. Stacking Methods

## Average

Mathematically:

```

Sum of all pixels

divided by

Number of images

```

Advantage:

- Maximum signal quality

Disadvantage:

- Outliers remain

---

## Median

The middle value is used.

Example:

```

5
6
7
100

```

Median:

```

6.5

```

The outlier 100 is ignored.

---

## Winsor Sigma

A combination of:

- Statistical analysis
- Outlier removal
- Averaging

Very suitable for deep sky.

Removes:

- Satellites
- Airplanes
- Random errors

---

# 16. Histogram

The histogram shows the brightness distribution.

Left:

```

Black

```

Middle:

```

Medium brightness

```

Right:

```

Bright areas

```

---

## Linear Astro Image

Typical:

```

████
█
█

```

Almost everything on the left.

This is normal.

---

# 17. Stretching

Stretching shifts the display.

It makes:

- faint nebulae visible
- Galaxy arms visible
- Colors visible

But:

Excessive stretching creates:

- Noise
- Hard transitions
- Blown-out stars

---

# 18. Color Calibration

A camera does not see colors exactly as the eye does.

PCC corrects:

- Color shifts
- Sensor characteristics
- Atmospheric effects

---

# 19. Order of Processing

Recommended sequence:

```

Conversion

↓

Calibration

↓

Registration

↓

Stacking

↓

Gradient removal

↓

PCC

↓

Stretch

```

Not:

```

Stretch

↓

Calibration

```

---

# 20. Key Insights

## Rule 1

Good source material is more important than heavy processing.

---

## Rule 2

Never unnecessarily modify linear data.

---

## Rule 3

Each processing step should have a clear purpose.

---

## Rule 4

Work target-dependent.

A workflow for M31 is not automatically optimal for Arcturus.
```
```
