"""A-M1 · Image capture: Raspberry Pi photographs, scheduling, and capture timestamps."""

import argparse
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# Camera settings and local storage
PROJECT_DIR = Path(__file__).resolve().parent
ENGLISH_LAYOUT_VERSION = 2
PI_ADDRESS = "biobox@100.65.232.105"
PI_CAPTURE_COMMAND = "/home/biobox/.local/bin/biobox-photo-test --single"
PI_PHOTO_DIR = "/home/biobox/Pictures/BioBox/recent"
PI_SSH_KEY = Path.home() / ".ssh" / "biobox_ed25519"  # Keep the private key outside the repository. Never store the Pi password here.
IMAGES_DIR = PROJECT_DIR / "images"
MAX_CAMERA_PHOTOS = 100
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
CAMERA_CALIBRATION_FILE = PROJECT_DIR / "camera_calibration.json"
LEGACY_CAMERA_CALIBRATION_FILE = PROJECT_DIR / "kamera_kalibrierung.json"
CHECKERBOARD_SIZE = (9, 6)
CHECKER_SQUARE_MM = 25.0


# Hourly capture helper and scheduler for the Raspberry Pi
PI_HOURLY_RUNNER = r'''import fcntl,json,os,re,signal,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
CFG = __CONFIGURATION__
state = Path.home()/'.local/state/BioBox'
state.mkdir(parents=True,exist_ok=True)
os.umask(0o077)
lock = (state/'camera.lock').open('a+b')
try:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(75)  # A capture is already running.
log = state/'hourly-capture.log'
if log.exists() and log.stat().st_size>1048576:
    log.replace(state/'hourly-capture.log.1')
env = os.environ.copy()
env['PATH'] = str(Path.home()/'.local/bin')+':/usr/local/bin:/usr/bin:/bin'
result = {'time':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'ok':False,'file':None}
code = 1
with log.open('a',encoding='utf-8') as stream:
    stream.write('\n'+result['time']+' Capture started\n');stream.flush()
    try:
        proc = subprocess.Popen(CFG['argv'],stdout=subprocess.PIPE,stderr=stream,text=True,
                                env=env,start_new_session=True)
    except OSError as error:
        result['error']='Could not start the capture helper: '+str(error)
        stream.write(json.dumps(result,ensure_ascii=False)+'\n')
        tmp=state/'hourly-capture-status.tmp';tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        tmp.replace(state/'hourly-capture-status.json')
        sys.exit(1)
    try:
        output,_ = proc.communicate(timeout=240)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGTERM)
        try: output,_ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);output,_ = proc.communicate()
        result['error']='Capture timed out after 240 seconds'
    else:
        folders = [line.split(':',1)[1].strip() for line in output.splitlines()
                   if line.startswith('Photos and camera metadata:')]
        if proc.returncode==0 and len(folders)==1:
            folder = Path(folders[0]);photo=folder/'normal.jpg'
            if (folder.parent==Path(CFG['photo_dir']) and
                    re.fullmatch(r'\d{8}T\d{6}Z-[A-Za-z0-9]+',folder.name) and photo.is_file()):
                with photo.open('rb') as f:
                    good=f.read(2)==b'\xff\xd8'
                    if photo.stat().st_size>128:
                        f.seek(-2,os.SEEK_END);good=good and f.read(2)==b'\xff\xd9'
                    else:good=False
                if good and photo.stat().st_size>128:
                    result.update(ok=True,file=str(photo));code=0
        if not result['ok']:result['error']='No unique completed normal.jpg. Exit code: '+str(proc.returncode)
    stream.write(output[-6000:]+'\n'+json.dumps(result,ensure_ascii=False)+'\n')
tmp=state/'hourly-capture-status.tmp';tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
tmp.replace(state/'hourly-capture-status.json')
sys.exit(code)
'''


PI_HOURLY_SETUP = r'''import fcntl,json,os,shlex,shutil,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
CFG = __CONFIGURATION__
RUNNER = __RUNNER__
os.umask(0o077)
state=Path.home()/'.local/state/BioBox';state.mkdir(parents=True,exist_ok=True)
with (state/'schedule.lock').open('a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    if not shutil.which('crontab'):raise RuntimeError('crontab is unavailable. Install cron on the Pi.')
    env=os.environ.copy();env['LC_ALL']='C'
    read=subprocess.run(['crontab','-l'],capture_output=True,text=True,env=env)
    if read.returncode==0:previous=read.stdout
    elif read.returncode==1 and not read.stdout and 'no crontab' in read.stderr.lower():previous=''
    else:raise RuntimeError('Could not safely read the existing crontab: '+read.stderr.strip())
    begin='# BEGIN BIOBOX HOURLY CAPTURE'
    legacy_begin='# BEGIN BIOBOX STUNDENAUFNAHME'
    end='# END BIOBOX HOURLY CAPTURE'
    legacy_end='# END BIOBOX STUNDENAUFNAHME'
    lines=previous.splitlines(keepends=True)
    plain=[];inside=False;seen=False
    for line in lines:
        if line.strip() in (begin,legacy_begin):
            if inside or seen:raise RuntimeError('Duplicate BioBox schedules. Review the existing crontab.')
            inside=True;seen=True
        elif line.strip() in (end,legacy_end):
            if not inside:raise RuntimeError('Incomplete BioBox schedule.')
            inside=False
        elif not inside:plain.append(line)
    if inside:raise RuntimeError('Incomplete BioBox schedule.')
    service=subprocess.run(['systemctl','is-active','cron'],capture_output=True,text=True)
    cron_ok=service.returncode==0
    boot=subprocess.run(['systemctl','is-enabled','cron'],capture_output=True,text=True)
    cron_boot=boot.returncode==0
    wrapper=Path.home()/'.local/bin/biobox-hourly-capture.py'
    action=CFG['operation']
    if action=='status':
        last=next((path for path in (state/'hourly-capture-status.json', state/'stundenaufnahme-status.json') if path.exists()), state/'hourly-capture-status.json')
        capture=json.loads(last.read_text()) if last.exists() else None
        if isinstance(capture,dict) and 'time' not in capture:
            capture={'time':capture.get('zeit'),'file':capture.get('datei'),'error':capture.get('fehler'),'ok':capture.get('ok')}
        print(json.dumps({'active':seen and wrapper.is_file() and cron_ok,'installed':seen,
                          'cron_active':cron_ok,'cron_enabled_at_boot':cron_boot,
                          'last_capture':capture},ensure_ascii=False))
    else:
        if action=='enable':
            if not cron_ok:raise RuntimeError('The cron service is not running. On the Pi: sudo systemctl enable --now cron')
            if not cron_boot:raise RuntimeError('cron does not start at boot. On the Pi: sudo systemctl enable --now cron')
            if not Path(CFG['argv'][0]).is_file():raise RuntimeError('Missing capture helper: '+CFG['argv'][0])
            wrapper.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile('w',dir=wrapper.parent,prefix='.biobox-capture-',suffix='.py',delete=False) as f:
                f.write(RUNNER);candidate=Path(f.name)
            try:
                test=subprocess.run([sys.executable,str(candidate)],timeout=270)
                if test.returncode!=0:raise RuntimeError('The test photo failed or the camera is busy. The schedule was unchanged. Use --schedule-status to check the last attempt.')
                new_runner=RUNNER
            finally:candidate.unlink(missing_ok=True)
            command=shlex.quote(sys.executable)+' '+shlex.quote(str(wrapper))+' >/dev/null 2>&1'
            command=command.replace('%',r'\%')
            clean=''.join(plain)
            updated=clean+('' if not clean or clean.endswith('\n') else '\n')+begin+'\n0 * * * * '+command+'\n'+end+'\n'
        elif action=='disable':
            updated=''.join(plain);new_runner=None
        else:raise RuntimeError('Unknown capture schedule action')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=state/('crontab-backup-'+stamp+'.txt');backup.write_text(previous,encoding='utf-8')
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
        print(json.dumps({'active':action=='enable','test_capture':action=='enable','schedule':'0 * * * *','backup':str(backup)},ensure_ascii=False))
'''


def jpeg_is_readable(file_path):
    "Treat only complete, readable JPEGs as downloaded."
    import cv2

    try:
        with Path(file_path).open("rb") as file_handle:
            if file_handle.read(2) != b"\xff\xd8":
                return False
        image = cv2.imread(str(file_path))
        return image is not None and min(image.shape[:2]) >= 3
    except OSError:
        return False


def ssh_command_options():
    "Use the SSH agent for the key and keep sync non-interactive."
    if not PI_SSH_KEY.is_file():
        raise RuntimeError(f"SSH key not found: {PI_SSH_KEY}. Check the configured key path.")
    return ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-i", str(PI_SSH_KEY), "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"]


def sync_camera_photos(take_new_photo=False):
    """Sync completed hourly photos or request a new capture explicitly. Sort by the UTC capture time in the session name. Keep previously imported camera photos when the Pi moves its own copies. Prune older imports only after all selected JPEGs download successfully."""
    if shutil.which("ssh") is None:
        raise RuntimeError("OpenSSH is unavailable. Install or enable the Windows OpenSSH Client.")
    if not isinstance(MAX_CAMERA_PHOTOS, int) or MAX_CAMERA_PHOTOS < 1:
        raise RuntimeError("MAX_CAMERA_PHOTOS must be at least one.")
    connection = ssh_command_options()
    # The helper publishes completed sessions only.
    # The strict session pattern rejects temporary .pending directories.
    list_command = (f"find {shlex.quote(PI_PHOTO_DIR)} -mindepth 2 -maxdepth 2 "
                 "-type f -name normal.jpg -printf 'BIOBOX_PHOTO:%h\\n'")
    print(("Requesting a new photo and listing completed captures" if take_new_photo else "Listing completed captures")+
          f" from {PI_ADDRESS} over SSH.",flush=True)
    # Use the same camera lock as the hourly job on the Pi.
    capture = ('mkdir -p "$HOME/.local/state/BioBox" && '
               'flock -w 30 "$HOME/.local/state/BioBox/camera.lock" '+PI_CAPTURE_COMMAND)
    command_args = capture+" && "+list_command if take_new_photo else list_command
    observation = subprocess.run(
        ["ssh", *connection, PI_ADDRESS, command_args],
        check=True, stdout=subprocess.PIPE, text=True, timeout=180)

    pattern = re.escape(PI_PHOTO_DIR) + r"/(\d{8}T\d{6}Z-[A-Za-z0-9]+)"
    remote, new_sessions = set(), []
    for row in observation.stdout.splitlines():
        row = row.strip()
        if row.startswith("Photos and camera metadata:"):
            match_result = re.fullmatch(pattern, row.split(":", 1)[1].strip())
            if match_result and is_camera_photo(f"biobox_{match_result[1]}.jpg"):
                new_sessions.append(match_result[1])
        elif row.startswith("BIOBOX_PHOTO:"):
            match_result = re.fullmatch(pattern, row[len("BIOBOX_PHOTO:"):])
            if match_result and is_camera_photo(f"biobox_{match_result[1]}.jpg"):
                remote.add(match_result[1])
    if take_new_photo and (len(new_sessions) != 1 or new_sessions[0] not in remote):
        raise RuntimeError("The Pi did not report a unique new photo session.")

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    local_path = {p.name[len("biobox_"):-4]: p for p in IMAGES_DIR.iterdir()
             if p.is_file() and not p.is_symlink() and is_camera_photo(p)}
    existing = {s for s, p in local_path.items() if jpeg_is_readable(p)}
    selection = sorted(remote | existing)[-MAX_CAMERA_PHOTOS:]
    missing = [s for s in selection if s not in existing]
    print(f"Pi: {len(remote)} completed captures; keeping {len(selection)}; "
          f"to download: {len(missing)}")

    if missing:
        # Transfer all missing JPEGs in one further SSH connection.
        # This avoids reconnecting for each photo.
        filenames = {f"{s}/normal.jpg": f"biobox_{s}.jpg" for s in missing}
        command_args = (f"tar -cf - -C {shlex.quote(PI_PHOTO_DIR)} -- "
                  + " ".join(shlex.quote(n) for n in filenames))
        with tempfile.TemporaryDirectory(dir=IMAGES_DIR, prefix=".biobox-download-") as tmp:
            tmp = Path(tmp)
            package = tmp / "download.tar"
            print("Downloading camera JPEGs over SSH.", flush=True)
            with package.open("wb") as stream:
                subprocess.run(["ssh", *connection, PI_ADDRESS, command_args],
                               check=True, stdout=stream, timeout=600)
            retained_count = set()
            with tarfile.open(package, "r:") as tar_archive:
                for entry in tar_archive:
                    if (entry.name not in filenames or not entry.isfile()
                            or entry.name in retained_count):
                        raise RuntimeError("The photo transfer contained an unexpected item.")
                    target = tmp / filenames[entry.name]
                    with tar_archive.extractfile(entry) as source, target.open("wb") as file_handle:
                        shutil.copyfileobj(source, file_handle)
                    if not jpeg_is_readable(target):
                        raise RuntimeError(f"Could not read JPEG: {entry.name}")
                    retained_count.add(entry.name)
            if retained_count != set(filenames):
                raise RuntimeError("The photo transfer was incomplete. No older photos were removed.")
            for name in filenames.values():
                target = IMAGES_DIR / name
                if target.is_symlink():
                    raise RuntimeError(f"The destination is a symbolic link: {target}")
            for name in filenames.values():
                (tmp / name).replace(IMAGES_DIR / name)

    retained = {f"biobox_{s}.jpg" for s in selection}
    removed = 0
    for file_path in local_path.values():
        if file_path.name not in retained:
            file_path.unlink()
            removed += 1
    print(f"{len(missing)} JPEGs downloaded; removed {removed} older local camera photos.")
    print(f"{len(selection)} camera photos in: {IMAGES_DIR}")
    return [IMAGES_DIR / f"biobox_{s}.jpg" for s in selection]


def find_images(directory_path):
    "List supported image files. Analysis checks readability and capture time."
    directory_path = Path(directory_path)
    if not directory_path.is_dir():
        return []
    return sorted(p for p in directory_path.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def is_camera_photo(file_path):
    "Recognise camera imports separately from manually added dataset photos."
    match_result = re.fullmatch(r"biobox_(\d{8}T\d{6}Z)-[A-Za-z0-9]+\.jpg",
                           os.path.basename(file_path))
    if match_result is None:
        return False
    try:
        datetime.strptime(match_result[1], "%Y%m%dT%H%M%SZ")
        return True
    except ValueError:
        return False


def manage_hourly_capture(operation):
    "Configure or inspect the BioBox schedule while keeping unrelated jobs."
    cfg={'operation':operation,'argv':shlex.split(PI_CAPTURE_COMMAND),'photo_dir':PI_PHOTO_DIR}
    if not cfg['argv'] or not cfg['argv'][0].startswith('/'):
        raise ValueError('PI_CAPTURE_COMMAND must start with the absolute path to the Pi capture helper.')
    runner=PI_HOURLY_RUNNER.replace('__CONFIGURATION__',repr(cfg))
    script=PI_HOURLY_SETUP.replace('__CONFIGURATION__',repr(cfg)).replace('__RUNNER__',repr(runner))
    if shutil.which('ssh') is None:raise ValueError('The Windows OpenSSH Client is unavailable.')
    print(f'Pi hourly capture: {operation} over SSH.',flush=True)
    result=subprocess.run(['ssh',*ssh_command_options(),PI_ADDRESS,'python3 -'],
                          input=script,text=True,stdout=subprocess.PIPE,check=True,timeout=330)
    data=json.loads(result.stdout)
    if operation=='status':
        print('Hourly capture is active.' if data['active'] else 'Hourly capture is inactive.')
        if not data.get('cron_enabled_at_boot'):print('cron is not set to start when the Pi boots.')
        last=data.get('last_capture')
        if last:print('Last attempt:',last.get('time'), '|',last.get('file') if last.get('ok') else last.get('error'))
        else:print('No capture attempt has been logged.')
    elif operation=='enable':
        print('The test photo succeeded. The Pi now takes a photo on the hour, even when the Windows PC is off.')
        print('Use python image_capture.py to retrieve completed photos.')
    else:print('The BioBox hourly schedule is disabled. Saved photos were kept.')
    return data


def calibrate_lens(directory_path):
    "Estimate lens distortion from checkerboard photos."
    import cv2
    import numpy as np

    paths = sorted(os.path.join(directory_path, n) for n in os.listdir(directory_path)
                   if n.lower().endswith(IMAGE_EXTENSIONS))
    if len(paths) < 5:
        print(f"Lens calibration needs at least five checkerboard photos. Found {len(paths)}")
        return

    pattern = np.zeros((CHECKERBOARD_SIZE[0] * CHECKERBOARD_SIZE[1], 3), np.float32)
    pattern[:, :2] = np.mgrid[0:CHECKERBOARD_SIZE[0], 0:CHECKERBOARD_SIZE[1]].T.reshape(-1, 2)
    pattern *= CHECKER_SQUARE_MM

    world_points, image_points, size = [], [], None
    for file_path in paths:
        grey = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
        if grey is None:
            continue
        if size is None:
            size = grey.shape[::-1]
        elif size != grey.shape[::-1]:
            print(f"   {os.path.basename(file_path)}: skipped because the image dimensions differ")
            continue
        found, corners = cv2.findChessboardCorners(grey, CHECKERBOARD_SIZE, None)
        print(f"   {os.path.basename(file_path):34s} "
              f"{'Checkerboard detected' if found else 'no checkerboard detected'}")
        if found:
            corners = cv2.cornerSubPix(
                grey, corners, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
            world_points.append(pattern)
            image_points.append(corners)

    if len(world_points) < 5:
        print(f"\nOnly {len(world_points)} usable photos; calibration cancelled.")
        return

    error, matrix, distortion, _, _ = cv2.calibrateCamera(
        world_points, image_points, size, None, None)

    with tempfile.TemporaryDirectory(dir=CAMERA_CALIBRATION_FILE.parent) as work:
        profile = Path(work) / CAMERA_CALIBRATION_FILE.name
        profile.write_text(json.dumps({"camera_matrix": matrix.tolist(), "image_size": list(size),
                           "distortion_coefficients": distortion.tolist(), "images": len(world_points),
                           "reprojection_error_px": round(float(error), 4)}, indent=2) + "\n", encoding="utf-8")
        profile.replace(CAMERA_CALIBRATION_FILE)

    print(f"\n{len(world_points)} calibration photos used")
    print(f"Reprojection error: {error:.3f} px (below 1.0 is good)")
    print(f"Saved to {CAMERA_CALIBRATION_FILE}")


def calibration_file():
    """Prefer the English lens profile and read the legacy profile when necessary."""
    return (LEGACY_CAMERA_CALIBRATION_FILE if not CAMERA_CALIBRATION_FILE.exists()
            and LEGACY_CAMERA_CALIBRATION_FILE.is_file() else CAMERA_CALIBRATION_FILE)


def lens_image_size(data):
    """Read dimensions from either supported lens profile format."""
    return data.get("image_size", data.get("bildgroesse"))


def undistort_image(image, data):
    "Adjust the camera matrix for a different resolution of the same field of view."
    import cv2
    import numpy as np

    original = lens_image_size(data)
    if not isinstance(original,(list,tuple)) or len(original)!=2 or min(original)<=0:
        raise ValueError("The lens profile has no image dimensions. Run --calibrate to renew it.")
    w,h = image.shape[1],image.shape[0]
    if abs((w/h)/(original[0]/original[1])-1) > .002:
        raise ValueError("The calibration profile and photo have different fields of view or aspect ratios.")
    matrix = np.asarray(data.get("camera_matrix", data.get("kamera_matrix")),dtype=float).copy()
    distortion = np.asarray(data.get("distortion_coefficients", data.get("verzeichnung")),dtype=float)
    if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or not np.isfinite(distortion).all():
        raise ValueError("Invalid lens calibration.")
    matrix[0,:]*=w/original[0];matrix[1,:]*=h/original[1]
    return cv2.undistort(image,matrix,distortion)


def time_from_filename(name):
    "Read only explicit timestamps. The file date is not the capture time."
    pattern = [(r"(\d{8}T\d{6}Z)", "%Y%m%dT%H%M%SZ"),
              (r"(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})", "%Y_%m_%d_%H_%M_%S"),
              (r"(\d{4}-\d{2}-\d{2}[T_ ]\d{2}[-:]\d{2}[-:]\d{2})", None)]
    # Check for an explicit ISO offset before parsing the old UTC pattern.
    offset = re.search(r"(\d{4}-\d{2}-\d{2})[T_ ](\d{2})[-:](\d{2})[-:](\d{2})([+-]\d{2}:?\d{2})(?!\d)",name)
    if offset:
        date_value,h,m,seconds,zone = offset.groups()
        try:
            return datetime.fromisoformat(f"{date_value}T{h}:{m}:{seconds}{zone}").astimezone(timezone.utc)
        except ValueError:
            return None
    for regex, fmt in pattern:
        match_result = re.search(regex, name)
        if match_result:
            try:
                if fmt:
                    return datetime.strptime(match_result[1], fmt).replace(tzinfo=timezone.utc)
                text = match_result[1].replace("_", "T").replace(" ", "T")
                return datetime.fromisoformat(text[:11] + text[11:].replace("-", ":")).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None


def capture_time(file_path):
    "Read UTC from the filename, or EXIF when it contains an offset."
    timestamp = time_from_filename(Path(file_path).name)
    if timestamp is not None:
        return timestamp,"name"
    try:
        from PIL import Image
        with Image.open(file_path) as image:
            exif = image.getexif()
            data = exif.get_ifd(34665)
        date_value = data.get(36867) or exif.get(36867)
        offset = data.get(36881) or exif.get(36881)
        if isinstance(date_value,str) and isinstance(offset,str) and re.fullmatch(r"[+-](?:0[0-9]|1[0-4]):[0-5][0-9]",offset):
            timestamp = datetime.strptime(date_value.strip()+" "+offset,"%Y:%m:%d %H:%M:%S %z")
            return timestamp.astimezone(timezone.utc),"exif_with_offset"
    except (ImportError,OSError,ValueError,TypeError,OverflowError,SyntaxError):
        pass
    return None,"unknown"


def load_capture_times(file_handle):
    "Load actual capture times by filename, without using file modification time."
    timestamps = {}
    with Path(file_handle).expanduser().open(encoding="utf-8-sig", newline="") as f:
        header = f.readline()
        f.seek(0)
        reader = csv.DictReader(f,delimiter=";" if ";" in header else ",")
        if reader.fieldnames not in (["file_name", "captured_at"], ["bild", "captured_at"]):
            raise ValueError("The capture-time CSV must contain file_name and captured_at.")
        for nr,row in enumerate(reader,2):
            name = (row.get("file_name") or row.get("bild") or "").strip()
            text = (row.get("captured_at") or "").strip()
            timestamp = parse_saved_time(text)
            if None in row or not name or "/" in name or "\\" in name or not timestamp or name in timestamps:
                raise ValueError(f"Timestamp file, row {nr}: expected a unique filename and an ISO timestamp with a time zone.")
            timestamps[name] = timestamp
    return timestamps


def parse_saved_time(value):
    "Use only saved capture times that include a time zone."
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return timestamp.astimezone(timezone.utc) if timestamp.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def iso(timestamp):
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if timestamp else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    plan = parser.add_mutually_exclusive_group()
    plan.add_argument("--schedule-hourly", dest="operation",
                      action="store_const", const="enable", help="Test the camera and enable hourly captures on the Pi")
    plan.add_argument("--schedule-status", dest="operation",
                      action="store_const", const="status", help="Show the hourly capture status")
    plan.add_argument("--disable-schedule", dest="operation",
                      action="store_const", const="disable", help="Disable the BioBox capture schedule")
    plan.add_argument("--calibrate", dest="calibration_directory", metavar="DIRECTORY",
                      help="Build a lens profile from checkerboard photos")
    plan.add_argument("--sync", action="store_true", help="Fetch completed photos from the Pi (default)")
    args = parser.parse_args(argv)
    try:
        if args.operation:
            manage_hourly_capture(args.operation)
        elif args.calibration_directory:
            calibrate_lens(args.calibration_directory)
        else:
            sync_camera_photos()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            message = f"SSH failed (exit code {error.returncode}). See the SSH message above."
        elif isinstance(error, subprocess.TimeoutExpired):
            message = "The Raspberry Pi did not respond before the timeout."
        else:
            message = str(error)
        print(f"Pi operation did not complete: {message}" if not args.calibration_directory
              else f"Lens calibration did not complete: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
