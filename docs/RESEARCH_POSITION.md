# Research Position — Dark STS Across Maritime Regions (Canonical Direction)

Companion to `PROJECT_PLAN.md`. This file is the **single source of truth for the research
claim and scope**. If the two disagree, this wins. Read this before touching any code.

Base paper: Ballinger, O. (2024), *Automatic Detection of Dark Ship-to-Ship Transfers Using
Deep Learning and Satellite Imagery*, arXiv:2404.07607.

---

## 1. What this project is NOT

**Not** "build a better dark-ship detector." GFW's Paolo et al. (2024, *Nature*) already
publishes global Sentinel-1 dark-vessel detections. You are not beating that, and you should
not frame yourself as trying to.

## 2. The research question

> **Can an open-data Sentinel-1 SAR pipeline detect and characterize suspicious ship-to-ship
> transfer (STS) events, and how reliably can multiple independent-ish signals distinguish
> AIS-visible, AIS-missing, and potentially dark STS activity across maritime regions?**

The unit of analysis is the **event**, not the vessel. The contribution is a
**fusion methodology over imperfect signals**, not a single detector.

---

## 3. Locked scope

| Component                      | Decision                                                          |
| ------------------------------ | ----------------------------------------------------------------- |
| Primary training regions       | Denmark / Skagen + Baltic (free raw AIS: DMA + HELCOM)            |
| Stretch training region        | US (MarineCadastre) — only if Denmark/Baltic pipeline is solid    |
| Test/generalization regions    | Hormuz, Malacca, Kerch — use trained model, **no separate training** |
| SAR                            | Sentinel-1 IW GRD via Microsoft Planetary Computer STAC — **no account**. See §3.1 |
| Detector                       | Ultralytics one-stage, classes `vessel` + `sts` only. Family chosen by benchmark, see §3.2 |
| Vessel type/flag/length        | Registry/GFW enrichment on AIS matches — **never visual CNN classification** |
| GFW datasets                   | Reference/comparison layers only (SAR presence, presence grid, GAPs, encounters) |
| GFW role                       | Cross-system comparison. **Never ground truth.**                  |
| Dark label                     | Never simply `GFW matched='false'` → "dark". It is one signal.    |
| Primary risk                   | Cross-region STS events are rarer than in Kerch — **shipping of STS training labels** |
| Compute                        | Google Colab free tier                                          |
| Budget                         | **₹0 until feasibility proven** (first 7 days)                  |
| License/citation requirement   | GFW APIs are non-commercial; attribute GFW in the paper           |

### 3.1 SAR source

Sentinel-1 GRD is accessed through **Microsoft Planetary Computer**, because the
originally planned CDSE Sentinel Hub route was unavailable throughout the
acquisition period. Both serve the same ESA archive; PC requires no account.

Two consequences carry into the method and are treated as experimental variables,
not assumptions — see §3.4:

1. **We geocode ourselves.** PC serves GRD in radar geometry with a ~210-point GCP
   grid. `rasterio.vrt.WarpedVRT` consumes those directly, so this is one call and
   not a SNAP chain. Output is UTM 32N at 10 m, so pixels are square metres and the
   length gate and spatial buffers work in metres.
2. **We work in raw DN**, not calibrated sigma-nought.

Full operational record, including the evidence CDSE was unusable, in
`docs/DATA_SOURCE_DECISIONS.md`.

### 3.2 Detector family: benchmarked, not asserted (2026-09-20)

The plan named YOLOv8. Nothing in the pipeline depends on that choice —
`src/train.py` takes `--model`, and every Ultralytics family shares one API, so
swapping is a string. Rather than declare a winner, `--benchmark` trains several
families on the **same split, same schedule, same data** and writes
`models/benchmark.csv`. The only variable is the backbone, so the numbers are
comparable and the paper reports a table instead of an assertion.

Default candidates: `yolov8n`, `yolo11n`, `yolo12n`. `--available` reports which
families the installed Ultralytics build can actually construct, since that
roster moves with the package version and training happens on Colab, not here.

**Architecture is not currently the binding constraint.** Measured on the Skagen
scene, vessel boxes run 19–33 px for 190–330 m ships, and the 30 m floor of the
length gate is 3 px — so small-object performance is the real limit. In order of
expected effect: more labelled scenes, then `imgsz`, then tile size, then model
family. A benchmark over 20 tiles from one scene would measure noise; run it once
`label_many()` has produced tens of scenes.

### 3.3 Evidence hierarchy

The contribution is multi-source fusion, not a GFW comparison. Sources rank:

```
PRIMARY     Sentinel-1 SAR  +  raw AIS          our own observation and identity evidence
SECONDARY   GFW-derived SAR / AIS products      one external evidence source among several
TERTIARY    registry / vessel metadata          attributes once identity exists
```

GFW is a derived product of somebody else's pipeline. It is weighted as one
secondary source and never as an arbiter. Any wording that positions this as "a
GFW comparison paper" misstates the contribution.

### 3.4 SAR preprocessing and polarisation as experiments, not assumptions

§3.1 records two processing choices. Neither is asserted; both are measured
against downstream detection performance, because a choice defended only by
argument is a choice a reviewer can attack.

**Radiometry.** Compare on the same scenes, same split:

| Arm | Input |
| --- | ----- |
| A | raw DN (current default) |
| B | log-scaled DN |
| C | calibrated sigma-nought |
| D | normalised backscatter |

Reported question: *does radiometric calibration materially affect vessel
detection under this pipeline?* Prior expectation is "little", because labelling
uses adaptive thresholding on relative contrast and Skagen boxes measured ≥20 dB
over local background — but a prior expectation is not a result.

**Polarisation.** Sentinel-1 IW over the AOI is dual-pol, so VV, VH and VV+VH are
all available at no extra acquisition cost. Compare all three. Even if VV-only
wins, the paper reports *"VV-only provided the chosen accuracy/compute tradeoff"*
rather than silently picking a channel.

### 3.5 Leakage control — binding rules

Adjacent SAR tiles overlap in sea state, wind streaks, incidence angle and often
contain the same vessel minutes apart. A random tile split puts near-duplicates
on both sides and reports a score the model has not earned. Enforced:

```
1. Splits are assigned by SCENE, never by tile.        (implemented: src/train.py)
2. No Sentinel-1 acquisition appears in two splits, including
   repeat slices of the same overpass.
3. No tile adjacent to a validation tile enters training.
4. No AIS from a test region is used in training or labelling.
5. GFW classifications never train, tune or select the detector. GFW AIS
   presence may confirm pseudo-labels, and this is disclosed. Nothing tuned on
   GFW data is scored against GFW data. (Amended 2026-10-04; see below.)
6. Test regions stay sealed until detector and fusion hyperparameters are frozen.
```

**Amendment to rule 5 (2026-10-04).** The original rule ("no GFW-derived product
trains or tunes the detector") was broken by the multi-region detector, whose
Gulf of Oman and Laconia pseudo-labels were confirmed with GFW AIS presence
(RESULTS.md §6), and would have been broken again by choosing the operating
threshold from recall against GFW AIS (RESULTS.md §7). What the rule exists to
stop is GFW's own *classifications* (its SAR detections and their matched flag,
gap and encounter events, vessel types) training or tuning the detector and GFW
then being used to score it. GFW AIS *presence* is plain AIS positions, the only
AIS available outside Denmark, so using it to confirm labels is a disclosed
exception, not a quiet one.

Condition attached to the amendment: **the final accuracy numbers come from data
independent of the tuning**: Skagen with Danish Maritime Authority AIS, and the
Gulf AIS recorder (`src/regional_ais.py`). GFW stays only as the cross-check
(test plan T7). The §7 recall figures, measured against GFW AIS in the training
months, are calibration, not final accuracy.

Rule 6 is the one most easily broken by accident. Hormuz, Malacca and Kerch are
not looked at, not tuned against, and not plotted until the training-region
pipeline is final.

### 3.6 Train / validation / test

The earlier framing jumped from training straight to geographic generalisation,
which leaves nowhere to tune. Three levels:

```
TRAIN        Denmark / Skagen + Baltic scenes
VALIDATION   held-out Denmark / Baltic SCENES — all model selection,
             all thresholds, all sensitivity analyses happen here
TEST         Hormuz, Malacca, Kerch — touched once, after freeze
```

Geographic degradation between validation and test is a **reported result**, not
something to be tuned away.

---

## 4. The fusion engine — the heart of the paper

### 4.1 Methodological contribution: multi-source evidence fusion

The system treats **no single data source as ground truth**. Sentinel-1 SAR provides the
image-based vessel/STS observation; AIS provides identity evidence; GFW SAR provides a
separate SAR-derived reference layer; GFW presence, gaps, and encounters provide additional
AIS-derived contextual evidence; registry information provides identity and vessel
attributes when an identity can be established.

The fusion layer is **evaluated as a classification methodology**, not presented as a
heuristic reporting layer. For every candidate STS event we assemble an **evidence state**:

```
SAR STS detected · AIS identity count (0/1/2+) · AIS gap duration ·
GFW SAR? · GFW SAR matched? · GFW presence? · GFW GAP? · GFW encounter? · registry match?
```

### 4.2 Positive vs. absence (negative) evidence — a hard rule

- **Positive evidence** — something observed: AIS identity present, GFW SAR detection
  present, GFW SAR matched, GAP event present, encounter present.
- **Absence evidence** — something not observed: no AIS identity, no GFW presence, no
  GFW match.

Absence is **not** equivalent to a positive signal. Enforce this in code and prose:

> Absence of GFW AIS presence shall **not independently increase dark-event confidence**,
> because absence may result from reception, coverage, gridding, or processing limitations
> rather than intentional AIS non-transmission.

Consequences: `AIS identity absent`, `GFW SAR unmatched`, and `GAP event present` are
*supporting* evidence for AIS-unmatched status. `GFW presence absent` is *weak /
non-informative* and is never added to a darkness confidence score.

#### 4.2.1 Measured evidence for the absence rule (2026-09-20)

Queried the GFW v3 events API for calendar year 2024 across our regions plus one
control, via `src/gfw.py`:

| Region                    | GFW gaps | GFW encounters |
| ------------------------- | -------: | -------------: |
| Skagerrak (training AOI)  |    **0** |             10 |
| Hormuz (test)             |        1 |            150 |
| Malacca (test)            |        4 |          2,326 |
| Kerch (test)              |        0 |              2 |
| Gulf of Guinea (control)  |      253 |             18 |

The query shape is verified: the same call returns 253 gaps in the Gulf of Guinea,
so zero in the Skagerrak is a property of the region, not a bug.

Gaps are abundant **only** in the control region, which has patchy AIS reception.
GFW's gap detection requires a disappearance that cannot be attributed to receiver
coverage, so gaps are structurally rare exactly where coastal reception is good —
Danish, Swedish and Norwegian waters included. This is §4.2's absence rule observed
in data rather than asserted, and the paper should present it as such.

Two consequences, both binding:

1. **`GFW GAP?` is not load-bearing anywhere in our scope.** It will be false for
   almost every candidate event in every region we work in. Treat a gap as a bonus
   when present; never let its absence move a score.
2. **`GFW encounter?` carries the comparison weight instead.** GFW encounters are
   that project's own ship-to-ship rendezvous detections, so they are the layer
   that actually shares our unit of analysis.

The Phase 0 kill criterion was therefore amended to test encounters rather than
gaps. Gaps play no role in the training region regardless: Skagerrak labels come
from DMA raw AIS, and GFW is a reference layer for the test regions only.

### 4.3 Outcome categories (characterization, not verdicts)

1. **AIS-visible STS** — ≥2 distinct AIS identities in the spatial/temporal window.
   High confidence the event is AIS-visible.

2. **AIS-partially-visible STS** — exactly **1** AIS identity. Do NOT dump this into "dark."
   It can mean: one partner silent, AIS timing mismatch, AIS/GFW coverage limits, GFW
   matching limits, or detector localization error.

3. **AIS-unmatched / dark candidate** — **0** distinct AIS identities pass the matching
   rule. Consult the other signals:

| Own SAR STS | AIS IDs | GFW SAR | GFW match | GAP/encounter | Interpretation |
| ----------- | ------: | ------: | --------: | ------------: | ------------------------------ |
| ✓ | 2+ | ✓ | ✓ | ✓ | AIS-visible STS |
| ✓ | 1 | ✓ | ✓ | ✓ | Partially visible |
| ✓ | 0 | ✓ | false | ✓ | **Strong dark candidate** |
| ✓ | 0 | ✓ | false | — | Dark candidate, weaker |
| ✓ | 0 | — | — | — | Unconfirmed SAR candidate |
| ✓ | 0 | ✓ | true | ✓ | Possible own-detector / AIS-timing error |

The table above is a *starting illustration* — the final classifier is learned and
evaluated (§4.4–4.5), not asserted.

#### 4.3.1 Why `sts` is a detector class — measured, not assumed

An STS transfer is a *relationship* between vessels, not an object, and this
document says the unit of analysis is the event. So treating `sts` as an object
class looks like a category error, and the obvious alternative is: detect vessels,
then pair them by proximity and orientation.

**That alternative fails on the physics, and we measured it.** In the Skagen scene
of 2025-06-08, four rafted pairs each produced a *single* bright blob, with the
two AIS identities resolving to byte-identical pixel boxes:

| Vessel A | Vessel B | Detected as |
| -------- | -------- | ----------- |
| RINA (120 m) | CAUVERI (252 m) | one blob, 271 m |
| ZIRCONE (124 m) | AK ANA (176 m) | one blob, 201 m |
| AMAK SWAN (93 m) | TRANSOCEAN (160 m) | one blob, 191 m |
| GAIA NORDIC (50 m) | FEED TRONDHEIM (100 m) | one blob, 100 m |

At 10 m ground resolution, two hull-to-hull vessels are not separable. A
pair-based approach has nothing to pair: there is one detection, not two, exactly
in the configuration we care about.

So the resolution is definitional, not architectural:

> `sts` is a **candidate-event detector** over a vessel configuration that
> Sentinel-1 renders as a single object. Its output is a candidate that enters the
> fusion layer as evidence. It is never, by itself, an STS event, and never a
> "dark" event.

Both paths are kept and compared, because resolvability depends on separation:

```
SAR scene
   ├── vessel detections ──┐
   └── sts detections ─────┤
                           ▼
              STS CANDIDATE EVENTS
    (merged-blob detections, plus pairs of
     vessel detections within the spatial /
     temporal rule where both ARE resolved)
                           ▼
              AIS · GFW · registry fusion
```

Reported as an ablation (§4.7): candidates from the `sts` class alone, from
vessel-pairing alone, and from both. Separation, not preference, decides which
recovers more real events.

### 4.4 Fusion evaluation experiment (the actual methods contribution)

Build a **fusion-reference dataset** of **100–300 candidate STS events**.

#### 4.4.1 Review labels describe the imagery, not the conclusion

The reference label answers only *"is this a ship-to-ship transfer?"* It must not
encode darkness, because darkness is what the fusion model exists to estimate.
Labelling events "probable dark" and then training a model to predict darkness is
circular, and a reviewer will say so.

**Review label — from imagery and context only:**

```
0 = non-STS / false detection
1 = probable STS
2 = confirmed / strong STS
```

**Evidence state — computed independently, never shown to the reviewer:**

```
AIS identity count (0 / 1 / 2+) · AIS gap duration · GFW SAR? ·
GFW SAR matched? · GFW presence? · GFW GAP? · GFW encounter? · registry match?
```

Darkness is then an *output* of fusion over the evidence state, evaluated against
the review label — never an input to it.

#### 4.4.2 Annotation protocol

"Expert-reviewed" on its own is not a method. Binding procedure:

```
Reviewer A ─┐
            ├─► independent labels ─► agree? ─ yes ─► final label
Reviewer B ─┘                           │
                                        no ─► adjudication by a third
                                               reviewer, recorded
```

- **Two independent reviewers** per event, working from a written guideline that
  defines what makes a configuration a probable versus confirmed STS (hull-to-hull
  contact, relative size, duration at low speed, anchorage context).
- **Blinded** to the fusion model's prediction, to the AIS identity count, and to
  every GFW field. Reviewers see imagery and basic context only.
- **Disagreements adjudicated** by a third reviewer; adjudicated items flagged.
- **Inter-annotator agreement reported** as Cohen's κ, with the confusion matrix
  between reviewers.

Because STS intent and the reason for AIS absence cannot be established from SAR
imagery alone, expert review is treated as a **reference annotation, not absolute
ground truth** — the labels carry the reviewers' uncertainty, and κ quantifies it.

#### 4.4.3 Baseline ladder

A progression, so "fusion helps" is demonstrated against something rather than
asserted. Baseline 0 matters most: without it there is no evidence the classifier
learned anything beyond the class prevalence.

| # | Baseline / Method | Rule |
| --- | ----------------- | ---- |
| 0 | **Random / prevalence** | predict the majority class, or sample at the base rate |
| 1 | AIS-only | identity count rule alone |
| 2 | SAR-only | SAR STS candidate alone |
| 3 | Rule-based fusion | the 0 / 1 / 2+ table of §4.3, hand-written |
| 4 | Logistic regression | interpretable linear model over the evidence state |
| 5 | Random forest / XGBoost | nonlinear reference |
| 6 | **Proposed interpretable fusion** | the contribution |

#### 4.4.4 Metrics

STS events are rare, so accuracy and ROC-AUC flatter a useless model. Report:

| Metric | Why |
| ------ | --- |
| **PR-AUC** | the headline number — robust when positives are rare |
| ROC-AUC | for comparability with other work |
| Precision / recall / F1 | per class, at the operating threshold |
| **Brier score** | are the probabilities honest, not just correctly ranked |
| **Calibration curve** | predicted 0.7 should mean 0.7 in reality |
| Confusion matrix | where the errors actually fall |
| False-positive rate | operational cost of an alert |
| Disagreement patterns | e.g. "SAR says STS, GFW says nothing" |

Confidence intervals by bootstrap over events, since n is 100–300.

#### 4.4.5 Model output is a distribution, not a verdict

The fusion model emits probabilities, never a binary label:

```
P(non-STS)   P(STS, AIS-visible)   P(STS, AIS-partial)   P(STS, AIS-unmatched)
```

An operator sees a ranked, calibrated confidence. Nothing in the output asserts a
vessel intentionally concealed itself — that is an inference about intent the data
cannot support.

> If fusion does not beat the simpler baselines, that is still a legitimate result:
> *"Additional GFW-derived evidence did not provide measurable improvement over the
> SAR-AIS baseline under the evaluated conditions."*

### 4.5 The fusion model itself — no invented weights

Start from evidence features, then evaluate in order:

```
rule-based baseline
  → logistic regression        ← preferred for small data / interpretable coefficients
  → random forest / XGBoost
  → proposed interpretable fusion
```

The contribution is an **interpretable multi-source evidence fusion framework**, not
"weights we chose because they seemed reasonable."

**Hard wording rules:**
- Say: *"our fusion framework characterizes the strength of evidence for AIS-unmatched STS
  events."*
- Never say: *"our fusion detects dark ships."*

### 4.6 Sensitivity analyses — no magic constants

Every threshold in the pipeline is currently a round number. A round number
defended by "it worked" is the easiest thing in the paper to attack. Each is swept
on the **validation** split and the chosen value reported with its curve.

| Constant | Current | Swept over | Decides |
| -------- | ------- | ---------- | ------- |
| STS spatial buffer | 500 m | 250 / 500 / 750 / 1000 m | identity-matching precision & recall |
| AIS match window | ±12 h | ±1 / ±3 / ±6 / ±12 / ±24 h | how much AIS silence counts as a gap |
| Label overpass window | ±30 min | ±5 / ±15 / ±30 / ±60 min | label positional accuracy |
| Land clearance | 1 km | 0.5 / 1 / 2 / 3 / 5 km | harbour rejection vs anchorage loss |
| Blob threshold `k` | 30 MAD | 3 → 40 | box length vs AIS length |
| Length gate | 30–400 m | 20/30/50 m floor | small-vessel recall vs clutter |

Two are already done and are the template for the rest:

- **Land clearance** — swept 0.5–5 km over 42,557 events. Totals fell 569→188
  between 0.5 and 1 km while tanker-involved events held at 71, then declined
  (69, 58, 39). 1 km chosen at the elbow.
- **Blob threshold** — swept against 114 AIS-matched vessels of known length. Box
  length / AIS length ran 2.05× at k=3, 1.38× at k=8, 1.14× at k=20, 1.07× at
  k=30. 30 chosen.

Temporal sensitivity deserves emphasis: STS is inherently temporal, and spatial
proximity alone does not define it. The ±12 h window is the least justified
constant in the document.

### 4.7 Ablation matrix — what does each source actually contribute?

The central experiment. Without it the paper demonstrates that a pipeline works,
but not that fusion was worth building.

| Run | SAR | AIS | GFW SAR | GFW encounter | GFW gap | Registry |
| --- | :-: | :-: | :-----: | :-----------: | :-----: | :------: |
| A | ✓ | | | | | |
| B | ✓ | ✓ | | | | |
| C | ✓ | ✓ | ✓ | | | |
| D | ✓ | ✓ | ✓ | ✓ | | |
| E | ✓ | ✓ | ✓ | ✓ | ✓ | |
| F | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Each run is the full fusion model retrained on that subset, scored by PR-AUC on
the same validation events. Reported as the marginal contribution of each source.

A second ablation over candidate generation (§4.3.1): `sts` class only,
vessel-pairing only, both.

**Expect E to add nothing.** §4.2.1 measured zero GFW gap events in the Skagerrak
and near-zero in every region except the poorly-covered control. A source that is
absent everywhere cannot carry weight, and demonstrating that is a result.

### 4.8 Hard-negative mining

SAR maritime detection fails on a well-known cast of bright things that are not
ships: wind farms, platforms, azimuth ambiguities, coastline returns, wakes, rain
cells, islets and breaking-wave clutter. The base paper's optical imagery never
had to deal with most of these.

```
train detector → run over negative-rich scenes → harvest false positives
              → add as hard negatives → retrain → measure FP rate change
```

Negative-rich scenes are chosen deliberately: offshore wind farms in the Kattegat,
high-wind acquisitions, coastline-heavy strips. The false-positive rate before and
after is a reportable result, not an implementation detail. The static-infrastructure
mask in `src/filters.py` already handles the recurring-position subset; hard-negative
mining covers what a positional mask cannot.

### 4.9 Success criteria — declared before results

Stated in advance so thresholds cannot be fitted to whatever came out.

| Level | Criterion | Status |
| ----- | --------- | ------ |
| **0 — Data feasibility** | ≥50 AIS-derived STS events/year in the AOI | **met**: 188 at-sea events in 7 days ≈ 9,800/yr |
| **1 — Labelling** | ≥70% of auto-generated boxes on real targets | **met**: 100% at ≥20 dB over local background |
| **2 — Detection** | mAP50 ≥ 0.40 on held-out validation *scenes*; small-vessel (<60 m) recall reported | pending |
| **3 — Fusion** | proposed fusion beats the best of baselines 0–3 on PR-AUC, by more than the bootstrap CI | pending |
| **4 — Generalisation** | test-region degradation *reported*, with no retraining and no tuning | pending |

Level 4 has no pass mark on purpose. Degradation across domains is a finding to
measure, not a bar to clear.

---

## 5. GFW population bias → benchmark variable, not weakness

GFW's SAR dataset is built around industrial-sized vessels; your YOLO can flag smaller ones
too. Do not merely report "our detector disagrees with GFW." Disaggregate disagreement by
**estimated vessel size** (from bounding-box diagonal):

```
<30 m · 30–60 m · 60–100 m · 100–150 m · 150–250 m · >250 m
```

Question to answer:

> Does our detector recover more SAR targets below the size range in which GFW's
> industrial-vessel dataset is strong?

That turns a comparison artifact into a result.

---

## 6. Generalization experiment (NOT per-region training)

```
              TRAIN
       Denmark + Baltic
              │
              ▼
         YOLO detector
         ────────────── Ten successive
              │         "unseen data" frames
       ┌──────┼──────┐
       ▼      ▼      ▼
    Hormuz  Malacca  Kerch
       │      │       │
       └──────┼───────┘
              ▼
       GFW reference layers
```

Research claim:

> How well does a detector trained in European waters generalize to geographically and
> operationally different maritime environments?

**Mandatory caveat sentence for the test regions** — put it verbatim in the paper:

> Because openly accessible raw AIS trajectories were not available at the same resolution as
> the training regions, dark-event validation relies partly on GFW's gridded AIS-derived
> presence products. These experiments therefore represent **cross-region generalization and
> reference analysis, not equivalent ground-truth evaluation**.

---

## 7. Contributions stack (ordered by value)

1. **Open-data reproduction.** Core Ballinger idea on free Sentinel-1 SAR + open AIS instead
   of PlanetScope + Lloyd's.
2. **Multi-signal dark-STS framework.** SAR + AIS + GFW SAR + GFW presence + GFW encounters +
   registry intelligence → structured event classification.
3. **Fusion methodology, evaluated against baselines.** An *interpretable* multi-source
   evidence fusion framework, tested against AIS-only / SAR-only / threshold / GFW-reference
   baselines on an expert-reviewed reference set. *Emphasize hardest.*
4. **Cross-region generalization.** Train in European waters, test in Kerch/Hormuz/Malacca,
   measure degradation.
5. **Vessel-type/identity enrichment (scoped).** Identity, not visual classification — with
   an explicit scope limit (see below).
6. **Reproducibility.** Code + config + acquisition + labels + evaluation dataset + fusion
   rules: the whole experiment runs without paying for PlanetScope or commercial AIS.

### 7.1 Hard scope statement — vessel-type coverage

> **Vessel-type coverage is achieved through identity enrichment, not SAR visual
> classification.**
>
> The SAR detector is responsible for detecting vessel geometry and STS configurations.
> Vessel type, flag, length, and other registry attributes are attached **only when** the
> detected vessel can be associated with an identifiable AIS/GFW/registry record.
>
> Consequently, vessel-type analysis applies primarily to **AIS-visible and partially-visible
> detections**. For **AIS-unmatched / dark candidates, vessel type may remain unknown** unless
> another independent source provides an identity or reliable attribute.
>
> This distinction prevents any unsupported claim of vessel type from 10-m Sentinel-1
> imagery alone.

This is a hard scope constraint, not a footnote. It modifies every place the docs or paper
say "all vessel types."

## 8. Things we will never claim

- "GFW independently validates our detections." → We say **cross-system comparison**:
  *GFW-derived SAR and AIS intelligence provides comparative evidence for evaluating and
  characterizing our SAR-derived STS candidates.* Both systems see the same Sentinel-1
  sensor; independence is partial.
- "10 m SAR visually classifies tanker/bulk/container." → It doesn't. Registry does, and
  only for identity-matched vessels (§7.1).
- "`matched=false` = dark ship." → It is **AIS-unmatched** SAR.
- "No GFW presence = dark." → Absence is weak / non-informative (§4.2).
- "Our fusion detects dark ships." → Our fusion **characterizes the strength of evidence
  for AIS-unmatched STS events**.
- "All straits, all vessel types." → Too absolute for the data. Use the phrasing in §6.

---

## 9. First action (Phase 0) — prove or kill the data assumption

Before any ML line of code:

> Can we obtain ≥50 useful AIS-derived STS events in Denmark/Baltic **and** match enough
> Sentinel-1 imagery to construct training examples?

- Continue → build the pipeline, and make the **fusion-reference dataset (100–300
  expert-reviewed candidate events) a formal deliverable**, not an end-of-project extra.
- Fail → change training region, do not push the model downstream.

This single decision outranks GFW integration, the dashboard, and the fusion engine.

---

## 9.5 Known limitations

Consolidated rather than scattered, because a limitations section a reviewer has
to assemble themselves reads as an omission.

1. **AIS coverage varies geographically.** Reception is excellent in Danish waters
   and poor in parts of the test regions, so AIS absence carries different meaning
   in each. Quantified in §4.2.1.
2. **GFW products are derived, not independent truth.** They are the output of
   another pipeline with its own detector, matcher and biases.
3. **Sentinel-1 resolution limits small-vessel interpretation.** At 10 m a 30 m
   vessel is three pixels; below that, detection and clutter are indistinguishable.
4. **SAR cannot establish identity.** Vessel type, flag and name come only from AIS
   or registry, never from pixels. Unmatched detections receive a size estimate and
   nothing more.
5. **AIS absence does not establish intentional concealment.** It may be reception,
   coverage, equipment failure, or processing. This is the document's central
   epistemic constraint, enforced in §4.2.
6. **Rafted vessels are not separable at 10 m.** Measured in §4.3.1: pairs merge
   into one blob, so per-vessel attribution inside an STS event is unavailable.
7. **Cross-region domain shift.** Sea state, traffic density, vessel population and
   incidence angle all differ between training and test regions.
8. **Training labels carry uncertainty.** They are AIS-derived and inherit AIS
   position error, timestamp error and the blob finder's own failures.
9. **Registry enrichment applies only to identifiable vessels**, which biases any
   type-conditioned analysis toward AIS-visible traffic — precisely the opposite of
   the population of interest.
10. **Raw DN is acquisition-dependent.** Without calibration, absolute brightness is
    not comparable across scenes; only within-scene relative contrast is used, and
    §3.4 tests whether this matters.
11. **Human review labels are reference annotations, not ground truth**, and their
    reliability is bounded by the reported inter-annotator agreement.
12. **Event counts are not incident counts.** A legal bunkering operation and an
    illicit transfer are geometrically identical in SAR. This work characterises
    evidence, not legality.

---

## 10. Reproducibility contract

Repo layout target:

```
src/            pipeline modules (ais, autolabel, train, filters, fusion, dashboard)
data/           raw/processed (gitignored)
outputs/        fusion-reference dataset, per-method metrics, fusion matrix, maps
tests/          smoke tests + synthetic fusion cases
references/     sat_tracker, sar_vessel_detect (study only)
```

Someone must be able to re-run the experiment for ₹0.