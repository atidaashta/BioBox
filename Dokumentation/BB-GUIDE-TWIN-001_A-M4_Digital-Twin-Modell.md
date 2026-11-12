# BioBox · Digital-Twin-Modell und 3D-Ansicht

| Feld | Stand |
| --- | --- |
| Dokument-ID | BB-GUIDE-TWIN-001 |
| Meilenstein | A-M4 · Digital-Twin-Modell |
| Version | 1.7 |
| Datum | 11.11.2026 |
| Software | analyse.py 4.11.0 · Modell 0.1.0 · 3D-Ansicht 0.6.0 |
| Status | Prototyp für lokale Darstellung, Projektion und Szenarien |

## 1. Starten

Mit `analyse.py` 4.11.0 wird im Projektordner folgender Befehl ausgeführt:

```powershell
python analyse.py
```

Nach der Bildauswertung wird die Ansicht im Browser geöffnet. Mit `python analyse.py --3d` kann eine vorhandene Ansicht geöffnet werden. Sind bereits Messwerte vorhanden und soll die Seite daraus neu erstellt werden, kann ohne Pi-Abruf und ohne erneute Bildanalyse folgender Befehl verwendet werden:

```powershell
python analyse.py --3d-aus-json auswertung/ergebnis.json
```

Die erzeugte Datei `auswertung/digital_twin_3d.html` kann auch per Doppelklick geöffnet werden. `digital_twin_3d.js` und `digital_twin_3d.css` müssen im selben Ordner liegen. JavaScript baut die Oberfläche auf und zeichnet die Pflanze. Ein Webserver wird nicht benötigt.

## 2. Ansicht bedienen

Die Seite öffnet die letzte Aufnahme automatisch. Wenn das zugehörige Original vorliegt, erscheint daneben eine kleine Vorschau. Die Pflanze wird mit der Maus oder per Touch gedreht; mit den Pfeiltasten lässt sich die Ansicht ebenfalls bedienen.

Der Regler zeigt die Pflanze zum Zeitpunkt der Aufnahme oder 1 bis 14 Tage später. Unter dem Modell steht die sichtbare Blattfläche. Ohne gültigen Maßstab wird sie in Pixeln angegeben. Wenn kein Bild brauchbar ausgewertet werden konnte, wird kein Pflanzenzustand geschätzt.

## 3. Was das Modell darstellt

Die räumliche Darstellung verwendet, soweit vorhanden, die geschätzte oder beschriftete Zahl sichtbarer Blätter und deren relative Flächen. Die räumliche Anordnung, Stiele und Höhe werden nur illustriert. Eine einzelne Aufnahme liefert keine dreidimensionale Vermessung.

Für spätere Tage wird die Blattfläche mit einer verfügbaren geprüften Änderungsrate aus einem Vergleich über mindestens zwölf Stunden fortgeschrieben. Falls eine solche Rate fehlt, zeigt die Ansicht ein ausdrücklich als Annahme gekennzeichnetes Szenario mit 2 % pro Tag. Der Regler ändert keine Messwerte.

## 4. Dateien

| Datei unter `auswertung/` | Inhalt |
| --- | --- |
| `digital_twin_3d.html` | Kleine Startdatei. |
| `digital_twin_3d.js` | Oberfläche, 3D-Modell und Daten der letzten Aufnahme. |
| `digital_twin_3d.css` | Gestaltung. |
| `ergebnis.csv`, `ergebnis.json` | Vollständiger Export der Bildmessungen. |
| `digital_twin.json` | Daten für die getrennte technische 24-Stunden-Projektion. |

Beim Öffnen per Doppelklick müssen die drei Viewer-Dateien im selben Ordner liegen. Sie werden durch `analyse.py` erzeugt.

## 5. Modell für die nächsten 24 Stunden

Die 24-Stunden-Projektion wird in `analyse.py` aus der gemessenen sichtbaren Blattfläche in Pixeln berechnet. Sie wird getrennt vom Szenario des Reglers aus Abschnitt 3 erzeugt. In `digital_twin.json` stehen der aktuelle Messpunkt (`state`), die Modellrechnung (`forecast`) und der jeweilige Status.

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

## 6. Zugehörige Dokumente

- [A-M1 · Bilderfassungssystem](BB-SPEC-IMG-001_A-M1_Bilderfassungssystem.md): Kamera, Masken und Maßstab.
- [A-M2 · Computer-Vision-Pipeline](BB-REF-MERKMALE-001_A-M2_Computer-Vision-Pipeline.md): Messwerte und gespeicherte Historie.
- [A-M3 · Gesundheitsbewertung](BB-SPEC-HEALTH-001_A-M3_Gesundheitsbewertung.md): Lichtabgleich und Gesundheitsscore.
- [README](../README.md): Installation und Schnellstart.
