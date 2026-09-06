# Workflow 10 – Open Clusters

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing open star clusters with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- M45 Pleiades
- M44 Beehive
- M11 Wild Duck Cluster
- NGC 869/884 Double Cluster
- M35

Open star clusters are among the most attractive objects for small telescopes.

They differ from globular clusters:

- Fewer stars
- Younger stars
- Often embedded in gas and dust
- Stronger star colors

---

# 1. Open Star Cluster Properties

Open star clusters consist of:

- Young stars
- Gas remnants from star formation
- Often reflection nebulae

Typical properties:

- Many bright stars
- Large extent
- Strong color differences

---

# 2. Main Processing Goal

With open star clusters the goal is:

- Natural star colors
- Sharp stars
- Controlled background
- Preserve any nebulae present

Not:

- Maximum brightness
- Extreme stretching

---

# 3. Acquisition Recommendation

## Standard Dwarf mini

| Parameter | Recommendation |
|---|---|
| Exposure | 30–180 seconds |
| Gain | 30–40 |
| Lights | 30–100 |
| Darks | 10–20 |
| Filter | No filter |

---

# 4. Exposure Time

Open star clusters often have bright stars.

---

## Shorter Exposure

Suitable for:

- Very bright stars
- Star colors
- Large dynamic range

Example:

```

30–60 seconds

```

---

## Longer Exposure

Suitable for:

- Faint stars
- Embedded nebulae

Example:

```

120–180 seconds

```

---

# 5. HDR with Open Clusters

Useful when:

- Very bright stars
- Large brightness differences

Example:

Short series:

```

30 × 30 seconds

```

For:

- Star colors
- Bright stars

+

Long series:

```

50 × 180 seconds

```

For:

- Faint stars
- Nebulae

---

Combination:

```

Short exposure stack

*

Long exposure stack

↓

HDR composition

```

---

# 6. Filter Selection

## No Filter

Standard recommendation.

Advantages:

- Natural colors
- Maximum star number
- Better color differentiation

---

## Dual-band

Only useful for open clusters with nebula content.

Examples:

- M45
- IC 2602 with nebula structures

Don't use just for the star cluster.

---

# 7. Preparation in Siril

Folders:

```

M45/

lights/

darks/

output/

```

---

# 8. Create Sequence

Result:

```

m45_light_.seq

```

Check:

- Stars visible
- No blurred frames
- Focus stable

---

# 9. Master Dark

Recommendation:

```

Median

```

---

# 10. Calibration

## Dark

Yes

---

## Flat

Optional.

Useful when:

- Visible dust spots
- Strong vignetting

---

## Bias

Usually:

No

---

# 11. Registration

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
| Maximum stars | 500 |
| Distortion removal | Off |

---

# 12. Peculiarity: Many Stars

Open star clusters can be very star-rich.

Problem:

Siril detects too many stars.

Results:

- Slower processing
- Wrong reference stars

---

If problems occur:

Reduce maximum stars:

Standard:

```

500

```

Alternative:

```

200–300

```

---

# 13. Stacking

Recommendation:

```

Winsor Sigma

```

Why:

- Removes satellites
- Removes individual errors
- Protects against outliers

---

# Normalization

Recommendation:

```

Additive

```

---

# RGB Weighting

Recommendation:

```

Off

```

Reason:

PCC comes later.

---

# 14. Background Correction

With star clusters be careful.

The background must not become artificially black.

---

Problem:

Too aggressive correction removes:

- Faint nebulae
- Star halos
- Natural color gradients

---

# GraXpert

Recommendation:

- Few samples
- Low aggressiveness

---

# 15. PCC

After background correction:

```

Stack

↓

GraXpert

↓

PCC

↓

Stretch

```

---

# 16. Color Management

Star colors are the main subject.

Preserve:

- Blue stars
- Yellow stars
- Red giant stars

Not:

Make everything white.

---

# 17. Denoising

Very careful.

Recommendation:

```

0.00–0.05

```

Often:

No denoising needed.

---

# 18. Stretching

Goal:

- Make stars visible
- Preserve background
- No blown-out stars

---

Recommendation:

Gently:

```

Small stretch

↓

Check

↓

Small stretch

```

---

# 19. Sharpening

Optional.

Very careful.

Suitable:

- Light structure enhancement

Not:

- Hard stars
- Black halos

---

# 20. Typical Errors

## All stars are white

Causes:

- Stretching too strong
- Wrong color calibration

Solution:

Less stretch.

---

## Background completely black

Cause:

Over-processing.

Solution:

Bring back natural background.

---

## Stars look huge

Causes:

- Too much denoising
- Too much sharpening

Solution:

Less processing.

---

## Nebula disappears at M45

Cause:

GraXpert removes faint structures.

Solution:

Gentler background correction.

---

# 21. Example Workflow M45

Acquisition:

```

80 × 120 seconds

Gain 40

No filter

```

Processing:

```

Master Dark

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma Stack

↓

GraXpert carefully

↓

PCC

↓

No or minimal denoising

↓

Stretch

↓

GIMP

```

---

# 22. Quality Goal

A good open cluster image:

- Shows many stars
- Preserves natural colors
- Shows any nebula present
- Does not appear over-processed

---

# Summary

```

30–180 seconds

Gain 30–40

30–100 lights

No filter

↓

Calibration

↓

Deep Sky Registration

↓

Winsor Sigma

↓

Gentle background correction

↓

PCC

↓

Light or no denoising

↓

Natural stretching

```
