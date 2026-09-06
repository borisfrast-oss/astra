# Workflow 05 – Galaxies

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing galaxy images with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- M31 Andromeda Galaxy
- M33 Triangulum Galaxy
- M81/M82 group
- M51 Whirlpool Galaxy
- M101 Pinwheel Galaxy
- NGC 4565

Galaxies are classic deep-sky targets.

They are more demanding than nebulae because:

- Contrast is low
- Background matters
- Fine structures must be protected

---

# 1. Galaxy Properties

Galaxies contain:

- Stars
- Dust clouds
- Star-forming regions
- Central bulges
- Spiral arms

Typical challenge:

Making the faint signal of outer regions visible against the dark sky.

---

# 2. Main Processing Goal

For galaxies:

Preserve:

- Spiral arms
- Dust lanes
- Color gradients
- Natural stars

Avoid:

- Artificially black background
- Exaggerated colors
- Lost outer regions

---

# 3. Acquisition Recommendation

## Standard Dwarf mini

| Parameter | Recommendation |
|---|---|
| Exposure | 120–180 seconds |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | No filter |

---

# 4. Exposure Time

## 180 Seconds

Recommended for:

- Dark sky
- Faint outer regions
- Galaxy halo

---

## 60–120 Seconds

Useful when:

- Bright sky
- Bright core

---

# 5. Number of Frames

Galaxies benefit strongly from integration.

Minimum:

```

30 lights

```

Good:

```

50–100 lights

```

Very good:

```

150+

```

---

# 6. Filter Selection

## No Filter

Standard.

Why:

Galaxies emit broadband light.

A filter reduces:

- Star colors
- Galaxy signal

---

## Dual-band

Not recommended.

Exception:

If also contains:

- H-II regions
- Emission areas

Example:

M31 with H-II regions.

---

# 7. Preparation in Siril

Folders:

```

M31/

lights/

darks/

output/

```

---

# 8. Create Sequence

Result:

```

m31_light_.seq

```

Check:

- All images present
- Galaxy visible
- No bad frames

---

# 9. Master Dark

Recommendation:

```

Median

```

Why:

- Removes hot pixels
- Reduces sensor pattern

---

# 10. Calibration

## Dark

Yes

---

## Flat

Recommended if available.

Helps with:

- Vignetting
- Dust
- Uneven illumination

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

# 12. Galaxy Peculiarity

Galaxies contain fewer stars than star fields.

Problems:

- Few reference stars
- Faint outer regions

---

If problems occur:

Reduce minimum star pairs:

Standard:

```

10

```

Alternative:

```

5

```

---

# 13. Stacking

Recommendation:

```

Winsor Sigma

```

Why:

- Removes satellites
- Removes airplanes
- Protects faint details

---

# Normalization

Recommendation:

```

Additive + Scaling

```

For different conditions:

```

Additive + Multiplicative

```

---

# RGB Weighting

Recommendation:

```

Off

```

Reason:

PCC comes later.

---

# 14. Background Correction

One of the most important steps.

Galaxies often sit against uneven sky.

Causes:

- Light pollution
- Moon
- Sensor gradients

---

# GraXpert

Excellent suited.

But:

The galaxy must not be removed as gradient.

---

Recommendation:

- Many control points outside galaxy
- No points directly on galaxy

---

# 15. Typical M31 Error

Andromeda is very large.

Problem:

GraXpert may recognize the outer halo as background.

Result:

The halo disappears.

---

Solution:

- Less aggressive correction
- Protect galaxy center
- Check before/after

---

# 16. PCC

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

# 17. Color Management

Galaxies have natural colors.

Typical:

## Core

Yellowish

Because:

- Old stars

---

## Spiral Arms

Bluish

Because:

- Young stars

---

## Dust Lanes

Dark

---

Not:

Make it too blue or too colorful.

---

# 18. Denoising

Galaxies are sensitive.

Recommendation:

```

0.03–0.08

```

---

Not:

```

0.1+

```

without checking.

Why:

- Dust lanes disappear
- Halo loses structure

---

# 19. Stretching

The most important creative step.

Goal:

- Make galaxy visible
- Preserve background

---

Recommendation:

Many small steps.

```

Stretch

↓

Check

↓

Stretch

↓

Check

```

---

# 20. Core Control

Many galaxies have a bright core.

Problem:

Core saturates.

---

Solution:

HDR:

Short series:

```

10–30 seconds

```

+

Long series:

```

180 seconds

```

---

# 21. Sharpening

Optional.

Suitable:

- Light structure enhancement

Not:

Strong sharpening.

Problem:

- Dark halos
- Artificial details

---

# 22. Typical Errors

## Galaxy disappears after GraXpert

Cause:

Background correction too aggressive.

---

## Image turns gray

Cause:

Over-neutralization.

---

## Only core visible

Cause:

Too little integration or stretching.

---

## Stars become huge

Cause:

Too much denoising or sharpening.

---

# 23. Example Workflow M31

Acquisition:

```

80 × 180 seconds

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

GraXpert cautiously

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

# 24. Quality Goal

A good galaxy image:

- Shows structure
- Preserves natural colors
- Shows faint outer regions
- Has natural background
- Contains no artificial artifacts

---

# Summary

```

120–180 seconds

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

GraXpert cautiously

↓

PCC

↓

Moderate denoising

↓

Slow stretching
```
