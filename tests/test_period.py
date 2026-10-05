"""Time-period search: date limits, pass selection, combining passes, recurring spots."""
import pandas as pd
import pytest

from src import dark_sts, plan, search

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


def test_worker_has_no_period_or_size_limit():
    a, b = search.validate_period("2025-01-01", "2026-10-01", today=TODAY, max_days=None)
    assert (b - a).days == 638
    assert search.validate((55.0, 24.0, 57.0, 26.0), max_km=None) == (55.0, 24.0, 57.0, 26.0)


def test_plan_cuts_a_large_box_into_cells_per_pass():
    big = (56.0, 24.8, 57.4, 26.3)                                   # ~141 x 166 km
    cores = plan.cells(big)
    assert len(cores) == 3 * 4 and all(max(plan.km(c)) <= plan.CELL_KM for c in cores)
    assert sum(plan.km(c)[0] * plan.km(c)[1] for c in cores) == pytest.approx(
        plan.km(big)[0] * plan.km(big)[1], rel=0.01)                 # cores tile the box exactly
    g = plan.grow(cores[0], big)
    assert g[:2] == big[:2] and g[2] > cores[0][2] and g[3] > cores[0][3]   # grown inward, clipped outside
    west = {"id": "W", "properties": {"datetime": "2026-09-20T02:14:00Z"}, "bbox": [55, 24, 58, 27],
            "geometry": {"type": "Polygon", "coordinates": [[[55.9, 24.7], [56.5, 24.7], [56.5, 26.4],
                                                             [55.9, 26.4], [55.9, 24.7]]]}}
    east = {**west, "id": "E", "properties": {"datetime": "2026-09-20T02:14:25Z"},
            "geometry": {"type": "Polygon", "coordinates": [[[56.4, 24.7], [57.5, 24.7], [57.5, 26.4],
                                                             [56.4, 26.4], [56.4, 24.7]]]}}
    p = plan.make_plan(big, "2026-09-01", "2026-09-30", items=[west])
    assert p["passes_found"] == 1 and p["units"] == 4               # only the western column of cells
    two = plan.make_plan(big, "2026-09-01", "2026-09-30", items=[east, west])   # two slices of one pass
    assert two["passes_found"] == 1 and two["units"] == 12           # every cell once, by its best slice
    assert {it["id"] for it, c in two["passes"][0]["units"] if c == cores[0]} == {"W"}
    assert p["estimate"]["minutes"] >= 2 and not p["estimate"]["over_limit"]
    with pytest.raises(LookupError, match="No Sentinel-1 pass"):
        plan.make_plan(big, "2026-09-01", "2026-09-30", items=[])


def test_merge_cells_counts_a_hull_in_two_cells_once():
    cores = [(56.0, 25.0, 56.5, 25.5), (56.5, 25.0, 57.0, 25.5)]
    ship = lambda lon, cat=dark_sts.AIS_UNMATCHED: {"id": 0, "lat": 25.2, "lon": lon, "category": cat,
                                                    "length_m": 200, "weak": False}
    a = {"scene": {"time": "t"}, "ships": [ship(56.2), ship(56.503)], "sts": [{"lat": 25.2, "lon": 56.501, "without_ais": 1}],
         "ais_available": True, "scene_note": None}
    b = {"scene": {"time": "t"}, "ships": [ship(56.503), ship(56.8, dark_sts.AIS_VISIBLE)],
         "sts": [{"lat": 25.2, "lon": 56.501, "without_ais": 1}], "ais_available": True}
    out = search.merge_cells([a, b], cores)
    assert [s["lon"] for s in out["ships"]] == [56.2, 56.503, 56.8] and [s["id"] for s in out["ships"]] == [0, 1, 2]
    assert len(out["sts"]) == 1 and out["counts"]["ships"] == 3 and out["cells_failed"] == 0
    part = search.merge_cells([a, {"error": "HTTP 429 from x"}], cores)
    assert part["cells_failed"] == 1 and "1 of 2 areas" in part["scene_note"]


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
