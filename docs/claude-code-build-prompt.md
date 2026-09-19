# Claude Code Build Prompt — Dark Ship-to-Ship Transfer Detection System

Copy everything below the line into Claude Code (in your project folder) as your starting instruction.

---

## PROMPT TO PASTE INTO CLAUDE CODE

I'm building a student research project: a system that detects "dark" ship-to-ship
cargo transfers (ships that turn off their AIS tracking to hide illegal transfers)
using free Sentinel-1 SAR satellite imagery cross-checked against free AIS tracking
data from Global Fishing Watch. Base paper for reference:
https://arxiv.org/abs/2404.07607 (Ballinger, 2024) — I am reproducing its idea but
with free Sentinel-1 SAR imagery instead of paid PlanetScope imagery, plus adding
a suspicion-scoring layer.

I want you to build this with me in STRICT PHASES. Do not skip ahead or combine
phases. After finishing each phase:
1. Write a short SMOKE TEST script (or exact manual steps if it needs my
   credentials/GUI action) that proves that phase's output is correct.
2. Run the smoke test yourself if possible and show me the result.
3. STOP and summarize in plain language: what you built, what the smoke test
   showed, and what could go wrong. Then WAIT for me to say "continue" before
   starting the next phase.

Set up the project with a clean folder structure from the start:
```
project/
  data/raw_sar/
  data/processed_sar/
  data/tiles/
  data/xview3/
  data/ais/
  models/
  src/
  notebooks/
  outputs/dashboard/
  tests/
```

Use Python 3.11+, and prefer: rasterio, geopandas, ultralytics (YOLOv8), requests,
folium, geopy, pytest. Explain any dependency before installing it.

---

### PHASE 0 — Environment & scaffolding
Goal: working Python environment, folder structure, dependency list, config file
for storing my Copernicus and Global Fishing Watch API credentials (as
environment variables, never hardcoded).

Smoke test: a script `tests/test_env.py` that imports every core library and
prints "Environment OK" plus each library's version.

---

### PHASE 1 — Sentinel-1 data acquisition
Goal: a script `src/download_sentinel.py` that, given a bounding box and date
range, queries the Copernicus Data Space Ecosystem and downloads Sentinel-1 GRD
products. Use the `cdsetool` library (not the deprecated `sentinelsat`, which
targets the old shut-down hub). Handle authentication via env vars
`CDSE_USERNAME` / `CDSE_PASSWORD`.

Ask me for my target bounding box before writing the download logic — I'll give
you the strait/chokepoint coordinates.

Smoke test: download exactly ONE small Sentinel-1 product for a 1-week date
range and confirm the file exists, has a non-zero size, and can be opened with
rasterio without error.

---

### PHASE 2 — SAR preprocessing pipeline
Goal: a script `src/preprocess_sar.py` that takes a raw Sentinel-1 GRD product
and applies: radiometric calibration → speckle filtering (Refined Lee) →
terrain correction, producing a clean GeoTIFF. Use ESA SNAP's `gpt` command-line
tool invoked via Python subprocess (I will install SNAP separately and give you
the path to `gpt`). If SNAP is not available, fall back to a documented
Python-only approximation using `rasterio` + `scipy` for basic calibration and
a median/Lee filter for speckle reduction, and clearly tell me this is a lower
quality fallback.

Smoke test: process the one sample file from Phase 1, then generate a
side-by-side PNG (before/after) so I can visually confirm the speckle noise is
reduced and the image still looks like a coherent radar scene.

---

### PHASE 3 — Tiling
Goal: `src/tile_image.py` that cuts a processed SAR GeoTIFF into 512x512 tiles,
preserving georeferencing metadata for each tile, saving only tiles that
contain actual data (skip empty/nodata tiles).

Smoke test: run on the Phase 2 output, report how many tiles were generated,
open 3 random tiles and save them as PNGs so I can visually check they look
like valid image crops (not blank/corrupted).

---

### PHASE 4 — xView3-SAR dataset + label conversion
Goal: I will manually download a subset of xView3-SAR (after registering at
https://iuu.xview.us/dataset) into `data/xview3/`. Write
`src/convert_xview3_labels.py` that converts their point-based lat/lon vessel
labels into YOLO-format bounding box `.txt` files (fixed-size box per point,
default 20x20 pixels — make this configurable), using each image's
georeferencing to convert lat/lon to pixel coordinates.

Smoke test: pick 3 converted images, draw the generated bounding boxes back
onto the image using OpenCV/PIL, and save them as PNGs so I can visually verify
the boxes actually land on ships and not empty water.

---

### PHASE 5 — Train ship detector on xView3-SAR
Goal: `src/train_detector.py` using Ultralytics YOLOv8 (start from `yolov8n.pt`),
training on the converted xView3 subset. Include a `data.yaml` config.

Smoke test: train for just 3 epochs first (not full training) as a sanity
check — confirm training loss decreases across those 3 epochs and the script
completes without error before I approve a full training run.

---

### PHASE 6 — Fine-tune on my target strait
Goal: `src/finetune_detector.py` that continues training the Phase 5 model on
a small set of manually-labeled tiles from MY chosen strait (I will label a
handful myself using a tool you recommend, e.g. LabelImg or Roboflow's free
tier — tell me which is easier for a beginner).

Smoke test: run inference with both the pre-fine-tune and post-fine-tune model
on the same held-out tile, save both prediction images side by side so I can
visually compare detection quality.

---

### PHASE 7 — AIS data pipeline
Goal: `src/fetch_ais.py` that queries the Global Fishing Watch API for AIS
vessel positions in my bounding box/date range (I will provide my API token as
`GFW_API_TOKEN` env var), and saves results as a clean CSV
(lat, lon, timestamp, vessel_id).

Smoke test: fetch one day of data, print row count, and print the first 5 rows
so I can confirm the data looks sane (real-looking lat/lon values within my
bounding box, plausible timestamps).

---

### PHASE 8 — Cross-verification: satellite detections vs AIS ("dark ship" logic)
Goal: `src/dark_ship_check.py` implementing the space+time matching logic: for
each satellite-detected ship, check if any AIS record is within a configurable
distance (default 2km) and time window (default 30min). No match = flag as dark.

Smoke test: build a small synthetic test in `tests/test_dark_ship_logic.py`
with 3 fake cases — (1) a detection with a matching nearby AIS point → should
NOT be flagged dark, (2) a detection with no nearby AIS point at all → SHOULD
be flagged dark, (3) a detection with an AIS point nearby but outside the time
window → SHOULD be flagged dark. Run this with pytest and show me all 3 pass.

---

### PHASE 9 — Ship-to-ship transfer event detection + suspicion scoring
Goal: `src/sts_events.py` that pairs up dark ships that are close together
(configurable distance threshold, default 100m) and persistent over time
(default 30+ min), and `src/suspicion_score.py` implementing the scoring
function (dark duration, proximity to sanctioned zones, distance from normal
shipping lanes, time of day). Ask me for the list of sanctioned
zones/ports I want to use before hardcoding anything.

Smoke test: `tests/test_sts_events.py` with synthetic paired-ship data,
confirming an obvious "transfer-like" pair gets flagged and an obviously
unrelated pair (far apart, brief) does not.

---

### PHASE 10 — Dashboard
Goal: `src/dashboard.py` generating a Folium map (`outputs/dashboard/map.html`)
plotting all flagged dark-ship events, color-coded by suspicion score, with
popups showing details.

Smoke test: run it on my synthetic Phase 9 test data first (before real data
is fully ready), open the HTML, confirm markers appear in the right rough
location and popups display correctly.

---

### PHASE 11 — End-to-end integration test
Goal: a single `src/run_pipeline.py` that chains Phases 1–10 together for one
small area/date range, end to end.

Smoke test: run the full pipeline on the smallest possible real slice of data
(1 image, 1 day of AIS) and confirm it completes without crashing and produces
a dashboard file, even if the result is "no dark ships found" (that's still a
valid, correct outcome for a small/quiet test slice).

---

**Do not proceed past Phase 0 until I confirm.** Start now by asking me for:
1. My target strait/chokepoint bounding box coordinates
2. Confirmation of whether I already have SNAP installed (for Phase 2)
3. Confirmation I've registered for Copernicus, xView3, and Global Fishing
   Watch API access

---

## How to use this doc

- Paste the whole prompt section above into Claude Code as your first message in a fresh project folder.
- After each phase, actually run the smoke test yourself too (don't just trust the report) — open the PNG, open the dashboard HTML, read the pytest output.
- If a smoke test fails or looks wrong, tell Claude Code exactly what looks off before saying "continue" — don't let it move to the next phase on a shaky foundation, especially Phase 2 (preprocessing) and Phase 4 (label conversion), since every later phase depends on those being correct.
- Keep this file in your repo (e.g. as `PROJECT_PLAN.md`) so you and Claude Code can both refer back to which phase you're on.
