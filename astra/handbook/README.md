# Dwarf mini + Siril 1.4.4
# Best Practices Handbook for Astrophotography

**Version:** 1.1  
**Date:** 2026-09  
**Profile:** `dwarf_mini` (alias `dwarf3` deprecated since V19 — hardware identical, 2.9 µm pixel, 150 mm focal length)

**Workflow:**

- DwarfLab Dwarf mini (formerly `dwarf3`)
- Siril 1.4.4
- GraXpert
- GIMP 3.x

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility.

---

# Purpose of this Handbook

This handbook describes a practical workflow for processing astrophotography captures with the Dwarf mini smart telescope.

Focus:

- Deep-sky astrophotography
- FITS processing
- Siril 1.4.4
- Reproducible workflows
- Target-dependent processing
- Sensible default parameters

The goal is not:

> "Click here and there"

but:

> Understand why a processing step is performed and when it is useful.

---

# Fundamentals of Astrophotography

Astrophotography differs fundamentally from normal photography.

A raw frame contains:

- Useful signal of the celestial object
- Sky background
- Read noise
- Dark current
- Hot pixels
- Random disturbances

Image processing pursues four main goals:

1. Remove errors
2. Preserve signal
3. Reduce noise
4. Render colors correctly

---

# Standard Workflow

```text
Dwarf mini acquisition

        ↓

FITS lights

        ↓

Acquire darks

        ↓

Siril:
Create sequences

        ↓

Create master dark

        ↓

Calibrate lights

        ↓

Registration

        ↓

Stacking

        ↓

Linear master

        ↓

Background Extraction

        ↓

Photometric Color Calibration

        ↓

Stretching

        ↓

GraXpert (optional)

        ↓

GIMP:
Finalization
````

---

# Ground Rule

## More signal matters more than more processing

The biggest improvement to an astro image usually comes from:

* longer total exposure time
* more sub-frames
* better acquisition conditions

Example:

```text
16 × 180 seconds

= 48 minutes integration time
```

is a workable start.

More data:

```text
60 × 180 seconds

= 3 hours integration time
```

typically leads to:

* less noise
* fainter detail becoming visible
* cleaner background
* more stable colors

---

# Dwarf mini Standard Recommendations

## Deep Sky

| Parameter       | Recommendation                               |
| --------------- | -------------------------------------------- |
| Exposure time   | depends on target, often 60–180 seconds      |
| Gain            | depends on target and goal                   |
| Lights          | as many sub-frames as possible               |
| Darks           | 10–20 or more                                |
| Flats           | optional as needed                           |
| Bias            | usually not required                         |

Optimal values depend on:

* target
* sky background
* moon phase
* filter
* desired result

---

# Target Classes

Not every object is processed the same.

| Object              | Examples        | Characteristic            |
| ------------------- | --------------- | ------------------------- |
| Galaxies            | M31, M33, M51   | faint signal              |
| Emission nebulae    | M42, NGC7000    | gas structures            |
| Reflection nebulae  | M78             | subtle contrast           |
| Planetary nebulae   | M57             | small bright objects      |
| Globular clusters   | M13             | many stars                |
| Open clusters       | M45             | star colors               |
| Star fields         | Milky Way       | natural star rendering    |
| Single stars        | bright stars    | color fidelity            |
| Moon                | surface         | short exposure            |
| Sun                 | surface         | special filter required   |
| Planets             | Jupiter, Saturn | short single frames       |
| Comets              | moving objects  | special processing        |

---

# Calibration Frames

## Darks

Darks contain no light information.

They measure:

* hot pixels
* dark current
* sensor pattern

Lights and darks should be acquired as identically as possible.

| Parameter       | ideally identical |
| --------------- | ----------------- |
| Camera          | yes               |
| Exposure time   | yes               |
| Gain            | yes               |
| Temperature     | as close as possible |

---

## Flats

Flats correct:

* vignetting
* dust spots
* uneven illumination

Flats must match the optical setup used.

---

## Bias

Bias describes the electronic offset of the sensor.

In the Dwarf mini workflow bias is often unnecessary because darks already handle most of the correction.

---

# Color Workflow

The Dwarf mini has a color sensor with Bayer matrix.

After stacking the image may appear green.

This is normal.

Recommended order:

```text
Stack

↓

Background Extraction

↓

Photometric Color Calibration

↓

Green Noise Reduction (optional)

↓

Stretch
```

Not:

```text
Green Noise Reduction

↓

Color Calibration
```

Reason:

Color calibration should be based on the original color distribution.

> **V19-FIX-13 Duo-Band note:** For Duo-Band targets use `nebula_standard` (PCC off, SCNR on). `star_standard` + Duo-Band + PCC pushes red (C19 R/G 1.608 vs 1.006 with nebula_standard) — see Chapters 06/08/15.

---

# Stacking

## Average

Advantages:

* maximum signal usage

Disadvantages:

* outliers remain

---

## Median

Advantages:

* removes outliers

Disadvantages:

* slightly less signal

---

## Winsorized Sigma Clipping

Recommended for many deep-sky images.

Removes:

* satellite trails
* airplanes
* single outliers

---

# Software Responsibilities

## Siril

Responsible for:

* FITS processing
* sequences
* calibration
* registration
* stacking
* color calibration
* linear processing
* stretching

---

## GraXpert

Responsible for:

* background gradients
* light-pollution correction
* optional denoising

---

## GIMP

Responsible for:

* final image editing
* contrast
* local adjustments
* presentation
* export

---

# Handbook Structure

Chapters are organized in five sections.

---

## 1. Fundamentals

```text
README.md

01-Introduction.md
02-Fundamentals.md
03-Dwarf-mini-Best-Practices.md
04-Siril-Reference.md
```

---

## 2. Target-Specific Processing

```text
05-Galaxies.md
06-Emission-Nebulae.md
07-Reflection-Nebulae.md
08-Planetary-Nebulae.md
09-Globular-Clusters.md
10-Open-Clusters.md
11-Stars-and-Star-Fields.md
12-Moon-and-Planets.md
13-Milky-Way-and-Wide-Field.md
14-Comets.md
15-Star-Forming-Regions-and-Complex-Nebulae.md
16-Dark-Nebulae.md
```

---

## 3. Image Processing

```text
17-Multiple-Exposures-and-HDR.md
18-Mosaics-and-Panoramas.md
19-Color-Calibration-and-Final-Processing.md
```

---

## 4. Practice and Tools

```text
20-Dwarf-mini-Imaging-Recommendations.md
21-Siril-1.4.4-Parameter-Reference.md
22-Siril-Workflow-Decision-Tree.md
23-Siril-Troubleshooting.md
24-Dwarf-mini-Master-Recipes.md
25-GIMP-Astrophotography-Workflow.md
26-GraXpert-Workflow.md
27-Astrophotography-Data-Management.md
28-Advanced-Techniques.md
```

---

## 5. Reference

```text
29-Siril-Quick-Checklist.md
30-Dwarf-mini-Pre-Night-Imaging-Checklist.md
31-Target-Selection-by-Season.md
32-Astrophotography-Glossary.md
33-Final-Dwarf-mini-Siril-Reference-Parameters.md
34-Siril-1.4.4-Menu-Navigation.md
35-Troubleshooting-Astrophotography.md
36-Dwarf-mini-End-to-End-Workflow.md
37-Siril-Command-Quick-Reference.md
```

---

# Version History

## Version 1.1 (2026-09)

- English translation of all 36 chapters (§17)
- `dwarf3` → `dwarf_mini` rename (profile `dwarf_mini`, alias `dwarf3` deprecated since V19, hardware identical)
- V19 addendum integrated: REG-SMART, CFA-GATE, PCC-FLAG, ghosting guard and Duo-Band Rosa fix (Ch. 06/07/08/15/22/23)
- Chapter file names DE → EN (git mv, 36 files)

## Version 1.0

Initial structured version.

Basis:

* Dwarf mini (formerly `dwarf3`)
* Siril 1.4.4
* GraXpert
* GIMP

---

# Goal of the Handbook

A reproducible workflow:

```text
Acquire

↓

Understand

↓

Process

↓

Improve

↓

Archive
```

Astrophotography thus becomes a traceable workflow rather than trial and error.
