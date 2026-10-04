import time

import pandas as pd

from src import openwaters as ow, regional_ais as ra
from tests.test_webapp import anon, client  # noqa: F401  (signed-in API client fixture)


def feature(mmsi, lat, lon, seen, **p):
    return {"geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"mmsi": mmsi, "seen": seen, "source": "aishub", **p}}


def test_chunks_stay_inside_the_area_cap(monkeypatch):
    monkeypatch.delenv("OPENWATERS_TOKEN", raising=False)
    tiles = ow.chunks((47.3, 22.3, 61.0, 30.3))
    assert len(tiles) == 2 and all((e - w) * (n - s) <= ow.AREA_CAP_ANON for w, s, e, n in tiles)
    assert min(t[0] for t in tiles) == 47.3 and max(t[2] for t in tiles) == 61.0
    monkeypatch.setenv("OPENWATERS_TOKEN", "x")
    assert len(ow.chunks((32.0, 12.0, 44.0, 30.0))) == 1                       # 216 sq deg fits a token


def test_normalise_reads_size_type_and_time():
    r = ow.normalise(feature(228463800, 25.8, 51.9, "2026-10-04T15:02:05Z", name="WADI AL SAIL", type=84,
                             imo=9981374, to_bow=250, to_stern=50, to_port=25, to_starboard=25))
    assert r["mmsi"] == 228463800 and r["type_code"] == 84 and r["length_m"] == 300 and r["beam_m"] == 50
    assert r["seen"] == pd.Timestamp("2026-10-04T15:02:05Z").timestamp()
    assert ow.normalise(feature(None, 1, 1, "2026-10-04T15:00:00Z")) is None
    assert ow.category(84) == "tanker" and ow.credit("aishub") == "AISHub, via Open Waters"
    assert "CC0" in ow.credit("volunteer")


def test_hormuz_now_only_fills_ships_open_waters_lacks():
    mmsi_rows = [{"name": "RAYAH", "lat": 26.0, "lon": 56.0}]
    hn = [{"name": "Rayah", "lat": 26.01, "lon": 56.01},          # same ship, ~1.5 km: dropped
          {"name": "RAYAH", "lat": 27.0, "lon": 56.0},            # same name, 111 km away: another ship
          {"name": "ONLY HN", "lat": 26.0, "lon": 56.0}]
    assert [(h["name"], h["lat"]) for h in ra.leftovers(hn, mmsi_rows)] == [("RAYAH", 27.0), ("ONLY HN", 26.0)]
    # different spelling, same spot and size: one ship; same spot but a different size: two ships
    mmsi_rows = [{"name": "AL WAHSH", "lat": 26.0, "lon": 56.0, "length_m": 43}]
    hn = [{"name": "ALWAHSH-1", "lat": 26.002, "lon": 56.0, "length_m": 45},
          {"name": "TUG 7", "lat": 26.002, "lon": 56.0, "length_m": 20}]
    assert [h["name"] for h in ra.leftovers(hn, mmsi_rows)] == ["TUG 7"]


def test_merge_newer_wins_and_static_data_is_kept(client):
    from webapp.backend import feeds
    feeds.ships.clear(); feeds.statics.clear(); feeds.tracks.clear()
    now = time.time()
    feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": 228463800, "ShipName": "WADI AL SAIL",
                  "latitude": 25.0, "longitude": 51.0}, "Message": {"PositionReport": {}}}, now)
    feeds.statics[228463800] = {"callsign": "FIXED", "t": now}
    base = {"mmsi": 228463800, "name": None, "sog": 9.0, "cog": 90.0, "heading": None, "nav_status": 0,
            "type_code": 84, "imo": 9981374, "callsign": None, "length_m": 300, "beam_m": 50, "destination": "FOR ORDERS",
            "draught_m": None, "eta": None, "flag": "FR", "source": "aishub"}
    feeds.merge_openwaters([{**base, "lat": 26.0, "lon": 52.0, "seen": now - 600}])   # older: position kept
    assert feeds.ships[228463800]["lat"] == 25.0
    feeds.merge_openwaters([{**base, "lat": 26.0, "lon": 52.0, "seen": now + 5}])     # newer: replaces
    v = client.get("/api/live/228463800").json()
    assert v["lat"] == 26.0 and v["name"] == "WADI AL SAIL" and v["type"].startswith("Tanker")
    assert v["callsign"] == "FIXED" and v["imo"] == 9981374 and v["source"] == "AISHub, via Open Waters"
    feeds.ships.clear(); feeds.statics.clear(); feeds.tracks.clear()


def test_strait_crossings_longest_unobserved_first(client, monkeypatch):
    from webapp.backend import feeds
    class R:
        def raise_for_status(self): pass
        def json(self):
            return [{"ship_name": "A", "ship_category": "Crude Oil Tanker", "flag": "SA", "dwt": 318990, "length": 333,
                     "direction": "inbound", "detected_at": "2026-10-04T13:01:35Z", "gap_hours": 2.5},
                    {"ship_name": "B ", "ship_category": "Bulk Carrier", "flag": "--", "dwt": None, "length": 190,
                     "direction": "outbound", "detected_at": "2026-10-04T12:00:00Z", "gap_hours": 108.5}]
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: R())
    feeds._strait.clear()
    d = client.get("/api/strait/crossings?hours=48").json()
    assert [c["name"] for c in d["crossings"]] == ["B", "A"] and d["crossings"][0]["unobserved_h"] == 108.5
    assert d["crossings"][0]["flag"] is None and "non-commercial" in d["source"]
    feeds._strait.clear()


def test_particulars_kept_only_when_present(monkeypatch):
    from webapp.backend import feeds
    replies = {"311027600": {"properties": {"particulars": {"builder": "Samsung Heavy Industries", "year_built": 2011,
                                                            "image": "x", "deadweight": 109325}}},
               "228463800": {"properties": {"particulars": None}}}
    class R:
        def __init__(self, url): self.k = url.rsplit("/", 1)[-1]; self.status_code = 200
        def raise_for_status(self): pass
        def json(self): return replies[self.k]
    monkeypatch.setattr(feeds.requests, "get", lambda url, **k: R(url))
    feeds._particulars.clear()
    p = feeds.particulars(311027600)
    assert p["fields"] == {"builder": "Samsung Heavy Industries", "year_built": 2011, "deadweight": 109325}
    assert feeds.particulars(228463800) is None and feeds.particulars("hn:1") is None
    feeds._particulars.clear()
