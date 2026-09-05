# Workflow 07 – Reflection Nebulae

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing reflection nebulae with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- M45 Pleiades
- M78
- Iris Nebula NGC 7023
- vdB objects

Reflection nebulae differ significantly from emission nebulae.

They do not shine themselves.

They reflect light from nearby stars.

---

# 1. Reflection Nebula Properties

Reflection nebulae consist of dust clouds that scatter starlight.

Typical properties:

- Bluish color
- Very faint structures
- Low contrast
- Sensitive to light pollution

---

# 2. Comparison to Emission Nebulae

| Property | Reflection Nebula | Emission Nebula |
|---|---|---|
| Own light source | No | Yes |
| Typical color | Blue | Red/blue/green |
| Filter effect | Low | Often strong |
| Difficulty | High | Medium |

---

# 3. Acquisition Recommendation

## Standard Dwarf mini

| Parameter | Recommendation |
|---|---|
| Exposure | 180 seconds |
| Gain | 40 |
| Lights | 50–150 |
| Darks | 10–20 |
| Filter | Usually no filter |

---

# 4. Why Many Frames Are Needed

Reflection nebulae have low surface brightness.

The signal spreads over a large area.

Therefore:

More integration is more important than aggressive processing.

Recommendation:

Minimum:

```

50 lights

```

Better:

```

100+ lights

```

---

# 5. Filter Selection

> **V19-FIX-13 Duo-Band:** As in Ch. 08 §14a — Duo-Band + `nebula_standard` (PCC off, SCNR on). For details see Ch. 08. With `star_standard` + Duo-Band + PCC the image turns pink (C19 R/G 1.608 vs 1.006 with nebula_standard) — evidence v19 suite 2026-09-02.

## No Filter

Usually best choice.

Advantages:

- Natural star colors
- Maximum light
- Better blue components

---

## Dual-band Filter

Only limited use.

Reason:

Dual-band enhances:

- H-alpha
- OIII

Reflection nebulae consist mainly of reflected starlight.

---

# 6. Preparation in Siril

Folders:

```

M78/

lights/

darks/

output/

```

---

# 7. Create Sequence

Result:

```

m78_light_.seq

```

Check:

- All images loaded
- Stars present
- Focus stable

---

# 8. Master Dark

Recommendation:

Method:

```

Median

```

Why:

- Stable sensor errors
- Low random fluctuation

---

# 9. Calibration

## Dark

Active:

Yes

---

## Flat

Only use if:

- Visible dust spots
- Strong vignetting

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

# 11. Peculiarity: Faint Nebulae

With reflection nebulae background correction must not be too aggressive.

Problem:

The nebula often looks like a gradient.

Example:

M45:

The blue nebula structures lie very broadly around the stars.

---

# 12. Stacking

Recommendation:

```

Winsor Sigma

```

Why:

- Removes satellites
- Removes random errors
- Preserves faint structures

---

# Normalization

Recommendation:

```

Additive

```

Usually sufficient for Dwarf series.

---

# RGB Weighting

Recommendation:

```

Off

```

Reason:

PCC comes later.

---

# 13. Background Correction

Very important step.

Reflection nebulae are sensitive to:

- Wrong gradient removal
- Too dark background
- Color shift

---

# GraXpert Recommendation

Work gently.

Goal:

Remove:

- Light pollution
- Uneven background

Don't remove:

- Large faint nebula areas

---

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

# 15. Color Character

Reflection nebulae often appear blue.

Don't try to make them completely neutral gray.

Example:

M45:

Normal:

- Blue dust clouds
- Warm stars

Not:

- Pure white nebula

---

# 16. Denoising

Especially careful.

Recommendation:

```

0.03–0.08

```

Why:

Faint dust structures can disappear quickly.

---

# 17. Stretching

Goal:

Make visible:

- Dust clouds
- Fine color gradients
- Star surroundings

---

Recommendation:

Very slowly.

Better:

```

Small stretch

↓

Check

↓

Small stretch

```

---

# 18. Stars

Reflection nebulae often contain bright stars.

Problems:

- Blown-out stars
- Missing color
- Over-sharpening

Recommendation:

No aggressive star processing.

---

# 19. Typical Errors

## Nebula disappears

Causes:

- Denoising too strong
- Background correction too aggressive

Solution:

Reduce processing.

---

## Image looks gray

Cause:

Over-neutralization.

Solution:

Preserve color character.

---

## Stars without color

Cause:

Stretching too strong.

Solution:

Work gently.

---

# 20. Example Workflow M45

Acquisition:

```

100 × 180 seconds

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

GraXpert carefully

↓

PCC

↓

Light denoising

↓

Slow stretching

↓

GIMP

```

---

# 21. Quality Goal

A good reflection nebula image:

- Shows blue dust structures
- Preserves natural star colors
- Has soft background
- Is not over-sharpened
- Shows details without artificial contrast

---

# Summary

```

180 seconds

Gain 40

50–150 lights

No dual-band

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma

↓

Gentle background correction

↓

PCC

↓

Careful stretching

```
