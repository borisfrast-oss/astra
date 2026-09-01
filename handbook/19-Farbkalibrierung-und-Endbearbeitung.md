# Workflow 19 – Farbkalibrierung und Endbearbeitung

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die letzten Verarbeitungsschritte nach dem Stacken.

Er gilt objektübergreifend für:

- Galaxien
- Nebel
- Sternhaufen
- Sternfelder
- Kometen
- Mosaike

Der Schwerpunkt liegt auf:

- natürlichen Farben
- kontrolliertem Kontrast
- optimaler Vorbereitung für GIMP

---

# 1. Grundprinzip

Die Bearbeitung sollte in einer festen Reihenfolge erfolgen.

Empfohlener Ablauf:

```

Stack

↓

Hintergrundkorrektur

↓

Farbkalibrierung

↓

Stretch

↓

Entrauschen

↓

Export

↓

GIMP

```

---

# 2. Warum Reihenfolge wichtig ist

Viele Fehler entstehen durch falsche Reihenfolge.

Beispiel:

Entrauschen vor Stretch:

Problem:

- Details werden verändert
- Rauschen wird später wieder sichtbar

---

Farbkorrektur nach extremem Stretch:

Problem:

- Farben werden unnatürlich
- Sterne brennen aus

---

# 3. Hintergrundkontrolle

Vor jeder Farbkorrektur:

prüfen:

- Ist der Hintergrund gleichmäßig?
- Gibt es Gradienten?
- Sind Nebelstrukturen erhalten?

---

Typische Ursachen:

- Lichtverschmutzung
- Mondlicht
- Vignettierung
- Sensorartefakte

---

# 4. Hintergrundextraktion in Siril

Alternative zu GraXpert:

Siril:

```

Hintergrundextraktion

```id="8p4w7k"

---

Geeignet für:

- leichte Gradienten
- kleine Korrekturen

---

Vorsicht bei:

- großen Nebeln
- Dunkelnebeln
- Galaxienhalo

---

# 5. GraXpert vor PCC

Empfohlener Ablauf:

```

Siril Stack

↓

GraXpert Hintergrundkorrektur

↓

zurück nach Siril

↓

PCC

```

---

Warum?

PCC benötigt ein möglichst neutrales Bild.

---

# 6. Photometric Color Calibration (PCC)

PCC ist der Standard für Farbkalibrierung.

Ziel:

Das Bild erhält eine astronomisch sinnvolle Farbbalance.

---

# 7. Voraussetzungen für PCC

Benötigt:

- Sterne
- bekannte Himmelsregion
- Internetzugang für Sternkatalog

---

Geeignet:

- Galaxien
- Nebel
- Sternhaufen
- Sternfelder

---

Schwieriger:

- reine Planetenbilder
- Mond
- sehr wenige Sterne

---

# 8. PCC Workflow Siril 1.4.4

Menü:

```

Bildbearbeitung

↓

Farbkalibrierung

↓

Photometrische Farbkalibrierung

```

---

Eingaben:

## Objekt

Name eingeben:

Beispiele:

```

M31
M42
M13

```id="2w6c9n"

---

## Fokallänge

Falls bekannt:

Dwarf 3:

entsprechenden Wert verwenden.

---

## Pixelgröße

Sensorparameter verwenden.

---

# 9. PCC Parameter

Typische Werte:

| Parameter | Empfehlung |
|---|---|
| Hintergrundneutralisierung | aktiv |
| Automatische Erkennung | aktiv |
| Sternauswahl | automatisch |
| Farbmodell | Standard |

---

Normalerweise:

keine manuellen Änderungen notwendig.

---

# 10. Wenn PCC nicht funktioniert

Typische Gründe:

## Keine Lösung gefunden

Ursachen:

- falsches Objekt
- zu wenige Sterne
- falsche Koordinaten

---

Lösung:

- Objektname prüfen
- Bildausrichtung prüfen
- mehr Sterne verwenden

---

## Farben danach komisch

Ursachen:

- vorher starke Bearbeitung
- falscher Hintergrund

---

Lösung:

Stack erneut prüfen.

---

# 11. Grünstich entfernen

Bei Dwarf OSC-Aufnahmen häufig.

Ursache:

Bayer-Matrix und Sensorcharakteristik.

---

Siril:

```

Grünstich entfernen

```

---

Empfehlung:

Nach PCC.

---

Nicht:

vor PCC.

---

# 12. Stretching

Stretching macht aus linearen Daten ein sichtbares Bild.

Vorher:

```

lineares Rohbild

```id="0n2m6s"

Nachher:

```

sichtbares Bild

```id="5v1x8d"

---

# 13. Stretch-Methoden in Siril

## Automatischer Stretch

Sehr gut für:

- erste Kontrolle
- schnelle Ergebnisse

---

## Manuelles Histogramm

Besser für:

- finale Bearbeitung

---

# 14. Histogramm-Grundprinzip

Links:

```

Schatten

```id="8m3r0k"

---

Mitte:

```

Mitteltöne

```id="2w8j1q"

---

Rechts:

```

Lichter

```id="7k4xqf"

---

Nicht:

den Schwarzpunkt zu weit nach rechts ziehen.

---

# 15. Mehrfaches Stretching

Empfohlen:

```

kleiner Stretch

↓

prüfen

↓

kleiner Stretch

↓

prüfen

```

---

Warum?

Kontrolle über:

- Sterne
- Hintergrund
- Nebeldetails

---

# 16. Entrauschen

Erst nach:

- Farbkorrektur
- Stretch

---

Empfehlungen:

| Objekt | Stärke |
|---|---|
| Galaxien | 0,03–0,08 |
| Nebel | 0,03–0,08 |
| Sternhaufen | 0–0,05 |
| Sterne | 0–0,05 |
| Dunkelnebel | 0,02–0,06 |

---

# 17. Kanalverknüpfung

Option:

```

Kanäle verknüpft

```

---

Bedeutung:

Die Rauschreduzierung wird auf alle Farbkanäle gleich angewendet.

---

Vorteile:

- weniger Farbrauschen
- natürliche Farben

---

Nachteile:

- einzelne Farbdetails können reduziert werden

---

Empfehlung:

Normalerweise:

```

aktiv

```

---

Bei speziellen Nebelfarben:

testen.

---

# 18. Export aus Siril

Empfehlung:

Format:

```

TIFF 16 Bit

```

---

Warum nicht JPEG?

JPEG:

- verlustbehaftet
- reduziert Farben
- ungeeignet für weitere Bearbeitung

---

Warum TIFF?

- hoher Dynamikumfang
- GIMP-kompatibel
- keine Qualitätsverluste

---

# 19. Übergabe an GIMP

In GIMP:

Importieren als:

```

16 Bit Integer

```

---

Nicht:

8 Bit.

---

# 20. GIMP letzte Schritte

Typische Schritte:

## Kurven

Für:

- Kontrast
- Tiefe

---

## Farbtemperatur

Für:

- leichte Korrekturen

---

## Sättigung

Vorsichtig:

```

+5 bis +20

```

---

## Ebenen

Für:

- HDR
- Mosaike
- Sternkontrolle

---

# 21. Typische Fehler

## Hintergrund schwarz

Ursache:

Schwarzpunkt zu weit verschoben.

---

## Sterne weiß

Ursache:

zu starkes Stretching.

---

## Farben künstlich

Ursache:

zu viel Sättigung.

---

## Nebel verschwindet

Ursache:

zu starke Rauschreduktion.

---

# 22. Qualitätskontrolle vor Export

Prüfen:

## Sterne

- keine ausgebrannten Zentren
- natürliche Farben

---

## Hintergrund

- keine starken Gradienten
- nicht komplett schwarz

---

## Objekt

- Strukturen sichtbar
- keine künstlichen Artefakte

---

# 23. Standard-Endworkflow

```

Siril Stack

↓

GraXpert Hintergrundkorrektur

↓

PCC

↓

Grünstich entfernen

↓

Stretch

↓

Entrauschen

↓

TIFF Export

↓

GIMP

↓

Kurven/Farbe/Finalisierung

```

---

# Qualitätsziel

Ein fertiges Astrobild:

- zeigt echte Strukturen
- besitzt natürliche Farben
- erhält Details
- wirkt nicht überbearbeitet

---

# Kurzfassung

```

Stack

↓

Hintergrund sauber machen

↓

PCC

↓

Grünstich entfernen

↓

langsames Stretching

↓

leichtes Entrauschen

↓

16 Bit TIFF

↓

GIMP

```
```
