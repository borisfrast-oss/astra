# Chapter 33 – Final Dwarf mini + Siril 1.4.4 Reference Parameters

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Objective

This chapter is the central reference for recommended standard values.

It contains:

- Dwarf mini capture parameters
- Siril 1.4.4 processing
- GraXpert settings
- GIMP workflow
- Object-dependent adjustments

If no special requirements exist, this workflow can be used as a standard.

---

# 1. Dwarf mini Standard Capture

## Deep Sky Standard

Suitable for:

- Galaxies
- Nebulae
- Star clusters

---

Recommended values:

```

Exposure time:
180 seconds

Gain:
35

Filter:
no filter

Lights:
200+

Darks:
20+

Flats:
if possible

```

---

# 2. Emission Nebula Standard

Suitable for:

- M42
- IC1805
- IC1848
- Rosette Nebula
- Veil Nebula

---

Settings:

```

Exposure:
180 seconds

Gain:
40

Filter:
Dual-band

Lights:
200–500

```

---

# 3. Galaxies Standard

Suitable for:

- M31
- M33
- M51
- M101

---

Settings:

```

Exposure:
180 seconds

Gain:
30–35

Filter:
no filter

Lights:
200+

```

---

# 4. Star Clusters Standard

Suitable for:

- M13
- M3
- M5

---

Settings:

```

Exposure:
30–90 seconds

Gain:
10–30

Filter:
no filter

Lights:
100+

```

---

# 5. Siril 1.4.4 Workflow Reference

---

# 5.1 Create Sequence

Menu:

```

File

↓

Create sequence

```

---

Parameters:

```

File type:
FITS

Debayer:
active

CFA:
automatic

Memory:
16-bit

```

---

# 5.2 Calibration

## Dark

Recommendation:

```

Master Dark:
yes

```

Creation:

```

Stack:
Median

```

---

## Flat

Recommendation:

```

Master Flat:
if available

```

Stack:

```

Median

```

---

## Bias

With Dwarf mini:

```

optional

```

---

# 5.3 Registration

Menu:

```

Registration

↓

Deep Sky

```

---

Standard values:

```

Method:
Global Star Alignment

Transformation:
Homography

Star search:
automatic

Max stars:
500

Minimal stars:
10

```

---

Options:

```

Use luminance:
active

Drizzle:
off

```

---

# 5.4 Stack

Recommendation:

```

Winsorized Sigma Clipping

```

---

Parameters:

```

Normalization:
Additive + Scaling

Weighting:
Signal weighting

Rejection:
active

```

---

Alternative:

With few images:

```

Median

```

---

# 5.5 Background Correction

Siril:

```

Editing

↓

Background Extraction

```

---

Recommendation:

```

Degree:
1–2

Samples:
only true background

```

---

Do not use on:

- Nebulae
- Galaxies
- Bright structures

---

# 5.6 Color Calibration

Recommendation:

```

Photometric Color Calibration

```

---

Prerequisites:

- Stars visible
- Correct object position
- Internet access for star catalog

---

Afterwards:

```

Green Noise Removal

```

---

# 5.7 Stretch

Recommended order:

```

Asinh Stretch

↓

Histogram Transformation

↓

Curves

```

---

Basic rule:

Do not maximize brightness.

---

# 6. GraXpert Standard Parameters

---

# Background Correction

Recommendation:

```

Model:
Degree 1–2

Strength:
moderate

```

---

Points:

Only:

```

Dark background

```

---

Not:

```

Object structures

```

---

# Denoise

Standard:

```

off

```

or:

```

minimal

```

---

Reason:

Preserve signal.

---

# 7. GIMP Standard Workflow

---

# Layers

Recommendation:

```

Original

↓

Color correction

↓

Contrast

↓

Local adjustments

↓

Export

```

---

# Values

## Saturation

Typical:

```

+10 to +30

```

---

## Sharpening

Unsharp mask:

```

Radius:
1–3 pixels

Strength:
low

```

---

## Contrast

Moderate adjustment.

---

# 8. Object-Dependent Adjustments

---

# M31

Additionally:

```

Protect core

Stretch slowly

HDR optional

```

---

# M42

Additionally:

```

Capture short exposure

Combine HDR

```

---

# M45

Additionally:

```

GraXpert very carefully

No aggressive background removal

```

---

# Cirrus Nebula

Additionally:

```

Very many lights

Gentle stretch

```

---

# Galaxies

Additionally:

```

Preserve stars

Enhance dust bands

```

---

# 9. Quality Control

Before export check:

---

## Stars

Good:

```

Small

Round

Colorful

```

---

Poor:

```

White spots

Blown out

Too large

```

---

## Background

Good:

```

Dark

But not black

```

---

## Colors

Good:

```

Natural

Object-dependent

```

---

# 10. Recommended Complete Workflow

```

Dwarf mini capture

↓

Secure lights

↓

Create darks

↓

Siril sequence

↓

Calibration

↓

Registration

↓

Winsor Sigma stack

↓

Background extraction

↓

PCC

↓

Green noise removal

↓

Asinh stretch

↓

GraXpert

↓

GIMP

↓

TIFF/XCF export

↓

Archiving

```

---

# 11. Minimal Workflow for Quick Results

If little time is available:

```

Sequence

↓

Calibrate

↓

Register

↓

Stack

↓

PCC

↓

Stretch

↓

Export

```

---

# 12. My Personal Dwarf mini Reference Values

Standard:

```

180 seconds

Gain 35

200 lights

20 darks

No filter

Winsor Sigma

PCC

Asinh stretch

TIFF 16-bit

```

---

Emission nebulae:

```

180 seconds

Gain 40

Dual-band

300 lights

```

---

Star clusters:

```

60 seconds

Gain 20

100 lights

```

---

# 13. Golden Rules

1. More lights beat aggressive processing.

2. Good calibration improves every image.

3. PCC first, creative colors later.

4. Never completely remove background.

5. Stars are part of the image.

6. Naturalness is more important than maximum visibility.

7. Always keep original data.


