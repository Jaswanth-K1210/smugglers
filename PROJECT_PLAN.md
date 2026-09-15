# Dark STS Detection on Sentinel-1 — Implementation Plan

Supersedes `claude-code-build-prompt.md`. Written after reading Ballinger (2024),
`2404.07607v1.pdf`. Where this disagrees with `dark-ship-detection-project-bible.md`,
this wins.

---

## What the paper actually does (and what the bible got wrong)

Read the paper carefully before starting. Three things in it invalidate large parts
of the original bible:

**1. There is no xView3. There is no manual labeling.**
The paper builds its 20,223-tile training set *automatically*: take AIS positions at
image time (±2h), cut a 500m tile around each ship, segment the ship with SAM, convert
the mask to a box, and take the class label from the AIS record's vessel type. Zero
human labeling. This is the single best idea in the paper and it is what you should
copy. **Phases 4, 5 and 6 of the original bible (xView3 download, label conversion,
manual fine-tuning) are deleted.** You are not downloading 2.5TB of xView3 to get
worse point-derived labels.

**2. STS is an object detection class, not a temporal rule.**
The model has six classes, two of which are `STS Cargo` and `STS Tanker` — a single
box drawn around two rafted vessels. The model learns what "two ships tied together"
looks like. It never reasons about time. This is why the whole "stationary for 30+
minutes" logic in bible §5.1 and §6 is unnecessary — and it's why single-snapshot
Sentinel-1 works fine here.

**3. Dark = fewer than 2 AIS identities within 500m, ±12 hours.**
Not 30 minutes. Detect an STS box in imagery, buffer 500m, count distinct vessel
identities in AIS over a ±12h window. `< 2` identities = dark STS. Note this catches
the important half-dark case: one ship broadcasting, its partner silent.

Their AIS came from **Lloyd's List Intelligence** — commercial, ~1M vessels. That is
the one paid input you have to replace, and replacing it drives the next decision.

---

## The decision that determines everything: where the free raw AIS is

The auto-labeling method needs **raw AIS positions** (lat, lon, timestamp, MMSI, vessel
type). Global Fishing Watch does **not** sell or serve those — its API returns derived
*events* and gridded activity, not position streams. So the target area must be
somewhere raw AIS is published free.

That rules out Hormuz, Malacca and Linggi for the labeling step.

**Recommendation: Skagen anchorage / Danish straits (Skagerrak–Kattegat).**

| Why | Detail |
|---|---|
| Free raw AIS | Danish Maritime Authority publishes full historical AIS as daily CSV, free, no key. ~1.9 GB/day. |
| Real subject matter | Skagen anchorage and the Danish straits are *the* documented Russian shadow-fleet STS site in European reporting since 2023. Abundant citable journalism. |
| Good SAR coverage | High latitude ⇒ Sentinel-1 swath overlap ⇒ ~2–3 day revisit, better than the 6-day equatorial figure. |
| Defensible novelty | Different geography from the paper's Kerch Strait, and a politically live one. |

If you reject Skagen, your fallback is US waters (MarineCadastre free raw AIS) — but
there is no comparable dark-fleet STS story there, so the project loses its point.
Pick Skagen unless you have a strong reason not to.

---

## Your contribution over the paper — state these four, they're real

1. **Free SAR replaces paid optical.** The stated goal. PlanetScope is ~$2/km²; you pay ₹0.
2. **Cloud immunity — quantify this, it's your headline.** The paper discarded scenes
   above 0.7 cloud and ended with imagery on **55% of days**. SAR sees through cloud
   and darkness; you lose ~0%. In the North Sea/Baltic, which is cloudier than the
   Black Sea, an optical pipeline would do *worse* than 55%. Compute your actual
   coverage % and put it next to their 55% — that single number justifies the paper.
3. **External validation the original never had.** The paper validates dark STS against
   nothing but its own AIS. You cross-check against **GFW's independent `gaps`
   (AIS-off) and `encounters` event datasets** — a second, independently-derived
   opinion on whether a vessel went dark. This is a genuine methodological upgrade.
4. **Suspicion scoring + capacity estimation.** Scoring is your own layer; capacity
   estimation from bounding-box diagonal is explicitly listed as future work in the
   paper's conclusion (§4), so implementing it is a direct, citable extension.

---

## Two things that will *not* transfer, adjust now

**Six classes collapse to two.** Sentinel-1 IW GRD is 10 m/pixel; PlanetScope is 3 m.
A 6,000 DWT general cargo ship is ~100 m = **10 pixels**. You cannot tell a bulk
carrier from a general cargo ship at 10 pixels — nobody can. Train on:

- `vessel`
- `sts` (two or more rafted)

Optionally add a size split (`vessel_large` ≥150 m) since length *is* measurable at
this resolution. Do not attempt the paper's six classes.

**Do not expect 97% F1.** That number is 3 m optical on six well-separated classes.
On 10 m SAR with two classes, budget for mAP50 in the 0.6–0.8 range and report it
honestly. A lower number on free imagery is still a publishable result; a fabricated
high one is not.

---

## Pipeline

```
DMA AIS CSV ──┬─► STS events in AIS (500m, <1kn)  ──► labels ──┐
              │                                                ├──► YOLOv8 (vessel, sts)
Sentinel Hub ─┴─► calibrated S1 GeoTIFF ──► 512px tiles ───────┘
                                                                    │
                                            inference on held-out scenes
                                                                    ▼
                          STS box ──► 500m buffer, AIS ±12h ──► <2 identities = DARK
                                                                    ▼
                                   GFW gaps/encounters cross-check (validation)
                                                                    ▼
                                        suspicion score ──► Folium map
```

---

## Phases

Same discipline as the original: finish a phase, run its smoke test, **stop**, show
results, wait for "continue". Each phase below also has a **kill criterion** — a
result that means stop and rethink rather than push on.

### Phase 0 — Setup and the one question that matters (½ day)
Env, folders, `.env` for `CDSE_CLIENT_ID` / `CDSE_CLIENT_SECRET` / `GFW_API_TOKEN`.
Then immediately: download **one day** of DMA AIS CSV for your box and **one** GFW
`gaps` events query over the same box/period.

- Smoke test: `tests/test_env.py` prints versions; print AIS row count and 5 rows; print GFW gap event count.
- **Kill criterion:** if the DMA CSV has no vessels in your box, or GFW returns zero gap events for the region over a year — change the box now, not in week five.

### Phase 1 — AIS ingest and STS event extraction (3 days)
`src/ais.py`: load DMA daily CSVs, filter to bbox, keep `mmsi, lat, lon, timestamp,
sog, ship_type, length`. Then `src/ais_sts.py` implementing the paper §2.2 rule:
vessels within **500 m** of each other for **≥1 hour** at **SOG < 1 knot** = an STS
event. This is the paper's rule verbatim; don't invent your own.

- Smoke test: run over one month; report count of STS events; plot 3 on a map and eyeball that the two tracks converge and sit still.
- **Kill criterion:** fewer than ~50 AIS STS events per year in your box means too little training signal — widen the box.

### Phase 2 — Sentinel-1 acquisition, no SNAP (2 days)
`src/fetch_s1.py` using **CDSE Sentinel Hub Process API**, which returns already
calibrated and geocoded S1 GRD as GeoTIFF for a bbox+date. This deletes the SNAP
install, the 1 GB `.zip` downloads, and the tiling of enormous scenes.

The bible's SNAP `gpt` commands (§2.5) do not run as written — chaining needs
BEAM-DIMAP intermediates and Terrain-Correction needs a DEM argument. Skip all of it.
Request VV, linear-to-dB, 10 m.

- Smoke test: pull one 20×20 km scene; open in rasterio; save a PNG; confirm you can see the coastline and bright dots on dark water.
- **Kill criterion:** if the free Sentinel Hub quota won't cover ~150 scenes, fall back to `cdsetool` + full GRD download for a smaller area.

### Phase 3 — Auto-labeling ⚠️ THE PHASE THAT DECIDES THE PROJECT (1 week)
`src/autolabel.py`. For each S1 scene, take AIS positions within ±30 min of overpass
(use the exact acquisition time from scene metadata; ±2h in the paper is too loose for
ships underway — at 12 knots a ship moves 44 km in 2 hours).

1. Project AIS lat/lon to pixels (`rasterio` `src.index`).
2. Extract a tight box around the bright blob at that pixel: **adaptive threshold +
   connected components** (scipy), not SAM. Ships are 10–30 dB brighter than sea
   clutter; a 20-pixel bright blob on dark water does not need a 2.4 GB foundation
   model. Keep a `sam` flag for later if thresholding disappoints.
3. Class: if this AIS position belongs to a Phase-1 STS event → `sts`, else `vessel`.
4. Write YOLO `.txt`, tile to 512 px, drop empty tiles.

- Smoke test (**do this by eye, do not skip**): draw generated boxes on 20 tiles, save PNGs, and personally confirm the boxes land on ships. Report what fraction do.
- **Kill criterion:** if under ~70% of boxes land on an actual bright target, stop. Either overpass-time matching or geolocation is broken, and everything downstream inherits the error.

### Phase 4 — Train (3 days, mostly waiting)
`src/train.py`, Ultralytics YOLOv8. Start `yolov8n.pt`; move to `yolov8s`/`m` only if
`n` underperforms. 512 px, 80/20 split, **split by scene not by tile** — tiles from
one scene are correlated and a random split will inflate your metrics.

- Smoke test: 3 epochs, confirm loss falls, then request approval for the full run.
- **Kill criterion:** mAP50 < 0.4 after full training ⇒ go back to Phase 3, the labels are wrong.

### Phase 5 — False-positive control ⚠️ NEW, NOT IN THE PAPER (4 days)
The paper never faces this because optical imagery makes ships obvious. SAR does not.
Wind streaks, offshore platforms, wind farms, wave breaking and **azimuth ambiguities**
(SAR "ghost" copies offset along-track) all produce bright targets with no AIS — so
they become false "dark ships" *by construction*. Untreated, this destroys the result.

`src/filters.py`: land/coastline mask (OSM or GSHHG), static-infrastructure mask (a
target appearing at the same coordinate in >50% of scenes is a platform or wind
turbine, not a ship — this is a cheap and very effective filter), and a length
plausibility gate (reject <30 m or >400 m).

- Smoke test: hand-inspect **100 random detections**, count true ships, report precision before and after filtering. This number goes in your paper.
- **Kill criterion:** post-filter precision below 0.5 means the dark-ship counts are noise; fix before proceeding.

### Phase 6 — Dark STS cross-check + independent validation (4 days)
`src/dark_sts.py`: paper §3 verbatim — for each detected `sts` box, buffer 500 m,
count distinct MMSIs in AIS within **±12 h**; `< 2` = dark STS. Then
`src/validate_gfw.py`: for each dark event, query GFW `gaps` and `encounters` for the
same area/time and report the agreement rate.

- Smoke test: `tests/test_dark_sts.py` with synthetic cases — (a) two AIS identities present → not dark, (b) zero → dark, (c) exactly one → dark (the half-dark case), (d) two identities but 20 h away → dark.
- **Kill criterion:** zero dark events across your whole study period is a *valid* finding but a thin paper — if it happens, extend the date range before concluding.

### Phase 7 — Suspicion scoring (2 days)
`src/score.py`. Three terms only:
- AIS gap duration around the event (from AIS, not from imagery)
- proximity to a sanctioned-linked port/zone (small hand-built GeoJSON; OFAC/EU lists)
- distance from normal shipping lanes (build the lane density surface from your own DMA AIS — free, and better than any external lane dataset)

**Drop the time-of-day term** from bible §6. Sentinel-1 is sun-synchronous: every
detection is at one of two local times. It carries zero information.

Optional and cheap: capacity estimation from box diagonal (paper §4 future work).

- Smoke test: `tests/test_score.py` — an event that is long-dark, near a sanctioned port, off-lane scores high; a brief mid-lane one scores low.

### Phase 8 — Dashboard and write-up (1 week)
`src/dashboard.py` → Folium HTML, colour by score, popups with the SAR chip, AIS
identities found, GFW agreement, and score breakdown. Then `src/run_pipeline.py`
chaining 2→7 for one date range.

Write-up compares to the paper on: coverage % (yours vs their 55%), detection counts,
precision, cost, and GFW agreement rate.

---

## Schedule

| Week | Phase |
|---|---|
| 1 | 0 + 1 — registrations, AIS ingest, AIS STS extraction |
| 2 | 2 + start 3 — imagery, begin auto-labeling |
| 3 | 3 — auto-labeling, visual verification (the crux week) |
| 4 | 4 — training |
| 5 | 5 — false-positive control, precision measurement |
| 6 | 6 — dark STS logic + GFW validation |
| 7 | 7 + 8 — scoring, dashboard |
| 8 | Buffer, write-up, slides |

## Dependencies

`rasterio geopandas shapely ultralytics requests folium geopy pandas numpy scipy pytest python-dotenv`

No SNAP. No `sentinelsat` (dead hub). No SAM unless thresholding fails. No xView3.

## Cost

₹0. Sentinel Hub free tier, DMA AIS free, GFW research API free, Colab free tier.

## Sources
- Base paper: https://arxiv.org/abs/2404.07607
- DMA AIS download: https://www.dma.dk/safety-at-sea/navigational-information/download-data
- GFW API docs: https://api-doc.globalfishingwatch.org/
- CDSE: https://dataspace.copernicus.eu/
