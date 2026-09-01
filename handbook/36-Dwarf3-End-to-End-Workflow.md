# Kapitel 36 – Dwarf 3 Langzeit-Workflow: Von der ersten Aufnahme bis zum fertigen Archivbild

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt den vollständigen Ablauf einer Astrofotografie-Session.

Vom Moment der Planung:

```

"Ich möchte M31 fotografieren"

```

bis zum fertigen Archivbild:

```

M31_final.xcf

*

M31_final.tif

*

M31_final.jpg

```

---

# 1. Übersicht Gesamtworkflow

Der komplette Prozess:

```

Planung

↓

Aufnahme mit Dwarf 3

↓

Daten sichern

↓

Siril Verarbeitung

↓

Gradienten entfernen

↓

Farbkorrektur

↓

Stretch

↓

GIMP Bearbeitung

↓

Export

↓

Archivierung

```

---

# 2. Phase 1 – Objektplanung

Vor der Aufnahme klären:

## Objekt

Beispiel:

```

M31 Andromedagalaxie

```

---

## Bedingungen

Prüfen:

- sichtbar?
- Höhe über Horizont?
- Mond?
- Lichtverschmutzung?

---

## Aufnahmeplan

Beispiel:

```

Objekt:
M31

Belichtung:
180 Sekunden

Gain:
35

Filter:
kein Filter

Ziel:
200 Lights

```

---

# 3. Phase 2 – Dwarf 3 Vorbereitung

Vor dem Start:

Checkliste:

```

☐ Akku geladen

☐ Speicher vorhanden

☐ App verbunden

☐ Standort gewählt

☐ Objekt gefunden

☐ Fokus geprüft

☐ Filter geprüft

```

---

# 4. Phase 3 – Testaufnahme

Nie direkt mehrere Stunden aufnehmen.

Erstes Bild prüfen.

---

Kontrolle:

## Sterne

Gut:

```

kleine runde Punkte

```

---

Schlecht:

```

Striche

Scheiben

verwaschen

```

---

## Histogramm

Nicht:

komplett links.

Nicht:

komplett rechts.

---

# 5. Phase 4 – Lights aufnehmen

Standard:

```

180 Sekunden

Gain 35

200 Bilder

```

---

Während der Aufnahme:

Kontrollieren:

- Verbindung
- Wetter
- Fortschritt

---

Nicht verändern:

- Fokus
- Standort
- Filter

---

# 6. Phase 5 – Darks aufnehmen

Nach den Lights:

gleiche Einstellungen:

```

Belichtung:

180 Sekunden

Gain:

35

```

---

Empfehlung:

```

20 Darks

```

---

# 7. Phase 6 – Datenorganisation

Ordner erstellen:

```

M31/

├── raw/

│   ├── lights/

│   ├── darks/

│   └── flats/

│

├── siril/

├── graxpert/

├── gimp/

└── export/

```

---

# 8. Phase 7 – Siril Verarbeitung

## Schritt 1

Sequenzen erstellen.

```

Lights

↓

lights.seq

Darks

↓

darks.seq

```

---

## Schritt 2

Dark Master erstellen.

```

Darks

↓

Median Stack

↓

master_dark

```

---

## Schritt 3

Lights kalibrieren.

```

Lights

*

Master Dark

↓

kalibrierte Lights

```

---

## Schritt 4

Registrierung.

Einstellung:

```

Deep Sky

Global Star Alignment

Homographie

```

---

Ergebnis:

Alle Sterne liegen übereinander.

---

## Schritt 5

Stack.

Empfehlung:

```

Winsor Sigma Clipping

```

---

Normalisierung:

```

Additiv + Skalierung

```

---

Ergebnis:

```

M31_stack.fit

```

---

# 9. Phase 8 – Technische Bildkorrektur

## Hintergrund

Siril:

```

Background Extraction

```

---

Ziel:

Entfernen:

- Lichtgradient
- ungleichmäßige Helligkeit

---

Danach:

```

Photometric Color Calibration

```

---

Danach:

```

Green Noise Removal

```

---

# 10. Phase 9 – Stretch

Jetzt wird das Bild sichtbar.

---

Reihenfolge:

```

Asinh Stretch

↓

Histogram Transformation

↓

Kurven

```

---

Ziel:

- Galaxie sichtbar
- Hintergrund erhalten
- Sterne kontrolliert

---

# 11. Phase 10 – GraXpert

Optional.

Verwendung:

Wenn:

- Gradient vorhanden
- Stadtlicht
- Mond

---

Workflow:

```

Siril TIFF/FITS

↓

GraXpert

↓

neue Version speichern

```

---

Regeln:

Nicht aggressiv.

---

# 12. Phase 11 – GIMP Bearbeitung

Import:

```

TIFF 16 Bit

```

---

Ebenenstruktur:

```

Original

↓

Farbe

↓

Kontrast

↓

lokale Anpassungen

↓

Export

```

---

Bearbeitung:

## Farben

leicht anpassen.

---

## Kontrast

sanft erhöhen.

---

## Sättigung

kleine Schritte.

---

## Schärfung

minimal.

---

# 13. Phase 12 – Export

Archiv:

```

M31_master.tif

```

---

Bearbeitung:

```

M31_final.xcf

```

---

Internet:

```

M31_final.jpg

```

---

# 14. Phase 13 – Archivierung

Speichern:

```

Originaldaten

*

Siril Projekt

*

GIMP Projekt

*

Finalbilder

```

---

# 15. Qualitätsprüfung

Vor Veröffentlichung:

Prüfen:

---

## Sterne

Sind sie:

- rund?
- natürlich?
- nicht ausgebrannt?

---

## Farben

Sind sie:

- glaubwürdig?
- nicht extrem gesättigt?

---

## Hintergrund

Ist er:

- dunkel?
- aber nicht schwarz?

---

## Details

Sind sichtbar:

- Nebelstrukturen?
- Staubbänder?
- Sterne?

---

# 16. Fehler vermeiden

Nicht:

```

Rohdaten löschen

↓

JPEG speichern

↓

Original verlieren

```

---

Nicht:

```

zu stark bearbeiten

↓

Details zerstören

```

---

# 17. Persönlicher Standardworkflow

Der ideale Dwarf-3-Alltag:

```

Objekt wählen

↓

180s / Gain 35

↓

200 Lights

↓

20 Darks

↓

Siril Standardworkflow

↓

PCC

↓

Green Removal

↓

Asinh Stretch

↓

GraXpert bei Bedarf

↓

GIMP

↓

Archiv

```

---

# 18. Lernstrategie

Nicht jedes Bild maximal bearbeiten.

Besser:

Vergleichen.

Beispiel:

```

Version 1:
natürlich

Version 2:
stärkerer Nebel

Version 3:
Starless

```

---

So entwickelt man ein Gefühl für:

- gutes Stretching
- Farben
- Details
- Grenzen der Daten

---

# 19. Endziel

Eine gute Dwarf-3-Aufnahme ist nicht die mit:

- maximaler Helligkeit
- maximaler Sättigung
- maximalem Kontrast

Sondern:

```

ein natürliches Bild

mit möglichst vielen echten Details

