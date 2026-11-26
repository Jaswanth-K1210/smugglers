# OpenSTS IGARSS 2027 paper: handoff for the next revision

Give this file together with `paper/main.tex`, `paper/refs.bib` and `docs/RESULTS.md`
to the model or person writing the next version. State on 2026-11-26, branch
`paper-igarss`, commit `240a1cb`.

---

## 1. Rules the next version must keep

1. **Every number must be in `docs/RESULTS.md`** with the same value. The comment
   beside each paragraph (`% §4d, §4g`) names the RESULTS section.
   `python3 paper/check_numbers.py` must print "all paper numbers found in RESULTS.md".
   If a number is derived (a sum, a ratio), add it to `DERIVED` in that script with
   its source.
2. **Never say "dark" about our detections.** Say *AIS-unmatched*. AIS absence can be
   reception, coverage, equipment failure or processing. "Dark" is allowed only when
   quoting another paper's title or term (Ballinger, xView3).
3. **No candidate is confirmed.** Do not write that any STS transfer happened.
4. **Solo author:** K. Jaswanth, Independent Researcher, Hyderabad, India. No team,
   no guide, no "we thank our supervisor".
5. **4 pages including references** (IGARSS limit). It is at 4 now; the references
   spill onto page 4. Related Work is the first thing to cut.
6. `\tbd{...}` (red text) marks things still open. Do not delete red text unless the
   number behind it is settled in RESULTS.
7. Build: `tectonic paper/main.tex`. Figure 2 is `paper/fig2.pdf` (do not regenerate).

---

## 2. What changed from the first draft (05df3a2) to now

### Author block
- Was: placeholder "Affiliation (or Independent researcher), city, country, email".
- Now: K. Jaswanth, Independent Researcher, Hyderabad, India, email.

### Abstract
- "15 AIS-unmatched STS candidates" → **"12 AIS-unmatched STS candidates"**.
- Everything else unchanged.

### Introduction and Related Work
- Were bullet-point notes (`% TODO`).
- Now full drafts written by Claude from those notes. Marked
  `% DRAFT by Claude ... rewrite`. **They must be rewritten in the author's own words**
  (see §4 below for what to check).
- `\nocite{*}` removed: every reference is now cited in the text.

### Method
- Detector citation: `\cite{ultralytics,rtdetr}` → `\cite{ultralytics,yolo26,rtdetr}`.
- One-hull rule, new last clause: *"two parts up to 200 m apart count as one hull with
  a dark gap when each points along the line between the detections or is round, and
  at least one is long."* (Reason: a big tanker often images as a bright bow and a
  bright superstructure with a dark deck between them, so one ship looked like two.)

### Results: STS candidates
| | First draft | Now |
|---|---|---|
| Oman | 14 (A 1, B 9, C 4) | **11 (A 0, B 7, C 4)** |
| Laconia | 1 (A 1) | 1 (A 1) |
| Total | 15 | **12** |

Why each changed (all recorded in RESULTS §4g):
- **Tier C (over-wide hull):** most "over-wide" hulls were one bright ship whose thin
  radar sidelobe cross was measured as width. Beam is now measured after removing
  features thinner than 30 m (3×3 binary opening). Oman C 11 → 4.
- **Tier B (two hulls 150–500 m apart):** two pairs (2026-07-17, 2026-07-23) were one
  tanker with a dark middle; parts 139 m and 178 m apart. Fixed by the 200 m split-hull
  rule. B 9 → 7. Pair 2026-09-25 (187 m, hulls at different headings) correctly stays.
- **Tier A (two hulls ≤150 m apart):** the only Oman tier-A pair (2026-09-22, 39 m
  apart, ~325 m hull) was two detection boxes on one tanker. A 1 → 0.
- **Laconia tier A** (2026-09-03, two parallel hulls 74 m apart, no AIS on either)
  passes every check and stays. It is Figure 2(d).
- Red note was "...; two tier-B pairs look like one hull." Now only: *"Provisional:
  34 newly over-wide detections await AIS counting (GFW presence API down)."*

### Figure 2
- Was a placeholder box.
- Now `fig2.pdf`, 2×2 Sentinel-1 VV chips with 200 m scale bars: (a) Oman AIS-unmatched
  vessel also unmatched by GFW, (b) same for Laconia, (c) Oman tier-C over-wide hull,
  (d) Laconia tier-A pair.

### References (`refs.bib`), already verified
- `ballinger2024`: added pages 8943–8948 and DOI 10.1109/IGARSS53475.2024.10641983
  (replaced the arXiv note).
- `li2017`: added address Beijing, China and DOI 10.1109/BIGSARDATA.2017.8124934.
- `rtdetr`: full 8 authors (was "and others"), pages 16965–16974.
- `yolo26`: new entry, arXiv:2606.03748 (2026).

### Outside the paper (no text change needed, mention only if space)
- Licences: code AGPL-3.0 (because Ultralytics YOLO is AGPL-3.0); labels, detections
  and weights CC BY-NC 4.0 (because derived from GFW data). See `LICENSE`,
  `DATA_LICENSE.md`.

---

## 3. Current numbers (all from RESULTS.md)

| Claim | Value | RESULTS § |
|---|---|---|
| Label audit, overall mAP50 | 0.156 → 0.380 (vessel 0.311 → 0.419, sts 0 → 0.341) | §1 |
| Skagen labels after fix | 854/63 boxes on 223 tiles → 516/64 on 170 | §1 |
| Doppler offset | 61 m below 1 kn → 376 m above 10 kn, ~60 m/kn | §1 |
| Four families, same labels | overall mAP50 0.348–0.402, spread 0.054 | §2, §3 |
| Multi-region set | 339 tiles (Skagen 170, Oman 140, Laconia 29), 284/55 | §6 |
| Skagen-only on new regions | 0.113 vessel mAP50 | §6b |
| Five multi-region detectors, new regions | 0.512–0.558 | §6b |
| Served model | YOLO26n, 0.31 s/tile CPU | §6b |
| Leave-one-region-out | Oman 0.122–0.140, Laconia 0.183–0.217, Skagen 0.428–0.509 | §6c |
| Oman AIS-unmatched, ≥100 m, also unmatched by GFW | 168 (of 7,417 checked, 512 unmatched, 213 +GFW) | §4c |
| Top 30 Oman inspected | all large ships, 134–388 m | §4c |
| STS candidates | 12 (Oman 11: B 7, C 4; Laconia 1: A 1) | §4g |
| GFW encounter events, Oman | 2 | §4d |
| Optical check | 12 candidates, none confirmed or ruled out; median gap ~40 h | §4f |

---

## 4. Introduction and Related Work: what to check when rewriting

Rewrite both in your own words, then check each claim below against the paper it cites.
Do not keep a sentence you cannot back with the source.

**Introduction**
- "AIS alone reveals transshipment only when both vessels broadcast [miller2018]":
  check that Miller et al. say this (they use AIS-only encounter/loitering events).
- "Sentinel-1 provides it free of charge [torres2012]": fine, but the free-data policy is
  Copernicus's, not the 2012 mission paper's. OK to keep the citation for Sentinel-1.
- **Ballinger contrast, check carefully.** Open Ballinger 2024 and note: (a) which
  imagery it uses (Sentinel-1 SAR, Sentinel-2 optical, or both), (b) whether it is
  free data, (c) whether code/data are released. If Ballinger also uses only free
  Sentinel data, contrast (i) "only free data end to end" is weak. Then lean on
  (ii) the audited labeler and (iii) evidence tiers + GFW cross-check, and say
  precisely what differs (e.g. regions, AIS source, one-hull rule, release).
- Contributions list (3 items) should match what Results actually shows. Currently it does.

**Related Work**
- "SSDD [li2017] and HRSID [wei2020], small chips with manual boxes": check chip sizes
  and that labels are manual.
- "xView3-SAR pairs full Sentinel-1 scenes with AIS-derived labels": xView3 labels
  combine AIS matching **and** manual annotation. Say that correctly.
- "Paolo et al. [paolo2024] extended this to a global map of vessels missing from
  public AIS": check the scope (industrial vessels, coastal waters, 2017–2021) and
  their headline figure if you quote one.
- "GFW, building on [kroodsma2018], publishes encounter events": kroodsma2018 is the
  fishing-effort paper; encounter events come from GFW's data products (Miller et al.
  2018 is the closer source). Consider citing miller2018 for encounters instead.
- Keep it to ~0.3 page.

---

## 5. References still to verify (9 entries)

Open each on the publisher's page (DOI link) and confirm: **author list and spelling,
title (exact capitalisation), venue name, volume, issue, pages, year**. Add the DOI
field to each. The DOIs below are what I expect; confirm each resolves to the right paper.

| Key | Check | Expected DOI (confirm) |
|---|---|---|
| `paolo2024` | Nature 625, 85–91, 2024; first ~3 authors + "others" fine for IEEE | 10.1038/s41586-023-06825-8 |
| `paolo2022` | NeurIPS 2022 Datasets & Benchmarks; add volume (35) and pages if the proceedings list them; else add arXiv:2206.00897 | none (NeurIPS) |
| `kroodsma2018` | Science 359(6378), 904–908, 2018 | 10.1126/science.aao5646 |
| `miller2018` | Front. Mar. Sci. 5, article 240, 2018; 5 authors spelled right | 10.3389/fmars.2018.00240 |
| `torres2012` | Remote Sens. Environ. 120, 9–24, 2012; title "GMES Sentinel-1 mission" | 10.1016/j.rse.2011.05.028 |
| `raney1971` | IEEE Trans. Aerosp. Electron. Syst. AES-7(3), 499–505, 1971 | 10.1109/TAES.1971.310292 |
| `wei2020` | IEEE Access 8, 120234–120254, 2020; 6 authors | 10.1109/ACCESS.2020.3005861 |
| `ultralytics` | Use the citation the GitHub repo gives (CITATION.cff): authors, title, version, year; add the version you used | Zenodo DOI if CITATION.cff gives one |
| `pc2022` | Zenodo record: authors and year match the record | 10.5281/zenodo.7261897 |

Also check: every `\cite{}` key exists in `refs.bib`, and no bib entry is uncited
(`\nocite{*}` is gone, so uncited entries just vanish from the list).

---

## 6. Still open (do not invent these)

- **34 newly over-wide detections** need AIS identity counts from GFW. GFW's presence
  API is down. Keep the red `\tbd` note until notebook `07_tierc.ipynb` §8a–8c is
  rerun and the result is added to RESULTS. The STS count of 12 may change.
- **Zenodo DOI** in the abstract is `XXXXXXX`.
- **Template:** preamble is IEEEtran as a stand-in; swap for the official IGARSS 2027
  kit. Body should need no change.

---

## 7. Prompt to give Claude with this file

> Revise `paper/main.tex` for IGARSS 2027 using `docs/PAPER_HANDOFF.md`,
> `docs/RESULTS.md` and `paper/refs.bib`. Rewrite the Introduction and Related Work
> in plain, precise academic English, keeping their content and citations but
> applying the checks in §4. Do not change any number; every number must be in
> RESULTS.md, and `python3 paper/check_numbers.py` must pass. Never call our
> detections "dark". Keep red `\tbd` text. Stay within 4 pages including references
> (`tectonic paper/main.tex`). Update `refs.bib` with the verified fields I give you
> from §5. Show me a diff of what you changed and why.
