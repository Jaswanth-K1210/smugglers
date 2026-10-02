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
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
EVENTS = Path(os.getenv("EVENTS_PATH", ROOT / "outputs" / "events.geojson"))
WEIGHTS = Path(os.getenv("WEIGHTS_PATH", ROOT / "models" / "darksts" / "weights" / "best.pt"))
FRONTEND = ROOT / "webapp" / "frontend"

app = FastAPI(title="Dark STS Detection", version="1.0",
              description="Open-data Sentinel-1 + AIS ship-to-ship transfer characterisation")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_cache = {"mtime": None, "data": None}


def load_events():
    """Read the GeoJSON, re-reading only when the file changes."""
    if not EVENTS.exists():
        return {"type": "FeatureCollection", "features": []}
    m = EVENTS.stat().st_mtime
    if _cache["mtime"] != m:
        _cache.update(mtime=m, data=json.loads(EVENTS.read_text()))
    return _cache["data"]


@app.get("/api/health")
def health():
    ev = load_events()
    return {"status": "ok", "events": len(ev["features"]),
            "events_file": EVENTS.name if EVENTS.exists() else None,
            "live_detection": WEIGHTS.exists()}


@app.get("/api/events")
def events(category: str = None, min_suspicion: float = 0.0, limit: int = 1000):
    """Precomputed candidates, optionally filtered."""
    feats = load_events()["features"]
    if category:
        feats = [f for f in feats if f["properties"].get("category") == category]
    if min_suspicion:
        feats = [f for f in feats
                 if (f["properties"].get("suspicion") or 0) >= min_suspicion]
    feats = sorted(feats, key=lambda f: -(f["properties"].get("suspicion") or 0))[:limit]
    return {"type": "FeatureCollection", "features": feats}


@app.get("/api/events/{index}")
def event(index: int):
    feats = load_events()["features"]
    if not 0 <= index < len(feats):
        raise HTTPException(404, f"no event {index}; {len(feats)} available")
    return feats[index]


@app.get("/api/summary")
def summary():
    """Counts by category and size class, for the dashboard header."""
    feats = load_events()["features"]
    cat, size = {}, {}
    for f in feats:
        p = f["properties"]
        cat[p.get("category", "unknown")] = cat.get(p.get("category", "unknown"), 0) + 1
        size[p.get("size_class", "unknown")] = size.get(p.get("size_class", "unknown"), 0) + 1
    return {"total": len(feats), "by_category": cat, "by_size_class": size,
            "note": "Categories describe AIS evidence, not intent. AIS_UNMATCHED is a "
                    "candidate, not a finding of concealment."}


@app.post("/api/detect")
async def detect(file: UploadFile = File(...)):
    """Run the detector on one uploaded tile, on CPU."""
    if not WEIGHTS.exists():
        raise HTTPException(503, "no trained weights in this deployment; "
                                 "precomputed results remain available at /api/events")
    import io

    import numpy as np
    from PIL import Image
    from ultralytics import YOLO

    img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    res = YOLO(str(WEIGHTS)).predict(np.array(img), conf=0.25, verbose=False)[0]
    names = {0: "vessel", 1: "sts"}
    return {"detections": [{
        "cls": names.get(int(b.cls[0]), str(int(b.cls[0]))),
        "conf": round(float(b.conf[0]), 3),
        "box": [round(v, 1) for v in b.xyxy[0].tolist()],
    } for b in res.boxes], "image_size": img.size}


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
