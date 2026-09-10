"""
BioBox - Bildanalyse
Berechnet aus Pflanzenbildern die projizierte Blattflaeche.

Aufruf:  python analyse.py bilder          (ganzer Ordner)
         python analyse.py bild.jpg        (einzelnes Bild)

Ergebnisse landen im Ordner "auswertung":
    auswertung/ergebnisse.csv
    auswertung/masken/
    auswertung/kontrolle/

Dateinamen der Bilder sollten den Zeitstempel enthalten, z. B.
    biobox01_20260930T081500Z.jpg
Daraus wird die Spalte "zeitpunkt" gebildet.
"""

import cv2
import numpy as np
import sys
import os
import re
import csv
import glob
from datetime import datetime

import merkmale
import gesundheit

# --- Einstellungen ---------------------------------------------------
MARKER_MM = 40.0          # physische Kantenlaenge des Markers in mm
MIN_BLOB_PX = 50          # kleinere Flecken werden verworfen
AUSGABE_ORDNER = "auswertung"
SCHAERFE_MIN = 5.0        # Laplace-Varianz; im Testbetrieb anpassen
SPRUNG_MAX_PCT = 30.0     # groessere Flaechenaenderung je Bild ist verdaechtig
BILD_ENDUNGEN = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

ZEIT_MUSTER = re.compile(r"(\d{8}T\d{6}Z)")


def zeitpunkt_aus_name(dateiname, pfad):
    """Liest den Zeitstempel aus dem Dateinamen, sonst aus dem Dateidatum."""
    treffer = ZEIT_MUSTER.search(dateiname)
    if treffer:
        t = datetime.strptime(treffer.group(1), "%Y%m%dT%H%M%SZ")
        return t.strftime("%Y-%m-%d %H:%M:%S"), True
    # Notfall-Rueckfall: Dateidatum. Das ist NICHT der Aufnahmezeitpunkt -
    # beim Kopieren kann es sich aendern. Nur zur Notüberbrückung.
    t = datetime.fromtimestamp(os.path.getmtime(pfad))
    return t.strftime("%Y-%m-%d %H:%M:%S"), False


def marker_finden(bild):
    """Sucht den hellen quadratischen Marker und liefert mm pro Pixel."""
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    _, hell = cv2.threshold(grau, 180, 255, cv2.THRESH_BINARY)
    konturen, _ = cv2.findContours(hell, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for k in konturen:
        flaeche = cv2.contourArea(k)
        if flaeche < 200:
            continue
        x, y, b, h = cv2.boundingRect(k)
        # darf nicht das halbe Bild sein -> sonst Fehlerkennung
        if b > bild.shape[1] * 0.4 or h > bild.shape[0] * 0.4:
            continue
        if 0.85 < b / h < 1.15 and flaeche / (b * h) > 0.85:
            kante_px = (b + h) / 2
            return MARKER_MM / kante_px, (x, y, b, h)

    return None, None


def pflanze_segmentieren(bild):
    """Trennt gruene Pflanzenpixel vom Hintergrund (Excess Green + Otsu)."""
    b, g, r = cv2.split(bild.astype(np.float32))
    exg = 2 * g - r - b                       # Vegetationsindex
    exg_norm = cv2.normalize(exg, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, maske = cv2.threshold(exg_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, kern)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, kern)

    anzahl, labels, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
    sauber = np.zeros_like(maske)
    for i in range(1, anzahl):
        if stats[i, cv2.CC_STAT_AREA] >= MIN_BLOB_PX:
            sauber[labels == i] = 255

    return sauber


def merkmale_berechnen(bild, maske, mm_pro_px):
    """Sammelt alle Merkmale eines Bildes."""
    w = {}
    w.update(merkmale.groesse_und_form(maske, mm_pro_px))
    w.update(merkmale.farbe_und_stress(bild, maske))
    w.update(merkmale.bildqualitaet(bild, maske))
    w["mm_pro_pixel"] = round(mm_pro_px, 4) if mm_pro_px is not None else None
    w["marker_gefunden"] = mm_pro_px is not None
    return w


def zeitreihe_ergaenzen(zeilen):
    """Ergaenzt Wachstumsrate und Auffaelligkeiten ueber die Zeitreihe.

    Kann erst berechnet werden, wenn alle Bilder sortiert vorliegen -
    diese Spalten sind die eigentliche Grundlage fuer den Digital Twin.
    """
    start = datetime.strptime(zeilen[0]["zeitpunkt"], "%Y-%m-%d %H:%M:%S")
    vorher = None

    for z in zeilen:
        jetzt = datetime.strptime(z["zeitpunkt"], "%Y-%m-%d %H:%M:%S")
        z["stunden_seit_start"] = round((jetzt - start).total_seconds() / 3600, 2)

        flaeche = z["blattflaeche_cm2"]
        z["flaeche_delta_cm2"] = None
        z["wachstumsrate_cm2_pro_tag"] = None
        z["flaeche_aenderung_pct"] = None

        if flaeche is not None and vorher is not None:
            d_h = (jetzt - vorher[0]).total_seconds() / 3600
            d_a = flaeche - vorher[1]
            z["flaeche_delta_cm2"] = round(d_a, 3)
            if d_h > 0:
                z["wachstumsrate_cm2_pro_tag"] = round(d_a / d_h * 24, 3)
            if vorher[1] > 0:
                z["flaeche_aenderung_pct"] = round(100 * d_a / vorher[1], 1)

        if flaeche is not None:
            vorher = (jetzt, flaeche)

    return zeilen


def auffaelligkeiten_pruefen(zeilen, schaerfe_min, sprung_max_pct):
    """Setzt je Zeile eine Textspalte mit den verletzten Kriterien."""
    for z in zeilen:
        gruende = []
        if not z["marker_gefunden"]:
            gruende.append("kein_marker")
        if z["pflanzen_pixel"] == 0:
            gruende.append("keine_pflanze")
        if z["schaerfe"] is not None and z["schaerfe"] < schaerfe_min:
            gruende.append("unscharf")
        if z["ueberbelichtet_pct"] > 1.0:
            gruende.append("ueberbelichtet")
        if z["groesste_komponente_pct"] is not None and z["groesste_komponente_pct"] < 70:
            gruende.append("zersplittert")
        aend = z.get("flaeche_aenderung_pct")
        if aend is not None and abs(aend) > sprung_max_pct:
            gruende.append("flaechensprung")
        z["auffaelligkeit"] = ";".join(gruende)
        z["brauchbar"] = len(gruende) == 0
    return zeilen

def kontrollbild(bild, maske, marker_box, pfad):
    """Speichert ein Bild mit eingezeichneter Kontur zur Sichtpruefung."""
    anzeige = cv2.convertScaleAbs(bild, alpha=3.0)   # nur zum Anschauen aufhellen
    konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(anzeige, konturen, -1, (0, 0, 255), 2)
    if marker_box:
        x, y, b, h = marker_box
        cv2.rectangle(anzeige, (x, y), (x + b, y + h), (255, 0, 0), 2)
    cv2.imwrite(pfad, anzeige)


def ausgabe_stamm(name, vergeben):
    """Eindeutiger Dateistamm fuer Maske und Kontrollbild.

    'foto.jpg' -> 'foto'.  Gibt es zusaetzlich 'foto.png', wuerde die
    zweite Maske die erste ueberschreiben. In dem Fall wird die Endung
    angehaengt: 'foto_png'.
    """
    stamm = os.path.splitext(name)[0]
    if stamm not in vergeben:
        vergeben.add(stamm)
        return stamm, False
    endung = os.path.splitext(name)[1].lstrip(".").lower()
    stamm2 = f"{stamm}_{endung}"
    n = 2
    while stamm2 in vergeben:
        stamm2 = f"{stamm}_{endung}{n}"
        n += 1
    vergeben.add(stamm2)
    return stamm2, True


def alte_ausgaben_loeschen(ordner_maske, ordner_kontrolle):
    """Loescht alle frueheren Masken und Kontrollbilder."""
    anzahl = 0
    for ordner in (ordner_maske, ordner_kontrolle):
        for f in glob.glob(os.path.join(ordner, "*.png")):
            os.remove(f)
            anzahl += 1
    return anzahl


def ein_bild(pfad, stamm, ordner_maske, ordner_kontrolle):
    """Analysiert ein einzelnes Bild und liefert die Messwerte."""
    bild = cv2.imread(pfad)
    if bild is None:
        return None

    name = os.path.basename(pfad)

    mm_pro_px, marker_box = marker_finden(bild)
    maske = pflanze_segmentieren(bild)
    werte = merkmale_berechnen(bild, maske, mm_pro_px)

    zeit, aus_name = zeitpunkt_aus_name(name, pfad)
    werte = {"zeitpunkt": zeit, "bild": name,
             "zeitquelle": "dateiname" if aus_name else "dateidatum", **werte}

    cv2.imwrite(os.path.join(ordner_maske, stamm + "_maske.png"), maske)
    kontrollbild(bild, maske, marker_box,
                 os.path.join(ordner_kontrolle, stamm + "_kontrolle.png"))
    return werte


def main():
    if len(sys.argv) < 2:
        print("Aufruf: python analyse.py bilder")
        print("   oder: python analyse.py bild.jpg")
        return

    ziel = sys.argv[1]

    if os.path.isdir(ziel):
        dateien = sorted(
            os.path.join(ziel, d) for d in os.listdir(ziel)
            if d.lower().endswith(BILD_ENDUNGEN)
            and "_maske" not in d.lower()          # eigene Ausgaben ignorieren
            and "_kontrolle" not in d.lower()
        )
    elif os.path.isfile(ziel):
        dateien = [ziel]
    else:
        print("nicht gefunden:", ziel)
        return

    if not dateien:
        print("keine Bilder gefunden in:", ziel)
        return

    ordner_maske = os.path.join(AUSGABE_ORDNER, "masken")
    ordner_kontrolle = os.path.join(AUSGABE_ORDNER, "kontrolle")
    os.makedirs(ordner_maske, exist_ok=True)
    os.makedirs(ordner_kontrolle, exist_ok=True)

    geloescht = alte_ausgaben_loeschen(ordner_maske, ordner_kontrolle)
    if geloescht:
        print(f"{geloescht} alte Ausgabedatei(en) geloescht\n")

    alle, ohne_zeit, ohne_marker, umbenannt = [], 0, 0, 0
    vergeben = set()

    for i, pfad in enumerate(dateien, 1):
        stamm, kollision = ausgabe_stamm(os.path.basename(pfad), vergeben)
        if kollision:
            umbenannt += 1
        werte = ein_bild(pfad, stamm, ordner_maske, ordner_kontrolle)
        if werte is None:
            print(f"[{i}/{len(dateien)}] {os.path.basename(pfad):40s} nicht lesbar")
            continue

        alle.append(werte)
        if werte["zeitquelle"] != "dateiname":
            ohne_zeit += 1
        if werte["blattflaeche_cm2"] is None:
            ohne_marker += 1
            info = f"{werte['pflanzen_pixel']} px (kein Marker)"
        else:
            info = f"{werte['blattflaeche_cm2']} cm2"
        print(f"[{i}/{len(dateien)}] {werte['bild']:40s} {info}")

    if not alle:
        return

    alle.sort(key=lambda z: z["zeitpunkt"])       # zeitlich sortieren
    zeiten = [z["zeitpunkt"] for z in alle]
    doppelt = sorted({t for t in zeiten if zeiten.count(t) > 1})
    if doppelt:
        print(f"\nWARNUNG: {len(doppelt)} Zeitstempel kommen mehrfach vor:")
        for t in doppelt[:5]:
            namen = [z["bild"] for z in alle if z["zeitpunkt"] == t]
            print(f"   {t}  ->  {', '.join(namen)}")
        print("   -> Wachstumsrate wird dadurch unbrauchbar")

    alle = zeitreihe_ergaenzen(alle)
    alle = auffaelligkeiten_pruefen(alle, SCHAERFE_MIN, SPRUNG_MAX_PCT)
    alle, referenz = gesundheit.bewerten(alle)

    csv_pfad = os.path.join(AUSGABE_ORDNER, "ergebnisse.csv")
    with open(csv_pfad, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(alle[0].keys()))
        w.writeheader()
        w.writerows(alle)

    print(f"\n{len(alle)} Bilder ausgewertet")

    if referenz:
        print(f"\nReferenzphase: {referenz['bilder']} Bilder "
              f"({referenz['von']} bis {referenz['bis']})")
        bewertet = [z for z in alle if z["gesundheit"] is not None]
        if bewertet:
            letzte = bewertet[-1]
            trend = letzte["gesundheit_trend_24h"]
            trend_txt = f"{trend:+.2f} in 24 h" if trend is not None else "noch kein Vergleich"
            print(f"Gesundheit aktuell: {letzte['gesundheit']:.1f}/10 "
                  f"({letzte['gesundheit_kategorie']}), {trend_txt}")
            warn = [z for z in bewertet if z["gesundheitswarnung"]]
            if warn:
                print(f"Warnungen bei {len(warn)} Bild(ern), zuletzt: "
                      f"{warn[-1]['gesundheitswarnung']}")
    else:
        print("\nGesundheitsbewertung: zu wenige brauchbare Bilder fuer eine Referenz")

    print(f"Tabelle:   {csv_pfad}")
    print(f"Masken:    {ordner_maske}")
    print(f"Kontrolle: {ordner_kontrolle}")
    if ohne_zeit:
        print(f"HINWEIS: bei {ohne_zeit} Bild(ern) kein Zeitstempel im Namen "
              f"-> Dateidatum verwendet (unzuverlaessig, Spalte 'zeitquelle')")
    if ohne_marker:
        print(f"HINWEIS: bei {ohne_marker} Bild(ern) kein Marker gefunden "
              f"-> nur Pixelwerte")
    if umbenannt:
        print(f"HINWEIS: {umbenannt} Bild(er) mit gleichem Namen bei anderer "
              f"Endung -> Endung an Maskennamen angehaengt")

    schlecht = [z for z in alle if not z["brauchbar"]]
    if schlecht:
        print(f"\n{len(schlecht)} von {len(alle)} Bild(ern) auffaellig:")
        for z in schlecht[:10]:
            print(f"   {z['bild']:40s} {z['auffaelligkeit']}")
        if len(schlecht) > 10:
            print(f"   ... und {len(schlecht) - 10} weitere")
        print("   -> Kontrollbilder ansehen, Spalte 'brauchbar' zum Filtern nutzen")

    if len(alle) != len(glob.glob(os.path.join(ordner_maske, "*.png"))):
        print("WARNUNG: Anzahl Masken passt nicht zur Anzahl Bilder")


if __name__ == "__main__":
    main()
