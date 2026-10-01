"""Sentinel-1 calibrated sigma-nought VV+VH from CDSE Sentinel Hub — the experiment arm.

Planetary Computer (fetch_s1) gives raw DN, VV only, warped by us. This gives the
same acquisition as calibrated sigma-nought, both polarisations, orthorectified by
Sentinel Hub onto the same UTM 32N / 10 m grid, so the two can be compared on
identical scenes (RESULTS.md §5, RESEARCH_POSITION.md §3.4).

It COSTS processing units (PU) from a 30k/month quota. `fetch` only estimates
unless called with `confirm=True`, and reports the PU actually charged.

Bands written: 1 = VV, 2 = VH (sigma-nought x 10000, uint16), 3 = data mask.
Scaled to uint16 so autolabel's MAD threshold, which assumes integer-like DN,
works unchanged on band 1.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.warp import transform_bounds

from src.config import CDSE_CLIENT_ID, CDSE_CLIENT_SECRET, DATA, bbox as default_bbox
from src.fetch_s1 import DST_CRS, DST_RES

TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
             "protocol/openid-connect/token")
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
OUT = DATA / "sar_cdse"
MAX_PX = 2500          # Process API limit per output dimension

EVALSCRIPT = """//VERSION=3
function setup() {
  return {input: ["VV", "VH", "dataMask"], output: {bands: 3, sampleType: "UINT16"}};
}
function evaluatePixel(s) { return [s.VV * 10000, s.VH * 10000, s.dataMask]; }
"""


def tiles(box=None, res=DST_RES, max_px=MAX_PX):
    """Split the AOI into UTM bboxes no larger than max_px on a side."""
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", DST_CRS, *(box or default_bbox()))
    step = max_px * res
    xs, ys = np.arange(x0, x1, step), np.arange(y0, y1, step)
    return [(x, y, min(x + step, x1), min(y + step, y1)) for x in xs for y in ys]


def estimate_pu(box=None, res=DST_RES):
    """Processing units for one scene over the AOI.

    Sentinel Hub: (pixels / 512^2) x (input bands / 3) x 2 for Sentinel-1
    orthorectification; uint16 output adds no factor. An estimate — the API
    reports the real charge in the X-ProcessingUnits-Spent header.
    """
    px = sum((b[2] - b[0]) / res * (b[3] - b[1]) / res for b in tiles(box, res))
    return px / 512 ** 2 * (2 / 3) * 2


def _token():
    if not (CDSE_CLIENT_ID and CDSE_CLIENT_SECRET):
        raise RuntimeError("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET not set (.env or Colab secrets)")
    r = requests.post(TOKEN_URL, data={"grant_type": "client_credentials",
                                       "client_id": CDSE_CLIENT_ID,
                                       "client_secret": CDSE_CLIENT_SECRET}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _request(b, t0, t1, res):
    return {
        "input": {
            "bounds": {"bbox": list(b),
                       "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/32632"}},
            "data": [{
                "type": "sentinel-1-grd",
                "dataFilter": {"timeRange": {"from": t0, "to": t1}, "acquisitionMode": "IW",
                               "polarization": "DV", "resolution": "HIGH"},
                "processing": {"backCoeff": "SIGMA0_ELLIPSOID", "orthorectify": True,
                               "demInstance": "COPERNICUS"},
            }],
        },
        "output": {"resx": res, "resy": res,
                   "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": EVALSCRIPT,
    }


def fetch(scene_time, box=None, name: str = None, confirm: bool = False, res=DST_RES):
    """Fetch one acquisition (scene_time +/- 2 min) over the AOI. Returns the path.

    Without confirm=True this prints the PU estimate and returns None.
    """
    t = pd.Timestamp(scene_time)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    bxs = tiles(box, res)
    est = estimate_pu(box, res)
    print(f"{len(bxs)} request(s), estimated ~{est:.0f} PU")
    if not confirm:
        print("not fetched: call again with confirm=True to spend the PU")
        return None

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{name or t.strftime('%Y%m%dT%H%M%S')}_cdse.tif"
    if dest.exists():
        print(f"cached: {dest}")
        return dest

    t0 = (t - pd.Timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    t1 = (t + pd.Timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    head = {"Authorization": f"Bearer {_token()}"}
    mems, parts, spent = [], [], 0.0
    for b in bxs:
        r = requests.post(PROCESS_URL, json=_request(b, t0, t1, res), headers=head, timeout=300)
        if r.status_code != 200:
            raise RuntimeError(f"CDSE {r.status_code}: {r.text[:300]}")
        spent += float(r.headers.get("x-processingunits-spent", 0))
        mems.append(MemoryFile(r.content))       # keep alive while parts are open
        parts.append(mems[-1].open())

    mosaic, transform = merge(parts)
    profile = parts[0].profile | {"height": mosaic.shape[1], "width": mosaic.shape[2],
                                  "transform": transform, "compress": "deflate"}
    with rasterio.open(dest, "w", **profile) as dst:
        dst.write(mosaic)
    valid = (mosaic[2] > 0).mean()
    print(f"{dest.name}  {mosaic.shape[2]}x{mosaic.shape[1]}px  {valid:.0%} covered  "
          f"PU charged: {spent:.1f}")
    return dest


if __name__ == "__main__":
    print(f"one scene over the AOI: ~{estimate_pu():.0f} PU")
    if len(sys.argv) > 1:
        fetch(sys.argv[1], confirm="--confirm" in sys.argv)
