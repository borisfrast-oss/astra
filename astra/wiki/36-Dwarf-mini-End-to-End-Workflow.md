# Chapter 36 – Dwarf mini Long-term Workflow: From First Capture to Final Archive Image

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Goal

This chapter describes the complete workflow of an astrophotography session.

From the moment of planning:

```

"I want to photograph M31"

```

to the final archive image:

```

M31_final.xcf

*

M31_final.tif

*

M31_final.jpg

```

---

# 1. Complete Workflow Overview

The entire process:

```

Planning

↓

Capture with Dwarf mini

↓

Secure data

↓

Siril processing

↓

Remove gradients

↓

Color correction

↓

Stretch

↓

GIMP editing

↓

Export

↓

Archiving

```

---

# 2. Phase 1 – Target Planning

Before capturing, clarify:

## Target

Example:

```

M31 Andromeda Galaxy

```

---

## Conditions

Check:

- Visible?
- Height above horizon?
- Moon?
- Light pollution?

---

## Capture Plan

Example:

```

Target:
M31

Exposure:
180 seconds

Gain:
35

Filter:
No filter

Goal:
200 lights

```

---

# 3. Phase 2 – Dwarf mini Preparation

Before starting:

Checklist:

```

☐ Battery charged

☐ Storage available

☐ App connected

☐ Location chosen

☐ Target found

☐ Focus checked

☐ Filter checked

```

---

# 4. Phase 3 – Test Capture

Never start multiple hours of capture immediately.

Check first image.

---

Checks:

## Stars

Good:

```

Small round points

```

---

Bad:

```

Trails

Disks

Blurry

```

---

## Histogram

Not:

Completely left.

Not:

Completely right.

---

# 5. Phase 4 – Capture Lights

Standard:

```

180 seconds

Gain 35

200 images

```

---

During capture:

Monitor:

- Connection
- Weather
- Progress

---

Don't change:

- Focus
- Location
- Filter

---

# 6. Phase 5 – Capture Darks

After the lights:

Same settings:

```

Exposure:

180 seconds

Gain:

35

```

---

Recommendation:

```

20 darks

```

---

# 7. Phase 6 – Data Organization

Create folders:

```

M31/

├── raw/

│   ├── lights/

│   ├── darks/

│   └── flats/

│

├── siril/

├── graxpert/

├── gimp/

└── export/

```

---

# 8. Phase 7 – Siril Processing

## Step 1

Create sequences.

```

Lights

↓

lights.seq

Darks

↓

darks.seq

```

---

## Step 2

Create dark master.

```

Darks

↓

Median Stack

↓

master_dark

```

---

## Step 3

Calibrate lights.

```

Lights

*

Master Dark

↓

Calibrated lights

```

---

## Step 4

Registration.

Settings:

```

Deep Sky

Global Star Alignment

Homography

```

---

Result:

All stars aligned.

---

## Step 5

Stack.

Recommendation:

```

Winsor Sigma Clipping

```

---

Normalization:

```

Additive + Scaling

```

---

Result:

```

M31_stack.fit

```

---

# 9. Phase 8 – Technical Image Correction

## Background

Siril:

```

Background Extraction

```

---

Goal:

Remove:

- Light gradient
- Uneven brightness

---

Then:

```

Photometric Color Calibration

```

---

Then:

```

Green Noise Removal

```

---

# 10. Phase 9 – Stretch

Now the image becomes visible.

---

Order:

```

Asinh Stretch

↓

Histogram Transformation

↓

Curves

```

---

Goal:

- Galaxy visible
- Background preserved
- Stars controlled

---

# 11. Phase 10 – GraXpert

Optional.

Usage:

If:

- Gradient present
- City light
- Moon

---

Workflow:

```

Siril TIFF/FITS

↓

GraXpert

↓

Save new version

```

---

Rules:

Not aggressive.

---

# 12. Phase 11 – GIMP Editing

Import:

```

TIFF 16-bit

```

---

Layer structure:

```

Original

↓

Color

↓

Contrast

↓

Local adjustments

↓

Export

```

---

Editing:

## Colors

Adjust lightly.

---

## Contrast

Increase gently.

---

## Saturation

Small steps.

---

## Sharpening

Minimal.

---

# 13. Phase 12 – Export

Archive:

```

M31_master.tif

```

---

Editing:

```

M31_final.xcf

```

---

Web:

```

M31_final.jpg

```

---

# 14. Phase 13 – Archiving

Save:

```

Original data

*

Siril project

*

GIMP project

*

Final images

```

---

# 15. Quality Check

Before publishing:

Check:

---

## Stars

Are they:

- Round?
- Natural?
- Not burned out?

---

## Colors

Are they:

- Believable?
- Not extremely saturated?

---

## Background

Is it:

- Dark?
- But not black?

---

## Details

Are visible:

- Nebula structures?
- Dust lanes?
- Stars?

---

# 16. Avoid Mistakes

Don't:

```

Delete raw data

↓

Save JPEG

↓

Lose original

```

---

Don't:

```

Over-process

↓

Destroy details

```

---

# 17. Personal Standard Workflow

The ideal Dwarf mini routine:

```

Choose target

↓

180s / Gain 35

↓

200 lights

↓

20 darks

↓

Siril standard workflow

↓

PCC

↓

Green Removal

↓

Asinh Stretch

↓

GraXpert if needed

↓

GIMP

↓

Archive

```

---

# 18. Learning Strategy

Don't process every image to the maximum.

Better:

Compare.

Example:

```

Version 1:
Natural

Version 2:
Stronger nebula

Version 3:
Starless

```

---

This helps develop a feel for:

- Good stretching
- Colors
- Details
- Data limits

---

# 19. Final Goal

A good Dwarf mini image is not the one with:

- Maximum brightness
- Maximum saturation
- Maximum contrast

But rather:

```

A natural image

With as many real details as possible

```
