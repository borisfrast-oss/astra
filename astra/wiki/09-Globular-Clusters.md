# Workflow 09 – Globular Clusters

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing globular clusters with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- M13 Hercules Cluster
- M3
- M5
- M15
- Omega Centauri

Globular clusters are among the most rewarding objects for small telescopes.

They are:

- Bright
- Compact
- Rich in stars
- Colorful

---

# 1. Globular Cluster Properties

Globular clusters consist of:

- Hundreds of thousands of stars
- Very old star populations
- Densely packed star fields

Typical properties:

- Bright core
- Many individual stars
- Large brightness differences

---

# 2. Main Processing Goal

With globular clusters it's not about faint diffuse structures.

More important:

- Preserve star colors
- Separate stars cleanly
- Avoid core saturation
- Maintain natural appearance

---

# 3. Acquisition Recommendation

## Standard Dwarf mini

| Parameter | Recommendation |
|---|---|
| Exposure | 30–180 seconds |
| Gain | 30–40 |
| Lights | 30–100 |
| Darks | 10–20 |
| Filter | No filter |

---

# 4. Exposure Time

Globular clusters are brighter than galaxies.

180 seconds can already be too much.

---

## Long Exposure

Advantages:

- More faint stars
- Better outer region

Disadvantages:

- Core can saturate
- Stars lose color

---

## Shorter Exposure

Advantages:

- Better star colors
- Controlled core

---

# 5. HDR Acquisition

Recommended for bright globular clusters.

Example:

## Long

```

50 × 180 seconds

```

For:

- Faint outer stars

---

## Short

```

30 × 30 seconds

```

For:

- Core region
- Bright stars

---

Combination:

```

Long exposure stack

*

Short exposure stack

↓

HDR composition

```

---

# 6. Filter Selection

## No Filter

Recommended.

Reason:

Stars contain many color information.

Filters reduce:

- Star signal
- Natural colors

---

## Dual-band

Not recommended.

Reason:

Globular clusters are not emission objects.

---

# 7. Preparation in Siril

Folders:

```

M13/

lights/

darks/

output/

```

---

# 8. Create Sequence

Result:

```

m13_light_.seq

```

Check:

- Stars visible
- Focus correct
- No blurred images

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

Optional.

Useful when:

- Vignetting
- Dust

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
| Luminance | Active |
| Maximum stars | 500 |
| Distortion removal | Off |

---

# 12. Star Field Peculiarity

With globular clusters there are very many stars.

Problems:

- Too many detection points
- Wrong stars
- Slow registration

---

If problems occur:

Reduce maximum stars:

Standard:

```

500

```

Alternative:

```

200–300

```

---

# 13. Stacking

Recommendation:

```

Winsor Sigma

```

---

Why?

- Removes satellites
- Reduces outliers
- Protects stars

---

# Normalization

Recommendation:

```

Additive

```

---

# RGB Weighting

Recommendation:

```

Off

```

---

# 14. Background Correction

Less aggressive than with galaxies.

Reason:

Many stars cover large parts of image.

---

Problem:

An algorithm may interpret stars as background.

---

# GraXpert

Recommendation:

- Few samples
- Gentle correction

Not:

Completely dark background.

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

Stars live from their colors.

Typical colors:

| Star | Color |
|---|---|
| Young hot stars | Blue |
| Sun-like stars | Yellow |
| Old giant stars | Orange/red |

---

# 17. Denoising

Very careful.

Recommendation:

```

0.00–0.05

```

Why:

Noise removal can blur stars.

---

# 18. Stretching

Goal:

- Make stars visible
- Preserve core
- Keep colors

---

Not:

Maximum brightening.

---

Better:

```

Small stretch

↓

Check

↓

Small stretch

```

---

# 19. Control Stars

Typical problems:

## White Stars

Cause:

Stretching too strong

Solution:

Less stretch

---

## Colorless Stars

Cause:

Over-processing

Solution:

Check PCC again

---

## Washed Out Core

Cause:

Exposure too long

Solution:

Use HDR

---

# 20. Example Workflow M13

Acquisition:

```

60 × 120 seconds

Gain 40

No filter

```

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

Gentle background correction

↓

PCC

↓

No or minimal denoising

↓

Slow stretching

↓

GIMP

```

---

# 21. Quality Goal

A good globular cluster image:

- Shows many individual stars
- Preserves star colors
- Has bright but structured core
- Is not artificially sharpened

---

# Summary

```

30–180 seconds

Gain 30–40

30–100 lights

No filter

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma

↓

Gentle correction

↓

PCC

↓

Careful stretching

```
