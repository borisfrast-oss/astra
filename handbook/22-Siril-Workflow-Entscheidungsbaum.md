# Kapitel 22 – Siril Workflow Entscheidungsbaum

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel dient als praktische Entscheidungshilfe:

**Welchen Workflow verwende ich für welches Objekt?**

Nicht jedes Objekt wird gleich verarbeitet.

Die wichtigsten Entscheidungen:

- Filter oder kein Filter?
- kurze oder lange Belichtung?
- welche Kalibrierung?
- welche Registrierung?
- welcher Stack?
- welche Nachbearbeitung?

---

# 1. Grundentscheidung

Nach der Aufnahme:

```

Was fotografiere ich?
|
|
+----------------+
|                |
Deep Sky          Sonne/Mond/Planet
|                |
|                |
Siril Deep Sky    Planetary Workflow

```

---

# 2. Deep Sky Entscheidungsbaum

```

Deep Sky Objekt

```
    |
    |
    +-- Galaxie?
    |
    +-- Nebel?
    |
    +-- Sternhaufen?
    |
    +-- Sternfeld?
    |
    +-- Komet?
```

```

---

# 3. Galaxien Workflow

Beispiele:

- M31
- M33
- M51
- M81/M82

---

## Aufnahme

```

Belichtung:
120–180 Sekunden

Gain:
30–40

Lights:
100–300

```

---

## Filter

Standard:

```

kein Filter

```

---

Dualband:

nur wenn:

- H-alpha-Gebiete interessant sind

---

## Siril Ablauf

```

Sequenz

↓

Dark

↓

Flat optional

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma Stack

↓

Background Extraction

↓

PCC

↓

Green Noise Removal

↓

Stretch

```

---

## Besondere Bearbeitung

Wichtig:

- Kern schützen
- Außenbereiche herausarbeiten

---

# 4. Emissionsnebel Workflow

Beispiele:

- M42
- Herznebel
- Rosettennebel
- Nordamerikanebel

---

## Aufnahme

```

Belichtung:
120–180 Sekunden

Gain:
30–50

```

---

## Filter

Empfehlung:

```

Dualband

```

bei:

- H-alpha
- OIII

---

## Siril Ablauf

```

Sequenz

↓

Dark

↓

Flat

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma Stack

↓

Background Extraction vorsichtig

↓

PCC

↓

Farbkorrektur

↓

Stretch

```

---

## Besondere Bearbeitung

Nicht entfernen:

- rote H-alpha-Strukturen
- blaue/grüne OIII-Bereiche

---

# 5. Reflexionsnebel Workflow

Beispiele:

- M45 Plejaden
- Irisnebel

---

## Aufnahme

```

Belichtung:
60–180 Sekunden

Gain:
30–40

```

---

## Filter

Empfehlung:

```

kein Filter

```

---

## Siril Ablauf

```

Sequenz

↓

Dark

↓

Flat

↓

Kalibrierung

↓

Registrierung

↓

Stack

↓

vorsichtige Background Extraction

↓

PCC

↓

sanfter Stretch

```

---

## Besondere Bearbeitung

Wichtig:

- Blau erhalten
- Hintergrund nicht zu dunkel machen

---

# 6. Sternhaufen Workflow

Beispiele:

- M13
- M3
- M44

---

## Aufnahme

```

Belichtung:
30–120 Sekunden

Gain:
10–30

```

---

## Filter

```

kein Filter

```

---

## Siril Ablauf

```

Kalibrierung

↓

Deep Sky Registrierung

↓

Stack

↓

PCC

↓

leichte Farbkorrektur

↓

Stretch

```

---

## Besondere Bearbeitung

Wichtig:

- Sternfarben erhalten
- Sterne nicht aufblasen

---

# 7. Helle Sterne / Doppelsterne Workflow

Beispiele:

- Arktur
- Albireo
- Sirius

---

## Aufnahme

```

Belichtung:
0,5–10 Sekunden

Gain:
0–20

```

---

## Filter

```

kein Filter

```

---

## Siril Ablauf

```

Sequenz

↓

Registrierung

↓

Stack

↓

leichte Farbkorrektur

↓

Export

```

---

## Besondere Bearbeitung

Nicht:

- stark entrauschen
- stark schärfen

---

# 8. Kometen Workflow

---

Besonderheit:

Komet bewegt sich.

---

## Siril Ablauf

Nicht nur ein Stack.

Zwei Varianten:

---

## Sternstack

```

Sterne ausrichten

↓

Stack

```

---

## Kometenstack

```

Kometenregistrierung

↓

Stack

```

---

Danach:

```

Kombination in GIMP

```

---

# 9. Milchstraße / Widefield Workflow

---

## Aufnahme

```

Belichtung:
10–60 Sekunden

Gain:
20–40

```

---

## Siril Ablauf

```

Sequenz

↓

Kalibrierung

↓

Registrierung

↓

Stack

↓

Background Extraction

↓

PCC

↓

Stretch

```

---

Besonderheit:

Vordergrund eventuell separat bearbeiten.

---

# 10. Mond Workflow

Nicht Deep Sky.

---

## Aufnahme

```

sehr kurze Belichtung

viele Frames

```

---

## Ziel

- Schärfe
- Details
- Krater

---

Ablauf:

```

Beste Bilder auswählen

↓

Stack

↓

Schärfung

↓

Kontrast

```

---

# 11. Planeten Workflow

Beispiele:

- Jupiter
- Saturn
- Mars

---

Nicht:

klassisches Deep Sky Stacking.

---

Ablauf:

```

Video aufnehmen

↓

beste Frames auswählen

↓

Stack

↓

Schärfen

↓

Farbkorrektur

```

---

# 12. Filterentscheidung

```

Welcher Filter?
|
|
+-- Emissionsnebel?
|       |
|       +-- Dualband möglich
|
+-- Galaxie?
|       |
|       +-- kein Filter
|
+-- Sternhaufen?
|       |
|       +-- kein Filter
|
+-- Reflexionsnebel?
|
+-- kein Filter

```

---

# 13. Kalibrierungsentscheidung

```

Brauche ich Flats?
|
|
+-- starke Bearbeitung?
|       |
|       +-- JA
|
+-- Dwarf Vignettierung sichtbar?
|
+-- JA

```

---

Empfehlung:

| Objekt | Dark | Flat |
|---|---|---|
| Galaxie | Ja | Ja |
| Emissionsnebel | Ja | Ja |
| Reflexionsnebel | Ja | Ja |
| Sternhaufen | Ja | optional |
| Sterne | optional | nein |
| Mond | nein | nein |

---

# 14. Stack-Entscheidung

Standard:

```

Winsor Sigma

```

---

Ausnahmen:

## Wenige Bilder

```

Median

```

---

## Sehr saubere Daten

```

Average

```

---

## Satelliten / Flugzeuge

```

Winsor Sigma

```

---

# 15. Problemorientierte Entscheidungen

## Bild zu grün

Reihenfolge:

```

PCC

↓

Green Noise Removal

↓

Farbkorrektur

```

---

## Hintergrund zu hell

Prüfen:

```

Stretch zurücknehmen

↓

Background Extraction

↓

Schwarzpunkt prüfen

```

---

## Nebel verschwindet

Prüfen:

```

GraXpert zu stark?

↓

Stretch zu aggressiv?

↓

Entrauschen zu stark?

```

---

## Sterne zu groß

Prüfen:

```

Belichtung reduzieren

↓

Stretch reduzieren

↓

Sternbearbeitung

```

---

# 16. Universeller Dwarf-Standardworkflow

Wenn unklar:

```

Sequenz erstellen

↓

Dark kalibrieren

↓

Flat verwenden

↓

Deep Sky Registrierung

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

TIFF Export

↓

GIMP


