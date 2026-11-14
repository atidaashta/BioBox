# BioBox: Image Capture System

| Field | Value |
|---|---|
| Document ID | BB-SPEC-IMG-001 |
| Milestone | A-M1 · Image Capture System |
| Revision | 1.9 |
| Updated | 14 November 2026 |
| Institution | HTL Shkodёr Peter Mahringer |
| Implementation | `image_capture.py`; image analysis 4.13.0 |
| Status | Capture and processing are implemented. The deployed capture settings and measurement accuracy still require verification. |

## 1. Measurement objective

The system measures the **visible projected leaf area of one plant**. The pot, substrate, supports, and background should be excluded, as should long, thin stems wherever they can be separated reliably. The system does not reconstruct overlapping or hidden parts of leaves. It can estimate the number of individually visible leaves, but one photograph cannot establish the plant's total leaf count or true three-dimensional leaf surface area.

Segmentation is not restricted to basil or a particular shade of green. The automatic method starts from colour cues typical of leaf tissue. Use a reviewed correction mask if unusual foliage or a similar-looking background defeats those cues.

## 2. Capture and transfer

| Component | Reference configuration |
|---|---|
| Capture device | Raspberry Pi 4 with a Camera Module 3 Wide, identified as `imx708_wide` |
| Capture helper | `/home/biobox/.local/bin/biobox-photo-test --single` |
| Completed session | `/home/biobox/Pictures/BioBox/recent/<session>/normal.jpg` |
| Previously recorded profile | 1920 × 1080 JPEG at quality 90; confirm the active profile on the device |
| Capture time | UTC timestamp in the session name; incomplete `.pending-*` sessions are ignored |

The local script uses OpenSSH over the existing Tailscale connection. Set `PI_ADRESSE`, `PI_AUFNAHME`, `PI_FOTO_ORDNER`, and `PI_SSH_KEY` in `image_capture.py` if your setup differs. SSH runs with `BatchMode=yes`. If the key is protected by a passphrase, load it into the SSH agent before running the script.

### Schedule one photograph per hour

```powershell
python -B image_capture.py --schedule-hourly
```

The script first tests the camera. Only after the test succeeds does it install the marked BioBox entry in the Pi user's crontab. The schedule `0 * * * *` runs at the start of every hour according to the Pi clock. The Windows computer can be off. The Pi and its `cron` service must be running.

The installer backs up the previous crontab, replaces the BioBox entry on subsequent runs, and keeps unrelated entries. Older jobs that were added by hand are not removed automatically. The scheduled job and a direct calibration capture share a camera lock. A failed test leaves the existing schedule unchanged.

```powershell
python -B image_capture.py --schedule-status
python -B image_capture.py --disable-schedule
```

The hourly helper is stored at `~/.local/bin/biobox-hourly-capture.py`. Its log, last attempt record, and crontab backups are under `~/.local/state/BioBox/`. The helper does not need OpenCV on the Pi. To verify the installation, check the status after the next full hour and confirm that a new completed session contains a readable `normal.jpg`. Disabling the schedule preserves saved photos. An outage cannot be backfilled with photographs that were never taken.

### Retrieve and analyse photos

```powershell
python -B image_capture.py; python -B computer_vision_pipeline.py images
```

The capture script retrieves completed JPEGs without requesting another photograph. It reuses valid local copies and retains up to 100 imported camera photos, ordered by capture time. It prunes older camera imports only after a successful transfer. Manually added images, remote files, and saved measurement history are outside that limit. Camera logs and sidecar JSON files stay on the Pi.

The analysis step scans supported files directly in `images/`, including manually added photos. It still runs after an SSH or transfer failure. If no local photos are available, the previous results are preserved. To fetch files without analysing them, run `python -B image_capture.py` on its own.

## 3. Camera placement and lighting

Place one plant in view and hold the camera and pot in fixed positions for a measurement series. A view close to perpendicular to the leaf plane improves the comparability of projected measurements. Avoid obstructions, use a matte background, and include a neutral area outside the leaves for lighting checks.

An earlier bench report recorded 373 mm between the camera plane and the substrate plane (815 mm − 442 mm). This is a setup dimension. Measure the actual distance to the leaves on the deployed rig before deriving a scale. Check exposure, gain, white balance, and focus before adopting a fixed profile. Any scheduled lighting state must be coordinated with the firmware.

## 4. Leaf masks and overlays

1. The original image is read and geometrically corrected if a matching lens profile is available. The working image is at most 960 pixels wide.
2. Leaf seed regions are selected using the green–red and blue–yellow axes of CIELAB. A constrained Otsu threshold supplies a starting point. Cool-coloured supports and dark areas with little green are suppressed.
3. Segmentation expands near the leaf seeds. Previously aligned leaf regions can help preserve yellowing or browning tissue where it remains connected to current leaf evidence.
4. Small enclosed gaps are closed, and thin connections far from broad leaf regions are removed. GrabCut then checks uncertain boundaries in a narrow band on the original image.
5. The binary mask uses the source image dimensions: white (255) denotes measured leaf pixels and black (0) denotes excluded areas. The pipeline counts the white pixels directly.

The overlay in `results/overlays/` marks the mask with a thin outline and light tint. The displayed photo is at most 1,500 pixels wide. Narrow leaf tips, stems, and backgrounds with leaf-like colours remain difficult cases. When the mask touches a frame or crop boundary, the pipeline can still compare visible area in a confirmed common frame, but whole-plant structure scoring is withheld.

### Correct a mask

```powershell
python -B computer_vision_pipeline.py --correct-mask images/photo.jpg
```

Left-click or drag to add leaf pixels; use the right mouse button to remove background pixels. Press `G` to rerun GrabCut with the marks, `+` or `-` to change brush size, `U` to undo, or `R` to reset. Enter saves the correction; Esc closes the window without saving.

To import an already reviewed binary PNG with the exact dimensions of the source image after any lens correction:

```powershell
python -B computer_vision_pipeline.py --correct-mask images/photo.jpg --mask-png reviewed_mask.png
```

The correction is stored in `results/mask_corrections/` and associated with the source photo's SHA-256 checksum and lens profile. The next analysis uses it for that photo only. Automatic masks, overlays, and charts are regenerated on every run. The pipeline retains existing measurements where the original is no longer local and preserves the last complete output if a write fails.

## 5. Scale and lens calibration

Pixel count is always measured from the final mask when it is readable. Physical measurements require a verified scale `s` in millimetres per pixel:

```text
s [mm/pixel]     = known distance [mm] / distance between the marked endpoints [pixels]
Leaf area [cm²]  = leaf pixels × s² / 100
Diameter [mm]    = largest extent of the masked area [pixels] × s
```

Place a ruler in the leaf plane. Mark the two endpoints of a known distance in a saved photograph:

```powershell
python -B computer_vision_pipeline.py --scale-image images/photo.jpg --reference-mm 50
```

Use the actual distance; 50 mm is an example. `--capture-scale --reference-mm 50` triggers a new Pi photograph for the same operation. The scale is saved as `results/scale_reference.npz` and reused only for a matching camera view and lens profile. Recheck it if camera height or leaf height changes. Leaves at different heights or angles are measured only approximately with a single planar reference. Without a verified scale, physical dimensions are omitted; pixel measurements remain available.

The alternative marker workflow needs four ArUco markers with IDs 0–3, a known marker side length, and known camera, marker, and leaf heights.

The wide lens can be calibrated using checkerboard photos taken at different positions in the frame. The configured pattern has 9 × 6 inner corners; the real square size must match `FELD_MM`.

```powershell
python -B image_capture.py --calibrate calibration_images
```

The resulting `camera_calibration.json` stores the camera matrix, distortion coefficients, and calibration image size. Rescaling is supported for the same aspect ratio. A different crop, field of view, or lens requires a new check.

## 6. Interfaces and validation

Health comparisons use lighting correction derived from matched background pixels. The export retains raw colour measurements. When too little comparable tissue or usable background remains, a health score is withheld. See [M3: Plant Health Assessment](m3-plant-health-assessment.md).

For recognised Pi imports, the JSON includes a relative storage path such as `recent/20261020T160551Z-bByql4/normal.jpg`. Confirm the eventual server path, device identifier, and HTTP contract before platform integration. The pipeline currently writes local files and does not send measurement records to a platform endpoint.

Development checks used original photos, controlled image changes, and a simulated Pi timeout. The deployed hourly job, active capture profile, and transfer should be checked on the Pi. Establish physical measurement accuracy using original photographs, independently reviewed masks, and a verified scale.

## References

- [M2: Computer Vision Pipeline and Measurement Reference](m2-computer-vision-pipeline.md)
- [OpenCV: Interactive foreground extraction with GrabCut](https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html)
- [Debian: crontab format](https://manpages.debian.org/trixie/cron/crontab.5.en.html)
- [Microsoft: OpenSSH key management on Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)
