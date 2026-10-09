"""When Planetary Computer fails a pass, the same pass comes from CDSE (and says so); never silently."""
import pytest

from src import fetch_cdse, fetch_s1, search

ITEM = {"id": "S1A_X", "properties": {"datetime": "2026-09-25T14:16:00Z"}}


def test_cdse_takes_over_and_the_pass_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_cdse, "configured", lambda: True)
    monkeypatch.setattr(fetch_cdse, "fetch_vv", lambda t, box, dest: (dest, 58.0))
    tif, note = search._from_cdse(ITEM, (56.3, 25.0, 56.7, 25.4), tmp_path, None,
                                  fetch_s1.ImageServerBusy("not answering"), lambda *a: None)
    assert tif.name == "cdse_vv.tif" and "CDSE" in note and "58 PU" in note


def test_both_failing_names_both_reasons(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_cdse, "configured", lambda: True)
    def boom(*a):
        raise RuntimeError("CDSE 503: busy")
    monkeypatch.setattr(fetch_cdse, "fetch_vv", boom)
    with pytest.raises(LookupError, match=r"Planetary Computer failed \(not answering\).*CDSE 503"):
        search._from_cdse(ITEM, (56.3, 25.0, 56.7, 25.4), tmp_path, None,
                          fetch_s1.ImageServerBusy("not answering"), lambda *a: None)


def test_without_cdse_keys_the_original_error_stands(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_cdse, "configured", lambda: False)
    with pytest.raises(fetch_s1.ImageServerBusy):
        search._from_cdse(ITEM, (56.3, 25.0, 56.7, 25.4), tmp_path, None,
                          fetch_s1.ImageServerBusy("not answering"), lambda *a: None)


def test_a_50_km_cell_stays_well_under_the_pu_cap():
    assert 30 < fetch_cdse.estimate_vv_pu((56.0, 25.0, 56.5, 25.45)) < fetch_cdse.FALLBACK_MAX_PU
