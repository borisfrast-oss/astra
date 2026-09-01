# Workflow 13 – Milchstraße und Weitfeldaufnahmen

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von großflächigen Himmelsaufnahmen mit dem Dwarf 3 mini.

Beispiele:

- Milchstraßenpanoramen
- Sternfelder
- große Nebelregionen
- Sternbilder
- Widefield-Aufnahmen

Diese Kategorie unterscheidet sich von klassischen Deep-Sky-Objekten.

Das Hauptziel ist:

- natürliche Sternfelder
- harmonischer Hintergrund
- Erhalt großer Strukturen

---

# 1. Eigenschaften von Weitfeldaufnahmen

Weitfeldbilder enthalten:

- sehr viele Sterne
- große Himmelsbereiche
- diffuse Milchstraßenstrukturen
- Farbverläufe des Himmels

Typische Herausforderungen:

- Lichtverschmutzung
- Gradienten
- sehr viele Sterne
- Hintergrundkorrektur

---

# 2. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 30–180 Sekunden |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | kein Filter |

---

# 3. Belichtungszeit

## Dunkler Himmel

Möglich:

```

120–180 Sekunden

```id="z0x7fb"

Vorteile:

- mehr Sterne
- mehr Milchstraßenstruktur

---

## Lichtverschmutzter Himmel

Besser:

```

30–90 Sekunden

```id="2x8q0z"

Grund:

Der Hintergrund wird sonst zu hell.

---

# 4. Filterwahl

## Kein Filter

Standard.

Vorteile:

- natürliche Farben
- maximale Sternanzahl
- natürliche Milchstraßenfarben

---

## Lichtverschmutzungsfilter

Kann sinnvoll sein bei:

- Stadt
- Vorstadt
- hellem Himmel

---

## Dualband

Nur für enthaltene Nebelbereiche.

Nicht für reine Milchstraße.

Grund:

Sterne und Sternfarben werden verändert.

---

# 5. Vorbereitung in Siril

Ordner:

```

MilkyWay/

lights/

darks/

output/

```id="v5x0ap"

---

# 6. Sequenz erzeugen

Ergebnis:

```

milkyway_light_.seq

```id="7u4lpc"

Prüfen:

- genügend Sterne
- keine Wolken
- gleichmäßiger Fokus

---

# 7. Master Dark

Empfehlung:

```

Median

```id="1pmq2h"

---

# 8. Kalibrierung

## Dark

Ja

---

## Flat

Optional.

Sinnvoll bei:

- starkem Randabfall
- Staub
- sichtbaren Flecken

---

## Bias

Normalerweise:

Nein

---

# 9. Registrierung

Menü:

Registrierung

---

Auswahl:

```

Allgemein Deep Sky

```id="qz3m2p"

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

# 10. Besonderheit bei Weitfeld

Durch die große Bildfläche gibt es viele Sterne.

Probleme:

- zu viele Erkennungspunkte
- falsche Referenzen
- lange Verarbeitung

---

Bei Problemen:

Maximale Sterne reduzieren:

Standard:

```

500

```id="q8l3jy"

Alternative:

```

200–300

```id="x4f2mc"

---

# 11. Stack

Empfehlung:

```

Winsor Sigma

```id="n4s7pv"

Warum:

- Satelliten entfernen
- Flugzeuge entfernen
- zufällige Fehler reduzieren

---

# Normalisierung

Empfehlung:

```

Additiv

```id="x3d9bm"

Bei identischen Aufnahmen ausreichend.

---

# RGB-Gewichtung

Empfehlung:

```

aus

```id="p0v9fa"

---

# 12. Hintergrundkorrektur

Der wichtigste Schritt bei Weitfeld.

Probleme:

- Lichtverschmutzungsgradienten
- Mondlicht
- ungleichmäßiger Himmel

---

# GraXpert

Sehr sinnvoll.

Aber:

vorsichtig arbeiten.

---

Gefahr:

Zu aggressive Korrektur entfernt:

- Milchstraßenstrukturen
- Staubwolken
- natürliche Helligkeitsverläufe

---

# 13. GraXpert-Empfehlung

Start:

- wenige Samples
- moderate Korrektur

Kontrolle:

Vorher:

```

natürlicher Himmel

```id="o4pl6r"

Nachher:

```

Gradient entfernt

Strukturen erhalten

```id="9o8h4c"

---

# 14. PCC

Bei Weitfeld sehr hilfreich.

Ablauf:

```

Stack

↓

GraXpert

↓

PCC

↓

Stretch

```id="v7x0pa"

---

# 15. Farbmanagement

Milchstraße enthält viele Farben:

- blaue Reflexionsbereiche
- rote Nebel
- gelbliche Sterne
- dunkle Staubbänder

Nicht:

alles neutral grau machen.

---

# 16. Entrauschen

Bei Weitfeld vorsichtig.

Empfehlung:

```

0,03–0,08

```id="d9k2fs"

---

Warum:

Große dunkle Bereiche zeigen Rauschen stärker.

---

# 17. Stretching

Das Ziel:

Die Milchstraße sichtbar machen.

---

Nicht:

zu stark aufhellen.

Problem:

- Sterne werden dominant
- Hintergrund wird grau
- Kontrast geht verloren

---

Empfehlung:

Mehrere kleine Schritte:

```

kleiner Stretch

↓

prüfen

↓

kleiner Stretch

```id="r2y6kv"

---

# 18. Sterne kontrollieren

Bei Weitfeld sind Sterne ein großer Teil des Bildes.

Probleme:

## Zu viele dominante Sterne

Lösung:

- weniger Stretch
- Sternreduktion in GIMP möglich

---

## Sterne ohne Farbe

Ursachen:

- Überbelichtung
- zu starker Stretch

---

# 19. Panorama und Mosaike

Große Himmelsbereiche können aus mehreren Feldern bestehen.

Beispiel:

```

Position 1

*

Position 2

*

Position 3

↓

Panorama

```id="p8h1jk"

---

Workflow:

Jede Position separat:

```

Stack

↓

PCC

↓

Stretch

```id="8q2k0m"

Danach:

Zusammenfügen in GIMP.

---

# 20. Typische Fehler

## Hintergrund sieht fleckig aus

Ursachen:

- zu wenig Bilder
- aggressive Hintergrundkorrektur

---

## Milchstraße verschwindet

Ursache:

GraXpert zu stark.

---

## Sterne wirken künstlich

Ursachen:

- zu starkes Schärfen
- zu viel Entrauschen

---

## Bild wirkt flach

Ursachen:

- zu wenig Kontrast
- zu starke Neutralisierung

---

# 21. Beispielworkflow Milchstraße

Aufnahme:

```

100 × 60 Sekunden

Gain 30–40

kein Filter

```id="h3p7vn"

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

GraXpert

↓

PCC

↓

leichtes Entrauschen

↓

sanftes Stretching

↓

GIMP

```id="m1z7yt"

---

# 22. Qualitätsziel

Eine gute Milchstraßenaufnahme:

- zeigt natürliche Sternfarben
- besitzt einen gleichmäßigen Hintergrund
- erhält dunkle Staubbänder
- zeigt Nebelbereiche ohne Übertreibung
- wirkt dreidimensional

---

# Kurzfassung

```

30–180 Sekunden

Gain 30–40

50–200 Lights

kein Filter

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma

↓

GraXpert vorsichtig

↓

PCC

↓

sanftes Stretching

```
```
