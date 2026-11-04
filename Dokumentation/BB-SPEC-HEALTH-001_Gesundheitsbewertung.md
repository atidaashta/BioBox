# Gesundheitsbewertung BioBox

| Feld | Stand |
|---|---|
| Dokument-ID | BB-SPEC-HEALTH-001 |
| Version | 1.3 |
| Datum | 04.11.2026 |
| Autorin | Atida Ashta |
| Implementierung | analyse.py 4.3.0 |
| Scoring-Version | 4.0.0 |
| Status | Technischer relativer Zustandsindex; keine biologisch validierte Diagnose |

## 1 Aussage des Wertes

Der Wert von 0 bis 100 beschreibt sichtbare Veränderungen gegenüber einer früheren Aufnahme **derselben Pflanze**. 100 bedeutet eine geringe Abweichung der untersuchten Merkmale von der Referenz, nicht den Nachweis einer gesunden Pflanze. Auch eine bereits geschädigte Referenz kann zunächst 100 Punkte ergeben.

Ein fester dunkler Grünton für Basilikum wird nicht als Sollzustand verwendet. Helle oder panaschierte Blätter, also Blätter mit unterschiedlich gefärbten Bereichen, werden gegen ihren eigenen Ausgangszustand verglichen. Aufnahmen verschiedener Pflanzen dürfen nicht zu einer gemeinsamen Bewertung zusammengefasst werden.

Der Index enthält Hinweise auf Farb- und Strukturänderungen. Er bestimmt keinen Chlorophyllgehalt und keine Ursache wie Nährstoffmangel, Krankheit oder Wurzelschaden. Die Kategoriebezeichnungen sind technische Bereiche dieses Index.

## 2 Feste Referenz

Die erste brauchbare Aufnahme einer ausgewählten Messreihe wird als Referenz gespeichert. Verwendet wird `auswertung/referenz.npz`. Bilddaten, Blattmaske, Aufnahmezeitpunkt, Dateihash, Bildgröße, Geometrie, Versionsinformationen und die begrenzte Scorehistorie werden erhalten. Die Referenz bleibt damit verfügbar, wenn das erste Foto aus dem lokalen 100-Bilder-Fenster fällt.

Es müssen nicht erst drei oder zehn Bilder gesammelt werden. Die automatische Referenz bleibt zunächst als `vorlaeufige_referenz` gekennzeichnet; die Berechnung wird dadurch nicht blockiert. Nach Sichtprüfung kann `REFERENZ_FREIGEGEBEN` auf `True` gesetzt werden. Eine solche Freigabe bestätigt die Referenzwahl, keine biologische Diagnose.

Die automatische Referenzmaske wird bei jedem Analyselauf neu berechnet. Bei einer geänderten Skriptdatei, Pipeline- oder Scoring-Version werden veraltete automatische Masken aktualisiert und alte Scorehistorien verworfen. Der ursprüngliche Referenzzeitpunkt bleibt erhalten. Neue Referenzdateien enthalten auch das Originalbild; bei alten Profilen wird es aus der Bildauswahl ergänzt, sofern verfügbar. Manuell geprüfte Masken werden geschützt. Bei einem Wechsel der Pflanze oder eines unpassenden Aufnahmeprofils muss eine passende neue Messreihe gewählt werden. `--neue-referenz` bildet die Referenz aus den tatsächlich ausgewählten Eingabebildern neu und entfernt keine alten Pflanzenbilder aus dem Eingabeordner.

## 3 Vergleich von Kamera, Licht und Blattgewebe

1. Verteilte Merkmale des Hintergrunds werden verwendet, um die Aufnahme an der Referenz auszurichten. Fehlen genug automatisch zugeordnete Merkmale, können übereinstimmende Kanten in mehreren Hintergrundbereichen eine unveränderte Ansicht bestätigen. Bei nicht bestätigter oder deutlich veränderter Ansicht entfällt der Index. Bei kleinen Maßstabs- oder Winkeländerungen kann ein Farbvergleich möglich sein, während der Strukturvergleich ausfällt.
2. Aus nicht überbelichteten Hintergrundpaaren wird eine robuste Abbildung für Helligkeit und Weißabgleich geschätzt. Ein linearer Ansatz wird gegen eine Kurve und einen langsamen räumlichen Gradienten geprüft. Dafür werden getrennte Prüfwerte verwendet. Auch regionale Restfehler werden geprüft. Blattbereiche werden ausgeschlossen und die Korrektur wird nach der Segmentierung nochmals bestimmt.
3. Nur die Überlappung der beiden Blattmasken wird für die Farbe bewertet. Der äußere Maskenrand wird um ein Arbeitspixel verkleinert. Die gemeinsame Fläche muss mindestens 60 % der kleineren und 35 % der größeren erodierten Maske abdecken. Beide Bilder werden an denselben Positionen geprüft. Sind weniger als 65 % der gemeinsamen Blattfläche oder weniger als 50 geeignete Arbeitspixel nutzbar, entfällt der Score. Gesättigte und sehr dunkle Pixel werden nicht rekonstruiert.

Die Blattfarben werden nicht an einen Sollzustand angepasst. Die Rohwerte in der Ergebnistabelle bleiben lichtabhängig. Eine ungleichmäßige Beleuchtung, die nur auf die Blätter fällt, kann trotz Hintergrundabgleich zu Fehlern führen. Für die Aufnahme wird deshalb ein gleichmäßiges Licht mit möglichst konstanten Kameraeinstellungen empfohlen. Ein mattes, neutrales Referenzfeld außerhalb der Blattfläche kann bei der späteren Validierung helfen.

## 4 Teilbewertungen

| Feld | Eingang | Gewicht im Farbteil |
|---|---|---:|
| `score_gruen` | Farbverteilung (42 %), Verlust des normierten Grünanteils (26 %), lokale Abweichung in Lab (32 %) | 0,30 |
| `score_gelb` | Zusätzliche Gelb-/Warmfärbung an gleichen Blattpositionen; Braun bleibt enthalten | 0,20 |
| `score_braun` | Zusätzliche dunkle Warmfärbung mit Verschiebung in Richtung Rot; reine Abdunkelung allein reicht nicht | 0,25 |
| `score_saettigung` | Logarithmische Änderung der mittleren Sättigung | 0,15 |
| `score_farbton` | Kreisförmige Farbtonänderung und Abstand der Lab-Farbkomponenten | 0,10 |

Lab bezeichnet den Farbraum der Internationalen Beleuchtungskommission (CIE). Für die lokale Farbänderung wird die Helligkeitskomponente L* nicht als Stress gewertet. Aus den Farbkomponenten a* und b* wird pro gemeinsamem Blattpixel der Abstand berechnet. Kleine Abweichungen werden gedämpft; stärkere Abweichungen werden über die gemeinsam sichtbare Fläche gemittelt. So gehen lokale Flecken in die Bewertung ein, auch wenn sie die mittlere Farbe des ganzen Blatts kaum ändern. Die Farb- und Warnschwellen sind technische Startwerte.

Für alle Teilbewertungen gilt mit nichtnegativem Abstand d und Halbwert h:

```text
Teilscore = 100 × exp(−ln(2) × (d / h)²)
```

Wo angegeben, wird vor der Berechnung eine Toleranz abgezogen. Innerhalb der Toleranz werden 100 Punkte erreicht. Beispiele: Der zusätzliche Gelb-/Warmanteil hat eine Toleranz von 0,4 und einen Halbwert von 8 Prozentpunkten; für Braun sind es 0,3 und 4,5 Prozentpunkte. Die Teilwerte sind technische Ähnlichkeitswerte und keine Wahrscheinlichkeiten.

## 5 Struktur und Rohscore

Struktur wird mit 15 % einbezogen, wenn die Ansicht vergleichbar ist und weder die aktuelle Maske noch die Referenz den Aufnahme- oder Auswerterand berührt. Die Farbgewichte werden dafür insgesamt auf 85 % skaliert. Andernfalls wird ausschließlich Farbe bewertet.

Bei der Struktur zählt vor allem der Verlust sichtbarer Blattfläche. Bis 3,5 % Flächenverlust werden toleriert. Die Kompaktheit wird nur ergänzend berücksichtigt und verändert ohne Flächenverlust den Strukturwert nicht. Ein hinzugewachsenes Blatt wird dadurch nicht automatisch als Schaden gewertet.

Der Rohwert besteht zu 65 % aus dem gewichteten arithmetischen und zu 35 % aus dem gewichteten geometrischen Mittel der Teilwerte. Für das geometrische Mittel wird jeder Teilwert intern mindestens mit 0,01 angesetzt. So wirkt ein deutlich schlechter Teilwert sichtbar auf den Gesamtwert, ohne den Index allein auf null zu setzen.

## 6 Zeitliche Darstellung

`gesundheit_roh` ist die Bewertung der einzelnen Aufnahme. `gesundheit` wird zeitabhängig exponentiell geglättet. Der neue Anteil wird mit `1 - exp(-Zeitabstand / 2 Stunden)` bestimmt und auf 0,25 bis 1 begrenzt. Damit werden größere Zeitabstände stärker berücksichtigt. Über einen Wechsel zwischen reinem Farbvergleich und Vergleich mit Struktur wird nicht geglättet.

Für den 24-Stunden-Trend wird ein gültiger Vergleich desselben Modus zwischen 22 und 26 Stunden Abstand gesucht. Verwendet wird die Aufnahme mit dem kleinsten Abstand zu 24 Stunden. Fehlt sie, bleibt `gesundheit_trend_24h` leer. Die Einheit sind Scorepunkte, keine Prozentänderung.

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

Mögliche beobachtete Veränderungen werden als `farbveraenderung`, `gelbanteil_gestiegen`, `braunanteil_gestiegen`, `saettigung_veraendert` oder `sichtbare_blattflaeche_gesunken` ausgegeben. Mehrere Werte werden mit Semikolon getrennt. Diese Namen ersetzen die früheren diagnostisch klingenden Warnungen im alten Entwurf.

Lichtprobleme stehen bei den Qualitätsmerkmalen und im Gesundheitsstatus, beispielsweise `licht_hintergrund_unzureichend`, `lichtkorrektur_nicht_stabil` oder `lichtvergleich_zu_wenig_blattgewebe`. Eine erfolgreiche Korrektur wird als Metadatum im JSON dokumentiert und nicht als Pflanzenkrankheit gemeldet.

## 8 Ausgabe und Datenbank

CSV und JSON werden aus denselben gerundeten Datensätzen erzeugt. JSON enthält echte Zahlen, boolesche Werte und `null`. Die CSV dient der Kontrolle mit Tabellenprogrammen. Sie wird gemeinsam mit Masken, Kontrollbildern, JSON und Diagrammen ersetzt. Bei einem Schreibfehler bleibt die vorherige zusammengehörige Ausgabe erhalten; eine gesperrte Excel-Datei muss vor einem erneuten Lauf geschlossen werden. Bei unbrauchbaren Bildern oder fehlender Vergleichbarkeit bleiben Scorefelder leer; es wird kein alter Wert als neuer Wert übernommen.

Die Gesundheitsdaten werden unter `health_assessment` ausgegeben, getrennt von `image_measurements`. `health_status` und `scoring_version` gehören zur Erklärung des Wertes. Die genaue HTTP-Anbindung und die Datenbank-IDs müssen mit Edona abgestimmt werden. Die konkreten Messfelder und Einheiten werden im Merkmalsverzeichnis beschrieben.

## 9 Technische Prüfung und Grenzen

Geprüft wurden ein echtes BioBox-Foto, Varianten desselben Fotos mit simulierter Lichtänderung und künstlich eingefärbte Blattstellen. Zusätzlich wurde eine künstliche Pflanzenszene mit bekannten Blattgrenzen für die Masken-, Farb-, Flächen- und Zeitreihentests verwendet. Das Verfahren wurde auf Wachstum ohne Verfärbung, Gelb- und Braunfärbung, schlechte Belichtung, geänderte Kameraansicht und fehlende Messwerte getestet.

Ein stabiler Index bei den getesteten Lichtvarianten bedeutet keine vollständige Lichtunabhängigkeit. Ebenso sind die künstlichen Verfärbungen kein Nachweis von Pflanzenkrankheiten. Für eine fachliche Abnahme werden weitere unveränderte Originalaufnahmen derselben Pflanze unter dokumentierten Bedingungen und eine überprüfte Referenz benötigt.

## 10 Grundlagen

- BB-SPEC-IMG-001 und BB-REF-MERKMALE-001, aktueller gemeinsamer Stand.
- OpenCV, GrabCut: https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html
- OpenCV, Histogrammvergleich: https://docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html
