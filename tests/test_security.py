"""Security regressions: file access outside the site, guessing, quotas, uploads, unsafe links."""
import io

import pytest
from starlette.testclient import TestClient

import webapp.backend.app as backend
from src import search

OMAN = [56.40, 25.10, 56.70, 25.40]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "USERS_DB", tmp_path / "users.db")
    monkeypatch.setattr(backend, "_search_store", backend.store.MemorySearches())
    c = TestClient(backend.app)
    r = c.post("/api/auth/register", json={"name": "T", "email": "t@example.org", "password": "correct horse"})
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


@pytest.mark.skipif(not (backend.DIST / "index.html").exists(), reason="frontend not built")
@pytest.mark.parametrize("path", ["/..%2F..%2F..%2F.env", "/%2e%2e/%2e%2e/%2e%2e/src/config.py",
                                  "/..%2F..%2F..%2Fdata%2Fusers.db"])
def test_no_file_outside_the_website(path):
    r = TestClient(backend.app).get(path)
    assert "GFW_API_TOKEN" not in r.text and "Shared config" not in r.text
    assert r.text.lstrip().lower().startswith("<!doctype html") or r.status_code == 404


def test_password_guessing_is_throttled(client):
    codes = [client.post("/api/auth/login", json={"email": "t@example.org", "password": f"wrong{i}"}).status_code
             for i in range(12)]
    assert codes[-1] == 429 and 401 in codes


def test_one_running_search_per_user(client, monkeypatch):
    class Never:                                    # job stays queued
        def submit(self, *a): pass
    monkeypatch.setattr(backend, "_executor", Never())
    monkeypatch.setattr(backend, "search_weights", lambda: "w.pt")
    assert client.post("/api/search", json={"bbox": OMAN}).status_code == 200
    r = client.post("/api/search", json={"bbox": OMAN})
    assert r.status_code == 429 and "already have a search" in r.json()["detail"]


def test_daily_search_quota(client, monkeypatch):
    class Now:
        def submit(self, fn, *a): fn(*a)
    monkeypatch.setattr(backend, "_executor", Now())
    monkeypatch.setattr(backend, "search_weights", lambda: "w.pt")
    monkeypatch.setattr(search, "run", lambda box, weights, progress: {})
    codes = [client.post("/api/search", json={"bbox": OMAN}).status_code for _ in range(backend.DAILY_SEARCHES + 1)]
    assert codes[:-1] == [200] * backend.DAILY_SEARCHES and codes[-1] == 429


def test_oversized_upload_refused(client, monkeypatch):
    monkeypatch.setattr(backend, "search_weights", lambda: "w.pt")
    big = io.BytesIO(b"0" * (backend.MAX_UPLOAD + 1))
    assert client.post("/api/detect", files={"file": ("x.png", big, "image/png")}).status_code == 413


def test_news_drops_script_links(monkeypatch):
    monkeypatch.setattr(backend.feeds, "news", lambda region: {"items": [
        {"title": "ok", "link": "https://example.org/a"}, {"title": "bad", "link": "javascript:alert(1)"}]})
    items = TestClient(backend.app).get("/api/news").json()["items"]
    assert [i["title"] for i in items] == ["ok"]
