FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch 2.4.0 — supports numpy 2.x natively
RUN pip install --no-cache-dir \
    torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu

# All other dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Download model into image layer (not the volume mount path)
# At runtime, if /app/models is an empty volume, startup script copies it over
RUN python3 -c "\
from sentence_transformers import SentenceTransformer; \
m = SentenceTransformer('BAAI/bge-small-en-v1.5', cache_folder='/app/model_baked'); \
print('Model baked into image, dim=' + str(m.get_sentence_embedding_dimension()))"

# Startup script: copy baked model to volume mount if not already there
COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 8000
CMD ["/start.sh"]
