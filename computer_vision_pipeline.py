"""A-M2 · Computer vision: leaf masks, measurements, exports, and charts."""

import argparse
import contextlib
import copy
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


PROJECT_DIR = Path(__file__).resolve().parent


# Browser viewer assets
TWIN_JSON_FILE = "digital_twin.json"
HEALTH_JSON_FILE = "plant_health.json"
CHART_MANIFEST_FILE = "charts.json"
CHART_FILES = ("01_leaf_area.png", "02_growth_rate.png", "03_leaf_color.png",
                 "04_plant_health.png", "05_health_subscores.png")
WEB_VIEWS = {"digital_twin": "digital_twin_3d", "plant_health": "plant_health",
                 "charts": "charts"}
WEB_CONTENT_TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
             "js": "text/javascript; charset=utf-8", "json": "application/json",
             "png": "image/png"}


def viewer_directories(output_dir):
    "For the default layout, place dashboard data beside the results directory."
    output_dir = Path(output_dir)
    base = output_dir.parent if output_dir.name.casefold() == "results" else output_dir
    return base/"digital_twin", base/"plant_health"


def chart_directory(output_dir):
    return viewer_directories(output_dir)[0].parent/"charts"


def serve_views(output_dir, ready_path):
    "Serve the browser views on this computer only."
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    twin, health_dir = viewer_directories(output_dir)
    plot_charts = chart_directory(output_dir)
    routes = {f"/{directory_path}/{filename_stem}.{end}": (PROJECT_DIR/directory_path/f"{filename_stem}.{end}", WEB_CONTENT_TYPES[end])
            for directory_path, filename_stem in WEB_VIEWS.items() for end in ("html", "css", "js")}
    for directory_path, name in ((twin, TWIN_JSON_FILE), (health_dir, HEALTH_JSON_FILE),
                         (plot_charts, CHART_MANIFEST_FILE), *((plot_charts, name) for name in CHART_FILES)):
        routes[f"/{directory_path.name}/{name}"] = (directory_path/name, WEB_CONTENT_TYPES[name.rsplit(".", 1)[1]])
    last_request_time = time.monotonic()

    class ViewerRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self._send_asset(header=False)

        def do_HEAD(self):
            self._send_asset(header=True)

        def _send_asset(self, header):
            nonlocal last_request_time
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(403)
                return
            try:
                file_path = unquote(urlsplit(self.path).path)
            except ValueError:
                self.send_error(400)
                return
            if file_path not in routes:
                self.send_error(404)
                return
            last_request_time = time.monotonic()
            file_handle, content_type = routes[file_path]
            try:
                data = file_handle.read_bytes()
            except OSError:
                self.send_error(404)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if not header:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    with ThreadingHTTPServer(("127.0.0.1", 0), ViewerRequestHandler) as server:
        server.timeout = 1
        temp = ready_path.with_suffix(".tmp")
        temp.write_text(str(server.server_port), encoding="ascii")
        temp.replace(ready_path)
        while time.monotonic() - last_request_time < 15 * 60:
            server.handle_request()


def open_browser_view(output_dir, directory_path, title):
    filename_stem = WEB_VIEWS[directory_path]
    source = PROJECT_DIR/directory_path
    files_to_publish = [f"{filename_stem}.{end}" for end in ("html", "css", "js")]
    missing = [name for name in files_to_publish if not (source/name).is_file()]
    if missing:
        raise FileNotFoundError(f"Place {', '.join(missing)} in {source}.")
    options = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                else {"start_new_session": True})
    with tempfile.TemporaryDirectory(prefix="biobox-browser-") as tmp:
        ready_file = Path(tmp)/"port"
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--_viewer-server",
                                   str(Path(output_dir).expanduser().resolve()), str(ready_file)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **options)
        deadline = time.monotonic() + 5
        while not ready_file.is_file() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.04)
        if not ready_file.is_file():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise OSError("Could not start the local browser server.")
        port = int(ready_file.read_text(encoding="ascii"))
    server_url = f"http://127.0.0.1:{port}/{quote(directory_path)}/{filename_stem}.html"
    print(f"{title}: {server_url}")
    if not webbrowser.open(server_url):
        print("Open this URL in your browser.")


# The viewer server uses only the Python standard library.
if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--_viewer-server":
    serve_views(Path(sys.argv[2]), Path(sys.argv[3]))
    raise SystemExit(0)

import cv2
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

def check_installation():
    """Explain which replacement files are needed if two editions were mixed."""
    names = ("image_capture.py", "health_assessment.py", "digital_twin.py")
    incompatible = [name for name in names if not (PROJECT_DIR/name).is_file()
                    or not re.search(r"(?m)^ENGLISH_LAYOUT_VERSION\s*=\s*2\s*$",
                                     (PROJECT_DIR/name).read_text(encoding="utf-8-sig"))]
    if incompatible:
        raise SystemExit("Install the four English Python files together in the project root. "
                         "Missing or outdated: " + ", ".join(incompatible))


check_installation()
from image_capture import (
    IMAGES_DIR, calibration_file, lens_image_size, capture_time, load_capture_times,
    parse_saved_time, iso, is_camera_photo, undistort_image, find_images,
    main as capture_cli,
)
ENGLISH_LAYOUT_VERSION = 2

# Share this module between direct execution and the other milestones.
if __name__ == "__main__":
    sys.modules["computer_vision_pipeline"] = sys.modules[__name__]


# Plant series, leaf mask and physical scale
DEVICE_ID = None  # Set this only when the device has been assigned an actual platform ID.
SERIES_ID = "plant-01"
MANUAL_MM_PER_PIXEL = None  # Use a verified scale at the height of the leaves.
CAMERA_HEIGHT_MM = None
LEAF_HEIGHT_MM = None
MARKER_HEIGHT_MM = 0.0
MARKER_MM = 40.0
NORMALISED_ROI = None  # Optional: (left, top, right, bottom), each from 0 to 1.
PROCESSING_WIDTH = 960
CHROMA_MIN = 4            # Minimum CIELAB a* distance from neutral grey.
RATE_MIN_MINUTES = 30    # Minimum interval; daily rates can fluctuate over short intervals.
RATE_STABLE_HOURS = 12  # Prefer a longer interval when available.
ANALYSIS_VERSION = "4.13.0"
CSV_UNAVAILABLE = "Unavailable"
OBSOLETE_TWIN_CHART = "06_digital_twin.png"  # Remove only this obsolete generated chart when migrating older outputs.

# Changes to a milestone change the fingerprint recorded in results.json.
PIPELINE_SHA256 = hashlib.sha256(b"\0".join(
    Path(__file__).with_name(name).read_bytes()
    for name in ("image_capture.py", "computer_vision_pipeline.py",
                 "health_assessment.py", "digital_twin.py")
)).hexdigest()


# CSV columns and JSON field mappings
COLUMNS = [
    "file_name", "captured_at", "capture_time_source", "hours_since_start", "plant_pixels", "leaf_coverage_pct", "visible_pixel_change_per_day", "pixel_reference_file",
    "leaf_area_cm2", "diameter_mm", "compactness",
    "growth_rate_cm2_per_day", "growth_rate_pct_per_day", "growth_reference_file", "growth_interval_hours",
    "mean_r", "mean_g", "mean_b", "color_hex", "mean_hue", "mean_saturation",
    "greenness_index", "yellow_fraction_pct", "brown_fraction_pct", "mm_per_px",
    "scale_source", "sharpness", "noise", "image_brightness",
    "overexposed_pct", "largest_component_pct", "quality_flags", "usable", "missing_values",
    "pipeline_version", "scoring_version", "health_score", "health_score_raw", "health_category",
    "health_status", "health_trend_24h", "health_warnings", "view_number", "health_reference_file",
    "score_green", "score_yellow", "score_brown", "score_saturation", "score_hue",
    "leaf_diameter_px", "visible_leaf_count", "visible_leaf_count_method",
]
ROUNDING = {"leaf_diameter_px": 1, "hours_since_start": 4, "leaf_coverage_pct": 3, "visible_pixel_change_per_day": 1, "leaf_area_cm2": 2, "diameter_mm": 1,
           "compactness": 4, "growth_rate_cm2_per_day": 3, "growth_rate_pct_per_day": 3, "growth_interval_hours": 3,
           "mean_r": 1, "mean_g": 1, "mean_b": 1, "mean_hue": 1, "mean_saturation": 1,
           "greenness_index": 4, "yellow_fraction_pct": 2, "brown_fraction_pct": 2,
           "mm_per_px": 6, "sharpness": 1, "noise": 2, "image_brightness": 1,
           "overexposed_pct": 2, "largest_component_pct": 1}
ROUNDING.update({k: 1 for k in COLUMNS if k.startswith("score_") or k in
                ("health_score", "health_score_raw", "health_trend_24h")})
API_MEASUREMENT_FIELDS = {
    "plant_pixels": "plant_pixels", "leaf_area_cm2": "leaf_area_cm2",
    "diameter_mm": "diameter_mm", "compactness": "compactness",
    "growth_rate_cm2_per_day": "growth_rate_cm2_per_day",
    "growth_rate_pct_per_day": "growth_rate_pct_per_day",
    "mean_r": "mean_r", "mean_g": "mean_g", "mean_b": "mean_b",
    "mean_hue": "mean_hue", "mean_saturation": "mean_saturation",
    "greenness_index": "greenness_index", "yellow_fraction_pct": "yellow_fraction_pct",
    "brown_fraction_pct": "brown_fraction_pct", "mm_per_px": "mm_per_px",
    "scale_source": "scale_source", "sharpness": "sharpness",
    "noise": "noise", "image_brightness": "image_brightness",
    "largest_component_pct": "largest_component_pct", "color_hex": "color_hex",
    "pipeline_version": "pipeline_version",
    "overexposed_pct": "overexposed_pct", "quality_flags": "quality_flags",
    "usable": "usable",
}
API_HEALTH_FIELDS = {
    "health_status": "health_status",
    "scoring_version": "scoring_version", "health_score": "health_score",
    "health_score_raw": "health_score_raw", "health_category": "health_category",
    "health_trend_24h": "health_trend_24h", "health_warnings": "health_warnings",
    "score_green": "score_green", "score_yellow": "score_yellow",
    "score_brown": "score_brown", "score_saturation": "score_saturation",
    "score_hue": "score_hue",
}


# Legacy labels are accepted when reading older exports. New exports use English.
LEGACY_CSV_FIELDS = {
    "ansicht": "view_number",
    "auffaelligkeit": "quality_flags",
    "bild": "file_name",
    "bildhelligkeit": "image_brightness",
    "blattanteil_im_bild_pct": "leaf_coverage_pct",
    "blattflaeche_cm2": "leaf_area_cm2",
    "blattpixel_aenderung_pro_tag": "visible_pixel_change_per_day",
    "blattzaehlung_quelle": "visible_leaf_count_method",
    "brauchbar": "usable",
    "braunanteil_pct": "brown_fraction_pct",
    "durchmesser_mm": "diameter_mm",
    "durchmesser_px": "leaf_diameter_px",
    "farbe_hex": "color_hex",
    "fehlende_werte": "missing_values",
    "gelbanteil_pct": "yellow_fraction_pct",
    "gesundheit": "health_score",
    "gesundheit_kategorie": "health_category",
    "gesundheit_referenzfoto": "health_reference_file",
    "gesundheit_roh": "health_score_raw",
    "gesundheit_status": "health_status",
    "gesundheit_trend_24h": "health_trend_24h",
    "gesundheitswarnung": "health_warnings",
    "groesste_komponente_pct": "largest_component_pct",
    "gruenindex": "greenness_index",
    "kompaktheit": "compactness",
    "massstab_quelle": "scale_source",
    "mittel_b": "mean_b",
    "mittel_g": "mean_g",
    "mittel_h": "mean_hue",
    "mittel_r": "mean_r",
    "mittel_s": "mean_saturation",
    "mm_pro_pixel": "mm_per_px",
    "pflanzen_pixel": "plant_pixels",
    "pixel_vergleichsfoto": "pixel_reference_file",
    "rauschen": "noise",
    "schaerfe": "sharpness",
    "score_braun": "score_brown",
    "score_farbton": "score_hue",
    "score_gelb": "score_yellow",
    "score_gruen": "score_green",
    "score_saettigung": "score_saturation",
    "sichtbare_blaetter": "visible_leaf_count",
    "stunden_seit_start": "hours_since_start",
    "ueberbelichtet_pct": "overexposed_pct",
    "wachstum_abstand_stunden": "growth_interval_hours",
    "wachstum_vergleichsfoto": "growth_reference_file",
    "wachstumsrate_cm2_pro_tag": "growth_rate_cm2_per_day",
    "wachstumsrate_pct_pro_tag": "growth_rate_pct_per_day",
    "zeitquelle": "capture_time_source",
}

LEGACY_VALUE_CODES = {
    "alte-grafiken": "legacy-charts",
    "analyse_version": "analysis_version",
    "analysefehler": "analysis_failed",
    "ansicht_geaendert": "view_changed",
    "arbeitsbreite": "processing_width",
    "aruco_hoehenkorrigiert": "aruco_height_corrected",
    "auffaellig": "significant_change",
    "aufloesung_geaendert": "resolution_changed",
    "aufnahme_vor_referenz": "photo_before_reference",
    "aufnahmezeit_fehlt": "capture_time_missing",
    "aufnahmezeit_liegt_in_der_zukunft": "capture_time_in_future",
    "ausgabe": "output_dir",
    "automatisch": "automatic",
    "beobachten": "monitor",
    "berechnet": "calculated",
    "berechnet_gemeinsamer_ausschnitt": "calculated_shared_frame",
    "berechnet_gemeinsamer_ausschnitt_kurz": "calculated_shared_frame_short_interval",
    "berechnet_historisch": "calculated_historical",
    "berechnet_kurzer_abstand": "calculated_short_interval",
    "beschnitten": "clipped",
    "beschnittener_bildausschnitt_verschoben": "clipped_frame_shifted",
    "bild_nicht_auswertbar": "image_not_measurable",
    "bild_nicht_brauchbar": "image_not_usable",
    "bild_original": "original_image",
    "bildbreite": "image_width",
    "bildgroesse": "image_size",
    "bildgroesse_nicht_gespeichert": "image_size_not_recorded",
    "bildhoehe": "image_height",
    "bildqualitaet_nicht_ausreichend": "image_quality_too_low",
    "biobox-analyse-": "biobox-analysis-",
    "blatt_am_bildrand": "leaf_at_image_edge",
    "blattebene_unbekannt": "leaf_plane_unknown",
    "blattfarbverteilung": "leaf_colour_distribution",
    "blattflaeche_ueberbelichtet": "leaf_area_overexposed",
    "blattmaske_nicht_berechenbar": "leaf_mask_unavailable",
    "blattpixel_ausgeschlossen_pct": "excluded_leaf_pct",
    "blattpixel_ungueltig": "invalid_leaf_pixel_count",
    "blattverteilung_chromatik": "leaf_distribution_chromatic",
    "blattverteilung_normiert": "leaf_distribution_normalised",
    "braunanteil_gestiegen": "brown_fraction_increased",
    "brauntoene_ohne_bestaetigte_helligkeit_nicht_bewertet": "brown_requires_verified_lighting",
    "chromatik_teilflaeche": "chromatic_region",
    "chromatisch_gepruefte_blattflaeche_pct": "verified_color_region_pct",
    "cron_start_beim_boot": "cron_enabled_at_boot",
    "datei_nicht_lesbar": "image_unreadable",
    "einzelbilder": "independent_images",
    "einzelbilder_keine_gemeinsame_referenz": "independent_images_no_reference",
    "einzelbilder_ohne_gemeinsamen_massstab": "independent_images_no_shared_scale",
    "einzelbilder_ohne_gemeinsamen_twin": "independent_images_no_shared_twin",
    "einzelbilder_ohne_wachstumsreihe": "independent_images_no_growth_series",
    "exif_mit_offset": "exif_with_offset",
    "externer_import_noch_keinem_serverpfad_zugeordnet": "imported_photo_has_no_server_path",
    "farbe_und_struktur": "colour_and_structure",
    "farbton": "hue",
    "farbveraenderung": "leaf_colour_changed",
    "farbverhaeltnis_teilflaeche": "colour_ratio_verified_regions",
    "flaechensprung_pruefen": "check_area_jump",
    "freigegeben": "reviewed_reference",
    "gelbanteil_gestiegen": "yellow_fraction_increased",
    "gemeinsame_blattflaeche_pct": "common_leaf_pct",
    "geometrie_ungueltig": "invalid_geometry",
    "geraet_noch_nicht_zugeordnet": "device_not_assigned",
    "gesundheit_ueber_blattfarbverteilung": "compared_leaf_colour_distribution",
    "gut": "good",
    "hintergrund_anteil_pct": "background_fraction_pct",
    "hintergrund_fehler": "background_error",
    "historie": "history",
    "historische_projektion_daten_veraltet": "historical_projection_stale_data",
    "historischer_methodenvergleich": "historical_method_comparison",
    "historischer_vergleich_nicht_gespeichert": "historical_comparison_not_saved",
    "historischer_wert_nicht_gespeichert": "historical_value_not_recorded",
    "identisch": "identical",
    "kamera_fuer_prognose_nicht_fest_genug": "camera_movement_too_large_for_projection",
    "kameraansicht_nicht_bestaetigt": "camera_view_unverified",
    "kameraansicht_nicht_vergleichbar": "camera_view_not_comparable",
    "kameraansicht_passt_nicht_zum_linealbild": "camera_view_differs_from_ruler_photo",
    "kameraausschnitt_nicht_vergleichbar": "image_crop_not_comparable",
    "kamerageometrie_ungueltig": "invalid_camera_geometry",
    "kameralage_nicht_verifiziert": "camera_position_unverified",
    "kein_frueheres_brauchbares_bild_gleicher_aufloesung_mit_mindestabstand": "no_suitable_earlier_photo",
    "kein_gemeinsamer_massstab_fuer_beide_aufnahmen": "no_shared_scale_for_pair",
    "kein_gueltiger_messwert": "no_valid_measurement",
    "kein_gueltiger_score_vor_24_stunden_plusminus_2h": "no_comparable_score_22_to_26_hours_earlier",
    "kein_verifizierter_massstab_in_blattebene": "no_verified_scale_in_leaf_plane",
    "keine_aufnahmezeit": "capture_time_unknown",
    "keine_auswertbare_blattmaske": "no_usable_leaf_mask",
    "keine_auswertbaren_blattkonturen": "no_usable_leaf_contours",
    "keine_blattmaske": "no_leaf_mask",
    "keine_daten": "no_data",
    "keine_fruehere_vergleichsaufnahme": "no_earlier_comparable_photo",
    "keine_gueltige_vergleichsaufnahme": "no_valid_comparable_photo",
    "keine_pruefsumme_gespeichert": "checksum_not_recorded",
    "keine_verlaessliche_aufnahmezeit": "no_reliable_capture_time",
    "kritisch": "critical",
    "kurve": "curve",
    "letzter_messwert_im_ruecktest_mindestens_gleich_gut": "baseline_at_least_as_accurate_in_backtest",
    "licht_hintergrund_unzureichend": "insufficient_background_for_lighting",
    "lichtkorrektur_nicht_stabil": "unstable_lighting_correction",
    "lichtvergleich_nicht_moeglich": "lighting_not_comparable",
    "lichtvergleich_nicht_verifiziert": "unverified_lighting_comparison",
    "lichtvergleich_zu_wenig_blattgewebe": "too_little_leaf_tissue_for_lighting_comparison",
    "lineal_blattebene": "ruler_in_leaf_plane",
    "linearer_wert_ausserhalb_der_bildflaeche": "linear_projection_exceeds_image_bounds",
    "manuell": "manual",
    "manuell_blattebene": "manual_scale_in_leaf_plane",
    "marker_uneinheitlich": "marker_inconsistent",
    "marker_unvollstaendig": "marker_incomplete",
    "maske_deckt_fast_den_gesamten_bereich_ab": "mask_covers_almost_entire_frame",
    "maske_original": "original_mask",
    "messreihe_nicht_bestaetigt": "plant_series_unverified",
    "mittel_": "mean_",
    "neue_kameraansicht": "new_camera_view",
    "nicht_auswertbar": "unusable",
    "nicht_kalibriert": "not_calibrated",
    "nicht_lesbar": "unreadable",
    "nicht_vergleichbar": "not_comparable",
    "noch_zu_wenige_zukunftsvergleiche": "too_few_forecast_checks",
    "nur_browserdaten": "viewer_data_only",
    "nur_farbe": "colour_only",
    "nur_farbvergleich": "colour_comparison_only",
    "objektiv_einstellung_gegenueber_lineal_geaendert": "lens_settings_changed_since_ruler_photo",
    "pflanze-01": "plant-01",
    "prognose_vorlaeufig": "provisional_forecast",
    "pruefen": "review",
    "referenz": "reference",
    "referenzfoto_start_der_ansicht": "reference_photo_start_of_view",
    "saettigung": "saturation",
    "saettigung_veraendert": "saturation_changed",
    "sehr gut": "very_good",
    "sehr_gut": "very_good",
    "sichtbare_blattflaeche_gesunken": "visible_leaf_area_decreased",
    "starkes_rauschen": "high_image_noise",
    "unbekannt": "unknown",
    "unscharf": "blurred",
    "vorlaeufige_referenz": "provisional_reference",
    "vorlaeufiger_linearer_startwert": "provisional_linear_baseline",
    "wachstum_gemeinsamer_bildausschnitt": "growth_shared_frame",
    "wachstumsrate_kurzer_zeitabstand": "growth_rate_short_interval",
    "zeitabstand_unter_": "interval_under_",
    "zeitdatei": "timestamp_file",
    "zeitreihe_kuerzer_als_24_stunden": "series_shorter_than_24_hours",
    "zu_grosse_luecke_in_der_zeitreihe": "sampling_gap_too_large",
    "zu_wenig_bestaetigte_farbteilflaeche": "too_little_verified_colour_region",
    "zu_wenig_blattflaeche_fuer_verteilungsvergleich": "too_little_leaf_area_for_distribution",
    "zu_wenig_gemeinsame_sichtflaeche": "too_little_shared_frame",
    "zu_wenig_gemeinsames_blattgewebe": "too_little_shared_leaf_tissue",
    "zu_wenige_vergleichbare_aufnahmen": "too_few_comparable_photos",
}


def normalise_saved_code(value):
    """Translate recognised status tokens while leaving unknown values intact."""
    if not isinstance(value, str):
        return value
    def convert(token):
        code, separator, detail = token.partition(":")
        interval = re.fullmatch(r"zeitabstand_unter_(\d+)_minuten", code)
        if interval:
            return f"interval_under_{interval[1]}_minutes" + separator + detail
        return LEGACY_VALUE_CODES.get(code, code) + separator + detail
    return ";".join(convert(part) for part in value.split(";"))


def normalise_extra_columns(values):
    """Retain old custom fields without putting their original labels in the CSV header."""
    fields = {}
    reserved = set(COLUMNS)
    for key, value in values.items():
        if re.fullmatch(r"legacy_field_[a-z0-9_]+", key):
            label = key
        else:
            label = f"legacy_field_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"
        while label in reserved or label in fields:
            label += "_copy"
        fields[label] = value
    return fields


def normalise_record(record):
    """Keep image identity and numeric measurements while updating old labels."""
    record = copy.deepcopy(record)
    sections = {
        "image_measurements": ("scale_source", "quality_flags"),
        "health_assessment": ("health_status", "health_category", "health_warnings"),
        "analysis": ("health_status", "capture_time_source", "mask_source", "scale_status",
                     "health_comparison_mode", "growth_comparison_mode"),
    }
    for section, fields in sections.items():
        data = record.get(section, {})
        for field in fields:
            if field in data:
                data[field] = normalise_saved_code(data[field])
    analysis = record.get("analysis", {})
    if analysis.get("series_id") == "pflanze-01":
        analysis["series_id"] = "plant-01"
    missing = analysis.get("missing_values")
    if isinstance(missing, dict):
        analysis["missing_values"] = {LEGACY_CSV_FIELDS.get(k, k): normalise_saved_code(v)
                                      for k, v in missing.items()}
    lighting = analysis.get("illumination")
    if isinstance(lighting, dict) and "method" in lighting:
        lighting["method"] = normalise_saved_code(lighting["method"])
    geometry = analysis.get("leaf_geometry")
    if isinstance(geometry, dict) and isinstance(geometry.get("note"), str):
        note = geometry["note"]
        for old, new in (
            ("Bei verdeckten oder zusammenhängenden Blättern ist der Zählwert unsicher.",
             "The count is uncertain when leaves are hidden or overlap."),
            ("Blattanzahl manuell markiert; Grenzverläufe wurden geschätzt.",
             "The leaf count was marked manually; region boundaries were estimated."),
            ("Einige Teilflächen waren für eigene Konturen zu klein.",
             "Some regions were too small to supply separate contours."),
            ("Blattmarkierungen nicht übernommen:", "Leaf annotations could not be used:"),
        ):
            note = note.replace(old, new)
        geometry["note"] = note
    return record


# Image processing
def estimate_noise(image):
    """Estimate sensor noise using Immerkaer's method (1996), which is designed to be less sensitive to edges and leaf structure."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float64)
    core = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float64)
    h, w = grey.shape
    total_sum = np.abs(cv2.filter2D(grey, -1, core)[1:-1, 1:-1]).sum()
    return float(np.sqrt(np.pi / 2) * total_sum / (6 * (w - 2) * (h - 2)))


def add_flags(z, *flags):
    existing = list(filter(None, (z.get("quality_flags") or "").split(";")))
    z["quality_flags"] = ";".join(dict.fromkeys(existing + list(flags)))


def downscale(image):
    factor = min(1.0, PROCESSING_WIDTH / image.shape[1])
    return cv2.resize(image, (round(image.shape[1]*factor), round(image.shape[0]*factor)),
                      interpolation=cv2.INTER_AREA) if factor < 1 else image.copy()


def _ellipse_kernel(n):
    "Create an elliptical structuring element with odd dimensions."
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(n) | 1, int(n) | 1))


def filter_components(leaf_mask, minimum):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(leaf_mask, connectivity=8)
    retained = np.zeros(n, np.uint8)
    retained[1:] = (stats[1:, cv2.CC_STAT_AREA] >= minimum).astype(np.uint8)*255
    return retained[labels]


def background_is_fixed(image, ref_image, background):
    "Accept the identity transform only if edges agree across the frame."
    h,w = background.shape
    def edges(im):
        g = cv2.GaussianBlur(cv2.cvtColor(im,cv2.COLOR_BGR2GRAY),(5,5),0)
        return (cv2.Sobel(g,cv2.CV_32F,1,0),cv2.Sobel(g,cv2.CV_32F,0,1))
    ax,ay = edges(ref_image)
    bx,by = edges(image)
    a = np.hypot(ax,ay)
    b = np.hypot(bx,by)
    ok = []
    relevant = []
    for i in range(3):
        for j in range(3):
            y,x = slice(i*h//3,(i+1)*h//3),slice(j*w//3,(j+1)*w//3)
            m = (background[y,x]>0) & (a[y,x]>=16)
            if np.count_nonzero(m)<max(50,int(.008*m.size)):
                continue
            direction = (ax[y,x][m]*bx[y,x][m]+ay[y,x][m]*by[y,x][m]) / (
                np.maximum(1.,a[y,x][m]*b[y,x][m]))
            # Reject new or heavily shifted edges.
            # A single aligned edge does not establish a match.
            a_tile,b_tile = a[y,x][m],b[y,x][m]
            gain = float(np.median(b_tile/a_tile))
            residual = np.median(np.abs(b_tile-gain*a_tile))/max(1.,float(np.median(b_tile)))
            relevant.append((i,j))
            if .25<gain<4 and np.mean(direction>.94)>=.90 and residual<.20:
                ok.append((i,j))
    return (len(ok)>=3 and len(ok)>=.80*len(relevant)
            and len({i for i,_ in ok})>=2 and len({j for _,j in ok})>=2)


def align_scene(image, ref, details=None):
    """Estimate camera movement from background features and align the reference mask. Compensate for small shifts when comparing colours. Suppress area comparisons when the view changes too much."""
    if ref is None or image.shape != ref["file_name"].shape:
        return None, None, [] if ref is None else ["resolution_changed"]
    ref_image, reference_mask = ref["file_name"], ref["mask"]
    if np.array_equal(image,ref_image):
        if details is not None:
            details.update(scale=1.,rotation=0.,translation=0.,matrix=IDENTITY)
        return reference_mask.copy(),ref_image.copy(),[]
    orb = cv2.ORB_create(nfeatures=1800)
    background = 255-cv2.dilate(reference_mask, np.ones((19, 19), np.uint8))
    def check_view():
        if background_is_fixed(image,ref_image,background):
            if details is not None:
                details.update(scale=1.,rotation=0.,translation=0.,matrix=IDENTITY)
            return reference_mask.copy(),ref_image.copy(),[]
        return None,None,["camera_position_unverified"]
    k1, d1 = orb.detectAndCompute(cv2.cvtColor(ref_image, cv2.COLOR_BGR2GRAY), background)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)
    if d1 is None or d2 is None:
        return check_view()
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    good = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < .72*b.distance]
    if len(good) < 12:
        return check_view()
    src = np.float32([k1[m.queryIdx].pt for m in good])
    dst = np.float32([k2[m.trainIdx].pt for m in good])
    matrix, inlier = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if matrix is None or inlier is None or int(inlier.sum()) < 12 or float(inlier.mean()) < .45:
        return check_view()
    # Require features spread across the scene.
    # A corner or a single leaf cannot establish the camera position.
    points = src[inlier.ravel() > 0]
    if cv2.contourArea(cv2.convexHull(points)) < .025*image.shape[0]*image.shape[1]:
        return check_view()
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    angle = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    offset_px = float(np.linalg.norm(matrix[:, 2])) / max(image.shape[:2])
    # Avoid interpolating shifts below half a working pixel.
    # Such small changes can be feature matching noise.
    if abs(scale-1)<.0005 and angle<.03 and np.linalg.norm(matrix[:,2])<.5:
        matrix=np.array([[1.,0.,0.],[0.,1.,0.]])
        scale,angle,offset_px=1.,0.,0.
    if details is not None:
        details.update(scale=scale, rotation=angle, translation=offset_px, matrix=matrix)
    flags = ["view_changed"] if abs(scale-1) > .025 or angle > 3 or offset_px > .035 else []
    h, w = image.shape[:2]
    return (cv2.warpAffine(reference_mask, matrix, (w, h), flags=cv2.INTER_NEAREST),
            cv2.warpAffine(ref_image, matrix, (w, h)), flags)


def greenness(bgr):
    "Return CIELAB opponent colours: green-red (-a*) and blue-yellow (b*)."
    lab = cv2.cvtColor(cv2.bilateralFilter(bgr, 5, 32, 5), cv2.COLOR_BGR2LAB)
    return np.clip(128-lab[:, :, 1].astype(np.int16), 0, 127).astype(np.uint8), lab[:, :, 2].astype(np.int16)-128


def plant_roi(image_shape):
    "Apply the optional fixed region of interest in original image coordinates."
    h, w = image_shape
    if NORMALISED_ROI is None:
        return np.full(image_shape, 255, np.uint8)
    x0, y0, x1, y1 = NORMALISED_ROI
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("NORMALISED_ROI must contain left, top, right and bottom between 0 and 1.")
    roi = np.zeros(image_shape, np.uint8)
    roi[round(y0*h):round(y1*h), round(x0*w):round(x1*w)] = 255
    return roi


def broad_leaf_regions(leaf_mask):
    "Remove narrow stems while retaining short leaf tips connected to wide regions."
    if not np.any(leaf_mask):
        return leaf_mask
    radius = max(2.2, .0065*min(leaf_mask.shape))
    stroke_width = cv2.distanceTransform(leaf_mask, cv2.DIST_L2, 5)
    core = np.uint8(stroke_width >= radius)*255
    if not np.any(core):
        return np.zeros_like(leaf_mask)
    span_px = cv2.dilate(core, _ellipse_kernel(2*round(radius*2.15)+1))
    return cv2.bitwise_and(leaf_mask, span_px)


def segment_leaves(working_image, prior=None, prior_scene=None):
    "Find leaf cores and nearby boundary pixels before refining the original image."
    green, yellow = greenness(working_image)
    roi = plant_roi(green.shape)
    signal = np.max(working_image, axis=2) >= 23
    dark = cv2.cvtColor(working_image, cv2.COLOR_BGR2GRAY) < 43
    # Cyan hardware contains little yellow. Retain cool regions with strong green tones.
    # Use Otsu's method only to initialise the threshold.
    plant_colour = (((yellow >= 3) | ((yellow >= -4) & (green >= 19))) & signal
                     & (~dark | (green >= 16)) & (roi > 0))
    chroma = np.where(plant_colour, green, 0).astype(np.uint8)
    otsu, _ = cv2.threshold(chroma, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold_value = max(8, min(19, float(otsu)))
    core = np.uint8(chroma >= threshold_value)*255
    h, w = core.shape
    image_width = max(3, 2*round(.0035*min(h,w))+1)
    core = cv2.morphologyEx(core, cv2.MORPH_OPEN, _ellipse_kernel(image_width))
    core = filter_components(core, max(20, round(.00007*core.size)))
    near = cv2.dilate(core, _ellipse_kernel(5)) > 0
    weak = (green >= max(CHROMA_MIN, 10)) & (yellow >= -2) & signal & (~dark | (green >= 17))
    leaf_mask = np.uint8((core > 0) | (near & weak))*255

    if prior is not None and prior_scene is not None and prior.shape == leaf_mask.shape:
        # Keep warm pixels only within the previous leaf region
        # and next to tissue visible in the current photo.
        interior = cv2.erode(prior, _ellipse_kernel(image_width)) > 0
        previous_l = cv2.cvtColor(prior_scene, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.int16)
        current = cv2.cvtColor(working_image, cv2.COLOR_BGR2LAB)
        current_l = current[:, :, 0].astype(np.int16)
        current_a = current[:, :, 1].astype(np.int16)-128
        contact = cv2.dilate(core, _ellipse_kernel(2*round(.047*min(h,w))+1)) > 0
        warm = (yellow >= 12) & (current_a <= 30) & (current_l >= np.maximum(27, previous_l*.42))
        leaf_mask[interior & contact & warm] = 255
    leaf_mask = cv2.morphologyEx(leaf_mask, cv2.MORPH_CLOSE, _ellipse_kernel(3))
    leaf_mask = fill_holes(leaf_mask)
    leaf_mask = broad_leaf_regions(leaf_mask)
    return filter_components(cv2.bitwise_and(leaf_mask, roi), max(24, round(.00009*leaf_mask.size)))


def fill_holes(leaf_mask):
    "Fill only small holes fully enclosed by the mask."
    count_items, labels, stats, _ = cv2.connectedComponentsWithStats(255-leaf_mask, connectivity=8)
    retained = stats[:, cv2.CC_STAT_AREA] <= max(16, round(.00045*leaf_mask.size))
    retained[0] = False
    retained[np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]])] = False
    leaf_mask[retained[labels]] = 255
    return leaf_mask


def refine_mask(image, small_mask, prior_scene=None):
    "Use GrabCut to refine boundaries in a limited band of the original image."
    h, w = image.shape[:2]
    base = cv2.resize(small_mask, (w,h), interpolation=cv2.INTER_NEAREST)
    if not np.any(base):
        return base
    edge = max(3, round(.004*min(h,w)))
    x,y,b,hb = cv2.boundingRect(base)
    x0,y0,x1,y1 = max(0,x-edge-2),max(0,y-edge-2),min(w,x+b+edge+2),min(h,y+hb+edge+2)
    reduced = base[y0:y1,x0:x1]
    original = np.ascontiguousarray(image[y0:y1,x0:x1])
    exterior = cv2.dilate(reduced, _ellipse_kernel(2*edge+1))
    interior = cv2.erode(reduced, _ellipse_kernel(2*max(1,edge//2)+1))
    gc = np.full(reduced.shape, cv2.GC_BGD, np.uint8)
    gc[exterior > 0] = cv2.GC_PR_BGD
    gc[reduced > 0] = cv2.GC_PR_FGD
    gc[interior > 0] = cv2.GC_FGD
    # Prevent cool and weakly green hardware at the edge from joining the mask.
    green, yellow = greenness(original)
    cool = (yellow < -4) & (green < 19)
    dark = (cv2.cvtColor(original, cv2.COLOR_BGR2GRAY) < 43) & (green < 16)
    gc[((reduced == 0) & (cool | dark)) | ((yellow < -3) & (green < 16))] = cv2.GC_BGD
    fine = reduced.copy()
    if np.any(gc == cv2.GC_BGD) and np.any(gc == cv2.GC_FGD):
        try:
            cv2.setRNGSeed(0)
            cv2.grabCut(original, gc, None, np.zeros((1,65), np.float64),
                        np.zeros((1,65), np.float64), 1, cv2.GC_INIT_WITH_MASK)
            fine = np.uint8((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD))*255
        except cv2.error:
            # Fall back to the usable initial mask if the colour distribution degenerates.
            pass
    fine = broad_leaf_regions(fill_holes(fine))
    fine[(yellow < -3) & (green < 16)] = 0
    base[y0:y1,x0:x1] = fine
    base = cv2.bitwise_and(base, plant_roi((h,w)))
    return filter_components(base, max(48, round(.00009*base.size)))


def leaf_colour_metrics(image, leaf_mask):
    m = leaf_mask > 0
    if not np.any(m):
        return None
    rgb = image[:, :, ::-1].astype(np.float32)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    lab = cv2.cvtColor(image.astype(np.float32)/255, cv2.COLOR_BGR2LAB)
    r, g, b = [rgb[:, :, i][m] for i in range(3)]
    h, s, v = [hsv[:, :, i][m] for i in range(3)]
    chromatic = s > 18
    angle = 2*np.pi*h[chromatic]/180
    mean_hue = (math.atan2(float(np.mean(np.sin(angle))), float(np.mean(np.cos(angle)))) % (2*np.pi))*180/(2*np.pi) if len(angle) else None
    brown = (h < 28) & (s > 60) & (v < 165) & (r > g*1.02)
    yellow = (h >= 15) & (h < 38) & (s > 50) & ~brown
    # Use a continuous warm/brown indicator for comparisons over time.
    # A brightness threshold should not make a pixel appear
    # to recover suddenly from browning.
    warm_last = 100*float((np.clip((32-h)/15, 0, 1)*np.clip((s-35)/100, 0, 1)*
                          np.clip((235-v)/100, 0, 1)*(r > g*1.01)).mean())
    # Soft histogram bins avoid jumps in the score
    # when a small colour change crosses a bin boundary.
    hf, sf = h*24/180, s*12/256
    hb, sb = np.floor(hf).astype(int), np.floor(sf).astype(int)
    wh, ws = hf-hb, sf-sb
    hist = np.zeros((24, 12), np.float32)
    for dh, hw in [(0, 1-wh), (1, wh)]:
        for ds, sw in [(0, 1-ws), (1, ws)]:
            ind = ((hb+dh) % 24)*12+np.clip(sb+ds, 0, 11)
            hist += np.bincount(ind, weights=hw*sw, minlength=288).reshape(24, 12).astype(np.float32)
    # Hue is circular: red at 179 and red at 0 are adjacent.
    hist = .5*hist+.25*np.roll(hist, 1, axis=0)+.25*np.roll(hist, -1, axis=0)
    hist = cv2.GaussianBlur(hist, (3, 1), .65)
    hist = hist / max(float(hist.sum()), 1e-8)
    return {"mean_r": float(r.mean()), "mean_g": float(g.mean()), "mean_b": float(b.mean()),
            "mean_hue": mean_hue, "mean_saturation": float(s.mean()),
            "greenness_index": float((g/(r+g+b+1e-6)).mean()),
            "yellow_fraction_pct": 100*float(yellow.mean()), "brown_fraction_pct": 100*float(brown.mean()),
            "_hist": hist, "_lab": np.median(lab[m], axis=0), "_warm_severity": warm_last}


def scale_from_points(points, length_mm, image_width, image_height):
    "Divide the measured physical length by its distance in pixels."
    p = np.asarray(points, dtype=float).reshape(2, 2)
    if not np.isfinite(p).all() or not math.isfinite(length_mm) or length_mm <= 0:
        raise ValueError("Use finite coordinates and a positive reference length.")
    if np.any(p < 0) or np.any(p[:, 0] >= image_width) or np.any(p[:, 1] >= image_height):
        raise ValueError("The reference points lie outside the image.")
    pixel = float(np.linalg.norm(p[1]-p[0]))
    if pixel < 5:
        raise ValueError("The reference points must be at least 5 pixels apart.")
    return float(length_mm/pixel)


def set_ruler_scale(image_path, length_mm, output_dir, points=None):
    """Mark the ends of a known distance on the same plane as the leaves. Coordinates refer to the original image after lens correction, if applied. Use --points to supply original pixel coordinates without a window."""
    image_path = Path(image_path).resolve()
    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The scale photo could not be read.")
    lens_hash = None
    if calibration_file().exists():
        text = calibration_file().read_bytes()
        d = json.loads(text)
        image = undistort_image(image,d)
        lens_hash = hashlib.sha256(text).hexdigest()
    h, w = image.shape[:2]
    if points is None:
        factor = min(1., 1300/w, 800/h)
        preview = cv2.resize(image, (round(w*factor), round(h*factor)))
        clicks = []
        title = "Click two ruler marks at leaf height | Enter: save | R: reset | Esc: cancel"
        def handle_click(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 2:
                clicks.append((x/factor, y/factor))
        try:
            cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
            cv2.setMouseCallback(title, handle_click)
            while True:
                panel = preview.copy()
                for x, y in clicks:
                    cv2.drawMarker(panel, (round(x*factor), round(y*factor)), (0, 0, 255), cv2.MARKER_CROSS, 18, 2)
                if len(clicks) == 2:
                    p1, p2 = [tuple(round(v*factor) for v in p) for p in clicks]
                    cv2.line(panel, p1, p2, (0, 0, 255), 2)
                cv2.imshow(title, panel)
                key_press = cv2.waitKey(30) & 255
                if key_press == 27 or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                    raise ValueError("Calibration cancelled. No scale was saved.")
                if key_press in (ord('r'), ord('R')):
                    clicks.clear()
                if key_press in (10, 13) and len(clicks) == 2:
                    points = clicks
                    break
        except cv2.error as error:
            raise ValueError("Could not open the calibration window. Install desktop OpenCV or use --points x1 y1 x2 y2.") from error
        finally:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
    value = scale_from_points(points, length_mm, w, h)
    working_image = downscale(image)
    leaf_mask = segment_leaves(working_image)
    ref = {"file_name": working_image, "mask": leaf_mask, "meta": {
        "kind": "ruler_scale", "version": 1, "mm_per_px": value,
        "reference_mm": float(length_mm), "points": np.asarray(points).reshape(2,2).tolist(),
        "file_name": image_path.name, "image_width": w, "image_height": h,
        "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "lens_hash": lens_hash, "plane": "leaf_plane"}}
    output_dir.mkdir(parents=True, exist_ok=True)
    save_reference(output_dir/"scale_reference.npz", ref)
    print(f"Measured scale: {value:.6f} mm/pixel -> {output_dir/'scale_reference.npz'}")
    print("The analysis uses this scale for matching camera views.")
    print("Recalibrate if the height of the camera or leaves changes.")
    return ref


def read_ruler_scale(file_path):
    if not file_path.exists():
        return None
    with np.load(file_path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        for old, new in (("mm_pro_pixel", "mm_per_px"), ("bildbreite", "image_width"),
                         ("bildhoehe", "image_height"), ("referenz_mm", "reference_mm"),
                         ("bild", "file_name"), ("punkte", "points")):
            if old in meta:
                meta.setdefault(new, meta.pop(old))
        value = meta.get("mm_per_px")
        if meta.get("kind") != "ruler_scale" or not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("The saved ruler scale is invalid.")
        image_key = "file_name" if "file_name" in data else "bild"
        mask_key = "mask" if "mask" in data else "maske"
        return {"meta": meta, "file_name": data[image_key].copy(), "mask": data[mask_key].copy()}


def measure_scale(image, manual, ruler=None):
    if manual is not None:
        return float(manual), "manual_scale_in_leaf_plane"
    if ruler is not None:
        lens_hash = hashlib.sha256(calibration_file().read_bytes()).hexdigest() if calibration_file().exists() else None
        if lens_hash != ruler["meta"].get("lens_hash"):
            return None, "lens_settings_changed_since_ruler_photo"
        working_image = downscale(image)
        details = {}
        if working_image.shape == ruler["file_name"].shape and np.array_equal(working_image, ruler["file_name"]):
            details["scale"] = 1.
            flags = []
        else:
            _, _, flags = align_scene(working_image, ruler, details)
        if flags or "scale" not in details:
            return None, "camera_view_differs_from_ruler_photo"
        factor = details["scale"]*image.shape[1]/ruler["meta"]["image_width"]
        return ruler["meta"]["mm_per_px"]/factor, "ruler_in_leaf_plane"
    if not hasattr(cv2, "aruco"):
        return None, "not_calibrated"
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector = cv2.aruco.ArucoDetector(dictionary)
    corners, ids, _ = detector.detectMarkers(image)
    if ids is None:
        return None, "not_calibrated"
    marker = {int(i): c.reshape(4, 2) for i, c in zip(ids.flatten(), corners) if int(i) in (0, 1, 2, 3)}
    if len(marker) != 4:
        return None, "marker_incomplete"
    edges = [np.linalg.norm(c-np.roll(c, -1, axis=0), axis=1).mean() for c in marker.values()]
    if min(edges) <= 0 or np.std(edges)/np.mean(edges) > .08:
        return None, "marker_inconsistent"
    if CAMERA_HEIGHT_MM is None or LEAF_HEIGHT_MM is None:
        return None, "leaf_plane_unknown"
    if not 0 <= LEAF_HEIGHT_MM < CAMERA_HEIGHT_MM or MARKER_HEIGHT_MM >= CAMERA_HEIGHT_MM:
        return None, "invalid_geometry"
    return (MARKER_MM/float(np.median(edges)) *
            (CAMERA_HEIGHT_MM-LEAF_HEIGHT_MM)/(CAMERA_HEIGHT_MM-MARKER_HEIGHT_MM), "aruco_height_corrected")


def mask_is_clipped(leaf_mask):
    if np.any(leaf_mask[0]) or np.any(leaf_mask[-1]) or np.any(leaf_mask[:,0]) or np.any(leaf_mask[:,-1]):
        return True
    if NORMALISED_ROI is not None:
        roi = plant_roi(leaf_mask.shape)
        return bool(np.any(cv2.subtract(roi,cv2.erode(roi,_ellipse_kernel(3))) & leaf_mask))
    return False


def measurements(image, leaf_mask, scale_mm_per_px):
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    pixel = cv2.countNonZero(leaf_mask)
    if pixel == 0:
        # Measure brightness across the whole photo.
        return {"plant_pixels": 0, "mm_per_px": scale_mm_per_px, "image_brightness": float(grey.mean())}
    contours, _ = cv2.findContours(leaf_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    perimeter = sum(cv2.arcLength(k, True) for k in contours)
    hull = cv2.convexHull(np.vstack(contours)).reshape(-1,2).astype(np.float32)
    corners = hull[:,None,:]+np.array([[-.5,-.5],[-.5,.5],[.5,-.5],[.5,.5]],np.float32)
    hull = cv2.convexHull(corners.reshape(-1,2)).reshape(-1,2)
    # Calculate the exact Feret diameter in blocks.
    # This avoids quadratic memory use when the outline has many points.
    max_q = max(float(np.max(np.sum((hull[i:i+128,None,:]-hull[None,:,:])**2,axis=2)))
                for i in range(0,len(hull),128))
    leaf_diameter_px = math.sqrt(max_q)
    n, _, stats, _ = cv2.connectedComponentsWithStats(leaf_mask, connectivity=8)
    colour = leaf_colour_metrics(image, leaf_mask)
    w = {k: v for k, v in colour.items() if not k.startswith("_")}
    w.update({"plant_pixels": pixel, "leaf_diameter_px": leaf_diameter_px,
              "leaf_area_cm2": pixel*scale_mm_per_px**2/100 if scale_mm_per_px else None,
              "diameter_mm": leaf_diameter_px*scale_mm_per_px if scale_mm_per_px else None,
              "compactness": float(4*np.pi*pixel/perimeter**2) if perimeter else None,
              "largest_component_pct": 100*float(stats[1:, cv2.CC_STAT_AREA].max())/pixel if n > 1 else None,
              "mm_per_px": scale_mm_per_px,
              "sharpness": float(cv2.Laplacian(grey, cv2.CV_64F)[leaf_mask > 0].var()),
              "image_brightness": float(grey.mean()),
              "overexposed_pct": 100*float(np.any(image[leaf_mask > 0] >= 254, axis=1).mean()),
              "color_hex": "#{:02x}{:02x}{:02x}".format(*[int(np.clip(round(w[k]), 0, 255)) for k in ("mean_r", "mean_g", "mean_b")])})
    return w


OVERLAY_STATUS_COLOURS = {"ok": (104, 160, 50), "review": (60, 170, 225), "error": (70, 70, 200)}


def _overlay_status(z):
    "Choose a status colour that is visible in a thumbnail."
    if not z.get("usable") or not z.get("plant_pixels"):
        return "error", "NOT USABLE"
    if z.get("quality_flags"):
        return "review", "REVIEW"
    return "ok", "OK"


def _text(panel, text, pos, size, colour, thickness=1):
    cv2.putText(panel, text, pos, cv2.FONT_HERSHEY_SIMPLEX, size, colour, thickness, cv2.LINE_AA)


def review_overlay(image, leaf_mask, z, file_path):
    "Draw fine leaf outlines and a short header on the original photo."
    h, w = image.shape[:2]
    factor = min(1.,1500/w,1150/h)
    image_width, image_height = max(1,round(w*factor)),max(1,round(h*factor))
    camera_view = cv2.resize(image,(image_width,image_height),interpolation=cv2.INTER_AREA)
    m = cv2.resize(leaf_mask,(image_width,image_height),interpolation=cv2.INTER_NEAREST)
    camera_view[m > 0] = np.rint(.94*camera_view[m > 0]+.06*np.array([225,75,211])).astype(np.uint8)
    contours, _ = cv2.findContours(m,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(camera_view,contours,-1,(240,45,228),max(1,round(image_width/1000)),cv2.LINE_AA)

    panel_width = max(625,image_width)
    header = 94
    panel = np.full((image_height+header,panel_width,3),248,np.uint8)
    start = (panel_width-image_width)//2
    panel[header:,start:start+image_width] = camera_view
    data_key, status = _overlay_status(z)
    colour = OVERLAY_STATUS_COLOURS[data_key]
    panel[:header,:8] = colour
    left = 23
    def row(text, y, scale, text_colour, available_width=None):
        max_w = panel_width-left-18 if available_width is None else available_width
        if cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0][0] > max_w:
            while text and cv2.getTextSize(text+"...",cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0][0] > max_w:
                text = text[:-1]
            text += "..."
        _text(panel,text,(left,y),scale,text_colour)

    row(z.get("file_name","?"),24,.61,(27,34,30),panel_width-left-190)
    status_width = cv2.getTextSize(status,cv2.FONT_HERSHEY_SIMPLEX,.5,1)[0][0]
    _text(panel,status,(panel_width-status_width-19,24),.5,colour)
    captured_at = z.get("captured_at")
    timestamp = captured_at.replace("T", " ").replace("Z", " UTC") if captured_at else "Capture time unknown"
    row(timestamp,44,.48,(89,98,93))
    area = (f"{z['leaf_area_cm2']:.2f} cm2" if z.get("leaf_area_cm2") is not None
               else f"{z.get('plant_pixels') or 0:,} Blattpixel".replace(","," "))
    index = f"Health score {z['health_score']:.1f}/100" if z.get("health_score") is not None else "No health score available"
    source = "Manual mask" if z.get("_mask_source")=="manual" else "Automatic mask"
    row(f"{area}  |  {index}  |  {source}",65,.55,(39,52,45))
    messages = {"leaf_at_image_edge":"Leaves touch the image or crop edge",
                 "camera_position_unverified":"Camera position unverified",
                 "view_changed":"Camera view changed",
                 "no_leaf_mask":"No usable leaf mask",
                 "blurred":"Image is blurred",
                 "unstable_lighting_correction":"Lighting comparison unverified",
                 "too_little_shared_leaf_tissue":"Too little overlapping leaf area",
                 "too_little_leaf_tissue_for_lighting_comparison":"Leaf colours cannot be measured reliably"}
    notices = [messages.get(f,f.replace("_"," ")) for f in (z.get("quality_flags") or "").split(";") if f]
    if (z.get("health_status") or "").startswith("provisional_reference"):
        notices.insert(0,"Provisional reference")
    if (z.get("health_status") or "").endswith(";colour_comparison_only"):
        notices.append("Colour comparison only")
    if z.get("_is_reference"):
        notices.append("Reference photo for this camera view")
    if z.get("_score_mode")=="colour_ratio_verified_regions":
        notices.append("Colour comparison in verified regions only")
    if notices:
        row(" | ".join(notices),84,.43,(96,106,100))
    save_png(file_path,panel)


def save_png(file_path,image):
    "Encode with OpenCV and write the path with Python for Windows Unicode support."
    ok, png = cv2.imencode(".png",image)
    if not ok:
        raise OSError(f"Could not save PNG: {file_path}")
    Path(file_path).write_bytes(png.tobytes())


def mask_override_path(output_dir, sha256, rectified=None):
    keep_matches = calibration_file().exists() if rectified is None else rectified
    lens = hashlib.sha256(calibration_file().read_bytes()).hexdigest()[:16] if keep_matches else "raw"
    return output_dir/"mask_corrections"/(sha256+"_"+lens+".png")


def load_mask_override(output_dir, sha256, image_shape, rectified=None):
    file_path = mask_override_path(output_dir,sha256,rectified)
    if not file_path.exists():
        return None
    leaf_mask = cv2.imdecode(np.fromfile(file_path,dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
    if leaf_mask is None or leaf_mask.shape != tuple(image_shape) or not np.isin(leaf_mask,[0,255]).all():
        raise ValueError("The saved mask has the wrong dimensions or is not binary.")
    return leaf_mask


def save_mask_override(output_dir, sha256, leaf_mask, image_shape):
    if leaf_mask.shape != tuple(image_shape) or not np.isin(leaf_mask,[0,255]).all():
        raise ValueError("A corrected mask must match the photo dimensions and contain only black (0) and white (255).")
    target = mask_override_path(output_dir,sha256)
    target.parent.mkdir(parents=True,exist_ok=True)
    ok,png = cv2.imencode(".png",leaf_mask)
    if not ok:
        raise ValueError("The corrected mask could not be encoded.")
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(png.tobytes());tmp.replace(target)
    return target


def correct_mask(image_path, output_dir, carry_forward=None):
    """Mark foreground and background, optionally rerun GrabCut, and save. A correction applies to the exact photo and lens profile. You can also import a full-size binary mask."""
    image_path = Path(image_path).expanduser().resolve()
    sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
    image = cv2.imdecode(np.fromfile(image_path,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The original photo could not be read.")
    if calibration_file().exists():
        d = json.loads(calibration_file().read_text(encoding="utf-8"))
        image = undistort_image(image,d)
    if carry_forward is not None:
        leaf_mask = cv2.imdecode(np.fromfile(carry_forward,dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
        if leaf_mask is None:
            raise ValueError("The imported mask could not be read.")
        return save_mask_override(output_dir,sha,leaf_mask,image.shape[:2])
    leaf_mask = load_mask_override(output_dir,sha,image.shape[:2])
    if leaf_mask is None:
        leaf_mask = refine_mask(image,segment_leaves(downscale(image)))
    original = leaf_mask.copy()
    h,w = leaf_mask.shape
    factor = min(1.,1400/w,800/h)
    size = (round(w*factor),round(h*factor))
    strokes = np.full(leaf_mask.shape,2,np.uint8)
    history = []
    condition = {"radius":max(2,round(6/factor)),"druck":None,"previous":None}
    title = "Correct the leaf mask"
    def draw(event,x,y,flags,param):
        point = (min(w-1,max(0,round(x/factor))),min(h-1,max(0,round(y/factor))))
        if event in (cv2.EVENT_LBUTTONDOWN,cv2.EVENT_RBUTTONDOWN):
            history.append((leaf_mask.copy(),strokes.copy()))
            if len(history)>8:history.pop(0)
            condition["druck"] = 255 if event==cv2.EVENT_LBUTTONDOWN else 0
            condition["previous"] = point
        if condition["druck"] is not None and event in (cv2.EVENT_MOUSEMOVE,cv2.EVENT_LBUTTONDOWN,cv2.EVENT_RBUTTONDOWN):
            a=condition["previous"] or point
            cv2.line(leaf_mask,a,point,condition["druck"],2*condition["radius"])
            cv2.line(strokes,a,point,1 if condition["druck"] else 0,2*condition["radius"])
            condition["previous"] = point
        if event in (cv2.EVENT_LBUTTONUP,cv2.EVENT_RBUTTONUP):
            condition["druck"]=None;condition["previous"]=None
    try:
        cv2.namedWindow(title,cv2.WINDOW_AUTOSIZE);cv2.setMouseCallback(title,draw)
        print("Left: leaf; right: background; +/-: brush; G: GrabCut; U: undo; R: reset; Enter: save; Esc: cancel.")
        while True:
            camera_view = image.copy()
            camera_view[leaf_mask>0] = (.80*camera_view[leaf_mask>0]+.20*np.array([210,50,220])).astype(np.uint8)
            camera_view = cv2.resize(camera_view,size)
            cv2.putText(camera_view,"Left: leaf | Right: background | +/-: brush | G: GrabCut | U: undo | Enter: save",(8,20),cv2.FONT_HERSHEY_SIMPLEX,.43,(10,10,10),2,cv2.LINE_AA)
            cv2.putText(camera_view,"Left: leaf | Right: background | +/-: brush | G: GrabCut | U: undo | Enter: save",(8,20),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1,cv2.LINE_AA)
            cv2.imshow(title,camera_view)
            key_press=cv2.waitKey(25)&255
            if key_press==27 or cv2.getWindowProperty(title,cv2.WND_PROP_VISIBLE)<1:
                print("Cancelled. No correction was saved.");return None
            if key_press in (10,13):
                return save_mask_override(output_dir,sha,leaf_mask,image.shape[:2])
            if key_press in (ord('+'),ord('=')):condition["radius"]=min(100,condition["radius"]+2)
            if key_press==ord('-'):condition["radius"]=max(1,condition["radius"]-2)
            if key_press in (ord('u'),ord('U')) and history:
                m,s=history.pop();leaf_mask[:]=m;strokes[:]=s
            if key_press in (ord('r'),ord('R')):
                leaf_mask[:]=original;strokes[:]=2
            if key_press in (ord('g'),ord('G')):
                history.append((leaf_mask.copy(),strokes.copy()))
                if len(history)>8:history.pop(0)
                gc=np.where(leaf_mask>0,cv2.GC_PR_FGD,cv2.GC_PR_BGD).astype(np.uint8)
                gc[0]=gc[-1]=cv2.GC_BGD;gc[:,0]=gc[:,-1]=cv2.GC_BGD
                if not np.any(strokes==1):
                    core=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9))
                    gc[cv2.erode(leaf_mask,core)>0]=cv2.GC_FGD
                gc[strokes==0]=cv2.GC_BGD;gc[strokes==1]=cv2.GC_FGD
                if np.any(gc==cv2.GC_FGD) and np.any(gc==cv2.GC_BGD):
                    cv2.setRNGSeed(7)
                    cv2.grabCut(image,gc,None,np.zeros((1,65)),np.zeros((1,65)),3,cv2.GC_INIT_WITH_MASK)
                    leaf_mask[:]=np.isin(gc,[cv2.GC_FGD,cv2.GC_PR_FGD]).astype(np.uint8)*255
    except cv2.error as error:
        raise ValueError("Could not open the mask editor. Install desktop OpenCV or use --mask-png to import a PNG.") from error
    finally:
        try:cv2.destroyAllWindows()
        except cv2.error:pass


def load_reference(file_path, new=False, image_source=None):
    from health_assessment import SCORING_VERSION

    if new or not file_path.exists():
        return None
    with np.load(file_path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        lens_hash = hashlib.sha256(calibration_file().read_bytes()).hexdigest() if calibration_file().exists() else None
        if "lens_hash" in meta and meta["lens_hash"] != lens_hash:
            raise ValueError("The lens profile changed. Choose the matching series or use --new-reference.")
        if "lens_hash" not in meta and lens_hash is not None:
            print("No verified lens profile for the old reference. The first usable photo becomes the new reference.")
            return None
        if meta.get("version") not in (SCORING_VERSION, "2.0.0", "2.1.0", "3.0.0") or meta.get("series_id") != SERIES_ID:
            raise ValueError("The reference uses a different series or score version. Use --new-reference.")
        if meta.get("processing_width", PROCESSING_WIDTH) != PROCESSING_WIDTH or meta.get("roi") != (list(NORMALISED_ROI) if NORMALISED_ROI else None):
            raise ValueError("The reference crop or resolution does not match. Use --new-reference.")
        ref = {"meta": meta, "file_name": data["file_name"].copy(), "mask": data["mask"].copy()}
        if "original_mask" in data.files:
            ref["original_mask"] = data["original_mask"].copy()
        if "original_image" in data.files:
            ref["original_image"] = data["original_image"].copy()
    if "original_image" not in ref and image_source:
        for photo in image_source:
            photo=Path(photo)
            if photo.name!=meta.get("file_name") or not photo.is_file():continue
            if hashlib.sha256(photo.read_bytes()).hexdigest()!=meta.get("sha256"):continue
            original=cv2.imdecode(np.fromfile(photo,dtype=np.uint8),cv2.IMREAD_COLOR)
            if original is not None:
                if calibration_file().exists():
                    original=undistort_image(original,json.loads(calibration_file().read_text(encoding="utf-8")))
                ref["original_image"]=original
                break
    image_width,image_height = meta.get("image_width"),meta.get("image_height")
    if image_width and image_height and meta.get("sha256"):
        corrected_input = load_mask_override(file_path.parent,meta["sha256"],(image_height,image_width))
        if corrected_input is not None and (ref.get("original_mask") is None or not np.array_equal(corrected_input,ref["original_mask"])):
            if not np.any(corrected_input):
                return None
            ref["original_mask"] = corrected_input
            ref["mask"] = cv2.resize(corrected_input,(ref["file_name"].shape[1],ref["file_name"].shape[0]),interpolation=cv2.INTER_NEAREST)
            geo = measurements(cv2.resize(ref["file_name"],(image_width,image_height)),corrected_input,None)
            meta.update(mask_source="manual",plant_pixels=geo["plant_pixels"],compactness=geo.get("compactness"),clipped=mask_is_clipped(corrected_input),history=[])
    changed_pipeline=(meta.get("analysis_version") != ANALYSIS_VERSION or meta.get("version") != SCORING_VERSION
                    or meta.get("pipeline_sha256") != PIPELINE_SHA256)
    if changed_pipeline or meta.get("mask_source")!="manual":
        # Preserve the capture time of the reference even if the mask changes.
        # Rebuild outdated masks rather than reusing background pixels.
        leaf_mask = ref["mask"].copy() if meta.get("mask_source")=="manual" else segment_leaves(ref["file_name"])
        if cv2.countNonZero(leaf_mask) < 80:
            print("The old reference is unusable. The first usable photo becomes the new reference.")
            return None
        h, w = ref["file_name"].shape[:2]
        image_width, image_height = meta.get("image_width", w), meta.get("image_height", h)
        if meta.get("mask_source")=="manual" and ref.get("original_mask") is not None:
            full_size=ref["original_mask"]
        elif ref.get("original_image") is not None:
            full_size=refine_mask(ref["original_image"],leaf_mask)
            leaf_mask=cv2.resize(full_size,(w,h),interpolation=cv2.INTER_NEAREST)
        else:
            full_size = cv2.resize(leaf_mask, (image_width, image_height), interpolation=cv2.INTER_NEAREST)
        if cv2.countNonZero(full_size) < max(80,.0004*full_size.size):
            print("The old reference is unusable after checking its mask.")
            return None
        geometry = measurements(cv2.resize(ref["file_name"], (image_width, image_height)), full_size, None)
        ref["mask"] = leaf_mask
        if meta.get("mask_source") != "manual":
            if ref.get("original_image") is not None:ref["original_mask"]=full_size
            else:ref.pop("original_mask",None)
        meta.update(version=SCORING_VERSION, analysis_version=ANALYSIS_VERSION,
                    pipeline_sha256=PIPELINE_SHA256,
                    plant_pixels=geometry["plant_pixels"],
                    compactness=geometry.get("compactness"), clipped=mask_is_clipped(full_size),
                    history=[] if changed_pipeline else meta.get("history",[]))
        print("Rebuilt the reference mask and kept its original photo.")
    return ref


def save_reference(file_path, ref):
    tmp = file_path.with_name("."+file_path.name+".tmp")
    with tmp.open("wb") as file_handle:
        arrays = {"file_name":ref["file_name"],"mask":ref["mask"]}
        if "original_mask" in ref:
            arrays["original_mask"] = ref["original_mask"]
        if "original_image" in ref:
            arrays["original_image"] = ref["original_image"]
        np.savez_compressed(file_handle,meta=json.dumps(ref["meta"],allow_nan=False),**arrays)
    tmp.replace(file_path)


IDENTITY = np.float64([[1.,0.,0.],[0.,1.,0.]])


def select_matching_view(working_image, original_form, sha256, camera_views):
    "Try the same file first, followed by the most recent camera references."
    h,w = original_form
    candidates = [r for r in camera_views if r["file_name"].shape==working_image.shape
                  and (r["meta"].get("image_height",h),r["meta"].get("image_width",w))==(h,w)]
    for ref in candidates:
        if ref["meta"].get("sha256")==sha256:
            return ref,ref["mask"],ref["file_name"],{"matrix":IDENTITY}
    for ref in reversed(candidates[-12:]):
        data = {}
        prior,base,flags = align_scene(working_image,ref,data)
        if not flags and prior is not None and "matrix" in data:
            return ref,prior,base,data
    return None,None,None,{}


def new_view(z, image, working_image, leaf_mask, small_mask, lens_hash):
    from health_assessment import SCORING_VERSION

    return {"file_name":working_image.copy(),"mask":small_mask.copy(),
            "original_mask":leaf_mask.copy(),"original_image":image.copy(),
            "meta":{"version":SCORING_VERSION,"analysis_version":ANALYSIS_VERSION,"series_id":SERIES_ID,
                    "pipeline_sha256":PIPELINE_SHA256,"processing_width":PROCESSING_WIDTH,
                    "roi":list(NORMALISED_ROI) if NORMALISED_ROI else None,"lens_hash":lens_hash,
                    "file_name":z["file_name"],"captured_at":z["captured_at"],"sha256":z["_sha256"],
                    "image_width":image.shape[1],"image_height":image.shape[0],
                    "plant_pixels":z["plant_pixels"],"compactness":z["compactness"],
                    "mask_source":z["_mask_source"],"clipped":z["_clipped"],"history":[]}}


def compare_pose(previous, new):
    "Check the relative camera position and whether a shared crop is needed."
    if previous.get("_pose") is None or new.get("_pose") is None:
        return None
    rel = (np.vstack((new["_pose"],[0.,0.,1.])) @ np.vstack(
        (cv2.invertAffineTransform(previous["_pose"]),[0.,0.,1.])))[:2]
    scale = float(np.hypot(rel[0,0],rel[1,0]))
    angle = abs(math.degrees(math.atan2(rel[1,0],rel[0,0])))
    if abs(scale-1)>.025 or angle>3.:
        return None
    h,w = new["_working_shape"]
    corners = np.array([[0.,0.,1.],[w-1.,0.,1.],[0.,h-1.,1.],[w-1.,h-1.,1.]])
    jump = float(np.max(np.linalg.norm(corners@rel.T-corners[:,:2],axis=1)))
    if jump>.055*max(h,w):
        return None
    overlap = bool((previous.get("_clipped") or new.get("_clipped"))
                      and jump>max(2.,.0025*max(h,w)))
    return rel,scale,overlap


def comparable_areas(previous, new, pose):
    "Count pixels in the earlier view, using the shared frame when needed."
    rel,scale,overlap = pose
    if not overlap:
        return float(previous["plant_pixels"]),new["plant_pixels"]/scale**2
    previous_mask,current_mask = previous["_rate_mask"],new["_rate_mask"]
    h,w = current_mask.shape
    older_field = cv2.warpAffine(np.full(previous_mask.shape,255,np.uint8),rel,(w,h),flags=cv2.INTER_NEAREST)
    visible = cv2.erode(older_field,_ellipse_kernel(3))>0
    visible[[0,-1],:] = False
    visible[:,[0,-1]] = False
    if np.mean(visible)<.90:
        return None
    previous_current = cv2.warpAffine(previous_mask,rel,(w,h),flags=cv2.INTER_NEAREST)
    n_previous,n_current = np.count_nonzero((previous_current>0)&visible),np.count_nonzero((current_mask>0)&visible)
    old_full_mask = cv2.countNonZero(previous_mask)
    new_full_mask = cv2.countNonZero(current_mask)
    if min(n_previous,n_current)<80 or n_previous<.88*old_full_mask*scale**2 or n_current<.88*new_full_mask:
        return None
    # Convert the fraction in the working image back to the original measurement.
    return (previous["plant_pixels"]*n_previous/(old_full_mask*scale**2),
            new["plant_pixels"]*n_current/(new_full_mask*scale**2))


def compare_growth(z, base):
    "Prefer 12 hours between photos and require at least 30 minutes."
    t = z["_capture_time"]
    earlier_rows = [previous for previous in base if previous["_capture_time"]<t]
    comparable = [(previous,pose) for previous in earlier_rows if (pose:=compare_pose(previous,z)) is not None]
    if not comparable:
        return "image_crop_not_comparable" if earlier_rows else "no_earlier_comparable_photo"
    stable = [p for p in comparable if p[0]["_capture_time"]<=t-timedelta(hours=RATE_STABLE_HOURS)]
    short_check = [p for p in comparable if t-timedelta(hours=RATE_STABLE_HOURS)<p[0]["_capture_time"]
            <=t-timedelta(minutes=RATE_MIN_MINUTES)]
    if not (stable or short_check):
        return f"interval_under_{RATE_MIN_MINUTES}_minutes"
    # For the same interval class, prefer a comparison of complete masks.
    for previous,pose in (sorted(reversed(stable),key=lambda p:p[1][2])+sorted(short_check,key=lambda p:p[1][2])):
        areas = comparable_areas(previous,z,pose)
        if areas is None:
            continue
        previous_pixels,current_pixels = areas
        if abs(current_pixels/previous_pixels-1)>.5:
            return "check_area_jump"
        days = (t-previous["_capture_time"]).total_seconds()/86400
        z["growth_rate_pct_per_day"] = 100*(current_pixels/previous_pixels-1)/days
        _,scale,overlap = pose
        previous_scale,current_scale = previous["mm_per_px"],z["mm_per_px"]
        if previous_scale is not None and current_scale is not None and (
                previous["scale_source"]==z["scale_source"]=="manual_scale_in_leaf_plane"
                or abs((current_scale/previous_scale)*scale-1)<=.035):
            z["growth_rate_cm2_per_day"] = (current_pixels-previous_pixels)*previous_scale**2/(100*days)
        z["growth_reference_file"] = previous["file_name"]
        z["growth_interval_hours"] = days*24
        short_interval = days*24<RATE_STABLE_HOURS
        if short_interval:
            add_flags(z,"growth_rate_short_interval")
        if overlap:
            add_flags(z,"growth_shared_frame")
            return "calculated_shared_frame_short_interval" if short_interval else "calculated_shared_frame"
        return "calculated_short_interval" if short_interval else "calculated"
    return "too_little_shared_frame"


def compare_pixels(z, base):
    "Calculate the direct pixel change per day without a geometric correction."
    t = z["_capture_time"]
    if t is None or not z["usable"]:
        return
    prior = [a for a in base if a["_image_shape"]==z["_image_shape"]
              and a["_capture_time"]<=t-timedelta(minutes=RATE_MIN_MINUTES)]
    stable = [a for a in prior if a["_capture_time"]<=t-timedelta(hours=RATE_STABLE_HOURS)]
    if prior:
        previous = stable[-1] if stable else prior[0]
        days = (t-previous["_capture_time"]).total_seconds()/86400
        z["visible_pixel_change_per_day"] = (z["plant_pixels"]-previous["plant_pixels"])/days
        z["pixel_reference_file"] = previous["file_name"]
    base.append(z)


def growth_series(rows, reference_time=None):
    "Build the time axis and calculate changes for each photo."
    first_selection = min((z["_capture_time"] for z in rows if z["_capture_time"]),default=None)
    start = reference_time or first_selection
    base, pixel_baseline = {}, []
    for z in rows:
        t = z["_capture_time"]
        group = z.get("_camera_view_id")
        if t and start:
            z["hours_since_start"] = (t-start).total_seconds()/3600
        if z["health_status"]=="independent_images_no_reference":
            z["_rate_status"] = "independent_images_no_growth_series"
        elif not z["usable"]:
            z["_rate_status"] = "image_not_measurable"
        elif not t:
            z["_rate_status"] = "no_reliable_capture_time"
        elif group is None:
            z["_rate_status"] = "camera_view_not_comparable"
        else:
            earlier_rows = base.setdefault(group,[])
            z["_rate_status"] = compare_growth(z,earlier_rows)
            if z["_rate_status"]=="check_area_jump":
                add_flags(z,"check_area_jump")
                earlier_rows.clear()
            if not earlier_rows or t>earlier_rows[-1]["_capture_time"]:
                earlier_rows.append(z)

        if z["health_status"]!="independent_images_no_reference":
            compare_pixels(z,pixel_baseline)


# Measurement history and export
def make_json_safe(value):
    if isinstance(value,np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {k: make_json_safe(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def historical_value(field, value):
    "Read CSV decimal commas and preserve measured zeroes."
    if field in ("quality_flags", "health_warnings") and value in ("None", "Keine"):
        return ""
    if value is None or (isinstance(value, str) and value.strip().casefold() in
                         ("null", "none", "nan", "—", "nicht verfügbar", CSV_UNAVAILABLE.casefold())):
        return None
    if field in ("quality_flags", "health_warnings", "health_status", "health_category", "scale_source", "capture_time_source"):
        value = normalise_saved_code(value)
    if field == "usable":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1"):
            return True
        if text in ("false", "0"):
            return False
        if text == "":
            return None
        raise ValueError(f"Invalid Boolean in saved results: {value!r}")
    if field in ROUNDING or field in ("plant_pixels", "view_number", "visible_leaf_count"):
        if value == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"Invalid number in {field}: {value!r}")
        number_value = float(str(value).strip().replace(",", "."))
        if not math.isfinite(number_value):
            raise ValueError(f"Non-finite number in {field}")
        if field in ("plant_pixels", "view_number", "visible_leaf_count"):
            if not number_value.is_integer():
                raise ValueError(f"Expected an integer in {field}: {value!r}")
            return int(number_value)
        return number_value
    if not isinstance(value, str):
        raise ValueError(f"Invalid text value in {field}: {value!r}")
    return None if field == "captured_at" and not value else value


def historical_row(record):
    "Read a saved API record for the CSV and charts."
    if not isinstance(record, dict) or not isinstance(record.get("image"), dict):
        raise ValueError("Invalid image record in results.json.")
    for section in ("image_measurements", "health_assessment", "analysis"):
        if section in record and not isinstance(record[section], dict):
            raise ValueError(f"Invalid section {section} in results.json")
    record = normalise_record(record)
    z = {field: None for field in COLUMNS}
    image, info = record["image"], record.get("analysis", {})
    z.update(file_name=image.get("file_name"), captured_at=image.get("captured_at"),
             capture_time_source=info.get("capture_time_source"), hours_since_start=info.get("hours_since_start"),
             view_number=info.get("view_number"), health_reference_file=info.get("reference_file"),
             growth_reference_file=info.get("growth_reference_file"),
             growth_interval_hours=info.get("growth_interval_hours"))
    for section, mapping in (("image_measurements", API_MEASUREMENT_FIELDS), ("health_assessment", API_HEALTH_FIELDS)):
        for de, en in mapping.items():
            z[de] = record.get(section, {}).get(en)
    geo = info.get("leaf_geometry")
    if isinstance(geo, dict):
        z["visible_leaf_count"] = geo.get("count")
        z["visible_leaf_count_method"] = geo.get("method")
    else:
        z["visible_leaf_count"] = info.get("visible_leaf_count")
        z["visible_leaf_count_method"] = info.get("visible_leaf_count_method")
    z["leaf_diameter_px"] = info.get("leaf_diameter_px")
    pixel = info.get("pixel_measurement", {})
    if not isinstance(pixel, dict):
        raise ValueError("Invalid pixel metadata in results.json.")
    z.update(leaf_coverage_pct=pixel.get("leaf_coverage_pct"),
             visible_pixel_change_per_day=pixel.get("visible_pixel_change_per_day"),
             pixel_reference_file=pixel.get("reference_file"))
    z = {field: historical_value(field, value) for field, value in z.items()}
    z["_historical_record"] = copy.deepcopy(record)
    legacy_columns = info.get("legacy_csv_fields", {})
    if not isinstance(legacy_columns, dict):
        raise ValueError("Invalid extra columns in the historical CSV.")
    z["_legacy_csv_fields"] = normalise_extra_columns(legacy_columns)
    return z


def derive_known_values(z, info):
    "Fill only values that can be derived from the same photo."
    image_shape = info.get("image_size") or z.get("_image_shape")
    pixel, scale = z.get("plant_pixels"), z.get("mm_per_px")
    if (z.get("leaf_coverage_pct") is None and isinstance(image_shape,(list,tuple))
            and len(image_shape)==2 and all(type(n) is int and n>0 for n in image_shape)
            and pixel is not None and 0<=pixel<=math.prod(image_shape)):
        z["leaf_coverage_pct"] = round(100*pixel/math.prod(image_shape),ROUNDING["leaf_coverage_pct"])
    if scale is not None and scale>0:
        if z.get("leaf_area_cm2") is None and pixel is not None and pixel>0:
            z["leaf_area_cm2"] = round(pixel*scale**2/100,ROUNDING["leaf_area_cm2"])
        if z.get("diameter_mm") is None and z.get("leaf_diameter_px") is not None and z["leaf_diameter_px"]>0:
            z["diameter_mm"] = round(z["leaf_diameter_px"]*scale,ROUNDING["diameter_mm"])
    rgb = [z.get("mean_"+k) for k in "rgb"]
    if z.get("color_hex") is None and all(v is not None and 0<=v<=255 for v in rgb):
        z["color_hex"] = "#{:02x}{:02x}{:02x}".format(*(round(v) for v in rgb))


def prepare_historical_row(z):
    "Preserve the original record even if its source photo is gone."
    if not isinstance(z.get("file_name"), str) or not z["file_name"].strip():
        raise ValueError("A historical record has no filename.")
    z["_capture_time"] = parse_saved_time(z.get("captured_at"))
    z["_historical"] = True
    saved = z.pop("_historical_record", None)
    derive_known_values(z,(saved or {}).get("analysis",{}))
    if saved is None:
        saved = build_api_record(z)
        # A CSV-only record has no verified source fingerprint.
        saved["device_id"] = None
        saved["analysis"].update(version=z.get("pipeline_version"),pipeline_sha256=None,
                                        series_id=None,mask_source=None,lens_corrected=None)
    info = saved.setdefault("analysis", {})
    z["_sha256"] = saved.get("image", {}).get("checksum_sha256")
    z["_is_reference"] = bool(info.get("is_reference") or z.get("health_status") == "reference_photo_start_of_view")
    z["_score_mode"] = info.get("health_comparison_mode")
    if z["_score_mode"] is None:
        status = z.get("health_status") or ""
        if "colour_ratio_verified_regions" in status:
            z["_score_mode"] = "colour_ratio_verified_regions"
        elif "colour_comparison_only" in status:
            z["_score_mode"] = "colour_only"
    missing_fields = info.get("missing_values", {})
    if not isinstance(missing_fields, dict):
        raise ValueError("Invalid missing_values section in results.json.")
    z["_rate_status"] = (info.get("growth_comparison_mode")
                         or ("calculated_historical" if z.get("growth_rate_pct_per_day") is not None else None)
                         or missing_fields.get("growth_rate_pct_per_day") or "historical_comparison_not_saved")
    saved.setdefault("image", {}).update(file_name=z["file_name"], captured_at=z.get("captured_at"))
    for section, mapping in (("image_measurements", API_MEASUREMENT_FIELDS), ("health_assessment", API_HEALTH_FIELDS)):
        saved.setdefault(section, {}).update({en: z.get(de) for de, en in mapping.items()})
        for de, en in mapping.items():
            if z.get(de) is not None:
                missing_fields.pop(en, None)
            else:
                missing_fields.setdefault(en, "historical_value_not_recorded")
    info.update(version=z.get("pipeline_version"), health_status=z.get("health_status"),
                capture_time_source=z.get("capture_time_source"), hours_since_start=z.get("hours_since_start"),
                view_number=z.get("view_number"), is_reference=z["_is_reference"],
                health_comparison_mode=z["_score_mode"], reference_file=z.get("health_reference_file"),
                growth_reference_file=z.get("growth_reference_file"),
                growth_interval_hours=z.get("growth_interval_hours"), missing_values=missing_fields)
    info.setdefault("pixel_measurement", {}).update(leaf_coverage_pct=z.get("leaf_coverage_pct"),
              visible_pixel_change_per_day=z.get("visible_pixel_change_per_day"), reference_file=z.get("pixel_reference_file"))
    info["leaf_diameter_px"] = z.get("leaf_diameter_px")
    if not info.get("leaf_geometry"):
        info["visible_leaf_count"] = z.get("visible_leaf_count")
        info["visible_leaf_count_method"] = z.get("visible_leaf_count_method")
    if z.get("_legacy_csv_fields"):
        info["legacy_csv_fields"] = copy.deepcopy(z["_legacy_csv_fields"])
    z["_camera_view_id"] = info.get("view_id")
    z["_historical_record"] = saved
    return z


def load_result_history(output_dir):
    "Read and validate previous measurements before replacing any files."
    output_dir = Path(output_dir)
    legacy_directory = output_dir.parent/"auswertung" if output_dir.name == "results" else output_dir
    json_path = next((p for p in (output_dir/"results.json", output_dir/"ergebnis.json",
                                  legacy_directory/"ergebnis.json") if p.is_file()), output_dir/"results.json")
    csv_path = next((p for p in (output_dir/"results.csv", output_dir/"ergebnis.csv",
                                 legacy_directory/"ergebnis.csv") if p.is_file()), output_dir/"results.csv")
    records, rows = [], []
    try:
        if json_path.is_file():
            def invalid_constant(value):
                raise ValueError(f"Invalid JSON number: {value}")
            records = json.loads(json_path.read_text(encoding="utf-8-sig"), parse_constant=invalid_constant)
            if not isinstance(records, list):
                raise ValueError("results.json must contain a list of records.")
        json_rows = [historical_row(record) for record in records]
        used_indices = set()
        json_index = {}
        for i, z in enumerate(json_rows):
            key = (z["file_name"], parse_saved_time(z["captured_at"]) or z["captured_at"])
            json_index.setdefault(key, []).append(i)
        if csv_path.is_file() and csv_path.stat().st_size:
            with csv_path.open(encoding="utf-8-sig", newline="") as file_handle:
                header = file_handle.readline(); file_handle.seek(0)
                delimiter = ";" if ";" in header else "\t" if "\t" in header else ","
                reader = csv.DictReader(file_handle, delimiter=delimiter, strict=True)
                columns = [LEGACY_CSV_FIELDS.get(k, k) for k in (reader.fieldnames or [])]
                if "file_name" not in columns or len(set(columns)) != len(columns) or "" in columns:
                    raise ValueError("The results CSV has an invalid or duplicate column heading.")
                reader.fieldnames = columns
                for number, raw_value in enumerate(reader, 2):
                    if None in raw_value or any(value is None for value in raw_value.values()):
                        raise ValueError(f"Incomplete CSV row {number}")
                    name, timestamp = raw_value.get("file_name"), historical_value("captured_at", raw_value.get("captured_at"))
                    candidates = json_index.get((name, parse_saved_time(timestamp) or timestamp), [])
                    if candidates:
                        index = candidates.pop(0); used_indices.add(index)
                        z = json_rows[index]
                    else:
                        # The CSV is intended for spreadsheet review.
                        # When the JSON also contains the record, keep the JSON values and provenance.
                        z = {field: historical_value(field, raw_value[field]) if field in raw_value else None
                             for field in COLUMNS}
                    z.setdefault("_legacy_csv_fields", {}).update(normalise_extra_columns(
                        {k: v for k, v in raw_value.items() if k not in COLUMNS}))
                    rows.append(z)
        rows.extend(z for i, z in enumerate(json_rows) if i not in used_indices)
        return [prepare_historical_row(z) for z in rows]
    except (OSError, ValueError, TypeError, csv.Error) as error:
        raise ValueError(f"Could not safely read the measurement history: {error}. Previous files were kept.") from error


def merge_result_history(history, current):
    "Update each photo and preserve records whose original photo is missing."
    result, by_name = [], {}
    for z in [*history, *current]:
        candidates = by_name.setdefault(z["file_name"], [])
        sha = z.get("_sha256")
        matching = [i for i in candidates if sha and result[i].get("_sha256") == sha]
        if not matching:
            matching = [i for i in candidates if not (sha and result[i].get("_sha256"))
                         and ((z.get("_capture_time") or z.get("captured_at")) ==
                              (result[i].get("_capture_time") or result[i].get("captured_at"))
                              or not result[i].get("captured_at"))]
            if z.get("_historical") and not sha and not z.get("captured_at"):
                # Same-named files without a timestamp or checksum may be different photos.
                # Merge only exact duplicates.
                matching = [i for i in matching if all(z.get(k) == result[i].get(k) for k in COLUMNS)]
        if (not matching and not z.get("_historical") and len(candidates) == 1
                and z.get("health_status") in ("image_unreadable", "analysis_failed")):
            previous = result[candidates[0]]
            if previous.get("usable") and previous.get("captured_at") == z.get("captured_at"):
                print(f"{z['file_name']}: this photo could not be analysed. Its previous measurement was kept.")
                continue
        if len(matching) == 1:
            index = matching[0]
            if (not z.get("_historical") and result[index].get("usable")
                    and z.get("health_status") in ("image_unreadable", "analysis_failed")):
                print(f"{z['file_name']}: this photo could not be analysed. Its previous measurement was kept.")
            else:
                # Preserve extra columns found in earlier exports.
                extra_fields = dict(result[index].get("_legacy_csv_fields", {}))
                extra_fields.update(z.get("_legacy_csv_fields", {}))
                if extra_fields:
                    z["_legacy_csv_fields"] = extra_fields
                result[index] = z
        else:
            candidates.append(len(result)); result.append(z)
    result.sort(key=lambda z: (z.get("_capture_time") or datetime.max.replace(tzinfo=timezone.utc),
                                z["file_name"], z.get("_sha256") or ""))
    # Keep separate plot lines when the reference or analysis method changes.
    groups = {}
    for z in result:
        info = z.get("_historical_record", {}).get("analysis", {})
        reference = z.get("_reference_metadata", {})
        uid = z.get("_camera_view_id") or info.get("reference_sha256") or z.get("health_reference_file")
        if uid is not None:
            key = (uid, reference.get("captured_at") or info.get("reference_captured_at"),
                   z.get("pipeline_version"), z.get("scoring_version"))
            z["_chart_group"] = groups.setdefault(key, len(groups)+1)
        elif z.get("health_score") is not None or z.get("growth_rate_pct_per_day") is not None:
            key = ("unknown", z["file_name"], z.get("captured_at"))
            z["_chart_group"] = groups.setdefault(key, len(groups)+1)
        else:
            z["_chart_group"] = None
    return result


def build_api_record(z, ref=None):
    if z.get("_historical_record") is not None:
        return copy.deepcopy(z["_historical_record"])
    measurement = {eng: z.get(de) for de, eng in API_MEASUREMENT_FIELDS.items()}
    health = {eng: z.get(de) for de, eng in API_HEALTH_FIELDS.items()}
    missing_fields = {}
    reference = z.get("_reference_metadata") or {}
    if is_camera_photo(z["file_name"]):
        # Record the camera file's relative path.
        # The path remains useful after local photo rotation.
        session = z["file_name"][len("biobox_"):-4]
        storage_path = f"recent/{session}/normal.jpg"
    else:
        storage_path = None
        missing_fields["storage_path"] = "imported_photo_has_no_server_path"
    if z["mm_per_px"] is None:
        for field in ("leaf_area_cm2","diameter_mm","mm_per_px"):
            missing_fields[field] = z.get("scale_source") or "no_verified_scale_in_leaf_plane"
    rate_reason = z.get("_rate_status") or "no_valid_comparable_photo"
    if z["growth_rate_cm2_per_day"] is None:
        missing_fields["growth_rate_cm2_per_day"] = (
            "no_shared_scale_for_pair" if rate_reason.startswith("calculated") else rate_reason)
    if z["growth_rate_pct_per_day"] is None:
        missing_fields["growth_rate_pct_per_day"] = rate_reason
    if z.get("visible_pixel_change_per_day") is None:
        missing_fields["visible_pixel_change_per_day"] = (
            "capture_time_missing" if not z["captured_at"] else
            "image_not_measurable" if not z["usable"] else
            "no_suitable_earlier_photo")
    if z.get("leaf_diameter_px") is None:
        missing_fields["leaf_diameter_px"] = "no_usable_leaf_mask"
    if z.get("visible_leaf_count") is None:
        missing_fields["visible_leaf_count"] = "no_usable_leaf_contours"
        missing_fields["visible_leaf_count_method"] = "no_usable_leaf_contours"
    if z.get("leaf_coverage_pct") is None:
        missing_fields["leaf_coverage_pct"] = "leaf_mask_unavailable"
    if z["health_trend_24h"] is None:
        missing_fields["health_trend_24h"] = "no_comparable_score_22_to_26_hours_earlier"
    if not z["captured_at"]:
        missing_fields["captured_at"] = "no_reliable_capture_time"
    for field, value in health.items():
        if value is None and field not in missing_fields:
            missing_fields[field] = z["health_status"]
    if z.get("_score_mode") in ("colour_ratio_verified_regions", "leaf_distribution_chromatic"):
        missing_fields["score_brown"] = "brown_requires_verified_lighting"
    for field, value in measurement.items():
        if value is None and field not in missing_fields:
            missing_fields[field] = "image_not_measurable" if not z["usable"] else "no_valid_measurement"
    return make_json_safe({"device_id": DEVICE_ID,
        "image": {"file_name": z["file_name"], "captured_at": z["captured_at"],
                  "storage_path": storage_path, "checksum_sha256": z.get("_sha256")},
        "image_measurements": measurement, "health_assessment": health,
        "analysis": {"version": ANALYSIS_VERSION, "health_status": z["health_status"],
                     **({"legacy_csv_fields": z["_legacy_csv_fields"]} if z.get("_legacy_csv_fields") else {}),
                     "pipeline_sha256": PIPELINE_SHA256,
                     "series_id": SERIES_ID,
                     "image_size": list(z["_image_shape"]) if z.get("_image_shape") is not None else None,
                     "camera_transform": z.get("_pose").tolist() if z.get("_pose") is not None else None,
                     "twin_view_id": z.get("_twin_view_id"),
                     "twin_camera_transform": z.get("_twin_pose").tolist() if z.get("_twin_pose") is not None else None,
                     "lens_profile_sha256": z.get("_lens_hash"),
                     "mask_clipped": z.get("_clipped"),
                     "leaf_geometry": z.get("_leaf_geometry"),
                     "leaf_diameter_px": z.get("leaf_diameter_px"),
                     "capture_time_source":z.get("capture_time_source"),
                     "hours_since_start":z.get("hours_since_start"),
                     "view_number":z.get("view_number"),
                     "mask_source": z.get("_mask_source","automatic"),
                     "illumination": {"method": z.get("_lighting_info",{}).get("model"),
                                      "corrected": z.get("_lighting_info",{}).get("corrected",False),
                                      "background_error": z.get("_lighting_info",{}).get("background_error"),
                                      "excluded_leaf_pct": z.get("_lighting_info",{}).get("excluded_leaf_pct"),
                                      "common_leaf_pct": z.get("_lighting_info",{}).get("common_leaf_pct"),
                                      "verified_color_region_pct":z.get("_lighting_info",{}).get("verified_color_region_pct")},
                     "measurement_mode": "metric" if z["mm_per_px"] is not None else "pixels",
                     "scale_status": z.get("_scale_status"),
                     "lens_corrected": z.get("_lens_corrected", False),
                     "reference_file": reference.get("file_name"),
                     "reference_captured_at": reference.get("captured_at"),
                     "reference_sha256": reference.get("sha256"),
                     "reference_approved": bool(reference and z.get("_reference_verified")),
                     "is_reference": bool(z.get("_is_reference")),
                     "health_comparison_mode":z.get("_score_mode"),
                     "structure_score": z.get("_structure_score"),
                     "view_id": z.get("_camera_view_id"),
                     "growth_reference_file": z.get("growth_reference_file"),
                     "growth_interval_hours": z.get("growth_interval_hours"),
                     "growth_comparison_mode":z.get("_rate_status") if rate_reason.startswith("calculated") else None,
                     "pixel_measurement": {"leaf_coverage_pct":z.get("leaf_coverage_pct"),
                                           "visible_pixel_change_per_day":z.get("visible_pixel_change_per_day"),
                                           "reference_file":z.get("pixel_reference_file")},
                     "missing_values": missing_fields}})


def omit_null_fields(value):
    "Omit optional null fields without changing numbers or arrays."
    if isinstance(value, dict):
        return {k: omit_null_fields(v) for k,v in value.items() if v is not None}
    if isinstance(value, list):
        return [omit_null_fields(v) for v in value]
    return value


RESULT_FIELDS = {
    **{de: ("image_measurements",en) for de,en in API_MEASUREMENT_FIELDS.items()},
    **{de: ("health_assessment",en) for de,en in API_HEALTH_FIELDS.items()},
    "captured_at": ("image","captured_at"),
    "capture_time_source": ("analysis","capture_time_source"),
    "hours_since_start": ("analysis","hours_since_start"),
    "view_number": ("analysis","view_number"),
    "health_reference_file": ("analysis","reference_file"),
    "growth_reference_file": ("analysis","growth_reference_file"),
    "growth_interval_hours": ("analysis","growth_interval_hours"),
    "leaf_diameter_px": ("analysis","leaf_diameter_px"),
    "leaf_coverage_pct": ("analysis","pixel_measurement","leaf_coverage_pct"),
    "visible_pixel_change_per_day": ("analysis","pixel_measurement","visible_pixel_change_per_day"),
    "pixel_reference_file": ("analysis","pixel_measurement","reference_file"),
    "visible_leaf_count": ("analysis","leaf_geometry","count"),
    "visible_leaf_count_method": ("analysis","leaf_geometry","method"),
}


def missing_reason(field,z):
    status = z.get("health_status") or "no_valid_measurement"
    if field in ("captured_at","hours_since_start","capture_time_source"):
        return "no_reliable_capture_time"
    if field in ("view_number","health_reference_file") or field.startswith("score_") or field.startswith("health_score"):
        return status
    if field in ("growth_reference_file","growth_interval_hours"):
        return z.get("_rate_status") or "no_valid_comparable_photo"
    if field=="pixel_reference_file":
        return "no_suitable_earlier_photo"
    return "image_not_measurable" if z.get("usable") is False else "no_valid_measurement"


def export_record(z,ref):
    record = build_api_record(z,ref)
    info = record["analysis"]
    missing_fields = {k: v for k,v in info.get("missing_values",{}).items()
             if isinstance(v,str) and v.strip()}
    for field,file_path in RESULT_FIELDS.items():
        key = file_path[-1] if field not in ("visible_leaf_count","visible_leaf_count_method","pixel_reference_file",
                                       "visible_pixel_change_per_day","leaf_coverage_pct") else field
        if z.get(field) is not None:
            missing_fields.pop(key,None)
        else:
            missing_fields.setdefault(key,missing_reason(field,z))
    for key in ("device_id","storage_path","checksum_sha256"):
        value = record.get(key) if key=="device_id" else record["image"].get(key)
        if value is not None:
            missing_fields.pop(key,None)
        else:
            missing_fields.setdefault(key,{"device_id":"device_not_assigned",
                "storage_path":"imported_photo_has_no_server_path",
                "checksum_sha256":"checksum_not_recorded"}[key])
    info["missing_values"] = missing_fields
    return omit_null_fields(make_json_safe(record))


def save_results(rows, ref, output_dir):
    from health_assessment import health_status_label

    # Export current measurements and retain the provenance of historical records.
    content = [export_record(z,ref) for z in rows]
    column_lookup = {file_path[-1] if len(file_path)==2 else de:de for de,file_path in RESULT_FIELDS.items()}
    for z, record in zip(rows, content):
        reasons = {}
        for field, reason in record["analysis"]["missing_values"].items():
            if field in column_lookup:
                reasons.setdefault(health_status_label(reason.split(";",1)[0]), []).append(column_lookup[field])
        z["missing_values"] = " | ".join(
            f"{', '.join(sorted(f))}: {g}" for g, f in sorted(reasons.items()))
    json_tmp = output_dir/".results.json.tmp"
    with json_tmp.open("w", encoding="utf-8") as file_handle:
        json.dump(content, file_handle, ensure_ascii=False, indent=2, allow_nan=False)
    json_tmp.replace(output_dir/"results.json")
    csv_tmp = output_dir/".results.csv.tmp"
    columns = COLUMNS + list(dict.fromkeys(k for z in rows for k in z.get("_legacy_csv_fields", {}) if k not in COLUMNS))
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=columns, delimiter=";", extrasaction="raise")
        writer.writeheader()
        for z in rows:
            data = {}
            for k in columns:
                v = make_json_safe(z.get(k) if k in COLUMNS else z.get("_legacy_csv_fields", {}).get(k))
                if v is None or v=="":
                    if v=="" and k in ("quality_flags","health_warnings"):
                        data[k] = "None"
                    else:
                        data[k] = CSV_UNAVAILABLE
                elif isinstance(v, bool):
                    data[k] = str(v)
                else:
                    data[k] = v
            writer.writerow(data)
    try:
        csv_tmp.replace(output_dir/"results.csv")
    except PermissionError:
        csv_tmp.unlink(missing_ok=True)
        print("Close results.csv in Excel and run the analysis again. Previous results were kept.")
        return False
    return True


def write_json_output(target, data):
    "Replace only JSON data; leave the browser source files in place."
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".biobox-data-", dir=target.parent) as tmp:
        file_handle = Path(tmp)/target.name
        file_handle.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        file_handle.replace(target)
    return target


# Charts and analysis
def plot_health_by_photo(rows, directory_path):
    "Distinguish missing scores, reference photos and measured zeroes."
    from health_assessment import health_status_label

    n = len(rows)
    image_width = max(10., min(26., 5.+.52*n))
    fig, (ax, status_ax) = plt.subplots(2, 1, figsize=(image_width, 7.8), sharex=True,
                                     gridspec_kw={"height_ratios": [4, 1.5]})
    x = np.arange(1, n+1)
    labels_text, colours, labels = [], [], []
    for i, z in enumerate(rows, 1):
        score = z.get("health_score")
        valid_mask = isinstance(score, (int, float)) and math.isfinite(score) and 0 <= score <= 100
        reference = bool(z.get("_is_reference"))
        if valid_mask:
            ax.bar(i, score, width=.67, color="#32816c", zorder=3)
            # Show a genuinely measured zero.
            ax.scatter([i], [score], s=22, color="#245c4e", zorder=4)
            if n <= 45:
                ax.text(i, min(score+3, 104), f"{score:.1f}", ha="center", va="bottom", fontsize=8)
            raw_value = z.get("health_score_raw")
            if isinstance(raw_value, (int, float)) and math.isfinite(raw_value):
                ax.scatter([i], [raw_value], marker="_", s=65, color="#795d91", zorder=5)
            labels_text.append("Calculated")
            colours.append("#32816c")
        elif reference:
            ax.scatter([i], [100], marker="D", s=55, facecolor="white", edgecolor="#547da0", zorder=4)
            if n <= 45:
                ax.text(i, 105, "Ref.", ha="center", fontsize=8, color="#547da0")
            labels_text.append("Reference photo")
            colours.append("#547da0")
        else:
            # The grey placeholder does not represent a score.
            ax.axvspan(i-.34, i+.34, ymin=.02, ymax=.92, facecolor="#e9edef", hatch="///",
                       edgecolor="#c4cdd0", linewidth=0, zorder=0)
            if n <= 45:
                ax.text(i, 48, "—", ha="center", color="#738089", fontsize=12)
            status = (z.get("health_status") or "").split(";", 1)[0]
            labels_text.append(health_status_label(status) if status else "No score recorded")
            colours.append("#9b7141")
        timestamp = z.get("_capture_time") or parse_saved_time(z.get("captured_at"))
        labels.append(f"{i}\n{timestamp:%d.%m. %H:%M}" if timestamp else str(i))
    ax.set_title("04 | Plant condition by photo", loc="left", fontweight="bold", pad=14)
    ax.set_ylabel("Relative index [0–100]")
    ax.set_ylim(-3, 114)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.grid(axis="y", alpha=.18, zorder=0)
    ax.axhline(100, color="#aebcbd", ls=":", lw=1)
    ax.plot([], [], "s", color="#32816c", label="Score by photo")
    ax.plot([], [], "_", color="#795d91", label="Score before smoothing")
    ax.plot([], [], "D", markerfacecolor="white", color="#547da0", label="Reference photo (no measured score)")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), fontsize=8, ncol=3)
    groups = list(dict.fromkeys(labels_text))
    for j, text in enumerate(groups):
        ids = [i for i, s in enumerate(labels_text) if s == text]
        status_ax.scatter([i+1 for i in ids], [j]*len(ids), color=[colours[i] for i in ids], s=25)
    status_ax.set_yticks(range(len(groups)), [t[:76] for t in groups], fontsize=8)
    status_ax.set_ylim(len(groups)-.4, -.6)
    status_ax.grid(axis="y", alpha=.15)
    tick_ids = list(range(n)) if n <= 32 else sorted(set(np.linspace(0, n-1, min(24, n), dtype=int)))
    status_ax.set_xticks([i+1 for i in tick_ids], [labels[i] for i in tick_ids], fontsize=8,
                        rotation=0 if n <= 16 else 45)
    status_ax.set_xlim(.4, max(1, n)+.6)
    status_ax.set_xlabel("Photo number in results.csv / results.json")
    calculated = sum(isinstance(z.get("health_score"), (float, int)) and math.isfinite(z["health_score"]) for z in rows)
    fig.text(.015, .018, f"{n} photos · {calculated} with a score · Hatched: no score. "
             "100 means close to the reference; this is not a diagnosis.", fontsize=8.5, color="#62737b")
    fig.tight_layout(rect=(0, .055, 1, 1))
    directory_path.mkdir(exist_ok=True)
    fig.savefig(directory_path/CHART_FILES[3], dpi=150, facecolor="white")
    plt.close(fig)


def plot_charts(rows, directory_path):
    from health_assessment import SCORE_WEIGHTS

    directory_path.mkdir(exist_ok=True)
    green, red, grey = "#32816c", "#b95750", "#62737b"
    timestamps = [z["_capture_time"] for z in rows]
    time_axis = bool(timestamps) and all(timestamps)
    x = timestamps if time_axis else list(range(1, len(rows)+1))
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    def line_points(ax, field, label, colour):
        y = [z.get(field) if z.get(field) is not None and z.get("usable") else np.nan for z in rows]
        if not any(np.isfinite(v) for v in y):
            return False
        ax.plot(x, y, "o-", ms=4, lw=1.7, color=colour, label=label)
        return True
    def note(ax, text):
        ax.text(.5, .5, text, ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color=grey, linespacing=1.7)
    def save_file(fig, number):
        for ax in fig.axes:
            ax.grid(alpha=.16)
            ax.set_xlabel("Capture time (UTC)" if time_axis else "Photo (capture time unavailable)")
            if time_axis:
                locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
            if len(x) == 1 and time_axis:
                t = mdates.date2num(x[0])
                ax.set_xlim(t-.02, t+.02)
        fig.text(.012, .012, f"BioBox | {sum(bool(z['usable']) for z in rows)}/{len(rows)} usable | Index relative to the plant's own reference", fontsize=8, color=grey)
        fig.tight_layout(rect=(0, .05, 1, 1))
        fig.savefig(directory_path/CHART_FILES[number], dpi=150, facecolor="white")
        plt.close(fig)
    def plot_series_with_status(number,title,field,ylabel,status,second_view=None,pixel=False):
        observations = np.arange(1,len(rows)+1)
        groups = list(dict.fromkeys(status))
        height_status = max(.95,.31*len(groups)+.3)
        heights = [3.1,2.1,height_status] if pixel else [3.5,height_status]
        fig,axis_pair = plt.subplots(len(heights),1,figsize=(11,sum(heights)+1.3),sharex=True,
                                 gridspec_kw={"height_ratios":heights})
        ax,bottom = axis_pair[0],axis_pair[-1]
        ax.set_title(title,loc="left",fontweight="bold",pad=12)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y",alpha=.19)
        y = np.array([z[field] if z.get(field) is not None else np.nan for z in rows])
        count_items = int(np.count_nonzero(np.isfinite(y)))
        ax.set_xlim(.5,max(1,len(rows))+.5)
        camera_views = [z.get("_chart_group", z.get("view_number")) for z in rows]
        colours = ["#2e806a","#547da0","#9362a1","#ad7340","#56705a","#8a6371"]
        modes = [z.get("_score_mode") for z in rows]
        for i,camera_view in enumerate(dict.fromkeys(a for a in camera_views if a is not None)):
            colour = colours[i%len(colours)]
            series_groups = list(dict.fromkeys(m for j,m in enumerate(modes) if camera_views[j]==camera_view)) if second_view else [None]
            for mode in series_groups:
                leaf_mask = np.array([a==camera_view and (not second_view or m==mode) for a,m in zip(camera_views,modes)])
                if not np.isfinite(y[leaf_mask]).any():
                    continue
                part = mode=="colour_ratio_verified_regions"
                label = f"Reference {camera_view}"+(" · Colour comparison in verified regions" if part else "")
                ax.plot(observations,np.where(leaf_mask,y,np.nan),"s-" if part else "o-",
                        ms=4.5,lw=1.6,color=colour,label=label)
                if second_view:
                    raw_value = np.array([z[second_view] if z.get(second_view) is not None else np.nan for z in rows])
                    ax.plot(observations,np.where(leaf_mask,raw_value,np.nan),"--",lw=.9,color=colour,alpha=.45)
        refs = [i for i,z in enumerate(rows) if z.get("_is_reference")] if second_view else []
        if number==3:
            ax.set_ylim(-3,107)
            ax.axhline(100,color="#b4bec3",lw=1,ls=":",zorder=0)
            ax.set_yticks([0,25,50,75,100])
        elif count_items:
            ax.axhline(0,color=grey,lw=.8)
        if refs:
            ax.scatter(observations[refs],[100]*len(refs),marker="D",facecolor="white",edgecolor="#517493",
                       s=44,zorder=5,label="Reference photo (no measurement)")
        if not count_items:
            note(ax,"No verified growth rate.\nDirect pixel change is shown below." if pixel
                    else "No valid colour comparison. See each photo's status below.")
            if number==1:
                ax.set_yticks([])
        if count_items or refs:
            handles,labels = ax.get_legend_handles_labels()
            ax.legend(handles[:12],labels[:12],loc="lower left" if second_view else "best",fontsize=8.5)
        if pixel:
            raw_axis = axis_pair[1]
            px = np.array([z["visible_pixel_change_per_day"] if z.get("visible_pixel_change_per_day") is not None
                           else np.nan for z in rows])
            raw_axis.set_title("Direct leaf-pixel change, including between views",loc="left",fontsize=10)
            raw_axis.set_ylabel("Pixels per day")
            raw_axis.grid(axis="y",alpha=.15)
            if np.isfinite(px).any():
                raw_axis.axhline(0,color=grey,lw=.7)
                raw_axis.plot(observations,px,"o:",color="#76548b",ms=4,lw=1.1)
            else:
                note(raw_axis,"Requires two usable photos at the same resolution, at least 30 minutes apart.")
        bottom.set_title("Status by photo",loc="left",fontsize=9,color=grey,pad=5)
        for idx,group in enumerate(groups):
            xs = [n for n,g in zip(observations,status) if g==group]
            marker = "D" if group=="Reference photo" else "o" if group.startswith("Calculated") else "x"
            colour = "#517493" if marker=="D" else green if marker=="o" else "#9c663b"
            bottom.scatter(xs,[idx]*len(xs),s=28,marker=marker,color=colour,linewidths=1.2)
        bottom.set_yticks(range(len(groups)),groups,fontsize=9)
        bottom.set_ylim(len(groups)-.4,-.6)
        bottom.grid(axis="y",alpha=.15)
        bottom.tick_params(axis="y",length=0)
        bottom.set_xticks(sorted(set(np.linspace(1,len(rows),min(9,len(rows)),dtype=int))))
        bottom.set_xlabel("Photo number (order in results.csv)")
        extra_fields = "Pixel change alone does not establish growth." if pixel else "Solid: smoothed score · Dashed: raw score."
        fig.text(.013,.013,f"BioBox | {count_items}/{len(rows)} with a verified comparison | {extra_fields}",fontsize=8.5,color=grey)
        fig.tight_layout(rect=(0,.045,1,1))
        fig.savefig(directory_path/CHART_FILES[number],dpi=150,facecolor="white")
        plt.close(fig)

    usable_rows = [z for z in rows if z["usable"]]
    calibrated = bool(usable_rows) and all(z["leaf_area_cm2"] is not None for z in usable_rows)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.set_title("01 | Visible projected leaf area")
    field = "leaf_area_cm2" if calibrated else "plant_pixels"
    has_data = line_points(ax, field, "Usable leaf mask", green)
    unverified = [(xi, z[field]) for xi, z in zip(x, rows)
                   if not z.get("usable") and z.get(field) is not None]
    if unverified:
        ax.scatter([p[0] for p in unverified], [p[1] for p in unverified],
                   color=red, marker="x", label="Review the mask; measurement unverified")
        ax.legend()
    if not has_data and not unverified:
        note(ax, "No usable leaf mask. Check the overlays and quality flags.")
    ax.set_ylabel("Area [cm²]" if calibrated else "Visible leaf area [pixels]")
    save_file(fig, 0)
    rate_cm = calibrated and any(z.get("growth_rate_cm2_per_day") is not None for z in rows)
    field = "growth_rate_cm2_per_day" if rate_cm else "growth_rate_pct_per_day"
    rate_labels = {"calculated":"Calculated", "calculated_short_interval":"Calculated · short interval",
                  "calculated_historical":"Calculated · saved comparison",
                  "image_crop_not_comparable":"Image crops are not comparable",
                  "too_little_shared_frame":"Too little overlap between frames",
                  "calculated_shared_frame":"Calculated · shared frame",
                  "calculated_shared_frame_short_interval":"Calculated · shared frame, short interval",
                  "image_not_measurable":"Image is not usable",
                  "camera_view_not_comparable":"Camera view is not comparable",
                  "no_reliable_capture_time":"Capture time unavailable",
                  "no_earlier_comparable_photo":"No earlier photo for comparison",
                  "check_area_jump":"Review the sudden change in area",
                  "independent_images_no_growth_series":"Independent image",
                  f"interval_under_{RATE_MIN_MINUTES}_minutes":f"Less than {RATE_MIN_MINUTES} minutes apart"}
    rate_statuses = [rate_labels.get(z.get("_rate_status"),"Not calculated") for z in rows]
    plot_series_with_status(1,"02 | Growth rate within comparable camera views",
                       field,"cm² per day" if rate_cm else "% per day",rate_statuses,pixel=True)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    top.set_title("03 | Raw leaf colour (lighting dependent)")
    for field, colour, label in [("mean_r", "#ba6262", "R"), ("mean_g", green, "G"), ("mean_b", "#5685a5", "B")]:
        line_points(top, field, label, colour)
    top.set_ylabel("Mean RGB channel [0–255]")
    if top.lines:
        top.legend()
    else:
        note(top, "No usable leaf colour data.")
    for field, colour, label in [("yellow_fraction_pct", "#c2a333", "Yellow"), ("brown_fraction_pct", "#95684f", "Brown")]:
        line_points(bottom, field, label, colour)
    bottom.set_ylabel("Share of leaf mask [%]")
    if bottom.lines:
        bottom.legend()
    else:
        note(bottom, "No usable leaf mask.")
    save_file(fig, 2)
    plot_health_by_photo(rows, directory_path)
    fig, ax = plt.subplots(figsize=(max(8.5,min(16,5+.45*len(rows))),4.7))
    ax.set_title("05 | Five health subscores by photo",loc="left",fontweight="bold")
    labels = ["Colour distribution","Increase in yellow","Increase in brown or warm tones","Saturation change","Hue change"]
    values = np.array([[np.nan if z.get("score_"+k) is None else z["score_"+k] for z in rows]
                      for k in SCORE_WEIGHTS],dtype=float)
    ax.set_facecolor("#edf0f2")
    heat = ax.imshow(np.ma.masked_invalid(values),aspect="auto",interpolation="nearest",
                     cmap="viridis",vmin=0,vmax=100)
    ax.set_yticks(range(len(labels)),labels)
    pos = list(range(len(rows))) if len(rows)<=32 else sorted(set(np.linspace(0,len(rows)-1,24,dtype=int)))
    ax.set_xticks(pos,[i+1 for i in pos])
    ax.set_xlabel("Photo number (order in results.csv)")
    if len(rows)<=16:
        for i,z in enumerate(rows):
            for j in range(len(labels)):
                if np.isfinite(values[j,i]):
                    ax.text(i,j,f"{values[j,i]:.1f}",ha="center",va="center",fontsize=8,
                            color="#192620" if values[j,i]>=58 else "white")
                elif z.get("_is_reference"):
                    ax.text(i,j,"Ref.",ha="center",va="center",fontsize=8,color="#517493")
                else:
                    ax.text(i,j,"—",ha="center",va="center",fontsize=8,color="#62737b")
    fig.colorbar(heat,ax=ax,label="Subscore [0–100]")
    fig.text(.014,.013,"Grey: no comparison. Ref. = reference photo for a camera view. See chart 03 for raw colours.",
             fontsize=8.5,color=grey)
    fig.tight_layout(rect=(0,.045,1,1))
    fig.savefig(directory_path/CHART_FILES[4],dpi=150,facecolor="white")
    plt.close(fig)


@contextlib.contextmanager
def lock_results(output_dir):
    "Prevent concurrent analysis without a lock file in the results directory."
    name = hashlib.sha256(str(output_dir).casefold().encode("utf-8")).hexdigest()[:24]
    if os.name == 'nt':
        # On Windows, use a named system mutex rather than a project file.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.ReleaseMutex.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        mutex = kernel.CreateMutexW(None, False, 'Local\\BioBox-Analyse-' + name)
        if not mutex:
            raise OSError('Could not create the Windows analysis lock.')
        status = kernel.WaitForSingleObject(mutex, 0)
        if status not in (0, 0x80):
            kernel.CloseHandle(mutex)
            if status == 0x102:
                raise ValueError('Another analysis is already using this results folder.')
            raise OSError('Could not acquire the Windows analysis lock.')
        try:
            yield
        finally:
            kernel.ReleaseMutex(mutex)
            kernel.CloseHandle(mutex)
    else:
        # On other systems, put the lock in the system temporary directory.
        import fcntl
        with (Path(tempfile.gettempdir()) / ('biobox-analysis-' + name + '.lock')).open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('Another analysis is already using this results folder.') from error
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def remove_legacy_reference_files(output_dir):
    "Remove only old reference files created by this program after successful analysis."
    for name in ('referenz.npz', '.analyse.lock'):
        try:
            (output_dir/name).unlink(missing_ok=True)
        except OSError as error:
            print(f"Could not remove the legacy file: {name} ({error}).")
    directory_path = output_dir/'kamera_referenzen'
    if directory_path.is_dir() and not directory_path.is_symlink():
        try:
            for file_path in directory_path.iterdir():
                if file_path.is_file() and re.fullmatch(r'ansicht-[0-9a-f]{64}\.npz',file_path.name):
                    file_path.unlink()
            directory_path.rmdir()  # Leave unrecognised files in place.
        except OSError as error:
            print(f"Could not remove the old camera reference folder: {error}.")


def publish_files(files_to_publish, work):
    "Publish outputs together and restore originals if a write fails."
    backup = work/"previous"; backup.mkdir()
    changes = []
    try:
        for i,(new,target) in enumerate(files_to_publish):
            backup_path = backup/str(i)
            item = {"target":target,"backup":backup_path,"old":False,"new":False}
            changes.append(item)
            if target.exists() or target.is_symlink():
                target.replace(backup_path);item["old"] = True
            if new is not None:
                new.replace(target);item["new"] = True
    except OSError as error:
        blocked_paths = []
        for item in reversed(changes):
            try:
                target = item["target"]
                if item["new"] and (not item["old"] or target.is_dir()):
                    target.replace(work/("rollback-"+item["backup"].name))
                if item["old"]:
                    item["backup"].replace(target)
            except OSError:
                blocked_paths.append(str(item["target"]))
        if blocked_paths:
            (work/"keep_backup").touch()
            raise OSError("Could not restore all outputs. Backup: "+str(backup)+": "+", ".join(blocked_paths)) from error
        raise OSError("Could not replace the outputs. Close open files and try again. "
                      "The previous outputs were restored.") from error


def validate_chart_directory(directory_path):
    if directory_path.is_symlink() or (directory_path.exists() and not directory_path.is_dir()):
        raise ValueError(f"Could not safely use the charts folder: {directory_path}")


def stage_legacy_charts(previous, target, working_image):
    "Move old chart outputs and leave source files in place."
    files_to_publish = []
    if previous == target or not previous.is_dir():
        return files_to_publish
    working_image.mkdir()
    for file_path in previous.iterdir():
        if file_path.suffix.lower() in (".html", ".css", ".js"):
            continue
        if file_path.name in (*CHART_FILES, CHART_MANIFEST_FILE, OBSOLETE_TWIN_CHART):
            if file_path.is_dir():
                raise ValueError(f"A folder occupies the expected output path: {file_path}")
            files_to_publish.append((None, file_path))
            continue
        new = target/file_path.name
        if new.exists() or new.is_symlink():
            raise ValueError(f"The same file is present in both chart folders: {file_path.name}. Rename one of the files.")
        copied_path = working_image/file_path.name
        if file_path.is_dir() and not file_path.is_symlink():
            shutil.copytree(file_path, copied_path, symlinks=True)
        else:
            shutil.copy2(file_path, copied_path, follow_symlinks=False)
        files_to_publish.extend(((copied_path, new), (None, file_path)))
    return files_to_publish


def remove_empty_chart_directory(previous, target):
    if previous != target:
        with contextlib.suppress(OSError):
            previous.rmdir()


def analyse_series(paths,output_dir,manual=None,independent_images=False,new_reference=False,capture_times=None):
    """Reanalyse all inputs and publish matching outputs together. Automatic masks are regenerated; hand-corrected masks remain inputs. Restore any replaced files if a write fails."""
    from digital_twin import load_forecast_history

    paths=list(paths);output_dir=Path(output_dir).expanduser().resolve()
    if not paths:raise ValueError('No input photos. Previous results were kept.')
    output_dir.mkdir(parents=True,exist_ok=True)
    target_twin,target_health = viewer_directories(output_dir)
    target_chart_folder,old_chart_folder = chart_directory(output_dir),output_dir/"charts"
    with lock_results(output_dir):
        history = load_result_history(output_dir)
        forecast_history = load_forecast_history(output_dir)
        work=Path(tempfile.mkdtemp(prefix='.biobox-analysis-',dir=output_dir.parent))
        staged_results=work/'new';staged_results.mkdir()
        try:
            # Build camera references in memory for each run.
            # Keep the optional saved ruler calibration.
            legacy_results = output_dir.parent/'auswertung' if output_dir.name=='results' else output_dir
            scale_file = next((p for p in (output_dir/'scale_reference.npz', output_dir/'massstab.npz',
                                           legacy_results/'massstab.npz') if p.is_file()), None)
            if scale_file:
                shutil.copy2(scale_file, staged_results/'scale_reference.npz')
            adopted_inputs = []
            if scale_file and scale_file != output_dir/'scale_reference.npz':
                adopted_inputs.append((staged_results/'scale_reference.npz', output_dir/'scale_reference.npz'))
            for folder, old_folder in (('mask_corrections', 'masken_korrektur'), ('leaf_labels', 'blattlabels')):
                overrides = next((p for p in (output_dir/folder, output_dir/old_folder,
                                              legacy_results/old_folder) if p.is_dir()), None)
                if overrides:
                    shutil.copytree(overrides, staged_results/folder)
                    if overrides != output_dir/folder and not (output_dir/folder).exists():
                        adopted_inputs.append((staged_results/folder, output_dir/folder))
            # Preserve files that this program did not generate.
            for folder,suffix in [('masks','_mask.png'),('overlays','_overlay.png')]:
                (staged_results/folder).mkdir()
                if (output_dir/folder).is_dir():
                    for path in (output_dir/folder).iterdir():
                        generated=bool(re.match(r'^\d{5}_',path.name) and path.name.endswith((suffix, "_maske.png" if folder=="masks" else "_kontrolle.png")))
                        if not generated:
                            target=staged_results/folder/path.name
                            if path.is_dir():shutil.copytree(path,target,symlinks=True)
                            else:shutil.copy2(path,target,follow_symlinks=False)
            staged_twin,staged_health = work/"twin",work/"health_score"
            staged_charts = work/"charts"; staged_charts.mkdir()
            expected_charts = (*CHART_FILES, CHART_MANIFEST_FILE)
            validate_chart_directory(target_chart_folder)
            validate_chart_directory(old_chart_folder)
            migration = stage_legacy_charts(old_chart_folder, target_chart_folder, work/"legacy-charts")
            rows=_analyse_images(paths,staged_results,manual,independent_images,new_reference,history,forecast_history,
                              capture_times,staged_twin,staged_health,staged_charts)
            files_to_publish = [(staged_results/name,output_dir/name) for name in
                       ('results.csv','results.json','masks','overlays')]
            files_to_publish += [(staged_twin/TWIN_JSON_FILE, target_twin/TWIN_JSON_FILE),
                        (staged_health/HEALTH_JSON_FILE, target_health/HEALTH_JSON_FILE)]
            files_to_publish += [(staged_charts/name, target_chart_folder/name) for name in expected_charts]
            retired_outputs = [(None, file_path) for file_path in (output_dir/TWIN_JSON_FILE, output_dir/HEALTH_JSON_FILE,
                                                  target_chart_folder/OBSOLETE_TWIN_CHART) if file_path.is_file()]
            if not all(new.exists() for new,_ in files_to_publish):
                raise OSError('Analysis produced incomplete outputs. Previous results were kept.')
            if any(target.is_dir() for new,target in files_to_publish if new.is_file()):
                raise OSError("A folder occupies an expected output filename.")
            target_twin.mkdir(parents=True,exist_ok=True)
            target_health.mkdir(parents=True,exist_ok=True)
            target_chart_folder.mkdir(parents=True,exist_ok=True)
            publish_files(files_to_publish+adopted_inputs+retired_outputs+migration,work)
            remove_empty_chart_directory(old_chart_folder, target_chart_folder)
        finally:
            if not (work/"keep_backup").exists():
                shutil.rmtree(work)
    remove_legacy_reference_files(output_dir)
    retained_count = sum(bool(z.get('_historical')) for z in rows)
    photo_label = "photo" if len(paths) == 1 else "photos"
    history_label = "measurement" if retained_count == 1 else "measurements"
    print(f"\nAnalysed {len(paths)} {photo_label} and retained {retained_count} historical {history_label}.")
    print(f'{len(rows)} records in total -> {output_dir/"results.csv"}')
    print('Updated masks, overlays, charts, measurement history, and browser data.')
    print("Open a view: python digital_twin.py, python health_assessment.py, or python computer_vision_pipeline.py --charts.")
    n_rate = sum(z.get("growth_rate_pct_per_day") is not None for z in rows)
    n_score = sum(z.get("health_score") is not None for z in rows)
    pixel_change_available = sum(z.get("visible_pixel_change_per_day") is not None for z in rows)
    print(f"Pixel change: {pixel_change_available}/{len(rows)} | Verified growth rate: {n_rate}/{len(rows)} | "
          f"Condition score: {n_score}/{len(rows)}. See charts 02 and 04.")
    area_available = sum(z.get("leaf_area_cm2") is not None for z in rows)
    capture_time_available = sum(bool(z.get("captured_at")) for z in rows)
    leaf_count_available = sum(z.get("visible_leaf_count") is not None for z in rows)
    print(f"Capture time: {capture_time_available}/{len(rows)} | Area in cm²: {area_available}/{len(rows)} | "
          f"Leaf count: {leaf_count_available}/{len(rows)}. See missing_values in results.csv for the reasons.")
    if manual is None and not any(z.get('mm_per_px') for z in rows):
        print('For cm² or mm, mark a known length in the leaf plane using --scale-image and --reference-mm.')
    return rows


def _analyse_images(paths, output_dir, manual, independent_images, new_reference, history,
                 forecast_history, capture_times, twin_folder, health_folder, charts_folder):
    from digital_twin import leaf_points_path, update_twin_model, merge_twin_views, twin_leaf_geometry
    from health_assessment import (
        SCORE_WEIGHTS, REFERENCE_APPROVED, SCORING_VERSION, assess_health, save_health,
        health_features, health_history, match_lighting, apply_lighting, health_status_label,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    masks, overlay = output_dir/"masks", output_dir/"overlays"
    masks.mkdir(exist_ok=True)
    overlay.mkdir(exist_ok=True)
    ruler = read_ruler_scale(output_dir/"scale_reference.npz")
    # Do not save or reload camera reference files.
    # Use the first suitable photo as this run's reference.
    primary_reference = None
    camera_views = []
    prior_history = {}
    view_numbers = {}
    lens_hash = hashlib.sha256(calibration_file().read_bytes()).hexdigest() if calibration_file().exists() else None
    calibration = None
    if calibration_file().exists() and not independent_images:
        d = json.loads(calibration_file().read_text(encoding="utf-8"))
        size = lens_image_size(d)
        if not isinstance(size,(list,tuple)) or len(size)!=2 or min(size)<=0:
            raise ValueError("The old lens profile has no image dimensions. Run --calibrate to renew it. Previous results were kept.")
        calibration = d
    capture_times = capture_times or {}
    capture_times_file = {p: (None,"unknown") if independent_images else
                      (capture_times[Path(p).name],"timestamp_file") if Path(p).name in capture_times
                      else capture_time(p) for p in paths}
    paths = sorted(paths,key=lambda p:(capture_times_file[p][0] or datetime.max.replace(tzinfo=timezone.utc),str(p)))
    rows, generated_file = [], set()
    for number, file_path in enumerate(paths, 1):
        timestamp, time_source = capture_times_file[file_path]
        file_path = Path(file_path)
        z = {k: None for k in COLUMNS}
        z.update({"file_name": file_path.name, "captured_at": iso(timestamp), "capture_time_source": time_source,
                  "pipeline_version": ANALYSIS_VERSION, "scoring_version": SCORING_VERSION, "quality_flags": "", "health_warnings": "",
                  "usable": False, "health_status": "unusable", "health_category": "no_data", "_capture_time": timestamp})
        rows.append(z)
        try:
            original = file_path.read_bytes()
            z["_sha256"] = hashlib.sha256(original).hexdigest()
            image = cv2.imdecode(np.frombuffer(original,dtype=np.uint8),cv2.IMREAD_COLOR) if original else None
            if image is None or min(image.shape[:2]) < 16:
                z["health_status"] = "image_unreadable"
                add_flags(z,"unreadable")
                continue
            if calibration is not None:
                image = undistort_image(image,calibration)
            working_image = downscale(image)
            ref,prior,reference_image,scene_data = select_matching_view(
                working_image,image.shape[:2],z["_sha256"],camera_views)
            lighting_info = {"model":"not_comparable","corrected":False}
            lighting_flags = []
            normal = working_image
            if ref is not None and prior is not None:
                g,b = greenness(working_image)
                sample = ((g>=8)&(b>=1)).astype(np.uint8)*255
                normal,lighting_flags,lighting_info = match_lighting(working_image,sample,reference_image,prior)
            z["_lighting_info"] = lighting_info
            leaf_mask = load_mask_override(output_dir,z["_sha256"],image.shape[:2],calibration is not None)
            manually_corrected = leaf_mask is not None
            if (leaf_mask is None and ref is not None and z["_sha256"]==ref["meta"].get("sha256") and
                    ref.get("original_mask") is not None and ref["original_mask"].shape==image.shape[:2]):
                leaf_mask=ref["original_mask"].copy()
                manually_corrected=ref["meta"].get("mask_source")=="manual"
            if leaf_mask is None:
                small_mask = segment_leaves(normal if normal is not None else working_image,prior if normal is not None else None,
                                          reference_image if normal is not None else None)
                leaf_mask = refine_mask(apply_lighting(image,lighting_info) if normal is not None else image,
                                         small_mask,reference_image)
            small_mask = cv2.resize(leaf_mask,(working_image.shape[1],working_image.shape[0]),interpolation=cv2.INTER_NEAREST)
            z["_mask_source"] = "manual" if manually_corrected else "automatic"
            scale_mm_per_px, source = (measure_scale(image,manual,ruler) if not independent_images else
                             (float(manual),"manual_scale_in_leaf_plane") if manual else (None,"independent_images_no_shared_scale"))
            z.update(measurements(image,leaf_mask,scale_mm_per_px))
            z["_image_shape"] = image.shape[:2]
            z["leaf_coverage_pct"] = 100*z["plant_pixels"]/leaf_mask.size
            # When scale is unavailable, record why
            # rather than treating a missing scale as zero.
            z["scale_source"] = source
            z["_scale_status"] = source
            z["_lens_corrected"] = calibration is not None
            z["_lens_hash"] = lens_hash
            z["noise"] = estimate_noise(image)
            if not timestamp:
                add_flags(z, "capture_time_unknown")
            enough_pixels = z["plant_pixels"] >= max(80,.0004*leaf_mask.size)
            roi_area = cv2.countNonZero(plant_roi(leaf_mask.shape)) if NORMALISED_ROI is not None else leaf_mask.size
            too_large = not manually_corrected and z["plant_pixels"] > .94*roi_area
            if too_large:
                add_flags(z,"mask_covers_almost_entire_frame")
            if not enough_pixels:
                add_flags(z, "no_leaf_mask")
            # Keep quality decisions stable under exposure adjustments.
            # Export the original sharpness measurement.
            test_image = normal if normal is not None else working_image
            grey_for_check = cv2.cvtColor(test_image,cv2.COLOR_BGR2GRAY)
            sharp = bool(np.any(small_mask) and
                          cv2.Laplacian(grey_for_check,cv2.CV_64F)[small_mask>0].var() >= 8)
            if enough_pixels and not sharp:
                add_flags(z, "blurred")
            exposed = z.get("overexposed_pct") is not None and z["overexposed_pct"] < 35
            if enough_pixels and not exposed:
                add_flags(z, "leaf_area_overexposed")
            z["_clipped"] = mask_is_clipped(leaf_mask)
            if z["_clipped"]:
                add_flags(z,"leaf_at_image_edge")
            z["usable"] = bool(enough_pixels and not too_large and sharp and exposed and z["noise"]<35)
            if z["noise"]>=35:
                add_flags(z,"high_image_noise")
            if z["usable"] and not independent_images:
                if ref is None:
                    ref = new_view(z,image,working_image,leaf_mask,small_mask,lens_hash)
                    camera_views.append(ref)
                    if primary_reference is None:
                        primary_reference = ref
                    else:
                        add_flags(z,"new_camera_view")
                    scene_data = {"matrix":IDENTITY}
                    z["_lighting_info"] = {"model":"reference","corrected":False}
                meta = ref["meta"]
                uid = meta["sha256"]
                camera_views[:] = [r for r in camera_views if r is not ref]+[ref]
                view_id_number = view_numbers.setdefault(uid,len(view_numbers)+1)
                z.update(view_number=view_id_number,health_reference_file=meta["file_name"],
                         _camera_view_id=uid,_reference_metadata=meta,_working_shape=working_image.shape[:2],
                         _pose=scene_data["matrix"],_rate_mask=small_mask,
                         _reference_verified=bool(ref is primary_reference and REFERENCE_APPROVED))

            if independent_images:
                z["health_status"] = "independent_images_no_reference"
            elif not z["usable"]:
                z["health_status"] = "image_quality_too_low"
            elif (z["_sha256"],z["file_name"],z["captured_at"])==(
                    meta.get("sha256"),meta.get("file_name"),meta.get("captured_at")):
                # The reference point at 100 is not a measured score.
                z["_is_reference"] = True
                z["health_status"] = "reference_photo_start_of_view"
            elif z["captured_at"] and meta.get("captured_at") and z["captured_at"]<meta["captured_at"]:
                z["health_status"] = "photo_before_reference"
            else:
                alignment = match_lighting(working_image,small_mask,reference_image,prior,allow_chroma=True)
                z["_lighting_info"] = alignment[2]
                f,lighting_flags = health_features(working_image,small_mask,reference_image,prior,alignment)
                add_flags(z,*lighting_flags)
                if f is None:
                    z["health_status"] = lighting_flags[0] if lighting_flags else "lighting_not_comparable"
                else:
                    affine = scene_data["matrix"]
                    structure = (not z["_clipped"] and not meta.get("clipped",False)
                                and abs(float(np.hypot(*affine[:,0]))-1)<.008
                                and abs(math.degrees(math.atan2(affine[1,0],affine[0,0])))<=1.)
                    assess_health(z,f,ref,allow_structure=structure)
            filename_stem = f"{number:05d}_{file_path.stem}"
            save_png(masks/(filename_stem+"_mask.png"),leaf_mask)
            try:
                sha = z["_sha256"]
                z["_leaf_geometry"] = twin_leaf_geometry(
                    image,leaf_mask,output_dir/"leaf_labels"/(sha+".png"),
                    leaf_points_path(output_dir,sha,calibration is not None))
            except (OSError,ValueError,cv2.error) as error:
                # An optional viewer geometry error must not discard the image measurement.
                z["_leaf_geometry"] = None
                print(f"Leaf contours unavailable: {file_path.name} ({error})")
            if z["_leaf_geometry"] is not None:
                z["visible_leaf_count"] = z["_leaf_geometry"]["count"]
                z["visible_leaf_count_method"] = z["_leaf_geometry"]["method"]
                note = z["_leaf_geometry"].get("note") or ""
                if note.startswith("Leaf annotations could not be used:"):
                    print(f"{file_path.name}: {note}")
            z["_output_stem"] = filename_stem
            generated_file.add(filename_stem)
            # Add the score to the overlay after smoothing the time series.
            z["_overlay_data"] = (image, leaf_mask) if len(paths) <= 5 else None
            labels = [health_status_label(code) for code in z['health_status'].split(';')]
            print(f"[{number}/{len(paths)}] {file_path.name}: {z['plant_pixels']} leaf pixels | {', '.join(labels)}")
        except (OSError, cv2.error, ValueError) as error:
            z["usable"] = False
            z["health_score"] = z["health_score_raw"] = None
            for k in SCORE_WEIGHTS:
                z["score_"+k] = None
            z["health_status"] = "analysis_failed"
            add_flags(z, "analysis_failed:"+str(error).splitlines()[0][:150])
            print(f"[{number}/{len(paths)}] {file_path.name}: {error}")
    if new_reference and not independent_images and primary_reference is None:
        raise ValueError("No suitable new reference. Previous results were kept.")
    reference_date = primary_reference["meta"].get("captured_at") if primary_reference else None
    reference_time = datetime.fromisoformat(reference_date.replace("Z","+00:00")) if reference_date else None
    growth_series(rows, reference_time)
    health_history(rows, prior_history)
    # Round once so that CSV, JSON and charts agree.
    for z in rows:
        for field, decimals in ROUNDING.items():
            if z.get(field) is not None:
                z[field] = round(float(z[field]), decimals)
        if z.get("_structure_score") is not None:
            z["_structure_score"] = round(z["_structure_score"],1)
        if z.get("mean_hue") == 180:
            z["mean_hue"] = 0.0  # Wrap circular hue to the range from 0 to below 180.
    for z, file_path in zip(rows, paths):
        if not z.get("_output_stem"):
            continue
        if z.get("_overlay_data") is not None:
            image, leaf_mask = z.pop("_overlay_data")
        else:
            original = Path(file_path).read_bytes()
            if hashlib.sha256(original).hexdigest() != z["_sha256"]:
                raise OSError(f"An input photo changed during analysis: {file_path}")
            image = cv2.imdecode(np.frombuffer(original,dtype=np.uint8),cv2.IMREAD_COLOR)
            if calibration is not None:
                image = undistort_image(image,calibration)
            leaf_mask = cv2.imdecode(np.fromfile(masks/(z["_output_stem"]+"_mask.png"),dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        review_overlay(image, leaf_mask, z, overlay/(z["_output_stem"]+"_overlay.png"))
    # Remove only previous previews generated by this program.
    for directory_path, suffix in [(masks, "_mask.png"), (overlay, "_overlay.png")]:
        for p in directory_path.glob("*"+suffix):
            if re.match(r"^\d{5}_", p.name) and p.name[:-len(suffix)] not in generated_file:
                p.unlink()
    merge_twin_views(history or [], rows)
    rows = merge_result_history(history or [], rows)
    csv_updated = save_results(rows,primary_reference,output_dir)
    if not csv_updated:
        raise PermissionError("Could not write the CSV. Previous results were kept.")
    plot_charts(rows,charts_folder)
    update_twin_model(rows, forecast_history, independent_images, twin_folder)
    save_chart_manifest(charts_folder)
    save_health(rows, health_folder, paths)
    return rows


def save_chart_manifest(directory_path):
    title = ("Leaf area", "Growth rate", "Leaf colour", "Plant health", "Health subscores")
    data = {"version": 1, "charts": [{"id": Path(name).stem[3:], "label": label, "file": name}
            for name, label in zip(CHART_FILES, title) if (directory_path/name).is_file()]}
    return write_json_output(directory_path/CHART_MANIFEST_FILE, data)


def charts_from_files(output_dir):
    "Reuse existing chart images and update the gallery manifest."
    output_dir = Path(output_dir).expanduser().resolve()
    target, previous = chart_directory(output_dir), output_dir/"charts"
    with lock_results(output_dir):
        validate_chart_directory(target)
        validate_chart_directory(previous)
        source = {name: next((directory_path/name for directory_path in (target, previous) if (directory_path/name).is_file()), None)
                  for name in CHART_FILES}
        if not any(source.values()):
            raise ValueError("No charts found. Run python computer_vision_pipeline.py images first.")
        work = Path(tempfile.mkdtemp(prefix=".biobox-charts-", dir=output_dir.parent))
        try:
            new = work/"charts"
            new.mkdir()
            migration = stage_legacy_charts(previous, target, work/"legacy-charts")
            files_to_publish = []
            for name, file_path in source.items():
                if file_path is not None:
                    shutil.copy2(file_path, new/name)
                    if file_path != target/name:
                        files_to_publish.append((new/name, target/name))
            save_chart_manifest(new)
            files_to_publish.append((new/CHART_MANIFEST_FILE, target/CHART_MANIFEST_FILE))
            if (target/OBSOLETE_TWIN_CHART).is_file():
                files_to_publish.append((None, target/OBSOLETE_TWIN_CHART))
            if any(file_path.is_dir() for _, file_path in files_to_publish):
                raise OSError("A folder occupies an expected output filename.")
            target.mkdir(parents=True, exist_ok=True)
            publish_files(files_to_publish+migration, work)
            remove_empty_chart_directory(previous, target)
        finally:
            if not (work/"keep_backup").exists():
                shutil.rmtree(work)
    return target/CHART_MANIFEST_FILE


def default_results_dir():
    "Prefer the current project's saved outputs without changing the camera folder."
    for directory_path in (Path.cwd(), PROJECT_DIR, IMAGES_DIR.parent):
        output_dir = directory_path/"results"
        if any(p.is_file() for p in (output_dir/"results.json", output_dir/"results.csv",
                                     viewer_directories(output_dir)[0]/TWIN_JSON_FILE,
                                     viewer_directories(output_dir)[1]/HEALTH_JSON_FILE)):
            return output_dir
    return IMAGES_DIR.parent/"results"


def open_charts(output_dir=None, no_browser=False):
    if output_dir is None:
        output_dir = next((directory_path/"results" for directory_path in (Path.cwd(), PROJECT_DIR, IMAGES_DIR.parent)
                        if any((directory/name).is_file() for name in CHART_FILES
                               for directory in (directory_path/"charts", directory_path/"results"/"charts"))),
                       default_results_dir())
    try:
        data = charts_from_files(output_dir)
        if no_browser:
            print("Chart data:", data)
        else:
            open_browser_view(output_dir, "charts", "Charts")
    except (OSError, ValueError) as error:
        print("Could not open the charts:", error)
        return 1
    return 0


def run_local_analysis(paths, output_dir, manual=None, independent_images=False,
                      new_reference=False, timestamp_file=None):
    capture_times = load_capture_times(timestamp_file) if timestamp_file else None
    if independent_images and capture_times:
        raise ValueError("--capture-times describes a single series. Do not combine it with --independent-images.")
    if capture_times and not any(Path(p).name in capture_times for p in paths):
        raise ValueError("No filename in the timestamp file matches the selected photos.")
    cv2.setNumThreads(2)
    return analyse_series(paths, output_dir, manual, independent_images, new_reference, capture_times)


def select_input_images(input_path=None):
    """Use the English photo directory, with a fallback during migration."""
    path = Path(input_path or IMAGES_DIR).expanduser().resolve()
    if path.is_file():
        return path, [path]
    images = find_images(path)
    legacy = path.parent / "bilder"
    if path.name == "images" and legacy.is_dir():
        current_names = {photo.name.casefold() for photo in images}
        # Once synced camera photos exist in the new folder, the old folder must
        # not bring camera imports back into the rolling window after pruning.
        has_synced_photos = any(is_camera_photo(photo) for photo in images)
        previous_images = [photo for photo in find_images(legacy) if photo.name.casefold() not in current_names
                           and not (has_synced_photos and is_camera_photo(photo))]
        if previous_images:
            print(f"Using {len(previous_images)} existing photos in {legacy}. Move them to images when ready.")
            images.extend(previous_images)
    return path, images


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory_path", nargs="?", metavar="IMAGE_OR_DIRECTORY", help="Photo or directory to analyse")
    parser.add_argument("--local", dest="local_path", metavar="PATH", help="Photo or directory to analyse")
    parser.add_argument("--output", dest="output_dir", type=Path, help="Output directory for the image series")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--charts", dest="charts", action="store_true", help="Open the existing charts")
    action.add_argument("--correct-mask", dest="mask_photo", type=Path, metavar="PHOTO",
                        help="Edit the mask for a source photo")
    action.add_argument("--scale-image", dest="scale_photo", type=Path, metavar="PHOTO",
                        help="Set the scale from a photo with a reference length")
    action.add_argument("--capture-scale", dest="capture_scale", action="store_true",
                        help="Take a new Pi photo for scale calibration")
    parser.add_argument("--mask-png", dest="mask_png", type=Path, metavar="PNG",
                        help="Import a binary PNG mask instead of opening the editor")
    parser.add_argument("--reference-mm", dest="reference_mm", type=float,
                        help="Known physical length in millimetres")
    parser.add_argument("--points", dest="points", type=float, nargs=4,
                        metavar=("X1", "Y1", "X2", "Y2"), help="Reference endpoints in image pixels")
    parser.add_argument("--no-browser", dest="no_browser", action="store_true",
                        help="With --charts, update chart data without opening a browser")
    parser.add_argument("--independent-images", dest="independent_images", action="store_true",
                        help="Analyse unrelated photos without treating them as a single series")
    parser.add_argument("--new-reference", dest="new_reference", action="store_true",
                        help="Require a suitable reference in the current photos")
    parser.add_argument("--capture-times", dest="capture_times_file", type=Path,
                        metavar="CSV", help="Known capture times by file name")
    parser.add_argument("--mm-per-pixel", dest="mm_per_px", type=float,
                        default=MANUAL_MM_PER_PIXEL, help="Verified millimetres per pixel")
    parser.add_argument("--sync", action="store_true",
                        help="Fetch completed Pi photos before analysing local images")
    args = parser.parse_args(argv)
    if args.mask_png and not args.mask_photo:
        parser.error("--mask-png requires --correct-mask PHOTO.")
    if args.scale_photo or args.capture_scale:
        if args.reference_mm is None or not math.isfinite(args.reference_mm) or args.reference_mm <= 0:
            parser.error("Provide a positive --reference-mm for scale calibration.")
    elif args.reference_mm is not None or args.points is not None:
        parser.error("--reference-mm and --points require --scale-image or --capture-scale.")
    if (args.charts or args.mask_photo or args.scale_photo or args.capture_scale) and (
            args.directory_path or args.local_path or args.capture_times_file or args.independent_images
            or args.new_reference or args.sync):
        parser.error("Run analysis, charts, mask correction, and scale calibration separately.")
    if args.sync and (args.directory_path or args.local_path or args.independent_images):
        parser.error("Use --sync without a custom input path or --independent-images.")
    if args.charts:
        return open_charts(args.output_dir, args.no_browser)
    if args.mask_photo or args.scale_photo or args.capture_scale:
        try:
            photo = args.mask_photo or args.scale_photo
            if args.capture_scale:
                from image_capture import sync_camera_photos, time_from_filename
                import tarfile
                try:
                    photos = sync_camera_photos(take_new_photo=True)
                except (RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
                    raise OSError(f"Pi capture failed: {error}") from error
                if not photos:
                    raise ValueError("No photo is available for scale calibration.")
                photo = max(photos, key=lambda p: (time_from_filename(p.name) or datetime.min.replace(tzinfo=timezone.utc), str(p)))
            photo = photo.expanduser().resolve()
            output_dir = Path(args.output_dir or photo.parent.parent/"results").expanduser().resolve()
            cv2.setNumThreads(2)
            with lock_results(output_dir):
                if args.mask_photo:
                    file_path = correct_mask(photo, output_dir, args.mask_png)
                    if file_path:
                        print(f"Mask correction saved: {file_path}")
                else:
                    set_ruler_scale(photo, args.reference_mm, output_dir, args.points)
        except (OSError, ValueError, cv2.error) as error:
            print("Could not save the correction or scale:", error)
            return 1
        return 0
    if args.mm_per_px is not None and (not math.isfinite(args.mm_per_px) or args.mm_per_px <= 0):
        parser.error("--mm-per-pixel must be positive and finite.")
    try:
        if args.sync and capture_cli(["--sync"]):
            print("Camera sync failed. Continuing with local photos.", flush=True)
        local_path, paths = select_input_images(args.local_path or args.directory_path)
        output_dir = args.output_dir or (local_path.parent.parent if local_path.is_file() else local_path.parent)/"results"
        if not paths:
            print(f"No images found in {local_path}. Existing results were kept.")
            return 1
        run_local_analysis(paths, output_dir, args.mm_per_px, args.independent_images,
                          args.new_reference, args.capture_times_file)
    except (OSError, ValueError) as error:
        print(f"Analysis stopped: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
