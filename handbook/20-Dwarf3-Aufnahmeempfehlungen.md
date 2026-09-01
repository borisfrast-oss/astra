# Kapitel 20 – Dwarf 3 Aufnahmeempfehlungen

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt die optimalen Aufnahmeparameter für den Dwarf 3 mini in Kombination mit Siril 1.4.4.

Es geht nicht um die Nachbearbeitung, sondern um die wichtigste Grundlage:

**gute Rohdaten aufnehmen.**

Die Qualität des Endergebnisses wird zu einem großen Teil bereits bei der Aufnahme bestimmt.

---

# 1. Grundprinzip des Dwarf 3 Workflows

Ein Smart-Teleskop wie der Dwarf 3 arbeitet anders als eine klassische Astrokamera.

Die wichtigsten Faktoren:

- begrenzte Öffnung
- kleiner Sensor
- automatische Nachführung
- keine klassische Kühlung
- integrierte Optik
- automatisches Stacking

Daher gilt:

## Mehr gute Einzelbilder schlagen meistens ein einzelnes perfektes Bild.

---

Grundregel:

```

mehr Lights

*

korrekte Belichtung

*

saubere Kalibrierung

=

besseres Endbild

```

---

# 2. Die drei wichtigsten Aufnahmeparameter

Die Qualität wird hauptsächlich bestimmt durch:

1. Belichtungszeit
2. Gain
3. Anzahl der Bilder

---

# 3. Belichtungszeit

Die Belichtungszeit bestimmt:

- Signalmenge
- Hintergrundhelligkeit
- Sternsättigung
- Nachführfehler

---

# 3.1 Kurze Belichtungen

Typisch:

```

0,5–10 Sekunden

```

Geeignet für:

- Mond
- Planeten
- helle Sterne
- Doppelsterne

Vorteile:

- scharfe Sterne
- weniger Überbelichtung

Nachteile:

- weniger Signal
- mehr Einzelbilder notwendig

---

# 3.2 Mittlere Belichtungen

Typisch:

```

10–60 Sekunden

```

Geeignet für:

- Sternhaufen
- helle Nebel
- helle Galaxien

---

# 3.3 Lange Belichtungen

Typisch:

```

60–180 Sekunden

```

Geeignet für:

- Deep Sky
- schwache Nebel
- Galaxien

---

# 3.4 Maximale Belichtung

180 Sekunden ist beim Dwarf 3 meistens der praktische Sweet Spot.

Längere Belichtungen bringen oft weniger Vorteile:

Probleme:

- Hintergrund wird heller
- Sterne sättigen
- Nachführfehler werden sichtbarer

---

# 4. Gain-Einstellungen

Gain beeinflusst:

- Empfindlichkeit
- Rauschen
- Dynamikumfang

---

# 4.1 Niedriger Gain

Bereich:

```

0–20

```

Geeignet für:

- Mond
- Sterne
- helle Objekte

Vorteile:

- mehr Dynamik
- bessere Sternfarben

---

# 4.2 Mittlerer Gain

Bereich:

```

20–40

```

Der typische Deep-Sky-Bereich.

Geeignet für:

- Galaxien
- Nebel
- Sternhaufen

---

# 4.3 Hoher Gain

Bereich:

```

40+

```

Geeignet für:

- sehr schwache Objekte
- kurze Belichtungen

Nachteile:

- mehr Rauschen
- weniger Dynamik

---

# 5. Empfohlene Dwarf-3 Profile

## Profil A – Deep Sky Standard

Für:

- Galaxien
- Nebel
- Sternhaufen

```

Belichtung:
120–180 Sekunden

Gain:
30–40

Lights:
100–300

```

---

## Profil B – Schwache Nebel

Für:

- Herznebel
- Seelennebel
- Schleiernebel

```

Belichtung:
180 Sekunden

Gain:
40

Lights:
200–500

```

---

## Profil C – Helle Objekte

Für:

- M42 Kern
- Plejaden
- helle Sterne

```

Belichtung:
5–60 Sekunden

Gain:
10–30

Lights:
100+

```

---

## Profil D – Mond

```

Belichtung:
Millisekunden bis wenige Sekunden

Gain:
0–20

viele Frames

```

---

# 6. Anzahl der Lights

Die wichtigste Regel:

## Signal wächst linear

## Rauschen sinkt mit der Quadratwurzel

---

Beispiel:

100 Bilder statt 25 Bilder:

- 4× mehr Daten
- ungefähr doppelte Rauschverbesserung

---

Empfehlungen:

| Objekt | Anzahl Lights |
|---|---:|
| Mond | viele kurze Frames |
| Planeten | viele Frames |
| Sterne | 50–200 |
| Sternhaufen | 100–300 |
| Nebel | 200–500 |
| Galaxien | 100–300 |

---

# 7. Darks

Darks enthalten:

- Sensorrauschen
- Hotpixel
- thermisches Signal

---

Empfehlung:

```

10–30 Darkframes

```

---

Mehr bringt wenig.

---

Wichtig:

Darks müssen möglichst gleich sein:

- gleiche Belichtung
- gleicher Gain
- gleiche Temperatur

---

# 8. Flats

Flats korrigieren:

- Vignettierung
- Staub
- ungleichmäßige Ausleuchtung

---

Beim Dwarf besonders hilfreich bei:

- starkem Stretch
- Nebeln
- Galaxien

---

Problem:

Falsche Flats verschlechtern das Bild.

---

Typische Fehler:

- andere Kameraposition
- andere Fokuseinstellung
- falsche Belichtung

---

# 9. Bias

Bias misst das Ausleserauschen.

Beim Dwarf:

meist optional.

---

Viele Anwender erzielen bessere Ergebnisse mit:

```

Dark + Flat

```

als mit:

```

Dark + Flat + Bias

```

---

# 10. Filterstrategie

## Kein Filter

Standard.

Geeignet für:

- Galaxien
- Sternhaufen
- Reflexionsnebel
- Sterne

---

## Dualband

Geeignet für:

- Emissionsnebel

Beispiele:

- H-alpha
- OIII

---

Nicht ideal für:

- Galaxien
- Reflexionsnebel
- Sterne

---

# 11. Aufnahme unter Mondlicht

Mond beeinflusst:

- Hintergrundhelligkeit
- Kontrast
- schwache Strukturen

---

Geeignet:

- helle Nebel mit Dualband
- Sternhaufen
- helle Objekte

---

Schlecht:

- schwache Galaxien
- Reflexionsnebel

---

# 12. Fokus

Ein perfekter Fokus ist wichtiger als viele andere Einstellungen.

---

Kontrolle:

Sterne sollten:

- klein
- rund
- symmetrisch

sein.

---

Probleme:

## Sterne groß

Ursachen:

- Fokus
- Seeing
- Überbelichtung

---

## Sterne oval

Ursachen:

- Nachführung
- Wind
- Stativ

---

# 13. Seeing und Wetter

Optimale Bedingungen:

- klare Nacht
- wenig Wind
- stabile Temperatur
- kein Hochnebel

---

Nicht optimal:

- dünne Wolken
- starke Luftunruhe
- Temperaturwechsel

---

# 14. Was tun, wenn der Dwarf automatisch weniger stackt?

Das ist normal.

Ursachen:

- schlechte Einzelbilder
- Sterne nicht erkannt
- Nachführfehler
- Wolken
- Bewegung

---

Besser:

Viele gute Bilder.

Nicht:

viele schlechte Bilder.

---

# 15. Qualitätskontrolle vor Siril

Vor Verarbeitung prüfen:

- Sind Sterne rund?
- Gibt es verwackelte Frames?
- Sind Bilder überbelichtet?
- Sind Wolken vorhanden?
- Ist das Objekt sichtbar?

---

Schlechte Frames aussortieren.

---

# 16. Empfohlene Standardaufnahme

Wenn man nicht weiß, was man einstellen soll:

```

Deep Sky:

180 Sekunden

Gain 35

kein Filter

200 Lights

10–20 Darks

Flats vorhanden

```

Das ist ein sehr guter Ausgangspunkt für:

- M31
- M42
- M45
- M13
- viele Nebel und Galaxien

---

# 17. Wichtigste Regeln zusammengefasst

```

Belichtung nicht übertreiben

↓

Gain moderat halten

↓

viele Lights aufnehmen

↓

Darks nicht vergessen

↓

Flats korrekt erstellen

↓

gute Rohdaten sind wichtiger als Nachbearbeitung


