# 01 – Introduction

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical (2.9 µm pixel, 150 mm focal length).

---

# 1. What Is Astrophotography?

Astrophotography is the technique of making faint light sources from space visible photographically.

Many astronomical objects are so faint that they:

- are invisible to the naked eye
- barely appear on normal photos
- only become visible with long exposure times

Examples:

- Galaxies
- Emission nebulae
- Reflection nebulae
- Planetary nebulae
- Star clusters

The camera collects photons over time.

---

# 2. How It Differs from Normal Photography

Normal photography:

```
Subject
+
Light
+
Short exposure

=

Finished image
```

Deep-sky astrophotography:

```
Faint object
*
Many individual frames
*
Calibration
*
Registration
*
Stacking
*
Image processing
=
Visible result
```

One astro image is not created from a single exposure.

---

# 3. Collecting Photons

The core principle:

> Astrophotography is collecting light.

Each exposure adds information.

A single frame contains only a small fraction of the information.

Example:

## Single Frame

```
Signal:
100

Noise:
30
```

The object is hard to see.

---

## 16 Frames Combined

```
Signal:
100

Noise:
30 / √16

=

7.5
```

The signal is preserved.

Random noise is reduced.

---

# 4. Signal and Noise

A sensor does not only measure light.

It also creates its own disturbances.

The image signal consists of:

```
Total signal

=

Object light

*

Sky background

*

Sensor effects

*

Noise
```

Processing aims to:

- preserve object light
- remove sensor effects
- reduce noise

---

# 5. Types of Noise

## 5.1 Read Noise

Occurs during sensor readout.

Properties:

- occurs on every frame
- independent of exposure time

---

## 5.2 Dark Current

Electrons are generated even without light.

Increases with:

- longer exposure times
- higher temperatures

Corrected with darks.

---

## 5.3 Hot Pixels

Individual pixels respond more strongly than others.

Visible as:

- bright points
- colored pixels
- fixed patterns

Reduced by:

- darks
- sigma stacking

---

## 5.4 Random Noise

This noise changes from frame to frame.

This is exactly why stacking works.

---

# 6. Why Stacking Works

When stacking, several images are combined.

Real signal:

```
Frame 1:
Star at position X

Frame 2:
Star at position X

Frame 3:
Star at position X
```

The signal remains.

---

Noise:

```
Frame 1:
Pixel deviation A

Frame 2:
Pixel deviation B

Frame 3:
Pixel deviation C
```

Random errors average out.

---

# 7. Integration Time

The most important quality metric is:

```
Total exposure time

=

Number of frames

×

Exposure time
```

Examples:

| Frames | Exposure | Total |
|---:|---:|---:|
| 10 | 180 s | 30 minutes |
| 20 | 180 s | 60 minutes |
| 40 | 180 s | 120 minutes |
| 80 | 180 s | 240 minutes |

---

# 8. Why Longer Exposures Help

More integration time means:

- fainter detail becomes visible
- background becomes cleaner
- colors become more stable
- less aggressive denoising is needed

Example M31:

With short integration:

- core visible
- outer arms barely visible

With longer integration:

- dust lanes
- outer regions
- M110

become visible.

---

# 9. The Dwarf mini Workflow

The Dwarf mini already handles:

- tracking
- automatic alignment
- acquisition planning

Actual image processing happens afterwards.

Typical flow:

```
Dwarf mini

↓

FITS files

↓

Siril

↓

Calibration

↓

Stacking

↓

Post-processing
```

---

# 10. FITS Files

FITS stands for:

Flexible Image Transport System.

It is the standard format in astronomy.

A FITS file contains:

- image data
- metadata
- acquisition information

Unlike JPEG:

JPEG:

- compressed
- already processed
- loses information

FITS:

- raw data
- high dynamic range
- ideal for scientific processing

---

# 11. Lights

Lights are the actual object frames.

Example:

```
m31_light_00001.fits
m31_light_00002.fits
m31_light_00003.fits
```

They contain:

- stars
- galaxy
- nebula
- background
- noise

---

# 12. Darks

Darks are taken without light.

They show:

- sensor pattern
- hot pixels
- dark current

A dark therefore contains:

```
No object

but

Sensor characteristics
```

---

# 13. Flats

Flats show optical defects.

They correct:

- dust
- vignetting
- uneven illumination

A flat answers:

> How uniformly does the camera see the area?

---

# 14. Bias

Bias measures the minimum electronic offset of the sensor.

Important for many astro cameras.

With the Dwarf mini:

- often not required
- darks are usually sufficient

---

# 15. Linear Image

After stacking, a linear image is created.

Properties:

- very dark
- detail barely visible
- mathematically unchanged

Example:

```
M31 present

but barely visible
```

This is normal.

---

# 16. Stretching

Stretching changes the display.

It makes:

- faint detail visible
- colors visible
- contrast visible

It does not create new signal.

A poor signal stays poor.

---

# 17. Why Different Objects Need Different Workflows

## Galaxies

Properties:

- faint
- large dynamic range

Need:

- lots of integration
- clean background processing

---

## Nebulae

Properties:

- diffuse structures
- color components

Need:

- good color management
- careful stretching

---

## Star Clusters

Properties:

- many bright stars

Need:

- preserve star colors
- little denoising

---

## Single Stars

Properties:

- very bright
- color matters

Need:

- minimal processing

---

# 18. Core Philosophy of this Handbook

The most important rule:

> The best processing is the one that makes the existing signal visible without creating new artifacts.

Therefore:

- do not stretch every image to the maximum
- do not denoise every image aggressively
- do not apply every correction

The right workflow depends on the target.
