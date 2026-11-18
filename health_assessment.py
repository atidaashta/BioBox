"""A-M3 · Plant health assessment: lighting correction and relative condition scores."""

import argparse
import base64
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

ENGLISH_LAYOUT_VERSION = 2
from image_capture import parse_saved_time, find_images
from computer_vision_pipeline import (
    select_input_images,
    HEALTH_JSON_FILE, _ellipse_kernel, lock_results, open_browser_view,
    export_record, default_results_dir, load_result_history,
    write_json_output, make_json_safe, omit_null_fields, viewer_directories,
)


# Reference and score settings
REFERENCE_APPROVED = False  # Label the reference as reviewed or provisional without blocking the score.
SCORING_VERSION = "5.0.0"

# Colour component weights and scoring response curves.
SCORE_WEIGHTS = {"green": .30, "yellow": .26, "brown": .26, "saturation": .08, "hue": .10}
_SRGB = np.arange(256, dtype=np.float32)/255
_LINEAR = np.where(_SRGB<=.04045, _SRGB/12.92, ((_SRGB+.055)/1.055)**2.4)
_LOG_LIGHT = np.log(np.maximum(_LINEAR, 1e-5))
_COLOUR_QUANTILES = [.20,.50,.75,.85,.92,.97]


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


def log_leaf_colour(bgr):
    "Two brightness-independent colour coordinates: log(red/green), log(blue/green)."
    linear = _LOG_LIGHT[bgr]
    return linear[..., [2,0]]-linear[..., 1,None]


def _coords(x, y, width, height):
    return np.column_stack((np.ones(len(x)), 2*x/max(1,width-1)-1, 2*y/max(1,height-1)-1))


def match_chromaticity(working_image, ref_image, idx, xx, yy, info):
    "Verify a colour-cast correction on separate background samples, never on the plant."
    h,w = working_image.shape[:2]
    cur = working_image.reshape(-1,3)[idx]
    previous = ref_image.reshape(-1,3)[idx]
    ok = (cur.min(axis=1)>=11)&(previous.min(axis=1)>=11)
    train = ok & (np.arange(len(idx))%4!=0)
    test = ok & ~train
    if np.count_nonzero(train)<300 or np.count_nonzero(test)<120:
        return None
    delta = log_leaf_colour(previous)-log_leaf_colour(cur)
    design = _coords(xx,yy,w,h)
    coeffs = np.zeros((3,2), np.float64)
    coeffs[0] = np.median(delta[train],axis=0)
    if np.max(np.abs(coeffs[0])) > .92:
        return None  # A very large cast cannot be distinguished from a scene change.
    error = np.max(np.abs(delta-design@coeffs),axis=1)
    # Only use a spatial correction if independently sampled background pixels
    # support it. Regularisation keeps corners with little data from drifting.
    train_design, train_delta = design[train], delta[train]
    fit = coeffs.copy()
    reg = np.diag([.01,1.0,1.0])
    for _ in range(4):
        residual = np.max(np.abs(train_delta-train_design@fit),axis=1)
        weight = np.sqrt(np.minimum(1.,max(.045, 2.5*float(np.median(residual)))/(residual+1e-7)))
        fit = np.linalg.lstsq(np.vstack((train_design*weight[:,None],reg)),
                              np.vstack((train_delta*weight[:,None],reg@coeffs)),rcond=None)[0]
    fitted_error = np.max(np.abs(delta-design@fit),axis=1)
    spatial = (np.max(np.abs(fit[1:])) < .45 and np.max(np.abs(fit[0])+np.abs(fit[1:]).sum(axis=0)) < 1.05
               and np.median(fitted_error[test])+.012 < .80*np.median(error[test])
               and np.percentile(fitted_error[test],80) <= np.percentile(error[test],80))
    if spatial:
        coeffs,error = fit,fitted_error
    sampling_grid = (4*yy//h)*4+4*xx//w
    good, bad = [], []
    for i in range(16):
        sample = error[test & (sampling_grid==i)]
        if len(sample)<24:
            continue
        (good if np.median(sample)<=.10 and np.percentile(sample,75)<=.20 else bad).append(i)
    stable = test & np.isin(sampling_grid,good)
    if (len(good)<4 or len({i//4 for i in good})<2 or len({i%4 for i in good})<2
            or np.count_nonzero(stable)<.32*np.count_nonzero(test)):
        return None
    whole_view = (len(good)>=7 and len({i//4 for i in good})>=3 and len({i%4 for i in good})>=3
                  and np.median(error[test])<=.068 and np.percentile(error[test],90)<=.22)
    zone = np.full((h,w),255 if whole_view else 0,np.uint8)
    for i in (bad if whole_view else good):
        y,x = divmod(i,4)
        # The proportions match the boundaries used to label each sample.
        ys = slice((y*h+3)//4,((y+1)*h+3)//4)
        xs = slice((x*w+3)//4,((x+1)*w+3)//4)
        zone[ys,xs] = 0 if whole_view else 255
    exposure = float(np.median((_LOG_LIGHT[cur[:,1]]-_LOG_LIGHT[previous[:,1]])[stable]))
    info.update(model=("chromaticity_spatial" if spatial else "chromaticity_global") if whole_view else "chromatic_region",
                corrected=bool(np.max(np.abs(coeffs))>.015),_lighting_region=zone,_colour_offset=coeffs,
                chroma_residual=round(float(np.median(error[stable])),4),
                exposure_ratio=round(math.exp(exposure),3))
    return working_image  # The measured features use the corrected log ratios, not rendered RGB.


def match_lighting(working_image, leaf_mask, ref_image=None, reference_mask=None, allow_chroma=False):
    "Estimate a background correction for colour scoring or for the sharpness check."
    info = {"model":"reference", "corrected":False, "background_error":None,
            "background_fraction_pct":None}
    if ref_image is None:
        return working_image.copy(), [], info
    if reference_mask is None or working_image.shape != ref_image.shape:
        return None, ["unverified_lighting_comparison"], info
    if np.array_equal(working_image,ref_image):
        info.update(model="identical",background_error=0.,chroma_residual=0.,exposure_ratio=1.)
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
    if allow_chroma:
        colour = match_chromaticity(working_image,ref_image,idx,xx,yy,info)
        return (colour,[],info) if colour is not None else (None,["unstable_lighting_correction"],info)
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
        return None,["unstable_lighting_correction"],info
    info["_coefficients"] = best
    normal = apply_lighting(working_image,info)
    info["corrected"] = bool(np.mean(np.abs(normal.astype(float)-working_image)) > .6)
    return normal,[],info


def _valid_leaf_pixels(image, core, zone):
    # Clipped highlights and near-black channels do not contain reliable colour.
    measured = (image.min(axis=2) >= 7) & (image.max(axis=2) >= 23) & (image.max(axis=2) < 250)
    return core & measured & zone


def _profile(image, selected, offset=None):
    y,x = np.nonzero(selected)
    if len(y)>30000:
        take = np.linspace(0,len(y)-1,30000,dtype=int)
        y,x = y[take],x[take]
    colour = log_leaf_colour(image[y,x])
    if offset is not None:
        colour = colour + _coords(x,y,image.shape[1],image.shape[0])@offset
    return colour


def _ramp(values, start, end):
    t = np.clip((values-start)/(end-start),0.,1.)
    return t*t*(3.-2.*t)


def _warm_colour(colour):
    red,blue = colour.T
    # Yellow and red-brown evidence are colour shifts, not absolute darkness.
    # This is intentionally unable to label a neutral shadow as browning.
    warm = _ramp(-blue,.40,1.35)
    red_brown = _ramp(red,.35,1.10)
    return _ramp(red,-.92,-.11)*warm*(1.-red_brown),red_brown*warm


def _colour_profile(colour):
    red,blue = colour.T
    yellow,red_brown = _warm_colour(colour)
    log_saturation = np.maximum(0.,np.maximum(red,blue))-np.minimum(0.,np.minimum(red,blue))
    centre = np.median(colour,axis=0)
    r,b = np.exp(np.clip(centre,-7.,7.))
    hue = math.degrees(math.atan2(math.sqrt(3)*(1.-b),2.*r-1.-b))
    return {"colour_points":np.quantile(colour,_COLOUR_QUANTILES,axis=0),
            "yellow":100.*float(np.mean(yellow)), "brown":100.*float(np.mean(red_brown)),
            "saturation":float(np.median(log_saturation)), "hue":hue,
            "hue_strength":float(np.ptp([r,1.,b])/max(r,1.,b))}


def _local_colour_changes(working_image, ref_image, shared, offset, n_leaf, error):
    "Measure coherent warm patches without treating isolated pixels as a symptom."
    if np.count_nonzero(shared) < max(150,.50*n_leaf):
        return 0.,0.
    y,x = np.nonzero(shared)
    now = log_leaf_colour(working_image[y,x])
    if offset is not None:
        now = now+_coords(x,y,working_image.shape[1],working_image.shape[0])@offset
    old = log_leaf_colour(ref_image[y,x])
    red_shift = now[:,0]-old[:,0] > .20+1.6*error
    before,after = _warm_colour(old),_warm_colour(now)
    changed_fractions = []
    for start,end in zip(before,after):
        candidates = np.zeros(shared.shape,np.uint8)
        candidates[y,x] = np.uint8(red_shift & (end-start>.26))*255
        opened = cv2.morphologyEx(candidates,cv2.MORPH_OPEN,_ellipse_kernel(3))
        _,_,counts,_ = cv2.connectedComponentsWithStats(opened,connectivity=8)
        sizes = counts[1:,cv2.CC_STAT_AREA]
        changed_fractions.append(100.*float(sizes[sizes>=max(16,.0012*n_leaf)].sum())/n_leaf)
    return tuple(changed_fractions)


def _enclosed_leaf_patches(leaf_mask, reference_core, n_leaf):
    "Look for small holes still surrounded by leaves and covered by the old blade."
    # A green area mask can leave out a patch that has actually browned. Use
    # such pixels only as local corroboration, without editing the saved mask.
    solid = cv2.morphologyEx(leaf_mask,cv2.MORPH_CLOSE,_ellipse_kernel(5))
    n,labels,stats,_ = cv2.connectedComponentsWithStats(255-solid,connectivity=8)
    size = stats[:,cv2.CC_STAT_AREA]
    covered = np.bincount(labels[reference_core],minlength=n)
    keep = ((size>=max(16,.0005*n_leaf)) & (size<=.025*n_leaf) & (covered>=.85*size))
    keep[0] = False
    keep[np.unique(np.r_[labels[0],labels[-1],labels[:,0],labels[:,-1]])] = False
    return keep[labels] & reference_core


def health_features(working_image, leaf_mask, ref_image=None, reference_mask=None, alignment=None):
    "Compare brightness-normalised leaf profiles, using only a verified field of view."
    if ref_image is None or reference_mask is None:
        return None, ["unverified_lighting_comparison"]
    matched, flags, info = (alignment if alignment is not None else
                           match_lighting(working_image,leaf_mask,ref_image,reference_mask,allow_chroma=True))
    if matched is None:
        return None, flags or ["unverified_lighting_comparison"]
    now_core = cv2.erode(leaf_mask,_ellipse_kernel(3)) > 0
    ref_core = cv2.erode(reference_mask,_ellipse_kernel(3)) > 0
    n_now,n_ref = np.count_nonzero(now_core),np.count_nonzero(ref_core)
    common = now_core & ref_core
    info["common_leaf_pct"] = round(100*np.count_nonzero(common)/max(1,min(n_now,n_ref)),2)
    if min(n_now,n_ref)<100:
        return None, ["too_little_leaf_tissue_for_lighting_comparison"]
    zone = info.get("_lighting_region")
    if zone is None:
        if info.get("model")!="identical":
            return None, ["unverified_lighting_comparison"]
        zone = np.ones(leaf_mask.shape,bool)
    else:
        zone = zone > 0
    now = _valid_leaf_pixels(working_image,now_core,zone)
    before = _valid_leaf_pixels(ref_image,ref_core,zone)
    reliable = min(np.count_nonzero(now)/n_now,np.count_nonzero(before)/n_ref)
    info["verified_color_region_pct"] = round(100*reliable,2)
    coefficients = info.get("_colour_offset")
    exposure = info.get("exposure_ratio")
    area_shift = max(n_now,n_ref)>1.22*min(n_now,n_ref)
    lighting_shift = ((exposure is not None and not .60<=exposure<=1.65)
                      or (coefficients is not None and np.max(np.abs(coefficients))>.19))
    partial = info.get("model")=="chromatic_region" or reliable<.70 or (lighting_shift and area_shift)
    if partial:
        # If only part of the room has verified lighting, compare the same
        # photographed leaf patch on both dates rather than two different crops.
        paired = now & before
        if np.count_nonzero(paired)<max(120,.24*min(n_now,n_ref)):
            return None, ["too_little_verified_colour_region"]
        before = now = paired
    elif min(np.count_nonzero(now),np.count_nonzero(before)) < 120:
        return None, ["too_little_leaf_tissue_for_lighting_comparison"]
    if reliable<.35 and info.get("model")!="chromatic_region":
        return None, ["too_little_leaf_tissue_for_lighting_comparison"]
    info["excluded_leaf_pct"] = round(100*(1.-reliable),2)
    cur = _colour_profile(_profile(working_image,now,coefficients))
    previous = _colour_profile(_profile(ref_image,before))
    error = float(info.get("chroma_residual",0.))
    local = (0.,0.)
    # Only use the position of a spot when the two masks still substantially
    # cover the same plant. An expanding canopy is compared by distribution.
    if np.count_nonzero(common)>=.72*max(n_now,n_ref) and reliable>=.65:
        integral_leaf = min(n_now,n_ref)
        shared = now & before
        if not partial and np.count_nonzero(common)>=.85*max(n_now,n_ref):
            patches = _enclosed_leaf_patches(leaf_mask,ref_core,integral_leaf)
            trusted = _valid_leaf_pixels(working_image,patches,zone)
            shared |= trusted & before
        local = _local_colour_changes(working_image,ref_image,shared,coefficients,integral_leaf,error)
    return {"current":cur,"previous":previous,"partial":partial,
            "calibration_error":error, "local_warm":local,
            "exposure_ratio":exposure,"coverage":reliable}, []


def assess_health(z, condition_features, ref, allow_structure=True):
    "Record the current comparison; health_history confirms changes across dates."
    if condition_features is None or not z["usable"]:
        z["health_status"] = "unusable"
        z["health_category"] = "no_data"
        return
    cur,previous = condition_features["current"],condition_features["previous"]
    partial = condition_features["partial"]
    error = min(.12,condition_features["calibration_error"])
    delta = cur["colour_points"]-previous["colour_points"]
    red_change = np.maximum(0.,delta[:,0])
    green_loss = .58*red_change[1]+.42*float(red_change[2:].mean())
    local_yellow,local_brown = condition_features["local_warm"]
    yellow_delta = max(2.4*local_yellow,cur["yellow"]-previous["yellow"])
    brown_delta = max(2.4*local_brown,cur["brown"]-previous["brown"])
    saturation_delta = abs(cur["saturation"]-previous["saturation"])
    hue_delta = abs((cur["hue"]-previous["hue"]+180)%360-180)
    hue_delta *= min(1.,min(cur["hue_strength"],previous["hue_strength"])/.34)
    # Let verified background residuals absorb small residual casts or JPEG noise.
    # Do not penalise higher green dominance or higher brightness by themselves.
    z["score_green"] = continuous_score(green_loss-(.042+.85*error),.35)
    z["score_yellow"] = continuous_score(yellow_delta-(.9+12*error),10.)
    z["score_brown"] = continuous_score(brown_delta-(.7+9*error),8.)
    z["score_saturation"] = continuous_score(saturation_delta-(.055+1.2*error),.55)
    z["score_hue"] = continuous_score(hue_delta-(1.8+25*error),29.)
    parts = [(weight,z["score_"+name]) for name,weight in SCORE_WEIGHTS.items()]
    arith = sum(weight*score for weight,score in parts)
    geo = math.exp(sum(weight*math.log(max(.01,score)) for weight,score in parts))
    z["health_score_raw"] = z["health_score"] = min(100.,.73*arith+.27*geo)
    z["health_status"] = "reviewed_reference" if z.get("_reference_verified") else "provisional_reference"
    z["_score_mode"] = "chromatic_profile_partial" if partial else "chromatic_profile"
    if partial:
        z["health_status"] += ";colour_ratio_verified_regions"
    warnings = []
    if green_loss > .30+error or hue_delta > 18+30*error:
        warnings.append("leaf_colour_changed")
    if yellow_delta > max(5+12*error,.28*brown_delta):
        warnings.append("yellow_fraction_increased")
    if brown_delta > 3.5+9*error:
        warnings.append("brown_fraction_increased")
    if saturation_delta > .34+error:
        warnings.append("saturation_changed")
    z["_photo_warnings"] = tuple(warnings)
    z["health_warnings"] = ""
    exposure = condition_features["exposure_ratio"]
    # The size of a mask can still shrink in heavy shadow. Area is only
    # supporting evidence, and only when exposure and camera pose are suitable.
    z["_health_area_reliable"] = bool(allow_structure and not partial and exposure is not None
                                      and .63<=exposure<=1.54 and condition_features["coverage"]>=.72)
    z["_health_exposure"] = exposure


def _area_observation(row):
    if not row.get("usable") or row.get("_clipped") or not row.get("plant_pixels"):
        return None
    if row.get("_is_reference"):
        return float(row["plant_pixels"]),1.
    if not row.get("_health_area_reliable") or row.get("_pose") is None:
        return None
    scale = abs(float(np.linalg.det(np.asarray(row["_pose"])[:,:2])))
    return ((float(row["plant_pixels"])/scale,float(row["_health_exposure"]))
            if .96<=scale<=1.04 else None)


def _persistent_area_score(now, area, previous):
    "Require repeat area loss against a confirmed recent level, at similar exposures."
    if area is None or len(previous)<3:
        return None
    value,exposure = area
    comparable = [p for p in previous if .78 <= p[2]/exposure <= 1.28]
    mature = [i for i,p in enumerate(comparable) if (now-p[0]).total_seconds()>=2*3600]
    if not mature or mature[-1]<2:
        return None
    i = mature[-1]
    most_recent = max(value,*(p[1] for p in comparable[i:]))
    anchor = float(np.median(sorted(p[1] for p in comparable[:i])[-3:]))
    if not anchor or most_recent>.88*anchor:
        return None
    loss = 1.-most_recent/anchor
    return continuous_score(loss-.09,.23)


def _set_category(row):
    score = row["health_score"]
    row["health_category"] = next(name for cutoff,name in
        [(85,"very_good"),(70,"good"),(50,"monitor"),(30,"significant_change"),(0,"critical")] if score>=cutoff)


def health_history(rows, prior_history):
    "Follow repeated changes over time without treating an isolated photo as a trend."
    groups = {}
    areas = {}
    # The caller passes one run's photos in capture order. Legacy scores used a
    # different scale; do not blend them into the brightness-independent series.
    for z in rows:
        t = z.get("_capture_time")
        group = (z.get("_camera_view_id"),z.get("scoring_version",SCORING_VERSION))
        raw = z.get("health_score_raw")
        sha = z.get("_sha256")
        if not t or not group[0]:
            if raw is not None:
                z["health_score"] = raw
                _set_category(z)
            continue
        line = groups.setdefault(group,[])
        size_line = areas.setdefault(group,[])
        earliest = t-timedelta(days=7)
        eligible = [p for p in line if earliest<=p["time"]<t and (not sha or p["sha"]!=sha)]
        recent = eligible[-5:]
        recent_areas = [p[:3] for p in size_line if earliest<=p[0]<t and (not sha or p[3]!=sha)]
        area = _area_observation(z)
        if area is not None and (not size_line or t>size_line[-1][0]) and not any(sha and p[3]==sha for p in size_line):
            size_line.append((t,*area,sha))
        if raw is None:
            continue
        warning_candidates = set(z.get("_photo_warnings",()))
        confirmed = set()
        for symptom in warning_candidates:
            for point in reversed(recent):
                if symptom not in point["symptoms"]:
                    break
                if (t-point["time"]).total_seconds()>=2*3600:
                    confirmed.add(symptom)
                    break
        structure = _persistent_area_score(t,area,recent_areas)
        z["_structure_score"] = structure
        target = raw
        if structure is not None:
            target = min(raw,.80*raw+.20*structure)
            confirmed.add("visible_leaf_area_decreased")
        if recent:
            last = recent[-1]
            elapsed = (t-last["time"]).total_seconds()/3600
            difference = target-last["score"]
            prior_direction = last["target"]-last["score"]
            repeats = bool(confirmed or (elapsed>=2 and (
                (difference < -5 and prior_direction < -3 and last["target"]<=target+6)
                or (difference > 5 and prior_direction > 3 and last["target"]>=target-6))))
            prior_level = .72*last["score"]+.28*float(np.median([p["target"] for p in recent[-3:]]))
            weight = min(.66,max(.24,1.-2.**(-elapsed/26.)))
            if repeats:
                weight = max(.62,weight)
            elif (len(recent)>1 and abs(last["target"]-recent[-2]["score"])>8
                  and abs(target-recent[-2]["score"])<3.5):
                weight = max(.78,weight)  # Return quickly from an isolated excursion.
            elif abs(difference)>5:
                weight = min(.33,weight)
                # A one-off outlier must not enter twice via the recent centre.
                prior_level = last["score"]
            if z.get("_score_mode")=="chromatic_profile_partial":
                weight = min(.55,weight)
            score = weight*target+(1.-weight)*prior_level
        else:
            score = target
        z["health_score"] = min(100.,max(0.,float(score)))
        _set_category(z)
        z["health_warnings"] = ";".join(sorted(confirmed))
        if warning_candidates-confirmed and not confirmed:
            z["health_status"] += ";change_awaiting_confirmation"
        comparisons = [p for p in eligible if p["mode"]==z.get("_score_mode") and
                       22<=(t-p["time"]).total_seconds()/3600<=26]
        if comparisons:
            near = min(comparisons,key=lambda p:abs((t-p["time"]).total_seconds()-86400))
            z["health_trend_24h"] = z["health_score"]-near["score"]
        # Only distinct captures can confirm the direction of a change.
        if (not line or t>line[-1]["time"]) and not any(sha and p["sha"]==sha for p in line):
            line.append({"time":t,"score":z["health_score"],"target":target,"mode":z.get("_score_mode"),
                         "symptoms":warning_candidates,"sha":sha})


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
    "chromatic_profile": "Brightness-normalised leaf colour",
    "chromatic_profile_partial": "Brightness-normalised colour in verified regions",
    "change_awaiting_confirmation": "Visible change: compare the next suitable photo",
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
