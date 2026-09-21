"""Land mask checks — the filter that keeps harbours out of the training labels.

    pytest tests/test_filters.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.filters import at_sea, drop_coastal, is_land, land_within  # noqa: E402

# The two harbours that produced 49% of one week's raw STS events, and two
# genuine offshore locations from the same week's data.
FREDERIKSHAVN = (57.72, 10.59)
HIRTSHALS = (57.59, 9.96)
SKAGEN_ANCHORAGE = (57.69827, 10.66889)   # ODIN / CLEAN FUTURE, 245 min
SKAGERRAK = (57.85, 10.30)


def test_harbours_are_land():
    assert is_land(*FREDERIKSHAVN)
    assert is_land(*HIRTSHALS)


def test_open_water_is_not_land():
    assert not is_land(*SKAGEN_ANCHORAGE)
    assert not is_land(*SKAGERRAK)


def test_harbours_are_rejected_by_clearance():
    assert not at_sea(*FREDERIKSHAVN)[0]
    assert not at_sea(*HIRTSHALS)[0]


def test_real_anchorage_transfer_survives():
    # A bunker vessel alongside a 299 m tanker at Skagen Red must not be culled.
    assert at_sea(*SKAGEN_ANCHORAGE)[0]
    assert at_sea(*SKAGERRAK)[0]


def test_clearance_is_stricter_than_a_point_lookup():
    # A spot can be water yet sit inside a harbour mouth; clearance catches it
    # where a single is_land lookup does not.
    lat, lon = 57.70, 10.58  # open water just outside Frederikshavn
    assert not is_land(lat, lon)
    assert not at_sea(lat, lon, 2.0)[0]


def test_land_within_grows_monotonically():
    lat, lon = SKAGERRAK
    near = land_within(lat, lon, 1.0)[0]
    far = land_within(lat, lon, 60.0)[0]
    assert not near and far, "60 km from this point must reach the Danish coast"


def test_vectorised_over_arrays():
    lats = np.array([FREDERIKSHAVN[0], SKAGERRAK[0]])
    lons = np.array([FREDERIKSHAVN[1], SKAGERRAK[1]])
    assert list(at_sea(lats, lons)) == [False, True]


def test_drop_coastal_filters_a_frame():
    ev = pd.DataFrame({
        "lat": [FREDERIKSHAVN[0], SKAGEN_ANCHORAGE[0], HIRTSHALS[0]],
        "lon": [FREDERIKSHAVN[1], SKAGEN_ANCHORAGE[1], HIRTSHALS[1]],
        "name": ["berth", "transfer", "berth"],
    })
    assert list(drop_coastal(ev).name) == ["transfer"]


def test_drop_coastal_handles_empty():
    assert drop_coastal(pd.DataFrame(columns=["lat", "lon"])).empty
