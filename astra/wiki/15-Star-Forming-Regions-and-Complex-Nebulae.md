# Workflow 15 – Star Forming Regions and Complex Nebulae

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing large, complex nebula regions with active star formation.

Examples:

- Orion Nebula M42
- Horsehead Nebula IC 434
- Rosette Nebula NGC 2237
- Eagle Nebula M16
- Lagoon Nebula M8
- Trifid Nebula M20
- North America Nebula NGC 7000

These objects are among the most spectacular deep-sky targets.

They combine multiple object types:

- Emission nebula
- Reflection nebula
- Dark nebula
- Star clusters

---

# 1. Properties of These Objects

Star-forming regions contain:

- ionized hydrogen gas
- dust clouds
- young stars
- reflection areas

Typical colors:

| Region | Color |
|---|---|
| H-alpha | red |
| OIII | blue/green |
| Reflection | blue |
| Dust | dark |

---

# 2. Main Processing Goal

Preserve:

- large nebula structures
- color gradients
- dark dust bands
- stars

Avoid:

- blown-out cores
- artificial colors
- lost dark structures

---

# 3. Recording Recommendation

## Standard Dwarf mini

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

| Parameter | Recommendation |
|---|---|
| Exposure | 60–180 seconds |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | depends on object |

---

# 4. Filter Selection

> **V19-FIX-13 Duo-Band:** As in Ch. 08 §14a — Duo-Band + `nebula_standard` (PCC off, SCNR on). For details see Ch. 08. With `star_standard` + Duo-Band + PCC the image turns pink (C19 R/G 1.608 vs 1.006 with nebula_standard) — evidence v19 suite 2026-09-02.

## No Filter

Suitable for:

- dark sky
- natural colors
- reflection components

---

## Dual-Band

Highly recommended.

Especially for:

- H-alpha regions
- OIII structures

Examples:

- M16
- M8
- Rosette Nebula
- North America Nebula

---

Disadvantages:

- fewer stars
- stronger color correction needed

---

# 5. Combining Multiple Recordings

These objects benefit especially from multiple series.

Example:

## No Filter

for:

- stars
- reflection components

---

## Dual-Band

for:

- emission structures

---

Combination:

```

Broadband Stack

*

Dual-Band Stack

↓

Mix in GIMP

```

---

# 6. Exposure Time

## 180 Seconds

Good for:

- faint outer regions
- nebula structures

---

## Shorter Exposures

Useful for:

- bright cores

Examples:

M42:

```

180 seconds

*

10–30 seconds

```

for HDR.

---

# 7. Preparation in Siril

Folder:

```

M42/

lights/

darks/

output/

```

---

# 8. Create Sequence

Result:

```

m42_light_.seq

```

Check:

- all frames present
- nebula visible
- no strong cloud changes

---

# 9. Master Dark

Recommendation:

```

Median

```

---

# 10. Calibration

## Dark

Yes

---

## Flat

Recommended for:

- large nebula areas
- visible vignetting

---

## Bias

Usually:

No

---

# 11. Registration

Menu:

Registration

---

Selection:

```

General Deep Sky

```

---

Parameters:

| Parameter | Value |
|---|---|
| Transformation | Homography |
| Minimum star pairs | 10 |
| Luminance | active |
| Maximum stars | 500 |
| Distortion removal | off |

---

# 12. Special Note: Large Nebulae

Large nebulae often cover much of the image.

Problem:

Automatic algorithms can interpret nebula as background.

---

Examples:

M42:

- nebula nearly fills entire image

NGC 7000:

- huge structure

---

# 13. Stack

Recommendation:

```

Winsor Sigma

```

---

Why:

- removes satellites
- reduces random noise
- protects faint structures

---

# Normalization

Recommendation:

```

Additive + Scaling

```

---

# RGB Weighting

Recommendation:

```

off

```

---

# 14. Background Correction

Very critical.

For nebulae, background is often not empty sky.

---

GraXpert:

Recommendation:

- careful
- few samples
- avoid nebula areas

---

Do not remove:

- faint outer regions
- dust structures

---

# 15. PCC

After background correction.

Workflow:

```

Stack

↓

GraXpert

↓

PCC

↓

Stretch

```

---

# 16. Color Management

These objects may show vibrant colors.

But:

Preserve naturalness.

---

Typical errors:

Too much red:

- H-alpha overdone

Too much green:

- OIII wrong weight

---

# 17. Denoising

Recommendation:

```

0.03–0.08

```

---

Not too strong.

Why:

Fine nebula structures disappear quickly.

---

# 18. Stretching

The most important creative step.

Goal:

- make nebula visible
- control stars
- preserve colors

---

Recommendation:

Many small steps:

```

Stretch

↓

check

↓

Stretch

↓

check

```

---

# 19. HDR for Bright Nebulae

Especially important for:

- M42
- M8
- M20

---

Workflow:

## Short Exposure

```

10–30 seconds

```

for:

- bright core

---

## Long Exposure

```

180 seconds

```

for:

- outer regions

---

Combination:

```

Short stack

*

Long stack

↓

HDR

```

---

# 20. Typical Errors

## Nebula looks flat

Cause:

denoising too aggressive.

---

## Stars dominate

Cause:

stretching too strong.

---

## Nebula disappears

Cause:

GraXpert too aggressive.

---

## Colors look artificial

Cause:

wrong color enhancement.

---

# 21. Example Workflow M42

Recording:

```

50 × 180 seconds

Gain 40

Dual-Band optional

```

Additionally:

```

30 × 15 seconds

```

for core.

---

Processing:

```

Master Dark

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma Stack

↓

GraXpert careful

↓

PCC

↓

light denoising

↓

Stretch

↓

HDR with short exposure

↓

GIMP

```

---

# 22. Quality Goal

A good star-forming region recording:

- shows large structures
- has natural colors
- preserves dark dust bands
- shows stars without dominance
- appears three-dimensional

---

# Summary

```

60–180 seconds

Gain 30–40

50–200 Lights

Dual-Band possible

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma

↓

careful background correction

↓

PCC

↓

moderate denoising

↓

slow stretching

```
```
```
