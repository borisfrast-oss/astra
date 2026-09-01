# Multi-Group Stacking

## Overview

Multi-Group is **always active** since v1.7 ("Always Multi-Group"). Every
`astra process` run goes through the same multi-group pipeline regardless of
the number of groups (including exactly one group). Light frames are grouped
automatically by the acquisition parameters **EXPTIME**, **GAIN**, and
**FILTER**. Each group is processed individually, then all group stacks are
registered onto a shared reference group, color-calibrated per group
(photometric color calibration / PCC), and finally merged into a single
output.

```text
astra process "C:\Astra\M13"
  1. Discovery (group by EXPTIME/GAIN/FILTER)
  2. Calibration + Debayer (per group)
  3. Pass 1: Registration + Stacking (per group)
  4. Pass 2: Cross-Group Registration (to reference group)
  5. PCC per group
  6. Weighted Merge -> merged/<Target>_merged.fits + preview
  7. Optional cleanup of group working dirs (only with --no-keep-groups)
```

## Group hash format

A group is identified by a readable hash built from `(EXPTIME, GAIN, FILTER)`:

```text
{exptime}s{gain}_{filter}   # with filter
{exptime}s{gain}            # without filter
```

Examples:

| EXPTIME | GAIN | FILTER   | Group hash     |
|---------|------|----------|----------------|
| 15 s    | 60   | —        | `15s60`        |
| 60 s    | 40   | Duo-Band | `60s40_Duo-Band` |
| 180 s   | 100  | H-Alpha  | `180s100_H-Alpha` |

## Deprecated flags

`--multi-group` and `--auto-group` are deprecated no-ops. They were kept as
a grace-period compatibility measure and are ignored; the pipeline prints a
warning when they are used. The correct way to disable merge is `--no-merge`.
