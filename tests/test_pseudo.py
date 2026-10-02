"""AIS-confirmed detections become labels; tiles with an unconfirmed ship are dropped."""
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from src import autolabel, pseudo


def test_only_clean_tiles_are_written(tmp_path):
    img = np.random.default_rng(0).normal(100, 5, (2048, 1024)).clip(1).astype("uint16")
    img[500:506, 485:515] = 5000          # tile 0: AIS-matched ship
    img[1500:1506, 485:515] = 5000        # tile 1: matched ship ...
    img[1700:1706, 300:330] = 5000        # ... and an unmatched one
    tif = tmp_path / "S1C_X_vv.tif"
    t = from_origin(0, 20480, 10, 10)
    with rasterio.open(tif, "w", driver="GTiff", height=2048, width=1024, count=1,
                       dtype="uint16", crs="EPSG:32640", transform=t) as dst:
        dst.write(img, 1)
    xy = lambda r, c: t * (c, r)
    det = pd.DataFrame([
        {"cls": "vessel", "category": "AIS_VISIBLE", **dict(zip("xy", xy(503, 500)))},
        {"cls": "vessel", "category": "AIS_VISIBLE", **dict(zip("xy", xy(1503, 500)))},
        {"cls": "vessel", "category": "AIS_UNMATCHED", **dict(zip("xy", xy(1703, 315)))},
    ])
    keep, skip = pseudo.boxes_for(det, tif)
    assert len(keep) == 2 and len(skip) == 1
    assert autolabel.tile_scene(tif, keep, out_dir=tmp_path / "t", skip=skip) == 1
    (label,) = (tmp_path / "t" / "labels").glob("*.txt")
    assert label.stem.endswith("_0_0") and len(label.read_text().splitlines()) == 1
