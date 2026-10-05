"""The Render backend: accounts and search records in MongoDB, searches run by the Modal worker."""
import mongomock
import pytest
from starlette.testclient import TestClient

import webapp.backend.app as backend
from webapp.backend import store

BOX = [56.35, 25.05, 56.65, 25.35]


@pytest.fixture
def mongo(monkeypatch):
    db = mongomock.MongoClient()["darksts"]
    monkeypatch.setenv("MONGODB_URI", "mongodb://test")
    monkeypatch.setattr(store, "_mongo_db", lambda: db)
    return db


def _signed_in(c, email="m@example.org"):
    r = c.post("/api/auth/register", json={"name": "M", "email": email, "password": "correct horse"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


def test_accounts_live_in_mongodb(mongo):
    c = _signed_in(TestClient(backend.app))
    doc = mongo["users"].find_one({"email": "m@example.org"})
    assert doc["name"] == "M" and "correct horse" not in str(doc)          # hash and salt only
    assert c.get("/api/auth/me").json()["user"]["email"] == "m@example.org"
    assert c.post("/api/auth/register", json={"name": "M", "email": "M@example.org",
                                              "password": "correct horse"}).status_code == 409
    assert TestClient(backend.app).post("/api/auth/login", json={"email": "m@example.org",
                                                                 "password": "correct horse"}).status_code == 200
    assert TestClient(backend.app).post("/api/auth/login", json={"email": "m@example.org",
                                                                 "password": "wrong pass"}).status_code == 401


@pytest.fixture
def worker_mode(mongo, monkeypatch):
    monkeypatch.setattr(backend, "SEARCH_MODE", "worker")
    calls = {"spawned": [], "status": {"status": "running", "error": None, "passes": 2, "passes_found": 3,
                                       "progress": 0.5, "stages": ["a", "b"]}, "result": None}
    monkeypatch.setattr(backend.worker, "spawn", lambda box, s, e, job: calls["spawned"].append((box, s, e, job)) or "fc-1")
    monkeypatch.setattr(backend.worker, "status", lambda job: calls["status"])
    monkeypatch.setattr(backend.worker, "result", lambda call: calls["result"])
    from src import plan
    world = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]
    calls["items"] = [{"id": f"P{i}", "bbox": [-180, -85, 180, 85], "geometry": {"type": "Polygon", "coordinates": [world]},
                       "properties": {"datetime": f"2026-09-{28 - 6 * i:02d}T02:14:00Z"}} for i in range(3)]
    monkeypatch.setattr(plan, "stac_search", lambda *a, **k: calls["items"])
    return calls


def test_estimate_before_go_any_size_any_period(worker_mode):
    c = _signed_in(TestClient(backend.app))
    big = [55.0, 24.0, 57.0, 26.0]                                          # ~200 x 220 km, a year
    r = c.post("/api/search/estimate", json={"bbox": big, "start": "2025-10-01", "end": "2026-09-30"})
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["passes"] == 3 and est["cells"] == 5 * 5 and est["units"] == 75 and est["minutes"] > 30
    assert est["first"] < est["last"] and not est["over_limit"] and est["daily_units_left"] == backend.DAILY_UNITS
    assert c.post("/api/search", json={"bbox": big, "start": "2025-10-01", "end": "2026-09-30"}).status_code == 200


def test_work_ceiling_and_daily_budget(worker_mode, monkeypatch):
    c = _signed_in(TestClient(backend.app))
    monkeypatch.setattr(backend, "DAILY_UNITS", 10)
    r = c.post("/api/search", json={"bbox": [55.0, 24.0, 57.0, 26.0]})
    assert r.status_code == 429 and "daily" in r.json()["detail"]
    from src import plan
    monkeypatch.setattr(plan, "MAX_UNITS", 2)
    r = c.post("/api/search", json={"bbox": BOX})
    assert r.status_code == 422 and "limit is 2" in r.json()["detail"]


def test_worker_mode_spawns_and_polls(worker_mode, mongo):
    c = _signed_in(TestClient(backend.app))
    r = c.post("/api/search", json={"bbox": BOX, "start": "2026-09-15", "end": "2026-09-30"})
    assert r.status_code == 200 and r.json()["period"] == ["2026-09-15", "2026-09-30"]
    job = r.json()["job_id"]
    box, s, e, j = worker_mode["spawned"][0]
    assert (str(s), str(e), j) == ("2026-09-15", "2026-09-30", job)
    assert mongo["searches"].find_one({"job_id": job})["call_id"] == "fc-1"
    running = c.get(f"/api/search/{job}").json()
    assert running["status"] == "running" and running["progress"] == 0.5 and running["passes"] == 2
    assert "call_id" not in running
    worker_mode["result"] = {"passes": [], "counts": {"ships": 3}}
    done = c.get(f"/api/search/{job}").json()
    assert done["status"] == "done" and done["result"]["counts"]["ships"] == 3
    assert mongo["searches"].find_one({"job_id": job})["status"] == "done"


def test_worker_mode_defaults_to_recent_days_and_checks_dates(worker_mode):
    c = _signed_in(TestClient(backend.app))
    assert c.post("/api/search", json={"bbox": BOX}).status_code == 200
    s, e = worker_mode["spawned"][0][1:3]
    assert (e - s).days == 11                                               # last 12 days, inclusive
    bad = c.post("/api/search", json={"bbox": BOX, "start": "2026-09-30", "end": "2026-09-01"})
    assert bad.status_code == 422 and "before the start" in bad.json()["detail"]


def test_worker_errors_reach_the_user(worker_mode):
    c = _signed_in(TestClient(backend.app))
    job = c.post("/api/search", json={"bbox": BOX}).json()["job_id"]
    worker_mode["status"] = {"status": "error", "error": "No Sentinel-1 pass covered at least half of this box.",
                             "passes": 0, "passes_found": None, "progress": 0, "stages": []}
    got = c.get(f"/api/search/{job}").json()
    assert got["status"] == "error" and "No Sentinel-1 pass" in got["error"]
    # the failed search no longer blocks a new one
    assert c.post("/api/search", json={"bbox": BOX}).status_code == 200


def test_quotas_hold_across_restarts(worker_mode, monkeypatch):
    c = _signed_in(TestClient(backend.app))
    assert c.post("/api/search", json={"bbox": BOX}).status_code == 200
    monkeypatch.setattr(backend, "_search_store", None)                     # restart: memory gone, Mongo kept
    r = c.post("/api/search", json={"bbox": BOX})
    assert r.status_code == 429 and "already have a search" in r.json()["detail"]


def test_render_server_validates_without_the_image_stack():
    import subprocess
    import sys
    code = ("import sys; from src.limits import validate, validate_period, default_period; "
            "validate([56.35,25.05,56.65,25.35]); default_period(); "
            "from src import plan; plan.cells((55, 24, 57, 26)); "
            "heavy = [m for m in ('rasterio','numpy','pandas','torch','ultralytics') if m in sys.modules]; "
            "print(heavy); assert not heavy")
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


def test_health_says_search_is_available_in_worker_mode(monkeypatch):
    monkeypatch.setattr(backend, "SEARCH_MODE", "worker")
    monkeypatch.delenv("HF_MODEL_REPO", raising=False)
    h = TestClient(backend.app).get("/api/health").json()
    assert h["search_available"] is True and h["search_mode"] == "worker"
