"""Region search: duplicates collapse but rafted partners survive, missing-AIS
scenes are excluded, and STS candidates are counted radar-vs-AIS."""
import pandas as pd

from src import dark_sts, hunt

T = pd.Timestamp("2026-08-23 02:06")
DEG_M = 111_000                                  # metres per degree of latitude


def det(scene, lat, conf=0.6, length=200, cls="vessel", lon=56.6):
    return {"scene": scene, "lat": lat, "lon": lon, "x": 0.0, "y": 0.0, "conf": conf,
            "length_m": length, "cls": cls, "time": T, "tif": "t.tif"}


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
                        det("a", 25.0 + 30 / DEG_M, length=380),                 # same spot, oversized
                        det("a", 25.2), det("a", 25.2 + 400 / DEG_M),            # close pair
                        det("a", 25.4)])                                         # alone
    c = hunt.sts_candidates(res).sort_values("lat")
    assert len(c) == 2
    assert set(c.iloc[0].evidence.split("+")) == {"rafted", "oversized"}
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
