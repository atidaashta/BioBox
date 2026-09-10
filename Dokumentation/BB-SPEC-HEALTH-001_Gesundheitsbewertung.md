# Spezifikation Gesundheitsbewertung BioBox

| | |
|---|---|
| **Dokument-ID** | BB-SPEC-HEALTH-001 |
| **Version** | 0.1 (Entwurf) |
| **Datum** | 10.09.2026 |
| **Autorin** | Atida Ashta |
| **Arbeitspaket** | 3. Gesundheitsbewertungssystem, PSP 3.1–3.8 |
| **Meilenstein** | A-M3 |
| **Vorgänger** | BB-SPEC-IMG-001 (Bildaufnahme) |
| **Status** | Entwurf – Kennlinien noch nicht an realen Pflanzen kalibriert |

---

## 1. Zweck

Dieses Dokument legt fest, wie aus den Bildmerkmalen ein **Gesundheitswert von 0 bis 10** für die Basilikumpflanze in der BioBox berechnet wird. Es beschreibt die Eingangsgrößen, die Bewertungsregeln, die Zustandskategorien und die Warnmeldungen.

Der Gesundheitswert ist ausdrücklich **kein biologisch-medizinischer Absolutwert**, sondern ein technischer Zustandsindex für Anzeige, Alarmierung und als Eingangsgröße für das Digital-Twin-Modell (A-M4). Diese Einordnung ist bewusst gewählt: Eine Kamera misst Farbe, nicht Pflanzengesundheit. Der Index ist ein reproduzierbarer Indikator, dessen Aussagekraft in Abschnitt 9 offen benannt wird.

---

## 2. Grundsatzentscheidung: Bewertung gegen den eigenen Referenzzustand

Die zentrale Entwurfsentscheidung lautet: **Die Pflanze wird gegen ihren eigenen früheren Zustand bewertet, nicht gegen absolute Farbsollwerte.**

Ein absoluter Ansatz („gesundes Basilikum hat Hue = 40, Sättigung = 170") wäre einfacher, aber fachlich nicht haltbar. Die gemessenen Farbwerte hängen ab von:

- dem gewählten Weißabgleich der Kamera (in BB-SPEC-IMG-001 bewusst fest, aber willkürlich eingestellt),
- dem Spektrum der verwendeten LED,
- der Basilikumsorte,
- der Belichtungseinstellung.

Ein auf einem Aufbau kalibrierter Absolutwert wäre auf einem anderen Aufbau wertlos. Der relative Ansatz umgeht das: Weißabgleich, LED und Belichtung sind über den gesamten Zyklus fixiert, also kürzen sich ihre Einflüsse aus dem Vergleich heraus.

Die Randbedingung, die das überhaupt möglich macht, ist die Aufnahmesituation: **alle Bilder zeigen dieselbe Pflanze unter identischen, fixierten Bedingungen.** Genau deshalb ist ein Vergleich mit der eigenen Vorgeschichte zulässig.

**Bekannte Schwäche des Ansatzes:** Ist die Pflanze bereits in der Referenzphase krank, wird dieser Zustand als „gesund" definiert. Eine schleichende Verschlechterung ab dem ersten Tag wird dann nicht erkannt. Gegenmaßnahme: Die Referenzphase wird zusätzlich manuell per Sichtprüfung der Kontrollbilder freigegeben (siehe 4).

---

## 3. Eingangsgrößen

Alle Eingangsgrößen stammen aus der Computer-Vision-Pipeline (A-M2) und liegen je Aufnahme in `ergebnisse.csv` vor.

| Merkmal | Bedeutung | Verwendung |
|---|---|---|
| `gruenindex` | G / (R+G+B) über allen Pflanzenpixeln | Chlorophyllgehalt |
| `mittel_s` | mittlere HSV-Sättigung | Farbkraft, Vitalität |
| `mittel_h` | mittlerer HSV-Farbton | Verschiebung des Grüntons |
| `gelbanteil_pct` | Anteil gelber Pixel an der Pflanzenfläche | Chlorose |
| `braunanteil_pct` | Anteil brauner Pixel an der Pflanzenfläche | Nekrose |
| `brauchbar` | Qualitätsprüfung bestanden | Filter |
| `blattflaeche_cm2` | projizierte Blattfläche | Wachstumsstillstand |
| `stunden_seit_start` | Zeitachse | Trend, Stillstand |

Nicht bewertet werden `pflanzen_pixel` und `bedeckungsgrad_pct` als Gesundheitsgrößen: Eine wachsende Pflanze wird zwangsläufig größer, Größe ist also kein Gesundheitssignal. Wachstum geht ausschließlich über die **Rate** ein (siehe 8).

---

## 4. Referenzphase

Die Referenz wird aus den **ersten 10 als brauchbar eingestuften Aufnahmen** gebildet. Verwendet wird jeweils der **Median**, nicht der Mittelwert, weil der Median gegen einzelne Ausreißer unempfindlich ist.

Referenzgrößen: `gruenindex`, `mittel_s`, `mittel_h`, `gelbanteil_pct`, `braunanteil_pct`.

Bedingungen:

1. Mindestens 3 brauchbare Bilder, sonst erfolgt keine Bewertung (Kategorie `keine_referenz`).
2. Die Kontrollbilder der Referenzphase werden **manuell gesichtet und freigegeben**. Das Datum der Freigabe wird protokolliert.
3. Die Referenz wird bei jedem Programmlauf neu aus denselben ersten Bildern gebildet und ist damit reproduzierbar.
4. Ein Eingriff nach BB-SPEC-IMG-001 Abschnitt 8.2 (Kamera verschoben, nachfokussiert, Hintergrund gewechselt) macht die bisherige Referenz **ungültig**. Die Messreihe beginnt in diesem Fall neu.

---

## 5. Teilscores und Kennlinien

Jeder Teilscore läuft von 0 bis 10 und ist eine **lineare Kennlinie** zwischen einem Wert für 10 Punkte und einem Wert für 0 Punkte. Linear und nicht z. B. sigmoid, weil jeder Zwischenwert von Hand nachrechenbar sein soll — eine Anforderung an die Verteidigbarkeit der Arbeit.

| Teilscore | Eingangsgröße | 10 Punkte bei | 0 Punkte bei |
|---|---|---|---|
| `score_gruen` | `gruenindex` / Referenz | ≥ 1,00 | ≤ 0,85 |
| `score_saettigung` | `mittel_s` / Referenz | ≥ 0,95 | ≤ 0,70 |
| `score_gelb` | `gelbanteil_pct` − Referenz | ≤ 0 Prozentpunkte | ≥ 25 Prozentpunkte |
| `score_braun` | `braunanteil_pct` − Referenz | ≤ 0 Prozentpunkte | ≥ 10 Prozentpunkte |
| `score_farbton` | \|`mittel_h` − Referenz\| | ≤ 2 | ≥ 12 |

**Begründung der Bandbreiten:**

Der Braunbereich ist mit 10 Prozentpunkten enger gefasst als der Gelbbereich mit 25. Vergilbung unterer Blätter ist bei Basilikum teilweise normale Alterung und reversibel; braunes Gewebe ist abgestorben und wächst nicht zurück. Gleicher Flächenanteil bedeutet also nicht gleiche Schwere, und die Kennlinie bildet das ab.

Sättigung darf bis 0,95 des Referenzwerts fallen, ohne Punktverlust — kleine Schwankungen sind normal. Unter 0,70 ist die Farbkraft so weit eingebrochen, dass ein deutlicher Stresszustand vorliegt.

---

## 6. Gewichtung und Gesamtscore

```
gesundheit_roh = 0,30 · score_gruen
               + 0,25 · score_gelb
               + 0,20 · score_braun
               + 0,15 · score_saettigung
               + 0,10 · score_farbton
```

Summe der Gewichte = 1,0, Ergebnis daher wieder 0 bis 10.

**Begründung:** Der Grünindex erhält das höchste Gewicht, weil er direkt mit dem Chlorophyllgehalt und damit der Photosyntheseleistung zusammenhängt. Gelb und Braun folgen als konkrete Schadbilder. Sättigung und Farbton sind unspezifischer und wirken eher unterstützend; sie erhalten deshalb weniger Gewicht, werden aber nicht weggelassen, weil sie früher reagieren als die Flächenanteile.

Die Gewichte sind **Startwerte**, keine Naturkonstanten. Sie sind in der Implementierung als eine Konstante zusammengefasst und werden im Testbetrieb (PSP 3.8) anhand realer Pflanzenzustände nachjustiert. Jede Änderung ist zu protokollieren.

---

## 7. Glättung und Kategorien

### 7.1 Glättung

Der Anzeigewert `gesundheit` ist der **gleitende Median der letzten 5 Rohscores**, nicht der Rohwert selbst. Grund: Ein einzelnes schlecht belichtetes oder verwackeltes Bild darf keinen Alarm auslösen.

Das Fenster ist in **Bildern** definiert, nicht in Stunden. Bei dem in BB-SPEC-IMG-001 festgelegten Intervall von 30 Minuten entsprechen 5 Bilder etwa 2,5 Stunden — eine sinnvolle Verzögerung. **Wird das Aufnahmeintervall geändert, muss dieser Wert mit angepasst werden**, sonst verzögert die Glättung die Erkennung um Tage statt Stunden.

### 7.2 Kategorien

| Score | Kategorie | Bedeutung |
|---|---|---|
| 8,5 – 10 | sehr gut | keine Abweichung vom Referenzzustand |
| 7,0 – 8,5 | gut | geringe Abweichung, kein Handlungsbedarf |
| 5,0 – 7,0 | beobachten | erkennbare Abweichung, Ursache prüfen |
| 3,0 – 5,0 | auffällig | deutliche Verschlechterung, Eingriff erwägen |
| 0 – 3,0 | kritisch | massive Abweichung, sofortige Prüfung |

### 7.3 Trend

Zusätzlich wird `gesundheit_trend_24h` als Differenz zum Wert vor 24 Stunden ausgegeben. Für die Beurteilung ist die **Richtung oft aussagekräftiger als der Absolutwert**: Ein Score von 7,0 mit fallender Tendenz ist bedenklicher als ein stabiler Score von 6,0.

---

## 8. Warnmeldungen

Neben dem Zahlenwert wird je Aufnahme eine Textspalte `gesundheitswarnung` gesetzt. Eine Zahl allein sagt nicht, *was* das Problem ist.

| Warnung | Auslöser | Typische Ursache |
|---|---|---|
| `vergilbung` | Gelbanteil ≥ 8 Prozentpunkte über Referenz | Stickstoffmangel, Staunässe, Lichtmangel |
| `nekrose` | Braunanteil ≥ 3 Prozentpunkte über Referenz | Verbrennung, Krankheit, abgestorbenes Gewebe |
| `chlorose` | Grünindex ≤ 93 % der Referenz | Nährstoffmangel, Wurzelprobleme |
| `entfaerbung` | Sättigung ≤ 88 % der Referenz | Welke, allgemeiner Stress |
| `wachstumsstillstand` | keine Flächenzunahme über 48 h | Wasser-, Licht- oder Nährstoffmangel |

Die Zuordnung der Ursachen ist ausdrücklich **hinweisend, nicht diagnostisch**. Das System stellt fest, dass sich etwas verändert hat; die Ursache muss der Betrachter beurteilen.

`wachstumsstillstand` ist die einzige nicht farbbasierte Warnung. Sie ist aufgenommen, weil eine Pflanze in Stillstand gehen kann, ohne die Farbe zu ändern — dieser Fall bliebe rein farbbasiert unentdeckt.

---

## 9. Grenzen des Verfahrens

Diese Abschnitte gehören in die Dokumentation, weil sie in der Verteidigung ohnehin gefragt werden.

**9.1 Die Segmentierung versagt genau dann, wenn die Pflanze krank ist.**
Im Test mit simulierter Vergilbung zerfiel die Maske ab einem Gelbanteil von etwa 60 % in Teilflächen und die Aufnahmen wurden als `zersplittert` verworfen. Ursache: Die Segmentierung beruht auf Excess Green (2G − R − B). Verliert die Pflanze ihr Grün, verliert der Index sein Trennmerkmal. Das ist eine grundsätzliche Eigenschaft des Verfahrens, kein Programmierfehler. Konsequenz: Bei sehr starker Vergilbung wird der letzte gültige Score fortgeschrieben, statt fälschlich Werte zu berechnen. Für schwere Schadfälle ist die Aussagekraft dadurch begrenzt.

**9.2 Nur die Oberseite wird bewertet.**
Die Top-Down-Kamera sieht die oberste Blattschicht. Vergilbung beginnt bei Basilikum typischerweise an den **unteren** Blättern und wird daher spät erkannt.

**9.3 Der Index ersetzt keine Sichtprüfung.**
Schädlinge, Mehltau und Wurzelprobleme sind aus einem Farbmittelwert nicht ableitbar.

**9.4 Die Referenz ist nur so gut wie die Pflanze zu Beginn.**
Siehe Abschnitt 2.

**9.5 Die Kennlinien sind noch nicht an realen Pflanzen kalibriert.**
Alle Zahlenwerte in Abschnitt 5 und 8 sind begründete Startwerte aus Tests mit simulierten Bildern. Die Kalibrierung ist Gegenstand von PSP 3.8.

---

## 10. Validierung (PSP 3.8)

**10.1 Funktionstest mit simulierten Verläufen**
20 Bilder derselben Pflanze, ab Bild 11 künstlich zunehmend vergilbt.
Erwartung: konstant 10 in der Referenzphase, danach monoton fallend, Warnungen in der Reihenfolge Vergilbung → Chlorose → Nekrose.
*Ergebnis: bestätigt. Score fiel von 10,0 auf 2,1; Warnungen erschienen in der erwarteten Reihenfolge.*

**10.2 Nullprobe**
Gesunde Pflanze über 7 Tage ohne Eingriff.
Abnahmekriterium: Score bleibt in der Kategorie `sehr gut`, keine Fehlalarme.

**10.3 Provokationstest**
Eine Pflanze wird kontrolliert unter Stress gesetzt (z. B. 5 Tage ohne Bewässerung). Der Zeitpunkt der ersten Warnung wird mit der ersten visuellen Auffälligkeit für einen menschlichen Betrachter verglichen.
Kernfrage: Erkennt das System den Stress **früher** als das bloße Auge? Genau darin liegt der Nutzen des Systems.

**10.4 Abgleich mit unabhängiger Einschätzung**
Mindestens 20 Aufnahmen werden von einer Person unabhängig auf einer Skala von 1 bis 10 beurteilt. Verglichen wird die Rangkorrelation zwischen manueller Beurteilung und berechnetem Score.
Abnahmekriterium: Rangkorrelation ≥ 0,7.

**10.5 Robustheitstest**
Bewusst schlechte Bilder (unscharf, überbelichtet, Marker verdeckt) werden eingespeist. Abnahmekriterium: Diese Bilder gehen nicht in die Bewertung ein, und die Glättung verhindert einen Score-Sprung.

---

## 11. Schnittstelle zur Webplattform (PSP 3.7)

Anforderung an Edona Peraj: Ergänzung der Tabelle `image_measurements` um folgende Felder. Im Konzeptentwurf ist bisher nur `stress_score` vorgesehen; das reicht für die Darstellung nicht aus.

```sql
health_score          NUMERIC(4,2),   -- geglaetteter Wert 0..10
health_score_raw      NUMERIC(4,2),   -- ungeglaetteter Wert
health_category       TEXT,           -- sehr gut | gut | beobachten | auffaellig | kritisch
health_trend_24h      NUMERIC(4,2),
health_warnings       TEXT,           -- semikolongetrennt
score_green           NUMERIC(4,2),
score_yellow          NUMERIC(4,2),
score_brown           NUMERIC(4,2),
score_saturation      NUMERIC(4,2),
score_hue             NUMERIC(4,2),
scoring_version       TEXT NOT NULL   -- Version der Gewichte und Kennlinien
```

`scoring_version` ist verpflichtend: Werden Gewichte oder Kennlinien angepasst, sind alte und neue Scores nicht mehr vergleichbar. Ohne dieses Feld ist später nicht rekonstruierbar, welche Regel einen gespeicherten Wert erzeugt hat.

Vorschlag für die Darstellung im Dashboard: Gesamtscore als Zahl mit Kategoriefarbe, darunter die fünf Teilscores als Balken. Der Nutzen liegt in der Aufschlüsselung — ein Wert von 6,0 mit `score_braun` = 2 bedeutet etwas völlig anderes als 6,0 mit `score_farbton` = 2.

---

## 12. Offene Punkte

| Nr. | Punkt | Zu klären bis |
|---|---|---|
| H-1 | Kalibrierung aller Kennlinien an realer Pflanze | PSP 3.8 |
| H-2 | Gewichtung nach Provokationstest überprüfen | PSP 3.8 |
| H-3 | Glättungsfenster an tatsächliche Aufnahmerate anpassen | nach Inbetriebnahme |
| H-4 | Umgang mit sehr starker Vergilbung (siehe 9.1) | offen |
| H-5 | Erfassung unterer Blattetagen (Seitenkamera?) — optionales Ziel A-O1 | offen |
