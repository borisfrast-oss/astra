# Workflow 07 – Reflexionsnebel

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Reflexionsnebeln mit dem Dwarf 3 mini.

Beispiele:

- M45 Plejaden
- M78
- Irisnebel NGC 7023
- vdB-Objekte

Reflexionsnebel unterscheiden sich deutlich von Emissionsnebeln.

Sie leuchten nicht selbst.

Sie reflektieren das Licht naher Sterne.

---

# 1. Eigenschaften von Reflexionsnebeln

Reflexionsnebel bestehen aus Staubwolken, die Sternlicht streuen.

Typische Eigenschaften:

- bläuliche Farbe
- sehr schwache Strukturen
- geringer Kontrast
- empfindlich gegen Lichtverschmutzung

---

# 2. Vergleich zu Emissionsnebeln

| Eigenschaft | Reflexionsnebel | Emissionsnebel |
|---|---|---|
| eigene Lichtquelle | nein | ja |
| typische Farbe | blau | rot/blau/grün |
| Filterwirkung | geringer | oft stark |
| Schwierigkeit | hoch | mittel |

---

# 3. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 180 Sekunden |
| Gain | 40 |
| Lights | 50–150 |
| Darks | 10–20 |
| Filter | meist ohne Filter |

---

# 4. Warum viele Bilder notwendig sind

Reflexionsnebel haben eine geringe Flächenhelligkeit.

Das Signal verteilt sich über eine große Fläche.

Deshalb:

Mehr Integration ist wichtiger als aggressive Bearbeitung.

Empfehlung:

Minimum:

```

50 Lights

```

Besser:

```

100+ Lights

```

---

# 5. Filterwahl

## Kein Filter

Meist beste Wahl.

Vorteile:

- natürliche Sternfarben
- maximale Lichtmenge
- bessere Blauanteile

---

## Dualband-Filter

Nur eingeschränkt sinnvoll.

Grund:

Dualband verstärkt:

- H-alpha
- OIII

Reflexionsnebel bestehen aber hauptsächlich aus reflektiertem Sternlicht.

---

# 6. Vorbereitung in Siril

Ordner:

```

M78/

lights/

darks/

output/

```

---

# 7. Sequenz erstellen

Ergebnis:

```

m78_light_.seq

```

Prüfen:

- alle Bilder geladen
- Sterne vorhanden
- Fokus stabil

---

# 8. Master Dark

Empfehlung:

Methode:

```

Median

```

Warum:

- stabile Sensorfehler
- geringe Zufallsschwankung

---

# 9. Kalibrierung

## Dark

Aktiv:

Ja

---

## Flat

Nur verwenden bei:

- sichtbaren Staubflecken
- starker Vignettierung

---

## Bias

Normalerweise:

Nein

---

# 10. Registrierung

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

# 11. Besonderheit: schwache Nebel

Bei Reflexionsnebeln darf die Hintergrundkorrektur nicht zu aggressiv sein.

Problem:

Der Nebel sieht oft ähnlich aus wie ein Gradient.

Beispiel:

M45:

Die blauen Nebelstrukturen liegen sehr großflächig um die Sterne.

---

# 12. Stack

Empfehlung:

```

Winsor Sigma

```

Warum:

- entfernt Satelliten
- entfernt zufällige Fehler
- erhält schwache Strukturen

---

# Normalisierung

Empfehlung:

```

Additiv

```

Bei Dwarf-Serien normalerweise ausreichend.

---

# RGB-Gewichtung

Empfehlung:

```

aus

```

Grund:

PCC erfolgt später.

---

# 13. Hintergrundkorrektur

Sehr wichtiger Schritt.

Reflexionsnebel reagieren empfindlich auf:

- falsche Gradientenentfernung
- zu dunklen Hintergrund
- Farbverschiebung

---

# GraXpert Empfehlung

Sanft arbeiten.

Ziel:

Entfernen:

- Lichtverschmutzung
- ungleichmäßigen Hintergrund

Nicht entfernen:

- große schwache Nebelbereiche

---

# 14. PCC

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

# 15. Farbcharakter

Reflexionsnebel sollen häufig blau erscheinen.

Nicht versuchen, sie komplett neutral grau zu machen.

Beispiel:

M45:

Normal:

- blaue Staubwolken
- warme Sterne

Nicht:

- rein weißer Nebel

---

# 16. Entrauschen

Besonders vorsichtig.

Empfehlung:

```

0,03–0,08

```

Warum:

Die schwachen Staubstrukturen können schnell verschwinden.

---

# 17. Stretching

Ziel:

sichtbar machen:

- Staubwolken
- feine Farbverläufe
- Umgebung der Sterne

---

Empfehlung:

Sehr langsam.

Besser:

```

kleiner Stretch

↓

prüfen

↓

kleiner Stretch

```

---

# 18. Sterne

Reflexionsnebel enthalten oft helle Sterne.

Probleme:

- ausgebrannte Sterne
- fehlende Farbe
- zu harte Schärfung

Empfehlung:

Keine aggressive Sternbearbeitung.

---

# 19. Typische Fehler

## Nebel verschwindet

Ursachen:

- zu starkes Entrauschen
- zu aggressive Hintergrundkorrektur

Lösung:

Bearbeitung zurücknehmen.

---

## Bild wirkt grau

Ursache:

zu starke Neutralisierung.

Lösung:

Farbcharakter erhalten.

---

## Sterne ohne Farbe

Ursache:

zu starkes Stretching.

Lösung:

sanfter arbeiten.

---

# 20. Beispielworkflow M45

Aufnahme:

```

100 × 180 Sekunden

Gain 40

ohne Filter

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

leichtes Entrauschen

↓

langsames Stretching

↓

GIMP

```

---

# 21. Qualitätsziel

Eine gute Reflexionsnebelaufnahme:

- zeigt blaue Staubstrukturen
- erhält natürliche Sternfarben
- besitzt einen weichen Hintergrund
- wirkt nicht überschärft
- zeigt Details ohne künstlichen Kontrast

---

# Kurzfassung

```

180 Sekunden

Gain 40

50–150 Lights

kein Dualband

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

vorsichtiges Stretching

```
```
