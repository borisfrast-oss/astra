# Darks Library

## Source of truth: DwarfLab TELE / cam_0 only

Astra's Darks Library is populated from the DwarfLab export under
`C:\Dwarflab\CALI_FRAME\dark\cam_0`. Only the **TELE** camera
(`cam_0`) is used; the WIDE camera (`cam_1`) must never be synced into the
library because its hot-pixel signature does not match TELE lights.

## Library layout

Darks are stored by exposure and gain under the configured darks repository
(default `C:\Astra\_darks`):

```text
C:\Astra\_darks\
  15s40\
  30s40\
  60s40\
  120s40\
  180s40\
  ...
```

Each subdirectory contains master or raw dark frames for one `(EXPTIME, GAIN)`
combination.

## CLI commands

- `astra darks sync` — sync DwarfLab `cam_0` export into the library.
- `astra darks list` — list all `(exp)s(gain)` buckets and their frame counts.
- `astra darks check <target>` — show dark coverage for each group of a target.
- `astra darks import <path>` — import external dark frames into the library.

Use `--dry-run` to preview changes without copying files.

## Dark matching order

For every `(EXPTIME, GAIN)` group the pipeline picks darks in this order:

1. **local** — darks placed in the target's own `darks/` folder.
2. **library_exact** — darks from the library with matching exposure and gain
   (temperature matched when possible).
3. **library_nearest** — nearest-temperature dark in the same `(exp, gain)`
   bucket if no exact temperature match exists (tolerance up to 10 °C).
4. **none** — no dark available; the group remains uncalibrated but the run
   continues with a warning.

Per-group master darks are written to `generated/<ts>/00_input/master/`.
