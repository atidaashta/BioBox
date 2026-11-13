# BioBox · Computer-Vision-Pipeline und Merkmalsverzeichnis

| Feld | Stand |
|---|---|
| Dokument-ID | BB-REF-MERKMALE-001 |
| Meilenstein | A-M2 · Computer-Vision-Pipeline |
| Version | 3.15 |
| Datum | 13.11.2026 |
| Autorin | Atida Ashta |
| Pipeline | computer_vision_pipeline.py 4.13.0 |
| Bewertung | Scoring 4.1.0 |

## 1 Ausgabeprinzip

Wenn eine Aufnahme sowohl im JSON als auch in der CSV gespeichert ist, werden für die Historie die Messwerte aus JSON verwendet. Fehlende Blattdeckung, metrische Maße und Farbcodes werden nur aus den dafür nötigen gespeicherten Messwerten derselben Aufnahme ergänzt. CSV-Einträge ohne entsprechendes JSON werden weiter gelesen. Optionale Blattkonturen für den Browser werden separat berechnet; ein Fehler dabei verwirft die vorhandenen Messwerte nicht.

Aus jedem Eingabebild wird ein Datensatz mit Messwerten oder einem Fehlerstatus erzeugt. Die Ausgabe verbindet diese Datensätze mit den bereits gespeicherten Aufnahmen. Kann ein bereits brauchbar ausgewertetes Foto bei einem späteren Lauf nicht mehr gelesen oder analysiert werden, kann sein gespeicherter Datensatz erhalten bleiben. Unbekannte Messwerte werden nicht mit 0 aufgefüllt.

Die Kontrollausgabe heißt `auswertung/ergebnis.csv`. CSV bedeutet Comma-Separated Values, ein tabellarisches Dateiformat. Für deutsche Tabellenprogramme werden hier Semikolon als Trennzeichen, Dezimalkomma und UTF-8 mit Byte Order Mark (BOM, Kennung der Textcodierung) verwendet. Fehlende Werte werden ausdrücklich als `Nicht verfügbar` geschrieben. Der Grund steht in `fehlende_werte`. `True` und `False` sind boolesche Angaben.

`ergebnis.json` verwendet JavaScript Object Notation (JSON), ein strukturiertes Datenaustauschformat. Dort stehen echte Zahlen und boolesche Werte. Nicht verfügbare Felder werden ausgelassen; Gründe für fehlende fachliche Werte stehen in `analysis.missing_values`. Dezimalkomma-Zahlen werden nicht als Text geschrieben. Beide Ausgaben und die Diagramme werden aus denselben gerundeten Datensätzen aufgebaut. Die spätere Programmierschnittstelle, Application Programming Interface (API), muss deshalb keine CSV-Datei einlesen.

## 2 Spalten und Zuordnung

Die Tabelle enthält die 52 Standardspalten in der Reihenfolge von `SPALTEN` in `computer_vision_pipeline.py` 4.13.0. Beim Einlesen älterer CSV-Dateien können vorhandene Zusatzspalten am Ende erhalten bleiben. `image_measurements` und `health_assessment` sind Objekte des JSON-Exports. Die Übernahme per HTTP ist getrennt abzustimmen.

| CSV-Spalte | Einheit | Bedeutung | JSON-Zuordnung |
|---|---|---|---|
| `bild` | Text | Dateiname mit Endung | `image.file_name` |
| `captured_at` | UTC | Expliziter Aufnahmezeitpunkt, sonst unbekannt | `image.captured_at` |
| `zeitquelle` | Text | `name`, `exif_mit_offset` oder `unbekannt`; in `--einzelbilder` unbekannt | `analysis.capture_time_source` |
| `stunden_seit_start` | h | Abstand zur Hauptreferenz dieses Laufs, sonst zur ersten bekannten Aufnahmezeit | `analysis.hours_since_start` |
| `pflanzen_pixel` | Pixelanzahl | Weiße Pixel der endgültigen Blattmaske | `image_measurements.plant_pixels` |
| `blattanteil_im_bild_pct` | % | Blattpixel / gesamte Bildpixel × 100 | `analysis.pixel_measurement.leaf_coverage_pct` |
| `blattpixel_aenderung_pro_tag` | Pixel/Tag | Direkte Pixeländerung bei gleicher Auflösung, ohne geometrische Prüfung | `analysis.pixel_measurement.visible_pixel_change_per_day` |
| `pixel_vergleichsfoto` | Text | Ältere Aufnahme zur direkten Pixeländerung | `analysis.pixel_measurement.reference_file` |
| `blattflaeche_cm2` | cm² | Sichtbare projizierte Fläche bei verifiziertem Maßstab | `image_measurements.leaf_area_cm2` |
| `durchmesser_mm` | mm | Größte Ausdehnung der maskierten Pixeloberfläche | `image_measurements.diameter_mm` |
| `kompaktheit` | ohne Einheit | 4 pi A / U²; geometrischer Prüfwert | `image_measurements.compactness` |
| `wachstumsrate_cm2_pro_tag` | cm²/Tag | Differenz eines vergleichbaren Bildpaars, zeitlich normiert | `image_measurements.growth_rate_cm2_per_day` |
| `wachstumsrate_pct_pro_tag` | %/Tag | Relative Flächenänderung eines vergleichbaren Bildpaars | `image_measurements.growth_rate_pct_per_day` |
| `wachstum_vergleichsfoto` | Text | Ältere Aufnahme zur geometrisch geprüften Rate | `analysis.growth_reference_file` |
| `wachstum_abstand_stunden` | h | Zeitabstand des geometrisch geprüften Bildpaars | `analysis.growth_interval_hours` |
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
| `massstab_quelle` | Text | Gültige Maßstabsquelle oder Grund für fehlenden Maßstab, z. B. `nicht_kalibriert` | `image_measurements.scale_source` |
| `schaerfe` | Prüfwert | Laplace-Varianz des Originalbilds über den Blattpixeln | `image_measurements.sharpness` |
| `rauschen` | Prüfwert | Rauschschätzung am Originalbild | `image_measurements.noise` |
| `bildhelligkeit` | 0–255 | Grauwertmittel des gesamten Originalbilds | `image_measurements.image_brightness` |
| `ueberbelichtet_pct` | % | Blattpixel mit mindestens einem RGB-Kanal ab 254 | `image_measurements.overexposed_pct` |
| `groesste_komponente_pct` | % | Größte zusammenhängende Blattteilfläche / Gesamtmaske | `image_measurements.largest_component_pct` |
| `auffaelligkeit` | Text | Qualitätsmeldungen, mit Semikolon getrennt | `image_measurements.quality_flags` |
| `brauchbar` | boolesch | Grundlegende Bild-/Maskenqualität erfüllt | `image_measurements.usable` |
| `fehlende_werte` | Text | Gruppierte Gründe für fehlende Werte | `analysis.missing_values`, als Objekt mit Feld → Grund |
| `pipeline_version` | Text | Version von Segmentierung und Messverfahren | `image_measurements.pipeline_version` |
| `scoring_version` | Text | Version der Bewertungsregeln | `health_assessment.scoring_version` |
| `gesundheit` | 0–100 | Zeitlich geglätteter relativer Index | `health_assessment.health_score` |
| `gesundheit_roh` | 0–100 | Unglättete Bewertung dieser Aufnahme | `health_assessment.health_score_raw` |
| `gesundheit_kategorie` | Text | Technischer Bereich des relativen Index | `health_assessment.health_category` |
| `gesundheit_status` | Text | Verfügbarkeit und Referenzstatus des Index | `health_assessment.health_status` |
| `gesundheit_trend_24h` | Scorepunkte | Differenz zu einem gültigen Vergleich im gleichen Bewertungsmodus vor 22–26 Stunden | `health_assessment.health_trend_24h` |
| `gesundheitswarnung` | Text | Beobachtete Veränderungen, mit Semikolon getrennt | `health_assessment.health_warnings` |
| `ansicht` | Ganzzahl | Ansichtsnummer innerhalb des Laufs; keine dauerhafte Geräte-ID | `analysis.view_number`; `analysis.view_id` enthält zusätzlich den Referenzhash |
| `gesundheit_referenzfoto` | Text | Referenzfoto der jeweiligen Kameraansicht | `analysis.reference_file` |
| `score_gruen` | 0–100 | Farbverteilung, normierter Grünanteil und lokale Lab-Farbabweichung | `health_assessment.score_green` |
| `score_gelb` | 0–100 | Positive Zunahme des Gelb-/Warmindikators an gemeinsamen Blattpositionen oder in geprüften Blattfarbverteilungen | `health_assessment.score_yellow` |
| `score_braun` | 0–100 | Zusätzliche Braun-/Warmfärbung | `health_assessment.score_brown` |
| `score_saettigung` | 0–100 | Änderung der Farbsättigung nach Lichtkorrektur | `health_assessment.score_saturation` |
| `score_farbton` | 0–100 | Farbton- und Lab-Farbänderung nach Lichtkorrektur | `health_assessment.score_hue` |
| `durchmesser_px` | Pixel | Größter Abstand über die Blattmaske; benötigt keinen Maßstab | `analysis.leaf_diameter_px` |
| `sichtbare_blaetter` | Anzahl | Erkannte oder manuell beschriftete sichtbare Blätter | `analysis.leaf_geometry.count` |
| `blattzaehlung_quelle` | Text | `estimated` für Schätzung oder `manual` für manuelle Beschriftung | `analysis.leaf_geometry.method` |

## 3 Bedeutung der wichtigsten Messwerte

### Von der Aufnahme zur Messung

Das Foto wird eingelesen und bei passender Objektivkalibrierung entzerrt. Die Blattmaske wird aus Farbinformationen im CIELAB-Farbraum, geprüften Bildvergleichen und einer Randverfeinerung gebildet. Eine manuelle Korrektur wird nur für das passende Original mit passendem Objektivprofil übernommen. Die finale Maske bestimmt, welche Pixel für Fläche und Farbe gezählt werden. In `kontrolle/` wird ihre Kontur auf dem Foto sichtbar gemacht. Details zu Kamera und Maskenkorrektur stehen in [A-M1](BB-SPEC-IMG-001_A-M1_Bilderfassungssystem.md).

### Fläche und Ausdehnung

`pflanzen_pixel` zählt weiße Pixel der endgültigen Blattmaske. Es wird keine Fläche des Topfes oder eine konvexe Hülle der gesamten Pflanze gemessen. Für `blattflaeche_cm2` wird mit dem Quadrat des verifizierten Millimeter-pro-Pixel-Maßstabs umgerechnet. `durchmesser_mm` ist die größte Ausdehnung der maskierten Pixeloberfläche einschließlich der äußeren Pixelgrenzen.

Ohne passenden Maßstab bleiben die physischen Werte `—`. Eine gültige Pixelmaske kann trotzdem ausgewertet werden. Eine nicht erkannte Blattmaske ist kein Nachweis dafür, dass biologisch keine Pflanze vorhanden ist. Bei unlesbaren Bildern bleibt sogar die Pixelzahl unbekannt.

`kompaktheit` wird aus `4 × pi × Fläche / Umfang²` berechnet. Die Umfänge der erfassten Blattbereiche und vorhandener innerer Lücken werden berücksichtigt. Eine Änderung kann auf eine andere Blattstellung oder eine andere Maske zurückgehen und ist keine sichere Diagnose einer Welke.

`groesste_komponente_pct` ist ein geometrisches Prüfmerkmal. Mehrere getrennt sichtbare Blätter sind normal. Ein kleiner Wert führt deshalb nicht pauschal zum Ausschluss der Pflanze.

### Farbe

RGB bedeutet Rot, Grün und Blau. Die RGB-Mittelwerte, der Farbton, die Sättigung sowie Gelb- und Braunanteil werden über der endgültigen Maske am Foto gemessen, gegebenenfalls nach der geometrischen Entzerrung. Sie sind **Rohwerte und lichtabhängig**. Der Gesundheitsvergleich verwendet zusätzlich eine aus dem Hintergrund ermittelte Lichtkorrektur; die Rohmessung wird dadurch nicht überschrieben.

HSV bedeutet Hue, Saturation, Value, also Farbton, Sättigung und Helligkeit. Der Farbton wird kreisförmig gemittelt. Bei zu wenig Farbsignal kann `mittel_h` fehlen. Der Grünindex ist der gemittelte normierte Anteil `G / (R + G + B)` der Blattpixel. Er ist keine direkte Messung des Chlorophyllgehalts.

Die Gelb- und Braunanteile sind technische Farbklassen. Sie beweisen für sich keine Chlorose oder Nekrose. `farbe_hex` ist nur die lesbare Darstellung der mittleren RGB-Farbe als `#RRGGBB` und wird nicht als zusätzliche unabhängige Zustandsmessung gewichtet.

### Zeit und Wachstum

Zeitstempel werden aus einem expliziten Aufnahmezeitpunkt im Dateinamen oder aus EXIF-Fotometadaten mit Zeitzonenoffset gelesen und in Coordinated Universal Time (UTC, koordinierte Weltzeit) angegeben. Ein Download- oder Änderungsdatum wird nicht als Aufnahmezeit verwendet.

`stunden_seit_start` wird auf die bekannte Zeit der Hauptreferenz des aktuellen Laufs bezogen, sonst auf den ersten bekannten Zeitpunkt der aktuellen Auswahl. Automatische Referenzen bestehen nur im Arbeitsspeicher. Wenn frühere Bilder aus dem 100-Bilder-Fenster ausscheiden, kann sich der Bezugspunkt bei der nächsten Neuberechnung verschieben. Die Spalte ist deshalb keine dauerhaft fortlaufende Pflanzen-Lebenszeit. Unterschiedliche Kameraansichten haben zusätzlich ihre eigene `analysis.reference_captured_at`.

Eine Rate der sichtbaren Blattfläche wird ab 30 Minuten Abstand bestimmt, wenn beide Aufnahmen brauchbar sind und die Kameraansicht vergleichbar ist. Vergleiche ab zwölf Stunden werden bevorzugt. Kürzere Abstände werden gekennzeichnet. Bei kleinen, nachweislich ausrichtbaren Änderungen können beide Blattmasken im gemeinsamen Bildausschnitt verglichen werden. In diesen Vergleichen müssen mindestens 88 % der jeweiligen Blattmasken im gemeinsamen Ausschnitt bleiben. Deutlich abweichende Kameraansichten werden getrennt. Flächensprünge über 50 % werden als prüfbedürftig markiert.

Die geprüfte relative Rate verwendet die Differenz der vergleichbaren Flächen geteilt durch die ältere Fläche und den Zeitabstand in Tagen, multipliziert mit 100. Für die absolute Rate in cm²/Tag wird zusätzlich ein gemeinsamer gültiger Maßstab benötigt. Die direkte Pixeländerung in `blattpixel_aenderung_pro_tag` ergibt sich aus der Pixelzahldifferenz und dem Zeitabstand bei gleicher Auflösung. Sie wird getrennt angezeigt, weil Kamerabewegung und Blattstellung sie ebenfalls verändern können.

Die Einheit pro Tag ist eine zeitliche Umrechnung, keine über einen ganzen Tag beobachtete Entwicklung. Bei kurzen Abständen können kleine Masken- oder Blattstellungsänderungen große hochgerechnete Raten ergeben. Eine einzelne Rate darf deshalb nicht als gesichertes biologisches Wachstum interpretiert werden.

### Qualität und Zustand

`brauchbar` beschreibt die grundlegende Bild- und Maskenqualität. Ein Maßstab ist dafür keine Pflicht. Ein wahrer Wert bedeutet auch nicht, dass jede zeitliche oder farbliche Vergleichsgröße verfügbar sein muss. Beispielsweise können Pixelwerte brauchbar sein, während ein verlässlicher Lichtvergleich fehlt.

`schaerfe` und `rauschen` sind Rohmessungen. Für die Entscheidung über die Schärfe wird bei erfolgreichem Lichtabgleich eine normalisierte Arbeitskopie verwendet. `ueberbelichtet_pct` zählt Blattpixel, bei denen mindestens ein RGB-Kanal 254 erreicht. Dies ist nicht identisch mit dem für den Farbvergleich ausgeschlossenen Anteil, da dort beide Aufnahmen und ein kleiner Rand betrachtet werden.

`gesundheit_status` erklärt die Verfügbarkeit des relativen Index. Eine automatische Referenz wird als vorläufig gekennzeichnet, aber nicht wegen einer fehlenden biologischen Kalibrierung vollständig gesperrt. Eine fehlende physische Längenreferenz verhindert ebenfalls keine reine Farbbewertung.

## 4 Fehlende Werte und Meldungen

Bekannte Aufnahmezeiten können über `--aufnahmezeiten` aus einer CSV mit den Spalten `bild;captured_at` übernommen werden. Die Uhrzeit muss eine Zeitzone enthalten. Ohne Maßstab kann eine gültige Blattmaske in Pixeln vermessen werden. Physische Maße oder ein fehlender Vergleichswert werden nicht geschätzt.

| Situation | Ergebnis |
|---|---|
| Datei nicht lesbar | Status `datei_nicht_lesbar`, Qualitätsmeldung `nicht_lesbar`, Messwerte unbekannt |
| keine ausreichende Blattmaske | `keine_blattmaske`, kein neuer Score |
| Bild zu unscharf oder zu verrauscht | Qualitätsmeldung, kein neuer gültiger Score |
| kein Maßstab | Pixel- und Farbwerte möglich, cm²/mm fehlen |
| Zeit unbekannt | Einzelmessungen möglich, zeitabhängige Angaben fehlen |
| Referenz oder Lichtabgleich ungeeignet | Erklärung im Status; ein Score wird nur bei einem gültigen Vergleich gespeichert |
| verschiedene Pflanzen mit `--einzelbilder` | keine gemeinsame Gesundheits- oder Wachstumszeitreihe |
| Pi-Abruf mit Timeout oder anderem Fehler, lokale Bilder vorhanden | Alle lokalen Bilder werden trotzdem neu analysiert; kein Gesundheitsabschlag wegen der Verbindung. |
| Keine lokalen Bilder vorhanden | Vorhandene Auswertung bleibt erhalten. |
| Referenzaufnahme einer Ansicht | Status `referenzfoto_start_der_ansicht`; Score und Teilwerte `—`; im Diagramm Referenzmarke bei 100. |
| CSV oder andere Ausgabedatei gesperrt | Vorherige Ausgabe wird wiederhergestellt; bei blockierter Wiederherstellung bleibt eine Sicherung am gemeldeten Pfad. |

Mehrere Qualitätsmeldungen werden mit Semikolon getrennt. Der CSV-Schreiber setzt die nötigen Anführungszeichen, damit dadurch keine Spalten verschoben werden. Ein Hinweis wie `blatt_am_bildrand` ist eine Auffälligkeit und verhindert den Strukturvergleich dieser Aufnahme. Ein Farbvergleich kann bei ausreichender Überlappung weiterhin möglich sein.

## 5 JSON-Struktur für die Übergabe

- `device_id`: vorhandener Plattformschlüssel; bis zur echten Zuordnung ausgelassen.
- `image`: Dateiname mit Endung, Aufnahmezeit, relativer Bildpfad und SHA-256-Prüfsumme. SHA-256 bedeutet Secure Hash Algorithm mit 256 Bit und dient hier zur eindeutigen Prüfung der Dateiinhalte.
- `image_measurements`: Bildmesswerte mit den in der Tabelle aufgeführten englischen Feldnamen.
- `health_assessment`: Score, Kategorie, Teilbewertungen, Status und Scoring-Version.
- `analysis`: Herkunft der Maske, Maßstabsstatus, Objektivstatus, Referenzdatei und -zeit, Lichtkorrektur, Anteil des gemeinsamen Blattgewebes (`illumination.common_leaf_pct`, bezogen auf die kleinere Rand-bereinigte Maske) und Gründe für fehlende Werte. `pipeline_sha256` kennzeichnet den gemeinsamen Stand der vier Meilensteindateien und ist ein technisches Herkunftsmerkmal, kein zusätzlicher Pflanzenmesswert.

`mm_per_px`, `image_brightness`, `largest_component_pct`, `color_hex` und `pipeline_version` entsprechen den bekannten Projektfeldnamen. Die früher verwendeten Aliasnamen `mm_per_pixel` und `brightness` werden nicht zusätzlich als doppelte Messwerte ausgegeben. Die genauen Datenbank-IDs und der HTTP-Vertrag sind weiterhin abzugleichen.

Bei erkannten Pi-Importen wird `image.storage_path` aus dem Sitzungsnamen als `recent/<Sitzung>/normal.jpg` abgeleitet. Bei anderen lokalen Bildern wird dieser Pfad ausgelassen, bis ein tatsächlicher Serverpfad zugeordnet ist. `analysis.missing_values` nennt dafür den Grund. `analysis.growth_comparison_mode` ist nur bei einer berechneten geometrisch geprüften Rate gesetzt; andernfalls steht der Grund unter `missing_values` beim jeweiligen Ratenfeld.

### Angaben zum Bildvergleich

| CSV-Feld | Bedeutung |
|---|---|
| `blattanteil_im_bild_pct` | Blattpixel geteilt durch die Pixelzahl des Bildes, in Prozent |
| `blattpixel_aenderung_pro_tag` | Direkte Differenz der Blattpixel je Tag bei gleicher Auflösung; kann sich auch durch die Ansicht ändern |
| `pixel_vergleichsfoto` | Älteres Foto zur direkten Pixeländerung |
| `wachstum_vergleichsfoto`, `wachstum_abstand_stunden` | Älteres Foto und Zeitabstand der geometrisch geprüften Rate |
| `ansicht`, `gesundheit_referenzfoto` | Ansichtsnummer in dieser Auswertung und zugehöriges Referenzfoto |

Im JSON stehen diese Zusatzinformationen unter `analysis`. `view_id` ist der SHA-256-Hash der Referenzdatei. Er kann sich mit dem 100-Bilder-Fenster oder der Bildauswahl ändern. Für die Modellhistorie können `twin_view_id` und `twin_camera_transform` eine nachgewiesene Ansichtsverbindung über mehrere Läufe abbilden. `series_id` trennt Messreihen; `image_size` wird als `[Höhe, Breite]` angegeben. `health_comparison_mode` kennzeichnet die Verfahren aus [A-M3](BB-SPEC-HEALTH-001_A-M3_Gesundheitsbewertung.md).

### Blattgeometrie für den Digital Twin

`analysis.leaf_geometry` enthält die Konturen in gemeinsamen, auf die Bildgröße normierten Koordinaten. `width_px` und `height_px` beschreiben die Ausdehnung der sichtbaren Gesamtmaske; `leaves[].pixels` gibt die Fläche des jeweiligen Teilbereichs an. `method` unterscheidet `estimated` und `manual`. Ohne verfügbare Konturen wird das Objekt ausgelassen. Die CSV enthält zusätzlich den Durchmesser in Pixeln und die Blattzählung mit Quelle. Der Zählwert betrifft nur sichtbare, voneinander getrennte oder manuell zugeordnete Flächen.

Die automatische Trennung beginnt mit Blattkernen, die aus dem Abstand zum Maskenrand ermittelt werden. Pixel werden diesen Kernen zugeordnet. Benachbarte Farbkanten können die Grenzen zwischen Regionen verschieben. Manuell können die Kerne im Originalfoto angeklickt oder vollständige Blattlabels als Graustufen-PNG importiert werden. Bei angeklickten Kernen bleibt der Grenzverlauf zwischen Blättern geschätzt. Die Gesamtmaske für Flächenmessung und Gesundheitsbewertung bleibt dabei unverändert.

## 6 Diagramme und Dateien

Die Messwerte und Diagramme werden in `computer_vision_pipeline.py` erzeugt. Der gesamte Ablauf wird mit `python analyse.py` gestartet; mit `python computer_vision_pipeline.py bilder` werden nur lokale Fotos verarbeitet.

| Datei unter `grafiken/` | Inhalt |
|---|---|
| `01_wachstum.png` | sichtbare Blattfläche, in cm² bei durchgehendem Maßstab der brauchbaren Aufnahmen, sonst in Pixeln |
| `02_wachstumsrate.png` | geprüfte Wachstumsrate, separate direkte Pixeländerung und Status je Aufnahme |
| `03_farbverlauf.png` | gemessene Rohfarben und Farbanteile; ausdrücklich lichtabhängig |
| `04_gesundheit.png` | relative Bewertung vor und nach zeitlicher Glättung, Referenzfoto und Status je Aufnahme |
| `05_teilscores.png` | Heatmap der fünf Teilbewertungen für jede Aufnahme; Referenzstarts und fehlende Werte bleiben erkennbar |

Die Galerie `grafiken/grafiken.html` zeigt die Diagramme einzeln. `grafiken.html`, `grafiken.css` und `grafiken.js` sind feste Projektdateien. Die Analyse erzeugt im selben Ordner die fünf PNGs und `grafiken.json` mit der Liste der verfügbaren Diagramme. Mit `python computer_vision_pipeline.py --grafiken` oder `python analyse.py --grafiken` wird die Galerie lokal aus den vorhandenen PNG-Dateien geöffnet. Ältere Grafiken aus `auswertung/grafiken/` werden dabei übernommen. Die Ergebnisdateien werden bei diesem Aufruf nicht neu berechnet.

Die Bildliste wird nach jedem normalen Abrufversuch frisch aus dem lokalen Ordner gebildet, unabhängig von dessen Erfolg. Auch selbst hinzugefügte Bilder werden erfasst. Die vorhandenen Originale werden neu ausgewertet. `--nur-bild` überspringt die Analyse. Automatische Masken und Kontrollen werden in `masken/` und `kontrolle/` aktualisiert; dateigenaue Korrekturen bleiben in `masken_korrektur/`. Die Diagramme werden auch bei fehlenden Einzelwerten mit dem jeweiligen Status ausgegeben. Für die weiteren Ansichten werden `digital twin/digital_twin.json` und `gesundheitssystem/gesundheitssystem.json` aktualisiert. Die Seiten lesen die Daten mit JavaScript; ihre Quelldateien bleiben unverändert. Die Browseransichten werden in [A-M4](BB-GUIDE-TWIN-001_A-M4_Digital-Twin-Modell.md) und [A-M3](BB-SPEC-HEALTH-001_A-M3_Gesundheitsbewertung.md) beschrieben.

Die sichtbare Blattanzahl wird bei der Analyse geschätzt oder anhand manueller Markierungen ermittelt. In der Zählansicht werden die daraus erzeugten Blätter einzeln dargestellt. Pflanzenhöhe und eine absolute biologische Gesundheitswahrscheinlichkeit werden nicht berechnet. Die tatsächliche Datenquelle bleibt das Originalfoto mit der finalen sichtbaren Blattmaske.

## 7 Aufbewahrung und Herkunft

Die Begrenzung auf 100 betrifft ausschließlich die erkannten Kamera-JPEGs. Eine Bereinigung erfolgt erst nach erfolgreichem Abgleich. Andere lokale Bilddateien werden nicht automatisch gelöscht oder begrenzt. Bereits gespeicherte Messwerte bleiben in der Ergebnishistorie, auch wenn das zugehörige Original nicht mehr lokal liegt. Masken und Kontrollen werden für die vorhandenen, verarbeiteten Bilder neu erzeugt.

Vorhandene CSV- und JSON-Datensätze werden eingelesen und mit den neuen Zeilen zusammengeführt. Ein erneut ausgewertetes identisches Foto wird anhand von Dateiname und SHA-256 zugeordnet; bei Altdaten ohne Prüfsumme wird auch die gespeicherte Aufnahmezeit berücksichtigt. Historische Zeilen ohne Original behalten Messwerte, Version und Referenz ihres früheren Laufs. Lässt sich die vorhandene Historie nicht sicher lesen, bleibt die bisherige Ausgabe erhalten. Für andere Pflanzen werden ein eigener Eingabeordner, ein eigener Ausgabeordner (`--ausgabe`) und eine passende `MESSREIHE` verwendet.

Automatische Referenzen und die Glättung der neu ausgewerteten Aufnahmen werden im Arbeitsspeicher aufgebaut. Gespeicherter Maßstab und manuelle Korrekturen bleiben eigene Eingaben. Die Historie speichert Messwerte und ihre Herkunft; sie ersetzt keine Originalfotos oder alten Referenzmasken.

Ein Pi-Abruffehler wird in der Konsole ausgegeben. Es wird dafür kein zusätzlicher Pflanzenmesswert und keine erfundene Fotoaufnahme in CSV oder JSON angelegt. Die reale Herkunft jeder Aufnahme bleibt über Dateiname, UTC-Aufnahmezeit und SHA-256-Dateihash nachvollziehbar. Die Aufnahmenummern in Grafik 02, 04 und 05 entsprechen der Reihenfolge in CSV/JSON; Fotos mit unbekannter Zeit folgen nach den zeitlich zuordenbaren Aufnahmen.

## 8 Maßgebliche Implementierung

- [`computer_vision_pipeline.py`](../computer_vision_pipeline.py), Pipeline 4.13.0: `SPALTEN`, `API_MESSFELDER`, `API_GESUNDHEIT`, `api_datensatz`, `ergebnishistorie_verbinden` und `ergebnisse_speichern`.
- [Bilderfassungssystem](BB-SPEC-IMG-001_A-M1_Bilderfassungssystem.md) und [Gesundheitsbewertung](BB-SPEC-HEALTH-001_A-M3_Gesundheitsbewertung.md).
