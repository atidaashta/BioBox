# Bildaufnahme und Blattmessung BioBox

| Feld | Stand |
|---|---|
| Dokument-ID | BB-SPEC-IMG-001 |
| Version | 1.3 |
| Datum | 04.11.2026 |
| Autorin | Atida Ashta |
| Software | analyse.py 4.3.0 |
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

Der Zugriff erfolgt über Tailscale und normale Secure Shell (SSH, verschlüsselter Fernzugriff).

### Stündliche Aufnahme auf dem Pi

Mit `python analyse.py --stundenaufnahme-einrichten` wird nach einer erfolgreichen Testaufnahme ein eigener Zeitplaneintrag beim Pi-Benutzer eingerichtet. Verwendet wird der Dienst cron mit `0 * * * *`, also einer Aufnahme zu jeder vollen Stunde nach der Pi-Uhr. Der Windows-PC muss dafür nicht laufen. Der Pi muss eingeschaltet und cron aktiv sein. Eine ausgeschaltete Kamera kann keine historischen Aufnahmen nachholen.

Andere Zeitplaneinträge werden erhalten. Vor einer Änderung wird die bisherige Benutzer-Crontab gesichert. Wiederholtes Einrichten erzeugt keinen zweiten eigenen Auftrag. Ein gemeinsamer Kameralock verhindert parallele Aufnahmen durch den neuen Stundenauftrag und den normalen Abruf. Ein blockierter oder fehlerhafter Test schaltet keinen neuen Auftrag ein.

Mit `python analyse.py --abholen` werden später vorhandene fertige JPEGs abgeglichen und alle lokalen Kamerabilder erneut analysiert. Es wird dabei keine zusätzliche Aufnahme ausgelöst. `python analyse.py` bleibt der Weg für eine sofortige neue Aufnahme mit anschließendem Abgleich. `--stundenaufnahme-status` zeigt den eigenen Zeitplan und den letzten protokollierten Aufnahmeversuch; `--stundenaufnahme-ausschalten` entfernt den eigenen Auftrag und erhält vorhandene Fotos.

Für die stündliche Ausführung wird auf dem Pi ein kleiner Helfer unter `~/.local/bin/biobox-hourly-capture.py` erzeugt. Protokoll und letzter Aufnahmestatus stehen unter `~/.local/state/BioBox/`. Der Stundenhelfer benötigt keine OpenCV-Installation auf dem Pi. Ein realer erfolgreicher Aufnahmeversuch ist erst nach der Einrichtung am tatsächlichen Gerät bestätigt.

## 3 Aufbau und Vergleichbarkeit

Die Kamera soll möglichst senkrecht auf eine einzelne Pflanze gerichtet werden. Kamera und Topf sollen während einer Messreihe fest stehen. Halterungen sollen möglichst keine Blätter verdecken. Gleichmäßiges Licht, ein ruhiger matter Hintergrund und ein sichtbares neutrales Referenzfeld erleichtern die Auswertung.

Die Raumaufnahme der derzeitigen Testpflanze ist nicht mit dem früheren BioBox-Bench-Aufbau gleichzusetzen. Die alten Annahmen zu 373 mm Einbauhöhe werden **nicht als Maßstab für diese Fotos übernommen**. Die tatsächliche Aufnahmehöhe und Blattebene müssen am jeweiligen Aufbau bestimmt werden.

Für einen späteren festen Aufnahmebetrieb sollen Belichtung, Verstärkung, Weißabgleich und Fokus überprüft und möglichst konstant gehalten werden. Ein vorhandenes festes Profil wird hier nicht als bereits eingerichteter Zustand behauptet. Ein geplanter LED-Aufnahmezustand muss vor seiner Nutzung mit der Firmware abgestimmt werden.

## 4 Verarbeitung der Blattmaske

1. Das Originalfoto wird gelesen und bei vorhandenem gültigem Objektivprofil entzerrt. Die Arbeitskopie ist höchstens 960 Pixel breit.
2. Blattkerne werden über Grün-Rot- und Blau-Gelb-Komponenten im CIELAB-Farbraum ausgewählt. Ein begrenzter Otsu-Schwellenwert dient als Startwert. Kühle und schwach grüne Halterungen sowie dunkle, wenig grüne Bodenbereiche werden gedämpft.
3. Nur nahe Randbereiche werden ergänzt. Gelb oder braun gewordenes Gewebe kann innerhalb einer registrierten älteren Blattfläche erhalten werden, wenn es an aktuell erfasstes Blattgewebe grenzt. Die alte Maske wird dabei nicht als aktuelle Messung kopiert.
4. Kleine eingeschlossene Lücken werden geschlossen. Dünne, weit vom breiten Blattkern entfernte Verbindungen werden abgetrennt. GrabCut prüft die unsicheren Grenzen in einem begrenzten Randband am Original.
5. Die binäre Maske wird in der Größe des Originalbilds gespeichert: 255 steht für erfasstes Blatt, 0 für ausgeschlossene Bereiche. Die Pixelzahl wird direkt aus dieser Maske bestimmt. Verdeckte Flächen werden nicht ergänzt.

Für jedes lesbare Foto wird eine Kontrollansicht mit dünner Kontur und schwacher Einfärbung erzeugt. Das Foto wird darin höchstens 1500 Pixel breit dargestellt. Die Ansicht enthält keine weiteren Fotoausschnitte. Berührt die Maske den Bild- oder Auswerterand, bleibt die **sichtbare** Fläche bei unverändertem Bildausschnitt zeitlich vergleichbar. Der Strukturteil des Zustandsindex für die gesamte Pflanze wird dabei ausgesetzt. Stängelreste, sehr schmale Blätter und gleichfarbiger Hintergrund bleiben mögliche Grenzfälle.

### Erneute Auswertung alter Bilder

Jeder Analyselauf verarbeitet die gesamte ausgewählte Bildliste erneut. Auch die automatische Referenzmaske wird neu berechnet. Ein SHA-256-Prüfwert der vollständigen Skriptdatei erkennt Änderungen, selbst wenn die Versionsnummer nicht angepasst wurde. Bei einem geänderten Verfahren werden alte Scorehistorien verworfen und die ausgewählten Bilder mit dem neuen Verfahren bewertet.

Bei neu angelegten Referenzen wird das ursprüngliche Referenzbild zusätzlich in `referenz.npz` erhalten. Dadurch kann seine Maske auch nach dem Ausscheiden aus dem 100-Bilder-Fenster neu berechnet werden. Bei alten Referenzen wird das Original nachgeladen, sofern es noch ausgewählt werden kann. Ist nur eine alte verkleinerte Referenz vorhanden, können verlorene Bilddetails nicht zurückgewonnen werden.

Neue Masken, Kontrollbilder, CSV/JSON-Ergebnisse, Grafiken und Referenz werden zunächst getrennt erzeugt und anschließend zusammen übernommen. Ein Schreibfehler führt zur Wiederherstellung der vorherigen Ausgaben. Ist eine Datei in Excel oder einer Vorschau gesperrt, muss sie geschlossen und der Lauf wiederholt werden. Bereits bestätigte manuelle Korrekturmasken und der Maßstab werden erhalten.

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

Nur überlappende Blattbereiche werden verglichen. Ausgebrannte oder zu dunkle Pixel werden in beiden Vergleichsbildern gemeinsam ausgeschlossen. Wenn zu wenig geeignetes Gewebe oder Hintergrund übrig bleibt, wird kein neuer Gesundheitswert ausgegeben. Ein dunkler schwarzer Hintergrund ohne messbare Referenz kann für einen verlässlichen Lichtabgleich unzureichend sein. Ein kleines mattes neutrales Referenzfeld hilft bei der Trennung von Licht- und Pflanzenänderungen.

## 8 Schnittstellen und Grenzen

Der im JSON ausgegebene relative Bildpfad wird aus dem Sitzungsnamen abgeleitet, beispielsweise `recent/20261020T160551Z-bByql4/normal.jpg`. Die Auflösung archivierter Dateien muss bei der späteren Plattformintegration mit den tatsächlichen Serverpfaden abgeglichen werden. UTC-Zeitpunkt und Dateihash werden im JSON-Export mitgegeben. Geräteschlüssel und HTTP-Endpunkt müssen mit Edona abgeglichen werden; durch das Analyseskript werden keine Datensätze an einen unbekannten Endpunkt versendet.

Eine neue Pflanzenart benötigt keinen fest vorgeschriebenen Grünton, aber eine eigene Messreihe mit eigener Referenz. Alte und neue Pflanzen dürfen nicht gemeinsam als Wachstumsverlauf bewertet werden. Beim Pflanzenwechsel werden die Eingabebilder getrennt und die Referenz für die tatsächlich ausgewählte neue Bildserie gebildet.

Die aktuelle Prüfung umfasst ein vorhandenes Originalfoto und kontrollierte Bildveränderungen. Daraus wird keine universelle Segmentierungsgenauigkeit für andere Pflanzen oder jede Aufnahme abgeleitet. Eine belastbare Flächengenauigkeit muss an Originalbildern mit unabhängig geprüften Blattmasken und passendem Maßstab bestimmt werden.

## 9 Grundlagen

- Projektdatei `Atida-Handover.md`, Stand 20.10.2026, für Aufnahme- und Archivpfade.
- OpenCV, GrabCut: https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html
- BB-SPEC-HEALTH-001 und BB-REF-MERKMALE-001 in der zu diesem Stand gehörenden Version.

- Debian, cron-Zeitpläne: https://manpages.debian.org/trixie/cron/crontab.5.en.html
