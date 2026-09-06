# Chapter 27 – Astrophotography Data Management

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Objective

This chapter describes organizing astrophotography data cleanly.

A good workflow consists of more than processing.

Also important:

- Reproducibility
- Archival
- Comparability
- Backup
- Versioning

Deep-sky imaging quickly produces many gigabytes of data.

---

# 1. Fundamental Principle

Original data is never modified.

Rule:

```

Original remains intact

↓

Processing creates new files

```

---

# 2. Recommended Folder Structure

Recommendation per object:

```

Astro/

└── M31/

```
├── 01_raw/
│
├── 02_calibration/
│
├── 03_siril/
│
├── 04_graxpert/
│
├── 05_gimp/
│
└── 06_export/
```

```

---

# 3. Raw Data

Folder:

```

01_raw

```

contains:

- Lights
- Darks
- Flats
- Bias

Example:

```

M31/

└── 01_raw/

```
├── lights/
├── darks/
├── flats/
└── bias/
```

```

---

# 4. Organizing Lights

Recommended name:

```

Object_Date_Exposure_Gain

```

Examples:

```

M31_2026-07-29_180s_G35

```

---

Advantages:

You can tell later:

- which object
- when it was captured
- which settings

---

# 5. Calibration Files

Folder:

```

02_calibration

```

---

Example:

```

02_calibration/

├── dark_master/
├── flat_master/
└── bias_master/

```

---

Keep master files.

They can be reused later.

---

# 6. Siril Working Folder

Folder:

```

03_siril

```

contains:

```

03_siril/

├── sequences/
├── registered/
├── stacked/
└── final/

```

---

Examples:

```

M31_light.seq

M31_registered.fit

M31_stack.fit

```

---

# 7. Why Save Sequences?

Siril creates:

```

.seq

```

files.

These contain:

- Image order
- Metadata
- Registration

---

Advantage:

Workflow can be repeated later.

---

# 8. GraXpert Versioning

Folder:

```

04_graxpert

```

---

Recommendation:

```

04_graxpert/

├── input/
├── processed/
└── versions/

```

---

Examples:

```

M31_graxpert_v1.tif

M31_graxpert_v2.tif

```

---

Do not overwrite.

---

# 9. GIMP Organization

Folder:

```

05_gimp

```

---

Save:

```

M31_final.xcf

```

---

Why XCF?

It stores:

- Layers
- Masks
- Adjustments

---

Do not save only TIFF.

---

# 10. Export Folder

Folder:

```

06_export

```

---

Contains finished images:

```

M31_final.jpg

M31_final.tif

M31_social.jpg

```

---

# 11. File Formats

## FITS

Usage:

- Raw data
- Siril processing

Advantages:

- maximum information

---

## TIFF 16-bit

Usage:

- Handoff to GIMP
- Archive

Advantages:

- high color depth

---

## XCF

Usage:

- GIMP project

---

## JPEG

Usage:

- Publishing
- Website

Not:

Archive.

---

# 12. Versioning

Recommendation:

Use version numbers.

Example:

```

M31_final_v01.xcf

M31_final_v02.xcf

M31_final_v03.xcf

```

---

Not:

```

M31_final_new_new2_final.xcf

```

---

# 13. Session Notes

For each session it makes sense:

File:

```

session_notes.md

```

---

Example:

```markdown
Object:
M31

Date:
2026-07-29

Location:
Vienna

Exposure:
180s

Gain:
35

Filter:
no filter

Lights:
200

Darks:
20

Seeing:
good

Notes:
light moon
```

---

# 14. Why Acquisition Data Matter

After months you won't remember:

* why one image was good
* why one was bad
* which settings worked

---

# 15. Backup Strategy

Recommendation:

3-2-1 Rule.

---

## 3 Copies

At minimum:

* Working copy
* Backup
* Archive

---

## 2 Different Media

Example:

* internal SSD
* external hard drive

---

## 1 External Copy

Example:

* Cloud
* different device

---

# 16. Storage Planning

Typical sizes:

## Single Image

Depending on format:

```

several MB per image

```

---

## 200 Lights

Can quickly reach:

```

several GB

```

---

Additionally:

* Intermediate states
* TIFF
* XCF

---

# 17. Cleaning Up

Do not delete:

* RAW
* Master Calibration
* final Siril file

---

Can be deleted:

* temporary registration files
* intermediate versions without value

---

# 18. Comparing Different Edits

Very worthwhile.

Example:

```

M31/

├── natural/
├── high_contrast/
├── starless/
└── experimental/

```

---

So you learn:

Which edit works better?

---

# 19. Automation Possibilities

Later possible:

* automatic folder creation
* automatic Siril scripts
* read metadata from FITS
* document workflow

---

Example:

```

New Dwarf folder

↓

Script recognizes object

↓

Select Siril workflow

↓

Generate stack

```

---

# 20. Minimal Personal Workflow

For daily use:

```

Dwarf capture

↓

Save RAW

↓

Create Siril project folder

↓

Generate stack

↓

GraXpert

↓

Save GIMP XCF

↓

Create export

↓

Backup

```

---

# 21. Recommended Archive Structure Long-Term

```

Astrophotography/

├── 2026/
│
├── 2027/
│
└── Library/

    ├── Galaxies/
    ├── Nebulae/
    ├── Star Clusters/
    ├── Planets/
    └── Moon/

```

---

# 22. Quality Rule

A good archive enables:

Today:

```

Create image

```

---

In one year:

```

Understand workflow

↓

Re-edit better

```

