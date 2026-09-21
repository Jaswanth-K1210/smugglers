"""False-positive filters shared by label generation and detection.

Built for Phase 3 (keep harbour events out of the training labels) and reused
by Phase 5 (keep land returns out of the detections), so there is one land mask
in this project rather than two.

Why it is needed: under the bare STS rule, 49% of one week's AIS events sit in
Frederikshavn and Hirtshals harbours. Berthed vessels are within 500 m of each
other, under 1 knot, for days. A training label centred on a packed quay would
teach the detector that a harbour is a transfer.

The mask is global_land_mask's bundled 30 arcsec grid — about 900 m, offline,
no download and no API key.
"""
import numpy as np
from global_land_mask import globe

EARTH_KM_PER_DEG = 111.32

# ponytail: 30 arcsec resolves a coastline to roughly 900 m, which is why
# `at_sea` asks for clearance rather than trusting a single point lookup. If
# Phase 5 needs true metre-accurate shorelines for SAR tiles, swap the backend
# for a vector coastline (Natural Earth / GSHHG) behind these same functions.


def is_land(lat, lon):
    """Elementwise land test. Accepts scalars or arrays."""
    return globe.is_land(np.asarray(lat, dtype=float), np.asarray(lon, dtype=float))


def land_within(lat, lon, km: float, bearings: int = 12, rings: int = 3):
    """True where any land lies within `km` of the point.

    Samples a small polar grid around each point instead of one lookup, because
    a 900 m mask cell can fall in a harbour basin while the quay 300 m away is
    land. Centre point included.
    """
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    hit = is_land(lat, lon).copy()

    angles = np.linspace(0, 2 * np.pi, bearings, endpoint=False)
    for r in np.linspace(km / rings, km, rings):
        dlat = r / EARTH_KM_PER_DEG
        dlon = r / (EARTH_KM_PER_DEG * np.cos(np.radians(lat)))
        for a in angles:
            probe_lat = np.clip(lat + dlat * np.sin(a), -90, 90)
            probe_lon = (lon + dlon * np.cos(a) + 180) % 360 - 180
            hit |= is_land(probe_lat, probe_lon)
    return hit


def at_sea(lat, lon, min_km: float = 1.0):
    """True where the point is water with `min_km` of clearance from land.

    1 km is measured, not guessed. Sweeping the threshold over one week of AIS
    events, total counts fall 569 -> 188 between 0.5 km and 1 km while the
    tanker-involved subset holds at 71: that band is entirely coastal clutter.
    Past 1 km the tanker count starts dropping (69, 58, 39 at 1.5, 2 and 5 km),
    which is genuine anchorage transfers being deleted.
    """
    return ~land_within(lat, lon, min_km)


def drop_coastal(events, min_km: float = 1.0, lat_col: str = "lat", lon_col: str = "lon"):
    """Keep only the rows of an events DataFrame that sit `min_km` clear of land."""
    if events.empty:
        return events
    keep = at_sea(events[lat_col].to_numpy(), events[lon_col].to_numpy(), min_km)
    return events[keep].reset_index(drop=True)


if __name__ == "__main__":
    spots = {
        "Frederikshavn harbour": (57.72, 10.59),
        "Hirtshals harbour": (57.59, 9.96),
        "Skagen anchorage": (57.70, 10.75),
        "Skagerrak open sea": (57.85, 10.30),
    }
    for name, (la, lo) in spots.items():
        print(f"{name:24} is_land={bool(is_land(la, lo))!s:6} at_sea(1km)={bool(at_sea(la, lo)[0])}")


# --- Phase 5: detection-side false-positive control ------------------------
# SAR produces bright targets that are not ships. The base paper's optical
# imagery never had to deal with wind turbines, platforms or azimuth
# ambiguities; we do.

def length_gate(detections, min_m: float = 30, max_m: float = 400, col: str = "length_m"):
    """Drop detections outside a plausible vessel length.

    Below 30 m a target is a pixel or three at 10 m and cannot be told from a
    bright scatterer; above 400 m it is longer than any ship afloat and is
    almost always a merged cluster or a platform.
    """
    if detections.empty:
        return detections
    L = detections[col]
    return detections[L.between(min_m, max_m)].reset_index(drop=True)


def infrastructure_mask(detections, cell_m: float = 200, min_scene_frac: float = 0.5,
                        scene_col: str = "scene"):
    """Flag positions that recur across scenes — turbines, platforms, moorings.

    A ship is somewhere else next week. Something bright at the same coordinates
    in more than `min_scene_frac` of scenes is fixed to the seabed. Returns the
    frame with an `is_infrastructure` column added.
    """
    if detections.empty:
        return detections.assign(is_infrastructure=[])
    d = detections.copy()
    n_scenes = d[scene_col].nunique()
    d["_cell"] = (
        (d.x.to_numpy() // cell_m).astype(int).astype(str) + "_"
        + (d.y.to_numpy() // cell_m).astype(int).astype(str)
    )
    seen = d.groupby("_cell")[scene_col].nunique()
    # With one scene every cell is trivially in "100%" of scenes, which would
    # flag every ship. Needs at least two scenes to mean anything.
    fixed = set() if n_scenes < 2 else set(seen[seen / n_scenes > min_scene_frac].index)
    d["is_infrastructure"] = d._cell.isin(fixed)
    return d.drop(columns="_cell")


def clean_detections(detections, min_m: float = 30, max_m: float = 400,
                     min_km: float = 1.0, drop_infrastructure: bool = True):
    """The full Phase 5 chain: length gate, land mask, static-infrastructure mask."""
    if detections.empty:
        return detections
    d = length_gate(detections, min_m, max_m)
    if d.empty:
        return d
    d = d[at_sea(d.lat.to_numpy(), d.lon.to_numpy(), min_km)].reset_index(drop=True)
    if d.empty:
        return d
    d = infrastructure_mask(d)
    if drop_infrastructure:
        d = d[~d.is_infrastructure].reset_index(drop=True)
    return d
