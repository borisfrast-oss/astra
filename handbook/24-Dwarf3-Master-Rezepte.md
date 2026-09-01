# Kapitel 24 – Dwarf 3 Master-Rezepte

# Dwarf 3 + Siril 1.4.4 Best Practices Handbuch

---

# Ziel

Dieses Kapitel enthält bewährte Standardrezepte für typische Objekte.

Die Rezepte sind keine starren Regeln.

Sie dienen als Ausgangspunkt:

- gleiche Bedingungen schaffen
- schneller zum Ergebnis kommen
- typische Fehler vermeiden

---

# 1. Grundrezept Deep Sky

Wenn keine Erfahrung mit dem Objekt vorhanden ist:

```

Belichtung:
180 Sekunden

Gain:
35

Filter:
kein Filter

Lights:
200

Darks:
20

Flat:
ja

Stack:
Winsor Sigma

Normalisierung:
Additiv + Skalierung

PCC:
ja

Stretch:
vorsichtig

```

Geeignet für:

- Galaxien
- Nebel
- Sternhaufen

---

# 2. M31 Andromedagalaxie

## Ziel

Darstellung von:

- Kern
- Staubbändern
- Außenbereichen
- Sternfeld

---

## Aufnahme

```

Belichtung:
180 Sekunden

Gain:
30–35

Filter:
kein Filter

Lights:
150–300

```

---

## Kalibrierung

Empfohlen:

```

Dark:
ja

Flat:
ja

Bias:
optional

```

---

## Siril Workflow

```

Sequenz erstellen

↓

Kalibrierung

↓

Deep Sky Registrierung

↓

Winsor Sigma Stack

↓

Background Extraction

↓

PCC

↓

Green Noise Removal

↓

Asinh Stretch

↓

Export TIFF

```

---

## Besonderheit

M31 besitzt einen sehr hellen Kern.

Nicht zu stark stretchen.

Optional:

HDR mit kürzeren Aufnahmen.

---

# 3. M42 Orionnebel

## Ziel

Gleichzeitig:

- heller Kern
- schwache Außenbereiche
- rote Nebelstrukturen

---

## Aufnahme

Empfohlen:

zwei Serien.

---

## Kurzbelichtung

```

Belichtung:
5–15 Sekunden

Gain:
10–20

Lights:
50+

```

für:

- Trapezium
- Kern

---

## Langbelichtung

```

Belichtung:
120–180 Sekunden

Gain:
30–40

Lights:
100+

```

für:

- Außenbereiche
- Nebelfilamente

---

## Verarbeitung

Zwei Stacks:

```

Kurzbelichtung

*

Langbelichtung

↓

HDR in GIMP

```

---

# 4. M45 Plejaden

## Ziel

Darstellung:

- blauer Reflexionsnebel
- Sternfarben
- Staubstrukturen

---

## Aufnahme

```

Belichtung:
120 Sekunden

Gain:
30

Filter:
kein Filter

Lights:
200+

```

---

## Verarbeitung

Besonders vorsichtig:

```

Background Extraction

↓

PCC

↓

sanfter Stretch

```

---

## Wichtig

Nicht:

- Dualband verwenden
- Hintergrund zu stark entfernen

---

# 5. M13 Kugelsternhaufen

## Ziel

Viele einzelne Sterne sichtbar machen.

---

## Aufnahme

```

Belichtung:
30–90 Sekunden

Gain:
10–30

Lights:
100–300

```

---

## Verarbeitung

```

Dark

↓

Registrierung

↓

Stack

↓

PCC

↓

leichter Stretch

```

---

## Wichtig

Sternfarben erhalten.

Nicht zu stark entrauschen.

---

# 6. M27 Hantelnebel

## Ziel

Planetarischer Nebel mit:

- OIII-Struktur
- H-alpha-Anteilen

---

## Aufnahme

Ohne Filter:

```

120 Sekunden

Gain:
30–40

```

---

Mit Dualband:

```

180 Sekunden

Gain:
40

```

---

## Verarbeitung

```

Stack

↓

Background Extraction vorsichtig

↓

PCC

↓

Farbkorrektur

↓

Stretch

```

---

# 7. Cirrusnebel / Schleiernebel

## Ziel

Extrem schwache Filamente.

---

## Aufnahme

```

Belichtung:
180 Sekunden

Gain:
40

Filter:
Dualband

Lights:
300+

```

---

## Verarbeitung

Sehr vorsichtig:

```

GraXpert

↓

PCC

↓

Stretch

```

---

## Wichtig

Nicht:

- aggressiv entrauschen
- Hintergrund schwarz machen

---

# 8. Herznebel IC1805

## Ziel

Große H-alpha-Struktur.

---

## Aufnahme

```

Belichtung:
180 Sekunden

Gain:
40

Filter:
Dualband

Lights:
300+

```

---

## Verarbeitung

```

Dark

↓

Flat

↓

Stack

↓

Background Extraction

↓

Farbkalibrierung

↓

Stretch

```

---

# 9. Rosettennebel

## Ziel

- rote Nebelstruktur
- zentrale Sternengruppe

---

## Aufnahme

```

180 Sekunden

Gain:
40

Dualband

200–500 Lights

```

---

## Besonderheit

OIII-Anteil kann grün/blau erscheinen.

Nicht komplett entfernen.

---

# 10. Arktur / helle Sterne

## Ziel

Natürliche Sternfarbe.

---

## Aufnahme

```

Belichtung:
1–10 Sekunden

Gain:
0–20

Lights:
100+

```

---

## Verarbeitung

Minimal:

```

Stack

↓

leichte Farbkorrektur

↓

Export

```

---

Nicht:

- stark schärfen
- stark entrauschen

---

# 11. Albireo Doppelstern

## Ziel

Farbkontrast:

- goldener Stern
- blauer Begleiter

---

## Aufnahme

```

Belichtung:
1–5 Sekunden

Gain:
0–10

```

---

## Verarbeitung

```

Stack

↓

Farbkorrektur

↓

leichte Schärfung

```

---

# 12. Mond

## Ziel

Maximale Details.

---

## Aufnahme

```

sehr kurze Belichtung

Gain:
0–20

viele Bilder

```

---

## Verarbeitung

Nicht klassisches Deep Sky:

```

beste Bilder auswählen

↓

Stack

↓

Schärfung

↓

Kontrast

```

---

# 13. Jupiter

## Ziel

- Wolkenbänder
- Monde

---

## Aufnahme

```

Video

oder viele kurze Frames

```

---

## Verarbeitung

```

beste Frames auswählen

↓

Stack

↓

Schärfen

↓

Farbkorrektur

```

---

# 14. Milchstraße

## Ziel

- große Strukturen
- Sternfelder

---

## Aufnahme

```

Belichtung:
10–30 Sekunden

Gain:
20–40

Lights:
100+

```

---

## Verarbeitung

```

Stack

↓

Background Extraction

↓

PCC

↓

Stretch

```

---

# 15. Kometen

## Ziel

Komet + Sterne getrennt optimieren.

---

## Aufnahme

```

Belichtung:
30–120 Sekunden

Gain:
30–40

```

---

## Verarbeitung

Zwei Stacks:

```

Sternregistrierung

↓

Sternstack

Kometenregistrierung

↓

Kometenstack

```

Danach:

```

GIMP Kombination

```

---

# 16. Universelles Fehlerschema

Wenn ein Rezept nicht funktioniert:

Nicht alle Parameter ändern.

Reihenfolge:

```

1. Fokus prüfen

↓

2. Einzelbilder prüfen

↓

3. Kalibrierung prüfen

↓

4. Stack prüfen

↓

5. Bearbeitung prüfen

```

---

# 17. Meine Dwarf-3 Standardwerte

Wenn ich heute ein unbekanntes Deep-Sky-Objekt aufnehmen würde:

```

180 Sekunden

Gain 35

kein Filter

200 Lights

20 Darks

Flat vorhanden

Winsor Sigma

PCC

Asinh Stretch


