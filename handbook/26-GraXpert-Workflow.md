# Kapitel 26 – GraXpert Workflow

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt den Einsatz von GraXpert in einem Dwarf-3-Astrofotografie-Workflow.

GraXpert ist kein allgemeines Bildbearbeitungsprogramm.

Die Hauptaufgabe:

**künstliche Hintergrundgradienten entfernen, ohne astronomisches Signal zu zerstören.**

---

# 1. Rolle von GraXpert im Workflow

Empfohlene Reihenfolge:

```

Dwarf 3

↓

Siril

Kalibrierung

Registrierung

Stack

Farbkorrektur

↓

GraXpert

Gradienten entfernen

↓

GIMP

Finale Bearbeitung

```

---

# 2. Wann GraXpert verwenden?

Sinnvoll bei:

- Lichtverschmutzung
- ungleichmäßigem Hintergrund
- Vignettierung
- Mondlicht
- Aufnahmen in Städten

---

Besonders hilfreich:

- Galaxien
- schwache Nebel
- Milchstraße
- große Sternfelder

---

# 3. Wann vorsichtig sein?

Problematisch bei:

- großen Reflexionsnebeln
- sehr schwachen Nebeln
- großen diffusen Strukturen

Beispiele:

- M45 Plejaden
- Irisnebel
- Cirrusnebel

---

Grund:

GraXpert erkennt Nebel nicht immer als Objekt.

Es kann echte Strukturen als Hintergrund interpretieren.

---

# 4. Vorbereitung

Vor GraXpert:

Das Bild sollte bereits:

- kalibriert
- registriert
- gestackt

sein.

Empfohlener Zustand:

```

Linear oder leicht gestreckt

```id="6rm2bw"

---

Nicht ideal:

stark bearbeitetes JPEG.

---

# 5. Export aus Siril

Empfehlung:

```

TIFF 16 Bit

```id="7v0a3f"

oder:

```

FITS

```id="8d0v4e"

---

Für maximale Datenqualität:

FITS bevorzugt.

---

# 6. Modellwahl

GraXpert verwendet ein mathematisches Modell des Hintergrunds.

---

# 6.1 Einfacher Hintergrund

Geeignet:

- kleine Gradienten
- leichte Lichtverschmutzung

Empfehlung:

```

Degree 1

```id="7c2q9f"

---

# 6.2 Komplexer Hintergrund

Geeignet:

- Stadtlicht
- Mondgradient
- starke Unterschiede

Empfehlung:

```

Degree 2

```id="0y3c5b"

---

Höhere Grade:

nur verwenden, wenn notwendig.

---

# 7. Hintergrundpunkte setzen

Das ist der wichtigste Schritt.

---

Regel:

Punkte nur setzen auf:

```

echten Hintergrund

```id="a6m9tv"

---

Nicht setzen auf:

- Sterne
- Nebel
- Galaxien
- helle Strukturen

---

# 8. Beispiel M31

Richtig:

Punkte:

- dunkle Bereiche außerhalb der Galaxie

Falsch:

- Spiralarme
- Kernbereich

---

# 9. Beispiel Emissionsnebel

Problem:

Der Nebel kann große Teile des Bildes bedecken.

---

Regel:

Sehr wenige Punkte.

Nicht:

den gesamten Nebel als Hintergrund behandeln.

---

# 10. Beispiel M45 Plejaden

Besonders schwierig.

Der blaue Reflexionsnebel ist großflächig.

---

Empfehlung:

- wenig Korrektur
- nur offensichtliche Gradienten entfernen

---

# 11. Stärke der Korrektur

Grundregel:

So wenig wie möglich.

---

Zu stark:

Folgen:

- Nebel verschwindet
- Farbverläufe werden unnatürlich
- Hintergrund wirkt künstlich

---

Gut:

Der Unterschied ist sichtbar, aber nicht dramatisch.

---

# 12. AI-Denoise in GraXpert

GraXpert besitzt auch Entrauschung.

---

Empfehlung:

Bei Dwarf-Daten vorsichtig.

---

Warum:

Kleine Sensoren erzeugen feine Strukturen, die ähnlich aussehen können wie Rauschen.

---

Zu stark:

entfernt:

- Nebelfilamente
- schwache Sterne
- Staubstrukturen

---

# 13. Vergleich vor/nach GraXpert

Immer prüfen:

Vorher:

- Wo ist Signal?

Nachher:

- Ist Signal noch vorhanden?

---

Nicht nur auf schönen Hintergrund achten.

---

# 14. Typische Probleme

---

## Problem: Nebel wurde entfernt

Ursachen:

- zu viele Punkte
- falsche Punkte
- Modell zu komplex

Lösung:

- weniger Punkte
- niedrigerer Grad
- Original vergleichen

---

## Problem: Hintergrund ist fleckig

Ursachen:

- zu wenige Punkte
- falsches Modell

Lösung:

- mehr gleichmäßig verteilte Hintergrundpunkte

---

## Problem: Sterne wirken verändert

Ursachen:

- falsche Anwendung auf stark gestrecktes Bild

Lösung:

- vor Stretch anwenden

---

# 15. Empfohlener Workflow nach Objektklasse

---

## Galaxien

```

Siril Stack

↓

Background Extraction

↓

PCC

↓

GraXpert

↓

GIMP

```

---

## Emissionsnebel

```

Siril Stack

↓

GraXpert vorsichtig

↓

PCC

↓

GIMP

```

---

## Reflexionsnebel

```

Siril Stack

↓

sehr vorsichtig GraXpert

↓

PCC

↓

GIMP

```

---

## Milchstraße

```

Siril Stack

↓

GraXpert

↓

PCC

↓

GIMP

```

---

# 16. Siril Background Extraction vs GraXpert

Beide machen ähnliche Dinge.

---

## Siril Background Extraction

Vorteile:

- integriert
- schnell
- ausreichend für viele Fälle

---

## GraXpert

Vorteile:

- oft bessere Gradientenerkennung
- einfacher zu kontrollieren
- besonders gut bei komplexen Gradienten

---

Empfehlung:

Nicht immer beide maximal verwenden.

---

# 17. Kombinationsregel

Nicht:

```

Siril aggressiv

*

GraXpert aggressiv

*

GIMP Kontrast extrem

```

---

Besser:

```

Siril leicht

↓

GraXpert leicht

↓

GIMP kontrolliert

```

---

# 18. Qualitätskontrolle

Nach GraXpert prüfen:

- Sind Nebelfilamente noch vorhanden?
- Sind Sterne unverändert?
- Ist der Hintergrund natürlicher?
- Gibt es neue Artefakte?

---

# 19. Standard Dwarf-3 GraXpert Einstellungen

Ausgangspunkt:

```

Modell:
Degree 1–2

Stärke:
moderat

Punkte:
nur Hintergrund

Denoise:
niedrig oder aus

```

---

# 20. Wichtigste Regel

GraXpert soll den Hintergrund verbessern.

Es soll nicht das Bild verändern.

Wenn der Unterschied zwischen vorher und nachher extrem ist:

war die Korrektur wahrscheinlich zu stark.

