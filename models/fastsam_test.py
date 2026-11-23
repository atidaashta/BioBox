from pathlib import Path
from ultralytics import FastSAM

here = Path(__file__).resolve().parent      # ...\Diploma\models
project = here.parent                       # ...\Diploma

model = FastSAM(str(here / "FastSAM-s.pt"))
photo = project / "images" / "basil03_20250208T120005Z.png"
result = model(str(photo), retina_masks=True, imgsz=1024, conf=0.4, iou=0.9)[0]
print("Segments found:", len(result.masks))
result.save(str(here / "fastsam_test.jpg"))
