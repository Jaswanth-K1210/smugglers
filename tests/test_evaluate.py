"""Recall against AIS: one detection can match one AIS ship only."""
import pandas as pd

from src import evaluate

D = 1 / 111_000                                   # degrees per metre of latitude


def test_one_detection_cannot_match_several_ships():
    det_lat, det_lon = [25.0], [56.5]
    ais_lat = [25.0 + 200 * D, 25.0 + 400 * D, 25.0 + 600 * D]  # three ships within 1.5 km of one blob
    assert evaluate.greedy_match(det_lat, det_lon, ais_lat, [56.5] * 3) == [(0, 0)]


def test_closest_pairs_win_and_radius_holds():
    pairs = evaluate.greedy_match([25.0, 25.0 + 1000 * D], [56.5, 56.5],
                                  [25.0 + 900 * D, 25.0 + 5000 * D], [56.5, 56.5])
    assert pairs == [(1, 0)]                      # det 1 is 100 m away; the far ship is unmatched


def test_score_per_threshold():
    det = pd.DataFrame({"lat": [25.0, 25.1], "lon": [56.5, 56.5], "conf": [0.6, 0.2]})
    ais = pd.DataFrame({"lat": [25.0, 25.1, 25.3], "lon": [56.5, 56.5, 56.5]})
    rows = {r["threshold"]: r for r in evaluate.score(det, ais, 100, thresholds=[0.1, 0.5])}
    assert (rows[0.1]["matched"], rows[0.5]["matched"]) == (2, 1)
    assert rows[0.5]["unmatched_det"] == 0 and rows[0.1]["n_ais"] == 3
