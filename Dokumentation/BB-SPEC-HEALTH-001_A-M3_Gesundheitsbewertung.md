# BioBox · Gesundheitsbewertung

| Feld | Stand |
|---|---|
| Dokument-ID | BB-SPEC-HEALTH-001 |
| Meilenstein | A-M3 · Gesundheitsbewertung |
| Version | 1.10 |
| Datum | 13.11.2026 |
| Autorin | Atida Ashta |
| Implementierung | analyse.py 4.13.0 |
| Scoring-Version | 4.1.0 |
| Status | Technischer relativer Zustandsindex; keine biologisch validierte Diagnose |

## 1 Aussage des Wertes

Der Gesundheitsscore von 0 bis 100 beschreibt sichtbare Veränderungen gegenüber einer Referenzaufnahme **derselben Pflanze**. 100 bedeutet eine geringe Abweichung der untersuchten Merkmale von der Referenz. Auch eine bereits geschädigte Pflanze kann bei geringer Abweichung zur eigenen Referenz einen hohen Vergleichswert erhalten. Für die Referenzaufnahme selbst wird kein gemessener Score ausgegeben. „Zustandsindex“ in den Diagrammen und „Gesundheitsscore“ in der Gesundheitsansicht bezeichnen denselben relativen Wert.

Ein fester dunkler Grünton für Basilikum wird nicht als Sollzustand verwendet. Helle oder panaschierte Blätter, also Blätter mit unterschiedlich gefärbten Bereichen, werden gegen ihren eigenen Ausgangszustand verglichen. Aufnahmen verschiedener Pflanzen dürfen nicht zu einer gemeinsamen Bewertung zusammengefasst werden.

Der Index enthält Hinweise auf Farb- und Strukturänderungen. Er bestimmt keinen Chlorophyllgehalt und keine Ursache wie Nährstoffmangel, Krankheit oder Wurzelschaden. Die Kategoriebezeichnungen sind technische Bereiche dieses Index.

## 2 Referenz innerhalb eines Analyselaufs

Die erste brauchbare Aufnahme je Kameraansicht der aktuellen Bildauswahl wird als Referenz im Arbeitsspeicher verwendet. Bilddaten, Blattmaske, Aufnahmezeit, Dateihash und Geometrie stehen während des Laufs für die Vergleiche bereit. Es werden keine automatischen `referenz.npz`-Dateien und keine Dateien in `kamera_referenzen/` eingelesen oder angelegt. Auch die Glättungshistorie wird aus den ausgewählten Bildern neu berechnet.

Der Referenzstart wird im Diagramm als Marke bei 100 dargestellt. Er ist kein gemessener Zustandswert: `gesundheit`, `gesundheit_roh` und die Teilbewertungen werden im Ergebnis-JSON dafür ausgelassen und in CSV als `Nicht verfügbar` markiert; der Status lautet `referenzfoto_start_der_ansicht`.

Ab einer weiteren brauchbaren Aufnahme derselben Ansicht kann ein Vergleich berechnet werden. Eine automatisch gewählte Referenz wird bei berechneten Scores durch `vorlaeufige_referenz` gekennzeichnet. Nach Sichtprüfung kann `REFERENZ_FREIGEGEBEN` auf `True` gesetzt werden; dies kennzeichnet im aktuellen Code nur die Hauptreferenz des Laufs als freigegeben. Es bestätigt die Referenzwahl, keine biologische Diagnose.

Jeder Lauf bildet die Referenzen aus den vorhandenen Originalen neu. Fällt ein altes Referenzfoto aus dem lokalen 100-Bilder-Fenster, wird das nächste geeignete verbleibende Foto zum Bezugspunkt. Gespeicherte Scores ohne lokales Original werden mit ihrem alten Bezug erhalten. `analysis.reference_file`, `analysis.reference_captured_at` und `analysis.reference_sha256` machen den tatsächlichen Bezug je Aufnahme nachvollziehbar. Werte mit unterschiedlichem Referenzfoto sind nur eingeschränkt direkt vergleichbar.

Manuelle Korrekturmasken werden dateigenau wiederverwendet. Für eine andere Pflanze werden Eingabe und Ausgabe getrennt. `--neue-referenz` verlangt zusätzlich, dass im aktuellen Lauf eine brauchbare Referenz gebildet werden kann; andernfalls wird die bisherige Ausgabe erhalten.

## 3 Vergleich von Kamera, Licht und Blattgewebe

1. Verteilte Merkmale des Hintergrunds werden verwendet, um die Aufnahme an der Referenz auszurichten. Fehlen genug automatisch zugeordnete Merkmale, können übereinstimmende Kanten in mehreren Hintergrundbereichen eine unveränderte Ansicht bestätigen. Bei deutlich veränderter Ansicht wird eine eigene Referenz begonnen. Die Werte verschiedener Ansichten werden weder verbunden noch miteinander geglättet. Bei kleinen Maßstabs- oder Winkeländerungen kann ein Farbvergleich möglich sein, während der Strukturvergleich ausfällt.
2. Aus nicht überbelichteten Hintergrundpaaren wird eine robuste Abbildung für Helligkeit und Weißabgleich geschätzt. Ein linearer Ansatz wird gegen eine Kurve und einen langsamen räumlichen Gradienten geprüft. Dafür werden getrennte Prüfwerte verwendet. Auch regionale Restfehler werden geprüft. Blattbereiche werden ausgeschlossen und die Korrektur wird nach der Segmentierung nochmals bestimmt.
3. Zuerst wird die Überlappung der um ein Arbeitspixel verkleinerten Blattmasken geprüft. Für einen Vergleich an denselben Bildpositionen werden mindestens 50 gemeinsame Arbeitspixel sowie 60 % der kleineren und 35 % der größeren Maske benötigt. In beiden Fotos werden ausgebrannte und sehr dunkle Pixel ausgeschlossen. Für den Vergleich müssen mindestens 65 % der ausgewählten gemeinsamen Fläche und mindestens 50 Arbeitspixel übrig bleiben.

Die Blattfarben werden nicht an einen Sollzustand angepasst. Die Rohwerte in der Ergebnistabelle bleiben lichtabhängig. Eine ungleichmäßige Beleuchtung, die nur auf die Blätter fällt, kann trotz Hintergrundabgleich zu Fehlern führen. Für die Aufnahme wird deshalb ein gleichmäßiges Licht mit möglichst konstanten Kameraeinstellungen empfohlen. Ein mattes, neutrales Referenzfeld außerhalb der Blattfläche kann bei der späteren Validierung helfen.

### Teilvergleich bei ungleichmäßiger Helligkeit

Schlägt der volle Lichtabgleich fehl, werden in geeigneten Hintergrundregionen die Verhältnisse Blau/Grün und Rot/Grün separat geprüft. In räumlich verteilten und bestätigten Bereichen können die gemeinsamen Blattpixel ohne ihre Helligkeitsinformation verglichen werden. Mindestens 30 % der gemeinsamen Blattfläche müssen dafür in bestätigten Bereichen liegen. Die Braunbewertung und die Strukturwertung entfallen; die übrigen Farbgewichte werden entsprechend normiert. Teilvergleiche werden als `farbverhaeltnis_teilflaeche` gekennzeichnet. Sie gehen nicht in denselben zeitlichen Trend ein wie Vollvergleiche.

### Vergleich der Blattfarbverteilungen seit Scoring 4.1.0

Bei zu geringer Überlappung wird nach bestätigter Kameraansicht und Lichtprüfung die Farbverteilung beider Blattmasken getrennt verglichen. Das erlaubt einen Vergleich, wenn sich Blätter verschoben haben oder hinzugewachsen sind. Dabei werden Farbverteilungen und Lab-Farbabstände aus Quantilen verwendet. Es werden keine Blattpixel an unterschiedlichen Positionen als direkte Paare behandelt.

Pro Foto müssen nach Ausschluss ungeeigneter Pixel mindestens 100 Arbeitspixel und 65 % des Maskenkerns nutzbar bleiben. Beim Vergleich nur nach Farbverhältnissen müssen mindestens 65 % beider Blattkerne in bestätigten Lichtbereichen liegen. Die Strukturwertung entfällt in beiden Fällen. Der Modus heißt `blattverteilung_normiert` bei vollem Lichtabgleich oder `blattverteilung_chromatik` beim Vergleich der Farbverhältnisse. Im zweiten Fall entfällt auch die Braunbewertung.

## 4 Teilbewertungen

| Feld | Eingang | Gewicht im Farbteil |
|---|---|---:|
| `score_gruen` | Farbverteilung (42 %), Verlust des normierten Grünanteils (26 %) und Lab-Farbabweichung (32 %) | 0,30 |
| `score_gelb` | Zusätzliche Gelb-/Warmfärbung; bei vollem Lichtabgleich einschließlich Braun | 0,20 |
| `score_braun` | Zusätzliche dunkle Warmfärbung. Bei gemeinsamen Pixeln wird zusätzlich eine Rotverschiebung geprüft. | 0,25 |
| `score_saettigung` | Logarithmische Änderung der mittleren Sättigung | 0,15 |
| `score_farbton` | Kreisförmige Farbtonänderung und Abstand der Lab-Farbkomponenten | 0,10 |

Lab bezeichnet den Farbraum der Internationalen Beleuchtungskommission (CIE). Für den Lab-Farbabstand werden a* und b* verwendet. Kleine Abweichungen werden gedämpft; im positionsgleichen Vergleich werden stärkere Abweichungen über die gemeinsam sichtbare Fläche gemittelt. So können Flecken in die Bewertung eingehen, auch wenn sich die mittlere Farbe wenig ändert. Die Farb- und Warnschwellen sind technische Startwerte.

Für alle Teilbewertungen gilt mit nichtnegativem Abstand d und Halbwert h:

```text
Teilscore = 100 × exp(−ln(2) × (d / h)²)
```

Wo angegeben, wird vor der Berechnung eine Toleranz abgezogen. Innerhalb der Toleranz werden 100 Punkte erreicht. Beispiele: Der zusätzliche Gelb-/Warmanteil hat eine Toleranz von 0,4 und einen Halbwert von 8 Prozentpunkten; für Braun sind es 0,3 und 4,5 Prozentpunkte. Die Teilwerte sind technische Ähnlichkeitswerte und keine Wahrscheinlichkeiten.

## 5 Struktur und Rohscore

Struktur wird mit 15 % einbezogen, wenn Kamera und Ausschnitt ausreichend stabil sind, der Vergleich über gemeinsame Blattpixel mit vollem Lichtabgleich erfolgt und keine der beiden Masken den Aufnahme- oder Auswerterand berührt. Die Farbgewichte werden dafür insgesamt auf 85 % skaliert. Andernfalls wird ausschließlich Farbe bewertet.

Bei der Struktur zählt vor allem der Verlust sichtbarer Blattfläche. Bis 3,5 % Flächenverlust werden toleriert. Die Kompaktheit wird nur ergänzend berücksichtigt und verändert ohne Flächenverlust den Strukturwert nicht. Ein hinzugewachsenes Blatt wird dadurch nicht automatisch als Schaden gewertet.

Der Rohwert besteht zu 65 % aus dem gewichteten arithmetischen und zu 35 % aus dem gewichteten geometrischen Mittel der Teilwerte. Für das geometrische Mittel wird jeder Teilwert intern mindestens mit 0,01 angesetzt. So wirkt ein deutlich schlechter Teilwert sichtbar auf den Gesamtwert, ohne den Index allein auf null zu setzen.

## 6 Zeitliche Darstellung

`gesundheit_roh` ist die Bewertung der einzelnen Aufnahme. `gesundheit` wird zeitabhängig exponentiell geglättet. Der neue Anteil wird mit `1 - exp(-Zeitabstand / 2 Stunden)` bestimmt und auf 0,25 bis 1 begrenzt. Damit werden größere Zeitabstände stärker berücksichtigt. Bei der Glättung werden Kameraansicht und Vergleichsmodus getrennt gehalten.

Für den 24-Stunden-Trend wird ein gültiger Vergleich derselben Ansicht und desselben Modus zwischen 22 und 26 Stunden Abstand gesucht. Verwendet wird die Aufnahme mit dem kleinsten Abstand zu 24 Stunden. Fehlt sie, wird `health_trend_24h` im Ergebnis-JSON ausgelassen und in CSV als `Nicht verfügbar` markiert. Die Einheit sind Scorepunkte, keine Prozentänderung.

| Bereich | Ausgabekategorie |
|---|---|
| ab 85 | `sehr gut` |
| ab 70 und unter 85 | `gut` |
| ab 50 und unter 70 | `beobachten` |
| ab 30 und unter 50 | `auffaellig` |
| unter 30 | `kritisch` |
| keine gültige Bewertung | `keine_daten` |

Die Worte „sehr gut“ und „kritisch“ beziehen sich auf diesen relativen Index. Eine Pflanzenart oder Erkrankung wird damit nicht bestimmt.

## 7 Meldungen

| Meldung | Auslöser im Vergleich |
| --- | --- |
| `farbveraenderung` | Lokale Farbabweichung bzw. Quantilkennwert ab 7, Histogrammabstand über 0,25 oder HSV-Farbtonänderung über 10 Einheiten. |
| `gelbanteil_gestiegen` | Gelb-/Warmindikator nimmt um mindestens 5 Prozentpunkte zu. |
| `braunanteil_gestiegen` | Braunindikator nimmt bei bestätigter Helligkeit um mindestens 2,5 Prozentpunkte zu. |
| `saettigung_veraendert` | Logarithmische Sättigungsabweichung über 0,22. |
| `sichtbare_blattflaeche_gesunken` | Mehr als 15 % sichtbarer Flächenverlust bei erlaubtem Strukturvergleich. |

Mehrere Meldungen werden mit Semikolon getrennt. Die Schwellen bezeichnen technische Hinweise auf sichtbare Änderungen.

Lichtprobleme stehen bei den Qualitätsmerkmalen und im Gesundheitsstatus, beispielsweise `licht_hintergrund_unzureichend`, `lichtkorrektur_nicht_stabil` oder `lichtvergleich_zu_wenig_blattgewebe`. Eine erfolgreiche Korrektur wird als Metadatum im JSON dokumentiert und nicht als Pflanzenkrankheit gemeldet.

## 8 Ausgabe und Datenbank

Die neu berechneten Werte werden gemeinsam in CSV und JSON gespeichert. Bei fehlender Vergleichbarkeit wird der Wert im Ergebnis-JSON ausgelassen und in CSV mit `Nicht verfügbar` gekennzeichnet. Die Gründe stehen in `analysis.missing_values` und `fehlende_werte`. Ein gemessener Wert von 0 bleibt 0. Bei entfernten Originalen bleibt der früher gespeicherte Datensatz mit damaliger Bewertung, Referenz und Version erhalten. Die Diagramme zeigen die verfügbaren Werte je Foto; fehlende Scores und Referenzstarts haben eigene Markierungen.

Die Gesundheitsdaten werden unter `health_assessment` ausgegeben, getrennt von `image_measurements`. `health_status`, `scoring_version` und `analysis.health_comparison_mode` erklären die Herkunft des Wertes. Die genauen Messfelder und Einheiten stehen im [Merkmalsverzeichnis](BB-REF-MERKMALE-001_A-M2_Computer-Vision-Pipeline.md).

### Lokale Gesundheitsansicht

Beim normalen Analyselauf werden `gesundheitssystem.html`, `gesundheitssystem.css`, `gesundheitssystem.js` und `gesundheitssystem.json` im Projektordner `gesundheitssystem/` erzeugt. Die HTML-Datei kann per Doppelklick geöffnet werden. Mit `python analyse.py --gesundheit` kann die Ansicht aus vorhandenen Ergebnissen neu erzeugt und geöffnet werden, ohne eine Aufnahme abzurufen.

Neben dem letzten zeitlich zuordenbaren Foto werden der geglättete Gesundheitsscore, die fünf farbbezogenen Teilbewertungen und die Blattmerkmale angezeigt. Auf schmalen Bildschirmen werden Foto und Messwerte untereinander angezeigt. Farbanteile stammen aus dem Rohbild. Der Rohscore, der 24-Stunden-Trend, Warnungen und Angaben zu Bildqualität, Lichtabgleich und Referenzbezug bleiben in den Ergebnisdateien verfügbar. Die Strukturwertung fließt weiterhin in den Score ein, wenn die Voraussetzungen aus Abschnitt 5 erfüllt sind.

Die Vorschau wird aus dem lokalen Original mit passender Prüfsumme erstellt. Fehlt das Original, bleiben die gespeicherten Bewertungen lesbar. Die Ansicht verwendet dieselben gerundeten Gesundheitswerte wie die Ergebnisausgabe.

### Verhalten bei ausgefallenem Pi-Abruf

Der Gesundheitsvergleich benötigt die lokal vorhandenen Bilder und keine aktive Pi-Verbindung. Bei einem Timeout, einer abgelehnten Verbindung oder einem anderen Abruffehler werden alle unterstützten lokalen Bilder erneut eingelesen und verarbeitet. Selbst hinzugefügte Fotos werden auch nach erfolgreichem Abruf berücksichtigt. Der Abruffehler wird als Konsolenmeldung ausgegeben und nicht als Pflanzenschaden gewertet.

Ein Foto erhält weiterhin nur dann einen Score, wenn Bildqualität, Ansicht und Farbvergleich ausreichend sind. Ein Verbindungsfehler erzeugt weder einen Ersatzscore noch einen zusätzlichen Gesundheitsabschlag. Ohne lokale Bilder bleibt die bisherige Ausgabe erhalten; `--nur-bild` überspringt die Bewertung ausdrücklich.

## 9 Technische Prüfung und Grenzen

Geprüft wurden ein echtes BioBox-Foto, Varianten desselben Fotos mit simulierter Lichtänderung und künstlich eingefärbte Blattstellen. Zusätzlich wurde eine künstliche Pflanzenszene mit bekannten Blattgrenzen für die Masken-, Farb-, Flächen- und Zeitreihentests verwendet. Das Verfahren wurde auf Wachstum ohne Verfärbung, Gelb- und Braunfärbung, schlechte Belichtung, geänderte Kameraansicht und fehlende Messwerte getestet.

Die technische Prüfung wird getrennt von der biologischen Validierung betrachtet. Eine Analyse mit vorhandenen Messwerten oder einem simulierten Pi-Timeout prüft den Ablauf und die Anzeige, aber weder den realen Stundenbetrieb noch die Aussagekraft für Pflanzenkrankheiten.

Ein stabiler Index bei den getesteten Lichtvarianten bedeutet keine vollständige Lichtunabhängigkeit. Ebenso sind die künstlichen Verfärbungen kein Nachweis von Pflanzenkrankheiten. Für eine fachliche Abnahme werden weitere unveränderte Originalaufnahmen derselben Pflanze unter dokumentierten Bedingungen und eine überprüfte Referenz benötigt.

## 10 Grundlagen

- Maßgeblich für die Berechnung: [`analyse.py`](../analyse.py), Funktionen `gesundheitsmerkmale`, `bewerten` und `zeitreihe_und_glaettung`.
- [Bilderfassungssystem](BB-SPEC-IMG-001_A-M1_Bilderfassungssystem.md) und [Computer-Vision-Pipeline](BB-REF-MERKMALE-001_A-M2_Computer-Vision-Pipeline.md).
- [OpenCV: GrabCut](https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html).
- [OpenCV: Histogrammvergleich](https://docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html).
