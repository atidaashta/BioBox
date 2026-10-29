"""BioBox: Kamera, Blattmaske, Messwerte, relativer Zustandsindex und 5 Grafiken.

Installation: python -m pip install opencv-contrib-python numpy matplotlib
Normal:       python analyse.py
Nur lokal:    python analyse.py --lokal bilder
Pi-Stundenplan einrichten: python analyse.py --stundenaufnahme-einrichten
Vorhandene Pi-Fotos holen: python analyse.py --abholen
Zeitplan pruefen/stoppen:   --stundenaufnahme-status / --stundenaufnahme-ausschalten
Nur Download: python analyse.py --nur-bild
Massstab:     python analyse.py --massstab-bild bilder/FOTO.jpg --referenz-mm 50
              Dann die zwei Linealmarken im Bild anklicken, Enter druecken.
              50 ist nur ein Beispiel: echte gemessene Laenge einsetzen!
Direkt neu:   python analyse.py --massstab --referenz-mm 50
              Vorher Lineal auf Blatthoehe ins Bild legen. Aufnehmen + markieren.
Einzelbilder verschiedener Pflanzen: python analyse.py --lokal bilder --einzelbilder
Neue Pflanze / geaenderter Aufbau: eigener Bildordner und --neue-referenz.
Maske pruefen/korrigieren: python analyse.py --maske-korrigieren bilder/FOTO.jpg
Import einer geprueften Originalmaske: zusaetzlich --korrekturmaske MASKE.png

Jeder Lauf berechnet alle ausgewaehlten Bilder erneut, auch alte Aufnahmen.
Masken, Kontrollbilder, CSV/JSON und Grafiken werden gemeinsam ersetzt.
Bei gesperrten Ausgabedateien bleibt die vorherige komplette Auswertung erhalten.
Ein Skript-Hash verhindert alte automatische Referenzmasken nach Codeaenderungen.
Eine ausfuehrbare Datei; gesundheit.py und grafiken.py werden nicht importiert.
Nur Kamera-JPEGs werden vom Pi geladen, lokal bleiben die neuesten 100.
Die Ausgabe enthaelt IMMER einen Datensatz je Eingabebild, auch bei Fehlern.
ergebnis.json enthaelt Zahlen/null, ergebnis.csv ist eine Excel-Kontrollansicht
(UTF-8, Semikolon, Dezimalkomma). Diagramme lesen direkt dieselben Datensaetze.

WICHTIG ZUR AUSSAGE:
Der Index misst sichtbare AENDERUNGEN gegen diese Pflanze, keine Diagnose.
100 bedeutet "wie die Referenz", nicht "biologisch gesund". Die automatische
Referenz ist vorlaeufig, bis die Kontrollbilder manuell gesichtet wurden.
Die Kennlinien sind technische Startwerte, nicht biologisch validiert.
Ohne Massstab in der Blattebene bleiben cm2/mm null; Pixelwerte sind messbar.
Linealwerte sind projizierte Groessen in der eingerichteten Referenzebene,
nicht die 3D-Blattoberflaeche. Bei veraenderter Kamera- oder Blatthoehe neu eichen.
Ohne echte Aufnahmezeit bleiben Wachstumsraten und 24h-Trend null.
Die Segmentierung trennt ueber den Gegenfarbkanal a* (CIELAB) und Otsu.
Sie wurde an einer echten panaschierten Pflanze geprueft und ist klassische
Bildverarbeitung, kein universelles Blatt-Erkennungsmodell.
Otsu teilt JEDES Bild in zwei Klassen. Ohne Pflanze im Bild kann deshalb
eine kleine Restflaeche uebrigbleiben; dagegen hilft kein Schwellwert,
sondern nur das Kontrollbild. Bei Dunkelheit und Rauschen bleibt die
Maske dank CHROMA_MIN leer.
Bei neuem Hintergrund oder anderen Blattfarben Kontrollbild pruefen.
Blattraender werden am Original verfeinert. Individuelle Korrekturen werden
dateigenau gespeichert und beim naechsten Lauf wiederverwendet.
Belichtung, Weissabgleich und langsame Lichtgradienten werden ausschliesslich
am registrierten Hintergrund korrigiert. Blattfarben werden NICHT an eine
Sollfarbe angepasst. Ausgebrannte Pixel werden paarweise ausgeschlossen.
Ohne verlaessliche Lichtmessung kein erfundener Score. CSV-Farben sind Rohwerte.

API: Die Messfeldnamen orientieren sich an BB-DB-HEALTH-001. Die endgueltige
HTTP-Struktur/IDs sind noch mit Edona abzustimmen. Es wird nichts versendet.
API_MESSFELDER ist die einzige Stelle fuer die Zuordnung Deutsch -> Englisch.
Kein stiller Ersatz von fehlenden Werten durch Null oder einen alten Score.
Grundlagen: BB-SPEC-IMG-001, BB-SPEC-HEALTH-001, BB-REF-MERKMALE-001.
OpenCV: docs.opencv.org/4.x/d7/d1b/group__imgproc__misc.html (Otsu)
        docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html (Maskenkorrektur)
        docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html
"""

import argparse
import contextlib
import csv
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

# ---------------- Einstellungen -------------------------------------
PI_ADRESSE = "biobox@100.65.232.105"
PI_AUFNAHME = "/home/biobox/.local/bin/biobox-photo-test --single"
PI_FOTO_ORDNER = "/home/biobox/Pictures/BioBox/recent"
BILDER_ORDNER = Path.home() / "Downloads" / "Diploma" / "bilder"
MAX_KAMERA_BILDER = 100
DEVICE_ID = None  # Erst Edonas echte Datenbank-ID eintragen, keine ID erfinden.
MESSREIHE = "pflanze-01"
REFERENZ_FREIGEGEBEN = False  # Kennzeichnet den Score; blockiert ihn nicht.
MM_PRO_PIXEL_MANUELL = None  # Nur verifizierter Massstab IN DER BLATTEBENE.
KAMERA_HOEHE_MM = None
BLATT_HOEHE_MM = None
MARKER_HOEHE_MM = 0.0
MARKER_MM = 40.0
KALIBRIERUNG = Path(__file__).resolve().with_name("kamera_kalibrierung.json")
SCHACHBRETT = (9, 6)
FELD_MM = 25.0
ROI_NORMIERT = None  # Optional: (links, oben, rechts, unten), Werte 0..1.
ARBEITSBREITE = 960
CHROMA_MIN = 4            # a*-Mindestabstand von Grau; darunter keine Pflanze
RATE_MIN_STUNDEN = 12     # Mindestzeitbasis der Wachstumsrate gegen Maskenrauschen
SCORING_VERSION = "3.0.0"
ANALYSE_VERSION = "4.1.0"
PIPELINE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ENDUNGEN = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
CSV_DEZIMALKOMMA = True

# Die alten DB-Teilscores bleiben benannt, werden aber relativ und stetig
# berechnet. Gruen bewertet jetzt auch die gesamte Farbverteilung, nicht
# einen angenommenen gesunden Gruenton. Struktur wirkt zusaetzlich (20 %).
GEWICHTE = {"gruen": .30, "gelb": .20, "braun": .25, "saettigung": .15, "farbton": .10}
# Abweichung, bei der ein Teilscore auf 50 faellt. Startwerte, an echten
# Verlaeufen zu validieren (PSP 3.8).
HALBWERTE = {"hist": .16, "gruenindex": .022, "gelb": 9., "braun": 5.,
             "saettigung": .20, "farbton": 7., "flaeche": .22, "form": .55}
SPALTEN = [
    "bild", "captured_at", "zeitquelle", "stunden_seit_start", "pflanzen_pixel",
    "blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
    "wachstumsrate_cm2_pro_tag", "wachstumsrate_pct_pro_tag",
    "mittel_r", "mittel_g", "mittel_b", "farbe_hex", "mittel_h", "mittel_s",
    "gruenindex", "gelbanteil_pct", "braunanteil_pct", "mm_pro_pixel",
    "massstab_quelle", "schaerfe", "rauschen", "bildhelligkeit",
    "ueberbelichtet_pct", "groesste_komponente_pct", "auffaelligkeit", "brauchbar", "fehlende_werte",
    "pipeline_version", "scoring_version", "gesundheit", "gesundheit_roh", "gesundheit_kategorie",
    "gesundheit_status", "gesundheit_trend_24h", "gesundheitswarnung",
    "score_gruen", "score_gelb", "score_braun", "score_saettigung", "score_farbton",
]
RUNDUNG = {"stunden_seit_start": 4, "blattflaeche_cm2": 2, "durchmesser_mm": 1,
           "kompaktheit": 4, "wachstumsrate_cm2_pro_tag": 3, "wachstumsrate_pct_pro_tag": 3,
           "mittel_r": 1, "mittel_g": 1, "mittel_b": 1, "mittel_h": 1, "mittel_s": 1,
           "gruenindex": 4, "gelbanteil_pct": 2, "braunanteil_pct": 2,
           "mm_pro_pixel": 6, "schaerfe": 1, "rauschen": 2, "bildhelligkeit": 1,
           "ueberbelichtet_pct": 2, "groesste_komponente_pct": 1}
RUNDUNG.update({k: 1 for k in SPALTEN if k.startswith("score_") or k in
                ("gesundheit", "gesundheit_roh", "gesundheit_trend_24h")})
API_MESSFELDER = {
    "pflanzen_pixel": "plant_pixels", "blattflaeche_cm2": "leaf_area_cm2",
    "durchmesser_mm": "diameter_mm", "kompaktheit": "compactness",
    "wachstumsrate_cm2_pro_tag": "growth_rate_cm2_per_day",
    "wachstumsrate_pct_pro_tag": "growth_rate_pct_per_day",
    "mittel_r": "mean_r", "mittel_g": "mean_g", "mittel_b": "mean_b",
    "mittel_h": "mean_hue", "mittel_s": "mean_saturation",
    "gruenindex": "greenness_index", "gelbanteil_pct": "yellow_fraction_pct",
    "braunanteil_pct": "brown_fraction_pct", "mm_pro_pixel": "mm_per_px",
    "massstab_quelle": "scale_source", "schaerfe": "sharpness",
    "rauschen": "noise", "bildhelligkeit": "image_brightness",
    "groesste_komponente_pct": "largest_component_pct", "farbe_hex": "color_hex",
    "pipeline_version": "pipeline_version",
    "ueberbelichtet_pct": "overexposed_pct", "auffaelligkeit": "quality_flags",
    "brauchbar": "usable",
}
API_GESUNDHEIT = {
    "gesundheit_status": "health_status",
    "scoring_version": "scoring_version", "gesundheit": "health_score",
    "gesundheit_roh": "health_score_raw", "gesundheit_kategorie": "health_category",
    "gesundheit_trend_24h": "health_trend_24h", "gesundheitswarnung": "health_warnings",
    "score_gruen": "score_green", "score_gelb": "score_yellow",
    "score_braun": "score_brown", "score_saettigung": "score_saturation",
    "score_farbton": "score_hue",
}
GRAFIK_DATEIEN = ["01_wachstum.png", "02_wachstumsrate.png", "03_farbverlauf.png",
                  "04_gesundheit.png", "05_teilscores.png"]

def jpeg_lesbar(pfad):
    """Nur vollstaendige, lesbare JPEGs als bereits heruntergeladen behandeln."""
    try:
        with Path(pfad).open("rb") as datei:
            if datei.read(2) != b"\xff\xd8":
                return False
        bild = cv2.imread(str(pfad))
        return bild is not None and min(bild.shape[:2]) >= 3
    except OSError:
        return False

def pi_bilder_holen(neue_aufnahme=True):
    """Neu aufnehmen, vorhandene Aufnahmen abgleichen, lokal die letzten 100 behalten.

    Die UTC-Aufnahmezeit im Sitzungsnamen bestimmt die Reihenfolge, nicht das
    Download-Datum. Bereits importierte Bilder bleiben auch erhalten, wenn die
    Pi-Archivierung sie aus 'recent' entfernt hat. Andere Dateien werden nie
    in die Bereinigung einbezogen. Die Bereinigung folgt erst nach einem
    vollstaendig erfolgreichen Download aller fehlenden, ausgewaehlten JPEGs.
    """
    if shutil.which("ssh") is None:
        raise RuntimeError("ssh fehlt. Bitte den Windows-OpenSSH-Client aktivieren.")
    if not isinstance(MAX_KAMERA_BILDER, int) or MAX_KAMERA_BILDER < 1:
        raise RuntimeError("MAX_KAMERA_BILDER muss mindestens 1 sein.")
    verbindung = ["-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
                  "-o", "ServerAliveCountMax=2"]
    # Der Helfer veroeffentlicht nur fertige Sitzungen. .pending-* kann im
    # find-Ergebnis erscheinen, wird aber vom strengen Sitzungsmuster verworfen.
    auflisten = (f"find {shlex.quote(PI_FOTO_ORDNER)} -mindepth 2 -maxdepth 2 "
                 "-type f -name normal.jpg -printf 'BIOBOX_FOTO:%h\\n'")
    print(("Neue Aufnahme und Bildliste" if neue_aufnahme else "Vorhandene Bildliste")+
          f" von {PI_ADRESSE}; Pi-Passwort ggf. eingeben.",flush=True)
    # Derselbe Lock wie bei der stuendlichen Aufnahme auf dem Pi.
    capture = ('mkdir -p "$HOME/.local/state/BioBox" && '
               'flock -w 30 "$HOME/.local/state/BioBox/camera.lock" '+PI_AUFNAHME)
    befehl = capture+" && "+auflisten if neue_aufnahme else auflisten
    aufnahme = subprocess.run(
        ["ssh", *verbindung, PI_ADRESSE, befehl],
        check=True, stdout=subprocess.PIPE, text=True, timeout=180)

    muster = re.escape(PI_FOTO_ORDNER) + r"/(\d{8}T\d{6}Z-[A-Za-z0-9]+)"
    remote, neue_sitzungen = set(), []
    for zeile in aufnahme.stdout.splitlines():
        zeile = zeile.strip()
        if zeile.startswith("Photos and camera metadata:"):
            treffer = re.fullmatch(muster, zeile.split(":", 1)[1].strip())
            if treffer and ist_pi_bild(f"biobox_{treffer[1]}.jpg"):
                neue_sitzungen.append(treffer[1])
        elif zeile.startswith("BIOBOX_FOTO:"):
            treffer = re.fullmatch(muster, zeile[len("BIOBOX_FOTO:"):])
            if treffer and ist_pi_bild(f"biobox_{treffer[1]}.jpg"):
                remote.add(treffer[1])
    if neue_aufnahme and (len(neue_sitzungen) != 1 or neue_sitzungen[0] not in remote):
        raise RuntimeError("Der Pi hat keinen eindeutigen neuen Fotoordner gemeldet.")

    BILDER_ORDNER.mkdir(parents=True, exist_ok=True)
    lokal = {p.name[len("biobox_"):-4]: p for p in BILDER_ORDNER.iterdir()
             if p.is_file() and not p.is_symlink() and ist_pi_bild(p)}
    vorhanden = {s for s, p in lokal.items() if jpeg_lesbar(p)}
    auswahl = sorted(remote | vorhanden)[-MAX_KAMERA_BILDER:]
    fehlend = [s for s in auswahl if s not in vorhanden]
    print(f"Pi: {len(remote)} fertige Aufnahmen; lokal behalten: {len(auswahl)}; "
          f"herunterladen: {len(fehlend)}")

    if fehlend:
        # Alle fehlenden JPEGs in EINER weiteren SSH-Verbindung uebertragen,
        # damit nicht fuer jedes einzelne Bild das Passwort abgefragt wird.
        dateinamen = {f"{s}/normal.jpg": f"biobox_{s}.jpg" for s in fehlend}
        befehl = (f"tar -cf - -C {shlex.quote(PI_FOTO_ORDNER)} -- "
                  + " ".join(shlex.quote(n) for n in dateinamen))
        with tempfile.TemporaryDirectory(dir=BILDER_ORDNER, prefix=".biobox-download-") as tmp:
            tmp = Path(tmp)
            paket = tmp / "download.tar"
            print("Kamera-JPEGs herunterladen; Pi-Passwort ggf. erneut eingeben.", flush=True)
            with paket.open("wb") as stream:
                subprocess.run(["ssh", *verbindung, PI_ADRESSE, befehl],
                               check=True, stdout=stream, timeout=600)
            erhalten = set()
            with tarfile.open(paket, "r:") as archiv:
                for eintrag in archiv:
                    if (eintrag.name not in dateinamen or not eintrag.isfile()
                            or eintrag.name in erhalten):
                        raise RuntimeError("Unerwarteter Inhalt beim Bilddownload.")
                    ziel = tmp / dateinamen[eintrag.name]
                    with archiv.extractfile(eintrag) as quelle, ziel.open("wb") as datei:
                        shutil.copyfileobj(quelle, datei)
                    if not jpeg_lesbar(ziel):
                        raise RuntimeError(f"JPEG nicht lesbar: {eintrag.name}")
                    erhalten.add(eintrag.name)
            if erhalten != set(dateinamen):
                raise RuntimeError("Der Bilddownload ist unvollstaendig. Keine alten Bilder entfernt.")
            for name in dateinamen.values():
                ziel = BILDER_ORDNER / name
                if ziel.is_symlink():
                    raise RuntimeError(f"Zieldatei ist eine Verknuepfung: {ziel}")
            for name in dateinamen.values():
                (tmp / name).replace(BILDER_ORDNER / name)

    behalten = {f"biobox_{s}.jpg" for s in auswahl}
    entfernt = 0
    for pfad in lokal.values():
        if pfad.name not in behalten:
            pfad.unlink()
            entfernt += 1
    print(f"{len(fehlend)} JPEGs geladen, {entfernt} aeltere lokale Kamera-Bilder entfernt.")
    print(f"{len(auswahl)} Kamera-Bilder in: {BILDER_ORDNER}")
    return [BILDER_ORDNER / f"biobox_{s}.jpg" for s in auswahl]

def vorhandene_bilder(ordner):
    """Alle lesbaren Bilddateien eines Ordners, zeitlich sortiert."""
    ordner = Path(ordner)
    if not ordner.is_dir():
        return []
    return sorted(p for p in ordner.iterdir()
                  if p.is_file() and p.suffix.lower() in ENDUNGEN)


def ist_pi_bild(pfad):
    """Nur Bilder unserer Pi-Importe, keine danebenliegenden Datensatzbilder."""
    treffer = re.fullmatch(r"biobox_(\d{8}T\d{6}Z)-[A-Za-z0-9]+\.jpg",
                           os.path.basename(pfad))
    if treffer is None:
        return False
    try:
        datetime.strptime(treffer[1], "%Y%m%dT%H%M%SZ")
        return True
    except ValueError:
        return False

# Der Pi-Teil braucht nur die Python-Standardbibliothek, kein OpenCV.
PI_STUNDEN_RUNNER = r'''import fcntl,json,os,re,signal,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
CFG = __KONFIGURATION__
state = Path.home()/'.local/state/BioBox'
state.mkdir(parents=True,exist_ok=True)
os.umask(0o077)
lock = (state/'camera.lock').open('a+b')
try:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(75)  # Eine andere Aufnahme ist gerade aktiv, keine zweite starten.
log = state/'stundenaufnahme.log'
if log.exists() and log.stat().st_size>1048576:
    log.replace(state/'stundenaufnahme.log.1')
env = os.environ.copy()
env['PATH'] = str(Path.home()/'.local/bin')+':/usr/local/bin:/usr/bin:/bin'
result = {'zeit':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'ok':False,'datei':None}
code = 1
with log.open('a',encoding='utf-8') as stream:
    stream.write('\n'+result['zeit']+' Aufnahme gestartet\n');stream.flush()
    try:
        proc = subprocess.Popen(CFG['argv'],stdout=subprocess.PIPE,stderr=stream,text=True,
                                env=env,start_new_session=True)
    except OSError as error:
        result['fehler']='Aufnahmehelfer nicht gestartet: '+str(error)
        stream.write(json.dumps(result,ensure_ascii=False)+'\n')
        tmp=state/'stundenaufnahme-status.tmp';tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        tmp.replace(state/'stundenaufnahme-status.json')
        sys.exit(1)
    try:
        output,_ = proc.communicate(timeout=240)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGTERM)
        try: output,_ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);output,_ = proc.communicate()
        result['fehler']='Aufnahme nach 240 Sekunden abgebrochen'
    else:
        folders = [line.split(':',1)[1].strip() for line in output.splitlines()
                   if line.startswith('Photos and camera metadata:')]
        if proc.returncode==0 and len(folders)==1:
            folder = Path(folders[0]);photo=folder/'normal.jpg'
            if (folder.parent==Path(CFG['ordner']) and
                    re.fullmatch(r'\d{8}T\d{6}Z-[A-Za-z0-9]+',folder.name) and photo.is_file()):
                with photo.open('rb') as f:
                    good=f.read(2)==b'\xff\xd8'
                    if photo.stat().st_size>128:
                        f.seek(-2,os.SEEK_END);good=good and f.read(2)==b'\xff\xd9'
                    else:good=False
                if good and photo.stat().st_size>128:
                    result.update(ok=True,datei=str(photo));code=0
        if not result['ok']:result['fehler']='Keine eindeutige fertige normal.jpg; Rueckgabecode '+str(proc.returncode)
    stream.write(output[-6000:]+'\n'+json.dumps(result,ensure_ascii=False)+'\n')
tmp=state/'stundenaufnahme-status.tmp';tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
tmp.replace(state/'stundenaufnahme-status.json')
sys.exit(code)
'''

PI_STUNDEN_SETUP = r'''import fcntl,json,os,shlex,shutil,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
CFG = __KONFIGURATION__
RUNNER = __RUNNER__
os.umask(0o077)
state=Path.home()/'.local/state/BioBox';state.mkdir(parents=True,exist_ok=True)
with (state/'zeitplan.lock').open('a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    if not shutil.which('crontab'):raise RuntimeError('crontab fehlt. Auf dem Pi: sudo apt install cron')
    env=os.environ.copy();env['LC_ALL']='C'
    read=subprocess.run(['crontab','-l'],capture_output=True,text=True,env=env)
    if read.returncode==0:previous=read.stdout
    elif read.returncode==1 and not read.stdout and 'no crontab' in read.stderr.lower():previous=''
    else:raise RuntimeError('Vorhandener Zeitplan konnte nicht sicher gelesen werden: '+read.stderr.strip())
    begin='# BEGIN BIOBOX STUNDENAUFNAHME'
    end='# END BIOBOX STUNDENAUFNAHME'
    lines=previous.splitlines(keepends=True)
    plain=[];inside=False;seen=False
    for line in lines:
        if line.strip()==begin:
            if inside or seen:raise RuntimeError('Doppelter BioBox-Zeitplan. Bitte vorhandene Eintraege pruefen.')
            inside=True;seen=True
        elif line.strip()==end:
            if not inside:raise RuntimeError('Unvollstaendiger BioBox-Zeitplan.')
            inside=False
        elif not inside:plain.append(line)
    if inside:raise RuntimeError('Unvollstaendiger BioBox-Zeitplan.')
    service=subprocess.run(['systemctl','is-active','cron'],capture_output=True,text=True)
    cron_ok=service.returncode==0
    boot=subprocess.run(['systemctl','is-enabled','cron'],capture_output=True,text=True)
    cron_boot=boot.returncode==0
    wrapper=Path.home()/'.local/bin/biobox-hourly-capture.py'
    action=CFG['aktion']
    if action=='status':
        last=state/'stundenaufnahme-status.json'
        print(json.dumps({'aktiv':seen and wrapper.is_file() and cron_ok,'eingetragen':seen,
                          'cron_aktiv':cron_ok,'cron_start_beim_boot':cron_boot,
                          'letzte_aufnahme':json.loads(last.read_text()) if last.exists() else None},ensure_ascii=False))
    else:
        if action=='einrichten':
            if not cron_ok:raise RuntimeError('cron ist nicht aktiv. Auf dem Pi: sudo systemctl enable --now cron')
            if not cron_boot:raise RuntimeError('cron startet nicht beim Booten. Auf dem Pi: sudo systemctl enable --now cron')
            if not Path(CFG['argv'][0]).is_file():raise RuntimeError('Aufnahmehelfer fehlt: '+CFG['argv'][0])
            wrapper.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile('w',dir=wrapper.parent,prefix='.biobox-capture-',suffix='.py',delete=False) as f:
                f.write(RUNNER);candidate=Path(f.name)
            try:
                test=subprocess.run([sys.executable,str(candidate)],timeout=270)
                if test.returncode!=0:raise RuntimeError('Testaufnahme fehlgeschlagen oder Kamera belegt. Zeitplan nicht veraendert. --stundenaufnahme-status zeigt den letzten Versuch.')
                new_runner=RUNNER
            finally:candidate.unlink(missing_ok=True)
            command=shlex.quote(sys.executable)+' '+shlex.quote(str(wrapper))+' >/dev/null 2>&1'
            command=command.replace('%',r'\%')
            clean=''.join(plain)
            updated=clean+('' if not clean or clean.endswith('\n') else '\n')+begin+'\n0 * * * * '+command+'\n'+end+'\n'
        elif action=='ausschalten':
            updated=''.join(plain);new_runner=None
        else:raise RuntimeError('Unbekannte Zeitplanaktion')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=state/('crontab-vorher-'+stamp+'.txt');backup.write_text(previous,encoding='utf-8')
        old_runner=wrapper.read_bytes() if wrapper.exists() else None
        try:
            if new_runner is not None:
                temp=wrapper.with_suffix('.tmp');temp.write_text(new_runner,encoding='utf-8');temp.chmod(0o700);temp.replace(wrapper)
            subprocess.run(['crontab','-'],input=updated,text=True,capture_output=True,check=True,env=env)
        except Exception:
            if new_runner is not None:
                if old_runner is None:wrapper.unlink(missing_ok=True)
                else:wrapper.write_bytes(old_runner)
            raise
        print(json.dumps({'aktiv':action=='einrichten','testaufnahme':action=='einrichten','zeitplan':'0 * * * *','sicherung':str(backup)},ensure_ascii=False))
'''


def stundenaufnahme(aktion):
    """Den eigenen Pi-Zeitplan einrichten/pruefen/stoppen, andere Jobs erhalten."""
    cfg={'aktion':aktion,'argv':shlex.split(PI_AUFNAHME),'ordner':PI_FOTO_ORDNER}
    if not cfg['argv'] or not cfg['argv'][0].startswith('/'):
        raise ValueError('PI_AUFNAHME braucht den absoluten Pfad des Aufnahmehelfers.')
    runner=PI_STUNDEN_RUNNER.replace('__KONFIGURATION__',repr(cfg))
    script=PI_STUNDEN_SETUP.replace('__KONFIGURATION__',repr(cfg)).replace('__RUNNER__',repr(runner))
    if shutil.which('ssh') is None:raise ValueError('Windows-OpenSSH-Client fehlt.')
    print(f'Pi-Stundenaufnahme: {aktion}; Pi-Passwort ggf. eingeben.',flush=True)
    result=subprocess.run(['ssh','-o','ConnectTimeout=15','-o','ServerAliveInterval=15',
                           '-o','ServerAliveCountMax=2',PI_ADRESSE,'python3 -'],
                          input=script,text=True,stdout=subprocess.PIPE,check=True,timeout=330)
    data=json.loads(result.stdout)
    if aktion=='status':
        print('Stundenaufnahme aktiv.' if data['aktiv'] else 'Stundenaufnahme NICHT aktiv.')
        if not data.get('cron_start_beim_boot'):print('cron startet aktuell nicht beim Booten des Pi.')
        last=data.get('letzte_aufnahme')
        if last:print('Letzter Versuch:',last.get('zeit'), '|',last.get('datei') if last.get('ok') else last.get('fehler'))
        else:print('Noch kein Aufnahmeversuch protokolliert.')
    elif aktion=='einrichten':
        print('Testaufnahme erfolgreich. Der Pi nimmt jetzt zu jeder vollen Stunde auf, auch ohne Windows-PC.')
        print('Spaeter mit python analyse.py --abholen die JPEGs holen und alle Bilder neu auswerten.')
    else:print('Der BioBox-Stundenplan ist ausgeschaltet. Gespeicherte Fotos bleiben erhalten.')
    return data


def kalibrieren(ordner):
    """Bestimmt die Verzeichnung aus Schachbrettaufnahmen."""
    pfade = sorted(os.path.join(ordner, n) for n in os.listdir(ordner)
                   if n.lower().endswith(ENDUNGEN))
    if len(pfade) < 5:
        print(f"mindestens 5 Schachbrettbilder noetig, {len(pfade)} gefunden")
        return

    muster = np.zeros((SCHACHBRETT[0] * SCHACHBRETT[1], 3), np.float32)
    muster[:, :2] = np.mgrid[0:SCHACHBRETT[0], 0:SCHACHBRETT[1]].T.reshape(-1, 2)
    muster *= FELD_MM

    welt, bildpunkte, groesse = [], [], None
    for pfad in pfade:
        grau = cv2.imread(pfad, cv2.IMREAD_GRAYSCALE)
        if grau is None:
            continue
        if groesse is None:
            groesse = grau.shape[::-1]
        elif groesse != grau.shape[::-1]:
            print(f"   {os.path.basename(pfad)}: andere Bildgroesse, ausgelassen")
            continue
        gefunden, ecken = cv2.findChessboardCorners(grau, SCHACHBRETT, None)
        print(f"   {os.path.basename(pfad):34s} "
              f"{'Muster erkannt' if gefunden else 'nichts gefunden'}")
        if gefunden:
            ecken = cv2.cornerSubPix(
                grau, ecken, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
            welt.append(muster)
            bildpunkte.append(ecken)

    if len(welt) < 5:
        print(f"\nnur {len(welt)} brauchbare Aufnahmen - Kalibrierung abgebrochen")
        return

    fehler, matrix, verzeichnung, _, _ = cv2.calibrateCamera(
        welt, bildpunkte, groesse, None, None)

    json.dump({"kamera_matrix": matrix.tolist(),
               "bildgroesse": list(groesse),
               "verzeichnung": verzeichnung.tolist(),
               "bilder": len(welt),
               "reprojektionsfehler_px": round(float(fehler), 4)},
              open(KALIBRIERUNG, "w"), indent=2)

    print(f"\n{len(welt)} Aufnahmen verwendet")
    print(f"Reprojektionsfehler: {fehler:.3f} px (unter 1.0 ist gut)")
    print(f"gespeichert in {KALIBRIERUNG}")

def objektiv_entzerren(bild, daten):
    """Kalibriermatrix an eine andere Aufloesung desselben Bildfelds anpassen."""
    original = daten.get("bildgroesse")
    if not isinstance(original,(list,tuple)) or len(original)!=2 or min(original)<=0:
        raise ValueError("Objektivdatei ohne Kalibrier-Bildgroesse. Einmal mit --kalibrieren erneuern.")
    w,h = bild.shape[1],bild.shape[0]
    if abs((w/h)/(original[0]/original[1])-1) > .002:
        raise ValueError("Kalibrierung und Foto haben verschiedene Bildfelder/Seitenverhaeltnisse.")
    matrix = np.asarray(daten["kamera_matrix"],dtype=float).copy()
    verzeichnung = np.asarray(daten["verzeichnung"],dtype=float)
    if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or not np.isfinite(verzeichnung).all():
        raise ValueError("Ungueltige Objektivkalibrierung.")
    matrix[0,:]*=w/original[0];matrix[1,:]*=h/original[1]
    return cv2.undistort(bild,matrix,verzeichnung)


def rauschen_schaetzen(bild):
    """Bildrauschen nach Immerkaer (1996). Reagiert kaum auf Kanten und
    Blattstrukturen, misst also tatsaechlich Sensorrauschen."""
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY).astype(np.float64)
    kern = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float64)
    h, w = grau.shape
    summe = np.abs(cv2.filter2D(grau, -1, kern)[1:-1, 1:-1]).sum()
    return float(np.sqrt(np.pi / 2) * summe / (6 * (w - 2) * (h - 2)))


def zeit_aus_name(name):
    """Nur explizite Aufnahmezeiten. Dateidatum ist KEINE Aufnahmezeit."""
    muster = [(r"(\d{8}T\d{6}Z)", "%Y%m%dT%H%M%SZ"),
              (r"(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})", "%Y_%m_%d_%H_%M_%S"),
              (r"(\d{4}-\d{2}-\d{2}[T_ ]\d{2}[-:]\d{2}[-:]\d{2})", None)]
    for regex, fmt in muster:
        treffer = re.search(regex, name)
        if treffer:
            try:
                if fmt:
                    return datetime.strptime(treffer[1], fmt).replace(tzinfo=timezone.utc)
                text = treffer[1].replace("_", "T").replace(" ", "T")
                return datetime.fromisoformat(text[:11] + text[11:].replace("-", ":")).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None


def iso(zeit):
    return zeit.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if zeit else None


def flags_hinzufuegen(z, *flags):
    vorhanden = list(filter(None, (z.get("auffaelligkeit") or "").split(";")))
    z["auffaelligkeit"] = ";".join(dict.fromkeys(vorhanden + list(flags)))


def kleiner(bild):
    faktor = min(1.0, ARBEITSBREITE / bild.shape[1])
    return cv2.resize(bild, (round(bild.shape[1]*faktor), round(bild.shape[0]*faktor)),
                      interpolation=cv2.INTER_AREA) if faktor < 1 else bild.copy()


def _kern(n):
    """Elliptisches Strukturelement mit garantiert ungerader Kantenlaenge."""
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(n) | 1, int(n) | 1))


def saubere_komponenten(maske, minimum):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
    behalten = np.zeros(n, np.uint8)
    behalten[1:] = (stats[1:, cv2.CC_STAT_AREA] >= minimum).astype(np.uint8)*255
    return behalten[labels]


def szene_abgleichen(bild, ref, details=None):
    """Hintergrundmerkmale, nicht Blaetter: Verschieben der Kamera erkennen.

    Liefert die Referenzmaske in aktuellen Koordinaten. Kleine Verschiebungen
    werden fuer den Farbvergleich ausgeglichen. Starke Aenderungen werden
    gemeldet; Groessenvergleiche werden dann unterdrueckt.
    """
    if ref is None or bild.shape != ref["bild"].shape:
        return None, None, [] if ref is None else ["aufloesung_geaendert"]
    ref_bild, ref_maske = ref["bild"], ref["maske"]
    orb = cv2.ORB_create(nfeatures=1800)
    hintergrund = 255-cv2.dilate(ref_maske, np.ones((19, 19), np.uint8))
    k1, d1 = orb.detectAndCompute(cv2.cvtColor(ref_bild, cv2.COLOR_BGR2GRAY), hintergrund)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY), None)
    if d1 is None or d2 is None:
        return ref_maske.copy(), ref_bild.copy(), ["kameralage_nicht_verifiziert"]
    paare = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    gut = [a for paar in paare if len(paar) == 2 for a, b in [paar] if a.distance < .72*b.distance]
    if len(gut) < 12:
        return ref_maske.copy(), ref_bild.copy(), ["kameralage_nicht_verifiziert"]
    src = np.float32([k1[m.queryIdx].pt for m in gut])
    dst = np.float32([k2[m.trainIdx].pt for m in gut])
    matrix, inlier = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if matrix is None or float(inlier.mean()) < .45:
        return None, None, ["kameralage_nicht_verifiziert"]
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    winkel = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    versatz = float(np.linalg.norm(matrix[:, 2])) / max(bild.shape[:2])
    # Unterhalb eines halben Arbeitspixels keine Interpolationsaenderung
    # durch das Rauschen der Merkmalsanpassung erzeugen.
    if abs(scale-1)<.0005 and winkel<.03 and np.linalg.norm(matrix[:,2])<.5:
        matrix=np.array([[1.,0.,0.],[0.,1.,0.]])
        scale,winkel,versatz=1.,0.,0.
    if details is not None:
        details.update(scale=scale, rotation=winkel, translation=versatz)
    flags = ["ansicht_geaendert"] if abs(scale-1) > .025 or winkel > 3 or versatz > .035 else []
    h, w = bild.shape[:2]
    return (cv2.warpAffine(ref_maske, matrix, (w, h), flags=cv2.INTER_NEAREST),
            cv2.warpAffine(ref_bild, matrix, (w, h)), flags)


def gruenheit(bgr):
    """Gegenfarbkanal a* aus CIELAB als Vegetationsmass (0..127).

    a* ist die Gruen-Rot-Achse. Blattgewebe liegt im negativen Bereich,
    Holz, Erde und Topf im positiven. Gegenueber Excess Green (2G-R-B)
    hat das zwei gemessene Vorteile: helle panaschierte Blattpartien
    bleiben erhalten (V-01 im Bench-Report), und die Trennung haengt
    weniger an der absoluten Gruenmenge der Beleuchtung.
    """
    glatt = cv2.bilateralFilter(bgr, 7, 45, 9)       # Kanten bleiben scharf
    lab = cv2.cvtColor(glatt, cv2.COLOR_BGR2LAB)
    a = lab[:, :, 1].astype(np.int16) - 128
    b = lab[:, :, 2].astype(np.int16) - 128
    return np.clip(-a, 0, 127).astype(np.uint8), b


def segmentieren(arbeit, prior=None, prior_bild=None):
    """Blattmaske ueber a*-Otsu, Morphologie und Komponentenfilter.

    Ein einziges Trennkriterium statt mehrerer sich widersprechender
    Heuristiken. CHROMA_MIN verhindert, dass neutrales Grau (Kabel,
    weisse Wand, Rauschen) als Pflanze durchgeht.
    """
    gruen, gelbachse = gruenheit(arbeit)
    schwelle, maske = cv2.threshold(gruen, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    maske[gruen < CHROMA_MIN] = 0

    if prior is not None and prior.shape == maske.shape:
        # Ein zuvor erfasstes Blatt kann vergilben; a* wandert dabei
        # Richtung Null. Nur innerhalb der alten Blattflaeche und nur
        # bei deutlich gelbem b* wird es weiter mitgezaehlt.
        vergilbt = (prior > 0) & (gruen >= CHROMA_MIN // 2) & (gelbachse > 12)
        maske[vergilbt] = 255

    n = max(3, round(.006 * min(maske.shape)))
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, _kern(n))
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, _kern(2 * n + 1))
    maske = loecher_schliessen(maske)
    return saubere_komponenten(maske, max(60, round(.0002 * maske.size)))


def loecher_schliessen(maske):
    """Eingeschlossene Luecken im Blatt fuellen, Erde dazwischen nicht."""
    frei = 255 - maske
    anzahl, labels, stats, _ = cv2.connectedComponentsWithStats(frei, 8)
    rand = set(np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    grenze = max(30, round(.0015 * maske.size))
    for i in range(1, anzahl):
        if i not in rand and stats[i, cv2.CC_STAT_AREA] <= grenze:
            maske[labels == i] = 255
    return maske


def maske_verfeinern(bild, maske_klein, prior_bild=None):
    """Blattrand an den Originalpixeln nachziehen.

    Die kleine Maske wird hochskaliert; neu entschieden wird nur in
    einem schmalen Band um die Kontur. Der sichere Innenbereich bleibt
    unangetastet, deshalb kann der Rand keine ganzen Blaetter verlieren.
    """
    h, w = bild.shape[:2]
    basis = cv2.resize(maske_klein, (w, h), interpolation=cv2.INTER_NEAREST)
    if not np.any(basis):
        return basis

    band_px = max(3, round(.004 * min(h, w)))
    aussen = cv2.dilate(basis, _kern(2 * band_px + 1))
    innen = cv2.erode(basis, _kern(2 * band_px + 1))
    band = cv2.subtract(aussen, innen)

    gruen, _ = gruenheit(bild)
    werte = gruen[basis > 0]
    if werte.size < 50:
        return basis
    schwelle = max(CHROMA_MIN, float(np.percentile(werte, 12)))

    fein = innen.copy()
    fein[(band > 0) & (gruen >= schwelle)] = 255
    fein = cv2.morphologyEx(fein, cv2.MORPH_CLOSE, _kern(band_px | 1))
    fein = loecher_schliessen(fein)
    fein = saubere_komponenten(fein, max(80, round(.0002 * fein.size)))

    if ROI_NORMIERT is not None:
        x0, y0, x1, y1 = ROI_NORMIERT
        roi = np.zeros_like(fein)
        roi[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)] = 255
        fein[roi == 0] = 0
    return fein


def farbmerkmale(bild, maske):
    m = maske > 0
    if not np.any(m):
        return None
    rgb = bild[:, :, ::-1].astype(np.float32)
    hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV).astype(np.float32)
    lab = cv2.cvtColor(bild.astype(np.float32)/255, cv2.COLOR_BGR2LAB)
    r, g, b = [rgb[:, :, i][m] for i in range(3)]
    h, s, v = [hsv[:, :, i][m] for i in range(3)]
    chromatisch = s > 18
    winkel = 2*np.pi*h[chromatisch]/180
    mittel_h = (math.atan2(float(np.mean(np.sin(winkel))), float(np.mean(np.cos(winkel)))) % (2*np.pi))*180/(2*np.pi) if len(winkel) else None
    braun = (h < 28) & (s > 60) & (v < 165) & (r > g*1.02)
    gelb = (h >= 15) & (h < 38) & (s > 50) & ~braun
    # Weicher Warm-/Braunindikator nur fuer den Verlauf: vermeidet, dass
    # ein Pixel beim Ueberschreiten einer Helligkeitsgrenze ploetzlich
    # "nicht mehr braun" und damit als erholt bewertet wird.
    warm_last = 100*float((np.clip((32-h)/15, 0, 1)*np.clip((s-35)/100, 0, 1)*
                          np.clip((235-v)/100, 0, 1)*(r > g*1.01)).mean())
    # Weiche Histogramm-Bins verhindern sprunghafte Scores, wenn nur eine
    # kleine Farbaenderung eine harte Bin-Grenze ueberschreitet.
    hf, sf = h*24/180, s*12/256
    hb, sb = np.floor(hf).astype(int), np.floor(sf).astype(int)
    wh, ws = hf-hb, sf-sb
    hist = np.zeros((24, 12), np.float32)
    for dh, hw in [(0, 1-wh), (1, wh)]:
        for ds, sw in [(0, 1-ws), (1, ws)]:
            ind = ((hb+dh) % 24)*12+np.clip(sb+ds, 0, 11)
            hist += np.bincount(ind, weights=hw*sw, minlength=288).reshape(24, 12).astype(np.float32)
    # H ist kreisfoermig: Rot bei 179 und Rot bei 0 sind Nachbarn.
    hist = .5*hist+.25*np.roll(hist, 1, axis=0)+.25*np.roll(hist, -1, axis=0)
    hist = cv2.GaussianBlur(hist, (3, 1), .65)
    hist = hist / max(float(hist.sum()), 1e-8)
    return {"mittel_r": float(r.mean()), "mittel_g": float(g.mean()), "mittel_b": float(b.mean()),
            "mittel_h": mittel_h, "mittel_s": float(s.mean()),
            "gruenindex": float((g/(r+g+b+1e-6)).mean()),
            "gelbanteil_pct": 100*float(gelb.mean()), "braunanteil_pct": 100*float(braun.mean()),
            "_hist": hist, "_lab": np.median(lab[m], axis=0), "_warm_last": warm_last}


def skalierung_aus_punkten(punkte, laenge_mm, breite, hoehe):
    """Bekannte echte Laenge / gemessener Pixelabstand; keine Schaetzung."""
    p = np.asarray(punkte, dtype=float).reshape(2, 2)
    if not np.isfinite(p).all() or not math.isfinite(laenge_mm) or laenge_mm <= 0:
        raise ValueError("Punkte und Referenzlaenge muessen gueltige positive Messwerte sein.")
    if np.any(p < 0) or np.any(p[:, 0] >= breite) or np.any(p[:, 1] >= hoehe):
        raise ValueError("Messpunkte liegen ausserhalb des Bildes.")
    pixel = float(np.linalg.norm(p[1]-p[0]))
    if pixel < 5:
        raise ValueError("Messpunkte muessen mindestens 5 Pixel auseinanderliegen.")
    return float(laenge_mm/pixel)


def massstab_einrichten(bildpfad, laenge_mm, ausgabe, punkte=None):
    """Zwei Endpunkte einer gemessenen Strecke IN DER BLATTEBENE markieren.

    Die Punkte beziehen sich auf das ggf. entzerrte Originalbild. Messlineal
    beim Aufnehmen auf Blatthoehe halten. Ohne bekannte Laenge keine Eichung.
    --punkte erlaubt dieselbe Eingabe ohne GUI in Original-Pixelkoordinaten.
    """
    bildpfad = Path(bildpfad).resolve()
    bild = cv2.imdecode(np.fromfile(bildpfad, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bild is None:
        raise ValueError("Massstabbild nicht lesbar.")
    lens_hash = None
    if KALIBRIERUNG.exists():
        text = KALIBRIERUNG.read_bytes()
        d = json.loads(text)
        bild = objektiv_entzerren(bild,d)
        lens_hash = hashlib.sha256(text).hexdigest()
    h, w = bild.shape[:2]
    if punkte is None:
        faktor = min(1., 1300/w, 800/h)
        vorschau = cv2.resize(bild, (round(w*faktor), round(h*faktor)))
        klicks = []
        titel = "Zwei Linealmarken auf Blatthoehe anklicken | Enter: speichern | R: neu | Esc: abbrechen"
        def klick(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN and len(klicks) < 2:
                klicks.append((x/faktor, y/faktor))
        try:
            cv2.namedWindow(titel, cv2.WINDOW_AUTOSIZE)
            cv2.setMouseCallback(titel, klick)
            while True:
                panel = vorschau.copy()
                for x, y in klicks:
                    cv2.drawMarker(panel, (round(x*faktor), round(y*faktor)), (0, 0, 255), cv2.MARKER_CROSS, 18, 2)
                if len(klicks) == 2:
                    p1, p2 = [tuple(round(v*faktor) for v in p) for p in klicks]
                    cv2.line(panel, p1, p2, (0, 0, 255), 2)
                cv2.imshow(titel, panel)
                taste = cv2.waitKey(30) & 255
                if taste == 27 or cv2.getWindowProperty(titel, cv2.WND_PROP_VISIBLE) < 1:
                    raise ValueError("Massstab-Eingabe abgebrochen; keine Eichung gespeichert.")
                if taste in (ord('r'), ord('R')):
                    klicks.clear()
                if taste in (10, 13) and len(klicks) == 2:
                    punkte = klicks
                    break
        except cv2.error as fehler:
            raise ValueError("Grafikfenster nicht verfuegbar. OpenCV mit GUI oder --punkte x1 y1 x2 y2 verwenden.") from fehler
        finally:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
    wert = skalierung_aus_punkten(punkte, laenge_mm, w, h)
    arbeit = kleiner(bild)
    maske = segmentieren(arbeit)
    ref = {"bild": arbeit, "maske": maske, "meta": {
        "kind": "ruler_scale", "version": 1, "mm_pro_pixel": wert,
        "referenz_mm": float(laenge_mm), "punkte": np.asarray(punkte).reshape(2,2).tolist(),
        "bild": bildpfad.name, "bildbreite": w, "bildhoehe": h,
        "sha256": hashlib.sha256(bildpfad.read_bytes()).hexdigest(),
        "lens_hash": lens_hash, "ebene": "Blattebene"}}
    ausgabe.mkdir(parents=True, exist_ok=True)
    referenz_speichern(ausgabe/"massstab.npz", ref)
    print(f"Gemessener Massstab: {wert:.6f} mm/Pixel -> {ausgabe/'massstab.npz'}")
    print("Beim normalen Aufruf wird dieser Massstab fuer passende Kameraansichten verwendet.")
    print("Bei veraenderter Blatt-/Kamerahoehe den Linealmassstab erneut einrichten.")
    return ref


def massstab_laden(pfad):
    if not pfad.exists():
        return None
    with np.load(pfad, allow_pickle=False) as daten:
        meta = json.loads(str(daten["meta"]))
        if meta.get("kind") != "ruler_scale" or meta.get("mm_pro_pixel", 0) <= 0:
            raise ValueError("Gespeicherter Linealmassstab ist ungueltig.")
        return {"meta": meta, "bild": daten["bild"].copy(), "maske": daten["maske"].copy()}


def massstab(bild, manuell, lineal=None):
    if manuell is not None:
        return float(manuell), "manuell_blattebene"
    if lineal is not None:
        lens_hash = hashlib.sha256(KALIBRIERUNG.read_bytes()).hexdigest() if KALIBRIERUNG.exists() else None
        if lens_hash != lineal["meta"].get("lens_hash"):
            return None, "objektiv_einstellung_gegenueber_lineal_geaendert"
        arbeit = kleiner(bild)
        details = {}
        if arbeit.shape == lineal["bild"].shape and np.array_equal(arbeit, lineal["bild"]):
            details["scale"] = 1.
            flags = []
        else:
            _, _, flags = szene_abgleichen(arbeit, lineal, details)
        if flags or "scale" not in details:
            return None, "kameraansicht_passt_nicht_zum_linealbild"
        faktor = details["scale"]*bild.shape[1]/lineal["meta"]["bildbreite"]
        return lineal["meta"]["mm_pro_pixel"]/faktor, "lineal_blattebene"
    if not hasattr(cv2, "aruco"):
        return None, "nicht_kalibriert"
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detektor = cv2.aruco.ArucoDetector(dictionary)
    ecken, ids, _ = detektor.detectMarkers(bild)
    if ids is None:
        return None, "nicht_kalibriert"
    marker = {int(i): c.reshape(4, 2) for i, c in zip(ids.flatten(), ecken) if int(i) in (0, 1, 2, 3)}
    if len(marker) != 4:
        return None, "marker_unvollstaendig"
    kanten = [np.linalg.norm(c-np.roll(c, -1, axis=0), axis=1).mean() for c in marker.values()]
    if min(kanten) <= 0 or np.std(kanten)/np.mean(kanten) > .08:
        return None, "marker_uneinheitlich"
    if KAMERA_HOEHE_MM is None or BLATT_HOEHE_MM is None:
        return None, "blattebene_unbekannt"
    if not 0 <= BLATT_HOEHE_MM < KAMERA_HOEHE_MM or MARKER_HOEHE_MM >= KAMERA_HOEHE_MM:
        return None, "geometrie_ungueltig"
    return (MARKER_MM/float(np.median(kanten)) *
            (KAMERA_HOEHE_MM-BLATT_HOEHE_MM)/(KAMERA_HOEHE_MM-MARKER_HOEHE_MM), "aruco_hoehenkorrigiert")


def merkmale(bild, maske, mm_px):
    pixel = cv2.countNonZero(maske)
    if pixel == 0:
        return {"pflanzen_pixel": 0, "mm_pro_pixel": mm_px}
    konturen, _ = cv2.findContours(maske, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    umfang = sum(cv2.arcLength(k, True) for k in konturen)
    _, _, breite, hoehe = cv2.boundingRect(np.vstack(konturen))
    huelle = cv2.convexHull(np.vstack(konturen)).reshape(-1,2).astype(np.float32)
    ecken = huelle[:,None,:]+np.array([[-.5,-.5],[-.5,.5],[.5,-.5],[.5,.5]],np.float32)
    huelle = cv2.convexHull(ecken.reshape(-1,2)).reshape(-1,2)
    abstaende = huelle[:,None,:]-huelle[None,:,:]
    durchmesser_px = float(np.sqrt(np.max(np.sum(abstaende**2,axis=2))))
    n, _, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    farbe = farbmerkmale(bild, maske)
    w = {k: v for k, v in farbe.items() if not k.startswith("_")}
    w.update({"pflanzen_pixel": pixel,
              "blattflaeche_cm2": pixel*mm_px**2/100 if mm_px else None,
              "durchmesser_mm": durchmesser_px*mm_px if mm_px else None,
              "kompaktheit": float(4*np.pi*pixel/umfang**2) if umfang else None,
              "groesste_komponente_pct": 100*float(stats[1:, cv2.CC_STAT_AREA].max())/pixel if n > 1 else None,
              "mm_pro_pixel": mm_px,
              "schaerfe": float(cv2.Laplacian(grau, cv2.CV_64F)[maske > 0].var()),
              "bildhelligkeit": float(grau.mean()),
              "ueberbelichtet_pct": 100*float(np.any(bild[maske > 0] >= 254, axis=1).mean()),
              "farbe_hex": "#{:02x}{:02x}{:02x}".format(*[int(np.clip(round(w[k]), 0, 255)) for k in ("mittel_r", "mittel_g", "mittel_b")])})
    return w


# Statusfarben (BGR) fuer den Randbalken des Kontrollbildes.
STATUSFARBEN = {"ok": (104, 160, 50), "pruefen": (60, 170, 225), "fehler": (70, 70, 200)}


def _status_kontrolle(z):
    """Eine Ampel, die schon in der Explorer-Miniatur erkennbar ist."""
    if not z.get("brauchbar") or not z.get("pflanzen_pixel"):
        return "fehler", "NICHT VERWENDBAR"
    if z.get("auffaelligkeit"):
        return "pruefen", "PRUEFEN"
    return "ok", "OK"


def _text(panel, text, pos, groesse, farbe, dick=1):
    cv2.putText(panel, text, pos, cv2.FONT_HERSHEY_SIMPLEX, groesse, farbe, dick, cv2.LINE_AA)


def kontrollbild(bild, maske, z, pfad):
    """Sichtpruefung: Foto, Blattkontur, Kennzahlen und Maskenvorschau.

    Alles, was zur Beurteilung einer Maske noetig ist, in einem Bild:
    die Fuellung zeigt, WAS gezaehlt wurde, die Kontur WO die Grenze
    liegt, die Miniatur rechts die Form ohne ablenkendes Foto.
    """
    faktor = min(1., 1500 / bild.shape[1])
    ansicht = cv2.resize(bild, None, fx=faktor, fy=faktor, interpolation=cv2.INTER_AREA)
    m = cv2.resize(maske, (ansicht.shape[1], ansicht.shape[0]), interpolation=cv2.INTER_NEAREST)
    hoehe, breite = ansicht.shape[:2]
    skala = breite / 1500

    schluessel, beschriftung = _status_kontrolle(z)
    farbe = STATUSFARBEN[schluessel]

    # Blattflaeche leicht einfaerben, Kontur kraeftig darueber.
    ansicht[m > 0] = (.93 * ansicht[m > 0] + .07 * np.array([215, 90, 205])).astype(np.uint8)
    konturen, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(ansicht, konturen, -1, (220, 40, 220), max(1, round(1.4 * skala)), cv2.LINE_AA)

    # Maskenminiatur: Form beurteilen, ohne dass das Foto ablenkt.
    mini_h = round(.17 * hoehe)
    mini = cv2.resize(m, (round(mini_h * breite / hoehe), mini_h), interpolation=cv2.INTER_AREA)
    mini = cv2.cvtColor(mini, cv2.COLOR_GRAY2BGR)
    rand = max(1, round(2 * skala))
    cv2.rectangle(mini, (0, 0), (mini.shape[1] - 1, mini.shape[0] - 1), (150, 150, 150), rand)
    y0, x0 = hoehe - mini.shape[0] - round(14 * skala), breite - mini.shape[1] - round(14 * skala)
    ansicht[y0:y0 + mini.shape[0], x0:x0 + mini.shape[1]] = mini

    kopf = round(78 * skala)
    panel = np.full((hoehe + kopf, breite, 3), 252, np.uint8)
    panel[kopf:] = ansicht
    panel[:kopf, :round(13 * skala)] = farbe          # Ampel, auch als Miniatur sichtbar

    links = round(26 * skala)
    _text(panel, z.get("bild", "?"), (links, round(27 * skala)), .62 * skala, (35, 35, 35), max(1, round(1.6 * skala)))
    zeit = (z.get("captured_at") or "keine Aufnahmezeit im Dateinamen").replace("T", " ").replace("Z", " UTC")
    _text(panel, zeit, (links, round(50 * skala)), .46 * skala, (115, 115, 115), max(1, round(skala)))

    flaeche = (f"{z['blattflaeche_cm2']:.2f} cm2" if z.get("blattflaeche_cm2") is not None
               else f"{z.get('pflanzen_pixel', 0):,} Blattpixel".replace(",", " "))
    anteil = 100 * cv2.countNonZero(maske) / maske.size
    index = f"Index {z['gesundheit']:.1f}/100" if z.get("gesundheit") is not None else "kein Index"
    _text(panel, f"{flaeche}   |   {anteil:.1f} % des Bildes   |   {index}",
          (links, round(71 * skala)), .50 * skala, (55, 55, 55), max(1, round(1.3 * skala)))

    marke = f"{beschriftung}"
    (tw, _), _ = cv2.getTextSize(marke, cv2.FONT_HERSHEY_SIMPLEX, .55 * skala, max(1, round(1.6 * skala)))
    _text(panel, marke, (breite - tw - round(26 * skala), round(30 * skala)), .55 * skala, farbe, max(1, round(1.6 * skala)))

    hinweise = [t for t in [z.get("auffaelligkeit"), z.get("gesundheitswarnung")] if t]
    if z.get("_maskenquelle") == "manuell":
        hinweise.insert(0, "manuell gepruefte Maske")
    if (z.get("gesundheit_status") or "").startswith("vorlaeufige_referenz"):
        hinweise.append("Referenz noch nicht freigegeben")
    if hinweise:
        text = " | ".join(hinweise).replace(";", ", ")
        _text(panel, text[:150], (breite - round(26 * skala) - cv2.getTextSize(text[:150], cv2.FONT_HERSHEY_SIMPLEX, .42 * skala, 1)[0][0],
                                  round(55 * skala)), .42 * skala, (110, 110, 110), max(1, round(skala)))

    ok, png = cv2.imencode(".png", panel)
    if not ok:
        raise OSError(f"Kontrollbild nicht gespeichert: {pfad}")
    Path(pfad).write_bytes(png.tobytes())


def korrektur_pfad(ausgabe, sha256, entzerrt=None):
    nutzen = KALIBRIERUNG.exists() if entzerrt is None else entzerrt
    lens = hashlib.sha256(KALIBRIERUNG.read_bytes()).hexdigest()[:16] if nutzen else "roh"
    return ausgabe/"masken_korrektur"/(sha256+"_"+lens+".png")


def korrektur_laden(ausgabe, sha256, form, entzerrt=None):
    pfad = korrektur_pfad(ausgabe,sha256,entzerrt)
    if not pfad.exists():
        return None
    maske = cv2.imdecode(np.fromfile(pfad,dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
    if maske is None or maske.shape != tuple(form) or not np.isin(maske,[0,255]).all():
        raise ValueError("Gespeicherte Korrekturmaske hat falsche Groesse oder ist nicht binaer.")
    return maske


def korrektur_speichern(ausgabe, sha256, maske, form):
    if maske.shape != tuple(form) or not np.isin(maske,[0,255]).all():
        raise ValueError("Korrektur: gleiche Pixelgroesse wie das Original; nur Schwarz/Weiss 0/255.")
    ziel = korrektur_pfad(ausgabe,sha256)
    ziel.parent.mkdir(parents=True,exist_ok=True)
    ok,png = cv2.imencode(".png",maske)
    if not ok:
        raise ValueError("Korrekturmaske konnte nicht codiert werden.")
    tmp = ziel.with_suffix(".tmp")
    tmp.write_bytes(png.tobytes());tmp.replace(ziel)
    return ziel


def maske_korrigieren(bildpfad, ausgabe, uebernehmen=None):
    """Fuer Grenzfaelle wenige FG/BG-Striche, optionales Nachrechnen und Speichern.

    Keine neue Abhaengigkeit, kein externes Modell. Korrekturen werden nur
    fuer EXAKT diese Originaldatei und Objektivkalibrierung wiederverwendet.
    Auch eine fremd erstellte binaere Originalmaske kann importiert werden.
    """
    bildpfad = Path(bildpfad).expanduser().resolve()
    sha = hashlib.sha256(bildpfad.read_bytes()).hexdigest()
    bild = cv2.imdecode(np.fromfile(bildpfad,dtype=np.uint8),cv2.IMREAD_COLOR)
    if bild is None:
        raise ValueError("Originalbild nicht lesbar.")
    if KALIBRIERUNG.exists():
        d = json.loads(KALIBRIERUNG.read_text(encoding="utf-8"))
        bild = objektiv_entzerren(bild,d)
    if uebernehmen is not None:
        maske = cv2.imdecode(np.fromfile(uebernehmen,dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
        if maske is None:
            raise ValueError("Importmaske nicht lesbar.")
        return korrektur_speichern(ausgabe,sha,maske,bild.shape[:2])
    maske = korrektur_laden(ausgabe,sha,bild.shape[:2])
    if maske is None:
        maske = maske_verfeinern(bild,segmentieren(kleiner(bild)))
    original = maske.copy()
    h,w = maske.shape
    faktor = min(1.,1400/w,800/h)
    groesse = (round(w*faktor),round(h*faktor))
    strokes = np.full(maske.shape,2,np.uint8)
    history = []
    zustand = {"radius":max(2,round(6/faktor)),"druck":None,"vorher":None}
    titel = "Blattmaske korrigieren"
    def zeichnen(event,x,y,flags,param):
        punkt = (min(w-1,max(0,round(x/faktor))),min(h-1,max(0,round(y/faktor))))
        if event in (cv2.EVENT_LBUTTONDOWN,cv2.EVENT_RBUTTONDOWN):
            history.append((maske.copy(),strokes.copy()))
            if len(history)>8:history.pop(0)
            zustand["druck"] = 255 if event==cv2.EVENT_LBUTTONDOWN else 0
            zustand["vorher"] = punkt
        if zustand["druck"] is not None and event in (cv2.EVENT_MOUSEMOVE,cv2.EVENT_LBUTTONDOWN,cv2.EVENT_RBUTTONDOWN):
            a=zustand["vorher"] or punkt
            cv2.line(maske,a,punkt,zustand["druck"],2*zustand["radius"])
            cv2.line(strokes,a,punkt,1 if zustand["druck"] else 0,2*zustand["radius"])
            zustand["vorher"] = punkt
        if event in (cv2.EVENT_LBUTTONUP,cv2.EVENT_RBUTTONUP):
            zustand["druck"]=None;zustand["vorher"]=None
    try:
        cv2.namedWindow(titel,cv2.WINDOW_AUTOSIZE);cv2.setMouseCallback(titel,zeichnen)
        print("Links: Blatt, rechts: Hintergrund, +/-: Pinsel, G: GrabCut, U: zurueck, R: neu, Enter: speichern, Esc: abbrechen.")
        while True:
            ansicht = bild.copy()
            ansicht[maske>0] = (.80*ansicht[maske>0]+.20*np.array([210,50,220])).astype(np.uint8)
            ansicht = cv2.resize(ansicht,groesse)
            cv2.putText(ansicht,"Links Blatt | Rechts Hintergrund | +/- Pinsel | G rechnen | U Undo | Enter speichern",(8,20),cv2.FONT_HERSHEY_SIMPLEX,.43,(10,10,10),2,cv2.LINE_AA)
            cv2.putText(ansicht,"Links Blatt | Rechts Hintergrund | +/- Pinsel | G rechnen | U Undo | Enter speichern",(8,20),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1,cv2.LINE_AA)
            cv2.imshow(titel,ansicht)
            taste=cv2.waitKey(25)&255
            if taste==27 or cv2.getWindowProperty(titel,cv2.WND_PROP_VISIBLE)<1:
                print("Abgebrochen; keine Korrektur gespeichert.");return None
            if taste in (10,13):
                return korrektur_speichern(ausgabe,sha,maske,bild.shape[:2])
            if taste in (ord('+'),ord('=')):zustand["radius"]=min(100,zustand["radius"]+2)
            if taste==ord('-'):zustand["radius"]=max(1,zustand["radius"]-2)
            if taste in (ord('u'),ord('U')) and history:
                m,s=history.pop();maske[:]=m;strokes[:]=s
            if taste in (ord('r'),ord('R')):
                maske[:]=original;strokes[:]=2
            if taste in (ord('g'),ord('G')):
                history.append((maske.copy(),strokes.copy()))
                if len(history)>8:history.pop(0)
                gc=np.where(maske>0,cv2.GC_PR_FGD,cv2.GC_PR_BGD).astype(np.uint8)
                gc[0]=gc[-1]=cv2.GC_BGD;gc[:,0]=gc[:,-1]=cv2.GC_BGD
                if not np.any(strokes==1):
                    kern=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9))
                    gc[cv2.erode(maske,kern)>0]=cv2.GC_FGD
                gc[strokes==0]=cv2.GC_BGD;gc[strokes==1]=cv2.GC_FGD
                if np.any(gc==cv2.GC_FGD) and np.any(gc==cv2.GC_BGD):
                    cv2.setRNGSeed(7)
                    cv2.grabCut(bild,gc,None,np.zeros((1,65)),np.zeros((1,65)),3,cv2.GC_INIT_WITH_MASK)
                    maske[:]=np.isin(gc,[cv2.GC_FGD,cv2.GC_PR_FGD]).astype(np.uint8)*255
    except cv2.error as fehler:
        raise ValueError("Bildfenster nicht verfuegbar. opencv-contrib-python mit GUI installieren; alternativ --korrekturmaske PNG importieren.") from fehler
    finally:
        try:cv2.destroyAllWindows()
        except cv2.error:pass


def referenz_laden(pfad, neu=False, bilder=None):
    if neu or not pfad.exists():
        return None
    with np.load(pfad, allow_pickle=False) as daten:
        meta = json.loads(str(daten["meta"]))
        lens_hash = hashlib.sha256(KALIBRIERUNG.read_bytes()).hexdigest() if KALIBRIERUNG.exists() else None
        if "lens_hash" in meta and meta["lens_hash"] != lens_hash:
            raise ValueError("Objektivprofil geaendert. Passende Messreihe waehlen oder --neue-referenz verwenden.")
        if "lens_hash" not in meta and lens_hash is not None:
            print("Alte Referenz ohne verifiziertes Objektivprofil; erste brauchbare Aufnahme wird neue Referenz.")
            return None
        if meta.get("version") not in (SCORING_VERSION, "2.0.0", "2.1.0") or meta.get("messreihe") != MESSREIHE:
            raise ValueError("Referenz gehoert zu anderer Messreihe/Scoreversion. --neue-referenz verwenden.")
        if meta.get("arbeitsbreite", ARBEITSBREITE) != ARBEITSBREITE or meta.get("roi") != (list(ROI_NORMIERT) if ROI_NORMIERT else None):
            raise ValueError("ROI/Aufloesung der Referenz passt nicht. --neue-referenz verwenden.")
        ref = {"meta": meta, "bild": daten["bild"].copy(), "maske": daten["maske"].copy()}
        if "maske_original" in daten.files:
            ref["maske_original"] = daten["maske_original"].copy()
        if "bild_original" in daten.files:
            ref["bild_original"] = daten["bild_original"].copy()
    if "bild_original" not in ref and bilder:
        for foto in bilder:
            foto=Path(foto)
            if foto.name!=meta.get("bild") or not foto.is_file():continue
            if hashlib.sha256(foto.read_bytes()).hexdigest()!=meta.get("sha256"):continue
            original=cv2.imdecode(np.fromfile(foto,dtype=np.uint8),cv2.IMREAD_COLOR)
            if original is not None:
                if KALIBRIERUNG.exists():
                    original=objektiv_entzerren(original,json.loads(KALIBRIERUNG.read_text(encoding="utf-8")))
                ref["bild_original"]=original
                break
    breite,hoehe = meta.get("bildbreite"),meta.get("bildhoehe")
    if breite and hoehe and meta.get("sha256"):
        korr = korrektur_laden(pfad.parent,meta["sha256"],(hoehe,breite))
        if korr is not None and (ref.get("maske_original") is None or not np.array_equal(korr,ref["maske_original"])):
            if not np.any(korr):
                return None
            ref["maske_original"] = korr
            ref["maske"] = cv2.resize(korr,(ref["bild"].shape[1],ref["bild"].shape[0]),interpolation=cv2.INTER_NEAREST)
            geo = merkmale(cv2.resize(ref["bild"],(breite,hoehe)),korr,None)
            meta.update(mask_source="manuell",pflanzen_pixel=geo["pflanzen_pixel"],kompaktheit=geo.get("kompaktheit"),historie=[])
    neues_verfahren=(meta.get("analyse_version") != ANALYSE_VERSION or meta.get("version") != SCORING_VERSION
                    or meta.get("pipeline_sha256") != PIPELINE_SHA256)
    if neues_verfahren or meta.get("mask_source")!="manuell":
        # Den urspruenglichen Referenzzeitpunkt trotz neuem Maskenverfahren
        # behalten. Veraltete, eventuell wandhaltige Masken nie weitergeben.
        maske = ref["maske"].copy() if meta.get("mask_source")=="manuell" else segmentieren(ref["bild"])
        if cv2.countNonZero(maske) < 80:
            print("Alte Referenz nicht auswertbar; erste brauchbare Aufnahme wird Referenz.")
            return None
        h, w = ref["bild"].shape[:2]
        breite, hoehe = meta.get("bildbreite", w), meta.get("bildhoehe", h)
        if meta.get("mask_source")=="manuell" and ref.get("maske_original") is not None:
            gross=ref["maske_original"]
        elif ref.get("bild_original") is not None:
            gross=maske_verfeinern(ref["bild_original"],maske)
            maske=cv2.resize(gross,(w,h),interpolation=cv2.INTER_NEAREST)
        else:
            gross = cv2.resize(maske, (breite, hoehe), interpolation=cv2.INTER_NEAREST)
        geometrie = merkmale(cv2.resize(ref["bild"], (breite, hoehe)), gross, None)
        ref["maske"] = maske
        if meta.get("mask_source") != "manuell":
            if ref.get("bild_original") is not None:ref["maske_original"]=gross
            else:ref.pop("maske_original",None)
        meta.update(version=SCORING_VERSION, analyse_version=ANALYSE_VERSION,
                    pipeline_sha256=PIPELINE_SHA256,
                    pflanzen_pixel=geometrie["pflanzen_pixel"],
                    kompaktheit=geometrie["kompaktheit"],
                    historie=[] if neues_verfahren else meta.get("historie",[]))
        print("Referenzmaske neu berechnet; urspruengliche Referenzaufnahme bleibt erhalten.")
    return ref


def referenz_speichern(pfad, ref):
    tmp = pfad.with_name("."+pfad.name+".tmp")
    with tmp.open("wb") as datei:
        arrays = {"bild":ref["bild"],"maske":ref["maske"]}
        if "maske_original" in ref:
            arrays["maske_original"] = ref["maske_original"]
        if "bild_original" in ref:
            arrays["bild_original"] = ref["bild_original"]
        np.savez_compressed(datei,meta=json.dumps(ref["meta"],allow_nan=False),**arrays)
    tmp.replace(pfad)


def stetiger_score(abweichung, halbwert):
    """100 bei null Abweichung, 50 bei halbwert, stetig gegen 0.

    Bewusst OHNE Totzone: eine Toleranzschwelle haette zur Folge, dass
    jede normale Aufnahme exakt 100,0 ergibt und der Score erst beim
    Ueberschreiten der Schwelle springt. Gemessen lagen die realen
    Abweichungen zwischen zwei Aufnahmen 3- bis 25-mal unter der
    frueheren Toleranz; der Index hatte dadurch im gesunden Bereich
    keinerlei Aufloesung. Die Warnschwellen in bewerten() bleiben
    getrennt davon, damit Rauschen keine Meldung ausloest.
    """
    d = max(0.0, float(abweichung))/halbwert
    return float(100*math.exp(-math.log(2)*min(d, 30)**2))


def licht_anwenden(bild, info):
    """Am unbewegten Hintergrund gelernte Abbildung auf andere Aufloesung anwenden."""
    koeff = info.get("_koeff")
    if koeff is None:
        return bild.copy()
    h, w = bild.shape[:2]
    x = np.linspace(-1,1,w,dtype=np.float32)[None,:]
    y = np.linspace(-1,1,h,dtype=np.float32)[:,None]
    out = np.empty(bild.shape,np.float32)
    for k,a in enumerate(koeff):
        t = bild[:,:,k].astype(np.float32)/255
        out[:,:,k] = a[0]+a[1]*t+a[2]*t*t+a[3]*t*x+a[4]*t*y
    return np.rint(np.clip(out,0,1)*255).astype(np.uint8)


def licht_abgleichen(arbeit, maske, ref_bild=None, ref_maske=None):
    """Robuste Belichtungs-/Weissabgleichkorrektur NUR aus Hintergrundpaaren.

    Die Pflanze wird nie an ihre alte Farbe angepasst. Linear, Gamma-Naeherung
    und langsamer Beleuchtungsgradient werden auf getrennten Pixeln validiert.
    Misslingt die Messung, entsteht kein erfundener besserer/schlechterer Score.
    """
    info = {"modell":"referenz", "korrigiert":False, "hintergrund_fehler":0.,
            "hintergrund_anteil_pct":None}
    if ref_bild is None:
        return arbeit.copy(), [], info
    if ref_maske is None or arbeit.shape != ref_bild.shape:
        return None, ["lichtvergleich_nicht_verifiziert"], info
    h,w = maske.shape
    bg = cv2.dilate(cv2.bitwise_or(maske,ref_maske),np.ones((31,31),np.uint8)) == 0
    # Nur lineare, nicht geclippte Kamerawerte zum Lernen verwenden.
    bg &= np.all((arbeit > 5)&(arbeit < 249)&(ref_bild > 5)&(ref_bild < 249),axis=2)
    idx = np.flatnonzero(bg)
    info["hintergrund_anteil_pct"] = round(100*len(idx)/bg.size,2)
    if len(idx) < max(300,round(.035*bg.size)):
        return None, ["licht_hintergrund_unzureichend"], info
    idx = idx[np.linspace(0,len(idx)-1,min(len(idx),14000)).astype(int)]
    yy,xx = np.divmod(idx,w)
    x,y = 2*xx/max(w-1,1)-1,2*yy/max(h-1,1)-1
    cur = arbeit.reshape(-1,3)[idx].astype(float)/255
    alt = ref_bild.reshape(-1,3)[idx].astype(float)/255
    if np.array_equal(cur,alt):
        info["modell"] = "identisch"
        return arbeit.copy(),[],info
    train = np.arange(len(idx)) % 4 != 0
    valid = ~train

    def anpassen(modell):
        koeff,fehler = [],[]
        for k in range(3):
            t = cur[:,k]
            X = np.stack([np.ones_like(t),t,t*t,t*x,t*y],axis=1)
            auswahl = {"linear":[0,1],"kurve":[0,1,2],"gradient":[0,1,2,3,4]}[modell]
            # Auf einem fast einfarbigen Hintergrund ist nur ein Gain messbar.
            if np.ptp(np.percentile(t,[5,95])) < .07:
                a = np.array([0.,float(np.median(alt[:,k]/np.maximum(t,1e-5))),0.,0.,0.])
            else:
                A,B = X[train][:,auswahl],alt[train,k]
                gew = np.ones(len(B))
                start = np.array([0.,1.,0.,0.,0.])[auswahl]
                for _ in range(5):
                    W = np.sqrt(gew)
                    reg = np.eye(len(auswahl))*.12
                    v = np.linalg.lstsq(np.vstack([A*W[:,None],reg]),
                                       np.r_[B*W,reg@start],rcond=None)[0]
                    e = A@v-B
                    sigma = max(.003,1.4826*float(np.median(np.abs(e-np.median(e)))))
                    gew = np.minimum(1.,2.5*sigma/(np.abs(e)+1e-8))
                a = np.zeros(5);a[auswahl] = v
            # Die Kurve muss im ganzen Bild sinnvoll und monoton bleiben.
            ableitungen = [a[1]+2*a[2]*t0+a[3]*x0+a[4]*y0
                           for t0 in (0,1) for x0 in (-1,1) for y0 in (-1,1)]
            if min(ableitungen) < .08 or max(ableitungen) > 6 or abs(a[0]) > .25:
                return None,None
            koeff.append(a.tolist())
            fehler.append(np.abs(X[valid]@a-alt[valid,k])*255)
        fehler = np.mean(fehler,axis=0)
        return koeff,fehler

    best,errors = anpassen("linear")
    name = "linear"
    for modell in ("kurve","gradient"):
        a,e = anpassen(modell)
        if a is not None and (best is None or np.median(e)+.15 < .75*np.median(errors)):
            best,errors,name = a,e,modell
    if best is None:
        return None,["lichtkorrektur_nicht_stabil"],info
    info.update(modell=name, hintergrund_fehler=round(float(np.median(errors)),3))
    if np.median(errors) > 6. or np.percentile(errors,90) > 18.:
        return None,["lichtkorrektur_nicht_stabil"],info
    info["_koeff"] = best
    normal = licht_anwenden(arbeit,info)
    info["korrigiert"] = bool(np.mean(np.abs(normal.astype(float)-arbeit)) > .6)
    return normal,[],info


def gesundheitsmerkmale(arbeit, maske, ref_bild=None, ref_maske=None, abgleich=None):
    """Ungekippte Blattfarben nach Hintergrundkorrektur vergleichen.

    Geclippte Pixel werden in BEIDEN Vergleichsbildern ausgeschlossen, damit
    ihre wechselnde Flaechengewichtung keinen falschen Zustandssprung erzeugt.
    Roh-RGB in CSV/JSON werden durch diese Arbeitskopie nicht veraendert.
    """
    korrigiert,flags,info = abgleich if abgleich is not None else licht_abgleichen(arbeit,maske,ref_bild,ref_maske)
    if korrigiert is None:
        return None,flags
    gueltig = maske.copy()
    basis_maske = ref_maske.copy() if ref_maske is not None else None
    schlecht = np.any(arbeit >= 254,axis=2) | (np.max(arbeit,axis=2) < 12)
    if ref_bild is not None:
        schlecht |= np.any(ref_bild >= 254,axis=2) | (np.max(ref_bild,axis=2) < 12)
    schlecht = cv2.dilate(schlecht.astype(np.uint8),np.ones((3,3),np.uint8)) > 0
    gueltig[schlecht] = 0
    anteil = cv2.countNonZero(gueltig)/max(1,cv2.countNonZero(maske))
    info["blattpixel_ausgeschlossen_pct"] = round(100*(1-anteil),2)
    if anteil < .65 or cv2.countNonZero(gueltig) < 50:
        return None,flags+["lichtvergleich_zu_wenig_blattgewebe"]
    f = farbmerkmale(korrigiert,gueltig)
    if basis_maske is not None:
        basis_maske[schlecht] = 0
        if cv2.countNonZero(basis_maske) < 50:
            return None,flags+["lichtvergleich_zu_wenig_referenzgewebe"]
        f["_vergleich_basis"] = farbmerkmale(ref_bild,basis_maske)
    f["_lichtinfo"] = info
    return f,flags


def bewerten(z, merkmale_gesund, ref, struktur_erlaubt=True):
    if merkmale_gesund is None or not z["brauchbar"]:
        z["gesundheit_status"] = "nicht_auswertbar"
        z["gesundheit_kategorie"] = "keine_daten"
        return
    basis = merkmale_gesund.get("_vergleich_basis") or farbmerkmale(ref["bild"], ref["maske"])
    cur, alt = merkmale_gesund, basis
    hist_abstand = float(cv2.compareHist(cur["_hist"].astype(np.float32), alt["_hist"].astype(np.float32), cv2.HISTCMP_BHATTACHARYYA))
    gruen_abstand = abs(cur["gruenindex"]-alt["gruenindex"])
    z["score_gruen"] = .6*stetiger_score(hist_abstand, HALBWERTE["hist"])+.4*stetiger_score(gruen_abstand, HALBWERTE["gruenindex"])
    # Braun gewordenes gelbes Gewebe darf den Gelbscore nicht verbessern.
    gelb_delta = max(0.,cur["gelbanteil_pct"]+cur["braunanteil_pct"]-
                         alt["gelbanteil_pct"]-alt["braunanteil_pct"])
    braun_delta = max(0., cur["braunanteil_pct"]-alt["braunanteil_pct"], cur["_warm_last"]-alt["_warm_last"])
    z["score_gelb"] = stetiger_score(gelb_delta, HALBWERTE["gelb"])
    z["score_braun"] = stetiger_score(braun_delta, HALBWERTE["braun"])
    saett_delta = abs(math.log((cur["mittel_s"]+8)/(alt["mittel_s"]+8)))
    z["score_saettigung"] = stetiger_score(saett_delta, HALBWERTE["saettigung"])
    if cur["mittel_h"] is not None and alt["mittel_h"] is not None:
        hue_delta = abs(cur["mittel_h"]-alt["mittel_h"])
        hue_delta = min(hue_delta, 180-hue_delta)
    else:
        hue_delta = 0.0
    lab_delta = float(np.linalg.norm(cur["_lab"][1:]-alt["_lab"][1:]))
    z["score_farbton"] = stetiger_score(max(hue_delta, lab_delta/2), HALBWERTE["farbton"])
    farbe = sum(GEWICHTE[k]*z["score_"+k] for k in GEWICHTE)
    flaechenverlust = max(0., 1-z["pflanzen_pixel"]/ref["meta"]["pflanzen_pixel"])
    form_delta = abs(math.log(max(z["kompaktheit"], 1e-6)/max(ref["meta"]["kompaktheit"], 1e-6)))
    struktur = .7*stetiger_score(flaechenverlust, HALBWERTE["flaeche"])+.3*stetiger_score(form_delta, HALBWERTE["form"])
    z["_struktur_score"] = struktur if struktur_erlaubt else None
    z["gesundheit_roh"] = .8*farbe+.2*struktur if struktur_erlaubt else farbe
    z["gesundheit"] = z["gesundheit_roh"]
    z["gesundheit_status"] = "freigegeben" if REFERENZ_FREIGEGEBEN else "vorlaeufige_referenz"
    if not struktur_erlaubt:
        z["gesundheit_status"] += ";nur_farbvergleich"
    warnungen = []
    if hist_abstand > .3 or hue_delta > 10:
        warnungen.append("farbveraenderung")
    if gelb_delta >= 8:
        warnungen.append("gelbanteil_gestiegen")
    if braun_delta >= 3:
        warnungen.append("braunanteil_gestiegen")
    if saett_delta > .25:
        warnungen.append("saettigung_veraendert")
    if struktur_erlaubt and flaechenverlust > .15:
        warnungen.append("sichtbare_blattflaeche_gesunken")
    z["gesundheitswarnung"] = ";".join(warnungen)


def zeitreihe_und_glaettung(zeilen, alte_historie, referenzzeit=None):
    letzter = None
    gueltige = []
    auswahl_start = min((z["_zeit"] for z in zeilen if z["_zeit"]), default=None)
    start = referenzzeit or auswahl_start
    fruehere_scores = [p for p in alte_historie if auswahl_start and p.get("captured_at") and
                       datetime.fromisoformat(p["captured_at"].replace("Z", "+00:00")) < auswahl_start]
    vorher_score = fruehere_scores[-1] if fruehere_scores else None
    basis = []          # (Zeit, Pixel, cm2) aller bisher gueltigen Aufnahmen
    for z in zeilen:
        t = z["_zeit"]
        if t and start:
            z["stunden_seit_start"] = (t-start).total_seconds()/3600
        if not z["brauchbar"] or not t:
            letzter = None
        else:
            # Sprungpruefung weiterhin gegen die unmittelbar vorige Aufnahme:
            # ein Kameraversatz zeigt sich genau dort.
            if letzter and z.get("_geometrie_ok") and letzter["pflanzen_pixel"]:
                if abs(z["pflanzen_pixel"]/letzter["pflanzen_pixel"]-1) > .5:
                    flags_hinzufuegen(z, "flaechensprung_pruefen")
                    basis.clear()

            # Wachstumsrate dagegen ueber einen laengeren Zeitraum. Gegen die
            # Vorgaengeraufnahme gerechnet wird das Maskenrauschen durch den
            # kurzen Zeitabstand massiv verstaerkt: 0,7 % Rauschen bei 30 min
            # Abstand ergibt bereits ueber 30 %/Tag Scheinwachstum. Erst ab
            # RATE_MIN_STUNDEN liegt die echte Aenderung ueber dem Rauschen.
            if z.get("_geometrie_ok"):
                grenze = t-timedelta(hours=RATE_MIN_STUNDEN)
                vergleich = next((p for p in reversed(basis) if p[0] <= grenze), None)
                if vergleich and vergleich[1]:
                    dt = (t-vergleich[0]).total_seconds()/86400
                    if dt > 0:
                        z["wachstumsrate_pct_pro_tag"] = 100*(z["pflanzen_pixel"]/vergleich[1]-1)/dt
                        if z["blattflaeche_cm2"] is not None and vergleich[2] is not None:
                            z["wachstumsrate_cm2_pro_tag"] = (z["blattflaeche_cm2"]-vergleich[2])/dt
                basis.append((t, z["pflanzen_pixel"], z["blattflaeche_cm2"]))
            letzter = z
        roh = z.get("gesundheit_roh")
        if roh is None:
            continue  # Kein alter Score wird als neue Messung fortgeschrieben.
        if vorher_score and t:
            t0 = datetime.fromisoformat(vorher_score["captured_at"].replace("Z", "+00:00"))
            stunden = (t-t0).total_seconds()/3600
            alpha = min(1., max(.25, 1-math.exp(-max(0., stunden)/2.)))
            z["gesundheit"] = alpha*roh+(1-alpha)*vorher_score["gesundheit"]
        score = z["gesundheit"]
        z["gesundheit_kategorie"] = next(n for grenze, n in [(85,"sehr gut"),(70,"gut"),(50,"beobachten"),(30,"auffaellig"),(0,"kritisch")] if score >= grenze)
        if t:
            gueltige.append(z)
            alle = fruehere_scores + [{"captured_at": iso(p["_zeit"]), "gesundheit": p["gesundheit"]} for p in gueltige[:-1]]
            vor24 = [p for p in alle if 22 <= (t-datetime.fromisoformat(p["captured_at"].replace("Z", "+00:00"))).total_seconds()/3600 <= 26]
            if vor24:
                vergleich = min(vor24, key=lambda p: abs((t-datetime.fromisoformat(p["captured_at"].replace("Z", "+00:00"))).total_seconds()/3600-24))
                z["gesundheit_trend_24h"] = score-vergleich["gesundheit"]
            vorher_score = {"captured_at": iso(t), "gesundheit": score}


def json_sicher(wert):
    if isinstance(wert,np.bool_):
        return bool(wert)
    if isinstance(wert, dict):
        return {k: json_sicher(v) for k, v in wert.items() if not k.startswith("_")}
    if isinstance(wert, (list, tuple)):
        return [json_sicher(v) for v in wert]
    if isinstance(wert, (float, np.floating)):
        return round(float(wert), 5) if math.isfinite(float(wert)) else None
    if isinstance(wert, np.integer):
        return int(wert)
    return wert


def api_datensatz(z, ref):
    messung = {eng: z.get(de) for de, eng in API_MESSFELDER.items()}
    gesundheit = {eng: z.get(de) for de, eng in API_GESUNDHEIT.items()}
    fehlt = {}
    if ist_pi_bild(z["bild"]):
        # Stabiler relativer Pfad aus dem Hardware-Handover. Funktioniert
        # auch auf beiden Archiven nach der lokalen 100-Bilder-Bereinigung.
        sitzung = z["bild"][len("biobox_"):-4]
        storage_path = f"recent/{sitzung}/normal.jpg"
    else:
        storage_path = None
        fehlt["storage_path"] = "externer_import_noch_keinem_serverpfad_zugeordnet"
    if z["mm_pro_pixel"] is None:
        for feld in ("leaf_area_cm2", "diameter_mm", "mm_per_px"):
            fehlt[feld] = "kein_verifizierter_massstab_in_blattebene"
    if z["wachstumsrate_cm2_pro_tag"] is None:
        fehlt["growth_rate_cm2_per_day"] = (f"massstab_fehlt_oder_keine_gueltige_vergleichsaufnahme_"
                                            f"mindestens_{RATE_MIN_STUNDEN}_stunden_frueher")
    if z["wachstumsrate_pct_pro_tag"] is None:
        fehlt["growth_rate_pct_per_day"] = (f"keine_gueltige_vergleichsaufnahme_mindestens_"
                                            f"{RATE_MIN_STUNDEN}_stunden_frueher")
    if z["gesundheit_trend_24h"] is None:
        fehlt["health_trend_24h"] = "kein_gueltiger_score_vor_24_stunden_plusminus_2h"
    if not z["captured_at"]:
        fehlt["captured_at"] = "keine_aufnahmezeit_im_dateinamen"
    if z["gesundheit"] is None:
        fehlt["health_score"] = z["gesundheit_status"]
    for feld, wert in messung.items():
        if wert is None and feld not in fehlt:
            fehlt[feld] = "bild_nicht_auswertbar" if not z["brauchbar"] else "kein_gueltiger_messwert"
    return json_sicher({"device_id": DEVICE_ID,
        "image": {"file_name": z["bild"], "captured_at": z["captured_at"],
                  "storage_path": storage_path, "checksum_sha256": z.get("_sha256")},
        "image_measurements": messung, "health_assessment": gesundheit,
        "analysis": {"version": ANALYSE_VERSION, "health_status": z["gesundheit_status"],
                     "pipeline_sha256": PIPELINE_SHA256,
                     "capture_time_source":z.get("zeitquelle"),
                     "mask_source": z.get("_maskenquelle","automatisch"),
                     "illumination": {"method": z.get("_lichtinfo",{}).get("modell"),
                                      "corrected": z.get("_lichtinfo",{}).get("korrigiert",False),
                                      "background_error": z.get("_lichtinfo",{}).get("hintergrund_fehler"),
                                      "excluded_leaf_pct": z.get("_lichtinfo",{}).get("blattpixel_ausgeschlossen_pct")},
                     "measurement_mode": "metric" if z["mm_pro_pixel"] is not None else "pixels",
                     "scale_status": z.get("_massstab_status"),
                     "lens_corrected": z.get("_objektiv_entzerrt", False),
                     "reference_file": ref["meta"]["bild"] if ref else None,
                     "reference_captured_at": ref["meta"].get("captured_at") if ref else None,
                     "reference_sha256": ref["meta"].get("sha256") if ref else None,
                     "reference_approved": REFERENZ_FREIGEGEBEN, "missing_values": fehlt}})


def ergebnisse_speichern(zeilen, ref, ausgabe):
    # CSV ist eine Kontrollansicht. Die API-Zahlen werden nie ueber CSV gelesen.
    inhalt = [api_datensatz(z, ref) for z in zeilen]
    # Jede leere Zelle bekommt in der CSV einen nachlesbaren Grund, damit
    # NULL nicht mit "Messwert war null" verwechselt wird.
    rueck = {e: d for d, e in {**API_MESSFELDER, **API_GESUNDHEIT}.items()}
    for z, satz in zip(zeilen, inhalt):
        gruende = {}
        for feld, grund in satz["analysis"]["missing_values"].items():
            gruende.setdefault(grund, []).append(rueck.get(feld, feld))
        z["fehlende_werte"] = " | ".join(
            f"{', '.join(sorted(f))}: {g}" for g, f in sorted(gruende.items()))
    json_tmp = ausgabe/".ergebnis.json.tmp"
    with json_tmp.open("w", encoding="utf-8") as datei:
        json.dump(inhalt, datei, ensure_ascii=False, indent=2, allow_nan=False)
    json_tmp.replace(ausgabe/"ergebnis.json")
    csv_tmp = ausgabe/".ergebnis.csv.tmp"
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as datei:
        writer = csv.DictWriter(datei, fieldnames=SPALTEN, delimiter=";", extrasaction="raise")
        writer.writeheader()
        for z in zeilen:
            daten = {}
            for k in SPALTEN:
                v = json_sicher(z.get(k))
                if v is None:
                    daten[k] = "NULL"
                elif isinstance(v, bool):
                    daten[k] = str(v)
                elif isinstance(v, float) and CSV_DEZIMALKOMMA:
                    daten[k] = str(v).replace(".", ",")
                else:
                    daten[k] = v
            writer.writerow(daten)
    try:
        csv_tmp.replace(ausgabe/"ergebnis.csv")
    except PermissionError:
        csv_tmp.unlink(missing_ok=True)
        print("CSV gesperrt: ergebnis.csv in Excel schliessen und erneut ausfuehren. Die neue Auswertung wird nicht uebernommen.")
        return False
    return True


def grafiken(zeilen, ordner):
    ordner.mkdir(exist_ok=True)
    gruen, rot, grau = "#32816c", "#b95750", "#62737b"
    zeiten = [z["_zeit"] for z in zeilen]
    zeitachse = bool(zeiten) and all(zeiten)
    x = zeiten if zeitachse else list(range(1, len(zeilen)+1))
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    def linie(ax, feld, label, farbe):
        y = [z.get(feld) if z.get(feld) is not None and z.get("brauchbar") else np.nan for z in zeilen]
        if not any(np.isfinite(v) for v in y):
            return False
        ax.plot(x, y, "o-", ms=4, lw=1.7, color=farbe, label=label)
        return True
    def hinweis(ax, text):
        ax.text(.5, .5, text, ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color=grau, linespacing=1.7)
    def speichern(fig, nummer):
        for ax in fig.axes:
            ax.grid(alpha=.16)
            ax.set_xlabel("Aufnahmezeit (UTC)" if zeitachse else "Aufnahme (ohne verlaessliche Zeit)")
            if zeitachse:
                locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
            if len(x) == 1 and zeitachse:
                t = mdates.date2num(x[0])
                ax.set_xlim(t-.02, t+.02)
        fig.text(.012, .012, f"BioBox | {sum(bool(z['brauchbar']) for z in zeilen)}/{len(zeilen)} auswertbar | Index relativ zur eigenen Referenz", fontsize=8, color=grau)
        fig.tight_layout(rect=(0, .05, 1, 1))
        fig.savefig(ordner/GRAFIK_DATEIEN[nummer], dpi=150, facecolor="white")
        plt.close(fig)
    kalibriert = any(z.get("blattflaeche_cm2") is not None for z in zeilen)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.set_title("01 | Sichtbare projizierte Blattflaeche")
    feld = "blattflaeche_cm2" if kalibriert else "pflanzen_pixel"
    hat_werte = linie(ax, feld, "Auswertbare Blattmaske", gruen)
    unbestaetigt = [(xi, z[feld]) for xi, z in zip(x, zeilen)
                   if not z.get("brauchbar") and z.get(feld) is not None]
    if unbestaetigt:
        ax.scatter([p[0] for p in unbestaetigt], [p[1] for p in unbestaetigt],
                   color=rot, marker="x", label="Maske pruefen; keine bestaetigte Messung")
        ax.legend()
    if not hat_werte and not unbestaetigt:
        hinweis(ax, "Keine lesbare Blattmaske. Kontrollbilder und Qualitaetsflags pruefen.")
    ax.set_ylabel("Flaeche [cm²]" if kalibriert else "Sichtbare Blattflaeche [Pixel]")
    speichern(fig, 0)
    fig, ax = plt.subplots(figsize=(10, 5))
    feld = "wachstumsrate_cm2_pro_tag" if kalibriert else "wachstumsrate_pct_pro_tag"
    ax.set_title("02 | Aenderung der sichtbaren Blattflaeche")
    if not linie(ax, feld, "Aenderungsrate", gruen):
        hinweis(ax, "Ab zwei vergleichbaren Aufnahmen mit Zeitstempel berechenbar.\nKeine Messung wird als 0 ergaenzt.")
    ax.axhline(0, color=grau, lw=.7)
    ax.set_ylabel("cm²/Tag" if kalibriert else "%/Tag — nur bei unveraenderter Kamera")
    speichern(fig, 1)
    fig, (oben, unten) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    oben.set_title("03 | Rohfarben der Blaetter (lichtabhaengig)")
    for feld, farbe, label in [("mittel_r", "#ba6262", "R"), ("mittel_g", gruen, "G"), ("mittel_b", "#5685a5", "B")]:
        linie(oben, feld, label, farbe)
    oben.set_ylabel("Mittlerer RGB-Kanal [0–255]")
    if oben.lines:
        oben.legend()
    else:
        hinweis(oben, "Keine auswertbare Blattfarbe.")
    for feld, farbe, label in [("gelbanteil_pct", "#c2a333", "Gelb"), ("braunanteil_pct", "#95684f", "Braun")]:
        linie(unten, feld, label, farbe)
    unten.set_ylabel("Anteil an Blattmaske [%]")
    if unten.lines:
        unten.legend()
    else:
        hinweis(unten, "Keine auswertbare Blattmaske.")
    speichern(fig, 2)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.set_title("04 | Sichtbarer Zustandsindex — 100 = Referenzzustand")
    for a, b, c in [(0,30,"#f6e3e0"),(30,50,"#f5e8da"),(50,70,"#f8f1d9"),(70,85,"#eaf0df"),(85,100,"#e0eee8")]:
        ax.axhspan(a, b, color=c)
    if linie(ax, "gesundheit", "Geglaettet", gruen):
        linie(ax, "gesundheit_roh", "Einzelaufnahme", grau)
        ax.legend()
    else:
        hinweis(ax, "Kein belastbarer Vergleich.\nGesundheit_status und Kontrollbilder pruefen.")
    ax.set_ylim(-2, 103)
    ax.set_ylabel("Relativer Index [0–100]")
    speichern(fig, 3)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    gute = [z for z in zeilen if z.get("gesundheit_roh") is not None]
    ax.set_title("05 | Ursachen des letzten Vergleichsindexes")
    if gute:
        z = gute[-1]
        labels = ["Farbverteilung", "Gelbzunahme", "Braun-/Warmzunahme", "Saettigungswechsel", "Farbtonwechsel"]
        werte = [z["score_"+k] for k in GEWICHTE]
        if z.get("_struktur_score") is not None:
            labels.append("Blattflaeche / Form")
            werte.append(z["_struktur_score"])
        balken = ax.barh(labels, werte, color=[gruen]*5+["#658199"] if len(werte)==6 else gruen)
        ax.bar_label(balken, fmt="%.1f", padding=3)
        ax.set_xlim(0, 112)
        ax.set_xlabel("Teilscore [0–100]; "+("Farbe 80 %, Struktur 20 %" if z.get("_struktur_score") is not None else "nur Farbvergleich"))
        ax.set_title(f"05 | {z['bild']}\nIndex {z['gesundheit']:.1f}/100 | {z['gesundheit_status']}", fontsize=11)
        ax.set_xticks([0, 25, 50, 75, 100])
        # Diese Grafik hat keine Zeitachse.
        fig.tight_layout()
        fig.savefig(ordner/GRAFIK_DATEIEN[4], dpi=150, facecolor="white")
        plt.close(fig)
    else:
        hinweis(ax, "Noch keine auswertbare Referenzaufnahme.")
        speichern(fig, 4)


@contextlib.contextmanager
def auswertung_sperren(ausgabe):
    """Nur ein schreibender Analyselauf; die Sperre endet auch bei Programmabbruch."""
    with (ausgabe/'.analyse.lock').open('a+b') as lock:
        if lock.seek(0,os.SEEK_END)==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('In diesem Ausgabeordner laeuft bereits eine Analyse.') from error
        try:yield
        finally:
            lock.seek(0)
            if os.name=='nt':msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(lock,fcntl.LOCK_UN)


def analysieren(pfade,ausgabe,manuell=None,einzelbilder=False,neue_referenz=False):
    """Alle Eingaben erneut auswerten; zusammenpassende Ausgaben gemeinsam ersetzen.

    Automatische Masken werden nicht aus dem Ausgabeordner eingelesen.
    Manuelle dateigenaue Korrekturen bleiben als bewusst gepruefte Eingabe.
    Bei einem Schreibfehler werden bereits ersetzte Dateien zurueckgesetzt.
    """
    pfade=list(pfade);ausgabe=Path(ausgabe).expanduser().resolve()
    if not pfade:raise ValueError('Keine Eingabebilder; vorhandene Auswertung bleibt erhalten.')
    ausgabe.mkdir(parents=True,exist_ok=True)
    with auswertung_sperren(ausgabe):
        work=Path(tempfile.mkdtemp(prefix='.biobox-auswertung-',dir=ausgabe.parent))
        fertig=work/'neu';fertig.mkdir();backup=work/'vorher';backup.mkdir()
        cleanup=True
        try:
            for name in ('referenz.npz','massstab.npz'):
                if (ausgabe/name).is_file():shutil.copy2(ausgabe/name,fertig/name)
            if (ausgabe/'masken_korrektur').is_dir():
                shutil.copytree(ausgabe/'masken_korrektur',fertig/'masken_korrektur')
            # Eigene fremde Dateien nicht als alte generierte Vorschauen loeschen.
            for folder,suffix in [('masken','_maske.png'),('kontrolle','_kontrolle.png')]:
                (fertig/folder).mkdir()
                if (ausgabe/folder).is_dir():
                    for path in (ausgabe/folder).iterdir():
                        generated=bool(re.match(r'^\d{5}_',path.name) and path.name.endswith(suffix))
                        if not generated:
                            target=fertig/folder/path.name
                            if path.is_dir():shutil.copytree(path,target,symlinks=True)
                            else:shutil.copy2(path,target,follow_symlinks=False)
            rows=_analysieren(pfade,fertig,manuell,einzelbilder,neue_referenz)
            required=['ergebnis.csv','ergebnis.json','masken','kontrolle','grafiken']
            if not all((fertig/name).exists() for name in required):
                raise OSError('Neue Auswertung ist unvollstaendig; alte Ausgabe bleibt erhalten.')
            if (fertig/'referenz.npz').is_file():required.append('referenz.npz')
            changes=[]
            try:
                for name in required:
                    old=ausgabe/name;new=fertig/name
                    item={'name':name,'old':False,'new':False};changes.append(item)
                    if old.exists():old.replace(backup/name);item['old']=True
                    new.replace(old);item['new']=True
            except OSError as error:
                rollback=[]
                for item in reversed(changes):
                    name=item['name']
                    try:
                        if item['new']:(ausgabe/name).replace(fertig/name)
                        if item['old']:(backup/name).replace(ausgabe/name)
                    except OSError:rollback.append(name)
                if rollback:
                    cleanup=False
                    raise OSError('Wiederherstellung blockiert. Sicherung erhalten unter '+str(backup)+': '+', '.join(rollback)) from error
                raise OSError('Ausgaben konnten nicht ersetzt werden. ergebnis.csv in Excel und offene Vorschauen schliessen. Bisherige Auswertung bleibt erhalten.') from error
        finally:
            if cleanup:shutil.rmtree(work)
    print(f'\n{len(rows)} Bilder erneut ausgewertet -> {ausgabe/"ergebnis.csv"}')
    print('Masken, Kontrollbilder, CSV/JSON und alle 5 Grafiken gemeinsam aktualisiert.')
    if manuell is None and not any(z.get('mm_pro_pixel') for z in rows):
        print('Fuer cm2/mm einmal eine bekannte Linealstrecke auf Blatthoehe markieren (--massstab-bild / --referenz-mm).')
    return rows


def _analysieren(pfade, ausgabe, manuell=None, einzelbilder=False, neue_referenz=False):
    ausgabe.mkdir(parents=True, exist_ok=True)
    masken, kontrolle = ausgabe/"masken", ausgabe/"kontrolle"
    masken.mkdir(exist_ok=True)
    kontrolle.mkdir(exist_ok=True)
    zustand = ausgabe/"referenz.npz"
    lineal = massstab_laden(ausgabe/"massstab.npz")
    ref = referenz_laden(zustand, neue_referenz, pfade) if not einzelbilder else None
    alte_historie = ref["meta"].get("historie", []) if ref else []
    kalibrierung = None
    if KALIBRIERUNG.exists() and not einzelbilder:
        d = json.loads(KALIBRIERUNG.read_text(encoding="utf-8"))
        groesse = d.get("bildgroesse")
        if not isinstance(groesse,(list,tuple)) or len(groesse)!=2 or min(groesse)<=0:
            raise ValueError("Alte Objektivdatei ohne Bildgroesse: mit --kalibrieren erneuern. Vorhandene Ergebnisse bleiben erhalten.")
        kalibrierung = d
    pfade = sorted(pfade, key=lambda p: (zeit_aus_name(Path(p).name) or datetime.max.replace(tzinfo=timezone.utc), str(p)))
    zeilen, erzeugt = [], set()
    vorheriges_bild = None
    for nummer, pfad in enumerate(pfade, 1):
        pfad = Path(pfad)
        zeit = None if einzelbilder else zeit_aus_name(pfad.name)
        z = {k: None for k in SPALTEN}
        z.update({"bild": pfad.name, "captured_at": iso(zeit), "zeitquelle": "name" if zeit else "unbekannt",
                  "pipeline_version": ANALYSE_VERSION, "scoring_version": SCORING_VERSION, "auffaelligkeit": "", "gesundheitswarnung": "",
                  "brauchbar": False, "gesundheit_status": "nicht_auswertbar", "gesundheit_kategorie": "keine_daten", "_zeit": zeit})
        zeilen.append(z)
        try:
            z["_sha256"] = hashlib.sha256(pfad.read_bytes()).hexdigest()
            bild = cv2.imdecode(np.fromfile(pfad, dtype=np.uint8), cv2.IMREAD_COLOR)
            if bild is None or min(bild.shape[:2]) < 16:
                flags_hinzufuegen(z, "nicht_lesbar")
                continue
            if kalibrierung is not None:
                bild = objektiv_entzerren(bild,kalibrierung)
            arbeit = kleiner(bild)
            prior, referenz_bild, szenen_flags = szene_abgleichen(arbeit, ref)
            if ref and (ref["meta"].get("bildbreite", bild.shape[1]), ref["meta"].get("bildhoehe", bild.shape[0])) != (bild.shape[1], bild.shape[0]):
                szenen_flags.append("aufloesung_geaendert")
            geometrie_ok = not any(f in szenen_flags for f in ("ansicht_geaendert", "aufloesung_geaendert", "kameralage_nicht_verifiziert"))
            z["_geometrie_ok"] = geometrie_ok and not einzelbilder
            registriert = not any(f in szenen_flags for f in ("aufloesung_geaendert", "kameralage_nicht_verifiziert"))
            lichtinfo = {"modell":"nicht_vergleichbar","korrigiert":False}
            licht_flags = []
            normal = arbeit
            if ref is not None and registriert and prior is not None:
                b,g,r = cv2.split(arbeit.astype(np.float32))
                probe = ((g > 1.015*r)&(g > 1.015*b)&(g > 20)).astype(np.uint8)*255
                normal,licht_flags,lichtinfo = licht_abgleichen(arbeit,probe,referenz_bild,prior)
            z["_lichtinfo"] = lichtinfo
            maske = korrektur_laden(ausgabe,z["_sha256"],bild.shape[:2],kalibrierung is not None)
            korrigiert_manuell = maske is not None
            if (maske is None and ref is not None and z["_sha256"]==ref["meta"].get("sha256") and
                    ref.get("maske_original") is not None and ref["maske_original"].shape==bild.shape[:2]):
                maske=ref["maske_original"].copy()
                korrigiert_manuell=ref["meta"].get("mask_source")=="manuell"
            if maske is None:
                maske_klein = segmentieren(normal if normal is not None else arbeit,prior if registriert else None,
                                          referenz_bild if registriert else None)
                maske = maske_verfeinern(licht_anwenden(bild,lichtinfo) if normal is not None else bild,
                                         maske_klein,referenz_bild if registriert else None)
            maske_klein = cv2.resize(maske,(arbeit.shape[1],arbeit.shape[0]),interpolation=cv2.INTER_NEAREST)
            z["_maskenquelle"] = "manuell" if korrigiert_manuell else "automatisch"
            mm_px, quelle = (massstab(bild,manuell,lineal) if not einzelbilder else
                             (float(manuell),"manuell_blattebene") if manuell else (None,"einzelbilder_ohne_gemeinsamen_massstab"))
            z.update(merkmale(bild, maske, mm_px))
            # Nie NULL: steht kein Massstab zur Verfuegung, nennt die Spalte
            # den Grund (z. B. nicht_kalibriert) statt einer leeren Zelle.
            z["massstab_quelle"] = quelle
            z["_massstab_status"] = quelle
            z["_objektiv_entzerrt"] = kalibrierung is not None
            z["rauschen"] = rauschen_schaetzen(bild)
            flags_hinzufuegen(z, *szenen_flags)
            if not zeit:
                flags_hinzufuegen(z, "keine_aufnahmezeit")
            genug = z["pflanzen_pixel"] >= max(80, .0004*maske.size)
            if not genug:
                flags_hinzufuegen(z, "keine_blattmaske")
            # Der Qualitaetsentscheid soll nicht allein durch einen Gain
            # schwanken. Der exportierte Schaerfewert bleibt die Rohmessung.
            pruefbild = normal if normal is not None else arbeit
            grau_pruef = cv2.cvtColor(pruefbild,cv2.COLOR_BGR2GRAY)
            scharf = bool(np.any(maske_klein) and
                          cv2.Laplacian(grau_pruef,cv2.CV_64F)[maske_klein>0].var() >= 8)
            if not scharf:
                flags_hinzufuegen(z, "unscharf")
            belichtet = z.get("ueberbelichtet_pct") is not None and z["ueberbelichtet_pct"] < 35
            if not belichtet:
                flags_hinzufuegen(z, "blattflaeche_ueberbelichtet")
            if np.any(maske[0]) or np.any(maske[-1]) or np.any(maske[:, 0]) or np.any(maske[:, -1]):
                flags_hinzufuegen(z, "blatt_am_bildrand")
            z["brauchbar"] = bool(genug and scharf and belichtet and z["rauschen"] < 35)
            if z["rauschen"] >= 35:
                flags_hinzufuegen(z, "starkes_rauschen")
            if vorheriges_bild is not None:
                _, _, paar_flags = szene_abgleichen(arbeit, vorheriges_bild)
                paar_gleich_gross = vorheriges_bild["meta"]["bildbreite"] == bild.shape[1] and vorheriges_bild["meta"]["bildhoehe"] == bild.shape[0]
                z["_geometrie_ok"] = bool(not paar_flags and paar_gleich_gross and not einzelbilder)
            if z["brauchbar"]:
                vorheriges_bild = {"bild": arbeit.copy(), "maske": maske_klein.copy(),
                                    "meta": {"bildbreite": bild.shape[1], "bildhoehe": bild.shape[0]}}
            else:
                vorheriges_bild = None
            if ref is None and z["brauchbar"] and not einzelbilder:
                ref = {"bild": arbeit.copy(), "bild_original":bild.copy(), "maske": maske_klein.copy(), "maske_original":maske.copy(), "meta": {
                    "version": SCORING_VERSION, "analyse_version": ANALYSE_VERSION, "messreihe": MESSREIHE,
                    "pipeline_sha256":PIPELINE_SHA256,
                    "arbeitsbreite": ARBEITSBREITE, "roi": list(ROI_NORMIERT) if ROI_NORMIERT else None,
                    "bild": z["bild"], "captured_at": z["captured_at"], "sha256": z["_sha256"],
                    "lens_hash": hashlib.sha256(KALIBRIERUNG.read_bytes()).hexdigest() if kalibrierung is not None else None,
                    "bildbreite": bild.shape[1], "bildhoehe": bild.shape[0],
                    "pflanzen_pixel": z["pflanzen_pixel"], "kompaktheit": z["kompaktheit"],
                    "mask_source":z["_maskenquelle"], "historie": []}}
                prior, referenz_bild = maske_klein, arbeit
            if ref is not None and z["_sha256"] == ref["meta"].get("sha256") and z["brauchbar"]:
                # Dieselbe urspruengliche Aufnahme: nach Maskenupgrade die
                # am Original gemessene Geometrie als Referenz nachziehen.
                ref["maske"] = maske_klein.copy()
                ref["maske_original"] = maske.copy()
                ref["bild_original"] = bild.copy()
                ref["meta"].update(pflanzen_pixel=z["pflanzen_pixel"],kompaktheit=z["kompaktheit"],mask_source=z["_maskenquelle"])
                prior,referenz_bild = maske_klein,arbeit
                normal,licht_flags,lichtinfo = arbeit,[],{"modell":"referenz","korrigiert":False}
                z["_lichtinfo"] = lichtinfo
            if einzelbilder:
                z["gesundheit_status"] = "einzelbilder_keine_gemeinsame_referenz"
            elif ref is not None:
                abgleich = (normal,licht_flags,lichtinfo) if registriert else (None,["lichtvergleich_nicht_verifiziert"],lichtinfo)
                f, licht_flags = gesundheitsmerkmale(arbeit, maske_klein, referenz_bild, prior,abgleich)
                flags_hinzufuegen(z, *licht_flags)
                if f is None:
                    z["gesundheit_status"] = licht_flags[0] if licht_flags else "lichtvergleich_nicht_moeglich"
                else:
                    bewerten(z, f, ref, struktur_erlaubt=geometrie_ok)
            stamm = f"{nummer:05d}_{pfad.stem}"
            z["_ausgabe_stamm"] = stamm
            if not cv2.imwrite(str(masken/(stamm+"_maske.png")), maske):
                raise OSError("Maske konnte nicht geschrieben werden")
            erzeugt.add(stamm)
            # Erst nach der zeitlichen Glaettung den Score ins Kontrollbild setzen.
            z["_kontrolle"] = (bild, maske) if len(pfade) <= 5 else None
            print(f"[{nummer}/{len(pfade)}] {pfad.name}: {z['pflanzen_pixel']} Blattpixel | {z['gesundheit_status']}")
        except (OSError, cv2.error, ValueError) as fehler:
            z["brauchbar"] = False
            z["gesundheit"] = z["gesundheit_roh"] = None
            for k in GEWICHTE:
                z["score_"+k] = None
            z["gesundheit_status"] = "analysefehler"
            flags_hinzufuegen(z, "analysefehler:"+str(fehler).splitlines()[0][:150])
            print(f"[{nummer}/{len(pfade)}] {pfad.name}: {z['auffaelligkeit']}")
    referenzzeit = (datetime.fromisoformat(ref["meta"]["captured_at"].replace("Z","+00:00"))
                   if ref is not None and ref["meta"].get("captured_at") else None)
    zeitreihe_und_glaettung(zeilen,alte_historie,referenzzeit)
    # Einmal runden: CSV, JSON und Diagramme benutzen dieselben Zahlen.
    for z in zeilen:
        for feld, stellen in RUNDUNG.items():
            if z.get(feld) is not None:
                z[feld] = round(float(z[feld]), stellen)
        if z.get("mittel_h") == 180:
            z["mittel_h"] = 0.0  # Kreisfoermiger Farbton, nicht ausserhalb 0..180.
    for z, pfad in zip(zeilen, pfade):
        if not z.get("_ausgabe_stamm"):
            continue
        if z.get("_kontrolle") is not None:
            bild, maske = z.pop("_kontrolle")
        else:
            bild = cv2.imdecode(np.fromfile(pfad, dtype=np.uint8), cv2.IMREAD_COLOR)
            if kalibrierung is not None:
                bild = objektiv_entzerren(bild,kalibrierung)
            maske = cv2.imread(str(masken/(z["_ausgabe_stamm"]+"_maske.png")), cv2.IMREAD_GRAYSCALE)
        kontrollbild(bild, maske, z, kontrolle/(z["_ausgabe_stamm"]+"_kontrolle.png"))
    # Nur alte, von diesem Programm erzeugte Vorschauen aufraeumen.
    for ordner, suffix in [(masken, "_maske.png"), (kontrolle, "_kontrolle.png")]:
        for p in ordner.glob("*"+suffix):
            if re.match(r"^\d{5}_", p.name) and p.name[:-len(suffix)] not in erzeugt:
                p.unlink()
    csv_aktuell = ergebnisse_speichern(zeilen, ref, ausgabe)
    if not csv_aktuell:
        raise PermissionError("CSV konnte nicht erstellt werden; bisherige Auswertung bleibt erhalten.")
    grafiken(zeilen, ausgabe/"grafiken")
    if ref is not None and not einzelbilder:
        neue = [{"captured_at": z["captured_at"], "gesundheit": z["gesundheit"]}
                for z in zeilen if z["captured_at"] and z["gesundheit"] is not None]
        historie = {p["captured_at"]: p for p in alte_historie+neue}
        ref["meta"]["historie"] = [historie[k] for k in sorted(historie)][-200:]
        referenz_speichern(zustand, ref)
    return zeilen


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ordner", nargs="?", help="Optional: nur diesen lokalen Ordner/dieses Bild analysieren")
    parser.add_argument("--lokal", metavar="PFAD", help="Vorhandene Bilder ohne Pi-Abruf analysieren")
    parser.add_argument("--abholen",action="store_true",help="Vorhandene Pi-Fotos abgleichen und alle Bilder neu auswerten; keine neue Aufnahme")
    plan=parser.add_mutually_exclusive_group()
    plan.add_argument("--stundenaufnahme-einrichten",action="store_true",help="Testaufnahme und stuendliche Aufnahmen direkt auf dem Pi einrichten")
    plan.add_argument("--stundenaufnahme-status",action="store_true",help="Pi-Zeitplan und letzten Aufnahmeversuch anzeigen")
    plan.add_argument("--stundenaufnahme-ausschalten",action="store_true",help="Nur den eigenen Pi-Stundenplan ausschalten")
    parser.add_argument("--nur-bild", action="store_true", help="Pi-Bilder holen, keine Analyse")
    parser.add_argument("--einzelbilder", action="store_true", help="Verschiedene Pflanzen: keine zeitlichen Gesundheits-/Wachstumsvergleiche")
    parser.add_argument("--neue-referenz", action="store_true", help="Referenz fuer diese Messreihe neu bilden")
    parser.add_argument("--ausgabe", type=Path, help="Ausgabeordner (Standard: neben bilder/auswertung)")
    parser.add_argument("--mm-pro-pixel", type=float, default=MM_PRO_PIXEL_MANUELL, help="Verifizierter Massstab der Blattebene")
    parser.add_argument("--kalibrieren", metavar="ORDNER", help="Objektiv mit Schachbrettbildern kalibrieren")
    parser.add_argument("--maske-korrigieren",type=Path,metavar="JPG",help="Blattmaske eines Originalfotos mit Pinsel korrigieren")
    parser.add_argument("--korrekturmaske",type=Path,metavar="PNG",help="Statt Fenster: binaere Maske mit Originalpixelgroesse importieren")
    skala = parser.add_mutually_exclusive_group()
    skala.add_argument("--massstab-bild", type=Path, metavar="JPG", help="Foto mit Lineal auf Blatthoehe: bekannte Strecke markieren und speichern")
    skala.add_argument("--massstab", action="store_true", help="Neues Linealfoto vom Pi holen und eine bekannte Strecke markieren")
    parser.add_argument("--referenz-mm", type=float, help="Tatsaechlich gemessene Laenge zwischen den zwei Punkten, in mm")
    parser.add_argument("--punkte", nargs=4, type=float, metavar=("X1", "Y1", "X2", "Y2"), help="Messpunkte im Originalbild; ohne Angabe zwei Klicks im Bildfenster")
    args = parser.parse_args()
    cv2.setNumThreads(2)
    if args.mm_pro_pixel is not None and (not math.isfinite(args.mm_pro_pixel) or args.mm_pro_pixel <= 0):
        parser.error("--mm-pro-pixel muss positiv und endlich sein")
    for aktion in ("einrichten","status","ausschalten"):
        if getattr(args,"stundenaufnahme_"+aktion):
            try:stundenaufnahme(aktion)
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as fehler:
                print(f"Pi-Zeitplan nicht bestaetigt: {fehler}");return 1
            return 0
    if args.abholen and (args.lokal or args.ordner or args.massstab):
        parser.error("--abholen ist fuer den Pi-Abruf, ohne --lokal/Ordner/--massstab")
    if args.kalibrieren:
        kalibrieren(args.kalibrieren)
        return 0
    if args.maske_korrigieren:
        try:
            ziel=args.ausgabe or args.maske_korrigieren.expanduser().resolve().parent.parent/"auswertung"
            pfad=maske_korrigieren(args.maske_korrigieren,ziel,args.korrekturmaske)
            if pfad:print(f"Maske gespeichert: {pfad}\nBeim naechsten Analyselauf wird diese Maske verwendet.")
        except (OSError,ValueError) as fehler:
            print(f"Maske nicht gespeichert: {fehler}");return 1
        return 0
    if args.korrekturmaske:
        parser.error("--korrekturmaske braucht --maske-korrigieren ORIGINALFOTO")
    if args.massstab_bild or args.massstab:
        if args.referenz_mm is None or not math.isfinite(args.referenz_mm) or args.referenz_mm <= 0:
            parser.error("Massstab-Eingabe braucht eine positive, echte --referenz-mm Laenge")
        try:
            bildpfad = args.massstab_bild
            if args.massstab:
                if args.lokal or args.ordner:
                    basis = Path(args.lokal or args.ordner).resolve()
                    auswahl = [basis] if basis.is_file() else [p for p in basis.iterdir() if p.is_file() and p.suffix.lower() in ENDUNGEN]
                else:
                    auswahl = pi_bilder_holen()
                if not auswahl:
                    raise ValueError("Kein Foto fuer die Linealmessung vorhanden.")
                bildpfad = max(auswahl, key=lambda p: (zeit_aus_name(Path(p).name) or datetime.min.replace(tzinfo=timezone.utc), str(p)))
            massstab_einrichten(bildpfad, args.referenz_mm,
                               args.ausgabe or BILDER_ORDNER.parent/"auswertung", args.punkte)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as fehler:
            print(f"Massstab nicht gespeichert: {fehler}")
            return 1
        return 0
    if args.referenz_mm is not None or args.punkte is not None:
        parser.error("--referenz-mm und --punkte gehoeren zu --massstab-bild")
    cv2.setNumThreads(2)
    lokal = args.lokal or args.ordner
    if lokal:
        ziel = Path(lokal).expanduser().resolve()
        if ziel.is_file():
            pfade = [ziel]
        elif ziel.is_dir():
            pfade = vorhandene_bilder(ziel)
        else:
            parser.error(f"Pfad nicht gefunden: {ziel}")
        ausgabe = args.ausgabe or ((ziel.parent.parent if ziel.is_file() else ziel.parent)/"auswertung")
    else:
        abruf_ok = True
        try:
            pfade = pi_bilder_holen(neue_aufnahme=not args.abholen)
        except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as fehler:
            # Ein nicht erreichbarer Pi darf die Auswertung nicht verhindern.
            # Alle vorhandenen Bilder werden trotzdem komplett neu gerechnet.
            abruf_ok = False
            print(f"Fotoabruf fehlgeschlagen: {fehler}")
            pfade = vorhandene_bilder(BILDER_ORDNER)
            if pfade:
                print(f"Weiter mit {len(pfade)} bereits vorhandenen Bildern; "
                      "alle Masken, Kontrollbilder, Tabellen und Grafiken werden neu erzeugt.")
            else:
                print(f"Keine Bilder in {BILDER_ORDNER}; vorhandene Auswertung bleibt erhalten.")
                return 1
        if args.nur_bild:
            return 0 if abruf_ok else 1
        ausgabe = args.ausgabe or BILDER_ORDNER.parent/"auswertung"
    if not pfade:
        print("Keine Bilder gefunden. Keine vorhandene Auswertung geloescht.")
        return 1
    try:
        analysieren(pfade, ausgabe, args.mm_pro_pixel, args.einzelbilder, args.neue_referenz)
    except (OSError, ValueError) as fehler:
        print(f"Analyse abgebrochen: {fehler}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
