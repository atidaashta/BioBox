# BioBox: Computer Vision Pipeline and Measurement Reference

| Field | Value |
|---|---|
| Document ID | BB-REF-MERKMALE-001 |
| Milestone | A-M2 · Computer Vision Pipeline |
| Revision | 3.16 |
| Updated | 14 November 2026 |
| Institution | HTL Shkodёr Peter Mahringer |
| Implementation | `computer_vision_pipeline.py`; image analysis 4.13.0; health scoring 4.1.0 |

## 1. Inputs and outputs

The pipeline produces a record for each input image. An unreadable or unsuitable image receives an explicit status. Existing measurements are loaded first and merged with the new results. For the same photo in both JSON and CSV, the JSON takes precedence; records found only in the CSV are retained. When an image that was measured successfully becomes unreadable, the earlier usable measurement can be kept. A failure to extract optional contours for the digital twin does not discard the image measurements.

`results/results.csv` is a review table formatted for spreadsheet software with a semicolon separator, decimal commas, and a UTF-8 byte order mark. An unavailable value is marked `Nicht verfügbar`; its reason appears in `fehlende_werte`. A measured zero remains zero. The existing column names and status codes are retained so older exports can still be read.

`results/results.json` is the structured export. Measurements are numbers and flags such as `usable` are Booleans. Unavailable fields are omitted; the reasons are listed in `analysis.missing_values`. The CSV, JSON, and charts use the same rounded measurement values. Use the JSON as the starting point for a future platform integration.

## 2. CSV columns and JSON mappings

The table lists the 52 standard columns in export order. Extra columns from earlier CSV versions may be retained at the end.

| CSV column | Unit or type | Meaning | JSON mapping |
|---|---|---|---|
| `bild` | Text | Photo file name, including its extension | `image.file_name` |
| `captured_at` | UTC | Capture time with an explicit time zone; omitted if unknown | `image.captured_at` |
| `zeitquelle` | Text | `name`, `exif_mit_offset`, `zeitdatei`, or `unbekannt`; independent images use the unknown-time mode | `analysis.capture_time_source` |
| `stunden_seit_start` | h | Hours since the main reference in this run or the first known capture time | `analysis.hours_since_start` |
| `pflanzen_pixel` | pixels | White pixels in the final leaf mask | `image_measurements.plant_pixels` |
| `blattanteil_im_bild_pct` | % | Leaf pixels divided by all image pixels, multiplied by 100 | `analysis.pixel_measurement.leaf_coverage_pct` |
| `blattpixel_aenderung_pro_tag` | pixels/day | Direct change in leaf pixels per day at the same resolution, without geometric verification | `analysis.pixel_measurement.visible_pixel_change_per_day` |
| `pixel_vergleichsfoto` | Text | Earlier photo used to calculate direct pixel change | `analysis.pixel_measurement.reference_file` |
| `blattflaeche_cm2` | cm² | Visible projected area at a verified scale | `image_measurements.leaf_area_cm2` |
| `durchmesser_mm` | mm | Maximum extent of the masked area | `image_measurements.diameter_mm` |
| `kompaktheit` | unitless | Shape diagnostic: 4π × area / perimeter² | `image_measurements.compactness` |
| `wachstumsrate_cm2_pro_tag` | cm²/day | Difference between comparable areas, divided by the elapsed time in days | `image_measurements.growth_rate_cm2_per_day` |
| `wachstumsrate_pct_pro_tag` | %/day | Relative area change between comparable photographs, expressed per day | `image_measurements.growth_rate_pct_per_day` |
| `wachstum_vergleichsfoto` | Text | Earlier photograph used for the geometrically verified rate | `analysis.growth_reference_file` |
| `wachstum_abstand_stunden` | h | Elapsed time between the geometrically verified pair | `analysis.growth_interval_hours` |
| `mittel_r` | 0–255 | Mean raw red channel over the mask | `image_measurements.mean_r` |
| `mittel_g` | 0–255 | Mean raw green channel over the mask | `image_measurements.mean_g` |
| `mittel_b` | 0–255 | Mean raw blue channel over the mask | `image_measurements.mean_b` |
| `farbe_hex` | Text | Mean raw RGB colour as #RRGGBB | `image_measurements.color_hex` |
| `mittel_h` | 0 to below 180 | Circular mean of the HSV hue | `image_measurements.mean_hue` |
| `mittel_s` | 0–255 | Mean HSV saturation of the raw colours | `image_measurements.mean_saturation` |
| `gruenindex` | 0–1 | Mean normalised green fraction, G/(R + G + B) | `image_measurements.greenness_index` |
| `gelbanteil_pct` | % | Raw share of pixels in the technical yellow colour class | `image_measurements.yellow_fraction_pct` |
| `braunanteil_pct` | % | Raw share of pixels in the technical brown colour class | `image_measurements.brown_fraction_pct` |
| `mm_pro_pixel` | mm/pixel | Verified scale in the leaf plane | `image_measurements.mm_per_px` |
| `massstab_quelle` | Text | Source of the scale, or a reason it is unavailable, such as `nicht_kalibriert` | `image_measurements.scale_source` |
| `schaerfe` | diagnostic value | Variance of the Laplacian at leaf pixels in the source image | `image_measurements.sharpness` |
| `rauschen` | diagnostic value | Estimated noise in the source image | `image_measurements.noise` |
| `bildhelligkeit` | 0–255 | Mean greyscale level of the entire source image | `image_measurements.image_brightness` |
| `ueberbelichtet_pct` | % | Leaf pixels with at least one RGB channel at 254 or above | `image_measurements.overexposed_pct` |
| `groesste_komponente_pct` | % | Largest connected leaf region divided by the total mask area | `image_measurements.largest_component_pct` |
| `auffaelligkeit` | Text | Quality flags separated by semicolons | `image_measurements.quality_flags` |
| `brauchbar` | Boolean | Whether the image and mask meet the basic quality checks | `image_measurements.usable` |
| `fehlende_werte` | Text | Grouped reasons for unavailable values; the JSON gives a field-to-reason mapping | `analysis.missing_values` |
| `pipeline_version` | Text | Version of the segmentation and measurement methods | `image_measurements.pipeline_version` |
| `scoring_version` | Text | Version of the health scoring rules | `health_assessment.scoring_version` |
| `gesundheit` | 0–100 | Temporally smoothed relative condition score | `health_assessment.health_score` |
| `gesundheit_roh` | 0–100 | Unsmoothed score for this photo | `health_assessment.health_score_raw` |
| `gesundheit_kategorie` | Text | Technical score band | `health_assessment.health_category` |
| `gesundheit_status` | Text | Reason a score is available or unavailable, and its reference status | `health_assessment.health_status` |
| `gesundheit_trend_24h` | score points | Difference from a valid comparison in the same mode 22–26 hours earlier | `health_assessment.health_trend_24h` |
| `gesundheitswarnung` | Text | Visible changes, separated by semicolons | `health_assessment.health_warnings` |
| `ansicht` | integer | View number in this run; the JSON also records the reference checksum as the view ID | `analysis.view_number`; `analysis.view_id` |
| `gesundheit_referenzfoto` | Text | Reference photo for this camera view | `analysis.reference_file` |
| `score_gruen` | 0–100 | Colour distribution, normalised green fraction, and local CIELAB deviation | `health_assessment.score_green` |
| `score_gelb` | 0–100 | Increase in yellow or warm tones in shared leaf tissue or in verified colour distributions | `health_assessment.score_yellow` |
| `score_braun` | 0–100 | Increase in dark brown or warm tones | `health_assessment.score_brown` |
| `score_saettigung` | 0–100 | Saturation change after lighting correction | `health_assessment.score_saturation` |
| `score_farbton` | 0–100 | Hue and CIELAB colour change after lighting correction | `health_assessment.score_hue` |
| `durchmesser_px` | pixels | Maximum extent of the mask without a physical scale | `analysis.leaf_diameter_px` |
| `sichtbare_blaetter` | count | Number of detected or manually annotated visible leaves | `analysis.leaf_geometry.count` |
| `blattzaehlung_quelle` | Text | `estimated` for automatic estimates or `manual` for manually supplied labels | `analysis.leaf_geometry.method` |

## 3. How to interpret the measurements

### Area and shape

The pipeline reads the photograph and corrects lens distortion if a matching profile is available. It builds a binary leaf mask from colour cues, a verified image alignment where available, and refinement along the boundaries. A manually reviewed mask applies only to the matching original and lens profile. The overlay in `results/overlays/` shows which regions were measured. See [M1: Image Capture System](m1-image-capture-system.md) for the workflow.

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
python -B computer_vision_pipeline.py images --capture-times capture_times.csv
```

The legacy `bild` header is also accepted. `hours_since_start` is relative to the main reference for the current run, or to the first known capture time in the current selection. If the reference changes as older photos leave the local capture window, this origin can move. It is not a permanent measure of the plant's age.

A geometrically checked growth rate requires two usable photographs at least 30 minutes apart and a comparable view. The pipeline prefers an interval of at least 12 hours. It flags shorter intervals because small segmentation or leaf-position changes are amplified by daily normalisation. For a slightly shifted but alignable view, the two masks can be compared within the shared frame if at least 88% of each mask remains. A change exceeding 50% is flagged for review.

The relative rate divides the difference in comparable area by the older area and the elapsed time in days, then multiplies by 100. The absolute rate in cm²/day also requires a shared verified scale. The separate direct pixel change divides the raw difference in leaf pixel count by elapsed days at the same image resolution. That value can reflect camera movement or leaf orientation and is not evidence of biological growth on its own.

## 4. Missing values and statuses

| Situation | Export behaviour |
|---|---|
| Unreadable file | Status `datei_nicht_lesbar`; quality flag `nicht_lesbar`; no new measurements |
| Too little detected leaf tissue | Flag `keine_blattmaske`; no new health score |
| Excessive blur or noise | Quality flag; no new valid health score |
| No verified scale | Pixel and colour measurements may be available; cm² and mm are omitted |
| Unknown capture time | Individual measurements may be available; time-dependent values are omitted |
| Unsuitable reference or lighting | The status gives the reason; a score is exported only for a valid comparison |
| Reference photo for a view | Status `referenzfoto_start_der_ansicht`; a reference marker appears at 100, but no measured score or subscores are recorded |
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
| `02_growth_rate.png` | Geometrically checked rate, direct pixel change, and comparison status for each photo |
| `03_leaf_color.png` | Raw RGB measurements and yellow and brown fractions |
| `04_plant_health.png` | Relative score by photo, raw score where available, reference markers, and unavailable states |
| `05_health_subscores.png` | Heat map of the five colour subscores by photo |

Run `python -B computer_vision_pipeline.py --charts` to open the existing charts. The gallery reads `charts.json`; its HTML, CSS, and JavaScript are source files. In charts that show photo numbers, the sequence matches the result records. Photos with unknown capture times follow those with known times. An unavailable value has its own marker and is not drawn as zero.

## 7. Retention and reproducibility

After a successful transfer, the 100-photo retention rule applies only to recognised local camera JPEGs. The analysis matches reprocessed photos by name and SHA-256 checksum; older records without a checksum can also be matched by capture time. A historical record retains its measurements and reference metadata even after its source photo has left the local folder.

Current-run references and smoothing are rebuilt from the input images. Manual masks and the verified scale remain separate inputs. `analysis.pipeline_sha256` identifies the source revision of the four Python modules. Use a separate input folder, output folder, and `MESSREIHE` when starting a different plant series. The image analysis and health scoring versions are recorded separately.

## Implementation references

- [`computer_vision_pipeline.py`](../computer_vision_pipeline.py): segmentation, `SPALTEN`, `API_MESSFELDER`, `API_GESUNDHEIT`, result merging, and chart output.
- [`health_assessment.py`](../health_assessment.py): lighting correction and relative scoring.
- [`digital_twin.py`](../digital_twin.py): visible leaf geometry and projections.
