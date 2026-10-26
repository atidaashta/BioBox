# Bildaufnahme und Blattmessung BioBox

| Feld | Stand |
|---|---|
| Dokument-ID | BB-SPEC-IMG-001 |
| Version | 1.0 |
| Datum | 26.10.2026 |
| Autorin | Atida Ashta |
| Software | analyse.py 4.0.0 |
| Status | Implementierter Analyseablauf; Aufnahmeprofil und reale Messgenauigkeit weiter zu prüfen |

## 1 Zweck

Es wird die **sichtbare projizierte Blattfläche einer einzelnen Pflanze** gemessen. Topf, Erde, Halterung, Fensterrahmen und möglichst auch lange dünne Stiele sollen ausgeschlossen werden. Überlappende oder verdeckte Blattflächen werden nicht hinzugeschätzt. Eine Blattanzahl und eine dreidimensionale Blattoberfläche werden nicht aus einem einzelnen Foto berechnet.

Die Verarbeitung ist nicht auf Basilikum oder einen festgelegten dunklen Grünton beschränkt. Die automatische Initialisierung nutzt jedoch vor allem grünliche Blattbereiche. Für ungewöhnliche Farben oder schwer trennbare Hintergründe ist eine geprüfte Korrekturmaske vorgesehen. Das Verfahren ist keine universell trainierte semantische Blatterkennung.

## 2 Nachgewiesener Aufnahmeweg

- Kamera: Camera Module 3 Wide, vom Pi als `imx708_wide` erkannt.
- Aufnahmegerät: Raspberry Pi 4; die Kamera ist dort angeschlossen.
- Vorhandener Helfer: `/home/biobox/.local/bin/biobox-photo-test --single`.
- Der Helfer speichert laut Handover 1920 × 1080 Pixel als JPEG mit Qualität 90.
- Vollständige Sitzungen liegen unter `/home/biobox/Pictures/BioBox/recent/<Sitzung>/normal.jpg`.
- Der Sitzungsname enthält den UTC-Aufnahmezeitpunkt. Verzeichnisse mit `.pending-` werden ignoriert.

Mit `python analyse.py` wird eine Aufnahme ausgelöst. Anschließend werden die neuesten verfügbaren Kamera-JPEGs abgeglichen. Bereits vorhandene Bilder werden nicht erneut übertragen. Lokal werden höchstens die neuesten 100 importierten Kamerabilder behalten. Die Bereinigung erfolgt erst nach vollständigem erfolgreichem Download. Andere Dateien und die entfernten Archive werden nicht gelöscht.

Es werden nur JPEGs vom Pi in den lokalen Bilderordner geladen. Die dortigen Kameraprotokolle und JSON-Begleitdateien werden nicht mitkopiert. Das lokal erzeugte `ergebnis.json` ist eine Analyseausgabe und gehört nicht zu diesen Kamera-Begleitdateien.

Der Zugriff erfolgt über Tailscale und normale Secure Shell (SSH, verschlüsselter Fernzugriff). Ein zeitgesteuerter Fotoauftrag wird von `analyse.py` nicht eingerichtet. Ein 30-Minuten-Intervall bleibt ein mögliches Betriebsziel und ist mit der Hardwareseite abzustimmen.

## 3 Aufbau und Vergleichbarkeit

Die Kamera soll möglichst senkrecht auf eine einzelne Pflanze gerichtet werden. Kamera und Topf sollen während einer Messreihe fest stehen. Halterungen sollen möglichst keine Blätter verdecken. Gleichmäßiges Licht, ein ruhiger matter Hintergrund und ein sichtbares neutrales Referenzfeld erleichtern die Auswertung.

Die Raumaufnahme der derzeitigen Testpflanze ist nicht mit dem früheren BioBox-Bench-Aufbau gleichzusetzen. Die alten Annahmen zu 373 mm Einbauhöhe werden **nicht als Maßstab für diese Fotos übernommen**. Die tatsächliche Aufnahmehöhe und Blattebene müssen am jeweiligen Aufbau bestimmt werden.

Für einen späteren festen Aufnahmebetrieb sollen Belichtung, Verstärkung, Weißabgleich und Fokus überprüft und möglichst konstant gehalten werden. Ein vorhandenes festes Profil wird hier nicht als bereits eingerichteter Zustand behauptet. Ein geplanter LED-Aufnahmezustand muss vor seiner Nutzung mit der Firmware abgestimmt werden.

## 4 Verarbeitung der Blattmaske

1. Das Originalfoto wird gelesen und bei vorhandenem gültigem Objektivprofil entzerrt.
2. Für die grobe Erkennung wird eine Arbeitskopie mit höchstens 960 Pixeln Breite erstellt.
3. Blattbereiche werden mit Farbhinweisen und GrabCut, einem Verfahren zur Trennung von Vorder- und Hintergrund, ausgewählt. Eine registrierte frühere Blattmaske kann verfärbte Bereiche stützen.
4. Große zusammenhängende Randflächen werden als Hintergrund geprüft. Lange gerade helle Kanten helfen bei der Erkennung von Rahmen und Halterungen. Nur ausreichend breite Blattkerne werden vor einer solchen Kantenmaske geschützt. Sind genügend helle schwach gesättigte Linienbereiche vorhanden, wird deren Farbstich zusätzlich genutzt, um grünlich beleuchtete warme Bodenbereiche von sicheren Blattkernen auszuschließen. Diese vorsichtige Heuristik ersetzt keine geprüfte Blattmaske.
5. Kleine eingeschlossene helle Gewebelücken dürfen ergänzt werden. Zwischenräume im Topf werden nicht mit einer gemeinsamen konvexen Hülle gefüllt.
6. Die unsicheren Ränder werden am höher aufgelösten Originalbild erneut getrennt. Lange schmale Fortsätze und sehr kleine Störungen werden geprüft.
7. Erst die endgültige binäre Maske wird für Pixelzahl, Fläche und Ausdehnung verwendet. 255 bedeutet erfasstes Blatt, 0 bedeutet ausgeschlossen.

Ein Kontrollbild zeigt die Maske direkt auf dem Original. Es wird nur eine solche Ansicht pro Aufnahme erzeugt. Die Kontrollansicht ist keine Eingabe für eine weitere Messung; dafür wird das unveränderte Original benötigt.

### Geprüfte Korrektur für Grenzfälle

```text
python analyse.py --maske-korrigieren bilder/FOTO.jpg
```

Mit der linken Maustaste werden Blattbereiche ergänzt, mit der rechten wird Hintergrund entfernt. `G` führt GrabCut mit den gezeichneten Hinweisen erneut aus. `+` und `-` ändern den Pinsel, `U` macht eine Änderung rückgängig, `R` stellt den Anfangszustand her. Mit Enter wird gespeichert, mit Esc ohne Speichern abgebrochen.

Alternativ kann eine binäre PNG-Maske mit exakt der Pixelgröße des gegebenenfalls entzerrten Originals übernommen werden:

```text
python analyse.py --maske-korrigieren bilder/FOTO.jpg --korrekturmaske BLATTMASKE.png
```

Die Korrektur wird an den SHA-256-Inhaltshash der Datei und das Objektivprofil gebunden. Sie wird unter `auswertung/masken_korrektur/` gespeichert und bei der erneuten Analyse genau dieses Fotos verwendet. Eine andere Datei bekommt diese Maske nicht automatisch. Die Prüfung der tatsächlichen Blattgrenzen bleibt auch bei einer manuellen Korrektur erforderlich.

## 5 Pixel und physische Maße

Die Pixelzahl ist die Anzahl weißer Pixel der endgültigen Maske. Der Maßstab `s` wird in Millimetern pro Pixel angegeben:

```text
Blattfläche in cm² = Blattpixel × s² / 100
Durchmesser in mm  = größte Ausdehnung der maskierten Pixeloberfläche × s
```

Der Durchmesser ist die größte Entfernung zwischen äußeren Pixelgrenzen, nicht nur die Breite eines achsenparallelen Rechtecks. Es werden nur erfasste Blattbereiche einbezogen.

### Maßstab mit einer bekannten Strecke

Ein Lineal muss bei der Aufnahme auf Höhe der zu messenden Blattebene liegen. Anschließend werden die zwei Endpunkte einer tatsächlich bekannten Strecke markiert:

```text
python analyse.py --massstab --referenz-mm 50
```

Dies löst eine neue Aufnahme aus. `50` ist nur ein Beispiel für eine wirklich gemessene Strecke. Für ein vorhandenes Foto wird `--massstab-bild bilder/FOTO.jpg --referenz-mm 50` verwendet. Der gespeicherte Maßstab wird nur für eine passende registrierte Kameraansicht und dasselbe Objektivprofil wiederverwendet.

Eine unveränderte Ansicht beweist keine unveränderte Blatthöhe. Nach einer Änderung von Kamera- oder Blattebene muss neu gemessen werden. Blätter auf verschiedenen Höhen sowie geneigte Blätter werden mit einer einzelnen ebenen Referenz nur näherungsweise physisch vermessen. Ohne verifizierten Maßstab bleiben cm² und mm `NULL`; Pixelwerte bleiben verfügbar.

Die automatische Marker-Alternative verwendet vier ArUco-Referenzmarker mit IDs 0–3 und bekannter Kantenlänge. Dafür müssen auch Kamera-, Marker- und Blatthöhe bekannt sein. Fehlende Marker verhindern nicht die Pixel- oder Farbauswertung.

## 6 Objektivkalibrierung

Die Wide-Optik kann besonders am Rand geometrische Verzerrungen verursachen. Für genauere physische Flächenmessungen wird eine passende Objektivkalibrierung benötigt. Dazu werden mehrere Schachbrettaufnahmen über das Bildfeld verteilt aufgenommen. Das konfigurierte Muster enthält 9 × 6 innere Ecken, also 10 × 7 Felder; die tatsächliche Feldgröße muss zu `FELD_MM` passen.

```text
python analyse.py --kalibrieren kalibrierbilder
```

Die erzeugte `kamera_kalibrierung.json` enthält Kameramatrix, Verzerrung und Kalibrier-Bildgröße. Für eine andere Auflösung desselben Seitenverhältnisses wird die Matrix skaliert. Ein anderer Zuschnitt oder ein altes Profil ohne Bildgröße wird nicht stillschweigend als passend angenommen. Nach Kamera-, Objektiv- oder Profilwechsel muss die Messreihe überprüft werden.

## 7 Licht und Gesundheitsvergleich

Der Gesundheitsvergleich verwendet eine separate lichtkorrigierte Arbeitskopie. Die Korrektur wird aus passenden Hintergrundpixeln derselben Ansicht geschätzt, nicht aus den Blattfarben. Linearer Helligkeits- und Kanaldrift sowie geeignete langsame Lichtverläufe können dadurch ausgeglichen werden. Die Rohfarbwerte im Export werden nicht überschrieben.

Ausgebrannte oder zu dunkle Blattpixel werden in beiden Vergleichsbildern gemeinsam ausgeschlossen. Wenn zu wenig geeignetes Gewebe oder Hintergrund übrig bleibt, wird kein neuer Gesundheitswert ausgegeben. Ein dunkler schwarzer Hintergrund ohne messbare Referenz kann für einen verlässlichen Lichtabgleich unzureichend sein. Ein kleines mattes neutrales Referenzfeld hilft bei der Trennung von Licht- und Pflanzenänderungen.

## 8 Schnittstellen und Grenzen

Der stabile Bildpfad lautet beispielsweise `recent/20261020T160551Z-bByql4/normal.jpg`. Dieser Pfad bleibt auch nach der Archivierung verwendbar. UTC-Zeitpunkt und Dateihash werden im JSON-Export mitgegeben. Geräteschlüssel und HTTP-Endpunkt müssen mit Edona abgeglichen werden; durch das Analyseskript werden keine Datensätze an einen unbekannten Endpunkt versendet.

Eine neue Pflanzenart benötigt keinen fest vorgeschriebenen Grünton, aber eine eigene Messreihe mit eigener Referenz. Alte und neue Pflanzen dürfen nicht gemeinsam als Wachstumsverlauf bewertet werden. Beim Pflanzenwechsel werden die Eingabebilder getrennt und die Referenz für die tatsächlich ausgewählte neue Bildserie gebildet.

Die aktuelle Prüfung umfasst ein vorhandenes Originalfoto und kontrollierte Bildveränderungen. Daraus wird keine universelle Segmentierungsgenauigkeit für andere Pflanzen oder jede Aufnahme abgeleitet. Eine belastbare Flächengenauigkeit muss an Originalbildern mit unabhängig geprüften Blattmasken und passendem Maßstab bestimmt werden.

## 9 Grundlagen

- Projektdatei `Atida-Handover.md`, Stand 20.10.2026, für Aufnahme- und Archivpfade.
- OpenCV, GrabCut: https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html
- BB-SPEC-HEALTH-001 und BB-REF-MERKMALE-001 in der zu diesem Stand gehörenden Version.
