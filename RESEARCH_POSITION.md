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

For every candidate STS event:

```
SAR STS detected
     │
     ├── AIS identities within 500 m / ±12 h         (≥0)
     ├── GFW SAR detection present?                  (yes/no)
     ├── GFW SAR `matched` flag?                     (true/false)
     ├── GFW AIS presence grid occupied?            (yes/no)
     ├── GFW encounter / AIS-off (GAP) events?      (yes/no)
     └── registry / vessel identity enrichment      (type/flag/length/OFAC)
              │
              ▼
          FUSION ENGINE
              │
      ┌───────┼───────┐
      ▼       ▼       ▼
  AIS-visible  Ambiguous  Dark candidate
```

### Outcome categories

1. **AIS-visible STS** — ≥2 distinct AIS identities in the spatial/temporal window.
   High confidence the event is AIS-visible.

2. **AIS-partially-visible STS** — exactly **1** AIS identity. Do NOT dump this into "dark."
   It can mean: one partner silent, AIS timing mismatch, AIS/GFW coverage limits, GFW matching
   limits, or detector localization error. This is where the fusion engine earns its keep.

3. **AIS-unmatched / dark candidate** — **0** distinct AIS identities pass the matching rule.
   Then consult the other signals:

| Own SAR STS | AIS IDs | GFW SAR | GFW match | GAP/encounter | Interpretation |
| ----------- | ------: | ------: | --------: | ------------: | ------------------------------ |
| ✓ | 2+ | ✓ | ✓ | ✓ | AIS-visible STS |
| ✓ | 1 | ✓ | ✓ | ✓ | Partially visible |
| ✓ | 0 | ✓ | false | ✓ | **Strong dark candidate** |
| ✓ | 0 | ✓ | false | — | Dark candidate, weaker |
| ✓ | 0 | — | — | — | Unconfirmed SAR candidate |
| ✓ | 0 | ✓ | true | ✓ | Possible own-detector / AIS-timing error |

Publishable deliverables: the matrix, the fusion rule, and the per-event outcome label.
The matrix is your **research dataset**.

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
3. **Fusion methodology.** How to combine heterogeneous, imperfect maritime signals when none
   is ground truth. *Emphasize hardest.*
4. **Cross-region generalization.** Train in European waters, test in Kerch/Hormuz/Malacca,
   measure degradation.
5. **Vessel-type/registry enrichment.** Detector says "geometry here"; registry says
   "tanker, flag, ~length." Delivers the "all vessel types" story without false visual claims.
6. **Reproducibility.** Code + config + acquisition + labels + evaluation dataset + fusion
   rules: the whole experiment runs without paying for PlanetScope or commercial AIS.

## 8. Things we will never claim

- "GFW independently validates our detections." → We say **cross-system comparison**.
  Both systems see the *same Sentinel-1 sensor*; independence is partial.
- "10 m SAR visually classifies tanker/bulk/container." → It doesn't. Registry does.
- "`matched=false` = dark ship." → It is **AIS-unmatched** SAR.
- "All straits, all vessel types." → Too absolute for the data. Use the phrasing in §6.

---

## 9. First action (Phase 0) — prove or kill the data assumption

Before any ML line of code:

> Can we obtain ≥50 useful AIS-derived STS events in Denmark/Baltic **and** match enough
> Sentinel-1 imagery to construct training examples?

- Continue → build the pipeline.
- Fail → change training region, do not push the model downstream.

This single decision outranks GFW integration, the dashboard, and the fusion engine.

---

## 10. Reproducibility contract

Repo layout target:

```
src/            pipeline modules (ais, autolabel, train, filters, fusion, dashboard)
data/           raw/processed (gitignored)
outputs/        evaluation dataset, fusion matrix, maps
tests/          smoke tests + synthetic fusion cases
references/     sat_tracker, sar_vessel_detect (study only)
```

Someone must be able to re-run the experiment for ₹0.