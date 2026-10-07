"""Ships whose AIS was silent across the radar pass, and which detections they could be."""
import pandas as pd

from src import context, search

T = pd.Timestamp("2026-09-25 14:16")
BOX = (56.3, 25.0, 56.7, 25.4)


def _rows(vid, reports, name="SHIP"):
    return [{"vesselId": vid, "shipName": name, "mmsi": f"9{len(vid)}", "flag": "PAN", "imo": "9240794",
             "callsign": "X", "vesselType": "CARRIER", "lat": la, "lon": lo, "ts": T + pd.Timedelta(hours=h)}
            for h, la, lo in reports]


def test_silent_across_the_pass_and_reachable():
    rows = pd.DataFrame(
        _rows("quiet", [(-5, 25.2, 56.0), (4, 25.25, 56.9)], "QUIET") +          # off 5 h before, on 4 h after
        _rows("steady", [(-1.5, 25.2, 56.5), (0, 25.2, 56.5), (2, 25.2, 56.5)]) +  # reported at the pass
        _rows("far", [(-1.2, 22.0, 60.0), (1.5, 22.0, 60.0)]) +                   # silent, but 500 km away
        _rows("one_side", [(-6, 25.2, 56.5)]))                                    # never came back
    silent = context.silent_at_pass(rows, T, BOX)
    assert [r["key"] for r in silent] == ["quiet"]
    q = silent[0]
    assert (q["off"]["hours_before"], q["on"]["hours_after"], q["silent_h"]) == (5.0, 4.0, 9.0)
    assert q["name"] == "QUIET" and q["imo"] == "9240794" and q["type"] == "carrier"
    assert context.could_be(25.2, 56.5, T, silent) == ["quiet"]
    assert context.could_be(24.0, 59.5, T, silent) == []                         # too far to get there and back


def test_cells_share_one_silent_list_linked_to_renumbered_ships():
    q = {"key": "quiet", "could_be": []}
    cores = [(56.0, 25.0, 56.5, 25.5), (56.5, 25.0, 57.0, 25.5)]
    ship = lambda lon, m: {"id": 0, "lat": 25.2, "lon": lon, "category": "AIS_UNMATCHED", "length_m": 200,
                           "weak": False, "ais_silent_match": m}
    a = {"scene": {"time": "t"}, "ships": [ship(56.2, [])], "sts": [], "ais_silent": [dict(q)]}
    b = {"scene": {"time": "t"}, "ships": [ship(56.8, ["quiet"])], "sts": [], "ais_silent": [dict(q)]}
    out = search.merge_cells([a, b], cores)
    assert len(out["ais_silent"]) == 1 and out["ais_silent"][0]["could_be"] == [1]
