# Workflow 05 – Galaxien

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Galaxienaufnahmen mit dem Dwarf 3 mini.

Beispiele:

- M31 Andromedagalaxie
- M33 Dreiecksgalaxie
- M81/M82 Gruppe
- M51 Whirlpoolgalaxie
- M101 Feuerradgalaxie
- NGC 4565

Galaxien gehören zu den klassischen Deep-Sky-Zielen.

Sie sind anspruchsvoller als Nebel, weil:

- der Kontrast niedrig ist
- der Hintergrund wichtig ist
- feine Strukturen geschützt werden müssen

---

# 1. Eigenschaften von Galaxien

Galaxien enthalten:

- Sterne
- Staubwolken
- Sternentstehungsgebiete
- zentrale Bulges
- Spiralarme

Typische Herausforderung:

Das schwache Signal der Außenbereiche gegen den dunklen Himmel sichtbar machen.

---

# 2. Hauptziel der Bearbeitung

Bei Galaxien:

Erhalten:

- Spiralarme
- Staubbänder
- Farbverläufe
- natürliche Sterne

Vermeiden:

- künstlich schwarzer Hintergrund
- übertriebene Farben
- verlorene Außenbereiche

---

# 3. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 120–180 Sekunden |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | kein Filter |

---

# 4. Belichtungszeit

## 180 Sekunden

Empfohlen für:

- dunklen Himmel
- schwache Außenbereiche
- Galaxienhalo

---

## 60–120 Sekunden

Sinnvoll bei:

- hellem Himmel
- hellem Zentrum

---

# 5. Anzahl der Bilder

Galaxien profitieren stark von Integration.

Minimum:

```

30 Lights

```

Gut:

```

50–100 Lights

```

Sehr gut:

```

150+

```

---

# 6. Filterwahl

## Kein Filter

Standard.

Warum:

Galaxien enthalten breitbandiges Licht.

Ein Filter reduziert:

- Sternfarben
- Galaxiensignal

---

## Dualband

Nicht empfohlen.

Ausnahme:

Wenn zusätzlich enthalten:

- H-II-Regionen
- Emissionsgebiete

Beispiel:

M31 mit H-II-Regionen.

---

# 7. Vorbereitung in Siril

Ordner:

```

M31/

lights/

darks/

output/

```

---

# 8. Sequenz erzeugen

Ergebnis:

```

m31_light_.seq

```

Prüfen:

- alle Bilder vorhanden
- Galaxie sichtbar
- keine schlechten Frames

---

# 9. Master Dark

Empfehlung:

```

Median

```

Warum:

- entfernt Hotpixel
- reduziert Sensormuster

---

# 10. Kalibrierung

## Dark

Ja

---

## Flat

Empfohlen wenn verfügbar.

Hilft bei:

- Vignettierung
- Staub
- ungleichmäßiger Ausleuchtung

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

# 12. Besonderheit Galaxien

Galaxien enthalten weniger Sterne als Sternfelder.

Probleme:

- wenige Referenzsterne
- schwache Außenbereiche

---

Bei Problemen:

Mindest Sternpaare reduzieren:

Standard:

```

10

```

Alternative:

```

5

```

---

# 13. Stack

Empfehlung:

```

Winsor Sigma

```

Warum:

- entfernt Satelliten
- entfernt Flugzeuge
- schützt schwache Details

---

# Normalisierung

Empfehlung:

```

Additiv + Skalierung

```

Bei unterschiedlichen Bedingungen:

```

Additiv + Multiplikativ

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

Einer der wichtigsten Schritte.

Galaxien liegen oft vor einem ungleichmäßigen Himmel.

Ursachen:

- Lichtverschmutzung
- Mond
- Sensorgradienten

---

# GraXpert

Sehr gut geeignet.

Aber:

Die Galaxie darf nicht als Gradient entfernt werden.

---

Empfehlung:

- viele Kontrollpunkte außerhalb der Galaxie
- keine Punkte direkt auf der Galaxie

---

# 15. Typischer M31 Fehler

Andromeda ist sehr groß.

Problem:

GraXpert erkennt den äußeren Halo eventuell als Hintergrund.

Folge:

Der Halo verschwindet.

---

Lösung:

- weniger aggressive Korrektur
- Galaxiezentrum schützen
- Kontrolle vor/nachher

---

# 16. PCC

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

# 17. Farbmanagement

Galaxien haben natürliche Farben.

Typisch:

## Kern

gelblich

wegen:

- alten Sternen

---

## Spiralarme

bläulich

wegen:

- jungen Sternen

---

## Staubbänder

dunkel

---

Nicht:

zu blau oder zu bunt machen.

---

# 18. Entrauschen

Galaxien sind empfindlich.

Empfehlung:

```

0,03–0,08

```

---

Nicht:

```

0,1+

```

ohne Kontrolle.

Warum:

- Staubbänder verschwinden
- Halo verliert Struktur

---

# 19. Stretching

Der wichtigste kreative Schritt.

Ziel:

- Galaxie sichtbar machen
- Hintergrund erhalten

---

Empfehlung:

Viele kleine Schritte.

```

Stretch

↓

prüfen

↓

Stretch

↓

prüfen

```

---

# 20. Kernkontrolle

Viele Galaxien haben einen hellen Kern.

Problem:

Kern brennt aus.

---

Lösung:

HDR:

Kurze Serie:

```

10–30 Sekunden

```

+

lange Serie:

```

180 Sekunden

```

---

# 21. Schärfung

Optional.

Geeignet:

- leichte Strukturverstärkung

Nicht:

starke Schärfung.

Problem:

- dunkle Ränder
- künstliche Details

---

# 22. Typische Fehler

## Galaxie verschwindet nach GraXpert

Ursache:

zu aggressive Hintergrundkorrektur.

---

## Bild wird grau

Ursache:

zu starke Neutralisierung.

---

## Nur Kern sichtbar

Ursache:

zu wenig Integration oder zu wenig Stretch.

---

## Sterne werden riesig

Ursache:

zu viel Entrauschen oder Schärfen.

---

# 23. Beispielworkflow M31

Aufnahme:

```

80 × 180 Sekunden

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

leichtes Entrauschen

↓

langsames Stretching

↓

GIMP

```

---

# 24. Qualitätsziel

Eine gute Galaxienaufnahme:

- zeigt Struktur
- erhält natürliche Farben
- zeigt schwache Außenbereiche
- besitzt einen natürlichen Hintergrund
- enthält keine künstlichen Artefakte

---

# Kurzfassung

```

120–180 Sekunden

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

moderates Entrauschen

↓

langsames Stretching
