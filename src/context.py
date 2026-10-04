"""Context for a ship with no AIS match: nearby AIS gap events and maritime zone.

Both are context, not evidence about the ship itself:

  gap events  GFW publishes when a known vessel's AIS went quiet (its
              "intentional disabling" class: long gaps with good reception
              around them). A gap that was open at the radar pass, starting
              within reach of the radar position, is a vessel that COULD be
              this one. It is worded that way.
  zone        Marine Regions (free, no key): inside a country's 12 NM
              territorial sea, its Exclusive Economic Zone, or neither.
              Says whose rules apply, not that any were broken.
"""
from functools import lru_cache

import numpy as np
import pandas as pd
import requests

from src import dark_sts, gfw

MARINE_REGIONS = "https://www.marineregions.org/rest/getGazetteerRecordsByLatLong.json/{lat}/{lon}/"
MAX_KN = 15                   # fastest a laden merchant ship plausibly went while silent
SEARCH_DEG = 0.5              # gap events looked up this far around the box
LOOKBACK = pd.Timedelta(days=7)


def gap_events(box, t, lookback=LOOKBACK, pad=SEARCH_DEG, max_events=500):
    """GFW AIS gap events around the box that were open at time t."""
    lo_lon, lo_lat, hi_lon, hi_lat = box
    wide = (lo_lon - pad, lo_lat - pad, hi_lon + pad, hi_lat + pad)
    rows, offset = [], 0
    while offset < max_events:
        total, entries = gfw.events("gaps", f"{t - lookback:%Y-%m-%d}", f"{t + pd.Timedelta(days=1):%Y-%m-%d}",
                                    box=wide, limit=100, offset=offset)
        for e in entries:
            off = (e.get("gap") or {}).get("offPosition") or e.get("position") or {}
            v = e.get("vessel") or {}
            rows.append({"start": pd.Timestamp(e["start"]).tz_localize(None),
                         "end": pd.Timestamp(e["end"]).tz_localize(None),
                         "lat": float(off.get("lat")), "lon": float(off.get("lon")),
                         "name": " ".join((v.get("name") or "").split()), "mmsi": v.get("ssvid"),
                         "flag": v.get("flag"), "type": v.get("type")})
        offset += len(entries)
        if not entries or offset >= total:
            break
    g = pd.DataFrame(rows, columns=["start", "end", "lat", "lon", "name", "mmsi", "flag", "type"])
    return g[(g.start <= t) & (g.end >= t)].reset_index(drop=True)


def nearest_gap(lat, lon, t, gaps, max_kn=MAX_KN):
    """The closest open gap this ship could have come from, or None."""
    if gaps is None or gaps.empty:
        return None
    d_km = pd.Series(np.asarray(dark_sts._metres_between(lat, lon, gaps.lat, gaps.lon)) / 1000, index=gaps.index)
    hours = (t - gaps.start).dt.total_seconds() / 3600
    ok = d_km <= max_kn * 1.852 * hours
    if not ok.any():
        return None
    i = d_km[ok].idxmin()
    return {**gaps.loc[i].to_dict(), "km": float(d_km[i]), "hours": float(hours[i])}


def gap_reason(g):
    who = g["name"] or f"MMSI {g['mmsi']}"
    flag = f", {g['flag']}" if g.get("flag") else ""
    kind = f" {g['type']}" if g.get("type") and g["type"] != "other" else ""
    return (f"Global Fishing Watch recorded the{kind} vessel {who}{flag} switching off AIS {g['km']:.0f} km "
            f"away, {g['hours']:.0f} h before this radar pass, and still silent at the pass. "
            f"A possible match, not proof it is the same ship.")


@lru_cache(maxsize=2048)
def zone(lat, lon):
    """('territorial' | 'eez' | 'high_seas', name) at a point; None if the lookup fails."""
    try:
        r = requests.get(MARINE_REGIONS.format(lat=lat, lon=lon), timeout=15)
        r.raise_for_status()
        places = r.json()
    except Exception:
        return None
    by_type = {}
    for p in places:
        by_type.setdefault(p.get("placeType"), p.get("preferredGazetteerName"))
    if by_type.get("Territorial Sea"):
        return "territorial", by_type["Territorial Sea"]
    if by_type.get("EEZ"):
        return "eez", by_type["EEZ"]
    return "high_seas", None


def zone_reason(z):
    if z is None:
        return None
    kind, name = z
    if kind == "territorial":
        country = name.replace(" 12 NM", "")
        return f"Inside {country} territorial waters (within 12 NM of the coast)."
    if kind == "eez":
        return f"Inside the {name}, outside territorial waters."
    return "On the high seas, outside any national Exclusive Economic Zone."


def zone_at(lat, lon):
    return zone(round(float(lat), 2), round(float(lon), 2))     # ~1 km cells share one lookup
