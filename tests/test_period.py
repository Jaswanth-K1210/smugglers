"""Time-period search: date limits, pass selection, combining passes, recurring spots."""
import pandas as pd
import pytest

from src import dark_sts, search

BOX = (56.35, 25.05, 56.65, 25.35)
TODAY = "2026-10-05"


@pytest.mark.parametrize("start,end,msg", [
    ("2026-09-10", "2026-09-01", "before the start"),
    ("2026-10-01", "2026-10-09", "future"),
    ("2014-01-01", "2014-01-20", "start on"),
    ("2026-08-01", "2026-09-15", "at most 31 days"),
    ("not-a-date", "2026-09-01", "YYYY-MM-DD"),
])
def test_period_limits(start, end, msg):
    with pytest.raises(ValueError, match=msg):
        search.validate_period(start, end, today=TODAY)


def test_period_ok():
    a, b = search.validate_period("2026-09-01", "2026-10-01", today=TODAY)   # 31 days inclusive
    assert (str(a), str(b)) == ("2026-09-01", "2026-10-01")


def _item(i, cover):
    full = [[56.30, 25.00], [56.70, 25.00], [56.70, 25.40], [56.30, 25.40], [56.30, 25.00]]
    sliver = [[56.35, 25.05], [56.45, 25.05], [56.35, 25.15], [56.35, 25.05]]
    return {"id": f"P{i}", "bbox": [56, 24.8, 57, 25.6], "properties": {"datetime": f"2026-09-{20 - i:02d}T02:14:00Z"},
            "geometry": {"type": "Polygon", "coordinates": [full if cover else sliver]}}


def test_passes_newest_first_real_footprint_and_capped(monkeypatch):
    items = [_item(i, cover=i != 2) for i in range(9)]               # P2 only clips a corner
    monkeypatch.setattr(search.fetch_s1, "search", lambda *a, **k: items)
    picked, found = search.period_passes(BOX, "2026-09-01", "2026-09-30")
    assert found == 8 and [p["id"] for p in picked] == ["P0", "P1", "P3", "P4", "P5", "P6"]
    monkeypatch.setattr(search.fetch_s1, "search", lambda *a, **k: [_item(0, cover=False)])
    with pytest.raises(LookupError, match="No Sentinel-1 pass"):
        search.period_passes(BOX, "2026-09-01", "2026-09-30")


def _pass(t, ships):
    return {"scene": {"time": t}, "ships": ships, "note": "n",
            "counts": search.counts(ships, [])}


def _ship(lat, cat=dark_sts.AIS_UNMATCHED, weak=False):
    return {"lat": lat, "lon": 56.5, "category": cat, "weak": weak}


def test_combine_flags_spots_seen_on_several_passes():
    d = 1 / 111_000
    a = _pass("2026-09-20T02:14", [_ship(25.20), _ship(25.30), _ship(25.10, dark_sts.AIS_VISIBLE)])
    b = _pass("2026-09-14T02:14", [_ship(25.20 + 100 * d), _ship(25.25, weak=True)])
    c = _pass("2026-09-08T02:14", [_ship(25.20 + 150 * d)])
    out = search.combine([c, a, b, {"error": "x"}], found=5)
    assert [p.get("scene", {}).get("time") for p in out["passes"]][:3] == ["2026-09-20T02:14", "2026-09-14T02:14",
                                                                          "2026-09-08T02:14"]
    assert len(out["recurring"]) == 1 and out["recurring"][0]["passes"] == 3
    assert out["counts"]["ais_unmatched"] == 4 and out["counts"]["ais_unmatched_spots"] == 2
    assert out["counts"]["weak_candidates"] == 1 and out["passes_failed"] == 1 and out["passes_found"] == 5
    assert a["ships"][0]["recurring_passes"] == 3 and "recurring_passes" not in a["ships"][1]
