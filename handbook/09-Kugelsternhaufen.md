# Workflow 09 – Kugelsternhaufen

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Kugelsternhaufen mit dem Dwarf 3 mini.

Beispiele:

- M13 Herkuleshaufen
- M3
- M5
- M15
- Omega Centauri

Kugelsternhaufen gehören zu den dankbarsten Objekten für kleine Teleskope.

Sie sind:

- hell
- kompakt
- reich an Sternen
- farbenprächtig

---

# 1. Eigenschaften von Kugelsternhaufen

Kugelsternhaufen bestehen aus:

- hunderttausenden Sternen
- sehr alten Sternpopulationen
- dicht gepackten Sternfeldern

Typische Eigenschaften:

- heller Kern
- viele Einzelsterne
- große Helligkeitsunterschiede

---

# 2. Hauptziel der Bearbeitung

Bei Kugelsternhaufen geht es weniger um schwache diffuse Strukturen.

Wichtiger:

- Sternfarben erhalten
- Sterne sauber trennen
- Kern nicht ausbrennen
- natürlichen Eindruck bewahren

---

# 3. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 30–180 Sekunden |
| Gain | 30–40 |
| Lights | 30–100 |
| Darks | 10–20 |
| Filter | kein Filter |

---

# 4. Belichtungszeit

Kugelsternhaufen sind heller als Galaxien.

180 Sekunden können bereits zu viel sein.

---

## Lange Belichtung

Vorteile:

- mehr schwache Sterne
- besserer Randbereich

Nachteile:

- Kern kann ausbrennen
- Sterne verlieren Farbe

---

## Kürzere Belichtung

Vorteile:

- bessere Sternfarben
- kontrollierter Kern

---

# 5. HDR-Aufnahme

Empfohlen bei hellen Kugelsternhaufen.

Beispiel:

## Lang

```

50 × 180 Sekunden

```

für:

- schwache Außensterne

---

## Kurz

```

30 × 30 Sekunden

```

für:

- Kernbereich
- helle Sterne

---

Kombination:

```

Langbelichtungs-Stack

*

Kurzbelichtungs-Stack

↓

HDR-Komposition

```

---

# 6. Filterwahl

## Kein Filter

Empfohlen.

Grund:

Sterne enthalten viele Farbinformationen.

Filter reduzieren:

- Sternsignal
- natürliche Farben

---

## Dualband

Nicht empfohlen.

Grund:

Kugelsternhaufen sind keine Emissionsobjekte.

---

# 7. Vorbereitung in Siril

Ordner:

```

M13/

lights/

darks/

output/

```

---

# 8. Sequenz erzeugen

Ergebnis:

```

m13_light_.seq

```

Prüfen:

- Sterne sichtbar
- Fokus korrekt
- keine verwackelten Bilder

---

# 9. Master Dark

Empfehlung:

```

Median

```

---

# 10. Kalibrierung

## Dark

Ja

---

## Flat

Optional.

Sinnvoll bei:

- Vignettierung
- Staub

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

# 12. Besonderheit Sternfelder

Bei Kugelsternhaufen gibt es sehr viele Sterne.

Probleme:

- zu viele Erkennungspunkte
- falsche Sterne
- langsame Registrierung

---

Bei Problemen:

Maximale Sterne reduzieren:

Standard:

```

500

```

Alternative:

```

200–300

```

---

# 13. Stack

Empfehlung:

```

Winsor Sigma

```

---

Warum?

- entfernt Satelliten
- reduziert Ausreißer
- schützt Sterne

---

# Normalisierung

Empfehlung:

```

Additiv

```

---

# RGB-Gewichtung

Empfehlung:

```

aus

```

---

# 14. Hintergrundkorrektur

Weniger aggressiv als bei Galaxien.

Grund:

Viele Sterne bedecken große Teile des Bildes.

---

Problem:

Ein Algorithmus kann Sterne als Hintergrund interpretieren.

---

# GraXpert

Empfehlung:

- wenige Samples
- sanfte Korrektur

Nicht:

komplett dunkler Hintergrund.

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

```

---

# 16. Farbmanagement

Sterne leben von ihren Farben.

Typische Farben:

| Stern | Farbe |
|---|---|
| junge heiße Sterne | blau |
| sonnenähnliche Sterne | gelb |
| alte Riesensterne | orange/rot |

---

# 17. Entrauschen

Sehr vorsichtig.

Empfehlung:

```

0,00–0,05

```

Warum:

Rauschentfernung kann Sterne verschmieren.

---

# 18. Stretching

Ziel:

- Sterne sichtbar machen
- Kern erhalten
- Farben bewahren

---

Nicht:

maximal aufhellen.

---

Besser:

```

kleiner Stretch

↓

prüfen

↓

kleiner Stretch

```

---

# 19. Sterne kontrollieren

Typische Probleme:

## Weiße Sterne

Ursache:

zu starkes Stretching

Lösung:

weniger Stretch

---

## Farblose Sterne

Ursache:

Überbearbeitung

Lösung:

PCC erneut prüfen

---

## Verwaschener Kern

Ursache:

zu lange Belichtung

Lösung:

HDR verwenden

---

# 20. Beispielworkflow M13

Aufnahme:

```

60 × 120 Sekunden

Gain 40

kein Filter

```

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

sanfte Hintergrundkorrektur

↓

PCC

↓

kein oder minimales Entrauschen

↓

langsames Stretching

↓

GIMP

```

---

# 21. Qualitätsziel

Eine gute Kugelsternhaufenaufnahme:

- zeigt viele einzelne Sterne
- behält Sternfarben
- hat einen hellen aber strukturierten Kern
- wirkt nicht künstlich geschärft

---

# Kurzfassung

```

30–180 Sekunden

Gain 30–40

30–100 Lights

kein Filter

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma

↓

sanfte Korrektur

↓

PCC

↓

vorsichtiges Stretching

```
```
