"""Region search: duplicates collapse but rafted partners survive, missing-AIS
scenes are excluded, and STS candidates are counted radar-vs-AIS."""
import pandas as pd

from src import dark_sts, hunt

T = pd.Timestamp("2026-08-23 02:06")
DEG_M = 111_000                                  # metres per degree of latitude


def det(scene, lat, conf=0.6, length=200, cls="vessel", lon=56.6, beam=40.0):
    return {"scene": scene, "lat": lat, "lon": lon, "x": 0.0, "y": 0.0, "conf": conf,
            "length_m": length, "beam_m": beam, "cls": cls, "time": T, "tif": "t.tif"}


def test_dedupe_keeps_rafted_partner():
    d = pd.DataFrame([det("a", 25.0, 0.5), det("a", 25.0 + 10 / DEG_M, 0.9),   # 10 m: duplicate
                      det("a", 25.0 + 50 / DEG_M, 0.4),                       # 50 m: rafted partner
                      det("b", 25.0, 0.3)])
    got = hunt.dedupe(d).sort_values(["scene", "conf"])
    assert got.conf.tolist() == [0.4, 0.9, 0.3]


def test_thin_scenes_excluded():
    cells = {"s1": 1400, "s2": 1500, "s3": 0, "s4": 93, "s5": 1100}
    assert hunt.thin_scenes(cells) == {"s3", "s4"}
    assert hunt.thin_scenes({"x": 0}) == {"x"}


def test_sts_candidates_merge_evidence():
    res = pd.DataFrame([det("a", 25.0), det("a", 25.0 + 60 / DEG_M),            # rafted pair
                        det("a", 25.0 + 30 / DEG_M, beam=110),                   # same spot, over-wide
                        det("a", 25.1, length=380),                              # long single VLCC: not STS
                        det("a", 25.2), det("a", 25.2 + 400 / DEG_M),            # close pair
                        det("a", 25.4)])                                         # alone
    c = hunt.sts_candidates(res).sort_values("lat")
    assert len(c) == 2
    assert set(c.iloc[0].evidence.split("+")) == {"rafted", "wide"}
    assert c.iloc[1].evidence == "pair"


def test_one_silent_partner_is_partial():
    res = pd.DataFrame([det("a", 25.0), det("a", 25.0 + 60 / DEG_M)])
    ais = {"a": pd.DataFrame([{"mmsi": "v1", "lat": 25.0, "lon": 56.6, "timestamp": T}])}
    c = hunt.count_identities(hunt.sts_candidates(res), res, ais)
    assert (c.n_radar.iloc[0], c.n_ais.iloc[0], c.missing.iloc[0]) == (2, 1, 1)
    assert c.category.iloc[0] == dark_sts.AIS_PARTIAL


def test_gfw_encounter_marks_visible_sts():
    c = pd.DataFrame([{"lat": 25.0, "lon": 56.6, "time": T}, {"lat": 25.3, "lon": 56.6, "time": T}])
    enc = pd.DataFrame([{"lat": 25.001, "lon": 56.6, "start": T - pd.Timedelta(hours=5),
                         "end": T + pd.Timedelta(hours=1)}])
    assert hunt.mark_encounters(c, enc).gfw_encounter.tolist() == [True, False]


def test_hull_shape_separates_one_hull_from_two(tmp_path):
    import numpy as np, rasterio
    from rasterio.transform import from_origin
    img = np.random.default_rng(0).normal(100, 5, (400, 400)).clip(1).astype("uint16")
    img[100:106, 85:115] = 5000          # one tanker: 300 m x 60 m
    img[300:312, 285:315] = 5000         # two side by side: 300 m x 120 m
    tif = tmp_path / "s.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=400, width=400, count=1, dtype="uint16",
                       crs="EPSG:32640", transform=from_origin(0, 4000, 10, 10)) as dst:
        dst.write(img, 1)
    res = pd.DataFrame([{"tif": str(tif), "x": 1000.0, "y": 4000 - 1030.0},
                        {"tif": str(tif), "x": 3000.0, "y": 4000 - 3060.0}])
    s = hunt.hull_shape(res)
    assert 280 <= s.hull_m[0] <= 330 and s.beam_m[0] < hunt.WIDE_M
    assert s.beam_m[1] >= hunt.WIDE_M
