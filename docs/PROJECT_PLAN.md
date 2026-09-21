# Dark STS Detection on Sentinel-1 — Implementation Plan

Companion: `RESEARCH_POSITION.md` is the canonical research framing; this file is the
execution plan. Where they disagree about a claim, `RESEARCH_POSITION.md` wins.

Supersedes `claude-code-build-prompt.md`. Written after reading Ballinger (2024),
`2404.07607v1.pdf`, and the GFW API documentation (v3, `latest` datasets).

---

## What the paper actually does (and what the bible got wrong)

Read the paper carefully before starting. Three things in it invalidate large parts
of the original bible:

**1. There is no xView3. There is no manual labeling.**
The paper builds its 20,223-tile training set *automatically*: take AIS positions at
image time (±2h), cut a 500m tile around each ship, segment the ship with SAM, convert
the mask to a box, and take the class label from the AIS record's vessel type. Zero
human labeling. Copy this. The original bible's xView3 plan is deleted.

**2. STS is an object detection class, not a temporal rule.**
The model has six classes, two of which are `STS Cargo` and `STS Tanker` — a single
box drawn around two rafted vessels. The model learns what "two ships tied together"
looks like. It never reasons about time. We keep this, but collapse to two classes
(§"What will not transfer").

**3. Dark = fewer than 2 AIS identities within 500m, ±12 hours.**
Detect an STS box in imagery, buffer 500m, count distinct vessel identities in AIS over
a ±12h window. `< 2` identities = dark STS. This catches the half-dark case: one ship
broadcasting, its partner silent.

Their AIS came from **Lloyd's List Intelligence** — commercial, ~1M vessels. That is
the one paid input we replace, and replacing it drives the next decisions.

---

## Two data decisions that shape everything

### Decision 1 — where the free raw AIS is

The auto-labeling method needs **raw AIS positions** (lat, lon, timestamp, MMSI, vessel
type). Global Fishing Watch does **not** serve those — its API returns derived events and
gridded presence, not position streams (confirmed by GFW's own FAQ).

**Training regions (free raw AIS):**

| Region | Source | Why |
|---|---|---|
| **Danish waters** (Skagen/Skagerrak/Kattegat) | DMA daily CSVs, free, no key | *The* documented Russian shadow-fleet STS area; good SAR overlap |
| **Baltic** | HELCOM monthly AIS dumps | Contiguous with Skagen region; second free source |
| **US waters** (stretch) | MarineCadastre | Free, but different format/schema — only after DK/Baltic is proven |

**Test/generalization regions — no training, no raw AIS:**

| Region | Role |
|---|---|
| Hormuz | Unseen-chokepoint generalization |
| Malacca | Unseen-chokepoint generalization |
| Kerch | Direct comparison to the paper's region |

Per `RESEARCH_POSITION.md` §6: these are **cross-region generalization / reference
analysis**, validated partly against GFW gridded presence — not equivalent ground truth.

### Decision 2 — GFW is a reference layer, not a source and not ground truth

GFW publishes **global Sentinel-1 SAR vessel detections** (2017 → ~5 days ago) with a
`matched='false'` filter, vessel presence grids, AIS-off (GAP) events, encounters, and a
vessel registry API. This is enormously useful — but:

- GFW's products are **modeled/estimated** (GFW documents caveats itself).
- GFW's SAR detections come from the **same Sentinel-1 sensor** we use, so comparing us to
  them is *cross-system*, not *ground-truth* validation.
- `matched='false'` means **AIS-unmatched**, not "dark." Dark is a fused conclusion.

We use GFW as: (1) a **comparison/benchmark layer**, (2) the **C** region of an
evaluation matrix, (3) **registry enrichment** for vessel type/flag/length of matched or
suspected vessels, including OFAC-linked lists.

**Do not write "GFW validates us" in the paper.**

---

## Contributions over the paper — reframed (see RESEARCH_POSITION §7)

1. **Open-data reproduction** — free SAR + open AIS vs their commercial stack.
2. **Multi-signal dark-STS framework** — SAR + AIS + GFW SAR + presence + encounters +
   registry → structured event classification.
3. **Fusion methodology** — the research heart (§"Fusion engine").
4. **Cross-region generalization** — train Europe, test Kerch/Hormuz/Malacca.
5. **Registry enrichment for vessel types** — "all types" via identity, not visual CNN.
6. **Reproducibility** — ₹0 re-runnable experiment.

---

## What will not transfer from the paper, adjust now

**Six classes collapse to two.** Sentinel-1 IW GRD is 10 m/pixel; PlanetScope is 3 m.
A 6,000 DWT general cargo ship is ~100 m = **10 pixels**. You cannot tell a bulk carrier
from a general cargo ship at 10 pixels — nobody can. Train on:

- `vessel`
- `sts` (two or more rafted)

Optionally add a size split (`vessel_large` ≥150 m) since length *is* measurable at
this resolution. Vessel type/flag/length for the final dashboard comes from **GFW Vessel
API registry enrichment on AIS matches** — never from the CNN.

**Do not expect 97% F1 / 99% mAP50.** That is 3 m optical on six well-separated classes.
On 10 m SAR with two classes, budget for mAP50 in the 0.6–0.8 range and report it
honestly. A lower number on free imagery is still a publishable result.

---

## Fusion engine (research heart)

Every STS candidate is a tuple of weak signals — never a single `dark` flag:

```
SAR STS box ──► { # AIS identities in 500m/±12h,
                 GFW SAR detection? GFW matched?
                 GFW presence? GAP/encounter? registry match }
                     │
                     ▼
       FUSION MODEL (src/fusion.py)  →  AIS-visible | Partially-visible | Dark candidate
```

Rules:
- **Positive vs absence evidence.** Observe and gap/encounter signals are supporting;
  `GFW presence absent` is weak / non-informative and never boosts a darkness score.
- **Evaluated, not asserted.** The fusion model is a *classification methodology* compared
  against AIS-only, SAR-only, AIS-threshold, and GFW-reference baselines on an
  expert-reviewed reference set (100–300 events). No invented weights: start rule-based,
  prefer **logistic regression** for interpretable coefficients on a small set. If fusion
  doesn't beat baselines, report it honestly.
- Definitions and the evaluation matrix are in `RESEARCH_POSITION.md` §4.

---

## Pipeline

```
DMA/HELCOM AIS ──┬─► STS events in AIS (500m, ≥1h, <1kn) ──► weak labels ──┐
                 │                                                        ├─► YOLOv8 (vessel, sts)
Planetary Computer┴─► S1 GRD, GCP-warped to UTM/10m ──► tiles ─────────────┘
                                                                           │
                                          inference on held-out + unseen scenes
                                                                           ▼
                          STS box ──► 500m buffer, AIS ±12h ──► 0/1/2+ identities
                                                                           │
                 ┌─────────────────────────────────────────────────────────┘
                 ▼
        GFW reference: SAR presence · matched? · presence grid · GAPs · encounters
                 ▼
        Registry enrichment (type/flag/length/OFAC) for matches
                 ▼
              FUSION ENGINE ──► AIS-visible | Partially-visible | Dark candidate
                 ▼
        Size-binned disagreement analysis (your YOLO vs GFW SAR)
                 ▼
          dashboard (Next.js + Leaflet)
```

---

## Phases

Finish a phase, run its smoke test, **stop**, show results, wait for "continue". Each
phase has a **kill criterion** — a result that means stop and rethink.

### Phase 0 — Prove or kill the STS data (Days 1–7) ⚠️ THE PROJECT'S ONLY REAL GATE
This is not optional. Before any ML code:

1. Set up env, folders, `.env` for `GFW_API_TOKEN` and `AOI_BBOX`. No SAR credential is
   needed; the `CDSE_*` slots are retained only in case CDSE returns.
2. Download **one month** of DMA AIS CSV for the bbox + one month HELCOM.
3. Run `src/ais_sts.py` (paper §2.2 rule) over it. Count STS events.
4. Match a handful to Sentinel-1 overpasses (`src/fetch_s1.py` initial test).
5. Confirm **≥50 genuine AIS-derived STS events/year** in-region and that imagery matches them.

- Smoke test: `tests/test_env.py`; print STS event count; plot 3 events on a map; show tracks
  converge and sit still.
- **Kill criterion:** <50 STS events/yr, or overpass matching fails → **change training
  region now.** Do not build the detector on a dead data assumption.

### Phase 1 — AIS ingest + STS event extraction (3 days)
`src/ais.py`: load DMA/HELCOM, filter to bbox, keep `mmsi, lat, lon, timestamp, sog,
ship_type, length`. `src/ais_sts.py`: vessels within **500 m** for **≥1 hour** at **SOG<1**
= STS event — the paper's rule verbatim. Store events as a **research dataset**
(`event_id, timestamp, lat, lon, vessel_1, vessel_2, distance, duration, mean_SOG, region`).

- Kill criterion: fewer than ~50 STS events/year → widen box or move region (Phase 0 gate
  still applies).

### Phase 2 — Sentinel-1 acquisition, no SNAP (2 days)
`src/fetch_s1.py` via **Microsoft Planetary Computer STAC** (`sentinel-1-grd`), which
needs no account — CDSE Sentinel Hub was abandoned, see RESEARCH_POSITION.md §3.1.
Search by AOI and date, sign anonymously, window-read the VV band straight out of the
cloud-optimized GeoTIFF, and warp the GCP grid to **UTM 32N at 10 m** via `WarpedVRT`.
Scenes are ranked by AOI overlap, not recency: a single IW slice is far smaller than a
multi-degree AOI, so recency picks whichever corner the satellite crossed — often land.
- Kill criterion: **met.** Skagen anchorage, 2025-06-08: 8 fully-covering scenes in 10
  days (S1A + S1C), quick-look shows the Grenen spit and ~30 bright targets at anchor.
- No quota to exhaust; COG window reads pull only the AOI, not whole scenes.

### Phase 3 — Auto-labeling (1 week) ⚠️ labels decide downstream accuracy
`src/autolabel.py`. For each S1 scene, AIS positions within **±30 min** of overpass, then:
1. Project AIS lat/lon to pixels (`rasterio` `src.index`).
2. Extract a tight box via **adaptive threshold + connected components** (scipy), not SAM.
   Keep a `sam` flag if thresholding disappoints.
3. Class: AIS position in a Phase-1 STS event → `sts`, else `vessel`.
4. Write YOLO `.txt`, tile to 512 px, drop empty tiles.

- Smoke test: draw boxes on 20 tiles, save PNGs, personally confirm the boxes land on ships.
- **Kill criterion:** <70% of boxes hit a bright target → overpass-time or geolocation is
  broken; everything downstream inherits the error.

### Phase 4 — Train (3 days)
`src/train.py`, Ultralytics YOLOv8. Start `yolov8n.pt`; escalate only if `n` underperforms.
512 px, 80/20, **split by scene not tile**.
- Smoke test: 3 epochs, loss falls, then approval for full run.
- **Kill criterion:** mAP50 < 0.4 after full training → Phase 3 labels are wrong.

### Phase 5 — False-positive control (4 days) ⚠️ SAR-specific, not in the paper
`src/filters.py`: land/coastline mask (OSM/GSHHG), **static-infrastructure mask** (target
at same coordinate in >50% of scenes = platform/wind turbine), length plausibility gate
(30–400 m).
- Smoke test: hand-inspect **100 random detections**; report precision pre/post filter.
- **Kill criterion:** post-filter precision < 0.5 → counts are noise; fix before proceeding.

### Phase 6 — Dark logic + GFW reference layer + fusion (5 days)
`src/dark_sts.py`: paper §3 verbatim — STS box → 500 m buffer → distinct MMSIs in AIS
±12 h → `<2` = candidate. Then `src/gfw_ref.py`: per candidate, query **GFW SAR presence,
`matched` flag, presence grid, GAP, encounters** via `gfw-api-python-client`. Then build
`src/fusion.py` as an **evaluated classifier**, not a hand-scored heuristic:

1. Assemble the evidence-state feature vector per candidate.
2. Build the **fusion-reference set**: 100–300 candidates with expert-reviewed labels
   (`0` non-STS / `1` probable STS / `2` probable dark / `3` high-confidence dark).
3. Implement the four baselines (AIS-only, SAR-only, AIS-threshold 0/1/2+, GFW-reference).
4. Fit the proposed fusion model — prefer **logistic regression** for interpretability on
   a small set, after a rule-based sanity baseline.
5. Report precision / recall / FPR and cross-source disagreement patterns.

Keep `GFW presence absent` as non-informative (§4.2 of the research position).

- Smoke test: `tests/test_fusion.py` synthetic cases — (a) 2 AIS IDs → AIS-visible;
  (b) 0 IDs + GFW SAR unmatched + GAP → strong dark candidate; (c) 1 ID → partially
  visible; (d) 0 IDs + GFW matched → possible timing error.
- **Kill criterion:** zero dark candidates across the whole study period is a valid but thin
  finding — extend date range before concluding.

### Phase 7 — Registry enrichment + suspicion scoring (2 days)
`src/enrich.py`: for any AIS-matched or GFW-referenced vessel, pull **GFW Vessel API**
identity (type, flag, length, OFAC lists). `src/score.py` — three terms ONLY:
- AIS gap duration around the event (from AIS, not imagery)
- proximity to sanctioned-linked port/zone (small hand-built GeoJSON; OFAC/EU lists)
- distance from normal shipping lanes (lane density from your own AIS)

Drop the time-of-day term (Sentinel-1 is sun-synchronous — zero information). Optional and
cheap: capacity estimation from box diagonal (paper §4 future work). This feeds the
size-bins for disagreement analysis in Phase 8.

### Phase 8 — Cross-region generalization (4 days)
`src/generalize.py`: run the trained detector on **Hormuz / Malacca / Kerch** scenes. No
training. Validate using GFW presence grids + SAR reference. Build the **size-binned
disagreement table** (your YOLO vs GFW SAR: <30 m … >250 m). Use the mandatory caveat
sentence from `RESEARCH_POSITION.md` §6 in any write-up.
- Smoke test: table renders for ≥1 region; disagreements hand-inspected on 25 detections.
- **Kill criterion:** model emits nonsense detections (e.g., <10% look like vessels) in
  every region → keep generalization section but report failure honestly.

### Phase 9 — Dashboard + write-up (1 week)
`src/dashboard.py` (or Next.js app per `FRONTEND_PLAN.md`) — colour by fusion outcome
(AIS-visible / partially-visible / dark candidate), popups with SAR chip, AIS identities
found, GFW agreement, registry info, score breakdown. `src/run_pipeline.py` chains 1→8.

Write-up compares to the paper on: coverage % (yours vs ~55%), detection counts, precision,
cost, and GFW agreement rate; plus the **fusion evaluation table** (baselines vs proposed:
precision / recall / FPR) as the methods contribution.

---

## Schedule

| Week | Phase |
|---|---|
| 1 | **0 — prove/kill the STS data (THE gate)** |
| 2 | 1 + 2 — AIS STS extraction + imagery |
| 3 | 3 — auto-labeling + visual verification (crux) |
| 4 | 4 — training |
| 5 | 5 — false-positive control, precision |
| 6 | 6 — dark logic + GFW reference + fusion |
| 7 | 7 + 8 — enrichment/scoring + generalization |
| 8 | 9 — dashboard, write-up, buffer |

## Dependencies

`rasterio geopandas shapely ultralytics requests folium geopy pandas numpy scipy pytest
python-dotenv gfw-api-python-client`

No SNAP. No `sentinelsat`. No SAM unless thresholding fails. No xView3.

## Reference repos (study, don't clone-and-claim)

- `allenai/sar_vessel_detect` — xView3 radar detector: preprocessing, tiling, training,
  inference, length estimation.
- `gSulpizio/sat_tracker` — SAR+AIS dark-vessel demo with human-in-the-loop dashboard:
  borrow the architecture, not the code.
- `GlobalFishingWatch/gfw-api-python-client` — official Python client; use it instead of
  hand-rolling GFW HTTP calls.

## Cost

₹0 core. Optional Colab Pro (~₹950/month) if training is slow. **Do not spend the ₹5000
until Phase 0 passes.** GFW API use is free for non-commercial research; attribute GFW in
the paper.

## Sources
- Base paper: https://arxiv.org/abs/2404.07607
- DMA AIS: https://www.dma.dk/safety-at-sea/navigational-information/download-data
- HELCOM AIS: https://helcom.fi/baltic-sea-trends/data-maps/
- GFW API docs: https://api-doc.globalfishingwatch.org/
- GFW SAR presence dataset (4Wings): https://globalfishingwatch.org/our-apis/documentation/docs/v3/4wings
- Planetary Computer: https://planetarycomputer.microsoft.com/dataset/sentinel-1-grd
- CDSE (unavailable as of 2026-09-20): https://dataspace.copernicus.eu/
- MarineCadastre (stretch): https://hub.marinecadastre.gov/pages/vesseltraffic