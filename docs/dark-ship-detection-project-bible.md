# Dark Ship-to-Ship Transfer Detection — Project Bible

**Base paper:** Ballinger, O. (2024). *Automatic Detection of Dark Ship-to-Ship Transfers Using Deep Learning and Satellite Imagery.* https://arxiv.org/abs/2404.07607

**Your improvement:** Rebuild it using **free Sentinel-1 SAR imagery** instead of paid PlanetScope, add a **suspicion-scoring layer**, and extend detection to a **new maritime chokepoint** (not Kerch Strait).

---

## 0. Big picture — the pipeline you're building

```
Step 1: Pick a target area (a strait/chokepoint)
Step 2: Download free SAR satellite images of that area over time
Step 3: Detect ships in each image (object detection model)
Step 4: Pull AIS tracking data for the same area/time
Step 5: Cross-check: does every detected ship have a matching AIS signal?
         → No match = "dark" ship
Step 6: Look for two dark/near ships sitting very close together,
         not moving, for an extended time → possible dark transfer
Step 7: Score each event by suspicion (how long dark, how close to
         a sanctioned port, how unusual the location is)
Step 8: Show it all on a simple map dashboard
```

Each step below tells you exactly where to get the data, what tool to use, and what code to write.

---

## 1. Choosing your target area

Don't pick a random ocean patch — pick a real chokepoint with known dark-fleet activity, so your results are meaningful and defensible.

**Good candidates (all have real, documented dark-ship activity you can cite):**
- **Strait of Hormuz / off the coast of Iran** — heavily documented "shadow fleet" oil smuggling
- **Malacca Strait** — high traffic, known STS transfer hotspot
- **Kerch Strait** — already covered by the base paper (use only if you want a direct comparison, not as your main contribution)
- **Off Malaysia/Singapore near Linggi/Pengerang** — well-documented STS anchorage zone, lots of open-source journalism to cite (e.g. reporting by Reuters, Global Fishing Watch, C4ADS)

**How to pick your bounding box (the rectangle of ocean you'll monitor):**
1. Go to Google Maps, find your chokepoint.
2. Note the four corners as latitude/longitude (e.g. top-left, bottom-right).
3. Keep it small — roughly 50km x 50km is plenty. A huge area means huge downloads and slow processing for no real benefit.

---

## 2. Getting satellite imagery (Sentinel-1 SAR) — FREE

### 2.1 Where to get it
**Official source:** Copernicus Data Space Ecosystem — https://dataspace.copernicus.eu/

This replaced the old "Copernicus Open Access Hub" in October 2023 — if any tutorial you find online mentions `scihub.copernicus.eu`, ignore it, that's outdated.

### 2.2 How to sign up
1. Go to https://dataspace.copernicus.eu/
2. Click **Register** (top right) — free, just needs an email.
3. Once registered, you can either:
   - Browse visually via **Copernicus Browser** (https://browser.dataspace.copernicus.eu/) — good for a first look at your area
   - Use the **API** to download programmatically (recommended once you know your area/dates)

### 2.3 What product to download
- **Product type:** Sentinel-1 **GRD** (Ground Range Detected) — this is the "already processed into a viewable image" version. Don't use SLC (raw/complex) unless you specifically need phase data — GRD is much easier for a first project.
- **Polarization:** VV (or VV+VH if available) — VV is standard for ship detection over water.

### 2.4 How to download via code (Python)
```python
# pip install sentinelsat  --> NOTE: sentinelsat targeted the OLD hub.
# For the NEW Copernicus Data Space Ecosystem, use one of these instead:

# Option A (recommended, actively maintained):
# pip install cdsetool
from cdsetool.query import query_features
from cdsetool.credentials import Credentials
from cdsetool.download import download_features

creds = Credentials("your_username", "your_password")

features = query_features(
    "Sentinel1",
    {
        "productType": "GRD",
        "startDate": "2025-01-01",
        "completionDate": "2025-03-01",
        "box": "55.0,26.5,56.5,27.5",  # lon_min, lat_min, lon_max, lat_max — Strait of Hormuz example
    },
)

download_features(features, "./sentinel_downloads", {"credentials": creds})
```

**If the API feels intimidating at first:** just use the **Copernicus Browser** web interface to manually download a handful of images for your area/date range to get started. You can automate downloading later once your pipeline works on a few test images.

### 2.5 Preprocessing the SAR image (important, don't skip)
Raw SAR images look grainy/noisy and aren't in a normal photo format. You need to process them first.

**Tool: ESA SNAP (Sentinel Application Platform)** — free desktop software, download at https://step.esa.int/main/download/snap-download/

Steps in SNAP (do this once, learn the GUI, then you can script it):
1. **Open** your downloaded `.zip` GRD product directly in SNAP.
2. **Calibration** (Radar → Radiometric → Calibrate) — converts raw pixel values into meaningful radar brightness values.
3. **Speckle filtering** (Radar → Speckle Filtering) — SAR images have natural "salt and pepper" noise; this cleans it up. Use "Lee" or "Refined Lee" filter.
4. **Terrain correction** (Radar → Geometric → Terrain Correction) — corrects for the satellite's viewing angle so the image lines up with real map coordinates.
5. **Export** as GeoTIFF.

You can also script this with **SNAP's `gpt` (Graph Processing Tool)** from the command line once you're comfortable, so it's not manual every time:
```bash
gpt Calibration -Ssource=input.zip -t calibrated.tif
gpt Speckle-Filter -Ssource=calibrated.tif -t filtered.tif
gpt Terrain-Correction -Ssource=filtered.tif -t final.tif
```

### 2.6 Cutting big images into tiles
A full Sentinel-1 scene can be huge (thousands of pixels per side). Cut it into smaller chunks (e.g. 512x512 pixels) before feeding into your detection model — this is standard practice and keeps things light enough for a free Colab GPU.

```python
import rasterio
from rasterio.windows import Window

def tile_image(path, tile_size=512, out_dir="tiles"):
    with rasterio.open(path) as src:
        for i in range(0, src.width, tile_size):
            for j in range(0, src.height, tile_size):
                window = Window(i, j, tile_size, tile_size)
                tile = src.read(window=window)
                # save each tile as its own small GeoTIFF
                transform = src.window_transform(window)
                out_path = f"{out_dir}/tile_{i}_{j}.tif"
                with rasterio.open(out_path, 'w', driver='GTiff',
                                    height=tile.shape[1], width=tile.shape[2],
                                    count=tile.shape[0], dtype=tile.dtype,
                                    crs=src.crs, transform=transform) as dst:
                    dst.write(tile)
```

---

## 3. Ship detection model

### 3.1 Don't train from scratch — pretrain on xView3-SAR first
Your own downloaded images (a few dozen scenes) are too few to train a detector from zero. Instead:

1. **Pretrain** your model on **xView3-SAR** (thousands of labeled ships, free) — https://iuu.xview.us/dataset (register, free, instant approval)
2. **Fine-tune** on your own tiles from your chosen strait (even a small number of manually-labeled images helps a lot once the model already knows "what a ship in SAR looks like")

### 3.2 Model choice
Use **YOLOv8** (or v11) — lightweight, fast, well-documented, runs fine on free Colab.

```bash
pip install ultralytics
```

```python
from ultralytics import YOLO

# Start from a small pretrained YOLO checkpoint
model = YOLO("yolov8n.pt")

# Train on xView3-SAR (after converting its labels to YOLO format — see 3.3)
model.train(data="xview3.yaml", epochs=50, imgsz=512)

# Fine-tune on your own strait images
model.train(data="my_strait.yaml", epochs=20, imgsz=512, resume=False)
```

### 3.3 Converting xView3 labels to YOLO format
xView3 provides labels as a CSV with lat/lon points, not YOLO's bounding-box `.txt` format. You'll need a short conversion script:
- Convert each ship's lat/lon into pixel x/y using the image's geotransform (`rasterio`'s `src.index(lon, lat)` does this directly)
- Draw a small fixed-size box around each point (ships are point-labeled in xView3, not box-labeled — a common, accepted workaround is a fixed-size box, e.g. 20x20 pixels, since most ships are small in these images)
- Write out in YOLO's format: `class x_center y_center width height` (all normalized 0–1)

---

## 4. Getting AIS tracking data — FREE

### 4.1 Where to get it
**Global Fishing Watch** — https://globalfishingwatch.org/data/
- Despite the name, GFW tracks **all vessel types**, not just fishing boats — cargo, tanker, passenger, everything with AIS.
- They provide a **free API** for researchers: https://globalfishingwatch.org/our-apis/
- Sign up for an API key (free, quick approval for academic/research use — mention it's for a student project).

### 4.2 Pulling AIS data via their API
```python
import requests

API_TOKEN = "your_gfw_api_token"
headers = {"Authorization": f"Bearer {API_TOKEN}"}

# Example: query vessel presence in your bounding box and date range
url = "https://gateway.api.globalfishingwatch.org/v3/events/ais"
params = {
    "datasets[0]": "public-global-ais-vessel-presence:latest",
    "start-date": "2025-01-01",
    "end-date": "2025-03-01",
    # add your bounding box geometry as required by their API docs
}
resp = requests.get(url, headers=headers, params=params)
ais_data = resp.json()
```

**Alternative free source (US waters only, no API key needed):** MarineCadastre.gov bulk AIS downloads — https://hub.marinecadastre.gov/pages/vesseltraffic — useful if you want a simpler, no-signup way to just practice on a dataset first before dealing with GFW's API.

---

## 5. Cross-verification logic (satellite detection ↔ AIS)

This is the actual "dark ship" detection step — the core of your project.

```python
from datetime import timedelta
from geopy.distance import geodesic

def is_dark_ship(detection, ais_records, time_window_minutes=30, distance_km=2):
    """
    detection: dict with 'lat', 'lon', 'timestamp' from your SAR model
    ais_records: list of AIS pings for the same time/area
    Returns True if NO AIS record is close enough in space+time to explain
    this satellite-detected ship — meaning it was likely running dark.
    """
    det_time = detection["timestamp"]
    det_loc = (detection["lat"], detection["lon"])

    for record in ais_records:
        time_diff = abs((record["timestamp"] - det_time).total_seconds()) / 60
        if time_diff > time_window_minutes:
            continue
        record_loc = (record["lat"], record["lon"])
        if geodesic(det_loc, record_loc).km <= distance_km:
            return False  # matched to a known, tracked ship

    return True  # no match found — this is a dark ship
```

### 5.1 Detecting "ship-to-ship transfer" events specifically
A transfer looks like: **two ships very close together (within ~50-100m), both stationary or moving very slowly, for an extended period (30+ minutes)**, in open water (not a normal port/anchorage).

```python
def detect_sts_event(dark_ships, distance_threshold_m=100, min_duration_minutes=30):
    """
    dark_ships: list of dark-ship detections with lat/lon/timestamp
    Looks for pairs of dark ships close together at the same time.
    """
    events = []
    for i, ship_a in enumerate(dark_ships):
        for ship_b in dark_ships[i+1:]:
            if abs((ship_a["timestamp"] - ship_b["timestamp"]).total_seconds()) < 600:
                dist_m = geodesic(
                    (ship_a["lat"], ship_a["lon"]),
                    (ship_b["lat"], ship_b["lon"])
                ).meters
                if dist_m <= distance_threshold_m:
                    events.append({"ship_a": ship_a, "ship_b": ship_b, "distance_m": dist_m})
    return events
```

---

## 6. Suspicion scoring (your original contribution)

```python
def suspicion_score(event, sanctioned_zones, normal_shipping_lanes):
    score = 0
    # Longer time dark = more suspicious
    score += min(event["dark_duration_minutes"] / 10, 40)
    # Closer to a known sanctioned port/zone = more suspicious
    if is_near_sanctioned_zone(event["location"], sanctioned_zones):
        score += 30
    # Off the normal shipping lane = more suspicious
    if not is_on_normal_lane(event["location"], normal_shipping_lanes):
        score += 20
    # Odd hours (late night local time) = mildly more suspicious
    if is_night_time(event["timestamp"], event["location"]):
        score += 10
    return min(score, 100)
```

You'll need a small reference list of sanctioned ports/zones and normal shipping lanes — these can come from public sources like OpenSeaMap or published sanctions lists (e.g. OFAC lists, EU sanctions lists — publicly available government documents, free to use for research).

---

## 7. Dashboard (tie it all together visually)

Simple options, all free:
- **Folium** (Python) — quick interactive map with markers for detected dark ships/events, exportable as an HTML file. Easiest option, get this working first.
- **Streamlit** — if you want a clickable dashboard with filters (date range, suspicion score threshold) — still free, runs locally or free-tier deployable.

```python
import folium

m = folium.Map(location=[26.5, 56.2], zoom_start=8)  # example: Hormuz area
for event in flagged_events:
    color = "red" if event["suspicion_score"] > 70 else "orange"
    folium.CircleMarker(
        location=[event["lat"], event["lon"]],
        radius=8, color=color, fill=True,
        popup=f"Suspicion: {event['suspicion_score']}"
    ).add_to(m)
m.save("dark_ship_dashboard.html")
```

---

## 8. Week-by-week plan

| Week | What you do |
|---|---|
| 1 | Register on Copernicus Data Space, xView3, and Global Fishing Watch. Pick your target strait. Manually download 3–5 sample Sentinel-1 images via the browser to get familiar. |
| 2 | Install SNAP, learn the calibration → speckle filter → terrain correction pipeline manually on your sample images. Write the tiling script. |
| 3 | Download xView3-SAR (subset), convert labels to YOLO format, train YOLOv8 on it (Colab free GPU). |
| 4 | Fine-tune the model on your own strait's tiles. Evaluate detection accuracy. |
| 5 | Pull AIS data for your strait/date range from Global Fishing Watch. Build the cross-verification (dark ship) logic. |
| 6 | Build the ship-to-ship transfer pairing logic + suspicion scoring. |
| 7 | Build the Folium/Streamlit dashboard. Polish, generate example results, write up your report/paper comparing your results to the original Kerch Strait findings. |
| 8 | Buffer week — fix bugs, prepare demo/slides, rehearse explanation of the pipeline. |

---

## 9. Cost summary (final check)

| Item | Cost |
|---|---|
| Sentinel-1 SAR imagery | ₹0 (Copernicus Data Space Ecosystem) |
| xView3-SAR pretraining dataset | ₹0 |
| AIS data (Global Fishing Watch) | ₹0 (free research API) |
| SNAP preprocessing software | ₹0 |
| Compute (Google Colab free tier) | ₹0 |
| **Total** | **₹0** |

Optional, not required: Colab Pro (~$10/month) only if training feels too slow on the free tier.

---

## 10. Key links, all in one place

- Copernicus Data Space Ecosystem (Sentinel-1 imagery): https://dataspace.copernicus.eu/
- Copernicus Browser (visual download): https://browser.dataspace.copernicus.eu/
- ESA SNAP software: https://step.esa.int/main/download/snap-download/
- xView3-SAR dataset: https://iuu.xview.us/dataset
- xView3 code repo: https://github.com/DIUx-xView
- Global Fishing Watch data/API: https://globalfishingwatch.org/data/ and https://globalfishingwatch.org/our-apis/
- Base paper: https://arxiv.org/abs/2404.07607
- xView3-SAR paper (for citing your dataset properly): https://arxiv.org/abs/2206.00897
