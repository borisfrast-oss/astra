# Kapitel 29 – Siril Schnellcheckliste

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel ist die praktische Kurzreferenz für eine normale Deep-Sky-Verarbeitung.

Wenn die Details aus den vorherigen Kapiteln nicht benötigt werden:

Diese Checkliste reicht für 90 % aller Dwarf-3-Aufnahmen.

---

# 1. Vor der Verarbeitung prüfen

## Ordner

```

Objekt/

├── lights/
├── darks/
├── flats/
└── output/

```

---

## Aufnahmequalität

Prüfen:

- Sterne rund?
- Fokus korrekt?
- keine Wolken?
- genug Lights?
- korrekter Filter?

---

# 2. Standard Deep-Sky Workflow

## Schritt 1 – Sequenz erstellen

Siril:

```

Datei

↓

Sequenz erstellen

```

Parameter:

```

Format:
FITS

Debayer:
aktiv

CFA:
automatisch

```

---

# Schritt 2 – Kalibrierung

Verwenden:

```

Dark:
ja

Flat:
wenn vorhanden

Bias:
optional

```

---

Master:

```

Median

```

---

# Schritt 3 – Registrierung

Menü:

```

Registrierung

↓

Allgemein Deep Sky

```

Parameter:

```

Transformation:
Homographie

Sternpaare:
10

Max Sterne:
500

Luminanz:
aktiv

Entzerrung:
aus

```

---

# Schritt 4 – Stack

Empfehlung:

```

Winsor Sigma Clipping

```

---

Parameter:

```

Normalisierung:

Additiv + Skalierung

```

---

Ergebnis:

```

gestacktes FITS

```

---

# Schritt 5 – Hintergrund korrigieren

Option A:

Siril:

```

Background Extraction

```

oder

Option B:

GraXpert.

---

Empfehlung:

Nicht beide aggressiv verwenden.

---

# Schritt 6 – Farbe

Siril:

```

Photometric Color Calibration

```

danach:

```

Green Noise Removal

```

---

# Schritt 7 – Stretch

Empfehlung:

Reihenfolge:

```

Asinh Stretch

↓

Histogramm

↓

Kurven

```

---

Ziel:

- Nebel sichtbar
- Hintergrund erhalten
- Sterne nicht ausbrennen

---

# Schritt 8 – Export

Für GIMP:

```

TIFF 16 Bit

```

---

# 3. Objektabhängige Anpassungen

---

# Galaxie

Beispiele:

- M31
- M33

Zusätzlich:

```

vorsichtig stretchen

Kern schützen

```

---

# Emissionsnebel

Beispiele:

- M42
- Herznebel

Zusätzlich:

```

Dualband möglich

Farben erhalten

```

---

# Reflexionsnebel

Beispiele:

- M45

Zusätzlich:

```

kein Filter

GraXpert sehr vorsichtig

```

---

# Sternhaufen

Beispiele:

- M13

Zusätzlich:

```

Sterne nicht aufblasen

```

---

# 4. Wenn etwas nicht passt

## Grün

```

PCC

↓

Green Noise Removal

```

---

## Hintergrund zu hell

```

Background Extraction

↓

weniger Stretch

```

---

## Nebel verschwindet

```

GraXpert reduzieren

↓

Schwarzpunkt prüfen

```

---

## Sterne zu groß

```

weniger Stretch

↓

kürzere Belichtung

```

---

# 5. Minimalworkflow ohne Extras

Wenn es schnell gehen muss:

```

Sequenz

↓

Dark

↓

Registrierung

↓

Winsor Stack

↓

PCC

↓

Asinh Stretch

↓

TIFF

```

---

# 6. Qualitätskontrolle vor GIMP

Das Siril-Ergebnis sollte:

- korrekt orientiert sein
- natürliche Farben haben
- keinen starken Farbstich besitzen
- sichtbare Details enthalten

---

Nicht in GIMP reparieren:

- falsche Kalibrierung
- falsche Registrierung
- schlechte Rohdaten

---

# 7. Standard Dwarf 3 Parameter

Als Ausgangspunkt:

```

Belichtung:
180 Sekunden

Gain:
35

Filter:
kein Filter

Lights:
200

Darks:
20

Flat:
ja

```

Siril:

```

Debayer:
aktiv

Dark:
Median

Flat:
Median

Registrierung:
Deep Sky

Stack:
Winsor Sigma

Normalisierung:
Additiv + Skalierung

PCC:
ja

Export:
TIFF 16 Bit

```

---

# 8. Die 10 wichtigsten Regeln

1. Gute Rohdaten sind wichtiger als Bearbeitung.

2. Viele Lights reduzieren Rauschen.

3. Darks verbessern die Qualität.

4. Flats müssen korrekt sein.

5. Nicht zu aggressiv stretchen.

6. Hintergrund nicht schwarz machen.

7. PCC vor Farbspielereien.

8. GraXpert vorsichtig einsetzen.

9. Sterne schützen.

10. Immer Originaldaten behalten.

---
