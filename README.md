# BioBox · Bildanalyse und Pflanzenmonitoring

BioBox ist ein Teil der Diplomarbeit zur Beobachtung einer Pflanze. Aus Kameraaufnahmen werden sichtbare Blattfläche, Farbmerkmale und Veränderungen im Zeitverlauf bestimmt. Eine lokale 3D-Ansicht stellt die Messreihe mit den sichtbaren Blattkonturen je Foto dar.

**Stand: 11.11.2026** · `analyse.py` 4.10.0 · Bewertung 4.1.0 · 3D-Ansicht 0.5.0

## Schnellstart

Im Projektordner unter Windows PowerShell:

```powershell
cd "$env:USERPROFILE\Downloads\Diploma"
python -m pip install opencv-contrib-python numpy matplotlib Pillow
python analyse.py
```

Der Standardaufruf holt fertige Fotos vom Raspberry Pi ab und wertet anschließend die lokalen Bilder unter `Downloads/Diploma/bilder` aus. Auch bei einem SSH-Timeout werden vorhandene und neu hinzugefügte lokale Bilder verarbeitet. Nach der Auswertung öffnet sich die 3D-Ansicht im Browser.

| Aufgabe | Befehl |
| --- | --- |
| Lokale Bilder ohne Pi auswerten | `python analyse.py --lokal bilder` |
| Unterschiedliche Pflanzen einzeln auswerten | `python analyse.py --lokal bilder --einzelbilder` |
| Auswerten, ohne den Browser zu öffnen | `python analyse.py --ohne-browser` |
| Bestehende 3D-Ansicht öffnen | `python analyse.py --3d` |
| Ansicht aus gespeicherten Messwerten neu erstellen | `python analyse.py --3d-aus-json auswertung/ergebnis.json` |

## Kamera und Stundenaufnahme

Auf dem Pi wird der vorhandene Kamerahelfer verwendet. Nach der einmaligen Einrichtung wird zu jeder vollen Stunde ein Foto auf dem Pi gespeichert. Der Windows-PC kann dabei ausgeschaltet bleiben. Der Standardaufruf auf Windows holt vorhandene Fotos ab und löst keine zusätzliche Aufnahme aus.

```powershell
python analyse.py --stundenaufnahme-einrichten
python analyse.py --stundenaufnahme-status
```

Die Einrichtung benötigt einen erreichbaren Pi, einen autorisierten SSH-Schlüssel und einen aktiven Cron-Dienst. Der Verbindungstest und die Prüfung der ersten geplanten Aufnahme stehen in der [Übergabe](Atida-Handover.md). Der Pi-Abruf lädt nur fertige JPEGs. Nach einem erfolgreichen Abgleich werden höchstens die letzten 100 importierten Kamera-JPEGs lokal behalten. Andere Bilder und ältere Messwerte bleiben erhalten.

## Ergebnisse lesen

| Pfad unter `auswertung/` | Inhalt |
| --- | --- |
| `masken/`, `kontrolle/` | Binäre Blattmasken und Fotos mit eingezeichneter Blattkontur für die aktuell ausgewerteten Bilder. |
| `ergebnis.csv` | Messwerte je Foto für die Tabellenansicht, einschließlich gespeicherter älterer Messwerte. |
| `ergebnis.json` | Dieselben neuen Messwerte als strukturierte Daten je Foto, mit Status und Messhistorie für die weitere Integration. |
| `grafiken/` | Fünf Diagramme für Fläche, Änderungsrate, Farbe, Gesundheit und Teilwerte. `06_digital_twin.png` zeigt zusätzlich den Modellstand. |
| `digital_twin.json` | Modellzustand, gegebenenfalls eine 24-Stunden-Projektion und das Protokoll ausgegebener Prognosen. |
| `digital_twin_3d.html`, `digital_twin_3d.css` | Lokale Browseransicht und separates Stylesheet. Beide Dateien bleiben im selben Ordner. |

Die Blattfläche wird aus der Maske in Pixeln gezählt. Angaben in cm² und mm benötigen einen verifizierten Maßstab in der Blattebene. Der Gesundheitsscore vergleicht das Foto mit einer Referenz derselben Pflanze. Ein fehlender Wert wird als `NULL` in CSV und `null` in JSON ausgegeben; die Gründe stehen in `fehlende_werte` beziehungsweise `analysis.missing_values`. Ein echter Wert von 0 bleibt eine Zahl.

Bei einem erneuten Lauf werden die vorhandenen Originale neu ausgewertet. Bereits gespeicherte Messungen zu entfernten Originalen behalten ihren damaligen Stand. Für eine neue Pflanze wird ein eigener Eingabe- und Ausgabeordner verwendet, damit ihre Daten getrennt bleiben.

## 3D-Ansicht und Pflegetipps

In **Pflanze** werden Konturen, sichtbare Blattflächen und das Verhältnis von Breite zu Höhe aus der jeweiligen Blattmaske angezeigt. Die Ansicht kann gedreht und über **Von oben** mit dem Foto verglichen werden. Der automatische Blattzählwert ist eine Schätzung; geprüfte Blattlabels können übernommen werden. Unter **Foto, Blattmaske und Kontrolle** werden die verfügbaren Vorschauen angezeigt. Unter **Alle Fotos** können frühere Messungen ausgewählt werden. **Wachstum testen** zeigt, wie sich die modellierte Fläche unter eingegebenen Annahmen verändern würde.

Die HTML-Datei kann auch per Doppelklick geöffnet werden. Für die Ansicht wird kein Webserver benötigt. Optional können Pflegetipps beim Export von einem lokalen [Ollama](https://ollama.com/download)-Modell formuliert werden. Nach der Installation wird das Modell einmal geladen:

```powershell
ollama pull qwen2.5:3b
```

Beim nächsten Analyselauf werden die Messwerte des neuesten brauchbaren Fotos für lokale KI-Tipps verwendet, sofern es die neueste Aufnahme ist. Für ein beliebiges gespeichertes Foto oder alle brauchbaren Fotos kann die KI separat gestartet werden:

```powershell
python analyse.py --pflege-ki "DATEINAME.png"
python analyse.py --pflege-ki "*"
```

Ausgewählte Messwerte werden an Ollama auf demselben PC übergeben. Ist keine KI-Antwort gespeichert, werden Hinweise aus den Messwerten angezeigt. Die Ansicht nutzt die Ebene des Fotos; Höhe, Tiefe und verdeckte Blätter bleiben unbekannt.

## Dokumentation

| Bereich | Dokument |
| --- | --- |
| A-M1 | [Bilderfassungssystem](docs/BB-SPEC-IMG-001_A-M1_Bilderfassungssystem.md): Kamera, Abruf, Maßstab und Maskenkontrolle. |
| A-M2 | [Computer-Vision-Pipeline](docs/BB-REF-MERKMALE-001_A-M2_Computer-Vision-Pipeline.md): Messwerte, CSV/JSON, Diagramme und Historie. |
| A-M3 | [Gesundheitsbewertung](docs/BB-SPEC-HEALTH-001_A-M3_Gesundheitsbewertung.md): Referenz, Lichtabgleich, Score und Gründe für fehlende Werte. |
| A-M4 | [Digital-Twin-Modell](docs/BB-GUIDE-TWIN-001_A-M4_Digital-Twin-Modell.md): 3D-Ansicht, Szenarien, Modellprüfung und Pflegetipps. |
| Betrieb | [Atida-Handover](Atida-Handover.md): Pi, Zeitplan, Archive und Übergabe an die Plattform. |

Der Datenexport für die spätere Integration ist `ergebnis.json`. Die Zuordnung zur Datenbank und der API-Vertrag werden mit Edona abgestimmt. `analyse.py` sendet die Daten nicht automatisch an die Plattform.
