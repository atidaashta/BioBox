# BioBox · Digital-Twin-Modell und 3D-Ansicht

| Feld | Stand |
| --- | --- |
| Dokument-ID | BB-GUIDE-TWIN-001 |
| Meilenstein | A-M4 · Digital-Twin-Modell |
| Version | 1.13 |
| Datum | 13.11.2026 |
| Software | digital_twin.py · Modell 0.1.0 · 3D-Ansicht 0.7.0 |
| Status | Prototyp für lokale Darstellung, Projektion und Szenarien |

## 1. Starten

Der gesamte Aufnahme- und Analyseablauf wird im Projektordner gestartet:

```powershell
python analyse.py
```

Nach der Bildauswertung wird die Ansicht im Browser geöffnet. Für vorhandene Daten wird die Ansicht separat geöffnet:

```powershell
python digital_twin.py
```

Sind bereits Messwerte vorhanden und sollen nur die Daten für die Ansicht aktualisiert werden, kann ohne Pi-Abruf und ohne erneute Bildanalyse folgender Befehl verwendet werden:

```powershell
python digital_twin.py --3d-aus-json auswertung/ergebnis.json
```

Die Seite wird über einen lokalen Server geöffnet. Das JavaScript lädt `digital_twin.json` automatisch und zeichnet die Pflanze. Wird die HTML-Datei direkt geöffnet, lässt der Browser den automatischen Zugriff auf die JSON-Datei nicht zu. `digital_twin_3d.js` und `digital_twin_3d.css` liegen neben der HTML-Datei. `python analyse.py --3d` bleibt als gleichwertiger Startbefehl verfügbar.

Bei Ergebnissen einer älteren Version wird mit `python analyse.py --lokal bilder` aus den vorhandenen Originalen neu segmentiert. Werden nur die gespeicherten JSON-Daten geöffnet, bleiben deren frühere Blattkonturen und Zählwerte maßgeblich.

## 2. Ansicht bedienen

Es wird das Modell der letzten Aufnahme gezeigt. Die Pflanze wird mit der Maus oder per Touch gedreht. Mit den Pfeiltasten lässt sich die Ansicht ebenfalls drehen; Doppelklick oder die Taste `Pos1` stellen die Startperspektive wieder her.

Über **Blätter zählen** werden alle im Modell verwendeten Blätter getrennt und nummeriert gezeigt. `≈` steht für eine automatisch geschätzte Anzahl. Über **Zur Pflanze** wird in die drehbare Ansicht gewechselt. Der Regler zeigt die Pflanze zum Aufnahmezeitpunkt oder als Szenario für 1 bis 14 Tage danach. Fehlen brauchbare Blattkonturen, wird kein Ersatzmodell aus erfundenen Blättern aufgebaut.

### Sichtbare Blätter nachzählen

Wenn Blätter im Originalfoto erkennbar sind, aber vom Programm falsch getrennt wurden, kann je sichtbarem Blatt einmal auf eine Stelle innerhalb des Blatts geklickt werden:

```powershell
python analyse.py --blaetter-markieren "bilder/FOTO.jpg"
python analyse.py --lokal bilder
```

`FOTO.jpg` wird durch den tatsächlichen Dateinamen ersetzt. Mit Rechtsklick oder `U` wird der letzte Punkt entfernt, mit `R` werden alle Punkte geleert und mit `F` wird zwischen Ausschnitt und ganzem Foto gewechselt. Gespeichert wird mit Enter. Beim nächsten Lauf wird je gültigem Punkt ein Blatt erzeugt. Liegt ein Punkt deutlich außerhalb der Messmaske, wird er bei der Prüfung gemeldet; dann kann die Markierung oder die Blattmaske korrigiert werden. Bereits importierte, passende Blattlabel-PNGs haben Vorrang.

## 3. Was das Modell darstellt

Für jede erkannte oder markierte Blattregion wird eine gewölbte Oberfläche aufgebaut. Position, Länge, Breite, Orientierung, sichtbare Kontur und Grundfarbe werden aus der zugehörigen Bildregion angenähert. Tiefe, Stiele und Blattwölbung werden modelliert. Für senkrecht von oben aufgenommene Bilder kann in `digital_twin.py` `TWIN_FOTOANSICHT = "oben"` gesetzt werden. Eine einzelne Aufnahme liefert keine dreidimensionale Vermessung und zeigt keine vollständig verdeckten Blätter.

Für spätere Tage wird die Modellgröße anhand einer verfügbaren geprüften Änderungsrate aus einem Vergleich über mindestens zwölf Stunden angepasst. Falls eine solche Rate fehlt, werden 2 % pro Tag als Annahme verwendet. Die Ansicht kennzeichnet spätere Tage als Szenario. Die Form wird nur in einem begrenzten Größenbereich skaliert; eine neue Blattanzahl und ein genauer späterer Wuchs werden daraus nicht abgeleitet. Der Regler ändert keine Messwerte.

## 4. Dateien

| Datei | Inhalt |
| --- | --- |
| `digital twin/digital_twin_3d.html` | Aufbau der Oberfläche mit Modellansicht, Blattliste und Regler. |
| `digital twin/digital_twin_3d.js` | Laden der Daten, Bedienung und Darstellung des 3D-Modells. |
| `digital twin/digital_twin_3d.css` | Gestaltung. |
| `auswertung/ergebnis.csv`, `auswertung/ergebnis.json` | Vollständiger Export der Bildmessungen. |
| `digital twin/digital_twin.json` | Zustand, 24-Stunden-Projektion, Prognosehistorie und Blattdaten der letzten Aufnahme unter `viewer`. |

Die drei Viewer-Dateien sind fester Quellcode und werden nicht von `analyse.py` überschrieben. Aus der Analyse oder aus gespeicherten Bildmessungen werden nur die Daten im JSON aktualisiert. Beim Öffnen eines gespeicherten Ergebnisses werden die bestehende Modellrechnung und die Prognosehistorie nicht neu berechnet. Die Gesundheitsansicht liegt separat unter `gesundheitssystem/`.

## 5. Modell für die nächsten 24 Stunden

Die 24-Stunden-Projektion wird in `digital_twin.py` aus der gemessenen sichtbaren Blattfläche in Pixeln berechnet. Sie wird getrennt vom Szenario des Reglers aus Abschnitt 3 erzeugt. In `digital_twin.json` stehen der aktuelle Messpunkt (`state`), die Modellrechnung (`forecast`) und der jeweilige Status.

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
