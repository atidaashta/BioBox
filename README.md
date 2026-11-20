# BioBox · Plant Vision

BioBox follows the same plant from one photograph to the next. A Raspberry Pi takes the photos; a Python pipeline uses OpenCV to separate the foliage from its background. The results can be explored in three local browser views: a rotatable digital twin, a plant health dashboard, and a chart gallery.

This repository contains the image analysis part of the BioBox diploma project at **HTL Shkodёr Peter Mahringer**. The structured results can be passed to the wider BioBox platform; the pipeline itself works without a database connection.

![The photo mask fills 57.0% of the canopy box. Smooth blade profiles fill 40.3%; keeping the full measured contours gives 56.5%.](docs/canopy-comparison.png)

## Everyday use

From the project folder, run:

```powershell
python computer_vision_pipeline.py --sync
```

This retrieves completed Raspberry Pi photos, then updates the masks, overlays, measurement history, charts, health assessment, and digital twin. If the Pi is offline, analysis continues with the photos already in `images/`. To work entirely offline, use the same command without `--sync`.

| Open a view | Command | What to look for |
|---|---|---|
| Digital twin | `python digital_twin.py` | The latest plant from the camera angle. Drag to rotate, double-click to return, or move the day slider to explore projected growth. |
| Plant health | `python health_assessment.py` | The latest photo and how its visible condition compares with the plant’s own reference. |
| Charts | `python computer_vision_pipeline.py --charts` | Leaf area, leaf colour, plant health, and the individual health scores across captures. |

The pipeline prepares all three views in one run. Open just the one you want to see. The browser loads its local JSON automatically.

## First run on Windows

Open PowerShell in the repository root. For a project kept in `Documents\Diploma`:

```powershell
cd "$HOME\Documents\Diploma"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install opencv-contrib-python numpy matplotlib Pillow
```

Place photos of one plant directly in `images/` and run `python computer_vision_pipeline.py`. Use a fixed camera position and preserve capture times. For photos of **unrelated plants**, run `python computer_vision_pipeline.py images --independent-images --output sample_results` to keep them out of the main plant’s history.

For hourly capture, follow the [Raspberry Pi setup](docs/m1-image-capture-system.md). The Pi takes the photos on its own schedule. Running `--sync` retrieves them; it does not take an extra photograph.

## Read the results

- **Check the mask first.** `results/masks/` contains the pixels counted as foliage. Open the matching photo in `results/overlays/` to see the purple boundary. If the mask includes the pot or misses a leaf, the area and twin inherit that error.
- **Read area in context.** Leaf area is the visible footprint in pixels. A leaf turning towards the camera can increase that footprint without growing. Physical units need a known length in the same plane as the leaves.
- **Follow the health trend.** BioBox compensates for lighting where possible and checks whether changes persist. A score near 100 means the visible features are close to the reference. Measurements that cannot be compared are marked unavailable.
- **Use day zero as the reference.** The twin preserves visible leaf pieces and the gaps between them. Rotated surfaces, hidden depth, and future growth are estimates. The day slider stays off until there is enough comparable history.

`results/results.csv` is the table for review; `results/results.json` contains the same captures with measurement details, quality flags, and geometry. Older measurements stay in the history when camera photos rotate out of the local 100-photo collection. Each viewer keeps its own display data beside its HTML, CSS, and JavaScript.

## Milestone guides

[M1 · Image capture](docs/m1-image-capture-system.md) · [M2 · Computer vision](docs/m2-computer-vision-pipeline.md) · [M3 · Plant health](docs/m3-plant-health-assessment.md) · [M4 · Digital twin](docs/m4-digital-twin.md)
