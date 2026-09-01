# Workflow 08 – Planetarische Nebel

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von planetarischen Nebeln mit dem Dwarf 3 mini.

Beispiele:

- M57 Ringnebel
- M27 Hantelnebel
- NGC 6543 Katzenaugennebel
- NGC 2392 Eskimonebel

Planetarische Nebel sind besondere Deep-Sky-Objekte.

Sie unterscheiden sich von Galaxien und großen Nebeln:

- klein
- relativ hell
- hoher Kontrast
- oft heller Zentralbereich
- viele Details in kleinen Strukturen

---

# 1. Eigenschaften planetarischer Nebel

Planetarische Nebel entstehen aus den abgestoßenen Gaswolken alter Sterne.

Typische Merkmale:

- kompakte Form
- starke Emissionslinien
- hohe Oberflächenhelligkeit
- farbige Strukturen

Häufig dominieren:

| Linie | Farbe |
|---|---|
| OIII | blau/grün |
| H-alpha | rot |

---

# 2. Schwierigkeit

Planetarische Nebel sind weniger schwierig wegen ihrer Helligkeit.

Die Herausforderung ist:

- kleine Strukturen erhalten
- Zentralstern sichtbar halten
- Farben nicht zerstören
- Sterne kontrollieren

---

# 3. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 60–180 Sekunden |
| Gain | 40 |
| Lights | 50–150 |
| Darks | 10–20 |
| Filter | optional Dualband |

---

# 4. Belichtungszeit

## 180 Sekunden

Geeignet für:

- schwächere planetarische Nebel
- Außenstrukturen

---

## Kürzere Belichtungen

Zusätzlich sinnvoll für:

- hellen Kern
- Zentralstern
- HDR

Beispiel:

```

50 × 180 Sekunden

*

30 × 30 Sekunden

```id="x9a2pv"

---

# 5. Filterwahl

## Ohne Filter

Vorteile:

- natürliche Farben
- mehr Sterne
- maximale Lichtmenge

---

## Dualband

Sehr sinnvoll.

Grund:

Planetarische Nebel enthalten starke:

- H-alpha
- OIII

Emissionen.

Vorteile:

- höherer Kontrast
- bessere Nebelstrukturen

Nachteile:

- weniger Sterne
- Farbverschiebungen

---

# 6. Vorbereitung in Siril

Ordner:

```

M57/

lights/

darks/

output/

```id="g2yx7m"

---

# 7. Sequenz erzeugen

Ergebnis:

```

m57_light_.seq

```id="6eqx6v"

Prüfen:

- Sterne sichtbar
- Objekt vorhanden
- keine stark verwackelten Frames

---

# 8. Master Dark

Empfehlung:

```

Median

```id="1x3xq4"

---

# 9. Kalibrierung

Aktiv:

## Dark

Ja

---

## Flat

Optional.

Sinnvoll bei:

- Staub
- Vignettierung

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

```id="l0gq1v"

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

# 11. Besonderheit kleiner Objekte

Planetarische Nebel können wenige Pixel groß sein.

Wichtig:

Die Sterne müssen sauber registriert werden.

Nicht:

- Objektzentrum manuell ausrichten
- Bilder nach Auge kombinieren

---

# 12. Stack

Empfehlung:

```

Winsor Sigma

```id="1v6x3h"

Warum:

- entfernt Satelliten
- entfernt Flugzeuge
- schützt vor Ausreißern

---

# Normalisierung

Empfehlung:

```

Additiv

```id="z5p4aw"

---

# RGB-Gewichtung

Empfehlung:

```

aus

```id="j1a8sf"

---

# 13. Hintergrundkorrektur

Vorsichtig.

Planetarische Nebel sind oft klein.

Ein Algorithmus kann sie als Hintergrund interpretieren.

---

# GraXpert

Empfehlung:

- wenige Samples
- keine aggressive Entfernung

Kontrollieren:

Vorher:

```

Nebel vorhanden

```

Nachher:

```

Nebel noch vorhanden?

```id="5qz4pz"

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

```id="rj8d6y"

---

# 15. Farbmanagement

Planetarische Nebel dürfen kräftige Farben zeigen.

Typisch:

M57:

- blau/grün im Inneren
- rötliche Außenbereiche

Nicht überneutralisieren.

---

# 16. Entrauschen

Weniger als bei Galaxien.

Empfehlung:

```

0,03–0,08

```id="hf3p8r"

Warum:

Kleine Details gehen schnell verloren.

---

# 17. Schärfung

Optional.

Sehr vorsichtig.

Geeignet:

- leichte Details
- Strukturverstärkung

Nicht:

- harte Kanten
- künstliche Ränder

---

# 18. HDR Workflow

Viele planetarische Nebel profitieren von zwei Belichtungsreihen.

Beispiel M57:

## Lang

```

180 Sekunden

```id="4px0az"

für:

- Außenbereich

---

## Kurz

```

10–30 Sekunden

```id="u2w7nf"

für:

- hellen Kern
- Zentralstern

---

Kombination:

```

Langbelichtungs-Stack

*

Kurzbelichtungs-Stack

↓

HDR-Komposition

```id="m4w8ck"

---

# 19. Typische Fehler

## Nebel sieht wie Stern aus

Ursache:

zu wenig Integration

Lösung:

mehr Lights sammeln

---

## Kern ausgebrannt

Ursache:

zu langer Stretch

Lösung:

HDR verwenden

---

## Farben verschwinden

Ursache:

zu starke Neutralisierung

Lösung:

PCC prüfen

---

## Hintergrund wird schwarz

Ursache:

zu aggressive Bearbeitung

Lösung:

natürlichen Hintergrund erhalten

---

# 20. Beispielworkflow M57

Aufnahme:

```

80 × 180 Sekunden

Gain 40

Dualband optional

```id="5m2x8r"

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

Stretch

↓

GIMP

```id="k4k3r6"

---

# 21. Qualitätsziel

Eine gute Aufnahme eines planetarischen Nebels:

- zeigt klare Strukturen
- erhält den Zentralbereich
- besitzt natürliche Farben
- hat kontrollierte Sterne
- wirkt nicht überschärft

---

# Kurzfassung

```

60–180 Sekunden

Gain 40

50–150 Lights

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

moderates Stretching

```
```
