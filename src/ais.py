"""Danish Maritime Authority AIS: download a day, filter it to the AOI.

Source files: https://web.ais.dk/aisdata/aisdk-YYYY-MM-DD.zip (~400 MB zipped,
several GB as CSV), so loading is chunked and filtered to the bbox as it reads.
"""
import sys
from pathlib import Path

import pandas as pd
import requests

from src.config import DATA, bbox as default_bbox

BASE_URL = "https://web.ais.dk/aisdata"
RAW = DATA / "ais_raw"

# The CSV header changes case/spacing between years; we normalise and pick these.
COLS = {
    "timestamp": "timestamp",
    "mmsi": "mmsi",
    "latitude": "lat",
    "longitude": "lon",
    "sog": "sog",
    "name": "name",
    "ship type": "ship_type",
    "length": "length",
    "width": "width",
    "navigational status": "nav_status",
}


def download(date: str, force: bool = False) -> Path:
    """Fetch one day of DMA AIS. `date` is YYYY-MM-DD. Returns the local path."""
    RAW.mkdir(parents=True, exist_ok=True)
    for ext in ("zip", "csv"):
        cached = RAW / f"aisdk-{date}.{ext}"
        if cached.exists() and not force:
            print(f"cached: {cached} ({cached.stat().st_size / 1e6:.0f} MB)")
            return cached

    url = f"{BASE_URL}/aisdk-{date}.zip"
    dest = RAW / f"aisdk-{date}.zip"
    # ponytail: web.ais.dk's TLS certificate expired upstream (June 2025), so a
    # verified fetch fails. Retry unverified for this one public, read-only,
    # non-secret dataset; restore strict verification once DMA renews the cert.
    for strict in (True, False):
        try:
            r = requests.get(url, stream=True, timeout=120, verify=strict)
        except requests.exceptions.SSLError:
            print("WARNING: web.ais.dk TLS certificate is invalid, retrying unverified")
            continue
        if r.status_code == 404:
            raise FileNotFoundError(f"no AIS file published for {date}: {url}")
        r.raise_for_status()
        total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                total += len(chunk)
                print(f"\r  {total / 1e6:.0f} MB", end="", flush=True)
        print(f"\rdownloaded: {dest} ({total / 1e6:.0f} MB)")
        return dest
    raise RuntimeError(f"could not download {url}")


def load(date: str, box=None, chunksize: int = 1_000_000) -> pd.DataFrame:
    """Load one day of AIS, keeping only rows inside `box` and only useful columns."""
    lo_lon, lo_lat, hi_lon, hi_lat = box or default_bbox()
    path = download(date)
    kept = []
    for chunk in pd.read_csv(path, chunksize=chunksize, low_memory=False):
        chunk.columns = [c.strip().lstrip("#").strip().lower() for c in chunk.columns]
        missing = set(COLS) - set(chunk.columns)
        if missing:
            raise KeyError(f"unexpected AIS columns, missing {missing}: {list(chunk.columns)}")
        chunk = chunk[list(COLS)].rename(columns=COLS)
        kept.append(chunk[chunk.lon.between(lo_lon, hi_lon) & chunk.lat.between(lo_lat, hi_lat)])

    df = pd.concat(kept, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df.timestamp, format="%d/%m/%Y %H:%M:%S", errors="coerce")
    return df.dropna(subset=["timestamp", "mmsi", "lat", "lon"])


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2025-06-01"
    df = load(date)
    print(f"\n{len(df):,} AIS rows in AOI on {date}, {df.mmsi.nunique():,} distinct MMSI")
    print(df.head())
