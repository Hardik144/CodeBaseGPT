#!/bin/sh
# Copy baked model to volume mount on first run
# This ensures the model is always available even with an empty volume
if [ ! -d "/app/models/BAAI" ] && [ ! -d "/app/models/models--BAAI" ]; then
    echo "[start] Copying model to volume..."
    cp -r /app/model_baked/. /app/models/ 2>/dev/null || true
    echo "[start] Model copied."
else
    echo "[start] Model already in volume, skipping copy."
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000
