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
| SAR                            | Sentinel-1 IW GRD via CDSE Sentinel Hub Process API               |
| Detector                       | YOLOv8, classes `vessel` + `sts` only                             |
| Vessel type/flag/length        | Registry/GFW enrichment on AIS matches — **never visual CNN classification** |
| GFW datasets                   | Reference/comparison layers only (SAR presence, presence grid, GAPs, encounters) |
| GFW role                       | Cross-system comparison. **Never ground truth.**                  |
| Dark label                     | Never simply `GFW matched='false'` → "dark". It is one signal.    |
| Primary risk                   | Cross-region STS events are rarer than in Kerch — **shipping of STS training labels** |
| Compute                        | Google Colab free tier                                          |
| Budget                         | **₹0 until feasibility proven** (first 7 days)                  |
| License/citation requirement   | GFW APIs are non-commercial; attribute GFW in the paper           |

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

### 4.4 Fusion evaluation experiment (the actual methods contribution)

Build a **fusion-reference dataset** of **100–300 candidate STS events**. For each event
record the full feature vector plus an independent human review label:

```
0 = non-STS / false detection
1 = probable STS
2 = probable dark / partially-dark STS
3 = high-confidence dark STS
```

Call these **expert-reviewed reference labels** — never "ground truth."

Compare five methods on the same reference set:

| # | Baseline / Method | Rule |
| --- | ----------------- | ---- |
| 1 | AIS-only | 0 identities → dark |
| 2 | SAR-only | SAR STS box → dark candidate |
| 3 | Simple AIS threshold | 0 / 1 / 2+ rule |
| 4 | GFW-reference | matched/unmatched + GAP + encounter rule |
| 5 | **Proposed multi-source fusion** | evidence-state classifier |

Report **precision, recall (where a reference exists), false-positive rate, and
disagreement patterns between evidence sources** (e.g., "SAR says STS, GFW says nothing").

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