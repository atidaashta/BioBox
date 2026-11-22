# BioBox: Digital Twin and 3D Viewer

| Field | Value |
|---|---|
| Document ID | BB-GUIDE-TWIN-001 |
| Milestone | A-M4 · Digital Twin |
| Revision | 1.17 |
| Updated | 21 November 2026 |
| Institution | HTL Shkodёr Peter Mahringer |
| Implementation | `digital_twin.py`; model 0.2.0; viewer 1.0.0 |
| Status | Prototype for local visualisation, scenarios, and short-term projection |

## 1. Open the viewer

Run the pipeline from any PowerShell window on the project laptop:

```powershell
python "$HOME\Documents\Diploma\computer_vision_pipeline.py" --sync
```

Then double-click `digital_twin/digital_twin_3d.html`. The page loads its local data automatically, even offline. Keep the HTML, CSS, JavaScript and generated `digital_twin.data.js` together. If the page is already open, refresh it. To process only the photos on the laptop, omit `--sync`. The optional `python digital_twin.py` launcher still opens the same viewer through a local server.

To refresh the viewer data from saved measurements without taking a photograph or rerunning the image analysis:

```powershell
python digital_twin.py --from-json results/results.json
```

If the results came from an older version and do not contain usable contours, rerun the pipeline on the original images. The saved data alone cannot reconstruct contours that were never exported.

## 2. Inspect the plant and visible leaves

The viewer opens at day zero on the most recent capture by timestamp. When the original and its mask match the saved measurement, the opening view is a crop of the photograph itself. It uses the same lens correction and display orientation as the measurements. The crop is saved losslessly, downsampled only when its longer edge exceeds 1,536 pixels.

Drag, swipe or use the arrow keys on the plant to rotate. The **Reset view** button in the upper-left corner restores the original camera angle and day zero, and closes the leaf list. Double-click and the Home key do the same. **Count leaves** displays the detected visible regions as numbered tiles; `≈` identifies an automatic estimate, not a verified leaf count.

Away from the opening angle, each region retains its measured contour, interior gaps and photographed colour where available. Pieces of one region remain one numbered leaf. The reverse sides of leaves and the stems are estimates. A pot is included in the rotated model only when the image supports one. If only verified photo pixels survive, the viewer can show the capture without pretending its leaves can be rotated. If only measured outlines survive, it can render their shapes in their recorded colours.

No side-view or overhead setting is required. With a calibrated lens and a visible, horizontal reference marker, the program estimates camera tilt and roll from the marker [3]. Without one, it looks for a sufficiently clear pot rim or pot axis. If neither is reliable, rotation stays relative to the photograph. The back of a leaf and anything hidden behind it cannot be recovered from one picture.

**Checked with the project photos.** The decoded opening crop from the latest of ten basil captures matched its source pixels exactly; that crop did not need downsampling. Rotating and pressing Reset restored the same rendered view. These checks verify the camera-facing view, not hidden geometry or the automatic leaf count.

### Add photos from other angles

1. Choose one primary image for that observation. Put it directly in `images/`, as before. For a growth series, keeping this primary camera position consistent makes measurements easier to compare.
2. For depth from several angles, use one calibrated camera with the same lens, resolution mode and zoom. Place a flat ArUco marker (OpenCV dictionary `DICT_4X4_50`, ID 0 is a simple choice) on a horizontal surface beside the plant. Keep the marker and plant still and both visible. Move the camera, not the pot. To create the lens profile from checkerboard photos, run `python image_capture.py --calibrate path/to/checkerboard_photos` from the project folder.
3. Take a few different views within 15 minutes. Put **only these extra photos** in a folder named after the primary file without its extension, followed by `.views`. Keep capture times in the filenames where possible.

| Example path inside `images/` | Used for |
|---|---|
| `plant_20261121T120000Z.jpg` | Opening photograph and one growth observation |
| `plant_20261121T120000Z.views/left_20261121T120105Z.jpg` | Supporting angle from the same session |
| `plant_20261121T120000Z.views/right_20261121T120210Z.jpg` | A different supporting angle |

Rerun the usual pipeline command. The twin uses silhouettes from accepted views to narrow the possible depth of the foliage visible in the primary capture. Nearly identical views, ambiguous marker fits and conflicting silhouettes do not supply reliable depth. Extra views never become additional dates in the growth history. You can check which views were used under `viewer.latest.canopy.depth.supporting_views` in the twin JSON, when present. Single photos still work without calibration or a marker.

### Review the leaf count

If the automatic segmentation merges or splits leaves, click one point inside each visible leaf in the original image:

```powershell
python digital_twin.py --mark-leaves images/photo.jpg
python computer_vision_pipeline.py images
```

Right-click or press `U` to remove the last point, press `R` to clear all points, or use `F` to switch between the cropped view and the full image. Enter saves the markings. A point clearly outside the measurement mask is rejected; review the point or the mask. A valid imported greyscale label image takes precedence:

```powershell
python digital_twin.py --leaf-labels images/photo.jpg leaf_labels.png
```

The label image must match the dimensions of the image used for analysis and may contain up to 200 distinct leaf IDs. Markings affect the displayed regions and count. They do not replace the overall mask used for area or health measurements.

## 3. Growth from the measurement history

The slider uses the comparable records in `results/results.json`, including older measurements whose photographs have already been removed. This file is the saved measurement history and can also be supplied as an export from the database. The viewer does not connect directly to Edona's database. Running the image analysis or importing an updated results file rebuilds the growth model for the available records.

The newest capture is day zero. Future days are counted from that capture, including when an older dataset is being inspected. The slider is limited to half the observed time span, with a maximum of 14 days. No assumed 2% daily growth is used. If the history is too short, unsuitable, or consists of unrelated images, the captured plant remains available and the slider is disabled.

### How the trajectory is fitted

| Check | Requirement |
|---|---|
| Comparison group | Same plant series, aligned camera reference, image size, lens profile, and measurement version |
| History | Up to 28 days, at least four distinct photos spanning 48 hours |
| Sampling | Hourly and irregular daily series are supported. A gap over seven days starts a new training segment. |
| Geometry | Small aligned shifts are allowed; area is corrected for image scale. Large viewpoint changes and shifted clipped masks are rejected. |
| Measurement quality | Usable masks, reliable capture times, and positive area. Flagged jumps, repeated image hashes, and duplicate timestamps do not supply additional training evidence. |

Median pairwise slopes reduce the influence of isolated noisy observations. Daily medians prevent a day with many hourly captures from outweighing all earlier dates. Three candidates are compared: a robust linear trend, an exponential trend that gradually slows, and the last measured value. The slowing curve has a bounded horizon; it is not a fitted biological carrying capacity.

A rolling check fits only the records before an observation and predicts the next photo at its actual capture time. It does not shuffle dates or train on the photo being predicted. After at least three checks, the candidate with the lowest mean absolute area error is selected; near ties favour the slowing curve. With fewer checks, that curve remains provisional. Uncertainty bounds in the JSON are a heuristic based on past prediction errors and increase with the horizon; they are not statistical confidence intervals.

The ten-photo development series spans 23 days and permits six next-photo checks. In this run, the selected linear model had a mean absolute error of about 18,028 aligned leaf pixels, compared with 23,231 for the last-value baseline. These are retrospective results for this series, not a guarantee for another plant or future photos. The code refits the model when new records arrive.

### How the plant develops in the viewer

At day zero, the same measured leaf regions, proportions, positions, and count are used. The container stays fixed. Future development is allocated to the existing blades and estimated new leaves instead of magnifying the whole object:

- Smaller, higher blades receive more expansion than mature blades.
- Reliable changes in the photographed canopy width and height guide the shape. These are image-plane proportions, not measured 3D height.
- When a sufficiently stable count trend is available, new leaves emerge gradually near shoot tips. They appear as opposite pairs, with later nodes rotated by 90 degrees, matching basil's leaf arrangement [1].
- Young pairs begin folded and open along a smooth S-shaped maturation curve. Combining new organs with continuous expansion follows a common approach in plant development graphics [2].
- Captured regions retain the texture of the visible foliage when the photo is available. New, projected blades use curved surfaces with a midrib and veins because they have no photographed texture.

The area budget follows the selected trajectory. Count trends, maturity, stem topology, and hidden depth are estimates. A future leaf shown in the viewer is not a measured leaf. The count button uses `≈` for projected days and shows tiles for the visible model leaves at the selected day. A flat history stays flat; a declining area does not trigger new leaf pairs.

### Separate 24-hour projection and forecast audit

The Python model also writes a 24-hour area projection to `forecast`. It uses the same comparable history and candidate comparison. `state.fresh` and `forecast.is_current` distinguish a current capture from a historical projection. A current forecast requires a capture no more than three hours old and a target time still in the future. Older data does not become a live forecast merely because it is reprocessed.

Issued forecasts remain in `forecast_history`. Reopening the viewer or importing later records does not rewrite their original values. Later measurements can evaluate an issued forecast within its recorded target window. The error is in aligned reference-image pixels. The photographed area in `results.csv` and `results.json` is preserved unchanged.

Future watering, light, disease, pruning, hidden leaf counts, and treatment effects cannot be inferred from the photographs alone. These require suitable sensor and intervention records and further validation. A single-view illustration cannot establish the exact future 3D plant.

## 4. Files

| Path | Role |
|---|---|
| `digital_twin/digital_twin_3d.html` | Viewer markup |
| `digital_twin/digital_twin_3d.css` | Viewer styling |
| `digital_twin/digital_twin_3d.js` | Data loading, 3D rendering, leaf tiles, and scenario slider |
| `digital_twin/digital_twin.json` | Latest observation, projection, forecast history, and data under `viewer` |
| `digital_twin/digital_twin.data.js` | Generated local copy of the viewer data for opening the HTML directly |
| `results/results.json` | Structured measurements and the original visible leaf geometry |
| `results/results.csv` | Measurement table for review |

Only generated data changes when the analysis runs. The captured frame and masked leaf texture are embedded in the viewer data; there are no external texture downloads. Refreshing from the results history refits the current trajectory while preserving previously issued forecasts.

See [M2: Computer Vision Pipeline and Measurement Reference](m2-computer-vision-pipeline.md) for the geometry and measurement fields and [M3: Plant Health Assessment](m3-plant-health-assessment.md) for the interpretation of the condition score.

## 5. References

[1] North Carolina State University Extension, “Ocimum basilicum,” *Extension Gardener Plant Toolbox*. [Online]. Available: https://plants.ces.ncsu.edu/plants/ocimum-basilicum/. Accessed: 20 November 2026.

[2] P. Prusinkiewicz, M. S. Hammel, and E. Mjolsness, “Animation of Plant Development,” in *Proceedings of SIGGRAPH*, 1993, pp. 351–360. [Online]. Available: https://algorithmicbotany.org/papers/animdev.sig93.pdf.

[3] OpenCV, “Perspective-n-Point (PnP) pose computation.” [Online]. Available: https://docs.opencv.org/4.6.0/d5/d1f/calib3d_solvePnP.html.
