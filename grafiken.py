"""
BioBox - Diagramme

Aufruf:  python grafiken.py        (nach analyse.py)

Liest auswertung/ergebnis.csv und schreibt PNG-Dateien nach
auswertung/grafiken/. Auffaellige Bilder werden ausgelassen.
Die Zeitachse zeigt Datum und Uhrzeit aus dem Bildnamen.
"""

import csv
import os
import re
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")                    # speichert nur Dateien, kein Fenster
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

CSV = os.path.join("auswertung", "ergebnis.csv")
ORDNER = os.path.join("auswertung", "grafiken")
GRUEN, GELB, BRAUN, BLAU, GRAU, ROT = (
    "#2e7d32", "#f9a825", "#6d4c41", "#1565c0", "#9e9e9e", "#c62828")

# Spalten, die immer Text bleiben. Ohne diese Liste wuerde z. B. der
# Bildname "20260913_110715" von float() als Zahl gelesen - Python erlaubt
# Unterstriche als Ziffern-Trennzeichen.
TEXTSPALTEN = {"bild", "zeitquelle", "massstab_quelle", "auffaelligkeit",
               "gesundheit_kategorie", "gesundheitswarnung"}

ZEITFORMATE = [
    (r"(\d{8})[T_-](\d{6})", "%Y%m%d%H%M%S"),
    (r"(\d{8})[T_-](\d{4})(?!\d)", "%Y%m%d%H%M"),
    (r"(\d{4}-\d{2}-\d{2})[T_ ](\d{2})[-.](\d{2})[-.](\d{2})", "%Y-%m-%d%H%M%S"),
    (r"(\d{4}-\d{2}-\d{2})(?!\d)", "%Y-%m-%d"),
    (r"(\d{8})(?!\d)", "%Y%m%d"),
]


def zeit_aus_name(name):
    for muster, format_ in ZEITFORMATE:
        treffer = re.search(muster, name)
        if treffer:
            try:
                return datetime.strptime("".join(treffer.groups()), format_)
            except ValueError:
                continue
    return None


def lesen():
    """Liest die CSV und ergaenzt je Zeile den echten Zeitpunkt."""
    zeilen = []
    for z in csv.DictReader(open(CSV)):
        neu = {}
        for k, v in z.items():
            if k in TEXTSPALTEN:
                neu[k] = v
            elif v == "":
                neu[k] = None
            elif v in ("True", "False"):
                neu[k] = v == "True"
            else:
                try:
                    neu[k] = float(v)
                except ValueError:
                    neu[k] = v
        zeilen.append(neu)

    # Absolute Zeitachse: aus dem ersten lesbaren Namen wird der Startzeitpunkt
    # abgeleitet, alle uebrigen Zeiten folgen aus stunden_seit_start. Dadurch
    # bekommen auch Bilder ohne Zeitstempel im Namen die richtige Position.
    start = next((zeit_aus_name(z["bild"]) - timedelta(hours=z["stunden_seit_start"])
                  for z in zeilen if zeit_aus_name(z["bild"])), None)
    for z in zeilen:
        z["zeit"] = (start + timedelta(hours=z["stunden_seit_start"])) if start else None
    return zeilen


def paare(zeilen, feld):
    """Zeitpunkte und Werte, bei denen beides vorhanden ist."""
    x = [z["zeit"] for z in zeilen if z["zeit"] and z.get(feld) is not None]
    y = [z[feld] for z in zeilen if z["zeit"] and z.get(feld) is not None]
    return x, y


def datumsachse(ax, zeilen):
    spanne = (zeilen[-1]["zeit"] - zeilen[0]["zeit"]).total_seconds() / 3600
    ax.xaxis.set_major_formatter(mdates.DateFormatter(
        "%d.%m." if spanne > 72 else "%d.%m. %H:%M"))


def speichern(fig, name):
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(os.path.join(ORDNER, name), dpi=130)
    plt.close(fig)
    print("  ", os.path.join(ORDNER, name))


def main():
    if not os.path.exists(CSV):
        print(f"{CSV} fehlt - zuerst analyse.py ausfuehren")
        return

    alle = lesen()
    zeilen = [z for z in alle if z["brauchbar"] and z["zeit"]]
    if not zeilen:
        print("keine brauchbaren Bilder mit Zeitangabe")
        return

    os.makedirs(ORDNER, exist_ok=True)
    verworfen = len(alle) - len(zeilen)
    print(f"{len(zeilen)} Bilder in den Diagrammen"
          f"{f', {verworfen} auffaellige ausgelassen' if verworfen else ''}\n")

    # 1 Wachstum
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(*paare(zeilen, "blattflaeche_cm2"), "o-", color=GRUEN, markersize=4)
    ax.set_ylabel("projizierte Blattflaeche [cm2]")
    ax.set_title("Wachstumsverlauf")
    ax.grid(alpha=0.3)
    datumsachse(ax, zeilen)
    speichern(fig, "01_wachstum.png")

    # 2 Wachstumsrate
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x, y = paare(zeilen, "wachstumsrate_cm2_pro_tag")
    ax.bar(x, y, color=[GRUEN if v >= 0 else ROT for v in y])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Wachstumsrate [cm2/Tag]")
    ax.set_title("Wachstumsrate - negative Werte deuten auf Messfehler")
    ax.grid(alpha=0.3, axis="y")
    datumsachse(ax, zeilen)
    speichern(fig, "02_wachstumsrate.png")

    # 3 Farbe
    fig, (oben, unten) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    oben.plot(*paare(zeilen, "gruenindex"), "-", color=GRUEN)
    oben.set_ylabel("Gruenindex")
    oben.set_title("Farbentwicklung")
    oben.grid(alpha=0.3)
    for feld, farbe, name in [("gelbanteil_pct", GELB, "Gelbanteil"),
                              ("braunanteil_pct", BRAUN, "Braunanteil")]:
        unten.plot(*paare(zeilen, feld), "-", color=farbe, label=name)
    unten.set_ylabel("Anteil an Blattflaeche [%]")
    unten.legend(loc="upper left")
    unten.grid(alpha=0.3)
    datumsachse(unten, zeilen)
    speichern(fig, "03_farbverlauf.png")

    # 4 Gesundheit
    x, y = paare(zeilen, "gesundheit")
    if x:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        for u, o, farbe in [(85, 100, "#c8e6c9"), (70, 85, "#dcedc8"),
                            (50, 70, "#fff9c4"), (30, 50, "#ffe0b2"),
                            (0, 30, "#ffcdd2")]:
            ax.axhspan(u, o, color=farbe, zorder=0)
        ax.plot(x, y, "o-", color="black", markersize=4, zorder=3)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Gesundheit [0-100]")
        ax.set_title("Gesundheitsverlauf")
        ax.grid(alpha=0.2)
        datumsachse(ax, zeilen)
        speichern(fig, "04_gesundheit.png")

    # 5 Teilscores der letzten Aufnahme
    letzte = [z for z in zeilen if z.get("score_gruen") is not None]
    if letzte:
        z = letzte[-1]
        felder = ["score_gruen", "score_gelb", "score_braun",
                  "score_saettigung", "score_farbton"]
        fig, ax = plt.subplots(figsize=(7, 4))
        balken = ax.barh(["Gruen", "Gelb", "Braun", "Saettigung", "Farbton"],
                         [z[f] for f in felder], color=BLAU)
        ax.bar_label(balken, fmt="%.0f", padding=3)
        ax.set_xlim(0, 108)
        ax.set_xlabel("Teilscore [0-100]")
        ax.set_title(f"Letzte Aufnahme - Gesamt {z['gesundheit']}/100")
        ax.grid(alpha=0.3, axis="x")
        fig.tight_layout()
        fig.savefig(os.path.join(ORDNER, "05_teilscores.png"), dpi=130)
        plt.close(fig)
        print("  ", os.path.join(ORDNER, "05_teilscores.png"))


if __name__ == "__main__":
    main()
