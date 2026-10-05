"""Plan a search before running it: which passes, which cells, how long, how much credit.

No size or period limit of its own. A box of any size is cut into cells of at most
CELL_KM; a period of any length lists every Sentinel-1 pass in it. Each (pass, cell)
where the pass really covers at least half the cell is one unit of work, run as one
Modal call. The plan gives the user an estimate before they press Go; the only
ceiling is MAX_UNITS (env SEARCH_MAX_UNITS), so one click cannot spend the month's
free credit.

Light on purpose (requests + shapely only): the Render backend plans and estimates
without loading the image-processing stack. src.fetch_s1 delegates here.
"""
import math
import os

import requests

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
CELL_KM = 50                   # one cell ~ one detector-sized image area; 3 cells across a 144 km box
EDGE_KM = 0.6                  # each cell is searched this far past its edge: a 500 m pair or a long hull stays whole
SLICE_GAP_S = 120              # STAC items of one pass are slices ~25 s apart; passes are hours apart
MIN_COVER = 0.5                # a pass must cover at least half a cell, by its real footprint
PARALLEL = 4                   # units run at once (GFW and Planetary Computer rate-limit wider)
UNIT_S = 100                   # measured: one 30-50 km pass takes 52-99 s on 2 CPUs
UNIT_USD = 0.0036              # 2 CPU x 100 s + 4 GiB x 100 s at Modal's published rates
MAX_UNITS = int(os.getenv("SEARCH_MAX_UNITS", 200))   # ~$0.70 and ~1.4 h at the ceiling


def km(box):
    """(width, height) of a (west, south, east, north) box in km."""
    w, s, e, n = box
    return (e - w) * 111.32 * math.cos(math.radians((s + n) / 2)), (n - s) * 110.57


def cells(box, cell_km=CELL_KM):
    """The box cut into an even grid of cells ("cores") no larger than cell_km a side; they tile it exactly."""
    w, s, e, n = box
    wk, hk = km(box)
    nx, ny = max(1, math.ceil(wk / cell_km)), max(1, math.ceil(hk / cell_km))
    dx, dy = (e - w) / nx, (n - s) / ny
    return [(w + i * dx, s + j * dy, w + (i + 1) * dx, s + (j + 1) * dy) for j in range(ny) for i in range(nx)]


def grow(core, box, edge_km=EDGE_KM):
    """The core plus edge_km all round, clipped to the box: what is searched. A hull or pair near a
    core's edge is then whole in that search, and keeping only ships inside the core
    (src.search.merge_cells) counts each hull once."""
    w, s, e, n = core
    wk, hk = km(core)
    gx, gy = (e - w) / wk * edge_km, (n - s) / hk * edge_km
    return (max(box[0], w - gx), max(box[1], s - gy), min(box[2], e + gx), min(box[3], n + gy))


def stac_search(start, end, box, limit=1000, mode="IW", pages=1):
    """Sentinel-1 GRD passes over the box, newest first, one per acquisition time.

    pages > 1 follows the catalogue's next-page links, so a period of years lists every pass."""
    body = {"collections": ["sentinel-1-grd"], "bbox": list(box),
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "query": {"sar:instrument_mode": {"eq": mode}}, "limit": limit}
    url, feats = f"{STAC}/search", []
    for _ in range(pages):
        r = requests.post(url, timeout=90, json=body)
        r.raise_for_status()
        j = r.json()
        feats += j.get("features", [])
        nxt = next((ln for ln in j.get("links", []) if ln.get("rel") == "next"), None)
        if not nxt:
            break
        url, body = nxt["href"], nxt.get("body") or body
    items, seen = [], set()
    for f in feats:
        if f["properties"]["datetime"] not in seen:
            seen.add(f["properties"]["datetime"])
            items.append(f)
    return sorted(items, key=lambda f: f["properties"]["datetime"], reverse=True)


def overlap(item, box):
    """Share of the box covered by the pass's real footprint (a tilted strip, not its bounding box)."""
    lo_lon, lo_lat, hi_lon, hi_lat = box
    if item.get("geometry"):
        from shapely.geometry import box as rect, shape
        aoi = rect(lo_lon, lo_lat, hi_lon, hi_lat)
        return shape(item["geometry"]).intersection(aoi).area / aoi.area
    b = item["bbox"]
    w = max(0.0, min(b[2], hi_lon) - max(b[0], lo_lon))
    h = max(0.0, min(b[3], hi_lat) - max(b[1], lo_lat))
    return w * h / ((hi_lon - lo_lon) * (hi_lat - lo_lat))


def estimate(n_units):
    minutes = math.ceil(n_units / PARALLEL) * UNIT_S / 60 + 1 if n_units else 0
    return {"units": n_units, "minutes": round(minutes), "usd": round(n_units * UNIT_USD, 2),
            "max_units": MAX_UNITS, "over_limit": n_units > MAX_UNITS}


def _t(item):
    from datetime import datetime
    return datetime.fromisoformat(item["properties"]["datetime"].replace("Z", "+00:00")).timestamp()


def passes_of(items, gap_s=SLICE_GAP_S):
    """STAC items grouped into satellite passes: one pass arrives as adjacent slices ~25 s apart."""
    groups = []
    for it in sorted(items, key=_t, reverse=True):
        g = groups[-1] if groups else None
        if g and _t(g[-1]) - _t(it) <= gap_s and g[-1]["properties"].get("platform") == it["properties"].get("platform"):
            g.append(it)
        else:
            groups.append([it])
    return groups


def make_plan(box, start, end, items=None):
    """{passes: [{item, units: [(slice, core)]}], passes_found, cells, units, estimate}, newest first.

    Each cell goes to the slice of the pass that covers it best, if that covers at least MIN_COVER,
    so no cell is searched twice in one pass. Raises LookupError if nothing covers."""
    grid = cells(box)
    items = stac_search(start, end, box, pages=20) if items is None else items
    passes = []
    for group in passes_of(items):
        units = []
        for core in grid:
            cover, best = max(((overlap(it, core), k) for k, it in enumerate(group)))
            if cover >= MIN_COVER:   # ponytail: one slice per cell; a cell split 60/40 between slices
                units.append((group[best], core))   # loses its 40 %, mosaic the slices if that matters
        if units:
            passes.append({"item": group[0], "units": units})
    if not passes:
        raise LookupError("No Sentinel-1 pass covered this area in that period. Try a longer period "
                          "or an area further from the coast.")
    n = sum(len(p["units"]) for p in passes)
    return {"passes": passes, "passes_found": len(passes), "cells": len(grid), "units": n, "estimate": estimate(n)}


def summary(plan):
    """What the website shows before Go (no STAC items, just counts and times)."""
    return {"passes": plan["passes_found"], "cells": plan["cells"], **plan["estimate"],
            "first": plan["passes"][-1]["units"][-1][0]["properties"]["datetime"],
            "last": plan["passes"][0]["item"]["properties"]["datetime"]}
