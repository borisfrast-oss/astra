# Kapitel 28 – Fortgeschrittene Techniken

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt fortgeschrittene Techniken, die über den normalen Dwarf-3-Workflow hinausgehen.

Diese Methoden sind besonders interessant, wenn die Grundlagen sicher funktionieren.

Themen:

- HDR Deep Sky
- Starless Processing
- Sterne separat bearbeiten
- Dualband HOO
- mehrere Belichtungszeiten kombinieren
- Mosaike
- Mehrfachsessions kombinieren

---

# 1. HDR Deep Sky

## Ziel

Der Dynamikumfang vieler astronomischer Objekte ist größer als eine einzelne Belichtung darstellen kann.

Beispiele:

- M42 Orionnebel
- M31 Andromedagalaxie
- helle Kugelsternhaufen
- Mond mit Schattenbereichen

---

# 1.1 Grundprinzip

Eine Aufnahme liefert:

```

schwache Außenbereiche

```

Eine zweite Aufnahme liefert:

```

helle Kernbereiche

```

Beide werden kombiniert.

---

Beispiel:

```

Langbelichtung

180 Sekunden

↓

Nebeldetails

Kurzbelichtung

5–20 Sekunden

↓

Kernstruktur

↓

HDR Kombination

```

---

# 1.2 Siril Workflow

Für beide Serien getrennt:

```

Sequenz erstellen

↓

Kalibrieren

↓

Registrieren

↓

Stacken

↓

Export TIFF

```

---

Danach:

```

GIMP

↓

beide Bilder als Ebenen öffnen

↓

Maske erstellen

↓

kombinieren

```

---

# 1.3 Typische Fehler

## Kern weiterhin ausgebrannt

Ursachen:

- Kurzbelichtung zu lang
- Maske falsch

---

## Übergang sichtbar

Lösung:

- weiche Maske verwenden
- Übergang großflächig gestalten

---

# 2. Starless Processing

## Ziel

Sterne und Objekt getrennt bearbeiten.

Vorteile:

- Nebel stärker hervorheben
- Sterne kontrollieren
- weniger Überstrahlung

---

# 2.1 Grundprinzip

Ausgang:

```

Bild

↓

Sterne entfernen

↓

Starless Bild

*

Sternmaske

```

---

Danach:

```

Nebel bearbeiten

↓

Sterne separat bearbeiten

↓

kombinieren

```

---

# 2.2 Vorteile

Besonders geeignet für:

- Emissionsnebel
- große Nebel
- schwache Strukturen

---

Beispiele:

- Herznebel
- Rosettennebel
- Schleiernebel

---

# 2.3 Nebelbearbeitung

Starless Bild erlaubt:

- stärkeren Kontrast
- stärkere Farbanpassung
- lokale Bearbeitung

ohne:

Sterne aufzublasen.

---

# 2.4 Sternbearbeitung

Eigene Ebene:

Möglichkeiten:

- Helligkeit reduzieren
- Sättigung anpassen
- Größe reduzieren

---

# 3. Dualband HOO Workflow

## Ziel

Aus Dualband-Daten eine natürliche Farbpalette erzeugen.

---

HOO bedeutet:

```

H-alpha → Rot

OIII → Grün + Blau

```

---

# 3.1 Aufnahme

Geeignet:

- Herznebel
- Rosettennebel
- Adlernebel
- Schleiernebel

---

Empfehlung:

```

180 Sekunden

Gain 40

Dualband

200–500 Lights

```

---

# 3.2 Siril Vorbereitung

Standard:

```

Kalibrierung

↓

Registrierung

↓

Stack

```

---

# 3.3 Kanalarbeit

Ziel:

H-alpha hervorheben:

```

Rotkanal

```

---

OIII:

```

Blaukanal

*

Grünkanal

```

---

# 3.4 Farbmanagement

Nicht jede Aufnahme benötigt extremes HOO.

Ziel:

natürliche Farben.

---

Vermeiden:

- giftiges Grün
- extremes Rot

---

# 4. Unterschiedliche Belichtungen kombinieren

## Ziel

Mehr Dynamik und bessere Details.

---

Beispiel:

```

30 Sekunden

*

180 Sekunden

*

300 Sekunden

```

---

Geeignet für:

- helle Nebel
- Galaxien
- Sternhaufen

---

# 4.1 Siril

Jede Serie separat:

```

Kalibrieren

↓

Stacken

```

---

Danach:

Kombination in:

- GIMP
- Photoshop
- ähnlicher Software

---

# 5. Mehrere Sessions kombinieren

## Ziel

Mehr Integrationszeit.

Beispiel:

Nacht 1:

```

100 × 180s

```

---

Nacht 2:

```

150 × 180s

```

---

Gesamt:

```

250 Lights

```

---

# 5.1 Voraussetzung

Gleich halten:

- Fokus
- Belichtung
- Gain
- Filter

---

# 5.2 Siril Workflow

Alle Lights gemeinsam:

```

Sequenz erstellen

↓

Kalibrieren

↓

Registrieren

↓

Stacken

```

---

Vorteil:

weniger Rauschen.

---

# 6. Mosaike

## Ziel

Größere Objekte aufnehmen.

Beispiele:

- große Nebel
- Mondpanorama
- Milchstraße

---

# 6.1 Aufnahmeplanung

Einzelbilder müssen:

- überlappen
- gleiche Einstellungen haben

---

Empfehlung:

Überlappung:

```

20–30 %

```

---

# 6.2 Workflow

Einzelne Felder:

```

Aufnehmen

↓

je Feld stacken

```

---

Danach:

```

Mosaik zusammensetzen

```

---

# 6.3 GIMP Mosaik

Geeignet für kleine Projekte.

Ablauf:

```

Neue große Leinwand

↓

Bilder als Ebenen öffnen

↓

Ausrichten

↓

Masken erstellen

↓

zusammenfügen

```

---

# 6.4 Professioneller

Bei großen Mosaiken:

verwenden:

- Siril Mosaikfunktionen
- spezielle Astrosoftware

---

# 7. Sterne separat verbessern

## Problem

Dwarf-Daten können kleine Sterne zeigen.

---

Möglichkeiten:

## Farbverstärkung

Sterne leicht sättigen.

---

## Größenkontrolle

Sterne reduzieren.

---

## Schärfung

Nur Sterne schärfen.

---

Nicht:

Gesamtbild stark schärfen.

---

# 8. Lokale Kontrastverstärkung

Ziel:

Strukturen hervorheben.

---

Geeignet:

- Galaxienarme
- Nebelfilamente
- Mondkrater

---

Werkzeuge:

- Ebenen
- Masken
- lokale Kurven

---

# 9. Mehrfarbige Kombinationen

Beispiele:

RGB:

```

Rot

Grün

Blau

```

---

Dualband:

```

H-alpha

OIII

```

---

Planet:

```

RGB Kanäle

```

---

# 10. Referenzbilder und Vergleich

Fortgeschrittene Bearbeitung bedeutet:

nicht nur schöner machen.

Vergleichen:

- Original
- Version 1
- Version 2

---

Fragen:

- Sind mehr Details sichtbar?
- Sind Farben glaubwürdig?
- Sind Artefakte entstanden?

---

# 11. Typischer Fortgeschrittenen-Workflow

```

Dwarf Aufnahme

↓

Siril Standardworkflow

↓

Stack

↓

PCC

↓

GraXpert

↓

Starless erzeugen

↓

Nebel bearbeiten

↓

Sterne bearbeiten

↓

kombinieren

↓

GIMP Finalisierung

```

---

# 12. Häufige Fehler bei fortgeschrittener Bearbeitung

## Zu künstliche Farben

Ursache:

zu viel Sättigung.

---

## Schwarzer Hintergrund

Ursache:

Schwarzpunkt zu aggressiv.

---

## Keine Sterne mehr

Ursache:

Starless falsch kombiniert.

---

## Plastischer Look

Ursachen:

- zu viel Schärfung
- zu viel Kontrast
- zu starke Entrauschung

---

# 13. Wann diese Techniken einsetzen?

Nicht jedes Bild braucht alles.

---

Einfach:

```

Stack

↓

PCC

↓

Stretch

↓

GIMP

```

reicht oft.

---

Fortgeschritten:

wenn:

- Signal vorhanden
- Workflow sicher
- Objekt geeignet

---

# 14. Qualitätsziel

Eine fortgeschritten bearbeitete Aufnahme:

- zeigt mehr Details
- bleibt natürlich
- erhält Sterne
- nutzt den Dynamikumfang
- vermeidet Artefakte

---


