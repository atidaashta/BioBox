# Bildaufnahme-Spezifikation BioBox

| | |
|---|---|
| **Dokument-ID** | BB-SPEC-IMG-001 |
| **Version** | 0.1 (Entwurf) |
| **Datum** | 10.09.2026 |
| **Autorin** | Atida Ashta |
| **Arbeitspaket** | 3.1 Bilderfassungssystem, PSP 1.1–1.8 |
| **Meilenstein** | A-M1, Termin 30.09.2026 |
| **Status** | Entwurf – Abstimmung mit Grid Tanushi (Hardware) und Edona Peraj (Plattform) offen |

---

## 1. Zweck und Geltungsbereich

Dieses Dokument legt verbindlich fest, unter welchen geometrischen, optischen und zeitlichen Bedingungen Pflanzenbilder in der BioBox aufgenommen werden. Es ist die Grundlage für die Computer-Vision-Pipeline (A-M2), die Gesundheitsbewertung (A-M3) und das Digital-Twin-Modell (A-M4).

Die zentrale Anforderung lautet: **Alle Bilder eines Wachstumszyklus müssen untereinander vergleichbar sein.** Eine Flächen- oder Farbmessung ist nur dann als Wachstumsgröße interpretierbar, wenn sich zwischen zwei Aufnahmen ausschließlich die Pflanze geändert hat – nicht die Kameraposition, nicht die Belichtung, nicht der Weißabgleich und nicht die Beleuchtung. Jede in diesem Dokument fixierte Größe dient diesem Ziel.

Nicht Gegenstand dieses Dokuments sind die Segmentierungsverfahren, die Merkmalsberechnung und die Modellbildung; diese werden in BB-SPEC-CV-001 bzw. BB-SPEC-DT-001 beschrieben.

---

## 2. Randbedingungen

| Größe | Festlegung | Quelle |
|---|---|---|
| Referenzpflanze | Basilikum (*Ocimum basilicum*), Einzelpflanze bzw. Topfbestand | Konzept BioBox |
| Erwartete Bestandshöhe | 50 mm (Start) bis ca. 300 mm (Zyklusende) | Annahme, im Testbetrieb zu prüfen |
| Aufnahmeort | Obere Wachstumszone der BioBox | Konzept BioBox |
| Beleuchtung | LED-Grow-Bar an der Decke, dimmbar | Arbeitspaket Grid Tanushi |
| Umgebungslicht | Fronttüre aus Polycarbonat, transparent → Fremdlichteintrag möglich | Konstruktionsbedingt |

---

## 3. Hardware

### 3.1 Abweichung vom Konzeptstand

Das Konzeptdokument nennt einen Raspberry Pi 5 als Edge-Rechner. Tatsächlich verfügbar ist ein **Raspberry Pi 4**. Diese Abweichung wird bewusst akzeptiert und wie folgt begründet:

Für die reine Bilderfassung ist der Pi 4 vollständig ausreichend. Das Camera Module 3 wird über die 15-polige CSI-2-Schnittstelle des Pi 4 direkt unterstützt; Autofokus und manuelle Steuerung aller relevanten Parameter stehen über `libcamera`/`picamera2` zur Verfügung. Der Pi 4 ist gegenüber dem Pi 5 lediglich rechenschwächer, was bei einem Aufnahmeintervall von 30 Minuten irrelevant ist.

**Daraus folgt jedoch eine Systementscheidung:** Der Pi 4 wird als reines Aufnahme- und Analysegerät eingesetzt. Backend, Datenbank und Dashboard laufen **nicht** auf dem Pi, sondern auf Schulserver oder Notebook. Damit ist auch der im Konzept offen gelassene Punkt „Backend lokal auf Pi oder auf Schulserver" beantwortet.

### 3.2 Komponenten

| Komponente | Auswahl | Anmerkung |
|---|---|---|
| Edge-Rechner | Raspberry Pi 4 | OS: Raspberry Pi OS Bookworm oder neuer, 64 bit |
| Kamera | Raspberry Pi Camera Module 3 **Standard** (nicht Wide) | Sensor IMX708, 11,9 MP, 4608 × 2592 px |
| Bildfeld | 66° horizontal / 41° vertikal / 75° diagonal (lt. Datenblatt) | Standard-FOV gewählt, da geringere Randverzerrung als Wide |
| Blende / Brennweite | f/1.8, f = 4,74 mm | fix, nicht veränderbar |
| Anschluss | CSI-2 FFC, 15-polig | Kabellänge nach Einbaulage, siehe 9.1 |
| Speicher | externe USB-SSD oder ≥ 128 GB Karte | Abschätzung siehe 7.3 |

Die NoIR-Variante wird nicht verwendet: Das System arbeitet mit definiertem sichtbarem Licht, und IR-Anteile würden die Farbauswertung (Greenness-Index, Gelbanteil) verfälschen.

---

## 4. Geometrie der Bilderfassung

### 4.1 Kameraposition

Die Kamera wird **mittig an der Decke der Wachstumszone** montiert, mit Blickrichtung senkrecht nach unten auf die Pflanzwanne.

Die Montage muss **starr und dauerhaft** sein. Eine nachträgliche Veränderung der Kameraposition während eines Wachstumszyklus macht alle vorher aufgenommenen Bilder unvergleichbar und ist ohne Neustart der Messreihe unzulässig. Ein Verschieben der Kamera ist ein dokumentationspflichtiges Ereignis (siehe 8.2).

Die Einbauhöhe **H** (Kamerasensor über Oberkante Pflanzwanne) wird nach dem mechanischen Aufbau einmalig gemessen und auf ±2 mm dokumentiert. Planungswert: **H ≈ 550 mm**.

### 4.2 Erfasstes Bildfeld

Bei H = 550 mm ergibt sich rechnerisch:

- Breite ≈ 2 · 550 · tan(33°) ≈ **714 mm**
- Höhe ≈ 2 · 550 · tan(20,5°) ≈ **411 mm**
- Auflösung ≈ 4608 px / 714 mm ≈ **6,4 px/mm**

Das Bildfeld ist damit größer als die Pflanzfläche; Gehäusewände sind im Bild sichtbar. Das ist gewollt: Der auszuwertende Bereich wird softwareseitig als ROI zugeschnitten (siehe 4.3), und Reserve am Rand verhindert, dass eine seitlich wachsende Pflanze aus dem Bild läuft.

### 4.3 Region of Interest (ROI)

Die ROI wird durch die vier Referenzmarker aufgespannt (siehe 4.4) und umfasst die Pflanzwanne zuzüglich 30 mm Rand. Die ROI wird **nicht** als feste Pixelkoordinate definiert, sondern in jedem Bild aus den erkannten Markern neu berechnet. Damit bleibt die Auswertung auch bei minimaler mechanischer Setzung des Gehäuses stabil.

### 4.4 Referenzmarker und Maßstab

**Ausführung:** Vier ArUco-Marker (Dictionary `DICT_4X4_50`, IDs 0–3), Kantenlänge **40 mm**, an den vier Ecken des Wannenrandes.

ArUco statt einfachem Maßstabsbalken, weil vier Marker gleichzeitig vier Aufgaben lösen:

1. **Maßstab** – Umrechnung Pixel → mm²
2. **Perspektivkorrektur** – Homographie auf die Wannenebene (Pipeline-Schritt 4)
3. **ROI-Definition** – siehe 4.3
4. **Lageüberwachung** – Verschiebt sich die Kamera, verschieben sich die Markerecken; das ist automatisch detektierbar (siehe 8.2)

**Material:** Matter Druck auf Papier oder Kunststoff, **ohne Glanzlaminat**. Glänzende Oberflächen erzeugen unter der LED Reflexe und werden nicht mehr zuverlässig erkannt. Die Markerhöhe **h_M** über der Wannenoberkante wird gemessen und dokumentiert.

### 4.5 Maßstabskorrektur über die Bestandshöhe

**Dies ist der kritischste Punkt der gesamten Bilderfassung.**

Die Marker liegen auf Wannenhöhe, die Blätter wachsen aber auf die Kamera zu. Bei H = 550 mm und einer Bestandshöhe von 250 mm halbiert sich der Objektabstand nahezu – die Pflanze erscheint im Bild deutlich größer, ohne tatsächlich entsprechend gewachsen zu sein. Unkorrigiert entsteht dadurch ein scheinbarer Wachstumsverlauf, der zu einem erheblichen Teil reine Perspektive ist.

Korrektur über das Lochkameramodell:

```
s_M = L_Marker / p_Marker                      [mm/px]  Maßstab in der Markerebene
s_C = s_M · (H − h_C) / (H − h_M)              [mm/px]  Maßstab in der Bestandsebene
A   = N_px · s_C²                              [mm²]    projizierte Blattfläche
```

mit
`L_Marker` = physische Markerkantenlänge (40 mm),
`p_Marker` = gemessene Kantenlänge in Pixel,
`H` = Kamerahöhe über Wannenoberkante,
`h_M` = Markerhöhe über Wannenoberkante,
`h_C` = Bestandshöhe (Canopy),
`N_px` = Anzahl der als Pflanze segmentierten Pixel.

`h_C` wird bis auf Weiteres **manuell** mit Lineal gemessen (mindestens zweimal pro Woche) und in den Metadaten mitgeführt. Zwischen zwei Messungen wird linear interpoliert. Eine automatische Bestandshöhenerfassung (z. B. seitlicher Maßstab im Bild oder ToF-Sensor) ist ein sinnvolles optionales Ziel, aber kein Muss.

Wichtig für die Dokumentation: Da der Maßstab in **jedem** Bild aus den Markern neu bestimmt wird, ist er eine Messgröße und keine Annahme. Ein Nachfokussieren (siehe 5.2) verändert die Abbildung geringfügig, wird durch diese Vorgehensweise aber automatisch mitkorrigiert.

### 4.6 Hintergrund

Die Pflanzwanne erhält eine **matte, nicht spiegelnde Einlage in Dunkelgrau oder Mattschwarz**. Der Hintergrund ist der größte Hebel für eine saubere Segmentierung – deutlich größer als jede Verbesserung des Algorithmus.

In PSP 1.5 wird zusätzlich eine **mattblaue** Variante getestet. Blau liegt im HSV-Farbraum weit von Pflanzengrün entfernt und erhält im Gegensatz zu Schwarz die Zeichnung in dunklen Blattpartien. Die endgültige Wahl erfolgt anhand der Segmentierungsgüte an Testbildern.

---

## 5. Optische Aufnahmeparameter

### 5.1 Grundsatz

**Alle Automatiken werden deaktiviert.** Autofokus, Belichtungsautomatik, Weißabgleichsautomatik und HDR reagieren auf die Bildinhalte – also auf die wachsende Pflanze. Eine Automatik, die auf zunehmende Grünfläche mit anderer Belichtung reagiert, macht Farbmetriken über die Zeit wertlos.

### 5.2 Festgelegte Parameter

| Parameter | Einstellung | Begründung |
|---|---|---|
| Fokus | `AfMode = Manual`, feste `LensPosition` | Autofokus je Aufnahme ändert Schärfe und Abbildung |
| Belichtungszeit | fest, `AeEnable = False` | verhindert Helligkeitsdrift über den Zyklus |
| Analogverstärkung | fest, möglichst niedrig | begrenzt Rauschen |
| Weißabgleich | `AwbEnable = False`, feste `ColourGains` | Greenness-Index hängt direkt vom Weißabgleich ab |
| HDR | deaktiviert | nichtlineare Tonwertabbildung, nicht reproduzierbar |
| Rauschreduktion / Schärfung | minimal und konstant | starke Schärfung erzeugt Kantenartefakte an Blatträndern |
| Auflösung | 4608 × 2592 px (volle Sensorauflösung) | |
| Format | JPEG, Qualität 95 | siehe 7.3 |

Die konkreten Zahlenwerte für `LensPosition`, `ExposureTime`, `AnalogueGain` und `ColourGains` werden bei der Inbetriebnahme einmalig ermittelt und in der Datei `capture_profile.json` abgelegt.

Ausgangswert für den Fokus: `LensPosition ≈ 1,8 dpt` (entspricht 1/0,55 m).

### 5.3 Nachfokussieren

Die Schärfentiefe beträgt bei H = 550 mm rechnerisch nur rund 150 mm. Wächst der Bestand um mehr als 100 mm gegenüber der letzten Fokuseinstellung, muss nachfokussiert werden. Jeder solche Eingriff ist ein **Profiländerungsereignis**: Die Version in `capture_profile.json` wird erhöht, das Ereignis wird protokolliert, und die Versionsnummer steht in den Metadaten jedes Bildes.

---

## 6. Beleuchtungsbedingungen bei der Aufnahme

### 6.1 Aufnahme-Lichtprofil

Die LED wird im Normalbetrieb von der DLI-Regelung gesteuert und ist daher zum Aufnahmezeitpunkt in einem **nicht vorhersehbaren Dimmzustand**. Bilder unter wechselnder Beleuchtung sind farbmetrisch nicht vergleichbar.

Deshalb gilt für jede Aufnahme:

1. LED auf definierten festen Wert setzen (Vorgabe: **100 % Duty**)
2. **60 s** stabilisieren lassen (thermische und elektrische Einschwingzeit der LED)
3. Bild aufnehmen
4. LED an die Regelung zurückgeben

Der tatsächliche LED-Zustand zum Aufnahmezeitpunkt wird in den Metadaten mitgeschrieben. Bilder, deren LED-Duty vom Sollwert abweicht, werden verworfen (siehe 8.1).

**Dies ist eine Schnittstellenanforderung an die Firmware** (siehe 9.1).

### 6.2 Fremdlicht

Die transparente Fronttüre lässt Raumlicht eintreten. Der Anteil variiert mit Tageszeit und Raumbeleuchtung und ist eine bekannte, bewusst akzeptierte Fehlerquelle.

Zur Quantifizierung wird einmal täglich ein **Dunkelreferenzbild** aufgenommen: identische Parameter, LED aus. Die mittlere Helligkeit dieses Bildes ist ein direktes Maß für den Fremdlichtanteil und wird im Langzeittest ausgewertet. Übersteigt sie einen im Test festzulegenden Grenzwert, ist eine Abdunkelung der Fronttüre während der Aufnahme nachzurüsten.

### 6.3 Anordnung LED / Kamera

Die LED-Emitter dürfen **nicht direkt im Bildfeld** der Kamera liegen. Die LED-Bars werden beidseitig neben der Kamera angeordnet, sodass der Bestand symmetrisch ausgeleuchtet wird und einseitige Schlagschatten vermieden werden. Die Kamera erhält eine kurze **Blendschutzhaube**. Auch dies ist eine Anforderung an den mechanischen Aufbau.

---

## 7. Zeitplan, Dateien und Speicherung

### 7.1 Aufnahmeintervall

| Aufnahmeart | Zeitpunkt |
|---|---|
| Regelaufnahme | alle **30 min** während der Lichtphase (16 h → 32 Bilder/Tag) |
| Tagesreferenzbild | 10 min nach Lichtbeginn, nach Stabilisierung |
| Dunkelreferenzbild | 1× täglich, LED aus |

Nachts wird nicht aufgenommen: Blattstellung, Kontrast und Belichtung variieren ohne verwertbaren Zusatznutzen.

### 7.2 Dateinamenskonvention

```
biobox01_20260930T081500Z_000042.jpg
biobox01_20260930T081500Z_000042.json
```

Aufbau: `{device_id}_{ISO8601-UTC}_{laufende Nummer}`. Zeitstempel **immer UTC**, um Sommer-/Winterzeitsprünge in der Zeitreihe zu vermeiden. Bild und Metadatendatei tragen denselben Dateistamm.

Ablage: `/data/images/{JJJJ}/{MM}/{TT}/`

### 7.3 Speicherbedarf

32 Bilder/Tag × ca. 5 MB ≈ **160 MB/Tag**, ca. **4,8 GB/Monat**, über die Projektlaufzeit ca. **30 GB**.

Daraus folgt: Ablage auf externer USB-SSD oder Karte ≥ 128 GB, plus tägliche Sicherung (`rsync`) auf Notebook oder Schulserver. **Nur die Metadaten und Analyseergebnisse gehen in die PostgreSQL-Datenbank, nicht die Bilddateien selbst**; die Datenbank speichert lediglich den `storage_path` und die SHA-256-Prüfsumme.

### 7.4 Metadaten-Sidecar

Jedes Bild erhält eine gleichnamige JSON-Datei:

```json
{
  "device_id": "biobox-01",
  "captured_at": "2026-09-30T08:15:00Z",
  "sequence": 42,
  "capture_profile_version": "1.0.0",
  "image_type": "regular",
  "camera": {
    "model": "imx708",
    "resolution": [4608, 2592],
    "lens_position": 1.8,
    "exposure_time_us": 8000,
    "analogue_gain": 1.0,
    "colour_gains": [1.85, 1.62],
    "hdr": false
  },
  "light": {
    "led_duty_pct": 100,
    "stabilisation_s": 60,
    "photoperiod_state": "day"
  },
  "geometry": {
    "camera_height_mm": 550.0,
    "marker_dict": "DICT_4X4_50",
    "marker_length_mm": 40.0,
    "marker_height_mm": 12.0,
    "canopy_height_mm": 85.0,
    "canopy_height_source": "manual"
  },
  "environment": {
    "air_temp_c": 24.6,
    "air_humidity_pct": 61.2,
    "soil_moisture_pct": 43.8,
    "soil_temp_c": 22.1,
    "light_lux": 21450
  },
  "checksum_sha256": "..."
}
```

Der Block `environment` wird zum Aufnahmezeitpunkt aus der jüngsten Telemetrie übernommen. **Er ist keine Nebensache:** Das Digital-Twin-Modell braucht Bildmerkmale und Umweltbedingungen als zusammengehöriges Paar. Fehlt diese Zuordnung, ist der Datensatz für A-M4 nur eingeschränkt brauchbar.

---

## 8. Qualitätssicherung

### 8.1 Automatische Prüfkriterien je Bild

| Kriterium | Prüfung | Bei Verletzung |
|---|---|---|
| Schärfe | Varianz des Laplace-Filters über der ROI ≥ Schwellwert | verwerfen |
| Belichtung | Anteil geklippter Pixel (Grünkanal > 250) unter Grenzwert | verwerfen |
| Helligkeit | Mittelwert innerhalb ± x % des Tagesreferenzbildes | markieren |
| Marker | alle vier Marker erkannt | verwerfen |
| Kameralage | Markerecken innerhalb ± 3 px zur Referenzaufnahme | **Alarm**, siehe 8.2 |
| LED-Zustand | `led_duty_pct` entspricht Sollwert | verwerfen |
| Profilversion | entspricht aktueller Version | markieren |

Die Schwellwerte werden in PSP 1.8 empirisch bestimmt. Verworfene Bilder werden **nicht gelöscht**, sondern nach `/data/images/rejected/` verschoben und protokolliert – die Ausschussrate ist selbst eine auswertbare Kennzahl für die Dokumentation.

### 8.2 Dokumentationspflichtige Ereignisse

Kameraverschiebung, Nachfokussieren, Parameteränderung, Markerwechsel, Hintergrundwechsel, Umtopfen. Jedes dieser Ereignisse wird mit Zeitstempel, Grund und neuer Profilversion in einem Ereignisprotokoll festgehalten. Ohne dieses Protokoll ist ein Sprung im Flächenverlauf später nicht mehr von echtem Pflanzenverhalten zu unterscheiden.

### 8.3 Abnahmekriterien Meilenstein A-M1

Das Bilderfassungssystem gilt als abgenommen, wenn:

1. über 72 h ununterbrochen automatisch aufgenommen wurde,
2. die Ausschussrate unter 5 % liegt,
3. in allen gültigen Bildern alle vier Marker erkannt wurden,
4. die aus den Markern berechnete Maßstabsgröße über 72 h um weniger als 1 % streut,
5. jedes Bild eine vollständige, valide Metadatendatei besitzt.

Kriterium 4 ist der eigentliche Nachweis: Es belegt, dass der Aufbau geometrisch stabil ist.

---

## 9. Schnittstellen

### 9.1 Anforderungen an Grid Tanushi (Hardware)

| Nr. | Anforderung |
|---|---|
| H-1 | Starrer, mittiger Kameramontagepunkt an der Decke der Wachstumszone, Blickrichtung senkrecht nach unten |
| H-2 | Einbauhöhe H nach Aufbau messen und dokumentieren (±2 mm) |
| H-3 | LED-Bars beidseitig neben der Kamera, keine Emitter im Bildfeld |
| H-4 | Platz für Blendschutzhaube (ca. 20 mm) |
| H-5 | CSI-Kabelführung Kamera → Pi; Kabellänge nach Einbaulage (Standardkabel 200 mm ggf. zu kurz), getrennt von LED- und PWM-Leitungen führen |
| H-6 | 5 V / 3 A Versorgung für den Raspberry Pi 4 auf der 5-V-Schiene |
| H-7 | Firmware: Kommando „Aufnahme-Lichtprofil" – LED auf festen Duty setzen, halten, freigeben |
| H-8 | Firmware: LED-Ist-Duty und aktuelle Sensorwerte auf Abruf für die Metadaten |
| H-9 | Wannenrand als Montagefläche für vier Marker, matte Wanneneinlage |

**Zeitkritisch:** H-1 bis H-4 und H-9 müssen vor dem Aufbau der Wachstumszone geklärt sein (Grid: G1, September/Oktober).

### 9.2 Anforderungen an Edona Peraj (Plattform)

| Nr. | Anforderung |
|---|---|
| E-1 | Endpunkt `POST /api/v1/images/metadata` gemäß Tabelle `images` |
| E-2 | Feldnamen und Datentypen für `image_measurements` einfrieren |
| E-3 | Übernahme von `capture_profile_version` und `canopy_height_mm` in das Datenmodell (im Konzeptentwurf noch nicht enthalten) |
| E-4 | Konvention für `storage_path` gemeinsam festlegen |

---

## 10. Offene Punkte

| Nr. | Punkt | Zu klären bis |
|---|---|---|
| O-1 | Endgültige Kamerahöhe H – erst nach mechanischem Aufbau messbar | Meilenstein B |
| O-2 | Hintergrundfarbe: Dunkelgrau oder Mattblau – Entscheidung nach Segmentierungstest | PSP 1.5 |
| O-3 | Schwellwerte der Qualitätsprüfung – empirisch | PSP 1.8 |
| O-4 | Verfahren zur Bestandshöhenerfassung – vorerst manuell | laufend |
| O-5 | Notwendigkeit einer Abdunkelung der Fronttüre – abhängig von Dunkelreferenzmessung | Langzeittest |
