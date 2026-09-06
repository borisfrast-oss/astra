# 37 – Siril Command Quick-Reference

# Dwarf mini + Siril 1.4.4 Best Practices Handbook — Profile `dwarf_mini` (alias `dwarf3` deprecated since V19)

---

# Goal

One-page overview of the most important Siril commands for daily workflow.
Not complete — for details: [Siril Online Docs](https://siril.readthedocs.io/en/stable/Commands.html).

---

# Structure

```
Category           | Command             | Most Important Parameters / Shortcut
-------------------|---------------------|------------------------------
```

---

# 1. File / Directory / Sequence

| Command | Parameters | Description |
|---------|-----------|--------------|
| `cd` | `directory` | Change working directory (`~` for home) |
| `dir` / `ls` | — | List files (Windows: `dir`, Linux/Mac: `ls`) |
| `convert` | `basename [-debayer] [-fitseq] [-ser] [-start=N] [-out=dir]` | FITS/RAW → Siril sequence (`.seq` or `.fitseq`) |
| `convertraw` | like `convert` | Convert DSLR RAW files only |
| `load` | `filename` | Load single image |
| `close` | — | Close image + sequence |
| `clear` | — | Clear console output (GUI) |

---

# 2. Calibration

| Command | Parameters | Description |
|---------|-----------|--------------|
| `calibrate` | `seq [-bias=] [-dark=] [-flat=] [-cc=dark\|bpm] [-cfa] [-debayer] [-opt[=exp]] [-all] [-prefix=] [-fitseq]` | **Main calibration** for sequence |
| `calibrate_single` | `image [-bias=] [-dark=] [-flat=] [-cc=...] [-cfa] [-debayer] [-opt[=exp]] [-prefix=]` | Calibrate single image |
| `stack` | `seq rej norm weight [-rgb=] [-out=] [-prefix=]` | Create master dark/flat/bias (methods: `median`, `average`, `winsor`, `norm=add/mul`, `weight=none/noise/scale`) |

### Cosmetic Correction (Hot/Cold Pixel)
| Command | Parameters | Description |
|---------|-----------|--------------|
| `find_hot` | `dark.fits cold_sigma hot_sigma` | Find hot/cold pixels in master dark → `.lst` file |
| `find_cosme` | `cold_sigma hot_sigma` | Auto-detect in loaded image |
| `cosme` | `hot_pixels.lst` | Apply bad pixel map to loaded image |
| `cosme_cfa` | `hot_pixels.lst` | For CFA RAW images |
| `seqcosme` | `seq hot_pixels.lst [-prefix=]` | Apply to entire sequence |

**`.lst` Format:**
```
P x y [C|H]   # Pixel (C=cold, H=hot)
C x 0         # Column x
L y 0         # Row y
```

---

# 3. Registration

| Command | Parameters | Description |
|---------|-----------|--------------|
| `register` | `seq [-2pass] [-drizzle] [-transf=] [-minpairs=] [-maxstars=] [-luminance] [-filter=] [-prefix=]` | Deep Sky registration |
| `register_comet` | `seq [-prefix=]` | Comet registration (orbital elements in header) |

### Important `register` Parameters
| Parameter | Default | Recommendation |
|-----------|---------|------------|
| `-2pass` | off | For large rotations/distortions |
| `-drizzle` | off | For drizzle stacking (resolution↑) |
| `-transf=homography` | homography | `translation`, `similarity`, `affine`, `homography` |
| `-minpairs=10` | 10 | Minimum star pairs |
| `-maxstars=500` | 500 | 300–500 deep sky, 200 star-rich |
| `-luminance` | on | Use luminance for star search |

---

# 4. Stacking

| Command | Parameters | Description |
|---------|-----------|--------------|
| `stack` | `seq rej norm weight [-rgb=] [-out=] [-prefix=]` | Stack images |

### Parameters

> **Note (V19):** Since V19 the profile is named `dwarf_mini`; `dwarf3` remains as a deprecated alias for compatibility. Hardware identical.

| Parameter | Options | Recommendation |
|-----------|---------|------------|
| `rej` (Rejection) | `none`, `minmax`, `sigma`, `winsor`, `median`, `ksigma` | `winsor` (deep sky standard) |
| `norm` (Normalization) | `none`, `add`, `mul`, `addscale` | `addscale` (Dwarf mini) |
| `weight` (Weighting) | `none`, `noise`, `scale`, `exptime` | `noise` or `exptime` |
| `-rgb=` | `r,g,b` | RGB weighting (usually **not** set, PCC does it) |

### Rejection Methods
| Method | Behavior |
|--------|-----------|
| `winsor` | Sigma clipping with replacement by limits (robust, standard) |
| `sigma` | Classical sigma clipping (remove outliers) |
| `minmax` | Remove min/max per pixel (few frames) |
| `median` | Median stacking (robust, little signal gain) |
| `ksigma` | K-sigma iterative (many frames) |

---

# 5. Background / Gradient

| Command | Parameters | Description |
|---------|-----------|--------------|
| `bg` | — | Show background median |
| `bgnoise` | — | Show background noise (MAD) |
| `gradient` | — | **GUI only:** Background extraction (DBE) — polynomial degree 1–3, sample points |

> **Note:** `gradient` is **not scriptable** (GUI-only). For automation: external tool (GraXpert) or Astra pipeline.

---

# 6. Color Calibration

| Command | Parameters | Description |
|---------|-----------|--------------|
| `pcc` | `[-gaia] [-local] [-gray] [-save]` | Photometric Color Calibration |
| `scnr` | `[amount]` | Green Noise Removal (default: 0.5) |
| `ccm` | `m00 m01 m02 m10 m11 m12 m20 m21 m22 [gamma]` | Color conversion matrix (9 values) |

### PCC Options
| Option | Meaning |
|--------|-----------|
| `-gaia` | Gaia DR3 catalog (online, default) |
| `-local` | Local catalog (Tycho2, offline) |
| `-gray` | Gray-world fallback (no catalog) |
| `-save` | Save correction factors to header |

**Order:** Stack → Background Extraction → **PCC** → SCNR → Stretch

---

# 7. Stretching / Histogram

| Command | Parameters | Description |
|---------|-----------|--------------|
| `autostretch` | `[-linked] [shadowsclip] [targetbg]` | Auto-stretch (default: -linked, -2.8σ, targetbg=0.25) |
| `asinh` | `stretch [offset] [-human] [-clipmode=]` | Asinh stretch (linear → non-linear) |
| `ght` | `-D= [-B=] [-SP=] [-HP=] [-LP=] [-human\|-even\|-independent\|-sat] [channels]` | Generalized hyperbolic stretch (advanced) |
| `histo` | `channel (0=R, 1=G, 2=B)` | Calculate histogram → `histo_[channel].dat` |

### Important Stretch Parameters
| Parameter | Range | Typical |
|-----------|-------|---------|
| `stretch` (asinh) | 1–1000 | 10–50 (deep sky) |
| `offset` (asinh) | 0–1 | 0.05–0.15 (black point) |
| `-D` (ght) | 0–10 | 0.3–1.0 (stretch strength) |
| `-SP` (ght) | 0–1 | 0.0–0.3 (symmetry point) |
| `-HP` (ght) | 0–1 | 0.7–1.0 (highlight protection) |

---

# 8. Photometry / Astrometry / Analysis

| Command | Parameters | Description |
|---------|-----------|--------------|
| `solve-field` | `[options]` | Internal plate solver (fast) |
| `astrometry.net` | `[options]` | External solver (robust, needs installation) |
| `catsearch` | `name` | Search object by name (SIMBAD) |
| `conesearch` | `[limit_mag] [-cat=] [-phot] [-out=]` | Catalog stars in FoV (Gaia, Tycho2, PGC, etc.) |
| `findstar` | `[-out=] [-layer=] [-maxstars=]` | Detect stars |
| `psf` | — | PSF fitting on detected stars |
| `findcompstars` | `star_name [-narrow\|-wide] [-catalog=] [-dvmag=] [-out=]` | Comparison stars for variables |
| `light_curve` | `seq star_name comp_stars [-out=]` | Create light curve |
| `disto` | `[clear]` | Show distortion field (after plate solving) |
| `entropy` | — | Image entropy (detail richness) |

### Catalogs for `conesearch` / `catsearch`
| Catalog | Type | Mag Limit | Usage |
|---------|-----|-----------|---------|
| `gaia` / `localgaia` | Stars | 20 | PCC, photometry, astrometry |
| `tycho2` | Stars | 11 | Bright, fast |
| `nomad` | Stars | 15 | All-sky |
| `apass` | Stars | 17 | Photometric (B,V,g,r,i) |
| `pgc` | Galaxies | — | Deep-sky annotation |
| `solsys` | Solar system | — | Comets, planets |

---

# 9. Advanced Processing

| Command | Parameters | Description |
|---------|-----------|--------------|
| `deconv` / `rl` / `wiener` | — | **GUI / Command:** Deconvolution (RL iterations, PSF model) — **linear only!** |
| `wavelet` | `layers` | Wavelet decomposition (scales 1–6) |
| `extract` | `layer` | Extract single wavelet scale |
| `wrecons` | — | Wavelet reconstruction |
| `clahe` | `cliplimit tilesize` | Local contrast (cliplimit 2–4, tilesize 32–64) |
| `fixbanding` | `amount sigma [-vertical]` | Remove banding (amount 1–2, sigma 1–2) |
| `fix_xtrans` | — | Fix Fuji X-Trans AF pixel pattern |
| `icc_assign` | `sRGB\|Rec2020\|linear\|working\|path` | Assign ICC profile |
| `icc_convert_to` | `profile [intent]` | Convert to profile (intent: perceptual/relative/saturation/absolute) |
| `icc_remove` | — | Remove profile |

---

# 10. Export / Save

| Command | Parameters | Description |
|---------|-----------|--------------|
| `save` | `filename [.fits\|.tif\|.png\|.jpg]` | Save current image |
| `savejpg` | `filename [quality]` | Save JPEG (quality 1–100) |
| `savetif` | `filename [16\|32]` | Save TIFF (16/32-bit) |
| `seqsave` | `seq [-prefix=] [-out=]` | Save sequence frames |

### Recommended Formats
| Purpose | Format | Command |
|---------|--------|--------|
| Archive (linear) | FITS 32-bit | `save image.fits` |
| GIMP/Further edit | TIFF 16-bit | `savetif image.tif 16` |
| Web/Sharing | JPEG | `savejpg image.jpg 95` |

---

# 11. Sequence Control (Scripting)

| Command | Parameters | Description |
|---------|-----------|--------------|
| `requires` | `min_version [max_version]` | Check Siril version (script header) |
| `set` | `group key value` | Set setting |
| `get` | `{-a\|-A\|variable}` | Read setting |
| `runcmd` | `command` | Execute Siril command (in scripts) |
| `wait` | `ms` | Wait (milliseconds) |
| `loop` / `endloop` | — | Loop over sequence frames |

---

# 12. Shortcuts: The 15 Commands for 90% of the Work

```bash
# 1. Create sequence
convert m31_light

# 2. Master dark
stack darks median none none -out master_dark

# 3. Calibrate
calibrate m31_light -dark=master_dark.fits -flat=master_flat.fits -cfa -debayer -prefix=pp_

# 4. Register
register pp_m31_light -luminance -transf=homography -minpairs=10 -maxstars=500

# 5. Stack
stack r_pp_m31_light winsor addscale noise -out m31_stacked

# 6. Plate solving (for PCC)
astrometry.net --downsample 2

# 7. PCC
pcc -gaia

# 8. Green removal
scnr 0.5

# 9. Auto-stretch (check)
autostretch -linked -2.8 0.25

# 10. Asinh stretch (final)
asinh 25 0.1

# 11. Export for GIMP
savetif m31_final.tif 16

# 12. Check frame quality
findstar -out frames.csv
# → Analyze CSV: FWHM, star count, background

# 13. Find hot pixels
find_hot master_dark.fits 3 3

# 14. Cosmetic correction
cosme hot_pixels.lst

# 15. Help
help [command]
```

---

# 13. Parameter Defaults for Dwarf mini (Cheat Sheet)

| Category | Parameter | Value |
|---------|-----------|------|
| **Debayer** | CFA Pattern | RGGB (auto from header) |
| **Master Dark** | Method | Median |
| **Master Flat** | Method | Median |
| **Calibration** | Cosmetic | if needed |
| | CFA Equalize | On (dual-band) |
| **Registration** | Method | Deep Sky / Homography |
| | Min star pairs | 10 |
| | Max stars | 500 |
| | Luminance | On |
| **Stack** | Method | Winsor Sigma |
| | Normalization | Additive + Scaling |
| | Weighting | Noise / Exptime |
| | Rejection | 2–3 Sigma |
| **Background** | Model | Polynomial degree 1–2 |
| | Sample points | Free sky only |
| **PCC** | Catalog | Gaia DR3 (Online) |
| **SCNR** | Amount | 0.5 |
| **Stretch** | Asinh | stretch 20–40, offset 0.05–0.15 |
| **Export** | Format | TIFF 16-bit (GIMP), FITS 32-bit (archive) |

---

# 14. Scripting Template (Python + sirilpy)

```python
#!/usr/bin/env python3
"""Siril Script Template — Dwarf mini Standard Workflow"""

import sirilpy as s
s.ensure_installed("numpy", "astropy")

from sirilpy import SirilInterface
import numpy as np

siril = SirilInterface()
siril.connect()
siril.cmd("requires", "1.4.4")

# Working directory
siril.cmd("cd", "C:/Astra/M31")

# Create sequence
siril.cmd("convert", "m31_light")

# Master dark (if not present)
siril.cmd("stack", "darks", "median", "none", "none", "-out=master_dark")

# Calibrate
siril.cmd("calibrate", "m31_light", "-dark=master_dark.fits", "-cfa", "-debayer", "-prefix=pp_")

# Register
siril.cmd("register", "pp_m31_light", "-luminance", "-transf=homography", "-minpairs=10", "-maxstars=500")

# Stack
siril.cmd("stack", "r_pp_m31_light", "winsor", "addscale", "noise", "-out=m31_stacked")

# Plate solving
siril.cmd("astrometry.net", "--downsample=2")

# PCC
siril.cmd("pcc", "-gaia")

# SCNR
siril.cmd("scnr", "0.5")

# Stretch + export
siril.cmd("asinh", "30", "0.1")
siril.cmd("savetif", "m31_final.tif", "16")

siril.disconnect()
print("Done!")
```

---

# 15. Further Reading

- **Siril Commands (complete):** https://siril.readthedocs.io/en/stable/Commands.html
- **Siril Python API:** https://siril.readthedocs.io/en/stable/Python-API.html
- **Siril Scripts Repository:** https://gitlab.com/free-astro/siril-scripts
- **Astrometry.net:** https://astrometry.net
- **Gaia DR3:** https://gea.esac.esa.int/archive/

---

> **Tip:** Print this sheet as PDF and hang it at your workplace.
> Questions: Use `help <command>` in the Siril console.
