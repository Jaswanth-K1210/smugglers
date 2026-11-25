"""Region search: duplicates collapse but rafted partners survive, missing-AIS
scenes are excluded, and STS candidates are counted radar-vs-AIS."""
import pandas as pd

from src import dark_sts, hunt

T = pd.Timestamp("2026-08-23 02:06")
DEG_M = 111_000                                  # metres per degree of latitude


def det(scene, lat, conf=0.6, length=200, cls="vessel", lon=56.6, beam=40.0, wide=False):
    return {"scene": scene, "lat": lat, "lon": lon, "x": 0.0, "y": 0.0, "conf": conf,
            "length_m": length, "beam_m": beam, "wide": wide, "cls": cls, "time": T, "tif": "t.tif"}


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
                        det("a", 25.0 + 30 / DEG_M, beam=110, wide=True),        # same spot, over-wide
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
    assert 280 <= s.hull_m[0] <= 330 and 55 <= s.beam_m[0] <= 75
    assert s.beam_m[1] >= 1.6 * s.beam_m[0]


def test_sidelobe_cross_is_not_beam(tmp_path):
    """A very bright ship images with thin range/azimuth sidelobe arms; they are
    not hull width (Oman tier C: 'beams' of 94-170 m were mostly this cross)."""
    import numpy as np, rasterio
    from rasterio.transform import from_origin
    img = np.random.default_rng(0).normal(100, 5, (400, 400)).clip(1).astype("uint16")
    img[100:106, 85:115] = 9000                      # tanker 300 m x 60 m ...
    img[102:104, 40:160] = 6000                      # ... with a 2 px range arm
    img[60:150, 99:101] = 6000                       # ... and a 2 px azimuth arm
    img[300:312, 285:315] = 9000                     # rafted pair, 120 m across
    img[305:307, 240:360] = 6000
    img[260:350, 299:301] = 6000
    tif = tmp_path / "s.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=400, width=400, count=1, dtype="uint16",
                       crs="EPSG:32640", transform=from_origin(0, 4000, 10, 10)) as dst:
        dst.write(img, 1)
    res = pd.DataFrame([{"tif": str(tif), "x": 1000.0, "y": 4000 - 1030.0},     # on the tanker
                        {"tif": str(tif), "x": 3000.0, "y": 4000 - 3060.0},     # on the pair
                        {"tif": str(tif), "x": 1000.0, "y": 4000 - 1400.0}])    # on the arm only
    s = hunt.hull_shape(res)
    assert 280 <= s.hull_m[0] <= 330 and 55 <= s.beam_m[0] <= 75
    assert s.beam_m[1] >= 1.6 * s.beam_m[0]
    assert np.isnan(s.beam_m[2])                     # a sidelobe arm is not a ship


def test_wide_cutoff_follows_length_band():
    rows = [{"category": "AIS_VISIBLE", "hull_m": 150, "beam_m": 50 + i % 10} for i in range(200)]
    rows += [{"category": "AIS_VISIBLE", "hull_m": 300, "beam_m": 70 + i % 10} for i in range(200)]
    rows += [{"category": "AIS_UNMATCHED", "hull_m": 150, "beam_m": 75},   # wide for its band
             {"category": "AIS_UNMATCHED", "hull_m": 300, "beam_m": 75}]   # normal for its band
    out, cut = hunt.mark_wide(pd.DataFrame(rows))
    assert out.wide.tolist()[-2:] == [True, False]


def test_wide_needs_enough_matched_ships():
    rows = [{"category": "AIS_VISIBLE", "hull_m": 250, "beam_m": 180}] * 5 + \
           [{"category": "AIS_UNMATCHED", "hull_m": 250, "beam_m": 190}]
    out, cut = hunt.mark_wide(pd.DataFrame(rows))
    assert not out.wide.any()


def test_no_gfw_encounters():
    c = pd.DataFrame([{"lat": 25.0, "lon": 56.6, "time": T}])
    enc = pd.DataFrame(columns=["lat", "lon", "start", "end"])
    assert hunt.mark_encounters(c, enc).gfw_encounter.tolist() == [False]


def test_one_long_hull_is_not_a_pair(tmp_path):
    import numpy as np, rasterio
    from rasterio.transform import from_origin
    img = np.random.default_rng(1).normal(100, 5, (400, 400)).clip(1).astype("uint16")
    img[50:56, 50:85] = 5000            # one 350 m hull, detected at both ends
    img[150:156, 50:80] = 5000          # rafted: two hulls side by side, touching
    img[156:162, 50:80] = 5000
    img[250:256, 50:80] = 5000          # two separate hulls 300 m apart
    img[250:256, 110:140] = 5000
    img[350:353, 50:110] = 5000         # bright hull + sidelobe line, 400 m
    for c in range(200, 240, 8):        # 400 m hull imaged as a chain of scatterers
        img[52:56, c:c + 4] = 5000
    tif = tmp_path / "s.tif"
    t = from_origin(0, 4000, 10, 10)
    with rasterio.open(tif, "w", driver="GTiff", height=400, width=400, count=1, dtype="uint16",
                       crs="EPSG:32640", transform=t) as dst:
        dst.write(img, 1)
    from rasterio.warp import transform as tr
    def pt(r, c):
        x, y = t * (c + 0.5, r + 0.5)
        (lon,), (lat,) = tr("EPSG:32640", "EPSG:4326", [x], [y])
        return pd.Series({"x": x, "y": y, "lat": lat, "lon": lon})
    assert hunt.one_hull(tif, pt(53, 56), pt(53, 80))          # along one hull
    assert not hunt.one_hull(tif, pt(153, 65), pt(159, 65))    # side by side
    assert not hunt.one_hull(tif, pt(253, 65), pt(253, 125))   # two hulls
    assert hunt.one_hull(tif, pt(351, 52), pt(351, 105))       # 530 m apart on one streak
    assert hunt.one_hull(tif, pt(54, 201), pt(54, 234))        # dotted hull, 330 m
    assert hunt.one_hull(tif, pt(253, 65), pt(253, 95))        # partner on empty sea


def test_hull_split_by_a_dark_gap_is_one_ship(tmp_path):
    """Oman tier B 07-17 / 07-23: two ~107 m boxes end to end on one ~300 m hull
    whose middle images dark for ~80 m, wider than the bridge closes."""
    import numpy as np, rasterio
    from rasterio.transform import from_origin
    img = np.random.default_rng(2).normal(100, 5, (300, 300)).clip(1).astype("uint16")
    img[50:54, 50:64] = 5000            # bow, 140 m long
    img[50:56, 79:90] = 5000            # superstructure, 150 m dark deck between, same line
    img[150:156, 50:61] = 5000          # two ships in a line 300 m apart: still two
    img[150:156, 91:102] = 5000
    img[180:210, 220:226] = 5000        # Oman 09-25: one hull along the step ...
    img[225:231, 205:240] = 5000        # ... one across it, 150 m below: two ships
    img[250:256, 50:61] = 5000          # 80 m gap but 200 m off the line: two
    img[270:276, 69:80] = 5000
    tif = tmp_path / "s.tif"
    t = from_origin(0, 3000, 10, 10)
    with rasterio.open(tif, "w", driver="GTiff", height=300, width=300, count=1, dtype="uint16",
                       crs="EPSG:32640", transform=t) as dst:
        dst.write(img, 1)
    from rasterio.warp import transform as tr
    def pt(r, c):
        x, y = t * (c + 0.5, r + 0.5)
        (lon,), (lat,) = tr("EPSG:32640", "EPSG:4326", [x], [y])
        return pd.Series({"x": x, "y": y, "lat": lat, "lon": lon})
    assert hunt.one_hull(tif, pt(52, 57), pt(53, 84))          # one hull, dark middle
    assert not hunt.one_hull(tif, pt(153, 55), pt(153, 96))    # gap 300 m: two ships
    assert not hunt.one_hull(tif, pt(195, 223), pt(228, 222))  # different headings: two ships
    assert not hunt.one_hull(tif, pt(253, 55), pt(273, 74))    # not on one line: two ships
    img2 = img.copy()
    img2[100:110, 50:60] = 9000         # round bright superstructure, no direction of its own
    img2[103:107, 68:84] = 5000         # rest of the hull, 80 m on, same line
    with rasterio.open(tif, "w", driver="GTiff", height=300, width=300, count=1, dtype="uint16",
                       crs="EPSG:32640", transform=t) as dst:
        dst.write(img2, 1)
    assert hunt.one_hull(tif, pt(105, 55), pt(105, 76))        # blob + streak: one hull


def test_gfw_outage_stops_before_writing(monkeypatch):
    import pytest
    monkeypatch.setattr(hunt, "_presence", lambda t, box: pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"]))
    clean = pd.DataFrame([det("a", 25.0), det("b", 25.1)])
    with pytest.raises(RuntimeError, match="GFW"):
        hunt.check_ais(clean, hunt.REGIONS["oman"])
