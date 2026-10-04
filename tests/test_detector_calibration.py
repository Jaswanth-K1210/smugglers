"""The operating threshold is chosen by a stated rule from measured recall, not inherited."""
import json
from pathlib import Path

import pandas as pd
import pytest

from src import evaluate

TABLE = pd.DataFrame({"threshold": [0.1, 0.2, 0.3, 0.4], "recall": [0.83, 0.75, 0.67, 0.55],
                      "ais_confirmed_share": [0.59, 0.66, 0.69, 0.73]})


def test_highest_recall_above_the_confirmed_floor():
    assert evaluate.select_threshold(TABLE, 0.6)["threshold"] == 0.2
    assert evaluate.select_threshold(TABLE, 0.7)["threshold"] == 0.4
    assert evaluate.select_threshold(TABLE, 0.9) is None


@pytest.mark.parametrize("path", sorted(Path("outputs").glob("calibration_yolo26n_*.json")))
def test_saved_calibration_follows_the_rule(path):
    c = json.loads(path.read_text())
    assert c["model"] == "yolo26n" and c["scenes"] >= 10
    assert c["selected"] == evaluate.select_threshold(pd.DataFrame(c["table"]), c["selected"]["min_confirmed"])


def test_weak_candidates_stay_out_of_the_headline_counts():
    from src import dark_sts, search
    ships = [{"category": dark_sts.AIS_UNMATCHED, "weak": False}, {"category": dark_sts.AIS_VISIBLE, "weak": False},
             {"category": dark_sts.AIS_UNMATCHED, "weak": True}, {"category": dark_sts.AIS_UNMATCHED, "weak": True}]
    c = search.counts(ships, [{"without_ais": 1}, {"without_ais": None}])
    assert (c["ships"], c["ais_unmatched"], c["weak_candidates"], c["weak_ais_unmatched"]) == (2, 1, 2, 2)
    assert c["sts_pairs"] == 2 and c["sts_pairs_with_silent_hull"] == 1


def test_served_thresholds_match_the_decision():
    from src import search
    assert (search.SHIP_CONF, search.WEAK_CONF) == (0.25, 0.15)   # 0.15 is not headline until T3 says so
