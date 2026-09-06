# Chapter 34 – Siril 1.4.4 Menu Navigation

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Goal

This chapter is a practical UI cheat sheet for Siril 1.4.4.

It answers:

- Where do I find which step?
- What order makes sense?
- What settings are important?
- Which menu items are frequently needed?

---

# 1. Understanding the Siril Interface

Siril fundamentally consists of:

```

Menu bar

↓

Tool areas

↓

Image display

↓

Status information

```

---

The main areas:

```

File

Sequence

Image Processing

Registration

Stacking

Analysis

View

```

---

# 2. Set Working Folder First

Before any processing:

Menu:

```

File

↓

Select Working Directory

```

---

Recommendation:

Separate folder per target.

Example:

```

M31/

├── lights

├── darks

├── flats

└── siril

```

---

Why?

Siril generates many intermediate files.

A clean folder prevents chaos.

---

# 3. Create Sequences

Menu:

```

File

↓

Create Sequence

```

---

Usage:

Individual images become a Siril sequence.

Example:

```

light_001.fit

light_002.fit

light_003.fit

↓

lights.seq

```

---

Important settings:

```

Debayer:
active for color cameras

CFA:
automatic

```

---

For Dwarf mini:

Normally:

```

Debayer:
yes

```

---

# 4. Display Sequence

Menu:

```

Sequence

↓

Open Sequence

```

---

Check here:

- Number of images
- Quality
- Bad frames

---

Check individual images:

Don't just look at the stack.

---

# 5. Calibration

Menu:

```

Image Processing

↓

Calibration

```

---

Task:

Corrects:

- Hot pixels
- Dark current
- Vignetting

---

Requires:

## Lights

```

Object frames

```

---

## Darks

```

Same exposure

```

---

## Flats

```

Optical correction

```

---

# 6. Registration

Menu:

```

Registration

↓

Deep Sky Registration

```

---

Task:

All images aligned to the same star position.

---

Before:

```

Image 1

*

```


```

Image 2

*

```

---

After:

```

Image 1

*

Image 2

*

```

---

Recommended setting:

```

Global Star Alignment

Transformation:
Homography

```

---

# 7. Stack

Menu:

```

Stacking

↓

Stack

```

---

Task:

Multiple images combined.

---

Recommended:

```

Winsorized Sigma Clipping

```

---

Why?

Removes:

- Satellites
- Airplanes
- Random artifacts

---

# 8. Normalization

Important during stacking.

---

Recommendation:

```

Additive + Scaling

```

---

Meaning:

Adjusts images for:

- Brightness
- Background

---

# 9. Remove Background

Menu:

```

Image Processing

↓

Background Extraction

```

---

Usage:

Removes:

- Gradients
- Light pollution

---

Rule:

Place points only on background.

---

Not on:

```

Nebula

Galaxies

Stars

```

---

# 10. Color Calibration

Menu:

```

Image Processing

↓

Photometric Color Calibration

```

---

Task:

Automatic color correction.

---

Result:

- More realistic stars
- Less color cast

---

After:

```

Green Noise Removal

```

---

# 11. Stretch

Menu:

```

Image Processing

↓

Histogram Transformation

```

---

Task:

Make linear image visible.

---

Recommendation:

First:

```

Asinh Transformation

```

---

Then:

```

Histogram

```

---

Then:

```

Curves

```

---

# 12. Display Color Channels

Menu:

```

View

↓

Channels

```

---

Helpful for:

- Green problems
- Color casts
- Dual-band

---

# 13. Control Black Point

Tool:

```

Histogram

```

---

Don't do:

Move black point too far.

---

Result:

Weak nebula details disappear.

---

# 14. Save Image

Menu:

```

File

↓

Save As

```

---

For archive:

```

FITS

```

---

For GIMP:

```

TIFF 16-bit

```

---

# 15. Common Siril Errors

---

# Problem:

Image green after stack

---

Cause:

OSC color calibration.

---

Solution:

```

PCC

↓

Green Noise Removal

```

---

# Problem:

Image almost black

---

Cause:

Linear image.

---

Solution:

```

Perform stretch

```

---

# Problem:

Stars appear shifted

---

Cause:

Registration failed.

---

Check:

- Enough stars
- Correct method
- Remove bad frames

---

# Problem:

Nebula details disappear

---

Causes:

- Too aggressive background removal
- Too aggressive stretch

---

Solution:

Less processing.

---

# 16. Minimal Menu Path

The complete standard path:

```

File

↓

Working Directory

↓

Create Sequence

↓

Calibrate

↓

Register

↓

Stack

↓

Background Extraction

↓

Photometric Color Calibration

↓

Green Noise Removal

↓

Asinh Stretch

↓

Histogram

↓

Save TIFF

```

---

# 17. Most Important Siril Functions as Table

| Function | Purpose |
|---|---|
| Create Sequence | Group individual images |
| Calibration | Remove errors |
| Registration | Align images |
| Stack | Combine images |
| Normalization | Equalize brightness |
| Background Extraction | Remove gradients |
| PCC | Correct colors |
| Green Noise Removal | Remove green cast |
| Stretch | Make signal visible |
| Export TIFF | Transfer to GIMP |

---

# 18. Dwarf mini Beginner Rule

If you don't know what to change:

Don't change ten parameters.

Always follow this order:

```

Check raw data

↓

Check calibration

↓

Check stack

↓

Correct color

↓

Stretch

