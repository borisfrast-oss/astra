# Chapter 35 – Troubleshooting: When the Astrophoto Fails

# Dwarf mini + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbook

---

# Goal

This chapter describes systematic troubleshooting.

Basic rule:

Don't correct immediately in GIMP.

An error usually originates in an earlier stage:

```

Capture

↓

Calibration

↓

Registration

↓

Stack

↓

Color Correction

↓

Stretch

↓

Finalization

```

---

# 1. Basic Troubleshooting Principle

If an image looks bad:

Don't change everything at once.

Always check backwards:

```

Final Image

↓

GIMP

↓

GraXpert

↓

Siril Stretch

↓

Stack

↓

Calibration

↓

Raw Data

```

---

# 2. Image is Completely Green

## Symptom

The entire image has a strong green cast.

---

## Cause

Typical for:

- OSC cameras
- Missing color calibration
- Incorrect debayering

Dwarf mini has a color sensor.

Raw data is not directly RGB.

---

## Solution

Order:

```

Photometric Color Calibration

↓

Green Noise Removal

```

---

After:

Check again.

---

## Don't Do

Don't simply:

- Reduce saturation
- Remove green channel

This destroys color information.

---

# 3. Image is Black After Stack

## Symptom

The stacked image looks almost empty.

---

## Cause

The image is still linear.

Astrophotos are initially stored dark.

---

## Solution

Perform stretch:

```

Asinh Stretch

↓

Histogram Transformation

```

---

Normal.

Not:

Stack again.

---

# 4. No Stars Visible

## Possible Causes

---

## Cause 1

Wrong focus.

---

Check:

Open individual frame.

Stars:

```

Points

Not disks

```

---

## Cause 2

Exposure too short.

---

Solution:

Gather more signal.

---

## Cause 3

Wrong filter.

Example:

Galaxy with dual-band.

Result:

Too little light.

---

# 5. Stars are Large White Spheres

## Cause

Too much:

- Stretch
- Exposure
- Sharpening

---

## Solution

In Siril:

Less stretch.

---

In GIMP:

Less:

- Contrast
- Sharpening

---

# 6. Background is Speckled

## Cause

Possible reasons:

- Light gradients
- Poor flats
- Aggressive processing

---

## Solution

Check:

```

Background Extraction

↓

GraXpert

```

---

Don't:

Use both at maximum.

---

# 7. Nebula Disappears After GraXpert

## Cause

GraXpert interpreted real structure as background.

---

Typical for:

- Cirrus nebula
- Reflection nebulae
- Large diffuse nebulae

---

## Solution

Go back:

```

Fewer points

Lower model degree

Less strength

```

---

# 8. Nebula Disappears After Stretch

## Cause

Black point set too aggressively.

---

Result:

Weak data gets clipped.

---

## Solution

Reset histogram.

Stretch more slowly.

---

# 9. Image is Very Noisy

## Causes

---

## Too Few Lights

Solution:

More frames.

---

## Too High Gain

Solution:

Lower gain.

---

## Too Aggressive Processing

Examples:

- Too much contrast
- Too much sharpening
- Too much noise reduction

---

# 10. Colors Appear Unnatural

## Problem

Red, green, or blue dominates.

---

## Solution

Order:

```

PCC

↓

Green Noise Removal

↓

Light color correction

```

---

Don't:

Go directly to extreme color saturation.

---

# 11. Image Looks Flat

## Cause

Too little contrast.

---

Solution:

Carefully:

```

Curves

Local contrast

Light saturation

```

---

Don't:

Make everything darker.

---

# 12. Image Looks Artificial

## Causes

- Too much stretch
- Too much saturation
- Too much sharpening
- Black background

---

Solution:

Go back one version.

---

# 13. Stars are Blurred

## Cause

Possibly:

- Focus
- Tracking
- Registration

---

Check:

Compare individual frames.

---

If individual frames are poor:

Stack cannot fix it.

---

# 14. Satellite Trails in Image

## Cause

Individual lights contain satellites.

---

## Solution

Stack method:

```

Winsor Sigma Clipping

```

Use.

---

For strong trails:

Remove individual frames.

---

# 15. Airplanes in Image

Similar to satellites.

---

Solution:

- Sigma clipping
- Filter out bad frames

---

# 16. Registration Doesn't Work

## Symptom

Stars are doubled.

---

## Causes

- Too few stars
- Clouds
- Wrong mode

---

## Solution

Check:

```

Deep Sky Registration

Enough stars

```

---

# 17. Stack Looks Worse Than Individual Frames

## Cause

Usually:

Wrong workflow.

---

Check:

- Were darks used correctly?
- Was registration done?
- Were bad images removed?

---

A stack should:

- Have less noise
- Show more detail

---

# 18. Image is Blurry

## Causes

- Focus
- Seeing
- Movement
- Wind

---

Software cannot fully fix poor sharpness.

---

# 19. Background is Too Bright

## Causes

- City light
- Moon
- Too much stretch

---

Solution:

```

GraXpert

↓

Background Extraction

↓

Less stretch

```

---

# 20. Image Looks Worse After GIMP

## Cause

GIMP doesn't change data quality.

Usually:

- Over-processing

---

Check:

Before:

Siril TIFF

After:

GIMP Result

Compare.

---

# 21. Decision Table

| Problem | Likely Cause | Solution |
|---|---|---|
| Green | Color calibration | PCC + Green Removal |
| Black | No stretch | Asinh/Histogram |
| Noise | Too little data | More lights |
| Stars large | Stretch too strong | Reduce |
| Nebula gone | Black point/GraXpert | Reduce |
| Specks | Gradient/Flat | BE/GraXpert |
| Blurry | Focus/Seeing | Improve capture |
| Wrong colors | Color workflow | PCC first |

---

# 22. The Most Important Rule

If an image doesn't look good:

Don't process more.

First figure out:

```

Where does the error come from?

```

---

# 23. Professional Diagnosis Process

Always follow this order:

```

1. Check individual frame

↓

2. Check calibrated frame

↓

3. Check registered frame

↓

4. Check stack

↓

5. Check color calibration

↓

6. Check stretch

↓

7. GIMP

