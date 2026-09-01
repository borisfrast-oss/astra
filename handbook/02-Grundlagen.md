# 02 – Grundlagen

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Übersicht

Dieses Kapitel erklärt die technischen Grundlagen, die notwendig sind, um die Siril-Workflows zu verstehen.

Behandelte Themen:

- FITS-Dateien
- RAW-Daten
- Bayer-Matrix
- Debayering
- Sequenzen
- Kalibrierung
- Registrierung
- Normalisierung
- Stacking
- lineare und nichtlineare Daten
- Histogramm
- Farbräume

---

# 1. FITS-Dateien

## Was ist FITS?

FITS bedeutet:

**Flexible Image Transport System**

Es ist das Standardformat der professionellen Astronomie.

Eine FITS-Datei enthält:

- Bildpixel
- Metadaten
- Aufnahmeeinstellungen
- Kamerainformationen

---

## Unterschied zu JPEG oder PNG

| Format | Eigenschaft |
|---|---|
| JPEG | komprimiert, verlustbehaftet |
| PNG | verlustfrei, aber für fertige Bilder |
| TIFF | Bildbearbeitung |
| FITS | astronomische Rohdaten |

---

## Warum FITS?

Astrofotografie benötigt:

- hohe Dynamik
- lineare Daten
- unveränderte Sensordaten

Ein JPEG wäre bereits:

- automatisch aufgehellt
- farbkorrigiert
- komprimiert

Damit gingen wichtige Informationen verloren.

---

# 2. Bilddaten in FITS

Ein FITS-Bild besteht aus Pixelwerten.

Beispiel:

```

Pixelwert 100

Pixelwert 250

Pixelwert 5000

```

Diese Werte sind nicht direkt Helligkeitswerte wie bei einem normalen Bild.

Sie repräsentieren:

- gemessene Elektronen
- Lichtintensität
- Sensorantwort

---

# 3. Linearer Workflow

Astrofotografie beginnt immer linear.

Das bedeutet:

Die Pixelwerte wurden noch nicht verändert.

Beispiel:

```

Original:

10
20
30
40
50

```

Nach Stretch:

```

10
40
120
220
255

```

Die Unterschiede wurden verstärkt.

---

# 4. Bayer-Matrix

Der Dwarf 3 verwendet einen Farbsensor.

Ein Sensorpixel misst jedoch nur eine Farbe.

Die Kamera verwendet deshalb eine Bayer-Matrix.

Typisches Muster:

```

G R

B G

```

Dabei gibt es:

- doppelt so viele grüne Pixel
- halb so viele rote Pixel
- halb so viele blaue Pixel

Warum Grün?

Das menschliche Auge ist besonders empfindlich für Grün.

---

# 5. Debayering

Debayering bedeutet:

Aus einzelnen Farbpixeln wird ein Farbbild erzeugt.

Vorher:

```

R G R G

G B G B

R G R G

```

Nachher:

```

RGB Pixel
RGB Pixel
RGB Pixel

```

---

## Wichtig

Debayering sollte nur einmal erfolgen.

Falsches mehrfaches Debayering kann verursachen:

- Farbstiche
- Artefakte
- Detailverlust

---

# 6. Sequenzen in Siril

Eine Sequenz ist eine Sammlung zusammengehöriger Bilder.

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

## Warum Sequenzen?

Siril arbeitet nicht direkt mit einzelnen Dateien.

Die Sequenz ermöglicht:

- Registrierung
- Kalibrierung
- Bewertung
- Stack

---

# 7. Ordnerstruktur

Empfohlene Struktur:

```

M31/

├── lights/

│   ├── m31_light_00001.fits
│   ├── m31_light_00002.fits

├── darks/

│   ├── m31_dark_00001.fits
│   ├── m31_dark_00002.fits

├── siril/

│   └── Sequenzen

```

---

## Wichtig

Sequenzdateien müssen die Bilder finden können.

Wenn FITS-Dateien verschoben werden:

Problem:

```

.seq

↓

zeigt auf alten Pfad

```

Folge:

```

Datei nicht gefunden

```

Typische Fehlermeldung:

```

[Datei-Erweiterung] nicht gefunden

```

---

# 8. Kalibrierung

Kalibrierung entfernt bekannte Fehler.

Sie erfolgt vor dem Stack.

Typischer Ablauf:

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

# 9. Master Dark

Ein einzelnes Dark ist verrauscht.

Deshalb werden mehrere Darks kombiniert.

Beispiel:

```

Dark 1
Dark 2
Dark 3
Dark 4

↓

Master Dark

```

Das Master Dark enthält:

- stabiles Sensormuster
- weniger Zufallsrauschen

---

# 10. Registrierung

Die Kamera bewegt sich während der Aufnahme minimal.

Auch bei Nachführung gibt es:

- kleine Verschiebungen
- Rotation
- optische Unterschiede

Registrierung richtet die Sterne aus.

Beispiel:

Vorher:

```

Bild 1:

```
*
```

Bild 2:

```
   *
```

```

Nachher:

```

```
*
*
```

```

---

# 11. Siril Registrierung

Für Deep Sky:

Empfehlung:

```

Allgemein:
Deep Sky

```

Geeignet für:

- Galaxien
- Nebel
- Sternfelder

---

# 12. Transformationen

Registrierung kann verschiedene mathematische Modelle verwenden.

## Translation

Nur Verschiebung.

Geeignet:

- sehr stabile Systeme

---

## Affin

Kann:

- Verschiebung
- Rotation
- Skalierung

ausgleichen.

---

## Homographie

Kann zusätzlich:

- perspektivische Verzerrungen

korrigieren.

Für Deep Sky meistens Standardwahl.

---

# 13. Normalisierung

Normalisierung gleicht Helligkeitsunterschiede zwischen Bildern aus.

Warum?

Einzelbilder können unterschiedlich sein durch:

- leichte Transparenzänderungen
- Hintergrundänderungen
- Sensoränderungen

---

# 14. Stacking

Beim Stack werden mehrere Bilder kombiniert.

Ziele:

- Rauschen reduzieren
- Signal erhöhen
- Ausreißer entfernen

---

# 15. Stackmethoden

## Durchschnitt

Mathematisch:

```

Summe aller Pixel

geteilt durch

Anzahl Bilder

```

Vorteil:

- maximale Signalqualität

Nachteil:

- Ausreißer bleiben

---

## Median

Der mittlere Wert wird verwendet.

Beispiel:

```

5
6
7
100

```

Median:

```

6,5

```

Der Ausreißer 100 wird ignoriert.

---

## Winsor Sigma

Eine Kombination aus:

- statistischer Analyse
- Ausreißerentfernung
- Mittelwertbildung

Sehr geeignet für Deep Sky.

Entfernt:

- Satelliten
- Flugzeuge
- zufällige Fehler

---

# 16. Histogramm

Das Histogramm zeigt die Helligkeitsverteilung.

Links:

```

schwarz

```

Mitte:

```

mittlere Helligkeit

```

Rechts:

```

helle Bereiche

```

---

## Lineares Astrobild

Typisch:

```

████
█
█

```

Fast alles links.

Das ist normal.

---

# 17. Stretching

Stretching verschiebt die Darstellung.

Es macht:

- schwache Nebel sichtbar
- Galaxienarme sichtbar
- Farben sichtbar

Aber:

Zu starkes Stretching erzeugt:

- Rauschen
- harte Übergänge
- ausgebrannte Sterne

---

# 18. Farbkalibrierung

Eine Kamera sieht Farben nicht exakt wie das Auge.

PCC korrigiert:

- Farbverschiebungen
- Sensorcharakteristik
- atmosphärische Effekte

---

# 19. Reihenfolge der Verarbeitung

Empfohlene Reihenfolge:

```

Konvertierung

↓

Kalibrierung

↓

Registrierung

↓

Stack

↓

Gradient entfernen

↓

PCC

↓

Stretch

```

Nicht:

```

Stretch

↓

Kalibrierung

```

---

# 20. Wichtigste Erkenntnisse

## Regel 1

Ein gutes Ausgangsmaterial ist wichtiger als starke Bearbeitung.

---

## Regel 2

Lineare Daten niemals unnötig verändern.

---

## Regel 3

Jeder Bearbeitungsschritt sollte einen klaren Zweck haben.

---

## Regel 4

Objektabhängig arbeiten.

Ein Workflow für M31 ist nicht automatisch optimal für Arcturus.
```
