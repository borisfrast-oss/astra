# Chapter 20 – Dwarf mini Imaging Recommendations

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This chapter describes optimal recording parameters for the Dwarf mini in combination with Siril 1.4.4.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

It's not about post-processing, but the most important foundation:

**collect good raw data.**

The quality of the final result is largely determined during recording.

---

# 1. Basic Principle of Dwarf mini Workflow

A smart telescope like the Dwarf mini works differently than a classical astro camera.

The most important factors:

- limited aperture
- small sensor
- automatic tracking
- no classical cooling
- integrated optics
- automatic stacking

Therefore:

## More good individual images usually beat a single perfect image.

---

Basic rule:

```

more Lights

*

correct exposure

*

clean calibration

=

better final image

```

---

# 2. Three Most Important Recording Parameters

Quality is mainly determined by:

1. Exposure time
2. Gain
3. Number of images

---

# 3. Exposure Time

Exposure time determines:

- Signal amount
- Background brightness
- Star saturation
- Tracking errors

---

# 3.1 Short Exposures

Typical:

```

0.5–10 seconds

```

Suitable for:

- Moon
- Planets
- bright stars
- double stars

Advantages:

- sharp stars
- less overexposure

Disadvantages:

- less signal
- more individual images needed

---

# 3.2 Medium Exposures

Typical:

```

10–60 seconds

```

Suitable for:

- star clusters
- bright nebulae
- bright galaxies

---

# 3.3 Long Exposures

Typical:

```

60–180 seconds

```

Suitable for:

- Deep Sky
- faint nebulae
- galaxies

---

# 3.4 Maximum Exposure

180 seconds is usually the practical sweet spot with the Dwarf mini.

Longer exposures often bring fewer benefits:

Problems:

- background becomes brighter
- stars saturate
- tracking errors become more visible

---

# 4. Gain Settings

Gain affects:

- sensitivity
- noise
- dynamic range

---

# 4.1 Low Gain

Range:

```

0–20

```

Suitable for:

- Moon
- Stars
- bright objects

Advantages:

- more dynamic range
- better star colors

---

# 4.2 Medium Gain

Range:

```

20–40

```

The typical Deep-Sky range.

Suitable for:

- galaxies
- nebulae
- star clusters

---

# 4.3 High Gain

Range:

```

40+

```

Suitable for:

- very faint objects
- short exposures

Disadvantages:

- more noise
- less dynamic range

---

# 5. Recommended Dwarf mini Profiles

## Profile A – Deep Sky Standard

For:

- galaxies
- nebulae
- star clusters

```

Exposure: 120–180 seconds
Gain: 30–40
Lights: 100–300

```

---

## Profile B – Faint Nebulae

For:

- Heart Nebula
- Soul Nebula
- Veil Nebula

```

Exposure: 180 seconds
Gain: 40
Lights: 200–500

```

---

## Profile C – Bright Objects

For:

- M42 core
- Pleiades
- bright stars

```

Exposure: 5–60 seconds
Gain: 10–30
Lights: 100+

```

---

## Profile D – Moon

```

Exposure: milliseconds to few seconds
Gain: 0–20
many frames

```

---

# 6. Number of Lights

The most important rule:

## Signal grows linearly

## Noise shrinks with the square root

---

Example:

100 images instead of 25 images:

- 4× more data
- approximately double noise improvement

---

Recommendations:

| Object | Number of Lights |
|---|---:|
| Moon | many short frames |
| Planets | many frames |
| Stars | 50–200 |
| Star clusters | 100–300 |
| Nebulae | 200–500 |
| Galaxies | 100–300 |

---

# 7. Darks

Darks contain:

- sensor noise
- hot pixels
- thermal signal

---

Recommendation:

```

10–30 Dark frames

```

---

More doesn't help much.

---

Important:

Darks must be as similar as possible:

- same exposure
- same gain
- same temperature

---

# 8. Flats

Flats correct:

- vignetting
- dust
- uneven illumination

---

Especially helpful with Dwarf for:

- strong stretching
- nebulae
- galaxies

---

Problem:

Wrong Flats worsen the image.

---

Typical errors:

- different camera position
- different focus setting
- wrong exposure

---

# 9. Bias

Bias measures minimum electronic offset of sensor.

With Dwarf:

usually optional.

---

Many users get better results with:

```

Dark + Flat

```

than with:

```

Dark + Flat + Bias

```

---

# 10. Filter Strategy

## No Filter

Standard.

Suitable for:

- galaxies
- star clusters
- reflection nebulae
- stars

---

## Dual-Band

Suitable for:

- emission nebulae

Examples:

- H-alpha
- OIII

---

Not ideal for:

- galaxies
- reflection nebulae
- stars

---

# 11. Recording Under Moonlight

Moon affects:

- background brightness
- contrast
- faint structures

---

Suitable:

- bright nebulae with dual-band
- star clusters
- bright objects

---

Poor:

- faint galaxies
- reflection nebulae

---

# 12. Focus

Perfect focus is more important than many other settings.

---

Control:

Stars should:

- small
- round
- symmetric

be.

---

Problems:

## Stars large

Causes:

- focus
- seeing
- overexposure

---

## Stars oval

Causes:

- tracking
- wind
- tripod

---

# 13. Seeing and Weather

Optimal conditions:

- clear night
- little wind
- stable temperature
- no high clouds

---

Not optimal:

- thin clouds
- strong air turbulence
- temperature changes

---

# 14. What If the Dwarf Automatically Stacks Less?

That's normal.

Causes:

- poor individual images
- stars not recognized
- tracking errors
- clouds
- movement

---

Better:

Many good images.

Not:

many bad images.

---

# 15. Quality Control Before Siril

Before processing check:

- Are stars round?
- Are there shaky frames?
- Are images overexposed?
- Are clouds present?
- Is object visible?

---

Sort out bad frames.

---

# 16. Recommended Standard Recording

If you don't know what to set:

```

Deep Sky:

180 seconds

Gain 35

no filter

200 Lights

10–20 Darks

Flats present

```

This is an excellent starting point for:

- M31
- M42
- M45
- M13
- many nebulae and galaxies

---

# 17. Most Important Rules Summarized

```

Don't overdo exposure time

↓

keep gain moderate

↓

record many Lights

↓

don't forget Darks

↓

create Flats correctly

↓

good raw data more important than post-processing

```
