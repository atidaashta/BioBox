# BioBox · Bilderfassungssystem

| Feld | Stand |
|---|---|
| Dokument-ID | BB-SPEC-IMG-001 |
| Meilenstein | A-M1 · Bilderfassungssystem |
| Version | 1.6 |
| Datum | 11.11.2026 |
| Autorin | Atida Ashta |
| Software | analyse.py 4.9.1 |
| Status | Implementierter Analyseablauf; Aufnahmeprofil und reale Messgenauigkeit weiter zu prüfen |

## 1 Zweck

Es wird die **sichtbare projizierte Blattfläche einer einzelnen Pflanze** gemessen. Topf, Erde, Halterung, Fensterrahmen und möglichst auch lange dünne Stiele sollen ausgeschlossen werden. Überlappende oder verdeckte Blattflächen werden nicht hinzugeschätzt. Eine Blattanzahl und eine dreidimensionale Blattoberfläche werden nicht aus einem einzelnen Foto berechnet.

Die Verarbeitung ist nicht auf Basilikum oder einen festgelegten dunklen Grünton beschränkt. Die automatische Initialisierung nutzt jedoch vor allem grünliche Blattbereiche. Für ungewöhnliche Farben oder schwer trennbare Hintergründe ist eine geprüfte Korrekturmaske vorgesehen. Das Verfahren ist keine universell trainierte semantische Blatterkennung.

## 2 Nachgewiesener Aufnahmeweg

- Kamera: Camera Module 3 Wide, vom Pi als `imx708_wide` erkannt.
- Aufnahmegerät: Raspberry Pi 4; die Kamera ist dort angeschlossen.
- Vorhandener Helfer: `/home/biobox/.local/bin/biobox-photo-test --single`.
- Der Helfer speicherte laut ursprünglicher Übergabe 1920 × 1080 Pixel als JPEG mit Qualität 90. Das Aufnahmeprofil wird bei der Einrichtung am Gerät geprüft.
- Vollständige Sitzungen liegen unter `/home/biobox/Pictures/BioBox/recent/<Sitzung>/normal.jpg`.
- Der Sitzungsname enthält den UTC-Aufnahmezeitpunkt. Verzeichnisse mit `.pending-` werden ignoriert.

Mit `python analyse.py` werden vorhandene fertige Stundenfotos abgeglichen; dabei wird keine zusätzliche Aufnahme ausgelöst. Anschließend wird der lokale Bilderordner vollständig neu eingelesen. Bereits vorhandene lesbare Kamera-JPEGs werden nicht erneut übertragen. Lokal werden nach erfolgreichem Abgleich höchstens die neuesten 100 importierten Kamerabilder behalten. Die Bereinigung erfolgt erst nach vollständigem erfolgreichem Download. Andere lokale Bilder und die entfernten Archive werden nicht gelöscht. Die Grenze von 100 gilt für Kameraimporte; manuell ergänzte Dateien werden nicht automatisch begrenzt.

Es werden nur JPEGs vom Pi in den lokalen Bilderordner geladen. Die dortigen Kameraprotokolle und JSON-Begleitdateien werden nicht mitkopiert. Das lokal erzeugte `ergebnis.json` ist eine Analyseausgabe. Bereits gespeicherte Messwerte bleiben in CSV und JSON erhalten, auch wenn ein älteres JPEG aus dem lokalen Bildbestand entfernt wurde.

Der Zugriff erfolgt über Tailscale und normale Secure Shell (SSH, verschlüsselter Fernzugriff). Verwendet wird der Schlüssel gemäß `PI_SSH_KEY`, standardmäßig `~/.ssh/biobox_ed25519`. Durch `BatchMode=yes` wird kein Pi-Passwortdialog geöffnet. Ein verschlüsselter Schlüssel muss vorher im SSH-Agent verfügbar sein.

### Stündliche Aufnahme auf dem Pi

Mit `python analyse.py --stundenaufnahme-einrichten` wird nach einer erfolgreichen Testaufnahme ein eigener Zeitplaneintrag beim Pi-Benutzer eingerichtet. Verwendet wird der Dienst cron mit `0 * * * *`, also einer Aufnahme zu jeder vollen Stunde nach der Pi-Uhr. Der Windows-PC muss dafür nicht laufen. Der Pi muss eingeschaltet und cron aktiv sein. Eine ausgeschaltete Kamera kann keine historischen Aufnahmen nachholen.

Andere Zeitplaneinträge werden erhalten. Vor einer Änderung wird die bisherige Benutzer-Crontab gesichert. Wiederholtes Einrichten erzeugt keinen zweiten eigenen Auftrag. Ein gemeinsamer Kameralock verhindert parallele Aufnahmen durch den neuen Stundenauftrag und die direkte Messaufnahme. Ein blockierter oder fehlerhafter Test schaltet keinen neuen Auftrag ein.

Mit `python analyse.py --abholen` werden vorhandene fertige JPEGs abgeglichen und danach alle lokalen Bilder erneut analysiert. Dies entspricht dem normalen Aufruf `python analyse.py`; beide lösen keine zusätzliche Aufnahme aus. Nur die Einrichtung des Stundenplans und die direkte Linealmessung mit `--massstab` lösen gezielt eine Test- beziehungsweise Messaufnahme aus. `--stundenaufnahme-status` zeigt den eigenen Zeitplan und den letzten protokollierten Aufnahmeversuch; `--stundenaufnahme-ausschalten` entfernt den eigenen markierten Auftrag und erhält vorhandene Fotos. Früher von Hand angelegte Aufnahmejobs werden nicht automatisch entfernt.

Für die stündliche Ausführung wird auf dem Pi ein Helfer unter `~/.local/bin/biobox-hourly-capture.py` erzeugt. Protokoll (`stundenaufnahme.log`), letzter Aufnahmestatus (`stundenaufnahme-status.json`) und Crontab-Sicherungen stehen unter `~/.local/state/BioBox/`. Der Stundenhelfer benötigt keine OpenCV-Installation auf dem Pi. Nach der nächsten vollen Stunde wird geprüft, ob der Zeitplan ein weiteres Foto erzeugt hat. Die Schritte zur Einrichtung und Prüfung stehen in der [Übergabe](../Atida-Handover.md).

### Getrennter Fotoabruf und lokale Auswertung

Der Abruf aktualisiert den lokalen Bildbestand. Die Analyse wird anschließend unabhängig vom Abrufstatus aus diesem Bestand gestartet. Beide Schritte bleiben in `analyse.py` enthalten; ein zweites Programm ist dafür nicht erforderlich.

| Situation | Verarbeitung |
|---|---|
| Abruf erfolgreich | Alle unterstützten lokalen Bilddateien werden erneut eingelesen und ausgewertet. |
| Timeout, fehlender Schlüssel, verweigerte Verbindung oder Übertragungsfehler | Abruffehler wird ausgegeben; vorhandene lokale Fotos werden trotzdem analysiert. |
| Während des Abrufversuchs werden lokale Fotos ergänzt | Diese werden bei der anschließenden neuen Ordnerauswahl berücksichtigt. |
| Keine lokalen Bilder vorhanden | Die bisherigen Ergebnisse bleiben erhalten. Beim normalen Start kann die Browseransicht aus vorhandenen JSON-Messwerten geöffnet werden. |
| `--nur-bild` beim Pi-Abruf | Nur Abruf; keine Analyse, auch bei vorhandenen lokalen Bildern. Nicht mit `--lokal` oder einem lokalen Bildpfad kombinieren. |
| `--lokal bilder` oder positionaler Bildpfad | Nur lokale Analyse; es wird keine Pi-Verbindung versucht. |

Der Standardordner ist `Downloads/Diploma/bilder` im Benutzerverzeichnis. Direkt darin liegende JPG/JPEG-, PNG-, BMP-, TIFF- und WebP-Dateien werden ausgewählt. Unterordner und temporäre Download-Verzeichnisse gehören nicht zur Bildauswahl. Ein erfolgreicher lokaler Analyselauf endet mit `0`, auch wenn der Abruf fehlgeschlagen ist. Ohne Bilder und ohne nutzbare vorhandene JSON-Ausgabe oder bei einem Analysefehler endet der Lauf mit `1`. Im reinen Downloadmodus gilt der Erfolg des Abrufs.

## 3 Aufbau und Vergleichbarkeit

Die Kamera soll möglichst senkrecht auf eine einzelne Pflanze gerichtet werden. Kamera und Topf sollen während einer Messreihe fest stehen. Halterungen sollen möglichst keine Blätter verdecken. Gleichmäßiges Licht, ein ruhiger matter Hintergrund und ein sichtbares neutrales Referenzfeld erleichtern die Auswertung.

Im früheren Bench-Report wurde eine Distanz von 373 mm zwischen Kameraebene und Substratebene dokumentiert (Z 815 − Z 442 mm). Diese Planungsangabe ist kein Maßstab der aktuellen Testaufnahmen und gibt nicht den Abstand der Blattoberfläche zur Kamera an. Die tatsächliche Aufnahmehöhe und die Blattebene müssen am jeweiligen Aufbau bestimmt werden.

Für einen späteren festen Aufnahmebetrieb sollen Belichtung, Verstärkung, Weißabgleich und Fokus überprüft und möglichst konstant gehalten werden. Ein vorhandenes festes Profil wird hier nicht als bereits eingerichteter Zustand behauptet. Ein geplanter LED-Aufnahmezustand muss vor seiner Nutzung mit der Firmware abgestimmt werden.

## 4 Verarbeitung der Blattmaske

1. Das Originalfoto wird gelesen und bei vorhandenem gültigem Objektivprofil entzerrt. Die Arbeitskopie ist höchstens 960 Pixel breit.
2. Blattkerne werden über Grün-Rot- und Blau-Gelb-Komponenten im CIELAB-Farbraum ausgewählt. Ein begrenzter Otsu-Schwellenwert dient als Startwert. Kühle und schwach grüne Halterungen sowie dunkle, wenig grüne Bodenbereiche werden gedämpft.
3. Nur nahe Randbereiche werden ergänzt. Gelb oder braun gewordenes Gewebe kann innerhalb einer registrierten älteren Blattfläche erhalten werden, wenn es an aktuell erfasstes Blattgewebe grenzt. Die alte Maske wird dabei nicht als aktuelle Messung kopiert.
4. Kleine eingeschlossene Lücken werden geschlossen. Dünne, weit vom breiten Blattkern entfernte Verbindungen werden abgetrennt. GrabCut prüft die unsicheren Grenzen in einem begrenzten Randband am Original.
5. Die binäre Maske wird in der Größe des Originalbilds gespeichert: 255 steht für erfasstes Blatt, 0 für ausgeschlossene Bereiche. Die Pixelzahl wird direkt aus dieser Maske bestimmt. Verdeckte Flächen werden nicht ergänzt.

Für jedes lesbare Foto wird eine Kontrollansicht mit dünner Kontur und schwacher Einfärbung erzeugt. Das Foto wird darin höchstens 1500 Pixel breit dargestellt. Die Ansicht enthält keine weiteren Fotoausschnitte. Berührt die Maske den Bild- oder Auswerterand, bleibt die **sichtbare** Fläche bei gleicher oder nachweislich ausrichtbarer Kameraansicht zeitlich vergleichbar. Bei einer kleinen Verschiebung wird dazu nur der gemeinsame Bildausschnitt verwendet. Der Strukturteil des Zustandsindex für die gesamte Pflanze wird dabei ausgesetzt. Stängelreste, sehr schmale Blätter und gleichfarbiger Hintergrund bleiben mögliche Grenzfälle.

### Erneute Auswertung alter Bilder

Jeder Analyselauf verarbeitet die gesamte ausgewählte Bildliste erneut. Automatische Masken, Messwerte, Referenzen und zeitliche Vergleiche werden aus den Originalbildern neu aufgebaut. Der SHA-256-Prüfwert der vollständigen Skriptdatei wird im JSON dokumentiert.

Referenzbilder und Referenzmasken werden ausschließlich im Arbeitsspeicher gehalten. Fällt die bisherige Referenz aus dem lokalen 100-Bilder-Fenster, wird im nächsten Lauf die erste geeignete verbleibende Aufnahme je Ansicht zur Referenz. Gespeicherte historische Messwerte behalten ihren ursprünglichen Bezug. Die JSON-Felder zur Referenz machen beide Fälle nachvollziehbar.

Neue Masken, Kontrollbilder, CSV/JSON, Grafiken und die Browserausgabe werden zunächst getrennt erzeugt und anschließend gemeinsam übernommen. Ein Schreibfehler löst die Wiederherstellung der vorherigen Ausgabe aus. Wird auch diese blockiert, bleibt die Sicherung am gemeldeten Pfad erhalten. Eine gesperrte Excel-Datei oder Vorschau muss vor einem erneuten Lauf geschlossen werden. Geprüfte manuelle Korrekturen und der Maßstab werden wiederverwendet. Parallele Analysen desselben Ausgabeordners werden verhindert.

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

Vorrangig werden überlappende Blattbereiche verglichen. Bei zu wenig Überlappung können nach bestätigtem Lichtabgleich die getrennten Blattfarbverteilungen verglichen werden. Ausgebrannte und sehr dunkle Pixel werden ausgeschlossen. Wenn zu wenig geeignetes Gewebe oder Hintergrund übrig bleibt, wird kein neuer Gesundheitswert ausgegeben. Ein dunkler Hintergrund ohne messbare Referenz kann für den Lichtabgleich unzureichend sein. Ein mattes neutrales Referenzfeld erleichtert die Trennung von Licht- und Pflanzenänderungen. Die Kriterien stehen in der [Gesundheitsbewertung](BB-SPEC-HEALTH-001_A-M3_Gesundheitsbewertung.md).

## 8 Schnittstellen und Grenzen

Der im JSON ausgegebene relative Bildpfad wird aus dem Sitzungsnamen abgeleitet, beispielsweise `recent/20261020T160551Z-bByql4/normal.jpg`. Die Auflösung archivierter Dateien muss bei der späteren Plattformintegration mit den tatsächlichen Serverpfaden abgeglichen werden. UTC-Zeitpunkt und Dateihash werden im JSON-Export mitgegeben. Geräteschlüssel und HTTP-Endpunkt müssen mit Edona abgeglichen werden; durch das Analyseskript werden keine Datensätze an einen unbekannten Endpunkt versendet.

Eine neue Pflanze benötigt eine eigene Messreihe mit eigener Referenz. Für den Wechsel werden die Eingabebilder getrennt und ein eigener Ausgabeordner verwendet, damit auch die erhaltene Messhistorie getrennt bleibt.

Die bisherigen Entwicklungsprüfungen umfassen Originalfotos, kontrollierte Bildveränderungen und einen simulierten Timeout mit einem neuen lokalen Foto. Die Neuerzeugung von Masken, Kontrollen und Messwerten wurde lokal geprüft. Für die Abnahme am Pi werden die tatsächlich geplante Aufnahme, das Aufnahmeprofil und die Übertragung geprüft. Eine belastbare Flächengenauigkeit muss an Originalbildern mit unabhängig geprüften Blattmasken und passendem Maßstab bestimmt werden.

## 9 Grundlagen

- Maßgeblich für den hier beschriebenen Ablauf: [`analyse.py`](../analyse.py), Pipeline 4.9.1, Scoring 4.1.0.
- [Atida-Handover](../Atida-Handover.md) für den dokumentierten Aufnahmeaufbau und die Prüfung am Gerät.
- [OpenCV: GrabCut](https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html).
- [Computer-Vision-Pipeline](BB-REF-MERKMALE-001_A-M2_Computer-Vision-Pipeline.md) und [Digital-Twin-Modell](BB-GUIDE-TWIN-001_A-M4_Digital-Twin-Modell.md).
- [Debian: crontab-Zeitpläne](https://manpages.debian.org/trixie/cron/crontab.5.en.html).
- [Microsoft: SSH-Schlüssel und ssh-agent unter Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).
