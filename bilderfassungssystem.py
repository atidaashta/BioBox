"""A-M1 · Bilderfassungssystem: Kamera, Pi-Abgleich und Aufnahmezeiten."""

import argparse
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# Kamera und lokale Ablage
PROJEKT_ORDNER = Path(__file__).resolve().parent
PI_ADRESSE = "biobox@100.65.232.105"
PI_AUFNAHME = "/home/biobox/.local/bin/biobox-photo-test --single"
PI_FOTO_ORDNER = "/home/biobox/Pictures/BioBox/recent"
PI_SSH_KEY = Path.home() / ".ssh" / "biobox_ed25519"  # Verschluesselter privater SSH-Schluessel, nie das Pi-Passwort.
BILDER_ORDNER = Path.home() / "Downloads" / "Diploma" / "bilder"
MAX_KAMERA_BILDER = 100
ENDUNGEN = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
KALIBRIERUNG = Path(__file__).resolve().with_name("kamera_kalibrierung.json")
SCHACHBRETT = (9, 6)
FELD_MM = 25.0


# Stündlicher Aufnahmehelfer für den Raspberry Pi
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


def jpeg_lesbar(pfad):
    """Nur vollstaendige, lesbare JPEGs als bereits heruntergeladen behandeln."""
    import cv2

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
    import cv2
    import numpy as np

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
    import cv2
    import numpy as np

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


def zeit_aus_name(name):
    """Nur explizite Aufnahmezeiten. Dateidatum ist KEINE Aufnahmezeit."""
    muster = [(r"(\d{8}T\d{6}Z)", "%Y%m%dT%H%M%SZ"),
              (r"(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})", "%Y_%m_%d_%H_%M_%S"),
              (r"(\d{4}-\d{2}-\d{2}[T_ ]\d{2}[-:]\d{2}[-:]\d{2})", None)]
    # Dateinamen mit explizitem ISO-Offset vor dem alten UTC-Muster lesen.
    offset = re.search(r"(\d{4}-\d{2}-\d{2})[T_ ](\d{2})[-:](\d{2})[-:](\d{2})([+-]\d{2}:?\d{2})(?!\d)",name)
    if offset:
        datum,h,m,sek,zone = offset.groups()
        try:
            return datetime.fromisoformat(f"{datum}T{h}:{m}:{sek}{zone}").astimezone(timezone.utc)
        except ValueError:
            return None
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


def aufnahmezeiten_laden(datei):
    """Echte Aufnahmezeiten je Dateiname; kein Ersatz durch das Änderungsdatum."""
    zeiten = {}
    with Path(datei).expanduser().open(encoding="utf-8-sig", newline="") as f:
        kopf = f.readline()
        f.seek(0)
        reader = csv.DictReader(f,delimiter=";" if ";" in kopf else ",")
        if reader.fieldnames != ["bild","captured_at"]:
            raise ValueError("Zeitdatei: Spalten bild;captured_at erwartet.")
        for nr,row in enumerate(reader,2):
            name = (row.get("bild") or "").strip()
            text = (row.get("captured_at") or "").strip()
            zeit = historienzeit(text)
            if None in row or not name or "/" in name or "\\" in name or not zeit or name in zeiten:
                raise ValueError(f"Zeitdatei, Zeile {nr}: eindeutiger Dateiname und ISO-Zeit mit Zeitzone erforderlich.")
            zeiten[name] = zeit
    return zeiten


def historienzeit(wert):
    """Nur gespeicherte Aufnahmezeiten mit Zeitzone als Zeitachse verwenden."""
    if not wert:
        return None
    try:
        zeit = datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
        return zeit.astimezone(timezone.utc) if zeit.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def iso(zeit):
    return zeit.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if zeit else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    plan = parser.add_mutually_exclusive_group()
    for aktion in ("einrichten", "status", "ausschalten"):
        plan.add_argument(f"--stundenaufnahme-{aktion}", dest="aktion",
                          action="store_const", const=aktion)
    plan.add_argument("--kalibrieren", metavar="ORDNER", help="Objektivprofil aus Schachbrettbildern erstellen")
    plan.add_argument("--abholen", action="store_true", help="Gespeicherte Fotos vom Pi holen (Standard)")
    args = parser.parse_args(argv)
    try:
        if args.aktion:
            stundenaufnahme(args.aktion)
        elif args.kalibrieren:
            kalibrieren(args.kalibrieren)
        else:
            pi_bilder_holen()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, tarfile.TarError) as fehler:
        print(f"Bilderfassung nicht abgeschlossen: {fehler}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
