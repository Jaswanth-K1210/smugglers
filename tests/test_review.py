"""The T3 review sheet must stay blind: reviewer files never carry score, band, scene or AIS."""
import csv

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from src import review


def test_bands_and_sampling():
    assert [review.band_of(s) for s in (0.10, 0.149, 0.15, 0.3, 0.4, 0.95)] == \
        ["0.10-0.15", "0.10-0.15", "0.15-0.25", "0.25-0.40", "0.40-1.00", "0.40-1.00"]
    assert review.band_of(0.05) is None
    dets = [{"score": s, "scene": "S", "tif": "t", "x": 0, "y": 0, "lat": 0, "lon": 0, "length_m": 100}
            for s in [0.11] * 40 + [0.2] * 10 + [0.3] * 30 + [0.6] * 30]
    picked = review.sample(dets)
    assert picked.band.value_counts().to_dict() == {"0.10-0.15": 25, "0.15-0.25": 10, "0.25-0.40": 25, "0.40-1.00": 25}
    assert review.sample(dets).equals(picked)           # same seed, same sample


def test_fixed_stretch_does_not_depend_on_the_chip(tmp_path):
    tif = tmp_path / "s.tif"
    img = np.full((400, 400), 100, "uint16")
    img[100:104, 100:110] = 1500
    img[300:304, 300:310] = 600
    with rasterio.open(tif, "w", driver="GTiff", height=400, width=400, count=1, dtype="uint16",
                       crs="EPSG:32640", transform=from_origin(0, 4000, 10, 10)) as d:
        d.write(img, 1)
    from PIL import Image
    import io
    a = np.array(Image.open(io.BytesIO(review.chips(tif, 1050, 4000 - 1020)[0])))
    b = np.array(Image.open(io.BytesIO(review.chips(tif, 3050, 4000 - 3020)[0])))
    assert a[0, 0, 0] == b[0, 0, 0]                      # same sea DN -> same grey in both chips


def test_reviewer_files_are_blind(tmp_path):
    picked = pd.DataFrame([{"score": s, "band": review.band_of(s), "scene": f"S1A_SECRET_{k}", "lat": 25.1,
                            "lon": 56.5, "length_m": 200, "tif": "t", "x": 0, "y": 0}
                           for k, s in enumerate([0.12, 0.2, 0.33, 0.77])])
    n = review.write_sheet(picked, [(b"png", b"png")] * 4, tmp_path)
    assert n == 4
    for who in review.REVIEWERS:
        text = (tmp_path / f"sheet_reviewer_{who}.html").read_text() + (tmp_path / f"labels_reviewer_{who}.csv").read_text()
        for leak in ("SECRET", "0.12", "0.77", "0.40-1.00", "score", "AIS_", "2026"):
            assert leak not in text
        assert list(csv.reader(open(tmp_path / f"labels_reviewer_{who}.csv")))[0] == ["id", "reviewer", "label", "notes"]
    key = list(csv.DictReader(open(tmp_path / "KEY_reviewers_do_not_open" / "key.csv")))
    assert {k["band"] for k in key} == {"0.10-0.15", "0.15-0.25", "0.25-0.40", "0.40-1.00"}
    assert [k["id"] for k in key] == sorted(k["id"] for k in key)
