# BioBox – Anleitung zur 3D-Ansicht

| Feld | Stand |
| --- | --- |
| Dokument-ID | BB-GUIDE-TWIN-001 |
| Version | 1.0 |
| Datum | 10.11.2026 |
| Software | analyse.py 4.8.0 · 3D-Ansicht 0.2.0 |
| Status | Prototyp für die lokale Darstellung und Szenarien |

## 1. Zweck

In der 3D-Ansicht werden die Bildmessungen einer Pflanze übersichtlich dargestellt. Fotos können ausgewählt, Zustandswerte verglichen und mögliche Entwicklungen der Blattfläche ausprobiert werden.

Die Ansicht wird von `analyse.py` als `auswertung/digital_twin_3d.html` erstellt. Sie kann ohne Webserver im Browser geöffnet werden. Für die Ansicht werden keine weiteren Python-Dateien, JavaScript-Installation oder Internetverbindung benötigt. Die bisherigen Python-Abhängigkeiten der Analyse bleiben erforderlich.

## 2. Starten und öffnen

Die bisherige `analyse.py` wird durch die neue Datei ersetzt. Die Anleitung kann im Projektordner `docs` abgelegt werden.

PowerShell wird im Projektordner geöffnet:

```powershell
cd "$env:USERPROFILE\Downloads\Diploma"
```

**Wenn bereits eine `auswertung/ergebnis.json` vorhanden ist**, wird die neue Ansicht damit erstellt und geöffnet:

```powershell
python analyse.py --3d-aus-json auswertung/ergebnis.json
```

Dabei werden nur vorhandene Messdaten gelesen. Eine Verbindung zum Raspberry Pi und eine erneute Bildanalyse werden nicht benötigt.

**Wenn die lokalen Bilder neu ausgewertet werden sollen**, wird folgender Befehl verwendet:

```powershell
python analyse.py --lokal bilder --3d
```

Anschließend kann die gespeicherte Ansicht mit `python analyse.py --3d` oder durch Doppelklick auf `auswertung/digital_twin_3d.html` geöffnet werden. Falls die Datei in einem Texteditor erscheint, wird über „Öffnen mit“ ein Browser, beispielsweise Edge oder Chrome, ausgewählt.

## 3. Die drei Bereiche

| Bereich | Verwendung |
| --- | --- |
| **Pflanze** | Modell und Messwerte des ausgewählten Fotos ansehen; Pflegepunkte vormerken. |
| **Wachstum testen** | Zeitraum einstellen und eine mögliche Flächenentwicklung mit eigenen Annahmen vergleichen. |
| **Alle Fotos** | Bewertungen und Gründe für fehlende Werte pro Foto ansehen; ältere Fotos suchen und auswählen. |

Zum Start wird das neueste Foto angezeigt. Über die Fotoauswahl und die Pfeile kann zwischen Aufnahmen gewechselt werden. Bei mehreren Messreihen wird zusätzlich deren Auswahl eingeblendet. Aufnahmezeiten werden in der Zeitzone Europe/Berlin angezeigt.

Das Modell wird mit Maus oder Finger gedreht. Mit dem Mausrad kann gezoomt werden. Nach Auswahl des Modells können auch Pfeiltasten sowie Plus und Minus verwendet werden. Über „Ansicht zurück“ wird die ursprüngliche Perspektive wiederhergestellt.

Unter **„Mehr anzeigen“** werden Dateiname, Bewertungsmethode und Teilwerte eingeblendet. Eine kleine Foto- und Maskenvorschau wird angezeigt, wenn sie für die ausgewählte Aufnahme eingebettet ist. Die HTML-Datei enthält kein vollständiges Fotoarchiv. Die Modellform kann unter „Darstellung ändern“ angepasst werden; Messwerte werden dadurch nicht verändert.

In „Alle Fotos“ werden bis zu 25 Einträge pro Seite angezeigt. Weitere Einträge sind über „Zurück“ und „Weiter“ erreichbar. Eine Zeile oder ein Balken öffnet die gewählte Aufnahme im Bereich „Pflanze“. Die Suche und der Filter „Ohne berechneten Index“ helfen bei der Kontrolle.

## 4. Pflege und Wachstum ausprobieren

Pflegehinweise werden zunächst im Bereich „Pflanze“ vorgemerkt. Unter „Warum dieser Hinweis?“ werden die Begründung und gegebenenfalls eine Quelle angezeigt. Basilikumhinweise werden nur nach Auswahl der Pflanzenart „Basilikum“ ergänzt.

Danach wird „Wachstum testen“ geöffnet:

1. Mit dem Regler wird ein Zeitraum von 0 bis 14 Tagen **ab dem ausgewählten Foto** eingestellt.
2. Eine passende Rate wird aus der bisherigen Auswertung übernommen. Fehlt sie, werden die Eingabefelder unter „Annahmen bearbeiten“ automatisch geöffnet.
3. Bei Bedarf werden die tägliche Änderung und eine zusätzliche Pflegewirkung eingetragen. Eine zusätzliche Wirkung ist nur bei vorgemerkter Pflege freigeschaltet und startet mit 0.
4. Über „Vergleichen“ werden das Szenario ohne zusätzliche Wirkung und das Szenario mit der eigenen Wirkungsannahme gegenübergestellt.

Beispiel: Bei 10.000 Blattpixeln und einer angenommenen Änderung von 2 % pro Tag ergeben sich nach einem Tag 10.200 Pixel. Wird zusätzlich 1 Prozentpunkt Pflegewirkung angenommen, werden 3 % pro Tag und damit 10.300 Pixel verwendet. Für mehrere Tage wird die Änderung täglich fortgeschrieben.

Durch das Vormerken eines Pflegepunkts wird **keine Verbesserung automatisch angenommen**. Die Wirkung ist noch nicht aus Messungen gelernt. Messwerte und Gesundheitsbewertungen bleiben unverändert; ein künftiger Gesundheitswert wird nicht vorhergesagt. Unmögliche Flächen oberhalb der gesamten Bildfläche werden abgelehnt.

„Zurücksetzen“ löscht den vorgemerkten Plan und eigene Wirkungsannahmen, stellt sieben Tage ein und übernimmt wieder die verfügbare Ausgangsrate. Beim Wechsel des Fotos werden diese Angaben ebenfalls zurückgesetzt. Über „Szenario speichern“ wird eine `biobox_szenario.json` mit den Annahmen heruntergeladen. Für den Erhalt des Plans muss sie vor einem Fotowechsel oder dem Schließen gespeichert werden. Die Szenariodatei ist ein Export; sie wird nicht über „Daten öffnen“ wieder eingelesen.

## 5. Werte richtig verstehen

| Anzeige | Bedeutung |
| --- | --- |
| Blattpixel | Sichtbare, projizierte Blattfläche der Maske; keine Höhe, keine cm² und keine verdeckten Blätter. |
| Zustandsindex 0–100 | Relativer Vergleich mit der eigenen Referenz. 100 bedeutet Nähe zur Referenz und keine bestätigte vollständige Gesundheit. |
| 0 | Tatsächlich gespeicherter Nullwert; er wird angezeigt. |
| — | Kein berechenbarer oder gespeicherter Wert. Der Grund wird angegeben. |
| Referenzfoto | Ausgangspunkt des Vergleichs; noch kein berechneter Zustandsindex. |

Die 3D-Pflanze ist eine vereinfachte Illustration. Höhe, Blattanzahl und Blattpositionen wurden nicht räumlich rekonstruiert. Die wählbare Form ist keine automatische Erkennung der Pflanzenart.

Das separate 24-Stunden-Modell wird unter „Weitere Möglichkeiten“ erläutert, sofern eine passende Projektion vorhanden ist. Es benötigt ausreichend vergleichbare Aufnahmen und ist noch nicht biologisch validiert. Längere Zeiträume im Wachstumstest sind angenommene Szenarien. Auch bei einer übernommenen Rate bleibt ihre Fortschreibung eine Annahme. Pflegehinweise sind Prüfpunkte und keine Diagnose oder automatische Bewässerungsanweisung.

## 6. Dateien und Aktualisierung

| Datei | Aufgabe |
| --- | --- |
| `auswertung/ergebnis.json` | Messwerte und Bewertungen je Foto; Grundlage für die geplante Datenbank-/API-Anbindung. |
| `auswertung/ergebnis.csv` | Dieselben Ergebnisse als Tabelle, beispielsweise für Excel. |
| `auswertung/digital_twin.json` | Letzter Modellzustand und gegebenenfalls die vorläufige 24-Stunden-Projektion. |
| `auswertung/digital_twin_3d.html` | Persönliche Browseransicht eines gespeicherten Datenstands. |
| `biobox_szenario.json` | Heruntergeladene Annahmen eines Wachstumstests; keine Messdaten oder bestätigte Prognose. |

Die Ansicht ist nicht live. Nach neuen Aufnahmen wird die Analyse erneut ausgeführt und die HTML-Datei neu geöffnet oder im Browser aktualisiert. Über „Daten öffnen“ können `ergebnis.json` und die passende `digital_twin.json` gemeinsam oder nacheinander lokal geladen werden. Eine neue Ergebnisdatei ersetzt die angezeigte Historie; getrennte Messreihen werden nicht zusammengeführt. Änderungen in der Ansicht verändern keine Quelldateien und werden nicht automatisch an Edona oder eine Datenbank übertragen. Quellenlinks öffnen sich nur bei Auswahl und benötigen Internet.

**Falls etwas fehlt:** Bei alter Oberfläche wird der Befehl `--3d-aus-json` aus Abschnitt 2 erneut ausgeführt. Bei fehlenden Fotos wird `ergebnis.json` geöffnet; die Twin-Datei allein enthält nur den letzten Zustand. Bei fehlender Szenariorate wird unter „Annahmen bearbeiten“ eine eigene Annahme eingetragen. Fehlende Zustandswerte werden anhand des angegebenen Grundes sowie der Aufnahme und Maske geprüft; sie werden nicht durch 0 oder 100 ersetzt.
