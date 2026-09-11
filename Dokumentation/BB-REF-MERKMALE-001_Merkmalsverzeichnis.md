# Merkmalsverzeichnis BioBox

| | |
|---|---|
| **Dokument-ID** | BB-REF-MERKMALE-001 |
| **Version** | 1.0 |
| **Datum** | 10.09.2026 |
| **Autorin** | Atida Ashta |
| **Gilt für** | `auswertung/ergebnisse.csv` und `auswertung/gesundheit.csv` |

---

## 1. `ergebnisse.csv` — Messwerte

Eine Zeile je Bild, zeitlich sortiert.

### Identifikation

| Spalte | Einheit | Bedeutung | Wofür |
|---|---|---|---|
| `bild` | — | Dateiname ohne Endung. Enthält den Aufnahmezeitpunkt. | Zuordnung zu Maske und Kontrollbild |
| `stunden_seit_start` | h | Abstand zur ersten Aufnahme | Zeitachse aller Diagramme und Modelle |

### Größe und Form

| Spalte | Einheit | Bedeutung | Wofür |
|---|---|---|---|
| `pflanzen_pixel` | px | Anzahl segmentierter Pflanzenpixel | Rohwert, unabhängig vom Maßstab |
| `blattflaeche_cm2` | cm² | projizierte Blattfläche | **Primärgröße** für Wachstum und Digital Twin |
| `durchmesser_mm` | mm | größte Ausdehnung des Bestands | Ausbreitung, Platzbedarf |
| `kompaktheit` | — | 4πA/U². 1,0 = Kreis, kleiner = zerklüftet | Formänderung bei Welke und Streckung |
| `wachstumsrate_cm2_pro_tag` | cm²/d | Flächenänderung gegenüber der Vorgängeraufnahme, auf einen Tag normiert | **Eingangsgröße Digital Twin**; erkennt Stillstand |

### Farbe

| Spalte | Einheit | Bedeutung | Wofür |
|---|---|---|---|
| `mittel_r` / `mittel_g` / `mittel_b` | 0–255 | mittlere Kanalwerte über den Pflanzenpixeln | Rohdaten; erlauben später neue Indizes ohne erneute Bildverarbeitung |
| `mittel_h` | 0–179 | mittlerer HSV-Farbton | Verschiebung des Grüntons |
| `mittel_s` | 0–255 | mittlere HSV-Sättigung | Farbkraft, sinkt bei Stress |
| `gruenindex` | 0–1 | G / (R+G+B) | wichtigster Einzelindikator, Chlorophyll |
| `gelbanteil_pct` | % | Anteil gelber Pixel an der Blattfläche | Chlorose |
| `braunanteil_pct` | % | Anteil brauner Pixel an der Blattfläche | Nekrose |

### Bildqualität

| Spalte | Einheit | Bedeutung | Wofür |
|---|---|---|---|
| `mm_pro_pixel` | mm/px | aus dem Marker berechneter Maßstab | **Nachweis der Aufbaustabilität** (BB-SPEC-IMG-001, 8.3); leer = kein Marker gefunden |
| `schaerfe` | — | Laplace-Varianz, nur über den Pflanzenpixeln | Unschärfe erkennen |
| `bildhelligkeit` | 0–255 | Mittelwert des Gesamtbildes | erkennt Belichtungs- und Fremdlichtänderungen |
| `ueberbelichtet_pct` | % | Anteil geklippter Pixel im Grünkanal | Sättigung zerstört die Farbmessung |
| `groesste_komponente_pct` | % | Anteil der größten Teilfläche an der Gesamtmaske | fällt der Wert, ist meist die Segmentierung gescheitert |
| `auffaelligkeit` | Text | verletzte Kriterien, semikolongetrennt | Fehlersuche |
| `brauchbar` | True/False | keine Auffälligkeit | **Filterspalte** vor jeder Auswertung |

### Werte von `auffaelligkeit`

| Wert | Auslöser |
|---|---|
| `kein_marker` | Marker nicht gefunden, kein Maßstab |
| `keine_pflanze` | Maske leer |
| `unscharf` | Schärfe unter `SCHAERFE_MIN` |
| `ueberbelichtet` | mehr als 1 % geklippte Pixel |
| `zersplittert` | größte Teilfläche unter 70 % |
| `flaechensprung` | Flächenänderung über `SPRUNG_MAX_PCT` gegenüber der Vorgängeraufnahme |

---

## 2. `gesundheit.csv` — Bewertung

Bewusst als eigene Datei geführt: Die Messwerte in `ergebnisse.csv` sind Rohdaten und ändern sich nicht mehr. Die Bewertung hängt dagegen von Gewichten und Kennlinien ab, die im Testbetrieb noch angepasst werden. Getrennte Dateien halten diese Trennung sichtbar.

| Spalte | Einheit | Bedeutung |
|---|---|---|
| `bild` | — | Verknüpfung zu `ergebnisse.csv` |
| `stunden_seit_start` | h | Zeitachse |
| `gesundheit` | 0–10 | geglätteter Wert (gleitender Median über 5 Bilder) — **Anzeigewert** |
| `gesundheit_roh` | 0–10 | ungeglätteter Einzelwert |
| `gesundheit_kategorie` | Text | sehr gut / gut / beobachten / auffällig / kritisch |
| `gesundheit_trend_24h` | — | Änderung gegenüber vor 24 h; Richtung ist oft aussagekräftiger als der Absolutwert |
| `gesundheitswarnung` | Text | vergilbung / nekrose / chlorose / entfaerbung / wachstumsstillstand |
| `score_gruen` | 0–10 | Teilscore, Gewicht 0,30 |
| `score_gelb` | 0–10 | Teilscore, Gewicht 0,25 |
| `score_braun` | 0–10 | Teilscore, Gewicht 0,20 |
| `score_saettigung` | 0–10 | Teilscore, Gewicht 0,15 |
| `score_farbton` | 0–10 | Teilscore, Gewicht 0,10 |

Berechnung siehe BB-SPEC-HEALTH-001.

---

## 3. Bewusst nicht erfasste Größen

Der Vollständigkeit halber dokumentiert — diese Größen wurden geprüft und verworfen:

| Größe | Grund |
|---|---|
| Bedeckungsgrad in % des Bildes | bei fest montierter Kamera exakt proportional zu `pflanzen_pixel`, also redundant |
| Umfang in mm | steckt bereits normiert in `kompaktheit` |
| ExG-Mittelwert | exakt aus `mittel_r/g/b` berechenbar (2G − R − B) |
| Mittlerer HSV-Helligkeitswert | aus den RGB-Mittelwerten ableitbar |
| Anzahl der Teilflächen | `groesste_komponente_pct` ist aussagekräftiger |
| Unterbelichteter Bildanteil | bei mattschwarzem Hintergrund konstant hoch, ohne Aussagewert |
| Geschätzte Blattanzahl | im Test 4 statt tatsächlich 6 Blättern; überlappende Blätter verschmelzen bei Top-Down-Aufnahme. Nicht belastbar, siehe Konzeptdokument |
| Absolute Flächenänderung in cm² | aus `wachstumsrate_cm2_pro_tag` und dem Zeitabstand rekonstruierbar |

---

## 4. Diagramme

`grafiken.py` erzeugt aus beiden Dateien folgende PNG-Dateien in `auswertung/grafiken/`. Bilder mit `brauchbar = False` werden ausgelassen.

| Datei | Inhalt |
|---|---|
| `01_wachstum.png` | Blattfläche über der Zeit — die Hauptkurve der Arbeit |
| `02_wachstumsrate.png` | Wachstumsrate je Aufnahme; negative Balken deuten auf Messfehler oder Blattverlust |
| `03_farbverlauf.png` | Grünindex oben, Gelb- und Braunanteil unten |
| `04_gesundheit.png` | Gesundheitsverlauf mit farbig hinterlegten Kategoriebändern |
| `05_teilscores.png` | Aufschlüsselung der letzten Aufnahme in die fünf Teilscores |
| `06_bildqualitaet.png` | Maßstab und Bildhelligkeit über der Zeit, beide müssen konstant bleiben |

Zu `06`: Die eingezeichneten roten Linien markieren ±1 % um den Mittelwert des Maßstabs. Verlässt die Kurve dieses Band, hat sich der Aufbau bewegt — das ist das Abnahmekriterium aus BB-SPEC-IMG-001, Abschnitt 8.3.
