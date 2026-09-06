# 24 – Dwarf mini Master Recipes

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Objective

This chapter contains proven standard recipes for typical objects.

Recipes are not rigid rules.

They serve as a starting point:

- Create consistent conditions
- Reach results faster
- Avoid typical mistakes

---

# 1. Basic Deep Sky Recipe

When no experience with the object exists:

```

Exposure:
180 seconds

Gain:
35

Filter:
No filter

Lights:
200

Darks:
20

Flat:
Yes

Stack:
Winsor Sigma

Normalization:
Additive + scaling

PCC:
Yes

Stretch:
Careful

```

Suitable for:

- Galaxies
- Nebulae
- Star clusters

---

# 2. M31 Andromeda Galaxy

## Objective

Show:

- Core
- Dust lanes
- Outer regions
- Star field

---

## Acquisition

```

Exposure:
180 seconds

Gain:
30–35

Filter:
No filter

Lights:
150–300

```

---

## Calibration

Recommended:

```

Dark:
Yes

Flat:
Yes

Bias:
Optional

```

---

## Siril Workflow

```

Create sequence

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma Stack

↓

Background Extraction

↓

PCC

↓

Green Noise Removal

↓

Asinh Stretch

↓

Export TIFF

```

---

## Special Feature

M31 has a very bright core.

Do not stretch too much.

Optional:

HDR with shorter exposures.

---

# 3. M42 Orion Nebula

## Objective

At the same time:

- Bright core
- Faint outer regions
- Red nebula structures

---

## Acquisition

Recommended:

Two series.

---

## Short Exposure

```

Exposure:
5–15 seconds

Gain:
10–20

Lights:
50+

```

For:

- Trapezium
- Core

---

## Long Exposure

```

Exposure:
120–180 seconds

Gain:
30–40

Lights:
100+

```

For:

- Outer regions
- Nebula filaments

---

## Processing

Two stacks:

```

Short exposure

*

Long exposure

↓

HDR in GIMP

```

---

# 4. M45 Pleiades

## Objective

Show:

- Blue reflection nebula
- Star colors
- Dust structures

---

## Acquisition

```

Exposure:
120 seconds

Gain:
30

Filter:
No filter

Lights:
200+

```

---

## Processing

Especially careful:

```

Background Extraction

↓

PCC

↓

Gentle stretch

```

---

## Important

Do not:

- Use dual-band
- Remove background too strongly

---

# 5. M13 Globular Cluster

## Objective

Make many individual stars visible.

---

## Acquisition

```

Exposure:
30–90 seconds

Gain:
10–30

Lights:
100–300

```

---

## Processing

```

Dark

↓

Registration

↓

Stack

↓

PCC

↓

Light stretch

```

---

## Important

Preserve star colors.

Do not denoise too much.

---

# 6. M27 Dumbbell Nebula

## Objective

Planetary nebula with:

- OIII structure
- H-alpha components

---

## Acquisition

Without filter:

```

120 seconds

Gain:
30–40

```

---

With dual-band:

```

180 seconds

Gain:
40

```

---

## Processing

```

Stack

↓

Background Extraction (careful)

↓

PCC

↓

Color correction

↓

Stretch

```

---

# 7. Cirrus Nebula / Veil Nebula

## Objective

Extremely faint filaments.

---

## Acquisition

```

Exposure:
180 seconds

Gain:
40

Filter:
Dual-band

Lights:
300+

```

---

## Processing

Very careful:

```

GraXpert

↓

PCC

↓

Stretch

```

---

## Important

Do not:

- Denoise aggressively
- Make background black

---

# 8. Heart Nebula IC1805

## Objective

Large H-alpha structure.

---

## Acquisition

```

Exposure:
180 seconds

Gain:
40

Filter:
Dual-band

Lights:
300+

```

---

## Processing

```

Dark

↓

Flat

↓

Stack

↓

Background Extraction

↓

Color calibration

↓

Stretch

```

---

# 9. Rosette Nebula

## Objective

- Red nebula structure
- Central star group

---

## Acquisition

```

180 seconds

Gain:
40

Dual-band

200–500 Lights

```

---

## Special Feature

OIII component may appear green/blue.

Do not remove completely.

---

# 10. Arcturus / Bright Stars

## Objective

Natural star color.

---

## Acquisition

```

Exposure:
1–10 seconds

Gain:
0–20

Lights:
100+

```

---

## Processing

Minimal:

```

Stack

↓

Light color correction

↓

Export

```

---

Do not:

- Sharpen heavily
- Denoise heavily

---

# 11. Albireo Double Star

## Objective

Color contrast:

- Golden star
- Blue companion

---

## Acquisition

```

Exposure:
1–5 seconds

Gain:
0–10

```

---

## Processing

```

Stack

↓

Color correction

↓

Light sharpening

```

---

# 12. Moon

## Objective

Maximum details.

---

## Acquisition

```

Very short exposure

Gain:
0–20

Many images

```

---

## Processing

Not classic deep sky:

```

Select best images

↓

Stack

↓

Sharpening

↓

Contrast

```

---

# 13. Jupiter

## Objective

- Cloud bands
- Moons

---

## Acquisition

```

Video

or many short frames

```

---

## Processing

```

Select best frames

↓

Stack

↓

Sharpen

↓

Color correction

```

---

# 14. Milky Way

## Objective

- Large structures
- Star fields

---

## Acquisition

```

Exposure:
10–30 seconds

Gain:
20–40

Lights:
100+

```

---

## Processing

```

Stack

↓

Background Extraction

↓

PCC

↓

Stretch

```

---

# 15. Comets

## Objective

Optimize comet + stars separately.

---

## Acquisition

```

Exposure:
30–120 seconds

Gain:
30–40

```

---

## Processing

Two stacks:

```

Star registration

↓

Star stack

Comet registration

↓

Comet stack

```

Afterwards:

```

GIMP combination

```

---

# 16. Universal Error Schema

If a recipe doesn't work:

Do not change all parameters.

Order:

```

1. Check focus

↓

2. Check individual images

↓

3. Check calibration

↓

4. Check stack

↓

5. Check processing

```

---

# 17. My Dwarf mini Standard Values

If I were to photograph an unknown deep-sky object today:

```

180 seconds

Gain 35

No filter

200 Lights

20 Darks

Flat present

Winsor Sigma

PCC

Asinh Stretch


```
