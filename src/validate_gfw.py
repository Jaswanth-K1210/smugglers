"""Compare our STS candidates against Global Fishing Watch's own layers.

GFW is a secondary evidence source (RESEARCH_POSITION.md 3.3) and never an
arbiter. Its layers are the output of somebody else's detector and matcher, with
their own population biases — notably toward industrial-size vessels.

The asymmetry that governs this file (4.2): a GFW *hit* is positive evidence, a
GFW *miss* is weak and never raises darkness confidence on its own. Measured
support in 4.2.1 — GFW gap events are near-zero in every region we work in, so
`gfw_gap` is expected to be uninformative and is carried only for the ablation.
"""
import pandas as pd

from src import gfw
from src.dark_sts import _metres_between

MATCH_M = 1000.0      # looser than the 500 m AIS buffer: GFW positions are gridded
MATCH_H = 12.0


def _events_frame(kind, start, end, box):
    total, entries = gfw.events(kind, start, end, box=box, limit=1000)
    rows = []
    for e in entries:
        pos = e.get("position") or {}
        if pos.get("lat") is None:
            continue
        rows.append({"kind": kind, "id": e.get("id"), "time": pd.Timestamp(e.get("start")),
                     "lat": pos.get("lat"), "lon": pos.get("lon"),
                     "vessel": (e.get("vessel") or {}).get("name")})
    print(f"GFW {kind}: {total} total, {len(rows)} with usable positions")
    return pd.DataFrame(rows)


def cross_check(detections, start: str, end: str, box=None,
                match_m: float = MATCH_M, match_h: float = MATCH_H):
    """Annotate detections with nearby GFW encounter and gap events.

    Adds `gfw_encounter` and `gfw_gap` booleans plus the matched ids. Both are
    evidence columns for the fusion layer; neither is a conclusion.
    """
    if detections is None or len(detections) == 0:
        return pd.DataFrame()

    layers = {}
    for kind in ("encounters", "gaps"):
        try:
            layers[kind] = _events_frame(kind, start, end, box)
        except Exception as e:
            print(f"GFW {kind} unavailable ({type(e).__name__}); recorded as missing, "
                  f"which is weak evidence either way")
            layers[kind] = pd.DataFrame()

    out = detections.copy()
    for kind, col in (("encounters", "gfw_encounter"), ("gaps", "gfw_gap")):
        df = layers[kind]
        hits, ids = [], []
        for _, det in out.iterrows():
            if df.empty:
                hits.append(False)
                ids.append(None)
                continue
            t = pd.Timestamp(det["time"])
            near = df[(df.time >= t - pd.Timedelta(hours=match_h)) &
                      (df.time <= t + pd.Timedelta(hours=match_h))]
            if near.empty:
                hits.append(False)
                ids.append(None)
                continue
            d = _metres_between(det["lat"], det["lon"], near.lat.to_numpy(), near.lon.to_numpy())
            m = near[d <= match_m]
            hits.append(len(m) > 0)
            ids.append(",".join(str(i) for i in m.id.tolist()) or None)
        out[col] = hits
        out[f"{col}_ids"] = ids
    return out


def agreement(detections):
    """Where we and GFW agree or differ, as a table rather than a verdict."""
    if detections.empty:
        return pd.DataFrame()
    return (detections.groupby(["category", "gfw_encounter"])
            .size().rename("n").reset_index()
            .sort_values("n", ascending=False))
