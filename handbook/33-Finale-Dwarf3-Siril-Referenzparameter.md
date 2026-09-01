# Kapitel 33 – Finale Dwarf 3 + Siril 1.4.4 Referenzparameter

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel ist die zentrale Referenz für die empfohlenen Standardwerte.

Es enthält:

- Dwarf 3 Aufnahmeparameter
- Siril 1.4.4 Verarbeitung
- GraXpert Einstellungen
- GIMP Übergabe
- Objektabhängige Anpassungen

Wenn keine speziellen Anforderungen bestehen, kann dieser Workflow als Standard verwendet werden.

---

# 1. Dwarf 3 Standardaufnahme

## Deep Sky Standard

Geeignet für:

- Galaxien
- Nebel
- Sternhaufen

---

Empfohlene Werte:

```

Belichtungszeit:
180 Sekunden

Gain:
35

Filter:
kein Filter

Lights:
200+

Darks:
20+

Flats:
wenn möglich

```

---

# 2. Emissionsnebel Standard

Geeignet für:

- M42
- IC1805
- IC1848
- Rosettennebel
- Schleiernebel

---

Einstellungen:

```

Belichtung:
180 Sekunden

Gain:
40

Filter:
Dualband

Lights:
200–500

```

---

# 3. Galaxien Standard

Geeignet für:

- M31
- M33
- M51
- M101

---

Einstellungen:

```

Belichtung:
180 Sekunden

Gain:
30–35

Filter:
kein Filter

Lights:
200+

```

---

# 4. Sternhaufen Standard

Geeignet für:

- M13
- M3
- M5

---

Einstellungen:

```

Belichtung:
30–90 Sekunden

Gain:
10–30

Filter:
kein Filter

Lights:
100+

```

---

# 5. Siril 1.4.4 Workflow Referenz

---

# 5.1 Sequenz erstellen

Menü:

```

Datei

↓

Sequenz erstellen

```

---

Parameter:

```

Dateityp:
FITS

Debayer:
aktiv

CFA:
automatisch

Speicher:
16 Bit

```

---

# 5.2 Kalibrierung

## Dark

Empfehlung:

```

Master Dark:
ja

```

Erstellung:

```

Stack:
Median

```

---

## Flat

Empfehlung:

```

Master Flat:
wenn vorhanden

```

Stack:

```

Median

```

---

## Bias

Bei Dwarf 3:

```

optional

```

---

# 5.3 Registrierung

Menü:

```

Registrierung

↓

Deep Sky

```

---

Standardwerte:

```

Methode:
Global Star Alignment

Transformation:
Homographie

Sternsuche:
automatisch

Max Sterne:
500

Minimal Sterne:
10

```

---

Optionen:

```

Luminanz verwenden:
aktiv

Drizzle:
aus

```

---

# 5.4 Stack

Empfehlung:

```

Winsorized Sigma Clipping

```

---

Parameter:

```

Normalisierung:
Additive + Skalierung

Gewichtung:
Signalgewichtung

Rejection:
aktiv

```

---

Alternative:

Bei wenigen Bildern:

```

Median

```

---

# 5.5 Hintergrundkorrektur

Siril:

```

Bearbeitung

↓

Background Extraction

```

---

Empfehlung:

```

Grad:
1–2

Samples:
nur echter Hintergrund

```

---

Nicht verwenden auf:

- Nebel
- Galaxien
- helle Strukturen

---

# 5.6 Farbkalibrierung

Empfehlung:

```

Photometric Color Calibration

```

---

Vorbedingungen:

- Sterne sichtbar
- korrekte Objektposition
- Internetzugang für Sternkatalog

---

Danach:

```

Green Noise Removal

```

---

# 5.7 Stretch

Empfohlene Reihenfolge:

```

Asinh Stretch

↓

Histogram Transformation

↓

Curves

```

---

Grundregel:

Nicht maximal aufhellen.

---

# 6. GraXpert Standardparameter

---

# Hintergrundkorrektur

Empfehlung:

```

Modell:
Degree 1–2

Stärke:
moderat

```

---

Punkte:

Nur:

```

dunkler Hintergrund

```

---

Nicht:

```

Objektstrukturen

```

---

# Denoise

Standard:

```

aus

```

oder:

```

minimal

```

---

Grund:

Signal erhalten.

---

# 7. GIMP Standardworkflow

---

# Ebenen

Empfehlung:

```

Original

↓

Farbkorrektur

↓

Kontrast

↓

Lokale Anpassungen

↓

Export

```

---

# Werte

## Sättigung

Typisch:

```

+10 bis +30

```

---

## Schärfung

Unscharf maskieren:

```

Radius:
1–3 Pixel

Stärke:
gering

```

---

## Kontrast

Moderate Anpassung.

---

# 8. Objektabhängige Änderungen

---

# M31

Zusätzlich:

```

Kern schützen

Stretch langsam

HDR optional

```

---

# M42

Zusätzlich:

```

Kurzbelichtung aufnehmen

HDR kombinieren

```

---

# M45

Zusätzlich:

```

GraXpert sehr vorsichtig

kein aggressiver Hintergrundabzug

```

---

# Cirrusnebel

Zusätzlich:

```

sehr viele Lights

sanfter Stretch

```

---

# Galaxien

Zusätzlich:

```

Sterne erhalten

Staubbänder hervorheben

```

---

# 9. Qualitätskontrolle

Vor Export prüfen:

---

## Sterne

Gut:

```

klein

rund

farbig

```

---

Schlecht:

```

weiße Punkte

ausgebrannt

zu groß

```

---

## Hintergrund

Gut:

```

dunkel

aber nicht schwarz

```

---

## Farben

Gut:

```

natürlich

Objektabhängig

```

---

# 10. Empfohlener kompletter Workflow

```

Dwarf 3 Aufnahme

↓

Lights sichern

↓

Darks erstellen

↓

Siril Sequenz

↓

Kalibrierung

↓

Registrierung

↓

Winsor Sigma Stack

↓

Background Extraction

↓

PCC

↓

Green Noise Removal

↓

Asinh Stretch

↓

GraXpert

↓

GIMP

↓

TIFF/XCF Export

↓

Archivierung

```

---

# 11. Minimalworkflow für schnelle Ergebnisse

Wenn wenig Zeit vorhanden ist:

```

Sequenz

↓

Kalibrieren

↓

Registrieren

↓

Stack

↓

PCC

↓

Stretch

↓

Export

```

---

# 12. Meine persönlichen Dwarf-3 Referenzwerte

Standard:

```

180 Sekunden

Gain 35

200 Lights

20 Darks

kein Filter

Winsor Sigma

PCC

Asinh Stretch

TIFF 16 Bit

```

---

Emissionsnebel:

```

180 Sekunden

Gain 40

Dualband

300 Lights

```

---

Sternhaufen:

```

60 Sekunden

Gain 20

100 Lights

```

---

# 13. Goldene Regeln

1. Mehr Lights schlagen aggressives Processing.

2. Gute Kalibrierung verbessert jedes Bild.

3. PCC zuerst, kreative Farben später.

4. Hintergrund nie komplett entfernen.

5. Sterne sind Teil des Bildes.

6. Natürlichkeit ist wichtiger als maximale Sichtbarkeit.

7. Originaldaten immer behalten.


