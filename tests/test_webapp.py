import io
import time
from pathlib import Path
import pytest
from starlette.testclient import TestClient

import webapp.backend.app as backend
from webapp.backend.app import app, transform_feature_to_dict, infer_region


@pytest.fixture
def anon(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "USERS_DB", tmp_path / "users.db")
    return TestClient(app)


@pytest.fixture
def client(anon):
    r = anon.post("/api/auth/register", json={"name": "Test", "email": "t@example.org", "password": "correct horse"})
    anon.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return anon


def test_infer_region():
    assert infer_region(57.68, 10.61) == "Skagerrak"
    assert infer_region(25.0, 56.5) == "Gulf of Oman"
    assert infer_region(36.5, 22.5) == "Laconia Bay"
    assert infer_region(0.0, 0.0) == "Coastal Europe"


def test_transform_feature_to_dict():
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [10.6, 57.6]},
        "properties": {
            "category": "AIS_VISIBLE",
            "conf": 0.9,
            "length_m": 200,
            "time": "2025-06-08 05:31:31",
            "mmsis": ["123456789", "987654321"],
            "gfw_encounter": True,
            "duration_min": 60,
        },
    }
    d = transform_feature_to_dict(feature, 0)
    assert d["id"] == "0"
    assert d["lat"] == 57.6
    assert d["lon"] == 10.6
    assert d["status"] == "AIS_VISIBLE"
    assert d["confidence"] == 0.9
    assert d["vessel1_mmsi"] == "123456789"
    assert d["vessel2_mmsi"] == "987654321"
    assert d["gfw_match"] is True
    assert d["region"] == "Skagerrak"


def test_api_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "events" in data
    assert "eventCount" in data
    assert data["events"] == data["eventCount"]
    assert "live_detection" in data


def test_api_events_geojson(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    data = r.json()
    assert data.get("type") == "FeatureCollection"
    assert isinstance(data.get("features"), list)


def test_api_events_flat_format(client):
    r = client.get("/api/events?format=flat")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if len(data) > 0:
        ev = data[0]
        assert "id" in ev
        assert "lat" in ev
        assert "lon" in ev
        assert "status" in ev
        assert "confidence" in ev
        assert "region" in ev


def test_api_events_filtering(client):
    r = client.get("/api/events?category=AIS_VISIBLE")
    assert r.status_code == 200
    data = r.json()
    for f in data.get("features", []):
        assert f["properties"]["category"] == "AIS_VISIBLE"


def test_api_events_limit(client):
    r = client.get("/api/events?limit=1")
    assert r.status_code == 200
    data = r.json()
    assert len(data.get("features", [])) <= 1


def test_api_event_by_index(client):
    # Check valid index 0 if features exist
    r_all = client.get("/api/events")
    feats = r_all.json().get("features", [])
    if feats:
        r = client.get("/api/events/0")
        assert r.status_code == 200
        data = r.json()
        assert "event" in data
        assert data["event"]["id"] is not None

    # Check invalid index returns 404
    r_404 = client.get("/api/events/999999")
    assert r_404.status_code == 404


def test_api_summary(client):
    r = client.get("/api/summary")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "by_category" in data
    assert "by_size_class" in data


def test_api_detect_without_weights(client, monkeypatch):
    # Ensure weights path points to non-existent file
    import webapp.backend.app as backend_app
    monkeypatch.setattr(backend_app, "WEIGHTS", Path("/non/existent/weights.pt"))

    fake_file = io.BytesIO(b"fake image bytes")
    r = client.post("/api/detect", content=fake_file.getvalue())
    assert r.status_code == 503
    assert "No detector weights" in r.json()["detail"]


def test_serve_frontend(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_auth_flow(anon):
    assert anon.get("/api/events").status_code == 401
    assert anon.get("/api/summary").status_code == 200
    creds = {"email": "A@Example.org", "password": "correct horse"}
    assert anon.post("/api/auth/register", json={**creds, "name": "A", "password": "short"}).status_code == 422
    assert anon.post("/api/auth/register", json={**creds, "name": "A"}).status_code == 200
    assert anon.post("/api/auth/register", json={**creds, "name": "A"}).status_code == 409
    assert anon.post("/api/auth/login", json={**creds, "password": "wrong password"}).status_code == 401
    r = anon.post("/api/auth/login", json=creds)
    assert r.status_code == 200 and r.json()["user"]["email"] == "a@example.org"
    token = r.json()["token"]
    assert anon.get("/api/events", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert anon.get("/api/events", headers={"Authorization": f"Bearer {token[:-1]}x"}).status_code == 401


def test_live_ais_store_and_bbox(client):
    from webapp.backend import feeds
    feeds.ships.clear()
    now = 1_000_000.0
    feeds._store({"MetaData": {"MMSI": 1, "ShipName": "ALPHA  ", "latitude": 57.7, "longitude": 10.6},
                  "Message": {"PositionReport": {"Sog": 0.2, "Cog": 90, "TrueHeading": 511}}}, now)
    feeds._store({"MetaData": {"MMSI": 2, "latitude": 25.0, "longitude": 56.5}, "Message": {}}, now - feeds.STALE_S - 1)
    feeds._store({"MetaData": {"MMSI": 3, "latitude": None, "longitude": 1}, "Message": {}}, now)
    v, total = feeds.live_vessels([10, 57, 11, 58], now=now)
    assert total == 1 and [x["mmsi"] for x in v] == ["1"] and v[0]["name"] == "ALPHA" and v[0]["heading"] is None
    assert 2 not in feeds.ships                     # stale position dropped
    r = client.get("/api/live?bbox=10,57,11,58")
    assert r.status_code == 200 and "configured" in r.json()
    assert client.get("/api/live?bbox=1,2").status_code == 422
    feeds.ships.clear()


def test_live_ais_thins_evenly_past_the_cap(monkeypatch):
    from webapp.backend import feeds
    feeds.ships.clear()
    monkeypatch.setattr(feeds, "MAX_VESSELS", 100)   # 10 × 10 grid
    for k in range(2000):                           # dense cluster in one corner + sparse spread
        lat, lon = (1 + k * 1e-5, 1 + k * 1e-5) if k < 1900 else ((k % 10) * 9 + 0.5, (k // 10 % 10) * 9 + 0.5)
        feeds._store({"MetaData": {"MMSI": k, "latitude": lat, "longitude": lon}, "Message": {}}, 1.0)
    v, total = feeds.live_vessels([0, 0, 90, 90], now=1.0)
    assert total == 2000 and len(v) == 100                                # the whole budget is used
    assert max(x["lat"] for x in v) > 45 and max(x["lon"] for x in v) > 45   # far corner still covered
    assert sum(1 for x in v if x["lat"] < 1.1) > 1                        # busy cell gets the leftover
    feeds.ships.clear()


def test_news_rss_parse():
    from webapp.backend import feeds
    xml = """<rss><channel>
      <item><title>Tanker seized - Reuters</title><link>https://a</link><source>Reuters</source>
        <pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>
      <item><title>Newer story</title><link>https://b</link><pubDate>Tue, 02 Sep 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""
    items = feeds.parse_rss(xml)
    assert [i["title"] for i in items] == ["Newer story", "Tanker seized"]
    assert items[1]["source"] == "Reuters"


def test_live_vessel_type_from_static_data(client):
    from webapp.backend import feeds
    feeds.ships.clear(); feeds.statics.clear()
    t = time.time()
    feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": 538001000, "ShipName": "NORD@@@", "latitude": 57.7, "longitude": 10.6},
                  "Message": {"PositionReport": {"Sog": 0.1, "NavigationalStatus": 1, "TrueHeading": 90}}}, t)
    feeds._store({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 538001000},
                  "Message": {"ShipStaticData": {"Type": 81, "ImoNumber": 9300001, "CallSign": "V7AB@",
                              "Dimension": {"A": 200, "B": 50, "C": 20, "D": 24}, "Destination": "FUJAIRAH@@"}}}, t)
    feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": 538003000, "latitude": 57, "longitude": 10},
                  "Message": {"PositionReport": {}}}, t)
    feeds._store({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 538003000},
                  "Message": {"ShipStaticData": {"Type": 70, "Name": "FENSFJORD@@"}}}, t)
    assert client.get("/api/live/538003000").json()["name"] == "FENSFJORD"
    feeds._store({"MessageType": "StaticDataReport", "MetaData": {"MMSI": 538002000},
                  "Message": {"StaticDataReport": {"ReportB": {"Valid": True, "ShipType": 37, "CallSign": "X"}}}}, t)
    r = client.get("/api/live/538001000").json()
    assert r["name"] == "NORD" and r["type"] == "Tanker (hazard category A)" and r["imo"] == 9300001
    assert r["length_m"] == 250 and r["beam_m"] == 44 and r["destination"] == "FUJAIRAH" and r["nav_status"] == "At anchor"
    assert client.get("/api/live/538002000").json()["type"] == "Pleasure craft"
    assert client.get("/api/live/999").status_code == 404
    assert feeds.ship_type(0) is None and feeds.ship_type(70) == "Cargo" and feeds.ship_type(52) == "Tug"
    assert r["flag"] == {"iso2": "MH", "country": "Marshall Islands (Republic of the)"}
    assert feeds.flag(2190001) is None and feeds.flag(992191234) is None   # short MMSI, aid to navigation
    assert r["track"] == [[57.7, 10.6]]
    feeds.ships.clear(); feeds.statics.clear(); feeds.tracks.clear()


def test_live_track_samples_every_5_min_for_6_h():
    from webapp.backend import feeds
    feeds.ships.clear(); feeds.tracks.clear()
    t0 = feeds.T0
    for k in range(0, 8 * 3600, 60):                 # a report every minute for 8 h
        feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": 7, "latitude": 50 + k / 1e5, "longitude": 1.0},
                      "Message": {"PositionReport": {}}}, t0 + k)
    tr = feeds.tracks[7]
    assert len(tr) // 3 <= feeds.TRACK_KEEP_S // feeds.TRACK_EVERY_S + 1
    assert tr[-1] - tr[2] <= feeds.TRACK_KEEP_S
    feeds.ships.clear(); feeds.tracks.clear()


def test_ais_eta():
    from webapp.backend import feeds
    assert feeds._eta({"Month": 10, "Day": 8, "Hour": 12, "Minute": 0}) == "10-08 12:00 UTC"
    assert feeds._eta({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}) is None
    assert feeds._eta({"Month": 3, "Day": 1, "Hour": 24, "Minute": 60}) == "03-01"


def test_ais_static_data_survives_restart(tmp_path, monkeypatch):
    from webapp.backend import feeds
    monkeypatch.setattr(feeds, "STATIC_PATH", tmp_path / "ais_static.json")
    monkeypatch.setattr(feeds, "POSITIONS_PATH", tmp_path / "ais_positions.json")
    feeds.statics.clear(); feeds.ships.clear()
    feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": 311027600, "latitude": 57.8, "longitude": 10.4},
                  "Message": {"PositionReport": {"Sog": 8.6}}}, time.time())
    feeds.statics[311027600] = {"type_code": 80, "imo": 9466130, "t": time.time()}
    feeds.statics[219000001] = {"type_code": 70, "imo": None, "t": time.time() - feeds.STATIC_TTL - 1}  # expired
    feeds.save_statics()
    feeds.statics.clear(); feeds.ships.clear()
    feeds.load_statics()
    assert list(feeds.statics) == [311027600] and feeds.statics[311027600]["imo"] == 9466130
    v, _ = feeds.live_vessels()
    assert v[0]["mmsi"] == "311027600" and v[0]["sog"] == 8.6 and v[0]["group"] == "tanker"
    feeds.statics.clear(); feeds.ships.clear(); feeds.tracks.clear()


def test_gfw_identity_picks_latest_type_and_fills_imo(monkeypatch):
    from webapp.backend import feeds
    import requests as rq
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"entries": [{"registryInfo": [], "selfReportedInfo": [{"ssvid": "538006472", "imo": "9268887", "callsign": "V7X"}],
                                 "combinedSourcesInfo": [{"shiptypes": [{"name": "NA", "yearTo": 2014}, {"name": "CARGO", "yearTo": 2026}]}]}]}
    monkeypatch.setattr(rq, "get", lambda *a, **k: R())
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr("src.gfw._headers", lambda: {})
    feeds._identities.clear()
    ident = feeds.gfw_identity(538006472)
    assert ident["type"] == "Cargo" and ident["imo"] == 9268887 and ident["callsign"] == "V7X"
    feeds._identities.clear()


def test_type_groups_for_map_colours():
    from webapp.backend import feeds
    assert [feeds.type_group(c) for c in (None, 30, 37, 52, 33, 41, 69, 79, 84, 90)] == [
        "unknown", "fishing", "pleasure", "special", "special", "highspeed", "passenger", "cargo", "tanker", "other"]


def test_map_group_falls_back_to_looked_up_gfw_identity():
    from webapp.backend import feeds
    feeds.ships.clear(); feeds.statics.clear(); feeds._identities.clear()
    feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": 215672000, "latitude": 57.7, "longitude": 10.8},
                  "Message": {"PositionReport": {}}}, time.time())
    assert feeds.live_vessels()[0][0]["group"] == "unknown"
    feeds._identities["215672000"] = {"type": "Cargo"}
    assert feeds.live_vessels()[0][0]["group"] == "cargo"
    feeds.ships.clear(); feeds._identities.clear()


def test_regional_gulf_ships_in_live_map_and_card(client, monkeypatch, tmp_path):
    from webapp.backend import feeds
    from src import regional_ais as ra
    monkeypatch.setattr(ra, "DIR", tmp_path)
    ra._last_recorded.clear()
    now = time.time()
    pos = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 120))
    row = {"id": "hn:6782510", "name": "RAYAH", "lat": 26.2, "lon": 56.4, "sog": 11.0, "cog": 300.0, "heading": None,
           "pos_time": pos, "category": "tanker", "type": "Tanker", "flag": "SA", "length_m": 333.0, "width_m": 60.0,
           "dwt": 318990.0, "destination": "SARAZ"}
    old = dict(row, id="hn:1", pos_time=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 2 * 3600)))
    feeds.regional.clear(); feeds.regional.update({row["id"]: row, old["id"]: old})
    ra.record([row], root=tmp_path)
    v, total = feeds.live_vessels([55, 25, 58, 27], now=now)
    assert [x["mmsi"] for x in v] == ["hn:6782510"] and total == 1            # stale one hidden
    assert v[0]["group"] == "tanker" and v[0]["len"] == 333.0 and v[0]["source"] == "hormuz.now"
    card = client.get("/api/live/hn:6782510").json()
    assert card["name"] == "RAYAH" and card["flag"] == {"iso2": "SA", "country": feeds.COUNTRY_BY_ISO2["SA"]}
    assert card["dwt"] == 318990.0 and card["track"][-1] == [26.2, 56.4] and "hormuz.now" in card["source"]
    feeds.regional.clear()


def test_regional_identity_needs_a_unique_exact_name(monkeypatch):
    from webapp.backend import feeds
    entries = {"PEARL": [{"selfReportedInfo": [{"shipname": "PEARL", "imo": "9000001"}]},
                         {"selfReportedInfo": [{"shipname": "PEARL", "imo": "9000002"}]}],
               "RAYAH": [{"selfReportedInfo": [{"shipname": "RAYAH", "imo": "9779898"}]},
                         {"selfReportedInfo": [{"shipname": "RAYAH 2", "imo": "1"}]}]}
    class R:
        def __init__(self, q): self.q = q
        def raise_for_status(self): pass
        def json(self): return {"entries": entries[self.q]}
    monkeypatch.setattr(feeds.requests, "get", lambda url, params, **k: R(params["query"]))
    monkeypatch.setattr("src.gfw._headers", lambda: {})
    feeds._identities.clear(); feeds.regional.clear()
    feeds.regional.update({"hn:1": {"name": "PEARL"}, "hn:2": {"name": "RAYAH"}})
    assert feeds.gfw_identity("hn:1") is None                      # two PEARLs: refuse to guess
    assert feeds.gfw_identity("hn:2")["imo"] == 9779898              # exact and unique
    feeds._identities.clear(); feeds.regional.clear()


def test_gfw_layers_newest_day_with_data_and_radar(client, monkeypatch):
    import pandas as pd
    from webapp.backend import feeds
    from src import gfw
    calls = []
    def presence(a, b, box):
        calls.append(a)
        if len(calls) < 2:                          # newest lag still empty, the next day has data
            return pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"])
        return pd.DataFrame({"mmsi": ["v1", "v1", "v2"], "lat": [26.0, 26.1, 26.2], "lon": [56.0, 56.1, 56.2],
                             "timestamp": pd.to_datetime(["2026-09-30 01:30", "2026-09-30 05:30", "2026-09-30 02:30"])})
    monkeypatch.setattr(gfw, "ais_presence", presence)
    monkeypatch.setattr(gfw, "_report", lambda *a, **k: pd.DataFrame({"lat": [26.1, 26.3], "lon": [55.9, 56.0],
                                                                      "mmsi": ["", "123"], "detections": [1, 2]}))
    feeds._gfw_layers.clear()
    d = client.get("/api/gfw/layers?bbox=55.8,25.8,57.2,26.9").json()
    assert d["delay_days"] == feeds.GFW_LAG_DAYS[1] and len(d["vessels"]) == 2
    assert {v["id"]: v["lat"] for v in d["vessels"]}["v1"] == 26.1          # latest position per vessel
    assert [r["ais_matched"] for r in d["radar"]] == [False, True]
    assert client.get("/api/gfw/layers?bbox=40,10,60,30").status_code == 422
    feeds._gfw_layers.clear()


def test_ship_search_finds_ships_outside_the_view(client):
    from webapp.backend import feeds
    feeds.ships.clear(); feeds.statics.clear(); feeds.regional.clear()
    feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": 311027600, "ShipName": "MARAN PEARY",
                  "latitude": 57.8, "longitude": 10.4}, "Message": {"PositionReport": {}}}, time.time())
    feeds.regional["hn:6782510"] = {"id": "hn:6782510", "name": "RAYAH", "lat": 26.2, "lon": 56.4}
    feeds.regional["hn:2"] = {"id": "hn:2", "name": "RAYAH STAR", "lat": 25.0, "lon": 55.0}
    r = client.get("/api/live/search?q=rayah").json()["ships"]
    assert [x["name"] for x in r] == ["RAYAH", "RAYAH STAR"] and r[0]["source"] == "hormuz.now"
    assert client.get("/api/live/search?q=311027600").json()["ships"][0]["name"] == "MARAN PEARY"
    assert client.get("/api/live/search?q=x").json()["ships"] == []
    feeds.ships.clear(); feeds.regional.clear()
