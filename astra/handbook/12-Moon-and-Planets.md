# Workflow 12 – Moon and Planets

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing lunar and planetary images with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- Moon
- Jupiter
- Saturn
- Mars
- Venus
- Bright planetary fields

This workflow differs fundamentally from deep-sky.

The focus is not on:

- Long integration
- Weak signal
- Noise reduction

But on:

- Sharpness
- Detail preservation
- Contrast
- Short exposure

---

# 1. Difference from Deep Sky

Deep sky:

```

Little light

*

Long exposure

*

Many images

```

Planetary:

```

Much light

*

Short exposure

*

Many individual frames

```

---

# 2. Acquisition Principle

Planets are bright enough that the sensor can capture many details in short time.

Goal:

Freeze the seeing.

Seeing means:

Atmospheric turbulence.

Example:

A planet appears:

- Flickering
- Distorted
- Soft

Short exposures reduce this effect.

---

# 3. Acquisition Recommendation

## Moon

| Parameter | Recommendation |
|---|---|
| Exposure | 1–10 ms to few seconds |
| Gain | Low |
| Lights | Many individual frames |
| Filter | Optional |

---

## Planets

| Parameter | Recommendation |
|---|---|
| Exposure | As short as possible |
| Gain | Moderate |
| Lights | Hundreds to thousands of frames |
| Filter | Optional |

---

# 4. Dwarf mini Peculiarities

The Dwarf mini is primarily optimized for deep sky.

With planets it is limited compared to:

- Planetary cameras
- Fast CMOS cameras
- Video stacking

Still possible:

- Moon
- Bright planets
- Large structures

---

# 5. Filters

## No Filter

Standard.

Suitable for:

- Moon
- Jupiter
- Saturn

---

## Color Filters

Useful with specialized planetary cameras.

With the Dwarf mini usually not necessary.

---

## ND Filter

Can be useful for the moon.

Goal:

Prevent overexposure.

---

# 6. Preparation in Siril

Folders:

```

Jupiter/

lights/

output/

```

---

# 7. Create Sequence

Result:

```

jupiter_light_.seq

```

Check:

- Sharp image present
- Planet visible
- No motion blur

---

# 8. Calibration

With planetary videos:

Darks usually not necessary.

Reason:

- Short exposures
- Little dark current

---

For longer lunar images:

Darks optional.

---

# 9. Registration

Different approach from deep sky.

Not:

```

General Deep Sky

```

Use.

---

Suitable:

```

Planetary registration

```

Or:

```

1-star registration

```

(Depending on capture type)

---

# 10. Stacking

Goal:

Select the best frames.

---

## Method

Recommendation:

```

Average

```

Or:

```

Median

```

---

Why?

With planets:

- Many similar images
- Few outliers

---

# 11. Selection of Best Images

Most important difference from deep sky.

Don't use all images.

Remove bad frames:

- Poor seeing
- Clouds
- Blur

---

Example:

Acquisitions:

```

1000 frames

```

Use:

```

Best 20–50 %

```

---

# 12. Sharpening

More important than denoising with planets.

Suitable:

- Wavelets
- Deconvolution
- Local contrast enhancement

---

But:

Be careful.

Too much creates:

- Hard edges
- Artifacts
- Noise rings

---

# 13. Denoising

Usually:

Very little.

Recommendation:

```

0–0.03

```

---

Reason:

Planetary details are extremely small.

---

# 14. Color Correction

PCC usually not the most important step with planets.

Reason:

- Few stars
- No good reference

---

Use manually:

- White balance
- Color temperature

---

# 15. Moon Workflow

The moon is a special case.

Goal:

- Craters
- Mountains
- Shadows
- Surface structures

---

Recommendation:

```

Many individual images

↓

Stack

↓

Sharpening

↓

Contrast

↓

Export

```

---

# 16. Typical Errors Moon

## Moon completely white

Cause:

Overexposure.

Solution:

- Shorter exposure
- Lower gain

---

## Craters look artificial

Cause:

Over-sharpening.

Solution:

Fewer wavelets.

---

## Noise in dark areas

Cause:

Over-brightening.

---

# 17. Jupiter Workflow

Jupiter is more challenging.

Goal:

Make visible:

- Cloud bands
- Great Red Spot
- Moons

---

Recommendation:

```

Many short acquisitions

↓

Select best frames

↓

Stack

↓

Sharpen

↓

Color correction

```

---

# 18. Saturn Workflow

Goal:

- Ring system
- Cassini division

Requires:

- Very good seeing
- Maximum sharpness

---

# 19. Mars Workflow

Mars is difficult.

Reason:

Small angular size.

Requires:

- Very good conditions
- Short exposures
- Strong selection

---

# 20. Typical Errors

## Planet is just a bright dot

Causes:

- Focus
- Wrong exposure
- Too low magnification

---

## Planet looks soft

Causes:

- Seeing
- Exposure too long

---

## Colors wrong

Causes:

- White balance
- Automatic camera correction

---

# 21. Example Workflow Moon

Acquisition:

```

Many short frames

Low gain

```

Processing:

```

Sequence

↓

Registration

↓

Select best images

↓

Stack

↓

Sharpening

↓

Contrast

↓

Export

```

---

# 22. Quality Goal

A good lunar/planetary image:

- Shows real surface details
- Has natural colors
- Has no sharpening artifacts
- Does not appear artificial

---

# Summary

```

Short exposures

Low gain

Many frames

↓

Registration

↓

Select best images

↓

Stack

↓

Sharpening

↓

Light color correction

```
