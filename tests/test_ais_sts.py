"""Phase 1 checks: the run-grouping and the 500 m / 1 h / 1 kn rule itself.

Run-grouping is the fiddly part — a dropped AIS message must not split one long
contact into two sub-threshold halves, but a genuine hour-long separation must
still break the event in two.

    pytest tests/test_ais_sts.py -v
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ais_sts import _runs, sts_events  # noqa: E402

AOI = (9.5, 56.5, 12.5, 58.5)


def test_runs_unbroken():
    assert _runs([0, 1, 2, 3, 4]) == [(0, 4, 5)]


def test_runs_tolerates_one_dropped_bin():
    # 5 is missing: one lost AIS message, still a single contact.
    assert _runs([0, 1, 2, 3, 4, 6, 7, 8]) == [(0, 8, 8)]


def test_runs_splits_on_a_real_separation():
    # A 10-bin (50 min) hole is the vessels genuinely parting company.
    assert _runs([0, 1, 2, 20, 21, 22]) == [(0, 2, 3), (20, 22, 3)]


def test_runs_empty():
    assert _runs([]) == []


def _track(mmsi, lat, lon, start, minutes, sog=0.2, nav="At anchor", step=5):
    ts = pd.date_range(start, periods=minutes // step + 1, freq=f"{step}min")
    return pd.DataFrame({
        "timestamp": ts, "mmsi": mmsi, "lat": lat, "lon": lon, "sog": sog,
        "name": f"V{mmsi}", "ship_type": "Tanker", "length": 180.0, "width": 30.0,
        "nav_status": nav,
    })


def _run_rule(frames, monkeypatch, **kw):
    """Feed synthetic tracks through sts_events by stubbing the AIS loader."""
    import src.ais_sts as mod
    monkeypatch.setattr(mod.ais, "load", lambda d, box=None: pd.concat(frames, ignore_index=True))
    return sts_events(["2025-06-08"], box=AOI, **kw)


# 57.7N: 0.0010 deg lon ~ 60 m, 0.0100 deg lon ~ 600 m.
NEAR, FAR = 0.0010, 0.0100


def test_pair_close_and_slow_for_two_hours_is_an_event(monkeypatch):
    ev = _run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 120),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 02:00", 120),
    ], monkeypatch)
    assert len(ev) == 1
    assert ev.duration_min.iloc[0] >= 60
    assert {ev.mmsi_a.iloc[0], ev.mmsi_b.iloc[0]} == {1, 2}


def test_too_far_apart_is_not_an_event(monkeypatch):
    ev = _run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 120),
        _track(2, 57.7, 10.6 + FAR, "2025-06-08 02:00", 120),
    ], monkeypatch)
    assert len(ev) == 0


def test_too_brief_is_not_an_event(monkeypatch):
    ev = _run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 30),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 02:00", 30),
    ], monkeypatch)
    assert len(ev) == 0


def test_moving_vessels_are_not_an_event(monkeypatch):
    # Close and long enough, but both making way: a convoy, not a transfer.
    ev = _run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 120, sog=8.0),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 02:00", 120, sog=8.0),
    ], monkeypatch)
    assert len(ev) == 0


def test_moored_pair_is_excluded(monkeypatch):
    # Two boats alongside a quay satisfy the raw rule and are not a transfer.
    ev = _run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 120, nav="Moored"),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 02:00", 120, nav="Moored"),
    ], monkeypatch)
    assert len(ev) == 0
    # ...but only because we asked for it.
    assert len(_run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 120, nav="Moored"),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 02:00", 120, nav="Moored"),
    ], monkeypatch, exclude_moored=False)) == 1


def test_berth_length_contact_is_capped(monkeypatch):
    # 20 hours alongside is a berth, not a transfer.
    ev = _run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 00:00", 1200),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 00:00", 1200),
    ], monkeypatch)
    assert len(ev) == 0
    # The raw rule, without the cap, does report it.
    assert len(_run_rule([
        _track(1, 57.7, 10.6, "2025-06-08 00:00", 1200),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 00:00", 1200),
    ], monkeypatch, max_minutes=None)) == 1


def test_vessels_too_small_for_sar_are_excluded(monkeypatch):
    small = [
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 120).assign(length=9.0),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 02:00", 120).assign(length=12.0),
    ]
    assert len(_run_rule(small, monkeypatch)) == 0
    assert len(_run_rule(small, monkeypatch, min_length_m=0)) == 1


def test_unreported_length_is_excluded_not_assumed(monkeypatch):
    # Class B craft leave length blank; blank must not pass the gate.
    blank = [
        _track(1, 57.7, 10.6, "2025-06-08 02:00", 120).assign(length=float("nan")),
        _track(2, 57.7, 10.6 + NEAR, "2025-06-08 02:00", 120).assign(length=float("nan")),
    ]
    assert len(_run_rule(blank, monkeypatch)) == 0
