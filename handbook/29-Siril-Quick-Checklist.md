# Chapter 29 – Siril Quick Checklist

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Objective

This chapter is the practical quick reference for standard deep-sky processing.

When the details from previous chapters are not needed:

This checklist covers 90% of all Dwarf mini captures.

---

# 1. Before Processing Check

## Folder

```

Object/

├── lights/
├── darks/
├── flats/
└── output/

```

---

## Capture Quality

Check:

- Stars round?
- Focus correct?
- No clouds?
- Enough Lights?
- Correct filter?

---

# 2. Standard Deep-Sky Workflow

## Step 1 – Create Sequence

Siril:

```

File

↓

Create Sequence

```

Parameters:

```

Format:
FITS

Debayer:
active

CFA:
automatic

```

---

# Step 2 – Calibration

Use:

```

Dark:
yes

Flat:
if available

Bias:
optional

```

---

Master:

```

Median

```

---

# Step 3 – Registration

Menu:

```

Registration

↓

General Deep Sky

```

Parameters:

```

Transformation:
Homography

Star Pairs:
10

Max Stars:
500

Luminance:
active

Distortion:
off

```

---

# Step 4 – Stack

Recommendation:

```

Winsor Sigma Clipping

```

---

Parameters:

```

Normalization:

Additive + Scaling

```

---

Result:

```

stacked FITS

```

---

# Step 5 – Correct Background

Option A:

Siril:

```

Background Extraction

```

or

Option B:

GraXpert.

---

Recommendation:

Do not use both aggressively.

---

# Step 6 – Color

Siril:

```

Photometric Color Calibration

```

then:

```

Green Noise Removal

```

---

# Step 7 – Stretch

Recommendation:

Order:

```

Asinh Stretch

↓

Histogram

↓

Curves

```

---

Goal:

- Nebula visible
- Background preserved
- Stars not blown out

---

# Step 8 – Export

For GIMP:

```

TIFF 16-bit

```

---

# 3. Object-Dependent Adjustments

---

# Galaxy

Examples:

- M31
- M33

Additionally:

```

stretch carefully

protect core

```

---

# Emission Nebula

Examples:

- M42
- Heart Nebula

Additionally:

```

Dualband possible

preserve colors

```

---

# Reflection Nebula

Examples:

- M45

Additionally:

```

no filter

GraXpert very cautiously

```

---

# Star Cluster

Examples:

- M13

Additionally:

```

do not enlarge stars

```

---

# 4. If Something Doesn't Fit

## Green

```

PCC

↓

Green Noise Removal

```

---

## Background Too Bright

```

Background Extraction

↓

less stretch

```

---

## Nebula Disappears

```

Reduce GraXpert

↓

check black point

```

---

## Stars Too Large

```

less stretch

↓

shorter exposure

```

---

# 5. Minimal Workflow Without Extras

If it needs to be quick:

```

Sequence

↓

Dark

↓

Registration

↓

Winsor Stack

↓

PCC

↓

Asinh Stretch

↓

TIFF

```

---

# 6. Quality Control Before GIMP

The Siril result should:

- be correctly oriented
- have natural colors
- have no strong color cast
- contain visible detail

---

Do not repair in GIMP:

- wrong calibration
- wrong registration
- poor raw data

---

# 7. Standard Dwarf mini Parameters

As starting point:

```

Exposure:
180 seconds

Gain:
35

Filter:
no filter

Lights:
200

Darks:
20

Flat:
yes

```

Siril:

```

Debayer:
active

Dark:
Median

Flat:
Median

Registration:
Deep Sky

Stack:
Winsor Sigma

Normalization:
Additive + Scaling

PCC:
yes

Export:
TIFF 16-bit

```

---

# 8. The 10 Most Important Rules

1. Good raw data is more important than processing.

2. Many Lights reduce noise.

3. Darks improve quality.

4. Flats must be correct.

5. Do not stretch too aggressively.

6. Do not make background black.

7. PCC before color adjustments.

8. Use GraXpert cautiously.

9. Protect stars.

10. Always keep original data.

---

