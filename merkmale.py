"""Merkmalsberechnung fuer die BioBox-Bildanalyse."""

import cv2
import numpy as np


def segmentieren(bild):
    """Trennt gruene Pflanzenpixel vom Hintergrund (Excess Green + Otsu)."""
    b, g, r = cv2.split(bild.astype(np.float32))
    exg = 2 * g - r - b
    exg = cv2.normalize(exg, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, maske = cv2.threshold(exg, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, kern)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, kern)

    # kleine Restflecken verwerfen
    n, labels, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
    sauber = np.zeros_like(maske)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 50:
            sauber[labels == i] = 255
    return sauber


def marker_finden(bild, marker_mm):
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
            continue                                  # zu gross -> Fehlerkennung
        if 0.85 < b / h < 1.15 and flaeche / (b * h) > 0.85:
            return marker_mm / ((b + h) / 2), (x, y, b, h)
    return None, None


def berechnen(bild, maske, mm_pro_px):
    """Alle Merkmale eines Bildes. Reihenfolge = Spaltenreihenfolge der CSV."""
    w = {}
    pixel = cv2.countNonZero(maske)
    w["pflanzen_pixel"] = pixel

    # --- Groesse und Form ---
    if pixel > 0:
        konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        umfang = sum(cv2.arcLength(k, True) for k in konturen)
        _, _, bb, bh = cv2.boundingRect(np.vstack(konturen))

        w["blattflaeche_cm2"] = round(pixel * mm_pro_px ** 2 / 100, 2) if mm_pro_px else None
        w["durchmesser_mm"] = round(max(bb, bh) * mm_pro_px, 1) if mm_pro_px else None
        # Kompaktheit: 1.0 = Kreis, kleiner = zerklueftet. Reagiert auf Welken.
        w["kompaktheit"] = round(4 * np.pi * pixel / umfang ** 2, 4) if umfang else None

        n, _, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
        groesste = max(stats[1:, cv2.CC_STAT_AREA]) if n > 1 else 0
        w["groesste_komponente_pct"] = round(100 * groesste / pixel, 1)
    else:
        for k in ["blattflaeche_cm2", "durchmesser_mm", "kompaktheit",
                  "groesste_komponente_pct"]:
            w[k] = None

    # --- Farbe ---
    if pixel > 0:
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
        for k in ["mittel_r", "mittel_g", "mittel_b", "mittel_h", "mittel_s",
                  "gruenindex", "gelbanteil_pct", "braunanteil_pct"]:
            w[k] = None

    # --- Bildqualitaet ---
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(grau, cv2.CV_64F)
    # Schaerfe nur auf der Pflanze - der schwarze Hintergrund haette sonst
    # jedes Bild unscharf aussehen lassen.
    w["schaerfe"] = round(float(lap[maske > 0].var()), 1) if pixel > 0 else None
    w["bildhelligkeit"] = round(float(grau.mean()), 1)
    w["ueberbelichtet_pct"] = round(100 * float((bild[:, :, 1] > 250).sum()) / grau.size, 2)
    w["mm_pro_pixel"] = round(mm_pro_px, 4) if mm_pro_px else None
    return w


def kontrollbild(bild, maske, marker_box, pfad):
    """Bild mit eingezeichneter Kontur zur Sichtpruefung."""
    anzeige = cv2.convertScaleAbs(bild, alpha=3.0)     # nur zum Anschauen aufhellen
    konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(anzeige, konturen, -1, (0, 0, 255), 2)
    if marker_box:
        x, y, b, h = marker_box
        cv2.rectangle(anzeige, (x, y), (x + b, y + h), (255, 0, 0), 2)
    cv2.imwrite(pfad, anzeige)
