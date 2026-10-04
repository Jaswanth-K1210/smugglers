"""Open Waters (aiscast): free AIS from government feeds, AISHub and volunteer receivers.

Tested 2026-10-04: 1,052 ships in the Strait of Hormuz box, every one with a real
9-digit MMSI, 92 % with an ITU type code and 83 % with an IMO number; median position
age 22 min. Anonymous use needs no key; OPENWATERS_TOKEN (free personal token from
openwaters.io) raises the area cap. Shore receivers only (satellite only in the
Norwegian EEZ via BarentsWatch), so this does not fill the open ocean.

Licensing is per source and Open Waters does not relicense: every row keeps its
`source`, and `credit()` gives the attribution that source requires.
"""
import math
import os
import time

import pandas as pd
import requests

BASE = "https://ais.openwaters.io/v1"
UA = {"User-Agent": "OpenSTS/1.0 (https://github.com/Jaswanth-K1210/smugglers)"}
MAX_AGE = "1h"                      # last report within the hour, like the rest of the live map
AREA_CAP_ANON = 100                 # square degrees per request (their published anonymous cap)
AREA_CAP_TOKEN = 400                # personal token, "~20 x 20"

CREDITS = {
    "aishub": "AISHub",
    "barentswatch": "Data delivered by BarentsWatch",
    "kystverket": "Contains data under the Norwegian licence for Open Government data (NLOD) "
                  "distributed by the Norwegian Coastal Administration",
    "digitraffic": "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY",
    "fintraffic": "Source: Fintraffic / digitraffic.fi, license CC 4.0 BY",
    "aisstream": "aisstream.io",
}


def category(code):
    """Map colour group from an ITU type code: cargo, tanker, passenger, highspeed, fishing,
    special, pleasure, other, unknown."""
    if not code:
        return "unknown"
    if code == 30:
        return "fishing"
    if code in (36, 37):
        return "pleasure"
    if code in (31, 32, 33, 34, 35) or 50 <= code <= 59:
        return "special"
    return {4: "highspeed", 6: "passenger", 7: "cargo", 8: "tanker"}.get(code // 10, "other")


def token():
    return os.getenv("OPENWATERS_TOKEN") or None


def credit(source):
    """Attribution the source requires; volunteer receptions are CC0 and need none."""
    base = CREDITS.get(source or "", None)
    return f"{base}, via Open Waters" if base else "Open Waters volunteer receivers (CC0)"


def chunks(box, cap=None):
    """Split [west, south, east, north] into tiles of at most `cap` square degrees."""
    cap = cap or (AREA_CAP_TOKEN if token() else AREA_CAP_ANON)
    w, s, e, n = box
    side = math.sqrt(cap) * 0.98                   # stay just inside the cap
    nx, ny = max(1, math.ceil((e - w) / side)), max(1, math.ceil((n - s) / side))
    dx, dy = (e - w) / nx, (n - s) / ny
    return [(w + i * dx, s + j * dy, w + (i + 1) * dx, s + (j + 1) * dy) for i in range(nx) for j in range(ny)]


def fetch(box, max_age=MAX_AGE, timeout=40):
    """Vessels last heard within `max_age` inside `box`, as normalised rows (see `normalise`)."""
    rows = {}
    for w, s, e, n in chunks(box):
        params = {"bbox": f"{s:.4f},{w:.4f},{n:.4f},{e:.4f}", "kind": "vessel", "max_age": max_age}
        headers = dict(UA)
        if token():
            headers["Authorization"] = f"Bearer {token()}"
        r = requests.get(f"{BASE}/vessels", params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        for f in r.json().get("features") or []:
            row = normalise(f)
            if row and (row["mmsi"] not in rows or row["seen"] > rows[row["mmsi"]]["seen"]):
                rows[row["mmsi"]] = row
        time.sleep(0.3)                            # polite between tiles
    return list(rows.values())


def normalise(feature):
    """One GeoJSON feature -> row with MMSI, position, report time and static data."""
    p = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    mmsi = p.get("mmsi")
    if not mmsi or len(coords) < 2 or not p.get("seen"):
        return None
    lon, lat = float(coords[0]), float(coords[1])
    length = p.get("length") or ((p.get("to_bow") or 0) + (p.get("to_stern") or 0)) or None
    beam = p.get("beam") or ((p.get("to_port") or 0) + (p.get("to_starboard") or 0)) or None
    seen = pd.Timestamp(p["seen"]).tz_convert(None) if pd.Timestamp(p["seen"]).tzinfo else pd.Timestamp(p["seen"])
    return {"mmsi": int(mmsi), "name": (p.get("name") or "").strip() or None, "lat": round(lat, 5),
            "lon": round(lon, 5), "sog": p.get("sog"), "cog": p.get("cog"), "heading": p.get("heading"),
            "nav_status": p.get("nav_status"), "type_code": p.get("type"), "imo": p.get("imo") or None,
            "callsign": (p.get("callsign") or "").strip() or None, "length_m": length, "beam_m": beam,
            "destination": (p.get("destination") or "").strip() or None, "draught_m": p.get("draught") or None,
            "eta": p.get("eta") or None, "flag": p.get("flag"), "source": p.get("source"),
            "seen": seen.timestamp() if seen.tzinfo else (seen - pd.Timestamp("1970-01-01")).total_seconds()}


def track(mmsi, hours=48, timeout=30):
    """[(lat, lon), ...] heard in the last `hours` (48 h is the anonymous/personal reach), oldest first."""
    end = pd.Timestamp.utcnow()
    params = {"from": (end - pd.Timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "interval": "5m", "limit": 1000 if token() else 200}
    headers = dict(UA)
    if token():
        headers["Authorization"] = f"Bearer {token()}"
    r = requests.get(f"{BASE}/vessels/{int(mmsi)}/track", params=params, headers=headers, timeout=timeout)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    g = r.json().get("geometry") or {}
    pts = g.get("coordinates") or []
    pts = [pts] if g.get("type") == "Point" else pts
    return [(round(c[1], 5), round(c[0], 5)) for c in pts if len(c) >= 2]
