"""Search worker on Modal: one box + a time period in, ships per pass out (docs/DEPLOYMENT_PLAN.md).

    modal deploy modal_worker.py                                   # app "darksts-worker"
    modal run modal_worker.py --start 2026-09-15 --end 2026-09-30  # try it from the terminal

The backend (Render, step 2) calls it by name and never needs the model itself:

    period = modal.Function.from_name("darksts-worker", "search_period")
    call = period.spawn(box, start, end, job_id)       # returns at once
    status = worker.status(job_id)                     # webapp/backend/worker.py: progress Dict
    result = modal.FunctionCall.from_id(call.object_id).get(timeout=0)   # when done

These are plain Modal functions, not public web endpoints: only a caller holding the
Modal token (the backend) can start them.
"""
import time

import modal

from modal_app import ais, image as base_image, values

image = base_image.add_local_file("modal_app.py", "/root/modal_app.py")
app = modal.App("darksts-worker")
cache = modal.Volume.from_name("darksts-worker-cache", create_if_missing=True)
progress = modal.Dict.from_name("darksts-progress", create_if_missing=True)
models = modal.Volume.from_name("darksts-models", create_if_missing=True)   # scripts/upload_model.py

MODEL_REPO = "Jaswanth-K/darksts-detector"    # best.pt = YOLO26n trained in Colab
PARALLEL = 4                                    # = src.plan.PARALLEL (src is not importable at deploy time)


def _setup():
    import os
    import sys
    sys.path.insert(0, "/app")
    os.chdir("/app")
    from src import regional_ais
    regional_ais.before_read = ais.reload        # see rows the scheduled Gulf recorder committed


def _describe(e):
    """'HTTP 429 from gateway.api.globalfishingwatch.org' rather than a bare 'HTTPError'."""
    resp = getattr(e, "response", None)
    if resp is not None and getattr(resp, "url", None):
        from urllib.parse import urlparse
        return f"HTTP {resp.status_code} from {urlparse(resp.url).netloc}"
    return type(e).__name__


def _put(job_id, key, **kw):
    try:
        progress[f"{job_id}:{key}"] = {**kw, "t": time.time()}
    except Exception:
        pass                                     # progress is a convenience; never fail a search on it


def _weights():
    from pathlib import Path
    weights = Path("/models/best.pt")             # uploaded straight from Colab (scripts/upload_model.py)
    if not weights.exists():                      # fallback: the Hugging Face model repo
        from huggingface_hub import hf_hub_download
        weights = Path(hf_hub_download(MODEL_REPO, "best.pt", cache_dir="/cache/hf"))
    return weights


@app.function(image=image, cpu=2, memory=4096, timeout=300, volumes={"/cache": cache, "/models": models},
              max_containers=2, scaledown_window=120)
def detect_tile(data: bytes):
    """The website's "Run detection" on one uploaded image (the Render backend has no model)."""
    _setup()
    from src import search
    return search.detect_upload(data, _weights())


@app.function(image=image, cpu=2, memory=4096, timeout=900, secrets=[modal.Secret.from_dict(values)],
              volumes={"/cache": cache, "/app/ais": ais, "/models": models}, max_containers=PARALLEL,
              scaledown_window=300)
def search_pass(item, box, job_id, index):
    """One Sentinel-1 pass of a period search; errors come back as a value, not an exception."""
    _setup()
    from src import search
    weights = _weights()
    t = item["properties"]["datetime"][:16].replace("T", " ")
    _put(job_id, index, stage=f"{t} UTC: starting", progress=0.0, scene=item["id"])
    try:
        out = search.run_pass(item, box, weights, cache="/cache/search",
                              progress=lambda stage, frac: _put(job_id, index, stage=f"{t} UTC: {stage}",
                                                                progress=frac, scene=item["id"]))
        import hashlib
        out["model"] = {"source": "modal volume darksts-models" if str(weights).startswith("/models/")
                        else f"huggingface {MODEL_REPO}",
                        "sha256": hashlib.sha256(open(weights, "rb").read()).hexdigest()[:16]}
        if not out.get("ais_available"):
            out["scene_note"] = ("No AIS could be fetched for this pass (Global Fishing Watch had no data for it "
                                 "yet, publishing runs a few days behind, or was busy), so its ships are shown "
                                 "unchecked rather than as having no AIS.")
        cache.commit()
        _put(job_id, index, stage=f"{t} UTC: done", progress=1.0, scene=item["id"])
        return out
    except Exception as e:
        msg = str(e) if isinstance(e, (ValueError, LookupError)) else _describe(e)
        _put(job_id, index, stage=f"{t} UTC: failed ({msg})", progress=1.0, scene=item["id"], error=True)
        return {"scene": {"id": item["id"], "time": item["properties"]["datetime"]}, "error": msg}


@app.function(image=image, cpu=1, memory=1024, timeout=6 * 3600, secrets=[modal.Secret.from_dict(values)],
              volumes={"/app/ais": ais})
def search_period(box, start, end, job_id):
    """Every pass of a period over a box of any size: (pass, cell) units in parallel, merged per pass,
    then search.combine(...). The only ceiling is plan.MAX_UNITS (the website shows the estimate first)."""
    _setup()
    from src import plan, search
    try:
        box = search.validate(box, max_km=None)
        a, b = search.validate_period(start, end, max_days=None)
        p = plan.make_plan(box, a, b)
        if p["estimate"]["over_limit"]:
            raise ValueError(f"This search is {p['units']} pieces of work; the limit is {plan.MAX_UNITS}. "
                             "Pick a shorter period or a smaller area.")
    except (ValueError, LookupError) as e:
        _put(job_id, "job", status="error", error=str(e))
        raise
    units = [(k, it, core) for k, ps in enumerate(p["passes"]) for it, core in ps["units"]]
    meta = dict(passes=p["passes_found"], found=p["passes_found"], units=[k for k, _, _ in units],
                times=[ps["item"]["properties"]["datetime"][:16].replace("T", " ") for ps in p["passes"]])
    _put(job_id, "job", status="running", **meta)
    results = list(search_pass.starmap([(it, plan.grow(core, box), job_id, u)
                                        for u, (k, it, core) in enumerate(units)]))
    per_pass = [search.merge_cells([r for r, (k2, _, _) in zip(results, units) if k2 == k],
                                   [c for k2, _, c in units if k2 == k]) for k in range(p["passes_found"])]
    out = search.combine(per_pass, found=p["passes_found"])
    out.update({"bbox": list(box), "period": [str(start), str(end)], "plan": plan.summary(p)})
    _put(job_id, "job", status="done", **meta)
    return out


def read_status(job_id):
    """Progress of a period search; the same reader the backend uses (webapp/backend/worker.py)."""
    from webapp.backend.worker import status
    return status(job_id)


@app.local_entrypoint()
def main(start: str = "2026-09-15", end: str = "2026-09-30", box: str = "56.35,25.05,56.65,25.35"):
    import uuid
    bbox = [float(v) for v in box.split(",")]
    job_id = uuid.uuid4().hex[:12]
    call = search_period.spawn(bbox, start, end, job_id)
    print(f"job {job_id}, call {call.object_id}")
    t0, last = time.time(), None
    while True:
        st = read_status(job_id)
        line = f"{st['status']} {st['progress']:.0%} | " + " | ".join(st["stages"])
        if line != last:
            print(f"{time.time() - t0:5.0f}s  {line}")
            last = line
        try:
            res = modal.FunctionCall.from_id(call.object_id).get(timeout=0)
            break
        except TimeoutError:
            time.sleep(5)
    print(f"\ndone in {time.time() - t0:.0f}s: {res['passes_searched']} of {res['passes_found']} passes, "
          f"{res['passes_failed']} failed")
    print("counts:", res["counts"])
    for p in res["passes"]:
        if "error" in p:
            print(f"  {p['scene']['time'][:16]}  FAILED: {p['error']}")
        else:
            print(f"  {p['scene']['time'][:16]}  {p['counts']}  AIS: {p.get('ais_available')}  {p.get('scene_note') or ''}")
    print("recurring AIS-unmatched spots:", res["recurring"][:5])
