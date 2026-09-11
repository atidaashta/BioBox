"""
BioBox - Bildanalyse

Aufruf:  python analyse.py bilder      (Ordner, auch mit Unterordnern)
         python analyse.py bild.jpg    (einzelnes Bild)

Ausgabe im Ordner "auswertung":
    ergebnisse.csv     Messwerte je Bild
    gesundheit.csv     Bewertung je Bild
    masken/            Segmentierungsmaske je Bild
    kontrolle/         Bild mit eingezeichneter Kontur je Bild

Die Bilddateien MUESSEN den Zeitstempel im Namen tragen:
    biobox01_20260930T081500Z.jpg
Bilder ohne Zeitstempel werden uebersprungen.
"""

import csv
import glob
import os
import re
import sys
from datetime import datetime

import cv2

import merkmale
import gesundheit

# --- Einstellungen ---------------------------------------------------
MARKER_MM = 40.0          # physische Kantenlaenge des Markers in mm
SCHAERFE_MIN = 5.0        # Laplace-Varianz; im Testbetrieb anpassen
SPRUNG_MAX_PCT = 30.0     # groessere Flaechenaenderung je Bild ist verdaechtig
AUSGABE = "auswertung"

ENDUNGEN = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
ZEIT_MUSTER = re.compile(r"(\d{8}T\d{6}Z)")


# --- Dateien einsammeln ----------------------------------------------
def bilder_suchen(ziel):
    """Liefert (name_ohne_endung, zeitpunkt, pfad) je gueltigem Bild."""
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
        return [], []

    gueltig, ohne_zeit = [], []
    for pfad in sorted(pfade):
        name = os.path.splitext(os.path.basename(pfad))[0]
        treffer = ZEIT_MUSTER.search(name)
        if treffer:
            zeit = datetime.strptime(treffer.group(1), "%Y%m%dT%H%M%SZ")
            gueltig.append((name, zeit, pfad))
        else:
            ohne_zeit.append(name)

    gueltig.sort(key=lambda x: x[1])          # zeitlich sortieren
    return gueltig, ohne_zeit


# --- Ein Bild --------------------------------------------------------
def bild_auswerten(name, pfad, ordner_maske, ordner_kontrolle):
    bild = cv2.imread(pfad)
    if bild is None:
        return None

    mm_pro_px, marker_box = merkmale.marker_finden(bild, MARKER_MM)
    maske = merkmale.segmentieren(bild)

    cv2.imwrite(os.path.join(ordner_maske, name + "_maske.png"), maske)
    merkmale.kontrollbild(bild, maske, marker_box,
                          os.path.join(ordner_kontrolle, name + "_kontrolle.png"))

    return {"bild": name, **merkmale.berechnen(bild, maske, mm_pro_px)}


# --- Zeitreihe -------------------------------------------------------
def zeitreihe_ergaenzen(zeilen, zeiten):
    """Stunden seit Start und Wachstumsrate. Basis fuer den Digital Twin."""
    start = zeiten[0]
    vorher = None

    for z, t in zip(zeilen, zeiten):
        z["stunden_seit_start"] = round((t - start).total_seconds() / 3600, 2)
        z["wachstumsrate_cm2_pro_tag"] = None
        z["_aenderung_pct"] = None

        flaeche = z["blattflaeche_cm2"]
        if flaeche is not None and vorher is not None:
            stunden = (t - vorher[0]).total_seconds() / 3600
            delta = flaeche - vorher[1]
            if stunden > 0:
                z["wachstumsrate_cm2_pro_tag"] = round(delta / stunden * 24, 3)
            if vorher[1] > 0:
                z["_aenderung_pct"] = 100 * delta / vorher[1]
        if flaeche is not None:
            vorher = (t, flaeche)
    return zeilen


def pruefen(zeilen):
    """Setzt je Zeile die Spalten 'auffaelligkeit' und 'brauchbar'."""
    for z in zeilen:
        gruende = []
        if z["mm_pro_pixel"] is None:
            gruende.append("kein_marker")
        if z["pflanzen_pixel"] == 0:
            gruende.append("keine_pflanze")
        if z["schaerfe"] is not None and z["schaerfe"] < SCHAERFE_MIN:
            gruende.append("unscharf")
        if z["ueberbelichtet_pct"] > 1.0:
            gruende.append("ueberbelichtet")
        if z["groesste_komponente_pct"] is not None and z["groesste_komponente_pct"] < 70:
            gruende.append("zersplittert")
        if z["_aenderung_pct"] is not None and abs(z["_aenderung_pct"]) > SPRUNG_MAX_PCT:
            gruende.append("flaechensprung")

        z["auffaelligkeit"] = ";".join(gruende)
        z["brauchbar"] = not gruende
    return zeilen


# --- Schreiben -------------------------------------------------------
def csv_schreiben(pfad, zeilen, spalten):
    with open(pfad, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=spalten, extrasaction="ignore")
        w.writeheader()
        w.writerows(zeilen)


MESS_SPALTEN = [
    "bild", "stunden_seit_start",
    "pflanzen_pixel", "blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
    "wachstumsrate_cm2_pro_tag",
    "mittel_r", "mittel_g", "mittel_b", "mittel_h", "mittel_s",
    "gruenindex", "gelbanteil_pct", "braunanteil_pct",
    "mm_pro_pixel", "schaerfe", "bildhelligkeit", "ueberbelichtet_pct",
    "groesste_komponente_pct", "auffaelligkeit", "brauchbar",
]

GESUND_SPALTEN = [
    "bild", "stunden_seit_start",
    "gesundheit", "gesundheit_roh", "gesundheit_kategorie",
    "gesundheit_trend_24h", "gesundheitswarnung",
    "score_gruen", "score_gelb", "score_braun", "score_saettigung", "score_farbton",
]


# --- Hauptprogramm ---------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    gueltig, ohne_zeit = bilder_suchen(sys.argv[1])
    if not gueltig:
        print("keine Bilder mit Zeitstempel im Namen gefunden")
        for n in ohne_zeit[:5]:
            print("   uebersprungen:", n)
        return

    ordner_maske = os.path.join(AUSGABE, "masken")
    ordner_kontrolle = os.path.join(AUSGABE, "kontrolle")
    os.makedirs(ordner_maske, exist_ok=True)
    os.makedirs(ordner_kontrolle, exist_ok=True)

    alt = glob.glob(os.path.join(ordner_maske, "*.png")) + \
          glob.glob(os.path.join(ordner_kontrolle, "*.png"))
    for f in alt:
        os.remove(f)
    if alt:
        print(f"{len(alt)} alte Ausgabedatei(en) geloescht\n")

    zeilen, zeiten = [], []
    for i, (name, zeit, pfad) in enumerate(gueltig, 1):
        z = bild_auswerten(name, pfad, ordner_maske, ordner_kontrolle)
        if z is None:
            print(f"[{i}/{len(gueltig)}] {name:38s} nicht lesbar")
            continue
        zeilen.append(z)
        zeiten.append(zeit)
        wert = z["blattflaeche_cm2"]
        info = f"{wert} cm2" if wert else f"{z['pflanzen_pixel']} px (kein Marker)"
        print(f"[{i}/{len(gueltig)}] {name:38s} {info}")

    if not zeilen:
        return

    zeilen = zeitreihe_ergaenzen(zeilen, zeiten)
    zeilen = pruefen(zeilen)
    zeilen, referenz = gesundheit.bewerten(zeilen)

    csv_schreiben(os.path.join(AUSGABE, "ergebnisse.csv"), zeilen, MESS_SPALTEN)
    csv_schreiben(os.path.join(AUSGABE, "gesundheit.csv"), zeilen, GESUND_SPALTEN)

    print(f"\n{len(zeilen)} Bilder ausgewertet -> {AUSGABE}/")
    if ohne_zeit:
        print(f"{len(ohne_zeit)} Bild(er) ohne Zeitstempel im Namen uebersprungen")

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
            print(f"\nGesundheit aktuell: {letzte['gesundheit']}/10 "
                  f"({letzte['gesundheit_kategorie']})")


if __name__ == "__main__":
    main()
