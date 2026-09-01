# Workflow 15 – Sternentstehungsgebiete und komplexe Nebel

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung großer, komplexer Nebelregionen mit aktiver Sternentstehung.

Beispiele:

- Orionnebel M42
- Pferdekopfnebel IC 434
- Rosettennebel NGC 2237
- Adlernebel M16
- Lagunennebel M8
- Trifidnebel M20
- Nordamerikanebel NGC 7000

Diese Objekte gehören zu den spektakulärsten Deep-Sky-Zielen.

Sie kombinieren mehrere Objektarten:

- Emissionsnebel
- Reflexionsnebel
- Dunkelnebel
- Sternhaufen

---

# 1. Eigenschaften dieser Objekte

Sternentstehungsgebiete enthalten:

- ionisiertes Wasserstoffgas
- Staubwolken
- junge Sterne
- Reflexionsbereiche

Typische Farben:

| Bereich | Farbe |
|---|---|
| H-alpha | rot |
| OIII | blau/grün |
| Reflexion | blau |
| Staub | dunkel |

---

# 2. Hauptziel der Bearbeitung

Erhalten:

- große Nebelstrukturen
- Farbverläufe
- dunkle Staubbänder
- Sterne

Vermeiden:

- ausgebrannte Kerne
- künstliche Farben
- verlorene dunkle Strukturen

---

# 3. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 60–180 Sekunden |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | abhängig vom Objekt |

---

# 4. Filterwahl

## Ohne Filter

Geeignet für:

- dunklen Himmel
- natürliche Farben
- Reflexionsanteile

---

## Dualband

Sehr empfehlenswert.

Besonders für:

- H-alpha-Gebiete
- OIII-Strukturen

Beispiele:

- M16
- M8
- Rosettennebel
- Nordamerikanebel

---

Nachteile:

- weniger Sterne
- stärkere Farbkorrektur notwendig

---

# 5. Kombination verschiedener Aufnahmen

Diese Objekte profitieren besonders von mehreren Serien.

Beispiel:

## Ohne Filter

für:

- Sterne
- Reflexionsanteile

---

## Dualband

für:

- Emissionsstrukturen

---

Kombination:

```

Breitband-Stack

*

Dualband-Stack

↓

Mischung in GIMP

```id="8m2rkd"

---

# 6. Belichtungszeit

## 180 Sekunden

Gut für:

- schwache Außenbereiche
- Nebelstrukturen

---

## Kürzere Belichtungen

Sinnvoll für:

- helle Kerne

Beispiele:

M42:

```

180 Sekunden

*

10–30 Sekunden

```id="m8q1fj"

für HDR.

---

# 7. Vorbereitung in Siril

Ordner:

```

M42/

lights/

darks/

output/

```id="6v3nkm"

---

# 8. Sequenz erzeugen

Ergebnis:

```

m42_light_.seq

```id="j9t6rq"

Prüfen:

- alle Frames vorhanden
- Nebel sichtbar
- keine starken Wolkenänderungen

---

# 9. Master Dark

Empfehlung:

```

Median

```id="2d7m4q"

---

# 10. Kalibrierung

## Dark

Ja

---

## Flat

Empfohlen bei:

- großen Nebelflächen
- sichtbarer Vignettierung

---

## Bias

Normalerweise:

Nein

---

# 11. Registrierung

Menü:

Registrierung

---

Auswahl:

```

Allgemein Deep Sky

```id="w6x1pr"

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

# 12. Besonderheit große Nebel

Große Nebel bedecken oft einen großen Teil des Bildes.

Problem:

Automatische Algorithmen können Nebel als Hintergrund interpretieren.

---

Beispiele:

M42:

- Nebel fast über gesamtes Bild

NGC 7000:

- riesige Struktur

---

# 13. Stack

Empfehlung:

```

Winsor Sigma

```id="a4z9fk"

---

Warum:

- entfernt Satelliten
- reduziert Zufallsrauschen
- schützt schwache Strukturen

---

# Normalisierung

Empfehlung:

```

Additiv + Skalierung

```id="q7w4hc"

---

# RGB-Gewichtung

Empfehlung:

```

aus

```id="r9v0mt"

---

# 14. Hintergrundkorrektur

Sehr kritisch.

Bei Nebeln ist Hintergrund oft kein echter leerer Himmel.

---

GraXpert:

Empfehlung:

- vorsichtig
- wenige Samples
- Nebelbereiche vermeiden

---

Nicht entfernen:

- schwache Außenbereiche
- Staubstrukturen

---

# 15. PCC

Nach Hintergrundkorrektur.

Workflow:

```

Stack

↓

GraXpert

↓

PCC

↓

Stretch

```id="n6s4pt"

---

# 16. Farbmanagement

Diese Objekte dürfen kräftige Farben zeigen.

Aber:

Natürlichkeit erhalten.

---

Typische Fehler:

Zu viel Rot:

- H-alpha übertrieben

Zu viel Grün:

- OIII falsch gewichtet

---

# 17. Entrauschen

Empfehlung:

```

0,03–0,08

```id="c8v5hx"

---

Nicht zu stark.

Warum:

Feine Nebelstrukturen verschwinden schnell.

---

# 18. Stretching

Der wichtigste kreative Schritt.

Ziel:

- Nebel sichtbar machen
- Sterne kontrollieren
- Farben erhalten

---

Empfehlung:

Viele kleine Schritte:

```

Stretch

↓

prüfen

↓

Stretch

↓

prüfen

```id="z4k7mv"

---

# 19. HDR bei hellen Nebeln

Besonders wichtig bei:

- M42
- M8
- M20

---

Workflow:

## Kurzbelichtung

```

10–30 Sekunden

```id="h2c9xs"

für:

- hellen Kern

---

## Langbelichtung

```

180 Sekunden

```id="x5m3kw"

für:

- Außenbereiche

---

Kombination:

```

Kurzstack

*

Langstack

↓

HDR

```id="p6r8nz"

---

# 20. Typische Fehler

## Nebel sieht flach aus

Ursache:

zu starkes Entrauschen.

---

## Sterne dominieren

Ursache:

zu starker Stretch.

---

## Nebel verschwindet

Ursache:

GraXpert zu aggressiv.

---

## Farben wirken unnatürlich

Ursache:

falsche Farbverstärkung.

---

# 21. Beispielworkflow M42

Aufnahme:

```

50 × 180 Sekunden

Gain 40

Dualband optional

```id="u7k2cz"

Zusätzlich:

```

30 × 15 Sekunden

```id="e3q9vf"

für Kern.

---

Verarbeitung:

```

Master Dark

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma Stack

↓

GraXpert vorsichtig

↓

PCC

↓

leichtes Entrauschen

↓

Stretch

↓

HDR mit Kurzbelichtung

↓

GIMP

```id="s6n1qt"

---

# 22. Qualitätsziel

Eine gute Aufnahme eines Sternentstehungsgebietes:

- zeigt große Strukturen
- besitzt natürliche Farben
- erhält dunkle Staubbänder
- zeigt Sterne ohne Überdominanz
- wirkt räumlich

---

# Kurzfassung

```

60–180 Sekunden

Gain 30–40

50–200 Lights

Dualband möglich

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma

↓

vorsichtige Hintergrundkorrektur

↓

PCC

↓

moderates Entrauschen

↓

langsames Stretching

```
```
