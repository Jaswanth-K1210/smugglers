"""AOIs outside Denmark: projection follows the AOI, GFW presence parses like ais.load()."""
import pandas as pd

from src import dark_sts, gfw
from src.fetch_s1 import utm_crs


def test_utm_zone_follows_aoi():
    assert utm_crs((10.4, 57.5, 11.4, 58.0)) == "EPSG:32632"      # Skagen
    assert utm_crs((22.45, 36.35, 23.15, 36.80)) == "EPSG:32634"  # Gulf of Laconia
    assert utm_crs((56.30, 24.90, 56.80, 25.50)) == "EPSG:32640"  # Gulf of Oman
    assert utm_crs((-70.0, -33.5, -69.0, -33.0)) == "EPSG:32719"  # southern hemisphere


def test_empty_gfw_window(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"entries": [{"public-global-presence:v4.0": None}]}
    monkeypatch.setattr(gfw, "_headers", lambda: {})
    monkeypatch.setattr(gfw.requests, "post", lambda *a, **k: R())
    a = gfw.ais_presence("2026-08-15T03:00", "2026-08-15T07:00", (56.3, 24.9, 56.8, 25.5))
    assert a.empty and list(a.columns) == ["mmsi", "lat", "lon", "timestamp"]


def test_presence_feeds_characterise(monkeypatch):
    rows = pd.DataFrame([{"vesselId": "v1", "mmsi": "123", "lat": 36.47, "lon": 22.97,
                          "date": "2026-08-15 04:00"}])
    monkeypatch.setattr(gfw, "_report", lambda *a, **k: rows)
    a = gfw.ais_presence("2026-08-15T03:00", "2026-08-15T07:00", (22.45, 36.35, 23.15, 36.80))
    det = pd.DataFrame([{"lat": 36.475, "lon": 22.975, "time": pd.Timestamp("2026-08-15 05:00")},
                        {"lat": 36.37, "lon": 23.10, "time": pd.Timestamp("2026-08-15 05:00")}])
    got = dark_sts.characterise(det, a, buffer_m=2000, window_h=1).category.tolist()
    assert got == [dark_sts.AIS_PARTIAL, dark_sts.AIS_UNMATCHED]


def test_rate_limit_is_retried(monkeypatch):
    codes = iter([429, 502, 200])
    class R:
        def __init__(self): self.status_code = next(codes)
    monkeypatch.setattr(gfw, "_headers", lambda: {})
    monkeypatch.setattr(gfw.time, "sleep", lambda s: None)
    monkeypatch.setattr(gfw.requests, "post", lambda *a, **k: R())
    assert gfw._post("u").status_code == 200
