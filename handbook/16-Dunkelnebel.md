# Workflow 16 – Dunkelnebel

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Dunkelnebeln mit dem Dwarf 3 mini.

Beispiele:

- Pferdekopfnebel Barnard 33 (mit IC 434 Hintergrund)
- Barnard 86
- Dunkelwolken im Rho-Ophiuchi-Komplex
- Coalsack-Nebel
- Barnard-Objekte

Dunkelnebel gehören zu den schwierigsten Objekten der Astrofotografie.

Der Grund:

Sie leuchten nicht selbst.

---

# 1. Eigenschaften von Dunkelnebeln

Dunkelnebel bestehen aus:

- kaltem interstellarem Staub
- dichten Molekülwolken
- Bereichen mit Sternentstehung

Sie werden sichtbar, weil sie:

- Licht dahinter blockieren
- Sterne verdecken
- vor helleren Nebeln liegen

---

# 2. Hauptziel der Bearbeitung

Bei Dunkelnebeln geht es um:

- Kontrast
- Hintergrundkontrolle
- Erhalt subtiler Strukturen

Nicht:

- maximale Helligkeit
- aggressive Kontraststeigerung

---

# 3. Warum Dunkelnebel schwierig sind

Das Signal ist indirekt.

Ein Emissionsnebel:

```

Nebel = Signal

```

Ein Dunkelnebel:

```

Hintergrundlicht - Staub = Struktur

```

Dadurch können Algorithmen die Struktur leicht entfernen.

---

# 4. Aufnahmeempfehlung

## Standard Dwarf 3

| Parameter | Empfehlung |
|---|---|
| Belichtung | 120–180 Sekunden |
| Gain | 30–40 |
| Lights | 100–300 |
| Darks | 10–20 |
| Filter | kein Filter bevorzugt |

---

# 5. Anzahl der Bilder

Dunkelnebel profitieren extrem von Integration.

Minimum:

```

50 Lights

```

Besser:

```

100–200 Lights

```

Sehr schwache Strukturen:

```

300+

```

---

# 6. Filterwahl

## Kein Filter

Meist beste Wahl.

Warum:

Dunkelnebel benötigen:

- Sternlicht
- Hintergrundnebel
- natürliche Farben

---

## Dualband

Nicht empfohlen.

Grund:

Dualband reduziert:

- Hintergrundlicht
- Sternfarben

Ausnahme:

Wenn der Dunkelnebel vor einem Emissionsnebel liegt.

Beispiel:

```

Pferdekopfnebel

Dunkelnebel

*

IC 434 Emission

```

---

# 7. Vorbereitung in Siril

Ordner:

```

Barnard/

lights/

darks/

output/

```

---

# 8. Sequenz erzeugen

Ergebnis:

```

darknebula_light_.seq

```

Prüfen:

- Sterne sichtbar
- Hintergrund vorhanden
- keine starken Gradienten

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

Sehr empfohlen.

Warum:

Dunkle Strukturen reagieren stark auf:

- Vignettierung
- Staubflecken
- Helligkeitsunterschiede

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

# 12. Stack

Empfehlung:

```

Winsor Sigma

```

Warum:

- entfernt Satelliten
- reduziert Rauschen
- erhält schwache Sterne

---

# Normalisierung

Empfehlung:

```

Additiv + Skalierung

```

---

# RGB-Gewichtung

Empfehlung:

```

aus

```

---

# 13. Hintergrundkorrektur

Der kritischste Schritt.

Problem:

Der Dunkelnebel ist oft großflächig.

Ein Algorithmus kann ihn als Gradient interpretieren.

---

# GraXpert

Sehr vorsichtig verwenden.

Empfehlung:

- wenige Samples
- nur auf echten Hintergrundbereichen
- nicht auf Staubstrukturen

---

Kontrolle:

Vorher:

```

Dunkle Struktur sichtbar

```

Nachher:

```

Dunkle Struktur noch vorhanden

```

---

# 14. PCC

Nach Hintergrundkorrektur:

Workflow:

```

Stack

↓

GraXpert vorsichtig

↓

PCC

↓

Stretch

```

---

# 15. Farbmanagement

Dunkelnebel sind nicht einfach schwarz.

Typisch:

- brauner Staub
- rötliche Hintergrundnebel
- blaue Reflexionsbereiche

Nicht:

komplett auf Schwarz ziehen.

---

# 16. Entrauschen

Sehr vorsichtig.

Empfehlung:

```

0,02–0,06

```

Warum:

Staubstrukturen haben sehr geringe Kontraste.

---

# 17. Stretching

Der wichtigste kreative Schritt.

Ziel:

Den Kontrast zwischen:

- Hintergrund
- Staub
- Sternen

sichtbar machen.

---

Empfehlung:

Sehr langsam:

```

kleiner Stretch

↓

prüfen

↓

kleiner Stretch

```

---

# 18. Kontrastanhebung

Optional.

Geeignet:

- lokale Kontrastverstärkung
- Kurven in GIMP

Nicht:

global extrem erhöhen.

---

# 19. Typische Fehler

## Dunkelnebel verschwindet

Ursache:

GraXpert zu aggressiv.

Lösung:

weniger Hintergrundkorrektur.

---

## Hintergrund wird schwarz

Ursache:

zu starkes Stretching.

Lösung:

natürlichen Himmel erhalten.

---

## Bild wirkt flach

Ursache:

zu wenig Kontrast zwischen Staub und Hintergrund.

Lösung:

sanfte Kurvenanpassung.

---

## Sterne wirken künstlich

Ursache:

zu starke Schärfung.

---

# 20. Beispielworkflow Pferdekopfregion

Aufnahme:

```

150 × 180 Sekunden

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

GraXpert sehr vorsichtig

↓

PCC

↓

leichtes Entrauschen

↓

langsames Stretching

↓

GIMP Kontrast/Kurven

```

---

# 21. Qualitätsziel

Eine gute Dunkelnebelaufnahme:

- zeigt subtile Staubstrukturen
- besitzt einen natürlichen Hintergrund
- erhält Sternfarben
- wirkt nicht künstlich schwarz

---

# Kurzfassung

```

120–180 Sekunden

Gain 30–40

100–300 Lights

kein Filter

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma

↓

sehr vorsichtige Hintergrundkorrektur

↓

PCC

↓

minimales Entrauschen

↓

langsames Stretching

```
```
