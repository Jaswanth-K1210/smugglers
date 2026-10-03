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
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
EVENTS = Path(os.getenv("EVENTS_PATH", ROOT / "outputs" / "events.geojson"))
WEIGHTS = Path(os.getenv("WEIGHTS_PATH", ROOT / "models" / "darksts" / "weights" / "best.pt"))
FRONTEND = ROOT / "webapp" / "frontend"
DIST = FRONTEND / "dist"
USERS_DB = Path(os.getenv("USERS_DB", ROOT / "data" / "users.db"))
# ponytail: without AUTH_SECRET every restart signs everyone out; set it in deployment.
AUTH_SECRET = (os.getenv("AUTH_SECRET") or secrets.token_hex(32)).encode()
TOKEN_TTL = 7 * 24 * 3600

app = FastAPI(title="Dark STS Detection", version="1.0",
              description="Open-data Sentinel-1 + AIS ship-to-ship transfer characterisation")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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


def _db():
    USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(USERS_DB)
    db.execute("CREATE TABLE IF NOT EXISTS users "
               "(email TEXT PRIMARY KEY, name TEXT, salt BLOB, hash BLOB)")
    return db


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def _token(email: str) -> str:
    body = base64.urlsafe_b64encode(f"{email}|{int(time.time()) + TOKEN_TTL}".encode()).decode()
    sig = hmac.new(AUTH_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _user(email: str):
    with _db() as db:
        row = db.execute("SELECT name, email FROM users WHERE email = ?", (email,)).fetchone()
    return {"name": row[0], "email": row[1]} if row else None


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


def _session(email: str):
    return {"token": _token(email), "user": _user(email)}


@app.post("/api/auth/register")
def auth_register(payload: dict):
    email = str(payload.get("email", "")).strip().lower()
    name = str(payload.get("name", "")).strip()
    password = str(payload.get("password", ""))
    if "@" not in email or not name:
        raise HTTPException(422, "Enter your name and a valid email address.")
    if len(password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters.")
    salt = secrets.token_bytes(16)
    try:
        with _db() as db:
            db.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (email, name, salt, _hash(password, salt)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    return _session(email)


@app.post("/api/auth/login")
def auth_login(payload: dict):
    email = str(payload.get("email", "")).strip().lower()
    with _db() as db:
        row = db.execute("SELECT salt, hash FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not hmac.compare_digest(_hash(str(payload.get("password", "")), row[0]), row[1]):
        raise HTTPException(401, "Email or password is incorrect.")
    return _session(email)


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(current_user)):
    return {"user": user}


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
        "live_detection": has_weights,
        "liveDetectionAvailable": has_weights,
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


@app.post("/api/detect")
async def detect(file: UploadFile = File(...), _user: dict = Depends(current_user)):
    """Run the detector on one uploaded tile, on CPU."""
    if not WEIGHTS.exists():
        raise HTTPException(503, "no trained weights in this deployment; "
                                 "precomputed results remain available at /api/events")
    import io
    import time
    import numpy as np
    from PIL import Image
    from ultralytics import YOLO

    t0 = time.time()
    img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    res = YOLO(str(WEIGHTS)).predict(np.array(img), conf=0.25, verbose=False)[0]
    names = {0: "vessel", 1: "sts"}
    detections = [{
        "cls": names.get(int(b.cls[0]), str(int(b.cls[0]))),
        "conf": round(float(b.conf[0]), 3),
        "box": [round(v, 1) for v in b.xyxy[0].tolist()],
    } for b in res.boxes]
    vessels_count = sum(1 for d in detections if d["cls"] == "vessel")
    sts_count = sum(1 for d in detections if d["cls"] == "sts")
    return {
        "detections": detections,
        "image_size": list(img.size),
        "vessels_count": vessels_count,
        "sts_count": sts_count,
        "processing_time": round(time.time() - t0, 3),
    }


if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

if DIST.exists() and (DIST / "index.html").exists():
    @app.get("/{full_path:path}")
    def serve_dist(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        file_path = DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(DIST / "index.html")
elif FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
