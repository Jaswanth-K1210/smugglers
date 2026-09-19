"""Shared config: secrets and the area of interest, both from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
CDSE_CLIENT_ID = os.getenv("CDSE_CLIENT_ID", "")
CDSE_CLIENT_SECRET = os.getenv("CDSE_CLIENT_SECRET", "")
GFW_API_TOKEN = os.getenv("GFW_API_TOKEN", "")


def bbox():
    """(min_lon, min_lat, max_lon, max_lat) from AOI_BBOX."""
    raw = os.getenv("AOI_BBOX", "")
    if not raw:
        raise RuntimeError("AOI_BBOX not set in .env (see .env.example)")
    lo_lon, lo_lat, hi_lon, hi_lat = (float(v) for v in raw.split(","))
    assert lo_lon < hi_lon and lo_lat < hi_lat, f"AOI_BBOX corners reversed: {raw}"
    return lo_lon, lo_lat, hi_lon, hi_lat
