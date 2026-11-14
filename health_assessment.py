"""A-M3 · Plant health assessment: lighting correction and relative condition scores."""

import argparse
import base64
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ENGLISH_LAYOUT_VERSION = 2
from image_capture import parse_saved_time, find_images
from computer_vision_pipeline import (
    select_input_images,
    HEALTH_JSON_FILE, _ellipse_kernel, lock_results, open_browser_view,
    export_record, default_results_dir, load_result_history, leaf_colour_metrics,
    write_json_output, make_json_safe, omit_null_fields, viewer_directories,
)


# Reference and score settings
REFERENCE_APPROVED = False  # Label the reference as reviewed or provisional without blocking the score.
SCORING_VERSION = "4.1.0"

# Colour component weights and scoring response curves.
SCORE_WEIGHTS = {"green": .30, "yellow": .20, "brown": .25, "saturation": .15, "hue": .10}
SCORE_HALF_POINTS = {"hist": .20, "greenness_index": .024, "yellow": 8., "brown": 4.5,
             "saturation": .23, "hue": 8., "area": .19, "image_shape": .52, "local_path": 12.}


def continuous_score(deviation, half_point):
    "Score 100 at zero deviation and 50 at the half point. Apply a tolerance for each feature."
    d = max(0.0, float(deviation))/half_point
    return float(100*math.exp(-math.log(2)*min(d, 30)**2))


def apply_lighting(image, info):
    "Apply the adjustment learned from the fixed background at a different resolution."
    coefficients = info.get("_coefficients")
    if coefficients is None:
        return image.copy()
    h, w = image.shape[:2]
    x = np.linspace(-1,1,w,dtype=np.float32)[None,:]
    y = np.linspace(-1,1,h,dtype=np.float32)[:,None]
    out = np.empty(image.shape,np.float32)
    for k,a in enumerate(coefficients):
        t = image[:,:,k].astype(np.float32)/255
        out[:,:,k] = a[0]+a[1]*t+a[2]*t*t+a[3]*t*x+a[4]*t*y
    return np.rint(np.clip(out,0,1)*255).astype(np.uint8)


def colour_without_brightness(image, gain=None):
    rgb = image.astype(np.float32)
    if gain is not None:
        rgb *= np.asarray(gain,dtype=np.float32)
    rgb *= 160./np.maximum(1.,rgb.max(axis=2,keepdims=True))
    return np.rint(rgb).clip(0,255).astype(np.uint8)


def match_chromaticity(working_image, ref_image, idx, xx, yy, info):
    "Estimate white balance from colour ratios in verified stable parts of the image."
    h,w = working_image.shape[:2]
    cur = working_image.reshape(-1,3)[idx].astype(float)
    previous = ref_image.reshape(-1,3)[idx].astype(float)
    ok = (cur.min(axis=1)>=12)&(previous.min(axis=1)>=12)
    train = ok & (np.arange(len(idx))%4!=0)
    test = ok & ~train
    if np.count_nonzero(train)<300 or np.count_nonzero(test)<120:
        return None
    def log_chroma(bgr):
        return np.log(bgr[:,[0,2]]/bgr[:,[1]])
    delta = log_chroma(previous)-log_chroma(cur)
    gain = np.median(delta[train],axis=0)
    if np.max(np.abs(gain))>.40:
        return None
    error = np.max(np.abs(delta-gain),axis=1)
    sampling_grid = (4*yy//h)*4+4*xx//w
    fields = []
    for i in range(16):
        sample = error[test & (sampling_grid==i)]
        if len(sample)>=45 and np.median(sample)<=.09 and np.percentile(sample,75)<=.145:
            fields.append(i)
    stable = test & np.isin(sampling_grid,fields)
    if (len(fields)<4 or len({i//4 for i in fields})<2 or len({i%4 for i in fields})<2
            or np.count_nonzero(stable)<.30*np.count_nonzero(test)):
        return None
    zone = np.zeros((h,w),np.uint8)
    for i in fields:
        y,x = divmod(i,4)
        zone[y*h//4:(y+1)*h//4,x*w//4:(x+1)*w//4] = 255
    zone = cv2.dilate(zone,_ellipse_kernel(max(3,round(.10*min(h,w)))))
    info.update(model="chromatic_region",corrected=True,_lighting_region=zone,
                chroma_residual=round(float(np.median(error[stable])),4))
    return colour_without_brightness(working_image,[np.exp(gain[0]),1.,np.exp(gain[1])])


def match_lighting(working_image, leaf_mask, ref_image=None, reference_mask=None, allow_chroma=False):
    """Estimate exposure and white balance using the background alone. Validate the linear, gamma and gradual lighting models on held-out pixels. Return no verified correction if validation fails."""
    info = {"model":"reference", "corrected":False, "background_error":None,
            "background_fraction_pct":None}
    if ref_image is None:
        return working_image.copy(), [], info
    if reference_mask is None or working_image.shape != ref_image.shape:
        return None, ["unverified_lighting_comparison"], info
    if np.array_equal(working_image,ref_image):
        info.update(model="identical",background_error=0.)
        return working_image.copy(),[],info
    h,w = leaf_mask.shape
    bg = cv2.dilate(cv2.bitwise_or(leaf_mask,reference_mask),np.ones((31,31),np.uint8)) == 0
    # Train only on linear, unclipped camera values.
    bg &= np.all((working_image > 5)&(working_image < 249)&(ref_image > 5)&(ref_image < 249),axis=2)
    idx = np.flatnonzero(bg)
    info["background_fraction_pct"] = round(100*len(idx)/bg.size,2)
    if len(idx) < max(300,round(.035*bg.size)):
        return None, ["insufficient_background_for_lighting"], info
    idx = idx[np.linspace(0,len(idx)-1,min(len(idx),14000)).astype(int)]
    yy,xx = np.divmod(idx,w)
    x,y = 2*xx/max(w-1,1)-1,2*yy/max(h-1,1)-1
    cur = working_image.reshape(-1,3)[idx].astype(float)/255
    previous = ref_image.reshape(-1,3)[idx].astype(float)/255
    train = np.arange(len(idx)) % 4 != 0
    valid = ~train

    def rescale(model):
        coefficients,error = [],[]
        for k in range(3):
            t = cur[:,k]
            X = np.stack([np.ones_like(t),t,t*t,t*x,t*y],axis=1)
            selection = {"linear":[0,1],"curve":[0,1,2],"gradient":[0,1,2,3,4]}[model]
            # A nearly uniform background supports only a gain adjustment.
            if np.ptp(np.percentile(t,[5,95])) < .07:
                a = np.array([0.,float(np.median(previous[:,k]/np.maximum(t,1e-5))),0.,0.,0.])
            else:
                A,B = X[train][:,selection],previous[train,k]
                weight = np.ones(len(B))
                start = np.array([0.,1.,0.,0.,0.])[selection]
                for _ in range(5):
                    W = np.sqrt(weight)
                    reg = np.eye(len(selection))*.12
                    v = np.linalg.lstsq(np.vstack([A*W[:,None],reg]),
                                       np.r_[B*W,reg@start],rcond=None)[0]
                    e = A@v-B
                    sigma = max(.003,1.4826*float(np.median(np.abs(e-np.median(e)))))
                    weight = np.minimum(1.,2.5*sigma/(np.abs(e)+1e-8))
                a = np.zeros(5);a[selection] = v
            # Require a sensible, monotonic curve across the whole image.
            derived_metrics = [a[1]+2*a[2]*t0+a[3]*x0+a[4]*y0
                           for t0 in (0,1) for x0 in (-1,1) for y0 in (-1,1)]
            if min(derived_metrics) < .08 or max(derived_metrics) > 6 or abs(a[0]) > .25:
                return None,None
            coefficients.append(a.tolist())
            error.append(np.abs(X[valid]@a-previous[valid,k])*255)
        error = np.mean(error,axis=0)
        return coefficients,error

    best,errors = rescale("linear")
    name = "linear"
    for model in ("curve","gradient"):
        a,e = rescale(model)
        if a is not None and (best is None or np.median(e)+.15 < .75*np.median(errors)):
            best,errors,name = a,e,model
    # Brightness, shadows and moving objects can distort the comparison.
    # Use relative colour ratios as a fallback.
    fully_verified = False
    if best is not None:
        info.update(model=name,background_error=round(float(np.median(errors)),3))
        sampling_grid = (4*yy[valid]//h)*4+4*xx[valid]//w
        regional = [float(np.median(errors[sampling_grid==field])) for field in np.unique(sampling_grid)
                    if np.count_nonzero(sampling_grid==field)>=45]
        fully_verified = (np.median(errors)<=5. and np.percentile(errors,90)<=16.
                             and (not regional or max(regional)<=13.))
    if not fully_verified:
        colour = match_chromaticity(working_image,ref_image,idx,xx,yy,info) if allow_chroma else None
        if colour is not None:
            return colour,[],info
        return None,["unstable_lighting_correction"],info
    info["_coefficients"] = best
    normal = apply_lighting(working_image,info)
    info["corrected"] = bool(np.mean(np.abs(normal.astype(float)-working_image)) > .6)
    return normal,[],info


def compare_leaf_distribution(working_image, leaf_mask, corrected, ref_image, reference_mask, info):
    """Compare leaf colour distributions after verifying camera alignment and lighting against the background. New leaves do not need pixel matches."""
    core = cv2.erode(leaf_mask, _ellipse_kernel(3)) > 0
    old_core = cv2.erode(reference_mask, _ellipse_kernel(3)) > 0
    counts = [int(np.count_nonzero(core)), int(np.count_nonzero(old_core))]
    if min(counts) < 100:
        return None, ["too_little_leaf_area_for_distribution"]
    chromatic = info.get("model") == "chromatic_region"
    if chromatic:
        zone = info.get("_lighting_region")
        if zone is None or zone.shape != leaf_mask.shape:
            return None, ["unverified_lighting_comparison"]
        fractions = [np.count_nonzero(core & (zone > 0))/counts[0],
                   np.count_nonzero(old_core & (zone > 0))/counts[1]]
        info["verified_color_region_pct"] = round(100*min(fractions), 2)
        if min(fractions) < .65:
            return None, ["too_little_verified_colour_region"]
        core &= zone > 0
        old_core &= zone > 0
    elif info.get("model") not in ("linear", "curve", "gradient", "identical"):
        return None, ["unverified_lighting_comparison"]
    # Exclude clipped or very dark leaf pixels in each photo.
    # Allow new leaves to appear in regions previously occupied by the background.
    for image, selection in ((working_image, core), (ref_image, old_core)):
        bad = (np.any(image >= 254, axis=2) | (np.max(image, axis=2) < 12))
        bad = cv2.dilate(bad.astype(np.uint8), _ellipse_kernel(3)) > 0
        selection[bad] = False
    retained = [int(np.count_nonzero(core)), int(np.count_nonzero(old_core))]
    fraction = min(retained[0]/counts[0], retained[1]/counts[1])
    info["excluded_leaf_pct"] = round(100*(1-fraction), 2)
    if min(retained) < 100 or fraction < .65:
        return None, ["too_little_leaf_tissue_for_lighting_comparison"]
    current_image = corrected
    prior_image = colour_without_brightness(ref_image) if chromatic else ref_image
    cur = leaf_colour_metrics(current_image, core.astype(np.uint8)*255)
    previous = leaf_colour_metrics(prior_image, old_core.astype(np.uint8)*255)
    def lab_pixel(image, selection):
        pixel = image[selection].reshape(-1, 1, 3).astype(np.float32)/255
        return cv2.cvtColor(pixel, cv2.COLOR_BGR2LAB).reshape(-1, 3)
    current_time, prior = lab_pixel(current_image, core), lab_pixel(prior_image, old_core)
    quantile = np.linspace(.02, .98, 49)
    # Quantiles do not require matching leaf positions or pixel counts.
    delta = np.quantile(current_time[:, 1:], quantile, axis=0)-np.quantile(prior[:, 1:], quantile, axis=0)
    cur["_local_colour_pp"] = 100*float(np.clip((np.linalg.norm(delta, axis=1)-4)/17, 0, 1).mean())
    def warm_colour_metrics(lab):
        l, a, b = lab.T
        yellow = np.clip((a+18)/22, 0, 1)*np.clip((b-9)/23, 0, 1)
        brown = np.clip((a+8)/18, 0, 1)*np.clip((b-3)/14, 0, 1)*np.clip((64-l)/35, 0, 1)
        return (yellow if chromatic else np.maximum(yellow, brown), brown)
    warm, brown = warm_colour_metrics(current_time)
    previous_warm, old_brown = warm_colour_metrics(prior)
    cur["_warm_delta"] = 100*max(0., float(warm.mean()-previous_warm.mean()))
    cur["_brown_delta"] = 100*max(0., float(brown.mean()-old_brown.mean()))
    cur.update(_comparison_baseline=previous, _chromatic=chromatic, _leaf_distribution=True)
    return cur, ["compared_leaf_colour_distribution"]


def health_features(working_image, leaf_mask, ref_image=None, reference_mask=None, alignment=None):
    "Compare shared leaf tissue or, when the plant grows, verified colour distributions."
    corrected, flags, info = alignment if alignment is not None else match_lighting(working_image,leaf_mask,ref_image,reference_mask)
    if corrected is None or ref_image is None or reference_mask is None:
        return None, flags or ["unverified_lighting_comparison"]
    # Inset the mask by one pixel to reduce mixed leaf and background colours.
    core = cv2.erode(leaf_mask, _ellipse_kernel(3))
    reference_core = cv2.erode(reference_mask, _ellipse_kernel(3))
    overlap = (core > 0) & (reference_core > 0)
    n = int(np.count_nonzero(overlap))
    n_cur, n_ref = cv2.countNonZero(core), cv2.countNonZero(reference_core)
    fraction = n/max(1,min(n_cur,n_ref))
    info["common_leaf_pct"] = round(100*fraction,2)
    if n < 50 or fraction < .60 or n < .35*max(n_cur,n_ref):
        cur, verification = compare_leaf_distribution(working_image, leaf_mask, corrected, ref_image, reference_mask, info)
        return cur, flags+verification
    # Discard pixels already clipped or too dark before lighting correction.
    bad = (np.any(working_image >= 254,axis=2) | (np.max(working_image,axis=2) < 12)
                | np.any(ref_image >= 254,axis=2) | (np.max(ref_image,axis=2) < 12))
    bad = cv2.dilate(bad.astype(np.uint8), _ellipse_kernel(3)) > 0
    chromatic = info.get("model")=="chromatic_region"
    if chromatic:
        overlap &= info["_lighting_region"]>0
        part_number = int(np.count_nonzero(overlap))
        info["verified_color_region_pct"] = round(100*part_number/max(1,n),2)
        if part_number<max(50,.30*n):
            return None,flags+["too_little_verified_colour_region"]
        n = part_number
    valid_mask = overlap & ~bad
    comparable = int(np.count_nonzero(valid_mask))
    info["excluded_leaf_pct"] = round(100*(1-comparable/max(1,n)),2)
    if comparable < 50 or comparable < .65*n:
        return None, flags + ["too_little_leaf_tissue_for_lighting_comparison"]
    g = valid_mask.astype(np.uint8)*255
    if chromatic:
        ref_image = colour_without_brightness(ref_image)
    cur = leaf_colour_metrics(corrected,g)
    cur["_chromatic"] = chromatic
    previous = leaf_colour_metrics(ref_image,g)
    # Measure local colour changes continuously at matching image positions.
    # Stable natural variegation cancels out in the comparison.
    def lab_pixel(image):
        pixel = image[valid_mask].reshape(-1,1,3).astype(np.float32)/255
        return cv2.cvtColor(pixel,cv2.COLOR_BGR2LAB).reshape(-1,3)
    current_time, prior = lab_pixel(corrected), lab_pixel(ref_image)
    delta = current_time[:,1:]-prior[:,1:]
    colour_distance = np.linalg.norm(delta,axis=1)
    def warm_colour_metrics(lab):
        l,a,b = lab.T
        yellow = np.clip((a+18)/22,0,1)*np.clip((b-9)/23,0,1)
        brown = np.clip((a+8)/18,0,1)*np.clip((b-3)/14,0,1)*np.clip((64-l)/35,0,1)
        return (yellow,brown) if chromatic else (np.maximum(yellow,brown),brown)
    warm,brown = warm_colour_metrics(current_time)
    previous_warm,old_brown = warm_colour_metrics(prior)
    # A darker patch does not count as increased browning without a red shift.
    signal = np.clip((delta[:,0]-2)/7,0,1)
    cur["_warm_delta"] = 100*float(np.maximum(0.,warm-previous_warm).mean())
    cur["_brown_delta"] = 100*float((np.maximum(0.,brown-old_brown)*signal).mean())
    cur["_local_colour_pp"] = 100*float(np.clip((colour_distance-4)/17,0,1).mean())
    cur["_comparison_baseline"] = previous
    return cur, flags


def assess_health(z, condition_features, ref, allow_structure=True):
    if condition_features is None or not z["usable"]:
        z["health_status"] = "unusable"
        z["health_category"] = "no_data"
        return
    cur, previous = condition_features, condition_features["_comparison_baseline"]
    histogram_distance = float(cv2.compareHist(cur["_hist"],previous["_hist"],cv2.HISTCMP_BHATTACHARYYA))
    green_loss = max(0.,previous["greenness_index"]-cur["greenness_index"]-.002)
    local_path = cur["_local_colour_pp"]
    z["score_green"] = (.42*continuous_score(max(0.,histogram_distance-.018), SCORE_HALF_POINTS["hist"])
                        + .26*continuous_score(green_loss,SCORE_HALF_POINTS["greenness_index"])
                        + .32*continuous_score(local_path,SCORE_HALF_POINTS["local_path"]))
    # Warm colours include yellow and brown.
    # A decrease in yellow does not imply recovery if that area has turned brown.
    yellow_delta = cur["_warm_delta"]
    brown_delta = cur["_brown_delta"]
    z["score_yellow"] = continuous_score(max(0.,yellow_delta-.4),SCORE_HALF_POINTS["yellow"])
    chromatic = cur.get("_chromatic",False)
    z["score_brown"] = None if chromatic else continuous_score(max(0.,brown_delta-.3),SCORE_HALF_POINTS["brown"])
    saturation_delta = abs(math.log((cur["mean_saturation"]+8)/(previous["mean_saturation"]+8)))
    z["score_saturation"] = continuous_score(max(0.,saturation_delta-.025),SCORE_HALF_POINTS["saturation"])
    hue_delta = 0.
    if cur["mean_hue"] is not None and previous["mean_hue"] is not None:
        d = abs(cur["mean_hue"]-previous["mean_hue"])
        hue_delta = min(d,180-d)
    lab_delta = float(np.linalg.norm(cur["_lab"][1:]-previous["_lab"][1:]))
    z["score_hue"] = continuous_score(max(0.,max(hue_delta,lab_delta/2)-.7),SCORE_HALF_POINTS["hue"])
    total_weight = sum(SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS if z["score_"+k] is not None)
    parts = [(SCORE_WEIGHTS[k]/total_weight,z["score_"+k]) for k in SCORE_WEIGHTS if z["score_"+k] is not None]
    allow_structure = allow_structure and not chromatic and not cur.get("_leaf_distribution", False)
    area_loss = max(0., 1-z["plant_pixels"]/max(1,ref["meta"]["plant_pixels"]))
    z["_structure_score"] = None
    if allow_structure:
        # Use shape only as supporting evidence when visible leaf area decreases.
        # A new leaf or growth alone does not lower the score.
        form_delta = 0.
        if z["compactness"] and ref["meta"].get("compactness"):
            form_delta = max(0.,abs(math.log(z["compactness"]/ref["meta"]["compactness"]))-.15)
        area = continuous_score(max(0.,area_loss-.035),SCORE_HALF_POINTS["area"])
        image_shape = continuous_score(form_delta,SCORE_HALF_POINTS["image_shape"])
        structure = area*(1-.2*min(1.,area_loss/.15)*(1-image_shape/100))
        z["_structure_score"] = structure
        parts = [(component_weight*.85,score) for component_weight,score in parts] + [(.15,structure)]
    # Combine arithmetic and geometric means.
    # One strong symptom can lower the score without forcing it to zero.
    arith = sum(value*component_weight for component_weight,value in parts)
    geo = math.exp(sum(component_weight*math.log(max(.01,value)) for component_weight,value in parts))
    z["health_score_raw"] = z["health_score"] = min(100.,.65*arith+.35*geo)
    z["health_status"] = "reviewed_reference" if z.get("_reference_verified") else "provisional_reference"
    z["_score_mode"] = "colour_and_structure" if allow_structure else "colour_only"
    if chromatic:
        z["_score_mode"] = "colour_ratio_verified_regions"
        z["health_status"] += ";colour_ratio_verified_regions"
    elif not allow_structure:
        z["health_status"] += ";colour_comparison_only"
    if cur.get("_leaf_distribution"):
        z["_score_mode"] = "leaf_distribution_chromatic" if chromatic else "leaf_distribution_normalised"
        z["health_status"] += ";leaf_colour_distribution"
    warnings = []
    if local_path >= 7 or histogram_distance > .25 or hue_delta > 10:
        warnings.append("leaf_colour_changed")
    if yellow_delta >= 5:
        warnings.append("yellow_fraction_increased")
    if not chromatic and brown_delta >= 2.5:
        warnings.append("brown_fraction_increased")
    if saturation_delta > .22:
        warnings.append("saturation_changed")
    if allow_structure and area_loss > .15:
        warnings.append("visible_leaf_area_decreased")
    z["health_warnings"] = ";".join(warnings)


def health_history(rows, prior_history):
    "Smooth scores within each view and add comparable 24-hour changes."
    first_selection = min((z["_capture_time"] for z in rows if z["_capture_time"]),default=None)
    timeline = {}
    if first_selection:
        for camera_view,points in prior_history.items():
            prior = [(datetime.fromisoformat(p["captured_at"].replace("Z","+00:00")),
                        p["health_score"],p["mode"]) for p in points]
            timeline[camera_view] = sorted(p for p in prior if p[0]<first_selection)
    for z in rows:
        t = z["_capture_time"]
        group = z.get("_camera_view_id")
        raw_value = z.get("health_score_raw")
        if raw_value is None:
            continue
        scores = timeline.setdefault(group,[])
        mode = z.get("_score_mode")
        if t and scores and scores[-1][0]<t and scores[-1][2]==mode:
            elapsed_hours = (t-scores[-1][0]).total_seconds()/3600
            alpha = min(1.,max(.25,1-math.exp(-elapsed_hours/2.)))
            z["health_score"] = alpha*raw_value+(1-alpha)*scores[-1][1]
        score = z["health_score"]
        z["health_category"] = next(n for limit,n in
            [(85,"very_good"),(70,"good"),(50,"monitor"),(30,"significant_change"),(0,"critical")] if score>=limit)
        if t:
            previous_24h = [p for p in scores if p[2]==mode and 22<=(t-p[0]).total_seconds()/3600<=26]
            if previous_24h:
                comparison = min(previous_24h,key=lambda p:abs((t-p[0]).total_seconds()/3600-24*3600))
                z["health_trend_24h"] = score-comparison[1]
            if not scores or t>scores[-1][0]:
                scores.append((t,score,mode))


HEALTH_STATUS_CODES = {
    "reviewed_reference": "Reviewed reference",
    "provisional_reference": "Provisional reference",
    "reference_photo_start_of_view": "Reference photo",
    "image_quality_too_low": "Image quality is too low for comparison",
    "image_unreadable": "The photo could not be read",
    "analysis_failed": "The photo could not be analysed",
    "photo_before_reference": "The photo was taken before the reference",
    "independent_images_no_reference": "Independent image with no shared reference",
    "unusable": "No usable comparison",
}


HEALTH_LABELS = {
    **HEALTH_STATUS_CODES,
    "very_good": "Very good",
    "good": "Good",
    "monitor": "Monitor",
    "critical": "Critical",
    "colour_and_structure": "Colour and structure",
    "colour_only": "Colour only",
    "colour_comparison_only": "Colour only",
    "colour_ratio_verified_regions": "Colour comparison in verified regions",
    "leaf_distribution_chromatic": "Leaf colour distribution without brightness",
    "leaf_distribution_normalised": "Leaf colour distribution with lighting correction",
    "leaf_colour_distribution": "Leaf colour distribution",
    "no_comparable_score_22_to_26_hours_earlier": "No comparable score from 22 to 26 hours earlier",
    "brown_requires_verified_lighting": "Brown tones require verified lighting",
    "historical_value_not_recorded": "Not recorded for this photo",
    "no_reliable_capture_time": "Capture time unknown",
    "too_little_verified_colour_region": "Too little leaf area with verified lighting",
    "too_little_leaf_tissue_for_lighting_comparison": "Too little comparable leaf tissue",
    "too_little_shared_leaf_tissue": "Too little overlapping leaf area",
    "unverified_lighting_comparison": "Lighting comparison could not be verified",
    "lighting_not_comparable": "Lighting could not be compared",
    "unstable_lighting_correction": "Lighting correction was not reliable",
    "leaf_area_overexposed": "Overexposed leaf area",
    "mask_covers_almost_entire_frame": "The mask covers almost the entire image",
    "no_leaf_mask": "Too little leaf area was detected",
    "blurred": "Blurred image",
    "leaf_at_image_edge": "Leaves touch the image edge",
    "high_image_noise": "High image noise",
    "capture_time_unknown": "Capture time unknown",
    "new_camera_view": "New camera view",
    "compared_leaf_colour_distribution": "Comparison based on leaf colour distribution",
    "no_valid_measurement": "Not measurable for this photo",
    "image_not_measurable": "The photo cannot be analysed",
    "not_calibrated": "No verified scale in the leaf plane",
    "no_verified_scale_in_leaf_plane": "No verified scale in the leaf plane",
    "no_shared_scale_for_pair": "No shared scale for the two photos",
    "no_suitable_earlier_photo": "No suitable earlier photo",
    "check_area_jump": "Check the sudden change in area",
    "leaf_colour_changed": "Leaf colour changed",
    "yellow_fraction_increased": "Yellow fraction increased relative to the reference",
    "brown_fraction_increased": "Brown fraction increased relative to the reference",
    "saturation_changed": "Colour saturation changed",
    "visible_leaf_area_decreased": "Visible leaf area decreased",
    "significant_change": "Significant change",
    "no_data": "No assessment",
}


def health_status_label(code):
    label = code.split(":",1)[0]
    return HEALTH_LABELS.get(label, label.replace("_", " ").capitalize())


def health_preview(z, image_paths):
    "Embed a preview of the exact original photo without creating another image file."
    name, sha = z.get("file_name"), z.get("_sha256")
    if not name or not sha:
        return None
    for file_path in image_paths:
        file_path = Path(file_path)
        if file_path.name != name:
            continue
        try:
            raw = file_path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=sha:
                continue
            image = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            if image is None or min(image.shape[:2])<3:
                continue
            h,w = image.shape[:2]
            f = min(1.,1050/max(h,w))
            if f<1:
                image = cv2.resize(image,(max(1,round(w*f)),max(1,round(h*f))),interpolation=cv2.INTER_AREA)
            ok,jpg = cv2.imencode(".jpg",image,[cv2.IMWRITE_JPEG_QUALITY,86])
            if ok:
                return "data:image/jpeg;base64,"+base64.b64encode(jpg).decode("ascii")
        except (OSError,cv2.error):
            continue
    return None


def health_data(rows,image_paths=()):
    "Show the latest capture. Store the measurement history separately."
    data = {"version":"1.2.0", "language":"en"}
    if not rows:
        return data
    # Do not substitute the import date or file modification time for capture time.
    _,z = max(enumerate(rows),key=lambda pair:(
        parse_saved_time(pair[1].get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc),
        not pair[1].get("_historical",False),pair[0]))
    result = export_record(z,None)
    info,missing = result["analysis"],result["analysis"]["missing_values"]
    assessment = result["health_assessment"]
    values = ("yellow_fraction_pct","brown_fraction_pct","mean_hue","mean_saturation","greenness_index","color_hex")
    parts = ("score_green","score_yellow","score_brown","score_saturation","score_hue")
    scores = ("health_score",*parts)
    measured_values = result["image_measurements"]
    status = assessment.get("health_status") or "unusable"
    short_status = status.split(";",1)[0]
    notices = {k:health_status_label(v.split(";",1)[0]) for k,v in missing.items() if k in scores}
    if info.get("is_reference"):
        notices["health_score"] = "This is the reference photo. A score requires a comparable photo taken later."
    data["latest"] = {"file_name":z["file_name"],"captured_at":z.get("captured_at"),
        "photo":health_preview(z,image_paths),"health":{k:assessment[k] for k in scores if k in assessment},
        "status_label":health_status_label(short_status),
        "category_label":health_status_label(assessment["health_category"]) if assessment.get("health_category") and assessment.get("health_score") is not None else None,
        "measurements":{k:measured_values[k] for k in values if k in measured_values},"missing":notices}
    return omit_null_fields(make_json_safe(data))


def save_health(rows, directory_path, image_paths=()):
    return write_json_output(Path(directory_path)/HEALTH_JSON_FILE, health_data(rows, image_paths))


def health_from_results(output_dir,image_directory=None):
    output_dir = Path(output_dir).expanduser().resolve()
    with lock_results(output_dir):
        health_folder = viewer_directories(output_dir)[1]
        cache = health_folder/HEALTH_JSON_FILE
        cached_photo = None
        if image_directory is None and cache.is_file():
            try:
                current = json.loads(cache.read_text(encoding="utf-8-sig"))
                if (isinstance(current, dict) and current.get("version") == "1.2.0"
                        and isinstance(current.get("latest"), dict)):
                    cached_photo = current["latest"]
                    results_are_newer = any(p.is_file() and cache.stat().st_mtime_ns < p.stat().st_mtime_ns
                                          for p in (output_dir/"results.json", output_dir/"results.csv"))
                    if not results_are_newer and current.get("language") == "en":
                        return cache
                    if not (output_dir/"results.json").is_file() and not (output_dir/"results.csv").is_file():
                        return cache
            except (OSError, ValueError):
                pass
        rows = load_result_history(output_dir)
        if not rows:
            raise ValueError("No saved results. Run python computer_vision_pipeline.py images first.")
        directory_path = Path(image_directory).expanduser().resolve() if image_directory else output_dir.parent/"images"
        paths = select_input_images(directory_path)[1] if image_directory is None else (
            find_images(directory_path) if directory_path.is_dir() else [directory_path] if directory_path.is_file() else [])
        data = health_data(rows, paths)
        latest = data.get("latest")
        if cached_photo and latest and not latest.get("photo") and all(
                latest.get(key) == cached_photo.get(key) for key in ("file_name", "captured_at")):
            if isinstance(cached_photo.get("photo"), str):
                latest["photo"] = cached_photo["photo"]
        return write_json_output(cache, data)


def open_health(output_dir=None, image_directory=None, no_browser=False):
    image_source = Path(image_directory).expanduser().resolve() if image_directory else None
    target = output_dir or ((image_source.parent if image_source.is_dir() else image_source.parent.parent)/"results"
                       if image_source else default_results_dir())
    try:
        data = health_from_results(target, image_source)
        if no_browser:
            print("Plant health data:", data)
        else:
            open_browser_view(target, "plant_health", "Plant health")
    except (OSError, ValueError, TypeError) as error:
        print("Could not open plant health:", error)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", dest="output_dir", type=Path, help="Saved results directory")
    parser.add_argument("--local", dest="local_path", metavar="PATH", help="Source photo or directory for the preview")
    parser.add_argument("--no-browser", dest="no_browser", action="store_true",
                        help="Update the JSON data without opening a browser")
    args = parser.parse_args(argv)
    return open_health(args.output_dir, args.local_path, args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
