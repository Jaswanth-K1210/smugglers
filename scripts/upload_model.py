"""Upload trained weights straight to Modal (volume "darksts-models"), no Hugging Face needed.

From Colab, after training (Modal token in Colab secrets MODAL_TOKEN_ID / MODAL_TOKEN_SECRET):

    !pip install -q modal
    import os
    from google.colab import userdata
    os.environ["MODAL_TOKEN_ID"] = userdata.get("MODAL_TOKEN_ID")
    os.environ["MODAL_TOKEN_SECRET"] = userdata.get("MODAL_TOKEN_SECRET")
    !python scripts/upload_model.py /content/drive/MyDrive/darksts/models/multi_yolo26n/weights/best.pt

From a machine where `modal setup` was run, the same command works without the two variables.
The served model is always /best.pt on the volume; the search worker and the website load it on
their next cold start (or redeploy them to switch at once). `--as rtdetr.pt` stores a backup model.
"""
import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

VOLUME = "darksts-models"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("weights", help="path to the trained .pt file")
    ap.add_argument("--as", dest="name", default="best.pt", help="name on the volume (best.pt is the served model)")
    ap.add_argument("--note", default="", help="free text kept in MODEL_INFO.json, e.g. the training run")
    a = ap.parse_args(argv)

    import modal
    path = Path(a.weights)
    if not path.is_file() or path.stat().st_size < 1_000_000:
        raise SystemExit(f"{path} is missing or too small to be trained weights.")
    vol = modal.Volume.from_name(VOLUME, create_if_missing=True)
    try:
        info = json.loads(b"".join(vol.read_file("MODEL_INFO.json")))
    except Exception:
        info = {}
    info[a.name] = {"sha256": sha256(path), "bytes": path.stat().st_size, "source": str(path),
                    "uploaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": a.note}
    with vol.batch_upload(force=True) as up:
        up.put_file(str(path), f"/{a.name}")
        up.put_file(io.BytesIO(json.dumps(info, indent=1).encode()), "/MODEL_INFO.json")
    print(f"uploaded {path.name} -> volume {VOLUME}:/{a.name}  sha256 {info[a.name]['sha256'][:16]}  "
          f"{info[a.name]['bytes'] / 1e6:.2f} MB")
    print("served on the next cold start; to switch now: modal deploy modal_worker.py && modal deploy modal_app.py")


if __name__ == "__main__":
    main()
