# Deployment plan: Vercel (website) + Render (API) + Modal (model)

Written 2026-10-05. Goal: the user draws an area **and picks a time period** in the
website; the search runs on Modal with our Colab-trained YOLO26n and the result comes
back to the page.

**Verdict: possible, and a good fit for Modal.** Modal is built for exactly this split:
a light web server elsewhere calls a Modal function by name, Modal runs the heavy work
on its own machines and keeps the result until the caller collects it.

---

## 1. Architecture

```
 Browser
   │  draws box, picks dates, polls progress
   ▼
 VERCEL  (static React build, free Hobby plan)
   │  HTTPS, Authorization: Bearer <token>
   ▼
 RENDER  (FastAPI, free web service)            ┌───────────────────────────┐
   - accounts, sign-in, rate limits             │ Postgres (Neon/Supabase,  │
   - POST /api/search  → spawns Modal job ─────►│ free): users, search log  │
   - GET  /api/search/{id} → reads progress     └───────────────────────────┘
   - live AIS map feed, news, precomputed results
   │  Modal Python client (MODAL_TOKEN_ID / MODAL_TOKEN_SECRET)
   ▼
 MODAL  (functions, $30/month free credits)
   - search_pass(item, box)   one Sentinel-1 pass: download, YOLO26n, AIS match, reasons
   - search_period(box, start, end)  picks passes in the period, fans out search_pass
   - progress written to a modal.Dict, results returned to the caller
   - weights: Hugging Face model repo Jaswanth-K/darksts-detector (best.pt = Colab YOLO26n)
   │
   ├─► Planetary Computer (Sentinel-1 images)
   ├─► Global Fishing Watch (AIS presence, GFW radar detections, gap events)
   └─► Gulf AIS recorder volume (scheduled Modal function, already running)
```

### Who does what

| Piece | Runs on | Why there |
| ----- | ------- | --------- |
| Website | Vercel | static files on a CDN: fast everywhere, free, deploys on every git push |
| API, accounts, job tracking | Render | small always-reachable server; no ML libraries needed any more |
| Model + image processing | Modal | needs 2-4 CPUs (or a GPU) and ~1 GB per search for 1-2 min; pay only while running |
| Users database | Neon or Supabase Postgres | Render's free disk is wiped on every restart, so accounts cannot live there |
| Model weights | Hugging Face model repo | free versioned storage of the Colab-trained `best.pt`; Modal downloads it |

### What changes compared with today

Today everything (website, API, model) is one Modal app at
`https://jaswanth-k1210--darksts-web.modal.run`, with an in-memory job table. In the new
split:

- **Render no longer imports torch, ultralytics or rasterio.** Its image drops from ~2 GB
  to ~150 MB and fits Render's 512 MB free instance.
- **Jobs live in Modal, not in server memory.** `Function.spawn()` returns a call id;
  Render stores it and asks Modal for status. A Render restart no longer loses searches,
  and the "one container only" limit of the current design goes away.
- **Searches can run in parallel.** Each pass in a time period runs in its own Modal
  container, 3 at a time (outside services rate-limit wider fan-out).

---

## 2. The time-period feature

Today the search uses the newest pass over the box that already has AIS. With a period:

1. The user picks a box of **any size** (at least 11 km a side) and a date range of
   **any length** (changed 2026-10-06; the first version capped 60 km and 31 days / 6 passes).
2. `src/plan.py` cuts the box into cells of at most 50 km and lists every Sentinel-1
   pass in the range (STAC slices ~25 s apart are one pass). Each cell goes to the
   slice whose **real footprint** covers it best, if that is >= 50 %. One (pass, cell)
   is one **unit** of work.
3. Before Go, `POST /api/search/estimate` returns passes, cells, units, minutes and
   about how much Modal credit it uses (~$0.004 a unit); the website shows it. The only
   ceilings are on work, not shape: `SEARCH_MAX_UNITS` per search (default 200, ~1.6 h)
   and `SEARCH_DAILY_UNITS` per account per day (default 400). Example: a 145 x 166 km
   box over 30 days in the Gulf is 18 passes, 142 units, about 70 minutes, ~$0.58.
4. Each unit runs `search_pass` on its cell grown by 0.6 km, 4 in parallel (`search.run_pass`,
   the same logic as the single-pass search). `search.merge_cells` keeps each ship and
   pair only from the cell whose core contains it, so a hull on a cell edge counts once.
5. The page shows a **timeline**: one dot per pass, with ship and no-AIS counts; clicking
   a pass shows its ships on the map. A ship seen without AIS on several passes at the
   same spot is flagged as "recurring" (likely a fixed structure or a ship at anchor).

AIS availability by date, shown to the user per pass:

| Pass date | AIS used | Note |
| --------- | -------- | ---- |
| older than ~5 days | GFW presence (2012 onward) | normal case |
| last ~5 days | Gulf recorder only, if inside the Gulf box; else none | GFW publishes with a lag; ships are shown "unchecked", never "no AIS" |
| before 2026-10-04 in the Gulf | GFW only | the recorder started on 2026-10-04 |

Sentinel-1 archive on Planetary Computer goes back to 2014, so any past period works.

---

## 3. API contract (Render)

```
POST /api/search          {"bbox": [w, s, e, n], "start": "2026-09-01", "end": "2026-09-30"}
  → 200 {"job_id": "...", "passes": 5}
  → 422 box or dates out of range (sentence the user can act on)
  → 429 quota (one running search per user, 20 per day)

GET  /api/search/{job_id}
  → {"status": "running", "stage": "Pass 3 of 5: detecting ships", "progress": 0.55}
  → {"status": "done", "result": {"passes": [ {scene, time, counts, ships, sts, note}, ... ],
                                  "recurring": [...], "counts": {...}}}
  → {"status": "error", "error": "The satellite image server is limiting requests ..."}
```

Render → Modal, in code:

```python
import modal
period = modal.Function.from_name("darksts-worker", "search_period")
call = period.spawn(box, start, end, job_id)          # returns at once
# later, on GET:
progress = modal.Dict.from_name("darksts-progress")[job_id]
try:
    result = modal.FunctionCall.from_id(call.object_id).get(timeout=0)
except TimeoutError:
    ...  # still running: return progress
```

The Modal functions are **not public web endpoints**: only Render, holding the Modal
token, can call them. Users never talk to Modal directly.

---

## 4. Timing (what the user waits for)

| Step | Time |
| ---- | ---- |
| Render wakes from sleep (free tier sleeps after 15 min idle) | ~30-60 s, first request only |
| Modal container cold start (image + model download) | ~20-40 s, first search after idle |
| One pass: find + download + detect + AIS + reasons | ~60-120 s (measured 52-99 s live) |
| A period of 6 passes, 3 at a time (measured 2026-10-05) | **~5.5 min** (324 s for 15-30 Sep, Fujairah) |

So: **1-2 minutes for a single pass, ~3 minutes for up to 3 passes, ~5-6 minutes for 6**,
plus up to ~1.5 minutes when Render and Modal are both asleep. Running all 6 at once
would bring a period back to ~2 minutes, but GFW and Planetary Computer rate-limit
wide fan-out (both seen in this project), so 3 at a time is the safe default
(`PARALLEL` in `modal_worker.py`). The page shows each pass as it finishes, so the
user sees results from the first wave after ~2 minutes.
Open the site a minute before a demo. An optional Modal GPU (T4) cuts the detection part
from ~10-30 s to ~2-5 s, but downloading the image dominates, so it is not needed.

---

## 5. Cost (all free tiers)

| Service | Plan | Limit that matters | Our use |
| ------- | ---- | ------------------ | ------- |
| Vercel | Hobby (free) | bandwidth, non-commercial | static site, tiny |
| Render | Free web service | sleeps after 15 min idle; 512 MB RAM; disk wiped on restart; 750 instance-hours/month | API only, fits |
| Neon or Supabase | Free Postgres | ~0.5 GB storage | users and search log, tiny |
| Modal | Starter, $30/month credit | pay per CPU-second | ~$0.004 per pass, so ~1,000 six-pass searches/month |
| Hugging Face | free model repo | none relevant | weights storage |

Free-tier terms change; check each provider's pricing page when deploying. Keep **no card
on Modal** (usage stops at the free credit) or set a budget if a card is added.

---

## 6. Risks and how they are handled

| Risk | Effect | Handling |
| ---- | ------ | -------- |
| Render free sleeps | first request slow | page shows "waking the server"; warm it before demos |
| Render disk wiped | accounts lost | users in Neon/Supabase Postgres, not SQLite |
| Live AIS websocket on Render stops while asleep | map empty right after wake | refill in ~1 min; or move the live feed into a small always-on Modal function |
| GFW rate limits (seen) | AIS check slow/fails | retries with backoff; passes marked "unchecked"; fewer parallel passes (max 3 at once) |
| Planetary Computer refuses tokens (seen from Modal) | pass fails | retries; free PC key `PC_SDK_SUBSCRIPTION_KEY`; clear message |
| Three services instead of one | more to configure | one env-var table (§8) and `scripts/check_live.py` extended to the new URLs |
| Long periods cost credit | budget | 31-day / 6-pass cap, 20 searches per user per day |

---

## 7. Work plan

Each step ends with tests green and, from step 3, `check_live.py` passing.

| # | Step | Code | Effort |
| - | ---- | ---- | ------ |
| 1 | **Modal worker app** `modal_worker.py`: `search_pass`, `search_period`, progress Dict; reuse `src/search.py` split into per-pass and per-period parts | **done 2026-10-05**: deployed as `darksts-worker`, 6-pass period searched in 324 s | half a day |
| 2 | **Backend for Render**: `webapp/backend/app.py` spawns Modal jobs instead of the in-memory executor; Postgres for users (`DATABASE_URL`); CORS for the Vercel domain; slim `requirements-render.txt` (no torch) | edit | half a day |
| 3 | **Deploy Render**: web service from the GitHub repo, start command `uvicorn webapp.backend.app:app --host 0.0.0.0 --port $PORT`, env vars from §8 | config | 1 hour |
| 4 | **Frontend**: API base URL from `VITE_API_URL`; date-range picker next to "draw area"; timeline of passes; longer timeout for the first request (cold starts) | edit | half a day |
| 5 | **Deploy Vercel**: project root `webapp/frontend`, build `npm run build`, output `dist`, env `VITE_API_URL=https://<render-app>.onrender.com/api` | config | 30 min |
| 6 | **Tests**: period limits, pass selection, Modal spawn/poll mocked, recurring-object flag; `check_live.py` against Vercel + Render URLs | tests | half a day |
| 7 | Keep the current all-in-one Modal app running until step 6 passes, then retire it | - | - |

About 2-3 days of work in total.

---

## 8. Environment variables

| Where | Variable | Value / source |
| ----- | -------- | -------------- |
| Vercel | `VITE_API_URL` | `https://<render-app>.onrender.com/api` |
| Render | `DATABASE_URL` | from Neon/Supabase |
| Render | `AUTH_SECRET` | long random string (set once, keep) |
| Render | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | Modal dashboard → API tokens |
| Render | `ALLOWED_ORIGINS` | `https://<project>.vercel.app` |
| Render | `AISSTREAM_API_KEY` | optional, live map |
| Modal | `GFW_API_TOKEN` | from `.env`, sent at deploy (as today) |
| Modal | `HF_MODEL_REPO` | `Jaswanth-K/darksts-detector` |
| Modal | `PC_SDK_SUBSCRIPTION_KEY` | optional, free Planetary Computer key |

Secrets go only into each provider's settings or the local `.env`, never into git or chat.

---

## 9. Simpler alternative (for comparison)

Keep what runs today: one Modal app serves the website, the API and the model from one
URL, and add the time-period feature to it. Less to configure and no cold start stacking
(one service sleeps, not two). The split above is better when the website should load
instantly from a CDN, when accounts must survive anything, and when the report should
show a clean three-tier design. Both use the same Colab-trained model from Hugging Face.
