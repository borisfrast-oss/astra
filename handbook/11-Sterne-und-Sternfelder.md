# Workflow 11 – Einzelsterne und Sternfelder

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Aufnahmen einzelner heller Sterne und dichter Sternfelder mit dem Dwarf 3 mini.

Beispiele:

- Arcturus
- Vega
- Sirius
- Antares
- Sternfelder der Milchstraße
- kleine Himmelsregionen ohne dominantes Deep-Sky-Objekt

Diese Kategorie unterscheidet sich deutlich von Deep-Sky-Objekten.

Das Ziel ist nicht:

- schwächste Details sichtbar machen
- maximales Stretching

Das Ziel ist:

- natürliche Sternfarben
- scharfe Sterne
- kontrollierte Helligkeit
- ästhetisches Sternbild

---

# 1. Eigenschaften von Sternaufnahmen

Ein Stern ist im Gegensatz zu einer Galaxie oder einem Nebel:

- punktförmig
- sehr hell
- farbabhängig
- schnell übersättigt

Die wichtigsten Informationen liegen in:

- Farbe
- Größe
- Umgebung

---

# 2. Größte Herausforderung

Der Sensor kann sehr helle Sterne schnell überbelichten.

Folgen:

- Stern wird weiß
- Farbe geht verloren
- Zentrum ist ausgebrannt

Deshalb:

> Kürzere Belichtungen liefern oft bessere Sternfarben.

---

# 3. Aufnahmeempfehlung

## Einzelne helle Sterne

| Parameter | Empfehlung |
|---|---|
| Belichtung | 5–30 Sekunden |
| Gain | 20–40 |
| Lights | 20–100 |
| Darks | 10–20 |
| Filter | kein Filter |

---

## Sternfelder

| Parameter | Empfehlung |
|---|---|
| Belichtung | 30–120 Sekunden |
| Gain | 30–40 |
| Lights | 50–100 |
| Darks | 10–20 |

---

# 4. Belichtungszeit

## Helle Sterne

Beispiele:

- Arcturus
- Vega
- Sirius

Empfehlung:

```

5–30 Sekunden

```

Warum:

- Farbe bleibt erhalten
- Kern brennt nicht aus

---

## Sternfelder

Längere Belichtung möglich:

```

60–120 Sekunden

```

Ziel:

- mehr schwache Sterne
- mehr Hintergrundsterne

---

# 5. Filterwahl

## Kein Filter

Standard.

Vorteile:

- natürliche Farben
- maximale Lichtmenge

---

## Dualband

Nicht empfohlen.

Grund:

Sterne bestehen aus kontinuierlichem Licht.

Dualband reduziert:

- Farbanteile
- natürliche Sternfarben

---

# 6. Vorbereitung in Siril

Ordner:

```

Arcturus/

lights/

darks/

output/

```

---

# 7. Sequenz erzeugen

Ergebnis:

```

arcturus_light_.seq

```

Prüfen:

- Sterne sichtbar
- Fokus korrekt
- keine Bewegungsunschärfe

---

# 8. Master Dark

Empfehlung:

```

Median

```

---

# 9. Kalibrierung

## Dark

Ja

---

## Flat

Normalerweise:

Nein

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
| Maximale Sterne | 200–500 |
| Entzerrung | aus |

---

# 11. Besonderheit bei wenigen Sternen

Bei einem einzelnen hellen Stern kann die automatische Sternsuche schwieriger sein.

Probleme:

- zu wenig Referenzsterne
- falsche Ausrichtung

Lösung:

- längere Sternfelder verwenden
- mehrere Sterne im Bild lassen

---

# 12. Stack

Empfehlung:

Bei Sternbildern:

```

Durchschnitt

```

oder

```

Winsor Sigma

```

---

Unterschied:

## Durchschnitt

Vorteil:

- maximale Farbinformation

Nachteil:

- Ausreißer bleiben

---

## Winsor Sigma

Vorteil:

- entfernt Satelliten
- entfernt einzelne Fehler

Nachteil:

- kann bei sehr wenigen Bildern aggressiver sein

---

# 13. Normalisierung

Empfehlung:

```

Additiv

```

---

# 14. RGB-Gewichtung

Empfehlung:

```

aus

```

Grund:

Die Farbkalibrierung erfolgt später.

---

# 15. Hintergrundkorrektur

Bei einzelnen Sternen vorsichtig.

Problem:

Ein dunkler Hintergrund ist nicht immer korrekt.

Die Umgebung enthält:

- Milchstraßenlicht
- Staub
- schwache Sterne

---

# GraXpert

Nur verwenden wenn:

- deutliche Gradienten vorhanden sind

Nicht:

bei reinen Sternaufnahmen automatisch.

---

# 16. PCC

Kann sinnvoll sein.

Nach:

```

Stack

↓

optional GraXpert

↓

PCC

```

---

# 17. Farbmanagement

Bei Sternen besonders wichtig.

Beispiele:

## Arcturus

Sollte:

- orange-gelb erscheinen

Nicht:

- blau oder weiß

---

## Vega

Sollte:

- leicht bläulich erscheinen

---

## Betelgeuse

Sollte:

- orange-rot erscheinen

---

# 18. Entrauschen

Minimal.

Empfehlung:

```

0–0,05

```

Oft:

gar nicht notwendig.

Warum?

Rauschen gehört bei Sternfeldern weniger zum Problem als Detailverlust.

---

# 19. Stretching

Sehr vorsichtig.

Ziel:

- Sterne sichtbar machen
- Farben erhalten

Nicht:

maximal aufhellen.

---

Empfehlung:

```

kleiner Stretch

↓

prüfen

↓

kleiner Stretch

```

---

# 20. Schärfung

Nicht notwendig.

Sterne sind bereits Punktquellen.

Zu viel Schärfung erzeugt:

- dunkle Halos
- unnatürliche Ränder

---

# 21. Typische Fehler

## Stern wird blau

Ursachen:

- falsche Farbkalibrierung
- Weißabgleichfehler
- zu starke Farbkorrektur

Lösung:

PCC prüfen.

---

## Alles grün nach Stack

Ursache:

OSC Bayer-Farbverarbeitung.

Lösung:

PCC durchführen.

---

## Sterne verlieren Farbe

Ursachen:

- zu lange Belichtung
- zu starkes Stretching

Lösung:

kürzere Belichtung oder HDR.

---

## Sterne sind riesige Bälle

Ursachen:

- Fokus
- zu viel Entrauschen
- Überschärfung

---

# 22. Beispielworkflow Arcturus

Aufnahme:

```

50 × 15 Sekunden

Gain 30

kein Filter

```

Verarbeitung:

```

Master Dark

↓

Kalibrierung

↓

Registrierung

↓

Stack

↓

PCC

↓

kein Entrauschen

↓

minimaler Stretch

```

---

# 23. Qualitätsziel

Eine gute Sternaufnahme:

- zeigt natürliche Farben
- erhält Helligkeitsunterschiede
- wirkt nicht überschärft
- zeigt einen natürlichen Hintergrund

---

# Kurzfassung

```

5–120 Sekunden

Gain 20–40

20–100 Lights

kein Filter

↓

Kalibrierung

↓

Registrierung

↓

Stack

↓

PCC

↓

minimaler Stretch

```
```
