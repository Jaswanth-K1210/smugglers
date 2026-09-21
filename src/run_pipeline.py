"""End-to-end: Sentinel-1 scenes in, ranked STS candidates out.

Chains Phases 2 through 7. Every stage is importable on its own; this module
only wires them together and writes the artifacts the dashboard and the web API
read.

Detection uses the trained detector when weights exist. When they do not, it
falls back to the same AIS-derived labelling used for training, and says so
loudly — that path is a pipeline smoke test, not a detection result, because the
"detections" are AIS positions and characterising them against AIS is circular.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform as warp_transform

from src import ais, autolabel, dark_sts, enrich_gfw, fetch_s1, score, validate_gfw
from src.config import DATA, ROOT, bbox as default_bbox
from src.filters import clean_detections

OUT = ROOT / "outputs"
WEIGHTS = ROOT / "models" / "darksts" / "weights" / "best.pt"


def detect(tif: Path, weights: Path = WEIGHTS, conf: float = 0.25, size: int = 1024):
    """Run the detector over a scene. Returns detections in world coordinates."""
    from ultralytics import YOLO

    model = YOLO(str(weights))
    rows = []
    with rasterio.open(tif) as src:
        for top in range(0, src.height - size + 1, size):
            for left in range(0, src.width - size + 1, size):
                win = rasterio.windows.Window(left, top, size, size)
                img = src.read(1, window=win)
                if (img > 0).mean() < 0.9:
                    continue
                v = img[img > 0]
                lo, hi = np.percentile(v, [1, 99])
                chip = np.clip((img.astype("float32") - lo) / max(hi - lo, 1) * 255, 0, 255)
                rgb = np.repeat(chip.astype("uint8")[:, :, None], 3, axis=2)

                for b in model.predict(rgb, conf=conf, verbose=False)[0].boxes:
                    x0, y0, x1, y1 = b.xyxy[0].tolist()
                    cls = autolabel.CLASSES_INV[int(b.cls[0])]
                    cx, cy = left + (x0 + x1) / 2, top + (y0 + y1) / 2
                    X, Y = src.transform * (cx, cy)
                    lon, lat = warp_transform(src.crs, "EPSG:4326", [X], [Y])
                    rows.append({
                        "cls": cls, "conf": float(b.conf[0]),
                        "lat": lat[0], "lon": lon[0], "x": X, "y": Y,
                        "length_m": max(x1 - x0, y1 - y0) * src.res[0],
                        "scene": Path(tif).stem, "time": autolabel.scene_time(tif),
                    })
    return pd.DataFrame(rows)


def detect_from_ais(tif: Path, box=None):
    """Fallback when no weights exist. NOT a detection result — see module docstring."""
    print("!! no trained weights: standing in AIS-derived labels for detections.\n"
          "!! Characterising these against AIS is circular. Smoke test only.")
    ev_path = DATA / "labels" / "sts_events_7d_at_sea.csv"
    events = pd.read_csv(ev_path, parse_dates=["start", "end"]) if ev_path.exists() else None
    if events is None:
        print("!! no Phase 1 event file; sts boxes cannot be formed. Run src.ais_sts first.")
    boxes = autolabel.label_scene(tif, events, box=box)
    if boxes.empty:
        return pd.DataFrame()
    with rasterio.open(tif) as src:
        cx = (boxes.c0 + boxes.c1) / 2
        cy = (boxes.r0 + boxes.r1) / 2
        X, Y = rasterio.transform.xy(src.transform, cy.tolist(), cx.tolist())
        lon, lat = warp_transform(src.crs, "EPSG:4326", list(X), list(Y))
        res = src.res[0]
    return pd.DataFrame({
        "cls": boxes.cls, "conf": 1.0, "lat": lat, "lon": lon, "x": X, "y": Y,
        "length_m": (boxes.c1 - boxes.c0 + 1).clip(lower=(boxes.r1 - boxes.r0 + 1)) * res,
        "scene": Path(tif).stem, "time": autolabel.scene_time(tif),
        "synthetic": True,
    })


def run(start: str, end: str, box=None, max_scenes: int = 3, weights: Path = WEIGHTS,
        zones_path: Path = None, conf: float = 0.25):
    """Phases 2-7 over a date range. Writes outputs/events.geojson."""
    box = box or default_bbox()
    OUT.mkdir(parents=True, exist_ok=True)

    items = [i for i in fetch_s1.search(start, end, box=box) if fetch_s1.overlap(i, box) >= 0.05]
    items.sort(key=lambda i: fetch_s1.overlap(i, box), reverse=True)
    items = items[:max_scenes]
    print(f"{len(items)} scene(s) selected")

    have_weights = Path(weights).exists()
    frames = []
    for n, it in enumerate(items, 1):
        tif = fetch_s1.fetch(it, box=box)
        d = detect(tif, weights, conf) if have_weights else detect_from_ais(tif, box=box)
        print(f"[{n}/{len(items)}] {Path(tif).stem[:44]} -> {len(d)} raw detections")
        frames.append(d)

    raw = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(
        len(f) for f in frames) else pd.DataFrame()
    if raw.empty:
        print("no detections")
        return raw

    # Phase 5
    clean = clean_detections(raw)
    print(f"after filters (length, land, infrastructure): {len(clean)} of {len(raw)}")
    sts = clean[clean.cls == "sts"] if "cls" in clean else clean
    if sts.empty:
        print("no STS candidates after filtering")
        sts = clean.head(0)

    # Phase 6
    days = sorted({pd.Timestamp(t).strftime("%Y-%m-%d") for t in sts.time}) if len(sts) else []
    ais_all = pd.concat([ais.load(d, box=box) for d in days], ignore_index=True) if days \
        else pd.DataFrame()
    events = dark_sts.characterise(sts, ais_all)
    if len(events):
        print("categories:", events.category.value_counts().to_dict())
        events = validate_gfw.cross_check(events, start, end, box=box)
        events = enrich_gfw.enrich(events)

    # Phase 7
    zones = json.loads(Path(zones_path).read_text()) if zones_path and Path(zones_path).exists() \
        else None
    if zones is None:
        print("no sanctioned-zone GeoJSON supplied; that term scores 0 for every event")
    lanes = score.lanes_from_ais(ais_all)
    if len(events):
        if "duration_min" not in events:
            events["duration_min"] = np.nan
        events = score.score(events, zones=zones, lanes=lanes)

    events.to_csv(OUT / "events.csv", index=False)
    (OUT / "events.geojson").write_text(json.dumps(to_geojson(events), default=str))
    print(f"\nwrote {OUT/'events.csv'} and {OUT/'events.geojson'} ({len(events)} events)")
    return events


def to_geojson(events):
    feats = []
    for _, e in events.iterrows():
        props = {k: (None if isinstance(v, float) and pd.isna(v) else v)
                 for k, v in e.items() if k not in ("lat", "lon")}
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [e.lon, e.lat]},
                      "properties": props})
    return {"type": "FeatureCollection", "features": feats}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--max-scenes", type=int, default=3)
    ap.add_argument("--weights", default=str(WEIGHTS))
    ap.add_argument("--zones", default=None, help="sanctioned-zone GeoJSON")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    ev = run(a.start, a.end, max_scenes=a.max_scenes, weights=Path(a.weights),
             zones_path=a.zones, conf=a.conf)
    if len(ev):
        cols = [c for c in ("time", "category", "n_identities", "size_class", "suspicion")
                if c in ev.columns]
        print(ev[cols].head(15).to_string(index=False))
