import pandas as pd

from src import match

T = pd.Timestamp("2026-10-04 02:14")


def ais(rows):
    return pd.DataFrame(rows, columns=["mmsi", "lat", "lon", "timestamp", "sog", "cog", "length_m", "name"])


def test_dead_reckoning_turns_an_old_report_into_a_match():
    # Ship reported 30 min before the pass, 12 kn due east -> 6 nm (11.1 km) further east at pass time.
    lat, lon = 26.0, 56.0
    start_lon = lon - 11_112 / (111_320 * 0.8988)
    a = ais([["A", lat, start_lon, T - pd.Timedelta(minutes=30), 12, 90, 270, "ALPHA"]])
    c = match.candidates(lat, lon, T, a, length_m=274)[0]
    assert c["plausible"] and c["distance_m"] < 300 and c["size"] == "consistent" and c["minutes_from_pass"] == -30


def test_impossible_speed_and_size_mismatch_are_flagged():
    lat, lon = 26.0, 56.0
    far = ais([["B", 26.0, 56.25, T - pd.Timedelta(minutes=10), 0.1, 0, 98, "BRAVO"]])   # 25 km, standing still
    c = match.candidates(lat, lon, T, far, length_m=274, max_km=30)[0]
    assert not c["plausible"] and c["speed_needed_kn"] > 30
    assert "not a plausible match" in match.explain([c])
    near_small = ais([["C", 26.001, 56.0, T, 0.0, 0, 81, "CHARLIE"]])
    c = match.candidates(lat, lon, T, near_small, length_m=274)[0]
    assert c["plausible"] and c["size"] == "mismatch" and "different ship" in match.explain([c])


def test_outside_time_window_is_not_a_candidate():
    a = ais([["D", 26.0, 56.0, T - pd.Timedelta(hours=3), 0, 0, 200, "D"]])
    assert match.candidates(26.0, 56.0, T, a) == []


def test_jamming_signs_see_land_positions_and_jumps():
    rows = [["J", 32.0, 53.0, T, 0, 0, 0, "x"]] * 3 + [["K", 26.0, 56.0, T, 0, 0, 0, "y"],
                                                       ["K", 26.0, 56.9, T + pd.Timedelta(minutes=10), 0, 0, 0, "y"]]
    s = match.jamming_signs(ais(rows))
    assert s["on_land"] == 0.6 and s["impossible_jumps"] == 1.0


def test_coverage_scores_and_labels():
    big = [{"length_m": 200, "n_ais": 1}] * 5
    good = match.coverage({"GFW": True, "hormuz.now": True}, big, 20, {"on_land": 0.0, "impossible_jumps": 0.0})
    assert good["label"] == "good" and good["score"] == 1.0
    dark = [{"length_m": 200, "n_ais": 0}] * 5
    jammed = match.coverage({"GFW": True}, dark, 1, {"on_land": 0.2, "impossible_jumps": 0.1})
    assert jammed["label"] == "poor" and any("jamming" in f for f in jammed["factors"])
    assert match.coverage({"GFW": False}, big, 0, {})["label"] == "none"


def test_gulf_search_uses_recorded_regional_ais_when_gfw_has_none(monkeypatch, tmp_path):
    """End to end through search.run with the radar and detector stubbed: GFW has no AIS yet
    (its usual lag), our recorded regional feed has a ship that reported 30 min before the
    pass 11 km west, steaming east at 12 kn -> it matches the first hull after dead reckoning.
    The second hull has no AIS near it and comes out AIS-unmatched with a coverage label."""
    from src import search, regional_ais, hunt, context, filters, run_pipeline
    t = pd.Timestamp("2026-10-04 02:14")
    monkeypatch.setattr(regional_ais, "DIR", tmp_path / "reg")
    regional_ais._last_recorded.clear()
    west = 56.0 - 11_112 / (111_320 * 0.8988)
    rows = [{"id": "hn:1", "name": "ALPHA", "lat": 26.0, "lon": west, "sog": 12.0, "cog": 90.0, "heading": None,
             "pos_time": (t - pd.Timedelta(minutes=30)).isoformat(), "category": "tanker", "type": "Tanker",
             "flag": "PA", "length_m": 270.0, "width_m": 44.0, "dwt": None, "destination": None}]
    rows += [{**rows[0], "id": f"hn:{k}", "name": f"FAR {k}", "lat": 26.4 + k / 100, "lon": 56.4,
              "pos_time": t.isoformat(), "sog": 0.0} for k in range(2, 8)]
    regional_ais.record(rows, root=tmp_path / "reg", now=t)

    item = {"id": "S1C_TEST", "properties": {"datetime": t.isoformat() + "Z", "platform": "sentinel-1c"}}
    monkeypatch.setattr(search, "scenes", lambda box, end=None: [item])
    monkeypatch.setattr(search.gfw, "ais_presence", lambda a, b, box: pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"]))
    monkeypatch.setattr(search.fetch_s1, "fetch", lambda item, box, out_dir: tmp_path / "scene.tif")
    det = pd.DataFrame({"cls": ["vessel", "vessel"], "conf": [0.9, 0.8], "lat": [26.0, 26.2], "lon": [56.0, 56.3],
                        "time": [t, t], "x": [0, 0], "y": [0, 0], "length_m": [274.0, 180.0], "scene": ["S1C_TEST"] * 2})
    monkeypatch.setattr(run_pipeline, "detect", lambda tif, weights, conf: det)
    monkeypatch.setattr(filters, "clean_detections", lambda d: d)
    monkeypatch.setattr(hunt, "dedupe", lambda d: d)
    monkeypatch.setattr(hunt, "hull_shape", lambda r: r.assign(hull_m=r.length_m, beam_m=float("nan")))
    monkeypatch.setattr(hunt, "sts_candidates", lambda r: pd.DataFrame())
    monkeypatch.setattr(search, "chip_png", lambda *a, **k: None)
    monkeypatch.setattr(context, "gap_events", lambda box, t: None)
    monkeypatch.setattr(context, "zone_at", lambda lat, lon: None)
    monkeypatch.setattr(context, "zone_reason", lambda z: None)

    out = search.run((55.85, 25.85, 56.4, 26.3), "w.pt", end=t, cache=tmp_path / "cache")
    by_lat = {s["lat"]: s for s in out["ships"]}
    a, b = by_lat[26.0], by_lat[26.2]
    assert a["category"] == "AIS_PARTIAL" and a["ais_candidates"][0]["name"] == "ALPHA"
    assert a["ais_candidates"][0]["plausible"] and a["ais_candidates"][0]["size"] == "consistent"
    assert b["category"] == "AIS_UNMATCHED" and b["coverage"] in ("good", "fair", "poor")
    assert any("hormuz.now" in r for r in b["reasons"]) and any("AIS coverage here" in r for r in b["reasons"])
    assert "hormuz.now" in out["ais_source"] and out["coverage"]["label"] != "none"
