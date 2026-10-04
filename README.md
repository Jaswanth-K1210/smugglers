# Dark Ship-to-Ship Transfer Detection

Detecting and characterising ship-to-ship (STS) transfers from **free, open data
only** — Sentinel-1 SAR imagery and AIS tracking — cross-checked against Global
Fishing Watch's independent layers.

B.Tech minor project, Anurag University. P. Ananya, S. Vinitha, K. Revanth Kumar,
K. Jaswanth. Guided by Padmapriya ma'am.

Base paper: Ballinger (2024), *Automatic Detection of Dark Ship-to-Ship Transfers
Using Deep Learning and Satellite Imagery*, IGARSS — [arXiv:2404.07607](https://arxiv.org/abs/2404.07607).

---

## What this does, and what it refuses to do

The pipeline detects vessels and STS configurations in SAR, then asks how much
AIS identity evidence stands behind each one:

```
2+ identities   AIS_VISIBLE      both partners broadcasting
1  identity     AIS_PARTIAL      one silent, or a timing / coverage / matching limit
0  identities   AIS_UNMATCHED    a candidate — nothing more
```

**Nothing here is called "dark".** Absence of AIS is absence of evidence about
AIS, not evidence of concealment: it may be reception, coverage, equipment
failure, or processing. A test asserts that no output column ever contains the
word. The reasoning is in `docs/RESEARCH_POSITION.md` §4.2, and §4.2.1 measures
it — GFW gap events are near-zero in every region with good coastal AIS
reception, and abundant only in a poorly-covered control.

**No credential is needed for imagery or AIS.** Only GFW requires a token.

---

## Status

| Phase | State | Evidence |
| ----- | ----- | -------- |
| 0 Environment, kill criterion | **PASS** | 1,093 vessels/day, 10 GFW encounters/yr in AOI |
| 1 AIS ingest + STS extraction | **PASS** | 42,557 raw events / 7 days; 188 at sea |
| 2 Sentinel-1 acquisition | **PASS** | Skagen anchorage imaged, ~30 ships at anchor |
| 3 Auto-labeling | **PASS** | 100% of boxes ≥20 dB over background (≥70% needed) |
| 4 Training | **done** (Colab) | Skagen RT-DETR; then multi-region (Skagen + Oman + Laconia), five detectors compared — RESULTS §3, §6, §6b |
| 5 False-positive control | code + tests | land, length, static-infrastructure masks |
| 6 Identity characterisation | code + tests | four specified cases pass |
| 7 Suspicion scoring | code + tests | triage order, not a probability |
| 8 Pipeline + dashboard | runs end to end | `outputs/events.geojson` |
| 9 Web deployment | **deployed** (Modal) | area-on-demand search, live AIS map, accounts |
| Region search | done | Gulf of Oman, Laconia; STS candidates with the one-hull rule — RESULTS §4c–4g |
| Recall vs AIS | measured | YOLO26n, 26 Fujairah passes: 71 % at the served 0.25 (calibration, not final accuracy) — RESULTS §7 |

159 backend tests and 12 frontend tests pass; `scripts/check_live.py` runs 18
end-to-end checks against the deployed site. Training needs a GPU and runs in
Colab (`torch` has no wheel for Python 3.13 on Intel macOS).

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add GFW_API_TOKEN and AOI_BBOX
pytest -q                     # 159 tests, no network or credentials needed
```

```bash
python -m src.ais        2025-06-08                    # AIS day → AOI extract
python -m src.ais_sts    2025-06-08                    # STS events
python -m src.fetch_s1   2025-06-01 2025-06-08         # Sentinel-1 scene + quick-look
python -m src.autolabel  data/sar_raw/<scene>.tif      # YOLO labels + chip sheet
python -m src.run_pipeline 2025-06-06 2025-06-08       # everything → outputs/
python -m src.dashboard                                # → outputs/dashboard/index.html
```

## The Colab loop

No local GPU is assumed, and for Phase 4 none is possible here.

```
Claude Code writes + commits  →  you push  →  Colab clones and runs the heavy step
        ↑                                              ↓
        └──────────  you paste back the full output  ──┘
```

| Notebook | Does | Needs GPU |
| -------- | ---- | --------- |
| `notebooks/03_autolabel.ipynb` | label + tile many scenes | no (network-heavy) |
| `notebooks/04_train.ipynb` | train, benchmark, validate | **yes** |
| `notebooks/05_pipeline.ipynb` | full pipeline + dashboard | no |

When something fails, paste the **entire traceback**, not the last line.

---

## Data sources

| Source | Auth | Used for |
| ------ | ---- | -------- |
| [Planetary Computer](https://planetarycomputer.microsoft.com/dataset/sentinel-1-grd) `sentinel-1-grd` | **none** | Sentinel-1 GRD |
| Danish Maritime Authority AIS (S3) | **none** | training labels, identity evidence |
| [Global Fishing Watch](https://globalfishingwatch.org/our-apis/) v3 | token | AIS presence outside Denmark, SAR detections, gap/encounter events, registry |
| hormuz.now, Open Waters, aisstream.io | none / free key | Gulf and live AIS for the map and matching |
| [Marine Regions](https://www.marineregions.org/) | none | territorial sea / EEZ context |
| Sentinel-2 L2A (Planetary Computer) | none | optical cross-check of STS candidates |

CDSE Sentinel Hub was the original plan and proved unusable — its OAuth endpoint
returned 503 throughout and registration never completed. Planetary Computer
mirrors the same ESA archive. Full record in `docs/DATA_SOURCE_DECISIONS.md`.

Two consequences, both deliberate and both treated as experiments (§3.4):
PC serves GRD in radar geometry with a GCP grid, so we warp it ourselves with
`WarpedVRT` to UTM 32N at 10 m — square metre pixels, no SNAP. And we work in
**raw DN**, not calibrated σ⁰, because thresholding needs relative contrast.

---

## Layout

```
src/
  config.py        .env-backed credentials and AOI
  ais.py           DMA AIS download (resumable), AOI extract
  ais_sts.py       STS events: 500 m / ≥1 h / both <1 kn
  fetch_s1.py      Planetary Computer STAC → windowed COG read → GCP warp
  autolabel.py     AIS → SAR labels, tiling, chip sheets
  filters.py       land, length and static-infrastructure masks
  train.py         scene-level split, training, model benchmark
  dark_sts.py      500 m / ±12 h identity characterisation
  validate_gfw.py  GFW encounter/gap cross-check
  enrich_gfw.py    registry lookup, or a size class and nothing more
  score.py         triage scoring, every term kept and explainable
  run_pipeline.py  phases 2–7 end to end; detector over every tile, strip edges excluded
  dashboard.py     Folium map
  gfw.py           GFW presence (AIS outside Denmark), SAR detections, events
  hunt.py          region search: AIS-unmatched ships and STS candidates (tiers A/B/C)
  pseudo.py        new-region training tiles from AIS-confirmed detections
  search.py        area-on-demand search behind the website: one box in, ships + reasons out
  match.py         radar-to-AIS matching with dead reckoning, feasibility, size, coverage
  context.py       nearby GFW AIS gap events and maritime zone (Marine Regions)
  regional_ais.py  Gulf AIS snapshots (recorded every 5 min on Modal)
  openwaters.py    Open Waters shore-receiver AIS
  optical.py       Sentinel-2 cross-check of STS candidates
  evaluate.py      scene-level recall against AIS, threshold selection rule
  review.py        blind review sheet for choosing the cut-off (test plan T3)
  model_select.py  detector families, trained on Skagen + Oman, tested on Laconia
webapp/            FastAPI backend (app.py, feeds.py) + React frontend
modal_app.py       deployment on Modal; modal_eval.py, modal_review.py run experiments there
scripts/           check_live.py (live end-to-end checks), deploy_space.py (HF Space, PRO only)
notebooks/         Colab notebooks, one per heavy phase
docs/              research position, results log, plan, data-source record
tests/             159 tests
```

---

## Deployment

Live at **https://jaswanth-k1210--darksts-web.modal.run**: one Modal app serves the
FastAPI backend and the built React site from the same URL (serverless CPU, $30/month
free credits, scales to zero; ~30 s cold start). The detector is downloaded from the
Hugging Face model repo `Jaswanth-K/darksts-detector`. Accounts and the search cache
live on a Modal volume; the Gulf AIS recorder runs every 5 minutes on its own volume.

```bash
pip install modal && modal setup             # once
(cd webapp/frontend && npm run build)        # the website
modal deploy modal_app.py                    # secrets come from the local .env at deploy time
python3 scripts/check_live.py                # 18 end-to-end checks against the live site
```

| Endpoint | Returns |
| -------- | ------- |
| `POST /api/search` | starts a search over `{"bbox": [west, south, east, north]}` (11–60 km a side, sign-in) |
| `GET /api/search/{id}` | progress stage, then ships with reasons, evidence points, radar chips, STS pairs |
| `GET /api/live` | live AIS positions for the map |
| `GET /api/events` | precomputed candidates |
| `GET /api/health` | status and whether search is available |
| `POST /api/auth/register`, `/login` | accounts (rate-limited) |

A search picks the newest Sentinel-1 pass that covers at least half the box by its
real footprint and already has AIS, runs the detector, matches AIS, measures hulls,
looks for side-by-side pairs and writes one sentence per piece of evidence.
Hugging Face Docker Spaces now need PRO; `scripts/deploy_space.py` is kept as a paid
fallback.

## Detector families

Trained and compared on the same scene-level split (RESULTS §3 Skagen only, §6b
Skagen + Oman + Laconia):

| Model | Vessel mAP50, new regions | CPU s / tile | Role |
| ----- | ------------------------- | ------------ | ---- |
| RT-DETR-l | 0.512 | 3.49 | accuracy reference (best on Skagen, 0.475) |
| YOLOv8n | 0.532 | 0.30 | |
| YOLO11n | 0.523 | 0.40 | |
| YOLO12n | 0.546 | 0.79 | |
| **YOLO26n** | **0.558** | 0.31 | **served** |

On 25 new-region tiles the five are within noise of each other; CPU speed decided.
The `sts` class is unreliable in every model (11 validation instances), so STS comes
from geometry (pairs, hull width, radar-vs-AIS counting), not from the class.
New-region labels are detections confirmed by GFW AIS presence; that exception to
research rule 5 is disclosed in `docs/RESEARCH_POSITION.md`.

## Calibration knobs

Real sensors need tuning. Each of these was measured, not guessed, and each is
swept in `docs/RESEARCH_POSITION.md` §4.6.

| Constant | Value | Why |
| -------- | ----- | --- |
| `BLOB_K` | 30 MAD | box/AIS length ratio 2.05× at k=3, 1.07× at k=30, over 114 vessels |
| land clearance | 1 km | totals fall 569→188 from 0.5→1 km while tanker events hold at 71 |
| STS buffer | 500 m | **specified, not yet swept** |
| AIS window | ±12 h | **least justified constant in the project** |
| vessel cut-off (YOLO26n) | 0.25 | 71 % AIS recall vs 55 % at 0.40 (RESULTS §7); 0.15–0.25 shown only as hidden weak candidates until reviewed precision (T3) |

---

## Known limitations

Twelve of them, consolidated in `docs/RESEARCH_POSITION.md` §9.5. The three that
matter most: SAR cannot establish identity, so unmatched detections get a size
estimate and never a type; rafted vessels are not separable at 10 m, measured in
§4.3.1; and AIS absence does not establish intentional concealment.

## Licence and attribution

Sentinel-1 data © ESA, via Microsoft Planetary Computer. AIS data © Danish
Maritime Authority. Global Fishing Watch APIs are non-commercial use — GFW must
be attributed in any publication from this work.
