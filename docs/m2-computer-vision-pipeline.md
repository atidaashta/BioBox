# BioBox: Computer Vision Pipeline and Measurement Reference

| Field | Value |
|---|---|
| Document ID | BB-REF-MERKMALE-001 |
| Milestone | A-M2 · Computer Vision Pipeline |
| Revision | 3.17 |
| Updated | 21 November 2026 |
| Institution | HTL Shkodёr Peter Mahringer |
| Implementation | `computer_vision_pipeline.py`; image analysis 4.13.0; health scoring 4.1.0 |

## 1. Inputs and outputs

The pipeline produces a record for each input image. An unreadable or unsuitable image receives an explicit status. Existing measurements are loaded first and merged with the new results. For the same photo in both JSON and CSV, the JSON takes precedence; records found only in the CSV are retained. When an image that was measured successfully becomes unreadable, the earlier usable measurement can be kept. A failure to extract optional contours for the digital twin does not discard the image measurements.

`results/results.csv` is a review table formatted for spreadsheet software with a semicolon separator, decimal points, and a UTF-8 byte order mark. An unavailable value is marked `Unavailable`; its reason appears in `missing_values`. A measured zero remains zero. Current column names and status codes are in English. The reader accepts the previous German headers and codes as well as decimal commas and preserves numerical measurements.

`results/results.json` is the structured export. Measurements are numbers and flags such as `usable` are Booleans. Unavailable fields are omitted; the reasons are listed in `analysis.missing_values`. The CSV, JSON, and charts use the same rounded measurement values. Use the JSON as the starting point for a future platform integration.

## 2. CSV columns and JSON mappings

The table lists the 52 standard English columns in export order. Extra columns from earlier CSV versions are retained under stable `legacy_field_…` names. The analysis preserves user-entered text and original filenames.

| CSV column | Unit or type | Meaning | JSON mapping |
|---|---|---|---|
| `file_name` | Text | Photo file name, including its extension | `image.file_name` |
| `captured_at` | UTC | Capture time with an explicit time zone; omitted if unknown | `image.captured_at` |
| `capture_time_source` | Text | `name`, `exif_with_offset`, `timestamp_file`, or `unknown`; independent images use the unknown-time mode | `analysis.capture_time_source` |
| `hours_since_start` | h | Hours since the main reference in this run or the first known capture time | `analysis.hours_since_start` |
| `plant_pixels` | pixels | White pixels in the final leaf mask | `image_measurements.plant_pixels` |
| `leaf_coverage_pct` | % | Leaf pixels divided by all image pixels, multiplied by 100 | `analysis.pixel_measurement.leaf_coverage_pct` |
| `visible_pixel_change_per_day` | pixels/day | Direct change in leaf pixels per day at the same resolution, without geometric verification | `analysis.pixel_measurement.visible_pixel_change_per_day` |
| `pixel_reference_file` | Text | Earlier photo used to calculate direct pixel change | `analysis.pixel_measurement.reference_file` |
| `leaf_area_cm2` | cm² | Visible projected area at a verified scale | `image_measurements.leaf_area_cm2` |
| `diameter_mm` | mm | Maximum extent of the masked area | `image_measurements.diameter_mm` |
| `compactness` | unitless | Shape diagnostic: 4π × area / perimeter² | `image_measurements.compactness` |
| `growth_rate_cm2_per_day` | cm²/day | Difference between comparable areas, divided by the elapsed time in days | `image_measurements.growth_rate_cm2_per_day` |
| `growth_rate_pct_per_day` | %/day | Relative area change between comparable photographs, expressed per day | `image_measurements.growth_rate_pct_per_day` |
| `growth_reference_file` | Text | Earlier photograph used for the geometrically verified rate | `analysis.growth_reference_file` |
| `growth_interval_hours` | h | Elapsed time between the geometrically verified pair | `analysis.growth_interval_hours` |
| `mean_r` | 0–255 | Mean raw red channel over the mask | `image_measurements.mean_r` |
| `mean_g` | 0–255 | Mean raw green channel over the mask | `image_measurements.mean_g` |
| `mean_b` | 0–255 | Mean raw blue channel over the mask | `image_measurements.mean_b` |
| `color_hex` | Text | Mean raw RGB colour as #RRGGBB | `image_measurements.color_hex` |
| `mean_hue` | 0 to below 180 | Circular mean of the HSV hue | `image_measurements.mean_hue` |
| `mean_saturation` | 0–255 | Mean HSV saturation of the raw colours | `image_measurements.mean_saturation` |
| `greenness_index` | 0–1 | Mean normalised green fraction, G/(R + G + B) | `image_measurements.greenness_index` |
| `yellow_fraction_pct` | % | Raw share of pixels in the technical yellow colour class | `image_measurements.yellow_fraction_pct` |
| `brown_fraction_pct` | % | Raw share of pixels in the technical brown colour class | `image_measurements.brown_fraction_pct` |
| `mm_per_px` | mm/pixel | Verified scale in the leaf plane | `image_measurements.mm_per_px` |
| `scale_source` | Text | Source of the scale, or a reason it is unavailable, such as `not_calibrated` | `image_measurements.scale_source` |
| `sharpness` | diagnostic value | Variance of the Laplacian at leaf pixels in the source image | `image_measurements.sharpness` |
| `noise` | diagnostic value | Estimated noise in the source image | `image_measurements.noise` |
| `image_brightness` | 0–255 | Mean greyscale level of the entire source image | `image_measurements.image_brightness` |
| `overexposed_pct` | % | Leaf pixels with at least one RGB channel at 254 or above | `image_measurements.overexposed_pct` |
| `largest_component_pct` | % | Largest connected leaf region divided by the total mask area | `image_measurements.largest_component_pct` |
| `quality_flags` | Text | Quality flags separated by semicolons | `image_measurements.quality_flags` |
| `usable` | Boolean | Whether the image and mask meet the basic quality checks | `image_measurements.usable` |
| `missing_values` | Text | Grouped reasons for unavailable values; the JSON gives a field-to-reason mapping | `analysis.missing_values` |
| `pipeline_version` | Text | Version of the segmentation and measurement methods | `image_measurements.pipeline_version` |
| `scoring_version` | Text | Version of the health scoring rules | `health_assessment.scoring_version` |
| `health_score` | 0–100 | Temporally smoothed relative condition score | `health_assessment.health_score` |
| `health_score_raw` | 0–100 | Unsmoothed score for this photo | `health_assessment.health_score_raw` |
| `health_category` | Text | Technical score band | `health_assessment.health_category` |
| `health_status` | Text | Reason a score is available or unavailable, and its reference status | `health_assessment.health_status` |
| `health_trend_24h` | score points | Difference from a valid comparison in the same mode 22–26 hours earlier | `health_assessment.health_trend_24h` |
| `health_warnings` | Text | Visible changes, separated by semicolons | `health_assessment.health_warnings` |
| `view_number` | integer | View number in this run; the JSON also records the reference checksum as the view ID | `analysis.view_number`; `analysis.view_id` |
| `health_reference_file` | Text | Reference photo for this camera view | `analysis.reference_file` |
| `score_green` | 0–100 | Colour distribution, normalised green fraction, and local CIELAB deviation | `health_assessment.score_green` |
| `score_yellow` | 0–100 | Increase in yellow or warm tones in shared leaf tissue or in verified colour distributions | `health_assessment.score_yellow` |
| `score_brown` | 0–100 | Increase in dark brown or warm tones | `health_assessment.score_brown` |
| `score_saturation` | 0–100 | Saturation change after lighting correction | `health_assessment.score_saturation` |
| `score_hue` | 0–100 | Hue and CIELAB colour change after lighting correction | `health_assessment.score_hue` |
| `leaf_diameter_px` | pixels | Maximum extent of the mask without a physical scale | `analysis.leaf_diameter_px` |
| `visible_leaf_count` | count | Number of detected or manually annotated visible leaves | `analysis.leaf_geometry.count` |
| `visible_leaf_count_method` | Text | `estimated` for automatic estimates or `manual` for manually supplied labels | `analysis.leaf_geometry.method` |

## 3. How to interpret the measurements

### Area and shape

The pipeline reads the photograph and corrects lens distortion if a matching profile is available. It builds a binary leaf mask from colour cues, a verified image alignment where available, and refinement along the boundaries. A manually reviewed mask applies only to the matching original and lens profile. The overlay in `results/overlays/` shows which regions were measured. See [M1: Image Capture System](m1-image-capture-system.md) for the workflow.

For a rotated photo with a matching profile, lens correction is applied in sensor coordinates before EXIF rotation. The image and camera matrix are rotated together so the mask, overlay and twin use the same pixels. An incompatible aspect ratio or mirrored orientation keeps the displayed image usable but does not supply calibrated camera geometry. Use the same lens, zoom and crop as the calibration when taking supporting views.

`plant_pixels` counts white pixels in the final mask. The measurement excludes gaps between leaves and does not approximate the plant as a convex hull. The physical area uses the square of the verified millimetres-per-pixel scale. The diameter is the greatest distance across the masked region, including the outer pixel boundaries. Without a scale, pixel measurements can still be available. A missing mask does not establish that the plant is absent.

Compactness is `4π × area / perimeter²`; the perimeter includes the detected regions and inner gaps. Changes in leaf orientation or segmentation can affect it. `largest_component_pct` is a diagnostic: separate visible leaves are normal, so a small largest component is not sufficient reason to reject an image.

### Colour and image quality

The mean RGB channels, circular mean HSV hue, mean saturation, and yellow and brown fractions are measured on the image within the final mask, after lens correction where applicable. These raw values depend on lighting. The lighting correction used in the health assessment does not overwrite them.

The green index is the mean normalised fraction `G / (R + G + B)`. It is not a measurement of chlorophyll. The yellow and brown fractions are technical colour classes and do not establish chlorosis or necrosis. The hex colour is another representation of the mean RGB colour. A hue can be absent when there is too little colour signal.

`usable` indicates that the image and mask passed basic quality checks. It does not guarantee a valid scale, capture time, or colour comparison. Raw sharpness and noise are exported as diagnostic values. Where a lighting correction succeeds, the pipeline uses the normalised working image for its sharpness decision. The raw overexposure fraction counts pixels with any RGB channel at 254 or above; the separate colour comparison applies its own checks to both images.

### Capture times and growth

Capture time comes from a timestamp in the file name, EXIF metadata with a time-zone offset, or a supplied timestamp table. The pipeline reports it in UTC. A download time or modification time is not used as a substitute.

For an image with a known capture time but no embedded timestamp, supply a CSV with one file name and an ISO 8601 timestamp with a time zone per row:

```csv
file_name;captured_at
photo.png;2026-11-12T10:30:00+01:00
```

```powershell
python computer_vision_pipeline.py images --capture-times capture_times.csv
```

Timestamp tables from the previous edition are accepted as well. `hours_since_start` is relative to the main reference for the current run, or to the first known capture time in the current selection. If the reference changes as older photos leave the local capture window, this origin can move. It is not a permanent measure of the plant's age.

A geometrically checked growth rate requires two usable photographs at least 30 minutes apart and a comparable view. The pipeline prefers an interval of at least 12 hours. It flags shorter intervals because small segmentation or leaf-position changes are amplified by daily normalisation. For a slightly shifted but alignable view, the two masks can be compared within the shared frame if at least 88% of each mask remains. A change exceeding 50% is flagged for review.

The relative rate divides the difference in comparable area by the older area and the elapsed time in days, then multiplies by 100. The absolute rate in cm²/day also requires a shared verified scale. The separate direct pixel change divides the raw difference in leaf pixel count by elapsed days at the same image resolution. That value can reflect camera movement or leaf orientation and is not evidence of biological growth on its own.

## 4. Missing values and statuses

| Situation | Export behaviour |
|---|---|
| Unreadable file | Status `image_unreadable`; quality flag `unreadable`; no new measurements |
| Too little detected leaf tissue | Flag `no_leaf_mask`; no new health score |
| Excessive blur or noise | Quality flag; no new valid health score |
| No verified scale | Pixel and colour measurements may be available; cm² and mm are omitted |
| Unknown capture time | Individual measurements may be available; time-dependent values are omitted |
| Unsuitable reference or lighting | The status gives the reason; a score is exported only for a valid comparison |
| Reference photo for a view | Status `reference_photo_start_of_view`; a reference marker appears at 100, but no measured score or subscores are recorded |
| Independent images | Individual measurements only; no combined health or growth series |
| Pi transfer fails | The local analysis can continue; the transfer failure does not change the plant score |
| Output is locked | The previous complete output is preserved or restored; if restoration is blocked, the console reports where the backup remains |

Quality flags are separated by semicolons. A mask touching the frame may rule out the structure subscore while still permitting a valid colour comparison. See [M3: Plant Health Assessment](m3-plant-health-assessment.md).

## 5. Structured data and provenance

| JSON section | Contents |
|---|---|
| `device_id` | Platform device identifier, omitted until a confirmed value is configured |
| `image` | File name, capture time, source checksum, and relative storage path where known |
| `image_measurements` | Area, extent, colour, quality, scale, and growth measurements |
| `health_assessment` | Relative score, subscores, category, status, trend, and scoring version |
| `analysis` | Mask source, reference metadata, lens and camera geometry, lighting correction, software fingerprint, and missing-value reasons |

For Pi imports, `image.storage_path` is derived from the session name as `recent/<session>/normal.jpg`. Other files have no server path until one is assigned. The current export uses `mm_per_px` and `image_brightness`, without duplicating them under the former aliases `mm_per_pixel` and `brightness`. Database identifiers and the HTTP contract remain to be agreed.

`analysis.view_id` is the SHA-256 checksum of the reference image. `twin_view_id` and `twin_camera_transform` can link a verified view across runs. `series_id` separates plant series, and `image_size` is stored as `[height, width]`. The common leaf fraction in `analysis.illumination.common_leaf_pct` is measured against the smaller mask after erosion. The pipeline records the geometrically checked growth comparison mode when a rate was calculated.

`analysis.leaf_geometry` stores visible contours in normalised image coordinates, mask width and height in pixels, and pixel area by visible leaf region. `method` distinguishes `estimated` from `manual`. Automatic separation starts from seed regions based on distance to the mask edge; colour boundaries can refine their assignment. A human can mark seed points or provide a greyscale label image. Those annotations affect the visible-leaf count and 3D viewer without changing the overall mask used for area and health measurements. See [M4: Digital Twin](m4-digital-twin.md).

## 6. Charts

| Generated file in `charts/` | Content |
|---|---|
| `01_leaf_area.png` | Visible projected area, in cm² when all usable observations have a verified scale, otherwise in pixels |
| `02_leaf_color.png` | Percentage of visible leaf area with yellow or brown tones in each photo. Lighting can affect these estimates. |
| `03_plant_health.png` | Relative score by photo, raw score where available, reference markers, and unavailable states |
| `04_health_subscores.png` | Heat map of the five colour subscores by photo |

Growth rates and raw RGB measurements remain in `results.csv` and `results.json`.

After analysis, double-click `charts/charts.html`. The local gallery finds the generated PNGs beside it. The optional `python computer_vision_pipeline.py --charts` launcher serves the same gallery using its JSON manifest. In charts that show photo numbers, the sequence matches the result records. Photos with unknown capture times follow those with known times. Unavailable values are left blank or marked as missing.

The same analysis publishes local display files for the other two views: `digital_twin/digital_twin.data.js` and `plant_health/plant_health.data.js`. They contain a snapshot of the exported data, not generated interface code. Keep them beside the matching HTML files; the API continues to use JSON. Refresh the page after a new analysis.

## 7. Retention and reproducibility

After a successful transfer, the 100-photo retention rule applies only to recognised local camera JPEGs. The analysis matches reprocessed photos by name and SHA-256 checksum; older records without a checksum can also be matched by capture time. A historical record retains its measurements and reference metadata even after its source photo has left the local folder.

Current-run references and smoothing are rebuilt from the input images. Manual masks and the verified scale remain separate inputs. `analysis.pipeline_sha256` identifies the source revision of the four Python modules. Use a separate input folder, output folder, and `SERIES_ID` when starting a different plant series. The image analysis and health scoring versions are recorded separately.

## Implementation references

- [`computer_vision_pipeline.py`](../computer_vision_pipeline.py): segmentation, `COLUMNS`, `API_MEASUREMENT_FIELDS`, `API_HEALTH_FIELDS`, result merging, and chart output.
- [`health_assessment.py`](../health_assessment.py): lighting correction and relative scoring.
- [`digital_twin.py`](../digital_twin.py): visible leaf geometry and projections.
