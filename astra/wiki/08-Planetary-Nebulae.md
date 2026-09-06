# Workflow 08 – Planetary Nebulae

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing planetary nebulae with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- M57 Ring Nebula
- M27 Dumbbell Nebula
- NGC 6543 Cat's Eye Nebula
- NGC 2392 Eskimo Nebula

Planetary nebulae are special deep-sky objects.

They differ from galaxies and large nebulae:

- Small
- Relatively bright
- High contrast
- Often bright central region
- Many details in small structures

---

# 1. Planetary Nebula Properties

Planetary nebulae are formed from ejected gas clouds of old stars.

Typical characteristics:

- Compact shape
- Strong emission lines
- High surface brightness
- Colored structures

Often dominated by:

| Line | Color |
|---|---|
| OIII | Blue/green |
| H-alpha | Red |

---

# 2. Difficulty

Planetary nebulae are less difficult due to their brightness.

The challenge is:

- Preserve small structures
- Keep central star visible
- Don't destroy colors
- Control stars

---

# 3. Acquisition Recommendation

## Standard Dwarf mini

| Parameter | Recommendation |
|---|---|
| Exposure | 60–180 seconds |
| Gain | 40 |
| Lights | 50–150 |
| Darks | 10–20 |
| Filter | Optional dual-band |

---

# 4. Exposure Time

## 180 Seconds

Suitable for:

- Fainter planetary nebulae
- Outer structures

---

## Shorter Exposures

Additionally useful for:

- Bright core
- Central star
- HDR

Example:

```

50 × 180 seconds

*

30 × 30 seconds

```

---

# 5. Filter Selection

## Without Filter

Advantages:

- Natural colors
- More stars
- Maximum light

---

## Dual-band

Very useful.

Reason:

Planetary nebulae contain strong:

- H-alpha
- OIII

Emissions.

Advantages:

- Higher contrast
- Better nebula structures

Disadvantages:

- Fewer stars
- Color shifts

---

# 6. Preparation in Siril

Folders:

```

M57/

lights/

darks/

output/

```

---

# 7. Create Sequence

Result:

```

m57_light_.seq

```

Check:

- Stars visible
- Object present
- No badly blurred frames

---

# 8. Master Dark

Recommendation:

```

Median

```

---

# 9. Calibration

Active:

## Dark

Yes

---

## Flat

Optional.

Useful when:

- Dust
- Vignetting

---

## Bias

Usually:

No

---

# 10. Registration

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

# 11. Peculiarity of Small Objects

Planetary nebulae can be a few pixels large.

Important:

Stars must be registered cleanly.

Don't:

- Manually align object center
- Combine images by eye

---

# 12. Stacking

Recommendation:

```

Winsor Sigma

```

Why:

- Removes satellites
- Removes airplanes
- Protects from outliers

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

# 13. Background Correction

Careful.

Planetary nebulae are often small.

An algorithm may interpret them as background.

---

# GraXpert

Recommendation:

- Few samples
- No aggressive removal

Check:

Before:

```

Nebula present

```

After:

```

Nebula still there?

```

---

> **V19-FIX-13 Duo-Band:** As in Ch. 08 §14a — Duo-Band + `nebula_standard` (PCC off, SCNR on). For details see Ch. 08. With `star_standard` + Duo-Band + PCC the image turns pink (C19 R/G 1.608 vs 1.006 with nebula_standard) — evidence v19 suite 2026-09-02.

# 14. PCC

After background correction:

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

# 15. Color Management

Planetary nebulae may show strong colors.

Typical:

M57:

- Blue/green inside
- Reddish outer regions

Don't over-neutralize.

---

# 16. Denoising

Less than with galaxies.

Recommendation:

```

0.03–0.08

```

Why:

Small details get lost quickly.

---

# 17. Sharpening

Optional.

Very careful.

Suitable:

- Light details
- Structure enhancement

Not:

- Hard edges
- Artificial halos

---

# 18. HDR Workflow

Many planetary nebulae benefit from two exposure series.

Example M57:

## Long

```

180 seconds

```

For:

- Outer region

---

## Short

```

10–30 seconds

```

For:

- Bright core
- Central star

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

# 19. Typical Errors

## Nebula looks like star

Cause:

Too little integration

Solution:

Collect more lights

---

## Core blown out

Cause:

Too much stretching

Solution:

Use HDR

---

## Colors disappear

Cause:

Over-neutralization

Solution:

Check PCC

---

## Background turns black

Cause:

Over-processing

Solution:

Preserve natural background

---

# 20. Example Workflow M57

Acquisition:

```

80 × 180 seconds

Gain 40

Dual-band optional

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

GraXpert

↓

PCC

↓

Light denoising

↓

Stretch

↓

GIMP

```

---

# 21. Quality Goal

A good planetary nebula image:

- Shows clear structures
- Preserves central region
- Has natural colors
- Has controlled stars
- Is not over-sharpened

---

# Summary

```

60–180 seconds

Gain 40

50–150 lights

Dual-band possible

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma

↓

Careful background correction

↓

PCC

↓

Moderate stretching

```
