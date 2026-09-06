# Chapter 21 – Siril 1.4.4 Parameter Reference

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This chapter serves as technical reference for Siril 1.4.4.

It describes:

- important menus
- parameters
- default values
- recommended values for Dwarf mini

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

- when changes make sense

Basic rule:

**Siril defaults are usually correct. Only make changes when there's a specific problem.**

---

# 1. General Siril Workflow

Standard Deep-Sky procedure:

```

Import files

↓

Create sequence

↓

Calibrate

↓

Register

↓

Stack

↓

Post-processing

↓

Export

```

---

# 2. Create Sequence

Menu:

```

File
→ Create Sequence

```

---

# 2.1 Image Type

For Dwarf mini:

```

FITS

```

---

# 2.2 Debayer

The Dwarf mini uses a color camera.

Therefore:

```

activated

```

---

# 2.3 CFA Pattern

Depends on sensor.

Don't change manually if:

- Dwarf FITS correctly recognized

---

Problem with wrong CFA:

- wrong colors
- green image
- color shifts

---

# 2.4 Sequence Names

Recommendation:

```

m31_light
m42_light
m45_light

```

---

# 3. Conversion (Preprocessing)

Menu:

```

Conversion

```

---

# 3.1 Debayer

Recommendation:

```

activated

```

---

# 3.2 Interpolation

Standard:

```

Bilinear

```

---

Alternative:

```

VNG

```

possible for:

- finer color details

---

# 3.3 Color Correction

Usually:

```

deactivated

```

---

Apply color correction later:

- PCC
- Photometric Calibration

---

# 4. Calibration

Menu:

```

Calibration

```

---

# 4.1 Dark

Recommended:

```

activated

```

---

Master Dark method:

```

Median

```

---

Why:

- remove hot pixels
- robust against outliers

---

# 4.2 Flat

Recommended:

```

activated

```

for:

- galaxies
- nebulae
- strong stretch

---

Master Flat:

```

Median

```

---

# 4.3 Bias

Dwarf mini:

```

optional

```

---

Not strictly necessary.

---

# 4.4 Cosmetic Correction

Removes:

- remaining hot pixels

Recommendation:

```

activate when problems

```

---

# 5. Registration

Menu:

```

Registration

```

---

# 5.1 Deep Sky Method

Standard for:

- nebulae
- galaxies
- star clusters

---

Selection:

```

General (Deep Sky)

```

---

# 5.2 Transformation

Recommendation:

```

Homography

```

---

Why:

Corrects:

- rotation
- slight distortion
- scaling

---

# 5.3 Star Pairs

Standard:

```

10

```

---

Recommendation Dwarf:

```

10

```

---

Increase if problems:

```

5

```

---

# 5.4 Maximum Stars

Standard:

```

100

```

---

Recommendation:

Deep Sky:

```

300–500

```

---

Many stars:

```

200

```

---

# 5.5 Use Luminance

Recommendation:

```

activated

```

---

Improves:

- star detection
- registration

---

# 5.6 Distortion Removal

Recommendation:

```

deactivated

```

---

Only necessary for:

- large image fields
- strong distortions

---

# 6. Stack

Menu:

```

Stacking

```

---

# 6.1 Combination

## Average

Standard:

```

Often available

```

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

## Winsor Sigma Clipping

Recommendation Dwarf:

```

Winsor Sigma

```

Suitable for:

- Deep Sky
- many frames

Removes:

- Satellites
- Airplanes
- random errors

---

# 6.2 Normalization

Recommendation:

```

Additive + Scaling

```

---

Why:

Corrects:

- different brightness
- background fluctuations

---

# 6.3 Rejection

With Sigma procedure:

Standard:

```

active

```

---

Typical values:

```

2–3 Sigma

```

---

Not too aggressive:

otherwise faint details lost.

---

# 7. Background Extraction (Background Extraction)

Menu:

```

Background Extraction

```

---

Goal:

Remove:

- Light pollution
- Gradients

---

Don't remove:

- real nebula structures

---

# 7.1 Model

Recommendation:

```

Polynomial degree 1 or 2

```

---

Degree 1:

light gradients

---

Degree 2:

stronger light pollution

---

Higher degrees:

usually avoid.

---

# 7.2 Control Points

Rule:

Don't set on:

- Stars
- Nebulae
- Galaxies

---

Only:

free background

---

# 8. Photometric Color Calibration (PCC)

Menu:

```

Color Calibration
→ Photometric

```

---

Prerequisites:

- Stars present
- Internet connection for star catalog

---

Recommendation:

After:

```

Stack

↓

Background Extraction

```

---

PCC corrects:

- Color balance
- Star colors

---

# 9. Green Noise Removal

Menu:

```

Remove Green Noise

```

---

With Dwarf OSC:

often useful.

---

Recommendation:

After PCC.

---

Don't use aggressively.

---

# 10. Histogram / Stretch

Menu:

```

Histogram

```

---

Goal:

Make signal visible.

---

Parameters:

## Black Value

Careful.

Too high:

- faint details disappear

---

## Midvalue

Controls:

- brightness
- contrast

---

## White Point

Don't burn out stars.

---

# 11. Asinh Stretch

Highly recommended for Deep Sky.

Advantages:

- preserves stars
- preserves colors
- good nebula structures

---

Suitable for:

- Galaxies
- Nebulae
- Star clusters

---

# 12. Export

Recommendation:

For GIMP:

```

TIFF 16 Bit

```

---

Not:

JPEG.

---

Why:

JPEG destroys:

- Color depth
- faint details

---

# 13. Recommended Dwarf Standard Parameters

```

Debayer: active

Dark: Median

Flat: Median

Registration: Deep Sky

Transformation: Homography

Star pairs: 10

Max stars: 500

Stack: Winsor Sigma

Normalization: Additive + Scaling

Background: Polynomial 1–2

PCC: active

Export: TIFF 16 Bit

```

---

# 14. What Not to Change?

These parameters usually stay default:

- Alignment fine parameters
- Cosmetic parameters
- internal quality parameters
- file format settings

---
