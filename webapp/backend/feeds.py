"""Live context for the console: AIS positions from aisstream.io and sanctions news.

Live AIS: one websocket to aisstream.io for the whole world, newest position
per MMSI kept in memory (~100k ships, tens of MB). Without AISSTREAM_API_KEY the feed is simply off and
/api/live says so. Positions older than STALE_S are dropped on read.

News: Google News RSS for ship-to-ship transfer / sanctions stories, cached so
the console's polling never hammers it.
"""
import asyncio
import html
import json
import math
import os
import re
import time
from array import array
from pathlib import Path
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
# aisstream wants [[lat, lon], [lat, lon]] corners; one box = the whole world
BOXES = [[[-90, -180], [90, 180]]]
STALE_S = 60 * 60   # MarineTraffic-style: show the last position for an hour; anchored ships report every ~3 min
MAX_VESSELS = 20000   # per response; past this the view is thinned evenly, not truncated

ships: dict = {}       # MMSI -> newest position
tracks: dict = {}      # MMSI -> array('f') of lat, lon, seconds-since-T0 triples
T0 = time.time()
TRACK_EVERY_S = 5 * 60   # one point per 5 min ...
TRACK_KEEP_S = 6 * 3600  # ... for 6 h: ≤72 points, 12 bytes each
# ITU-R MID table (itu.int/gladapp/Allocation/MIDs) with ISO 3166 alpha-2: MID -> [ISO2, country]
MIDS = json.loads((Path(__file__).parent / "mids.json").read_text())
COUNTRY_BY_ISO2 = {iso2: name for iso2, name in MIDS.values()}

# Regional feed for the Gulf (aisstream.io has no receivers there): see src/regional_ais.py
regional: dict = {}    # "hn:<id>" -> normalised row
regional_state = {"ok": None, "at": None, "error": None, "count": 0, "recorded": 0}
REGIONAL_EVERY_S = 5 * 60
statics: dict = {}     # MMSI -> type, IMO, call sign, size, destination (sent every ~6 min)
STATIC_TTL = 7 * 24 * 3600   # type / IMO / size barely change; destination and ETA refresh on the next report
STATIC_PATH = Path(os.getenv("AIS_STATIC_PATH", Path(__file__).resolve().parents[2] / "data" / "ais_static.json"))
POSITIONS_PATH = STATIC_PATH.with_name("ais_positions.json")
SAVE_EVERY_S = 5 * 60
SILENCE_S = 60       # no message for this long = dead connection
state = {"configured": False, "connected": False, "error": None, "messages": 0}

# ITU-R M.1371 ship type codes; the second digit of 20-99 is a hazard/cargo subclass.
SHIP_TYPES = {30: "Fishing", 31: "Towing", 32: "Towing (large)", 33: "Dredging or underwater ops",
              34: "Diving ops", 35: "Military ops", 36: "Sailing", 37: "Pleasure craft",
              50: "Pilot vessel", 51: "Search and rescue", 52: "Tug", 53: "Port tender",
              54: "Anti-pollution", 55: "Law enforcement", 58: "Medical transport", 59: "Noncombatant"}
TYPE_GROUPS = {2: "Wing in ground", 4: "High-speed craft", 6: "Passenger", 7: "Cargo", 8: "Tanker", 9: "Other"}
HAZARD = {1: "hazard category A", 2: "hazard category B", 3: "hazard category C", 4: "hazard category D"}
NAV_STATUS = {0: "Under way using engine", 1: "At anchor", 2: "Not under command", 3: "Restricted manoeuvrability",
              4: "Constrained by draught", 5: "Moored", 6: "Aground", 7: "Engaged in fishing",
              8: "Under way sailing", 14: "AIS-SART active"}


def ship_type(code):
    """'Tanker (hazard category A)' from 81; None when the ship did not say."""
    if not code or not 20 <= code <= 99:
        return None
    if code in SHIP_TYPES:
        return SHIP_TYPES[code]
    group = TYPE_GROUPS.get(code // 10)
    if not group:
        return f"Reserved type {code}"
    return f"{group} ({HAZARD[code % 10]})" if code % 10 in HAZARD and code // 10 in (2, 4, 6, 7, 8, 9) else group


def flag(mmsi):
    """Flag state from a ship MMSI (first three digits, 2xx-7xx); None for coast stations, AtoNs, SAR."""
    m = str(mmsi)
    hit = MIDS.get(m[:3]) if len(m) == 9 and m[0] in "234567" else None
    return {"iso2": hit[0], "country": hit[1]} if hit else None


def _eta(e):
    """AIS ETA has no year; 0 means not available."""
    if not e or not e.get("Month") or not e.get("Day"):
        return None
    hh, mm = e.get("Hour", 24), e.get("Minute", 60)
    t = f" {hh:02d}:{mm:02d} UTC" if hh < 24 and mm < 60 else ""
    return f"{e['Month']:02d}-{e['Day']:02d}{t}"


def type_group(code):
    """Map colour group, MarineTraffic-style (shared with src/ so the map and the search agree)."""
    from src.openwaters import category
    return category(code)


def _text(v):
    return (v or "").replace("@", "").strip() or None      # AIS pads strings with '@'


def _store(msg: dict, now: float):
    """Route one aisstream message: positions into `ships`, static data into `statics`."""
    meta = msg.get("MetaData") or {}
    kind = msg.get("MessageType")
    body = (msg.get("Message") or {}).get(kind) or next(iter((msg.get("Message") or {}).values()), {}) or {}
    mmsi = meta.get("MMSI")
    if mmsi is None:
        return
    if kind in ("ShipStaticData", "StaticDataReport"):
        b = (body.get("ReportB") or {}) if kind == "StaticDataReport" else body
        if kind == "StaticDataReport" and not b.get("Valid"):
            return                                      # part A only carries the name
        d = b.get("Dimension") or {}
        length, beam = (d.get("A") or 0) + (d.get("B") or 0), (d.get("C") or 0) + (d.get("D") or 0)
        statics[mmsi] = {**statics.get(mmsi, {}), "type_code": b.get("Type", b.get("ShipType")),
                         "imo": b.get("ImoNumber") or None, "callsign": _text(b.get("CallSign")),
                         "name": _text(b.get("Name")) or _text(meta.get("ShipName")),
                         "length_m": length or None, "beam_m": beam or None,
                         "destination": _text(b.get("Destination")),
                         "draught_m": b.get("MaximumStaticDraught") or None,
                         "eta": _eta(b.get("Eta")) if kind == "ShipStaticData" else None, "t": now}
        return
    lat, lon = meta.get("latitude"), meta.get("longitude")
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return
    heading = body.get("TrueHeading")
    ships[mmsi] = {
        "mmsi": str(mmsi),
        "mmsi_int": mmsi,
        "name": _text(meta.get("ShipName")),
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "sog": body.get("Sog"),
        "cog": body.get("Cog"),
        "heading": heading if heading is not None and heading < 360 else None,  # 511 = not available
        "nav_status": body.get("NavigationalStatus"),
        "t": now,
    }
    _track(mmsi, lat, lon, now)


def _track(mmsi, lat, lon, now):
    tr = tracks.get(mmsi)
    rel = now - T0
    if tr is None:
        tracks[mmsi] = array("f", (lat, lon, rel))
    elif rel - tr[-1] >= TRACK_EVERY_S:
        tr.extend((lat, lon, rel))
        cut = 0
        while cut < len(tr) and rel - tr[cut + 2] > TRACK_KEEP_S:
            cut += 3
        if cut:
            del tr[:cut]


def merge_openwaters(rows):
    """Open Waters rows into the same MMSI-keyed store as aisstream: a ship heard by both is
    one ship, the newer report wins, and static data fills gaps without erasing what is known."""
    for r in rows:
        key = r["mmsi"]
        old = ships.get(key)
        if not old or r["seen"] > old["t"]:
            heading = r["heading"]
            ships[key] = {"mmsi": str(key), "mmsi_int": key, "name": r["name"] or (old or {}).get("name"),
                          "lat": r["lat"], "lon": r["lon"], "sog": r["sog"], "cog": r["cog"],
                          "heading": heading if heading is not None and heading < 360 else None,
                          "nav_status": r["nav_status"], "t": r["seen"], "source": f"openwaters:{r['source']}"}
            _track(key, r["lat"], r["lon"], r["seen"])
        static = {k: r[k] for k in ("imo", "callsign", "length_m", "beam_m", "destination", "draught_m", "eta", "name")
                  if r[k] is not None}
        if r["type_code"] is not None:
            static["type_code"] = r["type_code"]
        if static:
            prev = statics.get(key, {})
            statics[key] = {**prev, **static, "t": max(prev.get("t", 0), r["seen"])}


OW_REGIONS = {                   # polled besides the Gulf; each split to the area cap by openwaters.chunks
    # (no Red Sea: Open Waters had 1 ship there in 24 h on 2026-10-04 - AISHub has no stations)
    "Skagerrak, Kattegat and western Baltic": (6.5, 53.5, 15.5, 60.5),
    "Laconia Bay": (20.0, 34.5, 25.0, 38.5),
}
OW_EVERY_S = 3 * 60
openwaters_state = {"ok": None, "at": None, "error": None, "count": 0}


async def run_openwaters():
    """Poll Open Waters for the study regions outside the Gulf (the Gulf rides with run_regional)."""
    from src import openwaters
    while True:
        n, err = 0, None
        for name, box in OW_REGIONS.items():
            try:
                rows = await asyncio.to_thread(openwaters.fetch, box)
                merge_openwaters(rows)
                n += len(rows)
            except Exception as e:
                err = f"{name}: {type(e).__name__}"
        openwaters_state.update(ok=err is None, at=time.time(), error=err, count=n)
        await asyncio.sleep(OW_EVERY_S)


def regional_vessel(key: str, now=None):
    """Card data for a Gulf ship from the regional feed: position, size, flag, destination, recorded track."""
    r = regional.get(key)
    if not r:
        return None
    now = now or time.time()
    from src import regional_ais
    t = pd_ts(r["pos_time"])
    try:
        import pandas as pd
        end = pd.Timestamp(r["pos_time"])
        tr = regional_ais.load_window(end - pd.Timedelta(hours=6), end)
        tr = tr[tr.mmsi == key].sort_values("timestamp")
        track = [[float(a), float(b)] for a, b in zip(tr.lat, tr.lon)]
        since = int(now - pd_ts(tr.timestamp.iloc[0].isoformat())) if len(tr) else 0
    except Exception:
        track, since = [], 0
    if not track or track[-1] != [r["lat"], r["lon"]]:
        track.append([r["lat"], r["lon"]])
    return {"mmsi": key, "name": r["name"], "lat": r["lat"], "lon": r["lon"], "sog": r["sog"], "cog": r["cog"],
            "heading": r["heading"], "age_s": int(now - t), "nav_status": None, "type": r["type"],
            "imo": None, "callsign": None, "length_m": r["length_m"], "beam_m": r["width_m"], "dwt": r["dwt"],
            "destination": r["destination"], "draught_m": None, "eta": None,
            "flag": {"iso2": r["flag"], "country": COUNTRY_BY_ISO2.get(r["flag"], r["flag"])} if r["flag"] else None,
            "track": track, "track_since_s": since, "source": regional_ais.ATTRIBUTION}


def pd_ts(iso: str) -> float:
    """ISO time without zone (UTC) -> unix seconds."""
    from datetime import datetime, timezone
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


def vessel(mmsi: str, now=None):
    """Everything known about one ship, in words; None if never heard."""
    if str(mmsi).startswith("hn:"):
        return regional_vessel(str(mmsi), now)
    now = now or time.time()
    try:
        key = int(mmsi)
    except ValueError:
        return None
    pos, st = ships.get(key), statics.get(key)
    if st and now - st["t"] > STALE_S + STATIC_TTL:
        st = None
    if not pos and not st:
        return None
    out = {"mmsi": str(key), **{k: v for k, v in (pos or {}).items() if k not in ("t", "mmsi", "mmsi_int", "nav_status", "source")}}
    if pos:
        out["age_s"] = int(now - pos["t"])
        out["nav_status"] = NAV_STATUS.get(pos.get("nav_status"))
    if st:
        out.update({k: v for k, v in st.items() if k not in ("t", "name")})
        out["name"] = out.get("name") or st.get("name")    # position reports sometimes carry no name
        out["type"] = ship_type(st.get("type_code"))
    out.setdefault("type", None)
    out["flag"] = flag(key)
    src = (pos or {}).get("source", "")
    if src.startswith("openwaters:"):
        from src.openwaters import credit
        out["source"] = credit(src.split(":", 1)[1])
    else:
        out["source"] = "aisstream.io, terrestrial"
    tr = tracks.get(key)
    # Past track, oldest first, ending at the newest position
    out["track"] = [[round(tr[i], 5), round(tr[i + 1], 5)] for i in range(0, len(tr), 3)] if tr else []
    if pos and (not out["track"] or out["track"][-1] != [pos["lat"], pos["lon"]]):
        out["track"].append([pos["lat"], pos["lon"]])
    out["track_since_s"] = int(now - T0 - tr[2]) if tr else 0
    return out


_identities: dict = {}
GFW_SKIP_TYPES = {"NA", "DISCREPANCY", None}


def gfw_identity(mmsi):
    """Type, IMO, call sign and size from Global Fishing Watch's vessel identity by MMSI; cached.

    Fallback for ships whose AIS static report has not reached us yet (aisstream
    delivers it for only a fraction of ships in any 6-minute window)."""
    key = str(mmsi)
    if key in _identities:
        return _identities[key]
    by_name = key.startswith("hn:")
    name = (regional.get(key) or {}).get("name") if by_name else None
    if by_name and not name:
        return None
    try:
        from src.gfw import BASE, _headers
        r = requests.get(f"{BASE}/vessels/search", headers=_headers(), timeout=20, params={
            "query": name or key, "datasets[0]": "public-global-vessel-identity:latest", "limit": 3})
        r.raise_for_status()
        entries = r.json().get("entries") or []
    except Exception:
        return None                                  # no token / GFW down: don't cache, retry next time
    out = None
    if by_name:
        # Regional ships have no MMSI: accept a name match only when it is exact and unique,
        # never "the first ship called PEARL".
        norm = lambda v: re.sub(r"[^A-Z0-9]", "", (v or "").upper())
        hits = [e for e in entries if norm(((e.get("selfReportedInfo") or [{}])[0].get("shipname")
                                            or (e.get("registryInfo") or [{}])[0].get("shipname"))) == norm(name)]
        entries = hits if len(hits) == 1 else []
    if entries:
        e = entries[0]
        reg = (e.get("registryInfo") or [{}])[0]
        own = (e.get("selfReportedInfo") or [{}])[0]
        if by_name or str(reg.get("ssvid") or own.get("ssvid") or key) == key:
            types = [t for t in ((e.get("combinedSourcesInfo") or [{}])[0].get("shiptypes") or [])
                     if t.get("name") not in GFW_SKIP_TYPES]
            latest = max(types, key=lambda t: t.get("yearTo") or 0)["name"] if types else None
            imo = reg.get("imo") or own.get("imo")
            out = {"type": latest.replace("_", " ").capitalize() if latest else None,
                   "imo": int(imo) if str(imo or "").isdigit() and int(imo) > 0 else None,
                   "callsign": reg.get("callsign") or own.get("callsign"),
                   "length_m": reg.get("lengthM"), "tonnage_gt": reg.get("tonnageGt"),
                   "source": "Global Fishing Watch"}
    _identities[key] = out
    return out


UA = {"User-Agent": "OpenSTS/1.0 (https://github.com/Jaswanth-K1210/smugglers)"}  # Wikimedia asks for one
_photos: dict = {}


def photo(imo):
    """A freely licensed Wikimedia Commons photo filed under 'IMO nnnnnnn', or None. Cached per IMO."""
    if not imo:
        return None
    if imo in _photos:
        return _photos[imo]
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", timeout=8, headers=UA, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f'"IMO {imo}"',
            "gsrnamespace": 6, "gsrlimit": 5, "prop": "imageinfo", "iiprop": "url|extmetadata|mime",
            "iiurlwidth": 640})
        r.raise_for_status()
        pages = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99))
    except Exception:
        return None                                  # transient: don't cache, try again next click
    hit = None
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        md = ii.get("extmetadata") or {}
        strip = lambda k: html.unescape(re.sub(r"<[^>]+>", "", (md.get(k) or {}).get("value", ""))).strip() or None
        hit = {"url": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"),
               "author": strip("Artist"), "license": strip("LicenseShortName"), "source": "Wikimedia Commons"}
        break
    _photos[imo] = hit
    return hit


def _load(path, into, ttl):
    try:
        now = time.time()
        into.update({int(k): v for k, v in json.loads(path.read_text()).items() if now - v["t"] < ttl})
    except (OSError, ValueError):
        pass


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(path)                              # atomic: a crash mid-write never leaves half a file


def load_statics():
    """Static data and recent positions survive restarts: cards are full and the map is not empty
    straight after a restart, instead of filling in over ~6 min."""
    _load(STATIC_PATH, statics, STATIC_TTL)
    _load(POSITIONS_PATH, ships, STALE_S)


def save_statics(snapshot=None, positions=None):
    _write(STATIC_PATH, snapshot if snapshot is not None else dict(statics))
    _write(POSITIONS_PATH, positions if positions is not None else dict(ships))


async def _autosave():
    while True:
        await asyncio.sleep(SAVE_EVERY_S)
        try:
            # copy on the event loop (where _store writes), serialise off it
            await asyncio.to_thread(save_statics, dict(statics), dict(ships))
        except OSError as e:
            state["error"] = f"Could not save AIS static data: {e}"


async def run_aisstream(key: str):
    """Hold the websocket open forever; reconnect after drops.

    Keepalive pings are off: aisstream answers them late while streaming, so the
    client's ping timeout (code 1011) cut the connection every minute or two and
    most ships' 6-minutely static reports were lost. A silence watchdog replaces it.
    aisstream allows one connection per key, so never run two of these at once."""
    import websockets
    state["configured"] = True
    load_statics()
    asyncio.get_running_loop().create_task(_autosave())
    sub = json.dumps({"APIKey": key, "BoundingBoxes": BOXES,
                      "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport",
                                             "ShipStaticData", "StaticDataReport"]})
    while True:
        try:
            async with websockets.connect(AISSTREAM_URL, ping_interval=None, open_timeout=15, max_queue=4096) as ws:
                await ws.send(sub)
                state.update(connected=True, error=None)
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), SILENCE_S))
                    if "error" in msg:                 # bad key, malformed subscription
                        state["error"] = str(msg["error"])
                        break
                    _store(msg, time.time())
                    state["messages"] += 1
        except Exception as e:                         # network drop, DNS, server restart
            code = getattr(getattr(e, "rcvd", None), "code", None) or getattr(getattr(e, "sent", None), "code", None)
            reason = getattr(getattr(e, "rcvd", None), "reason", "") or ""
            state["error"] = f"{type(e).__name__} {code or ''} {reason}".strip() + ": reconnecting"
        state["connected"] = False
        state["reconnects"] = state.get("reconnects", 0) + 1
        await asyncio.sleep(10)


def live_vessels(bbox=None, now=None):
    """Fresh positions inside [west, south, east, north]; (ships, total in view).

    A world view can hold 100k ships. Past MAX_VESSELS we keep one ship per grid
    cell so the whole view stays covered, instead of the first N in dict order."""
    now = now or time.time()
    for k in [k for k, v in ships.items() if now - v["t"] > STALE_S]:
        del ships[k]
        tracks.pop(k, None)
    for k in [k for k, v in statics.items() if now - v["t"] > STATIC_TTL]:
        del statics[k]
    w, s_, e, n = bbox or (-180, -90, 180, 90)
    inside = [v for v in ships.values() if w <= v["lon"] <= e and s_ <= v["lat"] <= n]
    total = len(inside)
    if total > MAX_VESSELS:
        inside = _thin(inside, (w, s_, e, n), MAX_VESSELS)
    out = [{**{k: v[k] for k in v if k not in ("t", "nav_status", "mmsi_int", "source")}, "age_s": int(now - v["t"]),
            "group": _group(v["mmsi_int"]), "len": (statics.get(v["mmsi_int"]) or {}).get("length_m")}
           for v in inside]
    reg = regional_in(w, s_, e, n, now)
    va = vesselapi_in(w, s_, e, n, now, exclude={str(v["mmsi"]) for v in out})
    return out + reg + va, total + len(reg) + len(va)


def _thin(ships_in, box, cap):
    """At most `cap` ships spread over the view: every occupied grid cell keeps an equal share,
    and what sparse cells cannot use goes to busy ones. One-per-cell would waste the budget on
    empty ocean when traffic is coastal (31k ships in view drew only a few thousand)."""
    w, s, e, n = box
    grid = int(math.sqrt(cap))
    cw, ch = max(e - w, 1e-6) / grid, max(n - s, 1e-6) / grid
    cells: dict = {}
    for v in ships_in:
        cells.setdefault((min(int((v["lon"] - w) / cw), grid - 1), min(int((v["lat"] - s) / ch), grid - 1)), []).append(v)
    out, left = [], list(cells.values())
    budget = cap
    while left and budget > 0:
        share = max(1, budget // len(left))
        nxt = []
        for lst in left:
            take = lst[:share]
            out.extend(take)
            budget -= len(take)
            if len(lst) > share:
                nxt.append(lst[share:])
            if budget <= 0:
                break
        left = nxt
    return out[:cap]


def regional_in(w, s, e, n, now):
    """Gulf ships from the regional feed inside the view, shaped like live_vessels rows."""
    out = []
    for r in regional.values():
        if not (w <= r["lon"] <= e and s <= r["lat"] <= n):
            continue
        age = now - pd_ts(r["pos_time"])
        if age > STALE_S:
            continue
        out.append({"mmsi": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"], "sog": r["sog"],
                    "cog": r["cog"], "heading": r["heading"], "age_s": int(age),
                    "group": r["category"] if r["category"] in REGIONAL_GROUPS else "unknown",
                    "len": r["length_m"], "source": "hormuz.now"})
    return out


REGIONAL_GROUPS = {"cargo", "tanker", "passenger", "highspeed", "fishing", "special", "pleasure", "other", "unknown"}


async def run_regional():
    """Poll the Gulf snapshot every 5 min (their data refreshes every ~20 s; 5 min is fair use) and record it."""
    from src import regional_ais
    while True:
        try:
            rows, ow = await asyncio.to_thread(regional_ais.fetch_gulf)
            merge_openwaters(ow)          # MMSI ships: same store, cards and photos as everywhere else
            regional.clear()              # hormuz.now only for the ships Open Waters lacks
            regional.update({r["id"]: r for r in rows if r["source"] == regional_ais.SOURCE})
            # Where a scheduled job owns the recording (Modal), this process only serves the live map
            n = await asyncio.to_thread(regional_ais.record, rows) if os.getenv("REGIONAL_RECORD", "1") != "0" else 0
            regional_state.update(ok=True, at=time.time(), error=None, count=len(rows),
                                  recorded=regional_state["recorded"] + n)
        except Exception as e:                      # their site down / network: keep the last snapshot
            regional_state.update(ok=False, error=f"{type(e).__name__}")
        await asyncio.sleep(REGIONAL_EVERY_S)


GFW_GROUPS = {"Cargo": "cargo", "Carrier": "cargo", "Passenger": "passenger", "Fishing": "fishing",
              "Tug": "special", "Bunker": "tanker"}   # GFW has no general tanker class; tankers come back "Other"


def _group(mmsi):
    """AIS static type first; else the GFW identity if someone already opened this ship's card."""
    g = type_group((statics.get(mmsi) or {}).get("type_code"))
    if g == "unknown":
        g = GFW_GROUPS.get(((_identities.get(str(mmsi)) or {}).get("type")), "unknown")
    return g


def search_ships(q: str, limit: int = 10):
    """Ships anywhere (live feed and Gulf feed) whose name or MMSI contains `q`, exact hits first."""
    q = q.strip().upper()
    if len(q) < 2:
        return []
    hits = []
    for v in ships.values():
        name = (v.get("name") or (statics.get(v["mmsi_int"]) or {}).get("name") or "").upper()
        if q in name or q in v["mmsi"]:
            hits.append((name != q and v["mmsi"] != q, name, {"mmsi": v["mmsi"], "name": name or None,
                                                             "lat": v["lat"], "lon": v["lon"], "source": "aisstream.io"}))
    for r in regional.values():
        name = (r["name"] or "").upper()
        if q in name:
            hits.append((name != q, name, {"mmsi": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
                                           "source": "hormuz.now"}))
    return [h[2] for h in sorted(hits, key=lambda h: (h[0], h[1]))[:limit]]


STRAIT_URL = "https://hormuz.data-tracking.net/api/crossings"
STRAIT_CREDIT = "Hormuz Ship Monitor (hormuz.data-tracking.net), CC BY 4.0, research and non-commercial use"
STRAIT_TTL = 10 * 60
_strait: dict = {}


def strait_crossings(hours=48):
    """Strait of Hormuz crossings, longest unobserved first.

    gap_hours is how long the ship was not observed between leaving one gulf and appearing in
    the other: a reception gap or a transponder switched off, not knowable which. Their linker
    tolerates gaps up to 15 days."""
    hours = max(1, min(int(hours), 168))
    hit = _strait.get(hours)
    if hit and time.time() - hit["at"] < STRAIT_TTL:
        return hit["data"]
    r = requests.get(STRAIT_URL, params={"hours": hours}, headers=UA, timeout=20)
    r.raise_for_status()
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("crossings") or []
    out = [{"name": (c.get("ship_name") or "").strip() or None, "category": c.get("ship_category"),
            "flag": c.get("flag") if c.get("flag") not in (None, "--") else None,
            "dwt": c.get("dwt"), "length_m": c.get("length"), "direction": c.get("direction"),
            "at": c.get("detected_at"), "unobserved_h": c.get("gap_hours"), "destination": c.get("destination"),
            "from_zone": c.get("first_seen_zone"), "to_zone": c.get("last_seen_zone")} for c in rows]
    out.sort(key=lambda c: -(c["unobserved_h"] or 0))
    data = {"hours": hours, "crossings": out, "source": STRAIT_CREDIT}
    _strait[hours] = {"at": time.time(), "data": data}
    return data


_particulars: dict = {}
PARTICULARS_TTL = 24 * 3600


def particulars(mmsi):
    """Registered particulars (builder, year built, tonnage, home port) from Open Waters'
    enrichment, with its credit; None when it holds none. Cached a day."""
    key = str(mmsi)
    if not key.isdigit():
        return None
    hit = _particulars.get(key)
    if hit and time.time() - hit["at"] < PARTICULARS_TTL:
        return hit["data"]
    try:
        from src import openwaters
        headers = dict(openwaters.UA)
        if openwaters.token():
            headers["Authorization"] = f"Bearer {openwaters.token()}"
        r = requests.get(f"{openwaters.BASE}/vessels/{key}", headers=headers, timeout=20)
        if r.status_code == 404:
            data = None
        else:
            r.raise_for_status()
            p = (r.json().get("properties") or {})
            part = p.get("particulars")
            keep = ("ship_type", "builder", "year_built", "gross_tonnage", "deadweight", "registry", "home_port")
            data = {"fields": {k: part[k] for k in keep if part.get(k) not in (None, "")},
                    "first_seen": p.get("first_seen"), "source": "Open Waters vessel particulars"} if part else None
            if data and not data["fields"]:
                data = None
    except Exception:
        return None                                  # don't cache failures
    _particulars[key] = {"at": time.time(), "data": data}
    return data


_gfw_layers: dict = {}
GFW_LAYER_TTL = 6 * 3600
GFW_MAX_DEG = 5.0            # hourly 1 km presence cells: bigger boxes are slow and heavy
GFW_LAG_DAYS = (4, 5, 6)     # measured: GFW AIS appears ~4-5 days after the fact


def gfw_layers(bbox):
    """GFW satellite AIS (latest position per vessel on the newest available day) and GFW's own
    Sentinel-1 radar detections for the same day, in [west, south, east, north].

    Delayed by days, so it is context, not a live layer; it covers what aisstream cannot."""
    import pandas as pd
    from src import gfw
    w, s, e, n = bbox
    if e - w > GFW_MAX_DEG or n - s > GFW_MAX_DEG:
        raise ValueError(f"Zoom in: GFW layers cover at most {GFW_MAX_DEG:.0f}° × {GFW_MAX_DEG:.0f}° at a time.")
    key = tuple(round(v, 1) for v in bbox)
    hit = _gfw_layers.get(key)
    if hit and time.time() - hit["at"] < GFW_LAYER_TTL:
        return hit["data"]
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    data = {"day": None, "vessels": [], "radar": [], "source": "Global Fishing Watch (satellite + terrestrial AIS; "
            "Sentinel-1 detections)", "delay_days": None}
    for lag in GFW_LAG_DAYS:
        day = today - pd.Timedelta(days=lag)
        p = gfw.ais_presence(str(day.date()), str((day + pd.Timedelta(days=1)).date()), bbox)
        if len(p):
            last = p.sort_values("timestamp").drop_duplicates("mmsi", keep="last")
            data.update(day=str(day.date()), delay_days=lag, vessels=[
                {"id": str(r.mmsi), "lat": round(float(r.lat), 4), "lon": round(float(r.lon), 4),
                 "time": r.timestamp.isoformat()} for r in last.itertuples(index=False)])
            try:
                sar = gfw._report(gfw.SAR, str(day.date()), str((day + pd.Timedelta(days=1)).date()), bbox, "DAILY")
                data["radar"] = [{"lat": round(float(r.lat), 4), "lon": round(float(r.lon), 4),
                                  "ais_matched": bool(r.mmsi), "detections": int(r.detections)}
                                 for r in sar.itertuples(index=False)] if len(sar) else []
            except Exception:
                data["radar"] = []               # radar layer failing must not hide the AIS layer
            break
    _gfw_layers[key] = {"at": time.time(), "data": data}
    return data


NEWS_QUERY = '("ship-to-ship transfer" OR "shadow fleet" OR "sanctioned tanker" OR "dark fleet")'
NEWS_REGIONS = {
    "all": "",
    "skagerrak": " (Skagerrak OR Baltic OR Denmark OR Norway)",
    "gulf-of-oman": " (\"Gulf of Oman\" OR Fujairah OR Iran OR Hormuz)",
    "laconia": " (Laconia OR Greece OR Kalamata OR Mediterranean)",
}
NEWS_TTL = 15 * 60
_news_cache: dict = {}


def parse_rss(xml_text: str, limit: int = 20):
    items = []
    for it in ET.fromstring(xml_text).iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):     # Google appends " - Publisher"
            title = title[: -len(source) - 3]
        try:
            published = parsedate_to_datetime(it.findtext("pubDate") or "").isoformat()
        except (TypeError, ValueError):
            published = None
        items.append({"title": title, "link": it.findtext("link"), "source": source or None,
                      "published": published})
    items.sort(key=lambda i: i["published"] or "", reverse=True)
    return items[:limit]


def news(region: str = "all"):
    region = region if region in NEWS_REGIONS else "all"
    hit = _news_cache.get(region)
    if hit and time.time() - hit["at"] < NEWS_TTL:
        return hit["data"]
    q = quote(NEWS_QUERY + NEWS_REGIONS[region] + " when:30d")
    try:
        r = requests.get(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
                         timeout=8, headers={"User-Agent": "OpenSTS/1.0"})
        r.raise_for_status()
        data = {"region": region, "items": parse_rss(r.text), "error": None}
    except Exception as e:
        if hit:                                           # stale news beats no news
            return hit["data"]
        return {"region": region, "items": [], "error": f"News is unavailable right now ({type(e).__name__})."}
    _news_cache[region] = {"at": time.time(), "data": data}
    return data


# ── VesselAPI: on-demand fill for views the free live feeds do not cover (e.g. India) ──
# The free plan is 150 requests a month and 50 ships per request, so it cannot drive a map
# that refreshes every 15 s. A user asks for it per view ("Fill this view"); ships stay on
# the map for VESSELAPI_KEEP_S, and a reserve of requests is never spent.
VESSELAPI_URL = "https://api.vesselapi.com/v1/location/vessels/bounding-box"
VESSELAPI_PAGES = 2            # 50 ships each: up to 100 ships per fill
VESSELAPI_MAX_DEG = 2.0        # larger views would scatter 100 ships too thinly to be useful
VESSELAPI_RESERVE = 10         # requests kept back so the month never runs dry
VESSELAPI_KEEP_S = 30 * 60
vesselapi_rows: dict = {}      # mmsi -> row, with "fetched"
vesselapi_state = {"remaining": None, "error": None, "last_fill": None}


def vesselapi_configured():
    return bool(os.getenv("VESSELAPI_KEY"))


def vesselapi_fill(box, now=None):
    """Fetch up to VESSELAPI_PAGES pages of positions inside box. Raises ValueError with a sentence."""
    now = now or time.time()
    key = os.getenv("VESSELAPI_KEY")
    if not key:
        raise ValueError("VesselAPI is not configured on this server.")
    w, s, e, n = box
    if e - w > VESSELAPI_MAX_DEG or n - s > VESSELAPI_MAX_DEG:
        raise ValueError(f"Zoom in to at most {VESSELAPI_MAX_DEG:g}° × {VESSELAPI_MAX_DEG:g}° to fill the view.")
    rem = vesselapi_state["remaining"]
    if rem is not None and rem <= VESSELAPI_RESERVE:
        raise ValueError("This month's VesselAPI requests are used up (a small reserve is kept).")
    params = {"filter.lonLeft": w, "filter.lonRight": e, "filter.latBottom": s, "filter.latTop": n,
              "pagination.limit": 50}
    added = 0
    for _ in range(VESSELAPI_PAGES):
        r = requests.get(VESSELAPI_URL, headers={"Authorization": f"Bearer {key}", **UA}, params=params, timeout=30)
        if r.headers.get("X-Ratelimit-Remaining", "").isdigit():
            vesselapi_state["remaining"] = int(r.headers["X-Ratelimit-Remaining"])
        if r.status_code != 200:
            vesselapi_state["error"] = f"VesselAPI answered {r.status_code}"
            raise ValueError("VesselAPI did not answer; try again later.")
        d = r.json()
        for v in d.get("vessels") or []:
            if v.get("suspected_glitch") or v.get("latitude") is None:
                continue
            vesselapi_rows[str(v["mmsi"])] = {
                "mmsi": str(v["mmsi"]), "name": (v.get("vessel_name") or "").strip() or None,
                "lat": float(v["latitude"]), "lon": float(v["longitude"]), "sog": v.get("sog"), "cog": v.get("cog"),
                "heading": v.get("heading"), "reported": pd_ts(v["timestamp"]) if v.get("timestamp") else now,
                "fetched": now}
            added += 1
        if not d.get("nextToken") or (vesselapi_state["remaining"] or 0) <= VESSELAPI_RESERVE:
            break
        params["pagination.nextToken"] = d["nextToken"]
    vesselapi_state.update(error=None, last_fill=now)
    return {"added": added, "remaining": vesselapi_state["remaining"]}


def vesselapi_in(w, s, e, n, now, exclude=()):
    """VesselAPI ships inside the view, shaped like live_vessels rows; a free feed's copy wins."""
    out = []
    for k in [k for k, r in vesselapi_rows.items() if now - r["fetched"] > VESSELAPI_KEEP_S]:
        del vesselapi_rows[k]
    for r in vesselapi_rows.values():
        if r["mmsi"] in exclude or not (w <= r["lon"] <= e and s <= r["lat"] <= n):
            continue
        mmsi = int(r["mmsi"]) if r["mmsi"].isdigit() else None
        out.append({"mmsi": r["mmsi"], "name": r["name"], "lat": r["lat"], "lon": r["lon"], "sog": r["sog"],
                    "cog": r["cog"], "heading": r["heading"], "age_s": int(now - r["reported"]),
                    "group": _group(mmsi) if mmsi else "unknown", "len": None, "source": "VesselAPI"})
    return out
