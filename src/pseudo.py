"""Training tiles from new regions, labelled by AIS-confirmed detections.

Outside Denmark there is no AIS with length and speed to autolabel from, but the
region search (`hunt.run`) already found ships and checked each one against
GFW AIS. A detection with an AIS identity next to it is a ship: it becomes a
`vessel` box, re-measured from the image like the autolabeller does.

Known limit (self-training): the model only learns ships it already finds.
It adapts to local sea state and imagery, not to its own misses. Tiles that
hold an AIS-unmatched or sts detection are left out entirely, so a possible
ship is never taught as background.
"""
from pathlib import Path

import pandas as pd
import rasterio
import requests

from src import autolabel, dark_sts, fetch_s1
from src.hunt import REGIONS

ROOT = Path("/content/drive/MyDrive/darksts")
HALF_PX = 20                  # detections are centred on the hull already


def scene_tif(tif, region, root=ROOT):
    """The saved scene, re-downloaded to Drive if the runtime that held it is gone."""
    tif = Path(tif)
    if tif.exists():
        return tif
    out = root / f"hunt_{region}" / "scenes"
    if (out / tif.name).exists():
        return out / tif.name
    item_id = tif.stem.rsplit("_", 1)[0]                      # drop the _vv suffix
    r = requests.get(f"{fetch_s1.STAC}/collections/sentinel-1-grd/items/{item_id}", timeout=90)
    r.raise_for_status()
    return fetch_s1.fetch(r.json(), box=REGIONS[region], out_dir=out)


def boxes_for(g, tif):
    """(vessel boxes, skip boxes) in pixels for one scene's checked detections."""
    keep, skip = [], []
    with rasterio.open(tif) as s:
        img, res = s.read(1), s.res[0]
        for _, d in g.iterrows():
            r, c = s.index(d.x, d.y)
            bb = autolabel._blob_at(img, r, c, HALF_PX)
            if bb is None:
                bb = (r - 2, c - 2, r + 2, c + 2)                 # still blocks its tile
            row = {"cls": "vessel", "r0": bb[0], "c0": bb[1], "r1": bb[2], "c1": bb[3]}
            length = (max(bb[2] - bb[0], bb[3] - bb[1]) + 1) * res
            matched = d.category != dark_sts.AIS_UNMATCHED and d.cls == "vessel"
            ok = autolabel.MIN_LEN_M <= length <= autolabel.MAX_LEN_M
            (keep if matched and ok else skip).append(row)
    cols = ["cls", "r0", "c0", "r1", "c1"]
    return pd.DataFrame(keep, columns=cols), pd.DataFrame(skip, columns=cols)


def build(regions=("oman", "laconia"), root=ROOT, out_dir=autolabel.TILES, max_tiles=400):
    """Write tiles + YOLO labels from hunt_<region>/all_checked.csv, up to max_tiles per region.

    The cap keeps one busy region from outweighing the others; scenes are taken
    in time order, so the tiles still span the whole period.
    """
    total = 0
    for region in regions:
        res = pd.read_csv(root / f"hunt_{region}" / "all_checked.csv")
        n_tiles = n_boxes = 0
        scenes = sorted(res.groupby("scene"), key=lambda sg: str(sg[1].time.iloc[0]))
        step = max(1, len(scenes) // max(1, max_tiles // 15))      # ~15 tiles per busy scene
        for scene, g in scenes[::step]:
            if n_tiles >= max_tiles:
                break
            try:
                tif = scene_tif(g.tif.iloc[0], region, root)
                keep, skip = boxes_for(g, tif)
                n_tiles += autolabel.tile_scene(tif, keep, out_dir=out_dir, skip=skip)
                n_boxes += len(keep)
            except Exception as e:
                print(f"   {scene[:40]} skipped: {e}")
        print(f"{region}: {n_boxes} AIS-confirmed boxes -> {n_tiles} tiles")
        total += n_tiles
    return total
