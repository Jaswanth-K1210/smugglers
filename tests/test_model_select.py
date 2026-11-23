from pathlib import Path

from src.model_select import partition


def test_test_region_never_in_train_or_val():
    imgs = [Path(f"{s}_0_{i}.png") for s in ["SKA1", "SKA2", "OMA1", "OMA2", "LAC1", "LAC2"] for i in (0, 1024)]
    p = partition(imgs, test_scenes={"LAC1", "LAC2"})
    assert {x.stem.rsplit("_", 2)[0] for x in p["test"]} == {"LAC1", "LAC2"}
    seen = {x.stem.rsplit("_", 2)[0] for x in p["train"] + p["val"]}
    assert not seen & {"LAC1", "LAC2"} and len(p["val"]) and len(p["train"])
    assert not {x.stem.rsplit("_", 2)[0] for x in p["train"]} & {x.stem.rsplit("_", 2)[0] for x in p["val"]}


def test_build_dataset_never_splits_a_scene(tmp_path):
    from src.train import build_dataset, scene_of
    tiles = tmp_path / "tiles"
    (tiles / "images").mkdir(parents=True)
    (tiles / "labels").mkdir()
    for s in range(8):
        for off in (0, 1024, 2048):
            name = f"SCENE{s}_vv_{off}_0"
            (tiles / "images" / f"{name}.png").write_bytes(b"")
            (tiles / "labels" / f"{name}.txt").write_text("0 0.5 0.5 0.1 0.1\n")
    build_dataset(tiles, tmp_path / "ds")
    seen = {split: {scene_of(p.stem) for p in (tmp_path / "ds" / split / "images").glob("*.png")}
            for split in ("train", "val")}
    assert seen["train"] and seen["val"] and not seen["train"] & seen["val"]


def test_skagen_is_every_scene_not_hunted():
    from src.model_select import region_scenes
    imgs = [Path(f"{s}_0_0.png") for s in ["SKA1", "SKA2", "OMA1", "LAC1"]]
    hunted = {"oman": {"OMA1"}, "laconia": {"LAC1"}}
    assert region_scenes("skagen", imgs, hunted) == {"SKA1", "SKA2"}
    assert region_scenes("oman", imgs, hunted) == {"OMA1"}
    import pytest
    with pytest.raises(ValueError):
        region_scenes("biscay", imgs, hunted)


def _drive(tmp_path):
    """Fake Drive: 3 scenes per region, 2 tiles each, hunt CSVs for Oman/Laconia."""
    import pandas as pd
    root, tiles = tmp_path / "drive", tmp_path / "drive" / "tiles_multi"
    (tiles / "images").mkdir(parents=True)
    (tiles / "labels").mkdir()
    scenes = {r: [f"{r.upper()}{i}_vv" for i in range(3)] for r in ("skagen", "oman", "laconia")}
    for ss in scenes.values():
        for s in ss:
            for off in (0, 1024):
                (tiles / "images" / f"{s}_{off}_0.png").write_bytes(b"")
                (tiles / "labels" / f"{s}_{off}_0.txt").write_text("0 0.5 0.5 0.1 0.1\n")
    for r in ("oman", "laconia"):
        (root / f"hunt_{r}").mkdir()
        pd.DataFrame({"scene": scenes[r]}).to_csv(root / f"hunt_{r}" / "all_checked.csv", index=False)
    return root, scenes


def test_build_holds_out_exactly_one_region(tmp_path):
    import yaml
    from src.model_select import REGIONS, build
    from src.train import scene_of
    root, scenes = _drive(tmp_path)
    for region in REGIONS:
        yml = build(root=root, test_region=region, out=tmp_path / f"sel_{region}")
        split = {s: {scene_of(p.stem) for p in (yml.parent / s / "images").glob("*.png")}
                 for s in ("train", "val", "test")}
        labels = {p.stem for p in (yml.parent / "test" / "labels").glob("*.txt")}
        assert split["test"] == set(scenes[region])                      # all of it, nothing else
        assert not (split["train"] | split["val"]) & split["test"]
        assert not split["train"] & split["val"] and split["train"] and split["val"]
        assert labels == {p.stem for p in (yml.parent / "test" / "images").glob("*.png")}
        assert yaml.safe_load(yml.read_text())["test"] == "test/images"


def test_rotations_runs_each_region_once_into_one_table(tmp_path, monkeypatch):
    import pandas as pd
    from src import model_select
    calls = []

    def fake_run(models, epochs, root, device, test_region):
        calls.append(test_region)
        return pd.DataFrame([{"model": m.replace(".pt", ""), "test_region": test_region,
                              f"{test_region}_vessel_mAP50": 0.5} for m in models])

    monkeypatch.setattr(model_select, "run", fake_run)
    t = model_select.rotations(root=tmp_path, device="cpu")
    assert calls == ["skagen", "oman", "laconia"]
    assert len(t) == 6 and t.test_vessel_mAP50.notna().all()
    assert (tmp_path / "model_select_rotations.csv").exists()


def test_run_reports_errors_when_every_model_fails(tmp_path, monkeypatch):
    import sys, types
    from src import model_select
    (tmp_path / "test" / "images").mkdir(parents=True)
    monkeypatch.setattr(model_select, "build", lambda root, test_region: tmp_path / "data.yaml")

    def boom(*a, **k):
        raise ValueError("Invalid CUDA 'device=0' requested")
    monkeypatch.setattr(model_select, "train", boom)
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=None))
    t = model_select.run(models=["yolo26n.pt", "rtdetr-l.pt"], root=tmp_path, test_region="skagen")
    assert list(t.model) == ["yolo26n", "rtdetr-l"] and t.error.str.contains("CUDA").all()
