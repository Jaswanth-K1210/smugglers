"""Train the YOLOv8 vessel/sts detector.

Written as a module, not notebook cells, so the Colab notebook stays a thin
caller and the logic lives in git.

The split is **by scene, never by tile**. Tiles from one Sentinel-1 scene share
sea state, incidence angle, wind streaks and often the same vessels minutes
apart. Splitting tiles at random puts near-duplicates on both sides and reports
a validation score the model has not earned.
"""
import argparse
import random
import shutil
import sys
from pathlib import Path

import yaml

from src.config import DATA, ROOT

TILES = DATA / "tiles"
DATASET = DATA / "dataset"
MODELS = ROOT / "models"
NAMES = ["vessel", "sts"]


def scene_of(tile_name: str) -> str:
    """Scene id from a tile filename like <scene>_<top>_<left>.png."""
    return tile_name.rsplit("_", 2)[0]


def build_dataset(tiles: Path = TILES, out: Path = DATASET, val_frac: float = 0.25, seed: int = 0):
    """Lay tiles out as a YOLO dataset, holding out whole scenes for validation."""
    images = sorted((tiles / "images").glob("*.png"))
    if not images:
        raise FileNotFoundError(f"no tiles in {tiles / 'images'} — run src.autolabel first")

    scenes = sorted({scene_of(p.stem) for p in images})
    if len(scenes) < 2:
        print(f"WARNING: only {len(scenes)} scene(s). A scene-level split needs at least 2, "
              f"so validation will reuse training data and its score means nothing. "
              f"Label more scenes before trusting any mAP from this run.")
        val_scenes = set()
    else:
        rng = random.Random(seed)
        n_val = max(1, round(len(scenes) * val_frac))
        val_scenes = set(rng.sample(scenes, n_val))

    counts = {"train": 0, "val": 0}
    for split in ("train", "val"):
        for kind in ("images", "labels"):
            d = out / split / kind
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)

    for img in images:
        label = tiles / "labels" / f"{img.stem}.txt"
        if not label.exists():
            continue
        split = "val" if scene_of(img.stem) in val_scenes else "train"
        shutil.copy(img, out / split / "images" / img.name)
        shutil.copy(label, out / split / "labels" / label.name)
        counts[split] += 1

    if counts["val"] == 0:                      # single-scene fallback
        for img in sorted((out / "train" / "images").glob("*.png"))[::4]:
            shutil.copy(img, out / "val" / "images" / img.name)
            shutil.copy(out / "train" / "labels" / f"{img.stem}.txt",
                        out / "val" / "labels" / f"{img.stem}.txt")
            counts["val"] += 1

    yml = out / "dataset.yaml"
    yml.write_text(yaml.safe_dump({
        "path": str(out.resolve()),
        "train": "train/images",
        "val": "val/images",
        "names": {i: n for i, n in enumerate(NAMES)},
    }))
    print(f"dataset: {counts['train']} train / {counts['val']} val tiles "
          f"from {len(scenes)} scene(s); held out {sorted(val_scenes) or 'NOTHING (see warning)'}")
    return yml


def train(data_yaml: Path = None, model: str = "yolov8n.pt", epochs: int = 50,
          imgsz: int = 1024, batch: int = 8, name: str = "darksts", device=None):
    """Fine-tune YOLOv8. Returns the path of the best weights."""
    from ultralytics import YOLO

    data_yaml = data_yaml or (DATASET / "dataset.yaml")
    if not Path(data_yaml).exists():
        data_yaml = build_dataset()

    yolo = YOLO(model)
    yolo.train(data=str(data_yaml), epochs=epochs, imgsz=imgsz, batch=batch,
               name=name, project=str(MODELS), device=device, exist_ok=True,
               # SAR is not a photograph: a ship looks the same from any angle and
               # colour jitter is meaningless on a single-band amplitude image.
               hsv_h=0.0, hsv_s=0.0, hsv_v=0.2, degrees=180, flipud=0.5, fliplr=0.5,
               mosaic=0.5, scale=0.3)
    best = MODELS / name / "weights" / "best.pt"
    print(f"best weights: {best}")
    return best


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--imgsz", type=int, default=1024)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--name", default="darksts")
    ap.add_argument("--device", default=None, help="0 for the Colab GPU, cpu to force CPU")
    ap.add_argument("--build-only", action="store_true", help="lay out the dataset and stop")
    ap.add_argument("--available", action="store_true", help="list detector families this build supports")
    ap.add_argument("--benchmark", nargs="*", metavar="MODEL",
                    help="train several models on the same split and compare "
                         "(default: yolov8n yolo11n yolo12n)")
    a = ap.parse_args(argv)

    if a.available:
        return available()
    yml = build_dataset()
    if a.build_only:
        return yml
    if a.benchmark is not None:
        models = [m if m.endswith(".pt") else f"{m}.pt" for m in a.benchmark] or \
                 ["yolov8n.pt", "yolo11n.pt", "yolo12n.pt"]
        return benchmark(models, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=a.device)
    return train(yml, model=a.model, epochs=a.epochs, imgsz=a.imgsz,
                 batch=a.batch, name=a.name, device=a.device)




def available(candidates=("yolov8n.pt", "yolo11n.pt", "yolo12n.pt", "rtdetr-l.pt")):
    """Which detector families this ultralytics build can actually construct.

    Reported rather than assumed: the roster moves with the package version, and
    the training box (Colab) is not the box this was written on.
    """
    from ultralytics import YOLO
    import ultralytics

    print(f"ultralytics {ultralytics.__version__}")
    ok = []
    for name in candidates:
        try:
            YOLO(name)
            ok.append(name)
            print(f"  {name:16} available")
        except Exception as e:
            print(f"  {name:16} NOT available — {type(e).__name__}: {str(e)[:60]}")
    return ok


def benchmark(models=("yolov8n.pt", "yolo11n.pt", "yolo12n.pt"), epochs: int = 50,
              imgsz: int = 1024, batch: int = 8, device=None):
    """Train each model on the same split and return a comparison table.

    Same data, same split, same schedule — the only variable is the backbone, so
    the numbers are comparable. This is the experiment the paper should report
    instead of asserting one family is best.

    Add `rtdetr-l.pt` for a transformer detector alongside the CNNs:

        benchmark(["yolov8n.pt", "yolo11n.pt", "yolo12n.pt", "rtdetr-l.pt"])

    Note what is being measured and what is not. The benchmark answers "which
    family detects best on our data". It does not choose what to deploy: RT-DETR
    is an order of magnitude larger than a nano CNN, and the served endpoint runs
    on two free-tier vCPUs. Winning the table and serving the demo are separate
    decisions — see `deploy_choice` below.
    """
    import pandas as pd

    yml = build_dataset()
    rows = []
    for m in models:
        tag = m.replace(".pt", "")
        try:
            best = train(yml, model=m, epochs=epochs, imgsz=imgsz, batch=batch,
                         name=f"bench_{tag}", device=device)
            from ultralytics import YOLO
            r = YOLO(best).val(data=str(yml), imgsz=imgsz, device=device)
            rows.append({
                "model": tag,
                "mAP50": round(float(r.box.map50), 4),
                "mAP50-95": round(float(r.box.map), 4),
                "precision": round(float(r.box.mp), 4),
                "recall": round(float(r.box.mr), 4),
                "weights": str(best),
            })
        except Exception as e:
            rows.append({"model": tag, "mAP50": None, "error": f"{type(e).__name__}: {e}"})
        print(f"--- {tag} done")

    table = pd.DataFrame(rows)
    out = MODELS / "benchmark.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False)
    print(f"\n{table.to_string(index=False)}\nwrote {out}")
    return table


def deploy_choice(bench_csv=None, cpu_budget_s: float = 2.0):
    """Pick serving weights from a benchmark, separating accuracy from latency.

    The most accurate model is not automatically the deployed one. `/api/detect`
    runs on two shared vCPUs with no GPU, so a transformer that wins mAP by a few
    points and takes ten seconds per tile makes a worse demo than a nano CNN that
    answers instantly. This prints both rankings and states the tradeoff rather
    than silently optimising one of them.

    Reports the accuracy winner and the smallest model within `cpu_budget_s`,
    measured on this machine — not guessed from parameter counts.
    """
    import time

    import numpy as np
    import pandas as pd
    from ultralytics import YOLO

    bench_csv = Path(bench_csv or MODELS / "benchmark.csv")
    if not bench_csv.exists():
        raise FileNotFoundError(f"{bench_csv} — run benchmark() first")
    table = pd.read_csv(bench_csv)

    dummy = np.zeros((1024, 1024, 3), dtype="uint8")
    rows = []
    for _, r in table.iterrows():
        if not isinstance(r.get("weights"), str) or not Path(r["weights"]).exists():
            continue
        m = YOLO(r["weights"])
        m.predict(dummy, device="cpu", verbose=False)          # warm up
        t0 = time.perf_counter()
        for _ in range(3):
            m.predict(dummy, device="cpu", verbose=False)
        rows.append({"model": r["model"], "mAP50": r.get("mAP50"),
                     "cpu_s_per_tile": round((time.perf_counter() - t0) / 3, 2),
                     "weights": r["weights"]})

    out = pd.DataFrame(rows)
    if out.empty:
        print("no usable weights in the benchmark table")
        return out

    best_acc = out.loc[out.mAP50.idxmax()]
    affordable = out[out.cpu_s_per_tile <= cpu_budget_s]
    serve = affordable.loc[affordable.mAP50.idxmax()] if len(affordable) else \
        out.loc[out.cpu_s_per_tile.idxmin()]

    print(out.to_string(index=False))
    print(f"\nmost accurate : {best_acc.model}  mAP50 {best_acc.mAP50}  "
          f"{best_acc.cpu_s_per_tile}s/tile")
    print(f"serve on CPU  : {serve.model}  mAP50 {serve.mAP50}  "
          f"{serve.cpu_s_per_tile}s/tile  (budget {cpu_budget_s}s)")
    if serve.model != best_acc.model:
        print("\nThese differ. Report the accurate one in the paper; ship the fast one.")
    return out

if __name__ == "__main__":
    # Must stay last: main() dispatches to available() and benchmark(), which
    # are defined below it. Bare call, not sys.exit(0 if ... else 1) — main can
    # return a DataFrame, and a DataFrame in boolean context raises.
    main()


def compare(weights: dict, dataset: Path = DATASET, skagen_tiles: Path = None, imgsz: int = 1024):
    """mAP50 of several models on the SAME held-out tiles, split by region.

    `skagen_tiles` is the folder of the original Skagen tiles; any val tile not
    in it came from the new regions (AIS-confirmed pseudo-labels, so ships the
    detector never found are unlabelled there and precision reads low).
    """
    from ultralytics import YOLO

    val = sorted((dataset / "val" / "images").glob("*.png"))
    skagen = {p.name for p in (skagen_tiles / "images").glob("*.png")} if skagen_tiles else set()
    subsets = {"all": val}
    if skagen:
        subsets["skagen"] = [p for p in val if p.name in skagen]
        subsets["new regions"] = [p for p in val if p.name not in skagen]

    ymls = {}
    for name, imgs in subsets.items():
        if not imgs:
            continue
        d = dataset.parent / f"compare_{name.replace(' ', '_')}"
        for kind in ("images", "labels"):
            shutil.rmtree(d / "val" / kind, ignore_errors=True)
            (d / "val" / kind).mkdir(parents=True)
        for p in imgs:
            shutil.copy(p, d / "val" / "images" / p.name)
            shutil.copy(dataset / "val" / "labels" / f"{p.stem}.txt", d / "val" / "labels" / f"{p.stem}.txt")
        ymls[name] = d / "data.yaml"
        ymls[name].write_text(yaml.safe_dump({"path": str(d.resolve()), "train": "val/images",
                                              "val": "val/images",
                                              "names": {i: n for i, n in enumerate(NAMES)}}))

    rows = []
    for model, w in weights.items():
        for name, yml in ymls.items():
            m = YOLO(str(w)).val(data=str(yml), imgsz=imgsz, batch=8, plots=False, verbose=False)
            ap = dict(zip(m.box.ap_class_index.tolist(), m.box.ap50.tolist()))
            rows.append({"model": model, "tiles": name, "n": len(subsets[name]),
                         "mAP50": round(m.box.map50, 3), "vessel": round(ap.get(0, float("nan")), 3),
                         "sts": round(ap.get(1, float("nan")), 3), "recall": round(m.box.mr, 3)})
    import pandas as pd
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    return table
