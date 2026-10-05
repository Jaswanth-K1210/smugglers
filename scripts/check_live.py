"""End-to-end check of the deployed site: website, API, model, outside data sources.

    python3 scripts/check_live.py [base_url] [--api]     # --api: backend only (Render)

Creates one throwaway account and runs one real search (~3 min). Prints PASS /
FAIL per check and exits non-zero if any check fails.
"""
import re
import secrets
import sys
import time

import requests

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
B = (ARGS[0] if ARGS else "https://jaswanth-k1210--darksts-web.modal.run").rstrip("/")
API_ONLY = "--api" in sys.argv          # Render backend: the website is on Vercel, not here
BOX = [56.35, 25.05, 56.65, 25.35]              # Fujairah anchorage, ~30 x 33 km: always busy
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def main():
    t = time.time()
    h = requests.get(f"{B}/api/health", timeout=180).json()
    check("server up, model available", h.get("search_available") is True, f"{time.time() - t:.0f}s, {h.get('status')}")

    if not API_ONLY:
        page = requests.get(B + "/", timeout=60)
        check("website served", page.ok and "<!doctype html" in page.text.lower())
        js = re.search(r'src="(/assets/[^"]+\.js)"', page.text)
        check("website script loads", bool(js) and requests.get(B + js.group(1), timeout=60).ok)

    probe = requests.get(B + "/..%2F..%2F..%2Fdata%2Fusers.db", timeout=60)
    check("private files not served", "SQLite" not in probe.text and "CREATE TABLE" not in probe.text)
    check("search refuses anonymous users", requests.post(f"{B}/api/search", json={"bbox": BOX},
                                                          timeout=60).status_code == 401)

    email, pw = f"check-{secrets.token_hex(4)}@example.org", secrets.token_urlsafe(12)
    r = requests.post(f"{B}/api/auth/register", json={"name": "Live check", "email": email, "password": pw}, timeout=60)
    check("sign up", r.ok, r.text[:80] if not r.ok else "")
    r = requests.post(f"{B}/api/auth/login", json={"email": email, "password": pw}, timeout=60)
    check("sign in", r.ok)
    H = {"Authorization": f"Bearer {r.json()['token']}"} if r.ok else {}
    check("session", requests.get(f"{B}/api/auth/me", headers=H, timeout=60).json().get("user", {}).get("email") == email)

    ev = requests.get(f"{B}/api/events", headers=H, timeout=60)
    check("precomputed results", ev.ok and len(ev.json().get("features", [])) > 0)
    news = requests.get(f"{B}/api/news", timeout=60)
    check("news feed", news.ok and isinstance(news.json().get("items"), list), f"{len(news.json().get('items', []))} items")
    live = requests.get(f"{B}/api/live", headers=H, timeout=60)
    check("live AIS feed", live.ok, f"connected={live.json().get('connected')}, in view={live.json().get('in_view')}")

    bad = requests.post(f"{B}/api/search", json={"bbox": [56.4, 25.1, 56.41, 25.11]}, headers=H, timeout=60)
    check("tiny box refused with a reason", bad.status_code == 422 and "at least" in bad.json().get("detail", ""))
    if API_ONLY:                                  # worker mode: any size and period, estimated before Go
        est = requests.post(f"{B}/api/search/estimate", headers=H, timeout=120,
                            json={"bbox": [55.8, 25.3, 57.25, 26.8], "start": "2026-09-06", "end": "2026-10-05"})
        e = est.json() if est.ok else {}
        check("145 x 166 km, 30 days: estimated, not refused", est.ok and e.get("units", 0) > 0,
              f"{e.get('passes')} passes, {e.get('cells')} cells, {e.get('units')} units, ~{e.get('minutes')} min, "
              f"${e.get('usd')}" if est.ok else est.text[:120])

    job = requests.post(f"{B}/api/search", json={"bbox": BOX}, headers=H, timeout=120)
    check("search starts", job.ok, job.text[:80] if not job.ok else "")
    if not job.ok:
        return
    job_id, t, last = job.json()["job_id"], time.time(), None
    while time.time() - t < 900:
        j = requests.get(f"{B}/api/search/{job_id}", headers=H, timeout=60).json()
        if j.get("stage") != last:
            print(f"        {time.time() - t:4.0f}s  {j.get('stage')}")
            last = j.get("stage")
        if j["status"] in ("done", "error"):
            break
        time.sleep(3)
    check("search finishes", j["status"] == "done", j.get("error") or f"{time.time() - t:.0f}s")
    if j["status"] != "done":
        return
    res = j["result"]
    # single pass (all-in-one site) or a period of passes (Render + Modal worker)
    passes = [p for p in res.get("passes", [res]) if "error" not in p]
    if "passes" in res:
        check("period search: passes searched", res["passes_searched"] > 0 and res["passes_failed"] == 0,
              f"{res['passes_searched']} of {res['passes_found']} found, {res['passes_failed']} failed")
    ships = [s for p in passes for s in p["ships"]]
    check("model found ships", len(ships) > 0, f"{res['counts']}")
    check("every ship has reasons", all(s["reasons"] for s in ships))
    text = " ".join(" ".join(s["reasons"]) for s in ships).lower()
    check("no 'dark' wording", "dark" not in text)
    check("radar chips attached", any(s.get("chip_png") for s in ships))
    for p in passes:
        print(f"        scene {p['scene']['time']}  {p.get('scene_note') or ''}")


if __name__ == "__main__":
    main()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
