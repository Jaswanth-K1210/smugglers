"""Radar-to-AIS matching with physics, and how far to trust "no AIS here".

dark_sts.characterise answers "how many AIS identities were near this hull?" with a fixed
buffer. This module adds what a fixed buffer cannot see:

  - dead reckoning: an AIS report 40 min before the pass is moved along its course at its
    speed to where the ship should have been at pass time, before measuring distance;
  - physical feasibility: the speed the ship would have needed to reach the radar position
    from where it last reported. A 25 km jump in 10 min is not the same ship;
  - size consistency: radar hull length against the AIS length;
  - coverage confidence: whether "no AIS match" means anything at this place and time.

Nothing here decides intent. Outputs are candidates, distances and plain sentences.
"""
import math

import numpy as np
import pandas as pd

KN_TO_MPS = 1852 / 3600
MAX_KN = 30                  # faster than almost any merchant ship
BASE_TOL_M = 2000            # radar localisation + AIS position error + hourly GFW cells
DR_ERROR = 0.15              # dead reckoning drifts ~15 % of the distance projected
WINDOW_MIN = 60


def _metres(lat1, lon1, lat2, lon2):
    dlat = (np.asarray(lat2, float) - lat1) * 111_320
    dlon = (np.asarray(lon2, float) - lon1) * 111_320 * math.cos(math.radians(lat1))
    return np.hypot(dlat, dlon)


def project(lat, lon, sog, cog, hours):
    """Position after `hours` at `sog` knots on `cog` degrees (flat earth, fine for < 1 h)."""
    if sog is None or cog is None or sog != sog or cog != cog or sog < 0.3:
        return lat, lon
    d = sog * KN_TO_MPS * hours * 3600
    a = math.radians(cog)
    return (lat + d * math.cos(a) / 111_320,
            lon + d * math.sin(a) / (111_320 * math.cos(math.radians(lat))))


def candidates(lat, lon, t, ais, length_m=None, source=None, max_km=15, window_min=WINDOW_MIN):
    """AIS ships near one radar detection, nearest-in-time report per ship, best first.

    `ais`: mmsi, lat, lon, timestamp, optional sog, cog, length_m, name, type.
    Each candidate: distance at pass time, minutes from the pass, speed needed, size check
    and `plausible` (could this report be the ship the radar saw?)."""
    if ais is None or len(ais) == 0:
        return []
    t = pd.Timestamp(t)
    a = ais[(ais.timestamp >= t - pd.Timedelta(minutes=window_min)) &
            (ais.timestamp <= t + pd.Timedelta(minutes=window_min))]
    if a.empty:
        return []
    a = a.assign(_dt=(a.timestamp - t).abs()).sort_values("_dt").drop_duplicates("mmsi")
    a = a[_metres(lat, lon, a.lat.to_numpy(), a.lon.to_numpy()) <= max_km * 1000]
    out = []
    for r in a.itertuples(index=False):
        hours = (t - r.timestamp).total_seconds() / 3600       # >0: report came before the pass
        sog = getattr(r, "sog", None)
        cog = getattr(r, "cog", None)
        plat, plon = project(r.lat, r.lon, sog, cog, hours)
        dist = float(_metres(lat, lon, plat, plon))
        raw = float(_metres(lat, lon, r.lat, r.lon))
        travelled = (sog or 0) * KN_TO_MPS * abs(hours) * 3600 if sog == sog else 0
        tol = BASE_TOL_M + DR_ERROR * travelled
        need_kn = raw / max(abs(hours) * 3600, 60) / KN_TO_MPS if abs(hours) > 1 / 60 else 0.0
        ais_len = getattr(r, "length_m", None)
        ais_len = None if ais_len is None or ais_len != ais_len else float(ais_len)
        size = None
        if length_m and ais_len:
            ratio = length_m / ais_len
            size = "consistent" if 0.6 <= ratio <= 1.6 else "mismatch"   # SAR hull length is ±30 % at 10 m pixels
        plausible = dist <= tol and (need_kn <= MAX_KN or raw <= BASE_TOL_M)
        name = getattr(r, "name", None)
        ssvid, flag = getattr(r, "ssvid", None), getattr(r, "flag", None)
        mmsi = str(ssvid) if ssvid == ssvid and ssvid not in (None, "") else (str(r.mmsi) if str(r.mmsi).isdigit() else None)
        out.append({"id": str(r.mmsi), "name": None if name != name else name, "source": source,
                    "mmsi": mmsi, "flag": None if flag != flag else flag,
                    "distance_m": round(dist), "minutes_from_pass": round(-hours * 60),
                    "speed_needed_kn": round(need_kn, 1), "ais_length_m": ais_len, "size": size,
                    "type": getattr(r, "type", None) if getattr(r, "type", None) == getattr(r, "type", None) else None,
                    "plausible": bool(plausible)})
    return sorted(out, key=lambda c: (not c["plausible"], c["size"] == "mismatch", c["distance_m"]))


def explain(cands, ais_ok=True):
    """One sentence on the best candidate, or on why the nearest one is not a match."""
    if not cands:
        return None
    best = cands[0]
    who = best["name"] or "an unnamed ship"
    src = f" ({best['source']})" if best["source"] else ""
    when = f"{abs(best['minutes_from_pass'])} min {'before' if best['minutes_from_pass'] <= 0 else 'after'} the pass"
    if best["plausible"] and best["size"] == "mismatch":
        return (f"Nearest plausible AIS ship{src}: {who}, {best['distance_m']} m away, but it reports "
                f"{best['ais_length_m']:.0f} m long; the radar hull may be a different ship.")
    if best["plausible"]:
        return None                       # an ordinary match needs no extra sentence
    return (f"Nearest AIS ship{src}: {who}, {best['distance_m'] / 1000:.1f} km from where it should have been, "
            f"reported {when}; it would have needed {best['speed_needed_kn']:.0f} kn, so it is not a plausible match.")


def jamming_signs(reg):
    """Share of regional AIS positions that are physically impossible: on land, or implying > 50 kn
    between consecutive reports of the same ship. GPS jamming/spoofing in the Gulf shows up here."""
    if reg is None or len(reg) < 5:
        return {"positions": 0 if reg is None else len(reg), "on_land": None, "impossible_jumps": None}
    from global_land_mask import globe
    land = float(np.mean(globe.is_land(reg.lat.to_numpy(), reg.lon.to_numpy())))
    jumps, pairs = 0, 0
    for _, g in reg.sort_values("timestamp").groupby("mmsi"):
        if len(g) < 2:
            continue
        d = _metres_seq(g.lat.to_numpy(), g.lon.to_numpy())
        dt = np.diff(g.timestamp.to_numpy()).astype("timedelta64[s]").astype(float)
        ok = dt > 0
        kn = d[ok] / dt[ok] / KN_TO_MPS
        jumps += int((kn > 50).sum())
        pairs += int(ok.sum())
    return {"positions": len(reg), "on_land": round(land, 3),
            "impossible_jumps": round(jumps / pairs, 3) if pairs else None}


def _metres_seq(lat, lon):
    dlat = np.diff(lat) * 111_320
    dlon = np.diff(lon) * 111_320 * np.cos(np.radians(lat[:-1]))
    return np.hypot(dlat, dlon)


def coverage(sources, ships, n_ais_in_box, signs):
    """How far 'no AIS match' can be trusted here, 0-1, with the reasons.

    PROVISIONAL: a triage aid for the website, not the paper's fusion model
    (RESEARCH_POSITION 4.5). The multipliers below are hand-set and listed for the
    4.6 sensitivity sweep in docs/DATA_SOURCE_DECISIONS.md.

    sources: {name: bool} whether each AIS source had data around the pass.
    ships: radar ships, each with length_m and n_ais.
    n_ais_in_box: distinct AIS identities seen in the box around the pass.
    signs: jamming_signs() output.

    Big ships must carry AIS (SOLAS), so the share of radar hulls >= 100 m that match AIS is
    the strongest local evidence that reception works. It is only used with 5+ big hulls,
    because a box full of genuinely dark ships would otherwise lower its own coverage."""
    factors, score = [], 1.0
    if not any(sources.values()):
        return {"score": 0.0, "label": "none", "factors": ["No AIS source had data for this pass."]}
    names = [k for k, v in sources.items() if v]
    factors.append(f"AIS sources with data at the pass: {', '.join(names)}.")
    if len(names) == 1:
        score *= 0.85
    big = [s for s in ships if (s.get("length_m") or 0) >= 100]
    if len(big) >= 5:
        rate = sum(1 for s in big if s.get("n_ais", 0) > 0) / len(big)
        score *= 0.4 + 0.6 * rate
        factors.append(f"{rate:.0%} of radar hulls ≥ 100 m matched AIS ({len(big)} hulls).")
    if ships:
        density = n_ais_in_box / len(ships)
        if density < 0.3:
            score *= 0.6
            factors.append(f"Few AIS ships in the box ({n_ais_in_box}) for {len(ships)} radar ships.")
    if signs.get("on_land") is not None:
        bad = max(signs["on_land"], signs.get("impossible_jumps") or 0)
        if bad > 0.02:
            score *= max(0.3, 1 - 5 * bad)
            factors.append(f"Signs of GPS jamming or spoofing: {signs['on_land']:.0%} of AIS positions on land, "
                           f"{(signs.get('impossible_jumps') or 0):.0%} impossible jumps.")
    score = round(min(1.0, max(0.0, score)), 2)
    label = "good" if score >= 0.7 else "fair" if score >= 0.4 else "poor"
    return {"score": score, "label": label, "factors": factors}
