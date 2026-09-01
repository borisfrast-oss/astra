# Workflow 10 – Offene Sternhaufen

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von offenen Sternhaufen mit dem Dwarf 3 mini.

Beispiele:

- M45 Plejaden
- M44 Krippe
- M11 Wildentenhaufen
- NGC 869/884 Doppelsternhaufen
- M35

Offene Sternhaufen gehören zu den attraktivsten Objekten für kleine Teleskope.

Sie unterscheiden sich von Kugelsternhaufen:

- weniger Sterne
- jüngere Sterne
- oft eingebettet in Gas und Staub
- stärkere Sternfarben

---

# 1. Eigenschaften offener Sternhaufen

Offene Sternhaufen bestehen aus:

- jungen Sternen
- Gasresten der Sternentstehung
- häufig Reflexionsnebeln

Typische Eigenschaften:

- viele helle Sterne
- große Ausdehnung
- starke Farbunterschiede

---

# 2. Hauptziel der Bearbeitung

Bei offenen Sternhaufen ist das Ziel:

- natürliche Sternfarben
- scharfe Sterne
- kontrollierter Hintergrund
- eventuell vorhandene Nebel erhalten

Nicht:

- maximale Helligkeit
- extremes Stretching

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

Offene Sternhaufen haben oft helle Sterne.

---

## Kürzere Belichtung

Geeignet für:

- sehr helle Sterne
- Sternfarben
- große Dynamik

Beispiel:

```

30–60 Sekunden

```

---

## Längere Belichtung

Geeignet für:

- schwache Sterne
- eingebettete Nebel

Beispiel:

```

120–180 Sekunden

```

---

# 5. HDR bei offenen Sternhaufen

Sinnvoll bei:

- sehr hellen Sternen
- großen Helligkeitsunterschieden

Beispiel:

Kurze Serie:

```

30 × 30 Sekunden

```

für:

- Sternfarben
- helle Sterne

+

lange Serie:

```

50 × 180 Sekunden

```

für:

- schwache Sterne
- Nebel

---

Kombination:

```

Kurzbelichtung Stack

*

Langbelichtung Stack

↓

HDR-Komposition

```

---

# 6. Filterwahl

## Kein Filter

Standardempfehlung.

Vorteile:

- natürliche Farben
- maximale Sternanzahl
- bessere Farbdifferenzierung

---

## Dualband

Nur bei offenen Sternhaufen mit Nebelanteilen sinnvoll.

Beispiele:

- M45
- IC 2602 mit Nebelstrukturen

Nicht verwenden nur wegen des Sternhaufens.

---

# 7. Vorbereitung in Siril

Ordner:

```

M45/

lights/

darks/

output/

```

---

# 8. Sequenz erzeugen

Ergebnis:

```

m45_light_.seq

```

Prüfen:

- Sterne sichtbar
- keine verwackelten Frames
- Fokus stabil

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

- sichtbaren Staubflecken
- starker Vignettierung

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

# 12. Besonderheit: viele Sterne

Offene Sternhaufen können sehr sternreich sein.

Problem:

Siril erkennt zu viele Sterne.

Folgen:

- langsamere Verarbeitung
- falsche Referenzsterne

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

Warum:

- entfernt Satelliten
- entfernt einzelne Fehler
- schützt vor Ausreißern

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

Grund:

PCC erfolgt später.

---

# 14. Hintergrundkorrektur

Bei Sternhaufen vorsichtig.

Der Hintergrund darf nicht künstlich schwarz werden.

---

Problem:

Zu starke Korrektur entfernt:

- schwache Nebel
- Sternhalos
- natürliche Farbverläufe

---

# GraXpert

Empfehlung:

- wenige Samples
- niedrige Aggressivität

---

# 15. PCC

Nach Hintergrundkorrektur:

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

Sternfarben sind das Hauptmotiv.

Beibehalten:

- blaue Sterne
- gelbe Sterne
- rote Riesensterne

Nicht:

alles weiß machen.

---

# 17. Entrauschen

Sehr vorsichtig.

Empfehlung:

```

0,00–0,05

```

Oft:

gar kein Entrauschen nötig.

---

# 18. Stretching

Ziel:

- Sterne sichtbar machen
- Hintergrund erhalten
- keine ausgebrannten Sterne

---

Empfehlung:

sanft:

```

kleiner Stretch

↓

prüfen

↓

kleiner Stretch

```

---

# 19. Schärfung

Optional.

Sehr vorsichtig.

Geeignet:

- leichte Strukturverstärkung

Nicht:

- harte Sterne
- schwarze Ränder

---

# 20. Typische Fehler

## Sterne sind alle weiß

Ursachen:

- zu starkes Stretching
- falsche Farbkalibrierung

Lösung:

weniger Stretch.

---

## Hintergrund komplett schwarz

Ursache:

zu aggressive Bearbeitung.

Lösung:

natürlichen Hintergrund zurückbringen.

---

## Sterne wirken riesig

Ursachen:

- zu viel Entrauschen
- zu viel Schärfung

Lösung:

weniger Bearbeitung.

---

## Nebel verschwindet bei M45

Ursache:

GraXpert entfernt schwache Strukturen.

Lösung:

sanftere Hintergrundkorrektur.

---

# 21. Beispielworkflow M45

Aufnahme:

```

80 × 120 Sekunden

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

GraXpert vorsichtig

↓

PCC

↓

kein oder minimales Entrauschen

↓

Stretch

↓

GIMP

```

---

# 22. Qualitätsziel

Eine gute Aufnahme eines offenen Sternhaufens:

- zeigt viele Sterne
- erhält natürliche Farben
- zeigt eventuell vorhandenen Nebel
- wirkt nicht überbearbeitet

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

sanfte Hintergrundkorrektur

↓

PCC

↓

leichtes oder kein Entrauschen

↓

natürliches Stretching

```
```
