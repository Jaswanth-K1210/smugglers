"""Area-on-demand search: a box in, ships and plain-language reasons out.

The website's one heavy call. Same steps as the region search (`hunt.run`), for
the newest Sentinel-1 pass over one box:

  1. newest pass covering at least half the box (Planetary Computer)
  2. warp the box to UTM / 10 m
  3. detector (YOLO26n by default) on every 1024 px tile, edges included
  4. land / length / infrastructure filters, duplicate removal
  5. AIS identities within 2 km / +-1 h (GFW presence)
  6. hull measurement and side-by-side pairs (STS), counted radar vs AIS
  7. GFW's own radar detections as an independent check
  8. one reason per piece of evidence, in words

Wording follows RESEARCH_POSITION.md: a ship with no AIS match is an
"AIS-unmatched candidate". Nothing here says "dark".
"""
import base64
import io
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src import context, dark_sts, fetch_s1, gfw, hunt, match, regional_ais
from src.config import DATA

MIN_KM, MAX_KM = 11, 60       # one 1024 px tile ... the free-CPU time budget
LOOKBACK_DAYS = 12            # Sentinel-1 revisit is ~6 days with S1C + S1D
MIN_OVERLAP = 0.5
CACHE = DATA / "search_cache"
CHIPS = 40                    # image chips returned, AIS-unmatched first
NOT_AVAILABLE = "AIS_NOT_AVAILABLE"
# YOLO26n operating point (RESULTS.md §7): 0.25 finds 71 % of visible AIS ships vs 55 % at
# the RT-DETR-era 0.40. Scores 0.15-0.25 are kept as weak candidates, hidden by default and
# outside the headline counts, until per-band precision from human review (test plan T3)
# shows whether they hold >= 0.80.
SHIP_CONF, WEAK_CONF = 0.25, 0.15
CACHE_VERSION = 3             # bump when results change, so stale cached searches are not served


MAX_PERIOD_DAYS, MAX_PASSES = 31, 6     # time-period search limits (docs/DEPLOYMENT_PLAN.md §2)
ARCHIVE_START = pd.Timestamp("2014-10-03")   # first Sentinel-1 IW data on Planetary Computer
RECUR_M = 300                 # same spot on two passes: likely a fixed structure or a ship at anchor


def box_km(box):
    lon0, lat0, lon1, lat1 = box
    return ((lon1 - lon0) * 111.32 * math.cos(math.radians((lat0 + lat1) / 2)), (lat1 - lat0) * 110.57)


def validate(box):
    """Raise ValueError with a sentence a user can act on."""
    if len(box) != 4:
        raise ValueError("Send the box as [west, south, east, north].")
    lon0, lat0, lon1, lat1 = map(float, box)
    if not (-180 <= lon0 < lon1 <= 180 and -85 <= lat0 < lat1 <= 85):
        raise ValueError("The box corners are out of order or off the map.")
    w, h = box_km(box)
    if min(w, h) < MIN_KM:
        raise ValueError(f"Draw a box at least {MIN_KM} km on each side (this one is {w:.0f} × {h:.0f} km).")
    if max(w, h) > MAX_KM:
        raise ValueError(f"Draw a box at most {MAX_KM} km on each side (this one is {w:.0f} × {h:.0f} km).")
    return lon0, lat0, lon1, lat1


def scenes(box, end=None, days=LOOKBACK_DAYS):
    """Passes covering at least half the box, newest first."""
    end = pd.Timestamp(end or pd.Timestamp.utcnow()).tz_localize(None)
    items = fetch_s1.search(f"{end - pd.Timedelta(days=days):%Y-%m-%d}", f"{end:%Y-%m-%d}", box=box, limit=100)
    return [i for i in items if fetch_s1.overlap(i, box) >= MIN_OVERLAP]


def scene_time(item):
    return pd.Timestamp(item["properties"]["datetime"]).tz_localize(None)


def pick_scene(items, box, tries=4):
    """(item, ais, note): the newest pass whose AIS can be checked.

    GFW AIS lags the satellite by a few days, so the very newest pass often has
    none yet; calling every ship on it "unmatched" would be wrong. Look back up
    to `tries` passes for one with AIS, and say so when it is not the newest.
    """
    for item in items[:tries]:
        t = scene_time(item)
        try:
            ais = gfw.ais_presence(t - pd.Timedelta(hours=2), t + pd.Timedelta(hours=2), box)
        except Exception:
            ais = pd.DataFrame()
        if not len(ais) and regional_window(box, t)[1]:
            ais = pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"])
            return item, ais, (None if item is items[0] else
                               f"Shows the newest pass with recorded AIS ({t:%d %b %H:%M} UTC).")
        if len(ais):
            note = None if item is items[0] else (
                f"The newest pass ({scene_time(items[0]):%d %b %H:%M} UTC) has no AIS data yet, so this "
                f"shows the newest pass that can be checked against AIS ({t:%d %b %H:%M} UTC).")
            return item, ais, note
    return items[0], pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"]), (
        "AIS for the recent passes over this box is not available yet; ships are shown unchecked.")


def counts(ships, sts):
    """Headline counts from full-strength ships only; weak candidates counted apart."""
    strong = [s for s in ships if not s.get("weak")]
    weak = [s for s in ships if s.get("weak")]
    return {"ships": len(strong),
            "ais_unmatched": sum(s["category"] == dark_sts.AIS_UNMATCHED for s in strong),
            "weak_candidates": len(weak),
            "weak_ais_unmatched": sum(s["category"] == dark_sts.AIS_UNMATCHED for s in weak),
            "sts_pairs": len(sts),
            "sts_pairs_with_silent_hull": sum((p["without_ais"] or 0) > 0 for p in sts)}


def evidence(ship, sts_note=None, gap=None, cover=None):
    """Tags for the evidence points that make an AIS-unmatched ship worth review.

    Missing AIS only counts where AIS coverage was fair or good: with poor
    coverage the absence is mostly reception, and neither it nor the size rule
    built on it ("ships this size must broadcast") may raise the count.
    """
    if ship["category"] != dark_sts.AIS_UNMATCHED:
        return []
    tags = []
    if cover is None or cover.get("label") in ("good", "fair"):
        tags.append("no_ais")
        if ship["length_m"] and ship["length_m"] >= 100:
            tags.append("large_ship")
    if ship.get("gfw_also_unmatched"):
        tags.append("gfw_radar_agrees")
    if sts_note:
        tags.append("hull_alongside")
    if gap:
        tags.append("nearby_ais_gap")
    return tags


def reasons(ship, ais_ok, sts_note=None, gap=None, zone=None, sources="Global Fishing Watch", cand_note=None,
            cover=None):
    """Evidence for one ship, one sentence each."""
    out = []
    if not ais_ok:
        out.append("AIS for this hour is not available yet, so this ship could not be checked against AIS.")
    elif ship["category"] == dark_sts.AIS_UNMATCHED:
        out.append(f"No AIS identity within 2 km and ±1 h of the radar pass (AIS sources: {sources}).")
        if cover and cover["label"] != "none":
            out.append(f"AIS coverage here was {cover['label']} ({cover['score']:.2f}), so this absence is "
                       f"{'strong' if cover['label'] == 'good' else 'weak' if cover['label'] == 'poor' else 'moderate'} "
                       "evidence about AIS, not about intent.")
    else:
        n = int(ship["n_ais"])
        out.append(f"Matches {n} AIS identit{'y' if n == 1 else 'ies'} within 2 km of the radar position.")
    length = ship["length_m"]
    if length:
        size = (" Most ships this size must broadcast AIS (SOLAS)." if length >= 100 else "")
        out.append(f"Radar length ≈ {length:.0f} m.{size}")
    if ship.get("gfw_also_unmatched"):
        out.append("Global Fishing Watch's own Sentinel-1 detections also show no AIS match here.")
    if sts_note:
        out.append(sts_note)
    if cand_note:
        out.append(cand_note)
    if gap:
        out.append(context.gap_reason(gap))
    if zone:
        out.append(zone)
    out.append(f"Detector score {ship['conf']:.2f} (how sure the model is that this is a ship, not a probability).")
    return out


def chip_png(tif, x, y, half=60):
    """Small stretched PNG of the radar around (x, y), base64."""
    import rasterio
    from PIL import Image
    with rasterio.open(tif) as s:
        r, c = s.index(x, y)
        img = s.read(1, window=rasterio.windows.Window(c - half, r - half, 2 * half, 2 * half),
                     boundless=True, fill_value=0).astype(float)
    v = img[img > 0]
    lo, hi = np.percentile(v, [1, 99.5]) if v.size else (0, 1)
    png = (np.clip((img - lo) / max(hi - lo, 1), 0, 1) * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(png).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def regional_window(box, t, minutes=60):
    """(positions, has_data_at_pass): our recorded Gulf AIS around the pass, if the box is in the Gulf.

    has_data_at_pass needs reports within 30 min of the pass; positions span ±`minutes`
    so dead reckoning can bring nearby reports to the pass time."""
    if not regional_ais.covers(box):
        return None, False
    pad = 0.15                     # ships just outside the box can still be the hull at its edge
    w, s, e, n = box
    reg = regional_ais.load_window(t - pd.Timedelta(minutes=minutes), t + pd.Timedelta(minutes=minutes),
                                   (w - pad, s - pad, e + pad, n + pad))
    near = (reg.timestamp - t).abs() <= pd.Timedelta(minutes=30) if len(reg) else []
    return reg, bool(len(reg) and near.any())


def _at_pass(reg, t):
    """Each regional ship's report nearest the pass, dead-reckoned to the pass time."""
    if reg is None or not len(reg):
        return pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"])
    r = reg.assign(_dt=(reg.timestamp - t).abs()).sort_values("_dt").drop_duplicates("mmsi")
    moved = [match.project(a.lat, a.lon, a.sog, a.cog, (t - a.timestamp).total_seconds() / 3600)
             for a in r.itertuples(index=False)]
    return pd.DataFrame({"mmsi": r.mmsi.to_numpy(), "lat": [m[0] for m in moved], "lon": [m[1] for m in moved],
                         "timestamp": t})


def run(box, weights, progress=lambda stage, frac: None, end=None, cache=CACHE):
    """Search one box on its newest checkable pass; returns a JSON-ready dict.

    Raises ValueError / LookupError for user errors.
    """
    box = validate(box)
    progress("Finding the newest Sentinel-1 pass over your box", 0.05)
    items = scenes(box, end)
    if not items:
        raise LookupError(f"No Sentinel-1 pass covered at least half of this box in the last "
                          f"{LOOKBACK_DAYS} days. Try a box further from the coast or a bit larger.")
    progress("Checking which pass already has AIS data", 0.1)
    item, ais, scene_note = pick_scene(items, box)
    return run_pass(item, box, weights, ais, scene_note, progress, cache)


def ais_for_pass(item, box):
    """GFW AIS presence within ±2 h of the pass; empty (never an error) when GFW has none or fails."""
    t = scene_time(item)
    try:
        return gfw.ais_presence(t - pd.Timedelta(hours=2), t + pd.Timedelta(hours=2), box)
    except Exception:
        return pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"])


def run_pass(item, box, weights, ais=None, scene_note=None, progress=lambda stage, frac: None, cache=CACHE):
    """Everything after the pass is chosen: download, detect, AIS, hulls, pairs, reasons."""
    from src.filters import clean_detections
    from src.run_pipeline import detect

    box = validate(box)
    if ais is None:
        progress("Getting AIS for this pass", 0.1)
        ais = ais_for_pass(item, box)
    key = f"v{CACHE_VERSION}_{item['id']}_{'_'.join(f'{v:.3f}' for v in box)}"
    hit = Path(cache) / f"{key}.json"
    if hit.exists():
        progress("Found an earlier search of this pass", 1.0)
        return {**json.loads(hit.read_text()), "cached": True}

    progress("Downloading the radar image", 0.15)
    tif = fetch_s1.fetch(item, box=box, out_dir=Path(cache) / "scenes" / key)
    t = scene_time(item)

    progress("Detecting ships", 0.4)
    det = detect(tif, weights, conf=WEAK_CONF)
    if len(det):
        det = det[(det.cls == "sts") | (det.conf >= WEAK_CONF)].copy()
        det["weak"] = (det.cls == "vessel") & (det.conf < SHIP_CONF)
        det["tif"] = str(tif)
        det = hunt.dedupe(clean_detections(det)) if len(det) else det

    result = {"scene": {"id": item["id"], "time": t.isoformat() + "Z",
                        "platform": item["properties"].get("platform")},
              "bbox": list(box), "ais_source": "Global Fishing Watch (hourly presence)",
              "scene_note": scene_note,
              "cached": False, "ships": [], "sts": []}
    if len(det):
        progress("Matching ships to AIS", 0.6)
        reg, reg_ok = regional_window(box, t)
        ais_ok = len(ais) > 0 or reg_ok
        res = dark_sts.characterise(det, ais, buffer_m=2000, window_h=1)
        if reg_ok:
            # Two sources can report the same ship under different ids (no shared MMSI), so take the
            # larger count, never the sum: summing would turn one ship into "two identities".
            reg_res = dark_sts.characterise(det, _at_pass(reg, t), buffer_m=2000, window_h=1)
            res["n_identities"] = np.maximum(res.n_identities.to_numpy(), reg_res.n_identities.to_numpy())
            res["mmsis"] = [sorted(set(a) | set(b)) for a, b in zip(res.mmsis, reg_res.mmsis)]
            res["category"] = [dark_sts.categorise(int(n)) for n in res.n_identities]
        if not ais_ok:
            res["category"] = NOT_AVAILABLE
        sources = {"Global Fishing Watch": len(ais) > 0}
        if reg is not None:
            sources[regional_ais.SOURCE] = reg_ok
        source_names = ", ".join(k for k, v in sources.items() if v) or "none"
        result["ais_source"] = source_names + (" (regional feed: " + regional_ais.ATTRIBUTION + ")" if reg_ok else "")

        progress("Measuring hulls and looking for ships side by side", 0.75)
        res = hunt.hull_shape(res)
        res["wide"] = False           # one box has too few AIS-matched ships to calibrate width
        sts = hunt.sts_candidates(res[~res.weak.astype(bool)])   # pairs only from full-strength hulls
        if len(sts):
            # Both sources together: a ship seen by both counts twice here, which can only
            # understate silent hulls, never invent one.
            both = pd.concat([ais[["mmsi", "lat", "lon", "timestamp"]], _at_pass(reg, t)]) if reg_ok else ais
            sts = hunt.count_identities(sts, res, {res.scene.iloc[0]: both})
            sts["tier"] = np.where(sts.evidence.str.contains("rafted"), "A", "B")

        progress("Cross-checking with Global Fishing Watch radar detections", 0.85)
        res["gfw_also_unmatched"] = False
        if ais_ok and (res.category == dark_sts.AIS_UNMATCHED).any():
            try:
                g = gfw.sar_unmatched(str(t.date()), box)
                if len(g):
                    res["gfw_also_unmatched"] = [
                        r.category == dark_sts.AIS_UNMATCHED and
                        bool((hunt.near(r.lat, r.lon, g.lat, g.lon) < 1500).any()) for _, r in res.iterrows()]
            except Exception:
                pass                  # an independent check failing must not fail the search

        progress("Writing the reasons", 0.95)
        notes = {}
        for _, s in sts.iterrows() if len(sts) else []:
            note = (f"Seen beside another hull {s.spacing_m:.0f} m away (ships moored together)."
                    if s.tier == "A" else f"Another hull {s.spacing_m:.0f} m away (within 500 m).")
            for i in res.index[hunt.near(s.lat, s.lon, res.lat, res.lon) <= max(s.spacing_m, 50) / 2 + 30]:
                notes[i] = note
        gaps = None
        if ais_ok and (res.category == dark_sts.AIS_UNMATCHED).any():
            progress("Looking for nearby AIS gap events and maritime zones", 0.97)
            try:
                gaps = context.gap_events(box, t)
            except Exception:
                gaps = None           # context failing must not fail the search
        progress("Scoring AIS coverage and nearby AIS candidates", 0.98)
        gfw_c = ais.assign(sog=np.nan, cog=np.nan, length_m=np.nan, name=None) if len(ais) else None
        prelim = [{"length_m": float(r.hull_m if r.hull_m == r.hull_m else r.length_m),
                   "n_ais": int(r.n_identities)} for _, r in res.iterrows()]
        in_box = max(ais.mmsi.nunique() if len(ais) else 0, reg.mmsi.nunique() if reg_ok else 0)
        signs = match.jamming_signs(reg) if reg_ok else {}
        cover = match.coverage(sources, prelim, in_box, signs) if ais_ok else {"score": 0.0, "label": "none",
                                                                             "factors": []}
        result["coverage"] = cover
        result["jamming_signs"] = signs or None
        order = res.assign(_u=(res.category == dark_sts.AIS_UNMATCHED), _w=res.weak.astype(bool)).sort_values(
            ["_w", "_u", "length_m"], ascending=[True, False, False])          # weak candidates last
        for n, (i, r) in enumerate(order.iterrows()):
            unmatched = r.category == dark_sts.AIS_UNMATCHED
            gap = context.nearest_gap(r.lat, r.lon, t, gaps) if unmatched else None
            zone = context.zone_reason(context.zone_at(r.lat, r.lon)) if unmatched and n < CHIPS else None
            ship = {"id": int(n), "lat": round(float(r.lat), 5), "lon": round(float(r.lon), 5),
                    "length_m": round(float(r.hull_m if r.hull_m == r.hull_m else r.length_m)),
                    "beam_m": None if r.beam_m != r.beam_m else round(float(r.beam_m)),
                    "conf": round(float(r.conf), 3), "category": r.category,
                    "n_ais": int(r.n_identities), "gfw_also_unmatched": bool(r.gfw_also_unmatched),
                    "weak": bool(r.weak)}
            cands = []
            if ais_ok:
                hull = ship["length_m"] or None
                cands = sorted(match.candidates(r.lat, r.lon, t, gfw_c, hull, "Global Fishing Watch")
                               + (match.candidates(r.lat, r.lon, t, reg, hull, regional_ais.SOURCE) if reg_ok else []),
                               key=lambda c: (not c["plausible"], c["size"] == "mismatch", c["distance_m"]))
            ship["ais_candidates"] = cands[:3]
            ship["coverage"] = cover["label"]
            ship["reasons"] = reasons(ship, ais_ok, notes.get(i), gap, zone, source_names,
                                      match.explain(cands), cover)
            if ship["weak"]:
                ship["reasons"].insert(0, f"Weak candidate: detector score {ship['conf']:.2f} is below "
                                          f"{SHIP_CONF:.2f}. Hidden by default; how often scores this low are "
                                          "real ships has not been measured yet.")
            ship["evidence"] = evidence(ship, notes.get(i), gap, cover)
            ship["evidence_points"] = len(ship["evidence"])
            ship["zone"] = zone
            ship["nearby_ais_gap"] = None if not gap else {
                "vessel": gap["name"] or None, "mmsi": gap["mmsi"], "flag": gap["flag"],
                "km": round(gap["km"], 1), "hours_before_pass": round(gap["hours"], 1)}
            ship["chip_png"] = chip_png(tif, r.x, r.y) if n < CHIPS else None
            result["ships"].append(ship)
        result["sts"] = [{"lat": round(float(s.lat), 5), "lon": round(float(s.lon), 5),
                          "tier": s.tier, "spacing_m": int(s.spacing_m), "radar_hulls": int(s.n_radar),
                          "ais_identities": int(s.n_ais) if ais_ok else None,
                          "without_ais": int(s.missing) if ais_ok else None}
                         for _, s in (sts.iterrows() if len(sts) else [])]
        result["ais_available"] = ais_ok
    else:
        result["ais_available"] = None

    result["thresholds"] = {"ship": SHIP_CONF, "weak": WEAK_CONF}
    result["counts"] = counts(result["ships"], result["sts"])
    result["note"] = ("A ship with no AIS match is a candidate for review, not a finding: AIS can be "
                      "missing for innocent reasons (reception gaps, small craft, military vessels).")
    hit.parent.mkdir(parents=True, exist_ok=True)
    hit.write_text(json.dumps(result))
    progress("Done", 1.0)
    return result


def validate_period(start, end, today=None):
    """(start, end) as Timestamps; ValueError with a sentence a user can act on."""
    try:
        a, b = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    except (ValueError, TypeError):
        raise ValueError("Send the dates as YYYY-MM-DD.")
    today = pd.Timestamp(today or pd.Timestamp.utcnow().tz_localize(None)).normalize()
    if b < a:
        raise ValueError("The end date is before the start date.")
    if b > today:
        raise ValueError("The end date is in the future.")
    if a < ARCHIVE_START:
        raise ValueError(f"Sentinel-1 images start on {ARCHIVE_START:%d %b %Y}; pick a later start date.")
    if (b - a).days + 1 > MAX_PERIOD_DAYS:
        raise ValueError(f"Pick a period of at most {MAX_PERIOD_DAYS} days (this one is {(b - a).days + 1}).")
    return a, b


def period_passes(box, start, end, max_passes=MAX_PASSES):
    """(passes to search, passes found): real-footprint coverage >= 50 %, newest first."""
    box = validate(box)
    a, b = validate_period(start, end)
    items = fetch_s1.search(f"{a:%Y-%m-%d}", f"{b:%Y-%m-%d}", box=box, limit=200)
    items = [i for i in items if fetch_s1.overlap(i, box) >= MIN_OVERLAP]
    if not items:
        raise LookupError("No Sentinel-1 pass covered at least half of this box in that period. "
                          "Try a longer period, a larger box or one further from the coast.")
    return items[:max_passes], len(items)


def combine(passes, found=None, radius_m=RECUR_M):
    """One period result from per-pass results; AIS-unmatched spots seen on 2+ passes are flagged.

    A position that is AIS-unmatched on several passes is more likely a fixed structure or a
    ship at anchor than a transfer, so it is flagged "recurring" for the reviewer, not removed.
    """
    ok = [p for p in passes if "error" not in p]
    spots = [(k, s) for k, p in enumerate(ok) for s in p["ships"]
             if s["category"] == dark_sts.AIS_UNMATCHED and not s.get("weak")]
    recurring, seen = [], set()
    for i, (k, s) in enumerate(spots):
        if i in seen:
            continue
        group = [i] + [j for j, (k2, s2) in enumerate(spots) if j > i and j not in seen and k2 != k and
                       float(dark_sts._metres_between(s["lat"], s["lon"], s2["lat"], s2["lon"])) <= radius_m]
        passes_hit = {spots[j][0] for j in group}
        if len(passes_hit) > 1:
            seen.update(group)
            for j in group:
                spots[j][1]["recurring_passes"] = len(passes_hit)
            recurring.append({"lat": s["lat"], "lon": s["lon"], "passes": len(passes_hit), "_n": len(group),
                              "times": sorted(ok[k2]["scene"]["time"] for k2 in passes_hit)})
    unique = len(spots) - sum(r["_n"] - 1 for r in recurring)
    for r in recurring:
        r.pop("_n")
    return {"passes": sorted(passes, key=lambda p: p.get("scene", {}).get("time", ""), reverse=True),
            "passes_found": found if found is not None else len(passes),
            "passes_searched": len(passes), "passes_failed": len(passes) - len(ok),
            "recurring": recurring,
            "counts": {"ships": sum(p["counts"]["ships"] for p in ok),
                       "ais_unmatched": sum(p["counts"]["ais_unmatched"] for p in ok),
                       "ais_unmatched_spots": unique,   # a recurring group is one place
                       "weak_candidates": sum(p["counts"].get("weak_candidates", 0) for p in ok),
                       "sts_pairs": sum(p["counts"]["sts_pairs"] for p in ok)},
            "note": ok[0]["note"] if ok else None}
