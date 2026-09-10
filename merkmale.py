"""Merkmalsberechnung fuer die BioBox-Bildanalyse.

Die Merkmale sind so gewaehlt, dass sie drei Ziele bedienen:
  A-M2 Computer-Vision-Pipeline   -> Flaeche, Form, Groesse
  A-M3 Gesundheitsbewertung       -> Farbe, Stressanteile, Fragmentierung
  A-M4 Digital-Twin-Modell        -> Zeitreihe LA[t], Wachstumsrate
Zusaetzlich Qualitaetskennzahlen, damit schlechte Bilder erkennbar sind.
"""

import cv2
import numpy as np


def groesse_und_form(maske, mm_pro_px):
    """Flaeche, Ausdehnung, Umfang, Kompaktheit, Fragmentierung."""
    w = {}
    pixel = cv2.countNonZero(maske)
    w["pflanzen_pixel"] = pixel
    w["bedeckungsgrad_pct"] = round(100 * pixel / maske.size, 2)

    if pixel == 0:
        for k in ["blattflaeche_cm2", "bbox_breite_mm", "bbox_hoehe_mm",
                  "umfang_mm", "kompaktheit", "groesste_komponente_pct",
                  "teilflaechen", "blattanzahl_schaetzung"]:
            w[k] = None
        return w

    if mm_pro_px is not None:
        w["blattflaeche_cm2"] = round(pixel * mm_pro_px ** 2 / 100, 2)
    else:
        w["blattflaeche_cm2"] = None

    konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    umfang_px = sum(cv2.arcLength(k, True) for k in konturen)

    alle = np.vstack(konturen)
    x, y, b, h = cv2.boundingRect(alle)

    # Kompaktheit: 1.0 = Kreis, kleiner = zerklueftet/ausgebreitet.
    # Reagiert auf Welken und Streckungswachstum, unabhaengig vom Massstab.
    w["kompaktheit"] = round(float(4 * np.pi * pixel / (umfang_px ** 2)), 4) \
        if umfang_px > 0 else None

    if mm_pro_px is not None:
        w["bbox_breite_mm"] = round(b * mm_pro_px, 1)
        w["bbox_hoehe_mm"] = round(h * mm_pro_px, 1)
        w["umfang_mm"] = round(umfang_px * mm_pro_px, 1)
    else:
        w["bbox_breite_mm"] = w["bbox_hoehe_mm"] = w["umfang_mm"] = None

    # Fragmentierung: faellt der Wert ploetzlich, ist meist die
    # Segmentierung gescheitert, nicht die Pflanze zerfallen.
    anzahl, _, stats, _ = cv2.connectedComponentsWithStats(maske, 8)
    flaechen = sorted(stats[1:, cv2.CC_STAT_AREA], reverse=True) if anzahl > 1 else []
    w["teilflaechen"] = len(flaechen)
    w["groesste_komponente_pct"] = round(100 * flaechen[0] / pixel, 1) if flaechen else None

    # Grobe Blattzahl ueber Distanztransformation. Bei Ueberlappung
    # systematisch zu niedrig -> nur Zusatzinfo, keine Primaergroesse.
    dist = cv2.distanceTransform(maske, cv2.DIST_L2, 5)
    if dist.max() > 0:
        _, peaks = cv2.threshold(dist, 0.5 * dist.max(), 255, 0)
        n, _ = cv2.connectedComponents(peaks.astype(np.uint8))
        w["blattanzahl_schaetzung"] = n - 1
    else:
        w["blattanzahl_schaetzung"] = None

    return w


def farbe_und_stress(bild, maske):
    """Rohfarbwerte plus Gelb-/Braunanteil als Stressindikatoren."""
    w = {}
    pixel = cv2.countNonZero(maske)
    if pixel == 0:
        for k in ["mittel_r", "mittel_g", "mittel_b", "mittel_h", "mittel_s",
                  "mittel_v", "exg_mittel", "gruenindex", "gelbanteil_pct",
                  "braunanteil_pct", "stressanteil_pct"]:
            w[k] = None
        return w

    m = maske > 0
    b, g, r = cv2.split(bild.astype(np.float32))

    # Rohe Mittelwerte mitschreiben, damit spaeter neue Indizes berechnet
    # werden koennen, ohne alle Bilder erneut zu verarbeiten.
    w["mittel_r"] = round(float(r[m].mean()), 1)
    w["mittel_g"] = round(float(g[m].mean()), 1)
    w["mittel_b"] = round(float(b[m].mean()), 1)

    hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
    h_, s_, v_ = cv2.split(hsv.astype(np.float32))
    w["mittel_h"] = round(float(h_[m].mean()), 1)
    w["mittel_s"] = round(float(s_[m].mean()), 1)
    w["mittel_v"] = round(float(v_[m].mean()), 1)

    w["exg_mittel"] = round(float((2 * g - r - b)[m].mean()), 1)
    w["gruenindex"] = round(float((g / (b + g + r + 1e-6))[m].mean()), 4)

    gelb = cv2.bitwise_and(cv2.inRange(hsv, (15, 60, 20), (33, 255, 255)), maske)
    braun = cv2.bitwise_and(cv2.inRange(hsv, (5, 40, 15), (20, 255, 160)), maske)
    w["gelbanteil_pct"] = round(100 * cv2.countNonZero(gelb) / pixel, 2)
    w["braunanteil_pct"] = round(100 * cv2.countNonZero(braun) / pixel, 2)
    w["stressanteil_pct"] = round(
        100 * cv2.countNonZero(cv2.bitwise_or(gelb, braun)) / pixel, 2)
    return w


def bildqualitaet(bild, maske):
    """Kennzahlen zur Beurteilung, ob das Bild ueberhaupt brauchbar ist."""
    w = {}
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    w["schaerfe"] = round(float(cv2.Laplacian(grau, cv2.CV_64F).var()), 1)
    w["bildhelligkeit"] = round(float(grau.mean()), 1)

    g = bild[:, :, 1]
    w["ueberbelichtet_pct"] = round(100 * float((g > 250).sum()) / g.size, 2)
    w["unterbelichtet_pct"] = round(100 * float((grau < 5).sum()) / grau.size, 2)

    if cv2.countNonZero(maske) > 0:
        # Schaerfe nur auf der Pflanze - aussagekraeftiger als das Gesamtbild,
        # weil ein schwarzer Hintergrund die Gesamtvarianz nach unten zieht.
        w["schaerfe_pflanze"] = round(
            float(cv2.Laplacian(grau, cv2.CV_64F)[maske > 0].var()), 1)
    else:
        w["schaerfe_pflanze"] = None
    return w
