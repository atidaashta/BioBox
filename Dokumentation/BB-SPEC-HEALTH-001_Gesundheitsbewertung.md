# Gesundheitsbewertung BioBox

| Feld | Stand |
|---|---|
| Dokument-ID | BB-SPEC-HEALTH-001 |
| Version | 1.0 |
| Datum | 26.10.2026 |
| Autorin | Atida Ashta |
| Implementierung | analyse.py 4.0.0 |
| Scoring-Version | 3.0.0 |
| Status | Technischer relativer Zustandsindex; keine biologisch validierte Diagnose |

## 1 Aussage des Wertes

Der Wert von 0 bis 100 beschreibt sichtbare Veränderungen gegenüber einer früheren Aufnahme **derselben Pflanze**. 100 bedeutet eine geringe Abweichung der untersuchten Merkmale von der Referenz, nicht den Nachweis einer gesunden Pflanze. Auch eine bereits geschädigte Referenz kann zunächst 100 Punkte ergeben.

Ein fester dunkler Grünton für Basilikum wird nicht als Sollzustand verwendet. Helle oder panaschierte Blätter, also Blätter mit unterschiedlich gefärbten Bereichen, werden gegen ihren eigenen Ausgangszustand verglichen. Aufnahmen verschiedener Pflanzen dürfen nicht zu einer gemeinsamen Bewertung zusammengefasst werden.

Der Index enthält Hinweise auf Farb- und Strukturänderungen. Er bestimmt keinen Chlorophyllgehalt und keine Ursache wie Nährstoffmangel, Krankheit oder Wurzelschaden. Die Kategoriebezeichnungen sind technische Bereiche dieses Index.

## 2 Feste Referenz

Die erste brauchbare Aufnahme einer ausgewählten Messreihe wird als Referenz gespeichert. Verwendet wird `auswertung/referenz.npz`. Bilddaten, Blattmaske, Aufnahmezeitpunkt, Dateihash, Bildgröße, Geometrie, Versionsinformationen und die begrenzte Scorehistorie werden erhalten. Die Referenz bleibt damit verfügbar, wenn das erste Foto aus dem lokalen 100-Bilder-Fenster fällt.

Es müssen nicht erst drei oder zehn Bilder gesammelt werden. Die automatische Referenz bleibt zunächst als `vorlaeufige_referenz` gekennzeichnet; die Berechnung wird dadurch nicht blockiert. Nach Sichtprüfung kann `REFERENZ_FREIGEGEBEN` auf `True` gesetzt werden. Eine solche Freigabe bestätigt die Referenzwahl, keine biologische Diagnose.

Bei einem Versionswechsel werden veraltete automatische Masken aktualisiert und alte Scorehistorien verworfen. Manuell geprüfte Masken werden geschützt. Bei einem Wechsel der Pflanze oder eines unpassenden Aufnahmeprofils muss eine passende neue Messreihe gewählt werden. `--neue-referenz` bildet die Referenz aus den tatsächlich ausgewählten Eingabebildern neu und entfernt keine alten Pflanzenbilder aus dem Eingabeordner.

## 3 Ausgleich von Lichtänderungen

### 3.1 Hintergrund statt Blattfarbe

Die Referenzansicht wird anhand von Hintergrundmerkmalen mit der aktuellen Ansicht abgeglichen. Ausgeschlossen werden die Referenzblätter, aktuelle wahrscheinliche Blattbereiche und ein zusätzlicher Rand. Über- oder unterbelichtete Hintergrundpixel werden nicht zum Lernen verwendet.

Auf räumlich verteilten Hintergrundpixeln wird eine robuste Abbildung von aktuellen RGB-Kanalwerten auf die Referenz geschätzt. Eine lineare Abbildung wird mit einer einfachen gekrümmten Tonwertabbildung und gegebenenfalls einem langsamen räumlichen Lichtgradienten verglichen. Zur Prüfung werden andere Pixel als zur Anpassung verwendet. Eine kompliziertere Abbildung wird nur bei deutlich kleinerem Vergleichsfehler übernommen.

**Die Blattfarbe wird nicht zum Lernen dieser Korrektur verwendet.** Echte Verfärbungen der Pflanze sollen deshalb nach der Korrektur erhalten bleiben. Die normalisierte Arbeitskopie wird für Segmentierung und Gesundheitsvergleich verwendet. Die gespeicherten Rohwerte `mittel_r`, `mittel_g`, `mittel_b`, `mittel_h`, `mittel_s`, Grünindex und Farbanteile werden nicht durch die korrigierten Werte ersetzt.

### 3.2 Unwiederbringlich verlorene Information

Pixel mit mindestens einem Kanalwert ab 254 oder mit sehr geringem Signal können nicht zuverlässig farbmetrisch verglichen werden. Solche Stellen werden im aktuellen Bild und in der Referenz gemeinsam ausgeschlossen. Damit wird eine geänderte Gewichtung heller Blattteile möglichst vermieden.

Mindestens 65 % der aktuellen Blattmaske und mindestens 50 Arbeitsbildpixel müssen für den Farbvergleich übrig bleiben. Ein unzureichender Hintergrund, eine instabile Korrektur oder zu wenig messbares Gewebe führen zu einem fehlenden Gesundheitswert mit erklärtem Status. Ein bisheriger Score wird nicht als neue Messung weitergeschrieben.

Das Verfahren kann geeignete Helligkeits-, Weißabgleichs- und langsame Lichtänderungen vermindern. Eine vollständige Unabhängigkeit von beliebigen Lichtspektren, örtlichen Reflexen oder zerstörten Bilddaten wird nicht behauptet. Ein neutrales Referenzfeld und stabile Aufnahmebedingungen bleiben sinnvoll.

## 4 Teilbewertungen

Die vorhandenen fünf Feldnamen bleiben erhalten. Sie werden relativ, stetig und ohne einen vorgeschriebenen gesunden Grünton berechnet. Für die Bewertungen werden die lichtkorrigierten Blattfarben und die passende Referenzteilfläche verwendet.

| Feld | Eingangsänderung | Gewicht im Farbscore |
|---|---|---:|
| `score_gruen` | Abstand der Farbverteilung und Änderung des normierten Grünanteils | 0,30 |
| `score_gelb` | Zunahme der Summe aus Gelb- und Braunanteil gegenüber der Referenz | 0,20 |
| `score_braun` | Zunahme des Braunanteils bzw. eines weichen Warmfarbindikators | 0,25 |
| `score_saettigung` | Verhältnisänderung der Farbsättigung | 0,15 |
| `score_farbton` | Kreisförmige Farbtonänderung und Änderung der Farbkomponenten in Lab | 0,10 |

Der weiche Warmfarbindikator reduziert Sprünge an einer einzelnen Braun-Schwelle. Da die Farben vorher auf die Referenzbeleuchtung bezogen werden, soll ein helleres Foto nicht automatisch als weniger braun und damit als erholt bewertet werden.

Gelb und Braun werden für `score_gelb` zusammen betrachtet, damit eine gelbe Stelle nach einer weiteren Braunfärbung nicht durch einen sinkenden Gelbanteil als Verbesserung bewertet wird. `score_braun` bewertet die zusätzliche Braunfärbung gesondert und stärker.

Die Grundkennlinie lautet für eine nichtnegative Abweichung `d`:

```text
q = max(0, d - Toleranz) / Halbwertabstand
Teilscore = 100 × exp(-ln(2) × min(q, 30)²)
```

Innerhalb der Toleranz werden 100 Punkte erreicht. Bei `Toleranz + Halbwertabstand` werden 50 Punkte erreicht. Dazwischen und darunter wird stetig bewertet.

| Eingang der Kennlinie | Toleranz | Halbwertabstand |
|---|---:|---:|
| Histogrammabstand | 0,035 | 0,28 |
| Unterschied des Grünindex | 0,006 | 0,045 |
| zusätzliche Summe aus Gelb- und Braunanteil in Prozentpunkten | 1,5 | 12 |
| zusätzlicher Braun-/Warmanteil in Prozentpunkten | 0,8 | 7 |
| Betrag des logarithmischen Sättigungsverhältnisses | 0,06 | 0,32 |
| kombinierter Farbton-/Lab-Abstand | 2 | 10 |

`score_gruen` besteht zu 60 % aus dem Histogrammvergleich und zu 40 % aus dem Grünindexvergleich. Für Sättigung wird vor dem Verhältnis eine kleine Stabilisierung von 8 Kanalstufen addiert. Der HSV-Farbton wird kreisförmig behandelt; 179 und 0 sind benachbart. Der Lab-Vergleich verwendet die Farbkomponenten, nicht die reine Helligkeit.

Die Parameter sind technische Startwerte. Ihre Nennung ist keine Behauptung einer biologischen Kalibrierung.

## 5 Struktur und Rohscore

Bei ausreichend vergleichbarer Kamerageometrie werden außerdem ein Rückgang der sichtbaren Blattfläche und eine Änderung der Kompaktheit berücksichtigt. Wachstum allein wird nicht als schlechter Zustand bewertet.

```text
Farbscore = 0,30 × score_gruen + 0,20 × score_gelb
         + 0,25 × score_braun + 0,15 × score_saettigung
         + 0,10 × score_farbton

Strukturscore = 0,70 × Score(Flächenverlust)
             + 0,30 × Score(Änderung der Kompaktheit)

gesundheit_roh = 0,80 × Farbscore + 0,20 × Strukturscore
```

Für den Flächenverlust gelten Toleranz 0,05 und Halbwertabstand 0,25. Für den Betrag der logarithmischen Kompaktheitsänderung gelten 0,12 und 0,70. Kann die Geometrie nicht sinnvoll verglichen werden, wird bei sonst verlässlicher Farbregistrierung nur der Farbscore verwendet und dies im Status angegeben. Die interne Strukturbewertung wird nicht als zusätzliche redundante CSV-Messgröße eingeführt.

## 6 Zeitliche Darstellung

`gesundheit_roh` ist die Bewertung der einzelnen Aufnahme. `gesundheit` wird zeitabhängig exponentiell geglättet. Der neue Anteil wird mit `1 - exp(-Zeitabstand / 2 Stunden)` bestimmt und auf 0,25 bis 1 begrenzt. Damit werden größere Zeitabstände stärker berücksichtigt.

Für den 24-Stunden-Trend wird ein gültiger Vergleich zwischen 22 und 26 Stunden Abstand gesucht. Verwendet wird die Aufnahme mit dem kleinsten Abstand zu 24 Stunden. Fehlt sie, bleibt `gesundheit_trend_24h` leer. Die Einheit sind Scorepunkte, keine Prozentänderung.

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

CSV und JSON werden aus denselben gerundeten Datensätzen erzeugt. JSON enthält echte Zahlen, boolesche Werte und `null`. Die CSV dient der Kontrolle mit Tabellenprogrammen. Bei unbrauchbaren Bildern oder fehlender Vergleichbarkeit bleiben Scorefelder leer; es wird kein alter Wert als neuer Wert übernommen.

Die Gesundheitsdaten werden unter `health_assessment` ausgegeben, getrennt von `image_measurements`. `health_status` und `scoring_version` gehören zur Erklärung des Wertes. Die genaue HTTP-Anbindung und die Datenbank-IDs müssen mit Edona abgestimmt werden. Maßgeblich sind der aktuelle Feldvertrag BB-DB-HEALTH-001 und das Merkmalsverzeichnis.

## 9 Prüfung und noch offene Validierung

Zur technischen Prüfung gehören identische Bilder, reine Helligkeitsänderungen, Weißabgleichs- und Gammaänderungen, schrittweise Verfärbung sowie nicht auswertbare Aufnahmen. Ein bereits verfärbtes Bild muss bei geänderter Beleuchtung ungefähr dieselbe Bewertung behalten. Gute Ergebnisse bei künstlichen Veränderungen beweisen keine biologische Diagnosegenauigkeit.

Für eine reale Validierung werden Originalbilder mit unabhängig geprüften Blattmasken und eine Beobachtungsreihe derselben Pflanze benötigt. Pflanzenzustand und Aufnahmebedingungen müssen getrennt protokolliert werden. Frühere Testbehauptungen aus dem Entwurf werden nicht ungeprüft als Nachweis dieser Softwareversion übernommen.

## 10 Grundlagen

- BB-SPEC-IMG-001 und BB-REF-MERKMALE-001, aktueller gemeinsamer Stand.
- OpenCV, GrabCut: https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html
- OpenCV, Histogrammvergleich: https://docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html
