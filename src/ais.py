"""Danish Maritime Authority AIS: download a day, filter it to the AOI.

The DMA archive moved off web.ais.dk (dead: expired certificate, connections
reset) to an S3 bucket linked from dma.dk. We address it path-style —
s3.eu-central-1.amazonaws.com/aisdata.ais.dk/... — because the bucket name
contains dots, which breaks TLS hostname matching on the virtual-host form.
Path-style presents a valid certificate, so verification stays on.

A day is a ~650 MB zip holding several GB of CSV, and a month of those will
not fit comfortably on a laptop. So loading filters to the AOI as it reads,
caches the (much smaller) filtered result, and drops the raw zip by default.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from src.config import DATA, bbox as default_bbox

BASE_URL = "https://s3.eu-central-1.amazonaws.com/aisdata.ais.dk"
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


def download(date: str, force: bool = False, attempts: int = 4) -> Path:
    """Fetch one day of DMA AIS. `date` is YYYY-MM-DD. Returns the local path.

    A day is ~650 MB and S3 drops a meaningful fraction of transfers that size —
    read timeouts and connection resets, not 4xx. So retry with backoff, and
    resume from whatever the last attempt got rather than starting over.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / f"aisdk-{date}.zip"
    if dest.exists() and not force:
        print(f"cached: {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
        return dest

    url = f"{BASE_URL}/aisdk-{date}.zip"
    tmp = dest.with_suffix(".part")
    for attempt in range(1, attempts + 1):
        have = tmp.stat().st_size if tmp.exists() else 0
        try:
            r = requests.get(
                url, stream=True, timeout=(30, 120),
                headers={"Range": f"bytes={have}-"} if have else {},
            )
            if r.status_code in (403, 404):
                raise FileNotFoundError(f"no AIS file published for {date} ({r.status_code})")
            if have and r.status_code != 206:
                # Range ignored; the body is the whole file, so start clean
                # rather than appending it onto what we already have.
                have = 0
            r.raise_for_status()

            total = have
            if have:
                print(f"  resuming at {have / 1e6:.0f} MB")
            with open(tmp, "ab" if have else "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    total += len(chunk)
                    # Step, not every megabyte: \r does nothing once output is
                    # piped or captured in a notebook, and 650 MB would print
                    # 650 lines.
                    if total % (50 << 20) < (1 << 20):
                        print(f"  {total / 1e6:.0f} MB", flush=True)
            tmp.replace(dest)
            print(f"downloaded: {dest} ({total / 1e6:.0f} MB)")
            return dest

        except FileNotFoundError:
            raise  # a genuine 404 is not worth retrying
        except (requests.exceptions.RequestException, OSError) as e:
            if dest.exists():
                # Another process finished this file while we were fetching it.
                print(f"cached by another run: {dest}")
                return dest
            if attempt == attempts:
                raise
            wait = 2 ** attempt
            print(f"  {type(e).__name__} at {have / 1e6:.0f} MB, "
                  f"retry {attempt}/{attempts - 1} in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"unreachable: {url}")


def load(date: str, box=None, chunksize: int = 1_000_000, keep_raw: bool = False) -> pd.DataFrame:
    """One day of AIS inside `box`, with only the columns we use.

    The filtered day is cached, so re-running is cheap. `keep_raw` keeps the
    ~650 MB zip; by default it is deleted once the cache is written.
    """
    box = box or default_bbox()
    cache = RAW / f"aoi-{date}.csv.gz"
    if cache.exists():
        print(f"cached AOI extract: {cache} ({cache.stat().st_size / 1e6:.0f} MB)")
        return pd.read_csv(cache, parse_dates=["timestamp"])

    lo_lon, lo_lat, hi_lon, hi_lat = box
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
    df = df.dropna(subset=["timestamp", "mmsi", "lat", "lon"]).sort_values("timestamp")
    df.to_csv(cache, index=False)
    if not keep_raw:
        path.unlink()
        print(f"removed raw {path.name}; AOI extract kept at {cache.name}")
    return df


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2025-06-08"
    df = load(date)
    print(f"\n{len(df):,} AIS rows in AOI on {date}, {df.mmsi.nunique():,} distinct MMSI")
    print(df.head().to_string())
