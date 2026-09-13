"""
BioBox - Bildanalyse (A-M2 Computer-Vision-Pipeline)

Aufruf:  python analyse.py bilder      Ordner, auch mit Unterordnern
         python analyse.py bild.jpg    einzelnes Bild

Ausgabe im Ordner "auswertung":
    ergebnis.csv    eine Zeile je Bild, Messwerte und Gesundheitsbewertung
    masken/         Segmentierungsmaske je Bild
    kontrolle/      Bild mit eingezeichneter Kontur je Bild

Der Dateiname muss Datum und Uhrzeit enthalten, z. B.
    biobox01_20260930T081500Z.jpg
Ohne erkennbaren Zeitstempel wird das Dateidatum verwendet.
"""

import csv
import glob
import os
import re
import sys
from datetime import datetime

import cv2
import numpy as np

import gesundheit

# --- Einstellungen ---------------------------------------------------
MARKER_MM = 40.0          # gemessene Kantenlaenge des gedruckten Markers
SCHAERFE_MIN = 5.0        # Laplace-Varianz, im Testbetrieb anpassen
SPRUNG_MAX_PCT = 30.0     # groessere Flaechenaenderung je Bild ist verdaechtig
MIN_BLOB_PX = 50          # kleinere Flecken sind Rauschen
AUSGABE = "auswertung"
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
    _, hell = cv2.threshold(grau, 180, 255, cv2.THRESH_BINARY)
    konturen, _ = cv2.findContours(hell, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for k in konturen:
        flaeche = cv2.contourArea(k)
        if flaeche < 200:
            continue
        x, y, b, h = cv2.boundingRect(k)
        if b > bild.shape[1] * 0.4 or h > bild.shape[0] * 0.4:
            continue                                   # zu gross -> Fehlerkennung
        if 0.85 < b / h < 1.15 and flaeche / (b * h) > 0.85:
            return MARKER_MM / ((b + h) / 2), (x, y, b, h)
    return None, None


def segmentieren(bild):
    """Trennt gruene Pflanzenpixel vom Hintergrund (Excess Green + Otsu)."""
    b, g, r = cv2.split(bild.astype(np.float32))
    exg = cv2.normalize(2 * g - r - b, None, 0, 255, cv2.NORM_MINMAX)
    _, maske = cv2.threshold(exg.astype(np.uint8), 0, 255,
                             cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
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

        hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
        h_, s_, _ = cv2.split(hsv.astype(np.float32))
        w["mittel_h"] = round(float(h_[m].mean()), 1)
        w["mittel_s"] = round(float(s_[m].mean()), 1)
        w["gruenindex"] = round(float((g / (b + g + r + 1e-6))[m].mean()), 4)

        gelb = cv2.bitwise_and(cv2.inRange(hsv, (15, 60, 20), (33, 255, 255)), maske)
        braun = cv2.bitwise_and(cv2.inRange(hsv, (5, 40, 15), (20, 255, 160)), maske)
        w["gelbanteil_pct"] = round(100 * cv2.countNonZero(gelb) / pixel, 2)
        w["braunanteil_pct"] = round(100 * cv2.countNonZero(braun) / pixel, 2)
    else:
        for k in ["blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
                  "groesste_komponente_pct", "mittel_r", "mittel_g", "mittel_b",
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
    anzeige = cv2.convertScaleAbs(bild, alpha=3.0)      # nur zum Anschauen aufhellen
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
        if z["mm_pro_pixel"] is None:
            gruende.append("kein_marker")
        if not z["pflanzen_pixel"]:
            gruende.append("keine_pflanze")
        if z["schaerfe"] is not None and z["schaerfe"] < SCHAERFE_MIN:
            gruende.append("unscharf")
        if z["ueberbelichtet_pct"] > 1.0:
            gruende.append("ueberbelichtet")
        if z["groesste_komponente_pct"] is not None and z["groesste_komponente_pct"] < 70:
            gruende.append("zersplittert")
        if z["_sprung_pct"] is not None and abs(z["_sprung_pct"]) > SPRUNG_MAX_PCT:
            gruende.append("flaechensprung")
        z["auffaelligkeit"] = ";".join(gruende)
        z["brauchbar"] = not gruende


# --- Spaltenreihenfolge der CSV --------------------------------------
SPALTEN = (["bild", "stunden_seit_start", "zeitquelle",
            "pflanzen_pixel", "blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
            "wachstumsrate_cm2_pro_tag",
            "mittel_r", "mittel_g", "mittel_b", "mittel_h", "mittel_s",
            "gruenindex", "gelbanteil_pct", "braunanteil_pct",
            "mm_pro_pixel", "schaerfe", "bildhelligkeit", "ueberbelichtet_pct",
            "groesste_komponente_pct", "auffaelligkeit", "brauchbar"]
           + gesundheit.SPALTEN)


# --- Hauptprogramm ---------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
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

    zeilen, zeiten = [], []
    for i, (zeit, name, quelle, pfad) in enumerate(bilder, 1):
        bild = cv2.imread(pfad)
        if bild is None:
            print(f"[{i}/{len(bilder)}] {name:38s} nicht lesbar")
            continue

        mm_px, marker_box = marker_finden(bild)
        maske = segmentieren(bild)
        cv2.imwrite(f"{ordner_maske}/{name}_maske.png", maske)
        kontrollbild(bild, maske, marker_box, f"{ordner_kontrolle}/{name}_kontrolle.png")

        z = {"bild": name, "zeitquelle": quelle, **merkmale(bild, maske, mm_px)}
        zeilen.append(z)
        zeiten.append(zeit)
        flaeche = z["blattflaeche_cm2"]
        info = f"{flaeche} cm2" if flaeche else f"{z['pflanzen_pixel']} px (kein Marker)"
        print(f"[{i}/{len(bilder)}] {name:38s} {info}")

    if not zeilen:
        print("kein Bild konnte gelesen werden")
        return

    zeitreihe(zeilen, zeiten)
    pruefen(zeilen)
    referenz = gesundheit.bewerten(zeilen)

    with open(csv_pfad, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SPALTEN, extrasaction="ignore")
        w.writeheader()
        w.writerows(zeilen)

    print(f"\n{len(zeilen)} Bilder ausgewertet -> {AUSGABE}/ergebnis.csv")

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


if __name__ == "__main__":
    main()
