# New Plan — Area-on-Demand Detection Website

Written 2026-09-30. Extends `PROJECT_PLAN.md` (Phases 0–9); does not replace it.
Nothing in `src/` changes meaning. The new work is wiring existing functions
behind a "select an area" website, plus one new data source for AIS outside
Denmark.

---

## 1. The goal

A user draws a box on a map. The site finds the latest Sentinel-1 pass over it,
runs our trained detector, checks each detected ship against AIS, and shows the
ships with no AIS match, each with plain-language reasons.

The model is trained and tested in Google Colab; the website only runs inference.

Wording rule (unchanged from `RESEARCH_POSITION.md` §4.2): the site says
**"no AIS match"**, never "dark ship". Absence of AIS is not proof of concealment.

---

## 2. What exists today

| Piece | Where | State |
| ----- | ----- | ----- |
| Sentinel-1 search + windowed download, any bbox | `src/fetch_s1.py` (`search`, `fetch`) | works, no account |
| Detector training + 4-model benchmark | `src/train.py`, `notebooks/04_train.ipynb` | code only, **never run** |
| Scene-wide detection | `src/run_pipeline.py` `detect()` | works once weights exist |
| False-positive filters | `src/filters.py` `clean_detections()` | tested |
| AIS matching (500 m / ±12 h) | `src/dark_sts.py` `characterise()` | tested |
| Explainable scoring | `src/score.py` (duration, sanctioned zone, lane deviation) | tested |
| GFW cross-check | `src/validate_gfw.py`, `src/gfw.py` | works, token set |
| AIS | `src/ais.py`, Danish Maritime Authority | **Denmark only**, ~650 MB/day |
| Website | `webapp/` FastAPI + Leaflet | precomputed results only, not deployed |

The gap: **no AIS outside Danish waters, and no on-demand path in the website.**

---

## 3. What we learned from similar projects

### World Monitor (worldmonitor.app, github.com/koala73/worldmonitor)

- Ship positions come from **aisstream.io**: a free, live AIS WebSocket
  (`wss://stream.aisstream.io/v0/stream`), subscribed by bounding box, API key
  from a free signup.
- They do **not** call it from the browser. An always-on Node process
  (`scripts/ais-relay.cjs`, hosted on Railway) holds the single WebSocket,
  keeps positions in Redis, and the website reads from that cache.
- They watch fixed **chokepoints** (Hormuz, Suez, Bab el-Mandeb, …), not the whole
  planet.
- They do **no satellite detection**. World Monitor shows vessels that *are*
  broadcasting. It cannot see a ship with AIS off. That is exactly the part our
  project adds.

**Lesson:** live AIS is free, but it is live-only. aisstream has no history, so to
match a satellite pass we must *record* AIS ourselves, continuously, for the areas
we care about. One connection per API key, so one recorder process.

### Skylight (Allen Institute for AI)

- Faster R-CNN on Sentinel-1 VV+VH, trained on ~55,000 hand-labelled points.
- Detections are labelled "AIS-correlated" or "dark" by matching nearby AIS
  points: the same idea as our `dark_sts.characterise()`.
- Model is open source: github.com/allenai/vessel-detection-sentinels. Useful as
  a **reference baseline** to compare our detector against.

### Global Fishing Watch SAR vessel detections

- Global Sentinel-1 vessel detections 2017 → ~5 days ago, already matched to AIS
  (`matched=false` = no AIS match). Served through the **4Wings API**, which our
  existing GFW token can call.
- Method: Paolo et al. 2024, *Nature*, "Satellite mapping reveals extensive
  industrial activity at sea": 72–76% of industrial fishing vessels are not
  publicly tracked.
- Use for us: an **independent answer to compare against** for any area, and an
  AIS-match fallback where we have no AIS of our own. Not a replacement for our
  detector, because then the project would have no model of its own.

### Datasets / papers to cite

- Ballinger 2024, IGARSS (arXiv:2404.07607): base paper, already in `docs/`.
- Paolo et al. 2022, **xView3-SAR**, NeurIPS Datasets & Benchmarks: ~1,000
  Sentinel-1 scenes with vessel labels, the largest public SAR vessel set. Fixes
  our biggest weakness (one training region). Free registration.
- Paolo et al. 2024, *Nature*: global scale, the "why this matters" citation.

---

## 4. Architecture

```
                    ┌───────────────────────────────┐
  aisstream.io ───► │ AIS recorder (always on)      │──► ais.sqlite
  (live, free)      │ watch-list bboxes only,       │    (rolling 14 days)
                    │ 1 fix / ship / minute         │
                    └───────────────────────────────┘
                                                     │
  Browser                                            ▼
  draw bbox ──► POST /api/jobs ──► worker:
                                    1. fetch_s1.search(latest pass, bbox)
                                    2. fetch_s1.fetch(window)
                                    3. run_pipeline.detect()  (trained weights, CPU)
                                    4. filters.clean_detections()
                                    5. AIS for the pass time, best available:
                                         a. DMA            (Danish waters)
                                         b. our recorder   (watch-list areas)
                                         c. GFW 4Wings     (anywhere, ~5 day lag)
                                    6. dark_sts.characterise()
                                    7. score.score()  → reasons
                                    8. cache by (scene_id, bbox)
             ◄── GET /api/jobs/{id}  (poll: queued / running / done)
  map shows ships + reasons + "AIS source used" + "image date"
```

Every result states **which AIS source** was used and **how old the image is**.
A match against GFW (weaker, delayed) must look different from a match against
recorded AIS.

---

## 5. Honest limits (put these on the site's About page)

1. **Not real time.** Sentinel-1 revisits a point every ~6–12 days; data reaches
   Planetary Computer hours to a day later. "Live" = latest pass.
2. **AIS coverage.** aisstream is terrestrial receivers, so it is strong near coasts
   and weak in open ocean. A "no AIS match" far offshore is often just coverage.
3. **Recorder only covers what it watched.** An area outside the watch list, with
   a pass before recording started, falls back to GFW or to "AIS unknown".
4. **Model trained on one region** until xView3 data is added. Say so.
5. **Free CPU is slow.** 30 s to a few minutes per area. Area size is capped.

---

## 6. Phases

Each phase ends with a check that proves it works. Numbering continues from
`PROJECT_PLAN.md`.

### Phase 10: Train the model (BLOCKER, do first)

- Run `notebooks/03_autolabel.ipynb` then `04_train.ipynb` in Colab (GPU).
- Save `best.pt` to Google Drive; copy to `models/darksts/weights/best.pt`.
- **Done when:** benchmark table printed, mAP reported on the held-out scene, and
  `deploy_choice()` names a model that runs < 3 s per 1024 px tile on CPU.

### Phase 11: More training regions (strongly recommended)

- Register for xView3-SAR; add a converter from xView3 point labels to YOLO boxes.
- Retrain in Colab on Skagen + xView3.
- **Done when:** the model is tested on a region it never saw in training, and
  that score is reported next to the in-region score.

### Phase 12: AIS recorder

- New `src/ais_live.py`: one aisstream WebSocket, subscribed to a watch list
  (start with 3–5 boxes: Skagen/Kattegat, Strait of Hormuz, Singapore Strait,
  Gulf of Laconia, one Indian area e.g. Gulf of Kutch).
- Store `mmsi, time, lat, lon, sog` in SQLite, thinned to 1 fix per ship per
  minute, delete rows older than 14 days.
- New `ais.load_recorded(start, end, box)` returning the same columns as
  `ais.load()`, so `dark_sts.characterise()` needs no change.
- Host: must be always on. Options: Oracle Cloud Always Free VM (free), or a
  small paid worker (Railway/Render ~US$5/mo). **Not** HF Spaces free, because it sleeps.
- **Done when:** after 24 h, the DB holds positions for every watch box, and a
  query for one box and hour returns ships.

### Phase 13: GFW fallback AIS

- In `src/gfw.py`: 4Wings report call for SAR detections (+ `matched` field) and
  AIS presence over bbox and date range.
- **Done when:** for a past Skagen scene, GFW's matched/unmatched split is shown
  beside ours (reuses `validate_gfw.agreement()` ideas).

### Phase 14: On-demand job API

- `POST /api/jobs {bbox}` → job id; `GET /api/jobs/{id}` → status and result.
- Worker = the eight steps in §4, calling existing functions.
- Guards: max bbox ~50×50 km; one job at a time (queue); cache by
  `(scene_id, bbox)`; timeout with a clear error.
- **Done when:** a test posts a small Skagen bbox and gets back GeoJSON with
  `category`, `suspicion`, `reasons`, `ais_source`, `image_time`.

### Phase 15: Reasons in plain language

- Turn each `score.py` term into a sentence, e.g.
  "No AIS position within 500 m in ±12 h (source: recorder)",
  "Stationary next to another vessel ≈ 6 h", "38 km from a sanctioned zone",
  "14 km outside usual shipping lanes", "Length ≈ 180 m (size class: large)".
- **Done when:** every result on the map has ≥ 1 reason and no output contains
  the word "dark" (existing test extended).

### Phase 16: Website UI

- Leaflet: draw-rectangle tool → submit → progress → results layer.
- Side panel per ship: image chip, reasons, AIS source, image date.
- Toggle layers: our detections / GFW SAR detections / recorded AIS tracks.
- Keep the existing precomputed Skagen view as the demo landing page.

### Phase 17: Deploy

- Website + worker: Hugging Face Spaces (Docker, 2 vCPU / 16 GB, free).
- Recorder: separate always-on host (Phase 12), exposing a read-only
  `/ais?bbox&start&end` endpoint the Space calls.
- **Done when:** a stranger can open the URL, draw a box in a watch area, and get
  a result in under ~3 minutes.

### Update 2026-10-02: deployment decision

- **AIS for the website comes from GFW 4Wings presence** (`gfw.ais_presence`, proven
  on Oman and Laconia), not the Phase 12 recorder. No always-on host is needed.
  Limit: GFW data lags a few days, so the newest scene may have no AIS yet; the
  thin-scene rule already refuses to call ships unmatched in that case.
- **Model:** retrained on Skagen + Oman + Laconia (`src/pseudo.py` turns
  AIS-confirmed detections into labels), weights pushed to a Hugging Face model
  repo.
- **Website:** Hugging Face Space (Docker, free CPU) loads the weights from the
  Hub at start-up; `GFW_API_TOKEN` is a Space secret.

---

## 7. Keys and accounts

| Key | Needed for | Who |
| --- | --- | --- |
| `GFW_API_TOKEN` | GFW cross-check + fallback | already set |
| `AISSTREAM_API_KEY` | recorder (Phase 12) | **get now**: free at aisstream.io (GitHub login) |
| xView3 account | extra training data (Phase 11) | register at iuu.xview.us |
| CDSE | not needed; Planetary Computer covers Sentinel-1. Keep the 30k PU/month for manual checks only | — |

Keys go in `.env`, never into chat or git.

---

## 8. Scope for the minor project

- **Must:** Phases 10, 12, 14, 15, 16 on the watch-list areas.
- **Should:** Phase 13 (GFW fallback) and 17 (deploy).
- **Stretch:** Phase 11 (xView3), any-area-on-earth.

---

## Sources

- World Monitor: https://www.worldmonitor.app — code: https://github.com/koala73/worldmonitor (`scripts/ais-relay.cjs`, `.env.example`)
- aisstream.io: https://aisstream.io
- Skylight Sentinel-1 model: https://github.com/allenai/vessel-detection-sentinels
- GFW 4Wings API: https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings
- GFW SAR detections dataset: https://globalfishingwatch.org/platform-update/2024-may-data-download-portal-new-dataset-released-featuring-vessel-detections-from-sentinel-1-sar/
- Paolo et al. 2022, xView3-SAR: https://arxiv.org/abs/2206.00897
- Paolo et al. 2024, Nature: https://pmc.ncbi.nlm.nih.gov/articles/PMC10764273
- Ballinger 2024: https://arxiv.org/abs/2404.07607
