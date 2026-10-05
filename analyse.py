"""
BioBox - Bildanalyse (A-M2 Computer-Vision-Pipeline)

Aufruf:  python analyse.py bilder_demo            Ordner, auch mit Unterordnern
         python analyse.py bild.jpg               einzelnes Bild
         python analyse.py --kalibrieren ordner   fuer die spaetere Kamera

Aktuell: lokale Datensatzbilder. Kein Abruf vom Raspberry Pi.
Originalbilder werden nicht geloescht. Jedes Bild wird einzeln ausgewertet.
Grid-Kalibrierung und Grid-Massstab werden im Datensatzmodus nicht verwendet.
Ohne verifizierten Massstab bleiben cm2 und mm leer; Pixelwerte bleiben erhalten.
Keine Wachstumsrate oder relative Gesundheit zwischen verschiedenen Pflanzen.

Ausgabe im Ordner "auswertung":
    ergebnis.csv    eine Zeile je ausgewertetem Bild
    masken/         Segmentierungsmaske je Bild
    kontrolle/      Nur Kontur und erkannte Pflanzenflaeche je Bild
    grafiken/       alle 5 Dateien aus BB-REF-MERKMALE-001; fehlende Werte
                    werden erklaert, nicht als Null oder Messung erfunden

Grundlagen: BB-SPEC-IMG-001, BB-SPEC-HEALTH-001, BB-REF-MERKMALE-001.
Externe Einzelbilder erfuellen nicht die Aufnahmebedingungen einer BioBox-Zeitreihe.
Die vollstaendige Kamera-ROI, Homographie und Hoehenkorrektur folgen mit der Kamera.
"""

import csv
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

import cv2
import numpy as np

import gesundheit

# --- Einstellungen ---------------------------------------------------
# True: externe Testbilder, keine gemeinsame Zeitreihe oder Gesundheitsreferenz.
# False spaeter nur fuer EINE Pflanze mit fester Kamera und echten Aufnahmezeiten.
DATENSATZ_MODUS = True
BILDQUELLE = "externer_testdatensatz"
# Nur fuer eine spaetere, zusammengehoerige Messreihe aktivieren, nachdem
# die ersten Referenz-Kontrollbilder manuell gesichtet wurden (HEALTH-001, 4).
REFERENZ_FREIGEGEBEN = False

MARKER_MM = 40.0          # gemessene Kantenlaenge des gedruckten Markers
# Ersatzmassstab fuer Bilder ohne Marker, z. B. mit dem Lineal bestimmt.
# None = ohne Marker gibt es keine Flaeche in cm2, nur Pixel.
MM_PRO_PIXEL_MANUELL = None
SCHAERFE_MIN = 5.0        # Laplace-Varianz, im Testbetrieb anpassen
SPRUNG_MAX_PCT = 30.0     # groessere Flaechenaenderung je Bild ist verdaechtig
MIN_BLOB_PX = 30          # kleinere Flecken sind Rauschen

# --- Segmentierung ---------------------------------------------------
# Bei einem Datensatzordner mit *_top_* nur diese Draufsichten auswerten.
# Keine Annahme, dass Dateien einer Pflanze eine zeitliche Messreihe sind.
NUR_DRAUFSICHT = True
SEGMENTIERUNG_MAX_KANTE = 1280    # GrabCut-Arbeitsbild; Maske bleibt in Originalgroesse
GRABCUT_ITERATIONEN = 4
MORPH_KERN_PX = 3               # kleine Kerne erhalten Blattrand und duenne Stiele
ENTRAUSCHEN_PX = 3              # nur fuer Segmentierung, nie fuer Farbmerkmale
SEED_ABSTAND_PX = 18            # nahe Blattteile fuer die Suchregion verbinden
ROI_NORMIERT = None             # optional (links, oben, rechts, unten), jeweils 0..1

# Startpunkte nur aus erkennbarem Gruen; moegliche Blattfarben fuer GrabCut
# schliessen Gelb und Braun ein. Die endgueltige Maske ist kein HSV-Schwellwert.
SEED_HSV = ((25, 35, 18), (95, 255, 255))
SUCHFARBE_HSV = ((5, 25, 12), (100, 255, 255))

# Farbbereiche in HSV (OpenCV: H 0-179, S und V 0-255)
GELB_HSV = ((15, 60, 20), (33, 255, 255))
BRAUN_HSV = ((5, 40, 15), (20, 255, 160))

# Qualitaetspruefung
UEBERBELICHTET_MAX_PCT = 1.0  # mehr geklippte Pixel -> auffaellig
ZERSPLITTERT_MIN_PCT = 70     # groesste Teilflaeche darunter -> auffaellig

# Bilder ueberspringen: werden nicht ausgewertet und nicht in die CSV geschrieben
MIN_PFLANZE_PCT = 0.05        # weniger Pflanzenanteil am Bild -> keine Pflanze erkannt
MAX_RAUSCHEN = 25.0           # mehr Rauschen -> Erkennung unzuverlaessig (unter 80 % Treffer)

# Kontrollbilder sind reine Vorschauen; Farbwerte stammen immer vom Original.
AUSGABE = "auswertung"

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


# --- Zeitstempel -----------------------------------------------------
def zeit_aus_name(name):
    for muster, format_ in ZEITFORMATE:
        treffer = re.search(muster, name)
        if treffer:
            try:
                return datetime.strptime("".join(treffer.groups()), format_).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# --- Bildverarbeitung ------------------------------------------------
def marker_finden(bild):
    """Nur echte ArUco-Marker aus BB-SPEC-IMG-001, keine weissen Quadrate.

    Liefert einen Massstab in der MARKEREBENE. Keine Bestandshoehenkorrektur!
    Vier IDs 0..3 sind erforderlich; im Datensatzmodus wird dies nicht benutzt.
    """
    if not hasattr(cv2, "aruco"):
        return None, None
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector = cv2.aruco.ArucoDetector(dictionary)
    corners, ids, _ = detector.detectMarkers(bild)
    if ids is None:
        return None, None
    marker = {int(i): c.reshape(4, 2) for i, c in zip(ids.flatten(), corners)
              if int(i) in (0, 1, 2, 3)}
    if len(marker) != 4:
        return None, None
    kanten = [np.linalg.norm(c - np.roll(c, -1, axis=0), axis=1).mean()
              for c in marker.values()]
    if min(kanten) <= 0:
        return None, None
    x, y, w, h = cv2.boundingRect(np.vstack(list(marker.values())).astype(np.float32))
    return MARKER_MM / float(np.median(kanten)), (x, y, w, h)


def rauschen_schaetzen(bild):
    """Bildrauschen nach Immerkaer (1996). Reagiert kaum auf Kanten und
    Blattstrukturen, misst also tatsaechlich Sensorrauschen."""
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY).astype(np.float64)
    kern = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float64)
    h, w = grau.shape
    summe = np.abs(cv2.filter2D(grau, -1, kern)[1:-1, 1:-1]).sum()
    return float(np.sqrt(np.pi / 2) * summe / (6 * (w - 2) * (h - 2)))


def segmentieren(bild):
    """Farb-Seeds lokalisieren die Pflanze; GrabCut verfeinert ihre Kontur.

    Gruene Pixel sind Startpunkte, nicht die endgueltige Maske. Gelbe, braune
    oder beschattete Blattteile innerhalb der Suchregion duerfen hinzukommen.
    Kleine Luecken zwischen Blaettern werden NICHT pauschal gefuellt.
    Ein gruener Gegenstand weit neben der Pflanze wird als Hintergrund behandelt.
    Grenzen: Eine voellig braune Pflanze ohne gruene Seeds bleibt unerkennbar.
    """
    h0, w0 = bild.shape[:2]
    faktor = min(1.0, SEGMENTIERUNG_MAX_KANTE / max(h0, w0))
    arbeit = cv2.resize(bild, (max(3, round(w0*faktor)), max(3, round(h0*faktor))))
    if ENTRAUSCHEN_PX:
        arbeit = cv2.medianBlur(arbeit, ENTRAUSCHEN_PX)
    hsv = cv2.cvtColor(arbeit, cv2.COLOR_BGR2HSV)
    b, g, r = cv2.split(arbeit.astype(np.float32))
    exg = (2*g-r-b) / (r+g+b+1e-6)
    seeds = cv2.inRange(hsv, *SEED_HSV)
    seeds[exg < 0.08] = 0

    if ROI_NORMIERT is not None:
        links, oben, rechts, unten = ROI_NORMIERT
        roi = np.zeros_like(seeds)
        h, w = seeds.shape
        roi[round(oben*h):round(unten*h), round(links*w):round(rechts*w)] = 255
        seeds = cv2.bitwise_and(seeds, roi)
    else:
        roi = np.full_like(seeds, 255)

    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (MORPH_KERN_PX, MORPH_KERN_PX))
    seeds = cv2.morphologyEx(seeds, cv2.MORPH_OPEN, kern)
    # Groesste raeumliche Blattgruppe, nicht einfach nur das groesste Blatt.
    abstand = max(3, round(SEED_ABSTAND_PX*faktor))
    gruppe = cv2.dilate(seeds, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2*abstand+1, 2*abstand+1)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(gruppe, 8)
    if n <= 1:
        return np.zeros((h0, w0), np.uint8)
    haupt = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    seeds[labels != haupt] = 0
    if cv2.countNonZero(seeds) < max(10, round(MIN_BLOB_PX*faktor*faktor)):
        return np.zeros((h0, w0), np.uint8)

    # Konvexe SUCHREGION, keine konvexe Pflanzenmaske: GrabCut entfernt
    # Hintergrund und echte Zwischenraeume weiterhin innerhalb dieser Region.
    punkte = cv2.findNonZero(seeds)
    huelle = np.zeros_like(seeds)
    cv2.fillConvexPoly(huelle, cv2.convexHull(punkte), 255)
    suchregion = cv2.dilate(huelle, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2*abstand+1, 2*abstand+1)))
    suchregion = cv2.bitwise_and(suchregion, roi)
    sicher = cv2.erode(seeds, kern)
    if cv2.countNonZero(sicher) < 10:
        sicher = seeds

    maske_gc = np.full(seeds.shape, cv2.GC_BGD, np.uint8)
    maske_gc[suchregion > 0] = cv2.GC_PR_BGD
    pflanzenfarbe = cv2.inRange(hsv, *SUCHFARBE_HSV)
    maske_gc[(pflanzenfarbe > 0) & (suchregion > 0)] = cv2.GC_PR_FGD
    maske_gc[sicher > 0] = cv2.GC_FGD
    # Bei nahezu vollstaendigem Pflanzenbild fehlt ein Hintergrundmodell.
    if not np.any(maske_gc == cv2.GC_BGD):
        maske_gc[0, :] = cv2.GC_BGD
        maske_gc[-1, :] = cv2.GC_BGD
        maske_gc[:, 0] = cv2.GC_BGD
        maske_gc[:, -1] = cv2.GC_BGD
    cv2.setRNGSeed(0)  # reproduzierbare Segmentierung
    try:
        cv2.grabCut(arbeit, maske_gc, None, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), GRABCUT_ITERATIONEN,
                    cv2.GC_INIT_WITH_MASK)
        maske = np.where((maske_gc == cv2.GC_FGD) |
                         (maske_gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    except cv2.error as fehler:
        # Keine unmarkierte Ersatzmessung, wenn GrabCut nicht auswerten kann.
        print(f"   Segmentierung fehlgeschlagen: {str(fehler).splitlines()[0]}")
        return np.zeros((h0, w0), np.uint8)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, kern)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
    sauber = np.zeros_like(maske)
    for i in range(1, n):
        if (stats[i, cv2.CC_STAT_AREA] >= max(5, round(MIN_BLOB_PX*faktor*faktor))
                and np.any((labels == i) & (seeds > 0))):
            sauber[labels == i] = 255
    return cv2.resize(sauber, (w0, h0), interpolation=cv2.INTER_NEAREST)


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
    """Nur die bisherige obere rechte Ansicht: Kontur und Pflanzen-Overlay.

    Nur diese Vorschau wird verkleinert, nicht Maske oder Messbild.
    """
    overlay = bild.copy()
    m = maske > 0
    overlay[m] = (0.80*bild[m] + 0.20*np.array([180, 220, 20])).astype(np.uint8)
    konturen, _ = cv2.findContours(maske, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, konturen, -1, (255, 0, 255), max(1, round(bild.shape[1]/900)))
    if marker_box:
        x, y, w, h = marker_box
        cv2.rectangle(overlay, (x, y), (x+w, y+h), (255, 180, 0), 2)
    breite = min(720, bild.shape[1])
    hoehe = max(1, round(bild.shape[0]*breite/bild.shape[1]))
    kopf = 36
    panel = np.full((hoehe+kopf, breite, 3), 245, np.uint8)
    panel[kopf:] = cv2.resize(overlay, (breite, hoehe))
    cv2.putText(panel, "Kontur und erkannte Pflanzenflaeche", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, min(0.55, breite/1000),
                (35, 35, 35), 1, cv2.LINE_AA)
    cv2.imwrite(pfad, panel)


# --- Zeitreihe und Pruefung ------------------------------------------
def zeitreihe(zeilen, zeiten):
    """Stunden seit Start und Wachstumsrate. Grundlage fuer den Digital Twin."""
    echte_zeiten = [t for z, t in zip(zeilen, zeiten) if z["captured_at"]]
    start = min(echte_zeiten) if echte_zeiten else None
    vorher = None
    for z, t in zip(zeilen, zeiten):
        z["stunden_seit_start"] = None
        z["wachstumsrate_cm2_pro_tag"] = None
        z["_sprung_pct"] = None
        if not z["captured_at"] or start is None:
            continue
        z["stunden_seit_start"] = round((t-start).total_seconds()/3600, 4)
        flaeche = z["blattflaeche_cm2"]
        if not z["brauchbar"] or flaeche is None:
            continue
        if vorher:
            stunden = (t-vorher[0]).total_seconds()/3600
            delta = flaeche-vorher[1]
            if stunden > 0:
                z["wachstumsrate_cm2_pro_tag"] = round(delta/stunden*24, 3)
            if vorher[1] > 0:
                z["_sprung_pct"] = 100*delta/vorher[1]
        vorher = (t, flaeche)


def pruefen(zeilen):
    """Setzt die Spalten 'auffaelligkeit' und 'brauchbar'."""
    for z in zeilen:
        gruende = []
        if z["massstab_quelle"] == "" and not DATENSATZ_MODUS:
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
SPALTEN = (["bild", "ausgabe_stamm", "captured_at", "bildquelle", "analyse_modus", "stunden_seit_start", "zeitquelle",
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

    if DATENSATZ_MODUS and NUR_DRAUFSICHT and os.path.isdir(ziel):
        top = [p for p in pfade if re.search(r"_top_", os.path.basename(p), re.I)]
        if top:
            print(f"Draufsicht-Filter: {len(top)} Bilder, {len(pfade)-len(top)} andere Ansichten ausgelassen")
            pfade = top

    bilder = []
    for pfad in pfade:
        # Relativer Pfad unterscheidet gleichnamige Bilder in Unterordnern.
        name = (os.path.relpath(pfad, ziel) if os.path.isdir(ziel)
                else os.path.basename(pfad)).replace(os.sep, "/")
        zeit = None if DATENSATZ_MODUS else zeit_aus_name(os.path.basename(name))
        quelle = "keine_aufnahmezeit" if DATENSATZ_MODUS else "name"
        if not DATENSATZ_MODUS and zeit is None:
            quelle = "dateidatum"
            zeit = datetime.fromtimestamp(os.path.getmtime(pfad), timezone.utc)
        bilder.append((zeit, name, quelle, pfad))
    def namensschluessel(name):
        return tuple((0, int(t)) if t.isdigit() else (1, t.lower())
                     for t in re.split(r"(\d+)", name))
    bilder.sort(key=lambda b: namensschluessel(b[1]) if DATENSATZ_MODUS
                else (b[0], namensschluessel(b[1])))

    # Erst aufraeumen, dann pruefen: auch bei null Bildern darf nichts
    # aus einem frueheren Lauf stehen bleiben.
    ordner_maske = os.path.join(AUSGABE, "masken")
    ordner_kontrolle = os.path.join(AUSGABE, "kontrolle")
    csv_pfad = os.path.join(AUSGABE, "ergebnis.csv")
    os.makedirs(ordner_maske, exist_ok=True)
    os.makedirs(ordner_kontrolle, exist_ok=True)

    alt = (glob.glob(f"{ordner_maske}/*.png")
           + glob.glob(f"{ordner_kontrolle}/*.png")
           + glob.glob(os.path.join(AUSGABE, "grafiken", "*.png")))
    if os.path.exists(csv_pfad):
        alt.append(csv_pfad)
    for f in alt:
        os.remove(f)
    if alt:
        print(f"{len(alt)} alte Ausgabedatei(en) geloescht\n")

    if not bilder:
        print("keine Bilder gefunden in:", ziel)
        return

    kalibrierung = None if DATENSATZ_MODUS else kalibrierung_laden()
    if DATENSATZ_MODUS:
        print("Datensatzmodus: lokale Einzelbilder, ohne Kamera-Kalibrierung")
    else:
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

        if min(bild.shape[:2]) < 3:
            print(f"{kopf} uebersprungen: Bild zu klein")
            uebersprungen.append((name, "Bild zu klein"))
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
        # Ein weisses Quadrat im Datensatz ist kein verifizierter 40-mm-Marker.
        mm_px, marker_box = (None, None) if DATENSATZ_MODUS else marker_finden(bild)
        quelle_massstab = "marker" if mm_px else ""
        if mm_px is None and MM_PRO_PIXEL_MANUELL:
            mm_px = MM_PRO_PIXEL_MANUELL
            quelle_massstab = "manuell"

        ausgabename = f"{i:05d}_{os.path.splitext(os.path.basename(pfad))[0]}"
        cv2.imwrite(f"{ordner_maske}/{ausgabename}_maske.png", maske)
        kontrollbild(bild, maske, marker_box,
                     f"{ordner_kontrolle}/{ausgabename}_kontrolle.png")

        z = {"bild": name, "ausgabe_stamm": ausgabename,
             "captured_at": zeit.isoformat().replace("+00:00", "Z") if zeit and quelle == "name" else "",
             "zeitquelle": quelle, "massstab_quelle": quelle_massstab,
             "bildquelle": BILDQUELLE if DATENSATZ_MODUS else "lokale_kameraaufnahme",
             "analyse_modus": "datensatz" if DATENSATZ_MODUS else "zeitreihe",
             **merkmale(bild, maske, mm_px), "rauschen": round(rauschen, 1)}
        zeilen.append(z)
        zeiten.append(zeit)
        flaeche = z["blattflaeche_cm2"]
        info = f"{flaeche} cm2" if flaeche else f"{z['pflanzen_pixel']} px (kein Massstab)"
        print(f"{kopf} {info}")

    if not zeilen:
        print(f"\nalle {len(bilder)} Bilder uebersprungen - nichts auszuwerten")
        return

    # Qualitaet vor zeitlichen Vergleichen pruefen: unbrauchbare Bilder
    # duerfen keine Vergleichsflaeche fuer spaetere Aufnahmen liefern.
    for z in zeilen:
        z["_sprung_pct"] = None
    pruefen(zeilen)
    if DATENSATZ_MODUS:
        for z in zeilen:
            z["stunden_seit_start"] = None
            z["wachstumsrate_cm2_pro_tag"] = None
            z["_sprung_pct"] = None
    else:
        zeitreihe(zeilen, zeiten)
    pruefen(zeilen)
    referenz = gesundheit.bewerten(zeilen, zeitreihe_aktiv=not DATENSATZ_MODUS,
                                    referenz_freigegeben=REFERENZ_FREIGEGEBEN)

    with open(csv_pfad, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SPALTEN, extrasaction="ignore")
        w.writeheader()
        w.writerows(zeilen)

    print(f"\n{len(zeilen)} Bilder ausgewertet -> {AUSGABE}/ergebnis.csv")
    if uebersprungen:
        print(f"{len(uebersprungen)} Bild(er) uebersprungen und nicht verwendet")

    ohne_name = sum(1 for z in zeilen if z["zeitquelle"] == "dateidatum")
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

    if DATENSATZ_MODUS:
        print("Datensatz: Pixel- und Farbwerte; keine gemeinsame Wachstums- oder Gesundheitszeitreihe")

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
            grafiken.main(csv_pfad=csv_pfad, ordner=os.path.join(AUSGABE, "grafiken"))
        except ImportError:
            print("matplotlib fehlt - 'pip install matplotlib', "
                  "dann 'python grafiken.py'")


if __name__ == "__main__":
    main()
