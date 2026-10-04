"""Scene-level recall of the served detector against AIS, on Modal (see src/evaluate.py).

    modal run modal_eval.py                       # 30 Gulf of Oman passes, Jul-Sep 2026
    modal run modal_eval.py --n 50 --region laconia

Each pass runs in its own container; results land in outputs/eval_<region>.json
and the tables are printed.
"""
import json
from pathlib import Path

import modal

from modal_app import image as base_image, values

# the container re-imports this file, which imports modal_app: ship it alongside
image = base_image.add_local_file("modal_app.py", "/root/modal_app.py")
app = modal.App("darksts-eval")


@app.function(image=image, cpu=2, memory=4096, timeout=1800, secrets=[modal.Secret.from_dict(values)],
              max_containers=3, env={"GFW_RETRY_WAIT": "30"})   # GFW rate-limits 10 parallel callers
def scene(item, box):
    import os
    import sys
    sys.path.insert(0, "/app")
    os.chdir("/app")
    from huggingface_hub import hf_hub_download
    from src import evaluate
    weights = hf_hub_download(os.environ.get("HF_MODEL_REPO", "Jaswanth-K/darksts-detector"), "best.pt",
                              cache_dir="/tmp/hf")
    try:
        return evaluate.scene_eval(item, box, weights)
    except Exception as e:                       # one bad pass must not sink the run
        return {"scene": item["id"], "error": f"{type(e).__name__}: {e}"}


@app.local_entrypoint()
def main(n: int = 30, region: str = "oman", start: str = "2026-07-01", end: str = "2026-09-26"):
    import numpy as np
    from src import evaluate, fetch_s1
    from src.hunt import REGIONS
    box = REGIONS[region]
    items = [i for i in fetch_s1.search(start, end, box=box, limit=200) if fetch_s1.overlap(i, box) >= 0.5]
    pick = [items[k] for k in np.linspace(0, len(items) - 1, min(n, len(items))).round().astype(int)]
    print(f"{len(items)} passes cover >= 50 % of {region}; evaluating {len(pick)}")
    results = list(scene.starmap([(it, box) for it in pick]))
    bad = [r for r in results if "error" in r]
    good = [r for r in results if "error" not in r and r["rows"][0]["n_ais"] > 0]
    for r in bad:
        print("  skipped", r["scene"][:40], r["error"][:120])
    print(f"{len(good)} passes with visible AIS ships "
          f"({sum(r['rows'][0]['n_ais'] == 0 for r in results if 'error' not in r)} had none / no AIS yet)")
    table, shore, area = evaluate.summarise(good)
    print(f"\nTotal footprint searched: {area:,.0f} km2\n")
    print(table.to_string(index=False))
    print("\nRecall by distance from shore:")
    print(shore.pivot(index="threshold", columns="shore", values="recall").to_string())
    print("\nAIS ships per shore class (same at every threshold):")
    print(shore[shore.threshold == evaluate.THRESHOLDS[0]][["shore", "n_ais"]].to_string(index=False))
    pick = evaluate.select_threshold(table)
    best_f1 = table.loc[table.f1_vs_ais.idxmax()]
    print(f"\nselected threshold (highest recall with >= 60 % AIS-confirmed): {pick}")
    print(f"F1-vs-AIS maximum: threshold {best_f1.threshold}, F1 {best_f1.f1_vs_ais}")
    Path("outputs").mkdir(exist_ok=True)
    (Path("outputs") / f"calibration_yolo26n_{region}.json").write_text(json.dumps({
        "model": "yolo26n", "region": region, "period": [start, end], "scenes": len(good),
        "visible_ais_ships": int(table.n_ais.iloc[0]), "area_km2": round(area),
        "selected": pick, "table": table.to_dict(orient="records")}, indent=1))
    out = Path("outputs") / f"eval_{region}.json"
    out.write_text(json.dumps({"region": region, "box": box, "results": results}, default=str))
    print(f"\nsaved {out}")
