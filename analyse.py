"""
BioBox - Bildanalyse (A-M2 Computer-Vision-Pipeline)

Aufruf:  python analyse.py bilder                 Ordner, auch mit Unterordnern
         python analyse.py bild.jpg               einzelnes Bild
         python analyse.py --kalibrieren ordner   Entzerrung einmalig bestimmen

Ausgabe im Ordner "auswertung":
    ergebnis.csv    eine Zeile je Bild, Messwerte und Gesundheitsbewertung
    masken/         Segmentierungsmaske je Bild
    kontrolle/      Bild mit eingezeichneter Kontur je Bild
    grafiken/       Diagramme, sofern GRAFIKEN_ERSTELLEN = True

# Entzerrung. Pflicht bei der Wide-Optik (BB-SPEC-IMG-001, 4.6), weil eine
# Flaeche am Bildrand sonst anders gemessen wird als in der Bildmitte.
# Datei anlegen mit:  python analyse.py --kalibrieren schachbrett/
KALIBRIERUNG = "kamera_kalibrierung.json"
SCHACHBRETT = (9, 6)      # Innenecken, nicht Felder
FELD_MM = 25.0

Sollen die Bilder automatisch vom Raspberry Pi geholt werden, PI_HOST unten
eintragen. Vorhandene Bilder werden dabei nicht erneut geladen.

Der Dateiname muss Datum und Uhrzeit enthalten, z. B.
    biobox01_20260930T081500Z.jpg
Ohne erkennbaren Zeitstempel wird das Dateidatum verwendet.
"""

import csv
import glob
import json
import subprocess
import os
import re
import sys
from datetime import datetime

import cv2
import numpy as np

import gesundheit

# --- Einstellungen ---------------------------------------------------
MARKER_MM = 40.0          # gemessene Kantenlaenge des gedruckten Markers
# Ersatzmassstab fuer Bilder ohne Marker, z. B. mit dem Lineal bestimmt.
# None = ohne Marker gibt es keine Flaeche in cm2, nur Pixel.
MM_PRO_PIXEL_MANUELL = 0.1519
SCHAERFE_MIN = 5.0        # Laplace-Varianz, im Testbetrieb anpassen
SPRUNG_MAX_PCT = 30.0     # groessere Flaechenaenderung je Bild ist verdaechtig
MIN_BLOB_PX = 50          # kleinere Flecken sind Rauschen

# --- Kalibrierung (Demo-Modus: alles hier anpassen, nichts im Code darunter) ---
# Marker-Erkennung
MARKER_HELLIGKEIT = 180       # Grauwert, ab dem ein Pixel als Marker-Weiss gilt
MARKER_MIN_FLAECHE = 200      # kleinere helle Flecken ignorieren (px)
MARKER_MAX_ANTEIL = 0.4       # groesser als 40 % der Bildbreite -> kein Marker
MARKER_FORM_TOLERANZ = 0.15   # erlaubte Abweichung vom Quadrat
MARKER_MIN_FUELLGRAD = 0.85   # Anteil der Umrissbox, der hell sein muss

# Segmentierung
MORPH_KERN_PX = 5             # Glaettung der Maske; bei hoeherer Aufloesung vergroessern
ENTRAUSCHEN_PX = 7            # Medianfilter gegen Nachtrauschen (ungerade), 0 = aus

# Pflanzenfarbe: nur Pixel in diesem Bereich koennen Pflanze sein.
# Gelb (ab H 15) ist ABSICHTLICH eingeschlossen - sonst verschwindet
# vergilbtes Gewebe aus der Maske und die Gesundheitsbewertung sieht
# keine Vergilbung mehr. Fuer "nur reines Gruen": PFLANZE_H_MIN = 35.
PFLANZE_H_MIN = 15            # Gelb beginnt bei ca. 15
PFLANZE_H_MAX = 90            # Blaugruen endet bei ca. 90, Topf liegt bei 105
PFLANZE_S_MIN = 40            # darunter Grau/Weiss: Topf, Kabel, Rauschen
PFLANZE_V_MIN = 30            # darunter zu dunkel fuer eine Farbaussage

# Farbbereiche in HSV (OpenCV: H 0-179, S und V 0-255)
GELB_HSV = ((15, 60, 20), (33, 255, 255))
BRAUN_HSV = ((5, 40, 15), (20, 255, 160))

# Qualitaetspruefung
UEBERBELICHTET_MAX_PCT = 1.0  # mehr geklippte Pixel -> auffaellig
ZERSPLITTERT_MIN_PCT = 70     # groesste Teilflaeche darunter -> auffaellig

# Bilder ueberspringen: werden nicht ausgewertet und nicht in die CSV geschrieben
MIN_PFLANZE_PCT = 0.05        # weniger Pflanzenanteil am Bild -> keine Pflanze erkannt
MAX_RAUSCHEN = 25.0           # mehr Rauschen -> Erkennung unzuverlaessig (unter 80 % Treffer)

# Kontrollbild: dunkle Bilder werden zum Anschauen aufgehellt, helle nicht
KONTROLLE_ZIELHELLIGKEIT = 110
KONTROLLE_MAX_AUFHELLUNG = 3.0
AUSGABE = "auswertung"

# Bilder automatisch vom Raspberry Pi holen.
# PI_HOST leer lassen, wenn die Bilder schon lokal liegen.
PI_HOST = "gridiii@100.82.28.104"     # leer lassen = nicht abholen
PI_ORDNER = "~/biobox/captures"

# Nur die neuesten N Bilder behalten. Aeltere werden lokal geloescht und
# nicht erneut vom Pi geholt. 0 = alle behalten.
MAX_BILDER = 100

# Diagramme direkt im Anschluss erzeugen. False = nur analysieren,
# grafiken.py laesst sich weiterhin einzeln aufrufen.
GRAFIKEN_ERSTELLEN = True

# Entzerrung. Pflicht bei der Wide-Optik (BB-SPEC-IMG-001, 4.6), weil eine
# Flaeche am Bildrand sonst anders gemessen wird als in der Bildmitte.
# Datei anlegen mit:  python analyse.py --kalibrieren schachbrett/
KALIBRIERUNG = "kamera_kalibrierung.json"
SCHACHBRETT = (9, 6)      # Innenecken, nicht Felder
FELD_MM = 25.0

ENDUNGEN = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

# Erkannte Zeitformate im Dateinamen, genauestes zuerst
ZEITFORMATE = [
    (r"(\d{8})[T_-](\d{6})", "%Y%m%d%H%M%S"),
    (r"(\d{8})[T_-](\d{4})(?!\d)", "%Y%m%d%H%M"),
    (r"(\d{4}-\d{2}-\d{2})[T_ ](\d{2})[-.](\d{2})[-.](\d{2})", "%Y-%m-%d%H%M%S"),
    (r"(\d{4}-\d{2}-\d{2})[T_ ](\d{2})[-.](\d{2})(?![-.\d])", "%Y-%m-%d%H%M"),
    (r"(\d{4}-\d{2}-\d{2})(?!\d)", "%Y-%m-%d"),
    (r"(\d{8})(?!\d)", "%Y%m%d"),
]


# --- Alte Bilder aussortieren ----------------------------------------
def sortiert_nach_zeit(namen):
    """Sortiert Dateinamen nach dem Zeitstempel im Namen, aeltestes zuerst."""
    def schluessel(n):
        zeit = zeit_aus_name(os.path.splitext(n)[0])
        return (zeit is not None, zeit or datetime.min, n)
    return sorted(namen, key=schluessel)


def alte_bilder_loeschen(ordner):
    """Behaelt nur die neuesten MAX_BILDER Aufnahmen im Bilderordner."""
    if not MAX_BILDER or not os.path.isdir(ordner):
        return
    namen = [n for n in os.listdir(ordner) if n.lower().endswith(ENDUNGEN)]
    if len(namen) <= MAX_BILDER:
        return
    alt = sortiert_nach_zeit(namen)[:-MAX_BILDER]
    for n in alt:
        os.remove(os.path.join(ordner, n))
    print(f"{len(alt)} aelteres Bild(er) geloescht, "
          f"die neuesten {MAX_BILDER} bleiben\n")


# --- Entzerrung ------------------------------------------------------
def kalibrierung_laden():
    """Liest die Kalibrierdatei, falls vorhanden."""
    if not os.path.exists(KALIBRIERUNG):
        return None
    d = json.load(open(KALIBRIERUNG))
    return np.array(d["kamera_matrix"]), np.array(d["verzeichnung"])


def entzerren(bild, kalibrierung):
    if kalibrierung is None:
        return bild
    matrix, verzeichnung = kalibrierung
    return cv2.undistort(bild, matrix, verzeichnung)


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
        groesse = grau.shape[::-1]
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
               "verzeichnung": verzeichnung.tolist(),
               "bilder": len(welt),
               "reprojektionsfehler_px": round(float(fehler), 4)},
              open(KALIBRIERUNG, "w"), indent=2)

    print(f"\n{len(welt)} Aufnahmen verwendet")
    print(f"Reprojektionsfehler: {fehler:.3f} px (unter 1.0 ist gut)")
    print(f"gespeichert in {KALIBRIERUNG}")


# --- Bilder vom Pi holen ---------------------------------------------
def bilder_holen(ordner):
    """Laedt neue Bilder vom Pi. Vorhandene werden nicht erneut geladen."""
    if not PI_HOST:
        return

    print(f"Verbinde mit {PI_HOST} ...")
    try:
        antwort = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             PI_HOST, f"ls {PI_ORDNER}"],
            capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError) as fehler:
        print(f"   nicht erreichbar ({fehler}) - arbeite mit lokalen Bildern\n")
        return

    if antwort.returncode != 0:
        print(f"   Fehler: {antwort.stderr.strip()}")
        print("   arbeite mit lokalen Bildern\n")
        return

    fern = [n for n in antwort.stdout.split() if n.lower().endswith(ENDUNGEN)]
    fern = sortiert_nach_zeit(fern)
    gesamt = len(fern)
    if MAX_BILDER:
        fern = fern[-MAX_BILDER:]          # nur die neuesten holen

    os.makedirs(ordner, exist_ok=True)
    vorhanden = set(os.listdir(ordner))
    neu = [n for n in fern if n not in vorhanden]

    if not neu:
        print(f"   {gesamt} Bilder auf dem Pi, alle benoetigten bereits lokal\n")
        return

    print(f"   {len(neu)} neue Bild(er) werden geladen")
    geladen = 0
    for i, name in enumerate(neu, 1):
        ergebnis = subprocess.run(
            ["scp", "-q", f"{PI_HOST}:{PI_ORDNER}/{name}", ordner])
        if ergebnis.returncode == 0:
            geladen += 1
        print(f"\r   {i}/{len(neu)}", end="", flush=True)
    print(f"\r   {geladen} von {len(neu)} geladen")
    if MAX_BILDER and gesamt > MAX_BILDER:
        print(f"   (von {gesamt} Bildern auf dem Pi nur die neuesten {MAX_BILDER})")
    print()


# --- Zeitstempel -----------------------------------------------------
def zeit_aus_name(name):
    for muster, format_ in ZEITFORMATE:
        treffer = re.search(muster, name)
        if treffer:
            try:
                return datetime.strptime("".join(treffer.groups()), format_)
            except ValueError:
                continue
    return None


# --- Bildverarbeitung ------------------------------------------------
def marker_finden(bild):
    """Sucht den hellen quadratischen Marker, liefert mm pro Pixel."""
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    _, hell = cv2.threshold(grau, MARKER_HELLIGKEIT, 255, cv2.THRESH_BINARY)
    konturen, _ = cv2.findContours(hell, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for k in konturen:
        flaeche = cv2.contourArea(k)
        if flaeche < MARKER_MIN_FLAECHE:
            continue
        x, y, b, h = cv2.boundingRect(k)
        if b > bild.shape[1] * MARKER_MAX_ANTEIL or h > bild.shape[0] * MARKER_MAX_ANTEIL:
            continue                                   # zu gross -> Fehlerkennung
        if (abs(b / h - 1) < MARKER_FORM_TOLERANZ
                and flaeche / (b * h) > MARKER_MIN_FUELLGRAD):
            return MARKER_MM / ((b + h) / 2), (x, y, b, h)
    return None, None


def rauschen_schaetzen(bild):
    """Bildrauschen nach Immerkaer (1996). Reagiert kaum auf Kanten und
    Blattstrukturen, misst also tatsaechlich Sensorrauschen."""
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY).astype(np.float64)
    kern = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float64)
    h, w = grau.shape
    summe = np.abs(cv2.filter2D(grau, -1, kern)[1:-1, 1:-1]).sum()
    return float(np.sqrt(np.pi / 2) * summe / (6 * (w - 2) * (h - 2)))


def segmentieren(bild):
    """Pflanzenpixel muessen ZWEI Bedingungen erfuellen:
    1. gruener als der Rest des Bildes (Excess Green + Otsu, relativ)
    2. tatsaechlich pflanzenfarben (HSV-Bereich, absolut)

    Otsu allein teilt JEDES Bild in zwei Gruppen - auch reines Rauschen
    bei Nacht. Die Farbbedingung verhindert, dass dann Rauschen als
    Pflanze gezaehlt wird.
    """
    if ENTRAUSCHEN_PX:
        bild = cv2.medianBlur(bild, ENTRAUSCHEN_PX)

    b, g, r = cv2.split(bild.astype(np.float32))
    exg = cv2.normalize(2 * g - r - b, None, 0, 255, cv2.NORM_MINMAX)
    _, relativ = cv2.threshold(exg.astype(np.uint8), 0, 255,
                               cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
    absolut = cv2.inRange(hsv, (PFLANZE_H_MIN, PFLANZE_S_MIN, PFLANZE_V_MIN),
                          (PFLANZE_H_MAX, 255, 255))
    maske = cv2.bitwise_and(relativ, absolut)

    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (MORPH_KERN_PX, MORPH_KERN_PX))
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, kern)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, kern)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
    sauber = np.zeros_like(maske)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= MIN_BLOB_PX:
            sauber[labels == i] = 255
    return sauber


def merkmale(bild, maske, mm_px):
    """Die 20 Messwerte eines Bildes."""
    w = {}
    pixel = cv2.countNonZero(maske)
    w["pflanzen_pixel"] = pixel

    if pixel:
        konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        umfang = sum(cv2.arcLength(k, True) for k in konturen)
        _, _, bb, bh = cv2.boundingRect(np.vstack(konturen))

        w["blattflaeche_cm2"] = round(pixel * mm_px ** 2 / 100, 2) if mm_px else None
        w["durchmesser_mm"] = round(max(bb, bh) * mm_px, 1) if mm_px else None
        # Kompaktheit: 1.0 = Kreis, kleiner = zerklueftet. Reagiert auf Welken.
        w["kompaktheit"] = round(4 * np.pi * pixel / umfang ** 2, 4) if umfang else None

        n, _, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
        w["groesste_komponente_pct"] = round(
            100 * max(stats[1:, cv2.CC_STAT_AREA]) / pixel, 1) if n > 1 else None

        m = maske > 0
        b, g, r = cv2.split(bild.astype(np.float32))
        w["mittel_r"] = round(float(r[m].mean()), 1)
        w["mittel_g"] = round(float(g[m].mean()), 1)
        w["mittel_b"] = round(float(b[m].mean()), 1)
        w["farbe_hex"] = "#{:02x}{:02x}{:02x}".format(
            round(w["mittel_r"]), round(w["mittel_g"]), round(w["mittel_b"]))

        hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
        h_, s_, _ = cv2.split(hsv.astype(np.float32))
        w["mittel_h"] = round(float(h_[m].mean()), 1)
        w["mittel_s"] = round(float(s_[m].mean()), 1)
        w["gruenindex"] = round(float((g / (b + g + r + 1e-6))[m].mean()), 4)

        gelb = cv2.bitwise_and(cv2.inRange(hsv, *GELB_HSV), maske)
        braun = cv2.bitwise_and(cv2.inRange(hsv, *BRAUN_HSV), maske)
        w["gelbanteil_pct"] = round(100 * cv2.countNonZero(gelb) / pixel, 2)
        w["braunanteil_pct"] = round(100 * cv2.countNonZero(braun) / pixel, 2)
    else:
        for k in ["blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
                  "groesste_komponente_pct", "mittel_r", "mittel_g", "mittel_b", "farbe_hex",
                  "mittel_h", "mittel_s", "gruenindex",
                  "gelbanteil_pct", "braunanteil_pct"]:
            w[k] = None

    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(grau, cv2.CV_64F)
    # Schaerfe nur auf der Pflanze - der dunkle Hintergrund liesse sonst
    # jedes Bild unscharf erscheinen.
    w["schaerfe"] = round(float(lap[maske > 0].var()), 1) if pixel else None
    w["bildhelligkeit"] = round(float(grau.mean()), 1)
    w["ueberbelichtet_pct"] = round(
        100 * float((bild[:, :, 1] > 250).sum()) / grau.size, 2)
    w["mm_pro_pixel"] = round(mm_px, 4) if mm_px else None
    return w


def kontrollbild(bild, maske, marker_box, pfad):
    """Bild mit eingezeichneter Kontur zur Sichtpruefung."""
    # Nur dunkle Bilder aufhellen. Feste 3-fache Aufhellung machte helle
    # Tageslichtbilder zu 70 % reinweiss und damit unbrauchbar.
    mittel = max(float(bild.mean()), 1.0)
    faktor = min(KONTROLLE_MAX_AUFHELLUNG, max(1.0, KONTROLLE_ZIELHELLIGKEIT / mittel))
    anzeige = cv2.convertScaleAbs(bild, alpha=faktor)
    konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(anzeige, konturen, -1, (0, 0, 255), 2)
    if marker_box:
        x, y, b, h = marker_box
        cv2.rectangle(anzeige, (x, y), (x + b, y + h), (255, 0, 0), 2)
    cv2.imwrite(pfad, anzeige)


# --- Zeitreihe und Pruefung ------------------------------------------
def zeitreihe(zeilen, zeiten):
    """Stunden seit Start und Wachstumsrate. Grundlage fuer den Digital Twin."""
    start, vorher = zeiten[0], None
    for z, t in zip(zeilen, zeiten):
        z["stunden_seit_start"] = round((t - start).total_seconds() / 3600, 2)
        z["wachstumsrate_cm2_pro_tag"] = None
        z["_sprung_pct"] = None

        flaeche = z["blattflaeche_cm2"]
        if flaeche is not None and vorher:
            stunden = (t - vorher[0]).total_seconds() / 3600
            delta = flaeche - vorher[1]
            if stunden > 0:
                z["wachstumsrate_cm2_pro_tag"] = round(delta / stunden * 24, 3)
            if vorher[1] > 0:
                z["_sprung_pct"] = 100 * delta / vorher[1]
        if flaeche is not None:
            vorher = (t, flaeche)


def pruefen(zeilen):
    """Setzt die Spalten 'auffaelligkeit' und 'brauchbar'."""
    for z in zeilen:
        gruende = []
        if z["massstab_quelle"] == "":
            gruende.append("kein_marker")
        if not z["pflanzen_pixel"]:
            gruende.append("keine_pflanze")
        if z["schaerfe"] is not None and z["schaerfe"] < SCHAERFE_MIN:
            gruende.append("unscharf")
        if z["ueberbelichtet_pct"] > UEBERBELICHTET_MAX_PCT:
            gruende.append("ueberbelichtet")
        if z["groesste_komponente_pct"] is not None and z["groesste_komponente_pct"] < ZERSPLITTERT_MIN_PCT:
            gruende.append("zersplittert")
        if z["_sprung_pct"] is not None and abs(z["_sprung_pct"]) > SPRUNG_MAX_PCT:
            gruende.append("flaechensprung")
        z["auffaelligkeit"] = ";".join(gruende)
        z["brauchbar"] = not gruende


# --- Spaltenreihenfolge der CSV --------------------------------------
SPALTEN = (["bild", "stunden_seit_start", "zeitquelle",
            "pflanzen_pixel", "blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
            "wachstumsrate_cm2_pro_tag",
            "mittel_r", "mittel_g", "mittel_b", "farbe_hex", "mittel_h", "mittel_s",
            "gruenindex", "gelbanteil_pct", "braunanteil_pct",
            "mm_pro_pixel", "massstab_quelle", "schaerfe", "rauschen", "bildhelligkeit", "ueberbelichtet_pct",
            "groesste_komponente_pct", "auffaelligkeit", "brauchbar"]
           + gesundheit.SPALTEN)


# --- Hauptprogramm ---------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == "--kalibrieren":
        if len(sys.argv) < 3:
            print("Aufruf: python analyse.py --kalibrieren schachbrett/")
        else:
            kalibrieren(sys.argv[2])
        return

    ziel = sys.argv[1]

    if os.path.isdir(ziel) or not os.path.exists(ziel):
        bilder_holen(ziel)
        alte_bilder_loeschen(ziel)

    if os.path.isfile(ziel):
        pfade = [ziel]
    elif os.path.isdir(ziel):
        pfade = []
        for wurzel, ordner, namen in os.walk(ziel):
            ordner[:] = [o for o in ordner if o != AUSGABE]
            pfade += [os.path.join(wurzel, n) for n in namen
                      if n.lower().endswith(ENDUNGEN)]
    else:
        print("nicht gefunden:", ziel)
        return

    bilder = []
    for pfad in pfade:
        name = os.path.splitext(os.path.basename(pfad))[0]
        zeit = zeit_aus_name(name)
        quelle = "name" if zeit else "dateidatum"
        if zeit is None:
            zeit = datetime.fromtimestamp(os.path.getmtime(pfad))
        bilder.append((zeit, name, quelle, pfad))
    bilder.sort()

    # Erst aufraeumen, dann pruefen: auch bei null Bildern darf nichts
    # aus einem frueheren Lauf stehen bleiben.
    ordner_maske = os.path.join(AUSGABE, "masken")
    ordner_kontrolle = os.path.join(AUSGABE, "kontrolle")
    csv_pfad = os.path.join(AUSGABE, "ergebnis.csv")
    os.makedirs(ordner_maske, exist_ok=True)
    os.makedirs(ordner_kontrolle, exist_ok=True)

    alt = glob.glob(f"{ordner_maske}/*.png") + glob.glob(f"{ordner_kontrolle}/*.png")
    if os.path.exists(csv_pfad):
        alt.append(csv_pfad)
    for f in alt:
        os.remove(f)
    if alt:
        print(f"{len(alt)} alte Ausgabedatei(en) geloescht\n")

    if not bilder:
        print("keine Bilder gefunden in:", ziel)
        return

    kalibrierung = kalibrierung_laden()
    print("Entzerrung aktiv" if kalibrierung else
          f"Entzerrung inaktiv ({KALIBRIERUNG} fehlt)")

    zeilen, zeiten, uebersprungen = [], [], []
    for i, (zeit, name, quelle, pfad) in enumerate(bilder, 1):
        kopf = f"[{i}/{len(bilder)}] {name:38s}"
        bild = cv2.imread(pfad)
        if bild is None:
            print(f"{kopf} nicht lesbar")
            uebersprungen.append((name, "nicht lesbar"))
            continue

        # Rauschen am Originalbild messen, vor Entzerrung und Filterung
        rauschen = rauschen_schaetzen(bild)
        if rauschen > MAX_RAUSCHEN:
            print(f"{kopf} uebersprungen: zu verrauscht ({rauschen:.1f})")
            uebersprungen.append((name, f"zu verrauscht ({rauschen:.1f})"))
            continue

        bild = entzerren(bild, kalibrierung)
        maske = segmentieren(bild)
        anteil = 100 * cv2.countNonZero(maske) / maske.size
        if anteil < MIN_PFLANZE_PCT:
            print(f"{kopf} uebersprungen: keine Pflanze erkannt ({anteil:.2f} %)")
            uebersprungen.append((name, f"keine Pflanze erkannt ({anteil:.2f} %)"))
            continue

        # Erst jetzt steht fest, dass das Bild verwendet wird
        mm_px, marker_box = marker_finden(bild)
        quelle_massstab = "marker" if mm_px else ""
        if mm_px is None and MM_PRO_PIXEL_MANUELL:
            mm_px = MM_PRO_PIXEL_MANUELL
            quelle_massstab = "manuell"

        cv2.imwrite(f"{ordner_maske}/{name}_maske.png", maske)
        kontrollbild(bild, maske, marker_box, f"{ordner_kontrolle}/{name}_kontrolle.png")

        z = {"bild": name, "zeitquelle": quelle, "massstab_quelle": quelle_massstab,
             **merkmale(bild, maske, mm_px), "rauschen": round(rauschen, 1)}
        zeilen.append(z)
        zeiten.append(zeit)
        flaeche = z["blattflaeche_cm2"]
        info = f"{flaeche} cm2" if flaeche else f"{z['pflanzen_pixel']} px (kein Massstab)"
        print(f"{kopf} {info}")

    if not zeilen:
        print(f"\nalle {len(bilder)} Bilder uebersprungen - nichts auszuwerten")
        return

    zeitreihe(zeilen, zeiten)
    pruefen(zeilen)
    referenz = gesundheit.bewerten(zeilen)

    with open(csv_pfad, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SPALTEN, extrasaction="ignore")
        w.writeheader()
        w.writerows(zeilen)

    print(f"\n{len(zeilen)} Bilder ausgewertet -> {AUSGABE}/ergebnis.csv")
    if uebersprungen:
        print(f"{len(uebersprungen)} Bild(er) uebersprungen und nicht verwendet")

    ohne_name = sum(1 for z in zeilen if z["zeitquelle"] != "name")
    if ohne_name:
        print(f"HINWEIS: {ohne_name} Bild(er) ohne Zeitstempel im Namen "
              f"-> Dateidatum verwendet, siehe Spalte 'zeitquelle'")

    schlecht = [z for z in zeilen if not z["brauchbar"]]
    if schlecht:
        print(f"\n{len(schlecht)} von {len(zeilen)} Bild(ern) auffaellig:")
        for z in schlecht[:8]:
            print(f"   {z['bild']:38s} {z['auffaelligkeit']}")
        if len(schlecht) > 8:
            print(f"   ... und {len(schlecht) - 8} weitere")

    if referenz:
        bewertet = [z for z in zeilen if z["gesundheit"] is not None]
        if bewertet:
            letzte = bewertet[-1]
            print(f"\nReferenz aus {referenz['bilder']} Bildern")
            print(f"Gesundheit aktuell: {letzte['gesundheit']}/100 "
                  f"({letzte['gesundheit_kategorie']})")

    if GRAFIKEN_ERSTELLEN:
        print()
        try:
            import grafiken
            grafiken.main()
        except ImportError:
            print("matplotlib fehlt - 'pip install matplotlib', "
                  "dann 'python grafiken.py'")


if __name__ == "__main__":
    main()
