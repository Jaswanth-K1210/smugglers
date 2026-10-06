"""FastAPI service for the Dark STS dashboard.

Serves PRECOMPUTED results. The pipeline runs offline (Colab), writes
outputs/events.geojson, and this process only reads it. No GPU is involved and
no scene is fetched per request — a 650 MB AIS day and a 30 MB SAR scene have no
place in an HTTP handler.

The one live endpoint, /detect, runs the detector on a single uploaded tile on
CPU. YOLO nano at 1024px is ~1-2 s on two vCPUs, which is what makes a demo
interactive instead of a slideshow. It is optional: if no weights ship with the
image, the endpoint reports that plainly instead of failing at import.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from webapp.backend import store, worker

ROOT = Path(__file__).resolve().parents[2]
EVENTS = Path(os.getenv("EVENTS_PATH", ROOT / "outputs" / "events.geojson"))
WEIGHTS = Path(os.getenv("WEIGHTS_PATH", ROOT / "models" / "darksts" / "weights" / "best.pt"))
FRONTEND = ROOT / "webapp" / "frontend"
DIST = FRONTEND / "dist"
USERS_DB = Path(os.getenv("USERS_DB", ROOT / "data" / "users.db"))


def _auth_secret() -> bytes:
    """AUTH_SECRET from the environment, else a random one kept next to the user DB."""
    if os.getenv("AUTH_SECRET"):
        return os.environ["AUTH_SECRET"].encode()
    f = USERS_DB.parent / "auth_secret"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists():
            f.write_text(secrets.token_hex(32))
            f.chmod(0o600)
        return f.read_text().strip().encode()
    except OSError:                                 # read-only disk: sessions end at restart
        return secrets.token_hex(32).encode()


AUTH_SECRET = _auth_secret()
TOKEN_TTL = 7 * 24 * 3600

app = FastAPI(title="Dark STS Detection", version="1.0",
              description="Open-data Sentinel-1 + AIS ship-to-ship transfer characterisation")
# Bearer tokens, not cookies, so "*" is safe; set ALLOWED_ORIGINS to the Vercel URL to narrow it.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

_cache = {"mtime": None, "data": None}


def infer_region(lat: float, lon: float) -> str:
    if 55.0 <= lat <= 60.0 and 8.0 <= lon <= 13.0:
        return "Skagerrak"
    if 22.0 <= lat <= 27.0 and 55.0 <= lon <= 61.0:
        return "Gulf of Oman"
    if 35.0 <= lat <= 38.0 and 21.0 <= lon <= 24.0:
        return "Laconia Bay"
    return "Coastal Europe"


def transform_feature_to_dict(f: dict, index: int) -> dict:
    p = f.get("properties", {})
    coords = f.get("geometry", {}).get("coordinates", [0.0, 0.0])
    lon = float(coords[0] if len(coords) > 0 else 0.0)
    lat = float(coords[1] if len(coords) > 1 else 0.0)
    mmsis = p.get("mmsis") or []
    if isinstance(mmsis, str):
        try:
            mmsis = json.loads(mmsis)
        except Exception:
            mmsis = []

    mmsi1 = str(mmsis[0]) if len(mmsis) > 0 else "Unknown"
    mmsi2 = str(mmsis[1]) if len(mmsis) > 1 else ("Dark Target" if p.get("category") == "AIS_UNMATCHED" else "Unknown")
    time_str = p.get("time") or p.get("timestamp") or ""
    if " " in time_str and "T" not in time_str:
        time_str = time_str.replace(" ", "T") + "Z"

    return {
        "id": str(p.get("id", index)),
        "lat": lat,
        "lon": lon,
        "timestamp": time_str,
        "vessel1": p.get("registry_name") or mmsi1,
        "vessel2": mmsi2,
        "distance": round(float(p.get("length_m") or p.get("distance") or 0)),
        "duration": round(float(p.get("duration_min") or 0) / 60.0, 1),
        "status": p.get("category") or "AIS_UNMATCHED",
        "confidence": float(p.get("conf") or 0.0),
        "gfw_match": bool(p.get("gfw_encounter")),
        "vessel1_mmsi": mmsi1,
        "vessel2_mmsi": mmsi2,
        "length_estimate": round(float(p.get("length_m") or 0)),
        "region": p.get("region") or infer_region(lat, lon),
    }


def load_events():
    """Read the GeoJSON, re-reading only when the file changes."""
    if not EVENTS.exists():
        return {"type": "FeatureCollection", "features": []}
    m = EVENTS.stat().st_mtime
    if _cache["mtime"] != m:
        _cache.update(mtime=m, data=json.loads(EVENTS.read_text()))
    return _cache["data"]


_stores = {}


def _users():
    """Accounts: MongoDB when MONGODB_URI is set (Render), else the SQLite file at USERS_DB."""
    key = "mongo" if os.getenv("MONGODB_URI") else str(USERS_DB)
    if key not in _stores:
        _stores[key] = store.open_stores(USERS_DB)
    return _stores[key][0]


_search_store = None


def _searches():
    """Search records (quotas, polling): MongoDB when configured, else memory."""
    global _search_store
    if _search_store is None:
        _search_store = (store.open_stores(USERS_DB)[1] if os.getenv("MONGODB_URI")
                         else store.MemorySearches())
    return _search_store


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def _token(email: str) -> str:
    body = base64.urlsafe_b64encode(f"{email}|{int(time.time()) + TOKEN_TTL}".encode()).decode()
    sig = hmac.new(AUTH_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _user(email: str):
    u = _users().get(email)
    return {"name": u["name"], "email": u["email"]} if u else None


def current_user(authorization: str = Header(None)):
    """Bearer token → user, or 401."""
    try:
        body, sig = (authorization or "").removeprefix("Bearer ").split(".")
        good = hmac.new(AUTH_SECRET, body.encode(), hashlib.sha256).hexdigest()
        email, exp = base64.urlsafe_b64decode(body).decode().rsplit("|", 1)
        if hmac.compare_digest(sig, good) and int(exp) > time.time() and (u := _user(email)):
            return u
    except ValueError:
        pass
    raise HTTPException(401, "Sign in to continue.")


_attempts = {}                                      # client -> recent auth attempt times
AUTH_LIMIT, AUTH_WINDOW = 10, 300


def _throttle(request: Request):
    """At most AUTH_LIMIT sign-in / sign-up attempts per client per AUTH_WINDOW seconds.

    ponytail: in-memory and keyed on the forwarded IP, which a client can spoof;
    enough to stop casual password guessing on one container.
    """
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?"))
    ip = ip.split(",")[0].strip()
    now = time.time()
    recent = [t for t in _attempts.get(ip, []) if now - t < AUTH_WINDOW]
    if len(recent) >= AUTH_LIMIT:
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    _attempts[ip] = recent + [now]


def _session(email: str):
    return {"token": _token(email), "user": _user(email)}


@app.post("/api/auth/register")
def auth_register(payload: dict, request: Request):
    _throttle(request)
    email = str(payload.get("email", "")).strip().lower()
    name = str(payload.get("name", "")).strip()
    password = str(payload.get("password", ""))
    if "@" not in email or not name:
        raise HTTPException(422, "Enter your name and a valid email address.")
    if len(email) > 254 or len(name) > 100 or len(password) > 256:
        raise HTTPException(422, "Name, email or password is too long.")
    if len(password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters.")
    salt = secrets.token_bytes(16)
    try:
        _users().add(email, name, salt, _hash(password, salt))
    except store.DuplicateUser:
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    return _session(email)


@app.post("/api/auth/login")
def auth_login(payload: dict, request: Request):
    _throttle(request)
    email = str(payload.get("email", "")).strip().lower()
    u = _users().get(email)
    if not u or not hmac.compare_digest(_hash(str(payload.get("password", "")), u["salt"]), u["hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    return _session(email)


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(current_user)):
    return {"user": user}


_STARTED = time.time()


def _process_stats():
    """Uptime and memory, to tell a server that keeps restarting (out of memory) from a slow one."""
    rss = None
    try:
        with open("/proc/self/status") as f:                       # Linux (Render, Modal)
            rss = next(int(l.split()[1]) // 1024 for l in f if l.startswith("VmRSS:"))
    except (OSError, StopIteration, ValueError):
        pass
    return {"uptime_s": int(time.time() - _STARTED), "rss_mb": rss,
            "live_ships": len(feeds.ships), "live_statics": len(feeds.statics), "live_tracks": len(feeds.tracks)}


@app.get("/api/health")
def health():
    ev = load_events()
    count = len(ev.get("features", []))
    has_weights = WEIGHTS.exists()
    status = "healthy" if EVENTS.exists() else "degraded"
    return {
        "status": status,
        "events": count,
        "eventCount": count,
        "events_file": EVENTS.name if EVENTS.exists() else None,
        "live_detection": SEARCH_MODE == "worker" or has_weights,
        # worker mode: the model runs on Modal, so this server needs no weights of its own
        "search_available": SEARCH_MODE == "worker" or has_weights or bool(os.getenv("HF_MODEL_REPO")),
        "search_mode": SEARCH_MODE,
        **_process_stats(),
        "liveDetectionAvailable": SEARCH_MODE == "worker" or has_weights,
    }


@app.get("/api/events")
def events(
    category: str = None,
    status: str = None,
    region: str = None,
    min_suspicion: float = 0.0,
    limit: int = 1000,
    format: str = None,
    _user: dict = Depends(current_user),
):
    """Precomputed candidates, optionally filtered."""
    feats = load_events().get("features", [])
    target_category = category or status
    if target_category and target_category != "all":
        feats = [f for f in feats if f.get("properties", {}).get("category") == target_category]
    if region and region != "all":
        feats = [f for f in feats if f.get("properties", {}).get("region") == region or infer_region(*f.get("geometry", {}).get("coordinates", [0, 0])[::-1]) == region]
    if min_suspicion:
        feats = [f for f in feats
                 if (f.get("properties", {}).get("suspicion") or 0) >= min_suspicion]
    feats = sorted(feats, key=lambda f: -(f.get("properties", {}).get("suspicion") or 0))[:limit]

    if format in ("flat", "list"):
        return [transform_feature_to_dict(f, i) for i, f in enumerate(feats)]
    return {"type": "FeatureCollection", "features": feats}


@app.get("/api/events/{index}")
def event(index: int, _user: dict = Depends(current_user)):
    feats = load_events().get("features", [])
    if not 0 <= index < len(feats):
        raise HTTPException(404, f"no event {index}; {len(feats)} available")
    f = feats[index]
    return {
        **f,
        "event": transform_feature_to_dict(f, index),
    }


@app.get("/api/summary")
def summary():
    """Counts by category and size class, for the dashboard header."""
    feats = load_events().get("features", [])
    cat, size = {}, {}
    for f in feats:
        p = f.get("properties", {})
        cat[p.get("category", "unknown")] = cat.get(p.get("category", "unknown"), 0) + 1
        size[p.get("size_class", "unknown")] = size.get(p.get("size_class", "unknown"), 0) + 1
    return {"total": len(feats), "by_category": cat, "by_size_class": size,
            "note": "Categories describe AIS evidence, not intent. AIS_UNMATCHED is a "
                    "candidate, not a finding of concealment."}


MAX_UPLOAD = 10 * 1024 * 1024


@app.post("/api/detect")
async def detect(file: UploadFile = File(...), _user: dict = Depends(current_user)):
    """Run the detector on one uploaded tile: here (all-in-one app) or on the Modal worker (Render)."""
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Upload an image of at most 10 MB.")
    try:
        if SEARCH_MODE == "worker":
            return await asyncio.to_thread(worker.detect, data)
        from src.search import detect_upload
        return await asyncio.to_thread(detect_upload, data, search_weights())
    except ValueError as e:
        raise HTTPException(422, str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, _service_error(e))


# ---- area search: draw a box, get ships and reasons ------------------------
# One search at a time: each needs ~1 GB and both free-tier CPUs. Jobs live in
# memory, so a restart forgets them; the result cache on disk survives.
# ponytail: in-memory job table + one worker; move to a queue if traffic grows.
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

HF_MODEL_REPO = os.getenv("HF_MODEL_REPO")            # e.g. "<user>/darksts-detector"
SEARCH_WEIGHTS = os.getenv("SEARCH_WEIGHTS", "best.pt")
_executor = ThreadPoolExecutor(max_workers=1)
MAX_QUEUE = 5                 # searches waiting or running, all users together
DAILY_SEARCHES = 20           # per account
STALE_S = 6 * 3600            # a search not finished in 6 h no longer blocks its user (worker timeout)
DAILY_UNITS = int(os.getenv("SEARCH_DAILY_UNITS", 400))   # per account; one unit = one pass x one 50 km cell, ~$0.004
# local: this server runs the model (the all-in-one Modal app). worker: the Modal worker
# app "darksts-worker" runs it, and this server only starts and polls (Render).
SEARCH_MODE = os.getenv("SEARCH_MODE", "local")


def search_weights() -> Path:
    """Local weights if shipped, else download once from the Hugging Face Hub."""
    if WEIGHTS.exists():
        return WEIGHTS
    if HF_MODEL_REPO:
        from huggingface_hub import hf_hub_download
        return Path(hf_hub_download(HF_MODEL_REPO, SEARCH_WEIGHTS, token=os.getenv("HF_TOKEN")))
    raise HTTPException(503, "No detector weights in this deployment (set HF_MODEL_REPO).")


def _service_error(e):
    """A sentence for a failed call to the search service (Modal), never a stack trace."""
    if any(w in str(e).lower() for w in ("spend limit", "workspace", "billing")):   # Modal refusing on cost
        return ("The search service has used its cloud credit for this billing period, so it cannot "
                "run the detector until the limit is raised or the period resets.")
    return f"The search service could not be reached ({type(e).__name__}). Try again in a minute."


def _set(job_id, **kw):
    _searches().update(job_id, **kw)


def _run_search(job_id, box, weights):
    from src import search
    _set(job_id, status="running")
    try:
        result = search.run(box, weights, progress=lambda stage, frac: _set(job_id, stage=stage,
                                                                            progress=round(frac, 2)))
        _set(job_id, status="done", stage="Done", progress=1.0, result=result)
    except (ValueError, LookupError) as e:
        _set(job_id, status="error", error=str(e))
    except Exception as e:                           # show something useful, never a stack trace
        _set(job_id, status="error", error=f"The search failed ({type(e).__name__}). Try again in a minute.")
        import traceback
        traceback.print_exc()


def _period(payload):
    """(start, end) dates: from the request, or the default recent window. Any length in worker mode."""
    from src import limits
    if payload.get("start") or payload.get("end"):
        return limits.validate_period(payload.get("start"), payload.get("end"),
                                      max_days=None if SEARCH_MODE == "worker" else limits.MAX_PERIOD_DAYS)
    return limits.default_period()


def _box(payload):
    from src.limits import MAX_KM, validate
    return validate(payload.get("bbox") or [], max_km=None if SEARCH_MODE == "worker" else MAX_KM)


def _plan(payload):
    """(box, start, end, plan) for a worker search; HTTP 422 with a sentence when it cannot run."""
    from src import plan
    try:
        box = _box(payload)
        start, end = _period(payload)
        return box, start, end, plan.make_plan(box, start, end)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e) or "Send the box as [west, south, east, north].")
    except LookupError as e:
        raise HTTPException(422, str(e))


def _units_today(email, now):
    return sum(j.get("units") or 0 for j in _searches().since(email, now - 86400))


@app.post("/api/search/estimate")
def estimate_search(payload: dict, user: dict = Depends(current_user)):
    """Passes, cells, minutes and credit for {"bbox", "start"?, "end"?}, before Go. Worker mode only."""
    if SEARCH_MODE != "worker":
        raise HTTPException(404, "Estimates are for period searches (worker mode).")
    from src import plan
    _, start, end, p = _plan(payload)
    left = DAILY_UNITS - _units_today(user["email"], time.time())
    return {**plan.summary(p), "period": [str(start), str(end)], "daily_units_left": max(0, left),
            "over_daily": p["units"] > left}


@app.post("/api/search")
def start_search(payload: dict, user: dict = Depends(current_user)):
    """Start a search over {"bbox": [w, s, e, n], "start"?: "YYYY-MM-DD", "end"?: ...}; poll /api/search/{id}."""
    if SEARCH_MODE == "worker":
        from src import plan
        box, start, end, p = _plan(payload)
        units = p["units"]
        if p["estimate"]["over_limit"]:
            raise HTTPException(422, f"This search is {units} pieces of work; the limit is {plan.MAX_UNITS}. "
                                     "Pick a shorter period or a smaller area.")
        if units > DAILY_UNITS - _units_today(user["email"], time.time()):
            raise HTTPException(429, f"This search ({units} pieces of work) is more than is left of your daily "
                                     f"{DAILY_UNITS}. Pick a shorter period or a smaller area, or try tomorrow.")
    else:
        try:
            box, start, end, units = _box(payload), None, None, None
        except (ValueError, TypeError) as e:
            raise HTTPException(422, str(e) or "Send the box as [west, south, east, north].")
    weights = search_weights() if SEARCH_MODE == "local" else None
    now = time.time()
    active = [j for j in _searches().active() if now - j["created"] < STALE_S]
    if any(j["user"] == user["email"] for j in active):
        raise HTTPException(429, "You already have a search running. Wait for it to finish.")
    if len(active) >= MAX_QUEUE:
        raise HTTPException(503, "The search service is busy. Try again in a few minutes.")
    if len(_searches().since(user["email"], now - 86400)) >= DAILY_SEARCHES:
        raise HTTPException(429, f"Daily limit of {DAILY_SEARCHES} searches reached. Try again tomorrow.")
    job_id = uuid.uuid4().hex[:12]
    ahead = len(active) if SEARCH_MODE == "local" else 0
    row = {"job_id": job_id, "status": "queued", "bbox": list(box), "progress": 0.0, "mode": SEARCH_MODE,
           "stage": "Waiting for the previous search to finish" if ahead else "Starting",
           "queue_position": ahead, "user": user["email"], "created": now}
    if SEARCH_MODE == "worker":
        row.update(period=[str(start), str(end)], status="running", units=units, estimate=plan.summary(p))
        try:
            row["call_id"] = worker.spawn(box, start, end, job_id)
        except Exception as e:
            raise HTTPException(503, _service_error(e))
        _searches().add(row)
    else:
        _searches().add(row)
        _executor.submit(_run_search, job_id, box, weights)
    return {"job_id": job_id, "queue_position": ahead,
            **{k: row[k] for k in ("period", "estimate") if k in row}}


def _worker_status(job):
    """Poll the Modal worker: progress while running, the period result when done."""
    try:
        st = worker.status(job["job_id"])
        res = worker.result(job["call_id"]) if st["status"] != "error" else None
    except Exception as e:                           # user errors raised in the worker carry a sentence
        msg = str(e) if type(e).__name__ in ("ValueError", "LookupError") else \
            f"The search failed ({type(e).__name__}). Try again in a minute."
        _set(job["job_id"], status="error", error=msg)
        return {"job_id": job["job_id"], "status": "error", "error": msg}
    if st["status"] == "error":
        _set(job["job_id"], status="error", error=st["error"])
        return {"job_id": job["job_id"], "status": "error", "error": st["error"]}
    if res is not None:
        _set(job["job_id"], status="done", progress=1.0)
        return {"job_id": job["job_id"], "status": "done", "progress": 1.0, "stage": "Done",
                "period": job.get("period"), "result": res}
    n, u = st["passes"], st.get("units") or 0
    stage = (f"Searching {n} satellite pass{'es' if n != 1 else ''}" + (f" in {u} pieces" if u > n else "")
             if n else "Finding satellite passes")
    return {"job_id": job["job_id"], "status": "running", "progress": st["progress"], "stage": stage,
            "stages": st["stages"], "passes": n, "passes_found": st["passes_found"], "period": job.get("period"),
            "estimate": job.get("estimate")}


@app.get("/api/search/{job_id}")
def search_status(job_id: str, user: dict = Depends(current_user)):
    job = _searches().get(job_id)
    if not job or job["user"] != user["email"]:
        raise HTTPException(404, "No such search. It may have expired after a restart.")
    if job.get("mode") == "worker" and job["status"] == "running":
        return _worker_status(job)
    return {k: v for k, v in job.items() if k not in ("user", "call_id")}


# ── Live context: AIS positions (aisstream.io) and sanctions news ─────────────
from webapp.backend import feeds


@app.on_event("startup")
async def start_live_ais():
    from src import config  # noqa: F401  loads .env when running locally
    key = os.getenv("AISSTREAM_API_KEY")
    if key:
        asyncio.get_running_loop().create_task(feeds.run_aisstream(key))
    if os.getenv("REGIONAL_AIS", "1") != "0":    # Gulf coverage aisstream lacks; off in tests
        asyncio.get_running_loop().create_task(feeds.run_regional())
        asyncio.get_running_loop().create_task(feeds.run_openwaters())


@app.on_event("shutdown")
def save_live_ais():
    if feeds.state["configured"]:
        feeds.save_statics()


@app.get("/api/live")
def live(bbox: str = None, _user: dict = Depends(current_user)):
    """Newest AIS position per ship, optionally inside bbox=west,south,east,north."""
    box = None
    if bbox:
        try:
            box = [float(v) for v in bbox.split(",")]
            assert len(box) == 4
        except (ValueError, AssertionError):
            raise HTTPException(422, "Send bbox as west,south,east,north.")
    vessels, total = feeds.live_vessels(box)
    return {"source": "aisstream.io", "regional": feeds.regional_state, "openwaters": feeds.openwaters_state,
            **{k: feeds.state.get(k) for k in ("configured", "connected", "error", "messages", "reconnects")},
            "vesselapi": {"configured": feeds.vesselapi_configured(), "remaining": feeds.vesselapi_state["remaining"],
                          "max_deg": feeds.VESSELAPI_MAX_DEG},
            "in_view": total, "vessels": vessels}


@app.get("/api/live/search")
def live_search(q: str, _user: dict = Depends(current_user)):
    """Find a ship anywhere by name or MMSI, not only in the current view."""
    return {"ships": feeds.search_ships(q)}


_va_clicks = {}                                     # user -> recent fill times
VESSELAPI_PER_USER_DAY = 5


@app.post("/api/live/vesselapi")
def live_vesselapi(payload: dict, user: dict = Depends(current_user)):
    """Fill the current view with VesselAPI positions (free plan: 150 requests a month)."""
    try:
        box = [float(v) for v in payload.get("bbox") or []]
        assert len(box) == 4 and box[0] < box[2] and box[1] < box[3]
    except (ValueError, TypeError, AssertionError):
        raise HTTPException(422, "Send bbox as [west, south, east, north].")
    now = time.time()
    recent = [t for t in _va_clicks.get(user["email"], []) if now - t < 86400]
    if len(recent) >= VESSELAPI_PER_USER_DAY:
        raise HTTPException(429, f"You can fill a view {VESSELAPI_PER_USER_DAY} times a day; the shared monthly "
                                 "VesselAPI quota is small.")
    try:
        out = feeds.vesselapi_fill(box, now)
    except ValueError as e:
        raise HTTPException(422, str(e))
    _va_clicks[user["email"]] = recent + [now]
    return out


@app.get("/api/live/{mmsi}")
def live_vessel(mmsi: str, _user: dict = Depends(current_user)):
    """One ship: position plus type, IMO, call sign, size and destination when broadcast."""
    v = feeds.vessel(mmsi)
    if not v:
        raise HTTPException(404, "No recent AIS from this ship.")
    return v


@app.get("/api/live/{mmsi}/extra")
def live_vessel_extra(mmsi: str, _user: dict = Depends(current_user)):
    """The slow lookups behind a ship card: GFW identity when AIS static data is missing,
    and a freely licensed photo (Wikimedia Commons, by IMO)."""
    v = feeds.vessel(mmsi)
    if not v:
        raise HTTPException(404, "No recent AIS from this ship.")
    ident = None if (v.get("type") and v.get("imo")) else feeds.gfw_identity(mmsi)
    imo = v.get("imo") or (ident or {}).get("imo")
    track = []
    if not str(mmsi).startswith("hn:"):
        try:                                     # 48 h from Open Waters beats our since-restart track
            from src import openwaters
            track = openwaters.track(mmsi)
        except Exception:
            track = []
    return {"identity": ident, "photo": feeds.photo(imo), "track": track,
            "particulars": None if str(mmsi).startswith("hn:") else feeds.particulars(mmsi)}


@app.get("/api/gfw/layers")
def gfw_layers(bbox: str, _user: dict = Depends(current_user)):
    """GFW satellite AIS and radar detections for the view, a few days delayed (context, not live)."""
    try:
        box = [float(v) for v in bbox.split(",")]
        assert len(box) == 4
    except (ValueError, AssertionError):
        raise HTTPException(422, "Send bbox as west,south,east,north.")
    try:
        return feeds.gfw_layers(box)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(503, f"Global Fishing Watch did not answer ({type(e).__name__}). Try again shortly.")


@app.get("/api/strait/crossings")
def strait_crossings(hours: int = 48, _user: dict = Depends(current_user)):
    """Strait of Hormuz crossings with how long each ship went unobserved while crossing."""
    try:
        return feeds.strait_crossings(hours)
    except Exception as e:
        raise HTTPException(503, f"The crossings feed did not answer ({type(e).__name__}). Try again shortly.")


@app.get("/api/news")
def news(region: str = "all"):
    """Recent ship-to-ship transfer and sanctions stories (Google News RSS, cached 15 min)."""
    out = feeds.news(region)
    # links come from an outside feed; a "javascript:" link would run in our page
    out["items"] = [i for i in out.get("items", []) if str(i.get("link") or "").startswith(("https://", "http://"))]
    return out


if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

if DIST.exists() and (DIST / "index.html").exists():
    @app.get("/{full_path:path}")
    def serve_dist(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        # resolve() and the containment check stop "/..%2F..%2F.env" walking out of dist/
        file_path = (DIST / full_path).resolve()
        if file_path.is_file() and file_path.is_relative_to(DIST.resolve()):
            return FileResponse(file_path)
        return FileResponse(DIST / "index.html")
elif FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
