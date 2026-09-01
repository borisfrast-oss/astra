# Kapitel 27 – Astrofotografie Datenmanagement

# Dwarf 3 + Siril 1.4.4 + GraXpert + GIMP 3.2.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel beschreibt eine saubere Organisation der Astrofotografie-Daten.

Ein guter Workflow besteht nicht nur aus Bearbeitung.

Auch wichtig:

- Wiederholbarkeit
- Archivierung
- Vergleichbarkeit
- Backup
- Versionierung

Gerade bei Deep-Sky-Aufnahmen entstehen schnell viele Gigabyte an Daten.

---

# 1. Grundprinzip

Die Originaldaten werden niemals verändert.

Regel:

```

Original bleibt erhalten

↓

Bearbeitung erzeugt neue Dateien

```

---

# 2. Empfohlene Ordnerstruktur

Empfehlung pro Objekt:

```

Astro/

└── M31/

```
├── 01_raw/
│
├── 02_calibration/
│
├── 03_siril/
│
├── 04_graxpert/
│
├── 05_gimp/
│
└── 06_export/
```

```

---

# 3. Rohdaten

Ordner:

```

01_raw

```

enthält:

- Lights
- Darks
- Flats
- Bias

Beispiel:

```

M31/

└── 01_raw/

```
├── lights/
├── darks/
├── flats/
└── bias/
```

```

---

# 4. Lights organisieren

Empfohlener Name:

```

Objekt_Datum_Belichtung_Gain

```

Beispiele:

```

M31_2026-07-29_180s_G35

```

---

Vorteile:

Man erkennt später:

- welches Objekt
- wann aufgenommen
- welche Einstellungen

---

# 5. Calibration Dateien

Ordner:

```

02_calibration

```

---

Beispiel:

```

02_calibration/

├── dark_master/
├── flat_master/
└── bias_master/

```

---

Masterdateien behalten.

Sie können später wieder verwendet werden.

---

# 6. Siril Arbeitsordner

Ordner:

```

03_siril

```

enthält:

```

03_siril/

├── sequences/
├── registered/
├── stacked/
└── final/

```

---

Beispiele:

```

M31_light.seq

M31_registered.fit

M31_stack.fit

```

---

# 7. Warum Sequenzen speichern?

Siril erzeugt:

```

.seq

```

Dateien.

Diese enthalten:

- Bildreihenfolge
- Metadaten
- Registrierung

---

Vorteil:

Workflow kann später wiederholt werden.

---

# 8. GraXpert Versionierung

Ordner:

```

04_graxpert

```

---

Empfehlung:

```

04_graxpert/

├── input/
├── processed/
└── versions/

```

---

Beispiele:

```

M31_graxpert_v1.tif

M31_graxpert_v2.tif

```

---

Nicht überschreiben.

---

# 9. GIMP Organisation

Ordner:

```

05_gimp

```

---

Speichern:

```

M31_final.xcf

```

---

Warum XCF?

Es speichert:

- Ebenen
- Masken
- Einstellungen

---

Nicht nur TIFF speichern.

---

# 10. Exportordner

Ordner:

```

06_export

```

---

Enthält fertige Bilder:

```

M31_final.jpg

M31_final.tif

M31_social.jpg

```

---

# 11. Dateiformate

## FITS

Verwendung:

- Rohdaten
- Siril Verarbeitung

Vorteile:

- maximale Information

---

## TIFF 16 Bit

Verwendung:

- Übergabe an GIMP
- Archiv

Vorteile:

- hohe Farbtiefe

---

## XCF

Verwendung:

- GIMP-Projekt

---

## JPEG

Verwendung:

- Veröffentlichung
- Webseite

Nicht:

Archiv.

---

# 12. Versionierung

Empfehlung:

Versionsnummern verwenden.

Beispiel:

```

M31_final_v01.xcf

M31_final_v02.xcf

M31_final_v03.xcf

```

---

Nicht:

```

M31_final_neu_neu2_final.xcf

```

---

# 13. Aufnahmeprotokoll

Für jede Session sinnvoll:

Datei:

```

session_notes.md

````

---

Beispiel:

```markdown
Objekt:
M31

Datum:
2026-07-29

Ort:
Wien

Belichtung:
180s

Gain:
35

Filter:
kein Filter

Lights:
200

Darks:
20

Seeing:
gut

Bemerkungen:
leichter Mond
````

---

# 14. Warum Aufnahmedaten wichtig sind

Nach Monaten weiß man sonst nicht mehr:

* warum ein Bild gut war
* warum eines schlecht war
* welche Einstellungen funktioniert haben

---

# 15. Backup-Strategie

Empfehlung:

3-2-1 Regel.

---

## 3 Kopien

Mindestens:

* Arbeitskopie
* Backup
* Archiv

---

## 2 verschiedene Medien

Beispiel:

* interne SSD
* externe Festplatte

---

## 1 externe Kopie

Beispiel:

* Cloud
* anderes Gerät

---

# 16. Speicherplanung

Typische Größen:

## Einzelaufnahme

Je nach Format:

```
mehrere MB pro Bild
```

---

## 200 Lights

Kann schnell erreichen:

```
mehrere GB
```

---

Zusätzlich:

* Zwischenstände
* TIFF
* XCF

---

# 17. Aufräumen

Nicht löschen:

* RAW
* Master Calibration
* finale Siril-Datei

---

Kann gelöscht werden:

* temporäre Registrierungsdateien
* Zwischenversionen ohne Wert

---

# 18. Vergleich verschiedener Bearbeitungen

Sehr sinnvoll.

Beispiel:

```
M31/

├── natural/
├── high_contrast/
├── starless/
└── experimental/
```

---

So lernt man:

Welche Bearbeitung funktioniert besser?

---

# 19. Automatisierungsmöglichkeiten

Später möglich:

* automatische Ordneranlage
* automatische Siril-Skripte
* Metadaten aus FITS lesen
* Workflow dokumentieren

---

Beispiel:

```
Neuer Dwarf-Ordner

↓

Script erkennt Objekt

↓

Siril Workflow auswählen

↓

Stack erzeugen
```

---

# 20. Minimaler persönlicher Workflow

Für den Alltag:

```
Dwarf Aufnahme

↓

RAW sichern

↓

Siril Projektordner erstellen

↓

Stack erzeugen

↓

GraXpert

↓

GIMP XCF speichern

↓

Export erstellen

↓

Backup
```

---

# 21. Empfohlene Archivstruktur langfristig

```
Astrofotografie/

├── 2026/
│
├── 2027/
│
└── Bibliothek/

    ├── Galaxien/
    ├── Nebel/
    ├── Sternhaufen/
    ├── Planeten/
    └── Mond/
```

---

# 22. Qualitätsregel

Ein gutes Archiv ermöglicht:

Heute:

```
Bild erstellen
```

---

In einem Jahr:

```
Workflow nachvollziehen

↓

besser neu bearbeiten
```


