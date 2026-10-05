"""The backend's side of the Modal search worker (modal_worker.py, app "darksts-worker").

Only needs the `modal` client and MODAL_TOKEN_ID / MODAL_TOKEN_SECRET in the environment:
no model, no image libraries. Start a period search, read its progress from the shared
Dict, collect the result when it is ready.
"""
APP, FUNCTION, PROGRESS = "darksts-worker", "search_period", "darksts-progress"


def spawn(box, start, end, job_id):
    """Start a period search; returns the Modal call id to poll."""
    import modal
    call = modal.Function.from_name(APP, FUNCTION).spawn(list(box), str(start), str(end), job_id)
    return call.object_id


def status(job_id):
    """{status, passes, progress 0..1, stages[]} from the worker's progress Dict."""
    import modal
    d = modal.Dict.from_name(PROGRESS, create_if_missing=True)
    job = d.get(f"{job_id}:job") or {"status": "queued"}
    n = job.get("passes") or 0
    each = [d.get(f"{job_id}:{k}") or {"stage": "waiting", "progress": 0.0} for k in range(n)]
    done = sum(p.get("progress", 0.0) for p in each) / n if n else 0.0
    return {"status": job.get("status", "queued"), "error": job.get("error"), "passes": n,
            "passes_found": job.get("found"), "progress": round(done, 2), "stages": [p["stage"] for p in each]}


def result(call_id):
    """The finished result, or None while the call is still running. Raises if the call failed."""
    import modal
    try:
        return modal.FunctionCall.from_id(call_id).get(timeout=0)
    except TimeoutError:
        return None
