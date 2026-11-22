# BioBox · Plant Vision

BioBox follows one plant over time. A Raspberry Pi photographs it; a Python pipeline uses OpenCV to identify foliage, measure its visible area and track changes in colour. Each run updates the plant health dashboard, four charts and a rotatable digital twin of the latest capture.

This is the image analysis part of the BioBox diploma project at **HTL Shkodёr Peter Mahringer**. It runs locally and exports data for the wider BioBox platform.

## Everyday use

From any PowerShell window on the project laptop, run:

```powershell
python "$HOME\Documents\Diploma\computer_vision_pipeline.py" --sync
```

This retrieves completed photos from the Pi and processes the photos in `images/`. If the connection fails, the local analysis still runs. Omit `--sync` to process local photos only. The hourly timer on the Pi takes the photos; syncing does not trigger an extra capture.

After a run, open any of these HTML files in a browser. No server, internet connection or JSON selection is needed. Refresh an open tab after processing new photos.

| View | File in the project |
| --- | --- |
| Digital twin | [digital_twin/digital_twin_3d.html](digital_twin/digital_twin_3d.html) |
| Plant health | [plant_health/plant_health.html](plant_health/plant_health.html) |
| Charts | [charts/charts.html](charts/charts.html) |

Keep each page in its folder. Python writes a local display copy for the twin and health; the chart gallery uses the four PNGs. The JSON files remain available for the platform. The existing Python viewer commands still work.

## First run

In PowerShell:

```powershell
cd "$HOME\Documents\Diploma"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install opencv-contrib-python numpy matplotlib Pillow
```

Put photos of the **same plant** directly in `images/`, keep their capture timestamps and run `python computer_vision_pipeline.py`. A fixed camera angle makes area measurements easier to compare. For a set of unrelated photos, use `python computer_vision_pipeline.py images --independent-images --output sample_results` to keep those measurements separate. For the camera and hourly timer, see the [Raspberry Pi setup](docs/m1-image-capture-system.md).

## What the results mean

| Output | How to read it |
| --- | --- |
| `results/masks/` and `results/overlays/` | The mask shows the pixels counted as foliage. The purple outline lets you check that decision against the photo. Area measures the visible footprint; centimetres require a known length in the image. |
| `results/results.csv` and `results/results.json` | One measurement record per capture. The CSV is convenient for review; the JSON also carries geometry and quality flags. Older records remain when camera photos rotate out of the 100-photo collection. |
| Plant health | The score compares the plant with its own reference. A value near 100 means the visible features are similar. Lighting and camera changes can still limit comparisons. |
| Digital twin | Day zero opens on the latest source photo, cropped around the plant. Drag to rotate the measured leaf contours in 3D. **Reset view** restores the photographed angle and day zero. With enough comparable history, the slider projects growth forward from that capture. |

A new camera angle needs no code change. A single photo only records the surfaces facing that camera. To constrain depth with several views of the same plant, follow the [multi-angle capture instructions](docs/m4-digital-twin.md#add-photos-from-other-angles).

## Milestone guides

[M1 · Image capture](docs/m1-image-capture-system.md) · [M2 · Computer vision](docs/m2-computer-vision-pipeline.md) · [M3 · Plant health](docs/m3-plant-health-assessment.md) · [M4 · Digital twin](docs/m4-digital-twin.md)
