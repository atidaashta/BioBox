# BioBox: Digital Twin and 3D Viewer

| Field | Value |
|---|---|
| Document ID | BB-GUIDE-TWIN-001 |
| Milestone | A-M4 · Digital Twin |
| Revision | 1.14 |
| Updated | 14 November 2026 |
| Institution | HTL Shkodёr Peter Mahringer |
| Implementation | `digital_twin.py`; model 0.1.0; viewer 0.7.0 |
| Status | Prototype for local visualisation, scenarios, and short-term projection |

## 1. Open the viewer

Run these commands from the project root:

```powershell
python -B computer_vision_pipeline.py images
python -B digital_twin.py
```

Skip the first command if the saved measurements are already current. The second opens a browser view on the current computer and automatically loads `digital_twin/digital_twin.json`. Opening the HTML file directly is suitable only if you select the JSON yourself, because the browser restricts automatic reads from neighbouring local files.

To refresh the viewer data from saved measurements without taking a photograph or rerunning the image analysis:

```powershell
python -B digital_twin.py --from-json results/results.json
```

If the results came from an older version and do not contain usable contours, rerun the pipeline on the original images. The saved data alone cannot reconstruct contours that were never exported.

## 2. Inspect the plant and visible leaves

The viewer uses the most recent photograph by capture time. If its contours are usable, drag with a mouse, use a touch gesture, or press the arrow keys to rotate the model. Double-click or press Home to restore the initial view.

**Count leaves** displays the individual visible regions as numbered tiles. The `≈` symbol identifies an automatic estimate. **Back to plant** restores the model. If the photograph does not supply usable contours, the viewer reports that condition instead of drawing a substitute plant.

For each visible region, the model approximates position, length, width, orientation, contour, and colour. Depth, stems, and curvature are modelled. Set `TWIN_FOTOANSICHT = "oben"` in `digital_twin.py` for an overhead camera; the default is a side view. One photograph cannot reveal hidden leaves or provide a full geometric measurement of the plant.

### Review the leaf count

If the automatic segmentation merges or splits leaves, click one point inside each visible leaf in the original image:

```powershell
python -B digital_twin.py --mark-leaves images/photo.jpg
python -B computer_vision_pipeline.py images
```

Right-click or press `U` to remove the last point, press `R` to clear all points, or use `F` to switch between the cropped view and the full image. Enter saves the markings. A point clearly outside the measurement mask is rejected; review the point or the mask. A valid imported greyscale label image takes precedence:

```powershell
python -B digital_twin.py --leaf-labels images/photo.jpg leaf_labels.png
```

The label image must match the dimensions of the image used for analysis and may contain up to 200 distinct leaf IDs. Markings affect the displayed regions and count. They do not replace the overall mask used for area or health measurements.

## 3. Distinguish scenarios from projections

### Scenario slider: 0 to 14 days

The slider displays a scaled version of the photographed plant. If a verified change rate is available from a comparison at least 12 hours apart, the viewer can use that rate. Otherwise it uses a 2% daily growth assumption. The applied visual scaling is bounded. The slider does not modify measurements, estimate a new leaf count, or predict the exact appearance of the plant.

### Separate model: projected visible area in 24 hours

The Python model projects visible leaf area in pixels using comparable photographs. `digital_twin.json` stores the current observation in `state`, the result in `forecast`, and the reason when a projection cannot be produced.

| Check | Requirement |
|---|---|
| Comparison group | Same plant series, verified camera view, image size, lens profile, and analysis fingerprint |
| Training period | Up to 72 hours before the last photo; at least six distinct capture times spanning at least 24 hours |
| Sampling | No more than six hours between consecutive training observations |
| Measurement quality | Reliable timestamps, positive measured area, usable masks, and a sufficiently stable camera; suspicious jumps are excluded |
| Recency | The last observation must be no more than three hours old for a current forecast; otherwise an available projection is marked historical |

The model fits a line to the measured pixels using the actual intervals between photos, then projects 24 hours from the latest capture time. The last observed value is the baseline. If at least three retrospective comparisons are available and the baseline's mean absolute error is no greater than the linear model's, the baseline is selected. The model also falls back to the baseline if the linear projection lies outside the image area.

A retrospective check uses earlier measurements to project an outcome and compares it with a later photo near the target time. A forecast issued in advance is recorded in `forecast_history` and is evaluated only when a later comparable measurement falls within 40 minutes of its target. The error is reported in leaf pixels. If the series is unsuitable, `forecast` is `null`; the measurements and 3D viewer remain available.

The current model cannot estimate the effect of a care intervention. That would require aligned records of sensor readings, interventions, and subsequent photographs.

## 4. Files

| Path | Role |
|---|---|
| `digital_twin/digital_twin_3d.html` | Viewer markup |
| `digital_twin/digital_twin_3d.css` | Viewer styling |
| `digital_twin/digital_twin_3d.js` | Data loading, 3D rendering, leaf tiles, and scenario slider |
| `digital_twin/digital_twin.json` | Latest observation, projection, forecast history, and data under `viewer` |
| `results/results.json` | Structured measurements and the original visible leaf geometry |
| `results/results.csv` | Measurement table for review |

Only generated data changes when the analysis runs. Refreshing the viewer from existing JSON does not recalculate the model or discard its forecast history. When moving from the previous repository layout, preserve the existing `digital_twin.json` as described in the [migration instructions](migrate-to-english-layout.md).

See [M2: Computer Vision Pipeline and Measurement Reference](m2-computer-vision-pipeline.md) for the geometry and measurement fields and [M3: Plant Health Assessment](m3-plant-health-assessment.md) for the interpretation of the condition score.
