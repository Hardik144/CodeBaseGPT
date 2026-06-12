"""
Ingestion pipeline — runs all heavy CPU work in a thread pool
so it never blocks the async event loop or overheats the CPU.
"""

import re
import shutil
import tempfile
import hashlib
import asyncio
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Optional

import git

from chunker import chunk_repository
from store import get_store
from config import get_settings

# Single shared thread pool — limits CPU parallelism to avoid overheating
_executor = ThreadPoolExecutor(max_workers=1)


class JobStatus(str, Enum):
    PENDING  = "pending"
    CLONING  = "cloning"
    CHUNKING = "chunking"
    INDEXING = "indexing"
    DONE     = "done"
    ERROR    = "error"


class IngestionJob:
    def __init__(self, job_id: str, repo_url: str):
        self.job_id         = job_id
        self.repo_url       = repo_url
        self.status         = JobStatus.PENDING
        self.progress       = 0
        self.total_chunks   = 0
        self.indexed_chunks = 0
        self.error: Optional[str] = None
        self.repo_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "job_id":         self.job_id,
            "repo_url":       self.repo_url,
            "status":         self.status,
            "progress":       self.progress,
            "total_chunks":   self.total_chunks,
            "indexed_chunks": self.indexed_chunks,
            "error":          self.error,
            "repo_id":        self.repo_id,
        }


_jobs: dict[str, IngestionJob] = {}


def create_job(repo_url: str) -> IngestionJob:
    job_id = hashlib.md5(repo_url.encode()).hexdigest()[:12]
    # Reuse if done or currently running — never overwrite a live job
    if job_id in _jobs and _jobs[job_id].status in (
        JobStatus.DONE, JobStatus.PENDING, JobStatus.CLONING,
        JobStatus.CHUNKING, JobStatus.INDEXING,
    ):
        return _jobs[job_id]
    # Create fresh only if errored or brand new
    job = IngestionJob(job_id=job_id, repo_url=repo_url)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[IngestionJob]:
    return _jobs.get(job_id)


def repo_url_to_id(url: str) -> str:
    clean = re.sub(r'https?://', '', url).rstrip('/')
    return hashlib.md5(clean.encode()).hexdigest()[:16]


def normalize_url(url: str) -> str:
    url = url.strip().rstrip('/')
    if not url.endswith('.git') and 'github.com' in url:
        url += '.git'
    return url


# ── Sync functions run in thread pool ────────────────────────────────────────

def _clone(url: str, tmpdir: str, token: str):
    if token and 'github.com' in url:
        url = url.replace('https://github.com', f'https://{token}@github.com')
    git.Repo.clone_from(url, tmpdir, depth=1)


def _chunk(tmpdir: str) -> list:
    return chunk_repository(tmpdir)


def _index_batch(store, batch: list) -> None:
    """Embed + store one small batch. Small batches = lower CPU spike."""
    store.add_chunks(batch, batch_size=len(batch))


# ── Main async pipeline ───────────────────────────────────────────────────────

async def run_ingestion(job: IngestionJob):
    settings = get_settings()
    loop     = asyncio.get_event_loop()
    tmpdir   = None

    try:
        # ── 1. Clone (network I/O in thread) ──────────────────────────
        job.status   = JobStatus.CLONING
        job.progress = 5

        tmpdir    = tempfile.mkdtemp(prefix="cgpt_")
        clone_url = normalize_url(job.repo_url)

        await loop.run_in_executor(
            _executor, _clone, clone_url, tmpdir, settings.github_token
        )
        job.progress = 20

        # ── 2. Chunk (CPU in thread) ───────────────────────────────────
        job.status   = JobStatus.CHUNKING
        job.progress = 25

        chunks = await loop.run_in_executor(_executor, _chunk, tmpdir)
        job.total_chunks = len(chunks)
        job.progress     = 45

        if not chunks:
            raise ValueError(
                "No source files found. Repo must contain .py, .js, or .ts files."
            )

        # ── 3. Index in tiny batches (CPU in thread, yield between) ───
        job.status  = JobStatus.INDEXING
        repo_id     = repo_url_to_id(job.repo_url)
        job.repo_id = repo_id

        store = get_store(repo_id)
        await loop.run_in_executor(_executor, store.clear)

        # 8 chunks per batch — small enough to not spike CPU for >1s at a time
        BATCH = 8
        total = len(chunks)

        for i in range(0, total, BATCH):
            batch = chunks[i : i + BATCH]
            await loop.run_in_executor(_executor, _index_batch, store, batch)
            job.indexed_chunks += len(batch)
            job.progress = 45 + int((job.indexed_chunks / total) * 54)
            # Yield to event loop between batches so health checks still respond
            await asyncio.sleep(0)

        job.status   = JobStatus.DONE
        job.progress = 100

    except Exception as e:
        job.status = JobStatus.ERROR
        job.error  = str(e)

    finally:
        if tmpdir and Path(tmpdir).exists():
            shutil.rmtree(tmpdir, ignore_errors=True)
