"""Search a region for dark vessels and dark ship-to-ship (STS) transfers.

The detector is trained where AIS is dense and reliable (Skagen) and applied
where unbroadcast traffic is expected (RESEARCH_POSITION.md §6). AIS outside
Denmark comes from GFW hourly presence on a ~1 km grid, so a scene whose GFW AIS
is missing or thin is EXCLUDED rather than counted: no AIS data is not evidence
of no AIS.

Two outputs per region:

  single vessels  — a detection with no AIS identity within 2 km / +-1 h.
  STS candidates  — two ships close together, found three ways, because at 10 m a
                    rafted pair is often one blob:
                      pair       two detections <= 500 m apart (<= 150 m = rafted)
                      wide       one hull wider than 99 % of AIS-matched ships of
                                 its length (rafted vessels lie side by side, so
                                 a pair is wider, not longer). Measured beam
                                 grows with ship size from blur and sidelobes,
                                 so the cutoff is per length band, per region.
                    Evidence tiers: A two hulls <= 150 m, B two hulls 150-500 m,
                    C one over-wide hull. Only A and B show two ships directly.
                      sts_class  the detector's own `sts` class
                    Each is checked by COUNTING: radar ships vs distinct AIS
                    identities within 1 km. One partner silent next to a
                    broadcasting one is the classic dark transfer, and a 2 km
                    "any AIS nearby" test cannot see it — the visible partner's
                    AIS would match both.
                    Then compared with GFW encounter events (AIS-visible STS): a
                    radar transfer with no encounter event is a dark-STS candidate.

    from src.hunt import run
    run("oman")
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests

from src import dark_sts, fetch_s1, gfw
from src.filters import clean_detections

REGIONS = {
    "laconia": (22.45, 36.35, 23.15, 36.80),   # Gulf of Laconia, Greece
    "oman": (56.30, 24.90, 56.80, 25.50),      # Fujairah anchorage, Gulf of Oman
}
near = dark_sts._metres_between
THIN = 0.3            # a scene with < 30 % of the region's median AIS cells is unreliable
DUP_M = 30            # closer than this is the same target detected twice
RAFTED_M = 150        # centre spacing of two hulls moored side by side
PAIR_M = 500          # the STS definition used in Phase 1
BANDS = [(0, 200), (200, 280), (280, 10_000)]   # hull length bands for the beam cutoff
COUNT_M = 1000        # radius for radar-vs-AIS counting (GFW grid is ~1 km)
VESSEL_CONF, STS_CONF = 0.4, 0.25


def scene_tif(tif, region, root=Path("/content/drive/MyDrive/darksts")):
    """The saved scene, re-downloaded to Drive if the runtime that held it is gone."""
    tif = Path(tif)
    if tif.exists():
        return tif
    out = root / f"hunt_{region}" / "scenes"
    if (out / tif.name).exists():
        return out / tif.name
    item_id = tif.stem.rsplit("_", 1)[0]                      # drop the _vv suffix
    r = requests.get(f"{fetch_s1.STAC}/collections/sentinel-1-grd/items/{item_id}", timeout=90)
    r.raise_for_status()
    return fetch_s1.fetch(r.json(), box=REGIONS[region], out_dir=out)


def dedupe(d, radius_m=DUP_M):
    """Within each scene keep the most confident detection per radius.

    Kept small on purpose: rafted partners sit 30-60 m apart, and a wider
    radius silently deletes one ship of every pair.
    """
    keep = []
    for _, g in d.sort_values("conf", ascending=False).groupby("scene"):
        k = []
        for i, r in g.iterrows():
            if not k or near(r.lat, r.lon, g.loc[k].lat, g.loc[k].lon).min() > radius_m:
                k.append(i)
        keep += k
    return d.loc[keep].reset_index(drop=True)


def thin_scenes(cells: dict, frac=THIN):
    """Scenes whose AIS cell count is missing or far below the region's median."""
    pos = [c for c in cells.values() if c > 0]
    if not pos:
        return set(cells)
    med = np.median(pos)
    return {s for s, c in cells.items() if c < frac * med}


def _presence(t, box, tries=3, wait=20):
    """GFW AIS around t, retried: GFW sometimes answers an empty window with null."""
    a = pd.DataFrame(columns=["mmsi", "lat", "lon", "timestamp"])
    for _ in range(tries):
        try:
            a = gfw.ais_presence(t - pd.Timedelta(hours=2), t + pd.Timedelta(hours=2), box)
            if len(a):
                return a
        except Exception as e:                       # network / 429 / 524
            print(f"   GFW error: {e}")
        time.sleep(wait)
    return a


def detect_region(box, start, end, weights, scene_dir, min_overlap=0.3):
    from src.run_pipeline import detect
    items = [i for i in fetch_s1.search(start, end, box=box, limit=200)
             if fetch_s1.overlap(i, box) >= min_overlap]
    print(f"{len(items)} scenes")
    raw = []
    for n, it in enumerate(items, 1):
        try:
            tif = fetch_s1.fetch(it, box=box, out_dir=scene_dir)
            d = detect(tif, weights, conf=STS_CONF)
            d = d[(d.cls == "sts") | (d.conf >= VESSEL_CONF)] if len(d) else d
            if len(d):
                d["tif"] = str(tif)
                raw.append(d)
            print(f"[{n}/{len(items)}] {len(d)} detections")
        except Exception as e:
            print(f"[{n}/{len(items)}] skipped: {e}")
    return dedupe(clean_detections(pd.concat(raw, ignore_index=True)))


def check_ais(clean, box):
    """GFW AIS per scene. Returns (res, excluded scenes, {scene: ais})."""
    res, cells, ais = [], {}, {}
    for n, (scene, g) in enumerate(clean.groupby("scene"), 1):
        a = _presence(pd.Timestamp(g.time.iloc[0]), box)
        cells[scene], ais[scene] = len(a), a
        res.append(dark_sts.characterise(g, a, buffer_m=2000, window_h=1))
        print(f"[{n}] {scene[:40]}  {len(a)} AIS cells")
    res = pd.concat(res, ignore_index=True)
    bad = thin_scenes(cells)
    return res[~res.scene.isin(bad)].reset_index(drop=True), bad, ais


def candidates(res, box):
    """Single AIS-unmatched detections, with recurrence and GFW radar corroboration."""
    un = res[(res.category == dark_sts.AIS_UNMATCHED) & (res.cls == "vessel")].copy()
    un["scenes_here"] = [res[near(r.lat, r.lon, res.lat, res.lon) < 200].scene.nunique()
                         for _, r in un.iterrows()]
    un["gfw_also_unmatched"] = False
    for day, g in un.groupby(pd.to_datetime(un.time).dt.date):
        try:
            s = gfw.sar_unmatched(str(day), box)
        except Exception as e:
            print(f"   GFW radar check skipped for {day}: {e}")
            continue
        for i, r in g.iterrows():
            un.at[i, "gfw_also_unmatched"] = bool(len(s)) and bool(
                (near(r.lat, r.lon, s.lat, s.lon) < 1500).any())
    return un


def hull_shape(res, k=30.0, half=40):
    """Measured hull length and beam (m) for every detection, from the image.

    Threshold at median + k MAD around the detection (the autolabel
    calibration), take the bright component nearest the centre, and read its
    principal axes: for a rectangle, side = sqrt(12 * variance). The detection
    box is axis-aligned, so it cannot give the beam of a ship lying diagonally.
    """
    from scipy import ndimage
    hull, beam = np.full(len(res), np.nan), np.full(len(res), np.nan)
    for tif, g in res.groupby("tif"):
        with rasterio.open(tif) as s:
            px = s.res[0]
            for i, r in g.iterrows():
                row, col = s.index(r.x, r.y)
                w = s.read(1, window=rasterio.windows.Window(col - half, row - half, 2 * half, 2 * half),
                           boundless=True, fill_value=0).astype(float)
                water = w[w > 0]
                if water.size < 50:
                    continue
                med = np.median(water)
                mad = max(np.median(np.abs(water - med)) * 1.4826, 1.0)
                lab, n = ndimage.label(w > med + k * mad)
                if n == 0:
                    continue
                cents = ndimage.center_of_mass(w, lab, range(1, n + 1))
                best = 1 + int(np.argmin([(y - half) ** 2 + (x - half) ** 2 for y, x in cents]))
                ys, xs = np.where(lab == best)
                if len(ys) < 3:
                    continue
                ev = np.sort(np.linalg.eigvalsh(np.cov(np.vstack([ys, xs]) * px)))
                beam[res.index.get_loc(i)] = np.sqrt(12 * max(ev[0], 0)) + px   # + one pixel
                hull[res.index.get_loc(i)] = np.sqrt(12 * ev[1]) + px
    out = res.copy()
    out["hull_m"], out["beam_m"] = hull.round(1), beam.round(1)
    return out


def mark_wide(res, q=0.99, min_n=50):
    """Flag hulls wider than the q-quantile of AIS-matched ships in their length band.

    AIS-matched ships are overwhelmingly single hulls, so they set what one ship
    measures like in this region's imagery. Returns (res, {band: cutoff_m}).
    """
    m = res[res.category != dark_sts.AIS_UNMATCHED]
    band = {b: m[(m.hull_m >= b[0]) & (m.hull_m < b[1])].beam_m.dropna() for b in BANDS}
    # too few matched ships and p99 is just the widest one seen: flag nothing in that band
    cut = {b: v.quantile(q) if len(v) >= min_n else np.nan for b, v in band.items()}
    wide = np.zeros(len(res), bool)
    for (lo, hi), c in cut.items():
        wide |= ((res.hull_m >= lo) & (res.hull_m < hi) & (res.beam_m > c)).to_numpy()
    out = res.copy()
    out["wide"] = wide
    return out, cut


def one_hull(tif, a, b, k=30.0, margin=20, along=0.8, bridge=3):
    """True when two pair detections are one radar object, not two ships.

    The main tier-B false alarm: one long hull, or a hull and its sidelobe
    cross, detected twice. Both detections then sit on the same bright
    component (threshold as in hull_shape). Further apart than RAFTED_M that is
    never two hulls. Closer, a rafted pair is also one component, so it is one
    hull only when the step from a to b runs along the component's long axis
    (|cos| > `along`); side by side is a rafted pair.
    """
    from scipy import ndimage
    with rasterio.open(tif) as s:
        (ra, ca), (rb, cb) = s.index(a.x, a.y), s.index(b.x, b.y)
        r0, c0 = min(ra, rb) - margin, min(ca, cb) - margin
        w = s.read(1, window=rasterio.windows.Window(c0, r0, abs(cb - ca) + 2 * margin,
                                                     abs(rb - ra) + 2 * margin),
                   boundless=True, fill_value=0).astype(float)
    water = w[w > 0]
    if water.size < 50:
        return False
    med = np.median(water)
    bright = w > med + k * max(np.median(np.abs(water - med)) * 1.4826, 1.0)
    # A big hull images as a chain of bright scatterers with dark gaps; bridge
    # gaps up to ~2 * bridge px so one hull stays one component.
    lab, n = ndimage.label(ndimage.binary_dilation(bright, iterations=bridge))

    def comp(r, c):                                   # component at or next to the centre
        win = lab[max(r - 3, 0):r + 4, max(c - 3, 0):c + 4]
        ids = win[win > 0]
        return int(np.bincount(ids).argmax()) if ids.size else 0

    la, lb = comp(ra - r0, ca - c0), comp(rb - r0, cb - c0)
    if la == 0 or la != lb:
        return False
    if near(a.lat, a.lon, b.lat, b.lon) > RAFTED_M:
        return True
    ys, xs = np.where(lab == la)
    axis = np.linalg.eigh(np.cov(np.vstack([ys, xs])))[1][:, -1]     # long axis (row, col)
    step = np.array([rb - ra, cb - ca], float)
    return bool(abs(axis @ step) / max(np.linalg.norm(step), 1e-9) > along)


def sts_candidates(res):
    """Two-ships-together candidates from pairs, over-wide hulls and the sts class.

    One row per candidate, merged when two lines of evidence point at the same
    spot (<= RAFTED_M) in the same scene.
    """
    rows = []
    for scene, g in res.groupby("scene"):
        g = g.reset_index(drop=True)
        la, lo = g.lat.to_numpy(), g.lon.to_numpy()
        for i in range(len(g)):
            d = near(la[i], lo[i], la[i + 1:], lo[i + 1:])
            for j in np.where(d <= PAIR_M)[0] + i + 1:
                a, b = g.loc[i], g.loc[j]
                try:
                    if one_hull(a.tif, a, b):
                        continue
                except Exception:                     # scene not on disk: keep the pair
                    pass
                rows.append({"scene": scene, "time": a.time, "tif": a.tif,
                             "lat": (a.lat + b.lat) / 2, "lon": (a.lon + b.lon) / 2,
                             "x": (a.x + b.x) / 2, "y": (a.y + b.y) / 2,
                             "evidence": "pair" if d[j - i - 1] > RAFTED_M else "rafted",
                             "spacing_m": round(float(d[j - i - 1])),
                             "length_m": max(a.length_m, b.length_m), "conf": min(a.conf, b.conf)})
        wide = g.wide.astype(bool) if "wide" in g else False
        for _, r in g[(g.cls == "sts") | wide].iterrows():
            rows.append({"scene": scene, "time": r.time, "tif": r.tif, "lat": r.lat, "lon": r.lon,
                         "x": r.x, "y": r.y, "spacing_m": 0, "length_m": r.length_m, "conf": r.conf,
                         "beam_m": r.get("beam_m", np.nan),
                         "evidence": "sts_class" if r.cls == "sts" else "wide"})
    c = pd.DataFrame(rows)
    if c.empty:
        return c
    merged = []
    for _, g in c.groupby("scene"):
        used = set()
        for i, r in g.iterrows():
            if i in used:
                continue
            same = g[near(r.lat, r.lon, g.lat, g.lon) <= RAFTED_M].index
            used.update(same)
            m = r.copy()
            m["evidence"] = "+".join(sorted(set("+".join(g.loc[same].evidence).split("+"))))
            merged.append(m)
    return pd.DataFrame(merged).reset_index(drop=True)


def count_identities(c, res, ais, radius_m=COUNT_M, window_h=1):
    """Radar ships vs distinct AIS identities around each STS candidate.

    `missing` = radar ships the AIS cannot account for. 0 -> AIS_VISIBLE,
    1 -> AIS_PARTIAL (one partner silent), 2+ -> AIS_UNMATCHED. Neighbouring
    traffic inflates both counts equally, which is why the difference is used
    rather than "is there any AIS".
    """
    out = []
    for _, r in c.iterrows():
        g = res[res.scene == r.scene]
        n_radar = int((near(r.lat, r.lon, g.lat, g.lon) <= radius_m).sum())
        n_radar = max(n_radar, 2)                     # a wide blob is two hulls
        # AIS radius padded by half a GFW cell diagonal: a cell's reported corner
        # can sit ~0.75 km from the ship. Padding only adds AIS, so `missing`
        # errs low — conservative for a dark claim.
        ids = dark_sts.identities_near(r, ais.get(r.scene), buffer_m=radius_m + 750,
                                       window_h=window_h)
        missing = max(n_radar - len(ids), 0)
        cat = (dark_sts.AIS_VISIBLE if missing == 0 else
               dark_sts.AIS_PARTIAL if missing == 1 else dark_sts.AIS_UNMATCHED)
        out.append({"n_radar": n_radar, "n_ais": len(ids), "missing": missing, "category": cat})
    return pd.concat([c.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def gfw_encounters(start, end, box):
    """All GFW encounter events (AIS-visible STS) in the box, as lat/lon/start/end."""
    rows, offset = [], 0
    while True:
        total, entries = gfw.events("encounters", start, end, box=box, limit=100, offset=offset)
        for e in entries:
            p = e.get("position") or {}
            rows.append({"lat": p.get("lat"), "lon": p.get("lon"),
                         "start": pd.Timestamp(e["start"]).tz_localize(None),
                         "end": pd.Timestamp(e["end"]).tz_localize(None)})
        offset += len(entries)
        if not entries or offset >= total:
            return pd.DataFrame(rows, columns=["lat", "lon", "start", "end"])


def mark_encounters(c, enc, radius_m=2000, pad_h=2):
    """True where an AIS-visible GFW encounter matches the candidate in space and time."""
    enc = enc.assign(start=pd.to_datetime(enc.start), end=pd.to_datetime(enc.end))   # empty -> object dtype
    hit = []
    for _, r in c.iterrows():
        t = pd.Timestamp(r.time)
        e = enc[(enc.start - pd.Timedelta(hours=pad_h) <= t) & (enc.end + pd.Timedelta(hours=pad_h) >= t)]
        hit.append(bool(len(e)) and bool((near(r.lat, r.lon, e.lat, e.lon) <= radius_m).any()))
    c = c.copy()
    c["gfw_encounter"] = hit
    return c


def chip_sheet(df, png, title, n=30):
    import matplotlib.pyplot as plt
    top = df.head(n)
    fig, axs = plt.subplots(6, 5, figsize=(15, 18))
    for ax, (_, r) in zip(axs.flat, top.iterrows()):
        with rasterio.open(r.tif) as s:
            row, col = s.index(r.x, r.y)
            img = s.read(1, window=rasterio.windows.Window(col - 60, row - 60, 120, 120),
                         boundless=True, fill_value=0).astype(float)
        v = img[img > 0]
        lo, hi = np.percentile(v, [1, 99.5]) if v.size else (0, 1)
        ax.imshow(np.clip((img - lo) / max(hi - lo, 1), 0, 1), cmap="gray")
        ax.plot(60, 60, "r+", ms=14)
        ax.set_title(title(r), fontsize=8)
    for ax in axs.flat:
        ax.axis("off")
    plt.tight_layout()
    plt.savefig(png, dpi=110)
    plt.close(fig)


def run(region, start="2026-07-01", end="2026-09-26", weights=None, out=None, reuse=False):
    """reuse=True skips detection and loads detections.csv from a previous run."""
    box = REGIONS[region]
    weights = Path(weights or "models/bench_rtdetr-l/weights/best.pt")
    if not weights.exists():
        weights = Path("/content/drive/MyDrive/darksts/models/bench/bench_rtdetr-l/weights/best.pt")
    out = Path(out or f"/content/drive/MyDrive/darksts/hunt_{region}")
    out.mkdir(parents=True, exist_ok=True)

    if reuse and (out / "detections.csv").exists():
        clean = pd.read_csv(out / "detections.csv", parse_dates=["time"])
        print(f"reusing {len(clean)} detections from {out / 'detections.csv'}")
        # scenes from a reset runtime: found in out/scenes, or downloaded there again
        tifs = {t: str(scene_tif(t, region, out.parent)) for t in clean.tif.unique()}
        clean["tif"] = clean.tif.map(tifs)
    else:
        clean = detect_region(box, start, end, weights, out / "scenes")   # on Drive: reuse survives a reset
        clean.to_csv(out / "detections.csv", index=False)   # survives a crash below
    res, bad, ais = check_ais(clean, box)
    print(f"\nexcluded {len(bad)} scene(s) with missing/thin GFW AIS")

    # single vessels
    un = candidates(res, box)
    res.drop(columns=["mmsis"]).to_csv(out / "all_checked.csv", index=False)
    un.drop(columns=["mmsis"]).to_csv(out / "ais_unmatched.csv", index=False)
    if len(un):
        chip_sheet(un.sort_values(["scenes_here", "gfw_also_unmatched", "conf"],
                                  ascending=[True, False, False]),
                   out / "ais_unmatched_chips.png",
                   lambda r: f"{str(r.time)[:16]} conf {r.conf:.2f}{' GFW✓' if r.gfw_also_unmatched else ''}"
                             f"\n{r.lat:.3f}N {r.lon:.3f}E ~{r.length_m:.0f} m"
                             f"{' (recurring)' if r.scenes_here > 1 else ''}")

    # STS — hull beam measured from the image; calibration printed so the 85 m
    # threshold can be checked against ships whose single identity is known
    res, cut = mark_wide(hull_shape(res))
    print("over-wide cutoff (p99 beam of AIS-matched ships) by hull length: " +
          ", ".join(f"{lo}-{hi if hi < 10_000 else '+'} m: {c:.0f} m" for (lo, hi), c in cut.items()))
    res.drop(columns=["mmsis"]).to_csv(out / "all_checked.csv", index=False)
    sts = sts_candidates(res)
    if len(sts):
        sts = count_identities(sts, res, ais)
        try:
            sts = mark_encounters(sts, gfw_encounters(start, end, box))
        except Exception as e:
            print(f"   GFW encounter check skipped: {e}")
            sts["gfw_encounter"] = False
        sts["dark_sts"] = (sts.missing >= 1) & ~sts.gfw_encounter
        # Hulls touching (rafted / one over-wide blob / sts class) is a transfer;
        # 150-500 m apart in a crowded anchorage may just be neighbours.
        sts["touching"] = sts.evidence.str.contains("rafted|wide|sts_class")
        sts["tier"] = np.where(sts.evidence.str.contains("rafted"), "A",
                      np.where(sts.evidence.str.contains("pair"), "B", "C"))
        sts = sts.sort_values(["dark_sts", "tier", "missing", "conf"],
                              ascending=[False, True, False, False])
        sts.to_csv(out / "sts_candidates.csv", index=False)
        chip_sheet(sts, out / "sts_chips.png",
                   lambda r: f"[{r.tier}] {str(r.time)[:16]} {r.evidence}\n"
                             f"radar {r.n_radar} / AIS {r.n_ais} -> {r.missing} silent"
                             f"{'  GFW-enc' if r.gfw_encounter else ''}  ~{r.length_m:.0f} m"
                             f"{f' beam {r.beam_m:.0f} m' if pd.notna(r.get('beam_m')) else ''}")

    print(f"\n{region}: {len(res)} ships checked | "
          f"{(res.category != dark_sts.AIS_UNMATCHED).sum()} AIS-matched | "
          f"{len(un)} single AIS-unmatched ({un.gfw_also_unmatched.sum()} GFW-corroborated)")
    if len(sts):
        print(f"STS candidates: {len(sts)} | by evidence {sts.evidence.value_counts().to_dict()}\n"
              f"  AIS: {sts.category.value_counts().to_dict()} | "
              f"{sts.gfw_encounter.sum()} match a GFW AIS encounter | "
              f"{sts.dark_sts.sum()} dark-STS candidates (>=1 ship silent, no AIS encounter)\n"
              f"  dark-STS by tier: " + str(sts[sts.dark_sts].tier.value_counts().sort_index().to_dict()) +
              "   (A two hulls <=150 m, B two hulls 150-500 m, C one over-wide hull)")
    print(f"saved to {out}")
    return res, un, sts
