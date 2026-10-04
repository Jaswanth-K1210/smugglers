"""Context for AIS-unmatched ships: reachable gap events and maritime zones, worded as context."""
import pandas as pd

from src import context, dark_sts, search

T = pd.Timestamp("2026-09-27 02:14")


def gaps():
    return pd.DataFrame([
        {"start": T - pd.Timedelta(hours=6), "end": T + pd.Timedelta(hours=20), "lat": 25.25, "lon": 56.70,
         "name": "SEA STAR", "mmsi": "123", "flag": "PAN", "type": "tanker"},      # ~15 km, 6 h: reachable
        {"start": T - pd.Timedelta(hours=1), "end": T + pd.Timedelta(hours=5), "lat": 26.20, "lon": 56.55,
         "name": "FAR AWAY", "mmsi": "456", "flag": "LBR", "type": "cargo"},       # ~105 km, 1 h: not
    ])


def test_only_a_reachable_gap_counts():
    g = context.nearest_gap(25.25, 56.55, T, gaps())
    assert g["name"] == "SEA STAR" and 13 < g["km"] < 17 and g["hours"] == 6
    assert context.nearest_gap(25.25, 56.55, T, gaps().iloc[1:]) is None
    assert context.nearest_gap(25.25, 56.55, T, None) is None


def test_gap_reason_is_worded_as_a_possibility():
    text = context.gap_reason(context.nearest_gap(25.25, 56.55, T, gaps()))
    assert "SEA STAR, PAN" in text and "15 km" in text and "6 h before" in text
    assert "not proof" in text and "dark" not in text.lower()


def test_zone_from_marine_regions(monkeypatch):
    class R:
        def __init__(self, places): self.places = places
        def raise_for_status(self): pass
        def json(self): return self.places
    replies = iter([[{"placeType": "EEZ", "preferredGazetteerName": "Emirati Exclusive Economic Zone"},
                     {"placeType": "Territorial Sea", "preferredGazetteerName": "Emirati 12 NM"}],
                    [{"placeType": "EEZ", "preferredGazetteerName": "Iranian Exclusive Economic Zone"}],
                    [{"placeType": "IHO Sea Area", "preferredGazetteerName": "Indian Ocean"}]])
    monkeypatch.setattr(context.requests, "get", lambda *a, **k: R(next(replies)))
    context.zone.cache_clear()
    assert context.zone_reason(context.zone(25.25, 56.55)) == "Inside Emirati territorial waters (within 12 NM of the coast)."
    assert "Iranian Exclusive Economic Zone, outside territorial" in context.zone_reason(context.zone(25.07, 57.65))
    assert "high seas" in context.zone_reason(context.zone(10.0, 65.0))


def test_evidence_points_count_only_supporting_facts():
    ship = {"category": dark_sts.AIS_UNMATCHED, "length_m": 274, "gfw_also_unmatched": True, "conf": 0.9, "n_ais": 0}
    tags = search.evidence(ship, sts_note="Another hull 150 m away.", gap={"name": "X"})
    assert tags == ["no_ais", "large_ship", "gfw_radar_agrees", "hull_alongside", "nearby_ais_gap"]
    assert search.evidence({**ship, "category": dark_sts.AIS_VISIBLE}) == []
    assert "not a probability" in search.reasons(ship, ais_ok=True)[-1]
