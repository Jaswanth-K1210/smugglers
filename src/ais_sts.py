"""Extract ship-to-ship transfer events from AIS tracks.

The rule, exactly as specified: two vessels within 500 m of each other, for at
least an hour, both under 1 knot.

These events are the Phase 3 training signal — each one tells the auto-labeller
where to look for a rafted pair in a SAR scene at a known time. They are not
themselves detections, and nothing here is ever called "dark": every vessel in
this file is by definition broadcasting AIS.

Approach: bin positions to a 5-minute grid per vessel (a median-10-messages bin,
so binning loses nothing), project to metres, then run one spatial pair query
per bin. Brute-force pairwise over 4.5M rows a day would be hopeless; per-bin
KD-tree queries over a few hundred slow vessels are instant.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rasterio.warp import transform as warp_transform
from scipy.spatial import cKDTree

from src import ais
from src.config import DATA

OUT = DATA / "labels"
METRIC_CRS = "EPSG:32632"  # same UTM zone the SAR tiles land in, see fetch_s1

# ponytail: output is dominated by harbours — berthed boats satisfy the rule
# perfectly, and Hirtshals plus Frederikshavn alone account for well over half
# of one day's events. The honest fix is distance from shore, and Phase 5
# already has to build a land/coastline mask for the SAR detections. Reuse that
# mask here rather than growing a second one.


def _runs(bins, max_gap: int = 1):
    """Group sorted bin indices into runs, tolerating short dropouts.

    AIS reception drops the odd message, and a single missing 5-minute bin
    should not split one two-hour contact into two sub-threshold halves.
    Returns (first_bin, last_bin, n_bins) per run.
    """
    if len(bins) == 0:
        return []
    runs, start, prev, seen = [], bins[0], bins[0], 1
    for b in bins[1:]:
        if b - prev <= max_gap + 1:
            seen += 1
        else:
            runs.append((start, prev, seen))
            start, seen = b, 1
        prev = b
    runs.append((start, prev, seen))
    return runs


def _to_metres(lon, lat):
    x, y = warp_transform("EPSG:4326", METRIC_CRS, np.asarray(lon), np.asarray(lat))
    return np.column_stack([x, y])


def _binned(df, bin_minutes, max_sog, exclude_moored):
    """Slow-moving vessels, one position per vessel per time bin."""
    slow = df[df.sog.notna() & (df.sog < max_sog)]
    if exclude_moored:
        # Moored vessels sit alongside a quay within 500 m of each other for
        # hours. They satisfy the rule and are never a transfer at sea.
        slow = slow[slow.nav_status != "Moored"]
    slow = slow.assign(bin=slow.timestamp.dt.floor(f"{bin_minutes}min"))
    return slow.groupby(["bin", "mmsi"], as_index=False).agg(
        lat=("lat", "median"), lon=("lon", "median"), sog=("sog", "median"),
        name=("name", "first"), ship_type=("ship_type", "first"), length=("length", "first"),
    )


def sts_events(dates, box=None, radius_m: float = 500, min_minutes: float = 60,
               max_sog: float = 1.0, bin_minutes: int = 5, exclude_moored: bool = False,
               max_minutes: float = None, min_length_m: float = 0):
    """STS events over the given dates (list of YYYY-MM-DD). Returns a DataFrame.

    Defaults are the specified rule and nothing else: within `radius_m`, for at
    least `min_minutes`, both under `max_sog`. Three optional exclusions are
    available but off, because the rule is the rule:

    `exclude_moored`  — drop pairs reporting AIS navigational status "Moored".
    `max_minutes`     — drop contacts longer than this; a berth is permanent,
                        a transfer is bounded.
    `min_length_m`    — drop pairs where either vessel is shorter than this.
                        30 m matches the gate Phase 5 applies to SAR detections;
                        below it a vessel is a pixel or two at 10 m resolution.

    For scale, one day of the AOI under the bare rule yields 6857 events, 1183
    of them spanning the full 24 hours and clustering on Hirtshals and
    Frederikshavn harbours. All three exclusions together leave 54.
    """
    frames = [_binned(ais.load(d, box=box), bin_minutes, max_sog, exclude_moored) for d in dates]
    binned = pd.concat(frames, ignore_index=True)
    if binned.empty:
        return pd.DataFrame()

    # Contacts per time bin. Pair keys are ordered so a pair is one key, not two.
    contacts = {}
    for bin_time, grp in binned.groupby("bin", sort=True):
        if len(grp) < 2:
            continue
        mmsi = grp.mmsi.to_numpy()
        tree = cKDTree(_to_metres(grp.lon.to_numpy(), grp.lat.to_numpy()))
        for i, j in tree.query_pairs(radius_m):
            contacts.setdefault((min(mmsi[i], mmsi[j]), max(mmsi[i], mmsi[j])), []).append(bin_time)

    step = pd.Timedelta(minutes=bin_minutes)
    info = binned.drop_duplicates("mmsi").set_index("mmsi")
    events = []
    for (a, b), times in contacts.items():
        # DatetimeIndex, not np.array: the latter gives an object array of
        # Timestamps, which will not do arithmetic against a Timestamp.
        times = pd.DatetimeIndex(sorted(set(times)))
        idx = ((times - times[0]) // step).to_numpy()
        for first, last, n in _runs(idx):
            start, end = times[0] + first * step, times[0] + last * step
            minutes = (end - start) / pd.Timedelta(minutes=1)
            if minutes < min_minutes or (max_minutes and minutes > max_minutes):
                continue
            if min_length_m and not (
                info.length.get(a, 0) >= min_length_m and info.length.get(b, 0) >= min_length_m
            ):
                continue
            here = binned[(binned.mmsi.isin([a, b])) & binned.bin.between(start, end)]
            events.append({
                "start": start, "end": end, "duration_min": round(minutes, 1),
                "mmsi_a": a, "mmsi_b": b,
                "name_a": info.name.get(a), "name_b": info.name.get(b),
                "type_a": info.ship_type.get(a), "type_b": info.ship_type.get(b),
                "length_a": info.length.get(a), "length_b": info.length.get(b),
                "lat": round(here.lat.median(), 5), "lon": round(here.lon.median(), 5),
                "n_bins": n,
            })
    out = pd.DataFrame(events)
    return out.sort_values("duration_min", ascending=False).reset_index(drop=True) if len(out) else out


def map_events(events, out_html: Path = None, n: int = None):
    """Drop events on a map so they can be eyeballed. All of them by default.

    Plotting all of them rather than a sample is the point: the harbour
    clustering is obvious at a glance and invisible in any top-N listing.
    """
    import folium

    out_html = out_html or OUT / "sts_sample.html"
    out_html.parent.mkdir(parents=True, exist_ok=True)
    top = events if n is None else events.head(n)
    m = folium.Map(location=[top.lat.mean(), top.lon.mean()], zoom_start=9, tiles="OpenStreetMap")
    for _, e in top.iterrows():
        folium.Circle([e.lat, e.lon], radius=500, color="red", fill=True, fill_opacity=0.15).add_to(m)
        folium.Marker(
            [e.lat, e.lon],
            popup=folium.Popup(
                f"<b>{e.name_a or e.mmsi_a}</b> ({e.type_a}, {e.length_a}m)<br>"
                f"<b>{e.name_b or e.mmsi_b}</b> ({e.type_b}, {e.length_b}m)<br>"
                f"{e.start:%Y-%m-%d %H:%M} &rarr; {e.end:%H:%M}<br>"
                f"{e.duration_min:.0f} min",
                max_width=320),
        ).add_to(m)
    m.save(out_html)
    print(f"map: {out_html}")
    return out_html


if __name__ == "__main__":
    dates = sys.argv[1:] or ["2025-06-08"]
    ev = sts_events(dates)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"\n{len(ev)} STS events over {len(dates)} day(s)")
    if len(ev):
        cols = ["start", "duration_min", "name_a", "type_a", "name_b", "type_b", "lat", "lon"]
        print(ev[cols].head(15).to_string(index=False))
        ev.to_csv(OUT / "sts_events.csv", index=False)
        print(f"\nwrote {OUT / 'sts_events.csv'}")
        map_events(ev)
