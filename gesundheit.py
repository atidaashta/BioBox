"""Gesundheitsbewertung der BioBox-Pflanze (A-M3).

Grundgedanke
------------
Alle Bilder zeigen dieselbe Pflanze beim Wachsen. Es gibt deshalb keinen
sinnvollen absoluten "Sollfarbwert" - Kamera, Weissabgleich, LED-Spektrum
und Sorte beeinflussen die gemessenen Farbwerte zu stark.

Stattdessen wird die Pflanze gegen ihren EIGENEN Referenzzustand bewertet:
Aus den ersten brauchbaren Bildern wird eine Referenz gebildet, und jede
spaetere Aufnahme wird als Abweichung davon bewertet.

Der Score laeuft von 0 bis 10 und setzt sich aus fuenf Farbteilscores
zusammen. Alle Kennlinien sind linear und damit nachvollziehbar.
"""

import statistics

# --- Referenzbildung -------------------------------------------------
BASIS_BILDER = 10        # erste N brauchbare Bilder bilden die Referenz
GLAETTUNG = 5            # gleitender Median ueber N Bilder

# --- Gewichte der Teilscores (Summe = 1.0) ---------------------------
GEWICHTE = {
    "gruen":      0.30,   # Chlorophyllgehalt, wichtigster Einzelindikator
    "gelb":       0.25,   # Vergilbung (Chlorose)
    "braun":      0.20,   # Nekrose, abgestorbenes Gewebe
    "saettigung": 0.15,   # Farbkraft, sinkt bei Welke und allgemeinem Stress
    "farbton":    0.10,   # Verschiebung des Grüntons
}

# --- Kennlinien: (Wert fuer 10 Punkte, Wert fuer 0 Punkte) -----------
# Alle Werte sind relativ zur Referenzphase.
KENNLINIEN = {
    "gruen":      (1.00, 0.85),    # Verhaeltnis gruenindex / Referenz
    "saettigung": (0.95, 0.70),    # Verhaeltnis mittel_s / Referenz
    "gelb":       (0.0, 25.0),     # Prozentpunkte ueber Referenz
    "braun":      (0.0, 10.0),     # Prozentpunkte ueber Referenz
    "farbton":    (2.0, 12.0),     # Betrag der Abweichung in HSV-Hue
}

KATEGORIEN = [
    (8.5, "sehr gut"),
    (7.0, "gut"),
    (5.0, "beobachten"),
    (3.0, "auffaellig"),
    (0.0, "kritisch"),
]

# --- Schwellen fuer Warnmeldungen ------------------------------------
WARN_GELB_PP = 8.0       # Prozentpunkte ueber Referenz
WARN_BRAUN_PP = 3.0
WARN_GRUEN_REL = 0.93    # Anteil des Referenzwerts
WARN_SAETTIGUNG_REL = 0.88
WARN_STILLSTAND_H = 48   # Stunden ohne Flaechenzuwachs


def _teilscore(wert, gut, schlecht):
    """Lineare Kennlinie: 'gut' -> 10 Punkte, 'schlecht' -> 0 Punkte."""
    if wert is None:
        return None
    if gut < schlecht:                       # kleiner ist besser
        if wert <= gut:
            return 10.0
        if wert >= schlecht:
            return 0.0
    else:                                    # groesser ist besser
        if wert >= gut:
            return 10.0
        if wert <= schlecht:
            return 0.0
    return round(10.0 * (wert - schlecht) / (gut - schlecht), 2)


def referenz_bilden(zeilen):
    """Median der Farbwerte ueber die ersten brauchbaren Bilder."""
    basis = [z for z in zeilen if z.get("brauchbar") and z.get("gruenindex") is not None]
    basis = basis[:BASIS_BILDER]
    if len(basis) < 3:
        return None, len(basis)

    ref = {
        "gruenindex":  statistics.median(z["gruenindex"] for z in basis),
        "mittel_s":    statistics.median(z["mittel_s"] for z in basis),
        "mittel_h":    statistics.median(z["mittel_h"] for z in basis),
        "gelbanteil":  statistics.median(z["gelbanteil_pct"] for z in basis),
        "braunanteil": statistics.median(z["braunanteil_pct"] for z in basis),
        "bilder":      len(basis),
        "von":         basis[0]["zeitpunkt"],
        "bis":         basis[-1]["zeitpunkt"],
    }
    return ref, len(basis)


def _bewerte_zeile(z, ref):
    """Berechnet die fuenf Teilscores und den Rohscore einer Aufnahme."""
    if not z.get("brauchbar") or z.get("gruenindex") is None:
        return None

    rel_gruen = z["gruenindex"] / ref["gruenindex"] if ref["gruenindex"] else None
    rel_saett = z["mittel_s"] / ref["mittel_s"] if ref["mittel_s"] else None
    ueber_gelb = z["gelbanteil_pct"] - ref["gelbanteil"]
    ueber_braun = z["braunanteil_pct"] - ref["braunanteil"]
    hue_abw = abs(z["mittel_h"] - ref["mittel_h"])

    teil = {
        "score_gruen":      _teilscore(rel_gruen, *KENNLINIEN["gruen"]),
        "score_saettigung": _teilscore(rel_saett, *KENNLINIEN["saettigung"]),
        "score_gelb":       _teilscore(ueber_gelb, *KENNLINIEN["gelb"]),
        "score_braun":      _teilscore(ueber_braun, *KENNLINIEN["braun"]),
        "score_farbton":    _teilscore(hue_abw, *KENNLINIEN["farbton"]),
    }

    roh = sum(GEWICHTE[k] * teil["score_" + k] for k in GEWICHTE)
    teil["gesundheit_roh"] = round(roh, 2)
    teil["_rel_gruen"] = rel_gruen
    teil["_rel_saett"] = rel_saett
    teil["_ueber_gelb"] = ueber_gelb
    teil["_ueber_braun"] = ueber_braun
    return teil


def _kategorie(score):
    for grenze, name in KATEGORIEN:
        if score >= grenze:
            return name
    return "kritisch"


def _warnungen(z, t):
    """Konkrete Hinweise, was auffaellig ist - nicht nur eine Zahl."""
    w = []
    if t["_ueber_gelb"] >= WARN_GELB_PP:
        w.append("vergilbung")
    if t["_ueber_braun"] >= WARN_BRAUN_PP:
        w.append("nekrose")
    if t["_rel_gruen"] is not None and t["_rel_gruen"] <= WARN_GRUEN_REL:
        w.append("chlorose")
    if t["_rel_saett"] is not None and t["_rel_saett"] <= WARN_SAETTIGUNG_REL:
        w.append("entfaerbung")
    return w


def bewerten(zeilen):
    """Ergaenzt alle Zeilen um Gesundheitsscore, Kategorie und Warnungen."""
    ref, n = referenz_bilden(zeilen)

    if ref is None:
        for z in zeilen:
            z.update({"gesundheit_roh": None, "gesundheit": None,
                      "gesundheit_kategorie": "keine_referenz",
                      "gesundheit_trend_24h": None, "gesundheitswarnung": "",
                      "score_gruen": None, "score_gelb": None,
                      "score_braun": None, "score_saettigung": None,
                      "score_farbton": None})
        return zeilen, ref

    # 1. Rohscore je Bild
    for z in zeilen:
        t = _bewerte_zeile(z, ref)
        if t is None:
            z.update({k: None for k in ["score_gruen", "score_gelb", "score_braun",
                                        "score_saettigung", "score_farbton",
                                        "gesundheit_roh"]})
            z["gesundheitswarnung"] = ""
        else:
            z["gesundheitswarnung"] = ";".join(_warnungen(z, t))
            for k in list(t):
                if k.startswith("_"):
                    del t[k]
            z.update(t)

    # 2. Glaetten - ein einzelnes schlechtes Bild darf keinen Alarm ausloesen
    werte = [z["gesundheit_roh"] for z in zeilen]
    for i, z in enumerate(zeilen):
        fenster = [v for v in werte[max(0, i - GLAETTUNG + 1): i + 1] if v is not None]
        z["gesundheit"] = round(statistics.median(fenster), 2) if fenster else None
        z["gesundheit_kategorie"] = _kategorie(z["gesundheit"]) if fenster else "keine_daten"

    # 3. Trend ueber 24 h - Richtung ist aussagekraeftiger als der Absolutwert
    for i, z in enumerate(zeilen):
        z["gesundheit_trend_24h"] = None
        if z["gesundheit"] is None or z.get("stunden_seit_start") is None:
            continue
        ziel = z["stunden_seit_start"] - 24
        frueher = [v for v in zeilen[:i + 1]
                   if v.get("stunden_seit_start") is not None
                   and v["stunden_seit_start"] <= ziel and v["gesundheit"] is not None]
        if frueher:
            z["gesundheit_trend_24h"] = round(z["gesundheit"] - frueher[-1]["gesundheit"], 2)

    # 4. Wachstumsstillstand ergaenzen (nicht farbbasiert, aber relevant)
    for i, z in enumerate(zeilen):
        if z.get("blattflaeche_cm2") is None or z.get("stunden_seit_start") is None:
            continue
        ziel = z["stunden_seit_start"] - WARN_STILLSTAND_H
        frueher = [v for v in zeilen[:i + 1]
                   if v.get("stunden_seit_start") is not None
                   and v["stunden_seit_start"] <= ziel
                   and v.get("blattflaeche_cm2") is not None]
        if frueher and z["blattflaeche_cm2"] <= frueher[-1]["blattflaeche_cm2"] * 1.01:
            vorhanden = z["gesundheitswarnung"]
            z["gesundheitswarnung"] = (vorhanden + ";" if vorhanden else "") + "wachstumsstillstand"

    return zeilen, ref
