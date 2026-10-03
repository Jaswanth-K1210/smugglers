"""Area search: box limits, wording of reasons, and the job API end to end."""
import pytest
from starlette.testclient import TestClient

import webapp.backend.app as backend
from src import dark_sts, search

OMAN = [56.40, 25.10, 56.70, 25.40]          # ~30 x 33 km


def test_box_limits():
    assert search.validate(OMAN) == tuple(OMAN)
    with pytest.raises(ValueError, match="at least 11 km"):
        search.validate([56.40, 25.10, 56.45, 25.15])
    with pytest.raises(ValueError, match="at most 60 km"):
        search.validate([56.0, 25.0, 57.0, 26.0])
    with pytest.raises(ValueError, match="out of order"):
        search.validate([56.7, 25.1, 56.4, 25.4])


def test_reasons_say_what_was_checked_and_never_dark():
    ship = {"category": dark_sts.AIS_UNMATCHED, "n_ais": 0, "length_m": 240, "conf": 0.71,
            "gfw_also_unmatched": True}
    r = search.reasons(ship, ais_ok=True, sts_note="Seen beside another hull 60 m away (ships moored together).")
    text = " ".join(r)
    assert "No AIS identity within 2 km" in text and "240 m" in text and "SOLAS" in text
    assert "Global Fishing Watch's own" in text and "beside another hull" in text
    assert "dark" not in text.lower()
    assert "not available yet" in " ".join(search.reasons({**ship, "category": "AIS_NOT_AVAILABLE"}, ais_ok=False))


class _Now:                                   # run submitted jobs immediately
    def submit(self, fn, *a):
        fn(*a)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "USERS_DB", tmp_path / "users.db")
    monkeypatch.setattr(backend, "_executor", _Now())
    monkeypatch.setattr(backend, "search_weights", lambda: tmp_path / "best.pt")
    c = TestClient(backend.app)
    r = c.post("/api/auth/register", json={"name": "T", "email": "t@example.org", "password": "correct horse"})
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


def test_search_job_runs_and_reports(client, monkeypatch):
    def fake_run(box, weights, progress):
        progress("Detecting ships", 0.4)
        return {"counts": {"ships": 3, "ais_unmatched": 1}, "ships": [], "sts": []}
    monkeypatch.setattr(search, "run", fake_run)
    job = client.post("/api/search", json={"bbox": OMAN}).json()
    got = client.get(f"/api/search/{job['job_id']}").json()
    assert got["status"] == "done" and got["result"]["counts"]["ais_unmatched"] == 1


def test_search_errors_are_sentences(client, monkeypatch):
    assert client.post("/api/search", json={"bbox": [56.4, 25.1, 56.41, 25.11]}).status_code == 422
    def no_scene(box, weights, progress):
        raise LookupError("No Sentinel-1 pass covered at least half of this box in the last 12 days.")
    monkeypatch.setattr(search, "run", no_scene)
    job = client.post("/api/search", json={"bbox": OMAN}).json()
    got = client.get(f"/api/search/{job['job_id']}").json()
    assert got["status"] == "error" and "No Sentinel-1 pass" in got["error"]


def test_search_needs_sign_in_and_hides_other_users_jobs(client, monkeypatch):
    monkeypatch.setattr(search, "run", lambda box, weights, progress: {})
    job = client.post("/api/search", json={"bbox": OMAN}).json()
    anon = TestClient(backend.app)
    assert anon.post("/api/search", json={"bbox": OMAN}).status_code == 401
    r = anon.post("/api/auth/register", json={"name": "U", "email": "u@example.org", "password": "correct horse"})
    anon.headers["Authorization"] = f"Bearer {r.json()['token']}"
    assert anon.get(f"/api/search/{job['job_id']}").status_code == 404


def test_pick_scene_skips_passes_without_ais(monkeypatch):
    import pandas as pd
    new, older = ({"id": i, "properties": {"datetime": d}} for i, d in
                  [("new", "2026-10-03T02:14:00Z"), ("older", "2026-09-27T02:14:00Z")])
    ais = pd.DataFrame([{"mmsi": "1", "lat": 25.2, "lon": 56.5, "timestamp": pd.Timestamp("2026-09-27 02:30")}])
    monkeypatch.setattr(search.gfw, "ais_presence",
                        lambda a, b, box: ais if a < pd.Timestamp("2026-10-01") else ais.iloc[:0])
    item, got, note = search.pick_scene([new, older], OMAN)
    assert item["id"] == "older" and len(got) == 1 and "no AIS data yet" in note
    monkeypatch.setattr(search.gfw, "ais_presence", lambda a, b, box: ais.iloc[:0])
    item, got, note = search.pick_scene([new, older], OMAN)
    assert item["id"] == "new" and got.empty and "unchecked" in note
