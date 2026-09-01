# Kapitel 32 – Astrofotografie Glossar

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel erklärt die wichtigsten Begriffe der Astrofotografie.

Es dient als Nachschlagewerk für:

- Dwarf 3
- Siril
- GraXpert
- GIMP
- Deep-Sky-Verarbeitung

---

# A

## ADU (Analog Digital Unit)

Messwert eines Kamerasensors.

Er beschreibt:

wie viel Licht der Sensor registriert.

---

Ein Pixelwert in einem FITS-Bild besteht aus ADU-Werten.

Beispiel:

```

0

↓

schwarz

65535

↓

maximaler Wert bei 16 Bit

```

---

Wichtig:

Nicht jedes Pixel sollte maximal hell sein.

---

## Apertur

Durchmesser der Optik.

Beispiel:

```

50 mm Öffnung

```

---

Größere Apertur bedeutet:

- mehr Licht
- schwächere Objekte möglich
- höhere Auflösung

---

## ASINH Stretch

Eine Stretch-Methode in Siril.

Ziel:

schwache Strukturen sichtbar machen.

Vorteil:

gleichzeitig:

- helle Bereiche schützen
- schwache Bereiche verstärken

---

# B

## Bias

Kalibrierbild mit:

- kürzester Belichtungszeit
- geschlossenem Verschluss

---

Verwendung:

Messung des elektronischen Grundsignals.

---

Bei vielen modernen Kameras:

oft weniger wichtig.

---

## Background Extraction (BE)

Hintergrundmodellierung in Siril.

Entfernt:

- Lichtgradienten
- ungleichmäßige Helligkeit

---

Nicht entfernen:

- echte Nebelstrukturen

---

## Bayer-Matrix

Farbfilter auf einem Farbsensor.

Typische Anordnung:

```

RG
GB

```

---

Der Sensor misst zunächst:

- Rot
- Grün
- Blau

nicht direkt ein Farbbild.

---

# C

## Calibration / Kalibrierung

Korrektur der Rohdaten.

Typisch:

```

Light

*

Dark

*

Flat

↓

kalibriertes Bild

```

---

## CFA (Color Filter Array)

Bezeichnung für die Farbfilterstruktur eines Sensors.

Relevant bei:

OSC-Kameras.

---

## Clipping

Verlust von Bildinformation.

---

Weiß-Clipping:

helle Bereiche sind nur noch weiß.

---

Schwarz-Clipping:

dunkle Bereiche sind nur noch schwarz.

---

# D

## Dark Frame

Dunkelbild zur Korrektur von:

- Hotpixel
- Dunkelstrom

---

Aufnahme:

gleiche:

- Belichtungszeit
- Gain
- Temperatur

wie Lights.

---

## Debayer

Umwandlung eines Farb-Rohbildes in RGB.

Aus:

```

Bayer-Muster

```

wird:

```

Farbbild

```

---

Bei Dwarf 3:

normalerweise notwendig.

---

## Deep Sky

Astronomische Objekte außerhalb unseres Sonnensystems.

Beispiele:

- Galaxien
- Nebel
- Sternhaufen

---

# F

## FITS

Standardformat in der Astronomie.

Speichert:

- Bilddaten
- Metadaten
- wissenschaftliche Informationen

---

Vorteile:

- verlustfrei
- hohe Datenqualität

---

## Flat Frame

Kalibrierbild gegen:

- Vignettierung
- Staubflecken
- ungleichmäßige Ausleuchtung

---

Aufnahme:

mit gleichmäßig beleuchteter Fläche.

---

# G

## Gain

Elektronische Verstärkung des Sensors.

---

Höherer Gain:

Vorteile:

- mehr Signalverstärkung

Nachteile:

- weniger Dynamikumfang
- mehr Rauschen

---

## Gradient

Langsame Helligkeitsänderung über das Bild.

Ursachen:

- Stadtlicht
- Mond
- Streulicht

---

# H

## H-alpha

Lichtlinie von ionisiertem Wasserstoff.

Wellenlänge:

```

656 nm

```

---

Wichtig bei:

- Emissionsnebeln

---

## Histogramm

Darstellung der Helligkeitsverteilung.

Zeigt:

- Schwarzpunkt
- Mitteltöne
- Weißpunkt

---

# I

## Integration Time

Gesamte Belichtungszeit.

Berechnung:

```

Anzahl Bilder × Einzelbelichtung

```

---

Beispiel:

```

200 × 180 Sekunden

=

10 Stunden

```

---

Mehr Integration:

meist:

- weniger Rauschen
- mehr Details

---

# L

## Light Frame

Normale Aufnahme des Objekts.

---

Die wichtigste Bildart.

---

## Linear Image

Bild ohne Stretch.

---

Charakter:

- dunkel
- wenig sichtbar

enthält aber:

maximale Information.

---

# M

## Master Dark

Durch Stacken vieler Darks erzeugtes Referenzbild.

---

Vorteil:

weniger Rauschen.

---

## Master Flat

Durch Stacken vieler Flats erzeugtes Referenzbild.

---

## Median Stack

Kombiniert Bilder über Medianwert.

Entfernt:

- zufällige Störungen
- Satelliten teilweise

---

# N

## Nebula / Nebel

Wolken aus Gas und Staub.

Typen:

---

Emissionsnebel:

leuchten selbst.

Beispiel:

M42.

---

Reflexionsnebel:

reflektieren Sternlicht.

Beispiel:

M45.

---

Dunkelnebel:

blockieren Licht.

---

# O

## OSC (One Shot Color)

Farbsensor.

Ein Bild enthält:

Rot, Grün und Blau Informationen.

---

Dwarf 3 verwendet einen OSC-Sensor.

---

## OIII

Ionisiertes Sauerstoffsignal.

Wellenlänge:

```

500,7 nm

```

---

Wichtig bei:

- planetarischen Nebeln
- Supernovaüberresten

---

# P

## PCC (Photometric Color Calibration)

Automatische Farbkalibrierung.

Verwendet:

- Sternfarben
- Katalogdaten

---

Ziel:

natürliche Farbbalance.

---

## Pixel Peeping

Übermäßiges Betrachten einzelner Pixel.

Problem:

Man optimiert Fehler statt Bildqualität.

---

# R

## Registration

Ausrichten vieler Bilder.

Sterne werden deckungsgleich gemacht.

---

Notwendig vor:

Stacking.

---

## RGB

Farbmodell:

```

Rot

Grün

Blau

```

---

# S

## SNR (Signal-to-Noise Ratio)

Signal-Rausch-Verhältnis.

---

Je höher:

desto besser:

- Details
- Kontrast
- Qualität

---

## Starless

Bild ohne Sterne.

---

Ermöglicht:

separate Bearbeitung von:

- Nebel
- Sternen

---

## Stacking

Kombination vieler Einzelbilder.

---

Vorteile:

- weniger Rauschen
- mehr Details

---

## Stretch

Veränderung der Tonwerte.

Ziel:

lineares Bild sichtbar machen.

---

Ohne Stretch:

Deep-Sky-Bilder wirken schwarz.

---

# T

## TIFF

Hochwertiges Bildformat.

Geeignet für:

- GIMP
- Archiv

---

Empfehlung:

16 Bit.

---

# V

## Vignettierung

Abdunklung zu den Bildecken.

---

Korrektur:

Flat Frames.

---

# W

## Winsor Sigma Clipping

Stacking-Methode.

Entfernt Ausreißer:

- Satelliten
- Flugzeuge
- kosmische Störungen

---

# Z

## Zenit

Punkt direkt über dem Beobachter.

---

Vorteil:

- geringste Atmosphäre
- beste Bildqualität

---

# Häufige Abkürzungen

| Kürzel | Bedeutung |
|---|---|
| ADU | Sensorwert |
| BE | Background Extraction |
| CFA | Farbfiltermatrix |
| DSLR | Digitalkamera |
| FITS | Astronomisches Dateiformat |
| Ha | H-alpha |
| OSC | Farbkamera |
| OIII | Sauerstoffsignal |
| PCC | Photometric Color Calibration |
| RGB | Rot-Grün-Blau |
| SNR | Signal-Rausch-Verhältnis |
| TIFF | Bildformat |
| WBPP | Weighted Batch Preprocessing |

---

# Siril-spezifische Begriffe

| Begriff | Bedeutung |
|---|---|
| Sequenz | Gruppe zusammengehöriger Bilder |
| Registrierung | Ausrichtung der Bilder |
| Stack | Kombination der Bilder |
| Normalisierung | Anpassung der Bildhelligkeiten |
| Debayer | Farbinterpolation |
| Stretch | Sichtbarmachen des Signals |

---

# Wichtigste Begriffe für Dwarf 3

Wenn nur die wichtigsten Begriffe behalten werden:

```

Light

Dark

Flat

Debayer

OSC

Stacking

Registration

PCC

Stretch

SNR

