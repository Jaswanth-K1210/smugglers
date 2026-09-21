"""Characterise STS detections against AIS identity evidence.

The rule, as specified: buffer each `sts` detection by 500 m, count distinct AIS
identities within +/-12 hours.

What the count is allowed to mean is narrower than "dark". Per
RESEARCH_POSITION.md 4.3 the outcome is a *category*, not a verdict:

    2+ identities  AIS_VISIBLE      both partners broadcasting
    1  identity    AIS_PARTIAL      one silent, or a timing/coverage/matching
                                    limit, or our own localisation error
    0  identities  AIS_UNMATCHED    a dark candidate, and only a candidate

Nothing here returns a boolean called `dark`. Absence of AIS is absence of
evidence about AIS, which is not evidence of concealment — that inference needs
the fusion layer and even then comes out as a probability.

Both constants are provisional and are swept in RESEARCH_POSITION.md 4.6; the
+/-12 h window is the least justified number in the project.
"""
import numpy as np
import pandas as pd

from src.filters import EARTH_KM_PER_DEG

BUFFER_M = 500.0
WINDOW_H = 12.0

AIS_VISIBLE = "AIS_VISIBLE"
AIS_PARTIAL = "AIS_PARTIAL"
AIS_UNMATCHED = "AIS_UNMATCHED"


def _metres_between(lat1, lon1, lat2, lon2):
    """Equirectangular distance. Exact enough at the hundreds-of-metres scale."""
    lat1, lon1 = np.asarray(lat1, dtype=float), np.asarray(lon1, dtype=float)
    dlat = (np.asarray(lat2, dtype=float) - lat1) * EARTH_KM_PER_DEG * 1000
    dlon = ((np.asarray(lon2, dtype=float) - lon1) * EARTH_KM_PER_DEG * 1000
            * np.cos(np.radians(lat1)))
    return np.hypot(dlat, dlon)


def identities_near(detection, ais, buffer_m=BUFFER_M, window_h=WINDOW_H):
    """Distinct MMSI within `buffer_m` and `window_h` of a detection.

    `detection` needs lat, lon and time. `ais` needs mmsi, lat, lon, timestamp.
    """
    if ais is None or len(ais) == 0:
        return set()
    t = pd.Timestamp(detection["time"])
    lo, hi = t - pd.Timedelta(hours=window_h), t + pd.Timedelta(hours=window_h)
    near = ais[(ais.timestamp >= lo) & (ais.timestamp <= hi)]
    if near.empty:
        return set()
    d = _metres_between(detection["lat"], detection["lon"],
                        near.lat.to_numpy(), near.lon.to_numpy())
    return set(near.mmsi.to_numpy()[d <= buffer_m])


def categorise(n_identities: int) -> str:
    """Identity count to outcome category. Never returns a boolean."""
    if n_identities >= 2:
        return AIS_VISIBLE
    return AIS_PARTIAL if n_identities == 1 else AIS_UNMATCHED


def characterise(detections, ais, buffer_m=BUFFER_M, window_h=WINDOW_H):
    """Add identity evidence to a frame of STS detections.

    Adds `n_identities`, `mmsis` and `category`. Adds nothing called `dark`.
    """
    if detections is None or len(detections) == 0:
        return pd.DataFrame()
    rows = []
    for _, det in detections.iterrows():
        ids = identities_near(det, ais, buffer_m, window_h)
        rows.append({**det.to_dict(),
                     "n_identities": len(ids),
                     "mmsis": sorted(ids),
                     "category": categorise(len(ids))})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ais = pd.DataFrame({
        "mmsi": [1, 2], "lat": [57.7, 57.7], "lon": [10.6, 10.6005],
        "timestamp": pd.to_datetime(["2025-06-08 05:00", "2025-06-08 05:10"]),
    })
    det = pd.DataFrame([{"lat": 57.7, "lon": 10.6, "time": "2025-06-08 05:31"}])
    print(characterise(det, ais)[["n_identities", "category"]].to_string(index=False))
