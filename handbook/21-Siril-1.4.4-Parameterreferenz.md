# Kapitel 21 – Siril 1.4.4 Parameterreferenz

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel dient als technische Referenz für Siril 1.4.4.

Es beschreibt:

- wichtige Menüs
- Parameter
- Standardwerte
- empfohlene Werte für Dwarf 3
- wann Änderungen sinnvoll sind

Grundregel:

**Die Siril-Defaults sind meistens korrekt. Änderungen nur durchführen, wenn ein konkretes Problem besteht.**

---

# 1. Allgemeiner Siril Workflow

Standard Deep-Sky Ablauf:

```

Dateien importieren

↓

Sequenz erstellen

↓

Kalibrieren

↓

Registrieren

↓

Stacken

↓

Nachbearbeitung

↓

Export

```

---

# 2. Sequenz erstellen

Menü:

```

Datei
→ Sequenz erstellen

```

---

# 2.1 Bildtyp

Für Dwarf 3:

```

FITS

```

---

# 2.2 Debayer

Der Dwarf 3 verwendet eine Farbkamera.

Daher:

```

aktiviert

```

---

# 2.3 CFA Pattern

Abhängig vom Sensor.

Nicht manuell ändern, wenn:

- Dwarf FITS korrekt erkannt wird

---

Problem bei falschem CFA:

- falsche Farben
- grünes Bild
- Farbverschiebungen

---

# 2.4 Sequenznamen

Empfehlung:

```

m31_light
m42_light
m45_light

```

---

# 3. Umwandlung (Preprocessing)

Menü:

```

Umwandlung

```

---

# 3.1 Debayer

Empfehlung:

```

aktiviert

```

---

# 3.2 Interpolation

Standard:

```

Bilinear

```

---

Alternative:

```

VNG

```

möglich bei:

- feineren Farbdetails

---

# 3.3 Farbkorrektur

Normalerweise:

```

deaktiviert

```

---

Farbkorrektur später durchführen:

- PCC
- Photometrische Kalibrierung

---

# 4. Kalibrierung

Menü:

```

Kalibrierung

```

---

# 4.1 Dark

Empfohlen:

```

aktiviert

```

---

Methode Master Dark:

```

Median

```

---

Warum:

- Hotpixel entfernen
- robust gegen Ausreißer

---

# 4.2 Flat

Empfohlen:

```

aktiviert

```

bei:

- Galaxien
- Nebeln
- starkem Stretch

---

Master Flat:

```

Median

```

---

# 4.3 Bias

Dwarf 3:

```

optional

```

---

Nicht zwingend notwendig.

---

# 4.4 Cosmetic Correction

Entfernt:

- verbleibende Hotpixel

Empfehlung:

```

aktivieren bei Problemen

```

---

# 5. Registrierung

Menü:

```

Registrierung

```

---

# 5.1 Methode Deep Sky

Standard für:

- Nebel
- Galaxien
- Sternhaufen

---

Auswahl:

```

Allgemein (Deep Sky)

```

---

# 5.2 Transformation

Empfehlung:

```

Homographie

```

---

Warum:

Korrigiert:

- Rotation
- leichte Verzerrung
- Skalierung

---

# 5.3 Sternpaare

Standard:

```

10

```

---

Empfehlung Dwarf:

```

10

```

---

Bei Problemen:

```

5

```

---

# 5.4 Maximale Sterne

Standard:

```

100

```

---

Empfehlung:

Deep Sky:

```

300–500

```

---

Viele Sterne:

```

200

```

---

# 5.5 Luminanz verwenden

Empfehlung:

```

aktiviert

```

---

Verbessert:

- Sternenerkennung
- Registrierung

---

# 5.6 Entzerrung

Empfehlung:

```

deaktiviert

```

---

Nur notwendig bei:

- großen Bildfeldern
- starken Verzerrungen

---

# 6. Stack

Menü:

```

Stacking

```

---

# 6.1 Kombination

## Durchschnitt

Standard:

```

Average

```

Geeignet:

- saubere Daten
- wenig Ausreißer

---

## Median

Geeignet:

- wenige Bilder
- starke Ausreißer

---

## Winsor Sigma Clipping

Empfehlung Dwarf:

```

Winsor Sigma

```

Geeignet für:

- Deep Sky
- viele Frames

Entfernt:

- Satelliten
- Flugzeuge
- zufällige Fehler

---

# 6.2 Normalisierung

Empfehlung:

```

Additive + Skalierung

```

---

Warum:

Korrigiert:

- unterschiedliche Helligkeit
- Hintergrundschwankungen

---

# 6.3 Rejection

Bei Sigma-Verfahren:

Standard:

```

aktiv

```

---

Typische Werte:

```

2–3 Sigma

```

---

Nicht zu aggressiv:

sonst gehen schwache Details verloren.

---

# 7. Hintergrundextraktion (Background Extraction)

Menü:

```

Hintergrundextraktion

```

---

Ziel:

Entfernen von:

- Lichtverschmutzung
- Gradienten

---

Nicht entfernen:

- echte Nebelstrukturen

---

# 7.1 Modell

Empfehlung:

```

Polynom Grad 1 oder 2

```

---

Grad 1:

leichte Gradienten

---

Grad 2:

stärkere Lichtverschmutzung

---

Höhere Grade:

meist vermeiden.

---

# 7.2 Kontrollpunkte

Regel:

Nicht setzen auf:

- Sterne
- Nebel
- Galaxien

---

Nur:

freien Hintergrund

---

# 8. Photometric Color Calibration (PCC)

Menü:

```

Farbkalibrierung
→ Photometrisch

```

---

Voraussetzungen:

- Sterne vorhanden
- Internetverbindung für Sternkatalog

---

Empfehlung:

Nach:

```

Stack

↓

Background Extraction

```

---

PCC korrigiert:

- Farbbalance
- Sternfarben

---

# 9. Green Noise Removal

Menü:

```

Grünrauschen entfernen

```

---

Bei Dwarf OSC:

oft sinnvoll.

---

Empfehlung:

Nach PCC.

---

Nicht aggressiv verwenden.

---

# 10. Histogramm / Stretch

Menü:

```

Histogramm

```

---

Ziel:

Signal sichtbar machen.

---

Parameter:

## Schwarzwert

Vorsichtig.

Zu hoch:

- schwache Details verschwinden

---

## Mittelwert

Steuert:

- Helligkeit
- Kontrast

---

## Weißpunkt

Nicht Sterne ausbrennen.

---

# 11. Asinh Stretch

Sehr empfehlenswert für Deep Sky.

Vorteile:

- erhält Sterne
- erhält Farben
- gute Nebelstrukturen

---

Geeignet für:

- Galaxien
- Nebel
- Sternhaufen

---

# 12. Export

Empfehlung:

Für GIMP:

```

TIFF 16 Bit

```

---

Nicht:

JPEG.

---

Warum:

JPEG zerstört:

- Farbtiefe
- schwache Details

---

# 13. Empfohlene Dwarf-Standardparameter

```

Debayer:
aktiv

Dark:
Median

Flat:
Median

Registrierung:
Deep Sky

Transformation:
Homographie

Sternpaare:
10

Max Sterne:
500

Stack:
Winsor Sigma

Normalisierung:
Additiv + Skalierung

Background:
Polynom 1–2

PCC:
aktiv

Export:
TIFF 16 Bit

```

---

# 14. Was nicht ändern?

Diese Parameter bleiben normalerweise Default:

- Alignment-Feinparameter
- Kosmetikparameter
- interne Qualitätsparameter
- Dateiformateinstellungen

---

