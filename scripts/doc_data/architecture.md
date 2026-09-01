Astra is a Python-native, multi-phase astrophotography processing pipeline.
It transforms raw FITS frames into calibrated, color-corrected 3D RGB FITS
files plus a stretched preview JPEG. The pipeline runs entirely in Python —
no external tools such as Siril, GraXpert, or GIMP are required — making it
deterministic, CI-testable, and free of GUI dependencies.

## Phases

1. **Discovery** — scan the target directory, parse FITS headers, and build
   the `ObservationContext`.
2. **Calibration** — create master dark/flat/bias frames and apply calibration
   to lights.
3. **Debayering** — convert Bayer CFA 2D data to RGB 3D using super-pixel,
   bilinear, or Malvar2004 demosaicing.
4. **Processing** — FFT-based registration, numpy stacking, photometric color
   calibration (PCC with GAIA DR3 + gray-world fallback), SCNR, optional
   CFA-Drizzle, and the preview/export pipeline.
5. **Archive** — export linear FITS (plus optional stretched variant), an
   asinh-stretched preview JPG, and sequence files.

## Key design decisions

- **FITS headers are the single source of truth** for lights; filename
  patterns are used only as a fallback for calibration frames.
- **Multi-group stacking is always active** since v1.7: every run groups
  frames by EXPTIME/GAIN/FILTER, processes each group, and merges the results.
- **The `merged/` directory is the canonical final-output path** for both
  single-group and multi-group runs.
