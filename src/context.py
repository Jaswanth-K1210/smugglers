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


# ── Ships whose AIS was silent across the pass ───────────────────────────────
# GFW's published gap events are rare (one in the whole Gulf over three months), so we also
# read the AIS itself: every ship that reported before the pass, went quiet across it and
# reported again after, and could have been in the box at the pass time.
SILENT_H = 12                 # AIS read this far either side of the pass
SILENT_PAD_DEG = 0.3          # and this far around the box (~33 km); 13-26 s per lookup measured
QUIET_H = 1.0                 # no report this close to the pass, on either side
SLACK_KM = 2.0                # GFW presence cells (~1 km) and hour-centred times


def ais_around(box, t, hours=SILENT_H, pad=SILENT_PAD_DEG):
    """GFW hourly AIS presence with identities, ±`hours` around t, in the box widened by `pad`."""
    w, s, e, n = box
    d = gfw._report(gfw.PRESENCE, t - pd.Timedelta(hours=hours), t + pd.Timedelta(hours=hours),
                    (w - pad, s - pad, e + pad, n + pad), "HOURLY", "VESSEL_ID")
    if d.empty:
        return d
    return d.assign(ts=pd.to_datetime(d.date) + pd.Timedelta(minutes=30))


def _reach_km(hours, max_kn):
    return max_kn * 1.852 * (abs(hours) + 0.5) + SLACK_KM        # +0.5 h: times are hour centres


def _km_to_box(lat, lon, box):
    w, s, e, n = box
    return float(dark_sts._metres_between(lat, lon, min(max(lat, s), n), min(max(lon, w), e))) / 1000


def silent_at_pass(rows, t, box, max_kn=MAX_KN, quiet_h=QUIET_H, limit=30):
    """Ships silent across the pass that could have been inside the box at t, longest silence last.

    Each: key, identity, where and when AIS went quiet ("off") and came back ("on")."""
    if rows is None or not len(rows):
        return []
    out = []
    for vid, x in rows.groupby("vesselId"):
        before, after = x[x.ts <= t - pd.Timedelta(hours=quiet_h)], x[x.ts >= t + pd.Timedelta(hours=quiet_h)]
        if before.empty or after.empty or ((x.ts - t).abs() < pd.Timedelta(hours=quiet_h)).any():
            continue
        off, on = before.loc[before.ts.idxmax()], after.loc[after.ts.idxmin()]
        h_off, h_on = (t - off.ts).total_seconds() / 3600, (on.ts - t).total_seconds() / 3600
        if (_km_to_box(off.lat, off.lon, box) > _reach_km(h_off, max_kn) or
                _km_to_box(on.lat, on.lon, box) > _reach_km(h_on, max_kn)):
            continue
        val = lambda c: None if c not in off or off[c] != off[c] or off[c] in ("", None) else off[c]
        imo = val("imo")
        out.append({"key": str(vid), "mmsi": None if val("mmsi") is None else str(val("mmsi")),
                    "name": val("shipName"), "flag": val("flag"), "imo": str(imo) if imo else None,
                    "callsign": val("callsign"), "type": (val("vesselType") or "").replace("_", " ").lower() or None,
                    "off": {"time": off.ts.isoformat() + "Z", "lat": round(float(off.lat), 4), "lon": round(float(off.lon), 4),
                            "hours_before": round(h_off, 1)},
                    "on": {"time": on.ts.isoformat() + "Z", "lat": round(float(on.lat), 4), "lon": round(float(on.lon), 4),
                           "hours_after": round(h_on, 1)},
                    "silent_h": round(h_off + h_on, 1), "could_be": []})
    return sorted(out, key=lambda r: r["silent_h"])[:limit]


def could_be(lat, lon, t, silent, max_kn=MAX_KN):
    """Keys of the silent ships that could be the radar ship at (lat, lon), nearest detour first."""
    hits = []
    for r in silent:
        a = float(dark_sts._metres_between(r["off"]["lat"], r["off"]["lon"], lat, lon)) / 1000
        b = float(dark_sts._metres_between(lat, lon, r["on"]["lat"], r["on"]["lon"])) / 1000
        if a <= _reach_km(r["off"]["hours_before"], max_kn) and b <= _reach_km(r["on"]["hours_after"], max_kn):
            hits.append((a + b, r["key"]))
    return [k for _, k in sorted(hits)]


def link_silent(result):
    """Fill each silent ship's could_be with the ids of the radar ships that list it."""
    for r in result.get("ais_silent") or []:
        r["could_be"] = [s["id"] for s in result["ships"] if r["key"] in (s.get("ais_silent_match") or [])]
    return result


def silent_reason(r):
    who = r["name"] or (f"MMSI {r['mmsi']}" if r["mmsi"] else "An unnamed ship")
    extra = ", ".join(v for v in (r.get("flag"), f"IMO {r['imo']}" if r.get("imo") else None, r.get("type")) if v)
    return (f"{who}{f' ({extra})' if extra else ''} stopped reporting AIS {r['off']['hours_before']:.0f} h before "
            f"this pass and reappeared {r['on']['hours_after']:.0f} h after; at up to {MAX_KN} kn it could have been "
            f"here at the pass. A possible match, not proof: AIS also drops out through poor reception.")


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
