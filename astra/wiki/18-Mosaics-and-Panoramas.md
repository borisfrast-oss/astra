# Workflow 18 – Mosaics and Panoramas

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes creating sky mosaics from multiple Dwarf mini recordings.

Examples:

- large nebula regions
- Milky Way areas
- Andromeda region
- lunar mosaics
- large star fields

A mosaic is created when an object is larger than the single field of view of the telescope.

---

# 1. Why Mosaics?

The Dwarf mini has a limited field of view.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Large objects often don't fit completely.

Examples:

| Object | Problem |
|---|---|
| M31 | only core region fits |
| North America Nebula | too large |
| Milky Way | very large |
| Moon | large detail areas |

---

# 2. Basic Principle

Not:

```

stack all individual images together

```

but:

```

Position A

↓

own stack

Position B

↓

own stack

Position C

↓

own stack

↓

create mosaic

```

---

# 3. Recording Planning

Before recording:

- plan overlap
- use same camera settings
- use same exposure time

---

Recommendation:

Overlap:

```

20–30 %

```

Why:

Programs need common stars for alignment.

---

# 4. Example M31

M31 doesn't fit completely in Dwarf field.

Plan:

```

M31 Center

*

M31 Northeast

*

M31 Southwest

```

---

Each position:

```

100 × 180 seconds

Gain 40

same focus

same filter

```

---

# 5. Folder Structure

Recommended:

```

M31_Mosaic/

tile_01/

lights/

darks/

tile_02/

lights/

darks/

tile_03/

lights/

darks/

```

---

# 6. Process Each Tile Separately

Each position gets its own Siril workflow.

---

Procedure:

```

Create sequence

↓

Calibration

↓

Registration

↓

Stack

↓

GraXpert

↓

PCC

↓

Export

```

---

# 7. Create Sequence

For each tile:

Example:

```

tile01_light_.seq

```

---

Check:

- sufficient stars
- same orientation
- no bad frames

---

# 8. Master Dark

If all recordings:

- same camera
- same temperature
- same exposure time

have:

a shared Master Dark can be used.

---

Otherwise:

separate Darks.

---

# 9. Calibration

Active:

```

Dark

```

Optional:

```

Flat

```

---

For mosaics, Flats are especially helpful.

Why:

Each tile must have the same brightness distribution.

---

# 10. Registration

Normal Deep-Sky registration:

```

General Deep Sky

```

---

Parameters:

| Parameter | Value |
|---|---|
| Transformation | Homography |
| Minimum star pairs | 10 |
| Luminance | active |
| Maximum stars | 500 |
| Distortion removal | off |

---

# 11. Stack

Recommendation:

```

Winsor Sigma

```

---

Normalization:

```

Additive + Scaling

```

---

RGB Weighting:

```

off

```

---

# 12. Background Correction

Important:

Don't maximize correction for each tile individually.

Problem:

Different corrections create visible transitions.

---

Better:

1. Create stacks

2. use similar background correction

3. create mosaic

4. perform final correction

---

# 13. PCC

Option 1:

Each tile:

```

PCC individually

```

---

Option 2:

After mosaic:

```

PCC on entire image

```

---

Recommendation:

For large mosaics:

PCC after merging.

---

# 14. Mosaic Creation in GIMP

GIMP can create simple mosaics.

---

Workflow:

1. Create new large image

2. open individual images as layers

3. move layers

4. align overlaps

5. use layer masks

---

# 15. Alignment in GIMP

Helpful:

- reduce transparency
- compare same stars
- use guides

---

For small deviations:

- rotate
- scale
- move

---

# 16. Layer Masks

Important for transitions.

Not:

hard edges.

---

Better:

soft transition:

```

black mask

*

soft brush

```

---

# 17. Siril Mosaic Function

Siril also has tools for mosaics.

Depending on workflow:

- mosaic registration
- mosaic composition

---

For Dwarf recordings, often simpler:

```

Individual stacks

↓

GIMP composition

```

---

# 18. Color Management

All tiles must be treated the same.

Important:

Not:

```

Tile 1 highly saturated

Tile 2 neutral

```

---

Recommended:

same workflow:

```

GraXpert

↓

PCC

↓

Stretch

```

---

# 19. Denoising

Not before merging.

Better:

```

Create mosaic

↓

final image

↓

denoise

```

---

Recommendation:

```

0.03–0.08

```

---

# 20. Typical Errors

## Visible Transitions

Causes:

- different background correction
- different exposure
- no masks

---

## Stars don't match

Causes:

- too little overlap
- different rotation

---

## One corner is brighter

Causes:

- gradients
- different Flats

---

## Details disappear

Cause:

background correction too aggressive.

---

# 21. Example Workflow North America Nebula

Recording:

```

6 tiles

each 80 × 180 seconds

Gain 40

Dual-Band

```

---

Processing:

```

each tile separately:

Master Dark

↓

Calibration

↓

Registration

↓

Winsor Sigma Stack

↓

PCC

↓

Export

↓

Mosaic in GIMP

↓

final GraXpert correction

↓

Stretch

↓

Denoise

```

---

# 22. Quality Goal

A good mosaic:

- shows large structures without transitions
- has uniform colors
- preserves stars and nebula details
- looks like a single recording

---

# Summary

```

Multiple overlapping recordings

↓

stack each position separately in Siril

↓

same color correction

↓

assemble mosaic

↓

masks for transitions

↓

final processing

```
```
```
