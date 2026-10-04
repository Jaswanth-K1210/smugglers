"""Regressions from the live Gulf deployment. Each bug gave a plausible-looking but wrong result."""
import re
from pathlib import Path

import numpy as np

from src import fetch_s1, run_pipeline, search

ROOT = Path(__file__).resolve().parents[1]
BOX = (56.35, 25.05, 56.65, 25.35)


def _item(name, coords):
    return {"id": name, "bbox": [56.0, 24.8, 57.0, 25.6], "properties": {"datetime": "2026-09-30T14:24:00Z"},
            "geometry": {"type": "Polygon", "coordinates": [coords]}}


def test_tilted_strip_that_clips_a_corner_is_not_searched(monkeypatch):
    sliver = _item("sliver", [[56.35, 25.05], [56.45, 25.05], [56.35, 25.15], [56.35, 25.05]])   # ~6 %
    full = _item("full", [[56.30, 25.00], [56.70, 25.00], [56.70, 25.40], [56.30, 25.40], [56.30, 25.00]])
    assert fetch_s1.overlap(sliver, BOX) < 0.1 and fetch_s1.overlap(full, BOX) == 1.0
    monkeypatch.setattr(fetch_s1, "search", lambda *a, **k: [sliver, full])
    assert [i["id"] for i in search.scenes(BOX)] == ["full"]


def test_strip_edge_detection_dropped_interior_kept():
    valid = np.ones((200, 200), bool)
    valid[:, :60] = False                         # no-data on the left: the strip edge at column 60
    assert run_pipeline.on_strip_edge(valid, 100, 65)          # 50 m inside the edge
    assert not run_pipeline.on_strip_edge(valid, 100, 150)     # 900 m inside


def test_partly_covered_tiles_are_searched():
    assert run_pipeline.MIN_VALID <= 0.25          # was 0.9: a strip edge through a tile lost every ship
    assert run_pipeline.tile_starts(2500) == [0, 1024, 1476]   # right/bottom strip covered


def test_ais_recorder_has_its_own_volume():
    src = (ROOT / "modal_app.py").read_text()
    web = src[src.index("def web"):]
    assert '"/app/ais": ais' in src and "before_read = ais.reload" in web
    recorder = src[src.index("schedule=modal.Period"):]
    assert "data.reload" not in recorder and "data.commit" not in recorder


def test_stale_cached_searches_are_versioned():
    assert re.search(r'key = f"v\{CACHE_VERSION\}_', (ROOT / "src" / "search.py").read_text())
