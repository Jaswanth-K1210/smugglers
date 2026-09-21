"""Phase 6: the four specified cases for the 500 m / +/-12 h identity rule.

    pytest tests/test_dark_sts.py -v

The specification names these as "2 identities = not dark, 0 = dark, 1 =
dark/half-dark, 2 but 20h away = dark". They are asserted here under the
three-category naming of RESEARCH_POSITION.md 4.3, which keeps exactly-one
identity distinct from zero instead of collapsing both into "dark".
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dark_sts import (  # noqa: E402
    AIS_PARTIAL, AIS_UNMATCHED, AIS_VISIBLE, categorise, characterise, identities_near,
)

T = pd.Timestamp("2025-06-08 05:31:31")          # the real Skagen overpass
AT = {"lat": 57.69827, "lon": 10.66889, "time": T}   # the ODIN / CLEAN FUTURE spot


def _ais(rows):
    """rows: (mmsi, metres_east, hours_offset)."""
    return pd.DataFrame([{
        "mmsi": m,
        "lat": AT["lat"],
        # 1 deg lon ~ 111320*cos(57.7) m ~ 59,500 m here
        "lon": AT["lon"] + east_m / (111320 * 0.5347),
        "timestamp": T + pd.Timedelta(hours=dt),
    } for m, east_m, dt in rows])


# --- the four specified cases ---------------------------------------------

def test_two_identities_in_window_is_ais_visible():
    ais = _ais([(111, 50, 0.0), (222, 120, 0.5)])
    assert characterise(pd.DataFrame([AT]), ais).category.iloc[0] == AIS_VISIBLE


def test_zero_identities_is_ais_unmatched():
    # Both far outside the 500 m buffer.
    ais = _ais([(111, 5000, 0.0), (222, 9000, 0.0)])
    assert characterise(pd.DataFrame([AT]), ais).category.iloc[0] == AIS_UNMATCHED


def test_one_identity_is_partial_not_unmatched():
    # The case the specification called "dark/half-dark". It must stay its own
    # category: one silent partner, a timing limit and a localisation error are
    # not distinguishable here, so collapsing it into "dark" overclaims.
    ais = _ais([(111, 80, 0.0), (222, 4000, 0.0)])
    row = characterise(pd.DataFrame([AT]), ais).iloc[0]
    assert row.n_identities == 1
    assert row.category == AIS_PARTIAL
    assert row.category != AIS_UNMATCHED


def test_two_identities_twenty_hours_away_is_ais_unmatched():
    # Close in space, far outside the +/-12 h window.
    ais = _ais([(111, 50, 20.0), (222, 120, -20.0)])
    assert characterise(pd.DataFrame([AT]), ais).category.iloc[0] == AIS_UNMATCHED


# --- boundaries and guarantees --------------------------------------------

def test_buffer_edge():
    assert len(identities_near(AT, _ais([(111, 450, 0)]))) == 1
    assert len(identities_near(AT, _ais([(111, 900, 0)]))) == 0


def test_window_edge():
    assert len(identities_near(AT, _ais([(111, 50, 11.5)]))) == 1
    assert len(identities_near(AT, _ais([(111, 50, 12.5)]))) == 0


def test_repeated_pings_count_once():
    ais = _ais([(111, 50, 0.0), (111, 60, 1.0), (111, 70, 2.0)])
    assert characterise(pd.DataFrame([AT]), ais).category.iloc[0] == AIS_PARTIAL


def test_no_ais_at_all_is_unmatched_not_an_error():
    assert characterise(pd.DataFrame([AT]), pd.DataFrame()).category.iloc[0] == AIS_UNMATCHED


def test_output_never_contains_a_dark_flag():
    # The epistemic guarantee of RESEARCH_POSITION.md 4.2, enforced in code.
    out = characterise(pd.DataFrame([AT]), _ais([(111, 50, 0)]))
    assert not any("dark" in c.lower() for c in out.columns)
    assert all(v in (AIS_VISIBLE, AIS_PARTIAL, AIS_UNMATCHED) for v in out.category)


@pytest.mark.parametrize("n,expected", [(0, AIS_UNMATCHED), (1, AIS_PARTIAL),
                                        (2, AIS_VISIBLE), (7, AIS_VISIBLE)])
def test_categorise(n, expected):
    assert categorise(n) == expected
