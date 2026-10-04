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

### Gulf AIS: hormuz.now as a regional, secondary feed (2026-10-04)

aisstream.io (the live map's feed) has **zero** positions in the Persian Gulf,
Strait of Hormuz, Gulf of Oman and Red Sea: it relies on volunteer shore
receivers and has none there. Measured against our saved feed: 0 positions in
each of those boxes versus 985 in the Skagerrak.

Two free sites publish Gulf AIS. Checked against their live APIs:

| | Hormuz Ship Monitor (`hormuz.data-tracking.net`) | hormuz.now |
|---|---|---|
| Ships per snapshot | ~1,365 | ~1,600 |
| Refresh | every 30 min | every ~20 s |
| Per-ship position time | **no**: every row carries the poll time | **yes** (`posAt`, 81 % < 1 h old) |
| MMSI | **no**: 6–8-digit internal ids in the `mmsi` field | **no**: empty; internal ids only |
| History via API | latest poll only | latest snapshot only |
| Licence | CC BY 4.0 **research and non-commercial** (docs); no licence file in its GitHub repo | CC BY 4.0 |
| Source stated | "publicly available sources", terrestrial | "public AIS, IMF PortWatch" |

Decision: **hormuz.now only**, because SAR matching needs a per-ship position
time. `src/regional_ais.py` polls it and keeps our own rolling 30-day record
(`data/regional_ais/`), since neither API serves past positions; passes before
recording began cannot be matched against it.

Provenance is **unverified**. Neither site publishes an MMSI; the internal ids
and field names (`shiptype`, `gtShiptype`, `elapsedMin`) look like a commercial
tracker's public map. Rules that follow, enforced in code:

1. It is **one** secondary AIS source. The two sites are not independent of
   each other, and neither is satellite AIS. Never present them as corroboration.
2. With no shared MMSI, the same ship can appear in GFW and in this feed under
   different ids. Identity counts take the **larger** of the two per-source
   counts, never the sum (`src/search.py`).
3. A regional ship is linked to a GFW identity (IMO, photo) only on an **exact,
   unique** name match.
4. Every result that uses it says so: "hormuz.now (CC BY 4.0), provenance unverified".

Open question sent to the operators: where the AIS comes from and under what
terms. Until answered, research and non-commercial use with attribution only.

### Radar-to-AIS matching physics and AIS coverage confidence (2026-10-04)

`src/match.py` adds, per radar hull: dead reckoning of each AIS report to the
pass time, the speed the ship would have needed (> 30 kn = not plausible), and a
radar-vs-AIS length check (outside 0.6–1.6× = "size differs").

It also scores how far "no AIS match" can be trusted at that place and time:
sources with data at the pass, the share of ≥ 100 m hulls that matched AIS,
AIS density, and jamming signs in the regional feed (positions on land,
> 50 kn jumps). **This score is a provisional triage aid for the website, not
part of the fusion model** (RESEARCH_POSITION §4.5). Its constants are
hand-set and belong in the §4.6 sweep before any use in the paper:

| Constant | Current | Decides |
|---|---|---|
| Dead-reckoning error | 15 % of distance travelled | match tolerance |
| Base match tolerance | 2,000 m | match tolerance |
| Implausible speed | 30 kn | feasibility |
| Size agreement | 0.6–1.6 × | "size differs" flag |
| Big-hull threshold | 100 m, used with ≥ 5 hulls | coverage proxy |
| Jamming flags | > 2 % on land or > 50 kn jumps | coverage penalty |

### Open Waters (aiscast) becomes the Gulf's first feed (2026-10-04)

Tested against the live API (`ais.openwaters.io/v1`, OpenAPI at `/openapi.json`):
1,152 ships in the Gulf coverage box from 2 anonymous requests, **every one with a
9-digit MMSI**, 94 % with an ITU type code, 90 % with an IMO, median position age
5 min. The data is AISHub's terrestrial network, re-served with `source` on every
row; AISHub has confirmed in writing (per Open Waters) that use and redistribution
are allowed with credit "AISHub". Government sources (Kystverket, BarentsWatch,
Digitraffic) carry their own NLOD / CC BY credits; volunteer receptions are CC0.
`src/openwaters.py:credit()` returns the credit for each source.

So the Gulf feed is now: **Open Waters first**, hormuz.now only for ships it does
not have (same normalised name within 5 km = the same ship, dropped). This fixes
hormuz.now's two weaknesses for every ship Open Waters covers: no MMSI, unverified
provenance. Open Waters is also polled for the Red Sea, Skagerrak/western Baltic
and Laconia Bay, merged into the live map by MMSI (one ship heard by two feeds is
one ship; the newer report wins).

Limits: anonymous requests cover at most 100 square degrees (a free personal token,
`OPENWATERS_TOKEN`, ~400); `src/openwaters.py:chunks()` splits boxes to fit. Tracks
reach the last 48 h. Shore receivers only (satellite only in the Norwegian EEZ), so
it does **not** fill the open ocean; nothing free and live does.

Considered and not used:
- **VesselAPI**: free tier is 150 calls/month (no use for a map); its satellite AIS
  is $0.41–0.50 per single-vessel lookup. A possible paid "where is this ship now"
  button, not a map layer.
- **AISHub direct**: free only for members who feed a receiver; its data already
  arrives through Open Waters.
- **Hormuz Ship Monitor**: no per-ship report time, no MMSI, non-commercial licence.
