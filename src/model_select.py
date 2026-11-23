"""Pick the detector for the website: YOLOv8n / 11n / 12n / 26n vs RT-DETR-l.

Leave-one-region-out: every model trains on two regions (scene split for
validation) and is TESTED on all tiles of the third, a region none of them saw.
That is the website's situation: a user draws a box somewhere new.
`rotations()` runs all three hold-outs (the paper's generalisation table).

Accuracy alone does not decide it; the free Hugging Face Space runs on CPU, so
each model is also timed on CPU and must stay under `max_cpu_s` per tile.

    from src import model_select
    model_select.run()                       # Laconia held out
    model_select.rotations()                 # Skagen, Oman, Laconia each held out once
"""
import random
import shutil
import time
from pathlib import Path

import pandas as pd
import yaml

from src.config import DATA
from src.train import NAMES, scene_of, train

ROOT = Path("/content/drive/MyDrive/darksts")
MODELS = ["yolov8n.pt", "yolo11n.pt", "yolo12n.pt", "yolo26n.pt", "rtdetr-l.pt"]
REGIONS = ("skagen", "oman", "laconia")
HUNTED = ("oman", "laconia")                 # regions with hunt_<region>/all_checked.csv


def partition(images, test_scenes, val_frac=0.25, seed=0):
    """{'train','val','test'} lists of tile paths; test = tiles of `test_scenes`."""
    test = [p for p in images if scene_of(p.stem) in test_scenes]
    rest = [p for p in images if scene_of(p.stem) not in test_scenes]
    scenes = sorted({scene_of(p.stem) for p in rest})
    val_scenes = set(random.Random(seed).sample(scenes, max(1, round(len(scenes) * val_frac))))
    return {"train": [p for p in rest if scene_of(p.stem) not in val_scenes],
            "val": [p for p in rest if scene_of(p.stem) in val_scenes],
            "test": test}


def region_scenes(region, images, hunted):
    """Scenes of `region`. `hunted` maps oman/laconia to their scene sets; Skagen
    (labelled from Danish AIS, no hunt CSV) is every tile scene not in them."""
    if region in hunted:
        return hunted[region]
    if region != "skagen":
        raise ValueError(f"unknown region {region!r}; expected one of {REGIONS}")
    return {scene_of(p.stem) for p in images} - set().union(*hunted.values())


def build(tiles=None, root=ROOT, test_region="laconia", out=None):
    """Lay out train/val/test; returns the dataset yaml."""
    tiles = Path(tiles or root / "tiles_multi")
    out = Path(out or DATA / f"select_{test_region}")
    images = [p for p in sorted((tiles / "images").glob("*.png"))
              if (tiles / "labels" / f"{p.stem}.txt").exists()]
    hunted = {r: set(pd.read_csv(root / f"hunt_{r}" / "all_checked.csv").scene) for r in HUNTED}
    test_scenes = region_scenes(test_region, images, hunted)
    parts = partition(images, test_scenes)
    for split, imgs in parts.items():
        for kind in ("images", "labels"):
            shutil.rmtree(out / split / kind, ignore_errors=True)
            (out / split / kind).mkdir(parents=True)
        for p in imgs:
            shutil.copy(p, out / split / "images" / p.name)
            shutil.copy(tiles / "labels" / f"{p.stem}.txt", out / split / "labels" / f"{p.stem}.txt")
    yml = out / "data.yaml"
    yml.write_text(yaml.safe_dump({"path": str(out.resolve()), "train": "train/images",
                                   "val": "val/images", "test": "test/images",
                                   "names": {i: n for i, n in enumerate(NAMES)}}))
    print({k: len(v) for k, v in parts.items()}, f"tiles; test = all {test_region} tiles")
    return yml


def cpu_seconds(weights, images, n=10):
    from ultralytics import YOLO
    model = YOLO(str(weights))
    model.predict(str(images[0]), device="cpu", verbose=False)          # warm-up
    t = time.time()
    for p in images[:n]:
        model.predict(str(p), device="cpu", verbose=False)
    return (time.time() - t) / min(n, len(images))


def run(models=MODELS, epochs=80, root=ROOT, max_cpu_s=0.3, device=0, test_region="laconia"):
    """Train, test on the unseen region, time on CPU, save the table, recommend one."""
    from ultralytics import YOLO
    yml = build(root=root, test_region=test_region)
    col = f"{test_region}_vessel_mAP50"
    test_imgs = sorted((yml.parent / "test" / "images").glob("*.png"))
    rows = []
    for m in models:
        tag = m.replace(".pt", "")
        try:
            best = train(yml, model=m, epochs=epochs, batch=8 if "rtdetr" in m else 16,
                         name=f"select_{test_region}_{tag}", device=device)
            run_dir = root / "models" / f"select_{test_region}_{tag}"
            shutil.copytree(best.parent.parent, run_dir, dirs_exist_ok=True)
            r = YOLO(str(best)).val(data=str(yml), split="test", imgsz=1024, plots=False, verbose=False)
            ap = dict(zip(r.box.ap_class_index.tolist(), r.box.ap50.tolist()))
            rows.append({"model": tag, "test_region": test_region, col: round(ap.get(0, float("nan")), 3),
                         "precision": round(r.box.mp, 3), "recall": round(r.box.mr, 3),
                         "cpu_s_per_tile": round(cpu_seconds(best, test_imgs), 2),
                         "size_MB": round(Path(best).stat().st_size / 1e6, 1),
                         "weights": str(run_dir / "weights" / "best.pt")})
        except Exception as e:                       # one model failing must not lose the rest
            rows.append({"model": tag, "test_region": test_region, "error": f"{type(e).__name__}: {e}"})
        print(f"--- {tag} done")
    table = pd.DataFrame(rows)
    csv = root / f"model_select_{test_region}.csv"
    table.to_csv(csv, index=False)
    print("\n" + table.drop(columns=["weights"], errors="ignore").to_string(index=False))

    if col not in table or table[col].isna().all():
        print(f"\nno model finished on {test_region}; see the error column")
        return table
    ok = table.dropna(subset=[col])
    fast = ok[ok.cpu_s_per_tile <= max_cpu_s]
    if len(ok):
        top = ok.loc[ok[col].idxmax()]
        print(f"\nmost accurate on {test_region}: {top.model} ({top[col]})")
    if len(fast):
        pick = fast.loc[fast[col].idxmax()]
        print(f"website pick (<= {max_cpu_s} s/tile on CPU): {pick.model} "
              f"({pick[col]}, {pick.cpu_s_per_tile} s/tile)\n  {pick.weights}")
    print(f"table saved to {csv}")
    return table


def rotations(models=("yolo26n.pt", "rtdetr-l.pt"), epochs=80, root=ROOT, device=0):
    """Hold out each region once; one long table saved as model_select_rotations.csv.

    Defaults to the served model and the accuracy reference only: 3 rotations x 5
    families is ~15 A100 runs. Pass MODELS for the full grid.
    Caveat for the Skagen hold-out: Oman/Laconia pseudo-labels were produced by a
    Skagen-trained detector (RESULTS.md §6), so Skagen is not fully unseen upstream.
    """
    if device != "cpu":
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("no CUDA GPU visible: in Colab, Runtime -> Change runtime type -> "
                               "A100 (or L4/T4), then re-run from the first cell")
    tables = []
    for region in REGIONS:
        t = run(models=models, epochs=epochs, root=root, device=device, test_region=region)
        tables.append(t.rename(columns={f"{region}_vessel_mAP50": "test_vessel_mAP50"}))
    table = pd.concat(tables, ignore_index=True)
    table.to_csv(root / "model_select_rotations.csv", index=False)
    print("\n" + table.drop(columns=["weights"], errors="ignore").to_string(index=False))
    return table
