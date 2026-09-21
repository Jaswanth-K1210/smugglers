"""Vessel attributes for matched detections — honest typing only.

RESEARCH_POSITION.md 3: type, flag and length come from the registry on an AIS
match, **never** from a visual classifier. At 10 m a vessel is a bright smudge a
few pixels across; a CNN asked to name its type from that would be inventing.

So there are exactly two paths:

  identity known    -> GFW Vessel API: name, flag, type, length, IMO/callsign
  identity unknown  -> a size CLASS from the bounding box, and nothing else

The second path returns a size bucket, not a type. A 200 m unmatched detection
is "large"; calling it a tanker would be a guess dressed as a measurement.
"""
import pandas as pd
import requests

from src.config import GFW_API_TOKEN
from src.gfw import BASE, _headers

# Buckets, not types. Boundaries follow the disaggregation in
# RESEARCH_POSITION.md 5 so detector/GFW disagreement can be split by size.
SIZE_CLASSES = [(0, 30, "sub-detection"), (30, 60, "small"), (60, 100, "medium"),
                (100, 150, "large"), (150, 250, "very large"), (250, 1e9, "ULCC/VLCC-scale")]


def size_class(length_m) -> str:
    """Size bucket from an estimated length. Never a vessel type."""
    if length_m is None or pd.isna(length_m):
        return "unknown"
    for lo, hi, name in SIZE_CLASSES:
        if lo <= length_m < hi:
            return name
    return "unknown"


def lookup(mmsi, datasets="public-global-vessel-identity:latest"):
    """Registry record for one MMSI, or None. Requires GFW_API_TOKEN."""
    if not GFW_API_TOKEN:
        return None
    try:
        r = requests.get(f"{BASE}/vessels/search", headers=_headers(),
                         params={"query": str(mmsi), "datasets[0]": datasets,
                                 "limit": 1, "includes[0]": "MATCH_CRITERIA"},
                         timeout=60)
        if r.status_code != 200:
            return None
        entries = r.json().get("entries") or []
        if not entries:
            return None
        v = entries[0]
        combined = (v.get("combinedSourcesInfo") or [{}])[0]
        reg = (v.get("registryInfo") or [{}])[0]
        return {
            "registry_name": reg.get("shipname"),
            "registry_flag": reg.get("flag"),
            "registry_type": (combined.get("shiptypes") or [{}])[0].get("name"),
            "registry_length_m": reg.get("lengthM"),
            "imo": reg.get("imo"),
            "callsign": reg.get("callsign"),
        }
    except requests.exceptions.RequestException:
        return None


def enrich(detections, length_col: str = "length_m"):
    """Attach registry attributes where an identity exists, a size class where not.

    Adds `attribution`, which records which path each row took, so no downstream
    consumer can confuse a looked-up type with an estimated size.
    """
    if detections is None or len(detections) == 0:
        return pd.DataFrame()

    cache, rows = {}, []
    for _, d in detections.iterrows():
        row = d.to_dict()
        ids = row.get("mmsis") or []
        if isinstance(ids, str):
            ids = [i for i in ids.split(",") if i]

        if ids:
            mmsi = ids[0]
            if mmsi not in cache:
                cache[mmsi] = lookup(mmsi)
            info = cache[mmsi]
            if info:
                row.update(info)
                row["attribution"] = "registry"
            else:
                row["attribution"] = "identity known, registry miss"
            row["size_class"] = size_class(row.get(length_col))
        else:
            row["size_class"] = size_class(row.get(length_col))
            row["registry_type"] = None
            row["attribution"] = "size estimate only"
        rows.append(row)
    return pd.DataFrame(rows)
