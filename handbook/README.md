# Dwarf 3 + Siril 1.4.4
# Best Practices Handbuch für Astrofotografie

**Version:** 1.0  
**Stand:** 2026  

**Workflow:**

- DwarfLab Dwarf 3 mini
- Siril 1.4.4
- GraXpert
- GIMP 3.x

---

# Zweck dieses Handbuchs

Dieses Handbuch beschreibt einen praxisorientierten Workflow zur Verarbeitung von Astrofotografie-Aufnahmen mit dem Dwarf 3 mini Smart Telescope.

Der Schwerpunkt liegt auf:

- Deep-Sky-Astrofotografie
- FITS-Verarbeitung
- Siril 1.4.4
- reproduzierbaren Workflows
- objektabhängiger Bildbearbeitung
- sinnvollen Standardparametern

Das Ziel ist nicht nur:

> "Klicke hier und dort"

sondern:

> Verstehen, warum ein Verarbeitungsschritt gemacht wird und wann er sinnvoll ist.

---

# Grundprinzip der Astrofotografie

Astrofotografie unterscheidet sich grundlegend von normaler Fotografie.

Ein Rohbild enthält:

- Nutzsignal des Himmelsobjekts
- Hintergrundlicht
- Sensorausleserauschen
- Dunkelstrom
- Hotpixel
- zufällige Störungen

Die Bildverarbeitung verfolgt vier Hauptziele:

1. Fehler entfernen
2. Signal erhalten
3. Rauschen reduzieren
4. Farben korrekt darstellen

---

# Standardworkflow

```text
Dwarf 3 Aufnahme

        ↓

FITS Lights

        ↓

Darks aufnehmen

        ↓

Siril:
Sequenzen erstellen

        ↓

Master Dark erstellen

        ↓

Lights kalibrieren

        ↓

Registrierung

        ↓

Stacking

        ↓

Lineares Masterbild

        ↓

Background Extraction

        ↓

Photometrische Farbkalibrierung

        ↓

Stretching

        ↓

GraXpert (optional)

        ↓

GIMP:
Finalisierung
````

---

# Grundregel

## Mehr Signal ist wichtiger als mehr Bearbeitung

Die wichtigste Verbesserung eines Astrobildes entsteht meistens durch:

* längere Gesamtbelichtungszeit
* mehr Einzelbilder
* bessere Aufnahmebedingungen

Beispiel:

```text
16 × 180 Sekunden

= 48 Minuten Integrationszeit
```

ist ein brauchbarer Anfang.

Mehr Daten:

```text
60 × 180 Sekunden

= 3 Stunden Integrationszeit
```

führen normalerweise zu:

* weniger Rauschen
* schwächeren sichtbaren Details
* besserem Hintergrund
* höherer Farbstabilität

---

# Dwarf 3 Standardempfehlungen

## Deep Sky

| Parameter       | Empfehlung                                  |
| --------------- | ------------------------------------------- |
| Belichtungszeit | abhängig vom Objekt, häufig 60–180 Sekunden |
| Gain            | abhängig vom Objekt und Aufnahmeziel        |
| Lights          | möglichst viele Einzelbilder                |
| Darks           | 10–20 oder mehr                             |
| Flats           | optional bei Bedarf                         |
| Bias            | meistens nicht erforderlich                 |

Die optimalen Werte hängen ab von:

* Objekt
* Himmelshintergrund
* Mondphase
* Filter
* gewünschtem Ergebnis

---

# Objektklassen

Nicht jedes Objekt wird gleich verarbeitet.

| Objekt              | Beispiele       | Besonderheit            |
| ------------------- | --------------- | ----------------------- |
| Galaxien            | M31, M33, M51   | schwaches Signal        |
| Emissionsnebel      | M42, NGC7000    | Gasstrukturen           |
| Reflexionsnebel     | M78             | feine Kontraste         |
| Planetarische Nebel | M57             | kleine helle Objekte    |
| Kugelsternhaufen    | M13             | viele Sterne            |
| Offene Sternhaufen  | M45             | Sternfarben             |
| Sternfelder         | Milchstraße     | natürliche Sternwirkung |
| Einzelsterne        | helle Sterne    | Farbtreue               |
| Mond                | Oberfläche      | kurze Belichtung        |
| Sonne               | Oberfläche      | Spezialfilter notwendig |
| Planeten            | Jupiter, Saturn | kurze Einzelbilder      |
| Kometen             | bewegte Objekte | spezielle Verarbeitung  |

---

# Kalibrierframes

## Darks

Darks enthalten keine Lichtinformation.

Sie messen:

* Hotpixel
* Dunkelstrom
* Sensormuster

Lights und Darks sollten möglichst identisch aufgenommen werden.

| Parameter       | möglichst gleich  |
| --------------- | ----------------- |
| Kamera          | ja                |
| Belichtungszeit | ja                |
| Gain            | ja                |
| Temperatur      | möglichst ähnlich |

---

## Flats

Flats korrigieren:

* Vignettierung
* Staubflecken
* ungleichmäßige Ausleuchtung

Flats müssen zum verwendeten Setup passen.

---

## Bias

Bias beschreibt das elektronische Grundsignal des Sensors.

Beim Dwarf-3-Workflow ist die Verwendung häufig nicht notwendig, da Darks bereits einen großen Teil der Korrektur übernehmen.

---

# Farbworkflow

Der Dwarf 3 besitzt einen Farbsensor mit Bayer-Matrix.

Nach dem Stack kann ein Bild grün erscheinen.

Das ist normal.

Empfohlene Reihenfolge:

```text
Stack

↓

Background Extraction

↓

Photometric Color Calibration

↓

Green Noise Reduction (optional)

↓

Stretch
```

Nicht:

```text
Green Noise Reduction

↓

Color Calibration
```

Grund:

Die Farbkalibrierung sollte auf der ursprünglichen Farbverteilung basieren.

---

# Stacking

## Durchschnitt

Vorteile:

* maximale Signalnutzung

Nachteile:

* Ausreißer bleiben erhalten

---

## Median

Vorteile:

* entfernt Ausreißer

Nachteile:

* etwas weniger Signal

---

## Winsor Sigma Clipping

Empfohlen für viele Deep-Sky-Aufnahmen.

Entfernt:

* Satellitenspuren
* Flugzeuge
* einzelne Ausreißer

---

# Softwareaufteilung

## Siril

Verantwortlich für:

* FITS-Verarbeitung
* Sequenzen
* Kalibrierung
* Registrierung
* Stack
* Farbkalibrierung
* lineares Processing
* Stretching

---

## GraXpert

Verantwortlich für:

* Hintergrundgradienten
* Lichtverschmutzungskorrektur
* optionales Entrauschen

---

## GIMP

Verantwortlich für:

* finale Bildbearbeitung
* Kontrast
* lokale Anpassungen
* Präsentation
* Export

---

# Handbuchstruktur

Die Kapitel sind in fünf Bereiche gegliedert.

---

## 1. Grundlagen

```text
README.md

01-Einleitung.md
02-Grundlagen.md
03-Dwarf3-Best-Practices.md
04-Siril-Referenz.md
```

---

## 2. Objektbezogene Verarbeitung

```text
05-Galaxien.md
06-Emissionsnebel.md
07-Reflexionsnebel.md
08-Planetarische-Nebel.md
09-Kugelsternhaufen.md
10-Offene-Sternhaufen.md
11-Sterne-und-Sternfelder.md
12-Mond-und-Planeten.md
13-Milchstrasse-und-Weitfeld.md
14-Kometen.md
15-Sternentstehungsgebiete-und-Komplexe-Nebel.md
16-Dunkelnebel.md
```

---

## 3. Bildverarbeitung

```text
17-Mehrfachbelichtungen-und-HDR.md
18-Mosaike-und-Panoramen.md
19-Farbkalibrierung-und-Endbearbeitung.md
```

---

## 4. Praxis und Werkzeuge

```text
20-Dwarf3-Aufnahmeempfehlungen.md
21-Siril-1.4.4-Parameterreferenz.md
22-Siril-Workflow-Entscheidungsbaum.md
23-Siril-Fehlerbehebung.md
24-Dwarf3-Master-Rezepte.md
25-GIMP-Astrofotografie-Workflow.md
26-GraXpert-Workflow.md
27-Astrofotografie-Datenmanagement.md
28-Fortgeschrittene-Techniken.md
```

---

## 5. Referenz und Nachschlagewerk

```text
29-Siril-Schnellcheckliste.md
30-Dwarf3-Aufnahmeliste-vor-der-Nacht.md
31-Objekt-Auswahl-nach-Jahreszeit.md
32-Astrofotografie-Glossar.md
33-Finale-Dwarf3-Siril-Referenzparameter.md
34-Siril-1.4.4-Menue-Navigation.md
35-Fehlerdiagnose-Astrofotografie.md
36-Dwarf3-End-to-End-Workflow.md
37-Siril-Command-Quick-Reference.md
```

---

# Versionshistorie

## Version 1.0

Erste strukturierte Version.

Basis:

* Dwarf 3 mini
* Siril 1.4.4
* GraXpert
* GIMP

---

# Ziel des Handbuchs

Ein reproduzierbarer Workflow:

```text
Aufnehmen

↓

Verstehen

↓

Verarbeiten

↓

Verbessern

↓

Archivieren
```

Astrofotografie wird dadurch nicht nur ein Trial-and-Error-Prozess, sondern ein nachvollziehbarer Arbeitsablauf.
