"""A-M2 · Computer-Vision-Pipeline: Masken, Messwerte, Exporte und Diagramme."""

import argparse
import contextlib
import copy
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


# Dateien für die Browseransichten
TWIN_JSON_DATEI = "digital_twin.json"
GESUND_JSON_DATEI = "gesundheitssystem.json"
GRAFIK_JSON_DATEI = "grafiken.json"
GRAFIK_DATEIEN = ("01_wachstum.png", "02_wachstumsrate.png", "03_farbverlauf.png",
                 "04_gesundheit.png", "05_teilscores.png")
WEB_ANSICHTEN = {"digital twin": "digital_twin_3d", "gesundheitssystem": "gesundheitssystem",
                 "grafiken": "grafiken"}
WEB_TYPEN = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
             "js": "text/javascript; charset=utf-8", "json": "application/json",
             "png": "image/png"}


def viewer_ordner(ausgabe):
    """Im Standardprojekt beide Datenordner neben der Auswertung ablegen."""
    ausgabe = Path(ausgabe)
    basis = ausgabe.parent if ausgabe.name.casefold() == "auswertung" else ausgabe
    return basis/"digital twin", basis/"gesundheitssystem"


def grafik_ordner(ausgabe):
    return viewer_ordner(ausgabe)[0].parent/"grafiken"


def ansichten_bereitstellen(ausgabe, startdatei):
    """Interner, auf diesen Rechner begrenzter Server für Browseransichten."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    twin, gesund = viewer_ordner(ausgabe)
    grafiken = grafik_ordner(ausgabe)
    wege = {f"/{ordner}/{stamm}.{end}": (Path(__file__).resolve().parent/ordner/f"{stamm}.{end}", WEB_TYPEN[end])
            for ordner, stamm in WEB_ANSICHTEN.items() for end in ("html", "css", "js")}
    for ordner, name in ((twin, TWIN_JSON_DATEI), (gesund, GESUND_JSON_DATEI),
                         (grafiken, GRAFIK_JSON_DATEI), *((grafiken, name) for name in GRAFIK_DATEIEN)):
        wege[f"/{ordner.name}/{name}"] = (ordner/name, WEB_TYPEN[name.rsplit(".", 1)[1]])
    letzter_zugriff = time.monotonic()

    class Ansicht(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self._liefern(kopf=False)

        def do_HEAD(self):
            self._liefern(kopf=True)

        def _liefern(self, kopf):
            nonlocal letzter_zugriff
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(403)
                return
            try:
                pfad = unquote(urlsplit(self.path).path)
            except ValueError:
                self.send_error(400)
                return
            if pfad not in wege:
                self.send_error(404)
                return
            letzter_zugriff = time.monotonic()
            datei, typ = wege[pfad]
            try:
                daten = datei.read_bytes()
            except OSError:
                self.send_error(404)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", typ)
                self.send_header("Content-Length", str(len(daten)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not kopf:
                    self.wfile.write(daten)
            except (BrokenPipeError, ConnectionResetError):
                pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Ansicht) as server:
        server.timeout = 1
        temp = startdatei.with_suffix(".tmp")
        temp.write_text(str(server.server_port), encoding="ascii")
        temp.replace(startdatei)
        while time.monotonic() - letzter_zugriff < 15 * 60:
            server.handle_request()


def browseransicht_oeffnen(ausgabe, ordner, titel):
    stamm = WEB_ANSICHTEN[ordner]
    quelle = PROJEKT_ORDNER/ordner
    dateien = [f"{stamm}.{end}" for end in ("html", "css", "js")]
    fehlend = [name for name in dateien if not (quelle/name).is_file()]
    if fehlend:
        raise FileNotFoundError(f"Bitte {', '.join(fehlend)} in {quelle} ablegen.")
    optionen = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                else {"start_new_session": True})
    with tempfile.TemporaryDirectory(prefix="biobox-browser-") as tmp:
        bereit = Path(tmp)/"port"
        prozess = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--_ansichten-server",
                                   str(Path(ausgabe).expanduser().resolve()), str(bereit)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **optionen)
        frist = time.monotonic() + 5
        while not bereit.is_file() and prozess.poll() is None and time.monotonic() < frist:
            time.sleep(.04)
        if not bereit.is_file():
            if prozess.poll() is None:
                prozess.terminate()
                try:
                    prozess.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    prozess.kill()
                    prozess.wait()
            raise OSError("Die lokale Browseransicht konnte nicht gestartet werden.")
        port = int(bereit.read_text(encoding="ascii"))
    adresse = f"http://127.0.0.1:{port}/{quote(ordner)}/{stamm}.html"
    print(f"{titel}: {adresse}")
    if not webbrowser.open(adresse):
        print("Diese Adresse im Browser öffnen.")


# Der Browserprozess benötigt nur die Standardbibliothek.
if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--_ansichten-server":
    ansichten_bereitstellen(Path(sys.argv[2]), Path(sys.argv[3]))
    raise SystemExit(0)

import cv2
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from bilderfassungssystem import (
    BILDER_ORDNER, KALIBRIERUNG, PROJEKT_ORDNER, aufnahmezeit, aufnahmezeiten_laden,
    historienzeit, iso, ist_pi_bild, objektiv_entzerren, vorhandene_bilder,
)

# Direkte Aufrufe und Importe verwenden dasselbe Modul für den Analyselauf.
if __name__ == "__main__":
    sys.modules["computer_vision_pipeline"] = sys.modules[__name__]


# Messreihe, Blattmaske und Maßstab
DEVICE_ID = None  # Erst Edonas echte Datenbank-ID eintragen, keine ID erfinden.
MESSREIHE = "pflanze-01"
MM_PRO_PIXEL_MANUELL = None  # Nur verifizierter Massstab IN DER BLATTEBENE.
KAMERA_HOEHE_MM = None
BLATT_HOEHE_MM = None
MARKER_HOEHE_MM = 0.0
MARKER_MM = 40.0
ROI_NORMIERT = None  # Optional: (links, oben, rechts, unten), Werte 0..1.
ARBEITSBREITE = 960
CHROMA_MIN = 4            # a*-Mindestabstand von Grau; darunter keine Pflanze
RATE_MIN_MINUTEN = 30    # Kurzer Vergleich; hohe Schwankung moeglich
RATE_STABIL_STUNDEN = 12  # Wenn verfuegbar, laengeren Abstand bevorzugen
ANALYSE_VERSION = "4.13.0"
CSV_NICHT_VERFUEGBAR = "Nicht verfügbar"
ALTE_TWIN_GRAFIK = "06_digital_twin.png"  # Nur bei der Übernahme alter Ausgaben entfernen.
CSV_DEZIMALKOMMA = True

# Änderungen an einem Meilenstein ändern den Verarbeitungsstand in ergebnis.json.
PIPELINE_SHA256 = hashlib.sha256(b"\0".join(
    Path(__file__).with_name(name).read_bytes()
    for name in ("bilderfassungssystem.py", "computer_vision_pipeline.py",
                 "gesundheitsbewertung.py", "digital_twin.py")
)).hexdigest()


# Felder für CSV und JSON
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
    "durchmesser_px", "sichtbare_blaetter", "blattzaehlung_quelle",
]
RUNDUNG = {"durchmesser_px": 1, "stunden_seit_start": 4, "blattanteil_im_bild_pct": 3, "blattpixel_aenderung_pro_tag": 1, "blattflaeche_cm2": 2, "durchmesser_mm": 1,
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


# Bildverarbeitung
def rauschen_schaetzen(bild):
    """Bildrauschen nach Immerkaer (1996). Reagiert kaum auf Kanten und
    Blattstrukturen, misst also tatsaechlich Sensorrauschen."""
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY).astype(np.float64)
    kern = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float64)
    h, w = grau.shape
    summe = np.abs(cv2.filter2D(grau, -1, kern)[1:-1, 1:-1]).sum()
    return float(np.sqrt(np.pi / 2) * summe / (6 * (w - 2) * (h - 2)))


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
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    pixel = cv2.countNonZero(maske)
    if pixel == 0:
        # Die Bildhelligkeit ist eine Messung des ganzen Fotos und braucht keine Maske.
        return {"pflanzen_pixel": 0, "mm_pro_pixel": mm_px, "bildhelligkeit": float(grau.mean())}
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
    farbe = farbmerkmale(bild, maske)
    w = {k: v for k, v in farbe.items() if not k.startswith("_")}
    w.update({"pflanzen_pixel": pixel, "durchmesser_px": durchmesser_px,
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
    from gesundheitsbewertung import SCORING_VERSION

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
    from gesundheitsbewertung import SCORING_VERSION

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


def wachstumszeitreihe(zeilen, referenzzeit=None):
    """Zeitachse und Flächenänderungen je Aufnahme bestimmen."""
    auswahl_start = min((z["_zeit"] for z in zeilen if z["_zeit"]),default=None)
    start = referenzzeit or auswahl_start
    basis, pixelbasis = {}, []
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


# Ergebnishistorie und Export
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


def historienwert(feld, wert):
    """CSV-Dezimalkomma lesen, ohne gemessene Nullen als fehlend zu behandeln."""
    if wert is None or (isinstance(wert, str) and wert.strip().casefold() in
                         ("null", "none", "nan", "—", CSV_NICHT_VERFUEGBAR.casefold())):
        return None
    if feld in ("auffaelligkeit","gesundheitswarnung") and wert=="Keine":
        return ""
    if feld == "brauchbar":
        if isinstance(wert, bool):
            return wert
        text = str(wert).strip().lower()
        if text in ("true", "1"):
            return True
        if text in ("false", "0"):
            return False
        if text == "":
            return None
        raise ValueError(f"Ungueltiger boolescher Historienwert: {wert!r}")
    if feld in RUNDUNG or feld in ("pflanzen_pixel", "ansicht", "sichtbare_blaetter"):
        if wert == "":
            return None
        if isinstance(wert, bool):
            raise ValueError(f"Ungueltiger Zahlenwert in {feld}: {wert!r}")
        zahl = float(str(wert).strip().replace(",", "."))
        if not math.isfinite(zahl):
            raise ValueError(f"Nicht endlicher Historienwert in {feld}")
        if feld in ("pflanzen_pixel", "ansicht", "sichtbare_blaetter"):
            if not zahl.is_integer():
                raise ValueError(f"Keine Ganzzahl in {feld}: {wert!r}")
            return int(zahl)
        return zahl
    if not isinstance(wert, str):
        raise ValueError(f"Ungueltiger Textwert in {feld}: {wert!r}")
    return None if feld == "captured_at" and not wert else wert


def historienzeile(satz):
    """Gespeicherten API-Datensatz fuer CSV und Diagramme zuruecklesen."""
    if not isinstance(satz, dict) or not isinstance(satz.get("image"), dict):
        raise ValueError("Ungueltiger Bilddatensatz in ergebnis.json")
    for bereich in ("image_measurements", "health_assessment", "analysis"):
        if bereich in satz and not isinstance(satz[bereich], dict):
            raise ValueError(f"Ungueltiger Bereich {bereich} in ergebnis.json")
    z = {feld: None for feld in SPALTEN}
    bild, info = satz["image"], satz.get("analysis", {})
    z.update(bild=bild.get("file_name"), captured_at=bild.get("captured_at"),
             zeitquelle=info.get("capture_time_source"), stunden_seit_start=info.get("hours_since_start"),
             ansicht=info.get("view_number"), gesundheit_referenzfoto=info.get("reference_file"),
             wachstum_vergleichsfoto=info.get("growth_reference_file"),
             wachstum_abstand_stunden=info.get("growth_interval_hours"))
    for bereich, zuordnung in (("image_measurements", API_MESSFELDER), ("health_assessment", API_GESUNDHEIT)):
        for de, en in zuordnung.items():
            z[de] = satz.get(bereich, {}).get(en)
    geo = info.get("leaf_geometry")
    if isinstance(geo, dict):
        z["sichtbare_blaetter"] = geo.get("count")
        z["blattzaehlung_quelle"] = geo.get("method")
    else:
        z["sichtbare_blaetter"] = info.get("visible_leaf_count")
        z["blattzaehlung_quelle"] = info.get("visible_leaf_count_method")
    z["durchmesser_px"] = info.get("leaf_diameter_px")
    pixel = info.get("pixel_measurement", {})
    if not isinstance(pixel, dict):
        raise ValueError("Ungueltige Pixelmetadaten in ergebnis.json")
    z.update(blattanteil_im_bild_pct=pixel.get("leaf_coverage_pct"),
             blattpixel_aenderung_pro_tag=pixel.get("visible_pixel_change_per_day"),
             pixel_vergleichsfoto=pixel.get("reference_file"))
    z = {feld: historienwert(feld, wert) for feld, wert in z.items()}
    z["_historie_export"] = copy.deepcopy(satz)
    z["_csv_zusatz"] = copy.deepcopy(info.get("legacy_csv_fields", {}))
    if not isinstance(z["_csv_zusatz"], dict):
        raise ValueError("Ungueltige historische CSV-Zusatzfelder")
    return z


def belegte_werte_ergaenzen(z, info):
    """Nur aus bekannten Werten derselben Aufnahme ableitbare Lücken füllen."""
    form = info.get("image_size") or z.get("_bildform")
    pixel, skala = z.get("pflanzen_pixel"), z.get("mm_pro_pixel")
    if (z.get("blattanteil_im_bild_pct") is None and isinstance(form,(list,tuple))
            and len(form)==2 and all(type(n) is int and n>0 for n in form)
            and pixel is not None and 0<=pixel<=math.prod(form)):
        z["blattanteil_im_bild_pct"] = round(100*pixel/math.prod(form),RUNDUNG["blattanteil_im_bild_pct"])
    if skala is not None and skala>0:
        if z.get("blattflaeche_cm2") is None and pixel is not None and pixel>0:
            z["blattflaeche_cm2"] = round(pixel*skala**2/100,RUNDUNG["blattflaeche_cm2"])
        if z.get("durchmesser_mm") is None and z.get("durchmesser_px") is not None and z["durchmesser_px"]>0:
            z["durchmesser_mm"] = round(z["durchmesser_px"]*skala,RUNDUNG["durchmesser_mm"])
    rgb = [z.get("mittel_"+k) for k in "rgb"]
    if z.get("farbe_hex") is None and all(v is not None and 0<=v<=255 for v in rgb):
        z["farbe_hex"] = "#{:02x}{:02x}{:02x}".format(*(round(v) for v in rgb))


def historie_vorbereiten(z):
    """Urspruengliche Herkunft behalten; alte Bilder dafuer nicht benoetigen."""
    if not isinstance(z.get("bild"), str) or not z["bild"].strip():
        raise ValueError("Historischer Datensatz ohne Bilddateinamen")
    z["_zeit"] = historienzeit(z.get("captured_at"))
    z["_historisch"] = True
    gespeichert = z.pop("_historie_export", None)
    belegte_werte_ergaenzen(z,(gespeichert or {}).get("analysis",{}))
    if gespeichert is None:
        gespeichert = api_datensatz(z)
        # Nur die CSV ist vorhanden: Herkunft nicht als aktuelle Messung ausgeben.
        gespeichert["device_id"] = None
        gespeichert["analysis"].update(version=z.get("pipeline_version"),pipeline_sha256=None,
                                        series_id=None,mask_source=None,lens_corrected=None)
    info = gespeichert.setdefault("analysis", {})
    z["_sha256"] = gespeichert.get("image", {}).get("checksum_sha256")
    z["_ist_referenz"] = bool(info.get("is_reference") or z.get("gesundheit_status") == "referenzfoto_start_der_ansicht")
    z["_score_modus"] = info.get("health_comparison_mode")
    if z["_score_modus"] is None:
        status = z.get("gesundheit_status") or ""
        if "farbverhaeltnis_teilflaeche" in status:
            z["_score_modus"] = "farbverhaeltnis_teilflaeche"
        elif "nur_farbvergleich" in status:
            z["_score_modus"] = "nur_farbe"
    fehlt = info.get("missing_values", {})
    if not isinstance(fehlt, dict):
        raise ValueError("Ungueltige missing_values in ergebnis.json")
    z["_rate_status"] = (info.get("growth_comparison_mode")
                         or ("berechnet_historisch" if z.get("wachstumsrate_pct_pro_tag") is not None else None)
                         or fehlt.get("growth_rate_pct_per_day") or "historischer_vergleich_nicht_gespeichert")
    gespeichert.setdefault("image", {}).update(file_name=z["bild"], captured_at=z.get("captured_at"))
    for bereich, zuordnung in (("image_measurements", API_MESSFELDER), ("health_assessment", API_GESUNDHEIT)):
        gespeichert.setdefault(bereich, {}).update({en: z.get(de) for de, en in zuordnung.items()})
        for de, en in zuordnung.items():
            if z.get(de) is not None:
                fehlt.pop(en, None)
            else:
                fehlt.setdefault(en, "historischer_wert_nicht_gespeichert")
    info.update(version=z.get("pipeline_version"), health_status=z.get("gesundheit_status"),
                capture_time_source=z.get("zeitquelle"), hours_since_start=z.get("stunden_seit_start"),
                view_number=z.get("ansicht"), is_reference=z["_ist_referenz"],
                health_comparison_mode=z["_score_modus"], reference_file=z.get("gesundheit_referenzfoto"),
                growth_reference_file=z.get("wachstum_vergleichsfoto"),
                growth_interval_hours=z.get("wachstum_abstand_stunden"), missing_values=fehlt)
    info.setdefault("pixel_measurement", {}).update(leaf_coverage_pct=z.get("blattanteil_im_bild_pct"),
              visible_pixel_change_per_day=z.get("blattpixel_aenderung_pro_tag"), reference_file=z.get("pixel_vergleichsfoto"))
    info["leaf_diameter_px"] = z.get("durchmesser_px")
    if not info.get("leaf_geometry"):
        info["visible_leaf_count"] = z.get("sichtbare_blaetter")
        info["visible_leaf_count_method"] = z.get("blattzaehlung_quelle")
    if z.get("_csv_zusatz"):
        info["legacy_csv_fields"] = copy.deepcopy(z["_csv_zusatz"])
    z["_ansicht_id"] = info.get("view_id")
    z["_historie_export"] = gespeichert
    return z


def ergebnishistorie_laden(ausgabe):
    """Bestehende Werte vor jedem Ersetzen vollstaendig lesen und pruefen."""
    json_pfad, csv_pfad = Path(ausgabe)/"ergebnis.json", Path(ausgabe)/"ergebnis.csv"
    saetze, zeilen = [], []
    try:
        if json_pfad.is_file():
            def ungueltig(wert):
                raise ValueError(f"Ungueltige JSON-Zahl: {wert}")
            saetze = json.loads(json_pfad.read_text(encoding="utf-8-sig"), parse_constant=ungueltig)
            if not isinstance(saetze, list):
                raise ValueError("ergebnis.json enthaelt keine Datensatzliste")
        json_zeilen = [historienzeile(satz) for satz in saetze]
        benutzt = set()
        json_index = {}
        for i, z in enumerate(json_zeilen):
            key = (z["bild"], historienzeit(z["captured_at"]) or z["captured_at"])
            json_index.setdefault(key, []).append(i)
        if csv_pfad.is_file() and csv_pfad.stat().st_size:
            with csv_pfad.open(encoding="utf-8-sig", newline="") as datei:
                kopf = datei.readline(); datei.seek(0)
                delimiter = ";" if ";" in kopf else "\t" if "\t" in kopf else ","
                reader = csv.DictReader(datei, delimiter=delimiter, strict=True)
                spalten = reader.fieldnames or []
                if "bild" not in spalten or len(set(spalten)) != len(spalten) or "" in spalten:
                    raise ValueError("ergebnis.csv hat keinen eindeutigen gueltigen Spaltenkopf")
                for nummer, roh in enumerate(reader, 2):
                    if None in roh or any(wert is None for wert in roh.values()):
                        raise ValueError(f"Unvollstaendige CSV-Zeile {nummer}")
                    name, zeit = roh.get("bild"), historienwert("captured_at", roh.get("captured_at"))
                    kandidaten = json_index.get((name, historienzeit(zeit) or zeit), [])
                    if kandidaten:
                        index = kandidaten.pop(0); benutzt.add(index)
                        z = json_zeilen[index]
                    else:
                        # CSV ist eine Ausgabe für Excel. Bei vorhandener JSON-Zeile
                        # gelten deren Werte und Herkunft, nicht die Tabellenkopie.
                        z = {feld: historienwert(feld, roh[feld]) if feld in roh else None
                             for feld in SPALTEN}
                    z.setdefault("_csv_zusatz", {}).update({k: v for k, v in roh.items() if k not in SPALTEN})
                    zeilen.append(z)
        zeilen.extend(z for i, z in enumerate(json_zeilen) if i not in benutzt)
        return [historie_vorbereiten(z) for z in zeilen]
    except (OSError, ValueError, TypeError, csv.Error) as fehler:
        raise ValueError(f"Ergebnishistorie nicht sicher lesbar: {fehler}. Bestehende Dateien bleiben erhalten.") from fehler


def ergebnishistorie_verbinden(historie, aktuell):
    """Je Foto aktualisieren; Messungen ohne lokales Original unveraendert behalten."""
    ergebnis, nach_name = [], {}
    for z in [*historie, *aktuell]:
        kandidaten = nach_name.setdefault(z["bild"], [])
        sha = z.get("_sha256")
        identisch = [i for i in kandidaten if sha and ergebnis[i].get("_sha256") == sha]
        if not identisch:
            identisch = [i for i in kandidaten if not (sha and ergebnis[i].get("_sha256"))
                         and ((z.get("_zeit") or z.get("captured_at")) ==
                              (ergebnis[i].get("_zeit") or ergebnis[i].get("captured_at"))
                              or not ergebnis[i].get("captured_at"))]
            if z.get("_historisch") and not sha and not z.get("captured_at"):
                # Ohne Zeit/Pruefsumme koennen gleichnamige alte Zeilen
                # unterschiedliche Aufnahmen sein. Nur exakte Duplikate falten.
                identisch = [i for i in identisch if all(z.get(k) == ergebnis[i].get(k) for k in SPALTEN)]
        if (not identisch and not z.get("_historisch") and len(kandidaten) == 1
                and z.get("gesundheit_status") in ("datei_nicht_lesbar", "analysefehler")):
            alt = ergebnis[kandidaten[0]]
            if alt.get("brauchbar") and alt.get("captured_at") == z.get("captured_at"):
                print(f"{z['bild']}: aktuelle Datei nicht auswertbar; bisherige Messung bleibt erhalten.")
                continue
        if len(identisch) == 1:
            index = identisch[0]
            if (not z.get("_historisch") and ergebnis[index].get("brauchbar")
                    and z.get("gesundheit_status") in ("datei_nicht_lesbar", "analysefehler")):
                print(f"{z['bild']}: aktuelle Datei nicht auswertbar; bisherige Messung bleibt erhalten.")
            else:
                # Echte Zusatzspalten alter CSV-Versionen nicht beim Update verlieren.
                zusatz = dict(ergebnis[index].get("_csv_zusatz", {}))
                zusatz.update(z.get("_csv_zusatz", {}))
                if zusatz:
                    z["_csv_zusatz"] = zusatz
                ergebnis[index] = z
        else:
            kandidaten.append(len(ergebnis)); ergebnis.append(z)
    ergebnis.sort(key=lambda z: (z.get("_zeit") or datetime.max.replace(tzinfo=timezone.utc),
                                z["bild"], z.get("_sha256") or ""))
    # Referenz- oder Verfahrenswechsel im Diagramm nicht zu einer Kurve verbinden.
    gruppen = {}
    for z in ergebnis:
        info = z.get("_historie_export", {}).get("analysis", {})
        referenz = z.get("_referenz_meta", {})
        uid = z.get("_ansicht_id") or info.get("reference_sha256") or z.get("gesundheit_referenzfoto")
        if uid is not None:
            key = (uid, referenz.get("captured_at") or info.get("reference_captured_at"),
                   z.get("pipeline_version"), z.get("scoring_version"))
            z["_diagramm_gruppe"] = gruppen.setdefault(key, len(gruppen)+1)
        elif z.get("gesundheit") is not None or z.get("wachstumsrate_pct_pro_tag") is not None:
            key = ("unbekannt", z["bild"], z.get("captured_at"))
            z["_diagramm_gruppe"] = gruppen.setdefault(key, len(gruppen)+1)
        else:
            z["_diagramm_gruppe"] = None
    return ergebnis


def api_datensatz(z, ref=None):
    if z.get("_historie_export") is not None:
        return copy.deepcopy(z["_historie_export"])
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
    if z.get("durchmesser_px") is None:
        fehlt["leaf_diameter_px"] = "keine_auswertbare_blattmaske"
    if z.get("sichtbare_blaetter") is None:
        fehlt["sichtbare_blaetter"] = "keine_auswertbaren_blattkonturen"
        fehlt["blattzaehlung_quelle"] = "keine_auswertbaren_blattkonturen"
    if z.get("blattanteil_im_bild_pct") is None:
        fehlt["blattanteil_im_bild_pct"] = "blattmaske_nicht_berechenbar"
    if z["gesundheit_trend_24h"] is None:
        fehlt["health_trend_24h"] = "kein_gueltiger_score_vor_24_stunden_plusminus_2h"
    if not z["captured_at"]:
        fehlt["captured_at"] = "keine_verlaessliche_aufnahmezeit"
    for feld, wert in gesundheit.items():
        if wert is None and feld not in fehlt:
            fehlt[feld] = z["gesundheit_status"]
    if z.get("_score_modus") in ("farbverhaeltnis_teilflaeche", "blattverteilung_chromatik"):
        fehlt["score_brown"] = "brauntoene_ohne_bestaetigte_helligkeit_nicht_bewertet"
    for feld, wert in messung.items():
        if wert is None and feld not in fehlt:
            fehlt[feld] = "bild_nicht_auswertbar" if not z["brauchbar"] else "kein_gueltiger_messwert"
    return json_sicher({"device_id": DEVICE_ID,
        "image": {"file_name": z["bild"], "captured_at": z["captured_at"],
                  "storage_path": storage_path, "checksum_sha256": z.get("_sha256")},
        "image_measurements": messung, "health_assessment": gesundheit,
        "analysis": {"version": ANALYSE_VERSION, "health_status": z["gesundheit_status"],
                     **({"legacy_csv_fields": z["_csv_zusatz"]} if z.get("_csv_zusatz") else {}),
                     "pipeline_sha256": PIPELINE_SHA256,
                     "series_id": MESSREIHE,
                     "image_size": list(z["_bildform"]) if z.get("_bildform") is not None else None,
                     "camera_transform": z.get("_pose").tolist() if z.get("_pose") is not None else None,
                     "twin_view_id": z.get("_twin_ansicht_id"),
                     "twin_camera_transform": z.get("_twin_pose").tolist() if z.get("_twin_pose") is not None else None,
                     "lens_profile_sha256": z.get("_objektiv_hash"),
                     "mask_clipped": z.get("_beschnitten"),
                     "leaf_geometry": z.get("_blattgeometrie"),
                     "leaf_diameter_px": z.get("durchmesser_px"),
                     "capture_time_source":z.get("zeitquelle"),
                     "hours_since_start":z.get("stunden_seit_start"),
                     "view_number":z.get("ansicht"),
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
                     "structure_score": z.get("_struktur_score"),
                     "view_id": z.get("_ansicht_id"),
                     "growth_reference_file": z.get("wachstum_vergleichsfoto"),
                     "growth_interval_hours": z.get("wachstum_abstand_stunden"),
                     "growth_comparison_mode":z.get("_rate_status") if rate_grund.startswith("berechnet") else None,
                     "pixel_measurement": {"leaf_coverage_pct":z.get("blattanteil_im_bild_pct"),
                                           "visible_pixel_change_per_day":z.get("blattpixel_aenderung_pro_tag"),
                                           "reference_file":z.get("pixel_vergleichsfoto")},
                     "missing_values": fehlt}})


def ohne_json_nulls(wert):
    """Optionale Objektfelder auslassen, Zahlen und Arrays unverändert behalten."""
    if isinstance(wert, dict):
        return {k: ohne_json_nulls(v) for k,v in wert.items() if v is not None}
    if isinstance(wert, list):
        return [ohne_json_nulls(v) for v in wert]
    return wert


ERGEBNIS_FELDER = {
    **{de: ("image_measurements",en) for de,en in API_MESSFELDER.items()},
    **{de: ("health_assessment",en) for de,en in API_GESUNDHEIT.items()},
    "captured_at": ("image","captured_at"),
    "zeitquelle": ("analysis","capture_time_source"),
    "stunden_seit_start": ("analysis","hours_since_start"),
    "ansicht": ("analysis","view_number"),
    "gesundheit_referenzfoto": ("analysis","reference_file"),
    "wachstum_vergleichsfoto": ("analysis","growth_reference_file"),
    "wachstum_abstand_stunden": ("analysis","growth_interval_hours"),
    "durchmesser_px": ("analysis","leaf_diameter_px"),
    "blattanteil_im_bild_pct": ("analysis","pixel_measurement","leaf_coverage_pct"),
    "blattpixel_aenderung_pro_tag": ("analysis","pixel_measurement","visible_pixel_change_per_day"),
    "pixel_vergleichsfoto": ("analysis","pixel_measurement","reference_file"),
    "sichtbare_blaetter": ("analysis","leaf_geometry","count"),
    "blattzaehlung_quelle": ("analysis","leaf_geometry","method"),
}


def ergebnis_grund(feld,z):
    status = z.get("gesundheit_status") or "kein_gueltiger_messwert"
    if feld in ("captured_at","stunden_seit_start","zeitquelle"):
        return "keine_verlaessliche_aufnahmezeit"
    if feld in ("ansicht","gesundheit_referenzfoto") or feld.startswith("score_") or feld.startswith("gesundheit"):
        return status
    if feld in ("wachstum_vergleichsfoto","wachstum_abstand_stunden"):
        return z.get("_rate_status") or "keine_gueltige_vergleichsaufnahme"
    if feld=="pixel_vergleichsfoto":
        return "kein_frueheres_brauchbares_bild_gleicher_aufloesung_mit_mindestabstand"
    return "bild_nicht_auswertbar" if z.get("brauchbar") is False else "kein_gueltiger_messwert"


def ergebnis_export(z,ref):
    satz = api_datensatz(z,ref)
    info = satz["analysis"]
    fehlt = {k: v for k,v in info.get("missing_values",{}).items()
             if isinstance(v,str) and v.strip()}
    for feld,pfad in ERGEBNIS_FELDER.items():
        key = pfad[-1] if feld not in ("sichtbare_blaetter","blattzaehlung_quelle","pixel_vergleichsfoto",
                                       "blattpixel_aenderung_pro_tag","blattanteil_im_bild_pct") else feld
        if z.get(feld) is not None:
            fehlt.pop(key,None)
        else:
            fehlt.setdefault(key,ergebnis_grund(feld,z))
    for key in ("device_id","storage_path","checksum_sha256"):
        wert = satz.get(key) if key=="device_id" else satz["image"].get(key)
        if wert is not None:
            fehlt.pop(key,None)
        else:
            fehlt.setdefault(key,{"device_id":"geraet_noch_nicht_zugeordnet",
                "storage_path":"externer_import_noch_keinem_serverpfad_zugeordnet",
                "checksum_sha256":"keine_pruefsumme_gespeichert"}[key])
    info["missing_values"] = fehlt
    return ohne_json_nulls(json_sicher(satz))


def ergebnisse_speichern(zeilen, ref, ausgabe):
    from gesundheitsbewertung import gesund_text

    # Neue Werte aus der Analyse, historische Herkunft aus der bestehenden Ausgabe.
    inhalt = [ergebnis_export(z,ref) for z in zeilen]
    rueck = {pfad[-1] if len(pfad)==2 else de:de for de,pfad in ERGEBNIS_FELDER.items()}
    for z, satz in zip(zeilen, inhalt):
        gruende = {}
        for feld, grund in satz["analysis"]["missing_values"].items():
            if feld in rueck:
                gruende.setdefault(gesund_text(grund.split(";",1)[0]), []).append(rueck[feld])
        z["fehlende_werte"] = " | ".join(
            f"{', '.join(sorted(f))}: {g}" for g, f in sorted(gruende.items()))
    json_tmp = ausgabe/".ergebnis.json.tmp"
    with json_tmp.open("w", encoding="utf-8") as datei:
        json.dump(inhalt, datei, ensure_ascii=False, indent=2, allow_nan=False)
    json_tmp.replace(ausgabe/"ergebnis.json")
    csv_tmp = ausgabe/".ergebnis.csv.tmp"
    spalten = SPALTEN + list(dict.fromkeys(k for z in zeilen for k in z.get("_csv_zusatz", {}) if k not in SPALTEN))
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as datei:
        writer = csv.DictWriter(datei, fieldnames=spalten, delimiter=";", extrasaction="raise")
        writer.writeheader()
        for z in zeilen:
            daten = {}
            for k in spalten:
                v = json_sicher(z.get(k) if k in SPALTEN else z.get("_csv_zusatz", {}).get(k))
                if v is None or v=="":
                    if v=="" and k in ("auffaelligkeit","gesundheitswarnung"):
                        daten[k] = "Keine"
                    else:
                        daten[k] = CSV_NICHT_VERFUEGBAR
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


def json_ausgabe_schreiben(ziel, daten):
    """Nur JSON austauschen; die zugehörigen Browserdateien bleiben unverändert."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".biobox-daten-", dir=ziel.parent) as tmp:
        datei = Path(tmp)/ziel.name
        datei.write_text(json.dumps(daten, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        datei.replace(ziel)
    return ziel


# Diagramme und Verarbeitungslauf
def gesundheit_pro_foto_grafik(zeilen, ordner):
    """Ein Eintrag je Foto. Fehlend, Referenz und gemessene Null unterscheiden."""
    n = len(zeilen)
    breite = max(10., min(26., 5.+.52*n))
    fig, (ax, status_ax) = plt.subplots(2, 1, figsize=(breite, 7.8), sharex=True,
                                     gridspec_kw={"height_ratios": [4, 1.5]})
    x = np.arange(1, n+1)
    texte, farben, labels = [], [], []
    for i, z in enumerate(zeilen, 1):
        score = z.get("gesundheit")
        gueltig = isinstance(score, (int, float)) and math.isfinite(score) and 0 <= score <= 100
        referenz = bool(z.get("_ist_referenz"))
        if gueltig:
            ax.bar(i, score, width=.67, color="#32816c", zorder=3)
            # Auch ein tatsaechlich berechneter Score 0 bleibt sichtbar.
            ax.scatter([i], [score], s=22, color="#245c4e", zorder=4)
            if n <= 45:
                ax.text(i, min(score+3, 104), f"{score:.1f}", ha="center", va="bottom", fontsize=8)
            roh = z.get("gesundheit_roh")
            if isinstance(roh, (int, float)) and math.isfinite(roh):
                ax.scatter([i], [roh], marker="_", s=65, color="#795d91", zorder=5)
            texte.append("Berechnet")
            farben.append("#32816c")
        elif referenz:
            ax.scatter([i], [100], marker="D", s=55, facecolor="white", edgecolor="#547da0", zorder=4)
            if n <= 45:
                ax.text(i, 105, "Ref.", ha="center", fontsize=8, color="#547da0")
            texte.append("Referenzstart")
            farben.append("#547da0")
        else:
            # Dieser graue Platzhalter hat absichtlich KEINE Hoehe in Score-Einheiten.
            ax.axvspan(i-.34, i+.34, ymin=.02, ymax=.92, facecolor="#e9edef", hatch="///",
                       edgecolor="#c4cdd0", linewidth=0, zorder=0)
            if n <= 45:
                ax.text(i, 48, "—", ha="center", color="#738089", fontsize=12)
            status = z.get("gesundheit_status") or "Kein Score gespeichert"
            texte.append(status.replace("_", " "))
            farben.append("#9b7141")
        zeit = z.get("_zeit") or historienzeit(z.get("captured_at"))
        labels.append(f"{i}\n{zeit:%d.%m. %H:%M}" if zeit else str(i))
    ax.set_title("04 | Zustandsindex je Foto", loc="left", fontweight="semibold", pad=14)
    ax.set_ylabel("Relativer Index [0–100]")
    ax.set_ylim(-3, 114)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.grid(axis="y", alpha=.18, zorder=0)
    ax.axhline(100, color="#aebcbd", ls=":", lw=1)
    ax.plot([], [], "s", color="#32816c", label="Berechneter Score je Foto")
    ax.plot([], [], "_", color="#795d91", label="Rohscore vor zeitlicher Glättung")
    ax.plot([], [], "D", markerfacecolor="white", color="#547da0", label="Referenzstart; kein Gesundheitsmesswert")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), fontsize=8, ncol=3)
    gruppen = list(dict.fromkeys(texte))
    for j, text in enumerate(gruppen):
        ids = [i for i, s in enumerate(texte) if s == text]
        status_ax.scatter([i+1 for i in ids], [j]*len(ids), color=[farben[i] for i in ids], s=25)
    status_ax.set_yticks(range(len(gruppen)), [t[:76] for t in gruppen], fontsize=8)
    status_ax.set_ylim(len(gruppen)-.4, -.6)
    status_ax.grid(axis="y", alpha=.15)
    tick_ids = list(range(n)) if n <= 32 else sorted(set(np.linspace(0, n-1, min(24, n), dtype=int)))
    status_ax.set_xticks([i+1 for i in tick_ids], [labels[i] for i in tick_ids], fontsize=8,
                        rotation=0 if n <= 16 else 45)
    status_ax.set_xlim(.4, max(1, n)+.6)
    status_ax.set_xlabel("Ein Platz pro Foto · Nummer entspricht ergebnis.csv / ergebnis.json")
    berechnet = sum(isinstance(z.get("gesundheit"), (float, int)) and math.isfinite(z["gesundheit"]) for z in zeilen)
    fig.text(.015, .018, f"{n} Fotos enthalten · {berechnet} mit Score · Schraffiert = nicht bewertbar, nicht 0. "
             "100 = wie die eigene Referenz; keine biologische Diagnose.", fontsize=8.5, color="#62737b")
    fig.tight_layout(rect=(0, .055, 1, 1))
    ordner.mkdir(exist_ok=True)
    fig.savefig(ordner/GRAFIK_DATEIEN[3], dpi=150, facecolor="white")
    plt.close(fig)


def grafiken(zeilen, ordner):
    from gesundheitsbewertung import GEWICHTE

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
        ansichten = [z.get("_diagramm_gruppe", z.get("ansicht")) for z in zeilen]
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
                label = f"Referenz {ansicht}"+(" · Farbteilfläche" if teil else "")
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
                  "berechnet_historisch":"Berechnet · gespeicherter Vergleich",
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
    gesundheit_pro_foto_grafik(zeilen, ordner)
    fig, ax = plt.subplots(figsize=(max(8.5,min(16,5+.45*len(zeilen))),4.7))
    ax.set_title("05 | Fünf Teilbewertungen · jede Spalte ist ein Foto",loc="left",fontweight="semibold")
    labels = ["Farbverteilung","Gelbzunahme","Braun-/Warmzunahme","Sättigungswechsel","Farbtonwechsel"]
    werte = np.array([[np.nan if z.get("score_"+k) is None else z["score_"+k] for z in zeilen]
                      for k in GEWICHTE],dtype=float)
    ax.set_facecolor("#edf0f2")
    heat = ax.imshow(np.ma.masked_invalid(werte),aspect="auto",interpolation="nearest",
                     cmap="viridis",vmin=0,vmax=100)
    ax.set_yticks(range(len(labels)),labels)
    pos = list(range(len(zeilen))) if len(zeilen)<=32 else sorted(set(np.linspace(0,len(zeilen)-1,24,dtype=int)))
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
                else:
                    ax.text(i,j,"—",ha="center",va="center",fontsize=8,color="#62737b")
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


def dateien_uebernehmen(dateien, work):
    """Ausgaben gemeinsam ersetzen und bei einem Fehler die Originale zurückholen."""
    backup = work/"vorher"; backup.mkdir()
    changes = []
    try:
        for i,(neu,ziel) in enumerate(dateien):
            sicherung = backup/str(i)
            item = {"ziel":ziel,"backup":sicherung,"old":False,"new":False}
            changes.append(item)
            if ziel.exists() or ziel.is_symlink():
                ziel.replace(sicherung);item["old"] = True
            if neu is not None:
                neu.replace(ziel);item["new"] = True
    except OSError as fehler:
        blockiert = []
        for item in reversed(changes):
            try:
                ziel = item["ziel"]
                if item["new"] and (not item["old"] or ziel.is_dir()):
                    ziel.replace(work/("rollback-"+item["backup"].name))
                if item["old"]:
                    item["backup"].replace(ziel)
            except OSError:
                blockiert.append(str(item["ziel"]))
        if blockiert:
            (work/"sicherung_behalten").touch()
            raise OSError("Wiederherstellung blockiert. Sicherung: "+str(backup)+": "+", ".join(blockiert)) from fehler
        raise OSError("Ausgaben konnten nicht ersetzt werden. Offene Dateien schließen und erneut versuchen. "
                      "Die bisherigen Ausgaben wurden wiederhergestellt.") from fehler


def grafikordner_pruefen(ordner):
    if ordner.is_symlink() or (ordner.exists() and not ordner.is_dir()):
        raise ValueError(f"Grafikordner kann nicht sicher übernommen werden: {ordner}")


def alte_grafiken_vorbereiten(alt, ziel, arbeit):
    """Nur bisherige Grafikausgaben verschieben; alte Webdateien liegen lassen."""
    dateien = []
    if alt == ziel or not alt.is_dir():
        return dateien
    arbeit.mkdir()
    for pfad in alt.iterdir():
        if pfad.suffix.lower() in (".html", ".css", ".js"):
            continue
        if pfad.name in (*GRAFIK_DATEIEN, GRAFIK_JSON_DATEI, ALTE_TWIN_GRAFIK):
            if pfad.is_dir():
                raise ValueError(f"Ausgabedateiname wird von einem Ordner belegt: {pfad}")
            dateien.append((None, pfad))
            continue
        neu = ziel/pfad.name
        if neu.exists() or neu.is_symlink():
            raise ValueError(f"Datei liegt in beiden Grafikordnern: {pfad.name}. Bitte eine davon umbenennen.")
        kopie = arbeit/pfad.name
        if pfad.is_dir() and not pfad.is_symlink():
            shutil.copytree(pfad, kopie, symlinks=True)
        else:
            shutil.copy2(pfad, kopie, follow_symlinks=False)
        dateien.extend(((kopie, neu), (None, pfad)))
    return dateien


def alten_grafikordner_aufraeumen(alt, ziel):
    if alt != ziel:
        with contextlib.suppress(OSError):
            alt.rmdir()


def analysieren(pfade,ausgabe,manuell=None,einzelbilder=False,neue_referenz=False,zeitdaten=None):
    """Alle Eingaben erneut auswerten; zusammenpassende Ausgaben gemeinsam ersetzen.

    Automatische Masken werden nicht aus dem Ausgabeordner eingelesen.
    Manuelle dateigenaue Korrekturen bleiben als bewusst gepruefte Eingabe.
    Bei einem Schreibfehler werden bereits ersetzte Dateien zurueckgesetzt.
    """
    from digital_twin import twin_historie_laden

    pfade=list(pfade);ausgabe=Path(ausgabe).expanduser().resolve()
    if not pfade:raise ValueError('Keine Eingabebilder; vorhandene Auswertung bleibt erhalten.')
    ausgabe.mkdir(parents=True,exist_ok=True)
    twin_ziel,gesund_ziel = viewer_ordner(ausgabe)
    grafik_ziel,grafik_alt = grafik_ordner(ausgabe),ausgabe/"grafiken"
    with auswertung_sperren(ausgabe):
        historie = ergebnishistorie_laden(ausgabe)
        twin_historie = twin_historie_laden(ausgabe)
        work=Path(tempfile.mkdtemp(prefix='.biobox-auswertung-',dir=ausgabe.parent))
        fertig=work/'neu';fertig.mkdir()
        try:
            # Referenzen werden waehrend jeder Auswertung im Arbeitsspeicher
            # aufgebaut. Nur die optional gespeicherte Lineal-Kalibrierung bleibt.
            if (ausgabe/'massstab.npz').is_file():
                shutil.copy2(ausgabe/'massstab.npz',fertig/'massstab.npz')
            if (ausgabe/'masken_korrektur').is_dir():
                shutil.copytree(ausgabe/'masken_korrektur',fertig/'masken_korrektur')
            if (ausgabe/'blattlabels').is_dir():
                shutil.copytree(ausgabe/'blattlabels',fertig/'blattlabels')
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
            twin_neu,gesund_neu = work/"twin",work/"gesundheit"
            grafik_neu = work/"grafiken"; grafik_neu.mkdir()
            erwartete_grafiken = (*GRAFIK_DATEIEN, GRAFIK_JSON_DATEI)
            grafikordner_pruefen(grafik_ziel)
            grafikordner_pruefen(grafik_alt)
            migration = alte_grafiken_vorbereiten(grafik_alt, grafik_ziel, work/"alte-grafiken")
            rows=_analysieren(pfade,fertig,manuell,einzelbilder,neue_referenz,historie,twin_historie,
                              zeitdaten,twin_neu,gesund_neu,grafik_neu)
            dateien = [(fertig/name,ausgabe/name) for name in
                       ('ergebnis.csv','ergebnis.json','masken','kontrolle')]
            dateien += [(twin_neu/TWIN_JSON_DATEI, twin_ziel/TWIN_JSON_DATEI),
                        (gesund_neu/GESUND_JSON_DATEI, gesund_ziel/GESUND_JSON_DATEI)]
            dateien += [(grafik_neu/name, grafik_ziel/name) for name in erwartete_grafiken]
            alte_daten = [(None, pfad) for pfad in (ausgabe/TWIN_JSON_DATEI, ausgabe/GESUND_JSON_DATEI,
                                                  grafik_ziel/ALTE_TWIN_GRAFIK) if pfad.is_file()]
            if not all(neu.exists() for neu,_ in dateien):
                raise OSError('Neue Auswertung ist unvollstaendig; alte Ausgabe bleibt erhalten.')
            if any(ziel.is_dir() for neu,ziel in dateien if neu.is_file()):
                raise OSError("Ein Ausgabe-Dateiname wird bereits für einen Ordner verwendet.")
            twin_ziel.mkdir(parents=True,exist_ok=True)
            gesund_ziel.mkdir(parents=True,exist_ok=True)
            grafik_ziel.mkdir(parents=True,exist_ok=True)
            dateien_uebernehmen(dateien+alte_daten+migration,work)
            alten_grafikordner_aufraeumen(grafik_alt, grafik_ziel)
        finally:
            if not (work/"sicherung_behalten").exists():
                shutil.rmtree(work)
    alte_referenzdateien_entfernen(ausgabe)
    erhalten = sum(bool(z.get('_historisch')) for z in rows)
    print(f'\n{len(pfade)} vorhandene Bilder verarbeitet; {erhalten} fruehere Messungen erhalten.')
    print(f'{len(rows)} Datensaetze insgesamt -> {ausgabe/"ergebnis.csv"}')
    print('Masken, Kontrollbilder, Grafiken, Ergebnishistorie und Daten für die Browseransichten aktualisiert.')
    print('Ansichten öffnen: python analyse.py --3d, --gesundheit oder --grafiken.')
    n_rate = sum(z.get("wachstumsrate_pct_pro_tag") is not None for z in rows)
    n_score = sum(z.get("gesundheit") is not None for z in rows)
    n_pixel = sum(z.get("blattpixel_aenderung_pro_tag") is not None for z in rows)
    print(f"Pixeländerung: {n_pixel}/{len(rows)} | Geprüfte Wachstumsrate: {n_rate}/{len(rows)} | "
          f"Zustandsvergleich: {n_score}/{len(rows)}. Details in Grafik 02 und 04.")
    n_flaeche = sum(z.get("blattflaeche_cm2") is not None for z in rows)
    n_zeiten = sum(bool(z.get("captured_at")) for z in rows)
    n_blaetter = sum(z.get("sichtbare_blaetter") is not None for z in rows)
    print(f"Aufnahmezeit: {n_zeiten}/{len(rows)} | Fläche in cm²: {n_flaeche}/{len(rows)} | "
          f"Blattzählung: {n_blaetter}/{len(rows)}. Fehlende Werte: siehe fehlende_werte in ergebnis.csv.")
    if manuell is None and not any(z.get('mm_pro_pixel') for z in rows):
        print('Fuer cm2/mm einmal eine bekannte Linealstrecke auf Blatthoehe markieren (--massstab-bild / --referenz-mm).')
    return rows


def _analysieren(pfade, ausgabe, manuell, einzelbilder, neue_referenz, historie,
                 twin_historie, zeitdaten, twin_ordner, gesund_ordner, grafiken_ordner):
    from digital_twin import blattpunkte_pfad, modell_aktualisieren, twin_ansichten_verbinden, twin_blattgeometrie
    from gesundheitsbewertung import (
        GEWICHTE, REFERENZ_FREIGEGEBEN, SCORING_VERSION, bewerten, gesundheit_speichern,
        gesundheitsmerkmale, gesundheitsverlauf, licht_abgleichen, licht_anwenden,
    )

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
    zeitdaten = zeitdaten or {}
    aufnahmezeiten = {p: (None,"unbekannt") if einzelbilder else
                      (zeitdaten[Path(p).name],"zeitdatei") if Path(p).name in zeitdaten
                      else aufnahmezeit(p) for p in pfade}
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
            z["_objektiv_hash"] = lens_hash
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
            try:
                sha = z["_sha256"]
                z["_blattgeometrie"] = twin_blattgeometrie(
                    bild,maske,ausgabe/"blattlabels"/(sha+".png"),
                    blattpunkte_pfad(ausgabe,sha,kalibrierung is not None))
            except (OSError,ValueError,cv2.error) as fehler:
                # Optionale Ansichtsgeometrie darf keine Bildmessung verwerfen.
                z["_blattgeometrie"] = None
                print(f"Blattkonturen nicht verfügbar: {pfad.name} ({fehler})")
            if z["_blattgeometrie"] is not None:
                z["sichtbare_blaetter"] = z["_blattgeometrie"]["count"]
                z["blattzaehlung_quelle"] = z["_blattgeometrie"]["method"]
                hinweis = z["_blattgeometrie"].get("note") or ""
                if hinweis.startswith("Blattmarkierungen nicht übernommen:"):
                    print(f"{pfad.name}: {hinweis}")
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
    wachstumszeitreihe(zeilen, referenzzeit)
    gesundheitsverlauf(zeilen, alte_historie)
    # Einmal runden: CSV, JSON und Diagramme benutzen dieselben Zahlen.
    for z in zeilen:
        for feld, stellen in RUNDUNG.items():
            if z.get(feld) is not None:
                z[feld] = round(float(z[feld]), stellen)
        if z.get("_struktur_score") is not None:
            z["_struktur_score"] = round(z["_struktur_score"],1)
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
    twin_ansichten_verbinden(historie or [], zeilen)
    zeilen = ergebnishistorie_verbinden(historie or [], zeilen)
    csv_aktuell = ergebnisse_speichern(zeilen,hauptref,ausgabe)
    if not csv_aktuell:
        raise PermissionError("CSV konnte nicht erstellt werden; bisherige Auswertung bleibt erhalten.")
    grafiken(zeilen,grafiken_ordner)
    modell_aktualisieren(zeilen, twin_historie, einzelbilder, twin_ordner)
    grafikdaten_speichern(grafiken_ordner)
    gesundheit_speichern(zeilen, gesund_ordner, pfade)
    return zeilen


def grafikdaten_speichern(ordner):
    titel = ("Wachstum", "Wachstumsrate", "Farbverlauf", "Gesundheit", "Teilbewertungen")
    daten = {"version": 1, "charts": [{"id": Path(name).stem[3:], "label": label, "file": name}
            for name, label in zip(GRAFIK_DATEIEN, titel) if (ordner/name).is_file()]}
    return json_ausgabe_schreiben(ordner/GRAFIK_JSON_DATEI, daten)


def grafikseite_aus_dateien(ausgabe):
    """Vorhandene PNGs bei Bedarf übernehmen und nur die Galerie-Daten aktualisieren."""
    ausgabe = Path(ausgabe).expanduser().resolve()
    ziel, alt = grafik_ordner(ausgabe), ausgabe/"grafiken"
    with auswertung_sperren(ausgabe):
        grafikordner_pruefen(ziel)
        grafikordner_pruefen(alt)
        quelle = {name: next((ordner/name for ordner in (ziel, alt) if (ordner/name).is_file()), None)
                  for name in GRAFIK_DATEIEN}
        if not any(quelle.values()):
            raise ValueError("Keine vorhandenen Grafiken. Zuerst python analyse.py ausführen.")
        work = Path(tempfile.mkdtemp(prefix=".biobox-grafiken-", dir=ausgabe.parent))
        try:
            neu = work/"grafiken"
            neu.mkdir()
            migration = alte_grafiken_vorbereiten(alt, ziel, work/"alte-grafiken")
            dateien = []
            for name, pfad in quelle.items():
                if pfad is not None:
                    shutil.copy2(pfad, neu/name)
                    if pfad != ziel/name:
                        dateien.append((neu/name, ziel/name))
            grafikdaten_speichern(neu)
            dateien.append((neu/GRAFIK_JSON_DATEI, ziel/GRAFIK_JSON_DATEI))
            if (ziel/ALTE_TWIN_GRAFIK).is_file():
                dateien.append((None, ziel/ALTE_TWIN_GRAFIK))
            if any(pfad.is_dir() for _, pfad in dateien):
                raise OSError("Ein Ausgabe-Dateiname wird bereits für einen Ordner verwendet.")
            ziel.mkdir(parents=True, exist_ok=True)
            dateien_uebernehmen(dateien+migration, work)
            alten_grafikordner_aufraeumen(alt, ziel)
        finally:
            if not (work/"sicherung_behalten").exists():
                shutil.rmtree(work)
    return ziel/GRAFIK_JSON_DATEI


def ergebnis_standardordner():
    """Das aktuelle Projekt bevorzugen, ohne den Standard-Pi-Ordner zu ändern."""
    for ordner in (Path.cwd(), PROJEKT_ORDNER, BILDER_ORDNER.parent):
        ausgabe = ordner/"auswertung"
        if any(p.is_file() for p in (ausgabe/"ergebnis.json", ausgabe/"ergebnis.csv",
                                     viewer_ordner(ausgabe)[0]/TWIN_JSON_DATEI,
                                     viewer_ordner(ausgabe)[1]/GESUND_JSON_DATEI)):
            return ausgabe
    return BILDER_ORDNER.parent/"auswertung"


def grafikansicht_anzeigen(ausgabe=None, ohne_browser=False):
    if ausgabe is None:
        ausgabe = next((ordner/"auswertung" for ordner in (Path.cwd(), PROJEKT_ORDNER, BILDER_ORDNER.parent)
                        if any((verzeichnis/name).is_file() for name in GRAFIK_DATEIEN
                               for verzeichnis in (ordner/"grafiken", ordner/"auswertung"/"grafiken"))),
                       ergebnis_standardordner())
    try:
        daten = grafikseite_aus_dateien(ausgabe)
        if ohne_browser:
            print("Grafikdaten:", daten)
        else:
            browseransicht_oeffnen(ausgabe, "grafiken", "Grafikansicht")
    except (OSError, ValueError) as fehler:
        print("Grafikansicht nicht erstellt:", fehler)
        return 1
    return 0


def lokale_auswertung(pfade, ausgabe, manuell=None, einzelbilder=False,
                      neue_referenz=False, zeitdatei=None):
    zeitdaten = aufnahmezeiten_laden(zeitdatei) if zeitdatei else None
    if einzelbilder and zeitdaten:
        raise ValueError("--aufnahmezeiten ist für eine gemeinsame Messreihe; nicht mit --einzelbilder verwenden.")
    if zeitdaten and not any(Path(p).name in zeitdaten for p in pfade):
        raise ValueError("Kein Dateiname aus der Zeitdatei passt zu den ausgewählten Bildern.")
    cv2.setNumThreads(2)
    return analysieren(pfade, ausgabe, manuell, einzelbilder, neue_referenz, zeitdaten)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ordner", nargs="?", help="Fotoordner oder einzelnes Foto")
    parser.add_argument("--lokal", metavar="PFAD", help="Fotoordner oder einzelnes Foto")
    parser.add_argument("--ausgabe", type=Path, help="Ausgabeordner für die Messreihe")
    parser.add_argument("--grafiken", action="store_true", help="Galerie aus vorhandenen Diagrammen öffnen")
    parser.add_argument("--ohne-browser", action="store_true", help="Mit --grafiken nur Galeriedaten aktualisieren")
    parser.add_argument("--einzelbilder", action="store_true", help="Unabhängige Fotos ohne gemeinsame Messreihe")
    parser.add_argument("--neue-referenz", action="store_true", help="Neue geeignete Referenz verlangen")
    parser.add_argument("--aufnahmezeiten", type=Path, metavar="CSV", help="Bekannte Aufnahmezeiten je Dateiname")
    parser.add_argument("--mm-pro-pixel", type=float, default=MM_PRO_PIXEL_MANUELL, help="Verifizierter Maßstab")
    args = parser.parse_args(argv)
    if args.grafiken:
        if args.ordner or args.lokal or args.aufnahmezeiten or args.einzelbilder or args.neue_referenz:
            parser.error("--grafiken liest vorhandene Diagramme; bitte separat ausführen.")
        return grafikansicht_anzeigen(args.ausgabe, args.ohne_browser)
    if args.mm_pro_pixel is not None and (not math.isfinite(args.mm_pro_pixel) or args.mm_pro_pixel <= 0):
        parser.error("--mm-pro-pixel muss positiv und endlich sein")
    lokal = Path(args.lokal or args.ordner or (PROJEKT_ORDNER/"bilder")).expanduser().resolve()
    ausgabe = args.ausgabe or (lokal.parent.parent if lokal.is_file() else lokal.parent)/"auswertung"
    try:
        pfade = [lokal] if lokal.is_file() else vorhandene_bilder(lokal)
        if not pfade:
            print(f"Keine Bilder gefunden in: {lokal}. Vorhandene Auswertung bleibt erhalten.")
            return 1
        lokale_auswertung(pfade, ausgabe, args.mm_pro_pixel, args.einzelbilder,
                          args.neue_referenz, args.aufnahmezeiten)
    except (OSError, ValueError) as fehler:
        print(f"Analyse abgebrochen: {fehler}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
