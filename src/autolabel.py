"""Generate YOLO training labels by matching AIS to Sentinel-1 scenes.

No manual annotation and no xView3. For each scene we know the acquisition time
to the second, so we know where every AIS-broadcasting vessel was standing when
the radar looked. Put a box on the bright blob at that spot and the label makes
itself.

Two classes, as specified:
  0 vessel — one AIS identity, one bright target
  1 sts    — a Phase 1 ship-to-ship event, ONE box around the rafted pair.
             Never inferred later from two nearby `vessel` detections.

The parts that decide whether this works:

*Interpolation, not nearest ping.* A vessel at 12 knots covers 185 m in 30 s —
nearly 19 pixels at 10 m. Taking the closest AIS message inside the window
would smear labels by tens of pixels, so each track is interpolated to the exact
overpass second.

*Adaptive thresholding, not a fixed cut.* Sea clutter varies with wind and
incidence angle across a scene. The threshold is computed from the local
background around each candidate, so it follows the sea state. Ships sit 10-30 dB
above water, so this is enough and SAM would be overkill.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform as warp_transform
from scipy import ndimage

from src import ais
from src.config import DATA
from src.filters import at_sea

TILES = DATA / "tiles"
LABELS = DATA / "labels"
CLASSES = {"vessel": 0, "sts": 1}
CLASSES_INV = {v: k for k, v in CLASSES.items()}

# A vessel is at most ~400 m; search a window comfortably larger than that so a
# slightly stale AIS fix still lands inside it, but small enough that the local
# background is genuinely local.
SEARCH_M = 600
MIN_LEN_M, MAX_LEN_M = 30, 400

# Threshold height in MADs above the local median. Calibrated, not guessed:
# swept against 114 AIS-matched vessels of known length in the Skagen scene,
# box length / AIS length came out 2.05x at k=3, 1.38x at k=8, 1.14x at k=20
# and 1.07x at k=30. SAR sea clutter has a long tail, so a 3-sigma cut sits
# *inside* the clutter distribution and the blob sprawls across speckle.
# 30 leaves a slight overshoot on purpose — clipping a bow is worse than a few
# extra metres of sea. Re-run `python -m src.autolabel --calibrate <scene>` if
# the sensor, polarisation or sea state changes.
BLOB_K = 30.0


def scene_time(path) -> pd.Timestamp:
    """Acquisition start time from a Sentinel-1 product name."""
    m = re.search(r"_(\d{8}T\d{6})_(\d{8}T\d{6})_", Path(path).name)
    if not m:
        raise ValueError(f"cannot read acquisition time from {Path(path).name}")
    start, end = (pd.Timestamp(t) for t in m.groups())
    return start + (end - start) / 2  # mid-swath is closer than either edge


def ais_at(scene_t: pd.Timestamp, window_min: int = 30, box=None,
           min_km: float = 1.0) -> pd.DataFrame:
    """Every AIS identity interpolated to the exact acquisition instant.

    Only vessels with a fix on both sides of the instant are kept — extrapolating
    past the last known position invents a location the radar never saw.

    `min_km` drops vessels without that much clearance from land. Without it the
    labels are dominated by Frederikshavn and Hirtshals, where berthed ships lie
    hull to hull: the blob finder merges neighbours into one component and emits
    boxes two or three times the vessel's true length.
    """
    day = ais.load(scene_t.strftime("%Y-%m-%d"), box=box)
    lo, hi = scene_t - pd.Timedelta(minutes=window_min), scene_t + pd.Timedelta(minutes=window_min)
    near = day[day.timestamp.between(lo, hi)].sort_values("timestamp")

    rows = []
    for mmsi, g in near.groupby("mmsi"):
        before, after = g[g.timestamp <= scene_t], g[g.timestamp >= scene_t]
        if before.empty or after.empty:
            continue
        b, a = before.iloc[-1], after.iloc[0]
        span = (a.timestamp - b.timestamp).total_seconds()
        f = 0.0 if span == 0 else (scene_t - b.timestamp).total_seconds() / span
        rows.append({
            "mmsi": mmsi,
            "lat": b.lat + f * (a.lat - b.lat),
            "lon": b.lon + f * (a.lon - b.lon),
            "sog": b.sog, "name": b["name"], "ship_type": b.ship_type, "length": b.length,
            "gap_s": span,
        })
    fixes = pd.DataFrame(rows)
    if min_km and len(fixes):
        fixes = fixes[at_sea(fixes.lat.to_numpy(), fixes.lon.to_numpy(), min_km)]
    return fixes.reset_index(drop=True)


def _blob_at(img, row, col, half, k=BLOB_K):
    """Find the bright target nearest (row, col). Returns a pixel bbox or None.

    Threshold is the local median plus `k` MADs, measured on the window itself,
    so it follows sea state instead of assuming it.
    """
    r0, c0 = max(0, row - half), max(0, col - half)
    win = img[r0:row + half, c0:col + half]
    if win.size == 0:
        return None
    water = win[win > 0]
    if water.size < 50:
        return None
    # Median and MAD rather than mean and std: a big ship in the window would
    # drag a mean threshold up above itself.
    med = np.median(water)
    mad = np.median(np.abs(water - med)) * 1.4826
    thresh = med + k * max(mad, 1.0)

    lab, n = ndimage.label(win > thresh)
    if n == 0:
        return None
    # Nearest component to the predicted position, not the brightest: the
    # brightest thing in a window may be a different ship entirely.
    cy, cx = row - r0, col - c0
    cents = ndimage.center_of_mass(win, lab, range(1, n + 1))
    best = 1 + int(np.argmin([(y - cy) ** 2 + (x - cx) ** 2 for y, x in cents]))
    ys, xs = np.where(lab == best)
    return r0 + ys.min(), c0 + xs.min(), r0 + ys.max(), c0 + xs.max()


def label_scene(tif: Path, sts_events: pd.DataFrame = None, window_min: int = 30,
                sts_window_min: int = 60, box=None, min_km: float = 1.0):
    """Boxes for one scene, in pixel coordinates. Returns a DataFrame."""
    t = scene_time(tif)
    fixes = ais_at(t, window_min, box=box, min_km=min_km)
    if fixes.empty:
        print(f"{Path(tif).name}: no AIS bracketing {t}")
        return pd.DataFrame()

    with rasterio.open(tif) as src:
        img = src.read(1)
        x, y = warp_transform("EPSG:4326", src.crs, fixes.lon.tolist(), fixes.lat.tolist())
        rows, cols = rasterio.transform.rowcol(src.transform, x, y)
        half = int(SEARCH_M / src.res[0])
        res = src.res[0]
        h, w = img.shape

        out = []
        for i, (r, c) in enumerate(zip(np.atleast_1d(rows), np.atleast_1d(cols))):
            if not (0 <= r < h and 0 <= c < w):
                continue
            bb = _blob_at(img, int(r), int(c), half)
            if bb is None:
                continue
            length_px = max(bb[2] - bb[0], bb[3] - bb[1]) + 1
            if not (MIN_LEN_M <= length_px * res <= MAX_LEN_M):
                continue
            f = fixes.iloc[i]
            out.append({"cls": "vessel", "mmsi": f.mmsi, "name": f["name"],
                        "ship_type": f.ship_type, "ais_length": f.length,
                        "r0": bb[0], "c0": bb[1], "r1": bb[2], "c1": bb[3],
                        "box_len_m": round(length_px * res, 1),
                        "pred_r": int(r), "pred_c": int(c)})
        boxes = pd.DataFrame(out)

        # STS: one box spanning both vessels of a Phase 1 event, when that event
        # was in progress at the acquisition instant.
        if sts_events is not None and len(sts_events) and len(boxes):
            live = sts_events[(sts_events.start <= t + pd.Timedelta(minutes=sts_window_min)) &
                              (sts_events.end >= t - pd.Timedelta(minutes=sts_window_min))]
            by_mmsi = boxes.set_index("mmsi")
            sts_rows = []
            for _, e in live.iterrows():
                if e.mmsi_a not in by_mmsi.index or e.mmsi_b not in by_mmsi.index:
                    continue
                a, b = by_mmsi.loc[e.mmsi_a], by_mmsi.loc[e.mmsi_b]
                a = a.iloc[0] if isinstance(a, pd.DataFrame) else a
                b = b.iloc[0] if isinstance(b, pd.DataFrame) else b
                sts_rows.append({
                    "cls": "sts", "mmsi": e.mmsi_a, "name": f"{e.name_a} + {e.name_b}",
                    "ship_type": f"{e.type_a}/{e.type_b}", "ais_length": np.nan,
                    "r0": min(a.r0, b.r0), "c0": min(a.c0, b.c0),
                    "r1": max(a.r1, b.r1), "c1": max(a.c1, b.c1),
                    "box_len_m": np.nan, "pred_r": np.nan, "pred_c": np.nan,
                })
            if sts_rows:
                boxes = pd.concat([boxes, pd.DataFrame(sts_rows)], ignore_index=True)

    boxes["scene"] = Path(tif).stem
    return boxes


def tile_scene(tif: Path, boxes: pd.DataFrame, size: int = 1024, out_dir: Path = None):
    """Cut the scene into tiles and write YOLO labels for the boxes inside each.

    Tiles with no box are dropped: an empty tile of open sea teaches nothing and
    would swamp the positives.
    """
    out_dir = out_dir or TILES
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "labels").mkdir(parents=True, exist_ok=True)
    stem = Path(tif).stem
    written = 0

    with rasterio.open(tif) as src:
        for top in range(0, src.height - size + 1, size):
            for left in range(0, src.width - size + 1, size):
                here = boxes[(boxes.r0 >= top) & (boxes.r1 < top + size) &
                             (boxes.c0 >= left) & (boxes.c1 < left + size)]
                if here.empty:
                    continue
                win = rasterio.windows.Window(left, top, size, size)
                img = src.read(1, window=win)
                if (img > 0).mean() < 0.9:          # mostly off-swath
                    continue

                name = f"{stem}_{top}_{left}"
                lo, hi = np.percentile(img[img > 0], [1, 99])
                png = np.clip((img.astype("float32") - lo) / max(hi - lo, 1) * 255, 0, 255)
                with rasterio.open(out_dir / "images" / f"{name}.png", "w", driver="PNG",
                                   height=size, width=size, count=1, dtype="uint8") as dst:
                    dst.write(png.astype("uint8"), 1)

                lines = []
                for _, b in here.iterrows():
                    xc = ((b.c0 + b.c1) / 2 - left) / size
                    yc = ((b.r0 + b.r1) / 2 - top) / size
                    bw = (b.c1 - b.c0 + 1) / size
                    bh = (b.r1 - b.r0 + 1) / size
                    lines.append(f"{CLASSES[b.cls]} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
                (out_dir / "labels" / f"{name}.txt").write_text("\n".join(lines) + "\n")
                written += 1
    return written


def preview_boxes(tif: Path, boxes: pd.DataFrame, out_png: Path = None, n: int = 20):
    """Chips around the first `n` boxes, drawn, for the eyeball check."""
    out_png = out_png or LABELS / f"{Path(tif).stem}_chips.png"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    half, cols = 60, 5
    rows = int(np.ceil(min(n, len(boxes)) / cols))
    sheet = np.zeros((rows * 2 * half, cols * 2 * half), dtype="uint8")

    with rasterio.open(tif) as src:
        for i, (_, b) in enumerate(boxes.head(n).iterrows()):
            cy, cx = (b.r0 + b.r1) // 2, (b.c0 + b.c1) // 2
            win = rasterio.windows.Window(cx - half, cy - half, 2 * half, 2 * half)
            chip = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
            v = chip[chip > 0]
            if v.size:
                lo, hi = np.percentile(v, [1, 99.5])
                chip = np.clip((chip - lo) / max(hi - lo, 1) * 255, 0, 255)
            # Draw the box edges so a miss is obvious.
            r0, c0 = int(b.r0 - cy + half), int(b.c0 - cx + half)
            r1, c1 = int(b.r1 - cy + half), int(b.c1 - cx + half)
            for rr in (r0, r1):
                if 0 <= rr < 2 * half:
                    chip[rr, max(0, c0):min(2 * half, c1 + 1)] = 255
            for cc in (c0, c1):
                if 0 <= cc < 2 * half:
                    chip[max(0, r0):min(2 * half, r1 + 1), cc] = 255
            gr, gc = divmod(i, cols)
            sheet[gr * 2 * half:(gr + 1) * 2 * half, gc * 2 * half:(gc + 1) * 2 * half] = chip

    with rasterio.open(out_png, "w", driver="PNG", height=sheet.shape[0],
                       width=sheet.shape[1], count=1, dtype="uint8") as dst:
        dst.write(sheet, 1)
    print(f"chips: {out_png}")
    return out_png


if __name__ == "__main__":
    tif = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(DATA.glob("sar_raw/*.tif"))[0]
    ev_path = LABELS / "sts_events_7d_at_sea.csv"
    events = pd.read_csv(ev_path, parse_dates=["start", "end"]) if ev_path.exists() else None

    print(f"scene {Path(tif).name}\nacquired {scene_time(tif)}")
    boxes = label_scene(tif, events)
    if boxes.empty:
        sys.exit("no labels generated")
    print(f"\n{len(boxes)} boxes: {boxes.cls.value_counts().to_dict()}")
    print(boxes[boxes.cls == "vessel"].nlargest(10, "box_len_m")[
        ["name", "ship_type", "ais_length", "box_len_m"]].to_string(index=False))
    boxes.to_csv(LABELS / f"{Path(tif).stem}_boxes.csv", index=False)
    preview_boxes(tif, boxes)
    print(f"tiles written: {tile_scene(tif, boxes)}")


def label_many(start: str, end: str, box=None, min_overlap: float = 0.05,
               max_scenes: int = None, tile_size: int = 1024):
    """Fetch, label and tile every Sentinel-1 scene over the AOI in a date range.

    This is the Colab entry point. AIS is the expensive part — one ~650 MB day
    per date — so scenes are grouped by date and each day is loaded once.
    """
    from src import fetch_s1

    items = [it for it in fetch_s1.search(start, end, box=box)
             if fetch_s1.overlap(it, box) >= min_overlap]
    items.sort(key=lambda it: fetch_s1.overlap(it, box), reverse=True)
    if max_scenes:
        items = items[:max_scenes]
    # Group by day so each AIS day is read once, not once per scene.
    items.sort(key=lambda it: it["properties"]["datetime"])
    print(f"{len(items)} scenes with >={min_overlap:.0%} AOI overlap, {start}..{end}")

    ev_path = LABELS / "sts_events_7d_at_sea.csv"
    events = pd.read_csv(ev_path, parse_dates=["start", "end"]) if ev_path.exists() else None

    summary, total_tiles = [], 0
    for n, it in enumerate(items, 1):
        try:
            tif = fetch_s1.fetch(it, box=box)
            boxes = label_scene(tif, events, box=box)
            if boxes.empty:
                print(f"[{n}/{len(items)}] {it['id'][:40]} — no labels")
                continue
            tiles = tile_scene(tif, boxes, size=tile_size)
            total_tiles += tiles
            counts = boxes.cls.value_counts().to_dict()
            summary.append({"scene": Path(tif).stem, "time": it["properties"]["datetime"],
                            "vessel": counts.get("vessel", 0), "sts": counts.get("sts", 0),
                            "tiles": tiles})
            print(f"[{n}/{len(items)}] {Path(tif).stem[:44]}  "
                  f"vessel={counts.get('vessel', 0):>3} sts={counts.get('sts', 0):>2} tiles={tiles}")
        except Exception as e:                         # one bad scene must not end the batch
            print(f"[{n}/{len(items)}] {it['id'][:40]} FAILED {type(e).__name__}: {e}")

    df = pd.DataFrame(summary)
    if len(df):
        LABELS.mkdir(parents=True, exist_ok=True)
        df.to_csv(LABELS / "label_batch_summary.csv", index=False)
        print(f"\n{len(df)} scenes labelled, {df.vessel.sum()} vessel + {df.sts.sum()} sts "
              f"boxes, {total_tiles} tiles")
    return df
