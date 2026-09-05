# 25 – GIMP Astrophotography Workflow

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Objective

This chapter describes the final processing of images created in Siril using GIMP 3.2.4.

Siril delivers:

- Calibrated image
- Registered image
- Stacked image
- Color-corrected signal

GIMP handles creative final processing:

- Contrast
- Colors
- Local adjustments
- Layers
- Masks
- Combinations

---

# 1. Basic Principle

Task division:

```

Dwarf mini

↓

Raw data

↓

Siril

Technical processing

↓

GraXpert

Gradients

↓

GIMP

Aesthetic processing

```

---

# 2. Export from Siril

Recommended:

```

TIFF 16-bit

```

---

Do not use:

```

JPEG

```

Why:

JPEG removes:

- Color information
- Weak details
- Dynamic range

---

# 3. Open Image

In GIMP:

```

File

↓

Open

```

---

On import:

Check color space.

Recommendation:

```

RGB

```

---

# 4. First Analysis

Do not change anything yet.

Check:

- Histogram
- Background
- Stars
- Colors
- Nebula structures

---

Questions:

## Is signal present?

If yes:

Continue.

---

## Is background poor?

Then go back to:

- Siril
- GraXpert

Do not repair everything in GIMP.

---

# 5. Layer Structure

Recommended structure:

```

Astroimage

├── Original
│
├── Color correction
│
├── Contrast
│
├── Stars
│
├── Nebula
│
└── Export

```

---

Basic rule:

Never work directly on the original.

---

# 6. Histogram

Menu:

```

Colors

↓

Levels

```

---

Objective:

- Set black point
- Increase dynamic range

---

## Black Point

Do not move too far right.

Too much:

- Faint nebulae disappear

---

## White Point

Do not blow out stars.

---

# 7. Curves

Menu:

```

Colors

↓

Curves

```

---

Very important for astrophotography.

---

Typical adjustment:

Light S-curve:

```

Darken dark areas slightly

Brighten light areas slightly

```

---

Do not overdo it.

---

# 8. Color Correction

Menu:

```

Colors

↓

Color Balance

```

---

Typical corrections:

## Too Green

Reduce:

- Green

Or:

- Increase magenta slightly

---

## Too Blue

For reflection nebulae:

Reduce carefully.

---

## Too Red

For H-alpha:

Not automatically wrong.

---

# 9. Saturation

Menu:

```

Colors

↓

Saturation

```

---

Recommendation:

Small steps.

Example:

```

+10 to +30

```

---

Do not:

Maximum saturation.

---

# 10. Edit Stars

Stars are often the limiting factor.

Problems:

- Too large
- Too bright
- Overwhelm nebula

---

Options:

## Method 1

Star reduction using layers.

---

## Method 2

Starless workflow.

---

# 11. Starless Workflow

Objective:

Process nebula separately.

---

Workflow:

```

Original

↓

Star removal

↓

Nebula layer

↓

Star layer

↓

Merge

```

---

Benefits:

- More nebula contrast
- Less star overwhelm

---

# 12. Enhance Nebula

Suitable tools:

## Layer Mode

```

Soft light

```

Or:

```

Overlay

```

---

## Masks

Process only nebula areas.

---

Do not:

Boost entire image maximally.

---

# 13. Local Contrast

Tools:

- Clarity
- Unsharp mask
- High-pass

---

Very careful.

---

Too much:

- Artificial structures
- Hard stars

---

# 14. Denoising in GIMP

Only if necessary.

---

Better:

First in Siril.

---

GIMP:

```

Filter

↓

Noise

↓

Despeckle

```

---

Strength:

Keep low.

---

# 15. Sharpen

For deep sky:

Little.

---

Suitable:

```

Unsharp mask

```

---

Typical values:

Radius:

```

1–3 pixels

```

Strength:

```

Small

```

---

Do not sharpen:

- Background
- Noise

---

# 16. HDR Technique with GIMP

For:

- M42
- Bright galaxy cores
- Moon

---

Workflow:

```

Open short exposure

↓

Long exposure as layer

↓

Create mask

↓

Combine bright areas

```

---

# 17. Mosaics in GIMP

GIMP can create simple mosaics.

---

Workflow:

```

File

↓

Open as layers

↓

Align images

↓

Use masks

↓

Merge

```

---

Suitable for:

- Large nebulae
- Milky Way
- Moon panoramas

---

For many individual images:

Better:

- Siril mosaic
- Specialized astrophotography software

---

# 18. Create Collages

For image collections:

Example:

- M31
- M42
- M45
- Moon

---

Workflow:

```

New file

↓

Choose size

↓

Open images as layers

↓

Scale

↓

Position

↓

Add text

```

---

# 19. Export

For archive:

```

TIFF 16-bit

```

---

For internet:

```

JPEG

```

---

Recommendation:

Always keep:

```

Master TIFF

*

Edited version

```

---

# 20. Example Workflow Deep Sky

Complete:

```

Open Siril TIFF

↓

Create layer copy

↓

Histogram

↓

Curves

↓

Correct color

↓

Increase saturation slightly

↓

Check stars

↓

Local contrast

↓

Export

```

---

# 21. Example Workflow Emission Nebula

```

Siril TIFF

↓

Color correction

↓

Saturation

↓

Enhance nebula layer

↓

Reduce stars

↓

Contrast

↓

Export

```

---

# 22. Example Workflow Star Field

```

Siril TIFF

↓

Color correction

↓

Stars sharpen slightly

↓

Contrast

↓

Export

```

---

# 23. Common GIMP Errors

## Image Looks Artificial

Causes:

- Too much saturation
- Too much contrast
- Too much sharpening

---

## Nebula Looks Flat

Causes:

- Background too dark
- No local processing

---

## Stars Dominate

Solution:

- Star reduction
- Process nebula separately

---

# 24. Quality Goal

A good final astrophoto:

- Natural colors
- Visible weak structures
- No artifacts
- Harmonious background
- Controlled stars
