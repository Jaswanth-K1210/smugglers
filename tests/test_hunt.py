"""Region search safeguards: duplicates collapse, missing-AIS scenes are excluded."""
import pandas as pd

from src import hunt


def test_dedupe_keeps_most_confident_per_150m():
    d = pd.DataFrame([
        {"scene": "a", "conf": 0.5, "lat": 25.0, "lon": 56.5},
        {"scene": "a", "conf": 0.9, "lat": 25.0005, "lon": 56.5},   # ~55 m away
        {"scene": "a", "conf": 0.4, "lat": 25.01, "lon": 56.5},     # ~1.1 km away
        {"scene": "b", "conf": 0.3, "lat": 25.0, "lon": 56.5},      # other scene
    ])
    got = hunt.dedupe(d).sort_values(["scene", "conf"])
    assert got.conf.tolist() == [0.4, 0.9, 0.3]


def test_thin_scenes_excluded():
    cells = {"s1": 1400, "s2": 1500, "s3": 0, "s4": 93, "s5": 1100}
    assert hunt.thin_scenes(cells) == {"s3", "s4"}
    assert hunt.thin_scenes({"x": 0}) == {"x"}
