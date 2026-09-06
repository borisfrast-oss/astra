# Workflow 11 – Individual Stars and Star Fields

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing individual bright stars and dense star fields with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- Arcturus
- Vega
- Sirius
- Antares
- Milky Way star fields
- Small sky regions without dominant deep-sky object

This category differs significantly from deep-sky objects.

The goal is not:

- Make faintest details visible
- Maximum stretching

The goal is:

- Natural star colors
- Sharp stars
- Controlled brightness
- Aesthetic star image

---

# 1. Properties of Star Images

A star in contrast to a galaxy or nebula is:

- Point-like
- Very bright
- Color-dependent
- Quickly saturated

The most important information lies in:

- Color
- Size
- Environment

---

# 2. Greatest Challenge

The sensor can easily overexpose very bright stars.

Results:

- Star becomes white
- Color lost
- Center blown out

Therefore:

> Shorter exposures often yield better star colors.

---

# 3. Acquisition Recommendation

## Individual Bright Stars

| Parameter | Recommendation |
|---|---|
| Exposure | 5–30 seconds |
| Gain | 20–40 |
| Lights | 20–100 |
| Darks | 10–20 |
| Filter | No filter |

---

## Star Fields

| Parameter | Recommendation |
|---|---|
| Exposure | 30–120 seconds |
| Gain | 30–40 |
| Lights | 50–100 |
| Darks | 10–20 |

---

# 4. Exposure Time

## Bright Stars

Examples:

- Arcturus
- Vega
- Sirius

Recommendation:

```

5–30 seconds

```

Why:

- Color preserved
- Core doesn't saturate

---

## Star Fields

Longer exposure possible:

```

60–120 seconds

```

Goal:

- More faint stars
- More background stars

---

# 5. Filter Selection

## No Filter

Standard.

Advantages:

- Natural colors
- Maximum light

---

## Dual-band

Not recommended.

Reason:

Stars consist of continuous light.

Dual-band reduces:

- Color components
- Natural star colors

---

# 6. Preparation in Siril

Folders:

```

Arcturus/

lights/

darks/

output/

```

---

# 7. Create Sequence

Result:

```

arcturus_light_.seq

```

Check:

- Stars visible
- Focus correct
- No motion blur

---

# 8. Master Dark

Recommendation:

```

Median

```

---

# 9. Calibration

## Dark

Yes

---

## Flat

Usually:

No

---

## Bias

Usually:

No

---

# 10. Registration

Menu:

Registration

---

Selection:

```

General Deep Sky

```

---

Parameters:

| Parameter | Value |
|---|---|
| Transformation | Homography |
| Minimum star pairs | 10 |
| Luminance | Active |
| Maximum stars | 200–500 |
| Distortion removal | Off |

---

# 11. Peculiarity with Few Stars

With a single bright star automatic star detection can be difficult.

Problems:

- Too few reference stars
- Wrong alignment

Solution:

- Use longer star fields
- Keep multiple stars in frame

---

# 12. Stacking

Recommendation:

For star images:

```

Average

```

or

```

Winsor Sigma

```

---

Difference:

## Average

Advantage:

- Maximum color information

Disadvantage:

- Outliers remain

---

## Winsor Sigma

Advantage:

- Removes satellites
- Removes individual errors

Disadvantage:

- Can be more aggressive with very few images

---

# 13. Normalization

Recommendation:

```

Additive

```

---

# 14. RGB Weighting

Recommendation:

```

Off

```

Reason:

Color calibration follows later.

---

# 15. Background Correction

With individual stars be careful.

Problem:

A dark background is not always correct.

The environment contains:

- Milky Way light
- Dust
- Faint stars

---

# GraXpert

Use only if:

- Clear gradients present

Not:

For pure star images automatically.

---

# 16. PCC

Can be useful.

After:

```

Stack

↓

Optional GraXpert

↓

PCC

```

---

# 17. Color Management

With stars especially important.

Examples:

## Arcturus

Should:

- Appear orange-yellow

Not:

- Blue or white

---

## Vega

Should:

- Appear slightly bluish

---

## Betelgeuse

Should:

- Appear orange-red

---

# 18. Denoising

Minimal.

Recommendation:

```

0–0.05

```

Often:

Not necessary.

Why?

With star fields noise is less of a problem than detail loss.

---

# 19. Stretching

Very careful.

Goal:

- Make stars visible
- Preserve colors

Not:

Maximum brightening.

---

Recommendation:

```

Small stretch

↓

Check

↓

Small stretch

```

---

# 20. Sharpening

Not necessary.

Stars are already point sources.

Too much sharpening creates:

- Dark halos
- Unnatural edges

---

# 21. Typical Errors

## Star becomes blue

Causes:

- Wrong color calibration
- White balance error
- Over-correction of color

Solution:

Check PCC.

---

## Everything green after stack

Cause:

OSC Bayer color processing.

Solution:

Perform PCC.

---

## Stars lose color

Causes:

- Exposure too long
- Stretching too strong

Solution:

Shorter exposure or HDR.

---

## Stars are huge balls

Causes:

- Focus
- Too much denoising
- Over-sharpening

---

# 22. Example Workflow Arcturus

Acquisition:

```

50 × 15 seconds

Gain 30

No filter

```

Processing:

```

Master Dark

↓

Calibration

↓

Registration

↓

Stacking

↓

PCC

↓

No denoising

↓

Minimal stretch

```

---

# 23. Quality Goal

A good star image:

- Shows natural colors
- Preserves brightness differences
- Is not over-sharpened
- Shows natural background

---

# Summary

```

5–120 seconds

Gain 20–40

20–100 lights

No filter

↓

Calibration

↓

Registration

↓

Stacking

↓

PCC

↓

Minimal stretch

```
