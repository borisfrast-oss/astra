# Chapter 32 – Astrophotography Glossary

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Objective

This chapter explains the most important terms in astrophotography.

It serves as a reference for:

- Dwarf mini
- Siril
- GraXpert
- GIMP
- Deep-Sky processing

---

# A

## ADU (Analog Digital Unit)

Measurement value of a camera sensor.

It describes:

how much light the sensor registers.

---

A pixel value in a FITS image consists of ADU values.

Example:

```

0

↓

black

65535

↓

maximum value at 16-bit

```

---

Important:

Not every pixel should be maximally bright.

---

## Aperture

Diameter of the optical system.

Example:

```

50 mm opening

```

---

Larger aperture means:

- more light
- fainter objects possible
- higher resolution

---

## ASINH Stretch

A stretch method in Siril.

Objective:

make faint structures visible.

Advantage:

simultaneously:

- protect bright areas
- enhance faint areas

---

# B

## Bias

Calibration image with:

- Shortest exposure time
- Closed shutter

---

Usage:

Measurement of electronic baseline signal.

---

For many modern cameras:

often less important.

---

## Background Extraction (BE)

Background modeling in Siril.

Removes:

- Light gradients
- Uneven brightness

---

Does not remove:

- True nebula structures

---

## Bayer Matrix

Color filter on a color sensor.

Typical arrangement:

```

RG
GB

```

---

The sensor initially measures:

- Red
- Green
- Blue

not directly as a color image.

---

# C

## Calibration

Correction of raw data.

Typical:

```

Light

*

Dark

*

Flat

↓

calibrated image

```

---

## CFA (Color Filter Array)

Designation for the color filter structure of a sensor.

Relevant for:

OSC cameras.

---

## Clipping

Loss of image information.

---

White clipping:

Bright areas are only white.

---

Black clipping:

Dark areas are only black.

---

# D

## Dark Frame

Dark image for correction of:

- Hot pixels
- Dark current

---

Capture:

Same:

- Exposure time
- Gain
- Temperature

As lights.

---

## Debayer

Conversion of raw color image to RGB.

From:

```

Bayer pattern

```

becomes:

```

Color image

```

---

With Dwarf mini:

Usually necessary.

---

## Deep Sky

Astronomical objects outside our solar system.

Examples:

- Galaxies
- Nebulae
- Star clusters

---

# F

## FITS

Standard format in astronomy.

Stores:

- Image data
- Metadata
- Scientific information

---

Advantages:

- Lossless
- High data quality

---

## Flat Frame

Calibration image against:

- Vignetting
- Dust spots
- Uneven illumination

---

Capture:

With uniformly illuminated surface.

---

# G

## Gain

Electronic amplification of the sensor.

---

Higher gain:

Advantages:

- More signal amplification

Disadvantages:

- Less dynamic range
- More noise

---

## Gradient

Slow brightness change across the image.

Causes:

- City light
- Moon
- Scattered light

---

# H

## H-alpha

Emission line of ionized hydrogen.

Wavelength:

```

656 nm

```

---

Important for:

- Emission nebulae

---

## Histogram

Representation of brightness distribution.

Shows:

- Black point
- Midtones
- White point

---

# I

## Integration Time

Total exposure time.

Calculation:

```

Number of frames × Individual exposure

```

---

Example:

```

200 × 180 seconds

=

10 hours

```

---

More integration:

Usually:

- Less noise
- More details

---

# L

## Light Frame

Normal capture of the object.

---

The most important image type.

---

## Linear Image

Image without stretch.

---

Character:

- Dark
- Little visible

But contains:

Maximum information.

---

# M

## Master Dark

Reference image created by stacking many darks.

---

Advantage:

Less noise.

---

## Master Flat

Reference image created by stacking many flats.

---

## Median Stack

Combines images via median value.

Removes:

- Random artifacts
- Satellites partially

---

# N

## Nebula

Clouds of gas and dust.

Types:

---

Emission nebula:

Self-luminous.

Example:

M42.

---

Reflection nebula:

Reflect starlight.

Example:

M45.

---

Dark nebula:

Block light.

---

# O

## OSC (One Shot Color)

Color sensor.

One image contains:

Red, green, and blue information.

---

Dwarf mini uses an OSC sensor.

---

## OIII

Ionized oxygen signal.

Wavelength:

```

500.7 nm

```

---

Important for:

- Planetary nebulae
- Supernova remnants

---

# P

## PCC (Photometric Color Calibration)

Automatic color calibration.

Uses:

- Star colors
- Catalog data

---

Objective:

Natural color balance.

---

## Pixel Peeping

Excessive viewing of individual pixels.

Problem:

You optimize flaws instead of image quality.

---

# R

## Registration

Alignment of many images.

Stars are made congruent.

---

Necessary before:

Stacking.

---

## RGB

Color model:

```

Red

Green

Blue

```

---

# S

## SNR (Signal-to-Noise Ratio)

Signal-to-noise ratio.

---

The higher:

The better:

- Details
- Contrast
- Quality

---

## Starless

Image without stars.

---

Enables:

Separate processing of:

- Nebula
- Stars

---

## Stacking

Combination of many individual images.

---

Advantages:

- Less noise
- More details

---

## Stretch

Change of tone values.

Objective:

Make linear image visible.

---

Without stretch:

Deep-sky images appear black.

---

# T

## TIFF

High-quality image format.

Suitable for:

- GIMP
- Archive

---

Recommendation:

16-bit.

---

# V

## Vignetting

Darkening toward image corners.

---

Correction:

Flat frames.

---

# W

## Winsor Sigma Clipping

Stacking method.

Removes outliers:

- Satellites
- Aircraft
- Cosmic interference

---

# Z

## Zenith

Point directly above the observer.

---

Advantage:

- Least atmosphere
- Best image quality

---

# Common Abbreviations

| Abbreviation | Meaning |
|---|---|
| ADU | Sensor value |
| BE | Background Extraction |
| CFA | Color Filter Array |
| DSLR | Digital camera |
| FITS | Astronomical file format |
| Ha | H-alpha |
| OSC | Color camera |
| OIII | Oxygen signal |
| PCC | Photometric Color Calibration |
| RGB | Red-Green-Blue |
| SNR | Signal-to-Noise Ratio |
| TIFF | Image format |
| WBPP | Weighted Batch Preprocessing |

---

# Siril-Specific Terms

| Term | Meaning |
|---|---|
| Sequence | Group of related images |
| Registration | Alignment of images |
| Stack | Combination of images |
| Normalization | Adjustment of image brightness |
| Debayer | Color interpolation |
| Stretch | Making the signal visible |

---

# Most Important Terms for Dwarf mini

If only the most important terms are retained:

```

Light

Dark

Flat

Debayer

OSC

Stacking

Registration

PCC

Stretch

SNR

```
