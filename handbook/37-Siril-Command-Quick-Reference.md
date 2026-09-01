# 37 – Siril Command Quick-Reference

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Einseitige Übersicht der wichtigsten Siril-Befehle für den täglichen Workflow.
Nicht vollständig — für Details: [Siril Online-Doku](https://siril.readthedocs.io/de/stable/Commands.html).

---

# Struktur

```
Kategorie          | Befehl              | Wichtigste Parameter / Shortcut
-------------------|---------------------|------------------------------
```

---

# 1. Datei / Verzeichnis / Sequenz

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `cd` | `directory` | Arbeitsverzeichnis wechseln (`~` für Home) |
| `dir` / `ls` | — | Dateien listen (Windows: `dir`, Linux/Mac: `ls`) |
| `convert` | `basename [-debayer] [-fitseq] [-ser] [-start=N] [-out=dir]` | FITS/RAW → Siril Sequenz (`.seq` oder `.fitseq`) |
| `convertraw` | wie `convert` | Nur DSLR-RAW-Dateien konvertieren |
| `load` | `filename` | Einzelnes Bild laden |
| `close` | — | Bild + Sequenz schließen |
| `clear` | — | Konsolen-Output leeren (GUI) |

---

# 2. Kalibrierung

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `calibrate` | `seq [-bias=] [-dark=] [-flat=] [-cc=dark\|bpm] [-cfa] [-debayer] [-opt[=exp]] [-all] [-prefix=] [-fitseq]` | **Haupt-Kalibrierung** für Sequenz |
| `calibrate_single` | `image [-bias=] [-dark=] [-flat=] [-cc=...] [-cfa] [-debayer] [-opt[=exp]] [-prefix=]` | Einzelbild kalibrieren |
| `stack` | `seq rej norm weight [-rgb=] [-out=] [-prefix=]` | Master Dark/Flat/Bias erstellen (Methoden: `median`, `average`, `winsor`, `norm=add/mul`, `weight=none/noise/scale`) |

### Cosmetic Correction (Hot/Cold Pixel)
| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `find_hot` | `dark.fits cold_sigma hot_sigma` | Hot/Cold Pixel in Master Dark finden → `.lst` Datei |
| `find_cosme` | `cold_sigma hot_sigma` | Automatisch in geladenem Bild finden |
| `cosme` | `hot_pixels.lst` | Bad Pixel Map auf geladenes Bild anwenden |
| `cosme_cfa` | `hot_pixels.lst` | Für CFA-RAW-Bilder |
| `seqcosme` | `seq hot_pixels.lst [-prefix=]` | Auf ganze Sequenz anwenden |

**`.lst` Format:**
```
P x y [C|H]   # Pixel (C=cold, H=hot)
C x 0         # Spalte x
L y 0         # Zeile y
```

---

# 3. Registrierung

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `register` | `seq [-2pass] [-drizzle] [-transf=] [-minpairs=] [-maxstars=] [-luminance] [-filter=] [-prefix=]` | Deep Sky Registrierung |
| `register_comet` | `seq [-prefix=]` | Kometen-Registrierung (Orbital-Elemente im Header) |

### Wichtige Parameter `register`
| Parameter | Standard | Empfehlung |
|-----------|----------|------------|
| `-2pass` | aus | Bei großen Rotationen/Verzerrungen |
| `-drizzle` | aus | Für Drizzle-Stacking (Auflösung↑) |
| `-transf=homography` | homography | `translation`, `similarity`, `affine`, `homography` |
| `-minpairs=10` | 10 | Mindest Sternpaare |
| `-maxstars=500` | 500 | 300–500 Deep Sky, 200 sternreich |
| `-luminance` | an | Luminanz für Sternsuche nutzen |

---

# 4. Stacking

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `stack` | `seq rej norm weight [-rgb=] [-out=] [-prefix=]` | Bilder stacken |

### Parameter
| Parameter | Optionen | Empfehlung |
|-----------|----------|------------|
| `rej` (Rejection) | `none`, `minmax`, `sigma`, `winsor`, `median`, `ksigma` | `winsor` (Deep Sky Standard) |
| `norm` (Normalisierung) | `none`, `add`, `mul`, `addscale` | `addscale` (Dwarf 3) |
| `weight` (Gewichtung) | `none`, `noise`, `scale`, `exptime` | `noise` oder `exptime` |
| `-rgb=` | `r,g,b` | RGB-Gewichtung (meist **nicht** setzen, PCC macht's) |

### Rejection-Methoden
| Methode | Verhalten |
|---------|-----------|
| `winsor` | Sigma-Clipping mit Ersetzen durch Grenzwerte (robust, Standard) |
| `sigma` | Klassisches Sigma-Clipping (Ausreißer entfernen) |
| `minmax` | Min/Max pro Pixel entfernen (wenige Frames) |
| `median` | Median-Stacking (robust, wenig Signalgewinn) |
| `ksigma` | K-Sigma iterativ (für viele Frames) |

---

# 5. Hintergrund / Gradient

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `bg` | — | Hintergrund-Median anzeigen |
| `bgnoise` | — | Hintergrund-Rauschen (MAD) anzeigen |
| `gradient` | — | **GUI only:** Background Extraction (DBE) — Polynom Grad 1–3, Sample Points |

> **Hinweis:** `gradient` ist **nicht scriptbar** (GUI-only). Für Automation: externes Tool (GraXpert) oder Astra-Pipeline.

---

# 6. Farbkalibrierung

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `pcc` | `[-gaia] [-local] [-gray] [-save]` | Photometric Color Calibration |
| `scnr` | `[amount]` | Green Noise Removal (Standard: 0.5) |
| `ccm` | `m00 m01 m02 m10 m11 m12 m20 m21 m22 [gamma]` | Farbkonvertierungsmatrix (9 Werte) |

### PCC Optionen
| Option | Bedeutung |
|--------|-----------|
| `-gaia` | Gaia DR3 Katalog (Online, Standard) |
| `-local` | Lokaler Katalog (Tycho2, offline) |
| `-gray` | Gray-World Fallback (kein Katalog) |
| `-save` | Korrektur-Faktoren in Header speichern |

**Reihenfolge:** Stack → Background Extraction → **PCC** → SCNR → Stretch

---

# 7. Stretching / Histogramm

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `autostretch` | `[-linked] [shadowsclip] [targetbg]` | Auto-Stretch (Standard: -linked, -2.8σ, targetbg=0.25) |
| `asinh` | `stretch [offset] [-human] [-clipmode=]` | Asinh-Stretch (linear → non-linear) |
| `ght` | `-D= [-B=] [-SP=] [-HP=] [-LP=] [-human\|-even\|-independent\|-sat] [channels]` | Generalized Hyperbolic Stretch (fortgeschritten) |
| `histo` | `channel (0=R, 1=G, 2=B)` | Histogramm berechnen → `histo_[Kanal].dat` |

### Wichtige Stretch-Parameter
| Parameter | Bereich | Typisch |
|-----------|---------|---------|
| `stretch` (asinh) | 1–1000 | 10–50 (Deep Sky) |
| `offset` (asinh) | 0–1 | 0.05–0.15 (Schwarzpunkt) |
| `-D` (ght) | 0–10 | 0.3–1.0 (Stretch-Stärke) |
| `-SP` (ght) | 0–1 | 0.0–0.3 (Symmetriepunkt) |
| `-HP` (ght) | 0–1 | 0.7–1.0 (Highlight-Schutz) |

---

# 8. Photometrie / Astrometrie / Analyse

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `solve-field` | `[options]` | Interner Plate Solver (schnell) |
| `astrometry.net` | `[options]` | Externer Solver (robust, braucht Installation) |
| `catsearch` | `name` | Objekt nach Name suchen (SIMBAD) |
| `conesearch` | `[limit_mag] [-cat=] [-phot] [-out=]` | Katalog-Sterne im FoV (Gaia, Tycho2, PGC, etc.) |
| `findstar` | `[-out=] [-layer=] [-maxstars=]` | Sterne detektieren |
| `psf` | — | PSF-Fitting auf erkannten Sternen |
| `findcompstars` | `star_name [-narrow\|-wide] [-catalog=] [-dvmag=] [-out=]` | Vergleichssterne für Variablen |
| `light_curve` | `seq star_name comp_stars [-out=]` | Lichtkurve erstellen |
| `disto` | `[clear]` | Verzerrungsfeld anzeigen (nach Plate Solving) |
| `entropy` | — | Bild-Entropie (Detail-Reichtum) |

### Kataloge für `conesearch` / `catsearch`
| Katalog | Typ | Mag Limit | Nutzung |
|---------|-----|-----------|---------|
| `gaia` / `localgaia` | Sterne | 20 | PCC, Photometrie, Astrometrie |
| `tycho2` | Sterne | 11 | Hell, schnell |
| `nomad` | Sterne | 15 | All-Sky |
| `apass` | Sterne | 17 | Photometrisch (B,V,g,r,i) |
| `pgc` | Galaxien | — | Deep-Sky Annotation |
| `solsys` | Sonnensystem | — | Kometen, Planeten |

---

# 9. Fortgeschrittene Verarbeitung

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `deconv` / `rl` / `wiener` | — | **GUI / Befehl:** Deconvolution (RL Iterationen, PSF-Modell) — **nur linear!** |
| `wavelet` | `layers` | Wavelet-Zerlegung (Skalen 1–6) |
| `extract` | `layer` | Einzelne Wavelet-Skala extrahieren |
| `wrecons` | — | Wavelet-Rekonstruktion |
| `clahe` | `cliplimit tilesize` | Local Contrast (cliplimit 2–4, tilesize 32–64) |
| `fixbanding` | `amount sigma [-vertical]` | Banding entfernen (amount 1–2, sigma 1–2) |
| `fix_xtrans` | — | Fuji X-Trans AF-Pixel-Muster korrigieren |
| `icc_assign` | `sRGB\|Rec2020\|linear\|working\|path` | ICC-Profil zuweisen |
| `icc_convert_to` | `profile [intent]` | In Profil konvertieren (intent: perceptual/relative/saturation/absolute) |
| `icc_remove` | — | Profil entfernen |

---

# 10. Export / Speichern

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `save` | `filename [.fits\|.tif\|.png\|.jpg]` | Aktuelles Bild speichern |
| `savejpg` | `filename [quality]` | JPEG speichern (Quality 1–100) |
| `savetif` | `filename [16\|32]` | TIFF speichern (16/32 Bit) |
| `seqsave` | `seq [-prefix=] [-out=]` | Sequenz-Frames speichern |

### Empfohlene Formate
| Zweck | Format | Befehl |
|-------|--------|--------|
| Archiv (linear) | FITS 32-bit | `save image.fits` |
| GIMP/Weiterbearbeitung | TIFF 16-bit | `savetif image.tif 16` |
| Web/Teilen | JPEG | `savejpg image.jpg 95` |

---

# 11. Sequenz-Steuerung (Scripting)

| Befehl | Parameter | Beschreibung |
|--------|-----------|--------------|
| `requires` | `min_version [max_version]` | Siril-Version prüfen (Script-Header) |
| `set` | `group key value` | Einstellung setzen |
| `get` | `{-a\|-A\|variable}` | Einstellung lesen |
| `runcmd` | `command` | Siril-Befehl ausführen (in Scripts) |
| `wait` | `ms` | Warten (Millisekunden) |
| `loop` / `endloop` | — | Schleife über Sequenz-Frames |

---

# 12. Shortcuts: Die 15 Befehle für 90% der Arbeit

```bash
# 1. Sequenz erstellen
convert m31_light

# 2. Master Dark
stack darks median none none -out master_dark

# 3. Kalibrieren
calibrate m31_light -dark=master_dark.fits -flat=master_flat.fits -cfa -debayer -prefix=pp_

# 4. Registrieren
register pp_m31_light -luminance -transf=homography -minpairs=10 -maxstars=500

# 5. Stacken
stack r_pp_m31_light winsor addscale noise -out m31_stacked

# 6. Plate Solving (für PCC)
astrometry.net --downsample 2

# 7. PCC
pcc -gaia

# 8. Green Removal
scnr 0.5

# 9. Auto-Stretch (Kontrolle)
autostretch -linked -2.8 0.25

# 10. Asinh Stretch (Final)
asinh 25 0.1

# 11. Export für GIMP
savetif m31_final.tif 16

# 12. Frame-Qualität prüfen
findstar -out frames.csv
# → CSV analysieren: FWHM, Sternzahl, Background

# 13. Hot Pixel finden
find_hot master_dark.fits 3 3

# 14. Cosmetic Correction
cosme hot_pixels.lst

# 15. Hilfe
help [befehl]
```

---

# 13. Parameter-Defaults für Dwarf 3 (Cheat-Sheet)

| Bereich | Parameter | Wert |
|---------|-----------|------|
| **Debayer** | CFA Pattern | RGGB (auto aus Header) |
| **Master Dark** | Methode | Median |
| **Master Flat** | Methode | Median |
| **Kalibrierung** | Cosmetic | bei Problemen |
| | CFA Equalize | an (Dual-Band) |
| **Registrierung** | Methode | Deep Sky / Homography |
| | Min Sternpaare | 10 |
| | Max Sterne | 500 |
| | Luminanz | an |
| **Stack** | Methode | Winsor Sigma |
| | Normalisierung | Additiv + Skalierung |
| | Gewichtung | Noise / Exptime |
| | Rejection | 2–3 Sigma |
| **Background** | Modell | Polynom Grad 1–2 |
| | Sample Points | nur freier Himmel |
| **PCC** | Katalog | Gaia DR3 (Online) |
| **SCNR** | Amount | 0.5 |
| **Stretch** | Asinh | stretch 20–40, offset 0.05–0.15 |
| **Export** | Format | TIFF 16-bit (GIMP), FITS 32-bit (Archiv) |

---

# 14. Scripting-Template (Python + sirilpy)

```python
#!/usr/bin/env python3
"""Siril Script Template — Dwarf 3 Standard Workflow"""

import sirilpy as s
s.ensure_installed("numpy", "astropy")

from sirilpy import SirilInterface
import numpy as np

siril = SirilInterface()
siril.connect()
siril.cmd("requires", "1.4.4")

# Arbeitsverzeichnis
siril.cmd("cd", "C:/Astra/M31")

# Sequenz erstellen
siril.cmd("convert", "m31_light")

# Master Dark (falls nicht vorhanden)
siril.cmd("stack", "darks", "median", "none", "none", "-out=master_dark")

# Kalibrieren
siril.cmd("calibrate", "m31_light", "-dark=master_dark.fits", "-cfa", "-debayer", "-prefix=pp_")

# Registrieren
siril.cmd("register", "pp_m31_light", "-luminance", "-transf=homography", "-minpairs=10", "-maxstars=500")

# Stacken
siril.cmd("stack", "r_pp_m31_light", "winsor", "addscale", "noise", "-out=m31_stacked")

# Plate Solving
siril.cmd("astrometry.net", "--downsample=2")

# PCC
siril.cmd("pcc", "-gaia")

# SCNR
siril.cmd("scnr", "0.5")

# Stretch + Export
siril.cmd("asinh", "30", "0.1")
siril.cmd("savetif", "m31_final.tif", "16")

siril.disconnect()
print("Done!")
```

---

# 15. Weiterführende Links

- **Siril Commands (vollständig):** https://siril.readthedocs.io/de/stable/Commands.html
- **Siril Python API:** https://siril.readthedocs.io/de/stable/Python-API.html
- **Siril Scripts Repository:** https://gitlab.com/free-astro/siril-scripts
- **Astrometry.net:** https://astrometry.net
- **Gaia DR3:** https://gea.esac.esa.int/archive/

---

> **Tipp:** Dieses Blatt als PDF drucken und am Arbeitsplatz aufhängen.
> Bei Fragen: `help <befehl>` in der Siril-Konsole.