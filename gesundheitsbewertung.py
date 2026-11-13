"""A-M3 · Gesundheitsbewertung: Lichtabgleich, Teilwerte und Gesundheitsscore."""

import argparse
import base64
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from bilderfassungssystem import historienzeit, vorhandene_bilder
from computer_vision_pipeline import (
    GESUND_JSON_DATEI, _kern, auswertung_sperren, browseransicht_oeffnen,
    ergebnis_export, ergebnis_standardordner, ergebnishistorie_laden, farbmerkmale,
    json_ausgabe_schreiben, json_sicher, ohne_json_nulls, viewer_ordner,
)


# Einstellungen für Referenz und Bewertung
REFERENZ_FREIGEGEBEN = False  # Kennzeichnet den Score; blockiert ihn nicht.
SCORING_VERSION = "4.1.0"

# Gewicht der Farbteilwerte und Kennlinien der Bewertung.
GEWICHTE = {"gruen": .30, "gelb": .20, "braun": .25, "saettigung": .15, "farbton": .10}
HALBWERTE = {"hist": .20, "gruenindex": .024, "gelb": 8., "braun": 4.5,
             "saettigung": .23, "farbton": 8., "flaeche": .19, "form": .52, "lokal": 12.}


def stetiger_score(abweichung, halbwert):
    """Stetig: 100 bei Null, 50 beim Halbwert; Toleranzen werden je Merkmal abgezogen."""
    d = max(0.0, float(abweichung))/halbwert
    return float(100*math.exp(-math.log(2)*min(d, 30)**2))


def licht_anwenden(bild, info):
    """Am unbewegten Hintergrund gelernte Abbildung auf andere Aufloesung anwenden."""
    koeff = info.get("_koeff")
    if koeff is None:
        return bild.copy()
    h, w = bild.shape[:2]
    x = np.linspace(-1,1,w,dtype=np.float32)[None,:]
    y = np.linspace(-1,1,h,dtype=np.float32)[:,None]
    out = np.empty(bild.shape,np.float32)
    for k,a in enumerate(koeff):
        t = bild[:,:,k].astype(np.float32)/255
        out[:,:,k] = a[0]+a[1]*t+a[2]*t*t+a[3]*t*x+a[4]*t*y
    return np.rint(np.clip(out,0,1)*255).astype(np.uint8)


def farbe_ohne_helligkeit(bild, gain=None):
    rgb = bild.astype(np.float32)
    if gain is not None:
        rgb *= np.asarray(gain,dtype=np.float32)
    rgb *= 160./np.maximum(1.,rgb.max(axis=2,keepdims=True))
    return np.rint(rgb).clip(0,255).astype(np.uint8)


def chromatik_abgleichen(arbeit, ref_bild, idx, xx, yy, info):
    """Weissabgleich aus Farbverhaeltnissen in nachweislich stabilen Bildteilen."""
    h,w = arbeit.shape[:2]
    cur = arbeit.reshape(-1,3)[idx].astype(float)
    alt = ref_bild.reshape(-1,3)[idx].astype(float)
    ok = (cur.min(axis=1)>=12)&(alt.min(axis=1)>=12)
    train = ok & (np.arange(len(idx))%4!=0)
    test = ok & ~train
    if np.count_nonzero(train)<300 or np.count_nonzero(test)<120:
        return None
    def log_chroma(bgr):
        return np.log(bgr[:,[0,2]]/bgr[:,[1]])
    delta = log_chroma(alt)-log_chroma(cur)
    gain = np.median(delta[train],axis=0)
    if np.max(np.abs(gain))>.40:
        return None
    fehler = np.max(np.abs(delta-gain),axis=1)
    raster = (4*yy//h)*4+4*xx//w
    felder = []
    for i in range(16):
        probe = fehler[test & (raster==i)]
        if len(probe)>=45 and np.median(probe)<=.09 and np.percentile(probe,75)<=.145:
            felder.append(i)
    stabil = test & np.isin(raster,felder)
    if (len(felder)<4 or len({i//4 for i in felder})<2 or len({i%4 for i in felder})<2
            or np.count_nonzero(stabil)<.30*np.count_nonzero(test)):
        return None
    zone = np.zeros((h,w),np.uint8)
    for i in felder:
        y,x = divmod(i,4)
        zone[y*h//4:(y+1)*h//4,x*w//4:(x+1)*w//4] = 255
    zone = cv2.dilate(zone,_kern(max(3,round(.10*min(h,w)))))
    info.update(modell="chromatik_teilflaeche",korrigiert=True,_lichtzone=zone,
                chroma_residual=round(float(np.median(fehler[stabil])),4))
    return farbe_ohne_helligkeit(arbeit,[np.exp(gain[0]),1.,np.exp(gain[1])])


def licht_abgleichen(arbeit, maske, ref_bild=None, ref_maske=None, chroma_erlaubt=False):
    """Robuste Belichtungs-/Weissabgleichkorrektur NUR aus Hintergrundpaaren.

    Die Pflanze wird nie an ihre alte Farbe angepasst. Linear, Gamma-Naeherung
    und langsamer Beleuchtungsgradient werden auf getrennten Pixeln validiert.
    Misslingt die Messung, entsteht kein erfundener besserer/schlechterer Score.
    """
    info = {"modell":"referenz", "korrigiert":False, "hintergrund_fehler":None,
            "hintergrund_anteil_pct":None}
    if ref_bild is None:
        return arbeit.copy(), [], info
    if ref_maske is None or arbeit.shape != ref_bild.shape:
        return None, ["lichtvergleich_nicht_verifiziert"], info
    if np.array_equal(arbeit,ref_bild):
        info.update(modell="identisch",hintergrund_fehler=0.)
        return arbeit.copy(),[],info
    h,w = maske.shape
    bg = cv2.dilate(cv2.bitwise_or(maske,ref_maske),np.ones((31,31),np.uint8)) == 0
    # Nur lineare, nicht geclippte Kamerawerte zum Lernen verwenden.
    bg &= np.all((arbeit > 5)&(arbeit < 249)&(ref_bild > 5)&(ref_bild < 249),axis=2)
    idx = np.flatnonzero(bg)
    info["hintergrund_anteil_pct"] = round(100*len(idx)/bg.size,2)
    if len(idx) < max(300,round(.035*bg.size)):
        return None, ["licht_hintergrund_unzureichend"], info
    idx = idx[np.linspace(0,len(idx)-1,min(len(idx),14000)).astype(int)]
    yy,xx = np.divmod(idx,w)
    x,y = 2*xx/max(w-1,1)-1,2*yy/max(h-1,1)-1
    cur = arbeit.reshape(-1,3)[idx].astype(float)/255
    alt = ref_bild.reshape(-1,3)[idx].astype(float)/255
    train = np.arange(len(idx)) % 4 != 0
    valid = ~train

    def anpassen(modell):
        koeff,fehler = [],[]
        for k in range(3):
            t = cur[:,k]
            X = np.stack([np.ones_like(t),t,t*t,t*x,t*y],axis=1)
            auswahl = {"linear":[0,1],"kurve":[0,1,2],"gradient":[0,1,2,3,4]}[modell]
            # Auf einem fast einfarbigen Hintergrund ist nur ein Gain messbar.
            if np.ptp(np.percentile(t,[5,95])) < .07:
                a = np.array([0.,float(np.median(alt[:,k]/np.maximum(t,1e-5))),0.,0.,0.])
            else:
                A,B = X[train][:,auswahl],alt[train,k]
                gew = np.ones(len(B))
                start = np.array([0.,1.,0.,0.,0.])[auswahl]
                for _ in range(5):
                    W = np.sqrt(gew)
                    reg = np.eye(len(auswahl))*.12
                    v = np.linalg.lstsq(np.vstack([A*W[:,None],reg]),
                                       np.r_[B*W,reg@start],rcond=None)[0]
                    e = A@v-B
                    sigma = max(.003,1.4826*float(np.median(np.abs(e-np.median(e)))))
                    gew = np.minimum(1.,2.5*sigma/(np.abs(e)+1e-8))
                a = np.zeros(5);a[auswahl] = v
            # Die Kurve muss im ganzen Bild sinnvoll und monoton bleiben.
            ableitungen = [a[1]+2*a[2]*t0+a[3]*x0+a[4]*y0
                           for t0 in (0,1) for x0 in (-1,1) for y0 in (-1,1)]
            if min(ableitungen) < .08 or max(ableitungen) > 6 or abs(a[0]) > .25:
                return None,None
            koeff.append(a.tolist())
            fehler.append(np.abs(X[valid]@a-alt[valid,k])*255)
        fehler = np.mean(fehler,axis=0)
        return koeff,fehler

    best,errors = anpassen("linear")
    name = "linear"
    for modell in ("kurve","gradient"):
        a,e = anpassen(modell)
        if a is not None and (best is None or np.median(e)+.15 < .75*np.median(errors)):
            best,errors,name = a,e,modell
    # Fehler durch Helligkeit, Schatten und bewegte Gegenstaende nicht mit
    # Farbfehlern gleichsetzen. Die Rueckfallebene prueft Farbverhaeltnisse.
    voll_verifiziert = False
    if best is not None:
        info.update(modell=name,hintergrund_fehler=round(float(np.median(errors)),3))
        raster = (4*yy[valid]//h)*4+4*xx[valid]//w
        regional = [float(np.median(errors[raster==feld])) for feld in np.unique(raster)
                    if np.count_nonzero(raster==feld)>=45]
        voll_verifiziert = (np.median(errors)<=5. and np.percentile(errors,90)<=16.
                             and (not regional or max(regional)<=13.))
    if not voll_verifiziert:
        farbe = chromatik_abgleichen(arbeit,ref_bild,idx,xx,yy,info) if chroma_erlaubt else None
        if farbe is not None:
            return farbe,[],info
        return None,["lichtkorrektur_nicht_stabil"],info
    info["_koeff"] = best
    normal = licht_anwenden(arbeit,info)
    info["korrigiert"] = bool(np.mean(np.abs(normal.astype(float)-arbeit)) > .6)
    return normal,[],info


def blattverteilung_vergleichen(arbeit, maske, korrigiert, ref_bild, ref_maske, info):
    """Neue Blaetter zulassen, ohne Hintergrund oder Belichtung als Schaden zu werten.

    Voraussetzung ist die bereits registrierte Kameraansicht und eine auf
    Hintergrundpaaren verifizierte Licht-/Chromatikkorrektur. Verglichen werden
    die getrennten Blattfarbverteilungen, keine erfundenen Pixelpaare.
    """
    kern = cv2.erode(maske, _kern(3)) > 0
    alt_kern = cv2.erode(ref_maske, _kern(3)) > 0
    counts = [int(np.count_nonzero(kern)), int(np.count_nonzero(alt_kern))]
    if min(counts) < 100:
        return None, ["zu_wenig_blattflaeche_fuer_verteilungsvergleich"]
    chromatisch = info.get("modell") == "chromatik_teilflaeche"
    if chromatisch:
        zone = info.get("_lichtzone")
        if zone is None or zone.shape != maske.shape:
            return None, ["lichtvergleich_nicht_verifiziert"]
        anteile = [np.count_nonzero(kern & (zone > 0))/counts[0],
                   np.count_nonzero(alt_kern & (zone > 0))/counts[1]]
        info["chromatisch_gepruefte_blattflaeche_pct"] = round(100*min(anteile), 2)
        if min(anteile) < .65:
            return None, ["zu_wenig_bestaetigte_farbteilflaeche"]
        kern &= zone > 0
        alt_kern &= zone > 0
    elif info.get("modell") not in ("linear", "kurve", "gradient", "identisch"):
        return None, ["lichtvergleich_nicht_verifiziert"]
    # Unwiederbringlich geclippte / schwarze Blattpixel je Foto ausschliessen.
    # Neue Blattpositionen duerfen nicht am damaligen Hintergrund scheitern.
    for bild, auswahl in ((arbeit, kern), (ref_bild, alt_kern)):
        schlecht = (np.any(bild >= 254, axis=2) | (np.max(bild, axis=2) < 12))
        schlecht = cv2.dilate(schlecht.astype(np.uint8), _kern(3)) > 0
        auswahl[schlecht] = False
    behalten = [int(np.count_nonzero(kern)), int(np.count_nonzero(alt_kern))]
    anteil = min(behalten[0]/counts[0], behalten[1]/counts[1])
    info["blattpixel_ausgeschlossen_pct"] = round(100*(1-anteil), 2)
    if min(behalten) < 100 or anteil < .65:
        return None, ["lichtvergleich_zu_wenig_blattgewebe"]
    jetzt_bild = korrigiert
    vorher_bild = farbe_ohne_helligkeit(ref_bild) if chromatisch else ref_bild
    cur = farbmerkmale(jetzt_bild, kern.astype(np.uint8)*255)
    alt = farbmerkmale(vorher_bild, alt_kern.astype(np.uint8)*255)
    def lab_pixel(bild, auswahl):
        pixel = bild[auswahl].reshape(-1, 1, 3).astype(np.float32)/255
        return cv2.cvtColor(pixel, cv2.COLOR_BGR2LAB).reshape(-1, 3)
    jetzt, vorher = lab_pixel(jetzt_bild, kern), lab_pixel(vorher_bild, alt_kern)
    quantile = np.linspace(.02, .98, 49)
    # Quantile brauchen weder dieselbe Blattposition noch gleich viele Pixel.
    delta = np.quantile(jetzt[:, 1:], quantile, axis=0)-np.quantile(vorher[:, 1:], quantile, axis=0)
    cur["_lokal_farb_pp"] = 100*float(np.clip((np.linalg.norm(delta, axis=1)-4)/17, 0, 1).mean())
    def warmwerte(lab):
        l, a, b = lab.T
        gelb = np.clip((a+18)/22, 0, 1)*np.clip((b-9)/23, 0, 1)
        braun = np.clip((a+8)/18, 0, 1)*np.clip((b-3)/14, 0, 1)*np.clip((64-l)/35, 0, 1)
        return (gelb if chromatisch else np.maximum(gelb, braun), braun)
    warm, braun = warmwerte(jetzt)
    warm_alt, braun_alt = warmwerte(vorher)
    cur["_warm_delta"] = 100*max(0., float(warm.mean()-warm_alt.mean()))
    cur["_braun_delta"] = 100*max(0., float(braun.mean()-braun_alt.mean()))
    cur.update(_vergleich_basis=alt, _chromatisch=chromatisch, _blattverteilung=True)
    return cur, ["gesundheit_ueber_blattfarbverteilung"]


def gesundheitsmerkmale(arbeit, maske, ref_bild=None, ref_maske=None, abgleich=None):
    """Gemeinsames Blattgewebe; bei Wachstum verifizierte Farbverteilungen."""
    korrigiert, flags, info = abgleich if abgleich is not None else licht_abgleichen(arbeit,maske,ref_bild,ref_maske)
    if korrigiert is None or ref_bild is None or ref_maske is None:
        return None, flags or ["lichtvergleich_nicht_verifiziert"]
    # Ein Pixel Rand Abstand vermindert Mischfarben aus Blatt und Hintergrund.
    kern = cv2.erode(maske, _kern(3))
    ref_kern = cv2.erode(ref_maske, _kern(3))
    gemeinsam = (kern > 0) & (ref_kern > 0)
    n = int(np.count_nonzero(gemeinsam))
    n_cur, n_ref = cv2.countNonZero(kern), cv2.countNonZero(ref_kern)
    anteil = n/max(1,min(n_cur,n_ref))
    info["gemeinsame_blattflaeche_pct"] = round(100*anteil,2)
    if n < 50 or anteil < .60 or n < .35*max(n_cur,n_ref):
        cur, pruefung = blattverteilung_vergleichen(arbeit, maske, korrigiert, ref_bild, ref_maske, info)
        return cur, flags+pruefung
    # Vor der Korrektur gesaettigte bzw. zu dunkle Pixel sind nicht wiederherstellbar.
    schlecht = (np.any(arbeit >= 254,axis=2) | (np.max(arbeit,axis=2) < 12)
                | np.any(ref_bild >= 254,axis=2) | (np.max(ref_bild,axis=2) < 12))
    schlecht = cv2.dilate(schlecht.astype(np.uint8), _kern(3)) > 0
    chromatisch = info.get("modell")=="chromatik_teilflaeche"
    if chromatisch:
        gemeinsam &= info["_lichtzone"]>0
        teiln = int(np.count_nonzero(gemeinsam))
        info["chromatisch_gepruefte_blattflaeche_pct"] = round(100*teiln/max(1,n),2)
        if teiln<max(50,.30*n):
            return None,flags+["zu_wenig_bestaetigte_farbteilflaeche"]
        n = teiln
    gueltig = gemeinsam & ~schlecht
    vergleichbar = int(np.count_nonzero(gueltig))
    info["blattpixel_ausgeschlossen_pct"] = round(100*(1-vergleichbar/max(1,n)),2)
    if vergleichbar < 50 or vergleichbar < .65*n:
        return None, flags + ["lichtvergleich_zu_wenig_blattgewebe"]
    g = gueltig.astype(np.uint8)*255
    if chromatisch:
        ref_bild = farbe_ohne_helligkeit(ref_bild)
    cur = farbmerkmale(korrigiert,g)
    cur["_chromatisch"] = chromatisch
    alt = farbmerkmale(ref_bild,g)
    # Kontinuierliche lokale Kennwerte fuer kleine Verfaerbungen. Gleiche
    # Bildpositionen werden verglichen; unveraenderte Panaschierung faellt heraus.
    def lab_pixel(bild):
        pixel = bild[gueltig].reshape(-1,1,3).astype(np.float32)/255
        return cv2.cvtColor(pixel,cv2.COLOR_BGR2LAB).reshape(-1,3)
    jetzt, vorher = lab_pixel(korrigiert), lab_pixel(ref_bild)
    delta = jetzt[:,1:]-vorher[:,1:]
    farbabstand = np.linalg.norm(delta,axis=1)
    def warmwerte(lab):
        l,a,b = lab.T
        gelb = np.clip((a+18)/22,0,1)*np.clip((b-9)/23,0,1)
        braun = np.clip((a+8)/18,0,1)*np.clip((b-3)/14,0,1)*np.clip((64-l)/35,0,1)
        return (gelb,braun) if chromatisch else (np.maximum(gelb,braun),braun)
    warm,braun = warmwerte(jetzt)
    warm_alt,braun_alt = warmwerte(vorher)
    # Ohne Rotverschiebung keine Braunzunahme durch eine dunklere Stelle.
    signal = np.clip((delta[:,0]-2)/7,0,1)
    cur["_warm_delta"] = 100*float(np.maximum(0.,warm-warm_alt).mean())
    cur["_braun_delta"] = 100*float((np.maximum(0.,braun-braun_alt)*signal).mean())
    cur["_lokal_farb_pp"] = 100*float(np.clip((farbabstand-4)/17,0,1).mean())
    cur["_vergleich_basis"] = alt
    return cur, flags


def bewerten(z, merkmale_gesund, ref, struktur_erlaubt=True):
    if merkmale_gesund is None or not z["brauchbar"]:
        z["gesundheit_status"] = "nicht_auswertbar"
        z["gesundheit_kategorie"] = "keine_daten"
        return
    cur, alt = merkmale_gesund, merkmale_gesund["_vergleich_basis"]
    hist_abstand = float(cv2.compareHist(cur["_hist"],alt["_hist"],cv2.HISTCMP_BHATTACHARYYA))
    gruenverlust = max(0.,alt["gruenindex"]-cur["gruenindex"]-.002)
    lokal = cur["_lokal_farb_pp"]
    z["score_gruen"] = (.42*stetiger_score(max(0.,hist_abstand-.018), HALBWERTE["hist"])
                        + .26*stetiger_score(gruenverlust,HALBWERTE["gruenindex"])
                        + .32*stetiger_score(lokal,HALBWERTE["lokal"]))
    # Warm schliesst Gelb und Braun ein: weiter gebraeuntes Gewebe wird
    # dadurch nicht allein wegen geringerer Gelbflaeche als erholt bewertet.
    gelb_delta = cur["_warm_delta"]
    braun_delta = cur["_braun_delta"]
    z["score_gelb"] = stetiger_score(max(0.,gelb_delta-.4),HALBWERTE["gelb"])
    chromatisch = cur.get("_chromatisch",False)
    z["score_braun"] = None if chromatisch else stetiger_score(max(0.,braun_delta-.3),HALBWERTE["braun"])
    saett_delta = abs(math.log((cur["mittel_s"]+8)/(alt["mittel_s"]+8)))
    z["score_saettigung"] = stetiger_score(max(0.,saett_delta-.025),HALBWERTE["saettigung"])
    hue_delta = 0.
    if cur["mittel_h"] is not None and alt["mittel_h"] is not None:
        d = abs(cur["mittel_h"]-alt["mittel_h"])
        hue_delta = min(d,180-d)
    lab_delta = float(np.linalg.norm(cur["_lab"][1:]-alt["_lab"][1:]))
    z["score_farbton"] = stetiger_score(max(0.,max(hue_delta,lab_delta/2)-.7),HALBWERTE["farbton"])
    gewicht_summe = sum(GEWICHTE[k] for k in GEWICHTE if z["score_"+k] is not None)
    teile = [(GEWICHTE[k]/gewicht_summe,z["score_"+k]) for k in GEWICHTE if z["score_"+k] is not None]
    struktur_erlaubt = struktur_erlaubt and not chromatisch and not cur.get("_blattverteilung", False)
    flaechenverlust = max(0., 1-z["pflanzen_pixel"]/max(1,ref["meta"]["pflanzen_pixel"]))
    z["_struktur_score"] = None
    if struktur_erlaubt:
        # Form ist nur Zusatzinformation bei Flaechenverlust. Wachstum oder
        # ein neues Blatt allein sollen den Index nicht verschlechtern.
        form_delta = 0.
        if z["kompaktheit"] and ref["meta"].get("kompaktheit"):
            form_delta = max(0.,abs(math.log(z["kompaktheit"]/ref["meta"]["kompaktheit"]))-.15)
        flaeche = stetiger_score(max(0.,flaechenverlust-.035),HALBWERTE["flaeche"])
        form = stetiger_score(form_delta,HALBWERTE["form"])
        struktur = flaeche*(1-.2*min(1.,flaechenverlust/.15)*(1-form/100))
        z["_struktur_score"] = struktur
        teile = [(gewicht*.85,score) for gewicht,score in teile] + [(.15,struktur)]
    # Arithmetisches und geometrisches Mittel: ein ausgepraegtes Symptom
    # kann den Index sichtbar senken, ohne dass ein einziger Teil ihn auf 0 setzt.
    arith = sum(wert*gewicht for gewicht,wert in teile)
    geo = math.exp(sum(gewicht*math.log(max(.01,wert)) for gewicht,wert in teile))
    z["gesundheit_roh"] = z["gesundheit"] = min(100.,.65*arith+.35*geo)
    z["gesundheit_status"] = "freigegeben" if z.get("_referenz_geprueft") else "vorlaeufige_referenz"
    z["_score_modus"] = "farbe_und_struktur" if struktur_erlaubt else "nur_farbe"
    if chromatisch:
        z["_score_modus"] = "farbverhaeltnis_teilflaeche"
        z["gesundheit_status"] += ";farbverhaeltnis_teilflaeche"
    elif not struktur_erlaubt:
        z["gesundheit_status"] += ";nur_farbvergleich"
    if cur.get("_blattverteilung"):
        z["_score_modus"] = "blattverteilung_chromatik" if chromatisch else "blattverteilung_normiert"
        z["gesundheit_status"] += ";blattfarbverteilung"
    warnungen = []
    if lokal >= 7 or hist_abstand > .25 or hue_delta > 10:
        warnungen.append("farbveraenderung")
    if gelb_delta >= 5:
        warnungen.append("gelbanteil_gestiegen")
    if not chromatisch and braun_delta >= 2.5:
        warnungen.append("braunanteil_gestiegen")
    if saett_delta > .22:
        warnungen.append("saettigung_veraendert")
    if struktur_erlaubt and flaechenverlust > .15:
        warnungen.append("sichtbare_blattflaeche_gesunken")
    z["gesundheitswarnung"] = ";".join(warnungen)


def gesundheitsverlauf(zeilen, alte_historie):
    """Gesundheitsscores je Ansicht glätten und 24-Stunden-Vergleiche ergänzen."""
    auswahl_start = min((z["_zeit"] for z in zeilen if z["_zeit"]),default=None)
    verlauf = {}
    if auswahl_start:
        for ansicht,punkte in alte_historie.items():
            vorher = [(datetime.fromisoformat(p["captured_at"].replace("Z","+00:00")),
                        p["gesundheit"],p["modus"]) for p in punkte]
            verlauf[ansicht] = sorted(p for p in vorher if p[0]<auswahl_start)
    for z in zeilen:
        t = z["_zeit"]
        gruppe = z.get("_ansicht_id")
        roh = z.get("gesundheit_roh")
        if roh is None:
            continue
        scores = verlauf.setdefault(gruppe,[])
        modus = z.get("_score_modus")
        if t and scores and scores[-1][0]<t and scores[-1][2]==modus:
            stunden = (t-scores[-1][0]).total_seconds()/3600
            alpha = min(1.,max(.25,1-math.exp(-stunden/2.)))
            z["gesundheit"] = alpha*roh+(1-alpha)*scores[-1][1]
        score = z["gesundheit"]
        z["gesundheit_kategorie"] = next(n for grenze,n in
            [(85,"sehr gut"),(70,"gut"),(50,"beobachten"),(30,"auffaellig"),(0,"kritisch")] if score>=grenze)
        if t:
            vor24 = [p for p in scores if p[2]==modus and 22<=(t-p[0]).total_seconds()/3600<=26]
            if vor24:
                vergleich = min(vor24,key=lambda p:abs((t-p[0]).total_seconds()/3600-24*3600))
                z["gesundheit_trend_24h"] = score-vergleich[1]
            if not scores or t>scores[-1][0]:
                scores.append((t,score,modus))


GESUND_STATUS = {
    "freigegeben": "Vergleich mit geprüfter Referenz",
    "vorlaeufige_referenz": "Vergleich mit vorläufiger Referenz",
    "referenzfoto_start_der_ansicht": "Referenzaufnahme",
    "bildqualitaet_nicht_ausreichend": "Bildqualität reicht nicht für einen Vergleich",
    "datei_nicht_lesbar": "Aufnahme konnte nicht gelesen werden",
    "analysefehler": "Aufnahme konnte nicht ausgewertet werden",
    "aufnahme_vor_referenz": "Aufnahme liegt vor der Referenz",
    "einzelbilder_keine_gemeinsame_referenz": "Einzelbild ohne gemeinsame Referenz",
    "nicht_auswertbar": "Kein auswertbarer Vergleich",
}


GESUND_TEXTE = {
    **GESUND_STATUS,
    "farbe_und_struktur": "Farbe und Struktur",
    "nur_farbe": "Nur Farbe",
    "nur_farbvergleich": "Nur Farbe",
    "farbverhaeltnis_teilflaeche": "Farbvergleich auf bestätigter Teilfläche",
    "blattverteilung_chromatik": "Blattfarbverteilung ohne Helligkeit",
    "blattverteilung_normiert": "Blattfarbverteilung mit Lichtabgleich",
    "blattfarbverteilung": "Blattfarbverteilung",
    "kein_gueltiger_score_vor_24_stunden_plusminus_2h": "Kein vergleichbarer Score vor 22–26 Stunden",
    "brauntoene_ohne_bestaetigte_helligkeit_nicht_bewertet": "Ohne geprüfte Helligkeit nicht bewertbar",
    "historischer_wert_nicht_gespeichert": "Bei dieser Aufnahme nicht gespeichert",
    "keine_verlaessliche_aufnahmezeit": "Aufnahmezeit nicht bekannt",
    "zu_wenig_bestaetigte_farbteilflaeche": "Zu wenig Blattfläche mit geprüftem Licht",
    "lichtvergleich_zu_wenig_blattgewebe": "Zu wenig vergleichbares Blattgewebe",
    "zu_wenig_gemeinsames_blattgewebe": "Zu wenig übereinstimmende Blattfläche",
    "lichtvergleich_nicht_verifiziert": "Lichtvergleich nicht bestätigt",
    "lichtvergleich_nicht_moeglich": "Lichtvergleich nicht möglich",
    "lichtkorrektur_nicht_stabil": "Lichtkorrektur zu unsicher",
    "blattflaeche_ueberbelichtet": "Blattfläche überbelichtet",
    "maske_deckt_fast_den_gesamten_bereich_ab": "Blattmaske deckt fast das ganze Bild ab",
    "keine_blattmaske": "Zu wenig Blattfläche gefunden",
    "unscharf": "Bild unscharf",
    "blatt_am_bildrand": "Blätter am Bildrand",
    "starkes_rauschen": "Starkes Bildrauschen",
    "keine_aufnahmezeit": "Aufnahmezeit nicht bekannt",
    "neue_kameraansicht": "Neue Kameraansicht",
    "gesundheit_ueber_blattfarbverteilung": "Vergleich über die Blattfarbverteilung",
    "kein_gueltiger_messwert": "Für diese Aufnahme nicht messbar",
    "bild_nicht_auswertbar": "Aufnahme nicht auswertbar",
    "nicht_kalibriert": "Kein Maßstab auf Blatthöhe",
    "kein_verifizierter_massstab_in_blattebene": "Kein Maßstab auf Blatthöhe",
    "kein_gemeinsamer_massstab_fuer_beide_aufnahmen": "Kein gemeinsamer Maßstab der Vergleichsfotos",
    "kein_frueheres_brauchbares_bild_gleicher_aufloesung_mit_mindestabstand": "Kein passendes früheres Bild",
    "flaechensprung_pruefen": "Plötzliche Flächenänderung prüfen",
    "farbveraenderung": "Blattfarbe verändert",
    "gelbanteil_gestiegen": "Gelbanteil gegenüber der Referenz gestiegen",
    "braunanteil_gestiegen": "Braunanteil gegenüber der Referenz gestiegen",
    "saettigung_veraendert": "Farbsättigung verändert",
    "sichtbare_blattflaeche_gesunken": "Sichtbare Blattfläche gesunken",
    "auffaellig": "Auffällig",
    "keine_daten": "Keine Bewertung",
}


def gesund_text(code):
    return GESUND_TEXTE.get(code,code.split(":",1)[0].replace("_"," ").capitalize())


def gesund_foto(z, bildpfade):
    """Vorschau des exakt gleichen Originals, lokal und ohne zusätzliche Datei."""
    name, sha = z.get("bild"), z.get("_sha256")
    if not name or not sha:
        return None
    for pfad in bildpfade:
        pfad = Path(pfad)
        if pfad.name != name:
            continue
        try:
            raw = pfad.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=sha:
                continue
            bild = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            if bild is None or min(bild.shape[:2])<3:
                continue
            h,w = bild.shape[:2]
            f = min(1.,1050/max(h,w))
            if f<1:
                bild = cv2.resize(bild,(max(1,round(w*f)),max(1,round(h*f))),interpolation=cv2.INTER_AREA)
            ok,jpg = cv2.imencode(".jpg",bild,[cv2.IMWRITE_JPEG_QUALITY,86])
            if ok:
                return "data:image/jpeg;base64,"+base64.b64encode(jpg).decode("ascii")
        except (OSError,cv2.error):
            continue
    return None


def gesundheit_daten(zeilen,bildpfade=()):
    """Nur die letzte Aufnahme anzeigen; die Ergebnishistorie bleibt separat."""
    daten = {"version":"1.2.0"}
    if not zeilen:
        return daten
    # Eine Importzeit oder das Änderungsdatum wird nicht als Aufnahmezeit ausgegeben.
    _,z = max(enumerate(zeilen),key=lambda paar:(
        historienzeit(paar[1].get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc),
        not paar[1].get("_historisch",False),paar[0]))
    ergebnis = ergebnis_export(z,None)
    info,fehlend = ergebnis["analysis"],ergebnis["analysis"]["missing_values"]
    bewertung = ergebnis["health_assessment"]
    werte = ("yellow_fraction_pct","brown_fraction_pct","mean_hue","mean_saturation","greenness_index","color_hex")
    teile = ("score_green","score_yellow","score_brown","score_saturation","score_hue")
    scores = ("health_score",*teile)
    messwerte = ergebnis["image_measurements"]
    status = bewertung.get("health_status") or "nicht_auswertbar"
    kurzstatus = status.split(";",1)[0]
    hinweise = {k:gesund_text(v.split(";",1)[0]) for k,v in fehlend.items() if k in scores}
    if info.get("is_reference"):
        hinweise["health_score"] = "Diese Aufnahme ist der Ausgangspunkt. Ein Score braucht ein späteres vergleichbares Foto."
    daten["latest"] = {"file_name":z["bild"],"captured_at":z.get("captured_at"),
        "photo":gesund_foto(z,bildpfade),"health":{k:bewertung[k] for k in scores if k in bewertung},
        "status_label":gesund_text(kurzstatus),
        "category_label":gesund_text(bewertung["health_category"]) if bewertung.get("health_category") and bewertung.get("health_score") is not None else None,
        "measurements":{k:messwerte[k] for k in werte if k in messwerte},"missing":hinweise}
    return ohne_json_nulls(json_sicher(daten))


def gesundheit_speichern(zeilen, ordner, bildpfade=()):
    return json_ausgabe_schreiben(Path(ordner)/GESUND_JSON_DATEI, gesundheit_daten(zeilen, bildpfade))


def gesundheit_aus_ergebnissen(ausgabe,bildordner=None):
    ausgabe = Path(ausgabe).expanduser().resolve()
    with auswertung_sperren(ausgabe):
        gesund_ordner = viewer_ordner(ausgabe)[1]
        cache = gesund_ordner/GESUND_JSON_DATEI
        if bildordner is None and cache.is_file() and all(
                not p.is_file() or cache.stat().st_mtime_ns >= p.stat().st_mtime_ns
                for p in (ausgabe/"ergebnis.json", ausgabe/"ergebnis.csv")):
            try:
                aktuell = json.loads(cache.read_text(encoding="utf-8-sig"))
                if (isinstance(aktuell, dict) and aktuell.get("version") == "1.2.0"
                        and isinstance(aktuell.get("latest"), dict)):
                    return cache
            except (OSError, ValueError):
                pass
        zeilen = ergebnishistorie_laden(ausgabe)
        if not zeilen:
            raise ValueError("Keine gespeicherten Ergebnisse. Zuerst python analyse.py ausführen.")
        ordner = Path(bildordner).expanduser().resolve() if bildordner else ausgabe.parent/"bilder"
        pfade = vorhandene_bilder(ordner) if ordner.is_dir() else [ordner] if ordner.is_file() else []
        return gesundheit_speichern(zeilen, gesund_ordner, pfade)


def gesundheit_anzeigen(ausgabe=None, bildordner=None, ohne_browser=False):
    bilder = Path(bildordner).expanduser().resolve() if bildordner else None
    ziel = ausgabe or ((bilder.parent if bilder.is_dir() else bilder.parent.parent)/"auswertung"
                       if bilder else ergebnis_standardordner())
    try:
        daten = gesundheit_aus_ergebnissen(ziel, bilder)
        if ohne_browser:
            print("Gesundheitsdaten:", daten)
        else:
            browseransicht_oeffnen(ziel, "gesundheitssystem", "Gesundheitsansicht")
    except (OSError, ValueError, TypeError) as fehler:
        print("Gesundheitsansicht nicht erstellt:", fehler)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ausgabe", type=Path, help="Ordner der gespeicherten Ergebnisse")
    parser.add_argument("--lokal", metavar="PFAD", help="Originalfoto oder Ordner für die Fotovorschau")
    parser.add_argument("--ohne-browser", action="store_true", help="Nur die JSON-Daten aktualisieren")
    args = parser.parse_args(argv)
    return gesundheit_anzeigen(args.ausgabe, args.lokal, args.ohne_browser)


if __name__ == "__main__":
    raise SystemExit(main())
