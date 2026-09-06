# Workflow 13 – Milky Way and Wide Field

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing large sky area images with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- Milky Way panoramas
- Star fields
- Large nebula regions
- Constellations
- Wide-field acquisitions

This category differs from classic deep-sky objects.

The main goal is:

- Natural star fields
- Harmonious background
- Preservation of large structures

---

# 1. Wide Field Image Properties

Wide-field images contain:

- Very many stars
- Large sky areas
- Diffuse Milky Way structures
- Sky color gradients

Typical challenges:

- Light pollution
- Gradients
- Very many stars
- Background correction

---

# 2. Acquisition Recommendation

## Standard Dwarf mini

| Parameter | Recommendation |
|---|---|
| Exposure | 30–180 seconds |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | No filter |

---

# 3. Exposure Time

## Dark Sky

Possible:

```

120–180 seconds

```

Advantages:

- More stars
- More Milky Way structure

---

## Light Pollution Sky

Better:

```

30–90 seconds

```

Reason:

Background becomes too bright otherwise.

---

# 4. Filter Selection

## No Filter

Standard.

Advantages:

- Natural colors
- Maximum star number
- Natural Milky Way colors

---

## Light Pollution Filter

Can be useful for:

- City
- Suburb
- Bright sky

---

## Dual-band

Only for contained nebula areas.

Not for pure Milky Way.

Reason:

Stars and star colors are altered.

---

# 5. Preparation in Siril

Folders:

```

MilkyWay/

lights/

darks/

output/

```

---

# 6. Create Sequence

Result:

```

milkyway_light_.seq

```

Check:

- Enough stars
- No clouds
- Uniform focus

---

# 7. Master Dark

Recommendation:

```

Median

```

---

# 8. Calibration

## Dark

Yes

---

## Flat

Optional.

Useful when:

- Strong edge falloff
- Dust
- Visible spots

---

## Bias

Usually:

No

---

# 9. Registration

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

# 10. Wide Field Peculiarity

Due to large image area there are many stars.

Problems:

- Too many detection points
- Wrong references
- Long processing

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

# 11. Stacking

Recommendation:

```

Winsor Sigma

```

Why:

- Remove satellites
- Remove airplanes
- Reduce random errors

---

# Normalization

Recommendation:

```

Additive

```

Sufficient for identical acquisitions.

---

# RGB Weighting

Recommendation:

```

Off

```

---

# 12. Background Correction

Most important step with wide field.

Problems:

- Light pollution gradients
- Moonlight
- Uneven sky

---

# GraXpert

Very useful.

But:

Work carefully.

---

Danger:

Too aggressive correction removes:

- Milky Way structures
- Dust clouds
- Natural brightness gradients

---

# 13. GraXpert Recommendation

Start:

- Few samples
- Moderate correction

Check:

Before:

```

Natural sky

```

After:

```

Gradient removed

Structures preserved

```

---

# 14. PCC

Very helpful with wide field.

Sequence:

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

Milky Way contains many colors:

- Blue reflection areas
- Red nebulae
- Yellowish stars
- Dark dust lanes

Not:

Make everything neutral gray.

---

# 16. Denoising

With wide field be careful.

Recommendation:

```

0.03–0.08

```

---

Why:

Large dark areas show noise more.

---

# 17. Stretching

The goal:

Make the Milky Way visible.

---

Not:

Over-brighten.

Problem:

- Stars become dominant
- Background becomes gray
- Contrast lost

---

Recommendation:

Several small steps:

```

Small stretch

↓

Check

↓

Small stretch

```

---

# 18. Control Stars

With wide field stars are a large part of image.

Problems:

## Too many dominant stars

Solution:

- Less stretch
- Star reduction in GIMP possible

---

## Stars without color

Causes:

- Overexposure
- Over-stretching

---

# 19. Panorama and Mosaics

Large sky areas can consist of multiple fields.

Example:

```

Position 1

*

Position 2

*

Position 3

↓

Panorama

```

---

Workflow:

Each position separately:

```

Stack

↓

PCC

↓

Stretch

```

Then:

Combine in GIMP.

---

# 20. Typical Errors

## Background looks spotty

Causes:

- Too few images
- Aggressive background correction

---

## Milky Way disappears

Cause:

GraXpert too strong.

---

## Stars look artificial

Causes:

- Over-sharpening
- Too much denoising

---

## Image looks flat

Causes:

- Too little contrast
- Over-neutralization

---

# 21. Example Workflow Milky Way

Acquisition:

```

100 × 60 seconds

Gain 30–40

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

GraXpert

↓

PCC

↓

Light denoising

↓

Gentle stretching

↓

GIMP

```

---

# 22. Quality Goal

A good Milky Way image:

- Shows natural star colors
- Has uniform background
- Preserves dark dust lanes
- Shows nebula areas without exaggeration
- Looks three-dimensional

---

# Summary

```

30–180 seconds

Gain 30–40

50–200 lights

No filter

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma

↓

GraXpert carefully

↓

PCC

↓

Gentle stretching

```
