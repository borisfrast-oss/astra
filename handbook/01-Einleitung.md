# 01 – Einleitung

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# 1. Was ist Astrofotografie?

Astrofotografie ist die Technik, schwache Lichtquellen aus dem Weltraum fotografisch sichtbar zu machen.

Viele astronomische Objekte sind so lichtschwach, dass sie:

- mit bloßem Auge nicht sichtbar sind
- auf normalen Fotos kaum erscheinen
- erst durch lange Belichtungszeiten sichtbar werden

Beispiele:

- Galaxien
- Emissionsnebel
- Reflexionsnebel
- Planetarische Nebel
- Sternhaufen

Die Kamera sammelt über längere Zeit Photonen.

---

# 2. Der Unterschied zur normalen Fotografie

Bei normaler Fotografie:

```

Motiv
+
Licht
+
kurze Belichtung

=

fertiges Bild

```

Bei Deep-Sky-Astrofotografie:

```

schwaches Objekt

*

viele Einzelaufnahmen

*

Kalibrierung

*

Registrierung

*

Stacking

*

Bildbearbeitung

=

sichtbares Ergebnis

```

Ein Astrobild entsteht also nicht durch eine einzelne Aufnahme.

---

# 3. Photonen sammeln

Das wichtigste Prinzip:

> Astrofotografie ist das Sammeln von Licht.

Jede Belichtung sammelt zusätzliche Information.

Eine einzelne Aufnahme enthält nur einen kleinen Teil der Information.

Beispiel:

## Einzelaufnahme

```

Signal:
100

Rauschen:
30

```

Das Objekt ist schwer sichtbar.

---

## 16 Aufnahmen kombiniert

```

Signal:
100

Rauschen:
30 / √16

=

7,5

```

Das Signal bleibt erhalten.

Das zufällige Rauschen wird reduziert.

---

# 4. Signal und Rauschen

Ein Sensor kann nicht nur Licht messen.

Er erzeugt auch eigene Störungen.

Das Bildsignal besteht aus:

```

Gesamtsignal

=

Objektlicht

*

Hintergrundlicht

*

Sensoreffekte

*

Rauschen

```

Die Verarbeitung versucht:

- Objektlicht zu erhalten
- Sensoreffekte zu entfernen
- Rauschen zu reduzieren

---

# 5. Arten von Rauschen

## 5.1 Ausleserauschen

Entsteht beim Auslesen des Sensors.

Eigenschaften:

- tritt bei jeder Aufnahme auf
- unabhängig von der Belichtungszeit

---

## 5.2 Dunkelstrom

Elektronen entstehen auch ohne Licht.

Verstärkt sich durch:

- längere Belichtungszeiten
- höhere Temperaturen

Wird durch Darks korrigiert.

---

## 5.3 Hotpixel

Einzelne Pixel reagieren stärker als andere.

Erkennbar als:

- helle Punkte
- farbige Pixel
- feste Muster

Werden durch:

- Darks
- Sigma-Stacking

reduziert.

---

## 5.4 Zufallsrauschen

Dieses Rauschen verändert sich von Bild zu Bild.

Genau deshalb funktioniert Stacking.

---

# 6. Warum Stacking funktioniert

Beim Stacken werden mehrere Bilder kombiniert.

Echtes Signal:

```

Bild 1:
Stern an Position X

Bild 2:
Stern an Position X

Bild 3:
Stern an Position X

```

Das Signal bleibt.

---

Rauschen:

```

Bild 1:
Pixelabweichung A

Bild 2:
Pixelabweichung B

Bild 3:
Pixelabweichung C

```

Die zufälligen Fehler mitteln sich heraus.

---

# 7. Integrationzeit

Die wichtigste Qualitätsgröße ist:

```

Gesamtbelichtungszeit

=

Anzahl Bilder

×

Belichtungszeit

```

Beispiele:

| Bilder | Belichtungszeit | Gesamt |
|---:|---:|---:|
| 10 | 180 s | 30 Minuten |
| 20 | 180 s | 60 Minuten |
| 40 | 180 s | 120 Minuten |
| 80 | 180 s | 240 Minuten |

---

# 8. Warum längere Belichtungen helfen

Mehr Integrationszeit bedeutet:

- schwächere Details werden sichtbar
- Hintergrund wird sauberer
- Farben werden stabiler
- weniger aggressives Entrauschen notwendig

Beispiel M31:

Mit kurzer Integration:

- Kern sichtbar
- Außenarme kaum sichtbar

Mit längerer Integration:

- Staubbänder
- Außenbereiche
- M110

werden sichtbar.

---

# 9. Der Dwarf 3 Workflow

Der Dwarf 3 übernimmt bereits:

- Nachführung
- automatische Ausrichtung
- Aufnahmeplanung

Die eigentliche Bildverarbeitung erfolgt danach.

Der typische Ablauf:

```

Dwarf 3

↓

FITS-Dateien

↓

Siril

↓

Kalibrierung

↓

Stacking

↓

Bildbearbeitung

```

---

# 10. FITS-Dateien

FITS bedeutet:

Flexible Image Transport System.

Es ist das Standardformat der Astronomie.

Eine FITS-Datei enthält:

- Bilddaten
- Metadaten
- Aufnahmeinformationen

Im Gegensatz zu JPEG:

JPEG:

- komprimiert
- bereits verarbeitet
- verliert Informationen

FITS:

- Rohdaten
- hoher Dynamikumfang
- ideal für wissenschaftliche Verarbeitung

---

# 11. Lights

Lights sind die eigentlichen Objektaufnahmen.

Beispiel:

```

m31_light_00001.fits
m31_light_00002.fits
m31_light_00003.fits

```

Sie enthalten:

- Sterne
- Galaxie
- Nebel
- Hintergrund
- Rauschen

---

# 12. Darks

Darks werden ohne Licht aufgenommen.

Sie zeigen:

- Sensormuster
- Hotpixel
- Dunkelstrom

Ein Dark enthält also:

```

kein Objekt

aber

Sensoreigenschaften

```

---

# 13. Flats

Flats zeigen optische Fehler.

Sie korrigieren:

- Staub
- Vignettierung
- ungleichmäßige Ausleuchtung

Ein Flat beantwortet:

> Wie gleichmäßig sieht die Kamera die Fläche?

---

# 14. Bias

Bias misst den minimalen elektronischen Offset des Sensors.

Bei vielen Astrokameras wichtig.

Beim Dwarf 3:

- häufig nicht notwendig
- Darks sind meist ausreichend

---

# 15. Lineares Bild

Nach dem Stack entsteht ein lineares Bild.

Eigenschaften:

- sehr dunkel
- Details kaum sichtbar
- mathematisch unverändert

Beispiel:

```

M31 vorhanden

aber kaum sichtbar

```

Das ist normal.

---

# 16. Stretching

Stretching verändert die Darstellung.

Es macht:

- schwache Details sichtbar
- Farben sichtbar
- Kontraste sichtbar

Es erzeugt kein neues Signal.

Ein schlechtes Signal bleibt schlecht.

---

# 17. Warum unterschiedliche Objekte unterschiedliche Workflows brauchen

## Galaxien

Eigenschaften:

- schwach
- großer Dynamikbereich

Benötigen:

- viel Integration
- saubere Hintergrundbearbeitung

---

## Nebel

Eigenschaften:

- diffuse Strukturen
- Farbanteile

Benötigen:

- gutes Farbmanagement
- vorsichtiges Stretching

---

## Sternhaufen

Eigenschaften:

- viele helle Sterne

Benötigen:

- Sternfarben erhalten
- wenig Entrauschen

---

## Einzelsterne

Eigenschaften:

- sehr hell
- Farbe wichtig

Benötigen:

- minimale Bearbeitung

---

# 18. Grundphilosophie dieses Handbuchs

Die wichtigste Regel:

> Die beste Bearbeitung ist die, die das vorhandene Signal sichtbar macht, ohne neue Artefakte zu erzeugen.

Deshalb:

- nicht jedes Bild maximal stretchen
- nicht jedes Bild maximal entrauschen
- nicht jede Korrektur anwenden

Der richtige Workflow hängt vom Objekt ab.

