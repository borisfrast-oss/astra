# Workflow 12 – Mond und Planeten

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieser Workflow beschreibt die Verarbeitung von Mond- und Planetenaufnahmen mit dem Dwarf 3 mini.

Beispiele:

- Mond
- Jupiter
- Saturn
- Mars
- Venus
- helle Planetenfelder

Dieser Workflow unterscheidet sich grundlegend von Deep-Sky.

Der Fokus liegt nicht auf:

- langer Integration
- schwachem Signal
- Rauschreduktion

Sondern auf:

- Schärfe
- Detailerhalt
- Kontrast
- kurzer Belichtung

---

# 1. Unterschied zu Deep Sky

Deep Sky:

```

wenig Licht

*

lange Belichtung

*

viele Bilder

```

Planetar:

```

viel Licht

*

kurze Belichtung

*

viele Einzelbilder

```

---

# 2. Aufnahmeprinzip

Planeten sind hell genug, dass der Sensor viele Details in kurzer Zeit aufnehmen kann.

Ziel:

Das Seeing einfrieren.

Seeing bedeutet:

Atmosphärische Unruhe.

Beispiel:

Ein Planet wirkt:

- flimmernd
- verzerrt
- weich

Kurze Belichtungen reduzieren diesen Effekt.

---

# 3. Aufnahmeempfehlung

## Mond

| Parameter | Empfehlung |
|---|---|
| Belichtung | 1–10 ms bis wenige Sekunden |
| Gain | niedrig |
| Lights | viele Einzelbilder |
| Filter | optional |

---

## Planeten

| Parameter | Empfehlung |
|---|---|
| Belichtung | möglichst kurz |
| Gain | moderat |
| Lights | hunderte bis tausende Frames |
| Filter | optional |

---

# 4. Dwarf 3 Besonderheiten

Der Dwarf 3 ist primär für Deep Sky optimiert.

Bei Planeten ist er eingeschränkt gegenüber:

- Planetenkameras
- schnellen CMOS-Kameras
- Videostacking

Trotzdem möglich:

- Mond
- helle Planeten
- große Strukturen

---

# 5. Filter

## Kein Filter

Standard.

Geeignet für:

- Mond
- Jupiter
- Saturn

---

## Farbfilter

Bei spezialisierten Planetenkameras sinnvoll.

Beim Dwarf 3 normalerweise nicht notwendig.

---

## ND-Filter

Kann beim Mond sinnvoll sein.

Ziel:

Überbelichtung verhindern.

---

# 6. Vorbereitung in Siril

Ordner:

```

Jupiter/

lights/

output/

```

---

# 7. Sequenz erzeugen

Ergebnis:

```

jupiter_light_.seq

```

Prüfen:

- scharfes Bild vorhanden
- Planet sichtbar
- keine Verwacklungen

---

# 8. Kalibrierung

Bei Planetenvideos:

Darks meistens nicht notwendig.

Grund:

- kurze Belichtungen
- wenig Dunkelstrom

---

Bei längeren Mondaufnahmen:

Darks optional.

---

# 9. Registrierung

Anderer Ansatz als Deep Sky.

Nicht:

```

Allgemein Deep Sky

```

verwenden.

---

Geeignet:

```

Planetare Registrierung

```

oder:

```

1-Stern-Registrierung

```

(abhängig vom Aufnahmetyp)

---

# 10. Stack

Ziel:

Die besten Frames auswählen.

---

## Methode

Empfehlung:

```

Durchschnitt

```

oder:

```

Median

```

---

Warum?

Bei Planeten:

- viele ähnliche Bilder
- geringe Ausreißer

---

# 11. Auswahl der besten Bilder

Wichtigster Unterschied zu Deep Sky.

Nicht alle Bilder verwenden.

Schlechte Frames entfernen:

- schlechtes Seeing
- Wolken
- Unschärfe

---

Beispiel:

Aufnahmen:

```

1000 Frames

```

verwenden:

```

beste 20–50 %

```

---

# 12. Schärfung

Bei Planeten wichtiger als Entrauschen.

Geeignet:

- Wavelets
- Deconvolution
- lokale Kontraststeigerung

---

Aber:

vorsichtig.

Zu viel erzeugt:

- harte Kanten
- Artefakte
- Rauschringe

---

# 13. Entrauschen

Normalerweise:

sehr wenig.

Empfehlung:

```

0–0,03

```

---

Grund:

Planetendetails sind extrem klein.

---

# 14. Farbkorrektur

PCC ist bei Planeten normalerweise nicht der wichtigste Schritt.

Grund:

- wenige Sterne
- keine gute Referenz

---

Manuell:

- Weißabgleich
- Farbtemperatur

verwenden.

---

# 15. Mondworkflow

Der Mond ist ein Sonderfall.

Ziel:

- Krater
- Berge
- Schatten
- Oberflächenstrukturen

---

Empfehlung:

```

viele Einzelbilder

↓

Stack

↓

Schärfung

↓

Kontrast

↓

Export

```

---

# 16. Typische Fehler Mond

## Mond komplett weiß

Ursache:

Überbelichtung.

Lösung:

- kürzere Belichtung
- geringerer Gain

---

## Krater wirken künstlich

Ursache:

zu starke Schärfung.

Lösung:

weniger Wavelets.

---

## Rauschen in dunklen Bereichen

Ursache:

zu starke Aufhellung.

---

# 17. Jupiter Workflow

Jupiter ist anspruchsvoller.

Ziel:

sichtbar machen:

- Wolkenbänder
- Großer Roter Fleck
- Monde

---

Empfehlung:

```

viele kurze Aufnahmen

↓

beste Frames auswählen

↓

Stack

↓

Schärfen

↓

Farbkorrektur

```

---

# 18. Saturn Workflow

Ziel:

- Ringsystem
- Cassini-Teilung

Benötigt:

- sehr gutes Seeing
- maximale Schärfe

---

# 19. Mars Workflow

Mars ist schwierig.

Grund:

kleine Winkelausdehnung.

Benötigt:

- sehr gute Bedingungen
- kurze Belichtungen
- starke Selektion

---

# 20. Typische Fehler

## Planet ist nur ein heller Punkt

Ursachen:

- Fokus
- falsche Belichtung
- zu geringe Vergrößerung

---

## Planet wirkt weich

Ursachen:

- Seeing
- zu lange Belichtung

---

## Farben falsch

Ursachen:

- Weißabgleich
- automatische Kamerakorrektur

---

# 21. Beispielworkflow Mond

Aufnahme:

```

viele kurze Frames

niedriger Gain

```

Verarbeitung:

```

Sequenz

↓

Registrierung

↓

beste Bilder auswählen

↓

Stack

↓

Schärfung

↓

Kontrast

↓

Export

```

---

# 22. Qualitätsziel

Eine gute Mond-/Planetenaufnahme:

- zeigt echte Oberflächendetails
- besitzt natürliche Farben
- hat keine Schärfungsartefakte
- wirkt nicht künstlich

---

# Kurzfassung

```

kurze Belichtungen

niedriger Gain

viele Frames

↓

Registrierung

↓

beste Bilder auswählen

↓

Stack

↓

Schärfung

↓

leichte Farbkorrektur

```
```
