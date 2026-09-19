"""Global Fishing Watch API v3 — comparison layers only, never ground truth.

GFW does not publish raw AIS positions. What we use it for:
  gaps       — AIS transmission gaps (a vessel stopped broadcasting)
  encounters — two AIS-visible vessels meeting at sea
  vessels    — registry lookup for honest type/flag/length on matched detections

Everything here is an independent reference layer we compare our own detections
against. `matched=false` in a GFW layer is evidence, not a verdict.
"""
import json
import sys

import requests

from src.config import GFW_API_TOKEN, bbox as default_bbox

BASE = "https://gateway.api.globalfishingwatch.org/v3"
DATASETS = {
    "gaps": "public-global-gaps-events:latest",
    "encounters": "public-global-encounters-events:latest",
}


def _headers():
    if not GFW_API_TOKEN:
        raise RuntimeError("GFW_API_TOKEN not set in .env (see .env.example)")
    return {"Authorization": f"Bearer {GFW_API_TOKEN}", "Content-Type": "application/json"}


def bbox_polygon(box=None):
    """GeoJSON polygon for a (min_lon, min_lat, max_lon, max_lat) box."""
    lo_lon, lo_lat, hi_lon, hi_lat = box or default_bbox()
    ring = [
        [lo_lon, lo_lat], [hi_lon, lo_lat], [hi_lon, hi_lat],
        [lo_lon, hi_lat], [lo_lon, lo_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def events(kind: str, start: str, end: str, box=None, limit: int = 100, offset: int = 0):
    """One page of GFW events of `kind` ('gaps' or 'encounters') in the box.

    Returns (total, entries). `total` is GFW's count for the whole query, which
    is what the Phase 0 kill criterion cares about, not the page length.
    """
    if kind not in DATASETS:
        raise ValueError(f"unknown event kind {kind!r}, expected one of {list(DATASETS)}")
    body = {
        "datasets": [DATASETS[kind]],
        "startDate": start,
        "endDate": end,
        "geometry": bbox_polygon(box),
    }
    r = requests.post(
        f"{BASE}/events",
        headers=_headers(),
        params={"limit": limit, "offset": offset},
        data=json.dumps(body),
        timeout=90,
    )
    if r.status_code == 401:
        raise RuntimeError("GFW rejected the token (401) — check GFW_API_TOKEN in .env")
    r.raise_for_status()
    payload = r.json()
    return payload.get("total", 0), payload.get("entries", [])


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "gaps"
    start = sys.argv[2] if len(sys.argv) > 2 else "2025-01-01"
    end = sys.argv[3] if len(sys.argv) > 3 else "2025-12-31"
    total, entries = events(kind, start, end, limit=5)
    print(f"{total} GFW {kind} events in AOI, {start}..{end}")
    for e in entries:
        print(f"  {e.get('start')}  {e.get('id')}")
