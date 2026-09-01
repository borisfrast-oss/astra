# Kapitel 35 – Fehlerdiagnose: Wenn das Astrobild nicht funktioniert

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt eine systematische Fehlersuche.

Grundregel:

Nicht sofort in GIMP korrigieren.

Ein Fehler entsteht meistens in einer früheren Phase:

```

Aufnahme

↓

Kalibrierung

↓

Registrierung

↓

Stack

↓

Farbkorrektur

↓

Stretch

↓

Finalisierung

```

---

# 1. Grundprinzip der Fehlersuche

Wenn ein Bild schlecht aussieht:

Nicht alles gleichzeitig verändern.

Immer rückwärts prüfen:

```

Finales Bild

↓

GIMP

↓

GraXpert

↓

Siril Stretch

↓

Stack

↓

Kalibrierung

↓

Rohdaten

```

---

# 2. Bild ist komplett grün

## Symptom

Das gesamte Bild hat einen starken Grünstich.

---

## Ursache

Typisch bei:

- OSC-Kameras
- fehlender Farbkalibrierung
- falschem Debayering

Dwarf 3 besitzt einen Farbsensor.

Die Rohdaten sind nicht direkt RGB.

---

## Lösung

Reihenfolge:

```

Photometric Color Calibration

↓

Green Noise Removal

```

---

Danach:

erneut prüfen.

---

## Nicht machen

Nicht einfach:

- Sättigung reduzieren
- Grünkanal entfernen

Das zerstört Farbinformation.

---

# 3. Bild ist nach Stack schwarz

## Symptom

Das gestackte Bild sieht fast leer aus.

---

## Ursache

Das Bild ist noch linear.

Astrofotos werden zunächst dunkel gespeichert.

---

## Lösung

Stretch durchführen:

```

Asinh Stretch

↓

Histogram Transformation

```

---

Normal.

Nicht:

noch einmal stacken.

---

# 4. Keine Sterne sichtbar

## Mögliche Ursachen

---

## Ursache 1

Falscher Fokus.

---

Prüfen:

Einzelbild öffnen.

Sterne:

```

Punkte

nicht Scheiben

```

---

## Ursache 2

Belichtung zu kurz.

---

Lösung:

mehr Signal sammeln.

---

## Ursache 3

Falscher Filter.

Beispiel:

Galaxie mit Dualband.

Folge:

zu wenig Licht.

---

# 5. Sterne sind große weiße Kugeln

## Ursache

Zu viel:

- Stretch
- Belichtung
- Schärfung

---

## Lösung

In Siril:

weniger Stretch.

---

In GIMP:

weniger:

- Kontrast
- Schärfung

---

# 6. Hintergrund ist fleckig

## Ursache

Mögliche Gründe:

- Lichtgradienten
- schlechte Flats
- aggressive Bearbeitung

---

## Lösung

Prüfen:

```

Background Extraction

↓

GraXpert

```

---

Nicht:

beide maximal einsetzen.

---

# 7. Nebel verschwindet nach GraXpert

## Ursache

GraXpert hat echte Struktur als Hintergrund interpretiert.

---

Typisch bei:

- Cirrusnebel
- Reflexionsnebeln
- großen diffusen Nebeln

---

## Lösung

Zurück:

```

weniger Punkte

niedrigerer Modellgrad

weniger Stärke

```

---

# 8. Nebel verschwindet nach Stretch

## Ursache

Schwarzpunkt zu aggressiv gesetzt.

---

Folge:

schwache Daten werden abgeschnitten.

---

## Lösung

Histogramm zurücksetzen.

Langsamer stretchen.

---

# 9. Bild ist sehr verrauscht

## Ursachen

---

## Zu wenige Lights

Lösung:

mehr Aufnahmen.

---

## Zu hoher Gain

Lösung:

niedrigerer Gain.

---

## Zu starke Bearbeitung

Beispiele:

- zu viel Kontrast
- zu viel Schärfung
- zu viel Entrauschung

---

# 10. Farben wirken unnatürlich

## Problem

Rot, Grün oder Blau dominieren.

---

## Lösung

Reihenfolge:

```

PCC

↓

Green Noise Removal

↓

leichte Farbkorrektur

```

---

Nicht:

direkt extreme Farbsättigung.

---

# 11. Bild wirkt flach

## Ursache

Zu wenig Kontrast.

---

Lösung:

vorsichtig:

```

Kurven

lokaler Kontrast

leichte Sättigung

```

---

Nicht:

alles dunkler machen.

---

# 12. Bild wirkt künstlich

## Ursachen

- zu viel Stretch
- zu viel Sättigung
- zu starke Schärfung
- schwarzer Hintergrund

---

Lösung:

Eine Version zurückgehen.

---

# 13. Sterne sind verschwommen

## Ursache

Möglicherweise:

- Fokus
- Nachführung
- Registrierung

---

Prüfen:

Einzelbilder vergleichen.

---

Wenn Einzelbilder schlecht:

Stack kann es nicht reparieren.

---

# 14. Satellitenspuren im Bild

## Ursache

Einzelne Lights enthalten Satelliten.

---

## Lösung

Stack-Methode:

```

Winsor Sigma Clipping

```

verwenden.

---

Bei starken Spuren:

Einzelbilder entfernen.

---

# 15. Flugzeuge im Bild

Ähnlich wie Satelliten.

---

Lösung:

- Sigma Clipping
- schlechte Frames aussortieren

---

# 16. Registrierung funktioniert nicht

## Symptom

Sterne sind doppelt.

---

## Ursachen

- zu wenige Sterne
- Wolken
- falscher Modus

---

## Lösung

Prüfen:

```

Deep Sky Registrierung

genügend Sterne

```

---

# 17. Stack sieht schlechter aus als Einzelbilder

## Ursache

Normalerweise:

falscher Workflow.

---

Prüfen:

- wurden Darks korrekt verwendet?
- wurde registriert?
- wurden schlechte Bilder entfernt?

---

Ein Stack sollte:

- weniger Rauschen
- mehr Details

zeigen.

---

# 18. Bild ist unscharf

## Ursachen

- Fokus
- Seeing
- Bewegung
- Wind

---

Software kann schlechte Schärfe nicht vollständig herstellen.

---

# 19. Der Hintergrund ist zu hell

## Ursachen

- Stadtlicht
- Mond
- zu langer Stretch

---

Lösung:

```

GraXpert

↓

Background Extraction

↓

weniger Stretch

```

---

# 20. Das Bild sieht nach GIMP schlechter aus

## Ursache

GIMP verändert nicht die Datenqualität.

Meist:

- Überbearbeitung

---

Prüfen:

Vorher:

Siril TIFF

Nachher:

GIMP Ergebnis

vergleichen.

---

# 21. Entscheidungstabelle

| Problem | Wahrscheinliche Ursache | Lösung |
|---|---|---|
| Grün | Farbkalibrierung | PCC + Green Removal |
| Schwarz | kein Stretch | Asinh/Histogramm |
| Rauschen | zu wenig Daten | mehr Lights |
| Sterne groß | Stretch zu stark | zurücknehmen |
| Nebel weg | Schwarzpunkt/GraXpert | reduzieren |
| Flecken | Gradient/Flat | BE/GraXpert |
| Unscharf | Fokus/Seeing | Aufnahme verbessern |
| Falsche Farben | Farbworkflow | PCC zuerst |

---

# 22. Die wichtigste Regel

Wenn ein Bild nicht gut aussieht:

Nicht mehr bearbeiten.

Erst herausfinden:

```

Wo entsteht der Fehler?

```

---

# 23. Professioneller Diagnoseablauf

Immer diese Reihenfolge:

```

1. Einzelbild prüfen

↓

2. Kalibriertes Bild prüfen

↓

3. Registriertes Bild prüfen

↓

4. Stack prüfen

↓

5. Farbkalibrierung prüfen

↓

6. Stretch prüfen

↓

7. GIMP

