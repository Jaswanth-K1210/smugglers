"""VesselAPI fill: on demand only, quota-guarded, merged into the live map. No real requests."""
import pytest
from starlette.testclient import TestClient

import webapp.backend.app as backend
from webapp.backend import feeds

MUMBAI = [72.4, 18.6, 73.2, 19.3]


class Resp:
    def __init__(self, vessels, next_token=None, remaining=100, status=200):
        self.status_code, self.headers = status, {"X-Ratelimit-Remaining": str(remaining)}
        self._d = {"vessels": vessels, **({"nextToken": next_token} if next_token else {})}

    def json(self):
        return self._d


def _v(mmsi, lat=19.0, lon=72.8, glitch=False, ts="2026-10-06T10:00:00Z"):
    return {"mmsi": mmsi, "vessel_name": f"SHIP {mmsi}", "latitude": lat, "longitude": lon, "sog": 0.1, "cog": 10,
            "heading": 12, "timestamp": ts, "suspected_glitch": glitch}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("VESSELAPI_KEY", "test-key")
    def reset():
        feeds.vesselapi_rows.clear()
        feeds.vesselapi_state.update(remaining=None, error=None, last_fill=None)
        backend._va_clicks.clear()
    reset()
    yield
    reset()                                   # ships added here must not leak into other map tests


def test_fill_follows_one_extra_page_and_skips_glitches(monkeypatch):
    calls = []
    pages = iter([Resp([_v(1), _v(2, glitch=True)], next_token="t2", remaining=120), Resp([_v(3)], remaining=119)])
    monkeypatch.setattr(feeds.requests, "get", lambda url, **k: calls.append(k["params"].copy()) or next(pages))
    out = feeds.vesselapi_fill(MUMBAI, now=1_000_000)
    assert out == {"added": 2, "remaining": 119} and len(calls) == 2
    assert calls[1]["pagination.nextToken"] == "t2" and calls[0]["filter.lonLeft"] == 72.4
    assert sorted(feeds.vesselapi_rows) == ["1", "3"]


def test_guards_size_and_reserve(monkeypatch):
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: pytest.fail("must not call VesselAPI"))
    with pytest.raises(ValueError, match="Zoom in"):
        feeds.vesselapi_fill([70.0, 15.0, 74.0, 19.0])
    feeds.vesselapi_state["remaining"] = feeds.VESSELAPI_RESERVE
    with pytest.raises(ValueError, match="used up"):
        feeds.vesselapi_fill(MUMBAI)


def test_rows_join_the_live_map_and_expire(monkeypatch):
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: Resp([_v(5), _v(6)]))
    feeds.vesselapi_fill(MUMBAI, now=1_000_000)
    rows = feeds.vesselapi_in(*MUMBAI, now=1_000_100, exclude={"6"})       # 6 also on a free feed: theirs wins
    assert [r["mmsi"] for r in rows] == ["5"] and rows[0]["source"] == "VesselAPI"
    assert feeds.vesselapi_in(*MUMBAI, now=1_000_000 + feeds.VESSELAPI_KEEP_S + 1) == []


def test_endpoint_limits_each_user(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "USERS_DB", tmp_path / "u.db")
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: Resp([_v(7)]))
    c = TestClient(backend.app)
    tok = c.post("/api/auth/register", json={"name": "V", "email": "v@example.org", "password": "correct horse"}).json()["token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    codes = [c.post("/api/live/vesselapi", json={"bbox": MUMBAI}).status_code
             for _ in range(backend.VESSELAPI_PER_USER_DAY + 1)]
    assert codes[:-1] == [200] * backend.VESSELAPI_PER_USER_DAY and codes[-1] == 429
    assert TestClient(backend.app).post("/api/live/vesselapi", json={"bbox": MUMBAI}).status_code == 401


def test_repeated_reports_keep_the_newest_and_count_ships(monkeypatch):
    rows = [_v(9, lat=19.00, ts="2026-10-06T10:00:00Z"), _v(9, lat=19.05, ts="2026-10-06T10:10:00Z"),
            _v(9, lat=19.02, ts="2026-10-06T10:05:00Z"), _v(10)]
    monkeypatch.setattr(feeds.requests, "get", lambda *a, **k: Resp(rows))
    out = feeds.vesselapi_fill(MUMBAI, now=2_000_000_000)
    assert out["added"] == 2 and feeds.vesselapi_rows["9"]["lat"] == 19.05


def test_live_memory_is_capped_oldest_first(monkeypatch):
    monkeypatch.setattr(feeds, "MAX_SHIPS", 3)
    monkeypatch.setattr(feeds, "MAX_STATICS", 2)
    saved = (dict(feeds.ships), dict(feeds.statics), dict(feeds.tracks))
    try:
        feeds.ships.clear(); feeds.statics.clear(); feeds.tracks.clear()
        now = 1_000_000.0
        for i in range(5):
            feeds.ships[i] = {"t": now - 100 + i, "lat": 0, "lon": 0}
            feeds.tracks[i] = [0]
            feeds.statics[i] = {"t": now - 100 + i}
        feeds.ships[99] = {"t": now - feeds.STALE_S - 1, "lat": 0, "lon": 0}     # stale: always dropped
        feeds.prune(now)
        assert sorted(feeds.ships) == [2, 3, 4] and sorted(feeds.tracks) == [2, 3, 4]
        assert sorted(feeds.statics) == [3, 4]
    finally:
        feeds.ships.clear(); feeds.statics.clear(); feeds.tracks.clear()
        feeds.ships.update(saved[0]); feeds.statics.update(saved[1]); feeds.tracks.update(saved[2])
