"""A-M4 · Digital twin: visible leaf geometry, projections, and the 3D viewer."""

import argparse
import copy
import hashlib
import http.client
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from image_capture import calibration_file, parse_saved_time, iso, undistort_image
from computer_vision_pipeline import (
    ANALYSIS_VERSION, PROCESSING_WIDTH, SERIES_ID, PIPELINE_SHA256, TWIN_JSON_FILE,
    _ellipse_kernel, build_api_record, lock_results, open_browser_view, default_results_dir,
    prepare_historical_row, historical_row, make_json_safe, downscale, load_mask_override, mask_override_path,
    refine_mask, segment_leaves, viewer_directories, normalise_saved_code,
)
ENGLISH_LAYOUT_VERSION = 2


# Camera view and forecast settings
TWIN_PHOTO_VIEW = "side"  # Use "top" for a camera mounted directly above the pot.
TWIN_3D_VERSION = "0.7.0"
TWIN_VERSION = "0.1.0"
TWIN_MAX_LEAVES = 200
TWIN_HORIZON_HOURS = 24
TWIN_WINDOW_HOURS = 72
TWIN_MIN_OBSERVATIONS = 6
TWIN_MIN_SPAN_HOURS = 24
TWIN_MAX_GAP_HOURS = 6
TWIN_MAX_AGE_HOURS = 3
TWIN_TARGET_TOLERANCE_MINUTES = 40
OLLAMA_CARE_MODEL = "qwen2.5:3b"


def merge_twin_views(history, current):
    """Keep camera geometry consistent across the rolling photo window. Match identical photos between runs and retain the transforms without retaining old image files."""
    previous = {(z["file_name"], z.get("_sha256")): z for z in history if z.get("_sha256")}
    groups = {}
    for z in current:
        if z.get("_camera_view_id") is not None and z.get("_pose") is not None:
            groups.setdefault(z["_camera_view_id"], []).append(z)
    for uid, rows in groups.items():
        base = np.eye(3)
        is_identity = uid
        for z in rows:
            prior = previous.get((z["file_name"], z.get("_sha256")))
            if prior is None:
                continue
            info = prior.get("_historical_record", {}).get("analysis", {})
            pose = info.get("twin_camera_transform")
            if pose is None:
                pose = info.get("camera_transform")
            previous_id = info.get("twin_view_id") or info.get("view_id")
            if (not previous_id or pose is None or info.get("series_id") != SERIES_ID
                    or info.get("pipeline_sha256") != PIPELINE_SHA256
                    or info.get("image_size") != list(z.get("_image_shape", ()))
                    or info.get("lens_profile_sha256") != z.get("_lens_hash")):
                continue
            matrix = np.asarray(pose, dtype=float)
            if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
                continue
            new = np.vstack((z["_pose"], [0., 0., 1.]))
            try:
                base = np.linalg.solve(new, np.vstack((matrix, [0., 0., 1.])))
            except np.linalg.LinAlgError:
                continue
            is_identity = previous_id
            break
        for z in rows:
            z["_twin_view_id"] = is_identity
            z["_twin_pose"] = (np.vstack((z["_pose"], [0., 0., 1.]))@base)[:2]


def load_forecast_history_file(file_path):
    try:
        data = json.loads(file_path.read_text(encoding="utf-8-sig"))
        history = data["forecast_history"]
        if not isinstance(history, list):
            raise ValueError("forecast_history must be a list.")
        ids = set()
        for entry in history:
            if not isinstance(entry, dict) or not isinstance(entry.get("forecast_id"), str):
                raise ValueError("A forecast has no unique ID.")
            if entry["forecast_id"] in ids:
                raise ValueError("Duplicate forecast ID.")
            ids.add(entry["forecast_id"])
            if any(parse_saved_time(entry.get(k)) is None for k in ("created_at", "as_of", "target_at")):
                raise ValueError("A forecast has no valid UTC timestamp.")
            for field in ("predicted_px", "source_px"):
                value = entry.get(field)
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"Invalid forecast value in {field}")
            if not isinstance(entry.get("comparison_group"), str):
                raise ValueError("Missing forecast comparison group.")
            if entry.get("evaluation") is not None and not isinstance(entry["evaluation"], dict):
                raise ValueError("Invalid forecast evaluation.")
        return history
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError(f"Could not safely read the forecast history: {error}. Previous files were kept.") from error


def load_forecast_history(output_dir):
    "Merge current and older forecast history without duplicating IDs."
    result = {}
    output_dir = Path(output_dir)
    sources = [viewer_directories(output_dir)[0]/TWIN_JSON_FILE, output_dir/TWIN_JSON_FILE]
    if output_dir.name == "results":
        sources.extend((output_dir.parent/"digital twin"/TWIN_JSON_FILE,
                        output_dir.parent/"auswertung"/TWIN_JSON_FILE))
    for file_path in sources:
        if file_path.is_file():
            for entry in load_forecast_history_file(file_path):
                if "model_selection" in entry:
                    entry["model_selection"] = normalise_saved_code(entry["model_selection"])
                if entry.get("series_id") == "pflanze-01":
                    entry["series_id"] = "plant-01"
                identity_fields = entry["forecast_id"]
                prior = result.setdefault(identity_fields,entry)
                if prior.get("evaluation") is None and entry.get("evaluation") is not None:
                    prior["evaluation"] = entry["evaluation"]
    return list(result.values())


def twin_observation(z):
    "Use only leaf pixel measurements verified as comparable for the same plant."
    timestamp = z.get("_capture_time") or parse_saved_time(z.get("captured_at"))
    if timestamp is None:
        return None, "capture_time_missing"
    if not z.get("usable") or not z.get("plant_pixels"):
        return None, "image_not_usable"
    if "check_area_jump" in (z.get("quality_flags") or ""):
        return None, "check_area_jump"
    info = build_api_record(z)["analysis"]
    if info.get("series_id") != SERIES_ID:
        return None, "plant_series_unverified"
    image_shape = info.get("image_size")
    pose = info.get("twin_camera_transform")
    if pose is None:
        pose = info.get("camera_transform")
    uid = info.get("twin_view_id") or info.get("view_id")
    if not isinstance(image_shape, (list, tuple)) or len(image_shape) != 2 or not all(isinstance(n, int) and n > 0 for n in image_shape):
        return None, "image_size_not_recorded"
    if not uid or not info.get("pipeline_sha256") or pose is None:
        return None, "camera_view_unverified"
    matrix = np.asarray(pose, dtype=float)
    if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
        return None, "invalid_camera_geometry"
    scale = float(np.hypot(*matrix[:, 0]))
    angle = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    translation_px = float(np.linalg.norm(matrix[:, 2]))
    # The prototype requires a nearly fixed camera.
    if abs(scale-1) > .005 or angle > .5 or translation_px > max(2., .003*min(PROCESSING_WIDTH, image_shape[1])):
        return None, "camera_movement_too_large_for_projection"
    if info.get("mask_clipped") and translation_px > 1.:
        return None, "clipped_frame_shifted"
    area = float(z["plant_pixels"])
    maximal = image_shape[0]*image_shape[1]
    if not math.isfinite(area) or not 0 < area <= maximal:
        return None, "invalid_leaf_pixel_count"
    group = {"series_id": SERIES_ID, "view_id": uid, "image_size": list(image_shape),
              "pipeline_sha256": info["pipeline_sha256"], "lens": info.get("lens_profile_sha256")}
    key = hashlib.sha256(json.dumps(group, sort_keys=True).encode("utf-8")).hexdigest()
    return {"time": timestamp, "pixels": area, "max_pixels": maximal, "group": key,
            "file_name": z["file_name"], "checksum_sha256": z.get("_sha256"),
            "pipeline_sha256": info["pipeline_sha256"]}, None


def twin_fit(points):
    "Fit a line at the actual capture times, subject to the minimum sample requirements."
    if len(points) < TWIN_MIN_OBSERVATIONS:
        return None, "too_few_comparable_photos"
    span = (points[-1]["time"]-points[0]["time"]).total_seconds()/3600
    if span < TWIN_MIN_SPAN_HOURS:
        return None, "series_shorter_than_24_hours"
    gap = max((b["time"]-a["time"]).total_seconds()/3600 for a, b in zip(points, points[1:]))
    if gap > TWIN_MAX_GAP_HOURS:
        return None, "sampling_gap_too_large"
    x = np.array([(p["time"]-points[-1]["time"]).total_seconds()/3600 for p in points])
    y = np.array([p["pixels"] for p in points])
    slope, start = np.linalg.lstsq(np.column_stack((x, np.ones(len(x)))), y, rcond=None)[0]
    return {"slope_px_per_hour": float(slope), "intercept_px": float(start),
            "points": len(points), "span_hours": round(span, 3),
            "fit_mae_px": float(np.mean(np.abs(y-(slope*x+start))))}, None


def twin_backtest(points):
    "Fit earlier measurements and test on a later one without shuffling the observations."
    linear_error, baseline_error = [], []
    tolerance = timedelta(minutes=TWIN_TARGET_TOLERANCE_MINUTES)
    for i, origin in enumerate(points):
        earlier = [p for p in points[:i+1] if p["time"] >= origin["time"]-timedelta(hours=TWIN_WINDOW_HOURS)]
        model, _ = twin_fit(earlier)
        if model is None:
            continue
        target = origin["time"]+timedelta(hours=TWIN_HORIZON_HOURS)
        later = [p for p in points[i+1:] if abs(p["time"]-target) <= tolerance]
        if not later:
            continue
        observed = min(later, key=lambda p: abs(p["time"]-target))
        # Evaluate both models at the actual observation time.
        h = (observed["time"]-origin["time"]).total_seconds()/3600
        forecast = model["intercept_px"]+model["slope_px_per_hour"]*h
        if not 0 < forecast <= origin["max_pixels"]:
            continue
        linear_error.append(abs(forecast-observed["pixels"]))
        baseline_error.append(abs(origin["pixels"]-observed["pixels"]))
    return {"method": "rolling_origin", "horizon_hours": TWIN_HORIZON_HOURS,
            "target_tolerance_minutes": TWIN_TARGET_TOLERANCE_MINUTES, "comparisons": len(linear_error),
            "linear_mae_px": float(np.mean(linear_error)) if linear_error else None,
            "last_value_mae_px": float(np.mean(baseline_error)) if baseline_error else None,
            "status": "historical_method_comparison" if len(linear_error) >= 3 else "too_few_forecast_checks"}


def evaluate_issued_forecasts(history, points, current_time):
    "Evaluate issued forecasts against later photos without changing the predictions."
    for entry in history:
        if entry.get("evaluation") is not None or entry.get("kind") != "issued_forecast":
            continue
        target = parse_saved_time(entry["target_at"])
        issued = parse_saved_time(entry["created_at"])
        origin = parse_saved_time(entry["as_of"])
        if issued >= target or current_time < target:
            continue  # Exclude forecasts created after the event from prospective evaluation.
        tolerance = timedelta(minutes=entry.get("target_tolerance_minutes", TWIN_TARGET_TOLERANCE_MINUTES))
        candidates = [p for p in points if p["group"] == entry["comparison_group"]
                      and issued < p["time"] <= current_time and origin < p["time"]
                      and abs(p["time"]-target) <= tolerance]
        if not candidates:
            continue
        observed = min(candidates, key=lambda p: abs(p["time"]-target))
        if abs(observed["time"]-target) > timedelta(minutes=1) and current_time < target+tolerance:
            continue  # Wait for the target window to finish if no close observation exists.
        entry["evaluation"] = {"checked_at": iso(current_time), "observed_at": iso(observed["time"]),
                    "file_name": observed["file_name"], "checksum_sha256": observed["checksum_sha256"],
                    "observed_px": observed["pixels"], "absolute_error_px": abs(entry["predicted_px"]-observed["pixels"]),
                    "last_value_error_px": abs(entry["source_px"]-observed["pixels"]),
                    "time_difference_minutes": (observed["time"]-target).total_seconds()/60}


def digital_twin(rows, history=None, independent_images=False, current_time=None):
    "Build an observational digital twin and short-term visible-area projection."
    current_time = current_time or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("A digital twin evaluation requires a time zone.")
    current_time = current_time.astimezone(timezone.utc)
    log = copy.deepcopy(history or [])
    data = {"version": TWIN_VERSION, "series_id": SERIES_ID, "generated_at": iso(current_time),
             "pipeline_version": ANALYSIS_VERSION, "scope": "visible_leaf_area_pixels",
             "status": "no_reliable_capture_time", "state": None, "forecast": None,
             "training": {"points": 0, "span_hours": 0, "min_points": TWIN_MIN_OBSERVATIONS,
                          "min_span_hours": TWIN_MIN_SPAN_HOURS, "window_hours": TWIN_WINDOW_HOURS},
             "validation": None, "online_validation": None, "forecast_history": log,
             "limitations": ["Prototype only. The growth projection has not been validated biologically.",
                             "Visible leaf area can change because leaves move or the mask changes.",
                             "The viewer uses visible contours. It does not measure plant height or depth.",
                             "Estimating care effects requires aligned sensor and intervention records."]}
    points, excluded = [], {}
    if independent_images:
        data["status"] = "independent_images_no_shared_twin"
        return data
    chronological = sorted((z for z in rows if z.get("_capture_time") or parse_saved_time(z.get("captured_at"))),
                      key=lambda z: z.get("_capture_time") or parse_saved_time(z["captured_at"]))
    for z in rows:
        point, reason = twin_observation(z)
        if point is not None:
            points.append(point)
        else:
            excluded[reason] = excluded.get(reason, 0)+1
    data["training"]["excluded_images"] = excluded
    evaluate_issued_forecasts(log, points, current_time)
    data["online_validation"] = {"comparisons": 0, "mae_px": None, "last_value_mae_px": None}
    if not chronological:
        return data
    latest_row = chronological[-1]
    timestamp = latest_row.get("_capture_time") or parse_saved_time(latest_row["captured_at"])
    observation_age = (current_time-timestamp).total_seconds()/3600
    data["state"] = {"observed_at": iso(timestamp), "file_name": latest_row["file_name"],
             "leaf_pixels": latest_row.get("plant_pixels"), "health_score": latest_row.get("health_score"),
             "leaf_area_cm2": latest_row.get("leaf_area_cm2"), "diameter_mm": latest_row.get("diameter_mm"),
             "mm_per_px": latest_row.get("mm_per_px"), "scale_source": latest_row.get("scale_source"),
             "growth_rate_pct_per_day": latest_row.get("growth_rate_pct_per_day"),
             "growth_rate_cm2_per_day": latest_row.get("growth_rate_cm2_per_day"),
             "health_status": latest_row.get("health_status"), "usable": bool(latest_row.get("usable")),
             "quality_flags": latest_row.get("quality_flags"), "age_hours": round(observation_age, 3),
             "fresh": bool(0 <= observation_age <= TWIN_MAX_AGE_HOURS)}
    if timestamp > current_time:
        data["status"] = "capture_time_in_future"
        return data
    current, reason = twin_observation(latest_row)
    if current is None:
        data["status"] = reason
        return data
    verified = [p["evaluation"] for p in log if p.get("kind") == "issued_forecast"
                and p.get("series_id") == SERIES_ID and p.get("model_version") == TWIN_VERSION
                and p.get("comparison_group") == current["group"] and p.get("evaluation") is not None]
    data["online_validation"] = {"comparisons": len(verified),
             "mae_px": float(np.mean([p["absolute_error_px"] for p in verified])) if verified else None,
             "last_value_mae_px": float(np.mean([p["last_value_error_px"] for p in verified])) if verified else None}
    # Count only one observation for each capture timestamp.
    by_time = {p["time"]: p for p in points if p["group"] == current["group"]
               and timestamp-timedelta(hours=TWIN_WINDOW_HOURS) <= p["time"] <= timestamp}
    by_time[timestamp] = current
    series = [by_time[t] for t in sorted(by_time)]
    span = (series[-1]["time"]-series[0]["time"]).total_seconds()/3600 if series else 0
    data["training"].update(points=len(series), span_hours=round(span, 3), comparison_group=current["group"],
                             first_at=iso(series[0]["time"]) if series else None, last_at=iso(timestamp))
    model, reason = twin_fit(series)
    if model is None:
        data["status"] = reason
        return data
    test = twin_backtest(series)
    data["validation"] = test
    target = timestamp+timedelta(hours=TWIN_HORIZON_HOURS)
    value = model["intercept_px"]+model["slope_px_per_hour"]*TWIN_HORIZON_HOURS
    name, selection = "linear_trend", "provisional_linear_baseline"
    if test["comparisons"] >= 3 and test["last_value_mae_px"] <= test["linear_mae_px"]:
        name, selection = "last_value", "baseline_at_least_as_accurate_in_backtest"
    if not 0 < value <= current["max_pixels"]:
        name, selection = "last_value", "linear_projection_exceeds_image_bounds"
    if name == "last_value":
        value = current["pixels"]
    live = bool(0 <= observation_age <= TWIN_MAX_AGE_HOURS and current_time < target)
    data["status"] = "provisional_forecast" if live else "historical_projection_stale_data"
    data["forecast"] = {"as_of": iso(timestamp), "target_at": iso(target), "horizon_hours": TWIN_HORIZON_HOURS,
             "predicted_px": round(float(value), 2), "source_px": current["pixels"], "model": name,
             "model_selection": selection, "is_current": live, "biologically_validated": False,
             "fit": model, "comparison_group": current["group"]}
    identity_fields = {"model_version": TWIN_VERSION, "source": current["checksum_sha256"],
                   "as_of": iso(timestamp), "target_at": iso(target), "group": current["group"]}
    forecast_id = hashlib.sha256(json.dumps(identity_fields, sort_keys=True).encode("utf-8")).hexdigest()
    existing = next((p for p in log if p["forecast_id"] == forecast_id), None)
    if existing is not None:
        # Late imports must not change a forecast that has already been issued.
        for field in ("predicted_px", "source_px", "model", "model_selection", "fit"):
            data["forecast"][field] = copy.deepcopy(existing.get(field))
        data["forecast"].update(forecast_id=forecast_id, issued_at=existing["created_at"])
    elif live:
        log.append({"forecast_id": forecast_id, "kind": "issued_forecast", "created_at": iso(current_time),
                     "series_id": SERIES_ID, "model_version": TWIN_VERSION, "model": name,
                     "model_selection": selection, "fit": copy.deepcopy(model),
                     "as_of": iso(timestamp), "target_at": iso(target), "predicted_px": round(float(value), 2),
                     "source_px": current["pixels"], "source_file": current["file_name"],
                     "source_checksum_sha256": current["checksum_sha256"], "comparison_group": current["group"],
                     "target_tolerance_minutes": TWIN_TARGET_TOLERANCE_MINUTES,
                     "evaluation": None})
        data["forecast"].update(forecast_id=forecast_id, issued_at=iso(current_time))
    return make_json_safe(data)


def save_twin(data, twin_folder):
    "Save the current model state and forecast history."
    twin_folder.mkdir(parents=True,exist_ok=True)
    tmp = twin_folder/".digital_twin.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(twin_folder/TWIN_JSON_FILE)


def leaf_points_path(output_dir, sha, rectified):
    # Use the same image coordinates as the manual leaf mask.
    return Path(output_dir)/"leaf_labels"/(mask_override_path(output_dir,sha,rectified).stem+".json")


def load_leaf_points(file_path, image_shape):
    data = json.loads(file_path.read_text(encoding="utf-8"))
    points = (data.get("points", data.get("punkte")) if isinstance(data, dict)
              and data.get("image_shape", data.get("form")) == list(image_shape) else None)
    h,w = image_shape
    if (not isinstance(points,list) or not 1 <= len(points) <= TWIN_MAX_LEAVES
            or any(not isinstance(p,list) or len(p)!=2 or any(type(n) is not int for n in p)
                   or not (0 <= p[0] < w and 0 <= p[1] < h) for p in points)
            or len(set(map(tuple,points)))!=len(points)):
        raise ValueError("The leaf markings contain invalid coordinates or duplicate points.")
    return [tuple(p) for p in points]


def save_leaf_points(file_path, image_shape, points):
    file_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=file_path.parent) as tmp:
        file_handle = Path(tmp)/"points.json"
        file_handle.write_text(json.dumps({"image_shape":list(image_shape),"points":points},ensure_ascii=False),encoding="utf-8")
        load_leaf_points(file_handle,image_shape)
        file_handle.replace(file_path)


def mark_leaves(photo, output_dir, independent_images=False):
    "Mark one point per visible leaf without changing the measurement mask."
    raw = photo.read_bytes()
    image = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The original photo could not be read.")
    rectified = calibration_file().is_file() and not independent_images
    if rectified:
        image = undistort_image(image,json.loads(calibration_file().read_text(encoding="utf-8")))
    if ((sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")))
            or (hasattr(cv2,"currentUIFramework") and not cv2.currentUIFramework())):
        raise ValueError("Could not open an OpenCV window. Use a desktop install of opencv-contrib-python.")
    sha = hashlib.sha256(raw).hexdigest()
    file_path = leaf_points_path(output_dir,sha,rectified)
    points = load_leaf_points(file_path,image.shape[:2]) if file_path.is_file() else []
    leaf_mask = load_mask_override(output_dir,sha,image.shape[:2],rectified)
    if leaf_mask is None:
        leaf_mask = refine_mask(image,segment_leaves(downscale(image)))
    h,w = image.shape[:2]
    full_view = (0,0,w,h)
    x,y,mw,mh = cv2.boundingRect(leaf_mask)
    edge = max(16,round(.09*max(mw,mh)))
    near = (max(0,x-edge),max(0,y-edge),min(w,x+mw+edge),min(h,y+mh+edge)) if mw and mh else full_view
    camera_view = {}
    def crop_box(bbox):
        x0,y0,x1,y1 = bbox
        factor = min(1.,1250/(x1-x0),740/(y1-y0))
        b,hc = max(1,round((x1-x0)*factor)),max(1,round((y1-y0)*factor))
        camera_view.update(file_name=cv2.resize(image[y0:y1,x0:x1],(b,hc),interpolation=cv2.INTER_AREA),
                       bbox=bbox, sx=b/(x1-x0), sy=hc/(y1-y0))
    def on_click(event,px,py,flags,param):
        if event==cv2.EVENT_RBUTTONDOWN and points:
            points.pop()
        elif event==cv2.EVENT_LBUTTONDOWN and len(points)<TWIN_MAX_LEAVES:
            x0,y0,x1,y1 = camera_view["bbox"]
            point = (min(x1-1,x0+int((px+.5)/camera_view["sx"])),min(y1-1,y0+int((py+.5)/camera_view["sy"])))
            if px>=0 and py>=0 and all(math.dist(p,point)>2 for p in points):
                points.append(point)
    title = "BioBox - Mark visible leaves"
    print("Click once per leaf. Right-click or U: undo; R: clear; F: full photo; Enter: save; Esc: cancel.")
    crop_box(near)
    try:
        cv2.namedWindow(title,cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(title,on_click)
        while True:
            preview = camera_view["file_name"].copy()
            x0,y0,x1,y1 = camera_view["bbox"]
            for i,(px,py) in enumerate(points,1):
                if not (x0<=px<x1 and y0<=py<y1):
                    continue
                bx = min(preview.shape[1]-1,int((px-x0+.5)*camera_view["sx"]))
                by = min(preview.shape[0]-1,int((py-y0+.5)*camera_view["sy"]))
                cv2.circle(preview,(bx,by),4,(16,19,14),-1,cv2.LINE_AA)
                cv2.circle(preview,(bx,by),2,(151,252,233),-1,cv2.LINE_AA)
                for colour,stroke_width in [((18,21,18),3),((235,254,242),1)]:
                    cv2.putText(preview,str(i),(bx+5,by-4),cv2.FONT_HERSHEY_SIMPLEX,.43,colour,stroke_width,cv2.LINE_AA)
            cv2.imshow(title,preview)
            key = cv2.waitKey(35)&255
            if key==27 or cv2.getWindowProperty(title,cv2.WND_PROP_VISIBLE)<1:
                return None
            if key in (10,13) and points:
                save_leaf_points(file_path,image.shape[:2],points)
                return len(points)
            if key in (ord('u'),ord('U')) and points:
                points.pop()
            if key in (ord('r'),ord('R')):
                points.clear()
            if key in (ord('f'),ord('F')):
                crop_box(full_view if camera_view["bbox"]==near else near)
    except cv2.error as error:
        raise ValueError("Could not open the annotation window. Use --leaf-labels PHOTO LABEL_PNG to import labels.") from error
    finally:
        try:cv2.destroyAllWindows()
        except cv2.error:pass


def assign_leaf_regions(fg, points, image=None):
    "Keep each seed region and allow nearby image edges to adjust the boundary."
    cores = np.ones(fg.shape,np.uint8)
    ys,xs = np.asarray(points,np.int32).T
    cores[ys,xs] = 0
    _, ids = cv2.distanceTransformWithLabels(cores,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
    lut = np.zeros(int(ids.max())+1,np.uint16)
    lut[ids[ys,xs]] = np.arange(1,len(points)+1,dtype=np.uint16)
    labels = lut[ids]
    if image is not None and len(points)>1:
        # Watershed alone can miss small leaves in a dense canopy.
        # Use the nearest seeds to anchor distinct colour regions.
        d = cv2.distanceTransform(cores,cv2.DIST_L2,5)
        marker = np.where(fg,np.where(d<=2.4,labels+1,0),1).astype(np.int32)
        marker[ys,xs] = np.arange(2,len(points)+2,dtype=np.int32)
        topo = cv2.GaussianBlur(image,(3,3),.65)
        cv2.watershed(topo,marker)
        py,px = np.nonzero(fg & (marker>1) & (d>2.4))
        idx = marker[py,px]-2
        spacing = np.hypot(py-ys[idx],px-xs[idx])
        near = spacing <= 1.27*d[py,px]+2.3
        labels[py[near],px[near]] = idx[near]+1
    labels[~fg] = 0
    return labels


def twin_colour_seeds(fg, colours, points, labels, dist):
    "Add seeds only to large regions that have visible colour edges."
    if len(points)<8 or len(points)>=TWIN_MAX_LEAVES:
        return points
    numerator = np.bincount(labels.ravel(),minlength=len(points)+1)
    typical = max(18.,float(np.median(numerator[1:])))
    full_size = numerator>2.9*typical
    full_size[0] = False
    if not np.any(full_size):
        return points
    l,a,b = cv2.split(cv2.cvtColor(colours,cv2.COLOR_BGR2LAB))
    e1 = cv2.Canny(cv2.GaussianBlur(l,(5,5),1.),20,42)
    e2 = cv2.Canny(cv2.GaussianBlur(a,(5,5),1.),12,24)
    edges = cv2.morphologyEx(e1|e2,cv2.MORPH_CLOSE,_ellipse_kernel(3))>0
    edge_count = np.bincount(labels[edges&fg],minlength=len(numerator))
    full_size &= edge_count>=.055*numerator
    chroma = cv2.absdiff(a,128).astype(np.uint16)+cv2.absdiff(b,128)
    interior = fg & ~edges & (chroma>=9)
    d = cv2.distanceTransform(interior.astype(np.uint8),cv2.DIST_L2,5)
    r = max(2.5,min(4.2,.0051*max(fg.shape)))
    maxima = (d>=cv2.dilate(d,_ellipse_kernel(9))-1e-5)&(d>=r)&(dist>=r*.75)&full_size[labels]
    added = list(points)
    count_items = np.zeros(len(numerator),dtype=int)
    for y,x in sorted(zip(*np.nonzero(maxima)),key=lambda p:-d[p]):
        ident = labels[y,x]
        if count_items[ident]>=min(7,int(numerator[ident]/(typical*1.75))-1):
            continue
        if any(math.hypot(y-ay,x-ax)<max(6.,.87*(d[y,x]+d[ay,ax])) for ay,ax in added):
            continue
        added.append((int(y),int(x)))
        count_items[ident] += 1
        if len(added)==TWIN_MAX_LEAVES:
            break
    return added


def twin_geometry_mask(leaf_mask):
    "Ignore tiny fragments for leaf geometry only."
    n,components,stats,_ = cv2.connectedComponentsWithStats(leaf_mask,connectivity=8)
    if n<=2:
        return leaf_mask
    total = int(stats[1:,4].sum())
    full_size = [s for s in stats[1:] if s[4]>=.012*total]
    if not full_size:
        return leaf_mask
    _,_,w,h = cv2.boundingRect(leaf_mask)
    retained = np.ones(n,np.uint8)*255
    retained[0] = 0
    for i,(x,y,b,hc,area) in enumerate(stats[1:],1):
        if area<.0045*total and all(math.hypot(max(0,u-x-b,x-u-bu),max(0,v-y-hc,y-v-hv))>
                                    .078*max(w,h) for u,v,bu,hv,_ in full_size):
            retained[i] = 0
    return retained[components] if np.any(retained[1:]==0) else leaf_mask


def twin_leaf_labels(leaf_mask, image=None, annotations=None):
    "Find seeds within the leaf mask and separate them along image boundaries."
    x,y,w,h = cv2.boundingRect(leaf_mask)
    if not w or not h:
        return None
    scale = min(1.,820/max(w,h))
    size = (max(1,round(w*scale)),max(1,round(h*scale)))
    raw_value = leaf_mask[y:y+h,x:x+w]>0
    fg = cv2.resize(raw_value.astype(np.uint8),size,interpolation=cv2.INTER_AREA)>0
    if annotations is not None:
        points = []
        tolerance = max(3,round(.003*max(w,h)))
        for nr,(px,py) in enumerate(annotations,1):
            rx,ry = px-x,py-y
            if not (0<=ry<h and 0<=rx<w and raw_value[ry,rx]):
                x1,x2 = max(0,rx-tolerance),min(w,rx+tolerance+1)
                y1,y2 = max(0,ry-tolerance),min(h,ry+tolerance+1)
                if x1>=x2 or y1>=y2:
                    raise ValueError(f"Leaf marking {nr} is outside the mask.")
                gy,gx = np.nonzero(raw_value[y1:y2,x1:x2]); gy,gx = gy+y1,gx+x1
                if not len(gy):
                    raise ValueError(f"Leaf marking {nr} is outside the mask.")
                i = np.argmin((gy-ry)**2+(gx-rx)**2)
                ry,rx = int(gy[i]),int(gx[i])
            points.append((ry,rx))
        if len(set(points))!=len(points):
            raise ValueError("Two leaf markings point to the same mask pixel.")
        reduced = [(int((py+.5)*size[1]/h),int((px+.5)*size[0]/w)) for py,px in points]
        if len(set(reduced))==len(reduced):
            points = reduced
        else:
            fg,size = raw_value,(w,h)
        for py,px in points:
            fg[py,px] = True
    else:
        pad = np.pad(fg.astype(np.uint8),2)
        d = cv2.distanceTransform(pad,cv2.DIST_L2,5)
        dist = d[2:-2,2:-2]
        n, components, stats, _ = cv2.connectedComponentsWithStats(fg.astype(np.uint8),connectivity=8)
        radius = max(1.5,min(2.8,.0042*max(size)))
        core = _ellipse_kernel(max(5,min(13,2*round(.006*max(size))+1)))
        maxima = (dist>=cv2.dilate(d,core)[2:-2,2:-2]-1e-5)&(dist>=radius)
        min_px = max(6,round(np.count_nonzero(fg)*.00033))
        candidates = []
        for i in range(1,n):
            cx,cy,cw,ch,a = stats[i]
            if a<min_px:
                continue
            local_path = dist[cy:cy+ch,cx:cx+cw]
            part = components[cy:cy+ch,cx:cx+cw]==i
            depth = float(local_path[part].max())
            if depth<radius:
                continue
            ys,xs = np.nonzero(part&maxima[cy:cy+ch,cx:cx+cw])
            if not len(ys):
                ys,xs = np.array(np.unravel_index(np.argmax(np.where(part,local_path,0)),local_path.shape)).reshape(2,1)
            candidates.extend((int(py)+cy,int(px)+cx) for py,px in zip(ys,xs))
        points = []
        for py,px in sorted(candidates,key=lambda p:-dist[p]):
            r = dist[py,px]
            near = False
            for ay,ax in points:
                spacing = math.hypot(py-ay,px-ax)
                ra = dist[ay,ax]
                if spacing<=max(5.,.68*(min(ra,20)+min(r,20))):
                    near = True
                    break
                if spacing<=2.4*(ra+r):
                    ys = np.rint(np.linspace(ay,py,9)).astype(int)
                    xs = np.rint(np.linspace(ax,px,9)).astype(int)
                    if dist[ys,xs].min()>=.85*min(ra,r):
                        near = True
                        break
            if not near:
                points.append((py,px))
            if len(points)==TWIN_MAX_LEAVES:
                break
        if not points:
            if not np.count_nonzero(fg)>=5:
                return None
            points = [np.unravel_index(dist.argmax(),dist.shape)]
    colours = cv2.resize(image[y:y+h,x:x+w],size,interpolation=cv2.INTER_AREA) if image is not None else None
    if annotations is None and colours is not None:
        points = twin_colour_seeds(fg,colours,points,assign_leaf_regions(fg,points),dist)
    reduced = assign_leaf_regions(fg,points,colours)
    labels = np.zeros(leaf_mask.shape,np.uint16)
    labels[y:y+h,x:x+w] = cv2.resize(reduced,(w,h),interpolation=cv2.INTER_NEAREST_EXACT)
    # Assign every original mask pixel to a valid neighbouring seed, including at thin edges.
    section = labels[y:y+h,x:x+w]
    gaps = raw_value&(section==0)
    if gaps.any():
        existing = section>0
        if not existing.any():
            return None
        _, ids = cv2.distanceTransformWithLabels((~existing).astype(np.uint8),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
        lut = np.zeros(int(ids.max())+1,np.uint16)
        lut[ids[existing]] = section[existing]
        section[gaps] = lut[ids[gaps]]
    labels[leaf_mask==0] = 0
    return labels


def twin_leaf_geometry(image, leaf_mask, label_path, points_path=None):
    "Return contours in shared photo coordinates, or no geometry if the mask is unusable."
    if not np.any(leaf_mask):
        return None
    source = "estimated"
    note = None
    labels = None
    if label_path.is_file():
        labels = cv2.imdecode(np.fromfile(label_path,dtype=np.uint8),cv2.IMREAD_UNCHANGED)
        if (labels is None or labels.ndim != 2 or labels.shape != leaf_mask.shape or
                labels.dtype not in (np.uint8,np.uint16) or not np.array_equal(labels>0,leaf_mask>0)
                or len(np.unique(labels))>TWIN_MAX_LEAVES+1):
            note = "Leaf labels do not match the current mask."
            labels = None
        else:
            source = "manual"
    if labels is None and points_path is not None and points_path.is_file():
        try:
            points = load_leaf_points(points_path,leaf_mask.shape)
            labels = twin_leaf_labels(leaf_mask,image,points)
            if labels is None or np.count_nonzero(np.bincount(labels.ravel())[1:])!=len(points):
                raise ValueError("At least one leaf marking could not be assigned to a distinct region.")
            source = "manual"
            note = "The leaf count was marked manually; region boundaries were estimated."
        except (OSError,ValueError,TypeError,cv2.error) as error:
            labels = None
            note = "Leaf annotations could not be used: "+str(error).splitlines()[0]
    if labels is None:
        note = note or "The count is uncertain when leaves are hidden or overlap."
        labels = twin_leaf_labels(twin_geometry_mask(leaf_mask),image)
    if labels is None:
        return None
    x,y,w,h = cv2.boundingRect(leaf_mask)
    divisor = max(leaf_mask.shape)
    cx,cy = x+(w-1)/2,y+(h-1)/2
    regions = labels[y:y+h,x:x+w]
    colours = image[y:y+h,x:x+w]
    ry,rx = np.nonzero(regions)
    if not len(ry):
        return None
    ids = regions[ry,rx]
    n = int(ids.max())+1
    minx,miny = np.full(n,w),np.full(n,h)
    maxx,maxy = np.zeros(n,dtype=int),np.zeros(n,dtype=int)
    np.minimum.at(minx,ids,rx); np.minimum.at(miny,ids,ry)
    np.maximum.at(maxx,ids,rx); np.maximum.at(maxy,ids,ry)
    leaf_regions = []
    for ident in np.unique(ids):
        x0,x1,y0,y1 = minx[ident],maxx[ident]+1,miny[ident],maxy[ident]+1
        segment = (regions[y0:y1,x0:x1]==ident).astype(np.uint8)
        contours,_ = cv2.findContours(segment,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        rings = []
        for k in sorted(contours,key=cv2.contourArea,reverse=True):
            if len(k)<3:
                continue
            k = cv2.approxPolyDP(k,max(.65,cv2.arcLength(k,True)*.001),True).reshape(-1,2)
            if len(k)>=3 and cv2.contourArea(k)>0:
                rings.append([[round((int(a)+x0+x-cx)/divisor,6),round((int(b)+y0+y-cy)/divisor,6)] for a,b in k])
        if not rings:
            if source!="manual":
                continue
            # Preserve the ID of even a small manually labelled leaf.
            rings = [[[round((a+x-cx)/divisor,6),round((b+y-cy)/divisor,6)] for a,b in
                      ((x0-.5,y0-.5),(x1-.5,y0-.5),(x1-.5,y1-.5),(x0-.5,y1-.5))]]
        b,g,r,_ = cv2.mean(colours[y0:y1,x0:x1],mask=segment)
        leaf_regions.append({"rings":rings,"rgb":[round(r),round(g),round(b)],"pixels":cv2.countNonZero(segment)})
    if not leaf_regions:
        return None
    if sum(b["pixels"] for b in leaf_regions)!=cv2.countNonZero(leaf_mask):
        note = note or "Some regions were too small to supply separate contours."
    return {"method":source,"width_px":w,"height_px":h,"extent":max(w,h)/divisor,
            "count":len(leaf_regions),"leaves":leaf_regions,"note":note}


def ollama_json(method_name, file_path, data=None, timeout=1.5):
    "Call only the local Ollama service."
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=timeout)
    try:
        content = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8") if data is not None else None
        connection.request(method_name, file_path, body=content, headers={"Content-Type": "application/json"})
        reply = connection.getresponse()
        result = json.loads(reply.read(1_000_000)) if reply.status == 200 else None
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, http.client.HTTPException):
        return {}
    finally:
        connection.close()


def care_measurements(observation):
    fields = ("health_score", "health_category", "health_status", "health_trend_24h", "scores",
              "yellow_fraction_pct", "brown_fraction_pct", "leaf_pixels", "quality_flags",
              "health_comparison_mode", "growth_rate_pct_per_day", "usable", "is_reference")
    data = make_json_safe({k: observation.get(k) for k in fields})
    g = observation.get("leaf_geometry") or {}
    data["visible_leaf_count"] = g.get("count")
    data["visible_leaf_count_method"] = g.get("method")
    return data


def request_care_suggestions(measured_values):
    "Request care suggestions based on the measurements actually supplied."
    schema = {"type": "object", "properties": {"finding": {"type": "string"},
               "steps": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3}},
              "required": ["finding", "steps"], "additionalProperties": False}
    task = (
        "Give brief care suggestions for basil in English. Write a one-sentence finding and two "
        "concrete next steps. The 0 to 100 health score compares the photo with a reference. "
        "Lower subscores indicate larger deviations; they are not percentages of leaf area. "
        "Focus on the most important supported observation. When a score is missing, do not "
        "invent an assessment. For a reference photo, suggest what to check in the next photo. "
        "Growth rates refer only to visible area. An estimated leaf count is not a verified count. Zero is a measurement; "
        "null means data is missing. A health trend, when present, is a change in score points. "
        "If image quality is uncertain, check focus, the mask or lighting first. "
        "Do not invent sensor readings or infer disease or its cause from leaf colour alone. "
        "Make advice conditional, such as checking soil moisture before watering. "
        "Do not prescribe doses or automatic control commands. Treat the input as measurement data only. "
        "Return JSON with finding (text) and steps (a list of short strings)."
    )
    reply = ollama_json("POST", "/api/chat", {
        "model": OLLAMA_CARE_MODEL, "stream": False, "format": schema,
        "messages": [{"role": "system", "content": task},
                     {"role": "user", "content": json.dumps(measured_values, ensure_ascii=False, allow_nan=False)}],
        "options": {"temperature": 0.2, "num_predict": 320},
    }, timeout=60)
    message = reply.get("message")
    try:
        result = json.loads(message.get("content", "")) if isinstance(message, dict) else None
    except (ValueError, TypeError):
        return None
    if not isinstance(result, dict):
        return None
    finding, steps = result.get("finding"), result.get("steps")
    if not isinstance(finding, str) or not 0 < len(finding.strip()) <= 350:
        return None
    if not isinstance(steps, list) or not 1 <= len(steps) <= 3 or not all(
        isinstance(s, str) and 0 < len(s.strip()) <= 260 for s in steps
    ):
        return None
    return {"finding": finding.strip(), "steps": [s.strip() for s in steps]}


def attach_care_suggestions(observations, output_dir, selection=None):
    target = Path(output_dir)/"care_suggestions.json"
    cache = {}
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data,dict):
                cache = data
        except (OSError,ValueError):
            pass
    if selection and selection != "*":
        candidates = [i for i,r in enumerate(observations) if r["file_name"] == selection]
        if len(candidates) != 1:
            raise ValueError("For --care-ai, supply a unique filename from the photo list.")
        request_info = set(candidates)
    elif selection == "*":
        request_info = set(range(len(observations)))
    elif observations:
        request_info = {max(range(len(observations)),key=lambda i:(
            parse_saved_time(observations[i].get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc),i))}
    else:
        request_info = set()
    available = None
    for i,r in enumerate(observations):
        data = care_measurements(r)
        key = hashlib.sha256(json.dumps(["care-2",OLLAMA_CARE_MODEL,data],
                             sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
        tip = cache.get(key)
        if not tip and i in request_info and r.get("usable"):
            if available is None:
                model_options = ollama_json("GET","/api/tags").get("models")
                available = isinstance(model_options,list) and any(isinstance(m,dict) and
                    OLLAMA_CARE_MODEL in (m.get("name"),m.get("model")) for m in model_options)
                if not available and selection:
                    print("The local Ollama service or model is unavailable.")
            if available:
                print("Local AI: "+r["file_name"],flush=True)
                tip = request_care_suggestions(data)
                if tip:
                    cache[key] = tip
                elif selection:
                    print("The local AI response was invalid.")
        if tip:
            r["care"] = tip


def twin_leaf_mesh(leaf, extent):
    "Build a two-dimensional section for each leaf in shared canopy coordinates."
    contours = []
    for ring in leaf.get("rings") or ():
        try:
            p = np.asarray(ring,dtype=np.float32)
            if p.ndim==2 and p.shape[1]==2 and len(p)>=3 and np.isfinite(p).all():
                contours.append(p)
        except (ValueError,TypeError):
            continue
    if not contours:
        return None
    p = max(contours,key=cv2.contourArea)/extent
    mom = cv2.moments(p)
    if mom['m00']<=1e-11:
        return None
    centre = np.array([mom['m10'],mom['m01']])/mom['m00']
    cov = np.array([[mom['mu20'],mom['mu11']],[mom['mu11'],mom['mu02']]])/mom['m00']
    eigenvalues, axis_pair = np.linalg.eigh(cov)
    primary_axis = axis_pair[:,-1]
    # The direction generally points from the centre of the canopy to the leaf tip.
    direction = centre-np.array([0.,0. if TWIN_PHOTO_VIEW=="top" else .16])
    if eigenvalues[1]<1.2*eigenvalues[0] and np.linalg.norm(direction)>.08:
        primary_axis = direction/np.linalg.norm(direction)
    if np.dot(primary_axis,direction)<0:
        primary_axis = -primary_axis
    transverse = np.array([-primary_axis[1],primary_axis[0]])
    longitudinal = (p-centre)@primary_axis
    side = (p-centre)@transverse
    nearest = np.roll(longitudinal,-1)
    qs = np.roll(side,-1)
    minimum,maximum = float(longitudinal.min()),float(longitudinal.max())
    if maximum-minimum<1e-5:
        return None
    def cross_section(position):
        e = (np.minimum(longitudinal,nearest)<=position)&(position<np.maximum(longitudinal,nearest))
        v = np.sort(side[e]+(qs[e]-side[e])*(position-longitudinal[e])/(nearest[e]-longitudinal[e]))
        if not len(v):
            i = int(np.argmin(abs(longitudinal-position)))
            return float(side[i]),float(side[i])
        return float(v[0]),float(v[-1])
    # Downweight thin protrusions such as remnants of stems when estimating length.
    sampling_grid = np.linspace(minimum,maximum,66)
    cross_sections = [cross_section(float(v)) for v in (sampling_grid[1:]+sampling_grid[:-1])/2]
    cum = np.cumsum([max(0.,hi-lo) for lo,hi in cross_sections])
    if cum[-1]>0:
        a,b = np.searchsorted(cum,[.017*cum[-1],.983*cum[-1]])
        minimum,maximum = float(sampling_grid[a]),float(sampling_grid[min(b+1,len(sampling_grid)-1)])
    centre = centre+(minimum+maximum)*.5*primary_axis
    profile = []
    for i in range(15):
        u = i/14
        t = minimum+(maximum-minimum)*min(.99999,max(.00001,u))
        lo,hi = cross_section(t)
        if i in (0,14):
            lo = hi = (lo+hi)*.5
        profile.append([round(lo,6),round(hi,6)])
    rgb = leaf.get("rgb")
    if not isinstance(rgb,(list,tuple)) or len(rgb)!=3 or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in rgb):
        rgb = [75,118,48]
    smoothed = [profile[0]]+[
        [round(.18*a+.64*b+.18*c,6) for a,b,c in zip(before,current_time,after)]
        for before,current_time,after in zip(profile,profile[1:],profile[2:])]+[profile[-1]]
    return {"center":centre.round(6).tolist(),"axis":primary_axis.round(6).tolist(),
            "length":round(maximum-minimum,6),"profile":smoothed,
            "rgb":[round(min(255,max(0,v))) for v in rgb]}


def twin_view_data(rows, output_dir=None, care_selection=None):
    "Send the latest photo's contours and any verified rate to the viewer."
    if care_selection is not None:
        # Care suggestions are available through the explicit CLI action only.
        care_suggestions = [{"file_name": z["file_name"], "captured_at": z.get("captured_at"),
                   "usable": bool(z.get("usable")), "leaf_pixels": z.get("plant_pixels"),
                   "health_score": z.get("health_score"), "health_status": z.get("health_status"),
                   "yellow_fraction_pct": z.get("yellow_fraction_pct"), "brown_fraction_pct": z.get("brown_fraction_pct"),
                   "quality_flags": z.get("quality_flags")} for z in rows]
        attach_care_suggestions(care_suggestions, output_dir, care_selection)
        for r in care_suggestions:
            if r.get("care"):
                print(r["file_name"]+": "+r["care"]["finding"])
                for tip in r["care"]["steps"]:
                    print("- "+tip)
    if not rows:
        return {"latest":None,"rate":None,"viewer_version":TWIN_3D_VERSION}
    z = max(enumerate(rows), key=lambda pair: (
        parse_saved_time(pair[1].get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc), pair[0]))[1]
    info = z.get("_historical_record",{}).get("analysis",{}) if z.get("_historical_record") else {}
    geo = z.get("_leaf_geometry") or info.get("leaf_geometry")
    extent = geo.get("extent") if isinstance(geo,dict) else None
    records = geo.get("leaves") if isinstance(geo,dict) else None
    leavedata = []
    if (isinstance(extent,(int,float)) and math.isfinite(extent) and 0<extent<=1
            and isinstance(records,list) and len(records)<=TWIN_MAX_LEAVES and z.get("usable")):
        for leaf in records:
            image_shape = twin_leaf_mesh(leaf,extent) if isinstance(leaf,dict) else None
            if image_shape is not None:
                leavedata.append(image_shape)
    manual = bool(leavedata and geo.get("method")=="manual" and len(leavedata)==geo.get("count"))
    if not manual:
        leavedata.sort(key=lambda b:(round(b['center'][1],2),b['center'][0]))
    rate = z.get("growth_rate_pct_per_day")
    elapsed_hours = z.get("growth_interval_hours")
    rate = rate if (leavedata and elapsed_hours is not None and elapsed_hours>=12
                    and rate is not None and -50<=rate<=100) else None
    return make_json_safe({"latest":{"file_name":z["file_name"],"captured_at":z.get("captured_at"),
                                  "leaves":leavedata,"count_estimated":not manual,
                                  "view":"top" if TWIN_PHOTO_VIEW=="top" else "side"},
                        "rate":rate,"viewer_version":TWIN_3D_VERSION})


def twin_view_from_json(source, output_dir, care_selection=None):
    "Refresh viewer data while preserving the saved model state and forecasts."
    source = Path(source).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    directory_path = viewer_directories(output_dir)[0]
    target = directory_path/TWIN_JSON_FILE
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    model = (isinstance(data, dict) and "forecast" in data and "state" in data
              and isinstance(data["state"], (dict, type(None))))
    viewer = data.get("viewer") if model else None
    if isinstance(data, list) or (isinstance(data, dict) and isinstance(data.get("image"), dict)):
        records = data if isinstance(data, list) else [data]
    elif model:
        base = source.parent.parent if source.parent.name == "digital_twin" else source.parent
        file_path = next((p for p in (base/"results"/"results.json", base/"results.json") if p.is_file()), None)
        if isinstance(viewer, dict) and viewer.get("viewer_version") == TWIN_3D_VERSION and not care_selection:
            if source == target:
                return target
            records = None
        else:
            records = json.loads(file_path.read_text(encoding="utf-8-sig")) if file_path is not None else []
            if not isinstance(records, list):
                raise ValueError("results.json must contain a list of image records.")
    else:
        raise ValueError("Choose results.json or digital_twin.json.")

    if records is not None:
        rows = [prepare_historical_row(historical_row(s)) for s in records]
        viewer = twin_view_data(rows, directory_path, care_selection)
    with lock_results(output_dir):
        existing_file = target if target.exists() else output_dir/TWIN_JSON_FILE
        if existing_file.exists():
            prior = json.loads(existing_file.read_text(encoding="utf-8-sig"))
        elif model:
            prior = data
        else:
            prior = {"version": TWIN_VERSION, "status": "viewer_data_only",
                       "state": None, "forecast": None, "forecast_history": []}
        if not isinstance(prior, dict) or not isinstance(prior.get("forecast_history"), list):
            raise ValueError("Could not safely read the existing digital twin JSON. It was kept.")
        prior["viewer"] = viewer
        save_twin(prior, directory_path)
    return target


def open_twin_view(output_dir):
    open_browser_view(output_dir, "digital_twin", "Digital twin")


def update_twin_model(rows, history, independent_images, directory_path):
    twin = digital_twin(rows, history, independent_images)
    twin["viewer"] = twin_view_data(rows)
    save_twin(twin, directory_path)
    status_label = {
        "too_few_comparable_photos": "Too few comparable photos for a forecast",
        "camera_movement_too_large_for_projection": "Camera movement is too large for a forecast",
        "historical_projection_stale_data": "Historical projection from older photos",
    }.get(twin["status"], twin["status"].replace("_", " ").capitalize())
    print(f"Digital twin: {status_label} | {twin['training']['points']} comparable photos")
    if twin.get("forecast"):
        p = twin["forecast"]
        print(f"  {p['target_at']}: {p['predicted_px']:.0f} leaf pixels ({p['model']}; provisional)")
    else:
        print(f"  A forecast requires at least {TWIN_MIN_OBSERVATIONS} comparable photos over {TWIN_MIN_SPAN_HOURS} hours. See digital_twin.json.")


def import_leaf_labels(photo, label, output_dir):
    "Bind a leaf label image to its exact original photograph."
    image_bytes = photo.read_bytes()
    label_raw = label.read_bytes()
    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    lab = cv2.imdecode(np.frombuffer(label_raw, np.uint8), cv2.IMREAD_UNCHANGED)
    if (label.suffix.lower() != ".png" or image is None or lab is None or lab.ndim != 2
            or lab.shape != image.shape[:2] or not np.any(lab)
            or np.count_nonzero(np.bincount(lab.ravel())[1:]) > TWIN_MAX_LEAVES):
        raise ValueError("Provide a non-empty greyscale PNG matching the original dimensions, with at most 200 leaf IDs.")
    target = Path(output_dir)/"leaf_labels"
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target) as tmp:
        file_handle = Path(tmp)/"labels.png"
        file_handle.write_bytes(label_raw)
        file_handle.replace(target/(hashlib.sha256(image_bytes).hexdigest()+".png"))


def open_digital_twin(source=None, output_dir=None, no_browser=False, run_care_ai=None):
    "Read saved data and optionally open the browser viewer."
    try:
        if source:
            source = Path(source).expanduser().resolve()
            base = source.parent
            if base.name in ("digital_twin", "digital twin"):
                base = base.parent
                if (base/"results").is_dir():
                    base /= "results"
            target = Path(output_dir or base).expanduser().resolve()
        else:
            target = Path(output_dir or default_results_dir()).expanduser().resolve()
            result = target/"results.json"
            twin_data = viewer_directories(target)[0]/TWIN_JSON_FILE
            source = result
            if twin_data.is_file() and (not result.is_file()
                    or twin_data.stat().st_mtime_ns >= result.stat().st_mtime_ns):
                saved = json.loads(twin_data.read_text(encoding="utf-8-sig"))
                if (not result.is_file() or isinstance(saved, dict) and
                        isinstance(saved.get("viewer"), dict) and
                        saved["viewer"].get("viewer_version") == TWIN_3D_VERSION):
                    source = twin_data
            elif not result.is_file() and (target/TWIN_JSON_FILE).is_file():
                source = target/TWIN_JSON_FILE
        if not source.is_file():
            candidates = [target/"ergebnis.json", target.parent/"auswertung"/"ergebnis.json",
                          target.parent/"digital twin"/TWIN_JSON_FILE]
            source = next((path for path in candidates if path.is_file()), source)
        if not source.is_file():
            raise ValueError("No saved JSON data. Run python computer_vision_pipeline.py images first.")
        data = twin_view_from_json(source, target, run_care_ai)
        if no_browser:
            print("3D data:", data)
        elif not run_care_ai:
            open_twin_view(target)
    except (OSError, ValueError, TypeError) as error:
        print("Could not open the digital twin:", error)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", dest="output_dir", type=Path, help="Saved results directory")
    parser.add_argument("--no-browser", dest="no_browser", action="store_true",
                        help="Update JSON data without opening a browser")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--from-json", dest="source", type=Path, metavar="JSON",
                        help="Read results.json or digital_twin.json")
    action.add_argument("--mark-leaves", dest="mark", type=Path, metavar="PHOTO",
                        help="Click one point per visible leaf")
    action.add_argument("--leaf-labels", dest="labels", nargs=2, type=Path,
                        metavar=("PHOTO", "LABEL_PNG"), help="Import a leaf label image")
    action.add_argument("--care-ai", dest="care", metavar="PHOTO",
                        help="Request optional care suggestions through the locally installed Ollama model")
    parser.add_argument("--independent-images", dest="independent", action="store_true",
                        help="With --mark-leaves, use the original image without lens correction")
    args = parser.parse_args(argv)
    if args.independent and not args.mark:
        parser.error("--independent-images applies to --mark-leaves.")
    if args.mark or args.labels:
        photo = Path(args.mark or args.labels[0]).expanduser().resolve()
        target = Path(args.output_dir or photo.parent.parent/"results").expanduser().resolve()
        try:
            with lock_results(target):
                if args.mark:
                    count = mark_leaves(photo, target, args.independent)
                    if count is not None:
                        print(f"Saved {count} leaf markings.")
                else:
                    import_leaf_labels(photo, args.labels[1].expanduser().resolve(), target)
                    print("Leaf labels saved.")
        except (OSError, ValueError, cv2.error) as error:
            print("Could not save leaf annotations:", error)
            return 1
        return 0
    if args.care:
        target = args.output_dir or default_results_dir()
        return open_digital_twin(target/"results.json", target, args.no_browser, args.care)
    return open_digital_twin(args.source, args.output_dir, args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
