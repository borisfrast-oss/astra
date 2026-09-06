# 03 – Dwarf mini Best Practices (formerly dwarf3)

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Overview

This chapter describes the optimal acquisition and processing strategies for the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Topics covered:

- Acquisition parameters
- Exposure times
- Gain
- Number of frames
- Darks
- Flats
- Filters
- different object types
- typical errors
- practical recommendations

---

# 1. Basic Principle of the Dwarf mini

The Dwarf mini is a smart telescope.

It handles:

- automatic tracking
- Platesolving
- object positioning
- image acquisition
- internal alignment

However, the quality of the final result heavily depends on acquisition planning.

Important factors:

1. Integration time
2. Exposure time per frame
3. Gain
4. Number of individual frames
5. Sky background
6. Filter selection

---

# 2. Recommended Standard Acquisition

For typical deep-sky objects:

| Parameter | Recommendation |
|---|---|
| Exposure | 180 seconds |
| Gain | 40 |
| Format | FITS |
| Number of lights | 30–100 |
| Dark frames | 10–20 |
| Filter | depends on object |

---

# 3. Exposure Time

Exposure time determines:

- how many photons are collected
- how visible faint structures become

---

## 180 Seconds

For the Dwarf mini an excellent standard.

Suitable for:

- Galaxies
- Nebulae
- Star clusters

Advantages:

- Good signal amount
- Fewer individual frames needed

---

## Shorter Exposures

Examples:

```

10 seconds
30 seconds
60 seconds

```

Suitable for:

- Bright stars
- Moon
- Planets
- Very bright objects

Advantages:

- Stars saturate less
- Tracking errors have less effect

---

## Longer Exposures

Example:

```

300 seconds

```

can theoretically provide more signal.

Disadvantages:

- Higher requirements
- More tracking errors
- More background light

---

# 4. Gain

Gain amplifies the sensor signal.

Important:

Gain does not create additional light.

It only changes:

- Amplification
- Readout behavior
- Dynamic range

---

## Recommendation

For deep sky:

```

Gain 40

```

Good compromise between:

- Sensitivity
- Dynamic range
- Noise behavior

---

# 5. Number of Lights

More frames improve quality.

Recommendations:

| Object | Recommendation |
|---|---:|
| Bright star cluster | 20–30 |
| Galaxy | 50+ |
| Nebula | 50–100+ |
| Very faint objects | As many as possible |

---

# 6. Why the Dwarf Sometimes Cannot Stack More

During automatic stacking in the Dwarf it can happen:

- Few frames are rejected
- Stars are not recognized
- Tracking quality is insufficient

Possible causes:

- Too few stars
- Clouds
- Dew
- Light pollution
- Poor focus

Individual frames can still be used in Siril.

---

# 7. Darks

## Purpose

Darks remove:

- Hot pixels
- Dark current
- Fixed sensor errors

---

# 8. Dark Acquisition with the Dwarf mini

Rules:

Darks must be identical to lights.

Identical:

| Parameter | Must match |
|---|---|
| Exposure time | Yes |
| Gain | Yes |
| Camera | Yes |
| Filter | Yes |

---

Example:

Lights:

```

180 seconds
Gain 40
No filter

```

Darks:

```

180 seconds
Gain 40
No filter

```

---

# 9. Darks With or Without ND Filter?

Recommendation:

No change from lights.

If lights were acquired without ND:

→ Darks without ND.

If lights were acquired with filter:

→ Darks with same configuration.

Reason:

Darks do not measure the subject.

They measure the sensor.

---

# 10. Number of Darks

Recommendation:

| Number | Quality |
|---:|---|
| 5 | Sufficient |
| 10 | Good |
| 20 | Very good |
| 30+ | Little further improvement |

---

# 11. Flats

Flats are more difficult than darks.

They require:

- Same optics
- Same orientation
- Same camera

They correct:

- Dust
- Vignetting
- Uneven illumination

---

# 12. When to Use Flats

Useful when:

- Visible spots
- Strong edge falloff
- Filter changes

Not strictly necessary:

- When image is uniform
- For short test acquisitions

---

# 13. Bias with the Dwarf mini

Bias is important for classical astrocameras.

With the Dwarf mini:

Usually not necessary.

Recommended workflow:

```

Lights

*

Darks

↓

Calibrated images

```

---

# 14. Filters

## No Filter

Suitable for:

- Galaxies
- Star clusters
- Stars

Advantages:

- Natural colors
- Maximum light

---

## Dual-band Filter

Suitable for:

- Emission nebulae

Examples:

- H-alpha
- OIII

Advantages:

- Better nebula structures
- Less light pollution

Disadvantages:

- Stars dimmer
- Colors change

---

# 15. Combining Different Exposure Times

Yes, this is possible.

Example:

M31:

```

60 × 180 seconds

*

30 × 30 seconds

```

Goal:

Long exposure:

- Outer regions
- Nebula structures

Short exposure:

- Core region
- Bright stars

---

The result usually is not simply stacked together.

Better:

```

Stack long exposure

↓

Stack short exposure

↓

Combine both images

```

This is called:

- HDR
- Compositing
- Luminance blending

---

# 16. Combining Dual-band and Regular Acquisitions

Also possible.

Example:

```

RGB acquisition

*

Dual-band acquisition

```

Workflow:

1. Process RGB normally
2. Stack dual-band separately
3. Extract nebula signal
4. Combine

---

# 17. Photographing Stars

For bright stars:

Examples:

- Arcturus
- Vega
- Sirius

Recommendation:

- Short exposure
- No aggressive denoising
- No strong sigma filtering

Why?

Star colors are sensitive.

---

# 18. Star Clusters

Properties:

- Many stars
- High dynamic range

Recommendation:

- Less denoising
- Careful stretching
- Preserve star colors

Winsor Sigma:

Yes, but cautiously.

---

# 19. Galaxies

Examples:

- M31
- M33
- M81

Recommendation:

```

180 seconds

Gain 40

50+ frames

```

Workflow:

- Winsor Sigma
- Background correction
- PCC
- Moderate stretching

---

# 20. Nebulae

Recommendation:

Many frames.

Especially important:

- Remove background
- Color calibration
- Don't denoise too aggressively

---

# 21. Typical Dwarf mini Issues (formerly dwarf3)

## Image completely black

Cause:

Linear image.

Solution:

Perform stretching.

---

## Image green

Cause:

OSC Bayer sensor.

Solution:

PCC then optionally SCNR.

---

## M110 disappears during denoising

Cause:

Denoising too aggressive.

Solution:

Reduce values.

Recommendation:

```

0.05–0.1

```

---

## Frame in GraXpert

Causes:

- Preview boundaries
- Background model
- Edge artifacts

Not automatically a real image error.

---

## 23. V19 Registration & Quality Gates (since astra 1.9.0)

- AZ mount (EQMODE 0) → always `astroalign --max-rotation 30` (REG-SMART auto, but verify per-group; if `fft median <0.05` → bug, force astroalign manually).
- Keep `zero_shift_threshold 0.05` (mandatory) enabled — otherwise ghosting (see M27 60s median 0.0045 → zero-shift).
- Cross-group: For Duo-Band ignore `low_corr_roh`; use `min_correlation 0.05` instead of 0.1.
- Evidence: v19 full test suite 2026-09-02 M27/C19.

---

# 22. Recommended Dwarf Workflow

For getting started:

```

Select object

↓

180 seconds

↓

Gain 40

↓

30-100 lights

↓

10-20 darks

↓

Siril calibration

↓

Registration:
General Deep Sky

↓

Stacking:
Winsor Sigma

↓

GraXpert

↓

PCC

↓

Stretch

↓

GIMP

```

---

# Most Important Rules

1. More frames are better than more aggressive processing.

2. Darks must match lights.

3. Not every object needs the same workflow.

4. Denoise late and carefully.

5. Stars are more sensitive than nebulae.

6. Natural appearance is more important than maximum brightness.
```
```
