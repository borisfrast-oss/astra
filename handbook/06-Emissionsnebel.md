# Workflow 06 – Emissionsnebel

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Emissionsnebeln mit dem Dwarf 3 mini.

Beispiele:

- M42 Orionnebel
- NGC 7000 Nordamerikanebel
- IC 434 Pferdekopfnebel
- Rosettennebel
- Lagunennebel M8
- Schwanennebel M17

Emissionsnebel gehören zu den spektakulärsten Deep-Sky-Objekten.

Sie unterscheiden sich von Galaxien:

- sie sind flächiger
- sie enthalten Gasstrukturen
- sie reagieren stark auf Filter
- Farben sind ein wesentlicher Bestandteil

---

# 1. Eigenschaften von Emissionsnebeln

Emissionsnebel leuchten durch ionisiertes Gas.

Wichtige Emissionen:

| Linie | Farbe | Ursprung |
|---|---|---|
| H-alpha | Rot | Wasserstoff |
| OIII | Blaugrün | Sauerstoff |
| SII | Rot | Schwefel |

Ein normaler Farbsensor kann diese Bereiche aufnehmen.

Ein Dualband-Filter kann den Kontrast erhöhen.

---

# 2. Aufnahmeempfehlung

## Ohne Filter

| Parameter | Empfehlung |
|---|---|
| Belichtung | 180 Sekunden |
| Gain | 40 |
| Lights | 50–100+ |
| Darks | 10–20 |

---

## Mit Dualband-Filter

Empfehlung:

| Parameter | Wert |
|---|---|
| Belichtung | 180 Sekunden |
| Gain | 40 |
| Lights | möglichst viele |
| Darks | passend zur Belichtung |

---

# 3. Filterwahl

## Kein Filter

Vorteile:

- natürliche Farben
- mehr Sterne
- mehr Gesamtsignal

Geeignet:

- dunkler Himmel
- helle Nebel

---

## Dualband-Filter

Vorteile:

- bessere Nebelstrukturen
- weniger Lichtverschmutzung
- stärkerer Kontrast

Nachteile:

- weniger Sterne
- veränderte Farben
- längere Belichtung notwendig

---

# 4. Aufnahmeplanung

Emissionsnebel profitieren stark von vielen Einzelbildern.

Empfehlung:

Minimum:

```

30 Bilder

```

Besser:

```

60–100 Bilder

```

---

# 5. Vorbereitung in Siril

Ordner:

```

NGC7000/

lights/

darks/

output/

```

---

# 6. Sequenz erzeugen

Ergebnis:

```

ngc7000_light_.seq

```

Kontrolle:

- alle Bilder vorhanden
- keine Wolkenbilder
- Fokus ausreichend

---

# 7. Master Dark

## Methode

Empfehlung:

```

Median

```

Grund:

- entfernt Zufallsrauschen
- erhält Sensormuster

---

# 8. Kalibrierung

Aktivieren:

## Dark

Ja

---

## Flat

Optional.

Sinnvoll bei:

- Staub
- Vignettierung
- Filterwechsel

---

## Bias

Normalerweise:

Nein

---

# 9. Registrierung

Menü:

Registrierung

---

## Auswahl

Verwenden:

```

Allgemein Deep Sky

```

---

## Parameter

| Parameter | Wert |
|---|---|
| Transformation | Homographie |
| Mindest Sternpaare | 10 |
| Luminanz | aktiv |
| Maximale Sterne | 500 |
| Entzerrung | aus |

---

# 10. Besonderheit bei Nebeln

Nebelflächen enthalten weniger scharfe Strukturen als Galaxien.

Die Sternregistrierung kann schwieriger sein.

Bei Problemen:

- mehr Sterne zulassen
- Mindeststernpaare reduzieren
- schlechte Bilder entfernen

---

# 11. Stack

Empfehlung:

```

Winsor Sigma

```

Warum:

- entfernt Satelliten
- entfernt Flugzeuge
- reduziert Ausreißer

---

# Normalisierung

Empfehlung:

```

Additiv

```

Bei identischen Dwarf-Aufnahmen ausreichend.

---

# RGB-Gewichtung

Empfehlung:

```

aus

```

Grund:

PCC übernimmt später die Farbkorrektur.

---

# 12. Hintergrundkorrektur

Emissionsnebel reagieren empfindlich auf falsche Hintergrundkorrektur.

Empfehlung:

GraXpert vorsichtig verwenden.

---

# Gefahr

Zu aggressive Hintergrundentfernung kann entfernen:

- schwache Nebelbereiche
- Halos
- diffuse Strukturen

---

# 13. GraXpert-Empfehlung

Start:

- wenige Samples
- sanfte Korrektur

Kontrollieren:

Vorher:

```

Nebel + Hintergrund

```

Nachher:

```

Nebel erhalten?

```

---

# 14. PCC Farbkalibrierung

Nach Hintergrundkorrektur.

Ablauf:

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

# 15. Dualband-Farbprobleme

Typisch:

- sehr rote Bilder
- grünliche Sterne
- wenige Sterne

Das ist normal.

Nicht sofort korrigieren.

---

# 16. Sterne bei Dualband

Dualband reduziert häufig Sternsignal.

Mögliche Lösung:

Separate Aufnahme:

```

RGB ohne Filter

*

Dualband Nebelbild

```

kombinieren.

---

# 17. Entrauschen

Bei Nebeln vorsichtig.

Empfehlung:

```

0,05

```

bis:

```

0,1

```

---

Nicht:

```

starkes Entrauschen

```

Warum?

Diffuse Strukturen sind empfindlich.

---

# 18. Stretching

Ziel:

sichtbar machen:

- Gasstrukturen
- Farbverläufe
- feine Details

---

Empfehlung:

Mehrere kleine Schritte.

Nicht:

```

maximaler Stretch

```

---

# 19. Typische Fehler

## Nebel verschwindet nach GraXpert

Ursache:

zu starke Hintergrundkorrektur

Lösung:

weniger aggressiv korrigieren

---

## Bild zu rot

Ursachen:

- H-alpha dominant
- Dualband
- falsches Stretching

Lösung:

PCC und vorsichtige Farbkorrektur

---

## Sterne grün

Ursache:

Bayer-Farbverarbeitung

Lösung:

PCC danach optional SCNR

---

## Zu wenig Nebel sichtbar

Ursachen:

- zu wenig Integration
- zu kurze Belichtung
- heller Himmel

Lösung:

mehr Lights sammeln

---

# 20. Beispielworkflow M42

Aufnahme:

```

50 × 180 Sekunden
Gain 40

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

GraXpert

↓

PCC

↓

leichtes Entrauschen

↓

Stretch

↓

GIMP

```

---

# 21. HDR bei hellen Nebeln

Bei M42 sinnvoll.

Problem:

Der Kern ist sehr hell.

Lösung:

Zwei Aufnahmeserien:

Lang:

```

180 Sekunden

```

für:

- Außennebel

Kurz:

```

10–30 Sekunden

```

für:

- Kernbereich

Danach:

```

Langbelichtung als Hauptbild

*

Kurzbelichtung als Kern

```

kombinieren.

---

# 22. Qualitätsziel

Eine gute Emissionsnebelaufnahme:

- zeigt feine Gasstrukturen
- behält natürliche Farben
- hat keinen künstlich schwarzen Hintergrund
- enthält Sterne mit natürlicher Größe
- zeigt Details ohne Überschärfung

---

# Kurzfassung

```

180 Sekunden

Gain 40

50–100 Lights

10–20 Darks

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

moderates Stretching

```
```
