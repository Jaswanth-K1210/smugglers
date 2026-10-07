"""Worldwide 'AIS went silent at sea' from the live feed: real silences, not ships leaving reception."""
import pytest

from webapp.backend import feeds

T = 1_000_000.0


@pytest.fixture(autouse=True)
def clean():
    for d in (feeds.ships, feeds.tracks, feeds.quiet, feeds.statics):
        d.clear()
    yield
    for d in (feeds.ships, feeds.tracks, feeds.quiet, feeds.statics):
        d.clear()


def _pos(mmsi, lat, lon, t, sog=12.0, cog=90.0, status=0):
    feeds._store({"MessageType": "PositionReport", "MetaData": {"MMSI": mmsi, "ShipName": f"S{mmsi}", "latitude": lat, "longitude": lon},
                  "Message": {"PositionReport": {"Sog": sog, "Cog": cog, "NavigationalStatus": status}}}, t)


def _crowd(lat, lon, t, base):
    for i in range(3):                                   # ships still heard nearby
        _pos(base + i, lat + 0.02 * i, lon + 0.02, t, sog=0.2)


def test_silent_where_others_are_heard_then_back_on():
    _pos(1, 57.5, 10.5, T)                                # under way east at 12 kn, then nothing
    _crowd(57.5, 10.5, T + 2400, 100)                     # heard where it was...
    _crowd(57.5, 10.85, T + 2400, 200)                    # ...and where it should be after 40 min
    _pos(2, 57.0, 5.0, T, sog=25.0, cog=270.0)            # silent, but nobody heard 31 km ahead: out of range
    _crowd(57.0, 5.0, T + 2400, 300)
    _pos(3, 57.5, 10.5, T, sog=0.0, status=5)             # moored: slow reports are normal
    feeds.find_quiet(T + 2400)
    assert list(feeds.quiet) == [1]
    rows = feeds.silent_at_sea(now=T + 3600)
    assert rows[0]["mmsi"] == "1" and rows[0]["silent_h"] == 1.0 and rows[0]["on"] is None
    assert feeds.vessel("1", now=T + 3600)["lat"] == 57.5              # ship card: last report
    _pos(1, 57.6, 11.2, T + 3 * 3600)                     # AIS back on, 3 h later, ~45 km on
    back = feeds.silent_at_sea(now=T + 4 * 3600, state="back")
    assert back[0]["silent_h"] == 3.0 and back[0]["on"]["moved_km"] > 40
    assert feeds.silent_at_sea(now=T + 4 * 3600, state="silent") == []
