"""label_scene on a synthetic scene: rafted pair, fast mover, wrong-length blob."""
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from src import autolabel

X0, Y0, RES = 600000.0, 6400000.0, 10.0
NAME = "S1A_IW_GRDH_1SDV_20260901T053953_20260901T054018_000000_000000_vv.tif"


def _lonlat(r, c):
    lon, lat = warp_transform("EPSG:32632", "EPSG:4326", [X0 + (c + .5) * RES], [Y0 - (r + .5) * RES])
    return lon[0], lat[0]


def _scene(tmp_path):
    rng = np.random.default_rng(0)
    img = rng.normal(100, 5, (300, 300)).clip(1).astype("uint16")
    img[100:105, 100:115] = 5000   # rafted pair A+B, one merged blob
    img[180:184, 195:205] = 5000   # C, displaced 800 m in azimuth from its AIS fix
    img[50:53, 250:255] = 5000     # D, 50 m blob for a 300 m AIS ship
    path = tmp_path / NAME
    with rasterio.open(path, "w", driver="GTiff", height=300, width=300, count=1, dtype="uint16",
                       crs="EPSG:32632", transform=from_origin(X0, Y0, RES, RES)) as dst:
        dst.write(img, 1)
    return path


def test_label_scene(tmp_path, monkeypatch):
    tif = _scene(tmp_path)
    fixes = []
    for mmsi, (r, c), sog, length in [(1, (102, 107), 0.2, 150), (2, (102, 107), 0.1, 140),
                                      (3, (260, 200), 15.0, 100), (4, (51, 252), 0.0, 300)]:
        lon, lat = _lonlat(r, c)
        fixes.append({"mmsi": mmsi, "lat": lat, "lon": lon, "sog": sog, "name": f"S{mmsi}",
                      "ship_type": "Tanker", "length": length})
    monkeypatch.setattr(autolabel, "ais_at", lambda *a, **k: pd.DataFrame(fixes))

    t = autolabel.scene_time(tif)
    events = pd.DataFrame([{"start": t - pd.Timedelta(hours=2), "end": t + pd.Timedelta(hours=2),
                            "mmsi_a": 1, "mmsi_b": 2, "name_a": "S1", "name_b": "S2",
                            "type_a": "Tanker", "type_b": "Tanker"}])
    boxes = autolabel.label_scene(tif, events)

    got = sorted(zip(boxes.cls, boxes.mmsi))
    # Pair labelled sts only; fast mover found despite 800 m offset; D rejected on length.
    assert got == [("sts", 1), ("vessel", 3)], got
    assert "len_ok" not in boxes and "pair" not in boxes


def test_search_grows_with_speed():
    assert autolabel.search_m(0) == autolabel.SEARCH_M
    assert autolabel.search_m(float("nan")) == autolabel.SEARCH_M
    assert autolabel.search_m(15) > 800 > autolabel.SEARCH_M
    assert autolabel.search_m(100) == autolabel.MAX_SEARCH_M
