"""
Hybrid retrieval: ChromaDB dense search + BM25 keyword search → RRF merge.
Local embeddings — no API key needed.
"""

from typing import Optional
from dataclasses import dataclass

import chromadb
from rank_bm25 import BM25Okapi

from chunker import CodeChunk
from config import get_settings


class LocalEmbeddingFunction:
    """ChromaDB-compatible embedding function using local sentence-transformers."""

    def __call__(self, input):  # input is list[str]
        from embedder import embed_documents
        return embed_documents(list(input))


@dataclass
class RetrievedChunk:
    chunk: CodeChunk
    score: float
    retrieval_method: str


class HybridStore:
    def __init__(self, repo_id: str):
        self.repo_id = repo_id
        settings = get_settings()

        self._client = chromadb.PersistentClient(path=settings.chroma_path)
        self._ef = LocalEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=f"repo_{repo_id}",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: list[str] = []

    def add_chunks(self, chunks: list[CodeChunk], batch_size: int = 32) -> int:
        """Upsert chunks in small batches to avoid memory spikes."""
        added = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            self._collection.upsert(
                ids=[c.chunk_id for c in batch],
                documents=[c.to_embed_text() for c in batch],
                metadatas=[c.to_metadata() for c in batch],
            )
            added += len(batch)
        self._bm25 = None  # invalidate
        return added

    def clear(self):
        try:
            self._client.delete_collection(f"repo_{self.repo_id}")
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=f"repo_{self.repo_id}",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        self._bm25 = None

    def count(self) -> int:
        return self._collection.count()

    def _build_bm25(self):
        if self._bm25 is not None:
            return
        if not hasattr(self, "_bm25_building"):
            self._bm25_building = False
        if self._bm25_building:
            return
        self._bm25_building = True
        results = self._collection.get(include=["documents"])
        if not results["ids"]:
            return
        self._bm25_ids = results["ids"]
        tokenized = [doc.lower().split() for doc in results["documents"]]
        self._bm25 = BM25Okapi(tokenized)
        self._bm25_building = False

    def _bm25_search(self, query: str, k: int) -> list[tuple[str, float]]:
        self._build_bm25()
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(query.lower().split())
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]
        return [(self._bm25_ids[i], float(s)) for i, s in ranked if s > 0]

    def search(self, query: str, k: int = 8) -> list[RetrievedChunk]:
        from embedder import embed_query

        count = self.count()
        if count == 0:
            return []

        k_over = min(k * 3, count)

        # Dense search using pre-computed embedding
        qvec = embed_query(query)
        dense = self._collection.query(
            query_embeddings=[qvec],
            n_results=k_over,
            include=["documents", "metadatas", "distances"],
        )
        dense_ids = dense["ids"][0]
        dense_metas = dense["metadatas"][0]
        dense_docs = dense["documents"][0]

        # BM25 search
        bm25_results = self._bm25_search(query, k_over)
        bm25_rank = {cid: r for r, (cid, _) in enumerate(bm25_results)}

        # Reciprocal Rank Fusion
        C = 60
        rrf: dict[str, float] = {}
        for r, cid in enumerate(dense_ids):
            rrf[cid] = rrf.get(cid, 0) + 1 / (C + r)
        for cid, _ in bm25_results:
            rrf[cid] = rrf.get(cid, 0) + 1 / (C + bm25_rank[cid])

        top_ids = sorted(rrf, key=lambda x: rrf[x], reverse=True)[:k]

        # Build lookup from dense results
        lookup: dict[str, tuple[dict, str]] = {}
        for cid, meta, doc in zip(dense_ids, dense_metas, dense_docs):
            lookup[cid] = (meta, doc)

        # Fetch any BM25-only IDs not in dense results
        missing = [cid for cid in top_ids if cid not in lookup]
        if missing:
            fetched = self._collection.get(
                ids=missing, include=["documents", "metadatas"]
            )
            for cid, meta, doc in zip(
                fetched["ids"], fetched["metadatas"], fetched["documents"]
            ):
                lookup[cid] = (meta, doc)

        dense_set = set(dense_ids)
        results = []
        for cid in top_ids:
            if cid not in lookup:
                continue
            meta, doc = lookup[cid]
            method = (
                "hybrid" if cid in bm25_rank and cid in dense_set
                else "dense" if cid in dense_set
                else "bm25"
            )
            results.append(RetrievedChunk(
                chunk=_meta_to_chunk(meta, doc),
                score=rrf[cid],
                retrieval_method=method,
            ))
        return results


def _meta_to_chunk(meta: dict, doc: str) -> CodeChunk:
    # Strip the metadata header lines (start with #) to get raw code
    lines = doc.split("\n")
    code_start = next((i for i, ln in enumerate(lines) if not ln.startswith("#")), 0)
    code = "\n".join(lines[code_start:]).strip()
    return CodeChunk(
        content=code,
        file_path=meta.get("file_path", ""),
        chunk_type=meta.get("chunk_type", "block"),
        name=meta.get("name", ""),
        start_line=int(meta.get("start_line", 0)),
        end_line=int(meta.get("end_line", 0)),
        language=meta.get("language", ""),
        parent_name=meta.get("parent_name") or None,
        docstring=meta.get("docstring") or None,
        calls=meta.get("calls", "").split(",") if meta.get("calls") else [],
    )


_stores: dict[str, HybridStore] = {}


def get_store(repo_id: str) -> HybridStore:
    if repo_id not in _stores:
        _stores[repo_id] = HybridStore(repo_id)
    return _stores[repo_id]
