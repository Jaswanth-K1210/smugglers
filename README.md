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
| 4 Training | code ready | **untested — `torch` has no wheel for Python 3.13 on Intel macOS** |
| 5 False-positive control | code + tests | land, length, static-infrastructure masks |
| 6 Identity characterisation | code + tests | four specified cases pass |
| 7 Suspicion scoring | code + tests | triage order, not a probability |
| 8 Pipeline + dashboard | runs end to end | `outputs/events.geojson` |
| 9 Web deployment | code ready | not yet deployed |

50 tests pass locally. Phase 4 has never been executed anywhere.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add GFW_API_TOKEN and AOI_BBOX
pytest -q                     # 50 tests, no network or credentials needed
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
| [Global Fishing Watch](https://globalfishingwatch.org/our-apis/) v3 | token | comparison layers, registry |

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
  run_pipeline.py  phases 2–7 end to end
  dashboard.py     Folium map
webapp/            FastAPI backend + Leaflet frontend + Dockerfile
notebooks/         Colab notebooks, one per heavy phase
docs/              research position, plan, data-source record
tests/             50 tests
```

---

## Deployment

Precomputed results, served fast. No GPU, no scene fetched per request.

**Hugging Face Spaces (Docker)** is the recommended target: 2 vCPU / 16 GB free,
enough RAM for the optional live endpoint. Render's free tier is 512 MB, which
`torch` alone exceeds. Vercel caps serverless bundles at 250 MB, so it can host
the frontend only.

```bash
docker build -f webapp/Dockerfile -t darksts .
docker run -p 7860:7860 darksts
```

| Endpoint | Returns |
| -------- | ------- |
| `GET /api/health` | status, event count, whether live detection is available |
| `GET /api/events` | precomputed candidates, filterable by category and score |
| `GET /api/summary` | counts by category and size class |
| `POST /api/detect` | runs the detector on one uploaded tile, on CPU |

`/api/detect` needs weights in the image; without them it returns a clear 503 and
the precomputed endpoints keep working.

---

## Detector families

Nothing is trained yet — `models/` is empty and no Space is deployed. The
benchmark compares CNNs against one transformer detector on the same split:

| Family | Kind | Role |
| ------ | ---- | ---- |
| `yolov8n` | CNN | the originally specified baseline |
| `yolo11n` | CNN | modern baseline |
| `yolo12n` | CNN with attention modules | candidate |
| `rtdetr-l` | **transformer (DETR-style)** | the transformer arm |

```bash
python -m src.train --benchmark yolov8n yolo11n yolo12n rtdetr-l
python -m src.train --available          # what this ultralytics build supports
```

**Winning the benchmark and being deployed are separate decisions.**
`deploy_choice()` measures CPU latency per model and reports both rankings: the
most accurate, and the most accurate that fits a CPU budget. `/api/detect` runs
on two shared vCPUs, so the served model will likely be a small CNN even if the
transformer wins the table. Report the accurate one; ship the fast one.

Architecture is not currently the binding constraint — measured vessel boxes run
19–33 px and the length-gate floor is 3 px, so scene count and small-object
handling dominate. Benchmarking across 20 tiles from one scene measures noise.

## Calibration knobs

Real sensors need tuning. Each of these was measured, not guessed, and each is
swept in `docs/RESEARCH_POSITION.md` §4.6.

| Constant | Value | Why |
| -------- | ----- | --- |
| `BLOB_K` | 30 MAD | box/AIS length ratio 2.05× at k=3, 1.07× at k=30, over 114 vessels |
| land clearance | 1 km | totals fall 569→188 from 0.5→1 km while tanker events hold at 71 |
| STS buffer | 500 m | **specified, not yet swept** |
| AIS window | ±12 h | **least justified constant in the project** |

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
