"""
BioBox - Diagramme aus den Auswertungsdaten

Aufruf:  python grafiken.py

Liest auswertung/ergebnisse.csv und auswertung/gesundheit.csv
und schreibt PNG-Dateien nach auswertung/grafiken/.

Auffaellige Bilder (brauchbar = False) werden nicht geplottet.
"""

import csv
import os

import matplotlib
matplotlib.use("Agg")                 # ohne Bildschirm, speichert nur Dateien
import matplotlib.pyplot as plt

AUSGABE = "auswertung"
ORDNER = os.path.join(AUSGABE, "grafiken")

FARBEN = {"gruen": "#2e7d32", "gelb": "#f9a825", "braun": "#6d4c41",
          "blau": "#1565c0", "grau": "#9e9e9e", "rot": "#c62828"}


def csv_lesen(pfad):
    """Liest eine CSV und wandelt Zahlen in float, leere Felder in None."""
    if not os.path.exists(pfad):
        return []
    zeilen = []
    for z in csv.DictReader(open(pfad)):
        neu = {}
        for k, v in z.items():
            if v == "":
                neu[k] = None
            elif v in ("True", "False"):
                neu[k] = v == "True"
            else:
                try:
                    neu[k] = float(v)
                except ValueError:
                    neu[k] = v
            neu[k] = neu[k]
        zeilen.append(neu)
    return zeilen


def spalten(zeilen, x, y):
    """Liefert zwei Listen mit den Paaren, bei denen beide Werte da sind."""
    xs, ys = [], []
    for z in zeilen:
        if z.get(x) is not None and z.get(y) is not None:
            xs.append(z[x])
            ys.append(z[y])
    return xs, ys


def speichern(fig, name):
    fig.tight_layout()
    pfad = os.path.join(ORDNER, name)
    fig.savefig(pfad, dpi=130)
    plt.close(fig)
    print("  ", pfad)


# --- Einzelne Diagramme ----------------------------------------------
def wachstum(mess):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x, y = spalten(mess, "stunden_seit_start", "blattflaeche_cm2")
    if not x:
        plt.close(fig)
        return
    ax.plot(x, y, "o-", color=FARBEN["gruen"], markersize=4)
    ax.set_xlabel("Stunden seit Beginn")
    ax.set_ylabel("projizierte Blattflaeche [cm2]")
    ax.set_title("Wachstumsverlauf")
    ax.grid(alpha=0.3)
    speichern(fig, "01_wachstum.png")


def wachstumsrate(mess):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x, y = spalten(mess, "stunden_seit_start", "wachstumsrate_cm2_pro_tag")
    if not x:
        plt.close(fig)
        return
    ax.bar(x, y, width=max(1, (max(x) - min(x)) / max(len(x), 1) * 0.8),
           color=[FARBEN["gruen"] if v >= 0 else FARBEN["rot"] for v in y])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Stunden seit Beginn")
    ax.set_ylabel("Wachstumsrate [cm2/Tag]")
    ax.set_title("Wachstumsrate - negative Werte deuten auf Messfehler oder Blattverlust")
    ax.grid(alpha=0.3, axis="y")
    speichern(fig, "02_wachstumsrate.png")


def farbverlauf(mess):
    fig, (oben, unten) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

    x, y = spalten(mess, "stunden_seit_start", "gruenindex")
    oben.plot(x, y, "-", color=FARBEN["gruen"], label="Gruenindex")
    oben.set_ylabel("Gruenindex")
    oben.legend(loc="upper right")
    oben.grid(alpha=0.3)
    oben.set_title("Farbentwicklung")

    for feld, farbe, name in [("gelbanteil_pct", FARBEN["gelb"], "Gelbanteil"),
                              ("braunanteil_pct", FARBEN["braun"], "Braunanteil")]:
        x, y = spalten(mess, "stunden_seit_start", feld)
        unten.plot(x, y, "-", color=farbe, label=name)
    unten.set_xlabel("Stunden seit Beginn")
    unten.set_ylabel("Anteil an Blattflaeche [%]")
    unten.legend(loc="upper left")
    unten.grid(alpha=0.3)
    speichern(fig, "03_farbverlauf.png")


def gesundheitsverlauf(ges):
    x, y = spalten(ges, "stunden_seit_start", "gesundheit")
    if not x:
        return
    fig, ax = plt.subplots(figsize=(9, 4.5))

    for unten, oben, farbe in [(8.5, 10, "#c8e6c9"), (7.0, 8.5, "#dcedc8"),
                               (5.0, 7.0, "#fff9c4"), (3.0, 5.0, "#ffe0b2"),
                               (0.0, 3.0, "#ffcdd2")]:
        ax.axhspan(unten, oben, color=farbe, zorder=0)

    ax.plot(x, y, "o-", color="black", markersize=4, zorder=3)
    ax.set_ylim(0, 10)
    ax.set_xlabel("Stunden seit Beginn")
    ax.set_ylabel("Gesundheit [0-10]")
    ax.set_title("Gesundheitsverlauf")
    ax.grid(alpha=0.2, zorder=1)
    speichern(fig, "04_gesundheit.png")


def teilscores(ges):
    letzte = [z for z in ges if z.get("score_gruen") is not None]
    if not letzte:
        return
    z = letzte[-1]
    namen = ["Gruen", "Gelb", "Braun", "Saettigung", "Farbton"]
    felder = ["score_gruen", "score_gelb", "score_braun",
              "score_saettigung", "score_farbton"]
    werte = [z[f] for f in felder]

    fig, ax = plt.subplots(figsize=(7, 4))
    balken = ax.barh(namen, werte, color=FARBEN["blau"])
    ax.bar_label(balken, fmt="%.1f", padding=3)
    ax.set_xlim(0, 10.8)
    ax.set_xlabel("Teilscore [0-10]")
    ax.set_title(f"Aufschluesselung letzte Aufnahme - Gesamt {z['gesundheit']}/10")
    ax.grid(alpha=0.3, axis="x")
    speichern(fig, "05_teilscores.png")


def bildqualitaet(mess):
    fig, (a, b) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)

    x, y = spalten(mess, "stunden_seit_start", "mm_pro_pixel")
    a.plot(x, y, "-", color=FARBEN["blau"])
    a.set_ylabel("mm pro Pixel")
    a.set_title("Massstab und Helligkeit - beides muss konstant bleiben")
    a.grid(alpha=0.3)
    if y:
        mitte = sum(y) / len(y)
        a.axhline(mitte * 1.01, color=FARBEN["rot"], linestyle="--", linewidth=0.8)
        a.axhline(mitte * 0.99, color=FARBEN["rot"], linestyle="--", linewidth=0.8)

    x, y = spalten(mess, "stunden_seit_start", "bildhelligkeit")
    b.plot(x, y, "-", color=FARBEN["grau"])
    b.set_xlabel("Stunden seit Beginn")
    b.set_ylabel("mittlere Bildhelligkeit")
    b.grid(alpha=0.3)
    speichern(fig, "06_bildqualitaet.png")


# --- Hauptprogramm ---------------------------------------------------
def main():
    alle_mess = csv_lesen(os.path.join(AUSGABE, "ergebnisse.csv"))
    alle_ges = csv_lesen(os.path.join(AUSGABE, "gesundheit.csv"))

    if not alle_mess:
        print("auswertung/ergebnisse.csv fehlt - zuerst analyse.py ausfuehren")
        return

    gut = {z["bild"] for z in alle_mess if z.get("brauchbar")}
    mess = [z for z in alle_mess if z["bild"] in gut]
    ges = [z for z in alle_ges if z["bild"] in gut]

    verworfen = len(alle_mess) - len(mess)
    os.makedirs(ORDNER, exist_ok=True)
    print(f"{len(mess)} Bilder in den Diagrammen"
          f"{f', {verworfen} auffaellige ausgelassen' if verworfen else ''}\n")

    wachstum(mess)
    wachstumsrate(mess)
    farbverlauf(mess)
    gesundheitsverlauf(ges)
    teilscores(ges)
    bildqualitaet(mess)


if __name__ == "__main__":
    main()
