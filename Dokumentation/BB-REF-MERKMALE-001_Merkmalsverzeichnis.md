# Merkmalsverzeichnis BioBox

| Feld | Stand |
|---|---|
| Dokument-ID | BB-REF-MERKMALE-001 |
| Version | 3.0 |
| Datum | 26.10.2026 |
| Autorin | Atida Ashta |
| Pipeline | analyse.py 4.0.0 |
| Bewertung | Scoring 3.0.0 |

## 1 Ausgabeprinzip

Pro Eingabebild wird genau ein Datensatz erzeugt. Auch eine unlesbare oder nicht auswertbare Datei bleibt mit ihrem Fehlerstatus enthalten. Es werden keine Messwerte durch erfundene Nullen oder einen alten Gesundheitswert ersetzt.

Die Kontrollausgabe heißt `auswertung/ergebnis.csv`. CSV bedeutet Comma-Separated Values, ein tabellarisches Dateiformat. Für deutsche Tabellenprogramme werden hier Semikolon als Trennzeichen, Dezimalkomma und UTF-8 mit Byte Order Mark (BOM, Kennung der Textcodierung) verwendet. Fehlende Werte werden ausdrücklich als `NULL` geschrieben. `True` und `False` sind boolesche Angaben.

`ergebnis.json` verwendet JavaScript Object Notation (JSON), ein strukturiertes Datenaustauschformat. Dort stehen echte Zahlen, boolesche Werte und `null`, keine Dezimalkomma-Zahlen als Text. Beide Ausgaben und die Diagramme werden aus denselben gerundeten Datensätzen aufgebaut. Die spätere Programmierschnittstelle, Application Programming Interface (API), muss deshalb keine CSV-Datei einlesen.

## 2 Spalten und Zuordnung

Die folgende Tabelle wird aus der aktuellen Feldzuordnung ergänzt. Die Namen in der ersten Spalte sind die tatsächlichen CSV-Überschriften. `image_measurements` und `health_assessment` bezeichnen die entsprechenden Objekte im JSON-Export, noch keinen bestätigten HTTP-Endpunkt.

| CSV-Spalte | Einheit | Bedeutung | JSON-Zuordnung |
|---|---|---|---|
| `bild` | Text | Dateiname mit Endung | `image.file_name` |
| `captured_at` | UTC | Expliziter Aufnahmezeitpunkt, sonst unbekannt | `image.captured_at` |
| `zeitquelle` | Text | name oder unbekannt; kein Dateidatum als Ersatz | `analysis.capture_time_source` |
| `stunden_seit_start` | h | Abstand zur festen Referenzzeit, sonst zum ersten bekannten Zeitpunkt der Auswahl | `aus Aufnahme- und Referenzzeit ableitbar` |
| `pflanzen_pixel` | Pixelanzahl | Weiße Pixel der endgültigen Blattmaske | `image_measurements.plant_pixels` |
| `blattflaeche_cm2` | cm² | Sichtbare projizierte Fläche bei verifiziertem Maßstab | `image_measurements.leaf_area_cm2` |
| `durchmesser_mm` | mm | Größte Ausdehnung der maskierten Pixeloberfläche | `image_measurements.diameter_mm` |
| `kompaktheit` | ohne Einheit | 4 pi A / U²; geometrischer Prüfwert | `image_measurements.compactness` |
| `wachstumsrate_cm2_pro_tag` | cm²/Tag | Differenz eines vergleichbaren Bildpaars, zeitlich normiert | `image_measurements.growth_rate_cm2_per_day` |
| `wachstumsrate_pct_pro_tag` | %/Tag | Relative Flächenänderung eines vergleichbaren Bildpaars | `image_measurements.growth_rate_pct_per_day` |
| `mittel_r` | 0–255 | Mittlerer roter Rohkanal über der Maske | `image_measurements.mean_r` |
| `mittel_g` | 0–255 | Mittlerer grüner Rohkanal über der Maske | `image_measurements.mean_g` |
| `mittel_b` | 0–255 | Mittlerer blauer Rohkanal über der Maske | `image_measurements.mean_b` |
| `farbe_hex` | Text | Mittlere Rohfarbe als #RRGGBB | `image_measurements.color_hex` |
| `mittel_h` | 0 bis unter 180 | Kreisförmig gemittelter HSV-Farbton | `image_measurements.mean_hue` |
| `mittel_s` | 0–255 | Mittlere HSV-Sättigung der Rohfarben | `image_measurements.mean_saturation` |
| `gruenindex` | 0–1 | Mittelwert des normierten Grünanteils G/(R+G+B) | `image_measurements.greenness_index` |
| `gelbanteil_pct` | % | Anteil der technischen gelben Farbklasse, Rohwert | `image_measurements.yellow_fraction_pct` |
| `braunanteil_pct` | % | Anteil der technischen braunen Farbklasse, Rohwert | `image_measurements.brown_fraction_pct` |
| `mm_pro_pixel` | mm/Pixel | Verifizierter Maßstab in der Blattebene | `image_measurements.mm_per_px` |
| `massstab_quelle` | Text | manuell_blattebene, lineal_blattebene oder aruco_hoehenkorrigiert | `image_measurements.scale_source` |
| `schaerfe` | Prüfwert | Laplace-Varianz des Originalbilds über den Blattpixeln | `image_measurements.sharpness` |
| `rauschen` | Prüfwert | Rauschschätzung am Originalbild | `image_measurements.noise` |
| `bildhelligkeit` | 0–255 | Grauwertmittel des gesamten Originalbilds | `image_measurements.image_brightness` |
| `ueberbelichtet_pct` | % | Blattpixel mit mindestens einem RGB-Kanal ab 254 | `image_measurements.overexposed_pct` |
| `groesste_komponente_pct` | % | Größte zusammenhängende Blattteilfläche / Gesamtmaske | `image_measurements.largest_component_pct` |
| `auffaelligkeit` | Text | Qualitätsmeldungen, mit Semikolon getrennt | `image_measurements.quality_flags` |
| `brauchbar` | boolesch | Grundlegende Bild-/Maskenqualität erfüllt | `image_measurements.usable` |
| `pipeline_version` | Text | Version von Segmentierung und Messverfahren | `image_measurements.pipeline_version` |
| `scoring_version` | Text | Version der Bewertungsregeln | `health_assessment.scoring_version` |
| `gesundheit` | 0–100 | Zeitlich geglätteter relativer Index | `health_assessment.health_score` |
| `gesundheit_roh` | 0–100 | Unglättete Bewertung dieser Aufnahme | `health_assessment.health_score_raw` |
| `gesundheit_kategorie` | Text | Technischer Bereich des relativen Index | `health_assessment.health_category` |
| `gesundheit_status` | Text | Verfügbarkeit und Referenzstatus des Index | `health_assessment.health_status` |
| `gesundheit_trend_24h` | Scorepunkte | Differenz zu einem gültigen Vergleich vor 22–26 Stunden | `health_assessment.health_trend_24h` |
| `gesundheitswarnung` | Text | Beobachtete Veränderungen, mit Semikolon getrennt | `health_assessment.health_warnings` |
| `score_gruen` | 0–100 | Relative Farbverteilung und normierter Grünanteil | `health_assessment.score_green` |
| `score_gelb` | 0–100 | Zunahme der gemeinsamen Gelb-/Braunfläche | `health_assessment.score_yellow` |
| `score_braun` | 0–100 | Zusätzliche Braun-/Warmfärbung | `health_assessment.score_brown` |
| `score_saettigung` | 0–100 | Änderung der Farbsättigung nach Lichtkorrektur | `health_assessment.score_saturation` |
| `score_farbton` | 0–100 | Farbton- und Lab-Farbänderung nach Lichtkorrektur | `health_assessment.score_hue` |

## 3 Bedeutung der wichtigsten Messwerte

### Fläche und Ausdehnung

`pflanzen_pixel` zählt weiße Pixel der endgültigen Blattmaske. Es wird keine Fläche des Topfes oder eine konvexe Hülle der gesamten Pflanze gemessen. Für `blattflaeche_cm2` wird mit dem Quadrat des verifizierten Millimeter-pro-Pixel-Maßstabs umgerechnet. `durchmesser_mm` ist die größte Ausdehnung der maskierten Pixeloberfläche einschließlich der äußeren Pixelgrenzen.

Ohne passenden Maßstab bleiben die physischen Werte `NULL`. Eine gültige Pixelmaske kann trotzdem ausgewertet werden. Eine nicht erkannte Blattmaske ist kein Nachweis dafür, dass biologisch keine Pflanze vorhanden ist. Bei unlesbaren Bildern bleibt sogar die Pixelzahl unbekannt.

`kompaktheit` wird aus `4 × pi × Fläche / Umfang²` berechnet. Die Umfänge der erfassten Blattbereiche und vorhandener innerer Lücken werden berücksichtigt. Eine Änderung kann auf eine andere Blattstellung oder eine andere Maske zurückgehen und ist keine sichere Diagnose einer Welke.

`groesste_komponente_pct` ist ein geometrisches Prüfmerkmal. Mehrere getrennt sichtbare Blätter sind normal. Ein kleiner Wert führt deshalb nicht pauschal zum Ausschluss der Pflanze.

### Farbe

RGB bedeutet Rot, Grün und Blau. Die RGB-Mittelwerte, der Farbton, die Sättigung sowie Gelb- und Braunanteil in der CSV werden am Originalfoto über der endgültigen Maske gemessen. Sie sind **Rohwerte und lichtabhängig**. Der Gesundheitsvergleich verwendet zusätzlich eine aus dem Hintergrund ermittelte Lichtkorrektur; die Rohmessung wird dadurch nicht überschrieben.

HSV bedeutet Hue, Saturation, Value, also Farbton, Sättigung und Helligkeit. Der Farbton wird kreisförmig gemittelt. Bei zu wenig Farbsignal kann `mittel_h` fehlen. Der Grünindex ist der gemittelte normierte Anteil `G / (R + G + B)` der Blattpixel. Er ist keine direkte Messung des Chlorophyllgehalts.

Die Gelb- und Braunanteile sind technische Farbklassen. Sie beweisen für sich keine Chlorose oder Nekrose. `farbe_hex` ist nur die lesbare Darstellung der mittleren RGB-Farbe als `#RRGGBB` und wird nicht als zusätzliche unabhängige Zustandsmessung gewichtet.

### Zeit und Wachstum

Zeitstempel werden aus einem expliziten Aufnahmezeitpunkt im Dateinamen gelesen und in Coordinated Universal Time (UTC, koordinierte Weltzeit) angegeben. Ein Download- oder Änderungsdatum wird nicht als Aufnahmezeit verwendet.

`stunden_seit_start` wird bei bekannter Referenzzeit auf diese feste Zeit bezogen. Das Entfernen alter Bilder aus dem 100-Bilder-Fenster setzt den Beginn nicht auf null zurück. Ohne bekannte Referenzzeit wird die erste bekannte Zeit der aktuellen Auswahl verwendet.

Eine Wachstumsrate wird nur für aufeinanderfolgende brauchbare und geometrisch vergleichbare Aufnahmen berechnet. Der Zeitabstand wird berücksichtigt. Bei großen Flächensprüngen über 50 % werden die Raten zunächst weggelassen und die Aufnahme markiert. Nach einer Kameraverschiebung kann die Rate bei einem nachfolgenden wieder stabilen Bildpaar erneut berechnet werden.

Die Einheit pro Tag ist eine zeitliche Umrechnung, keine über einen ganzen Tag beobachtete Entwicklung. Bei kurzen Abständen können kleine Masken- oder Blattstellungsänderungen große hochgerechnete Raten ergeben. Eine einzelne Rate darf deshalb nicht als gesichertes biologisches Wachstum interpretiert werden.

### Qualität und Zustand

`brauchbar` beschreibt die grundlegende Bild- und Maskenqualität. Ein Maßstab ist dafür keine Pflicht. Ein wahrer Wert bedeutet auch nicht, dass jede zeitliche oder farbliche Vergleichsgröße verfügbar sein muss. Beispielsweise können Pixelwerte brauchbar sein, während ein verlässlicher Lichtvergleich fehlt.

`schaerfe` und `rauschen` sind Rohmessungen. Für die Entscheidung über die Schärfe wird bei erfolgreichem Lichtabgleich eine normalisierte Arbeitskopie verwendet. `ueberbelichtet_pct` zählt Blattpixel, bei denen mindestens ein RGB-Kanal 254 erreicht. Dies ist nicht identisch mit dem für den Farbvergleich ausgeschlossenen Anteil, da dort beide Aufnahmen und ein kleiner Rand betrachtet werden.

`gesundheit_status` erklärt die Verfügbarkeit des relativen Index. Eine automatische Referenz wird als vorläufig gekennzeichnet, aber nicht wegen einer fehlenden biologischen Kalibrierung vollständig gesperrt. Eine fehlende physische Längenreferenz verhindert ebenfalls keine reine Farbbewertung.

## 4 Fehlende Werte und Meldungen

| Situation | Ergebnis |
|---|---|
| Datei nicht lesbar | Datensatz mit `nicht_lesbar`, Messwerte unbekannt |
| keine ausreichende Blattmaske | `keine_blattmaske`, kein neuer Score |
| Bild zu unscharf oder zu verrauscht | Qualitätsmeldung, kein neuer gültiger Score |
| kein Maßstab | Pixel- und Farbwerte möglich, cm²/mm fehlen |
| Zeit unbekannt | Einzelmessungen möglich, zeitabhängige Angaben fehlen |
| Referenz oder Lichtabgleich ungeeignet | Erklärung im Status, keine erfundene Bewertung |
| verschiedene Pflanzen mit `--einzelbilder` | keine gemeinsame Gesundheits- oder Wachstumszeitreihe |
| CSV gerade in Excel gesperrt | vorhandene CSV bleibt erhalten; JSON und Diagramme werden aktualisiert |

Mehrere Qualitätsmeldungen werden mit Semikolon getrennt. Der CSV-Schreiber setzt die nötigen Anführungszeichen, damit dadurch keine Spalten verschoben werden. Ein Hinweis wie `blatt_am_bildrand` ist eine Auffälligkeit, aber nicht allein ein Beweis für eine unbrauchbare Farbaufnahme.

## 5 JSON-Struktur für die Übergabe

- `device_id`: vorhandener Plattformschlüssel; bis zur echten Zuordnung `null`.
- `image`: Dateiname mit Endung, Aufnahmezeit, relativer Bildpfad und SHA-256-Prüfsumme. SHA-256 bedeutet Secure Hash Algorithm mit 256 Bit und dient hier zur eindeutigen Prüfung der Dateiinhalte.
- `image_measurements`: Bildmesswerte mit den vereinbarten englischen Feldnamen.
- `health_assessment`: Score, Kategorie, Teilbewertungen, Status und Scoring-Version.
- `analysis`: Herkunft der Maske, Maßstabsstatus, Objektivstatus, Referenzdatei und -zeit, Lichtkorrektur und Gründe für fehlende Werte.

`mm_per_px`, `image_brightness`, `largest_component_pct`, `color_hex` und `pipeline_version` entsprechen den bekannten Projektfeldnamen. Die früher verwendeten Aliasnamen `mm_per_pixel` und `brightness` werden nicht zusätzlich als doppelte Messwerte ausgegeben. Die genauen Datenbank-IDs und der HTTP-Vertrag sind weiterhin abzugleichen.

## 6 Diagramme und Dateien

Alle Schritte sind in `analyse.py` enthalten. Es werden keine getrennten Module `gesundheit.py` oder `grafiken.py` benötigt.

| Datei unter `auswertung/grafiken/` | Inhalt |
|---|---|
| `01_wachstum.png` | sichtbare Blattfläche, mit cm² bei gültigem Maßstab, sonst Pixel |
| `02_wachstumsrate.png` | verfügbare Wachstumsraten vergleichbarer Bildpaare |
| `03_farbverlauf.png` | gemessene Rohfarben und Farbanteile; ausdrücklich lichtabhängig |
| `04_gesundheit.png` | relative Bewertung vor und nach zeitlicher Glättung |
| `05_teilscores.png` | letzte auswertbare Teilbewertungen mit identifizierter Aufnahme |

Die fünf Dateien werden auch dann erzeugt, wenn einzelne Daten fehlen. Fehlende Daten werden erklärt und nicht als Nullkurve erfunden. Masken und einzelne Kontrollansichten liegen in `masken/` und `kontrolle/`. Eine manuell gespeicherte Maske wird separat unter `masken_korrektur/` erhalten.

Blattanzahl, Pflanzenhöhe und eine absolute biologische Gesundheitswahrscheinlichkeit werden nicht zusätzlich erfunden. Die tatsächliche Datenquelle bleibt das Originalfoto mit der finalen sichtbaren Blattmaske.
