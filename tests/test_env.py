"""Phase 0 smoke test: is the environment usable, and does the AOI have data?

Run the library/config checks with pytest (no network, no credentials needed):

    pytest tests/test_env.py -v

Run the live data checks, which need .env filled in, as a script:

    python tests/test_env.py 2025-06-01
"""
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REQUIRED = ["pandas", "numpy", "scipy", "requests", "dotenv"]
LATER = ["rasterio", "geopandas", "shapely", "folium", "ultralytics"]


def test_required_libraries_import():
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    assert not missing, f"missing Phase 0 dependencies: {missing} (pip install -r requirements.txt)"


def test_print_versions():
    import numpy, pandas, scipy, requests
    for m in (pandas, numpy, scipy, requests):
        print(f"{m.__name__:10} {m.__version__}")
    print("later phases:", {m: bool(importlib.util.find_spec(m)) for m in LATER})


def test_bbox_parses():
    from src.config import bbox
    try:
        box = bbox()
    except RuntimeError as e:
        pytest.skip(str(e))
    lo_lon, lo_lat, hi_lon, hi_lat = box
    assert -180 <= lo_lon < hi_lon <= 180 and -90 <= lo_lat < hi_lat <= 90, box
    print(f"AOI: {box}  ({hi_lon - lo_lon:.2f}° x {hi_lat - lo_lat:.2f}°)")


def main(date: str):
    """Live checks — Phase 0 kill criterion. Needs .env and network."""
    from src import ais, gfw
    from src.config import bbox

    print(f"AOI: {bbox()}\n")

    df = ais.load(date)
    print(f"AIS rows in AOI on {date}: {len(df):,}   distinct MMSI: {df.mmsi.nunique():,}")
    print(df.head().to_string(), "\n")

    total, entries = gfw.events("gaps", "2025-01-01", "2025-12-31", limit=5)
    print(f"GFW gap events in AOI over 2025: {total}")
    for e in entries:
        print(f"  {e.get('start')}  {e.get('id')}")

    print("\n--- KILL CRITERION ---")
    if df.mmsi.nunique() == 0:
        print("FAIL: zero vessels in the box. Pick a new bounding box.")
    elif total == 0:
        print("FAIL: zero GFW gap events for the region over a year. Pick a new bounding box.")
    else:
        print(f"PASS: {df.mmsi.nunique():,} vessels/day and {total} GFW gaps/year in the AOI.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-06-01")
