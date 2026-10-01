"""Search a region for AIS-unmatched vessels: detect on Sentinel-1, check against AIS.

The detector is trained where AIS is dense and reliable (Skagen); this applies it
where unbroadcast traffic is expected (RESEARCH_POSITION.md §6). AIS outside
Denmark comes from GFW hourly presence, so a scene whose GFW AIS is missing or
thin is EXCLUDED rather than counted: no AIS data is not evidence of no AIS.

Outputs, per region, in `out`: all_checked.csv (every detection and its AIS
evidence), ais_unmatched.csv (the candidates) and ais_unmatched_chips.png.

    from src.hunt import run
    run("oman")
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from src import dark_sts, fetch_s1, gfw
from src.filters import clean_detections

REGIONS = {
    "laconia": (22.45, 36.35, 23.15, 36.80),   # Gulf of Laconia, Greece
    "oman": (56.30, 24.90, 56.80, 25.50),      # Fujairah anchorage, Gulf of Oman
}
near = dark_sts._metres_between
THIN = 0.3        # a scene with < 30 % of the region's median AIS cells is unreliable


def dedupe(d, radius_m=150):
    """Within each scene keep the most confident detection per radius."""
    keep = []
    for _, g in d.sort_values("conf", ascending=False).groupby("scene"):
        k = []
        for i, r in g.iterrows():
            if not k or near(r.lat, r.lon, g.loc[k].lat, g.loc[k].lon).min() > radius_m:
                k.append(i)
        keep += k
    return d.loc[keep].reset_index(drop=True)


def thin_scenes(cells: dict, frac=THIN):
    """Scenes whose AIS cell count is missing or far below the region's median."""
    pos = [c for c in cells.values() if c > 0]
    if not pos:
        return set(cells)
    med = np.median(pos)
    return {s for s, c in cells.items() if c < frac * med}


def _presence(t, box, tries=3, wait=20):
    """GFW AIS around t, retried: GFW sometimes answers an empty window with null."""
    a = pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"])
    for _ in range(tries):
        try:
            a = gfw.ais_presence(t - pd.Timedelta(hours=2), t + pd.Timedelta(hours=2), box)
            if len(a):
                return a
        except Exception as e:                       # network / 429 / 524
            print(f"   GFW error: {e}")
        time.sleep(wait)
    return a


def detect_region(box, start, end, weights, scene_dir, conf=0.4, min_overlap=0.3):
    from src.run_pipeline import detect
    items = [i for i in fetch_s1.search(start, end, box=box, limit=200)
             if fetch_s1.overlap(i, box) >= min_overlap]
    print(f"{len(items)} scenes")
    raw = []
    for n, it in enumerate(items, 1):
        try:
            tif = fetch_s1.fetch(it, box=box, out_dir=scene_dir)
            d = detect(tif, weights, conf=conf)
            if len(d):
                d["tif"] = str(tif)
                raw.append(d)
            print(f"[{n}/{len(items)}] {len(d)} detections")
        except Exception as e:
            print(f"[{n}/{len(items)}] skipped: {e}")
    return dedupe(clean_detections(pd.concat(raw, ignore_index=True)))


def check_ais(clean, box):
    """GFW AIS per scene; drops scenes whose AIS is missing/thin. Returns (res, excluded)."""
    res, cells = [], {}
    for n, (scene, g) in enumerate(clean.groupby("scene"), 1):
        a = _presence(pd.Timestamp(g.time.iloc[0]), box)
        cells[scene] = len(a)
        res.append(dark_sts.characterise(g, a, buffer_m=2000, window_h=1))
        print(f"[{n}] {scene[:40]}  {len(a)} AIS cells")
    res = pd.concat(res, ignore_index=True)
    bad = thin_scenes(cells)
    return res[~res.scene.isin(bad)].reset_index(drop=True), bad


def candidates(res, box):
    """AIS-unmatched detections, with recurrence and GFW radar corroboration."""
    un = res[res.category == dark_sts.AIS_UNMATCHED].copy()
    un["scenes_here"] = [res[near(r.lat, r.lon, res.lat, res.lon) < 200].scene.nunique()
                         for _, r in un.iterrows()]
    un["gfw_also_unmatched"] = False
    for day, g in un.groupby(pd.to_datetime(un.time).dt.date):
        try:
            s = gfw.sar_unmatched(str(day), box)
        except Exception as e:
            print(f"   GFW radar check skipped for {day}: {e}")
            continue
        for i, r in g.iterrows():
            un.at[i, "gfw_also_unmatched"] = bool(len(s)) and bool(
                (near(r.lat, r.lon, s.lat, s.lon) < 1500).any())
    return un


def chip_sheet(un, png, n=30):
    import matplotlib.pyplot as plt
    top = un.sort_values(["scenes_here", "gfw_also_unmatched", "conf"],
                         ascending=[True, False, False]).head(n)
    fig, axs = plt.subplots(6, 5, figsize=(15, 18))
    for ax, (_, r) in zip(axs.flat, top.iterrows()):
        with rasterio.open(r.tif) as s:
            row, col = s.index(r.x, r.y)
            img = s.read(1, window=rasterio.windows.Window(col - 60, row - 60, 120, 120),
                         boundless=True, fill_value=0).astype(float)
        v = img[img > 0]
        lo, hi = np.percentile(v, [1, 99.5]) if v.size else (0, 1)
        ax.imshow(np.clip((img - lo) / max(hi - lo, 1), 0, 1), cmap="gray")
        ax.plot(60, 60, "r+", ms=14)
        tag = " GFW✓" if r.gfw_also_unmatched else ""
        ax.set_title(f"{str(r.time)[:16]} conf {r.conf:.2f}{tag}\n{r.lat:.3f}N {r.lon:.3f}E "
                     f"~{r.length_m:.0f} m{' (recurring)' if r.scenes_here > 1 else ''}", fontsize=8)
    for ax in axs.flat:
        ax.axis("off")
    plt.tight_layout()
    plt.savefig(png, dpi=110)
    plt.close(fig)


def run(region, start="2026-07-01", end="2026-09-26", weights=None, out=None):
    box = REGIONS[region]
    weights = Path(weights or "models/bench_rtdetr-l/weights/best.pt")
    if not weights.exists():
        weights = Path("/content/drive/MyDrive/darksts/models/bench/bench_rtdetr-l/weights/best.pt")
    out = Path(out or f"/content/drive/MyDrive/darksts/hunt_{region}")
    out.mkdir(parents=True, exist_ok=True)

    clean = detect_region(box, start, end, weights, Path(f"data/sar_{region}"))
    clean.to_csv(out / "detections.csv", index=False)       # survives a crash below
    res, bad = check_ais(clean, box)
    print(f"\nexcluded {len(bad)} scene(s) with missing/thin GFW AIS")
    un = candidates(res, box)
    res.drop(columns=["mmsis"]).to_csv(out / "all_checked.csv", index=False)
    un.drop(columns=["mmsis"]).to_csv(out / "ais_unmatched.csv", index=False)
    if len(un):
        chip_sheet(un, out / "ais_unmatched_chips.png")
    print(f"\n{region}: {len(res)} ships checked | "
          f"{(res.category != dark_sts.AIS_UNMATCHED).sum()} AIS-matched | "
          f"{len(un)} AIS-unmatched ({(un.scenes_here > 1).sum()} at a recurring spot) | "
          f"{un.gfw_also_unmatched.sum()} also unmatched in GFW's own radar data\nsaved to {out}")
    return res, un
