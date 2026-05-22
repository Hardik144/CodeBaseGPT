"""
Local embedder — BAAI/bge-small-en-v1.5.
Batch size kept small (8) to avoid long CPU spikes that overheat the machine.
"""

import os
from functools import lru_cache

MODEL_NAME      = "BAAI/bge-small-en-v1.5"
MODEL_CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR", "/app/models")
MODEL_BAKED_DIR = "/app/model_baked"


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    for cache_dir in [MODEL_CACHE_DIR, MODEL_BAKED_DIR]:
        try:
            print(f"[embedder] Loading from {cache_dir}...")
            m = SentenceTransformer(MODEL_NAME, cache_folder=cache_dir)
            print(f"[embedder] Ready — dim={m.get_sentence_embedding_dimension()}")
            return m
        except Exception as e:
            print(f"[embedder] {cache_dir} failed: {e}")
    raise RuntimeError("Could not load embedding model")


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    # Small batch size = shorter CPU bursts = cooler Mac
    vecs = model.encode(
        texts,
        batch_size=8,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return vecs.tolist()


def embed_query(query: str) -> list[float]:
    return embed_texts([f"Represent this sentence: {query}"])[0]


def embed_documents(docs: list[str]) -> list[list[float]]:
    return embed_texts(docs)
# backend: add OpenAI embedding module
# backend: add retry and backoff to embedder
# backend: add OpenAI embedding module
# backend: add retry and backoff to embedder
# backend: add OpenAI embedding module
# backend: add retry and backoff to embedder
# backend: add OpenAI embedding module
