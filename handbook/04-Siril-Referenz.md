# 04 – Siril 1.4.4 Referenz

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Übersicht

Dieses Kapitel beschreibt die wichtigsten Siril-1.4.4-Funktionen und Parameter.

Ziel:

- verstehen, welche Optionen wichtig sind
- Standardwerte kennen
- sinnvolle Änderungen erkennen
- typische Fehler vermeiden

Behandelte Bereiche:

- Verzeichnisstruktur
- Sequenzen
- Konvertierung
- Kalibrierung
- Registrierung
- Stacking
- Normalisierung
- Farbkalibrierung
- Stretching
- Export

---

# 1. Arbeitsverzeichnis

Siril arbeitet immer mit einem aktuellen Arbeitsverzeichnis.

Empfehlung:

```

Projekt/

├── lights/

├── darks/

├── flats/

├── bias/

└── output/

```

---

# 2. Sequenzen

Eine Sequenz ist eine Gruppe von Bildern.

Beispiel:

```

m31_light_00001.fits
m31_light_00002.fits
m31_light_00003.fits

```

wird:

```

m31_light_.seq

```

---

# Wichtig

Die `.seq`-Datei enthält Verweise auf die Bilder.

Werden FITS-Dateien verschoben:

Problem:

```

Sequenz zeigt auf alten Pfad

```

Folge:

```

Datei nicht gefunden

```

Typische Meldung:

```

m31_light_00001.fits.[Datei-Erweiterung] nicht gefunden

```

Lösung:

Sequenz neu erzeugen.

---

# 3. Sequenz-Tab

Der Sequenz-Tab dient zur Verwaltung der geladenen Bildserie.

Typische Aufgaben:

- Sequenz öffnen
- Bilder auswählen
- Qualität prüfen
- Bilder markieren

---

# Empfehlungen

Vor Verarbeitung prüfen:

- Sind alle Bilder geladen?
- Sind Sterne sichtbar?
- Gibt es fehlerhafte Bilder?
- Sind die Dateipfade korrekt?

---

# 4. Konvertierung

## Zweck

Konvertierung erzeugt Siril-kompatible Sequenzen.

Typischer Ablauf:

```

FITS Bilder

↓

Siril Sequenz

```

---

# Parameter

## Ausgabeformat

Empfehlung:

```

FITS

```

---

## 32 Bit erzwingen

Standard:

Aus

Empfehlung:

Aus lassen.

Grund:

Der Dwarf liefert bereits geeignete FITS-Daten.

32 Bit kann sinnvoll sein bei:

- extremen Dynamikumfängen
- speziellen wissenschaftlichen Workflows

---

# RGB-Gewichtung

Standard:

Aus

Empfehlung:

Aus

Grund:

Bei OSC-Kameras übernimmt Siril die Farbverarbeitung.

Nicht manuell beeinflussen, bevor PCC erfolgt.

---

# 5. Kalibrierung

Die Kalibrierung entfernt bekannte Sensorfehler.

Ablauf:

```

Lights

*

Master Dark

*

(optional)
Master Flat

↓

kalibrierte Lights

```

---

# Master Dark erstellen

Mehrere Darks werden kombiniert.

Beispiel:

```

dark_001

dark_002

dark_003

↓

Master Dark

```

---

# Dark-Stack Parameter

## Methode

Empfehlung:

```

Median

```

Warum:

- entfernt zufällige Fehler
- erhält Hotpixelstruktur

---

## Normalisierung

Standard:

je nach Dialog

Empfehlung:

Standardwert verwenden.

Grund:

Darks haben normalerweise konstante Bedingungen.

---

# Master Flat

Nur verwenden, wenn Flats vorhanden sind.

Flats benötigen:

- gleiche Optik
- gleiche Kamera
- gleiche Konfiguration

---

# 6. Registrierung

## Zweck

Alle Bilder werden exakt ausgerichtet.

Siril erkennt Sterne und berechnet die Transformation.

---

# Auswahl

Für Deep Sky:

```

Allgemein Deep Sky

```

verwenden.

Geeignet für:

- Galaxien
- Nebel
- Sternfelder

---

# Transformation

## Homographie

Standard:

aktiv

Empfehlung:

verwenden.

Kann korrigieren:

- Verschiebung
- Rotation
- Skalierung
- leichte Verzerrung

---

# Mindest-Sternpaare

Standard:

10

Empfehlung:

10

Erhöhen nur bei Problemen.

Beispiel:

Wenn Siril falsche Sterne verwendet.

---

# Luminanz verwenden

Standard:

aktiv

Empfehlung:

aktiv lassen.

Grund:

Die Helligkeitsinformation ist stabiler für die Sternsuche.

---

# Maximale Anzahl Sterne

Standard:

500

Empfehlung:

500

Bei sehr sternreichen Feldern eventuell reduzieren.

---

# Entzerrung

Standard:

Aus

Empfehlung:

Aus

Aktivieren nur bei deutlichen Verzerrungen.

---

# 7. Stacking

Nach der Registrierung werden die Bilder kombiniert.

Ziele:

- Signal verstärken
- Rauschen reduzieren
- Ausreißer entfernen

---

# Methode

## Durchschnitt

Standard:

oft verfügbar

Eigenschaften:

- maximale Signalqualität
- empfindlich gegen Ausreißer

---

## Median

Eigenschaften:

- robust gegen Ausreißer
- weniger Signal

Geeignet:

- wenige Bilder

---

## Winsor Sigma

Empfehlung:

Deep Sky Standard.

Geeignet für:

- Galaxien
- Nebel
- lange Serien

Entfernt:

- Satelliten
- Flugzeuge
- einzelne Hotpixel

---

# 8. Normalisierung beim Stack

Normalisierung gleicht Unterschiede aus.

---

## Additiv

Verändert den Hintergrund.

Geeignet:

- wenn nur Helligkeitsunterschiede vorhanden sind

---

## Multiplikativ

Verändert die Skalierung.

Geeignet:

- wenn die Belichtung unterschiedlich wirkt

---

## Additiv + Multiplikativ

Kombiniert beide Methoden.

Geeignet:

- schwierige Datensätze

---

# Empfehlung Dwarf 3

Bei identischen Lights:

```

Additiv

```

ist meist ausreichend.

---

# 9. RGB-Gewichtung beim Stack

Standard:

Aus

Empfehlung:

Aus

Grund:

PCC übernimmt später die Farbkorrektur.

Aktivieren nur bei speziellen Problemen.

---

# 10. Ausgabe des Stacks

Typisches Ergebnis:

```

r_pp_m31_light_stacked.fits

```

Das ist ein lineares Masterbild.

Es wirkt:

- dunkel
- kontrastarm
- unscheinbar

Das ist normal.

---

# 11. Histogramm und Stretch

Ein lineares FITS sieht dunkel aus.

Nicht weil Information fehlt.

Sondern weil die Darstellung nicht angepasst ist.

---

# Auto-Stretch

Empfehlung:

Für erste Kontrolle verwenden.

Vorteil:

- schneller Überblick

Nachteil:

- nicht immer optimal

---

# Manuelles Stretching

Prinzip:

Schwarzpunkt:

- Hintergrund setzen

Mitteltöne:

- schwache Strukturen sichtbar machen

Weißpunkt:

- helle Bereiche begrenzen

---

# 12. Photometrische Farbkalibrierung (PCC)

## Zweck

Korrigiert:

- Farbstich
- Sensorabweichungen
- atmosphärische Einflüsse

---

# Voraussetzungen

Benötigt:

- Sternfelder
- Platesolving
- bekannte Himmelsposition

---

# Reihenfolge

Richtig:

```

Stack

↓

Hintergrundkorrektur

↓

PCC

↓

Stretch

```

---

Falsch:

```

Stack

↓

Stretch

↓

PCC

```

---

# 13. Hintergrundkorrektur

Siril:

Background Extraction

oder

GraXpert

---

# Empfehlung

Bei Dwarf 3:

GraXpert liefert oft sehr gute Ergebnisse.

Workflow:

```

Stack

↓

GraXpert

↓

PCC

```

---

# 14. Export

Für Weiterbearbeitung:

Empfehlung:

```

TIFF 16 Bit

```

Für Archiv:

```

FITS behalten

```

---

# 15. Siril Standardworkflow Dwarf 3

```

FITS importieren

↓

Sequenz erzeugen

↓

Master Dark

↓

Kalibrieren

↓

Registrieren

↓

Stacken

↓

GraXpert

↓

PCC

↓

Stretch

↓

Export

```

---

# 16. Häufige Fehler

## Schwarzes TIFF

Ursache:

Lineares Bild exportiert.

Lösung:

Vor Export stretchen.

---

## Alles grün

Ursache:

OSC Bayer-Farbverarbeitung.

Lösung:

PCC durchführen.

---

## Sterne verschwinden

Ursache:

Zu starkes Entrauschen.

Lösung:

Denoise reduzieren.

---

## Stack schlägt fehl

Ursachen:

- Sequenzpfade falsch
- Dateien verschoben
- beschädigte FITS
- falsche Sequenz

---

# 17. Siril 1.4.4 – Erweiterte Funktionen (Referenz)

> Diese Funktionen sind in den Standard-Workflows (Kap. 15, 22, 36) nicht enthalten,
> aber für spezielle Probleme oder fortgeschrittene Bearbeitung relevant.

---

## 17.1 Plate Solving / Astrometrie

**Menü:** `Astrometrie` → `Plate Solving`  
**Befehle:** `solve-field`, `astrometry.net`, `catsearch`, `conesearch`

### Zweck
Ermittelt die exakte Himmelsposition (WCS) des Bildes. Voraussetzung für:
- Photometrie / PCC mit Gaia-Katalog
- Objekt-Annotation (Kataloge überlagern)
- Mosaik-Stitching (Overlap-Berechnung)

### Voraussetzungen
- `astrometry.net` installiert (externes Tool)
- Index-Dateien für Brennweite/Sensor downloadet
- Sternfelder im Bild (mind. ~20 Sterne)

### Workflow
```
Stack
↓
Plate Solving (solve-field / astrometry.net)
↓
WCS im Header → PCC / Annotation / Mosaik
```

### Wichtige Befehle
| Befehl | Beschreibung |
|--------|--------------|
| `solve-field` | Interner Solver (schnell, weniger robust) |
| `astrometry.net` | Externer Solver (robust, braucht Installation) |
| `catsearch` | Objekt nach Name suchen (SIMBAD) |
| `conesearch` | Katalog-Sterne im FoV anzeigen (Gaia, Tycho2, PGC, etc.) |
| `disto` | Verzerrungsfeld anzeigen (nach Plate Solving) |

### Typische Parameter (`astrometry.net`)
- `--downsample 2` — schneller, für große Sensoren
- `--scale-units degwidth` — Skala in Grad
- `--scale-low 0.5 --scale-high 3.0` — erwarteter FoV-Bereich
- `--cpulimit 60` — Timeout in Sekunden

---

## 17.2 Photometrie

**Menü:** `Analyse` → `Photometrie`  
**Befehle:** `findstar`, `psf`, `findcompstars`, `light_curve`

### Zweck
- Stern-Helligkeiten messen (instrumentelle Magnituden)
- Vergleichssterne für variable Sterne finden
- Lichtkurven erstellen
- PSF-Parameter (FWHM, Rundheit, Background) auslesen

### Workflow
```
Stack (Plate Solved)
↓
findstar (Sterne detektieren)
↓
psf (PSF-Fitting für präzise Photometrie)
↓
findcompstars (Vergleichssterne für Variablen)
↓
light_curve (Lichtkurve erstellen)
```

### Wichtige Parameter
| Parameter | Empfehlung | Hinweis |
|-----------|------------|---------|
| `-layer` | 0 (Mono/R), 1 (G), 2 (B) | Kanal für Detektion |
| `-maxstars` | 500–1000 | Begrenzen für Performance |
| `-out` | CSV-Datei | Export für externe Analyse |
| `psf` | nach `findstar` | Fit-Modell: Moffat/Gauss |

### Kataloge für `conesearch` / `catsearch`
| Katalog | Typ | Limit Mag | Nutzung |
|---------|-----|-----------|---------|
| `gaia` / `localgaia` | Sterne | 20 | PCC, Astrometrie, Photometrie |
| `tycho2` | Sterne | 11 | Hellere Sterne, schnell |
| `nomad` | Sterne | 15 | All-Sky, gute Abdeckung |
| `apass` | Sterne | 17 | Photometrisch kalibriert (B,V,g,r,i) |
| `pgc` | Galaxien | — | Deep-Sky Objekte |
| `solsys` | Sonnensystem | — | Kometen, Asteroiden, Planeten |
| `aavso_chart` | Variable | — | Vergleichssterne für AAVSO |

---

## 17.3 Deconvolution (Schärfung)

**Menü:** `Verarbeitung` → `Deconvolution`  
**Befehle:** `deconv`, `rl` (Richardson-Lucy), `wiener`

### Zweck
Entfernung von optischer Unschärfe (Seeing, Fokus, Beugung). **Nur auf linearen Daten!**

### Methoden
| Methode | Parameter | Einsatzbereich |
|---------|-----------|----------------|
| `rl` (Richardson-Lucy) | Iterationen (10–50), Regularisierung | Standard für Deep Sky, erhält Sterne gut |
| `wiener` | Rausch-Leistungsspektrum | Wenn Rausch-Modell bekannt |
| `deconv` (GUI) | PSF-Modell (Stern/Datei), Iterationen | Interaktiv, Preview möglich |

### Empfehlung Dwarf 3
```
Stack (linear)
↓
PCC
↓
Deconvolution (RL, 15–25 Iterationen, Stern-PSF)
↓
Stretch
```

**Warnung:** Zu viele Iterationen → Ring-Artefakte um Sterne, Rauschen-Verstärkung.

---

## 17.4 Wavelets (Detail-Enhancement)

**Menü:** `Verarbeitung` → `Wavelets`  
**Befehle:** `wavelet`, `extract`, `wrecons`

### Zweck
Multi-Skalen-Zerlegung für gezielte Schärfung/Grauntung pro Skala.

### Workflow
```
wavelet layers [1-6]     → Zerlegung in Skalen
extract layer            → Einzelne Skala bearbeiten
wrecons                  → Rekonstruktion
```

### Typische Anwendung
- **Skalen 1-2:** Stern-Schärfung (kleine Strukturen)
- **Skalen 3-4:** Nebel-Details (mittlere Strukturen)
- **Skalen 5-6:** Großflächige Strukturen (meist unberührt lassen)

---

## 17.5 CLAHE (Local Contrast Enhancement)

**Befehl:** `clahe cliplimit tilesize`

### Zweck
Kontrastbegrenzte adaptive Histogramm-Ausgleichung. Hebt lokale Details hervor ohne globales Überstrahlen.

### Parameter
| Parameter | Bereich | Empfehlung |
|-----------|---------|------------|
| `cliplimit` | 1–10 | 2–4 (höher = stärker, mehr Artefakte) |
| `tilesize` | 8–128 | 32–64 (kleiner = lokaler, größer = globaler) |

### Einsatz
Nach Stretch, vor Export — für "Pop" in Nebelstrukturen.

---

## 17.6 Cosmetic Correction (Hot/Cold Pixel)

**Menü:** `Kalibrierung` → `Cosmetic Correction`  
**Befehle:** `find_hot`, `find_cosme`, `cosme`, `cosme_cfa`, `seqcosme`

### Zweck
Entfernung verbleibender Hot/Cold Pixel nach Kalibrierung.

### Workflow
```
Master Dark erstellen
↓
find_hot master_dark.fits 3 3  → hot_pixels.lst (3σ hot, 3σ cold)
↓
cosme hot_pixels.lst           → auf Lights anwenden
```

### Parameter `find_hot`
| Parameter | Standard | Bedeutung |
|-----------|----------|-----------|
| `cold_sigma` | 3 | Kalt-Pixel Threshold (σ unter Median) |
| `hot_sigma` | 3 | Hot-Pixel Threshold (σ über Median) |

### Bad Pixel Map (BPM) Format
```
P x y [C|H]    # Einzelnes Pixel (C=cold, H=hot)
C x 0          # Ganze Spalte x
L y 0          # Ganze Zeile y
```

---

## 17.7 Banding Removal

**Befehl:** `fixbanding amount sigma [-vertical]`

### Zweck
Entfernung horizontale/vertikale Streifen (Sensor Readout, Elektronik).

### Parameter
| Parameter | Bereich | Empfehlung |
|-----------|---------|------------|
| `amount` | 0–4 | 1–2 (Korrekturstärke) |
| `sigma` | 0–5 | 1–2 (Highlight-Schutz, höher = mehr Schutz) |
| `-vertical` | Flag | Vertikales statt horizontales Banding |

### Wann anwenden
Nach Kalibrierung, vor Registrierung — nur wenn Banding sichtbar ist.

---

## 17.8 X-Trans Fix (Fuji Kameras)

**Befehl:** `fix_xtrans`

### Zweck
Entfernt das quadratische Muster von Phasen-AF-Pixeln in Dark/Bias-Frames bei Fuji X-Trans Sensoren.

### Anwendung
```
Master Dark erstellen
↓
fix_xtrans (auf Master Dark anwenden)
↓
Kalibrierung mit korrigiertem Master Dark
```

---

## 17.9 ICC Profile / Color Management

**Befehle:** `icc_assign`, `icc_convert_to`, `icc_remove`

### Zweck
Farbprofil-Management für korrekte Farbwiedergabe.

| Befehl | Nutzung |
|--------|---------|
| `icc_assign sRGB` / `Rec2020` / `linear` / `working` / Pfad | Profil zuweisen (keine Konvertierung) |
| `icc_convert_to sRGB [perceptual\|relative\|saturation\|absolute]` | In Profil konvertieren (Rendering Intent) |
| `icc_remove` | Profil entfernen |

### Empfehlung
- Lineare Daten: `icc_assign linear` (oder gar keins)
- Finaler Export für Web/sRGB: `icc_convert_to sRGB perceptual`
- Für Druck: `icc_convert_to /pfad/zum/profil.icc relative`

---

## 17.10 Statistik & QC (Quality Control)

**Befehle:** `entropy`, `histo`, `bg`, `bgnoise`, `findstar -out`, `psf`

### Schnelle Bild-Beurteilung
| Befehl | Was es zeigt | Gut für |
|--------|--------------|---------|
| `bg` | Hintergrund-Median | Belichtungskonsistenz |
| `bgnoise` | Hintergrund-Rauschen (MAD) | Rauschvergleich |
| `entropy` | Entropie (Informationsgehalt) | Detail-Reichtum, Fokus-Qualität |
| `histo 0/1/2` | Histogramm pro Kanal | Schwarzen/Weißen Punkt setzen |
| `findstar -out stats.csv` | Stern-Liste mit FWHM, Rundheit, SNR | Frame-Qualität, Culling |
| `psf` | PSF-Parameter der erkannten Sterne | Seeing, Tracking-Qualität |

### Frame-Culling Workflow
```
findstar -out all_frames.csv (pro Frame)
→ CSV analysieren: FWHM, Sternzahl, Background
→ Schlechte Frames markieren (ausschließen)
→ Stack nur mit guten Frames
```

---

# Wichtigste Siril-Regeln

1. FITS niemals unnötig verändern.

2. Kalibrierung vor Registrierung.

3. Registrierung vor Stack.

4. PCC vor aggressiver Farbkorrektur.

5. Entrauschen erst am Ende.

6. Das lineare Bild sieht immer schlechter aus als das fertige Bild.

7. **Plate Solving vor PCC** (für Gaia-Katalog-Matching).

8. **Deconvolution/Wavelets nur auf linearen Daten** (vor Stretch).

9. **Cosmetic Correction nach Kalibrierung** (auf kalibrierten Daten).

10. **ICC Profile erst am Ende** (für Export/Web/Druck).
```
