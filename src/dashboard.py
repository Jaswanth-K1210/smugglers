"""Folium map of characterised STS candidates.

Colour encodes the identity category, not a verdict. There is no red "DARK"
pin, because the pipeline never concludes that — an AIS_UNMATCHED event is a
candidate whose partners were not found in AIS, which is a statement about the
evidence and not about intent.
"""
import json
from pathlib import Path

import pandas as pd

from src.config import ROOT
from src.dark_sts import AIS_PARTIAL, AIS_UNMATCHED, AIS_VISIBLE

OUT = ROOT / "outputs" / "dashboard"

COLOURS = {AIS_VISIBLE: "#2b8cbe", AIS_PARTIAL: "#fdae61", AIS_UNMATCHED: "#d7191c"}
EXPLAIN = {
    AIS_VISIBLE: "Two or more AIS identities present. Both partners broadcasting.",
    AIS_PARTIAL: "Exactly one AIS identity. One partner silent, or an AIS timing, "
                 "coverage or matching limit, or a localisation error.",
    AIS_UNMATCHED: "No AIS identity matched. A candidate — absence of AIS is not "
                   "evidence of concealment.",
}


def build(events, out_html: Path = None, title: str = "Dark STS candidates"):
    """Write the map. `events` is the frame from run_pipeline."""
    import folium

    out_html = Path(out_html or OUT / "index.html")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    if events is None or len(events) == 0:
        out_html.write_text(f"<h1>{title}</h1><p>No events in this run.</p>")
        print(f"dashboard (empty): {out_html}")
        return out_html

    m = folium.Map(location=[events.lat.mean(), events.lon.mean()], zoom_start=9,
                   tiles="CartoDB positron")
    for _, e in events.iterrows():
        cat = e.get("category", AIS_UNMATCHED)
        colour = COLOURS.get(cat, "#666666")
        susp = e.get("suspicion", 0) or 0
        rows = [f"<b>{cat}</b>", EXPLAIN.get(cat, ""), "<hr style='margin:4px 0'>"]
        for label, key, fmt in [
            ("Time", "time", str), ("AIS identities", "n_identities", str),
            ("Size class", "size_class", str), ("Registry type", "registry_type", str),
            ("Flag", "registry_flag", str), ("Length (est.)", "length_m", lambda v: f"{v:.0f} m"),
            ("GFW encounter", "gfw_encounter", str), ("GFW gap", "gfw_gap", str),
            ("Suspicion", "suspicion", lambda v: f"{v:.3f}"),
        ]:
            v = e.get(key)
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                rows.append(f"{label}: {fmt(v)}")
        folium.CircleMarker(
            [e.lat, e.lon],
            radius=6 + 10 * float(susp),
            color=colour, fill=True, fill_color=colour, fill_opacity=0.65, weight=2,
            popup=folium.Popup("<br>".join(rows), max_width=340),
            tooltip=f"{cat} · suspicion {susp:.2f}",
        ).add_to(m)

    counts = events.category.value_counts().to_dict() if "category" in events else {}
    legend = "".join(
        f"<div><span style='display:inline-block;width:11px;height:11px;"
        f"background:{COLOURS[k]};border-radius:50%;margin-right:6px'></span>"
        f"{k} ({counts.get(k, 0)})</div>" for k in COLOURS)
    m.get_root().html.add_child(folium.Element(f"""
      <div style="position:fixed;bottom:22px;left:22px;z-index:9999;background:#fff;
                  padding:10px 13px;border-radius:7px;font:12px/1.55 system-ui,sans-serif;
                  box-shadow:0 1px 6px rgba(0,0,0,.25);max-width:290px">
        <b>{title}</b><br>{len(events)} candidate events<br>
        <div style="margin:7px 0">{legend}</div>
        <span style="color:#555">Marker size is the triage score. Categories describe
        AIS evidence, not intent.</span>
      </div>"""))
    m.save(out_html)
    print(f"dashboard: {out_html}")
    return out_html


if __name__ == "__main__":
    csv = ROOT / "outputs" / "events.csv"
    if not csv.exists():
        raise SystemExit("no outputs/events.csv — run src.run_pipeline first")
    build(pd.read_csv(csv))
