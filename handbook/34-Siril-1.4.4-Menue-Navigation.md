# Kapitel 34 – Siril 1.4.4 Menü-Navigation

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel ist ein praktischer UI-Spickzettel für Siril 1.4.4.

Es beantwortet:

- Wo finde ich welchen Schritt?
- Welche Reihenfolge ist sinnvoll?
- Welche Einstellungen sind wichtig?
- Welche Menüpunkte werden häufig benötigt?

---

# 1. Siril Oberfläche verstehen

Siril besteht grundsätzlich aus:

```

Menüleiste

↓

Werkzeugbereiche

↓

Bildanzeige

↓

Statusinformationen

```

---

Die wichtigsten Bereiche:

```

Datei

Sequenz

Bildverarbeitung

Registrierung

Stacking

Analyse

Ansicht

```

---

# 2. Arbeitsordner zuerst setzen

Vor jeder Verarbeitung:

Menü:

```

Datei

↓

Arbeitsverzeichnis wählen

```

---

Empfehlung:

Pro Objekt eigener Ordner.

Beispiel:

```

M31/

├── lights

├── darks

├── flats

└── siril

```

---

Warum?

Siril erzeugt viele Zwischendateien.

Ein sauberer Ordner verhindert Chaos.

---

# 3. Sequenzen erstellen

Menü:

```

Datei

↓

Sequenz erstellen

```

---

Verwendung:

Aus Einzelbildern wird eine Siril-Sequenz.

Beispiel:

```

light_001.fit

light_002.fit

light_003.fit

↓

lights.seq

```

---

Wichtige Einstellungen:

```

Debayer:
aktiv bei Farbkameras

CFA:
automatisch

```

---

Bei Dwarf 3:

Normalerweise:

```

Debayer:
ja

```

---

# 4. Sequenz anzeigen

Menü:

```

Sequenz

↓

Sequenz öffnen

```

---

Hier prüfen:

- Anzahl Bilder
- Qualität
- Ausschussbilder

---

Einzelbilder kontrollieren:

Nicht nur den Stack anschauen.

---

# 5. Kalibrierung

Menü:

```

Bildverarbeitung

↓

Kalibrierung

```

---

Aufgabe:

Korrigiert:

- Hotpixel
- Dunkelstrom
- Vignettierung

---

Benötigt:

## Lights

```

Objektaufnahmen

```

---

## Darks

```

gleiche Belichtung

```

---

## Flats

```

Optische Korrektur

```

---

# 6. Registrierung

Menü:

```

Registrierung

↓

Deep Sky Registrierung

```

---

Aufgabe:

Alle Bilder werden auf dieselbe Sternposition gebracht.

---

Vorher:

```

Bild 1

*

```


```

Bild 2

*

```

---

Nachher:

```

Bild 1

*

Bild 2

*

```

---

Empfohlene Einstellung:

```

Global Star Alignment

Transformation:
Homographie

```

---

# 7. Stacken

Menü:

```

Stacking

↓

Stacken

```

---

Aufgabe:

Viele Bilder werden kombiniert.

---

Empfohlen:

```

Winsorized Sigma Clipping

```

---

Warum?

Entfernt:

- Satelliten
- Flugzeuge
- zufällige Fehler

---

# 8. Normalisierung

Beim Stack wichtig.

---

Empfehlung:

```

Additiv + Skalierung

```

---

Bedeutung:

Passt Bilder an:

- Helligkeit
- Hintergrund

an.

---

# 9. Hintergrund entfernen

Menü:

```

Bildverarbeitung

↓

Background Extraction

```

---

Verwendung:

Entfernt:

- Gradienten
- Lichtverschmutzung

---

Regel:

Punkte nur auf Hintergrund setzen.

---

Nicht auf:

```

Nebel

Galaxien

Sterne

```

---

# 10. Farbkalibrierung

Menü:

```

Bildverarbeitung

↓

Photometric Color Calibration

```

---

Aufgabe:

Automatische Farbkorrektur.

---

Ergebnis:

- realistischere Sterne
- weniger Farbstich

---

Danach:

```

Green Noise Removal

```

---

# 11. Stretch

Menü:

```

Bildverarbeitung

↓

Histogramm Transformation

```

---

Aufgabe:

Lineares Bild sichtbar machen.

---

Empfehlung:

Erst:

```

Asinh Transformation

```

---

Dann:

```

Histogramm

```

---

Dann:

```

Kurven

```

---

# 12. Farbkanäle anzeigen

Menü:

```

Ansicht

↓

Kanäle

```

---

Hilfreich bei:

- Grünproblemen
- Farbstichen
- Dualband

---

# 13. Schwarzpunkt kontrollieren

Werkzeug:

```

Histogramm

```

---

Nicht machen:

Schwarzpunkt zu weit verschieben.

---

Folge:

schwache Nebelstrukturen verschwinden.

---

# 14. Bild speichern

Menü:

```

Datei

↓

Speichern unter

```

---

Für Archiv:

```

FITS

```

---

Für GIMP:

```

TIFF 16 Bit

```

---

# 15. Häufige Siril-Fehler

---

# Problem:

Bild nach Stack grün

---

Ursache:

OSC-Farbkalibrierung.

---

Lösung:

```

PCC

↓

Green Noise Removal

```

---

# Problem:

Bild fast schwarz

---

Ursache:

Linearbild.

---

Lösung:

```

Stretch durchführen

```

---

# Problem:

Sterne sehen verschoben aus

---

Ursache:

Registrierung fehlerhaft.

---

Prüfen:

- genügend Sterne
- richtige Methode
- schlechte Einzelbilder entfernen

---

# Problem:

Nebeldetails verschwinden

---

Ursachen:

- zu starker Hintergrundabzug
- zu aggressiver Stretch

---

Lösung:

weniger Bearbeitung.

---

# 16. Minimaler Menüpfad

Der komplette Standardpfad:

```

Datei

↓

Arbeitsverzeichnis

↓

Sequenz erstellen

↓

Kalibrieren

↓

Registrieren

↓

Stacken

↓

Background Extraction

↓

Photometric Color Calibration

↓

Green Noise Removal

↓

Asinh Stretch

↓

Histogramm

↓

Speichern TIFF

```

---

# 17. Die wichtigsten Siril-Funktionen als Tabelle

| Funktion | Zweck |
|---|---|
| Sequenz erstellen | Einzelbilder gruppieren |
| Kalibrierung | Fehler entfernen |
| Registrierung | Bilder ausrichten |
| Stack | Bilder kombinieren |
| Normalisierung | Helligkeit angleichen |
| Background Extraction | Gradienten entfernen |
| PCC | Farben korrigieren |
| Green Noise Removal | Grünstich entfernen |
| Stretch | Signal sichtbar machen |
| Export TIFF | Übergabe an GIMP |

---

# 18. Dwarf-3 Anfängerregel

Wenn du nicht weißt, was du ändern sollst:

Nicht zehn Parameter verändern.

Immer diese Reihenfolge:

```

Rohdaten prüfen

↓

Kalibrierung prüfen

↓

Stack prüfen

↓

Farbe korrigieren

↓

Stretch

