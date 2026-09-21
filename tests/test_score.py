"""Phase 7: suspicion scoring behaves the way the definition says it does.

    pytest tests/test_score.py -v
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dark_sts import AIS_PARTIAL, AIS_UNMATCHED, AIS_VISIBLE  # noqa: E402
from src.score import (  # noqa: E402
    duration_term, lane_deviation_term, lanes_from_ais, sanctioned_term, score,
)

ZONES = [(57.0, 10.0)]
LANES = pd.DataFrame({"lat": [57.70], "lon": [10.60]})


def _ev(**kw):
    base = {"lat": 57.0, "lon": 10.0, "duration_min": 600, "category": AIS_UNMATCHED}
    return pd.DataFrame([{**base, **kw}])


def test_high_case_scores_near_one():
    # Unmatched, long, on a sanctioned zone, far from any lane.
    s = score(_ev(), zones=ZONES, lanes=LANES).suspicion.iloc[0]
    assert s > 0.8, s


def test_low_case_scores_near_zero():
    # Both partners broadcasting, brief, no zone, sitting on a lane.
    s = score(_ev(lat=57.70, lon=10.60, duration_min=60, category=AIS_VISIBLE),
              zones=None, lanes=LANES).suspicion.iloc[0]
    assert s < 0.05, s


def test_ais_visible_is_always_zero():
    # Whatever else is true, two broadcasting partners is not concealment.
    s = score(_ev(category=AIS_VISIBLE), zones=ZONES, lanes=LANES).suspicion.iloc[0]
    assert s == 0.0


def test_partial_scores_below_unmatched_all_else_equal():
    hi = score(_ev(category=AIS_UNMATCHED), zones=ZONES, lanes=LANES).suspicion.iloc[0]
    lo = score(_ev(category=AIS_PARTIAL), zones=ZONES, lanes=LANES).suspicion.iloc[0]
    assert lo < hi


def test_longer_contact_scores_higher():
    short = score(_ev(duration_min=60), zones=ZONES, lanes=LANES).suspicion.iloc[0]
    long = score(_ev(duration_min=720), zones=ZONES, lanes=LANES).suspicion.iloc[0]
    assert long > short


def test_duration_saturates():
    assert duration_term([12])[0] == pytest.approx(1.0)
    assert duration_term([48])[0] == pytest.approx(1.0)
    assert duration_term([6])[0] == pytest.approx(0.5)


def test_missing_zones_contribute_nothing():
    # Absent a zone list, proximity is unknown, and unknown must not inflate.
    assert sanctioned_term([57.0], [10.0], None)[0] == 0.0
    assert sanctioned_term([57.0], [10.0], [])[0] == 0.0


def test_sanctioned_term_decays_with_distance():
    near = sanctioned_term([57.0], [10.0], ZONES)[0]
    far = sanctioned_term([59.0], [14.0], ZONES)[0]
    assert near > 0.9 and far < near


def test_geojson_polygon_zone_is_accepted():
    gj = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[9.9, 56.9], [10.1, 56.9],
                                                         [10.1, 57.1], [9.9, 57.1], [9.9, 56.9]]]},
    }]}
    assert sanctioned_term([57.0], [10.0], gj)[0] > 0.9


def test_on_lane_is_zero_off_lane_is_high():
    assert lane_deviation_term([57.70], [10.60], LANES)[0] < 0.05
    assert lane_deviation_term([56.00], [12.00], LANES)[0] > 0.9


def test_lanes_from_ais_keeps_only_moving_vessels():
    ais = pd.DataFrame({"lat": [57.0, 57.1, 57.2], "lon": [10.0, 10.1, 10.2],
                        "sog": [0.1, 8.0, None]})
    assert len(lanes_from_ais(ais)) == 1


def test_results_are_ordered_and_explainable():
    ev = pd.concat([_ev(duration_min=60), _ev(duration_min=720)], ignore_index=True)
    out = score(ev, zones=ZONES, lanes=LANES)
    assert list(out.suspicion) == sorted(out.suspicion, reverse=True)
    for c in ("term_duration", "term_sanctioned", "term_lane_deviation"):
        assert c in out.columns, "a score nobody can explain is a score nobody trusts"


def test_empty_input():
    assert score(pd.DataFrame()).empty
