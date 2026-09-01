# Kapitel 23 – Siril Fehlerbehebung

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt typische Probleme bei der Verarbeitung von Dwarf-3-Aufnahmen in Siril 1.4.4.

Grundregel:

Nicht jedes schlechte Ergebnis bedeutet, dass die Aufnahme schlecht ist.

Sehr häufig liegt das Problem an:

- falscher Reihenfolge
- falschen Parametern
- zu aggressiver Nachbearbeitung
- falscher Interpretation des Signals

---

# 1. Nach dem Stack ist das Bild komplett grün

## Symptom

Das gestackte Bild erscheint:

- grün
- türkis
- mit falschen Farben

---

## Häufige Ursachen

### Ursache 1

OSC-Debayer falsch.

Prüfen:

```

Sequenz erstellen

↓

Debayer aktiviert?

```

---

### Ursache 2

Keine Farbkalibrierung.

Lösung:

```

PCC durchführen

```

---

### Ursache 3

OIII-lastige Dualbandaufnahme.

Normal:

Bei:

- Herznebel
- Rosettennebel
- Schleiernebel

---

## Lösung Reihenfolge

```

PCC

↓

Green Noise Removal

↓

manuelle Farbkorrektur

```

---

# 2. Nach PCC sind die Farben schlechter

## Symptom

Vor PCC:

- schöne Farben

Nach PCC:

- grau
- blass
- unnatürlich

---

## Ursachen

PCC ist keine automatische Verschönerung.

Es versucht:

- wissenschaftlich korrekte Farben

nicht:

- maximale Ästhetik

---

## Lösung

Nach PCC:

- Sättigung leicht erhöhen
- Kurven anpassen
- lokale Farbkorrektur

---

# 3. Hintergrund ist nach Stretch zu hell

## Symptom

Das Bild wirkt:

- grau
- milchig
- kontrastarm

---

## Ursachen

### Zu viel Stretch

Lösung:

Histogramm zurücknehmen.

---

### Lichtverschmutzung

Lösung:

```

Background Extraction

```

---

### Schwarzpunkt zu hoch

Lösung:

Schwarzpunkt vorsichtiger setzen.

---

# 4. Nebel verschwindet nach Hintergrundkorrektur

## Symptom

Vor GraXpert:

Nebeldetails sichtbar

Nach GraXpert:

Nebelfläche weg

---

## Ursache

Der Algorithmus interpretiert echte Strukturen als Hintergrund.

---

## Lösung

Kontrollpunkte prüfen:

NICHT setzen auf:

- Nebel
- Galaxien
- Staubstrukturen

---

Alternative:

weniger starke Korrektur.

---

# 5. Sterne sind aufgebläht

## Symptom

Sterne wirken:

- groß
- weich
- weiß

---

## Ursachen

### Überbelichtung

Lösung:

kürzere Einzelbelichtung.

---

### Zu viel Stretch

Lösung:

weniger aggressiv stretchen.

---

### Seeing

Nicht immer vermeidbar.

---

# 6. Sterne haben Farbränder

## Symptom

Sterne zeigen:

- rote Ränder
- blaue Ränder

---

## Ursachen

- atmosphärische Dispersion
- Fokus
- Farbkanalverschiebung

---

## Lösung

Prüfen:

- Fokus
- PCC
- Farbkorrektur

---

# 7. Sterne sind nicht rund

## Symptom

Sterne erscheinen:

- oval
- länglich
- verzogen

---

## Ursachen

### Nachführung

häufigste Ursache.

---

### Wind

Stativ/Vibration.

---

### Registrierung

falsche Methode.

---

## Lösung

Frames prüfen:

schlechte Bilder entfernen.

---

# 8. Siril findet keine Sterne bei Registrierung

## Symptom

Fehler:

- keine Sterne erkannt
- Registrierung schlägt fehl

---

## Ursachen

### Zu dunkles Bild

Lösung:

Star Detection Threshold reduzieren.

---

### Zu wenige Sterne

Lösung:

Maximale Sterne erhöhen.

Beispiel:

```

100

↓

500

```

---

### Dualbandfilter

Problem:

weniger sichtbare Sterne.

---

Lösung:

Mindeststerne reduzieren:

```

10

↓

5

```

---

# 9. Stack enthält Streifen oder Artefakte

## Ursachen

- Satelliten
- Flugzeuge
- schlechte Frames
- falscher Stack

---

## Lösung

Verwenden:

```

Winsor Sigma

```

---

Bei wenigen Bildern:

Frames manuell prüfen.

---

# 10. Flats verschlechtern das Bild

## Symptom

Nach Flat-Kalibrierung:

- dunkle Flecken
- Helligkeitsfehler
- unnatürlicher Hintergrund

---

## Ursachen

### Falsche Flats

Beispiele:

- anderer Fokus
- andere Position
- andere Belichtung

---

### Flat falsch erstellt

---

## Lösung

Ohne Flats vergleichen.

Wenn besser:

Flat neu aufnehmen.

---

# 11. Darks machen das Bild schlechter

## Ursachen

Dark passt nicht.

Beispiele:

- andere Temperatur
- andere Belichtung
- anderer Gain

---

Lösung:

Neue Darks erstellen.

---

# 12. Bild ist nach Stretch verrauscht

## Ursachen

Normal bei schwachem Signal.

---

Verbesserungen:

```

mehr Lights

↓

bessere Kalibrierung

↓

vorsichtiges Entrauschen

```

---

Nicht:

Rauschen aggressiv wegfiltern.

---

# 13. Schwache Details verschwinden

## Ursachen

### Zu starke Entrauschung

---

### Hintergrund zu dunkel

---

### GraXpert zu stark

---

### Zu wenig Integration

---

Lösung:

Details schrittweise zurückholen.

---

# 14. Galaxienkern ist ausgebrannt

## Symptom

M31-Kern:

- weiß
- ohne Struktur

---

## Lösung

HDR-Technik:

```

kurze Belichtung

*

lange Belichtung

↓

kombinieren

```

---

# 15. Nebelfarben wirken künstlich

## Ursachen

- Sättigung zu hoch
- falsche Farbkanäle
- aggressive Bearbeitung

---

Lösung:

Zurück zu:

- PCC
- natürlicher Sättigung

---

# 16. Bild ist zu blau

## Häufig bei

- Plejaden
- Reflexionsnebeln

---

Nicht automatisch falsch.

---

Prüfen:

Ist echte Reflexionsfarbe vorhanden?

---

Korrektur:

leicht reduzieren.

Nicht:

komplett neutralisieren.

---

# 17. Bild ist zu rot

## Häufig bei

- H-alpha-Dualband

---

Prüfen:

Ist H-alpha das Ziel?

---

Korrektur:

- Kanäle balancieren
- nicht komplett entfernen

---

# 18. Siril ist langsam

## Ursachen

- viele Lights
- große FITS-Dateien
- wenig RAM

---

Optimierung:

- temporäre Dateien bereinigen
- nur benötigte Sequenzen behalten
- Stack nicht mehrfach neu rechnen

---

# 19. Wann neu aufnehmen?

Neuaufnahme sinnvoll bei:

- falschem Fokus
- starken Wolken
- verzogenen Sternen
- falscher Belichtung
- falschem Filter

---

Nicht neu aufnehmen wegen:

- etwas Rauschen
- hellem Hintergrund
- fehlender Perfektion

Diese Probleme sind meistens Bearbeitungsprobleme.

---

# 20. Allgemeine Diagnose-Reihenfolge

Wenn das Ergebnis schlecht ist:

Immer prüfen:

```

1. Rohbilder

↓

2. Kalibrierung

↓

3. Registrierung

↓

4. Stack

↓

5. Hintergrund

↓

6. Farbe

↓

7. Stretch

↓

8. GIMP

```

---

# 21. Wichtigste Regel

Nicht alles gleichzeitig korrigieren.

Immer nur einen Schritt ändern:

```

Problem erkennen

↓

eine Änderung

↓

prüfen

↓

weitermachen

