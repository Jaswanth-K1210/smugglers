"""Sentinel-1 GRD acquisition via the Microsoft Planetary Computer STAC API.

Why not CDSE Sentinel Hub: its OAuth endpoint was down and registration was
failing. Planetary Computer mirrors the same ESA Sentinel-1 data, needs no
account, and serves cloud-optimized GeoTIFFs we can window-read over HTTP.

The GRD assets are in radar geometry with a ~210-point GCP grid rather than a
map projection, so we warp them. GDAL picks the GCPs up automatically through
WarpedVRT; we only choose the output CRS and resolution.

Output is UTM 32N at 10 m, not EPSG:4326, so that pixels are square metres.
Phase 5's length gate and Phase 6's 500 m buffer both work in metres, and a
detector trained on square pixels does not have to unlearn latitude stretch.

No calibration step: ships sit 10-30 dB above water, so adaptive thresholding
works on raw DN. We never need absolute sigma-nought.
"""
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from src.config import DATA, bbox as default_bbox

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token"
RAW = DATA / "sar_raw"

# One UTM zone per AOI, chosen from its centre. An AOI straddling a zone edge
# costs well under a percent of scale; one far outside a fixed zone (Oman is ~47
# deg east of 32N) would be badly stretched, so the zone follows the AOI.
DST_CRS = "EPSG:32632"   # Skagen; kept for callers that assume the training AOI
DST_RES = 10.0


def utm_crs(box) -> str:
    """UTM zone EPSG code for the centre of a (lon0, lat0, lon1, lat1) box."""
    lon, lat = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"

# Keep GDAL from listing the whole blob container on every open.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tiff,.tif")


def search(start: str, end: str, box=None, limit: int = 50, mode: str = "IW"):
    """Sentinel-1 GRD scenes overlapping the AOI. Dates are YYYY-MM-DD.

    Returns items newest-first, deduplicated to one per acquisition — the STAC
    catalogue carries a few near-identical entries per overpass.
    """
    box = box or default_bbox()
    r = requests.post(
        f"{STAC}/search",
        json={
            "collections": ["sentinel-1-grd"],
            "bbox": list(box),
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "query": {"sar:instrument_mode": {"eq": mode}},
            "limit": limit,
        },
        timeout=90,
    )
    r.raise_for_status()
    items, seen = [], set()
    for f in r.json().get("features", []):
        key = f["properties"]["datetime"]
        if key in seen:
            continue
        seen.add(key)
        items.append(f)
    return sorted(items, key=lambda f: f["properties"]["datetime"], reverse=True)


def overlap(item, box=None) -> float:
    """Fraction of the AOI covered by this scene's footprint, 0..1.

    A single IW slice is much smaller than a multi-degree AOI, so picking a
    scene by recency alone lands on whichever corner the satellite happened to
    cross — often solid land. Rank by overlap instead.
    """
    lo_lon, lo_lat, hi_lon, hi_lat = box or default_bbox()
    b = item["bbox"]
    w = max(0.0, min(b[2], hi_lon) - max(b[0], lo_lon))
    h = max(0.0, min(b[3], hi_lat) - max(b[1], lo_lat))
    return w * h / ((hi_lon - lo_lon) * (hi_lat - lo_lat))


_tokens = {}


def sign(href: str) -> str:
    """Planetary Computer SAS signing, one token per storage container.

    Signing each file hits the anonymous rate limit (429) after a few dozen
    calls; a container token is valid for about an hour and covers every file.
    """
    host, container = href.split("/")[2], href.split("/")[3]
    key = (host.split(".")[0], container)
    tok, expiry = _tokens.get(key, (None, pd.Timestamp(0, tz="UTC")))
    if expiry - pd.Timestamp.now(tz="UTC") < pd.Timedelta(minutes=5):
        for i in range(5):
            r = requests.get(f"{TOKEN}/{key[0]}/{key[1]}", timeout=60)
            if r.status_code != 429:
                break
            time.sleep(10 * (i + 1))
        r.raise_for_status()
        j = r.json()
        tok, expiry = j["token"], pd.Timestamp(j["msft:expiry"])
        _tokens[key] = (tok, expiry)
    return f"{href}?{tok}"


def fetch(item, box=None, pol: str = "vv", out_dir: Path = RAW) -> Path:
    """Warp one scene's AOI overlap to UTM/10 m and save it as a GeoTIFF.

    Only the pixels covering `box` are pulled across the network — the source
    is a COG, so the windowed read fetches the relevant tiles and nothing else.
    """
    box = box or default_bbox()
    if pol not in item["assets"]:
        raise KeyError(f"{item['id']} has no {pol!r} asset (has {list(item['assets'])})")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{item['id']}_{pol}.tif"
    if dest.exists():
        print(f"cached: {dest}")
        return dest

    with rasterio.open(sign(item["assets"][pol]["href"])) as src:
        if not src.gcps[0]:
            raise RuntimeError(f"{item['id']} has no GCPs; cannot geocode")
        crs = utm_crs(box)
        with WarpedVRT(
            src, crs=crs, resolution=(DST_RES, DST_RES), resampling=Resampling.bilinear
        ) as vrt:
            left, bottom, right, top = transform_bounds("EPSG:4326", crs, *box)
            window = from_bounds(left, bottom, right, top, vrt.transform).round_offsets().round_lengths()
            # Clip to the scene: most overpasses only clip a corner of the AOI.
            window = window.intersection(rasterio.windows.Window(0, 0, vrt.width, vrt.height))
            if window.width < 1 or window.height < 1:
                raise ValueError(f"{item['id']} does not overlap the AOI")
            data = vrt.read(1, window=window)
            profile = vrt.profile | {
                "driver": "GTiff",
                "height": window.height,
                "width": window.width,
                "transform": vrt.window_transform(window),
                "compress": "deflate",
                "tiled": True,
            }
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)

    with rasterio.open(dest, "w", **profile) as dst:
        dst.write(data, 1)
    filled = float((data > 0).mean())
    print(f"{dest.name}  {window.width}x{window.height}px  {filled:.0%} covered  "
          f"{dest.stat().st_size / 1e6:.1f} MB")
    return dest


def preview(tif: Path, png: Path = None, max_px: int = 1200) -> Path:
    """Downsampled 8-bit quick-look, so we can eyeball coastline and bright dots.

    Stretched on percentiles of the water background — a linear stretch over the
    full range would be all black, since ships are orders of magnitude brighter.
    """
    png = png or tif.with_suffix(".png")
    with rasterio.open(tif) as src:
        scale = max(1, max(src.width, src.height) // max_px)
        data = src.read(
            1, out_shape=(src.height // scale, src.width // scale), resampling=Resampling.average
        )
    valid = data[data > 0]
    if valid.size == 0:
        raise ValueError(f"{tif} is empty")
    lo, hi = np.percentile(valid, [2, 98])
    scaled = np.clip((data.astype("float32") - lo) / max(hi - lo, 1) * 255, 0, 255).astype("uint8")
    with rasterio.open(
        png, "w", driver="PNG", height=scaled.shape[0], width=scaled.shape[1], count=1, dtype="uint8"
    ) as dst:
        dst.write(scaled, 1)
    print(f"preview: {png}  {scaled.shape[1]}x{scaled.shape[0]}")
    return png


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else "2025-06-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2025-06-08"
    items = search(start, end)
    print(f"{len(items)} Sentinel-1 IW scenes over the AOI, {start}..{end}")
    for it in sorted(items, key=overlap, reverse=True)[:10]:
        print(f"  {it['properties']['datetime'][:19]}  AOI overlap {overlap(it):4.0%}  {it['id']}")
    if not items:
        sys.exit("no scenes found — widen the date range")
    preview(fetch(max(items, key=overlap)))
