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

import pandas as pd
import requests

from src.config import GFW_API_TOKEN, bbox as default_bbox

BASE = "https://gateway.api.globalfishingwatch.org/v3"
DATASETS = {
    "gaps": "public-global-gaps-events:latest",
    "encounters": "public-global-encounters-events:latest",
}


PRESENCE = "public-global-presence:latest"      # AIS, all vessel types
SAR = "public-global-sar-presence:latest"       # GFW's own Sentinel-1 detections


def _report(dataset, start, end, box, temporal, group_by=None):
    """One 4Wings report over the box, flattened to a DataFrame (one row per cell-time)."""
    params = {"datasets[0]": dataset, "format": "JSON", "spatial-resolution": "HIGH",
              "temporal-resolution": temporal, "spatial-aggregation": "false",
              "date-range": f"{pd.Timestamp(start):%Y-%m-%dT%H:%M:%S.000Z},"
                            f"{pd.Timestamp(end):%Y-%m-%dT%H:%M:%S.000Z}"}
    if group_by:
        params["group-by"] = group_by
    r = requests.post(f"{BASE}/4wings/report", headers=_headers(), params=params,
                      data=json.dumps({"geojson": bbox_polygon(box)}), timeout=120)
    r.raise_for_status()
    # GFW returns {dataset: null} rather than [] for a window with no data.
    rows = [row for e in (r.json().get("entries") or []) for v in e.values() for row in (v or [])]
    return pd.DataFrame(rows)


def ais_presence(start, end, box):
    """AIS outside Denmark: GFW hourly presence on its ~1 km grid (0.01 deg).

    Shaped like ais.load() — mmsi, lat, lon, timestamp — so dark_sts.characterise
    runs on it unchanged. Positions are cell corners and times are hour centres,
    so match with a buffer of at least ~1.5 km and a window of at least 1 h.
    Includes GFW's satellite AIS, so open-sea coverage beats terrestrial-only feeds.
    """
    d = _report(PRESENCE, start, end, box, "HOURLY", "VESSEL_ID")
    if d.empty:
        return pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"])
    return pd.DataFrame({"mmsi": d.vesselId.where(d.vesselId != "", d.mmsi),
                         "lat": d.lat, "lon": d.lon,
                         "timestamp": pd.to_datetime(d.date) + pd.Timedelta(minutes=30)})


def sar_unmatched(day, box):
    """GFW's own Sentinel-1 detections with no AIS match on `day` — an independent check."""
    d = _report(SAR, day, pd.Timestamp(day) + pd.Timedelta(days=1), box, "DAILY")
    return d[d.mmsi == ""][["lat", "lon", "detections"]] if len(d) else d


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
