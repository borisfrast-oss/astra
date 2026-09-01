# Workflow 17 – Mehrfachbelichtungen und HDR

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Aufnahmen mit unterschiedlichen Belichtungszeiten.

HDR (High Dynamic Range) ist besonders wichtig bei Objekten mit extremen Helligkeitsunterschieden.

Beispiele:

- M42 Orionnebel
- M31 Andromedagalaxie
- Mond mit Terminator
- helle Sterne mit Umgebung
- planetarische Nebel

---

# 1. Warum unterschiedliche Belichtungen?

Ein Sensor kann nur einen begrenzten Helligkeitsbereich aufnehmen.

Problem:

Ein Bild kann entweder:

- schwache Details zeigen

oder:

- helle Bereiche korrekt darstellen

Nicht immer beides gleichzeitig.

---

# Beispiel M42

Eine einzige Aufnahme:

180 Sekunden:

```

Außenbereiche sichtbar

aber

Kern ausgebrannt

```

---

30 Sekunden:

```

Kern korrekt

aber

Außenbereiche schwach

```

---

Lösung:

Beide kombinieren.

---

# 2. Grundprinzip

Nicht:

```

30s + 180s direkt stacken

```

sondern:

```

30s Serie stacken

↓

180s Serie stacken

↓

beide fertigen Bilder kombinieren

```

---

# 3. Warum nicht direkt mischen?

Unterschiedliche Belichtungszeiten haben:

- anderes Signal-Rausch-Verhältnis
- andere Sättigung
- andere Dynamik
- unterschiedliche Sterne

Siril kann solche Reihen nicht sinnvoll als einen normalen Stack behandeln.

---

# 4. Aufnahmeplanung

Empfehlung:

Mindestens zwei Serien.

---

## Kurzbelichtung

Für:

- helle Kerne
- helle Sterne
- Details

Beispiele:

```

5–30 Sekunden

```

---

## Langbelichtung

Für:

- schwache Nebel
- Außenbereiche
- Galaxienhalo

Beispiele:

```

120–180 Sekunden

```

---

# 5. Beispiel M42

Aufnahmen:

## Kurz

```

50 × 15 Sekunden

```

---

## Mittel

```

50 × 60 Sekunden

```

---

## Lang

```

100 × 180 Sekunden

```

---

Ergebnis:

```

Kurzstack

*

Mittelstack

*

Langstack

↓

HDR-Komposition

```

---

# 6. Verarbeitung jeder Serie

Jede Belichtungsreihe wird separat verarbeitet.

Beispiel:

Ordner:

```

M42/

lights_15s/

lights_60s/

lights_180s/

darks/

```

---

Jede Serie:

```

Sequenz erzeugen

↓

Kalibrierung

↓

Registrierung

↓

Stack

```

---

# 7. Siril Workflow für jede Serie

## Sequenz

Erzeugen:

```

lights_xxx.seq

```

---

## Master Dark

Verwenden:

gleiches Temperatur-/Belichtungsprofil.

---

## Kalibrierung

Aktiv:

```

Dark

```

Optional:

```

Flat

```

---

## Registrierung

Verwenden:

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

## Stack

Empfehlung:

```

Winsor Sigma

```

---

# 8. HDR-Zusammenführung

Nach Siril:

Du hast:

```

M42_15s.tif

M42_180s.tif

```

---

Diese werden in GIMP kombiniert.

---

# 9. GIMP HDR-Technik

Grundprinzip:

Langbelichtung:

```

untere Ebene

```

---

Kurzbelichtung:

```

obere Ebene

```

---

Kurzbelichtung mit Ebenenmaske.

---

Maske:

- helle Bereiche sichtbar machen
- ausgebrannte Bereiche ersetzen

---

# 10. Typischer Ablauf in GIMP

1. Langbelichtung öffnen

2. Kurzbelichtung als Ebene hinzufügen

3. Ebenenmaske erstellen

4. Mit weichem Pinsel arbeiten

5. Hellen Kern aus Kurzbelichtung einblenden

---

# 11. Beispiel Andromeda M31

Problem:

Kern:

- sehr hell

Außenhalo:

- extrem schwach

---

Serien:

Lang:

```

100 × 180 Sekunden

```

für:

- Halo
- Staubbänder

---

Kurz:

```

50 × 30 Sekunden

```

für:

- Zentrum

---

Kombination:

```

Halo aus Langstack

*

Kern aus Kurzstack

```

---

# 12. Beispiel Planetarischer Nebel

Problem:

kleiner heller Kern.

---

Serien:

Lang:

```

80 × 180 Sekunden

```

---

Kurz:

```

50 × 10 Sekunden

```

---

Ergebnis:

- Zentralstern erhalten
- Außenstrukturen sichtbar

---

# 13. Farbmanagement

Wichtig:

Alle Teilbilder müssen dieselbe Farbverarbeitung erhalten.

Empfehlung:

Alle Stacks:

```

GraXpert

↓

PCC

↓

gleicher Stretch

```

---

Nicht:

ein Bild extrem anders bearbeiten.

---

# 14. Entrauschen

Nicht vor der Kombination.

Besser:

```

HDR kombinieren

↓

Gesamtbild entrauschen

```

---

Warum:

Sonst entstehen Unterschiede zwischen Ebenen.

---

# 15. Typische Fehler

## Kern bleibt ausgebrannt

Ursache:

Kurzbelichtung nicht verwendet.

---

## Bild wirkt unnatürlich

Ursache:

zu harte Übergänge.

Lösung:

weiche Masken.

---

## Sterne doppelt

Ursache:

Stacks nicht exakt registriert.

Lösung:

vor Kombination beide Bilder exakt ausrichten.

---

## Farben passen nicht

Ursache:

unterschiedliche Bearbeitung.

Lösung:

gleiche Farbkalibrierung.

---

# 16. Qualitätsziel

Eine gute HDR-Aufnahme:

- zeigt helle und schwache Details
- besitzt natürlichen Kontrast
- hat keine sichtbaren Übergänge
- erhält Sternfarben

---

# Kurzfassung

```

Belichtungsreihen getrennt aufnehmen

↓

jede Serie in Siril:

Kalibrieren

↓

Registrieren

↓

Stacken

↓

PCC

↓

Stretch

↓

in GIMP kombinieren

↓

HDR-Maske erstellen

```
```
