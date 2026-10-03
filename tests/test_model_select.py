from pathlib import Path

from src.model_select import partition


def test_test_region_never_in_train_or_val():
    imgs = [Path(f"{s}_0_{i}.png") for s in ["SKA1", "SKA2", "OMA1", "OMA2", "LAC1", "LAC2"] for i in (0, 1024)]
    p = partition(imgs, test_scenes={"LAC1", "LAC2"})
    assert {x.stem.rsplit("_", 2)[0] for x in p["test"]} == {"LAC1", "LAC2"}
    seen = {x.stem.rsplit("_", 2)[0] for x in p["train"] + p["val"]}
    assert not seen & {"LAC1", "LAC2"} and len(p["val"]) and len(p["train"])
    assert not {x.stem.rsplit("_", 2)[0] for x in p["train"]} & {x.stem.rsplit("_", 2)[0] for x in p["val"]}
