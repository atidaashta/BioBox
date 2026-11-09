"""BioBox: Kamera, Blattmaske, Messwerte, relativer Zustandsindex und 5 Grafiken.

Installation: python -m pip install opencv-contrib-python numpy matplotlib
Normal:       python analyse.py (vorhandene Stundenfotos abholen und analysieren)
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
Neue Pflanze / geaenderter Aufbau: eigener Bildordner (Referenz nur im RAM).
Maske pruefen/korrigieren: python analyse.py --maske-korrigieren bilder/FOTO.jpg
Import einer geprueften Originalmaske: zusaetzlich --korrekturmaske MASKE.png

Jeder Lauf berechnet alle ausgewaehlten Bilder erneut, auch alte Aufnahmen.
Fotoabruf und lokale Auswertung sind unabhaengig: Auch bei einem SSH-Fehler
werden alle bereits im Bilderordner vorhandenen Fotos erneut ausgewertet.
Nach dem Abruf wird der Ordner neu eingelesen, auch fuer selbst ergaenzte Fotos.
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
CIELAB, Blattkerne und eine begrenzte Randverfeinerung trennen Blattflaeche
von typischen Hintergruenden. Aehnlich gefaerbte Gegenstaende koennen
weiterhin in die Maske gelangen; sehr schmale Blattpartien koennen fehlen.
Bei neuem Hintergrund oder anderen Blattfarben Kontrollbild pruefen. Individuelle Korrekturen werden
dateigenau gespeichert und beim naechsten Lauf wiederverwendet.
Belichtung, Weissabgleich und langsame Lichtgradienten werden ausschliesslich
am registrierten Hintergrund korrigiert. Blattfarben werden NICHT an eine
Sollfarbe angepasst. Der Index vergleicht nur gemeinsame, ausreichend
belichtete Blattpixel. Bei fehlender Vergleichbarkeit gibt es keinen Score.
Die CSV-Farben bleiben Rohwerte.

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
PI_SSH_KEY = Path.home() / ".ssh" / "biobox_ed25519"  # Verschluesselter privater SSH-Schluessel, nie das Pi-Passwort.
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
RATE_MIN_MINUTEN = 30    # Kurzer Vergleich; hohe Schwankung moeglich
RATE_STABIL_STUNDEN = 12  # Wenn verfuegbar, laengeren Abstand bevorzugen
SCORING_VERSION = "4.0.0"
ANALYSE_VERSION = "4.4.1"
PIPELINE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ENDUNGEN = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
CSV_DEZIMALKOMMA = True

# Die alten DB-Teilscores bleiben benannt, werden aber relativ und stetig
# berechnet. Gruen bewertet jetzt auch die gesamte Farbverteilung, nicht
# einen angenommenen gesunden Gruenton. Struktur wirkt zusaetzlich (15 %).
GEWICHTE = {"gruen": .30, "gelb": .20, "braun": .25, "saettigung": .15, "farbton": .10}
# Abweichung, bei der ein Teilscore auf 50 faellt. Startwerte, an echten
# Verlaeufen zu validieren (PSP 3.8).
HALBWERTE = {"hist": .20, "gruenindex": .024, "gelb": 8., "braun": 4.5,
             "saettigung": .23, "farbton": 8., "flaeche": .19, "form": .52, "lokal": 12.}
SPALTEN = [
    "bild", "captured_at", "zeitquelle", "stunden_seit_start", "pflanzen_pixel", "blattanteil_im_bild_pct", "blattpixel_aenderung_pro_tag", "pixel_vergleichsfoto",
    "blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
    "wachstumsrate_cm2_pro_tag", "wachstumsrate_pct_pro_tag", "wachstum_vergleichsfoto", "wachstum_abstand_stunden",
    "mittel_r", "mittel_g", "mittel_b", "farbe_hex", "mittel_h", "mittel_s",
    "gruenindex", "gelbanteil_pct", "braunanteil_pct", "mm_pro_pixel",
    "massstab_quelle", "schaerfe", "rauschen", "bildhelligkeit",
    "ueberbelichtet_pct", "groesste_komponente_pct", "auffaelligkeit", "brauchbar", "fehlende_werte",
    "pipeline_version", "scoring_version", "gesundheit", "gesundheit_roh", "gesundheit_kategorie",
    "gesundheit_status", "gesundheit_trend_24h", "gesundheitswarnung", "ansicht", "gesundheit_referenzfoto",
    "score_gruen", "score_gelb", "score_braun", "score_saettigung", "score_farbton",
]
RUNDUNG = {"stunden_seit_start": 4, "blattanteil_im_bild_pct": 3, "blattpixel_aenderung_pro_tag": 1, "blattflaeche_cm2": 2, "durchmesser_mm": 1,
           "kompaktheit": 4, "wachstumsrate_cm2_pro_tag": 3, "wachstumsrate_pct_pro_tag": 3, "wachstum_abstand_stunden": 3,
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

def pi_ssh_optionen():
    """SSH-Schluessel ueber ssh-agent verwenden; nie Passwortdialoge im Analyselauf."""
    if not PI_SSH_KEY.is_file():
        raise RuntimeError(f"SSH-Schluessel fehlt: {PI_SSH_KEY}. Erst unter Windows einrichten.")
    return ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-i", str(PI_SSH_KEY), "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"]


def pi_bilder_holen(neue_aufnahme=False):
    """Vorhandene Stundenfotos abgleichen; nur auf Wunsch neu aufnehmen.

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
    verbindung = pi_ssh_optionen()
    # Der Helfer veroeffentlicht nur fertige Sitzungen. .pending-* kann im
    # find-Ergebnis erscheinen, wird aber vom strengen Sitzungsmuster verworfen.
    auflisten = (f"find {shlex.quote(PI_FOTO_ORDNER)} -mindepth 2 -maxdepth 2 "
                 "-type f -name normal.jpg -printf 'BIOBOX_FOTO:%h\\n'")
    print(("Neue Aufnahme und Bildliste" if neue_aufnahme else "Vorhandene Bildliste")+
          f" von {PI_ADRESSE} ueber SSH-Schluessel.",flush=True)
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
            print("Kamera-JPEGs ueber verschluesselten SSH-Kanal herunterladen.", flush=True)
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
    """Alle Bilddateien eines Ordners; Lesbarkeit und Aufnahmezeit prueft die Analyse."""
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
    print(f'Pi-Stundenaufnahme: {aktion}; SSH-Schluessel verwenden.',flush=True)
    result=subprocess.run(['ssh',*pi_ssh_optionen(),PI_ADRESSE,'python3 -'],
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


def aufnahmezeit(pfad):
    """UTC aus Dateiname; EXIF nur mit tatsaechlich vorhandenem Zeitzonenoffset."""
    zeit = zeit_aus_name(Path(pfad).name)
    if zeit is not None:
        return zeit,"name"
    try:
        from PIL import Image
        with Image.open(pfad) as bild:
            exif = bild.getexif()
            daten = exif.get_ifd(34665)
        datum = daten.get(36867) or exif.get(36867)
        offset = daten.get(36881) or exif.get(36881)
        if isinstance(datum,str) and isinstance(offset,str) and re.fullmatch(r"[+-](?:0[0-9]|1[0-4]):[0-5][0-9]",offset):
            zeit = datetime.strptime(datum.strip()+" "+offset,"%Y:%m:%d %H:%M:%S %z")
            return zeit.astimezone(timezone.utc),"exif_mit_offset"
    except (ImportError,OSError,ValueError,TypeError,OverflowError,SyntaxError):
        pass
    return None,"unbekannt"


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
    n, labels, stats, _ = cv2.connectedComponentsWithStats(maske, connectivity=8)
    behalten = np.zeros(n, np.uint8)
    behalten[1:] = (stats[1:, cv2.CC_STAT_AREA] >= minimum).astype(np.uint8)*255
    return behalten[labels]


def feste_hintergrundlage(bild, ref_bild, hintergrund):
    """Identitaet nur bestaetigen, wenn Kanten in verteilten Bildteilen passen."""
    h,w = hintergrund.shape
    def kanten(im):
        g = cv2.GaussianBlur(cv2.cvtColor(im,cv2.COLOR_BGR2GRAY),(5,5),0)
        return (cv2.Sobel(g,cv2.CV_32F,1,0),cv2.Sobel(g,cv2.CV_32F,0,1))
    ax,ay = kanten(ref_bild)
    bx,by = kanten(bild)
    a = np.hypot(ax,ay)
    b = np.hypot(bx,by)
    ok = []
    relevant = []
    for i in range(3):
        for j in range(3):
            y,x = slice(i*h//3,(i+1)*h//3),slice(j*w//3,(j+1)*w//3)
            m = (hintergrund[y,x]>0) & (a[y,x]>=16)
            if np.count_nonzero(m)<max(50,int(.008*m.size)):
                continue
            richtung = (ax[y,x][m]*bx[y,x][m]+ay[y,x][m]*by[y,x][m]) / (
                np.maximum(1.,a[y,x][m]*b[y,x][m]))
            # Auch neue/stark verschobene Kanten verwerfen; ein einzelner
            # gleichgerichteter Rand reicht nicht als Beleg.
            a_tile,b_tile = a[y,x][m],b[y,x][m]
            gain = float(np.median(b_tile/a_tile))
            rest = np.median(np.abs(b_tile-gain*a_tile))/max(1.,float(np.median(b_tile)))
            relevant.append((i,j))
            if .25<gain<4 and np.mean(richtung>.94)>=.90 and rest<.20:
                ok.append((i,j))
    return (len(ok)>=3 and len(ok)>=.80*len(relevant)
            and len({i for i,_ in ok})>=2 and len({j for _,j in ok})>=2)


def szene_abgleichen(bild, ref, details=None):
    """Hintergrundmerkmale, nicht Blaetter: Verschieben der Kamera erkennen.

    Liefert die Referenzmaske in aktuellen Koordinaten. Kleine Verschiebungen
    werden fuer den Farbvergleich ausgeglichen. Starke Aenderungen werden
    gemeldet; Groessenvergleiche werden dann unterdrueckt.
    """
    if ref is None or bild.shape != ref["bild"].shape:
        return None, None, [] if ref is None else ["aufloesung_geaendert"]
    ref_bild, ref_maske = ref["bild"], ref["maske"]
    if np.array_equal(bild,ref_bild):
        if details is not None:
            details.update(scale=1.,rotation=0.,translation=0.,matrix=IDENTITAET)
        return ref_maske.copy(),ref_bild.copy(),[]
    orb = cv2.ORB_create(nfeatures=1800)
    hintergrund = 255-cv2.dilate(ref_maske, np.ones((19, 19), np.uint8))
    def lage_pruefen():
        if feste_hintergrundlage(bild,ref_bild,hintergrund):
            if details is not None:
                details.update(scale=1.,rotation=0.,translation=0.,matrix=IDENTITAET)
            return ref_maske.copy(),ref_bild.copy(),[]
        return None,None,["kameralage_nicht_verifiziert"]
    k1, d1 = orb.detectAndCompute(cv2.cvtColor(ref_bild, cv2.COLOR_BGR2GRAY), hintergrund)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY), None)
    if d1 is None or d2 is None:
        return lage_pruefen()
    paare = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    gut = [a for paar in paare if len(paar) == 2 for a, b in [paar] if a.distance < .72*b.distance]
    if len(gut) < 12:
        return lage_pruefen()
    src = np.float32([k1[m.queryIdx].pt for m in gut])
    dst = np.float32([k2[m.trainIdx].pt for m in gut])
    matrix, inlier = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if matrix is None or inlier is None or int(inlier.sum()) < 12 or float(inlier.mean()) < .45:
        return lage_pruefen()
    # Merkmale muessen ueber die Szene verteilt sein. Eine Ecke oder ein
    # einzelnes Blatt kann die Lage der gesamten Kamera nicht belegen.
    punkte = src[inlier.ravel() > 0]
    if cv2.contourArea(cv2.convexHull(punkte)) < .025*bild.shape[0]*bild.shape[1]:
        return lage_pruefen()
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    winkel = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    versatz = float(np.linalg.norm(matrix[:, 2])) / max(bild.shape[:2])
    # Unterhalb eines halben Arbeitspixels keine Interpolationsaenderung
    # durch das Rauschen der Merkmalsanpassung erzeugen.
    if abs(scale-1)<.0005 and winkel<.03 and np.linalg.norm(matrix[:,2])<.5:
        matrix=np.array([[1.,0.,0.],[0.,1.,0.]])
        scale,winkel,versatz=1.,0.,0.
    if details is not None:
        details.update(scale=scale, rotation=winkel, translation=versatz, matrix=matrix)
    flags = ["ansicht_geaendert"] if abs(scale-1) > .025 or winkel > 3 or versatz > .035 else []
    h, w = bild.shape[:2]
    return (cv2.warpAffine(ref_maske, matrix, (w, h), flags=cv2.INTER_NEAREST),
            cv2.warpAffine(ref_bild, matrix, (w, h)), flags)


def gruenheit(bgr):
    """CIELAB-Gegenfarben: Gruen-Rot (-a*) und Blau-Gelb (b*)."""
    lab = cv2.cvtColor(cv2.bilateralFilter(bgr, 5, 32, 5), cv2.COLOR_BGR2LAB)
    return np.clip(128-lab[:, :, 1].astype(np.int16), 0, 127).astype(np.uint8), lab[:, :, 2].astype(np.int16)-128


def pflanzen_roi(form):
    """Optionaler, fest eingestellter Aufnahmebereich in Originalkoordinaten."""
    h, w = form
    if ROI_NORMIERT is None:
        return np.full(form, 255, np.uint8)
    x0, y0, x1, y1 = ROI_NORMIERT
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("ROI_NORMIERT muss links, oben, rechts, unten im Bereich 0..1 enthalten.")
    roi = np.zeros(form, np.uint8)
    roi[round(y0*h):round(y1*h), round(x0*w):round(x1*w)] = 255
    return roi


def breite_blattbereiche(maske):
    """Schmale Stiele abtrennen und kurze Blattspitzen am breiten Kern erhalten."""
    if not np.any(maske):
        return maske
    radius = max(2.2, .0065*min(maske.shape))
    dicke = cv2.distanceTransform(maske, cv2.DIST_L2, 5)
    kern = np.uint8(dicke >= radius)*255
    if not np.any(kern):
        return np.zeros_like(maske)
    ausdehnung = cv2.dilate(kern, _kern(2*round(radius*2.15)+1))
    return cv2.bitwise_and(maske, ausdehnung)


def segmentieren(arbeit, prior=None, prior_bild=None):
    """Blattkerne und nahe Randpixel ermitteln, bevor am Original verfeinert wird."""
    gruen, gelb = gruenheit(arbeit)
    roi = pflanzen_roi(gruen.shape)
    signal = np.max(arbeit, axis=2) >= 23
    dunkel = cv2.cvtColor(arbeit, cv2.COLOR_BGR2GRAY) < 43
    # Cyanflaechen/Halterungen haben wenig Gelbanteil. Kuehle, aber stark
    # gruene Blattpartien bleiben moeglich. Otsu liefert nur eine Startschwelle.
    pflanzenfarbe = (((gelb >= 3) | ((gelb >= -4) & (gruen >= 19))) & signal
                     & (~dunkel | (gruen >= 16)) & (roi > 0))
    chroma = np.where(pflanzenfarbe, gruen, 0).astype(np.uint8)
    otsu, _ = cv2.threshold(chroma, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    schwelle = max(8, min(19, float(otsu)))
    kern = np.uint8(chroma >= schwelle)*255
    h, w = kern.shape
    breite = max(3, 2*round(.0035*min(h,w))+1)
    kern = cv2.morphologyEx(kern, cv2.MORPH_OPEN, _kern(breite))
    kern = saubere_komponenten(kern, max(20, round(.00007*kern.size)))
    nah = cv2.dilate(kern, _kern(5)) > 0
    schwach = (gruen >= max(CHROMA_MIN, 10)) & (gelb >= -2) & signal & (~dunkel | (gruen >= 17))
    maske = np.uint8((kern > 0) | (nah & schwach))*255

    if prior is not None and prior_bild is not None and prior.shape == maske.shape:
        # Kein blosses Kopieren der alten Maske: warme Pixel muessen in der
        # alten Blattflaeche liegen UND an aktuell sichtbares Gewebe grenzen.
        innen = cv2.erode(prior, _kern(breite)) > 0
        vorher_l = cv2.cvtColor(prior_bild, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.int16)
        aktuell = cv2.cvtColor(arbeit, cv2.COLOR_BGR2LAB)
        aktuell_l = aktuell[:, :, 0].astype(np.int16)
        aktuell_a = aktuell[:, :, 1].astype(np.int16)-128
        kontakt = cv2.dilate(kern, _kern(2*round(.047*min(h,w))+1)) > 0
        warm = (gelb >= 12) & (aktuell_a <= 30) & (aktuell_l >= np.maximum(27, vorher_l*.42))
        maske[innen & kontakt & warm] = 255
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, _kern(3))
    maske = loecher_schliessen(maske)
    maske = breite_blattbereiche(maske)
    return saubere_komponenten(cv2.bitwise_and(maske, roi), max(24, round(.00009*maske.size)))


def loecher_schliessen(maske):
    """Nur kleine, ringsum eingeschlossene Loecher fuellen."""
    anzahl, labels, stats, _ = cv2.connectedComponentsWithStats(255-maske, connectivity=8)
    behalten = stats[:, cv2.CC_STAT_AREA] <= max(16, round(.00045*maske.size))
    behalten[0] = False
    behalten[np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]])] = False
    maske[behalten[labels]] = 255
    return maske


def maske_verfeinern(bild, maske_klein, prior_bild=None):
    """Konturen in einem begrenzten Band an Originalpixeln mit GrabCut pruefen."""
    h, w = bild.shape[:2]
    basis = cv2.resize(maske_klein, (w,h), interpolation=cv2.INTER_NEAREST)
    if not np.any(basis):
        return basis
    rand = max(3, round(.004*min(h,w)))
    x,y,b,hb = cv2.boundingRect(basis)
    x0,y0,x1,y1 = max(0,x-rand-2),max(0,y-rand-2),min(w,x+b+rand+2),min(h,y+hb+rand+2)
    klein = basis[y0:y1,x0:x1]
    original = np.ascontiguousarray(bild[y0:y1,x0:x1])
    aussen = cv2.dilate(klein, _kern(2*rand+1))
    innen = cv2.erode(klein, _kern(2*max(1,rand//2)+1))
    gc = np.full(klein.shape, cv2.GC_BGD, np.uint8)
    gc[aussen > 0] = cv2.GC_PR_BGD
    gc[klein > 0] = cv2.GC_PR_FGD
    gc[innen > 0] = cv2.GC_FGD
    # Halterungen (kalt und nur schwach gruen) am Rand nicht anwachsen lassen.
    gruen, gelb = gruenheit(original)
    kalt = (gelb < -4) & (gruen < 19)
    dunkel = (cv2.cvtColor(original, cv2.COLOR_BGR2GRAY) < 43) & (gruen < 16)
    gc[((klein == 0) & (kalt | dunkel)) | ((gelb < -3) & (gruen < 16))] = cv2.GC_BGD
    fein = klein.copy()
    if np.any(gc == cv2.GC_BGD) and np.any(gc == cv2.GC_FGD):
        try:
            cv2.setRNGSeed(0)
            cv2.grabCut(original, gc, None, np.zeros((1,65), np.float64),
                        np.zeros((1,65), np.float64), 1, cv2.GC_INIT_WITH_MASK)
            fein = np.uint8((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD))*255
        except cv2.error:
            # Bei entarteter Farbverteilung die bereits gueltige Basismaske.
            pass
    fein = breite_blattbereiche(loecher_schliessen(fein))
    fein[(gelb < -3) & (gruen < 16)] = 0
    basis[y0:y1,x0:x1] = fein
    basis = cv2.bitwise_and(basis, pflanzen_roi((h,w)))
    return saubere_komponenten(basis, max(48, round(.00009*basis.size)))


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
        wert = meta.get("mm_pro_pixel")
        if meta.get("kind") != "ruler_scale" or not isinstance(wert,(int,float)) or not math.isfinite(wert) or wert <= 0:
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


def mask_beschnitten(maske):
    if np.any(maske[0]) or np.any(maske[-1]) or np.any(maske[:,0]) or np.any(maske[:,-1]):
        return True
    if ROI_NORMIERT is not None:
        roi = pflanzen_roi(maske.shape)
        return bool(np.any(cv2.subtract(roi,cv2.erode(roi,_kern(3))) & maske))
    return False


def merkmale(bild, maske, mm_px):
    pixel = cv2.countNonZero(maske)
    if pixel == 0:
        return {"pflanzen_pixel": 0, "mm_pro_pixel": mm_px}
    konturen, _ = cv2.findContours(maske, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    umfang = sum(cv2.arcLength(k, True) for k in konturen)
    huelle = cv2.convexHull(np.vstack(konturen)).reshape(-1,2).astype(np.float32)
    ecken = huelle[:,None,:]+np.array([[-.5,-.5],[-.5,.5],[.5,-.5],[.5,.5]],np.float32)
    huelle = cv2.convexHull(ecken.reshape(-1,2)).reshape(-1,2)
    # Exakter Feret-Durchmesser; blockweise, damit viele Randpunkte
    # keinen quadratischen Speicherbedarf verursachen.
    max_q = max(float(np.max(np.sum((huelle[i:i+128,None,:]-huelle[None,:,:])**2,axis=2)))
                for i in range(0,len(huelle),128))
    durchmesser_px = math.sqrt(max_q)
    n, _, stats, _ = cv2.connectedComponentsWithStats(maske, connectivity=8)
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
    """Eine Ansicht: Originalfoto mit duennen Blattkonturen und kurzer Kopfzeile."""
    h, w = bild.shape[:2]
    faktor = min(1.,1500/w,1150/h)
    breite, hoehe = max(1,round(w*faktor)),max(1,round(h*faktor))
    ansicht = cv2.resize(bild,(breite,hoehe),interpolation=cv2.INTER_AREA)
    m = cv2.resize(maske,(breite,hoehe),interpolation=cv2.INTER_NEAREST)
    ansicht[m > 0] = np.rint(.94*ansicht[m > 0]+.06*np.array([225,75,211])).astype(np.uint8)
    konturen, _ = cv2.findContours(m,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(ansicht,konturen,-1,(240,45,228),max(1,round(breite/1000)),cv2.LINE_AA)

    panel_breite = max(625,breite)
    kopf = 94
    panel = np.full((hoehe+kopf,panel_breite,3),248,np.uint8)
    start = (panel_breite-breite)//2
    panel[kopf:,start:start+breite] = ansicht
    schluessel, status = _status_kontrolle(z)
    farbe = STATUSFARBEN[schluessel]
    panel[:kopf,:8] = farbe
    links = 23
    def zeile(text, y, skala, farbe_text, platz=None):
        max_w = panel_breite-links-18 if platz is None else platz
        if cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,skala,1)[0][0] > max_w:
            while text and cv2.getTextSize(text+"...",cv2.FONT_HERSHEY_SIMPLEX,skala,1)[0][0] > max_w:
                text = text[:-1]
            text += "..."
        _text(panel,text,(links,y),skala,farbe_text)

    zeile(z.get("bild","?"),24,.61,(27,34,30),panel_breite-links-190)
    breite_status = cv2.getTextSize(status,cv2.FONT_HERSHEY_SIMPLEX,.5,1)[0][0]
    _text(panel,status,(panel_breite-breite_status-19,24),.5,farbe)
    zeit = (z.get("captured_at") or "Aufnahmezeit unbekannt").replace("T"," ").replace("Z"," UTC")
    zeile(zeit,44,.48,(89,98,93))
    flaeche = (f"{z['blattflaeche_cm2']:.2f} cm2" if z.get("blattflaeche_cm2") is not None
               else f"{z.get('pflanzen_pixel') or 0:,} Blattpixel".replace(","," "))
    index = f"Index {z['gesundheit']:.1f}/100" if z.get("gesundheit") is not None else "Index nicht bestimmbar"
    quelle = "Manuelle Maske" if z.get("_maskenquelle")=="manuell" else "Automatische Maske"
    zeile(f"{flaeche}  |  {index}  |  {quelle}",65,.55,(39,52,45))
    meldungen = {"blatt_am_bildrand":"Blaetter am Bild-/ROI-Rand",
                 "kameralage_nicht_verifiziert":"Kameralage nicht bestaetigt",
                 "ansicht_geaendert":"Kameraansicht veraendert",
                 "keine_blattmaske":"Keine brauchbare Blattmaske",
                 "unscharf":"Bild unscharf",
                 "lichtkorrektur_nicht_stabil":"Lichtvergleich zu unsicher",
                 "zu_wenig_gemeinsames_blattgewebe":"Zu wenig gemeinsame Blattflaeche",
                 "lichtvergleich_zu_wenig_blattgewebe":"Blattfarben nicht ausreichend messbar"}
    hinweise = [meldungen.get(f,f.replace("_"," ")) for f in (z.get("auffaelligkeit") or "").split(";") if f]
    if (z.get("gesundheit_status") or "").startswith("vorlaeufige_referenz"):
        hinweise.insert(0,"Referenz vorlaeufig")
    if (z.get("gesundheit_status") or "").endswith(";nur_farbvergleich"):
        hinweise.append("nur Farbvergleich")
    if z.get("_ist_referenz"):
        hinweise.append("Start dieser Kameraansicht; noch kein Vergleich")
    if z.get("_score_modus")=="farbverhaeltnis_teilflaeche":
        hinweise.append("nur farblich gepruefte Teilflaeche")
    if hinweise:
        zeile(" | ".join(hinweise),84,.43,(96,106,100))
    png_speichern(pfad,panel)


def png_speichern(pfad,bild):
    """OpenCV kodieren; Dateipfad ueber Python, auch bei Unicode auf Windows."""
    ok, png = cv2.imencode(".png",bild)
    if not ok:
        raise OSError(f"PNG konnte nicht gespeichert werden: {pfad}")
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
        if meta.get("version") not in (SCORING_VERSION, "2.0.0", "2.1.0", "3.0.0") or meta.get("messreihe") != MESSREIHE:
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
            meta.update(mask_source="manuell",pflanzen_pixel=geo["pflanzen_pixel"],kompaktheit=geo.get("kompaktheit"),beschnitten=mask_beschnitten(korr),historie=[])
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
        if cv2.countNonZero(gross) < max(80,.0004*gross.size):
            print("Alte Referenz nach Maskenpruefung nicht auswertbar.")
            return None
        geometrie = merkmale(cv2.resize(ref["bild"], (breite, hoehe)), gross, None)
        ref["maske"] = maske
        if meta.get("mask_source") != "manuell":
            if ref.get("bild_original") is not None:ref["maske_original"]=gross
            else:ref.pop("maske_original",None)
        meta.update(version=SCORING_VERSION, analyse_version=ANALYSE_VERSION,
                    pipeline_sha256=PIPELINE_SHA256,
                    pflanzen_pixel=geometrie["pflanzen_pixel"],
                    kompaktheit=geometrie.get("kompaktheit"), beschnitten=mask_beschnitten(gross),
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
    """Stetig: 100 bei Null, 50 beim Halbwert; Toleranzen werden je Merkmal abgezogen."""
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


def farbe_ohne_helligkeit(bild, gain=None):
    rgb = bild.astype(np.float32)
    if gain is not None:
        rgb *= np.asarray(gain,dtype=np.float32)
    rgb *= 160./np.maximum(1.,rgb.max(axis=2,keepdims=True))
    return np.rint(rgb).clip(0,255).astype(np.uint8)


def chromatik_abgleichen(arbeit, ref_bild, idx, xx, yy, info):
    """Weissabgleich aus Farbverhaeltnissen in nachweislich stabilen Bildteilen."""
    h,w = arbeit.shape[:2]
    cur = arbeit.reshape(-1,3)[idx].astype(float)
    alt = ref_bild.reshape(-1,3)[idx].astype(float)
    ok = (cur.min(axis=1)>=12)&(alt.min(axis=1)>=12)
    train = ok & (np.arange(len(idx))%4!=0)
    test = ok & ~train
    if np.count_nonzero(train)<300 or np.count_nonzero(test)<120:
        return None
    def log_chroma(bgr):
        return np.log(bgr[:,[0,2]]/bgr[:,[1]])
    delta = log_chroma(alt)-log_chroma(cur)
    gain = np.median(delta[train],axis=0)
    if np.max(np.abs(gain))>.40:
        return None
    fehler = np.max(np.abs(delta-gain),axis=1)
    raster = (4*yy//h)*4+4*xx//w
    felder = []
    for i in range(16):
        probe = fehler[test & (raster==i)]
        if len(probe)>=45 and np.median(probe)<=.09 and np.percentile(probe,75)<=.145:
            felder.append(i)
    stabil = test & np.isin(raster,felder)
    if (len(felder)<4 or len({i//4 for i in felder})<2 or len({i%4 for i in felder})<2
            or np.count_nonzero(stabil)<.30*np.count_nonzero(test)):
        return None
    zone = np.zeros((h,w),np.uint8)
    for i in felder:
        y,x = divmod(i,4)
        zone[y*h//4:(y+1)*h//4,x*w//4:(x+1)*w//4] = 255
    zone = cv2.dilate(zone,_kern(max(3,round(.10*min(h,w)))))
    info.update(modell="chromatik_teilflaeche",korrigiert=True,_lichtzone=zone,
                chroma_residual=round(float(np.median(fehler[stabil])),4))
    return farbe_ohne_helligkeit(arbeit,[np.exp(gain[0]),1.,np.exp(gain[1])])


def licht_abgleichen(arbeit, maske, ref_bild=None, ref_maske=None, chroma_erlaubt=False):
    """Robuste Belichtungs-/Weissabgleichkorrektur NUR aus Hintergrundpaaren.

    Die Pflanze wird nie an ihre alte Farbe angepasst. Linear, Gamma-Naeherung
    und langsamer Beleuchtungsgradient werden auf getrennten Pixeln validiert.
    Misslingt die Messung, entsteht kein erfundener besserer/schlechterer Score.
    """
    info = {"modell":"referenz", "korrigiert":False, "hintergrund_fehler":None,
            "hintergrund_anteil_pct":None}
    if ref_bild is None:
        return arbeit.copy(), [], info
    if ref_maske is None or arbeit.shape != ref_bild.shape:
        return None, ["lichtvergleich_nicht_verifiziert"], info
    if np.array_equal(arbeit,ref_bild):
        info.update(modell="identisch",hintergrund_fehler=0.)
        return arbeit.copy(),[],info
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
    # Fehler durch Helligkeit, Schatten und bewegte Gegenstaende nicht mit
    # Farbfehlern gleichsetzen. Die Rueckfallebene prueft Farbverhaeltnisse.
    voll_verifiziert = False
    if best is not None:
        info.update(modell=name,hintergrund_fehler=round(float(np.median(errors)),3))
        raster = (4*yy[valid]//h)*4+4*xx[valid]//w
        regional = [float(np.median(errors[raster==feld])) for feld in np.unique(raster)
                    if np.count_nonzero(raster==feld)>=45]
        voll_verifiziert = (np.median(errors)<=5. and np.percentile(errors,90)<=16.
                             and (not regional or max(regional)<=13.))
    if not voll_verifiziert:
        farbe = chromatik_abgleichen(arbeit,ref_bild,idx,xx,yy,info) if chroma_erlaubt else None
        if farbe is not None:
            return farbe,[],info
        return None,["lichtkorrektur_nicht_stabil"],info
    info["_koeff"] = best
    normal = licht_anwenden(arbeit,info)
    info["korrigiert"] = bool(np.mean(np.abs(normal.astype(float)-arbeit)) > .6)
    return normal,[],info


def gesundheitsmerkmale(arbeit, maske, ref_bild=None, ref_maske=None, abgleich=None):
    """Nur dieselben sichtbaren Blattbereiche in beiden Bildern vergleichen."""
    korrigiert, flags, info = abgleich if abgleich is not None else licht_abgleichen(arbeit,maske,ref_bild,ref_maske)
    if korrigiert is None or ref_bild is None or ref_maske is None:
        return None, flags or ["lichtvergleich_nicht_verifiziert"]
    # Ein Pixel Rand Abstand vermindert Mischfarben aus Blatt und Hintergrund.
    kern = cv2.erode(maske, _kern(3))
    ref_kern = cv2.erode(ref_maske, _kern(3))
    gemeinsam = (kern > 0) & (ref_kern > 0)
    n = int(np.count_nonzero(gemeinsam))
    n_cur, n_ref = cv2.countNonZero(kern), cv2.countNonZero(ref_kern)
    anteil = n/max(1,min(n_cur,n_ref))
    info["gemeinsame_blattflaeche_pct"] = round(100*anteil,2)
    if n < 50 or anteil < .60 or n < .35*max(n_cur,n_ref):
        return None, flags + ["zu_wenig_gemeinsames_blattgewebe"]
    # Vor der Korrektur gesaettigte bzw. zu dunkle Pixel sind nicht wiederherstellbar.
    schlecht = (np.any(arbeit >= 254,axis=2) | (np.max(arbeit,axis=2) < 12)
                | np.any(ref_bild >= 254,axis=2) | (np.max(ref_bild,axis=2) < 12))
    schlecht = cv2.dilate(schlecht.astype(np.uint8), _kern(3)) > 0
    chromatisch = info.get("modell")=="chromatik_teilflaeche"
    if chromatisch:
        gemeinsam &= info["_lichtzone"]>0
        teiln = int(np.count_nonzero(gemeinsam))
        info["chromatisch_gepruefte_blattflaeche_pct"] = round(100*teiln/max(1,n),2)
        if teiln<max(50,.30*n):
            return None,flags+["zu_wenig_bestaetigte_farbteilflaeche"]
        n = teiln
    gueltig = gemeinsam & ~schlecht
    vergleichbar = int(np.count_nonzero(gueltig))
    info["blattpixel_ausgeschlossen_pct"] = round(100*(1-vergleichbar/max(1,n)),2)
    if vergleichbar < 50 or vergleichbar < .65*n:
        return None, flags + ["lichtvergleich_zu_wenig_blattgewebe"]
    g = gueltig.astype(np.uint8)*255
    if chromatisch:
        ref_bild = farbe_ohne_helligkeit(ref_bild)
    cur = farbmerkmale(korrigiert,g)
    cur["_chromatisch"] = chromatisch
    alt = farbmerkmale(ref_bild,g)
    # Kontinuierliche lokale Kennwerte fuer kleine Verfaerbungen. Gleiche
    # Bildpositionen werden verglichen; unveraenderte Panaschierung faellt heraus.
    def lab_pixel(bild):
        pixel = bild[gueltig].reshape(-1,1,3).astype(np.float32)/255
        return cv2.cvtColor(pixel,cv2.COLOR_BGR2LAB).reshape(-1,3)
    jetzt, vorher = lab_pixel(korrigiert), lab_pixel(ref_bild)
    delta = jetzt[:,1:]-vorher[:,1:]
    farbabstand = np.linalg.norm(delta,axis=1)
    def warmwerte(lab):
        l,a,b = lab.T
        gelb = np.clip((a+18)/22,0,1)*np.clip((b-9)/23,0,1)
        braun = np.clip((a+8)/18,0,1)*np.clip((b-3)/14,0,1)*np.clip((64-l)/35,0,1)
        return (gelb,braun) if chromatisch else (np.maximum(gelb,braun),braun)
    warm,braun = warmwerte(jetzt)
    warm_alt,braun_alt = warmwerte(vorher)
    # Ohne Rotverschiebung keine Braunzunahme durch eine dunklere Stelle.
    signal = np.clip((delta[:,0]-2)/7,0,1)
    cur["_warm_delta"] = 100*float(np.maximum(0.,warm-warm_alt).mean())
    cur["_braun_delta"] = 100*float((np.maximum(0.,braun-braun_alt)*signal).mean())
    cur["_lokal_farb_pp"] = 100*float(np.clip((farbabstand-4)/17,0,1).mean())
    cur["_vergleich_basis"] = alt
    return cur, flags


def bewerten(z, merkmale_gesund, ref, struktur_erlaubt=True):
    if merkmale_gesund is None or not z["brauchbar"]:
        z["gesundheit_status"] = "nicht_auswertbar"
        z["gesundheit_kategorie"] = "keine_daten"
        return
    cur, alt = merkmale_gesund, merkmale_gesund["_vergleich_basis"]
    hist_abstand = float(cv2.compareHist(cur["_hist"],alt["_hist"],cv2.HISTCMP_BHATTACHARYYA))
    gruenverlust = max(0.,alt["gruenindex"]-cur["gruenindex"]-.002)
    lokal = cur["_lokal_farb_pp"]
    z["score_gruen"] = (.42*stetiger_score(max(0.,hist_abstand-.018), HALBWERTE["hist"])
                        + .26*stetiger_score(gruenverlust,HALBWERTE["gruenindex"])
                        + .32*stetiger_score(lokal,HALBWERTE["lokal"]))
    # Warm schliesst Gelb und Braun ein: weiter gebraeuntes Gewebe wird
    # dadurch nicht allein wegen geringerer Gelbflaeche als erholt bewertet.
    gelb_delta = cur["_warm_delta"]
    braun_delta = cur["_braun_delta"]
    z["score_gelb"] = stetiger_score(max(0.,gelb_delta-.4),HALBWERTE["gelb"])
    chromatisch = cur.get("_chromatisch",False)
    z["score_braun"] = None if chromatisch else stetiger_score(max(0.,braun_delta-.3),HALBWERTE["braun"])
    saett_delta = abs(math.log((cur["mittel_s"]+8)/(alt["mittel_s"]+8)))
    z["score_saettigung"] = stetiger_score(max(0.,saett_delta-.025),HALBWERTE["saettigung"])
    hue_delta = 0.
    if cur["mittel_h"] is not None and alt["mittel_h"] is not None:
        d = abs(cur["mittel_h"]-alt["mittel_h"])
        hue_delta = min(d,180-d)
    lab_delta = float(np.linalg.norm(cur["_lab"][1:]-alt["_lab"][1:]))
    z["score_farbton"] = stetiger_score(max(0.,max(hue_delta,lab_delta/2)-.7),HALBWERTE["farbton"])
    gewicht_summe = sum(GEWICHTE[k] for k in GEWICHTE if z["score_"+k] is not None)
    teile = [(GEWICHTE[k]/gewicht_summe,z["score_"+k]) for k in GEWICHTE if z["score_"+k] is not None]
    struktur_erlaubt = struktur_erlaubt and not chromatisch
    flaechenverlust = max(0., 1-z["pflanzen_pixel"]/max(1,ref["meta"]["pflanzen_pixel"]))
    z["_struktur_score"] = None
    if struktur_erlaubt:
        # Form ist nur Zusatzinformation bei Flaechenverlust. Wachstum oder
        # ein neues Blatt allein sollen den Index nicht verschlechtern.
        form_delta = 0.
        if z["kompaktheit"] and ref["meta"].get("kompaktheit"):
            form_delta = max(0.,abs(math.log(z["kompaktheit"]/ref["meta"]["kompaktheit"]))-.15)
        flaeche = stetiger_score(max(0.,flaechenverlust-.035),HALBWERTE["flaeche"])
        form = stetiger_score(form_delta,HALBWERTE["form"])
        struktur = flaeche*(1-.2*min(1.,flaechenverlust/.15)*(1-form/100))
        z["_struktur_score"] = struktur
        teile = [(gewicht*.85,score) for gewicht,score in teile] + [(.15,struktur)]
    # Arithmetisches und geometrisches Mittel: ein ausgepraegtes Symptom
    # kann den Index sichtbar senken, ohne dass ein einziger Teil ihn auf 0 setzt.
    arith = sum(wert*gewicht for gewicht,wert in teile)
    geo = math.exp(sum(gewicht*math.log(max(.01,wert)) for gewicht,wert in teile))
    z["gesundheit_roh"] = z["gesundheit"] = min(100.,.65*arith+.35*geo)
    z["gesundheit_status"] = "freigegeben" if z.get("_referenz_geprueft") else "vorlaeufige_referenz"
    z["_score_modus"] = "farbe_und_struktur" if struktur_erlaubt else "nur_farbe"
    if chromatisch:
        z["_score_modus"] = "farbverhaeltnis_teilflaeche"
        z["gesundheit_status"] += ";farbverhaeltnis_teilflaeche"
    elif not struktur_erlaubt:
        z["gesundheit_status"] += ";nur_farbvergleich"
    warnungen = []
    if lokal >= 7 or hist_abstand > .25 or hue_delta > 10:
        warnungen.append("farbveraenderung")
    if gelb_delta >= 5:
        warnungen.append("gelbanteil_gestiegen")
    if not chromatisch and braun_delta >= 2.5:
        warnungen.append("braunanteil_gestiegen")
    if saett_delta > .22:
        warnungen.append("saettigung_veraendert")
    if struktur_erlaubt and flaechenverlust > .15:
        warnungen.append("sichtbare_blattflaeche_gesunken")
    z["gesundheitswarnung"] = ";".join(warnungen)


IDENTITAET = np.float64([[1.,0.,0.],[0.,1.,0.]])


def passende_ansicht(arbeit, original_form, sha256, ansichten):
    """Zuerst dieselbe Datei, dann die zuletzt verwendeten Kamerareferenzen."""
    h,w = original_form
    kandidaten = [r for r in ansichten if r["bild"].shape==arbeit.shape
                  and (r["meta"].get("bildhoehe",h),r["meta"].get("bildbreite",w))==(h,w)]
    for ref in kandidaten:
        if ref["meta"].get("sha256")==sha256:
            return ref,ref["maske"],ref["bild"],{"matrix":IDENTITAET}
    for ref in reversed(kandidaten[-12:]):
        daten = {}
        prior,basis,flags = szene_abgleichen(arbeit,ref,daten)
        if not flags and prior is not None and "matrix" in daten:
            return ref,prior,basis,daten
    return None,None,None,{}


def ansicht_neu(z, bild, arbeit, maske, maske_klein, lens_hash):
    return {"bild":arbeit.copy(),"maske":maske_klein.copy(),
            "maske_original":maske.copy(),"bild_original":bild.copy(),
            "meta":{"version":SCORING_VERSION,"analyse_version":ANALYSE_VERSION,"messreihe":MESSREIHE,
                    "pipeline_sha256":PIPELINE_SHA256,"arbeitsbreite":ARBEITSBREITE,
                    "roi":list(ROI_NORMIERT) if ROI_NORMIERT else None,"lens_hash":lens_hash,
                    "bild":z["bild"],"captured_at":z["captured_at"],"sha256":z["_sha256"],
                    "bildbreite":bild.shape[1],"bildhoehe":bild.shape[0],
                    "pflanzen_pixel":z["pflanzen_pixel"],"kompaktheit":z["kompaktheit"],
                    "mask_source":z["_maskenquelle"],"beschnitten":z["_beschnitten"],"historie":[]}}


def pose_vergleichen(alt, neu):
    """Relative Kameralage und Bedarf nach einem gemeinsamen Ausschnitt."""
    if alt.get("_pose") is None or neu.get("_pose") is None:
        return None
    rel = (np.vstack((neu["_pose"],[0.,0.,1.])) @ np.vstack(
        (cv2.invertAffineTransform(alt["_pose"]),[0.,0.,1.])))[:2]
    scale = float(np.hypot(rel[0,0],rel[1,0]))
    winkel = abs(math.degrees(math.atan2(rel[1,0],rel[0,0])))
    if abs(scale-1)>.025 or winkel>3.:
        return None
    h,w = neu["_arbeitsform"]
    ecken = np.array([[0.,0.,1.],[w-1.,0.,1.],[0.,h-1.,1.],[w-1.,h-1.,1.]])
    sprung = float(np.max(np.linalg.norm(ecken@rel.T-ecken[:,:2],axis=1)))
    if sprung>.055*max(h,w):
        return None
    gemeinsam = bool((alt.get("_beschnitten") or neu.get("_beschnitten"))
                      and sprung>max(2.,.0025*max(h,w)))
    return rel,scale,gemeinsam


def vergleichbare_flaechen(alt, neu, pose):
    """Pixel in der Ansicht des aelteren Fotos; ggf. nur gemeinsame Sicht."""
    rel,scale,gemeinsam = pose
    if not gemeinsam:
        return float(alt["pflanzen_pixel"]),neu["pflanzen_pixel"]/scale**2
    altmaske,neumaske = alt["_rate_maske"],neu["_rate_maske"]
    h,w = neumaske.shape
    altfeld = cv2.warpAffine(np.full(altmaske.shape,255,np.uint8),rel,(w,h),flags=cv2.INTER_NEAREST)
    sichtbar = cv2.erode(altfeld,_kern(3))>0
    sichtbar[[0,-1],:] = False
    sichtbar[:,[0,-1]] = False
    if np.mean(sichtbar)<.90:
        return None
    alt_neu = cv2.warpAffine(altmaske,rel,(w,h),flags=cv2.INTER_NEAREST)
    n_alt,n_neu = np.count_nonzero((alt_neu>0)&sichtbar),np.count_nonzero((neumaske>0)&sichtbar)
    voll_alt = cv2.countNonZero(altmaske)
    voll_neu = cv2.countNonZero(neumaske)
    if min(n_alt,n_neu)<80 or n_alt<.88*voll_alt*scale**2 or n_neu<.88*voll_neu:
        return None
    # Der Arbeitsrasteranteil wird auf die Originalmessung zurueckgerechnet.
    return (alt["pflanzen_pixel"]*n_alt/(voll_alt*scale**2),
            neu["pflanzen_pixel"]*n_neu/(voll_neu*scale**2))


def wachstum_vergleichen(z, basis):
    """12 h wenn moeglich; bei kuerzerer Serie wenigstens 30 Minuten."""
    t = z["_zeit"]
    fruehere = [alt for alt in basis if alt["_zeit"]<t]
    vergleichbar = [(alt,pose) for alt in fruehere if (pose:=pose_vergleichen(alt,z)) is not None]
    if not vergleichbar:
        return "kameraausschnitt_nicht_vergleichbar" if fruehere else "keine_fruehere_vergleichsaufnahme"
    stabil = [p for p in vergleichbar if p[0]["_zeit"]<=t-timedelta(hours=RATE_STABIL_STUNDEN)]
    kurz = [p for p in vergleichbar if t-timedelta(hours=RATE_STABIL_STUNDEN)<p[0]["_zeit"]
            <=t-timedelta(minutes=RATE_MIN_MINUTEN)]
    if not (stabil or kurz):
        return f"zeitabstand_unter_{RATE_MIN_MINUTEN}_minuten"
    # Bei gleicher Zeitklasse erst den Vergleich der vollstaendigen Masken suchen.
    for alt,pose in (sorted(reversed(stabil),key=lambda p:p[1][2])+sorted(kurz,key=lambda p:p[1][2])):
        flaechen = vergleichbare_flaechen(alt,z,pose)
        if flaechen is None:
            continue
        pixel_alt,pixel_neu = flaechen
        if abs(pixel_neu/pixel_alt-1)>.5:
            return "flaechensprung_pruefen"
        tage = (t-alt["_zeit"]).total_seconds()/86400
        z["wachstumsrate_pct_pro_tag"] = 100*(pixel_neu/pixel_alt-1)/tage
        _,scale,gemeinsam = pose
        mm_alt,mm_neu = alt["mm_pro_pixel"],z["mm_pro_pixel"]
        if mm_alt is not None and mm_neu is not None and (
                alt["massstab_quelle"]==z["massstab_quelle"]=="manuell_blattebene"
                or abs((mm_neu/mm_alt)*scale-1)<=.035):
            z["wachstumsrate_cm2_pro_tag"] = (pixel_neu-pixel_alt)*mm_alt**2/(100*tage)
        z["wachstum_vergleichsfoto"] = alt["bild"]
        z["wachstum_abstand_stunden"] = tage*24
        kurz_verwendet = tage*24<RATE_STABIL_STUNDEN
        if kurz_verwendet:
            flags_hinzufuegen(z,"wachstumsrate_kurzer_zeitabstand")
        if gemeinsam:
            flags_hinzufuegen(z,"wachstum_gemeinsamer_bildausschnitt")
            return "berechnet_gemeinsamer_ausschnitt_kurz" if kurz_verwendet else "berechnet_gemeinsamer_ausschnitt"
        return "berechnet_kurzer_abstand" if kurz_verwendet else "berechnet"
    return "zu_wenig_gemeinsame_sichtflaeche"


def pixel_vergleichen(z, basis):
    """Bildmessung in px/Tag ohne geometrische Korrektur; kein Wachstumsnachweis."""
    t = z["_zeit"]
    if t is None or not z["brauchbar"]:
        return
    vorher = [a for a in basis if a["_bildform"]==z["_bildform"]
              and a["_zeit"]<=t-timedelta(minutes=RATE_MIN_MINUTEN)]
    stabil = [a for a in vorher if a["_zeit"]<=t-timedelta(hours=RATE_STABIL_STUNDEN)]
    if vorher:
        alt = stabil[-1] if stabil else vorher[0]
        tage = (t-alt["_zeit"]).total_seconds()/86400
        z["blattpixel_aenderung_pro_tag"] = (z["pflanzen_pixel"]-alt["pflanzen_pixel"])/tage
        z["pixel_vergleichsfoto"] = alt["bild"]
    basis.append(z)


def zeitreihe_und_glaettung(zeilen, alte_historie, referenzzeit=None):
    auswahl_start = min((z["_zeit"] for z in zeilen if z["_zeit"]),default=None)
    start = referenzzeit or auswahl_start
    verlauf, basis, pixelbasis = {}, {}, []
    if auswahl_start:
        for ansicht,punkte in alte_historie.items():
            vorher = [(datetime.fromisoformat(p["captured_at"].replace("Z","+00:00")),
                        p["gesundheit"],p["modus"]) for p in punkte]
            verlauf[ansicht] = sorted(p for p in vorher if p[0]<auswahl_start)
    for z in zeilen:
        t = z["_zeit"]
        gruppe = z.get("_ansicht_id")
        if t and start:
            z["stunden_seit_start"] = (t-start).total_seconds()/3600
        if z["gesundheit_status"]=="einzelbilder_keine_gemeinsame_referenz":
            z["_rate_status"] = "einzelbilder_ohne_wachstumsreihe"
        elif not z["brauchbar"]:
            z["_rate_status"] = "bild_nicht_auswertbar"
        elif not t:
            z["_rate_status"] = "keine_verlaessliche_aufnahmezeit"
        elif gruppe is None:
            z["_rate_status"] = "kameraansicht_nicht_vergleichbar"
        else:
            fruehere = basis.setdefault(gruppe,[])
            z["_rate_status"] = wachstum_vergleichen(z,fruehere)
            if z["_rate_status"]=="flaechensprung_pruefen":
                flags_hinzufuegen(z,"flaechensprung_pruefen")
                fruehere.clear()
            if not fruehere or t>fruehere[-1]["_zeit"]:
                fruehere.append(z)

        if z["gesundheit_status"]!="einzelbilder_keine_gemeinsame_referenz":
            pixel_vergleichen(z,pixelbasis)
        roh = z.get("gesundheit_roh")
        if roh is None:
            continue
        scores = verlauf.setdefault(gruppe,[])
        modus = z.get("_score_modus")
        if t and scores and scores[-1][0]<t and scores[-1][2]==modus:
            stunden = (t-scores[-1][0]).total_seconds()/3600
            alpha = min(1.,max(.25,1-math.exp(-stunden/2.)))
            z["gesundheit"] = alpha*roh+(1-alpha)*scores[-1][1]
        score = z["gesundheit"]
        z["gesundheit_kategorie"] = next(n for grenze,n in
            [(85,"sehr gut"),(70,"gut"),(50,"beobachten"),(30,"auffaellig"),(0,"kritisch")] if score>=grenze)
        if t:
            vor24 = [p for p in scores if p[2]==modus and 22<=(t-p[0]).total_seconds()/3600<=26]
            if vor24:
                vergleich = min(vor24,key=lambda p:abs((t-p[0]).total_seconds()/3600-24*3600))
                z["gesundheit_trend_24h"] = score-vergleich[1]
            if not scores or t>scores[-1][0]:
                scores.append((t,score,modus))


def json_sicher(wert):
    if isinstance(wert,np.bool_):
        return bool(wert)
    if isinstance(wert, dict):
        return {k: json_sicher(v) for k, v in wert.items() if not k.startswith("_")}
    if isinstance(wert, (list, tuple)):
        return [json_sicher(v) for v in wert]
    if isinstance(wert, (float, np.floating)):
        return float(wert) if math.isfinite(float(wert)) else None
    if isinstance(wert, np.integer):
        return int(wert)
    return wert


def api_datensatz(z, ref=None):
    messung = {eng: z.get(de) for de, eng in API_MESSFELDER.items()}
    gesundheit = {eng: z.get(de) for de, eng in API_GESUNDHEIT.items()}
    fehlt = {}
    referenz = z.get("_referenz_meta") or {}
    if ist_pi_bild(z["bild"]):
        # Stabiler relativer Pfad aus dem Hardware-Handover. Funktioniert
        # auch auf beiden Archiven nach der lokalen 100-Bilder-Bereinigung.
        sitzung = z["bild"][len("biobox_"):-4]
        storage_path = f"recent/{sitzung}/normal.jpg"
    else:
        storage_path = None
        fehlt["storage_path"] = "externer_import_noch_keinem_serverpfad_zugeordnet"
    if z["mm_pro_pixel"] is None:
        for feld in ("leaf_area_cm2","diameter_mm","mm_per_px"):
            fehlt[feld] = z.get("massstab_quelle") or "kein_verifizierter_massstab_in_blattebene"
    rate_grund = z.get("_rate_status") or "keine_gueltige_vergleichsaufnahme"
    if z["wachstumsrate_cm2_pro_tag"] is None:
        fehlt["growth_rate_cm2_per_day"] = (
            "kein_gemeinsamer_massstab_fuer_beide_aufnahmen" if rate_grund.startswith("berechnet") else rate_grund)
    if z["wachstumsrate_pct_pro_tag"] is None:
        fehlt["growth_rate_pct_per_day"] = rate_grund
    if z.get("blattpixel_aenderung_pro_tag") is None:
        fehlt["blattpixel_aenderung_pro_tag"] = (
            "aufnahmezeit_fehlt" if not z["captured_at"] else
            "bild_nicht_auswertbar" if not z["brauchbar"] else
            "kein_frueheres_brauchbares_bild_gleicher_aufloesung_mit_mindestabstand")
    if z.get("blattanteil_im_bild_pct") is None:
        fehlt["blattanteil_im_bild_pct"] = "blattmaske_nicht_berechenbar"
    if z["gesundheit_trend_24h"] is None:
        fehlt["health_trend_24h"] = "kein_gueltiger_score_vor_24_stunden_plusminus_2h"
    if not z["captured_at"]:
        fehlt["captured_at"] = "keine_verlaessliche_aufnahmezeit"
    for feld, wert in gesundheit.items():
        if wert is None and feld not in fehlt:
            fehlt[feld] = z["gesundheit_status"]
    if z.get("_score_modus")=="farbverhaeltnis_teilflaeche":
        fehlt["score_brown"] = "brauntoene_ohne_bestaetigte_helligkeit_nicht_bewertet"
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
                                      "excluded_leaf_pct": z.get("_lichtinfo",{}).get("blattpixel_ausgeschlossen_pct"),
                                      "common_leaf_pct": z.get("_lichtinfo",{}).get("gemeinsame_blattflaeche_pct"),
                                      "verified_color_region_pct":z.get("_lichtinfo",{}).get("chromatisch_gepruefte_blattflaeche_pct")},
                     "measurement_mode": "metric" if z["mm_pro_pixel"] is not None else "pixels",
                     "scale_status": z.get("_massstab_status"),
                     "lens_corrected": z.get("_objektiv_entzerrt", False),
                     "reference_file": referenz.get("bild"),
                     "reference_captured_at": referenz.get("captured_at"),
                     "reference_sha256": referenz.get("sha256"),
                     "reference_approved": bool(referenz and z.get("_referenz_geprueft")),
                     "is_reference": bool(z.get("_ist_referenz")),
                     "health_comparison_mode":z.get("_score_modus"),
                     "view_id": z.get("_ansicht_id"),
                     "growth_reference_file": z.get("wachstum_vergleichsfoto"),
                     "growth_interval_hours": z.get("wachstum_abstand_stunden"),
                     "growth_comparison_mode":z.get("_rate_status") if rate_grund.startswith("berechnet") else None,
                     "pixel_measurement": {"leaf_coverage_pct":z.get("blattanteil_im_bild_pct"),
                                           "visible_pixel_change_per_day":z.get("blattpixel_aenderung_pro_tag"),
                                           "reference_file":z.get("pixel_vergleichsfoto")},
                     "missing_values": fehlt}})


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
        if z.get("stunden_seit_start") is None:
            gruende.setdefault("keine_verlaessliche_aufnahmezeit",[]).append("stunden_seit_start")
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
    def verlauf_mit_status(nummer,titel,feld,ylabel,status,zweiter=None,pixel=False):
        aufnahmen = np.arange(1,len(zeilen)+1)
        gruppen = list(dict.fromkeys(status))
        hoehe_status = max(.95,.31*len(gruppen)+.3)
        hoehen = [3.1,2.1,hoehe_status] if pixel else [3.5,hoehe_status]
        fig,achsen = plt.subplots(len(hoehen),1,figsize=(11,sum(hoehen)+1.3),sharex=True,
                                 gridspec_kw={"height_ratios":hoehen})
        ax,unten = achsen[0],achsen[-1]
        ax.set_title(titel,loc="left",fontweight="semibold",pad=12)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y",alpha=.19)
        y = np.array([z[feld] if z.get(feld) is not None else np.nan for z in zeilen])
        anzahl = int(np.count_nonzero(np.isfinite(y)))
        ax.set_xlim(.5,max(1,len(zeilen))+.5)
        ansichten = [z.get("ansicht") for z in zeilen]
        farben = ["#2e806a","#547da0","#9362a1","#ad7340","#56705a","#8a6371"]
        modi = [z.get("_score_modus") for z in zeilen]
        for i,ansicht in enumerate(dict.fromkeys(a for a in ansichten if a is not None)):
            farbe = farben[i%len(farben)]
            serien = list(dict.fromkeys(m for j,m in enumerate(modi) if ansichten[j]==ansicht)) if zweiter else [None]
            for modus in serien:
                maske = np.array([a==ansicht and (not zweiter or m==modus) for a,m in zip(ansichten,modi)])
                if not np.isfinite(y[maske]).any():
                    continue
                teil = modus=="farbverhaeltnis_teilflaeche"
                label = f"Ansicht {ansicht}"+(" · Farbteilfläche" if teil else "")
                ax.plot(aufnahmen,np.where(maske,y,np.nan),"s-" if teil else "o-",
                        ms=4.5,lw=1.6,color=farbe,label=label)
                if zweiter:
                    roh = np.array([z[zweiter] if z.get(zweiter) is not None else np.nan for z in zeilen])
                    ax.plot(aufnahmen,np.where(maske,roh,np.nan),"--",lw=.9,color=farbe,alpha=.45)
        refs = [i for i,z in enumerate(zeilen) if z.get("_ist_referenz")] if zweiter else []
        if nummer==3:
            ax.set_ylim(-3,107)
            ax.axhline(100,color="#b4bec3",lw=1,ls=":",zorder=0)
            ax.set_yticks([0,25,50,75,100])
        elif anzahl:
            ax.axhline(0,color=grau,lw=.8)
        if refs:
            ax.scatter(aufnahmen[refs],[100]*len(refs),marker="D",facecolor="white",edgecolor="#517493",
                       s=44,zorder=5,label="Referenzstart (kein Messwert)")
        if not anzahl:
            hinweis(ax,"Keine geprüfte Wachstumsrate.\nDirekte Pixelmessung siehe unten." if pixel
                    else "Noch kein gültiger Farbvergleich. Status je Aufnahme unten.")
            if nummer==1:
                ax.set_yticks([])
        if anzahl or refs:
            handles,labels = ax.get_legend_handles_labels()
            ax.legend(handles[:12],labels[:12],loc="lower left" if zweiter else "best",fontsize=8.5)
        if pixel:
            roh_ax = achsen[1]
            px = np.array([z["blattpixel_aenderung_pro_tag"] if z.get("blattpixel_aenderung_pro_tag") is not None
                           else np.nan for z in zeilen])
            roh_ax.set_title("Direkte Änderung der Blattpixel · auch zwischen Ansichten",loc="left",fontsize=10)
            roh_ax.set_ylabel("Pixel pro Tag")
            roh_ax.grid(axis="y",alpha=.15)
            if np.isfinite(px).any():
                roh_ax.axhline(0,color=grau,lw=.7)
                roh_ax.plot(aufnahmen,px,"o:",color="#76548b",ms=4,lw=1.1)
            else:
                hinweis(roh_ax,"Keine zwei brauchbaren Aufnahmen mit gleicher Auflösung und mindestens 30 min Abstand.")
        unten.set_title("Status je Aufnahme",loc="left",fontsize=9,color=grau,pad=5)
        for idx,gruppe in enumerate(gruppen):
            xs = [n for n,g in zip(aufnahmen,status) if g==gruppe]
            marker = "D" if gruppe=="Referenzstart" else "o" if gruppe.startswith("Berechnet") else "x"
            farbe = "#517493" if marker=="D" else gruen if marker=="o" else "#9c663b"
            unten.scatter(xs,[idx]*len(xs),s=28,marker=marker,color=farbe,linewidths=1.2)
        unten.set_yticks(range(len(gruppen)),gruppen,fontsize=9)
        unten.set_ylim(len(gruppen)-.4,-.6)
        unten.grid(axis="y",alpha=.15)
        unten.tick_params(axis="y",length=0)
        unten.set_xticks(sorted(set(np.linspace(1,len(zeilen),min(9,len(zeilen)),dtype=int))))
        unten.set_xlabel("Aufnahmenummer (Reihenfolge in ergebnis.csv)")
        zusatz = "Pixeländerung ist kein Wachstumsnachweis." if pixel else "Linie: geglättet · gestrichelt: Rohwert."
        fig.text(.013,.013,f"BioBox | {anzahl}/{len(zeilen)} mit geprüftem Vergleich | {zusatz}",fontsize=8.5,color=grau)
        fig.tight_layout(rect=(0,.045,1,1))
        fig.savefig(ordner/GRAFIK_DATEIEN[nummer],dpi=150,facecolor="white")
        plt.close(fig)

    brauchbare = [z for z in zeilen if z["brauchbar"]]
    kalibriert = bool(brauchbare) and all(z["blattflaeche_cm2"] is not None for z in brauchbare)
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
    rate_cm = kalibriert and any(z.get("wachstumsrate_cm2_pro_tag") is not None for z in zeilen)
    feld = "wachstumsrate_cm2_pro_tag" if rate_cm else "wachstumsrate_pct_pro_tag"
    ratetexte = {"berechnet":"Berechnet", "berechnet_kurzer_abstand":"Berechnet · kurzer Abstand",
                  "kameraausschnitt_nicht_vergleichbar":"Bildausschnitt nicht vergleichbar",
                  "zu_wenig_gemeinsame_sichtflaeche":"Zu wenig gemeinsamer Ausschnitt",
                  "berechnet_gemeinsamer_ausschnitt":"Berechnet · gemeinsamer Ausschnitt",
                  "berechnet_gemeinsamer_ausschnitt_kurz":"Berechnet · gemeinsamer Ausschnitt, kurz",
                  "bild_nicht_auswertbar":"Bild nicht auswertbar",
                  "kameraansicht_nicht_vergleichbar":"Kameraansicht nicht vergleichbar",
                  "keine_verlaessliche_aufnahmezeit":"Aufnahmezeit fehlt",
                  "keine_fruehere_vergleichsaufnahme":"Kein früheres Vergleichsfoto",
                  "flaechensprung_pruefen":"Flächensprung prüfen",
                  "einzelbilder_ohne_wachstumsreihe":"Einzelbild ohne Messreihe",
                  f"zeitabstand_unter_{RATE_MIN_MINUTEN}_minuten":f"Weniger als {RATE_MIN_MINUTEN} min Abstand"}
    ratestatus = [ratetexte.get(z.get("_rate_status"),"Nicht berechnet") for z in zeilen]
    verlauf_mit_status(1,"02 | Wachstumsrate innerhalb vergleichbarer Kameraansichten",
                       feld,"cm² pro Tag" if rate_cm else "% pro Tag",ratestatus,pixel=True)
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
    scoretexte = {"datei_nicht_lesbar":"Datei nicht lesbar",
                   "bildqualitaet_nicht_ausreichend":"Bildqualität unzureichend",
                   "kameravergleich_nicht_verifiziert":"Kameraansicht nicht vergleichbar",
                   "zu_wenig_gemeinsames_blattgewebe":"Zu wenig gemeinsame Blattfläche",
                   "zu_wenig_bestaetigte_farbteilflaeche":"Zu wenig farblich geprüfte Blattfläche",
                   "lichtvergleich_zu_wenig_blattgewebe":"Zu wenig belichtete Blattfläche",
                   "einzelbilder_keine_gemeinsame_referenz":"Einzelbild ohne Referenz",
                   "aufnahme_vor_referenz":"Aufnahme vor Referenz",
                   "analysefehler":"Analysefehler"}
    def score_status(z):
        if z.get("_ist_referenz"):
            return "Referenzstart"
        if z.get("gesundheit") is not None:
            return "Berechnet · Farbteilfläche" if z.get("_score_modus")=="farbverhaeltnis_teilflaeche" else "Berechnet"
        status = z["gesundheit_status"]
        return scoretexte.get(status,"Lichtvergleich nicht möglich" if status.startswith("licht") else "Nicht berechnet")
    verlauf_mit_status(3,"04 | Relativer Zustandsindex — 100 = nahe an der Referenz",
                       "gesundheit","Index [0–100]",[score_status(z) for z in zeilen],"gesundheit_roh")
    fig, ax = plt.subplots(figsize=(max(8.5,min(16,5+.45*len(zeilen))),4.7))
    ax.set_title("05 | Teilbewertungen je Aufnahme",loc="left",fontweight="semibold")
    labels = ["Farbverteilung","Gelbzunahme","Braun-/Warmzunahme","Sättigungswechsel","Farbtonwechsel"]
    werte = np.array([[np.nan if z.get("score_"+k) is None else z["score_"+k] for z in zeilen]
                      for k in GEWICHTE],dtype=float)
    ax.set_facecolor("#edf0f2")
    heat = ax.imshow(np.ma.masked_invalid(werte),aspect="auto",interpolation="nearest",
                     cmap="viridis",vmin=0,vmax=100)
    ax.set_yticks(range(len(labels)),labels)
    pos = sorted(set(np.linspace(0,len(zeilen)-1,min(14,len(zeilen)),dtype=int)))
    ax.set_xticks(pos,[i+1 for i in pos])
    ax.set_xlabel("Aufnahmenummer (Reihenfolge in ergebnis.csv)")
    if len(zeilen)<=16:
        for i,z in enumerate(zeilen):
            for j in range(len(labels)):
                if np.isfinite(werte[j,i]):
                    ax.text(i,j,f"{werte[j,i]:.1f}",ha="center",va="center",fontsize=8,
                            color="#192620" if werte[j,i]>=58 else "white")
                elif z.get("_ist_referenz"):
                    ax.text(i,j,"Ref.",ha="center",va="center",fontsize=8,color="#517493")
    fig.colorbar(heat,ax=ax,label="Teilscore [0–100]")
    fig.text(.014,.013,"Graue Felder: kein Vergleich. Ref. = Start einer Kameraansicht. Rohfarben stehen in Grafik 03.",
             fontsize=8.5,color=grau)
    fig.tight_layout(rect=(0,.045,1,1))
    fig.savefig(ordner/GRAFIK_DATEIEN[4],dpi=150,facecolor="white")
    plt.close(fig)


@contextlib.contextmanager
def auswertung_sperren(ausgabe):
    """Parallele Analysen verhindern, ohne eine .analyse.lock-Datei zu erzeugen."""
    name = hashlib.sha256(str(ausgabe).casefold().encode("utf-8")).hexdigest()[:24]
    if os.name == 'nt':
        # Windows: benannter System-Mutex, kein Sperrfile im Ausgabeordner.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.ReleaseMutex.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        mutex = kernel.CreateMutexW(None, False, 'Local\\BioBox-Analyse-' + name)
        if not mutex:
            raise OSError('Windows-Sperre konnte nicht erstellt werden.')
        status = kernel.WaitForSingleObject(mutex, 0)
        if status not in (0, 0x80):
            kernel.CloseHandle(mutex)
            if status == 0x102:
                raise ValueError('In diesem Ausgabeordner laeuft bereits eine Analyse.')
            raise OSError('Windows-Sperre konnte nicht aktiviert werden.')
        try:
            yield
        finally:
            kernel.ReleaseMutex(mutex)
            kernel.CloseHandle(mutex)
    else:
        # Andere Betriebssysteme: Sperrfile ausschliesslich im System-Tempordner.
        import fcntl
        with (Path(tempfile.gettempdir()) / ('biobox-analyse-' + name + '.lock')).open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('In diesem Ausgabeordner laeuft bereits eine Analyse.') from error
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def alte_referenzdateien_entfernen(ausgabe):
    """Ausschliesslich frueher erzeugte Referenzdateien nach erfolgreicher Analyse entfernen."""
    for name in ('referenz.npz', '.analyse.lock'):
        try:
            (ausgabe/name).unlink(missing_ok=True)
        except OSError as fehler:
            print(f"Alte Datei konnte nicht entfernt werden: {name} ({fehler}).")
    ordner = ausgabe/'kamera_referenzen'
    if ordner.is_dir() and not ordner.is_symlink():
        try:
            for pfad in ordner.iterdir():
                if pfad.is_file() and re.fullmatch(r'ansicht-[0-9a-f]{64}\.npz',pfad.name):
                    pfad.unlink()
            ordner.rmdir()  # Unbekannte Dateien niemals automatisch loeschen.
        except OSError as fehler:
            print(f"Alter Ordner kamera_referenzen konnte nicht entfernt werden: {fehler}.")


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
            # Referenzen werden waehrend jeder Auswertung im Arbeitsspeicher
            # aufgebaut. Nur die optional gespeicherte Lineal-Kalibrierung bleibt.
            if (ausgabe/'massstab.npz').is_file():
                shutil.copy2(ausgabe/'massstab.npz',fertig/'massstab.npz')
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
    alte_referenzdateien_entfernen(ausgabe)
    print(f'\n{len(rows)} Bilder erneut ausgewertet -> {ausgabe/"ergebnis.csv"}')
    print('Masken, Kontrollbilder, CSV/JSON und alle 5 Grafiken gemeinsam aktualisiert.')
    n_rate = sum(z.get("wachstumsrate_pct_pro_tag") is not None for z in rows)
    n_score = sum(z.get("gesundheit") is not None for z in rows)
    n_pixel = sum(z.get("blattpixel_aenderung_pro_tag") is not None for z in rows)
    print(f"Pixeländerung: {n_pixel}/{len(rows)} | Geprüfte Wachstumsrate: {n_rate}/{len(rows)} | "
          f"Zustandsvergleich: {n_score}/{len(rows)}. Details in Grafik 02 und 04.")
    if manuell is None and not any(z.get('mm_pro_pixel') for z in rows):
        print('Fuer cm2/mm einmal eine bekannte Linealstrecke auf Blatthoehe markieren (--massstab-bild / --referenz-mm).')
    return rows


def _analysieren(pfade, ausgabe, manuell=None, einzelbilder=False, neue_referenz=False):
    ausgabe.mkdir(parents=True, exist_ok=True)
    masken, kontrolle = ausgabe/"masken", ausgabe/"kontrolle"
    masken.mkdir(exist_ok=True)
    kontrolle.mkdir(exist_ok=True)
    lineal = massstab_laden(ausgabe/"massstab.npz")
    # Keine gespeicherten Kamera-Referenzdateien lesen oder anlegen.
    # Die erste geeignete Aufnahme ist die Referenz dieser Auswertung.
    hauptref = None
    ansichten = []
    alte_historie = {}
    ansichtnummern = {}
    lens_hash = hashlib.sha256(KALIBRIERUNG.read_bytes()).hexdigest() if KALIBRIERUNG.exists() else None
    kalibrierung = None
    if KALIBRIERUNG.exists() and not einzelbilder:
        d = json.loads(KALIBRIERUNG.read_text(encoding="utf-8"))
        groesse = d.get("bildgroesse")
        if not isinstance(groesse,(list,tuple)) or len(groesse)!=2 or min(groesse)<=0:
            raise ValueError("Alte Objektivdatei ohne Bildgroesse: mit --kalibrieren erneuern. Vorhandene Ergebnisse bleiben erhalten.")
        kalibrierung = d
    aufnahmezeiten = {p: (None,"unbekannt") if einzelbilder else aufnahmezeit(p) for p in pfade}
    pfade = sorted(pfade,key=lambda p:(aufnahmezeiten[p][0] or datetime.max.replace(tzinfo=timezone.utc),str(p)))
    zeilen, erzeugt = [], set()
    for nummer, pfad in enumerate(pfade, 1):
        zeit, zeitquelle = aufnahmezeiten[pfad]
        pfad = Path(pfad)
        z = {k: None for k in SPALTEN}
        z.update({"bild": pfad.name, "captured_at": iso(zeit), "zeitquelle": zeitquelle,
                  "pipeline_version": ANALYSE_VERSION, "scoring_version": SCORING_VERSION, "auffaelligkeit": "", "gesundheitswarnung": "",
                  "brauchbar": False, "gesundheit_status": "nicht_auswertbar", "gesundheit_kategorie": "keine_daten", "_zeit": zeit})
        zeilen.append(z)
        try:
            original = pfad.read_bytes()
            z["_sha256"] = hashlib.sha256(original).hexdigest()
            bild = cv2.imdecode(np.frombuffer(original,dtype=np.uint8),cv2.IMREAD_COLOR) if original else None
            if bild is None or min(bild.shape[:2]) < 16:
                z["gesundheit_status"] = "datei_nicht_lesbar"
                flags_hinzufuegen(z,"nicht_lesbar")
                continue
            if kalibrierung is not None:
                bild = objektiv_entzerren(bild,kalibrierung)
            arbeit = kleiner(bild)
            ref,prior,referenz_bild,szenendaten = passende_ansicht(
                arbeit,bild.shape[:2],z["_sha256"],ansichten)
            lichtinfo = {"modell":"nicht_vergleichbar","korrigiert":False}
            licht_flags = []
            normal = arbeit
            if ref is not None and prior is not None:
                g,b = gruenheit(arbeit)
                probe = ((g>=8)&(b>=1)).astype(np.uint8)*255
                normal,licht_flags,lichtinfo = licht_abgleichen(arbeit,probe,referenz_bild,prior)
            z["_lichtinfo"] = lichtinfo
            maske = korrektur_laden(ausgabe,z["_sha256"],bild.shape[:2],kalibrierung is not None)
            korrigiert_manuell = maske is not None
            if (maske is None and ref is not None and z["_sha256"]==ref["meta"].get("sha256") and
                    ref.get("maske_original") is not None and ref["maske_original"].shape==bild.shape[:2]):
                maske=ref["maske_original"].copy()
                korrigiert_manuell=ref["meta"].get("mask_source")=="manuell"
            if maske is None:
                maske_klein = segmentieren(normal if normal is not None else arbeit,prior if normal is not None else None,
                                          referenz_bild if normal is not None else None)
                maske = maske_verfeinern(licht_anwenden(bild,lichtinfo) if normal is not None else bild,
                                         maske_klein,referenz_bild)
            maske_klein = cv2.resize(maske,(arbeit.shape[1],arbeit.shape[0]),interpolation=cv2.INTER_NEAREST)
            z["_maskenquelle"] = "manuell" if korrigiert_manuell else "automatisch"
            mm_px, quelle = (massstab(bild,manuell,lineal) if not einzelbilder else
                             (float(manuell),"manuell_blattebene") if manuell else (None,"einzelbilder_ohne_gemeinsamen_massstab"))
            z.update(merkmale(bild,maske,mm_px))
            z["_bildform"] = bild.shape[:2]
            z["blattanteil_im_bild_pct"] = 100*z["pflanzen_pixel"]/maske.size
            # Nie NULL: steht kein Massstab zur Verfuegung, nennt die Spalte
            # den Grund (z. B. nicht_kalibriert) statt einer leeren Zelle.
            z["massstab_quelle"] = quelle
            z["_massstab_status"] = quelle
            z["_objektiv_entzerrt"] = kalibrierung is not None
            z["rauschen"] = rauschen_schaetzen(bild)
            if not zeit:
                flags_hinzufuegen(z, "keine_aufnahmezeit")
            genug = z["pflanzen_pixel"] >= max(80,.0004*maske.size)
            roi_flaeche = cv2.countNonZero(pflanzen_roi(maske.shape)) if ROI_NORMIERT is not None else maske.size
            zu_gross = not korrigiert_manuell and z["pflanzen_pixel"] > .94*roi_flaeche
            if zu_gross:
                flags_hinzufuegen(z,"maske_deckt_fast_den_gesamten_bereich_ab")
            if not genug:
                flags_hinzufuegen(z, "keine_blattmaske")
            # Der Qualitaetsentscheid soll nicht allein durch einen Gain
            # schwanken. Der exportierte Schaerfewert bleibt die Rohmessung.
            pruefbild = normal if normal is not None else arbeit
            grau_pruef = cv2.cvtColor(pruefbild,cv2.COLOR_BGR2GRAY)
            scharf = bool(np.any(maske_klein) and
                          cv2.Laplacian(grau_pruef,cv2.CV_64F)[maske_klein>0].var() >= 8)
            if genug and not scharf:
                flags_hinzufuegen(z, "unscharf")
            belichtet = z.get("ueberbelichtet_pct") is not None and z["ueberbelichtet_pct"] < 35
            if genug and not belichtet:
                flags_hinzufuegen(z, "blattflaeche_ueberbelichtet")
            z["_beschnitten"] = mask_beschnitten(maske)
            if z["_beschnitten"]:
                flags_hinzufuegen(z,"blatt_am_bildrand")
            z["brauchbar"] = bool(genug and not zu_gross and scharf and belichtet and z["rauschen"]<35)
            if z["rauschen"]>=35:
                flags_hinzufuegen(z,"starkes_rauschen")
            if z["brauchbar"] and not einzelbilder:
                if ref is None:
                    ref = ansicht_neu(z,bild,arbeit,maske,maske_klein,lens_hash)
                    ansichten.append(ref)
                    if hauptref is None:
                        hauptref = ref
                    else:
                        flags_hinzufuegen(z,"neue_kameraansicht")
                    szenendaten = {"matrix":IDENTITAET}
                    z["_lichtinfo"] = {"modell":"referenz","korrigiert":False}
                meta = ref["meta"]
                uid = meta["sha256"]
                ansichten[:] = [r for r in ansichten if r is not ref]+[ref]
                ansichtnummer = ansichtnummern.setdefault(uid,len(ansichtnummern)+1)
                z.update(ansicht=ansichtnummer,gesundheit_referenzfoto=meta["bild"],
                         _ansicht_id=uid,_referenz_meta=meta,_arbeitsform=arbeit.shape[:2],
                         _pose=szenendaten["matrix"],_rate_maske=maske_klein,
                         _referenz_geprueft=bool(ref is hauptref and REFERENZ_FREIGEGEBEN))

            if einzelbilder:
                z["gesundheit_status"] = "einzelbilder_keine_gemeinsame_referenz"
            elif not z["brauchbar"]:
                z["gesundheit_status"] = "bildqualitaet_nicht_ausreichend"
            elif (z["_sha256"],z["bild"],z["captured_at"])==(
                    meta.get("sha256"),meta.get("bild"),meta.get("captured_at")):
                # 100 ist der definierte Bezugspunkt, kein gemessener Score.
                z["_ist_referenz"] = True
                z["gesundheit_status"] = "referenzfoto_start_der_ansicht"
            elif z["captured_at"] and meta.get("captured_at") and z["captured_at"]<meta["captured_at"]:
                z["gesundheit_status"] = "aufnahme_vor_referenz"
            else:
                abgleich = licht_abgleichen(arbeit,maske_klein,referenz_bild,prior,chroma_erlaubt=True)
                z["_lichtinfo"] = abgleich[2]
                f,licht_flags = gesundheitsmerkmale(arbeit,maske_klein,referenz_bild,prior,abgleich)
                flags_hinzufuegen(z,*licht_flags)
                if f is None:
                    z["gesundheit_status"] = licht_flags[0] if licht_flags else "lichtvergleich_nicht_moeglich"
                else:
                    affine = szenendaten["matrix"]
                    struktur = (not z["_beschnitten"] and not meta.get("beschnitten",False)
                                and abs(float(np.hypot(*affine[:,0]))-1)<.008
                                and abs(math.degrees(math.atan2(affine[1,0],affine[0,0])))<=1.)
                    bewerten(z,f,ref,struktur_erlaubt=struktur)
            stamm = f"{nummer:05d}_{pfad.stem}"
            png_speichern(masken/(stamm+"_maske.png"),maske)
            z["_ausgabe_stamm"] = stamm
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
    if neue_referenz and not einzelbilder and hauptref is None:
        raise ValueError("Keine geeignete neue Referenz. Bisherige Auswertung bleibt erhalten.")
    refdatum = hauptref["meta"].get("captured_at") if hauptref else None
    referenzzeit = datetime.fromisoformat(refdatum.replace("Z","+00:00")) if refdatum else None
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
            original = Path(pfad).read_bytes()
            if hashlib.sha256(original).hexdigest() != z["_sha256"]:
                raise OSError(f"Eingabebild waehrend der Auswertung geaendert: {pfad}")
            bild = cv2.imdecode(np.frombuffer(original,dtype=np.uint8),cv2.IMREAD_COLOR)
            if kalibrierung is not None:
                bild = objektiv_entzerren(bild,kalibrierung)
            maske = cv2.imdecode(np.fromfile(masken/(z["_ausgabe_stamm"]+"_maske.png"),dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        kontrollbild(bild, maske, z, kontrolle/(z["_ausgabe_stamm"]+"_kontrolle.png"))
    # Nur alte, von diesem Programm erzeugte Vorschauen aufraeumen.
    for ordner, suffix in [(masken, "_maske.png"), (kontrolle, "_kontrolle.png")]:
        for p in ordner.glob("*"+suffix):
            if re.match(r"^\d{5}_", p.name) and p.name[:-len(suffix)] not in erzeugt:
                p.unlink()
    csv_aktuell = ergebnisse_speichern(zeilen,hauptref,ausgabe)
    if not csv_aktuell:
        raise PermissionError("CSV konnte nicht erstellt werden; bisherige Auswertung bleibt erhalten.")
    grafiken(zeilen,ausgabe/"grafiken")
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
                    auswahl = pi_bilder_holen(neue_aufnahme=True)
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
    # 1. Der Pi-Abruf aktualisiert nur den lokalen Bildbestand. Sein Erfolg
    # entscheidet nicht darueber, ob vorhandene Bilder ausgewertet werden.
    if not lokal:
        abruf_ok = True
        try:
            pi_bilder_holen(neue_aufnahme=False)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as fehler:
            abruf_ok = False
            print(f"Fotoabruf fehlgeschlagen: {fehler}", flush=True)
        if args.nur_bild:
            return 0 if abruf_ok else 1
        if not abruf_ok:
            print("Der Pi-Abruf wird uebersprungen; die lokale Auswertung startet trotzdem.", flush=True)

    # 2. Immer frisch aus dem lokalen Ordner lesen, unabhaengig vom Abruf.
    # Dadurch werden auch manuell hinzugefuegte und aeltere Bilder erfasst.
    ziel = Path(lokal).expanduser().resolve() if lokal else BILDER_ORDNER.expanduser().resolve()
    ausgabe = args.ausgabe or ((ziel.parent.parent if ziel.is_file() else ziel.parent)/"auswertung")
    try:
        if ziel.is_file():
            pfade = [ziel]
        elif ziel.is_dir():
            pfade = vorhandene_bilder(ziel)
        elif lokal:
            parser.error(f"Pfad nicht gefunden: {ziel}")
        else:
            pfade = []
    except OSError as fehler:
        print(f"Lokaler Bilderordner konnte nicht eingelesen werden: {fehler}")
        return 1
    if not pfade:
        print(f"Keine Bilder gefunden in: {ziel}. Vorhandene Auswertung bleibt erhalten.")
        return 1
    print(f"Lokale Auswertung: {len(pfade)} Bilder aus {ziel}; alle Ausgaben werden neu berechnet.", flush=True)
    try:
        analysieren(pfade, ausgabe, args.mm_pro_pixel, args.einzelbilder, args.neue_referenz)
    except (OSError, ValueError) as fehler:
        print(f"Analyse abgebrochen: {fehler}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
