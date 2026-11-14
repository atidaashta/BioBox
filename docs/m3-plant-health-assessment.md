# BioBox: Plant Health Assessment

| Field | Value |
|---|---|
| Document ID | BB-SPEC-HEALTH-001 |
| Milestone | A-M3 · Plant Health Assessment |
| Revision | 1.14 |
| Updated | 14 November 2026 |
| Institution | HTL Shkodёr Peter Mahringer |
| Implementation | `health_assessment.py`; scoring version 4.1.0 |
| Status | Relative image-based condition index; biological validity has not yet been established |

## 1. Interpret the score

The score measures visible change relative to a reference photograph of **the same plant**. A value near 100 means that the measured features resemble the reference. A plant that was already damaged in the reference photograph can therefore still receive a high score. The score does not diagnose disease, identify the cause of stress, or measure chlorophyll directly.

The method does not assume that healthy basil must be dark green. Light or variegated foliage is compared with its own starting appearance. Images of different plants belong in separate series.

## 2. Select a reference for each camera view

The first usable photograph for each camera view in the current run becomes the reference. The pipeline keeps its image, mask, capture time, checksum, and geometry in memory. It does not persist an automatic reference image or mask between runs.

The chart places a reference marker at 100. This marker establishes the scale of comparison. The reference itself has no measured score or subscores, and its status is `referenzfoto_start_der_ansicht`. A subsequent usable photo can receive a score once a valid comparison is available.

An automatically selected reference is provisional (`vorlaeufige_referenz`). After review, `REFERENZ_FREIGEGEBEN = True` marks the main reference for that run as reviewed. It confirms the choice of reference. If the original reference is removed from the local capture window, a later run selects another suitable photo. Historical records retain their original reference; compare scores across a reference change with care. The reference file, timestamp, and checksum are recorded in `analysis.reference_file`, `analysis.reference_captured_at`, and `analysis.reference_sha256`.

Use a different input folder, output folder, and series identifier for another plant. The pipeline option `--new-reference` requires a usable reference in the current selection; if none can be established, existing results are preserved.

## 3. Compare like with like

1. **Align the camera view.** The pipeline matches features distributed across the background. If too few feature pairs are available, consistent edges in several background regions can confirm an unchanged view. A materially different view starts a separate reference series. Modest changes in scale or angle may still permit a colour comparison, although structure scoring can be withheld.
2. **Estimate the lighting correction.** The pipeline uses background pixels that are not overexposed and excludes leaf tissue. It tests a linear correction against a curved response and a gradual spatial gradient, using separate validation measurements and checking residual error by region. The correction is estimated again after segmentation.
3. **Check overlapping leaf tissue.** After each leaf mask is eroded by one working-image pixel, a position-by-position comparison needs at least 50 shared working pixels and overlap covering at least 60% of the smaller mask and 35% of the larger one. After very dark and clipped pixels are removed from both photos, at least 65% of the selected overlap and at least 50 working pixels must remain.

The correction does not force leaf colours towards a target. Raw colour measurements in the export remain lighting dependent. A lighting change that affects the leaves but not the background can still bias the result. Even light, stable camera settings, and a matte neutral reference area improve comparability.

### Partial comparison when brightness is unreliable

If the full lighting correction cannot be verified, the pipeline checks the blue-to-green and red-to-green ratios in suitable background regions. A colour comparison can proceed without brightness information when at least 30% of the shared leaf area falls inside verified regions. Brown and structure subscores are withheld; the available colour weights are rescaled. These comparisons use `farbverhaeltnis_teilflaeche` and are kept separate from full comparisons when calculating trends.

### Compare leaf colour distributions when leaves have shifted

With scoring version 4.1.0, a verified camera view and lighting check can support comparison of the two masks' colour distributions even when overlap is insufficient. This allows a comparison when leaves have moved or new leaves have appeared. The method uses colour distributions and quantile-based CIELAB differences; it does not treat pixels at unrelated positions as a direct pair.

Each image must retain at least 100 working pixels and 65% of its leaf mask core after unsuitable pixels are removed. For a colour-ratio comparison, verified lighting regions must cover at least 65% of each core. Structure is withheld for both distribution modes. The export uses `blattverteilung_normiert` for full lighting correction and `blattverteilung_chromatik` for a ratio-only comparison. The ratio-only mode also withholds the brown subscore.

## 4. Colour subscores

| Export field | Measurement | Weight within colour |
|---|---|---:|
| `score_green` | Colour distribution (42%), decline in normalised green fraction (26%), and local CIELAB deviation (32%) | 30% |
| `score_yellow` | Increase in yellow or warm tones; includes brown where full lighting correction is verified | 20% |
| `score_brown` | Increase in dark warm tones; the shared-pixel comparison also checks for a shift towards red | 25% |
| `score_saturation` | Logarithmic change in mean saturation | 15% |
| `score_hue` | Circular hue change and distance on the CIELAB colour axes | 10% |

The CIELAB colour comparison uses the a* and b* axes. Local departures can contribute to the score even when the mean leaf colour changes little. Given a non-negative deviation `d` and a half-score deviation `h`, the subscore is:

```text
Subscore = 100 × exp(−ln(2) × (d / h)²)
```

Where defined, a tolerance is subtracted before the formula is applied. A deviation within tolerance scores 100. For the yellow or warm fraction, the tolerance is 0.4 percentage points and the half-score deviation is 8 percentage points. For the brown fraction, the values are 0.3 and 4.5 percentage points. These thresholds describe the prototype's response; they are not biological probabilities.

## 5. Structure and the unsmoothed score

Structure contributes 15% only when camera geometry is sufficiently stable, full lighting correction is verified, common leaf pixels can be compared, and neither mask touches the image or analysis boundary. The colour weights are then scaled to total 85%. If those conditions are not met, the score uses the available colour evidence.

The structure component primarily responds to the loss of visible leaf area. Losses of up to 3.5% are tolerated. Compactness is a secondary factor and cannot lower the structure score without an area loss. New visible leaf growth is not automatically counted as damage.

The raw score combines a weighted arithmetic mean (65%) with a weighted geometric mean (35%). The geometric calculation uses an internal minimum of 0.01 for each component. This gives a weak subscore a meaningful effect without making it the sole determinant.

## 6. Smoothing, categories, and alerts

The raw score (`health_score_raw`) describes the current photo. The displayed `health_score` uses time-dependent exponential smoothing within the same camera view and comparison mode. The current score receives a weight of `1 − exp(−elapsed time / 2 hours)`, clamped to the interval 0.25–1.

The 24-hour trend is the difference from the closest valid comparison to 24 hours earlier within a 22–26 hour window, using the same view and mode. It is expressed in score points. If no suitable comparison exists, `health_trend_24h` is omitted from the JSON.

| Score | Dashboard label | Stored category |
|---|---|---|
| 85–100 | Very good | `sehr gut` |
| 70 to below 85 | Good | `gut` |
| 50 to below 70 | Monitor | `beobachten` |
| 30 to below 50 | Significant change | `auffaellig` |
| Below 30 | Critical | `kritisch` |
| No valid comparison | No score | `keine_daten` |

| Stored alert | Trigger |
|---|---|
| `farbveraenderung` | Local or quantile-based colour deviation reaches 7, histogram distance exceeds 0.25, or HSV hue changes by more than 10 units |
| `gelbanteil_gestiegen` | Yellow or warm fraction increases by at least 5 percentage points |
| `braunanteil_gestiegen` | Brown fraction increases by at least 2.5 percentage points under verified lighting |
| `saettigung_veraendert` | Logarithmic saturation deviation exceeds 0.22 |
| `sichtbare_blattflaeche_gesunken` | Visible area falls by more than 15% when structure comparison is permitted |

Alerts can be separated by semicolons. Lighting failures are recorded as quality or comparison statuses, not as plant damage. A failed transfer also does not lower the score: the pipeline can still analyse the local photographs.

## 7. Outputs and dashboard

The full output in `results/results.json` keeps `health_assessment` separate from `image_measurements`. See [M2](m2-computer-vision-pipeline.md) for field definitions. Unavailable scores are omitted and explained in `analysis.missing_values`. The CSV marks unavailable values as `Nicht verfügbar`; a measured zero remains zero. Historical scores and their provenance are retained even when the original photograph is no longer local.

Open the dashboard:

```powershell
python -B health_assessment.py
```

The browser automatically reads `plant_health/plant_health.json` from the local server. It displays the latest photo, smoothed score, five colour subscores, and raw leaf measurements. The raw score, 24-hour trend, quality flags, and lighting and reference details remain available in the full result files. Where an exact matching original or saved preview is available, it is displayed alongside the score. Health and subscore charts are also available in the chart gallery.

## 8. Validation and limits

Development checks used a BioBox photo, controlled exposure and colour changes, and a synthetic scene with known leaf boundaries. They covered changes in visible area, yellowing and browning, unsuitable lighting, changes in camera view, and missing measurements. These tests check behaviour under known conditions. The index still requires validation against a documented series of unmodified photographs with a reviewed reference and independently assessed changes.

## References

- [M1: Image Capture System](m1-image-capture-system.md)
- [M2: Computer Vision Pipeline and Measurement Reference](m2-computer-vision-pipeline.md)
- [OpenCV: Interactive foreground extraction with GrabCut](https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html)
- [OpenCV: Histogram comparison](https://docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html)
