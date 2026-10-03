"""
BioBox - Gesundheitsbewertung (A-M3)

Wird von analyse.py aufgerufen. Bewertet jede Aufnahme mit 0 bis 100 Punkten.

Grundgedanke: Alle Bilder zeigen dieselbe Pflanze unter fest eingestellter
Kamera und Beleuchtung. Es gibt deshalb keinen sinnvollen absoluten Sollfarbwert.
Bewertet wird die Abweichung vom EIGENEN Referenzzustand aus den ersten Bildern.
Bei externen Einzelbildern wird diese Bewertung deaktiviert: unterschiedliche
Pflanzen und Beleuchtungen haben keinen gemeinsamen Referenzzustand.
"""

import statistics

SCORING_VERSION = "1.0.0"  # Gewichte und Kennlinien aus BB-SPEC-HEALTH-001

BASIS_BILDER = 10        # erste N brauchbare Bilder bilden die Referenz
GLAETTUNG = 5            # gleitender Median ueber N Bilder

# Gewichte der Teilscores, Summe = 1.0
GEWICHTE = {
    "gruen":      0.30,  # Chlorophyll, wichtigster Einzelindikator
    "gelb":       0.25,  # Vergilbung
    "braun":      0.20,  # abgestorbenes Gewebe
    "saettigung": 0.15,  # Farbkraft, sinkt bei Welke
    "farbton":    0.10,  # Verschiebung des Gruentons
}

# Kennlinien: (Wert fuer 100 Punkte, Wert fuer 0 Punkte), relativ zur Referenz
KENNLINIEN = {
    "gruen":      (1.00, 0.85),   # Verhaeltnis gruenindex / Referenz
    "saettigung": (0.95, 0.70),   # Verhaeltnis mittel_s / Referenz
    "gelb":       (0.0, 25.0),    # Prozentpunkte ueber Referenz
    "braun":      (0.0, 10.0),    # Prozentpunkte ueber Referenz
    "farbton":    (2.0, 12.0),    # Betrag der Abweichung im HSV-Farbton
}

KATEGORIEN = [(85, "sehr gut"), (70, "gut"), (50, "beobachten"),
              (30, "auffaellig"), (0, "kritisch")]

# Schwellen fuer Warnmeldungen
WARN_GELB_PP = 8.0
WARN_BRAUN_PP = 3.0
WARN_GRUEN_REL = 0.93
WARN_SAETTIGUNG_REL = 0.88
WARN_STILLSTAND_H = 48

SPALTEN = ["scoring_version", "gesundheit", "gesundheit_roh", "gesundheit_kategorie",
           "gesundheit_trend_24h", "gesundheitswarnung",
           "score_gruen", "score_gelb", "score_braun",
           "score_saettigung", "score_farbton"]


def _score(wert, gut, schlecht):
    """Lineare Kennlinie: 'gut' -> 100 Punkte, 'schlecht' -> 0 Punkte."""
    if wert is None:
        return None
    spanne = gut - schlecht
    anteil = (wert - schlecht) / spanne
    return round(100 * min(1.0, max(0.0, anteil)), 1)


def _referenz(zeilen):
    """Median der Farbwerte ueber die ersten brauchbaren Bilder."""
    basis = [z for z in zeilen
             if z["brauchbar"] and z["gruenindex"] is not None
             and z.get("stunden_seit_start") is not None][:BASIS_BILDER]
    if len(basis) < 3:
        return None
    return {
        "gruenindex":  statistics.median(z["gruenindex"] for z in basis),
        "mittel_s":    statistics.median(z["mittel_s"] for z in basis),
        "mittel_h":    statistics.median(z["mittel_h"] for z in basis),
        "gelbanteil":  statistics.median(z["gelbanteil_pct"] for z in basis),
        "braunanteil": statistics.median(z["braunanteil_pct"] for z in basis),
        "bilder": len(basis), "von": basis[0]["bild"], "bis": basis[-1]["bild"],
    }


def _leer(z):
    for s in SPALTEN:
        z[s] = None
    z["gesundheitswarnung"] = ""
    z["scoring_version"] = SCORING_VERSION


def bewerten(zeilen, zeitreihe_aktiv=True, referenz_freigegeben=False):
    """Relative Bewertung nur bei einer zusammengehoerigen Pflanzenzeitreihe."""
    if not zeitreihe_aktiv:
        for z in zeilen:
            _leer(z)
            z["gesundheit_kategorie"] = "nicht_bewertet_datensatz"
        return None

    for z in zeilen:
        _leer(z)
    if not referenz_freigegeben:
        for z in zeilen:
            z["gesundheit_kategorie"] = "referenz_nicht_freigegeben"
        return None
    ref = _referenz(zeilen)
    if ref is not None and (ref["gruenindex"] <= 0 or ref["mittel_s"] <= 0):
        ref = None
    if ref is None:
        for z in zeilen:
            _leer(z)
            z["gesundheit_kategorie"] = "keine_referenz"
        return ref

    # 1. Teilscores und Rohwert je Bild
    for z in zeilen:
        if not z["brauchbar"] or z["gruenindex"] is None or z.get("stunden_seit_start") is None:
            _leer(z)
            continue

        rel_gruen = z["gruenindex"] / ref["gruenindex"]
        rel_saett = z["mittel_s"] / ref["mittel_s"]
        ueber_gelb = z["gelbanteil_pct"] - ref["gelbanteil"]
        ueber_braun = z["braunanteil_pct"] - ref["braunanteil"]
        hue_abw = abs(z["mittel_h"] - ref["mittel_h"])
        hue_abw = min(hue_abw, 180-hue_abw)

        z["score_gruen"] = _score(rel_gruen, *KENNLINIEN["gruen"])
        z["score_saettigung"] = _score(rel_saett, *KENNLINIEN["saettigung"])
        z["score_gelb"] = _score(ueber_gelb, *KENNLINIEN["gelb"])
        z["score_braun"] = _score(ueber_braun, *KENNLINIEN["braun"])
        z["score_farbton"] = _score(hue_abw, *KENNLINIEN["farbton"])
        z["gesundheit_roh"] = round(
            sum(GEWICHTE[k] * z["score_" + k] for k in GEWICHTE), 1)

        warnungen = []
        if ueber_gelb >= WARN_GELB_PP:
            warnungen.append("vergilbung")
        if ueber_braun >= WARN_BRAUN_PP:
            warnungen.append("nekrose")
        if rel_gruen <= WARN_GRUEN_REL:
            warnungen.append("chlorose")
        if rel_saett <= WARN_SAETTIGUNG_REL:
            warnungen.append("entfaerbung")
        z["gesundheitswarnung"] = ";".join(warnungen)

    # 2. Glaetten - ein einzelnes schlechtes Bild darf keinen Alarm ausloesen
    roh = [z["gesundheit_roh"] for z in zeilen]
    letzter_score = None
    for i, z in enumerate(zeilen):
        if z["gesundheit_roh"] is None:
            # HEALTH-001, 9.1 / DB-Hinweis: Anzeige fortschreiben, aber keine
            # Rohscores fuer ein unbrauchbares Bild erfinden.
            z["gesundheit"] = letzter_score
            z["gesundheit_kategorie"] = next(
                (n for g, n in KATEGORIEN if letzter_score >= g), "kritisch"
            ) if letzter_score is not None else "keine_daten"
            continue
        fenster = [v for v in roh[max(0, i - GLAETTUNG + 1):i + 1] if v is not None]
        z["gesundheit"] = round(statistics.median(fenster), 1) if fenster else None
        z["gesundheit_kategorie"] = next(
            (n for g, n in KATEGORIEN if z["gesundheit"] >= g), "kritisch"
        ) if fenster else "keine_daten"
        letzter_score = z["gesundheit"]

    # 3. Trend ueber 24 h - die Richtung sagt mehr als der Absolutwert
    for i, z in enumerate(zeilen):
        z["gesundheit_trend_24h"] = None
        if z["gesundheit_roh"] is None or z.get("stunden_seit_start") is None:
            continue
        frueher = [v for v in zeilen[:i]
                   if v.get("stunden_seit_start") is not None and v["gesundheit_roh"] is not None
                   and v["stunden_seit_start"] <= z["stunden_seit_start"] - 24]
        if frueher:
            z["gesundheit_trend_24h"] = round(
                z["gesundheit"] - frueher[-1]["gesundheit"], 1)

    # 4. Wachstumsstillstand - nicht farbbasiert, aber sonst unentdeckt
    for i, z in enumerate(zeilen):
        if not z["brauchbar"] or z["blattflaeche_cm2"] is None or z.get("stunden_seit_start") is None:
            continue
        frueher = [v for v in zeilen[:i]
                   if v["brauchbar"] and v.get("stunden_seit_start") is not None
                   and v["stunden_seit_start"] <= z["stunden_seit_start"] - WARN_STILLSTAND_H
                   and v["blattflaeche_cm2"] is not None]
        if frueher and z["blattflaeche_cm2"] <= frueher[-1]["blattflaeche_cm2"] * 1.01:
            z["gesundheitswarnung"] = ";".join(
                filter(None, [z["gesundheitswarnung"], "wachstumsstillstand"]))

    return ref
