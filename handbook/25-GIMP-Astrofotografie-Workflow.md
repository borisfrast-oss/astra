# Kapitel 25 – GIMP Astrofotografie Workflow

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt die finale Bearbeitung der in Siril erzeugten Bilder in GIMP 3.2.4.

Siril liefert:

- kalibriertes Bild
- registriertes Bild
- gestacktes Bild
- farblich korrigiertes Signal

GIMP übernimmt die kreative Endbearbeitung:

- Kontrast
- Farben
- lokale Anpassungen
- Ebenen
- Masken
- Kombinationen

---

# 1. Grundprinzip

Die Aufgabenverteilung:

```

Dwarf 3

↓

Rohdaten

↓

Siril

technische Verarbeitung

↓

GraXpert

Gradienten

↓

GIMP

ästhetische Bearbeitung

```

---

# 2. Export aus Siril

Empfohlen:

```

TIFF 16 Bit

```

---

Nicht verwenden:

```

JPEG

```

Warum:

JPEG entfernt:

- Farbinformationen
- schwache Details
- Dynamikumfang

---

# 3. Bild öffnen

In GIMP:

```

Datei

↓

Öffnen

```

---

Beim Import:

Farbraum prüfen.

Empfehlung:

```

RGB

```

---

# 4. Erste Analyse

Noch nichts verändern.

Prüfen:

- Histogramm
- Hintergrund
- Sterne
- Farben
- Nebelstrukturen

---

Fragen:

## Ist das Signal vorhanden?

Wenn ja:

weiterarbeiten.

---

## Ist der Hintergrund schlecht?

Dann zurück zu:

- Siril
- GraXpert

Nicht alles in GIMP reparieren.

---

# 5. Ebenenstruktur

Empfohlene Struktur:

```

Astrobild

├── Original
│
├── Farbkorrektur
│
├── Kontrast
│
├── Sterne
│
├── Nebel
│
└── Export

```

---

Grundregel:

Nie direkt auf dem Original arbeiten.

---

# 6. Histogramm

Menü:

```

Farben

↓

Werte

```

---

Ziel:

- Schwarzwert setzen
- Dynamik erhöhen

---

## Schwarzwert

Nicht zu weit nach rechts.

Zu viel:

- schwache Nebel verschwinden

---

## Weißpunkt

Nicht Sterne ausbrennen.

---

# 7. Kurven

Menü:

```

Farben

↓

Kurven

```

---

Sehr wichtig für Astrofotografie.

---

Typische Anpassung:

leichte S-Kurve:

```

dunkle Bereiche leicht abdunkeln

helle Bereiche leicht anheben

```

---

Nicht übertreiben.

---

# 8. Farbkorrektur

Menü:

```

Farben

↓

Farbabgleich

```

---

Typische Korrekturen:

## Zu grün

Reduzieren:

- Grün

oder:

- Magenta leicht erhöhen

---

## Zu blau

Bei Reflexionsnebeln:

vorsichtig reduzieren.

---

## Zu rot

Bei H-alpha:

nicht automatisch Fehler.

---

# 9. Sättigung

Menü:

```

Farben

↓

Sättigung

```

---

Empfehlung:

kleine Schritte.

Beispiel:

```

+10 bis +30

```

---

Nicht:

maximale Sättigung.

---

# 10. Sterne bearbeiten

Sterne sind oft der limitierende Faktor.

Probleme:

- zu groß
- zu hell
- überstrahlen Nebel

---

Möglichkeiten:

## Methode 1

Sternreduktion mit Ebenen.

---

## Methode 2

Starless Workflow.

---

# 11. Starless Workflow

Ziel:

Nebel separat bearbeiten.

---

Ablauf:

```

Original

↓

Sternentfernung

↓

Nebelebene

↓

Sternebene

↓

Zusammenführen

```

---

Vorteile:

- mehr Nebelkontrast
- weniger Sternüberstrahlung

---

# 12. Nebel verstärken

Geeignete Werkzeuge:

## Ebenenmodus

```

Weiches Licht

```

oder:

```

Überlagern

```

---

## Masken

Nur Nebelbereiche bearbeiten.

---

Nicht:

gesamtes Bild maximal verstärken.

---

# 13. Lokaler Kontrast

Werkzeuge:

- Klarheit
- Unscharf maskieren
- Hochpass

---

Sehr vorsichtig.

---

Zu viel:

- künstliche Strukturen
- harte Sterne

---

# 14. Entrauschen in GIMP

Nur wenn notwendig.

---

Besser:

erst in Siril.

---

GIMP:

```

Filter

↓

Rauschen

↓

Rauschreduzierung

```

---

Stärke:

gering halten.

---

# 15. Schärfen

Für Deep Sky:

wenig.

---

Geeignet:

```

Unscharf maskieren

```

---

Typische Werte:

Radius:

```

1–3 Pixel

```

Stärke:

```

klein

```

---

Nicht schärfen:

- Hintergrund
- Rauschen

---

# 16. HDR-Technik mit GIMP

Für:

- M42
- helle Galaxienkerne
- Mond

---

Ablauf:

```

Kurze Belichtung öffnen

↓

lange Belichtung als Ebene

↓

Maske erstellen

↓

helle Bereiche kombinieren

```

---

# 17. Mosaike in GIMP

GIMP kann einfache Mosaike erstellen.

---

Ablauf:

```

Datei

↓

Als Ebenen öffnen

↓

Bilder ausrichten

↓

Masken verwenden

↓

zusammenfügen

```

---

Geeignet für:

- große Nebel
- Milchstraße
- Mondpanoramen

---

Bei vielen Einzelbildern:

besser:

- Siril Mosaik
- spezielle Astrosoftware

---

# 18. Collagen erstellen

Für eine Bildsammlung:

Beispiel:

- M31
- M42
- M45
- Mond

---

Ablauf:

```

Neue Datei

↓

Größe wählen

↓

Bilder als Ebenen öffnen

↓

skalieren

↓

positionieren

↓

Text hinzufügen

```

---

# 19. Export

Für Archiv:

```

TIFF 16 Bit

```

---

Für Internet:

```

JPEG

```

---

Empfehlung:

Immer behalten:

```

Master TIFF

*

bearbeitete Version

```

---

# 20. Beispielworkflow Deep Sky

Komplett:

```

Siril TIFF öffnen

↓

Ebenenkopie erstellen

↓

Histogramm

↓

Kurven

↓

Farbe korrigieren

↓

Sättigung leicht erhöhen

↓

Sterne kontrollieren

↓

lokaler Kontrast

↓

Export

```

---

# 21. Beispielworkflow Emissionsnebel

```

Siril TIFF

↓

Farbkorrektur

↓

Sättigung

↓

Nebelebene verstärken

↓

Sterne reduzieren

↓

Kontrast

↓

Export

```

---

# 22. Beispielworkflow Sternfeld

```

Siril TIFF

↓

Farbkorrektur

↓

Sterne leicht schärfen

↓

Kontrast

↓

Export

```

---

# 23. Häufige GIMP-Fehler

## Bild wirkt künstlich

Ursachen:

- zu viel Sättigung
- zu viel Kontrast
- zu stark geschärft

---

## Nebel sieht flach aus

Ursachen:

- Hintergrund zu dunkel
- keine lokale Bearbeitung

---

## Sterne dominieren

Lösung:

- Sternreduzierung
- Nebel separat bearbeiten

---

# 24. Qualitätsziel

Ein gutes finales Astrofoto:

- natürliche Farben
- sichtbare schwache Strukturen
- keine Artefakte
- harmonischer Hintergrund
- kontrollierte Sterne
