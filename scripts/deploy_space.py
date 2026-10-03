"""Publish the backend to a Hugging Face Space (Docker, free CPU) in one command.

    python3 scripts/deploy_space.py

Asks for a Hugging Face WRITE token in a hidden prompt (never pass it as an
argument or put it in code). Uploads only what the image needs, with the
Dockerfile at the root as Spaces expect, and sets the Space's secrets:
GFW_API_TOKEN from .env, a random AUTH_SECRET, and HF_MODEL_REPO as a variable.
"""
import secrets
import shutil
import sys
import tempfile
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPACE = "darksts"
MODEL_REPO = "Jaswanth-K/darksts-detector"
README = """---
title: Dark STS search
emoji: 🛰️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

Backend API for the dark ship-to-ship transfer detection project: draw a box,
get Sentinel-1 ship detections checked against AIS, with reasons.
Source: https://github.com/Jaswanth-K1210/smugglers
"""


def main():
    from huggingface_hub import HfApi
    from src.config import GFW_API_TOKEN

    if not GFW_API_TOKEN:
        sys.exit("GFW_API_TOKEN is empty in .env; the Space needs it for AIS.")
    api = HfApi(token=getpass("Hugging Face WRITE token (hidden): ").strip())
    repo = f"{api.whoami()['name']}/{SPACE}"
    api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copytree(ROOT / "src", tmp / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "webapp" / "backend", tmp / "webapp" / "backend",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "webapp" / "frontend", tmp / "webapp" / "frontend",
                        ignore=shutil.ignore_patterns("node_modules", "dist", ".vite"))
        shutil.copy(ROOT / "webapp" / "requirements.txt", tmp / "webapp" / "requirements.txt")
        (tmp / "outputs").mkdir()
        shutil.copy(ROOT / "outputs" / "events.geojson", tmp / "outputs" / "events.geojson")
        shutil.copy(ROOT / "webapp" / "Dockerfile", tmp / "Dockerfile")
        (tmp / "README.md").write_text(README)
        api.upload_folder(folder_path=str(tmp), repo_id=repo, repo_type="space",
                          commit_message="deploy from GitHub main")

    api.add_space_secret(repo, "GFW_API_TOKEN", GFW_API_TOKEN)
    api.add_space_secret(repo, "AUTH_SECRET", secrets.token_hex(32))
    api.add_space_variable(repo, "HF_MODEL_REPO", MODEL_REPO)
    host = repo.replace("/", "-").lower()
    print(f"Space: https://huggingface.co/spaces/{repo}")
    print(f"API:   https://{host}.hf.space/api/health   (ready after the build, ~5-10 min)")


if __name__ == "__main__":
    main()
