# Workflow 18 – Mosaike und Panoramen

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Erstellung von Himmelsmosaiken aus mehreren Dwarf-3-Aufnahmen.

Beispiele:

- große Nebelregionen
- Milchstraßenbereiche
- Andromedaregion
- Mondmosaike
- große Sternfelder

Ein Mosaik entsteht, wenn ein Objekt größer ist als das einzelne Sichtfeld des Teleskops.

---

# 1. Warum Mosaike?

Der Dwarf 3 hat ein begrenztes Gesichtsfeld.

Große Objekte passen oft nicht vollständig hinein.

Beispiele:

| Objekt | Problem |
|---|---|
| M31 | nur Kernbereich passt |
| Nordamerikanebel | zu groß |
| Milchstraße | sehr groß |
| Mond | große Detailbereiche |

---

# 2. Grundprinzip

Nicht:

```

alle Einzelbilder zusammen stacken

```

sondern:

```

Position A

↓

eigener Stack

Position B

↓

eigener Stack

Position C

↓

eigener Stack

↓

Mosaik erstellen

```

---

# 3. Aufnahmeplanung

Vor der Aufnahme:

- Überlappung planen
- gleiche Kameraeinstellungen verwenden
- gleiche Belichtungszeit verwenden

---

Empfehlung:

Überlappung:

```

20–30 %

```

Warum:

Programme benötigen gemeinsame Sterne zur Ausrichtung.

---

# 4. Beispiel M31

M31 passt nicht komplett ins Dwarf-Feld.

Plan:

```

M31 Zentrum

*

M31 Nordost

*

M31 Südwest

```

---

Jede Position:

```

100 × 180 Sekunden

Gain 40

gleicher Fokus

gleicher Filter

```

---

# 5. Ordnerstruktur

Empfohlen:

```

M31_Mosaic/

tile_01/

lights/

darks/

tile_02/

lights/

darks/

tile_03/

lights/

darks/

```

---

# 6. Jede Kachel separat bearbeiten

Jede Position bekommt ihren eigenen Siril-Workflow.

---

Ablauf:

```

Sequenz erstellen

↓

Kalibrierung

↓

Registrierung

↓

Stack

↓

GraXpert

↓

PCC

↓

Export

```

---

# 7. Sequenz erzeugen

Für jede Kachel:

Beispiel:

```

tile01_light_.seq

```

---

Kontrolle:

- genügend Sterne
- gleiche Orientierung
- keine schlechten Frames

---

# 8. Master Dark

Wenn alle Aufnahmen:

- gleiche Kamera
- gleiche Temperatur
- gleiche Belichtungszeit

haben:

kann ein gemeinsamer Master Dark verwendet werden.

---

Sonst:

separate Darks.

---

# 9. Kalibrierung

Aktiv:

```

Dark

```

Optional:

```

Flat

```

---

Bei Mosaiken sind Flats besonders hilfreich.

Warum:

Jede Kachel muss dieselbe Helligkeitsverteilung besitzen.

---

# 10. Registrierung

Normale Deep-Sky-Registrierung:

```

Allgemein Deep Sky

```

---

Parameter:

| Parameter | Wert |
|---|---|
| Transformation | Homographie |
| Mindest Sternpaare | 10 |
| Luminanz | aktiv |
| Maximale Sterne | 500 |
| Entzerrung | aus |

---

# 11. Stack

Empfehlung:

```

Winsor Sigma

```

---

Normalisierung:

```

Additiv + Skalierung

```

---

RGB-Gewichtung:

```

aus

```

---

# 12. Hintergrundkorrektur

Wichtig:

Nicht jede Kachel einzeln maximal korrigieren.

Problem:

Unterschiedliche Korrekturen erzeugen sichtbare Übergänge.

---

Besser:

1. Stacks erstellen

2. ähnliche Hintergrundkorrektur verwenden

3. Mosaik erstellen

4. finale Korrektur durchführen

---

# 13. PCC

Möglichkeit 1:

Jede Kachel:

```

PCC einzeln

```

---

Möglichkeit 2:

Nach Mosaik:

```

PCC auf Gesamtbild

```

---

Empfehlung:

Bei großen Mosaiken:

PCC nach Zusammenführung.

---

# 14. Mosaik-Erstellung in GIMP

GIMP kann einfache Mosaike erstellen.

---

Workflow:

1. Neues großes Bild erstellen

2. Einzelbilder als Ebenen öffnen

3. Ebenen verschieben

4. Überlappungen ausrichten

5. Ebenenmasken verwenden

---

# 15. Ausrichtung in GIMP

Hilfreich:

- Transparenz reduzieren
- gleiche Sterne vergleichen
- Hilfslinien verwenden

---

Bei kleinen Abweichungen:

- Drehen
- Skalieren
- Verschieben

---

# 16. Ebenenmasken

Wichtig für Übergänge.

Nicht:

harte Kanten.

---

Besser:

weicher Übergang:

```

schwarze Maske

*

weicher Pinsel

```

---

# 17. Siril Mosaik-Funktion

Siril besitzt auch Werkzeuge für Mosaike.

Je nach Workflow:

- Mosaik-Registrierung
- Mosaik-Komposition

---

Für Dwarf-Aufnahmen ist oft einfacher:

```

Einzelne Stacks

↓

GIMP Zusammensetzung

```

---

# 18. Farbmanagement

Alle Kacheln müssen gleich behandelt werden.

Wichtig:

Nicht:

```

Tile 1 stark gesättigt

Tile 2 neutral

```

---

Empfohlen:

gleicher Workflow:

```

GraXpert

↓

PCC

↓

Stretch

```

---

# 19. Entrauschen

Nicht vor der Zusammenführung.

Besser:

```

Mosaik erstellen

↓

finales Bild

↓

Entrauschen

```

---

Empfehlung:

```

0,03–0,08

```

---

# 20. Typische Fehler

## Sichtbare Übergänge

Ursachen:

- unterschiedliche Hintergrundkorrektur
- unterschiedliche Belichtung
- keine Masken

---

## Sterne passen nicht

Ursachen:

- zu wenig Überlappung
- unterschiedliche Rotation

---

## Eine Ecke ist heller

Ursachen:

- Gradienten
- unterschiedliche Flats

---

## Details verschwinden

Ursache:

zu aggressive Hintergrundkorrektur.

---

# 21. Beispielworkflow Nordamerikanebel

Aufnahme:

```

6 Kacheln

je 80 × 180 Sekunden

Gain 40

Dualband

```

---

Verarbeitung:

```

jede Kachel separat:

Master Dark

↓

Kalibrierung

↓

Registrierung

↓

Winsor Sigma Stack

↓

PCC

↓

Export

↓

Mosaik in GIMP

↓

finale GraXpert-Korrektur

↓

Stretch

↓

Entrauschen

```

---

# 22. Qualitätsziel

Ein gutes Mosaik:

- zeigt große Strukturen ohne Übergänge
- besitzt gleichmäßige Farben
- erhält Sterne und Nebeldetails
- wirkt wie eine einzige Aufnahme

---

# Kurzfassung

```

Mehrere überlappende Aufnahmen

↓

jede Position separat in Siril stacken

↓

gleiche Farbkorrektur

↓

Mosaik zusammensetzen

↓

Masken für Übergänge

↓

finale Bearbeitung

```
```
