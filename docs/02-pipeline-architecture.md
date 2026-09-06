# Pipeline Architecture

> Auto-generated from `src/astro_process/core/` module structure + `doc_data/architecture.md`.

---

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


## Core modules

### cfa_drizzle

V19-CFA-GATE core: CFA_DEFAULTS + resolver re-export.

### cosmetic

Cosmetic correction — bad-pixel map and interpolation before debayering.

| Symbol | Kind | Description |
| --- | --- | --- |
| `same_color_neighbor_median` | function | — |
| `detect_bad_pixels` | function | Derive a bad-pixel map from calibrated lights (CFA, before debayer). |
| `interpolate_bad_pixels` | function | Replace defective pixels with the median of same-color neighbors. |

### debayer

Debayering — convert Bayer CFA 2D data to RGB 3D (super-pixel / bilinear / Malvar2004).

| Symbol | Kind | Description |
| --- | --- | --- |
| `debayer_superpixel` | function | Convert Bayer CFA to RGB 3D using the super-pixel method. |
| `debayer_bilinear` | function | Convert Bayer CFA to RGB 3D using bilinear interpolation. |
| `debayer_malvar2004` | function | Convert Bayer CFA to RGB 3D using the Malvar2004 demosaicing algorithm. |
| `apply_bzero` | function | — |
| `debayer_fits` | function | — |
| `batch_debayer` | function | — |

### equipment

Equipment auto-detection from FITS headers and config profiles.

| Symbol | Kind | Description |
| --- | --- | --- |
| `detect_mount_type` | function | — |
| `detect_preferred_registration` | function | — |
| `match_equipment_profile` | function | Select the equipment profile according to the header/config priority. |
| `detect_bayer_pattern` | function | — |
| `detect_input_is_rgb` | function | — |
| `resolve_debayer_factor` | function | — |
| `resolve_equipment` | function | Resolve equipment parameters from FITS headers and config. |

### export

Export — FITS copy, header enrichment, preview generation, and Siril-compatible .seq files.

| Symbol | Kind | Description |
| --- | --- | --- |
| `effective_pixel_size_um` | function | — |
| `annotate_export_header` | function | Enrich the export FITS header with best-effort metadata. |
| `export_stretched_fits` | function | Write a stretched FITS for display purposes. |
| `export` | function | — |

### fits_parser

FITS header parser with alias handling and filename-based metadata fallback.

| Symbol | Kind | Description |
| --- | --- | --- |
| `normalize_value` | function | — |
| `get_header_value` | function | — |
| `parse_filename_metadata` | function | Extract metadata from filename when FITS header is incomplete. |
| `parse_fits_header` | function | Parse a FITS file header into the standardized FitsHeader model. |
| `apply_filename_fallback` | function | — |
| `detect_frame_type` | function | — |
| `scan_directory` | function | Scan a directory for FITS files and categorize them by frame type. |
| `build_observation_context` | function | Build a complete ObservationContext from a directory scan. |

### gradient_removal

Gradient removal — polynomial background modelling for stacked frames.

| Symbol | Kind | Description |
| --- | --- | --- |
| `GradientRemovalError` | class | — |
| `GradientModel` | class | — |
| `GradientRemovalResult` | class | — |
| `fit_background` | function | Fit a polynomial background model with iterative rejection. |
| `remove_gradient` | function | Remove a smooth background gradient from a 2D or RGB frame. |
| `shape_str` | function | — |
| `background_extraction` | function | Apply gradient removal to the stacked frame. |

### pcc

Photometric color calibration — star detection, GAIA/VizieR catalog matching, gray-world fallback.

| Symbol | Kind | Description |
| --- | --- | --- |
| `PCCResult` | class | — |
| `detect_stars` | function | — |
| `compute_pixel_scale` | function | — |
| `gray_world_white_balance` | function | Simple gray-world white balance using bright star regions. |
| `apply_pcc` | function | Apply photometric color calibration (VizieR primary, GAIA fallback since v1.6). |
| `apply_scnr` | function | Remove green cast via SCNR (subtract chromatic noise from RGB). |
| `get_pcc_fallback` | function | — |
| `photometric_color_calibration` | function | Apply PCC to the stacked frame (in-place overwrite). |
| `scnr` | function | — |

### plugins

Plugin interface for optional pipeline steps loaded via entry points.

| Symbol | Kind | Description |
| --- | --- | --- |
| `PluginResult` | class | — |
| `PluginContext` | class | — |
| `Plugin` | class | Abstract base class for pipeline-step plugins. |
| `PluginRegistry` | class | Registry for pipeline-step plugins loaded from entry points. |
| `default_registry` | function | — |
| `resolve_step` | function | Resolve the first plugin that handles a given step name. |

### preview

Auto-stretched JPG preview generation for quick visual inspection.

| Symbol | Kind | Description |
| --- | --- | --- |
| `auto_asinh` | function | — |
| `create_preview_jpg` | function | Create an auto-stretched JPG preview from a linear FITS file. |

### quality

Frame quality metrics — SNR, FWHM, outlier flagging, and double-star detection.

| Symbol | Kind | Description |
| --- | --- | --- |
| `FrameQuality` | class | — |
| `detect_double_stars` | function | — |
| `compute_frame_quality` | function | Compute SNR, FWHM median, star count, double rate, and elongation for one frame. |
| `flag_outliers` | function | — |
| `reject_outlier_frames` | function | Reject frames exceeding configurable per-metric thresholds. |
| `qual_to_dict` | function | — |
| `summarize_qualities` | function | Group-level summary of frame quality metrics. |
| `compute_frame_score` | function | — |

### registration

Registration adapters — FFT, astroalign, and rotation-FFT strategies with fallback.

| Symbol | Kind | Description |
| --- | --- | --- |
| `AstroalignResult` | class | — |
| `AstroalignUnavailableError` | class | — |
| `RegistrationTransform` | class | — |
| `RegistrationSanityError` | class | — |
| `RegistrationStrategy` | class | — |
| `FftGridRegistration` | class | FFT phase-correlation registration strategy. |
| `AstroalignRegistration` | class | Astroalign-based registration strategy (optional extra). |
| `RotationFftRegistration` | class | Log-polar FFT rotation strategy for AZ field rotation. |
| `get_astroalign` | function | — |
| `astroalign_register` | function | — |
| `create_registration` | function | — |
| `apply_rotation_shift` | function | — |

### selection

Frame selection and outlier rejection pipeline.

### seq_file

Siril-compatible sequence file helper.

| Symbol | Kind | Description |
| --- | --- | --- |
| `write_seq` | function | — |
| `read_seq` | function | — |
| `parse_seq_prefix` | function | — |

### stacking

Frame stacking — rejection mapping, winsorized sigma-clip, sigma-clipped mean.

| Symbol | Kind | Description |
| --- | --- | --- |
| `resolve_stack_method` | function | — |
| `winsorized_sigma_clip` | function | Siril-style winsorized sigma clipping along the stack axis. |
| `sigma_clipped_mean` | function | Sigma-clipped mean along the stack axis (reject, not clamp). |
| `stack_frames` | function | Stack registered frames; per-channel for 3D RGB data. |
| `stack_frames_python` | function | — |
| `stack_2d` | function | — |

### staging

Input staging — copy conventional input folders into generated/<ts>/00_input.

| Symbol | Kind | Description |
| --- | --- | --- |
| `stage_input` | function | — |

### suggest

V1.11-ENTSCHLACKUNG — core logic for ``astra suggest``.

| Symbol | Kind | Description |
| --- | --- | --- |
| `SuggestInputError` | class | — |
| `parse_target_cache` | function | — |
| `find_cache_entry` | function | — |
| `load_target_cache` | function | — |
| `classify_and_cite` | function | — |
| `query_simbad` | function | — |
| `read_fits_header` | function | — |
| `build_registration_options` | function | — |
| `SuggestResult` | class | — |
| `build_result` | function | — |
| `render_human` | function | — |
| `to_json_dict` | function | — |

## Key agents

### calibration

Calibration — master dark/bias/flat creation and application to lights.

| Symbol | Kind | Description |
| --- | --- | --- |
| `CalibrationResult` | class | Result of the calibration workflow. |
| `CalibrationAgent` | class | Handles calibration frame stacking and light-frame calibration. |
| `create_calibration_agent` | function | — |

### archive

Archive — agent-log.yaml, run-info.json, and final output resolution.

| Symbol | Kind | Description |
| --- | --- | --- |
| `ArchiveResult` | class | Paths to final FITS, agent log, and run-info JSON. |
| `ArchiveAgent` | class | Creates agent-log.yaml summarizing the pipeline run. |
| `create_archive_agent` | function | — |
