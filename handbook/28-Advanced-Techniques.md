# Chapter 28 – Advanced Techniques

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Objective

This chapter describes advanced techniques beyond the standard Dwarf mini workflow.

These methods are particularly interesting once the basics work reliably.

Topics:

- HDR Deep Sky
- Starless Processing
- Process stars separately
- Dualband HOO
- combine multiple exposures
- Mosaics
- combine multiple sessions

---

# 1. HDR Deep Sky

## Objective

The dynamic range of many astronomical objects is larger than a single exposure can represent.

Examples:

- M42 Orion Nebula
- M31 Andromeda Galaxy
- bright globular clusters
- Moon with shadow regions

---

# 1.1 Basic Principle

One exposure provides:

```

faint outer regions

```

A second exposure provides:

```

bright core regions

```

Both are combined.

---

Example:

```

Long exposure

180 seconds

↓

Nebula details

Short exposure

5–20 seconds

↓

Core structure

↓

HDR combination

```

---

# 1.2 Siril Workflow

For both series separately:

```

Create sequence

↓

Calibrate

↓

Register

↓

Stack

↓

Export TIFF

```

---

Then:

```

GIMP

↓

open both images as layers

↓

create mask

↓

combine

```

---

# 1.3 Typical Mistakes

## Core Still Blown Out

Causes:

- Short exposure too long
- Mask incorrect

---

## Transition Visible

Solution:

- use soft mask
- make transition large

---

# 2. Starless Processing

## Objective

Process stars and object separately.

Advantages:

- enhance nebula more
- control stars
- less overexposure

---

# 2.1 Basic Principle

Starting point:

```

Image

↓

Remove stars

↓

Starless image

*

Star mask

```

---

Then:

```

Process nebula

↓

Process stars separately

↓

Combine

```

---

# 2.2 Advantages

Particularly suitable for:

- Emission nebulae
- large nebulae
- faint structures

---

Examples:

- Heart Nebula
- Rosette Nebula
- Veil Nebula

---

# 2.3 Nebula Processing

Starless image allows:

- stronger contrast
- stronger color adjustment
- local processing

without:

enlarging stars.

---

# 2.4 Star Processing

Separate layer:

Possibilities:

- reduce brightness
- adjust saturation
- reduce size

---

# 3. Dualband HOO Workflow

## Objective

Create a natural color palette from dualband data.

---

HOO means:

```

H-alpha → Red

OIII → Green + Blue

```

---

# 3.1 Image Capture

Suitable for:

- Heart Nebula
- Rosette Nebula
- Eagle Nebula
- Veil Nebula

---

Recommendation:

```

180 seconds

Gain 40

Dualband

200–500 Lights

```

---

# 3.2 Siril Preparation

Standard:

```

Calibration

↓

Registration

↓

Stack

```

---

# 3.3 Channel Work

Goal:

Emphasize H-alpha:

```

Red channel

```

---

OIII:

```

Blue channel

*

Green channel

```

---

# 3.4 Color Management

Not every image needs extreme HOO.

Goal:

natural colors.

---

Avoid:

- toxic green
- extreme red

---

# 4. Combining Different Exposures

## Objective

More dynamic range and better detail.

---

Example:

```

30 seconds

*

180 seconds

*

300 seconds

```

---

Suitable for:

- bright nebulae
- Galaxies
- Star clusters

---

# 4.1 Siril

Each series separately:

```

Calibrate

↓

Stack

```

---

Afterward:

Combination in:

- GIMP
- Photoshop
- similar software

---

# 5. Combining Multiple Sessions

## Objective

More integration time.

Example:

Night 1:

```

100 × 180s

```

---

Night 2:

```

150 × 180s

```

---

Total:

```

250 Lights

```

---

# 5.1 Requirements

Keep the same:

- Focus
- Exposure
- Gain
- Filter

---

# 5.2 Siril Workflow

All Lights together:

```

Create sequence

↓

Calibrate

↓

Register

↓

Stack

```

---

Advantage:

less noise.

---

# 6. Mosaics

## Objective

Capture larger objects.

Examples:

- large nebulae
- Moon panorama
- Milky Way

---

# 6.1 Image Planning

Individual images must:

- overlap
- have the same settings

---

Recommendation:

Overlap:

```

20–30%

```

---

# 6.2 Workflow

Individual fields:

```

Capture

↓

stack each field

```

---

Then:

```

Assemble mosaic

```

---

# 6.3 GIMP Mosaic

Suitable for small projects.

Procedure:

```

Create new large canvas

↓

open images as layers

↓

align

↓

create masks

↓

merge

```

---

# 6.4 Professional

For large mosaics:

use:

- Siril mosaic functions
- specialized astro software

---

# 7. Enhance Stars Separately

## Problem

Dwarf data can show small stars.

---

Possibilities:

## Color Boost

Saturate stars slightly.

---

## Size Control

Reduce stars.

---

## Sharpening

Sharpen stars only.

---

Not:

Sharpen entire image heavily.

---

# 8. Local Contrast Enhancement

Goal:

Emphasize structures.

---

Suitable for:

- Galaxy arms
- Nebular filaments
- Lunar craters

---

Tools:

- Layers
- Masks
- local curves

---

# 9. Multiple Color Combinations

Examples:

RGB:

```

Red

Green

Blue

```

---

Dualband:

```

H-alpha

OIII

```

---

Planet:

```

RGB channels

```

---

# 10. Reference Images and Comparison

Advanced processing means:

not just making it prettier.

Compare:

- Original
- Version 1
- Version 2

---

Questions:

- Are more details visible?
- Are colors believable?
- Have artifacts appeared?

---

# 11. Typical Advanced Workflow

```

Dwarf capture

↓

Siril standard workflow

↓

Stack

↓

PCC

↓

GraXpert

↓

Create starless

↓

Process nebula

↓

Process stars

↓

Combine

↓

GIMP finalization

```

---

# 12. Common Mistakes in Advanced Processing

## Overly Artificial Colors

Cause:

too much saturation.

---

## Black Background

Cause:

black point too aggressive.

---

## No More Stars

Cause:

Starless combined incorrectly.

---

## Plastic Look

Causes:

- too much sharpening
- too much contrast
- too strong denoising

---

# 13. When to Use These Techniques?

Not every image needs everything.

---

Simple:

```

Stack

↓

PCC

↓

Stretch

↓

GIMP

```

often sufficient.

---

Advanced:

when:

- Signal present
- Workflow reliable
- Object suitable

---

# 14. Quality Goal

An advanced-processed image:

- shows more detail
- remains natural
- retains stars
- uses dynamic range
- avoids artifacts

---




## CFA-Drizzle (V19)

- Scale 2.0, `CFA_DEFAULTS` vs `DEBAYERED` star_count threshold, mode `auto`.
- Auto quality gate: uses CFA-adjusted defaults when `is_cfa=True`.
- Evidence: M31 60/90/120s → Drizzle 3840×2160 instead of fallback.

