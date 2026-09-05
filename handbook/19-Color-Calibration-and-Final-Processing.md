# Workflow 19 – Color Calibration and Final Processing

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes the final processing steps after stacking.

It applies across objects:

- Galaxies
- Nebulae
- Star clusters
- Star fields
- Comets
- Mosaics

Focus is on:

- natural colors
- controlled contrast
- optimal preparation for GIMP

---

# 1. Basic Principle

Processing should follow a fixed order.

Recommended workflow:

```

Stack

↓

Background correction

↓

Color calibration

↓

Stretch

↓

Denoise

↓

Export

↓

GIMP

```

---

# 2. Why Order Matters

Many errors come from wrong order.

Example:

Denoise before Stretch:

Problem:

- details get changed
- noise becomes visible again later

---

Color correction after extreme Stretch:

Problem:

- colors become unnatural
- stars blow out

---

# 3. Background Control

Before any color correction:

check:

- Is background uniform?
- Are there gradients?
- Are nebula structures preserved?

---

Typical causes:

- light pollution
- moonlight
- vignetting
- sensor artifacts

---

# 4. Background Extraction in Siril

Alternative to GraXpert:

Siril:

```

Background Extraction

```

---

Suitable for:

- light gradients
- small corrections

---

Be careful with:

- large nebulae
- dark nebulae
- galaxy halo

---

# 5. GraXpert Before PCC

Recommended workflow:

```

Siril Stack

↓

GraXpert background correction

↓

back to Siril

↓

PCC

```

---

Why?

PCC needs the most neutral image possible.

---

# 6. Photometric Color Calibration (PCC)

PCC is the standard for color calibration.

Goal:

Image receives astronomically sensible color balance.

---

# 7. Prerequisites for PCC

Requires:

- stars
- known sky region
- internet access for star catalog

---

Suitable for:

- Galaxies
- Nebulae
- Star clusters
- Star fields

---

More difficult:

- pure planetary images
- Moon
- very few stars

---

# 8. PCC Workflow Siril 1.4.4

Menu:

```

Image Processing

↓

Color Calibration

↓

Photometric Color Calibration

```

---

Inputs:

## Object

Enter name:

Examples:

```

M31
M42
M13

```

---

## Focal Length

If known:

Dwarf mini:

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

use corresponding value.

---

## Pixel Size

Use sensor parameters.

---

# 9. PCC Parameters

Typical values:

| Parameter | Recommendation |
|---|---|
| Background neutralization | active |
| Automatic detection | active |
| Star selection | automatic |
| Color model | Standard |

---

Usually:

no manual changes needed.

---

# 10. If PCC Doesn't Work

Typical reasons:

## No Solution Found

Causes:

- wrong object
- too few stars
- wrong coordinates

---

Solution:

- check object name
- check image orientation
- use more stars

---

## Colors strange afterward

Causes:

- strong processing before
- wrong background

---

Solution:

check stack again.

---

# 11. Remove Green Cast

Frequent with Dwarf OSC recordings.

Cause:

Bayer matrix and sensor characteristics.

---

Siril:

```

Remove Green Noise

```

---

Recommendation:

After PCC.

---

Not:

before PCC.

---

# 12. Stretching

Stretching converts linear data into visible image.

Before:

```

linear raw image

```

After:

```

visible image

```

---

# 13. Stretch Methods in Siril

## Auto Stretch

Very good for:

- first check
- quick results

---

## Manual Histogram

Better for:

- final processing

---

# 14. Histogram Principle

Left:

```

Shadows

```

---

Middle:

```

Midtones

```

---

Right:

```

Highlights

```

---

Not:

move black point too far to the right.

---

# 15. Multiple Stretches

Recommended:

```

small stretch

↓

check

↓

small stretch

↓

check

```

---

Why?

Control over:

- stars
- background
- nebula details

---

# 16. Denoising

Only after:

- Color correction
- Stretch

---

Recommendations:

| Object | Strength |
|---|---|
| Galaxies | 0.03–0.08 |
| Nebulae | 0.03–0.08 |
| Star clusters | 0–0.05 |
| Stars | 0–0.05 |
| Dark nebulae | 0.02–0.06 |

---

# 17. Channel Linking

Option:

```

Channels linked

```

---

Meaning:

Noise reduction applied equally to all color channels.

---

Advantages:

- less color noise
- natural colors

---

Disadvantages:

- individual color details may be reduced

---

Recommendation:

Usually:

```

active

```

---

For special nebula colors:

test.

---

# 18. Export from Siril

Recommendation:

Format:

```

TIFF 16 Bit

```

---

Why not JPEG?

JPEG:

- lossy
- reduces colors
- unsuitable for further processing

---

Why TIFF?

- high dynamic range
- GIMP compatible
- no quality loss

---

# 19. Handover to GIMP

In GIMP:

Import as:

```

16 Bit Integer

```

---

Not:

8 Bit.

---

# 20. GIMP Final Steps

Typical steps:

## Curves

For:

- contrast
- depth

---

## Color Temperature

For:

- light corrections

---

## Saturation

Carefully:

```

+5 to +20

```

---

## Layers

For:

- HDR
- Mosaics
- Star control

---

# 21. Typical Errors

## Background black

Cause:

Black point moved too far.

---

## Stars white

Cause:

stretching too strong.

---

## Colors artificial

Cause:

too much saturation.

---

## Nebula disappears

Cause:

noise reduction too aggressive.

---

# 22. Quality Control Before Export

Check:

## Stars

- no blown-out centers
- natural colors

---

## Background

- no strong gradients
- not completely black

---

## Object

- structures visible
- no artificial artifacts

---

# 23. Standard Final Workflow

```

Siril Stack

↓

GraXpert background correction

↓

PCC

↓

Remove green cast

↓

Stretch

↓

Denoise

↓

TIFF Export

↓

GIMP

↓

Curves/Color/Finalization

```

---

# Quality Goal

A finished astrophoto:

- shows real structures
- has natural colors
- preserves details
- doesn't look over-processed

---

# Summary

```

Stack

↓

Clean background

↓

PCC

↓

Remove green cast

↓

slow stretching

↓

light denoising

↓

16 Bit TIFF

↓

GIMP

```
