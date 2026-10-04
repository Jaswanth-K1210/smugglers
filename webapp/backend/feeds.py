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
STALE_S = 30 * 60
MAX_VESSELS = 20000   # per response; past this the view is thinned evenly, not truncated

ships: dict = {}       # MMSI -> newest position
tracks: dict = {}      # MMSI -> array('f') of lat, lon, seconds-since-T0 triples
T0 = time.time()
TRACK_EVERY_S = 5 * 60   # one point per 5 min ...
TRACK_KEEP_S = 6 * 3600  # ... for 6 h: ≤72 points, 12 bytes each
# ITU-R MID table (itu.int/gladapp/Allocation/MIDs) with ISO 3166 alpha-2: MID -> [ISO2, country]
MIDS = json.loads((Path(__file__).parent / "mids.json").read_text())
statics: dict = {}     # MMSI -> type, IMO, call sign, size, destination (sent every ~6 min)
STATIC_TTL = 7 * 24 * 3600   # type / IMO / size barely change; destination and ETA refresh on the next report
STATIC_PATH = Path(os.getenv("AIS_STATIC_PATH", Path(__file__).resolve().parents[2] / "data" / "ais_static.json"))
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
    """Map colour group, MarineTraffic-style: cargo, tanker, passenger, highspeed, fishing, special, pleasure, other."""
    if not code:
        return "unknown"
    if code == 30:
        return "fishing"
    if code in (36, 37):
        return "pleasure"
    if code in (31, 32, 33, 34, 35) or 50 <= code <= 59:
        return "special"
    return {4: "highspeed", 6: "passenger", 7: "cargo", 8: "tanker"}.get(code // 10, "other")


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


def vessel(mmsi: str, now=None):
    """Everything known about one ship, in words; None if never heard."""
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
    out = {"mmsi": str(key), **{k: v for k, v in (pos or {}).items() if k not in ("t", "mmsi", "mmsi_int", "nav_status")}}
    if pos:
        out["age_s"] = int(now - pos["t"])
        out["nav_status"] = NAV_STATUS.get(pos.get("nav_status"))
    if st:
        out.update({k: v for k, v in st.items() if k not in ("t", "name")})
        out["name"] = out.get("name") or st.get("name")    # position reports sometimes carry no name
        out["type"] = ship_type(st.get("type_code"))
    out.setdefault("type", None)
    out["flag"] = flag(key)
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
    try:
        from src.gfw import BASE, _headers
        r = requests.get(f"{BASE}/vessels/search", headers=_headers(), timeout=20, params={
            "query": key, "datasets[0]": "public-global-vessel-identity:latest", "limit": 1})
        r.raise_for_status()
        entries = r.json().get("entries") or []
    except Exception:
        return None                                  # no token / GFW down: don't cache, retry next time
    out = None
    if entries:
        e = entries[0]
        reg = (e.get("registryInfo") or [{}])[0]
        own = (e.get("selfReportedInfo") or [{}])[0]
        if str(reg.get("ssvid") or own.get("ssvid") or key) == key:
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


def load_statics():
    """Static data survives restarts, so ship cards are full straight away instead of after ~6 min."""
    try:
        now = time.time()
        statics.update({int(k): v for k, v in json.loads(STATIC_PATH.read_text()).items() if now - v["t"] < STATIC_TTL})
    except (OSError, ValueError):
        pass


def save_statics(snapshot=None):
    STATIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATIC_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot if snapshot is not None else dict(statics), separators=(",", ":")))
    tmp.replace(STATIC_PATH)                       # atomic: a crash mid-write never leaves half a file


async def _autosave():
    while True:
        await asyncio.sleep(SAVE_EVERY_S)
        try:
            # copy on the event loop (where _store writes), serialise off it
            await asyncio.to_thread(save_statics, dict(statics))
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
        grid = int(math.sqrt(MAX_VESSELS))           # grid² ≤ cap, so no cell is ever cut
        cw, ch = max(e - w, 1e-6) / grid, max(n - s_, 1e-6) / grid
        cells = {}
        for v in inside:
            cells.setdefault((min(int((v["lon"] - w) / cw), grid - 1), min(int((v["lat"] - s_) / ch), grid - 1)), v)
        inside = list(cells.values())
    return [{**{k: v[k] for k in v if k not in ("t", "nav_status", "mmsi_int")}, "age_s": int(now - v["t"]),
             "group": _group(v["mmsi_int"])} for v in inside], total


GFW_GROUPS = {"Cargo": "cargo", "Carrier": "cargo", "Passenger": "passenger", "Fishing": "fishing",
              "Tug": "special", "Bunker": "tanker"}   # GFW has no general tanker class; tankers come back "Other"


def _group(mmsi):
    """AIS static type first; else the GFW identity if someone already opened this ship's card."""
    g = type_group((statics.get(mmsi) or {}).get("type_code"))
    if g == "unknown":
        g = GFW_GROUPS.get(((_identities.get(str(mmsi)) or {}).get("type")), "unknown")
    return g


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
