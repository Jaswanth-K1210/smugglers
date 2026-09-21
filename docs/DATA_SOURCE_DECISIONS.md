# Data Source Decisions — operational record

Working log of which data sources were tried, what failed, and what replaced it.
Kept out of `RESEARCH_POSITION.md` on purpose: that document carries the research
claim, this one carries the plumbing. Cite this from the paper only where a
source substitution affects reproducibility.

---

## Sentinel-1 imagery

### CDSE Sentinel Hub → Microsoft Planetary Computer (2026-09-20)

The plan specified the Copernicus Data Space Ecosystem's Sentinel Hub Process API.
That route is unavailable to us:

- `sh.dataspace.copernicus.eu/oauth/token` has returned **503 "No server is
  available"** on every probe since 2026-09-18, for GET and POST alike. The
  commercial `services.sentinel-hub.com` equivalent returns a correct 405 to the
  same request, so the fault is CDSE-side, not ours.
- Account registration does not complete — the form submits and no confirmation
  mail arrives. Even on success, the token endpoint above still issues nothing.

**Replacement: Microsoft Planetary Computer**, `sentinel-1-grd` collection. This is
the same ESA Sentinel-1 archive mirrored into Azure. Verified end to end with no
`Authorization` header on any request: STAC search 200, SAS signing 200, raster
byte read 206. The collection carries no `msft:requires_account` flag, unlike
their `sentinel-1-rtc` collection, which does and is therefore not used.

Two consequences, both deliberate:

1. **We geocode ourselves.** PC serves GRD measurement images in radar geometry
   with a ~210-point GCP grid, not map-projected. GDAL picks the GCPs up through
   `rasterio.vrt.WarpedVRT`, so this is one call, not a SNAP processing chain —
   the "no SNAP" constraint holds. Output is **UTM 32N at 10 m**, chosen over
   EPSG:4326 so pixels are square metres: the Phase 5 length gate and the Phase 6
   500 m buffer then work directly in metres.
2. **We use raw DN, not calibrated sigma-nought.** Labelling is adaptive
   brightness thresholding, which needs relative contrast; ships sit 10-30 dB
   above water in uncalibrated DN just as they do after calibration. Absolute
   radiometry is never required, so the earlier "pre-calibrated" wording in the
   plan and the slides is obsolete.

This strengthens rather than weakens the open-data claim: the pipeline now needs
**no registration of any kind** for imagery. Fallback if PC ever becomes
unavailable: ASF (`asf_search`, free NASA Earthdata login), verified reachable.


---

## AIS

### web.ais.dk → S3 (2026-09-20)

The Danish Maritime Authority's historical AIS archive moved off `web.ais.dk`,
which now serves a certificate expired in June 2025 and resets connections even
unverified — reproduced on two machines. The live AIS page on `dma.dk` points at
an S3 bucket instead.

Addressed path-style, `s3.eu-central-1.amazonaws.com/aisdata.ais.dk/...`, because
the dotted bucket name breaks TLS hostname matching on the virtual-host form.
Path-style presents a valid certificate, so verification stays on.

A day is ~650 MB and a meaningful fraction of transfers that size fail on read
timeout or connection reset, so `src/ais.py` retries with backoff and resumes via
HTTP Range rather than restarting.
