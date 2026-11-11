# BioBox – Anleitung zur 3D-Ansicht

| Feld | Stand |
| --- | --- |
| Dokument-ID | BB-GUIDE-TWIN-001 |
| Meilenstein | A-M4 |
| Version | 1.3 |
| Datum | 11.11.2026 |
| Software | analyse.py 4.9.1 · 3D-Ansicht 0.4.1 |
| Status | Prototyp für die lokale Darstellung und Szenarien |

## 1. Starten

Die bisherige `analyse.py` wird ersetzt. Anschließend wird im Projektordner folgender Befehl ausgeführt:

```powershell
python analyse.py
```

Nach der Bildauswertung wird die Ansicht im Browser geöffnet. Sind bereits Messwerte vorhanden und sollen nur diese angezeigt werden, kann die Seite ohne Raspberry Pi und ohne erneute Bildanalyse erstellt werden:

```powershell
python analyse.py --3d-aus-json auswertung/ergebnis.json
```

Die erzeugte Datei `auswertung/digital_twin_3d.html` kann auch per Doppelklick geöffnet werden. Das Stylesheet `digital_twin_3d.css` muss dafür im selben Ordner liegen. Ein Webserver wird nicht benötigt.

## 2. Pflanze ansehen und drehen

Die Ansicht zeigt ein Basilikummodell. Zum Start wird die neueste Aufnahme ausgewählt. Über die Fotoauswahl und die Pfeile kann zwischen den Aufnahmen gewechselt werden. Bei mehreren Messreihen wird zusätzlich deren Auswahl angezeigt. Die Uhrzeiten werden in der Zeitzone Europe/Berlin dargestellt.

| Bedienung | Wirkung |
| --- | --- |
| Linke Maustaste halten und ziehen | Das Modell waagrecht und senkrecht frei drehen. Auch Ansichten von unten und über Kopf sind möglich. |
| Umschalttaste halten und waagrecht ziehen | Das Modell zusätzlich seitlich kippen. |
| Mausrad | Vergrößern oder verkleinern. |
| „Drehen“ | Automatische Drehung starten oder anhalten. |
| „Ansicht zurück“ | Ausgangsperspektive und Vergrößerung wiederherstellen. |

Nach einem Klick auf das Modell kann auch mit den Pfeiltasten gedreht werden. Umschalt mit Pfeil links oder rechts kippt das Modell seitlich. Plus und Minus ändern die Vergrößerung. Am Handy kann waagrecht über das Modell gewischt werden.

Unter dem Modell stehen die Blattfläche im Foto und der **Gesundheitsscore**. **„Messdetails“** zeigt den Dateinamen, die Bewertung und ihre Teilwerte. Unter **„Foto, Blattmaske und Kontrolle“** stehen die verfügbaren Vorschauen der neuesten Aufnahme. Das Kontrollbild zeigt die erkannten Blattkonturen auf dem Foto. Die HTML-Datei speichert verkleinerte Vorschauen; die Originaldateien liegen weiterhin im Projektordner.

## 3. Wachstum testen

1. **„Wachstum testen“** öffnen und 0 bis 14 Tage ab dem ausgewählten Foto einstellen.
2. Mit **„Beim Foto“** und **„Nach … Tagen“** zwischen dem Modell zur Aufnahme und dem Szenario wechseln.
3. Bei Bedarf unter **„Annahmen bearbeiten“** eine eigene tägliche Änderung eingeben. Ist keine passende Rate verfügbar, wird dieser Bereich automatisch geöffnet, sofern die Blattfläche für ein Szenario geeignet ist.
4. Unter **„Annahmen bearbeiten“** kann eine angenommene Pflegewirkung als Zahl eingegeben werden. Unter **„Weitere Möglichkeiten“ → „Pflegewirkung vergleichen“** werden die beiden Annahmen mit und ohne zusätzliche Wirkung gegenübergestellt.

Beispiel: Aus 10.000 Blattpixeln werden bei einer angenommenen Änderung von 2 % pro Tag nach einem Tag 10.200 Pixel. Mit einer zusätzlich angenommenen Pflegewirkung von 1 Prozentpunkt werden 3 % pro Tag angesetzt, also 10.300 Pixel nach einem Tag.

Die Pflegetipps ändern die Wachstumsrate nicht automatisch. Eine Pflegewirkung wird als eigene Annahme eingetragen. Die separate vorläufige 24-Stunden-Projektion wird unter „Weitere Möglichkeiten“ angezeigt, wenn sie für die Aufnahme verfügbar ist.

Unter **„Weitere Möglichkeiten“** kann das Szenario gespeichert oder zurückgesetzt werden. „Zurücksetzen“ stellt sieben Tage und die verfügbare vorgeschlagene Rate wieder her und setzt die angenommene Pflegewirkung auf null. Auch bei einem Fotowechsel werden diese Angaben zurückgesetzt. Die gespeicherte `biobox_szenario.json` dient als Export der Annahmen.

## 4. Frühere Fotos finden

Unter **„Alle Fotos“** werden die Aufnahmen mit Messwerten und Bewertungsstatus angezeigt. Ein Klick auf eine Zeile öffnet das Foto im Bereich „Pflanze“. Mit „Zurück“ und „Weiter“ wird zwischen den Seiten gewechselt.

Unter **„Filter und Diagramm“** können Aufnahmen gesucht, nach fehlenden Scores gefiltert und im Diagramm angezeigt werden. Ein Klick auf einen Balken öffnet ebenfalls das zugehörige Foto.

## 5. Werte richtig einordnen

| Anzeige | Bedeutung |
| --- | --- |
| Blattpixel | Sichtbare Blattfläche in der Bildmaske. |
| Gesundheitsscore 0–100 | Vergleich mit der eigenen Referenzaufnahme. 100 bedeutet eine hohe Ähnlichkeit zur Referenz. In älteren Ansichten wurde dieser Wert „Zustandsindex“ genannt. |
| 0 | Ein gespeicherter Nullwert. |
| — | Ein Wert fehlt oder konnte nicht berechnet werden. Der Grund steht in der Bewertung. |
| Referenzfoto | Ausgangsaufnahme für den Vergleich. |

Das Basilikummodell ist eine vereinfachte Darstellung. Die Form und Größe der einzelnen Blätter sowie die Höhe der Pflanze werden daraus nicht gemessen. Der Gesundheitsscore dient zum Vergleich der Aufnahmen; eine Pflanzendiagnose ist daraus nicht ableitbar. Wachstumsszenarien beruhen auf Annahmen und lösen keine Gerätesteuerung aus.

## 6. Pflegetipps und lokale KI

Unter **„Pflegetipps“** werden ein kurzer Befund und konkrete nächste Schritte für das ausgewählte Foto angezeigt. Für den Befund werden der Gesundheitsscore, auffällige Teilwerte wie Gelb- oder Braunzunahme und die Bildqualität berücksichtigt. Bei unzureichender Bildqualität wird zuerst eine besser vergleichbare Aufnahme vorgeschlagen.

Für formulierte **KI-Tipps** wird [Ollama](https://ollama.com/download) einmal installiert und gestartet. Danach wird das Modell in PowerShell heruntergeladen:

```powershell
ollama pull qwen2.5:3b
```

Bei laufendem Ollama wird anschließend wie gewohnt `python analyse.py` ausgeführt. Liegt für die neueste Aufnahme ein vergleichbarer Score vor, werden ihre Messwerte an die [lokale Chat-Schnittstelle von Ollama](https://docs.ollama.com/api/chat) übergeben. Die Bilder werden dafür nicht übertragen. Die Antwort wird in die HTML-Datei eingebettet und mit **„Lokale KI“** gekennzeichnet.

Wenn Ollama oder das Modell nicht verfügbar ist, werden die Tipps aus den Messwerten abgeleitet. Das gilt auch beim Wechsel auf ältere Aufnahmen. Ein Farbwechsel kann verschiedene Ursachen haben; die Tipps dienen dazu, passende Prüfungen auszuwählen.

## 7. Dateien und Aktualisierung

| Datei | Inhalt |
| --- | --- |
| `auswertung/ergebnis.json` | Messwerte und Bewertungen je Foto. |
| `auswertung/ergebnis.csv` | Ergebnisse als Tabelle, z. B. für Excel. |
| `auswertung/digital_twin.json` | Letzter Modellzustand und gegebenenfalls die vorläufige 24-Stunden-Projektion. |
| `auswertung/digital_twin_3d.html` | Die im Browser angezeigte Seite mit dem gespeicherten Datenstand. |
| `auswertung/digital_twin_3d.css` | Farben, Abstände und Gestaltung der Seite. |
| `auswertung/kontrolle/` | Kontrollbilder mit markierten Blattkonturen. |
| `biobox_szenario.json` | Export der Annahmen aus einem Wachstumsszenario. |

Nach neuen Aufnahmen wird `python analyse.py` erneut ausgeführt. Über **„Daten öffnen“** können `ergebnis.json` und die passende `digital_twin.json` auch im Browser lokal geladen werden. Für die vollständige Fotoliste wird `ergebnis.json` benötigt. Ein Szenarioexport kann über diese Funktion nicht importiert werden.

Beim Export werden die HTML-Datei und das Stylesheet gemeinsam erzeugt. Beim Verschieben oder Weitergeben bleiben beide Dateien im selben Ordner. Änderungen direkt an der CSS-Datei sind nach dem Neuladen im Browser sichtbar. Beim nächsten Export wird das Stylesheet aus dem Abschnitt `TWIN_3D_CSS` in `analyse.py` neu geschrieben.
