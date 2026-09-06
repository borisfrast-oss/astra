# Output Structure

> Auto-generated from `src/astro_process/agents/archive.py`, `src/astro_process/core/fits_parser.py` `OUTPUT_SUBDIRS`, and source-extracted constants.

---

## Archive Agent

Archive — agent-log.yaml, run-info.json, and final output resolution.

## Output subdirectories skipped during scan (`OUTPUT_SUBDIRS`)

- 00_input
- 00_masters
- 01_calibrated
- 02_debayered
- 03_registered
- 04_stacked
- _siril
- calibrated
- debayered
- generated
- master
- masters
- registered
- stacked

## Run directory layout

```text
generated/<timestamp>/
├── 00_input/
│   └── master/
│       ├── master_dark_{group_hash}.fits
│       ├── master_flat_*.fits
│       └── ...
├── 01_calibrated/
├── 02_debayered/
├── group_{hash}/
│   ├── 03_registered/
│   └── 04_stacked/
│       ├── stacked.fits
│       ├── aligned.fits
│       ├── pcc_applied.fits
│       └── preview_{hash}.jpg
├── merged/
│   ├── <Target>_merged.fits
│   ├── <Target>_merged_preview.jpg
│   └── merge_report.json
├── agent-log.yaml
└── run-info.json
```

## Final output resolution

The Archive Agent resolves the final FITS in the following order:

1. `merged/<Target>_merged.fits` (canonical since v1.3-6)
2. Legacy top-level `<Target>_final.fits` (only from direct API use)

External tools should always point to the `merged/` path.
