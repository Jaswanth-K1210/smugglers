"""Research contract: missing AIS is evidence about AIS, never a verdict, and weak where coverage is poor."""
import json

import pytest

from src import dark_sts, search
from src.dark_sts import identities_near

SHIP = {"category": dark_sts.AIS_UNMATCHED, "length_m": 250, "conf": 0.5, "n_ais": 0,
        "gfw_also_unmatched": False}
M = 1 / float(dark_sts._metres_between(25.0, 56.5, 26.0, 56.5))   # degrees per metre, in the matcher's own metric
T = "2026-09-27 02:15"


def test_poor_coverage_absence_earns_no_points():
    assert search.evidence(SHIP, cover={"label": "poor", "score": 0.2}) == []
    assert search.evidence(SHIP, cover={"label": "good", "score": 0.9}) == ["no_ais", "large_ship"]
    assert search.evidence(SHIP, cover={"label": "fair", "score": 0.5}) == ["no_ais", "large_ship"]


def test_independent_positive_evidence_survives_poor_coverage():
    tags = search.evidence({**SHIP, "gfw_also_unmatched": True}, sts_note="hull", cover={"label": "poor"})
    assert tags == ["gfw_radar_agrees", "hull_alongside"]


def test_ais_matched_ship_has_no_evidence_points():
    assert search.evidence({**SHIP, "category": dark_sts.AIS_VISIBLE}) == []


@pytest.mark.parametrize("cover", [None, {"label": "poor", "score": 0.2}, {"label": "good", "score": 0.9}])
def test_no_dark_word_anywhere_in_a_ship_payload(cover):
    ship = {**SHIP, "evidence": search.evidence(SHIP, cover=cover),
            "reasons": search.reasons(SHIP, True, "Another hull 150 m away.", cover=cover)}
    assert "dark" not in json.dumps(ship).lower()


def _ais(rows):
    import pandas as pd
    return pd.DataFrame([{"mmsi": m, "lat": 25.0 + dm * M, "lon": 56.5,
                          "timestamp": pd.Timestamp(T) + pd.Timedelta(seconds=ds)} for m, dm, ds in rows])


AT = {"lat": 25.0, "lon": 56.5, "time": T}


def test_identity_buffer_boundary_is_inclusive():
    assert identities_near(AT, _ais([(1, 499.5, 0)])) == {1}
    assert identities_near(AT, _ais([(1, 501.0, 0)])) == set()


def test_identity_window_boundary_is_inclusive():
    assert identities_near(AT, _ais([(1, 10, 12 * 3600)])) == {1}
    assert identities_near(AT, _ais([(1, 10, 12 * 3600 + 1)])) == set()
    assert identities_near(AT, _ais([(1, 10, -12 * 3600 - 1)])) == set()
