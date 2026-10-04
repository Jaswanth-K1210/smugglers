"""Regional AIS for the Persian Gulf, Strait of Hormuz and Gulf of Oman (hormuz.now).

aisstream.io has no receivers in the Gulf, so the live map was empty there. hormuz.now
publishes a free live snapshot (~1,600 ships, refreshed every ~20 s, CC BY 4.0, attribution
"hormuz.now") with a per-ship position time.

What this source is NOT, and the code keeps it that way:
  - not independent of other public trackers: it has no MMSI, only an internal ship id, and
    its fields look like those of a commercial tracker's public map. Its provenance is
    unverified, so it counts as ONE secondary AIS source, never as corroboration of another
    public tracker, and never as satellite AIS;
  - not an archive: the API serves only the latest snapshot. Matching a Sentinel-1 pass needs
    positions around the pass time, so `record()` keeps our own rolling history from now on.
    Passes before recording started cannot be matched against this source.

Recorder: one gzip CSV per UTC day under data/regional_ais/, one row per ship at most every
RECORD_EVERY_MIN, kept RETAIN_DAYS. Roughly 3 MB per day compressed.
"""
import csv
import gzip
import math
import time
import os
from pathlib import Path

import pandas as pd
import requests

from src.config import DATA

SNAPSHOT_URL = "https://hormuz.now/api/snapshot"
ATTRIBUTION = "hormuz.now (CC BY 4.0), provenance unverified"
# The Gulf feed is now Open Waters first (real MMSI; AISHub data, redistribution confirmed),
# with hormuz.now only for ships Open Waters does not have. See fetch_gulf().
SOURCE = "hormuz.now"
# Where the feed has coverage: west, south, east, north (Persian Gulf + Strait + Gulf of Oman)
COVERAGE = (47.3, 22.3, 61.0, 30.3)
UA = {"User-Agent": "OpenSTS/1.0 (https://github.com/Jaswanth-K1210/smugglers)"}

DIR = Path(os.getenv("REGIONAL_AIS_DIR", DATA / "regional_ais"))   # own Modal volume in deployment
RECORD_EVERY_MIN = 15
RETAIN_DAYS = 30
MAX_LENGTH_M = 460          # longer than any ship afloat: a bad record, not a ship
FIELDS = ["id", "name", "lat", "lon", "sog", "cog", "heading", "pos_time", "category", "type",
          "flag", "length_m", "width_m", "dwt", "destination", "source"]
DUP_KM = 5                  # same name within this distance = the same ship seen by both feeds


def covers(box) -> bool:
    w, s, e, n = box
    cw, cs, ce, cn = COVERAGE
    return w < ce and e > cw and s < cn and n > cs


def _num(v, lo=None, hi=None):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v != v or (lo is not None and v < lo) or (hi is not None and v > hi):
        return None
    return v


def normalise(v: dict):
    """One hormuz.now vessel -> our row, or None for aids to navigation and broken records."""
    if v.get("category") == "navaid" or v.get("lat") is None or v.get("lon") is None or not v.get("posAt"):
        return None
    length = _num(v.get("length"), 1, MAX_LENGTH_M)
    return {
        "id": f"hn:{v['id']}",
        "name": (v.get("name") or "").strip() or None,
        "lat": round(float(v["lat"]), 5),
        "lon": round(float(v["lon"]), 5),
        "sog": _num(v.get("speed"), 0, 60),
        "cog": _num(v.get("course"), 0, 359.9),
        "heading": _num(v.get("heading"), 0, 359.9) or None,   # 0 is their "not available"
        "pos_time": pd.Timestamp(int(v["posAt"]), unit="ms").isoformat(),
        "category": v.get("category") or "unknown",
        "type": v.get("shiptypeLabel") or None,
        "flag": (v.get("flag") or "").strip() or None,
        "length_m": length,
        "width_m": _num(v.get("width"), 1, 80) if length else None,
        "dwt": _num(v.get("dwt"), 1) or None,
        "destination": (v.get("destination") or "").strip() or None,
        "source": SOURCE,
    }


def _norm_name(v):
    return "".join(ch for ch in (v or "").upper() if ch.isalnum())


def from_openwaters(r):
    """An Open Waters row in this module's row shape (id = the real MMSI)."""
    from src import openwaters
    t = pd.Timestamp(r["seen"], unit="s")
    return {"id": str(r["mmsi"]), "name": r["name"], "lat": r["lat"], "lon": r["lon"], "sog": r["sog"],
            "cog": r["cog"], "heading": r["heading"], "pos_time": t.isoformat(),
            "category": openwaters.category(r["type_code"]), "type": None, "flag": r["flag"],
            "length_m": r["length_m"], "width_m": r["beam_m"], "dwt": None, "destination": r["destination"],
            "source": f"openwaters:{r['source']}"}


SAME_SPOT_KM = 0.5          # ...or this close with a similar length, whatever the spelling of the name
LENGTH_TOL = 0.15


def _km(a, b):
    return math.hypot((a["lat"] - b["lat"]) * 111.32, (a["lon"] - b["lon"]) * 111.32 * math.cos(math.radians(b["lat"])))


def leftovers(hn_rows, mmsi_rows):
    """hormuz.now rows for ships the MMSI feed does not have. Counting both would make one ship
    two identities (hormuz.now has no MMSI to join on), so a hormuz.now row is dropped when an
    MMSI row has the same name within DUP_KM, or sits within SAME_SPOT_KM with a length within
    LENGTH_TOL (names are spelled differently between feeds)."""
    by_name: dict = {}
    for r in mmsi_rows:
        by_name.setdefault(_norm_name(r["name"]), []).append(r)
    out = []
    for h in hn_rows:
        same = by_name.get(_norm_name(h["name"]), []) if h["name"] else []
        if any(_km(o, h) <= DUP_KM for o in same):
            continue
        hl = h.get("length_m")
        if hl and any(o.get("length_m") and abs(o["length_m"] - hl) <= LENGTH_TOL * hl and _km(o, h) <= SAME_SPOT_KM
                      for o in mmsi_rows):
            continue
        out.append(h)
    return out


def fetch_gulf():
    """(rows to record, Open Waters rows): Open Waters first (real MMSI, named source), then
    hormuz.now for the ships it lacks. Either source failing leaves the other."""
    from src import openwaters
    ow, hn = [], []
    try:
        ow = openwaters.fetch(COVERAGE)
    except Exception:
        pass
    try:
        hn = fetch_snapshot()
    except Exception:
        pass
    if not ow and not hn:
        raise RuntimeError("Neither Gulf AIS source answered.")
    return [from_openwaters(r) for r in ow] + leftovers(hn, ow), ow


def fetch_snapshot(timeout=30):
    r = requests.get(SNAPSHOT_URL, headers=UA, timeout=timeout)
    r.raise_for_status()
    return [row for row in map(normalise, r.json().get("vessels") or []) if row]


_last_recorded: dict = {}   # id -> pos_time of the last row written
before_read = None          # optional hook, e.g. Modal's volume.reload, to see another writer's rows


def _seed(root, now):
    """A fresh process (a scheduled run) learns what is already recorded today, so sampling holds."""
    for day in (now - pd.Timedelta(days=1), now):
        path = root / f"{day:%Y-%m-%d}.csv.gz"
        if path.exists():
            d = pd.read_csv(path, compression="gzip", usecols=["id", "pos_time"])
            for i, t in d.groupby("id").pos_time.max().items():
                _last_recorded[i] = max(_last_recorded.get(i, pd.Timestamp.min), pd.Timestamp(t))


def record(rows, root=None, now=None):
    """Append positions not seen in the last RECORD_EVERY_MIN; prune old days. Returns rows written."""
    root = Path(root or DIR)
    root.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp(now or pd.Timestamp.utcnow())
    now = now.tz_localize(None) if now.tzinfo else now
    if not _last_recorded:
        _seed(root, now)
    by_day: dict = {}
    for row in rows:
        t = pd.Timestamp(row["pos_time"])
        last = _last_recorded.get(row["id"])
        if last is not None and (t - last) < pd.Timedelta(minutes=RECORD_EVERY_MIN):
            continue
        _last_recorded[row["id"]] = t
        by_day.setdefault(f"{t:%Y-%m-%d}", []).append(row)
    for day, day_rows in by_day.items():
        path = root / f"{day}.csv.gz"
        new = not path.exists()
        with gzip.open(path, "at", newline="") as f:      # appends a gzip member; readers see one stream
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(day_rows)
    for old in root.glob("*.csv.gz"):
        if old.name < f"{now - pd.Timedelta(days=RETAIN_DAYS):%Y-%m-%d}":
            old.unlink()
    return sum(len(v) for v in by_day.values())


def load_window(start, end, box=None, root=None):
    """Recorded positions in [start, end] (and box), shaped for dark_sts.characterise:
    mmsi (our 'hn:' id), lat, lon, timestamp, plus sog, cog, length_m, type, name."""
    root = Path(root or DIR)
    if before_read:
        try:
            before_read()
        except Exception:
            pass                      # stale view of the recording beats a failed search
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    frames = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        path = root / f"{day:%Y-%m-%d}.csv.gz"
        if path.exists():
            frames.append(pd.read_csv(path, compression="gzip"))
    cols = ["mmsi", "lat", "lon", "timestamp", "sog", "cog", "length_m", "type", "name"]
    if not frames:
        return pd.DataFrame(columns=cols)
    d = pd.concat(frames, ignore_index=True)
    d["timestamp"] = pd.to_datetime(d.pos_time)
    d = d[(d.timestamp >= start) & (d.timestamp <= end)]
    if box:
        w, s, e, n = box
        d = d[(d.lon >= w) & (d.lon <= e) & (d.lat >= s) & (d.lat <= n)]
    return d.rename(columns={"id": "mmsi"})[cols].reset_index(drop=True)


def recorded_span(root=None):
    """(first, last) recorded position time, or (None, None)."""
    files = sorted(Path(root or DIR).glob("*.csv.gz"))
    if not files:
        return None, None
    first = pd.read_csv(files[0], compression="gzip", usecols=["pos_time"]).pos_time.min()
    last = pd.read_csv(files[-1], compression="gzip", usecols=["pos_time"]).pos_time.max()
    return pd.Timestamp(first), pd.Timestamp(last)


if __name__ == "__main__":
    t0 = time.time()
    rows, ow = fetch_gulf()
    print(f"{len(rows)} ships ({len(ow)} from Open Waters) in {time.time() - t0:.1f}s; "
          f"recorded {record(rows)} rows to {DIR}")
