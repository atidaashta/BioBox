# BioBox · Digital-Twin-Modell und 3D-Ansicht

| Feld | Stand |
| --- | --- |
| Dokument-ID | BB-GUIDE-TWIN-001 |
| Meilenstein | A-M4 · Digital-Twin-Modell |
| Version | 1.5 |
| Datum | 11.11.2026 |
| Software | analyse.py 4.10.0 · Modell 0.1.0 · 3D-Ansicht 0.5.0 |
| Status | Prototyp für lokale Darstellung, Projektion und Szenarien |

## 1. Starten

Mit `analyse.py` 4.10.0 wird im Projektordner folgender Befehl ausgeführt:

```powershell
python analyse.py
```

Nach der Bildauswertung wird die Ansicht im Browser geöffnet. Mit `python analyse.py --3d` kann eine vorhandene Ansicht geöffnet werden. Sind bereits Messwerte vorhanden und soll die Seite daraus neu erstellt werden, kann ohne Pi-Abruf und ohne erneute Bildanalyse folgender Befehl verwendet werden:

```powershell
python analyse.py --3d-aus-json auswertung/ergebnis.json
```

Die erzeugte Datei `auswertung/digital_twin_3d.html` kann auch per Doppelklick geöffnet werden. Das Stylesheet `digital_twin_3d.css` muss dafür im selben Ordner liegen. Ein Webserver wird nicht benötigt.

## 2. Pflanze ansehen und drehen

Die Ansicht zeichnet die sichtbaren Blattkonturen des gewählten Fotos. Bei älteren Datensätzen ohne Konturen wird die Ansicht nach einer erneuten Analyse des Originals ergänzt. Zum Start wird die neueste Aufnahme ausgewählt. Über die Fotoauswahl und die Pfeile kann zwischen den Aufnahmen gewechselt werden. Bei mehreren Messreihen wird zusätzlich deren Auswahl angezeigt. Die Uhrzeiten werden in der Zeitzone Europe/Berlin dargestellt.

| Bedienung | Wirkung |
| --- | --- |
| Linke Maustaste halten und ziehen | Das Modell waagrecht und senkrecht frei drehen. Auch Ansichten von unten und über Kopf sind möglich. |
| Umschalttaste halten und waagrecht ziehen | Das Modell zusätzlich seitlich kippen. |
| Mausrad | Vergrößern oder verkleinern. |
| „Drehen“ | Automatische Drehung starten oder anhalten. |
| „Von oben“ | Projektion ohne Perspektivverzerrung mit der Ausrichtung des Fotos anzeigen. |
| „Ansicht zurück“ | Ausgangsperspektive und Vergrößerung wiederherstellen. |

Nach einem Klick auf das Modell kann auch mit den Pfeiltasten gedreht werden. Umschalt mit Pfeil links oder rechts kippt das Modell seitlich. Plus und Minus ändern die Vergrößerung. Am Handy kann waagrecht über das Modell gewischt werden.

Unter dem Modell stehen die Blattfläche im Foto und der **Gesundheitsscore**. **„Messdetails“** zeigt den Dateinamen, die Bewertung und ihre Teilwerte. Unter **„Foto, Blattmaske und Kontrolle“** stehen die verfügbaren Vorschauen der ausgewählten Aufnahme, soweit sie beim Export verfügbar sind. Das Kontrollbild zeigt die erkannten Blattkonturen auf dem Foto. In der HTML-Datei werden verkleinerte Vorschauen gespeichert. Zu älteren Aufnahmen können die gespeicherten Messwerte weiterhin angezeigt werden.

## 3. Wachstum testen

1. **„Wachstum testen“** öffnen und 0 bis 14 Tage ab dem ausgewählten Foto einstellen.
2. Mit **„Beim Foto“** und **„Nach … Tagen“** zwischen dem Modell zur Aufnahme und dem Szenario wechseln.
3. Bei Bedarf unter **„Annahmen bearbeiten“** eine eigene tägliche Änderung eingeben. Ist keine passende Rate verfügbar, wird dieser Bereich automatisch geöffnet, sofern die Blattfläche für ein Szenario geeignet ist.
4. Unter **„Annahmen bearbeiten“** kann eine angenommene Pflegewirkung als Zahl eingegeben werden. Unter **„Weitere Möglichkeiten“ → „Pflegewirkung vergleichen“** werden die beiden Annahmen mit und ohne zusätzliche Wirkung gegenübergestellt.

Beispiel: Aus 10.000 Blattpixeln werden bei einer angenommenen Änderung von 2 % pro Tag nach einem Tag 10.200 Pixel. Mit einer zusätzlich angenommenen Pflegewirkung von 1 Prozentpunkt werden 3 % pro Tag angesetzt, also 10.300 Pixel nach einem Tag. Bei mehreren Tagen wird der Faktor `1 + Rate / 100` für jeden Tag erneut angewendet. Die Basisrate kann zwischen −50 und 100 % pro Tag liegen, die zusätzliche Wirkung zwischen −20 und 20 Prozentpunkten pro Tag. Szenarien oberhalb der bekannten Bildfläche werden abgelehnt.

Die Pflegetipps ändern die Wachstumsrate nicht automatisch. Eine Pflegewirkung wird als eigene Annahme eingetragen. Die separate vorläufige 24-Stunden-Projektion wird unter „Weitere Möglichkeiten“ angezeigt, wenn sie für die Aufnahme verfügbar ist.

Unter **„Weitere Möglichkeiten“** kann das Szenario gespeichert oder zurückgesetzt werden. „Zurücksetzen“ stellt sieben Tage und die verfügbare vorgeschlagene Rate wieder her und setzt die angenommene Pflegewirkung auf null. Auch bei einem Fotowechsel werden diese Angaben zurückgesetzt. Die gespeicherte `biobox_szenario.json` dient als Export der Annahmen.

## 4. Frühere Fotos finden

Unter **„Alle Fotos“** werden die Aufnahmen mit Messwerten und Bewertungsstatus angezeigt. Ein Klick auf eine Zeile wählt den Datensatz im Bereich „Pflanze“ aus. Mit „Zurück“ und „Weiter“ wird zwischen den Seiten gewechselt.

Unter **„Filter und Diagramm“** können Aufnahmen gesucht, nach fehlenden Scores gefiltert und im Diagramm angezeigt werden. Ein Klick auf einen Balken öffnet ebenfalls das zugehörige Foto.

## 5. Werte richtig einordnen

| Anzeige | Bedeutung |
| --- | --- |
| Blattpixel | Sichtbare Blattfläche in der Bildmaske. |
| Gesundheitsscore 0–100 | Vergleich mit der eigenen Referenzaufnahme. 100 bedeutet eine hohe Ähnlichkeit zur Referenz. In den Analysediagrammen wird derselbe Wert „Zustandsindex“ genannt. |
| 0 | Ein gespeicherter Nullwert. |
| — | Ein Wert fehlt oder konnte nicht berechnet werden. Der Grund steht in der Bewertung. |
| Referenzfoto | Ausgangsaufnahme für den Vergleich. |

Die Konturen kommen aus der finalen Blattmaske. Für das automatische Aufteilen werden Blattkerne in der Maske gesucht und über Watershed getrennt. Der automatische Zählwert ist eine Schätzung: Besonders dichte, überlappende oder unvollständig maskierte Bereiche können zusammengefasst oder geteilt werden. In **Messdetails** stehen die sichtbaren Pixel je Blattbereich und ihr Anteil an der gesamten Maske. Breite und Höhe beziehen sich auf die sichtbare Ausdehnung im Bild. Das Modell übernimmt beide Achsen im gleichen Maßstab. Die Ansicht ist drehbar, zeigt aber nur die Fotoebene; tatsächliche Höhe, Tiefe und verdeckte Blattflächen werden nicht gemessen.

Für einen geprüften sichtbaren Blattzählwert kann eine Graustufen-PNG in Originalgröße mit genau einer ID je Blatt eingelesen werden. Im Hintergrund ist der Wert 0, Blatt 1 hat den Wert 1, Blatt 2 den Wert 2 usw. Die positiven Pixel müssen gemeinsam genau die finale Blattmaske ergeben. Bei entzerrten Aufnahmen werden die Koordinaten der ausgegebenen Maske verwendet. Die Zuordnung wird an den Inhalt des Fotos gebunden:

```powershell
python analyse.py --blattlabels bilder/FOTO.png LABELS.png
python analyse.py --lokal bilder
```

Falls ein anderer Ausgabeordner genutzt wird, muss er in beiden Aufrufen mit `--ausgabe` angegeben werden. Stimmen Labels und Maske nicht überein, wird die automatische Schätzung mit einem Hinweis angezeigt. Manuelle Labels bestätigen nur die tatsächlich beschrifteten sichtbaren Blätter. Szenarien skalieren die Konturen einheitlich; sie erfinden keine neuen Blätter.

## 6. Pflegetipps und lokale KI

Unter **„Pflegetipps“** werden ein kurzer Befund und konkrete nächste Schritte für das ausgewählte Foto angezeigt. Für den Befund werden der Gesundheitsscore, auffällige Teilwerte wie Gelb- oder Braunzunahme und die Bildqualität berücksichtigt. Bei unzureichender Bildqualität wird zuerst eine besser vergleichbare Aufnahme vorgeschlagen.

Für formulierte **KI-Tipps** wird [Ollama](https://ollama.com/download) einmal installiert und gestartet. Danach wird das Modell in PowerShell heruntergeladen:

```powershell
ollama pull qwen2.5:3b
```

Bei laufendem Ollama wird das neueste brauchbare Foto bei einem normalen Lauf berücksichtigt, sofern es die neueste Aufnahme ist. Für ein bestimmtes älteres Foto oder alle brauchbaren Fotos:

```powershell
python analyse.py --pflege-ki "FOTO.png"
python analyse.py --pflege-ki "*"
```

Die Befehle lesen vorhandene Ergebnisse und erstellen die Browseransicht neu. Der Dateiname muss eindeutig sein. Für einen abweichenden Messordner kann `--3d-aus-json PFAD/ergebnis.json` ergänzt werden. Ein Auftrag für alle Fotos kann je nach Modell länger dauern. Gespeicherte Antworten werden anhand der Messwerte und der Modellkennung wiederverwendet.

Ollama erhält nur ausgewählte Messwerte, etwa die sichtbare Blattfläche, Farbanteile, Qualitätsmeldungen und verfügbare Gesundheitsscores. Fotos werden nicht übergeben. Die passenden Antworten werden am jeweiligen Foto als **„Lokale KI“** angezeigt. Ohne gültige Antwort erscheinen Hinweise aus den Messwerten. Die Hinweise ändern weder Messwerte noch Pflegesteuerung.

## 7. Dateien und Aktualisierung

| Datei | Inhalt |
| --- | --- |
| `auswertung/ergebnis.json` | Messwerte und Bewertungen je Foto. |
| `auswertung/ergebnis.csv` | Ergebnisse als Tabelle, z. B. für Excel. |
| `auswertung/digital_twin.json` | Letzter Modellzustand, gegebenenfalls die vorläufige 24-Stunden-Projektion und Prognosehistorie. |
| `auswertung/digital_twin_3d.html` | Die im Browser angezeigte Seite mit dem gespeicherten Datenstand. |
| `auswertung/digital_twin_3d.css` | Farben, Abstände und Gestaltung der Seite. |
| `auswertung/pflege_ki.json` | Lokal gespeicherte KI-Antworten für wiederholte Exporte. |
| `auswertung/blattlabels/` | Optionale, manuell beschriftete Blätter je Original. |
| `auswertung/kontrolle/` | Kontrollbilder mit markierten Blattkonturen. |
| `biobox_szenario.json` | Export der Annahmen aus einem Wachstumsszenario. |

Nach neuen Aufnahmen wird `python analyse.py` erneut ausgeführt. Über **„Daten öffnen“** können `ergebnis.json` und die passende `digital_twin.json` auch im Browser lokal geladen werden. Für die vollständige Fotoliste wird `ergebnis.json` benötigt. Ein Szenarioexport kann über diese Funktion nicht importiert werden.

Beim Export werden die HTML-Datei und das Stylesheet gemeinsam erzeugt. Beim Verschieben oder Weitergeben bleiben beide Dateien im selben Ordner. Änderungen direkt an der CSS-Datei sind nach dem Neuladen im Browser sichtbar. Beim nächsten Export wird das Stylesheet aus dem Abschnitt `TWIN_3D_CSS` in `analyse.py` neu geschrieben.

## 8. Modell für die nächsten 24 Stunden

Die 24-Stunden-Projektion wird in `analyse.py` aus der gemessenen sichtbaren Blattfläche in Pixeln berechnet. Sie wird getrennt vom frei einstellbaren Szenario aus Abschnitt 3 erzeugt. In `digital_twin.json` stehen der aktuelle Messpunkt (`state`), die Modellrechnung (`forecast`) und der jeweilige Status.

| Prüfung | Voraussetzung |
| --- | --- |
| Vergleichsgruppe | Dieselbe Messreihe, bestätigte Kameraansicht, gleiches Bildformat, Objektivprofil und derselbe Skriptstand. |
| Zeitfenster | Bis zu 72 Stunden vor der letzten Aufnahme, mindestens sechs verschiedene Aufnahmezeitpunkte über mindestens 24 Stunden. |
| Abstände | Höchstens sechs Stunden zwischen benachbarten verwendeten Messpunkten. |
| Datenqualität | Verlässliche Aufnahmezeit, positive Blattfläche, brauchbare Maske und weitgehend feste Kamera. Auffällige Flächensprünge werden ausgeschlossen. |
| Aktualität | Eine Prognose wird nur bei einem höchstens drei Stunden alten Messpunkt als aktuell ausgegeben. Sonst kann eine berechenbare Projektion als historisch gekennzeichnet werden. |

Über die echten Zeitabstände wird eine Gerade an die Blattpixel angepasst. Für den Zielwert wird die Gerade 24 Stunden ab dem letzten Aufnahmezeitpunkt fortgeführt. Der letzte Messwert dient als einfache Vergleichsmethode. Liegen mindestens drei rückblickende Vergleiche vor und hat der letzte Messwert dabei den kleineren oder gleichen mittleren absoluten Fehler, wird er als Projektion verwendet. Liegt der lineare Wert außerhalb der Bildfläche, wird ebenfalls auf den letzten Messwert zurückgegriffen.

Bei der rückblickenden Prüfung werden die jeweils früheren Messungen verwendet und mit einer späteren Aufnahme nahe dem Zielzeitpunkt verglichen. Eine tatsächlich im Voraus ausgegebene Prognose bleibt im `forecast_history` unverändert gespeichert. Sie wird erst mit einer danach aufgenommenen vergleichbaren Messung im Fenster von ±40 Minuten um das Ziel bewertet. Der Fehler wird in Blattpixeln dokumentiert. Ist keine geeignete Zeitreihe vorhanden, bleibt `forecast` auf `null`; Messwerte und 3D-Ansicht sind weiterhin nutzbar.

Eine Auswirkung der Pflege auf die Pflanze wird damit noch nicht gelernt. Dafür wären abgestimmte Zeitreihen der Sensorwerte, Pflegemaßnahmen und späterer Aufnahmen erforderlich.

## 9. Zugehörige Dokumente

- [A-M1 · Bilderfassungssystem](BB-SPEC-IMG-001_A-M1_Bilderfassungssystem.md): Kamera, Masken und Maßstab.
- [A-M2 · Computer-Vision-Pipeline](BB-REF-MERKMALE-001_A-M2_Computer-Vision-Pipeline.md): Messwerte und gespeicherte Historie.
- [A-M3 · Gesundheitsbewertung](BB-SPEC-HEALTH-001_A-M3_Gesundheitsbewertung.md): Lichtabgleich und Gesundheitsscore.
- [README](../README.md): Installation und Schnellstart.
