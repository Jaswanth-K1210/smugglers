"""Backend on Modal (serverless CPU, $30/month free credits).

    pip install modal && modal setup          # once: browser login
    (cd webapp/frontend && npm run build)     # the website, served from the same URL
    modal deploy modal_app.py                 # prints the URL

Same FastAPI app as the Docker image (webapp/backend/app.py). Secrets are read
from the local .env at deploy time and sent to Modal, never committed. User
accounts, the search cache and the downloaded detector live on a Modal Volume,
so they survive restarts and redeploys.

One container (max_containers=1): the search jobs table is in memory, so the
poll for a job must reach the container that runs it. It scales to zero after
10 idle minutes; the first request after that waits ~30 s for a cold start.
Cost: ~2 CPU-minutes per search, well under a cent.
"""
import modal

values = {}
if modal.is_local():                          # deploy time only: read .env, keep only what's needed
    from src.config import GFW_API_TOKEN
    if not GFW_API_TOKEN:
        raise SystemExit("GFW_API_TOKEN is empty in .env; the backend needs it for AIS.")
    import os
    if os.getenv("AISSTREAM_API_KEY"):        # live ship dots on the map; optional
        values["AISSTREAM_API_KEY"] = os.environ["AISSTREAM_API_KEY"]
    values["GFW_API_TOKEN"] = GFW_API_TOKEN
    # no AUTH_SECRET here: the app makes a random one on the volume and keeps it

image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install_from_requirements("webapp/requirements.txt",
                                        extra_index_url="https://download.pytorch.org/whl/cpu")
         .env({"HF_MODEL_REPO": "Jaswanth-K/darksts-detector",
               "EVENTS_PATH": "/app/outputs/events.geojson",
               "USERS_DB": "/app/data/users.db",
               "HF_HOME": "/app/data/hf",
               "YOLO_CONFIG_DIR": "/app/data/ultralytics",
               "GFW_RETRY_WAIT": "5"})
         .add_local_dir("src", "/app/src", ignore=["__pycache__"])
         .add_local_dir("webapp/backend", "/app/webapp/backend", ignore=["__pycache__"])
         .add_local_file("outputs/events.geojson", "/app/outputs/events.geojson")
         # built website (cd webapp/frontend && npm run build), served by the same app: one URL
         .add_local_dir("webapp/frontend/dist", "/app/webapp/frontend/dist"))

app = modal.App("darksts")
data = modal.Volume.from_name("darksts-data", create_if_missing=True)


@app.function(image=image, cpu=2, memory=4096, timeout=900, volumes={"/app/data": data},
              secrets=[modal.Secret.from_dict(values)], max_containers=1, scaledown_window=600)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    import os
    import sys
    sys.path.insert(0, "/app")
    os.chdir("/app")
    from webapp.backend.app import app as api
    return api
