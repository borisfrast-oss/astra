# Workflow 06 – Emission Nebulae

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing emission nebulae with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- M42 Orion Nebula
- NGC 7000 North America Nebula
- IC 434 Horsehead Nebula
- Rosette Nebula
- Lagoon Nebula M8
- Swan Nebula M17

Emission nebulae are among the most spectacular deep-sky objects.

They differ from galaxies:

- They are more diffuse
- They contain gas structures
- They respond strongly to filters
- Colors are essential

---

# 1. Emission Nebula Properties

Emission nebulae glow through ionized gas.

Important emissions:

| Line | Color | Source |
|---|---|---|
| H-alpha | Red | Hydrogen |
| OIII | Cyan | Oxygen |
| SII | Red | Sulfur |

A normal color sensor can record these ranges.

A dual-band filter can increase contrast.

---

# 2. Acquisition Recommendation

## Without Filter

| Parameter | Recommendation |
|---|---|
| Exposure | 180 seconds |
| Gain | 40 |
| Lights | 50–100+ |
| Darks | 10–20 |

---

## With Dual-band Filter

Recommendation:

| Parameter | Value |
|---|---|
| Exposure | 180 seconds |
| Gain | 40 |
| Lights | As many as possible |
| Darks | Matching exposure |

---

# 3. Filter Selection

> **V19-FIX-13 Duo-Band:** As in Ch. 08 §14a — Duo-Band + `nebula_standard` (PCC off, SCNR on). For details see Ch. 08. With `star_standard` + Duo-Band + PCC the image turns pink (C19 R/G 1.608 vs 1.006 with nebula_standard) — evidence v19 suite 2026-09-02.

## No Filter

Advantages:

- Natural colors
- More stars
- More total signal

Suitable for:

- Dark sky
- Bright nebulae

---

## Dual-band Filter

Advantages:

- Better nebula structures
- Less light pollution
- Stronger contrast

Disadvantages:

- Fewer stars
- Changed colors
- Longer exposure needed

---

# 4. Acquisition Planning

Emission nebulae benefit strongly from many frames.

Recommendation:

Minimum:

```

30 frames

```

Better:

```

60–100 frames

```

---

# 5. Preparation in Siril

Folders:

```

NGC7000/

lights/

darks/

output/

```

---

# 6. Create Sequence

Result:

```

ngc7000_light_.seq

```

Check:

- All images present
- No cloudy images
- Focus sufficient

---

# 7. Master Dark

## Method

Recommendation:

```

Median

```

Reason:

- Removes random noise
- Preserves sensor pattern

---

# 8. Calibration

Enable:

## Dark

Yes

---

## Flat

Optional.

Useful when:

- Dust
- Vignetting
- Filter change

---

## Bias

Usually:

No

---

# 9. Registration

Menu:

Registration

---

## Selection

Use:

```

General Deep Sky

```

---

## Parameters

| Parameter | Value |
|---|---|
| Transformation | Homography |
| Minimum star pairs | 10 |
| Luminance | Active |
| Maximum stars | 500 |
| Distortion removal | Off |

---

# 10. Nebula Peculiarity

Nebula surfaces contain fewer sharp structures than galaxies.

Star registration can be more difficult.

If problems occur:

- Allow more stars
- Reduce minimum star pairs
- Remove bad frames

---

# 11. Stacking

Recommendation:

```

Winsor Sigma

```

Why:

- Removes satellites
- Removes airplanes
- Reduces outliers

---

# Normalization

Recommendation:

```

Additive

```

Sufficient for identical Dwarf acquisitions.

---

# RGB Weighting

Recommendation:

```

Off

```

Reason:

PCC handles color correction later.

---

# 12. Background Correction

Emission nebulae are sensitive to incorrect background correction.

Recommendation:

Use GraXpert carefully.

---

# Danger

Overly aggressive background removal can remove:

- Faint nebula regions
- Halos
- Diffuse structures

---

# 13. GraXpert Recommendation

Start:

- Few samples
- Gentle correction

Check:

Before:

```

Nebula + background

```

After:

```

Nebula preserved?

```

---

# 14. PCC Color Calibration

After background correction.

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

# 15. Dual-band Color Problems

Typical:

- Very red images
- Greenish stars
- Few stars

This is normal.

Don't correct immediately.

---

# 16. Stars with Dual-band

Dual-band often reduces star signal.

Possible solution:

Separate acquisition:

```

RGB without filter

*

Dual-band nebula image

```

Combine.

---

# 17. Denoising

With nebulae be careful.

Recommendation:

```

0.05

```

to:

```

0.1

```

---

Not:

```

Strong denoising

```

Why?

Diffuse structures are sensitive.

---

# 18. Stretching

Goal:

Make visible:

- Gas structures
- Color gradients
- Fine details

---

Recommendation:

Many small steps.

Not:

```

Maximum stretch

```

---

# 19. Typical Errors

## Nebula disappears after GraXpert

Cause:

Background correction too strong

Solution:

Correct less aggressively

---

## Image too red

Causes:

- H-alpha dominant
- Dual-band
- Wrong stretching

Solution:

PCC and careful color correction

---

## Stars green

Cause:

Bayer color processing

Solution:

PCC then optionally SCNR

---

## Too little nebula visible

Causes:

- Too little integration
- Exposure too short
- Bright sky

Solution:

Collect more lights

---

# 20. Example Workflow M42

Acquisition:

```

50 × 180 seconds
Gain 40

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

# 21. HDR for Bright Nebulae

Useful for M42.

Problem:

The core is very bright.

Solution:

Two acquisition series:

Long:

```

180 seconds

```

For:

- Outer nebula

Short:

```

10–30 seconds

```

For:

- Core region

Then:

```

Long exposure as main image

*

Short exposure as core

```

Combine.

---

# 22. Quality Goal

A good emission nebula image:

- Shows fine gas structures
- Keeps natural colors
- Has no artificially black background
- Contains stars with natural size
- Shows details without over-sharpening

---

# Summary

```

180 seconds

Gain 40

50–100 lights

10–20 darks

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

Moderate stretching

```
