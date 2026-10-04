"""Build the T3 blind review sheet (src/review.py): detections and chips on Modal.

    modal run modal_review.py

Phase 1 runs the detector on every dev pass (scenes kept on a volume), phase 2 cuts
chips for the sampled detections from the same files. Writes bench/t3_review/.
"""
import json
from pathlib import Path

import modal

from modal_app import image as base_image, values

image = base_image.add_local_file("modal_app.py", "/root/modal_app.py")
app = modal.App("darksts-review")
bench = modal.Volume.from_name("darksts-bench", create_if_missing=True)
SCENES = "/bench/scenes"


def _setup():
    import os
    import sys
    sys.path.insert(0, "/app")
    os.chdir("/app")


@app.function(image=image, cpu=2, memory=4096, timeout=1800, volumes={"/bench": bench},
              secrets=[modal.Secret.from_dict(values)], max_containers=3)
def detect_scene(item, box):
    _setup()
    from huggingface_hub import hf_hub_download
    from src import review
    weights = hf_hub_download("Jaswanth-K/darksts-detector", "best.pt", cache_dir="/tmp/hf")
    try:
        out = review.detections(item, box, weights, SCENES)
        bench.commit()
        return out
    except Exception as e:
        return {"scene": item["id"], "error": f"{type(e).__name__}: {e}"}


@app.function(image=image, cpu=1, memory=2048, timeout=600, volumes={"/bench": bench})
def cut_chips(rows):
    _setup()
    from src import review
    bench.reload()
    return [review.chips(r["tif"], r["x"], r["y"]) for r in rows]


@app.local_entrypoint()
def main():
    import requests
    from src import review
    from src.fetch_s1 import STAC
    from src.hunt import REGIONS
    box = REGIONS["oman"]
    ev = json.loads(Path("outputs/eval_oman.json").read_text())
    dev = [r["scene"] for r in ev["results"] if "error" not in r and r["rows"][0]["n_ais"] > 0]
    items = [requests.get(f"{STAC}/collections/sentinel-1-grd/items/{s}", timeout=90).json() for s in dev]
    print(f"{len(items)} dev passes (RESULTS.md §7)")
    dets, failed = [], []
    for res in detect_scene.starmap([(it, box) for it in items]):
        (failed.append(res) if isinstance(res, dict) else dets.extend(res))
    for f in failed:
        print("  failed", f["scene"][:40], f["error"][:120])
    picked = review.sample(dets)
    counts = picked.band.value_counts().sort_index().to_dict()
    print(f"{len(dets)} cleaned detections >= 0.10; sampled per band: {counts}")
    groups = {}
    for i, r in picked.iterrows():
        groups.setdefault(r.tif, []).append(i)
    pngs = {}
    for idx, out in zip(groups.values(), cut_chips.map([[picked.loc[i].to_dict() for i in idx]
                                                        for idx in groups.values()])):
        pngs.update(dict(zip(idx, out)))
    n = review.write_sheet(picked, [pngs[i] for i in range(len(picked))], "bench/t3_review")
    Path("bench/t3_review/build_log.json").write_text(json.dumps({
        "dev_passes": dev, "failed_passes": failed, "detections_total": len(dets),
        "sampled_per_band": counts, "per_band_target": review.PER_BAND, "seed": review.SEED,
        "bands": review.BANDS, "chip_halfwidth_px": [review.SMALL, review.WIDE],
        "stretch": "log10(DN) fixed 20..2000 for every chip"}, indent=1))
    print(f"wrote {n} cards to bench/t3_review/")
