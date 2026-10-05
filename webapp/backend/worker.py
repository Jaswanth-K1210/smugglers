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
    """{status, passes, progress 0..1, stages[] (one per pass)} from the worker's progress Dict.

    A pass of a large box runs as several cells ("units"); its line reads "3 of 9 areas done"."""
    import modal
    from concurrent.futures import ThreadPoolExecutor
    d = modal.Dict.from_name(PROGRESS, create_if_missing=True)
    job = d.get(f"{job_id}:job") or {"status": "queued"}
    n = job.get("passes") or 0
    units = job.get("units") or list(range(n))
    with ThreadPoolExecutor(16) as ex:           # one Dict read per unit; up to plan.MAX_UNITS of them
        each = list(ex.map(lambda u: d.get(f"{job_id}:{u}") or {"stage": "waiting", "progress": 0.0},
                           range(len(units))))
    stages = []
    for k in range(n):
        mine = [e for e, p in zip(each, units) if p == k]
        if len(mine) == 1:
            stages.append(mine[0]["stage"])
            continue
        done = sum(e.get("progress", 0.0) >= 1 for e in mine)
        failed = sum(bool(e.get("error")) for e in mine)
        t = (job.get("times") or [""] * n)[k]
        state = "waiting" if not any(e.get("progress") for e in mine) else f"{done} of {len(mine)} areas done"
        stages.append(f"{t} UTC: {state}" + (f", {failed} failed" if failed else ""))
    done = sum(e.get("progress", 0.0) for e in each) / len(each) if each else 0.0
    return {"status": job.get("status", "queued"), "error": job.get("error"), "passes": n,
            "passes_found": job.get("found"), "units": len(units), "progress": round(done, 2), "stages": stages}


def result(call_id):
    """The finished result, or None while the call is still running. Raises if the call failed."""
    import modal
    try:
        return modal.FunctionCall.from_id(call_id).get(timeout=0)
    except TimeoutError:
        return None
