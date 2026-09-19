# Multi-Group

> Auto-generated from `doc_data/multi_group.md`, `src/astro_process/cli.py` merge flags, and `src/astro_process/agents/multi_group_agent.py`.

---

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

## Merge — Single vs. Multiple Groups

**Single-group targets** (one EXPTIME/GAIN/FILTER combination) are automatically
materialized to `merged/<Target>_merged.fits` by the process pipeline — **no merge
step needed** and the `astra merge` subcommand is not applicable.

**Multi-group targets** (>=2 groups) require the merge step: either run
`astra process` which merges automatically (default `--merge`), or use
`astra merge <target>` to manually merge existing group stacks.

The standalone `astra merge` subcommand is useful for re-merging with different
parameters (method, weighting, filters) without re-processing each group.

## Deprecated flags

`--multi-group` and `--auto-group` are deprecated no-ops. They were kept as
a grace-period compatibility measure and are ignored; the pipeline prints a
warning when they are used. The correct way to disable merge is `--no-merge`.


## Merge subcommand (`astra merge`)

Merge existing group stacks into a single FITS.

    Scans generated/{timestamp}/group_*/04_stacked/pcc_applied.fits,
    extracts metadata from FITS headers, and merges all groups using the
    chosen method and weighting.

    Note: Requires >=2 groups. Single-group targets are automatically
    materialized to merged/ by the process pipeline (no merge step needed).
    For single-group: run 'astra process <target>' or manually copy the
    stacked FITS to merged/.
    

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `target_path` | path | Sentinel.UNSET |  |
| `--method` | Choice(weighted_average,average,median) | weighted_average | Merge method |
| `--weight-by` | Choice(frame_count,total_exposure) | frame_count | Weighting method |
| `--merge-filter` | text | Sentinel.UNSET | Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro) |
| `--output, -o` | path | Sentinel.UNSET | Output directory (default: generated/{timestamp}/merged/) |
| `--dry-run` | boolean | False | Show groups without merging |

## `process` merge flags

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--merge` | boolean |  | Enable or disable merge step (default: enabled). Note: merge requires >=2 groups; single-group targets are automatically materialized to merged/ |
| `--weight-by` | Choice(frame_count,total_exposure) | Sentinel.UNSET | Merge weighting method (overrides config) |
| `--merge-method` | Choice(weighted_average,average,median) | Sentinel.UNSET | Merge method (overrides config) |
| `--merge-filter` | text | Sentinel.UNSET | Filter selection for merge (repeatable, case-insensitive trimmed, e.g. --merge-filter Astro --merge-filter "Duo-Band"; overrides config) |

## Source: multi_group_agent.py

Multi-group processing — per-group stacks, cross-group registration, merge.

| Symbol | Kind | Description |
| --- | --- | --- |
| `build_reference_selection` | function | Choose and document the reference group for cross-group registration. |
| `copy_wcs_headers` | function | — |
| `register_to_reference_stack` | function | — |
| `MultiGroupProcessor` | class | Core multi-group stacking logic (phase 2). |
