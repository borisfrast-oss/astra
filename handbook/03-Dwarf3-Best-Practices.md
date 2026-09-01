# 03 – Dwarf 3 Best Practices

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Übersicht

Dieses Kapitel beschreibt die optimalen Aufnahme- und Verarbeitungsstrategien für den Dwarf 3 mini.

Behandelte Themen:

- Aufnahmeparameter
- Belichtungszeiten
- Gain
- Anzahl Aufnahmen
- Darks
- Flats
- Filter
- unterschiedliche Objektarten
- typische Fehler
- praktische Empfehlungen

---

# 1. Grundprinzip beim Dwarf 3

Der Dwarf 3 ist ein Smart Telescope.

Er übernimmt:

- automatische Nachführung
- Platesolving
- Objektpositionierung
- Bildaufnahme
- interne Ausrichtung

Die Qualität des Endergebnisses hängt trotzdem stark von der Aufnahmeplanung ab.

Wichtige Faktoren:

1. Integrationszeit
2. Belichtungszeit pro Bild
3. Gain
4. Anzahl der Einzelbilder
5. Himmelshintergrund
6. Filterwahl

---

# 2. Empfohlene Standardaufnahme

Für typische Deep-Sky-Objekte:

| Parameter | Empfehlung |
|---|---|
| Belichtung | 180 Sekunden |
| Gain | 40 |
| Format | FITS |
| Anzahl Lights | 30–100 |
| Dark Frames | 10–20 |
| Filter | abhängig vom Objekt |

---

# 3. Belichtungszeit

Die Belichtungszeit bestimmt:

- wie viele Photonen gesammelt werden
- wie stark schwache Strukturen sichtbar werden

---

## 180 Sekunden

Für den Dwarf 3 ein sehr guter Standard.

Geeignet für:

- Galaxien
- Nebel
- Sternhaufen

Vorteile:

- gute Signalmenge
- weniger Einzelbilder notwendig

---

## Kürzere Belichtungen

Beispiele:

```

10 Sekunden
30 Sekunden
60 Sekunden

```

Geeignet für:

- helle Sterne
- Mond
- Planeten
- sehr helle Objekte

Vorteile:

- Sterne brennen weniger aus
- Nachführfehler wirken sich weniger aus

---

## Längere Belichtungen

Beispiel:

```

300 Sekunden

```

können theoretisch mehr Signal liefern.

Nachteile:

- höhere Anforderungen
- mehr Fehler durch Nachführung
- mehr Hintergrundlicht

---

# 4. Gain

Gain verstärkt das Sensorsignal.

Wichtig:

Gain erzeugt kein zusätzliches Licht.

Es verändert nur:

- Verstärkung
- Ausleseverhalten
- Dynamikbereich

---

## Empfehlung

Für Deep Sky:

```

Gain 40

```

guter Kompromiss zwischen:

- Empfindlichkeit
- Dynamik
- Rauschverhalten

---

# 5. Anzahl der Lights

Mehr Bilder verbessern die Qualität.

Empfehlungen:

| Objekt | Empfehlung |
|---|---:|
| heller Sternhaufen | 20–30 |
| Galaxie | 50+ |
| Nebel | 50–100+ |
| sehr schwache Objekte | möglichst viele |

---

# 6. Warum der Dwarf manchmal nicht mehr stackt

Bei automatischem Stacken im Dwarf kann es passieren:

- wenige Bilder werden verworfen
- Sterne werden nicht erkannt
- Trackingqualität reicht nicht

Mögliche Ursachen:

- zu wenig Sterne
- Wolken
- Tau
- Lichtverschmutzung
- schlechte Fokussierung

Die Einzelbilder können trotzdem in Siril verwendet werden.

---

# 7. Darks

## Zweck

Darks entfernen:

- Hotpixel
- Dunkelstrom
- feste Sensorfehler

---

# 8. Dark-Aufnahme mit dem Dwarf 3

Regeln:

Die Darks müssen identisch zu den Lights sein.

Gleich:

| Parameter | Muss gleich |
|---|---|
| Belichtungszeit | Ja |
| Gain | Ja |
| Kamera | Ja |
| Filter | Ja |

---

Beispiel:

Lights:

```

180 Sekunden
Gain 40
kein Filter

```

Darks:

```

180 Sekunden
Gain 40
kein Filter

```

---

# 9. Darks mit oder ohne ND-Filter?

Empfehlung:

Keine Änderung gegenüber den Lights.

Wenn die Lights ohne ND aufgenommen wurden:

→ Darks ohne ND.

Wenn die Lights mit Filter aufgenommen wurden:

→ Darks mit derselben Konfiguration.

Grund:

Darks messen nicht das Motiv.

Sie messen den Sensor.

---

# 10. Anzahl der Darks

Empfehlung:

| Anzahl | Qualität |
|---:|---|
| 5 | ausreichend |
| 10 | gut |
| 20 | sehr gut |
| 30+ | kaum noch Verbesserung |

---

# 11. Flats

Flats sind schwieriger als Darks.

Sie benötigen:

- gleiche Optik
- gleiche Ausrichtung
- gleiche Kamera

Sie korrigieren:

- Staub
- Vignettierung
- ungleichmäßige Ausleuchtung

---

# 12. Wann Flats verwenden?

Sinnvoll bei:

- sichtbaren Flecken
- starkem Randabfall
- Filterwechsel

Nicht zwingend notwendig:

- wenn das Bild gleichmäßig ist
- bei kurzen Testaufnahmen

---

# 13. Bias beim Dwarf 3

Bias ist bei klassischen Astrokameras wichtig.

Beim Dwarf 3:

meist nicht notwendig.

Empfohlener Workflow:

```

Lights

*

Darks

↓

kalibrierte Bilder

```

---

# 14. Filter

## Kein Filter

Geeignet für:

- Galaxien
- Sternhaufen
- Sterne

Vorteile:

- natürliche Farben
- maximale Lichtmenge

---

## Dualband-Filter

Geeignet für:

- Emissionsnebel

Beispiele:

- H-alpha
- OIII

Vorteile:

- bessere Nebelstrukturen
- weniger Lichtverschmutzung

Nachteile:

- Sterne schwächer
- Farben verändern sich

---

# 15. Unterschiedliche Belichtungszeiten kombinieren

Ja, das ist möglich.

Beispiel:

M31:

```

60 × 180 Sekunden

*

30 × 30 Sekunden

```

Ziel:

lange Belichtung:

- Außenbereiche
- Nebelstrukturen

kurze Belichtung:

- Kernbereich
- helle Sterne

---

Das Ergebnis wird normalerweise nicht einfach gemeinsam gestackt.

Besser:

```

lange Belichtung stacken

↓

kurze Belichtung stacken

↓

beide Bilder kombinieren

```

Das nennt man:

- HDR
- Compositing
- Luminanzkombination

---

# 16. Dualband und normale Aufnahmen kombinieren

Auch möglich.

Beispiel:

```

RGB Aufnahme

*

Dualband Aufnahme

```

Workflow:

1. RGB normal verarbeiten
2. Dualband separat stacken
3. Nebelsignal extrahieren
4. kombinieren

---

# 17. Sterne fotografieren

Für helle Sterne:

Beispiele:

- Arcturus
- Vega
- Sirius

Empfehlung:

- kurze Belichtung
- kein aggressives Entrauschen
- keine starke Sigma-Filterung

Warum?

Sternfarben sind empfindlich.

---

# 18. Sternhaufen

Eigenschaften:

- viele Sterne
- hohe Dynamik

Empfehlung:

- weniger Entrauschen
- vorsichtiges Stretching
- Sternfarben erhalten

Winsor Sigma:

ja, aber vorsichtig.

---

# 19. Galaxien

Beispiele:

- M31
- M33
- M81

Empfehlung:

```

180 Sekunden

Gain 40

50+ Bilder

```

Workflow:

- Winsor Sigma
- Hintergrundkorrektur
- PCC
- moderates Stretching

---

# 20. Nebel

Empfehlung:

Viele Frames.

Besonders wichtig:

- Hintergrund entfernen
- Farbkalibrierung
- nicht zu stark entrauschen

---

# 21. Typische Dwarf-3-Probleme

## Bild komplett schwarz

Ursache:

Linearbild.

Lösung:

Stretching durchführen.

---

## Bild grün

Ursache:

OSC Bayer-Sensor.

Lösung:

PCC danach optional SCNR.

---

## M110 verschwindet beim Entrauschen

Ursache:

zu aggressives Entrauschen.

Lösung:

Werte reduzieren.

Empfehlung:

```

0,05–0,1

```

---

## Rahmen in GraXpert

Ursachen:

- Vorschaugrenzen
- Hintergrundmodell
- Randartefakte

Nicht automatisch ein echter Bildfehler.

---

# 22. Empfohlener Dwarf-Workflow

Für den Einstieg:

```

Objekt auswählen

↓

180 Sekunden

↓

Gain 40

↓

30-100 Lights

↓

10-20 Darks

↓

Siril Kalibrierung

↓

Registrierung:
Allgemein Deep Sky

↓

Stack:
Winsor Sigma

↓

GraXpert

↓

PCC

↓

Stretch

↓

GIMP

```

---

# Wichtigste Regeln

1. Mehr Bilder sind besser als stärkere Bearbeitung.

2. Darks müssen zu den Lights passen.

3. Nicht jedes Objekt braucht denselben Workflow.

4. Entrauschen erst spät und vorsichtig.

5. Sterne sind empfindlicher als Nebel.

6. Natürliches Aussehen ist wichtiger als maximale Helligkeit.
```
