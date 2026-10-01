"""CDSE fetch must never spend processing units without confirm=True."""
from src import fetch_cdse

SKAGEN = (10.4, 57.5, 11.4, 58.0)


def test_tiles_respect_api_limit():
    for x0, y0, x1, y1 in fetch_cdse.tiles(SKAGEN):
        assert (x1 - x0) / 10 <= fetch_cdse.MAX_PX and (y1 - y0) / 10 <= fetch_cdse.MAX_PX


def test_no_request_without_confirm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call without confirm")
    monkeypatch.setattr(fetch_cdse.requests, "post", boom)
    assert fetch_cdse.fetch("2026-09-07T16:53:13", box=SKAGEN) is None
    assert 100 < fetch_cdse.estimate_pu(SKAGEN) < 400
