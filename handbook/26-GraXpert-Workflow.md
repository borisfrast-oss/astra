# 26 – GraXpert Workflow

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Objective

This chapter describes using GraXpert in a Dwarf mini astrophotography workflow.

GraXpert is not a general image editor.

Main task:

**Remove artificial background gradients without destroying astronomical signal.**

---

# 1. Role of GraXpert in Workflow

Recommended order:

```

Dwarf mini

↓

Siril

Calibration

Registration

Stack

Color correction

↓

GraXpert

Remove gradients

↓

GIMP

Final processing

```

---

# 2. When to Use GraXpert?

Makes sense for:

- Light pollution
- Uneven background
- Vignetting
- Moonlight
- Urban images

---

Especially helpful for:

- Galaxies
- Faint nebulae
- Milky Way
- Large star fields

---

# 3. When to Be Careful?

Problematic for:

- Large reflection nebulae
- Very faint nebulae
- Large diffuse structures

Examples:

- M45 Pleiades
- Iris Nebula
- Cirrus Nebula

---

Reason:

GraXpert doesn't always recognize nebulae as objects.

It can interpret real structures as background.

---

# 4. Preparation

Before GraXpert:

Image should already be:

- Calibrated
- Registered
- Stacked

Recommended state:

```

Linear or slightly stretched

```

---

Not ideal:

Heavily processed JPEG.

---

# 5. Export from Siril

Recommendation:

```

TIFF 16-bit

```

Or:

```

FITS

```

---

For maximum data quality:

FITS preferred.

---

# 6. Model Selection

GraXpert uses a mathematical model of the background.

---

# 6.1 Simple Background

Suitable for:

- Small gradients
- Light light pollution

Recommendation:

```

Degree 1

```

---

# 6.2 Complex Background

Suitable for:

- City light
- Moon gradient
- Strong differences

Recommendation:

```

Degree 2

```

---

Higher degrees:

Only use if necessary.

---

# 7. Set Background Points

This is the most important step.

---

Rule:

Place points only on:

```

True background

```

---

Do not place on:

- Stars
- Nebulae
- Galaxies
- Bright structures

---

# 8. Example M31

Correct:

Points:

- Dark areas outside galaxy

Incorrect:

- Spiral arms
- Core region

---

# 9. Example Emission Nebula

Problem:

Nebula can cover large parts of image.

---

Rule:

Very few points.

Do not:

Treat entire nebula as background.

---

# 10. Example M45 Pleiades

Especially difficult.

Blue reflection nebula is large.

---

Recommendation:

- Little correction
- Only remove obvious gradients

---

# 11. Strength of Correction

Basic rule:

As little as possible.

---

Too strong:

Consequences:

- Nebula disappears
- Color gradients become unnatural
- Background looks artificial

---

Good:

Difference is visible but not dramatic.

---

# 12. AI-Denoise in GraXpert

GraXpert also includes denoising.

---

Recommendation:

Be cautious with Dwarf data.

---

Why:

Small sensors generate fine structures that can look similar to noise.

---

Too strong:

removes:

- Nebular filaments
- Faint stars
- Dust structures

---

# 13. Before/After Comparison with GraXpert

Always check:

Before:

- Where is the signal?

After:

- Is the signal still present?

---

Do not focus only on a clean background.

---

# 14. Common Problems

---

## Problem: Nebula was removed

Causes:

- Too many points
- Wrong points
- Model too complex

Solution:

- Fewer points
- Lower degree
- Compare with original

---

## Problem: Background is spotty

Causes:

- Too few points
- Wrong model

Solution:

- More evenly distributed background points

---

## Problem: Stars appear changed

Causes:

- Incorrect application on heavily stretched image

Solution:

- Apply before stretching

---

# 15. Recommended Workflow by Object Class

---

## Galaxies

```

Siril Stack

↓

Background Extraction

↓

PCC

↓

GraXpert

↓

GIMP

```

---

## Emission Nebulae

```

Siril Stack

↓

GraXpert cautiously

↓

PCC

↓

GIMP

```

---

## Reflection Nebulae

```

Siril Stack

↓

GraXpert very cautiously

↓

PCC

↓

GIMP

```

---

## Milky Way

```

Siril Stack

↓

GraXpert

↓

PCC

↓

GIMP

```

---

# 16. Siril Background Extraction vs GraXpert

Both accomplish similar tasks.

---

## Siril Background Extraction

Advantages:

- integrated
- fast
- sufficient for many cases

---

## GraXpert

Advantages:

- often better gradient recognition
- easier to control
- especially good for complex gradients

---

Recommendation:

Do not use both aggressively.

---

# 17. Combination Rule

Not:

```

Siril aggressive

*

GraXpert aggressive

*

GIMP contrast extreme

```

---

Better:

```

Siril light

↓

GraXpert light

↓

GIMP controlled

```

---

# 18. Quality Control

After GraXpert check:

- Are nebular filaments still present?
- Are stars unchanged?
- Is the background more natural?
- Are there new artifacts?

---

# 19. Standard Dwarf mini GraXpert Settings

Starting point:

```

Model:
Degree 1–2

Strength:
moderate

Points:
background only

Denoise:
low or off

```

---

# 20. Most Important Rule

GraXpert should improve the background.

It should not change the image.

If the difference between before and after is extreme:

the correction was probably too strong.

