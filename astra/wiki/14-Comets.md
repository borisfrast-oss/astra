# Workflow 14 – Comets

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

This workflow describes processing comet images with the Dwarf mini.

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

Examples:

- Comets with visible tail
- Short-period comets
- Bright visitors like C/2023 A3 (Tsuchinshan-ATLAS)

Comets differ from normal deep-sky objects.

The most important difference:

The comet moves.

---

# 1. Comet Properties

A comet consists of:

- Nucleus
- Coma
- Dust tail
- Ion tail

Typical properties:

- Stars remain stationary
- Comet moves relative to star background
- Brightness can change significantly

---

# 2. Main Problem with Stacking

With normal deep-sky images:

```

Align stars

```

With comets:

```

Align comet or stars

```

Doing both perfectly at once doesn't work.

---

# 3. Two Possible Workflows

There are two options.

---

# Option A

## Stars Optimized

Suitable when:

- Comet only faintly visible
- Stars important
- Comet shows little motion

Workflow:

```

Normal deep-sky stacking

```

---

# Option B

## Comet Optimized

Recommended when:

- Visible tail
- Multiple hours of acquisitions
- Fast motion

Workflow:

```

Align comet

↓

Stack comet

↓

Process stars separately

↓

Combine

```

---

# 4. Acquisition Recommendation

## Standard Dwarf mini

| Parameter | Recommendation |
|---|---|
| Exposure | 30–180 seconds |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | Depends on comet |

---

# 5. Exposure Time

Long exposures:

Advantages:

- Faint tail visible
- More signal

Disadvantages:

- Comet moves more

---

Recommendation:

For fast comets:

```

30–120 seconds

```

For slow comets:

```

120–180 seconds

```

---

# 6. Filter Selection

## No Filter

Standard.

Advantages:

- Natural colors
- Maximum brightness

---

## Dual-band

Only rarely useful.

Comets contain emissions, but usually dominated by:

- Reflected sunlight
- Dust

---

# 7. Preparation in Siril

Folders:

```

Comet/

lights/

darks/

output/

```

---

# 8. Create Sequence

Result:

```

comet_light_.seq

```

Check:

- Comet visible in all images
- Stars not blurred
- No clouds

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

- Vignetting
- Dust

---

## Bias

Usually:

No

---

# 11. Registration

Different with comets.

Not always use:

```

General Deep Sky

```

---

For comets use:

```

Comet registration

```

---

Goal:

The comet stays fixed during stacking.

---

# 12. Stacking

## Comet Stack

Recommendation:

```

Median

```

Or:

```

Winsor Sigma

```

---

Why:

- Removes stars as outliers
- Preserves comet structure

---

# 13. Remove Stars / Process Stars Separately

With long series often:

- Star trails
- Dark areas

Solution:

Create two stacks.

---

## Star Stack

Alignment:

```

Stars

```

---

## Comet Stack

Alignment:

```

Comet

```

---

Then:

Combine.

---

# 14. Background Correction

Very careful.

Problem:

The tail can be large area.

GraXpert can remove it.

---

Recommendation:

- Control points far from comet
- Few aggressive corrections

---

# 15. PCC

After background correction.

Workflow:

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

Comet colors:

Typical:

## Coma

Greenish

From:

- C2 emission

---

## Tail

Bluish

From:

- Ionized gases

---

Don't overdo it.

---

# 17. Denoising

Recommendation:

```

0.03–0.08

```

---

For faint tails:

Very careful.

---

# 18. Stretching

Goal:

Make visible:

- Coma
- Tail
- Structure

---

Not:

Make background completely black.

---

# 19. Typical Errors

## Comet disappeared

Cause:

Stack aligned to stars instead of comet.

---

## Tail is cut off

Cause:

GraXpert too aggressive.

---

## Stars are trails

Cause:

Used comet registration.

---

## Background spotty

Cause:

Too few images or wrong correction.

---

# 20. Example Workflow

Acquisition:

```

100 × 120 seconds

Gain 40

No filter

```

Processing:

```

Master Dark

↓

Calibration

↓

Comet registration

↓

Comet stack

↓

GraXpert carefully

↓

PCC

↓

Light denoising

↓

Stretch

↓

GIMP

```

---

# 21. Quality Goal

A good comet image:

- Shows comet motion
- Preserves tail
- Shows natural colors
- Avoids artificial artifacts

---

# Summary

```

30–180 seconds

Gain 30–40

50–200 lights

↓

Calibration

↓

Comet registration

↓

Comet stack

↓

Gentle background correction

↓

PCC

↓

Stretch

```
