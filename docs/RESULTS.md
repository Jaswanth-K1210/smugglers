# Results log

Measured results, newest last. Each entry states the setup so it can be re-run.
Wording follows `RESEARCH_POSITION.md` §4.2: a detection with no AIS match is an
**AIS-unmatched candidate**, never "dark".

---

## Setup common to all runs below (2026-10-01)

| Item | Value |
| ---- | ----- |
| AOI | Skagen anchorage, `(10.4, 57.5, 11.4, 58.0)` |
| Imagery | Sentinel-1 IW GRDH VV, Planetary Computer, warped to UTM 32N / 10 m |
| AIS | Danish Maritime Authority daily files |
| Dates | 2026-08-27 → 2026-09-26: 31 scenes (S1C + S1D), 469 at-sea STS events |
| Split | by scene: 24 scenes; 6 held out (133 train / 37 val tiles of 1024 px) |
| Training | 80 epochs, batch 8, imgsz 1024, seed 0, deterministic, A100 |

---

## 1. Label audit: three defects in the AIS→SAR auto-labeller

Found by inspecting validation predictions, then confirmed numerically. Fixed in
commit `80d41cc`; regression test `tests/test_autolabel.py`.

**1a. Rafted pairs carried two classes on one box.** Two vessels moored together
are one blob at 10 m. Both partners' `vessel` boxes landed on that blob, and the
`sts` box drawn around them had the same coordinates. Every `sts` label was also a
`vessel` label, so `sts` could not be learned (mAP50 = 0 with 63 boxes).
Fix: a pair in an STS event is labelled `sts` only.

**1b. Moving ships are displaced in azimuth (Doppler).** Offset between the box
centre and the AIS position interpolated to the acquisition second, over 854
labels:

| Speed | n | Median offset | Share > 300 m | Box / AIS length |
| ----- | - | ------------- | ------------- | ---------------- |
| < 1 kn | 452 | 61 m | 0 % | 0.99 |
| 1–5 kn | 55 | 93 m | 9 % | 1.25 |
| 5–10 kn | 143 | 231 m | 26 % | 0.88 |
| > 10 kn | 204 | 376 m | 75 % | 0.76 |

Stationary ships are geolocated to ~60 m; the error grows with speed as expected
from the ~115 s range/velocity ratio of Sentinel-1 IW (~60 m per knot of radial
speed). A fixed 600 m search window dropped fast ships or boxed the wrong target,
which taught the model that isolated bright targets are background.
Fix: search radius = 600 m + 60 m/kn × SOG, capped at 2 km.

**1c. Wrong-object boxes.** Boxes whose length is outside 0.5–2× the AIS length
are dropped (stationary median is 0.99, so the band is loose).

**Effect on the dataset:** 854 vessel + 63 sts boxes / 223 tiles →
516 vessel + 64 sts boxes / 170 tiles. Fewer labels, but consistent ones.

## 2. Detector before / after the label fix (YOLOv8n, same scenes)

| | Vessel mAP50 | STS mAP50 | Overall mAP50 |
| - | ------------ | --------- | ------------- |
| Old labels | 0.311 | 0.000 | 0.156 |
| Fixed labels | **0.419** | **0.341** | **0.380** |

The held-out scenes differ slightly between the two runs (two scenes lost all
labels under the stricter rules), so the comparison is indicative, not paired.
Validation images show the fixed model detecting isolated open-sea vessels it
previously ignored, including bright targets with **no AIS label at all** — these
count as false positives in mAP, so mAP understates usefulness for this task.

## 3. Detector family benchmark (fixed labels, identical split and schedule)

| Model | Family | Vessel mAP50 | STS mAP50 | Overall mAP50 | Recall | CPU s / tile |
| ----- | ------ | ------------ | --------- | ------------- | ------ | ------------ |
| yolov8n | CNN | 0.419 | 0.341 | 0.380 | 0.30 | 0.09 |
| yolo11n | CNN | 0.450 | 0.246 | 0.348 | 0.30 | 0.09 |
| yolo12n | CNN + attention | **0.462** | 0.290 | 0.376 | 0.48 | 0.18 |
| rtdetr-l | Transformer | 0.448 | **0.356** | **0.402** | **0.66** | 0.85 |

CPU latency measured on the Colab host; the 2-vCPU deployment target will be
slower.

**Reading:** all four are within noise of each other on overall mAP — 37
validation tiles and 11 STS instances, with ±0.05 epoch-to-epoch swings. The
transformer's recall advantage (0.66 vs 0.30) is the clearest difference and
matters most here, since a missed vessel cannot become a candidate. Consistent
with §3.2: the label fix moved mAP far more than the choice of architecture.

**Deployment:** report rtdetr-l as most accurate; serve yolov8n until rtdetr-l's
latency is measured on the deployment host.

## 4. AIS-unmatched candidates

RT-DETR (conf ≥ 0.4) over all 31 scenes → 887 detections → 818 after the
land / length / infrastructure filters. Each detection was checked for any AIS
identity within **2 km and ±1 h** (deliberately generous, so a miss is meaningful
and the 60 m/kn Doppler offset cannot cause a false miss).

| Split | AIS matched (1+ identities) | AIS-unmatched | Total |
| ----- | --------------------------- | ------------- | ----- |
| test (6 held-out scenes) | 195 | 3 | 198 |
| train | 610 | 10 | 620 |
| **all** | **805 (98.4 %)** | **13** | **818** |

Every one of the 13 was inspected as an image chip:

| Verdict | Count | Notes |
| ------- | ----- | ----- |
| Strong vessel-like target | 3 | ~200 m streaked target (test), ~97 m and ~66 m compact targets |
| Weak (faint, near clutter level) | 4 | ~53–67 m |
| Duplicate detection | 1 | same scene, same position as another |
| Sea-surface feature, not a target | 2 | large curved bright bands (wake / front) |
| One static object seen on 3 dates | 3 | 57.770 N 10.547 E on 09-07, 09-24, 09-25 — fixed structure |

**7 distinct plausible AIS-unmatched candidates (3 strong).** Two filter gaps
surfaced and are cheap to close: per-scene de-duplication, and a persistence
check (an unmatched position recurring across scenes is a structure, not a
vessel). The 98.4 % match rate is itself a result: in a well-covered AOI, AIS
absence is rare, which is what §4.2.1 predicts.

### 4b. Skagen, months the model never saw (2026-07-01 → 08-26)

Same detector and AIS rule, on 50 scenes from before the training window, with
two filter fixes from §4: per-scene de-duplication (150 m) and a persistence
check (an unmatched position detected in more than one scene is a structure).

**1297 ships checked → 1254 AIS-matched (96.7 %), 14 static objects removed,
29 AIS-unmatched candidates.** All 29 inspected as image chips:

| Verdict | Count | Typical appearance |
| ------- | ----- | ------------------ |
| Strong vessel-like target | 8 | bright, elongated, often with sidelobe cross or wake, 97–191 m |
| Plausible | 8 | compact bright target clearly above clutter, 50–134 m |
| Weak | 7 | faint, near clutter level |
| Not a target | 6 | on bright sea-surface bands / fronts, or nothing visible |

**16 strong-or-plausible AIS-unmatched candidates on unseen data.** Caveat for
the weak class: a very bright ship can leave a faint azimuth-ambiguity "ghost"
a few km away, which has no AIS by construction; weak candidates should not be
reported without a second sensor (§5 optical cross-check).

### 4c. Gulf of Oman — Fujairah anchorage (2026-07-01 → 09-26)

Skagen-trained RT-DETR applied unchanged to a new region (`src/hunt.py`), AIS from
GFW hourly presence (2 km / ±1 h). 57 scenes; 6 excluded because GFW returned
no or thin AIS for their window (counting them would have made every ship in
them "unmatched").

**7,417 ships checked → 6,905 AIS-matched (93.1 %), 512 AIS-unmatched (6.9 %).**
Unmatched rate is ~3× Skagen's.

| Subset of the 512 | Count |
| ----------------- | ----- |
| Seen once (not at a recurring spot) | 336 |
| Also unmatched in **GFW's own** Sentinel-1 detections (independent) | 213 |
| Length ≥ 100 m (AIS carriage mandatory for most ships this size) | 326 |
| Length ≥ 150 m | 225 |
| **Length ≥ 100 m and GFW agrees** | **168** |
| … of which seen once | 128 |

The top 30 by ranking (seen once, GFW-corroborated, confidence) were all inspected:
**30/30 are unambiguous large ships** — bright elongated hulls with sidelobe
crosses, 134–388 m, consistent with Aframax (~245 m), Suezmax (~275 m) and VLCC
(~330 m) tanker classes. Median length of all 512 is 131 m.

Caveats: Fujairah is one of the densest anchorages in the world, where satellite
AIS messages collide and are lost — the GFW cross-check is what guards against
that, since GFW matches its detections against its full AIS archive. The UAE
Navy operates from Fujairah, so naval exclusion (evidence ladder level 3) is
still to be applied. No claim of intent is made at this level.

### 4d. Gulf of Oman — two-hull (STS) candidates

Same scenes and detections as §4c, with three changes so that two ships moored
together are no longer merged into one: de-duplication only within 30 m; each
hull's beam measured from the radar blob; and AIS counted per candidate
(radar hulls within 1 km minus AIS identities within 1 km + 750 m). Evidence tiers:
**A** two hulls ≤ 150 m apart (moored together), **B** 150–500 m apart, **C** one hull
wider than the 99th-percentile beam of AIS-matched ships of its length band
(cutoffs 92 / 130 / 144 m for < 200 / 200–280 / > 280 m).

**191 STS candidates; 41 have at least one hull without AIS and no GFW encounter
event (A 8, B 22, C 11).** GFW listed only 2 encounter events in the AOI for the
whole period, so it cannot confirm or rule out these candidates.

The 30 strongest (all of A, then B) were inspected as image chips:

| Verdict | Count | Appearance |
| ------- | ----- | ---------- |
| Strong: two separate hulls | 4 | 08-14 14:16 (three hulls, 0 AIS), 09-22 02:06 (two hulls side by side, 0 AIS), 08-26 14:16 and 09-25 14:16 (two parallel tankers ~300 m apart, 0 AIS) |
| Plausible | 9 | a large hull with a smaller target beside it, or two lobes along one blob |
| One hull only | 12 | single hull with a sidelobe cross; the pair rule split one ship into two detections |
| Not a vessel | 3 | two long straight streaks (08-14, 09-13) and a cluster of linear structures (09-01) |
| Weak | 2 | small targets near clutter level (07-24) |

**13 of 30 are plausible-or-better two-vessel AIS-unmatched candidates; 4 are
strong.** Main failure: one long hull detected twice, which the pair rule reads
as two ships. Fix (commit after `42150b5`, `hunt.one_hull`): a pair whose two
detections sit on the same bright radar component is one object when they are
more than 150 m apart, or when the step between them runs along the hull's
long axis; side by side stays a rafted pair. Recurring positions (streaks) are
still to do. The Oman numbers above predate the fix.
No claim of intent is made. Optical confirmation (Sentinel-2 / Landsat) is the next level of the
evidence ladder.

### 4e. Gulf of Laconia, Greece (2026-07-01 → 09-26)

Same detector and pipeline as §4c/§4d, with two fixes: GFW requests back off on
429 / 5xx (the first run lost 22 of 23 GFW radar checks to rate limiting), and the
over-wide test is disabled for any length band with fewer than 50 AIS-matched
ships (a p99 from a handful of ships is just the widest one seen). 63 scenes, 32
with ships after the land / length filters; no scene excluded for thin AIS.

**123 ships checked → 58 AIS-matched, 65 AIS-unmatched (25 also unmatched in
GFW's own Sentinel-1 detections).** The anchorage is small, so there are too few
matched ships to calibrate hull width: no tier C candidates here.

The top 30 single AIS-unmatched (by recurrence, GFW agreement, confidence):

| Verdict | Count | Notes |
| ------- | ----- | ----- |
| Strong vessel-like target | 20 | bright hulls with sidelobe crosses, 124–247 m; 13 of them GFW-corroborated |
| Plausible | 5 | compact targets 71–105 m, or two short parallel hulls |
| Weak / clutter | 5 | 46–75 m, near the noise level |

One position (36.599 N 22.896 E, ~260–300 m) is unmatched in 6–7 scenes: a fixed
or long-term-moored object, already flagged as recurring and ranked last.

**STS: 4 candidates, all tier A (two hulls ≤ 150 m apart); 2 with no AIS on
either hull**, both in the 2026-09-03 16:30 scene:

| Position | Hull spacing | Length | Radar / AIS |
| -------- | ------------ | ------ | ----------- |
| 36.545 N 22.638 E | 44 m | ~176 m | 2 / 0 |
| 36.444 N 22.658 E | 74 m | ~214 m | 2 / 0 |

Both chips show two short parallel hulls side by side, the expected look of a
rafted STS pair at 10 m. Caveat: that same scene holds ~14 of the 65 unmatched
ships, clustered near 22.63–22.66 E, although GFW returned normal AIS volume for
it (121 cells). Corroboration from a second pass or optical imagery is needed
before these two are reported further. The Gulf of Laconia is a designated STS
transfer area, so AIS-visible transfers here are routine; the two above are of
interest only because neither hull has AIS.

### 4f. Optical cross-check (Sentinel-2) of the STS candidates

`src/optical.py`: for each AIS-unmatched tier A/B candidate (top 10 Oman, both
Laconia), the nearest-in-time Sentinel-2 L2A image clear over the spot
(SCL cloud / shadow / haze ≤ 20 % of a 1.5 km chip), within ±5 days.

| Region | Candidates | Nearest clear image | Pair visible at the spot |
| ------ | ---------- | ------------------- | ------------------------ |
| Oman | 10 | +5 h to −91 h (median ~40 h) | 0 |
| Laconia | 2 | +17 h | 0 |

The closest match in time (25.231 N 56.590 E, +5 h) is at a swath edge with
strong sun glint; no hull is visible. Other ships appear within a few hundred
metres in several chips, as expected in a busy anchorage, but not at the
candidate positions. **Result: no optical confirmation, and no contradiction.**
Sentinel-2 passes at ~06:46 UTC (Oman) / ~09:20 UTC (Laconia), never at the
radar time, and moored transfers typically last hours to a day or two, so an
empty sea hours later is the expected outcome either way. Same-time optical
confirmation needs a sensor passing close to the radar time (commercial
imagery, or Landsat/Sentinel-2 on a lucky overlap) and is left as future work.

## 5. CDSE σ⁰ VV+VH vs Planetary Computer DN VV

*Pending* — one-scene cost and quality check first (`src/fetch_cdse.py`), then a
paired retrain if it is worth the processing units.
