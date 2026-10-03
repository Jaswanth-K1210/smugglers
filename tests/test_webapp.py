import io
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
    r = client.post("/api/detect", files={"file": ("tile.tif", fake_file, "image/tiff")})
    assert r.status_code == 503
    assert "no trained weights" in r.json()["detail"]


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
