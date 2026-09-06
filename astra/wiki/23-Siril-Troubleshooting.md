# 23 – Siril Troubleshooting

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Objective

This chapter describes typical problems when processing Dwarf mini images in Siril 1.4.4.

Basic rule:

Not every poor result means the acquisition is poor.

Very often the problem is:

- wrong order
- wrong parameters
- too aggressive post-processing
- misinterpretation of the signal

---

# 1. After Stacking Image Is Completely Green

## Symptom

The stacked image appears:

- green
- cyan
- with wrong colors

---

## Common Causes

### Cause 1

OSC debayer incorrect.

Check:

```

Create sequence

↓

Debayer enabled?

```

---

### Cause 2

No color calibration.

Solution:

```

Perform PCC

```

---

### Cause 3

OIII-heavy dual-band acquisition.

Normal:

For:

- Heart Nebula
- Rosette Nebula
- Veil Nebula

---

## Solution Order

```

PCC

↓

Green Noise Removal

↓

Manual color correction

```

---

# 2. After PCC Colors Are Worse

## Symptom

Before PCC:

- beautiful colors

After PCC:

- gray
- pale
- unnatural

---

## Causes

PCC is not automatic enhancement.

It tries:

- scientifically correct colors

Not:

- maximum aesthetics

---

## Solution

After PCC:

- Increase saturation slightly
- Adjust curves
- Local color correction

---

# 3. Background Too Bright After Stretch

## Symptom

The image looks:

- gray
- milky
- low contrast

---

## Causes

### Too Much Stretch

Solution:

Reduce histogram.

---

### Light Pollution

Solution:

```

Background Extraction

```

---

### Black Point Too High

Solution:

Set black point more carefully.

---

# 4. Nebula Disappears After Background Correction

## Symptom

Before GraXpert:

Nebula details visible

After GraXpert:

Nebula surface gone

---

## Cause

The algorithm interprets real structures as background.

---

## Solution

Check control points:

Do NOT place on:

- Nebula
- Galaxies
- Dust structures

---

Alternative:

Use less strong correction.

---

# 5. Stars Are Bloated

## Symptom

Stars appear:

- large
- soft
- white

---

## Causes

### Overexposure

Solution:

Use shorter individual exposure.

---

### Too Much Stretch

Solution:

Stretch less aggressively.

---

### Seeing

Not always avoidable.

---

# 6. Stars Have Color Fringing

## Symptom

Stars show:

- red edges
- blue edges

---

## Causes

- Atmospheric dispersion
- Focus
- Color channel shift

---

## Solution

Check:

- Focus
- PCC
- Color correction

---

# 7. Stars Are Not Round

## Symptom

Stars appear:

- oval
- elongated
- distorted

---

## Causes

### Tracking

Most common cause.

---

### Wind

Tripod/vibration.

---

### Registration

Wrong method.

---

## Solution

Check frames:

Remove bad images.

---

# 8. Siril Finds No Stars During Registration

## Symptom

Error:

- No stars detected
- Registration fails

---

## Causes

### Image Too Dark

Solution:

Reduce star detection threshold.

---

### Too Few Stars

Solution:

Increase maximum stars.

Example:

```

100

↓

500

```

---

### Dual-band Filter

Problem:

Fewer visible stars.

---

Solution:

Reduce minimum stars:

```

10

↓

5

```

---

# 9. Stack Contains Streaks or Artifacts

## Causes

- Satellites
- Aircraft
- Bad frames
- Wrong stack method

---

## Solution

Use:

```

Winsor Sigma

```

---

For few images:

Check frames manually.

---

# 10. Flats Make Image Worse

## Symptom

After flat calibration:

- Dark spots
- Brightness errors
- Unnatural background

---

## Causes

### Wrong Flats

Examples:

- Different focus
- Different position
- Different exposure

---

### Flat Created Incorrectly

---

## Solution

Compare without flats.

If better:

Retake flats.

---

# 11. Darks Make Image Worse

## Causes

Dark doesn't match.

Examples:

- Different temperature
- Different exposure
- Different gain

---

Solution:

Create new darks.

---

# 12. Image Is Noisy After Stretch

## Causes

Normal with weak signal.

---

Improvements:

```

More lights

↓

Better calibration

↓

Careful denoising

```

---

Do not:

Filter noise aggressively.

---

# 13. Weak Details Disappear

## Causes

### Too Strong Denoising

---

### Background Too Dark

---

### GraXpert Too Strong

---

### Too Little Integration

---

Solution:

Recover details step by step.

---

# 14. Galaxy Core Is Blown Out

## Symptom

M31 core:

- white
- no structure

---

## Solution

HDR technique:

```

Short exposure

*

Long exposure

↓

Combine

```

---

# 15. Nebula Colors Look Artificial

## Causes

- Saturation too high
- Wrong color channels
- Aggressive processing

---

Solution:

Go back to:

- PCC
- Natural saturation

---

# 16. Image Is Too Blue

## Common With

- Pleiades
- Reflection nebulae

---

Not automatically wrong.

---

Check:

Is real reflection color present?

---

Correction:

Reduce slightly.

Do not:

Neutralize completely.

---

# 17. Image Is Too Red

## Common With

- H-alpha dual-band

---

Check:

Is H-alpha the target?

---

Correction:

- Balance channels
- Do not remove completely

---

# 18. Siril Is Slow

## Causes

- Many lights
- Large FITS files
- Little RAM

---

Optimization:

- Clean temporary files
- Keep only needed sequences
- Do not recalculate stack multiple times

---

# 19. When to Retake?

Retake makes sense for:

- Wrong focus
- Heavy clouds
- Distorted stars
- Wrong exposure
- Wrong filter

---

Do not retake for:

- Some noise
- Bright background
- Lack of perfection

These problems are usually processing issues.

---

# 20. General Diagnostic Order

If the result is poor:

Always check:

```

1. Raw images

↓

2. Calibration

↓

3. Registration

↓

4. Stack

↓

5. Background

↓

6. Color

↓

7. Stretch

↓

8. GIMP

```

---

# 21. Most Important Rule

Do not correct everything at once.

Always change only one step:

```

Identify problem

↓

Make one change

↓

Check

↓

Continue

```
