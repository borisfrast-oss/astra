# Workflow 14 – Kometen

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Kometenaufnahmen mit dem Dwarf 3 mini.

Beispiele:

- Kometen mit sichtbarem Schweif
- kurzperiodische Kometen
- helle Besucher wie C/2023 A3 (Tsuchinshan-ATLAS)

Kometen unterscheiden sich von normalen Deep-Sky-Objekten.

Der wichtigste Unterschied:

Der Komet bewegt sich.

---

# 1. Eigenschaften von Kometen

Ein Komet besteht aus:

- Kern
- Koma
- Staubschweif
- Ionenschweif

Typische Eigenschaften:

- Sterne bleiben stationär
- Komet bewegt sich relativ zum Sternhintergrund
- Helligkeit kann sich stark verändern

---

# 2. Hauptproblem beim Stacken

Bei normalen Deep-Sky-Bildern:

```

Sterne ausrichten

```

Bei Kometen:

```

Komet oder Sterne ausrichten

```

Beides gleichzeitig funktioniert nicht perfekt.

---

# 3. Zwei mögliche Workflows

Es gibt zwei Varianten.

---

# Variante A

## Sterne optimiert

Geeignet wenn:

- Komet nur schwach sichtbar
- Sterne wichtig sind
- Komet kaum Bewegung zeigt

Workflow:

```

Normales Deep-Sky-Stacking

```

---

# Variante B

## Komet optimiert

Empfohlen bei:

- sichtbarem Schweif
- mehreren Stunden Aufnahmen
- schneller Bewegung

Workflow:

```

Komet ausrichten

↓

Komet stacken

↓

Sterne separat bearbeiten

↓

kombinieren

```

---

# 4. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 30–180 Sekunden |
| Gain | 30–40 |
| Lights | 50–200 |
| Darks | 10–20 |
| Filter | abhängig vom Kometen |

---

# 5. Belichtungszeit

Lange Belichtungen:

Vorteile:

- schwacher Schweif sichtbar
- mehr Signal

Nachteile:

- Komet bewegt sich stärker

---

Empfehlung:

Bei schnellen Kometen:

```

30–120 Sekunden

```

Bei langsamen Kometen:

```

120–180 Sekunden

```

---

# 6. Filterwahl

## Kein Filter

Standard.

Vorteile:

- natürliche Farben
- maximale Helligkeit

---

## Dualband

Nur selten sinnvoll.

Kometen enthalten zwar Emissionen, aber meistens dominiert:

- reflektiertes Sonnenlicht
- Staub

---

# 7. Vorbereitung in Siril

Ordner:

```

Komet/

lights/

darks/

output/

```

---

# 8. Sequenz erzeugen

Ergebnis:

```

comet_light_.seq

```

Prüfen:

- Komet in allen Bildern sichtbar
- Sterne nicht verwischt
- keine Wolken

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

Bei Kometen anders.

Nicht immer:

```

Allgemein Deep Sky

```

verwenden.

---

Für Kometen:

```

Kometenregistrierung

```

verwenden.

---

Ziel:

Der Komet bleibt während des Stackings fix.

---

# 12. Stack

## Kometenstack

Empfehlung:

```

Median

```

oder:

```

Winsor Sigma

```

---

Warum:

- entfernt Sterne als Ausreißer
- erhält Kometenstruktur

---

# 13. Sterne entfernen / Sterne separat

Bei langen Serien entstehen oft:

- Sternspuren
- dunkle Bereiche

Lösung:

Zwei Stacks erstellen.

---

## Sternstack

Ausrichtung:

```

Sterne

```

---

## Kometenstack

Ausrichtung:

```

Komet

```

---

Danach:

kombinieren.

---

# 14. Hintergrundkorrektur

Sehr vorsichtig.

Problem:

Der Schweif kann großflächig sein.

GraXpert kann ihn entfernen.

---

Empfehlung:

- Kontrollpunkte weit vom Kometen
- wenige aggressive Korrekturen

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

Kometenfarben:

Typisch:

## Koma

grünlich

durch:

- C2-Emission

---

## Schweif

bläulich

durch:

- ionisierte Gase

---

Nicht übertreiben.

---

# 17. Entrauschen

Empfehlung:

```

0,03–0,08

```

---

Bei schwachen Schweifen:

sehr vorsichtig.

---

# 18. Stretching

Ziel:

sichtbar machen:

- Koma
- Schweif
- Struktur

---

Nicht:

den Hintergrund komplett schwarz machen.

---

# 19. Typische Fehler

## Komet ist verschwunden

Ursache:

Stack auf Sterne statt Komet.

---

## Schweif ist abgeschnitten

Ursache:

GraXpert zu aggressiv.

---

## Sterne sind Striche

Ursache:

Kometenregistrierung verwendet.

---

## Hintergrund fleckig

Ursache:

zu wenig Bilder oder falsche Korrektur.

---

# 20. Beispielworkflow

Aufnahme:

```

100 × 120 Sekunden

Gain 40

kein Filter

```

Verarbeitung:

```

Master Dark

↓

Kalibrierung

↓

Kometenregistrierung

↓

Kometenstack

↓

GraXpert vorsichtig

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

# 21. Qualitätsziel

Eine gute Kometenaufnahme:

- zeigt die Bewegung des Kometen
- erhält den Schweif
- zeigt natürliche Farben
- vermeidet künstliche Artefakte

---

# Kurzfassung

```

30–180 Sekunden

Gain 30–40

50–200 Lights

↓

Kalibrierung

↓

Kometenregistrierung

↓

Kometenstack

↓

sanfte Hintergrundkorrektur

↓

PCC

↓

Stretch

```
```
