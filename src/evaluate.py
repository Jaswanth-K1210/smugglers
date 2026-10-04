"""How many AIS ships does the detector find? Scene-level recall against AIS.

For each Sentinel-1 pass over a region:
  1. detect at a low score (0.05) so every threshold can be scored afterwards
  2. AIS ships from GFW presence within +-1 h, one position per ship (nearest in time)
  3. keep only AIS ships the radar could see: inside the real footprint, on a
     valid pixel, at least 1 km from land (the detector's own land filter)
  4. match detections to AIS ships ONE-TO-ONE, closest pairs first, within
     MATCH_M. "Any ship within 2 km" would let one detection in a crowded
     anchorage count for five ships and inflate recall.

Per threshold: AIS recall (share of visible AIS ships matched), AIS-confirmed
share of detections, and unmatched detections per 1000 km2 (AIS-unmatched
candidates PLUS false alarms; this experiment cannot tell them apart).

Not measured, and why: vessel size and type (GFW presence gives neither), and
incidence angle (needs the GRD annotation files).

    modal run modal_eval.py            # runs scene_eval for every pass in parallel
"""
import numpy as np
import pandas as pd

from src import dark_sts, fetch_s1, gfw

THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
MATCH_M = 1500                # GFW presence cells are ~1.1 km; plus Doppler shift of movers
SHORE_BINS = [(1, 3), (3, 10), (10, 1e9)]


def greedy_match(det_lat, det_lon, ais_lat, ais_lon, radius_m=MATCH_M):
    """One-to-one pairs (det_index, ais_index), closest first, within radius_m."""
    det_lat, det_lon = np.asarray(det_lat, float), np.asarray(det_lon, float)
    ais_lat, ais_lon = np.asarray(ais_lat, float), np.asarray(ais_lon, float)
    if not len(det_lat) or not len(ais_lat):
        return []
    d = np.stack([dark_sts._metres_between(la, lo, ais_lat, ais_lon) for la, lo in zip(det_lat, det_lon)])
    pairs, used_d, used_a = [], set(), set()
    for k in np.argsort(d, axis=None):
        i, j = divmod(int(k), d.shape[1])
        if d[i, j] > radius_m:
            break
        if i not in used_d and j not in used_a:
            pairs.append((i, j))
            used_d.add(i)
            used_a.add(j)
    return pairs


def score(det, ais, area_km2, thresholds=THRESHOLDS):
    """Rows per threshold: n_det, n_ais, matched, recall, confirmed share, unmatched per 1000 km2."""
    rows = []
    for thr in thresholds:
        d = det[det.conf >= thr]
        m = len(greedy_match(d.lat, d.lon, ais.lat, ais.lon))
        rows.append({"threshold": thr, "n_det": len(d), "n_ais": len(ais), "matched": m,
                     "unmatched_det": len(d) - m, "area_km2": area_km2})
    return rows


def visible_ais(ais, t, tif, footprint, min_km=1.0):
    """One position per AIS ship, nearest the pass, that the radar could have seen."""
    import rasterio
    from shapely.geometry import Point, shape
    from src.filters import at_sea
    if ais.empty:
        return ais.assign(shore_km=[])
    a = ais.assign(dt=(ais.timestamp - t).abs()).sort_values("dt").drop_duplicates("mmsi")
    poly = shape(footprint)
    a = a[[poly.contains(Point(lo, la)) for la, lo in zip(a.lat, a.lon)]]
    a = a[at_sea(a.lat.to_numpy(), a.lon.to_numpy(), min_km)]
    if a.empty:
        return a.assign(shore_km=[])
    with rasterio.open(tif) as s:
        from rasterio.warp import transform
        xs, ys = transform("EPSG:4326", s.crs, a.lon.tolist(), a.lat.tolist())
        vals = [v[0] for v in s.sample(zip(xs, ys))]
    a = a[np.array(vals) > 0]
    shore = np.full(len(a), 1.0)
    for km in (3, 10):                                   # coarse distance-to-shore class
        shore[at_sea(a.lat.to_numpy(), a.lon.to_numpy(), km)] = km
    return a.assign(shore_km=shore).reset_index(drop=True)


def scene_eval(item, box, weights, out_dir="/tmp/eval"):
    """Detections at 0.05, visible AIS and per-threshold scores for one pass."""
    from pathlib import Path
    from shapely.geometry import box as rect, shape
    from src.filters import clean_detections
    from src.hunt import dedupe
    from src.run_pipeline import detect

    t = pd.Timestamp(item["properties"]["datetime"]).tz_localize(None)
    tif = fetch_s1.fetch(item, box=box, out_dir=Path(out_dir))
    det = detect(tif, weights, conf=THRESHOLDS[0])
    det = det[det.cls == "vessel"] if len(det) else det
    det = dedupe(clean_detections(det)) if len(det) else pd.DataFrame(columns=["lat", "lon", "conf"])
    ais = gfw.ais_presence(t - pd.Timedelta(hours=1), t + pd.Timedelta(hours=1), box)
    seen = visible_ais(ais, t, tif, item["geometry"])
    area = shape(item["geometry"]).intersection(rect(*box)).area * 111.32 * 110.57 * np.cos(np.radians((box[1] + box[3]) / 2))
    rows = score(det, seen, round(float(area)))
    # recall by distance from shore at each threshold
    by_shore = []
    for thr in THRESHOLDS:
        d = det[det.conf >= thr]
        hit = np.zeros(len(seen), bool)
        for _, j in greedy_match(d.lat, d.lon, seen.lat, seen.lon):
            hit[j] = True
        for lo, hi in SHORE_BINS:
            sel = (seen.shore_km >= lo) & (seen.shore_km < hi) if len(seen) else []
            by_shore.append({"threshold": thr, "shore": f"{lo}-{hi if hi < 1e8 else '+'} km",
                             "n_ais": int(np.sum(sel)), "matched": int(hit[sel].sum()) if len(seen) else 0})
    return {"scene": item["id"], "time": str(t), "n_ais_raw": int(ais.mmsi.nunique()) if len(ais) else 0,
            "rows": rows, "by_shore": by_shore,
            "conf": det.conf.round(3).tolist()}


def summarise(results):
    """Totals over scenes: one table per threshold, one per shore class."""
    rows = pd.DataFrame([r | {"scene": x["scene"]} for x in results for r in x["rows"]])
    t = rows.groupby("threshold")[["n_det", "n_ais", "matched", "unmatched_det"]].sum()
    area = rows.groupby("scene").area_km2.first().sum()
    t["recall"] = (t.matched / t.n_ais).round(3)
    t["ais_confirmed_share"] = (t.matched / t.n_det).round(3)
    t["unmatched_per_1000km2"] = (t.unmatched_det / area * 1000).round(1)
    t["f1_vs_ais"] = (2 * t.recall * t.ais_confirmed_share / (t.recall + t.ais_confirmed_share)).round(3)
    s = pd.DataFrame([r for x in results for r in x["by_shore"]]).groupby(["threshold", "shore"]).sum()
    s["recall"] = (s.matched / s.n_ais).round(3)
    return t.reset_index(), s.reset_index(), float(area)


def select_threshold(table, min_confirmed=0.6):
    """Operating threshold: the highest AIS recall whose AIS-confirmed share is >= min_confirmed.

    For finding ships without AIS, a missed ship costs more than a doubtful
    candidate, so recall leads; the floor keeps candidates mostly real ships
    (AIS-confirmed share is a lower bound on precision: some "unconfirmed"
    detections are genuine AIS-unmatched ships). None if no threshold qualifies.
    """
    ok = table[table.ais_confirmed_share >= min_confirmed]
    if ok.empty:
        return None
    row = ok.sort_values(["recall", "threshold"], ascending=[False, False]).iloc[0]
    return {"threshold": float(row.threshold), "recall": float(row.recall),
            "ais_confirmed_share": float(row.ais_confirmed_share), "min_confirmed": min_confirmed}
