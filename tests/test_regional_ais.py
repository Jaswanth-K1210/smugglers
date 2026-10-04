import pandas as pd

from src import regional_ais as ra


def raw(i, lat, lon, pos_ms, **kw):
    return {"id": str(i), "name": f"SHIP {i}", "lat": lat, "lon": lon, "speed": 10, "course": 90, "heading": 0,
            "posAt": pos_ms, "category": "tanker", "shiptypeLabel": "Tanker", "flag": "PA",
            "length": 250, "width": 44, "dwt": 0, "destination": "FUJAIRAH", **kw}


def ms(ts):
    return int(pd.Timestamp(ts).value // 1_000_000)


def test_normalise_drops_navaids_and_bad_sizes():
    assert ra.normalise(raw(1, 26, 56, ms("2026-10-04 10:00"), category="navaid")) is None
    r = ra.normalise(raw(2, 26, 56, ms("2026-10-04 10:00"), length=1022))
    assert r["id"] == "hn:2" and r["length_m"] is None and r["width_m"] is None
    assert r["heading"] is None and r["dwt"] is None and r["pos_time"] == "2026-10-04T10:00:00"


def test_record_samples_appends_and_loads_window(tmp_path):
    ra._last_recorded.clear()
    rows = [ra.normalise(raw(1, 26.0, 56.0, ms(f"2026-10-04 10:{m:02d}"))) for m in (0, 5, 20)]
    for r in rows:                                   # three polls; the 5-min one is skipped
        ra.record([r], root=tmp_path, now="2026-10-04 11:00")
    d = ra.load_window("2026-10-04 09:30", "2026-10-04 10:30", box=(55, 25, 57, 27), root=tmp_path)
    assert list(d.timestamp.dt.minute) == [0, 20] and set(d.mmsi) == {"hn:1"}
    assert ra.load_window("2026-10-04 09:30", "2026-10-04 10:30", box=(0, 0, 1, 1), root=tmp_path).empty
    first, last = ra.recorded_span(root=tmp_path)
    assert first.minute == 0 and last.minute == 20


def test_record_prunes_old_days(tmp_path):
    (tmp_path / "2026-08-01.csv.gz").write_bytes(b"")
    ra.record([], root=tmp_path, now="2026-10-04")
    assert not (tmp_path / "2026-08-01.csv.gz").exists()


def test_coverage_box():
    assert ra.covers((56.0, 26.0, 56.5, 26.5)) and not ra.covers((10, 57, 11, 58))


def test_fresh_process_keeps_15_min_sampling(tmp_path):
    ra._last_recorded.clear()
    ra.record([ra.normalise(raw(1, 26.0, 56.0, ms("2026-10-04 10:00")))], root=tmp_path, now="2026-10-04 10:05")
    ra._last_recorded.clear()                        # a new scheduled run: no memory
    n = ra.record([ra.normalise(raw(1, 26.0, 56.0, ms("2026-10-04 10:05")))], root=tmp_path, now="2026-10-04 10:06")
    assert n == 0                                     # learned 10:00 from the file, so 10:05 is skipped
    d = ra.load_window("2026-10-04 09:00", "2026-10-04 11:00", root=tmp_path)
    assert len(d) == 1
