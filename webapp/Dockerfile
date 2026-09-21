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

COPY webapp/backend ./webapp/backend
COPY webapp/frontend ./webapp/frontend
COPY outputs/events.geojson ./outputs/events.geojson
# Weights are optional: without them /api/detect reports 503 and the
# precomputed endpoints still work.
COPY models* ./models/

ENV EVENTS_PATH=/app/outputs/events.geojson \
    WEIGHTS_PATH=/app/models/darksts/weights/best.pt
EXPOSE 7860
CMD ["uvicorn", "webapp.backend.app:app", "--host", "0.0.0.0", "--port", "7860"]
