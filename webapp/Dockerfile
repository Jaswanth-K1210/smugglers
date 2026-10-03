# Hugging Face Spaces (Docker SDK). CPU only — no GPU is needed to serve
# precomputed results, and the optional /api/detect endpoint runs YOLO nano on CPU.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch: ~200 MB instead of ~800 MB for the CUDA build. This is the
# difference between fitting a free tier and not.
COPY webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

COPY src ./src
COPY webapp/backend ./webapp/backend
COPY webapp/frontend ./webapp/frontend
COPY outputs/events.geojson ./outputs/events.geojson
# No weights in the image: they come from the Hugging Face Hub (HF_MODEL_REPO).

# Spaces run the container as uid 1000: everything written at runtime (user
# accounts, search cache, downloaded weights, Ultralytics settings) goes to one
# writable folder. Set HF_MODEL_REPO (and HF_TOKEN if the repo is private) and
# GFW_API_TOKEN as Space secrets; the detector is fetched from the Hub on the
# first search.
RUN mkdir -p /app/data && chmod 777 /app/data
ENV EVENTS_PATH=/app/outputs/events.geojson \
    WEIGHTS_PATH=/app/models/darksts/weights/best.pt \
    USERS_DB=/app/data/users.db \
    HF_HOME=/app/data/hf \
    YOLO_CONFIG_DIR=/app/data/ultralytics
EXPOSE 7860
CMD ["uvicorn", "webapp.backend.app:app", "--host", "0.0.0.0", "--port", "7860"]
