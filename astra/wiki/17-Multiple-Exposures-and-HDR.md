# Workflow 17 – Multiple Exposures and HDR

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing images with different exposure times.

HDR (High Dynamic Range) is especially important for objects with extreme brightness differences.

Examples:

- M42 Orion Nebula
- M31 Andromeda Galaxy
- Moon with terminator
- bright stars with surroundings
- planetary nebulae

---

# 1. Why Different Exposures?

A sensor can only capture a limited brightness range.

Problem:

An image can either:

- show faint details

or:

- correctly display bright areas

Not always both at once.

---

# Example M42

A single recording:

180 seconds:

```

Outer regions visible

but

Core blown out

```

---

30 seconds:

```

Core correct

but

Outer regions faint

```

---

Solution:

Combine both.

---

# 2. Basic Principle

Not:

```

30s + 180s stack directly

```

but:

```

Stack 30s series

↓

Stack 180s series

↓

combine both finished images

```

---

# 3. Why Not Mix Directly?

Different exposure times have:

- different signal-to-noise ratio
- different saturation
- different dynamics
- different stars

Siril cannot meaningfully handle such series as a normal stack.

---

# 4. Recording Planning

Recommendation:

At least two series.

---

## Short Exposure

For:

- bright cores
- bright stars
- details

Examples:

```

5–30 seconds

```

---

## Long Exposure

For:

- faint nebulae
- outer regions
- galaxy halo

Examples:

```

120–180 seconds

```

---

# 5. Example M42

Recordings:

## Short

```

50 × 15 seconds

```

---

## Medium

```

50 × 60 seconds

```

---

## Long

```

100 × 180 seconds

```

---

Result:

```

Short stack

*

Medium stack

*

Long stack

↓

HDR composition

```

---

# 6. Processing Each Series

Each exposure series is processed separately.

Example:

Folder:

```

M42/

lights_15s/

lights_60s/

lights_180s/

darks/

```

---

Each series:

```

Create sequence

↓

Calibration

↓

Registration

↓

Stack

```

---

# 7. Siril Workflow for Each Series

## Sequence

Create:

```

lights_xxx.seq

```

---

## Master Dark

Use:

same temperature/exposure profile.

---

## Calibration

Active:

```

Dark

```

Optional:

```

Flat

```

---

## Registration

Use:

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

## Stack

Recommendation:

```

Winsor Sigma

```

---

# 8. HDR Merging

After Siril:

You have:

```

M42_15s.tif

M42_180s.tif

```

---

These are combined in GIMP.

---

# 9. GIMP HDR Technique

Basic principle:

Long exposure:

```

lower layer

```

---

Short exposure:

```

upper layer

```

---

Short exposure with layer mask.

---

Mask:

- make bright areas visible
- replace blown-out areas

---

# 10. Typical Procedure in GIMP

1. Open long exposure

2. Add short exposure as layer

3. Create layer mask

4. Work with soft brush

5. Reveal bright core from short exposure

---

# 11. Example Andromeda M31

Problem:

Core:

- very bright

Outer halo:

- extremely faint

---

Series:

Long:

```

100 × 180 seconds

```

for:

- halo
- dust bands

---

Short:

```

50 × 30 seconds

```

for:

- center

---

Combination:

```

Halo from long stack

*

Core from short stack

```

---

# 12. Example Planetary Nebula

Problem:

small bright core.

---

Series:

Long:

```

80 × 180 seconds

```

---

Short:

```

50 × 10 seconds

```

---

Result:

- central star preserved
- outer structures visible

---

# 13. Color Management

Important:

All partial images must receive the same color processing.

Recommendation:

All stacks:

```

GraXpert

↓

PCC

↓

same stretch

```

---

Not:

process one image extremely differently.

---

# 14. Denoising

Not before combination.

Better:

```

Combine HDR

↓

Denoise final image

```

---

Why:

Otherwise differences appear between layers.

---

# 15. Typical Errors

## Core remains blown out

Cause:

Short exposure not used.

---

## Image looks unnatural

Cause:

transitions too harsh.

Solution:

soft masks.

---

## Stars double

Cause:

stacks not exactly registered.

Solution:

align both images exactly before combination.

---

## Colors don't match

Cause:

different processing.

Solution:

same color calibration.

---

# 16. Quality Goal

A good HDR recording:

- shows bright and faint details
- has natural contrast
- no visible transitions
- preserves star colors

---

# Summary

```

Record exposure series separately

↓

each series in Siril:

Calibrate

↓

Register

↓

Stack

↓

PCC

↓

Stretch

↓

combine in GIMP

↓

create HDR mask

```
```
```
