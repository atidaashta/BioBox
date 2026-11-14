# BioBox: Image Capture and Plant Analysis

BioBox is a diploma project at **HTL Shkodёr Peter Mahringer**. This repository covers the camera and image analysis work: it retrieves photographs from a Raspberry Pi, measures visible plant features, and presents the results in charts, a plant health dashboard, and a browser-based digital twin.

**Status:** Working prototype under validation. Image analysis is at version 4.13.0 and health scoring is at version 4.1.0. The tools work locally; sending the measurements to the BioBox platform is planned.

## Quick start

Run these commands from the repository root in PowerShell. The folder can keep its current name, `Diploma`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install opencv-contrib-python numpy matplotlib Pillow
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` instead of `python` in the following commands. Use a desktop OpenCV build for interactive mask editing and scale calibration.

To **retrieve the latest completed Pi photos and update all outputs**:

```powershell
python -B image_capture.py; python -B computer_vision_pipeline.py images
```

The second command still runs if the Pi is unreachable. It reads all supported images in `images/` and updates the masks, overlays, charts, measurement history, and JSON used by both browser views. The `-B` option prevents Python from writing `__pycache__` files. The commands do not trigger an extra photograph.

To use local photos only:

```powershell
python -B computer_vision_pipeline.py images
```

The pipeline reads JPG, JPEG, PNG, BMP, TIFF, and WebP files directly inside the selected folder. It also accepts a single image path. Use `--output PATH` for a separate output directory, or `--independent-images` for photographs of unrelated plants:

```powershell
python -B computer_vision_pipeline.py sample_images --independent-images --output sample_results
```

That mode produces individual measurements without treating the photos as a shared health or growth series.

## Project layout

| Path | Purpose |
|---|---|
| `image_capture.py` | M1: Pi photo retrieval, hourly scheduling, lens calibration, and capture timestamps |
| `computer_vision_pipeline.py` | M2: segmentation, measurements, CSV and JSON exports, charts, and the local viewer server |
| `health_assessment.py` | M3: lighting correction, the relative health score, and the health dashboard |
| `digital_twin.py` | M4: visible leaf geometry, the 24-hour projection, and the 3D viewer |
| `images/` | Original photos and retrieved camera JPEGs |
| `results/` | Measurement history in `results.csv` and `results.json`; generated images in `masks/` and `overlays/` |
| `digital_twin/` | 3D viewer source files and generated `digital_twin.json` |
| `plant_health/` | Health dashboard source files and generated `plant_health.json` |
| `charts/` | Chart gallery source files, five generated PNG charts, and `charts.json` |
| `docs/` | English technical documentation for the four milestones |
| `.gitattributes` | Line endings and classification of generated files |

If upgrading from the German layout, follow the [migration instructions](docs/migrate-to-english-layout.md) before running the new scripts. Move existing data rather than starting with empty folders, so the pipeline can carry forward the measurements and projections already saved.

## Raspberry Pi capture

The reference setup uses a Raspberry Pi 4 with a Camera Module 3 Wide. The existing `biobox-photo-test` helper must be available on the Pi, and the analysis computer needs an OpenSSH client and access to the Pi, normally through Tailscale. Configure `PI_ADRESSE`, `PI_AUFNAHME`, and `PI_SSH_KEY` in `image_capture.py` to match your setup. SSH runs in batch mode; if the private key has a passphrase, load it into your SSH agent first. Keep private keys outside the repository.

Run `python -B image_capture.py --schedule-hourly` to test the camera and set up the hourly job. The job runs on the Pi at the start of each hour, according to the Pi's clock. `--schedule-status` shows the last attempt, and `--disable-schedule` removes the BioBox job while keeping saved photos. The Pi must be running, and its `cron` service must be enabled. See [M1](docs/m1-image-capture-system.md) for the setup and verification details.

A successful sync keeps up to 100 of the latest imported camera JPEGs locally. This limit does not apply to manually added images or saved measurements. The Pi keeps its own copies.

## Browser views

Run the command for the view you want. Each starts a server on the current computer and loads the appropriate JSON automatically. An internet connection and a Pi connection are unnecessary once the data is available.

| View | Command | What it shows |
|---|---|---|
| Digital twin | `python -B digital_twin.py` | A rotatable model derived from the latest photo, individual visible leaves, and a 0–14 day scenario slider |
| Plant health | `python -B health_assessment.py` | The latest photo, relative score, five colour subscores, and raw leaf measurements |
| Charts | `python -B computer_vision_pipeline.py --charts` | Leaf area, growth rate, leaf colour, health score, and health subscores |

Use these commands instead of opening the HTML files directly. On a local `file:` URL, the browser does not allow the page to fetch its neighbouring JSON automatically. If a series was saved to a custom output folder, pass the same `--output PATH` when opening its view. The browser server listens on `127.0.0.1` and stops after 15 minutes without requests.

The HTML, CSS, and JavaScript files are source files. Running the analysis updates the data and PNG charts alongside them. The [digital twin guide](docs/m4-digital-twin.md) explains the difference between the scenario slider and the separate 24-hour projection.

## Measurement and validation

- **Leaf area:** OpenCV segments visible leaf tissue in the camera image. The final binary mask provides a pixel count. A verified scale in the leaf plane is needed for cm² or mm. Occlusion and leaf orientation can change the projected area even when the plant has not grown.
- **Plant health:** The score ranges from 0 to 100 and compares the plant with its own reference photo. A value near 100 means the measured features are similar to the reference. It does not identify disease or establish that the plant is healthy.
- **Growth:** A geometrically checked rate requires usable, comparable views and capture timestamps. Comparisons start at 30 minutes and prefer intervals of at least 12 hours. Direct changes in leaf pixel count appear separately, including when they cannot be treated as growth.
- **Data quality:** Unknown measurements remain unknown. The JSON export records reasons in `analysis.missing_values`; the CSV uses `Nicht verfügbar` and the `fehlende_werte` column. The existing column names and machine-readable status codes are retained for compatibility.

To correct the mask for one photo or set a scale from a ruler at leaf height:

```powershell
python -B computer_vision_pipeline.py --correct-mask images/photo.jpg
python -B computer_vision_pipeline.py --scale-image images/photo.jpg --reference-mm 50
```

Replace `photo.jpg` and the example `50` with your file name and the actual distance between the marked points. Rerun the analysis after either operation. A stored mask correction is reused only for the matching source image and lens profile. Instructions for importing a mask, setting a scale, and calibrating the lens are in [M1](docs/m1-image-capture-system.md).

Use actual capture times, rather than file modification times. If a photograph's timestamp is known but missing from its name or EXIF metadata, provide it with `--capture-times capture_times.csv`. See [M2](docs/m2-computer-vision-pipeline.md) for the format, export field definitions, and how existing results are merged.

Local development checks covered real photos, simulated lighting changes, manually introduced colour changes, and a simulated Pi timeout. The final installation still needs checks for the camera position, physical scale, segmentation accuracy, and consistency of the health score on an observed plant. The 3D reconstruction approximates depth and does not reconstruct hidden leaves. The current projection is not a model of the effect of watering, light, or other interventions.

## Technical documentation

| Milestone | Document |
|---|---|
| M1 | [Image Capture System](docs/m1-image-capture-system.md) |
| M2 | [Computer Vision Pipeline and Measurement Reference](docs/m2-computer-vision-pipeline.md) |
| M3 | [Plant Health Assessment](docs/m3-plant-health-assessment.md) |
| M4 | [Digital Twin and 3D Viewer](docs/m4-digital-twin.md) |

Use a separate series identifier (`MESSREIHE`) and output folder for another plant. Configure the region of interest and scale in `computer_vision_pipeline.py`, reference review and score weights in `health_assessment.py`, and the camera view and projection thresholds in `digital_twin.py`. Run any of the four scripts with `--help` to see its options.

Future work includes testing the deployed capture schedule and measurement accuracy, validating the condition score over a documented plant series, and agreeing on the device identifiers, image paths, and HTTP contract for platform integration.
