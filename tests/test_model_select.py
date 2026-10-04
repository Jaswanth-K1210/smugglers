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
