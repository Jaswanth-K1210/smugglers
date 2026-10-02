"""Sentinel-2 optical cross-check of STS candidates (evidence ladder: optical).

For each candidate, the nearest-in-time Sentinel-2 L2A image (Planetary
Computer, free, no account) that is clear over the spot. Two hulls moored
together are visible at 10 m in true colour. Sentinel-2 passes at ~10:30 local
and revisits every ~5 days, so the image is hours to days from the radar pass:
a pair still there days later supports a transfer; an empty sea proves nothing.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.warp import transform
from rasterio.windows import from_bounds

from src.fetch_s1 import STAC, sign

CLOUDY = {3, 7, 8, 9, 10}     # SCL: cloud shadow, unclassified (thin cloud / haze), cloud, cirrus
HALF_M = 750                  # chip half-width


def scenes(lat, lon, t, days=5, max_cloud=80):
    """Sentinel-2 L2A items over the point within +-days of t, nearest in time first."""
    t = pd.Timestamp(t)
    r = requests.post(f"{STAC}/search", json={
        "collections": ["sentinel-2-l2a"],
        "intersects": {"type": "Point", "coordinates": [lon, lat]},
        "datetime": f"{t - pd.Timedelta(days=days):%Y-%m-%dT%H:%M:%SZ}/"
                    f"{t + pd.Timedelta(days=days):%Y-%m-%dT%H:%M:%SZ}",
        "query": {"eo:cloud_cover": {"lt": max_cloud}}, "limit": 50}, timeout=90)
    r.raise_for_status()
    gap = lambda f: abs(pd.Timestamp(f["properties"]["datetime"]).tz_localize(None) - t)
    return sorted(r.json().get("features", []), key=gap)


def _read(href, lat, lon, half_m=HALF_M):
    with rasterio.open(sign(href)) as s:
        (x,), (y,) = transform("EPSG:4326", s.crs, [lon], [lat])
        w = from_bounds(x - half_m, y - half_m, x + half_m, y + half_m, s.transform)
        return s.read(window=w, boundless=True, fill_value=0)


def cloud_fraction(scl):
    """Share of valid SCL pixels that are cloud or shadow; 1.0 if none are valid."""
    valid = scl > 0
    return float(np.isin(scl, list(CLOUDY))[valid].mean()) if valid.any() else 1.0


def clear_chip(lat, lon, t, days=5, max_cloud_frac=0.2):
    """(rgb uint8 HxWx3, item) for the nearest clear image, or (None, None)."""
    for it in scenes(lat, lon, t, days):
        scl = _read(it["assets"]["SCL"]["href"], lat, lon)[0]
        if cloud_fraction(scl) <= max_cloud_frac:
            return np.moveaxis(_read(it["assets"]["visual"]["href"], lat, lon), 0, -1), it
    return None, None


def run(regions=("oman", "laconia"), n=10, root="/content/drive/MyDrive/darksts", days=5):
    """Optical sheet + CSV per region for the top-n AIS-unmatched STS candidates."""
    import matplotlib.pyplot as plt
    for region in regions:
        out = Path(root) / f"hunt_{region}"
        c = pd.read_csv(out / "sts_candidates.csv", parse_dates=["time"])
        c = c[c.dark_sts & c.tier.isin(["A", "B"])].head(n)
        rows, chips = [], []
        for _, r in c.iterrows():
            try:
                rgb, it = clear_chip(r.lat, r.lon, r.time, days)
            except Exception as e:
                print(f"   {r.lat:.3f}N {r.lon:.3f}E: {e}")
                rgb, it = None, None
            t2 = pd.Timestamp(it["properties"]["datetime"]).tz_localize(None) if it else pd.NaT
            gap = round((t2 - r.time).total_seconds() / 3600, 1) if it else None
            rows.append({"lat": r.lat, "lon": r.lon, "sar_time": r.time, "tier": r.tier,
                         "evidence": r.evidence, "missing": r.missing,
                         "s2_id": it["id"] if it else None, "s2_time": t2, "gap_h": gap})
            chips.append(rgb)
            print(f"[{r.tier}] {r.lat:.3f}N {r.lon:.3f}E  " +
                  (f"S2 {t2:%Y-%m-%d %H:%M}  ({gap:+.0f} h)" if it else "no clear S2 image"))
        pd.DataFrame(rows).to_csv(out / "optical_check.csv", index=False)
        if not rows:
            continue
        fig, axs = plt.subplots(2, 5, figsize=(15, 7))
        for ax, row, rgb in zip(axs.flat, rows, chips):
            if rgb is not None:
                v = rgb[rgb.sum(-1) > 0]
                lo, hi = np.percentile(v, [2, 98]) if v.size else (0, 255)
                ax.imshow(np.clip((rgb - lo) / max(hi - lo, 1), 0, 1))
                h, w = rgb.shape[:2]
                ax.add_patch(plt.Circle((w / 2, h / 2), w * 0.12, fill=False, ec="r"))
            ax.set_title(f"[{row['tier']}] {row['lat']:.3f}N {row['lon']:.3f}E\n"
                         f"SAR {row['sar_time']:%m-%d %H:%M}, " +
                         (f"S2 {row['gap_h']:+.0f} h" if row["gap_h"] is not None else "no clear S2"),
                         fontsize=8)
        for ax in axs.flat:
            ax.axis("off")
        plt.tight_layout()
        plt.savefig(out / "optical_check.png", dpi=110)
        plt.close(fig)
        print(f"saved {out / 'optical_check.png'}")
