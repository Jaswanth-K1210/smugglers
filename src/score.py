"""Rank STS candidates by how much attention they deserve.

Three terms, as specified: dark duration, proximity to a sanctioned zone,
deviation from normal shipping lanes. No time-of-day term — night is not
suspicious, and SAR does not care about daylight.

What this is NOT: a probability that an event is illicit. It is a triage order,
so an analyst with an hour looks at the right twenty events first. The calibrated
probability belongs to the fusion model (RESEARCH_POSITION.md 4.4.5), and these
weights are the hand-written rule-based baseline that fusion has to beat
(baseline 3 in 4.4.3).

The weights below are declared, not derived. That is exactly why they are a
baseline rather than the contribution.
"""
import numpy as np
import pandas as pd

from src.dark_sts import AIS_PARTIAL, AIS_UNMATCHED, _metres_between

WEIGHTS = {"duration": 0.4, "sanctioned": 0.3, "lane_deviation": 0.3}

# Category multiplier. AIS_VISIBLE scores zero: both partners were broadcasting,
# so whatever else is true, it is not a concealment candidate.
CATEGORY_FACTOR = {AIS_UNMATCHED: 1.0, AIS_PARTIAL: 0.5}


def duration_term(hours, saturate_h: float = 12.0):
    """Longer contact, more opportunity. Saturating, not linear — the difference
    between 1 h and 6 h matters; between 30 h and 36 h it does not."""
    h = pd.to_numeric(pd.Series(hours), errors="coerce").fillna(0).clip(lower=0)
    return np.minimum(h / saturate_h, 1.0).to_numpy()


def sanctioned_term(lat, lon, zones, falloff_km: float = 50.0):
    """Proximity to the nearest sanctioned-zone centroid, decaying with distance.

    `zones` is a GeoJSON FeatureCollection, a list of (lat, lon), or None. With no
    zones supplied the term is zero for every event, which is honest: absent a
    zone list, proximity to one is unknown, and unknown must not inflate a score.
    """
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    pts = _zone_points(zones)
    if not pts:
        return np.zeros(len(lat))
    d = np.min([_metres_between(lat, lon, zlat, zlon) / 1000.0 for zlat, zlon in pts], axis=0)
    return np.exp(-d / falloff_km)


def _zone_points(zones):
    if not zones:
        return []
    if isinstance(zones, dict) and zones.get("type") == "FeatureCollection":
        pts = []
        for f in zones.get("features", []):
            g = f.get("geometry") or {}
            c = g.get("coordinates")
            if g.get("type") == "Point" and c:
                pts.append((c[1], c[0]))
            elif g.get("type") in ("Polygon", "MultiPolygon") and c:
                ring = c[0][0] if g["type"] == "MultiPolygon" else c[0]
                arr = np.asarray(ring, dtype=float)
                pts.append((float(arr[:, 1].mean()), float(arr[:, 0].mean())))
        return pts
    return [(float(a), float(b)) for a, b in zones]


def lane_deviation_term(lat, lon, lanes, falloff_km: float = 20.0):
    """How far off the normal traffic pattern the event sits.

    `lanes` are positions of ordinary moving traffic, taken from our own AIS —
    not an external lane product. On a lane, term is 0; far from any, term is 1.
    """
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    if lanes is None or len(lanes) == 0:
        return np.zeros(len(lat))
    llat = np.asarray(lanes["lat"] if hasattr(lanes, "columns") else [p[0] for p in lanes], float)
    llon = np.asarray(lanes["lon"] if hasattr(lanes, "columns") else [p[1] for p in lanes], float)
    out = np.empty(len(lat))
    for i in range(len(lat)):
        d = _metres_between(lat[i], lon[i], llat, llon).min() / 1000.0
        out[i] = 1.0 - np.exp(-d / falloff_km)
    return out


def lanes_from_ais(ais, min_sog: float = 5.0, sample: int = 4000, seed: int = 0):
    """Positions of vessels actually under way, as a proxy for shipping lanes."""
    if ais is None or len(ais) == 0:
        return pd.DataFrame(columns=["lat", "lon"])
    moving = ais[ais.sog.notna() & (ais.sog >= min_sog)][["lat", "lon"]]
    if len(moving) > sample:
        moving = moving.sample(sample, random_state=seed)
    return moving.reset_index(drop=True)


def score(events, zones=None, lanes=None, weights=None):
    """Add `suspicion` in 0..1 plus each term, so a score can be explained."""
    if events is None or len(events) == 0:
        return pd.DataFrame()
    w = {**WEIGHTS, **(weights or {})}
    e = events.copy()

    hours = (e["duration_min"] / 60.0 if "duration_min" in e
             else pd.Series(np.zeros(len(e)), index=e.index))
    e["term_duration"] = duration_term(hours)
    e["term_sanctioned"] = sanctioned_term(e.lat.to_numpy(), e.lon.to_numpy(), zones)
    e["term_lane_deviation"] = lane_deviation_term(e.lat.to_numpy(), e.lon.to_numpy(), lanes)

    raw = (w["duration"] * e.term_duration
           + w["sanctioned"] * e.term_sanctioned
           + w["lane_deviation"] * e.term_lane_deviation)
    factor = (e["category"].map(CATEGORY_FACTOR).fillna(0.0)
              if "category" in e else pd.Series(1.0, index=e.index))
    e["suspicion"] = (raw * factor).clip(0, 1).round(4)
    return e.sort_values("suspicion", ascending=False).reset_index(drop=True)
