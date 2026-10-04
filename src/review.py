"""Blind review sheet for choosing the vessel cut-off (test plan T3).

Dev scenes only: the 26 Fujairah passes already used in RESULTS.md §7. Detector at
0.10, same cleaning as the live search, vessel class only. 25 random detections
per score band, shuffled into one order with opaque IDs. Reviewers see the ID and
two chips (640 m and 3.2 km across, a FIXED log stretch identical for every chip,
so brightness cannot leak the score) and nothing else. The key (ID -> score, band,
scene, position) is written to a separate folder reviewers never open.

    modal run modal_review.py          # detections + chips on Modal, sheet written here
"""
import csv
import html
import io
import random
from pathlib import Path

import numpy as np
import pandas as pd

BANDS = [(0.10, 0.15), (0.15, 0.25), (0.25, 0.40), (0.40, 1.01)]
PER_BAND = 25
SEED = 20261004
SMALL, WIDE = 32, 160                 # half-widths in 10 m pixels: 640 m and 3.2 km chips
LOG_LO, LOG_HI = np.log10(20), np.log10(2000)   # fixed DN stretch for every chip
REVIEWERS = ("A", "B", "C")           # two labellers + one to settle disagreements


def band_of(score):
    for lo, hi in BANDS:
        if lo <= score < hi:
            return f"{lo:.2f}-{min(hi, 1.0):.2f}"
    return None


def detections(item, box, weights, scene_dir):
    """Cleaned vessel detections at >= 0.10 for one pass; the scene GeoTIFF stays in scene_dir."""
    from src import fetch_s1
    from src.filters import clean_detections
    from src.hunt import dedupe
    from src.run_pipeline import detect
    tif = fetch_s1.fetch(item, box=box, out_dir=Path(scene_dir))
    det = detect(tif, weights, conf=BANDS[0][0])
    det = det[det.cls == "vessel"] if len(det) else det
    det = dedupe(clean_detections(det)) if len(det) else det
    if not len(det):
        return []
    return [{"scene": item["id"], "tif": str(tif), "x": float(r.x), "y": float(r.y), "lat": float(r.lat),
             "lon": float(r.lon), "score": float(r.conf), "length_m": float(r.length_m)} for _, r in det.iterrows()]


def sample(dets, per_band=PER_BAND, seed=SEED):
    """per_band random detections from each score band (all of a band if it has fewer)."""
    d = pd.DataFrame(dets)
    d["band"] = d.score.map(band_of)
    rng = random.Random(seed)
    picks = []
    for lo, hi in BANDS:
        b = d[d.band == band_of(lo)]
        idx = list(b.index)
        rng.shuffle(idx)
        picks.append(b.loc[sorted(idx[:per_band])])
    return pd.concat(picks).reset_index(drop=True)


def _png(img):
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


def chips(tif, x, y):
    """(small_png, wide_png): fixed log stretch; red ticks around the detection, centre left clear."""
    import rasterio
    out = []
    with rasterio.open(tif) as s:
        r, c = s.index(x, y)
        for half in (SMALL, WIDE):
            a = s.read(1, window=rasterio.windows.Window(c - half, r - half, 2 * half, 2 * half),
                       boundless=True, fill_value=0).astype(float)
            v = np.clip((np.log10(np.maximum(a, 1)) - LOG_LO) / (LOG_HI - LOG_LO), 0, 1)
            g = (v * 255).astype("uint8")
            rgb = np.stack([g, g, g], -1)
            gap, arm = max(6, half // 5), max(3, half // 8)   # four ticks around the object, centre left clear
            for d in (-1, 1):
                rgb[half, half + d * gap:half + d * (gap + arm):d] = (255, 40, 40)
                rgb[half + d * gap:half + d * (gap + arm):d, half] = (255, 40, 40)
            out.append(_png(rgb))
    return out


def assign_ids(n, seed=SEED):
    """Shuffled order and opaque IDs (R001..), independent of band or scene."""
    order = list(range(n))
    random.Random(seed + 1).shuffle(order)
    return {row: f"R{k + 1:03d}" for k, row in enumerate(order)}


def write_sheet(picked, chip_pngs, out_dir):
    """Reviewer copies (HTML to look, CSV to label) and the separate key. No results computed."""
    out = Path(out_dir)
    (out / "chips").mkdir(parents=True, exist_ok=True)
    (out / "KEY_reviewers_do_not_open").mkdir(exist_ok=True)
    ids = assign_ids(len(picked))
    rows = sorted(((ids[i], i) for i in range(len(picked))), key=lambda t: t[0])
    for rid, i in rows:
        small, wide = chip_pngs[i]
        (out / "chips" / f"{rid}_small.png").write_bytes(small)
        (out / "chips" / f"{rid}_wide.png").write_bytes(wide)
    with open(out / "KEY_reviewers_do_not_open" / "key.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "score", "band", "scene_id", "lat", "lon", "length_m"])
        for rid, i in rows:
            p = picked.iloc[i]
            w.writerow([rid, round(p.score, 4), p.band, p.scene, round(p.lat, 6), round(p.lon, 6), round(p.length_m)])
    cards = "\n".join(
        f'<div class="c"><b>{rid}</b><br><img src="chips/{rid}_small.png" width="192" height="192" alt="{rid} close">'
        f'<img src="chips/{rid}_wide.png" width="192" height="192" alt="{rid} context"></div>' for rid, _ in rows)
    for who in REVIEWERS:
        with open(out / f"labels_reviewer_{who}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "reviewer", "label", "notes"])
            for rid, _ in rows:
                w.writerow([rid, who, "", ""])
        (out / f"sheet_reviewer_{who}.html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>Ship review sheet, reviewer {who}</title>
<style>body{{font:14px system-ui;margin:16px;background:#fff;color:#111}}
.c{{display:inline-block;margin:6px;padding:6px;border:1px solid #ccc;text-align:center}}
img{{image-rendering:pixelated;margin:2px;background:#000}}</style>
<h1>Ship review, reviewer {html.escape(who)}</h1>
<p>Each card: ID, a close chip (640 m across) and a context chip (3.2 km across) of Sentinel-1 radar.
The object to judge is in the centre, between the four red ticks. Label it in <code>labels_reviewer_{who}.csv</code> as
<b>Ship</b>, <b>Not a ship</b> (wave, land edge, infrastructure, streak, strip edge) or <b>Unsure</b>.
Work alone; do not compare with other reviewers until you have finished.</p>
{cards}
""")
    return len(rows)
