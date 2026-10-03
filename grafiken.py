"""
BioBox - die fuenf Diagramme aus BB-REF-MERKMALE-001.

Aufruf: python grafiken.py
Liest auswertung/ergebnis.csv, schreibt auswertung/grafiken/.

Unbrauchbare Bilder werden immer ausgeschlossen. Alle fuenf Dateien werden
angelegt, auch wenn einzelne Messgroessen fehlen. Fehlende Werte werden NICHT
als Null gezeichnet. Externe Einzelbilder sind keine Wachstumszeitreihe.
"""
import csv
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

CSV = os.path.join("auswertung", "ergebnis.csv")
ORDNER = os.path.join("auswertung", "grafiken")
DATEIEN = ["01_wachstum.png", "02_wachstumsrate.png", "03_farbverlauf.png",
           "04_gesundheit.png", "05_teilscores.png"]
GRUEN, GELB, BRAUN, BLAU, ROT = "#2e7d32", "#e6a000", "#78513b", "#27628b", "#bd4545"
TEXTSPALTEN = {"bild", "ausgabe_stamm", "bildquelle", "analyse_modus", "zeitquelle",
               "massstab_quelle", "auffaelligkeit", "farbe_hex", "gesundheit_kategorie",
               "gesundheitswarnung", "scoring_version", "captured_at"}


def lesen(csv_pfad=CSV):
    with open(csv_pfad, encoding="utf-8-sig", newline="") as f:
        daten = list(csv.DictReader(f))
    zeilen = []
    for nummer, z in enumerate(daten, 1):
        neu = {"bildnummer": nummer}
        for k, v in z.items():
            if k in TEXTSPALTEN:
                neu[k] = v or ""
            elif not v:
                neu[k] = None
            elif v in ("True", "False"):
                neu[k] = v == "True"
            else:
                try:
                    neu[k] = float(v)
                except ValueError:
                    neu[k] = v
        neu["zeit"] = None
        if neu.get("analyse_modus") != "datensatz" and neu.get("captured_at"):
            try:
                neu["zeit"] = datetime.fromisoformat(neu["captured_at"].replace("Z", "+00:00"))
            except ValueError:
                pass
        zeilen.append(neu)
    return zeilen


def paare(zeilen, feld, datensatz):
    auswahl = [z for z in zeilen if z.get(feld) is not None
               and (datensatz or z.get("zeit") is not None)]
    return ([z["bildnummer"] if datensatz else z["zeit"] for z in auswahl],
            [z[feld] for z in auswahl])


def achse(ax, zeilen, datensatz):
    ax.grid(alpha=0.18)
    ax.spines[["top", "right"]].set_visible(False)
    if datensatz:
        ax.set_xlabel("Bildnummer in ergebnis.csv (keine Zeitachse)")
        ax.xaxis.get_major_locator().set_params(integer=True)
    else:
        ax.set_xlabel("Aufnahmezeit (UTC)")
        zeiten = [z["zeit"] for z in zeilen if z["zeit"]]
        spanne = (max(zeiten)-min(zeiten)).total_seconds()/3600 if zeiten else 0
        ax.xaxis.set_major_formatter(mdates.DateFormatter(
            "%d.%m." if spanne > 72 else "%d.%m. %H:%M"))


def hinweis(ax, text):
    ax.set_xticks([])
    ax.set_yticks([])
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center",
            fontsize=12, color="#52616b", linespacing=1.6,
            bbox={"boxstyle": "round,pad=1", "facecolor": "#f3f6f7", "edgecolor": "none"})
    ax.spines[:].set_visible(False)


def speichern(fig, name, ordner, fuss):
    fig.text(0.02, 0.015, fuss, fontsize=8, color="#66727b")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(ordner, name), dpi=150, facecolor="white")
    plt.close(fig)
    print("  ", os.path.join(ordner, name))


def main(csv_pfad=CSV, ordner=ORDNER):
    if not os.path.exists(csv_pfad):
        print(f"{csv_pfad} fehlt - zuerst analyse.py ausfuehren")
        return
    alle = lesen(csv_pfad)
    datensatz = bool(alle and alle[0].get("analyse_modus") == "datensatz")
    zeilen = [z for z in alle if z.get("brauchbar") is True
              and (datensatz or z.get("zeit") is not None)]
    os.makedirs(ordner, exist_ok=True)
    # Auch die zwei frueheren Datensatzgrafiken entfernen.
    for name in DATEIEN + ["01_pflanzenpixel.png", "02_farbwerte.png"]:
        pfad = os.path.join(ordner, name)
        if os.path.exists(pfad):
            os.remove(pfad)
    fuss = (f"BioBox | {len(zeilen)} brauchbare Bilder | "
            f"{len(alle)-len(zeilen)} Bilder ausgeschlossen | "
            + ("Externer Testdatensatz" if datensatz else "Pflanzenzeitreihe"))
    leer = "Keine brauchbaren Bilder.\nQualitaetsflags in ergebnis.csv und Kontrollbilder pruefen."

    # 1: Echte Flaeche ueber der Zeit oder klar gekennzeichnete Pixel-Rohwerte.
    fig, ax = plt.subplots(figsize=(10, 5))
    if datensatz:
        x, y = paare(zeilen, "pflanzen_pixel", True)
        ax.set_title("01 | Pflanzenflaeche je Einzelbild - Datensatztest")
        ax.set_ylabel("Segmentierte Pflanzenpixel [px]")
        if x:
            ax.bar(x, y, color=GRUEN)
            achse(ax, zeilen, True)
            ax.text(0.02, 0.98, "Pixelwerte: kein cm2-Massstab, kein Wachstumsverlauf",
                    transform=ax.transAxes, va="top", fontsize=9)
        else:
            hinweis(ax, leer)
    else:
        ax.set_title("01 | Wachstumsverlauf")
        ax.set_ylabel("Projizierte Blattflaeche [cm2]")
        x, y = paare(zeilen, "blattflaeche_cm2", False)
        if x:
            ax.plot(x, y, "o-", color=GRUEN, markersize=4)
            achse(ax, zeilen, False)
        else:
            hinweis(ax, "Keine kalibrierten Flaechen mit Aufnahmezeit.\nMassstab und Zeitquelle pruefen.")
    speichern(fig, DATEIEN[0], ordner, fuss)

    # 2: Nie die Groessendifferenz verschiedener Pflanzen als Wachstum ausgeben.
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.set_title("02 | Wachstumsrate")
    x, y = paare(zeilen, "wachstumsrate_cm2_pro_tag", False) if not datensatz else ([], [])
    if x:
        ax.bar(x, y, width=0.015, color=[GRUEN if v >= 0 else ROT for v in y])
        ax.axhline(0, color="#555", linewidth=0.8)
        ax.set_ylabel("Wachstumsrate [cm2/Tag]")
        achse(ax, zeilen, False)
    else:
        hinweis(ax, "Keine Wachstumsrate berechenbar.\nNoetig: dieselbe Pflanze zu mehreren Aufnahmezeiten\nund ein verifizierter Massstab in mm/px.")
    speichern(fig, DATEIEN[1], ordner, fuss)

    # 3: Farbwerte sind auch im Einzelbildmodus messbar.
    fig, (oben, unten) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    oben.set_title("03 | " + ("Farbwerte je Einzelbild" if datensatz else "Farbverlauf"))
    x, y = paare(zeilen, "gruenindex", datensatz)
    if x:
        if datensatz:
            oben.scatter(x, y, s=22, color=GRUEN)
        else:
            oben.plot(x, y, "o-", markersize=3, color=GRUEN)
        oben.set_ylabel("Gruenindex G / (R+G+B)")
        for feld, farbe, label in [("gelbanteil_pct", GELB, "Gelbanteil"),
                                   ("braunanteil_pct", BRAUN, "Braunanteil")]:
            x, y = paare(zeilen, feld, datensatz)
            unten.plot(x, y, "o" if datensatz else "o-", markersize=4,
                       color=farbe, label=label)
        unten.set_ylabel("Anteil in Pflanzenmaske [%]")
        unten.legend()
        achse(oben, zeilen, datensatz)
        achse(unten, zeilen, datensatz)
        oben.set_xlabel("")
    else:
        hinweis(oben, leer)
        hinweis(unten, "Keine auswertbaren Farbwerte.")
    speichern(fig, DATEIEN[2], ordner, fuss)

    # 4: Relative Gesundheit ausschliesslich aus einer eigenen Referenz.
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.set_title("04 | Gesundheitsverlauf")
    x, y = paare(zeilen, "gesundheit", False) if not datensatz else ([], [])
    if x:
        for u, o, farbe in [(85, 100, "#d6eaca"), (70, 85, "#e6edca"),
                            (50, 70, "#fcf1cb"), (30, 50, "#fce0c4"),
                            (0, 30, "#f6d2d2")]:
            ax.axhspan(u, o, color=farbe)
        ax.plot(x, y, "o-", color="#25333b", markersize=4)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Relativer Gesundheitsindex [0-100]")
        achse(ax, zeilen, False)
    else:
        hinweis(ax, "Keine relative Gesundheitsbewertung.\nNoetig: mindestens 3 brauchbare Referenzbilder\nderselben Pflanze bei gleicher Kamera und Beleuchtung.\nDie Referenz muss per Sichtpruefung freigegeben sein.")
    speichern(fig, DATEIEN[3], ordner, fuss)

    # 5: Letzte gueltige Aufnahme mit vollstaendigen Teilscores.
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.set_title("05 | Teilscores der letzten gueltigen Aufnahme")
    felder = ["score_gruen", "score_gelb", "score_braun", "score_saettigung", "score_farbton"]
    bewertet = [z for z in zeilen if all(z.get(k) is not None for k in felder)] if not datensatz else []
    if bewertet:
        z = bewertet[-1]
        balken = ax.barh(["Gruen (30 %)", "Gelb (25 %)", "Braun (20 %)",
                         "Saettigung (15 %)", "Farbton (10 %)"],
                        [z[k] for k in felder], color=BLAU)
        ax.bar_label(balken, fmt="%.1f", padding=3)
        ax.set_xlim(0, 110)
        ax.set_xlabel("Teilscore [0-100]")
        ax.set_title(f"05 | {z['bild']} - Gesamt {z['gesundheit']}/100", fontsize=11)
        ax.grid(alpha=0.18, axis="x")
        ax.spines[["top", "right"]].set_visible(False)
    else:
        hinweis(ax, "Keine Teilscores vorhanden.\nGruen, Gelb, Braun, Saettigung und Farbton\nwerden gegen die eigene freigegebene Referenz bewertet.\nVerschiedene Pflanzen sind keine gemeinsame Referenz.")
    speichern(fig, DATEIEN[4], ordner, fuss)


if __name__ == "__main__":
    main()
