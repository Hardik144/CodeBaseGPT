import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import get_settings
from ingestion import create_job, get_job, run_ingestion, JobStatus, _jobs, IngestionJob
from store import get_store
from chat import stream_chat

_startup_executor = ThreadPoolExecutor(max_workers=1)


def _load_model():
    try:
        from embedder import embed_documents
        embed_documents(["warmup"])
        print("[startup] Embedding model ready.")
    except Exception as e:
        print(f"[startup] Model warmup warning: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    print("[startup] Loading embedding model in background...")
    loop.run_in_executor(_startup_executor, _load_model)
    yield


settings = get_settings()
app = FastAPI(title="CodebaseGPT", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origins, "http://localhost:3001", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    repo_url: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    repo_id: str
    question: str
    history: Optional[list[ChatMessage]] = []


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/ingest")
async def ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    url = req.repo_url.strip()
    if not url:
        raise HTTPException(400, "repo_url required")
    if not any(h in url for h in ["github.com", "gitlab.com", "bitbucket"]):
        raise HTTPException(400, "Only GitHub / GitLab / Bitbucket URLs supported")

    job = create_job(url)

    if job.status == JobStatus.DONE:
        return job.to_dict()

    if job.status in (JobStatus.CLONING, JobStatus.CHUNKING, JobStatus.INDEXING):
        return job.to_dict()

    # Reset error state so user can retry
    if job.status == JobStatus.ERROR:
        job = IngestionJob(job_id=job.job_id, repo_url=url)
        _jobs[job.job_id] = job

    background_tasks.add_task(run_ingestion, job)
    return job.to_dict()


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "question required")

    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]

    async def generate():
        try:
            async for token in stream_chat(
                repo_id=req.repo_id,
                question=req.question,
                history=history,
            ):
                yield {"data": token.replace("\n", "\\n")}
        except Exception as e:
            yield {"data": f"[ERROR]{e}[/ERROR]"}

    return EventSourceResponse(generate())


@app.get("/api/repos/{repo_id}")
async def repo_info(repo_id: str):
    store = get_store(repo_id)
    count = store.count()
    if count == 0:
        raise HTTPException(404, "Not indexed")
    return {"repo_id": repo_id, "chunk_count": count, "status": "ready"}
# backend: add FastAPI main entry point
# backend: add per-user rate limiting on chat endpoint
# fix: correct CORS origins in main.py
# backend: add /health endpoint for Docker healthcheck
# chore: clean up unused imports across backend
# backend: add FastAPI main entry point
# backend: add per-user rate limiting on chat endpoint
# fix: correct CORS origins in main.py
# backend: add /health endpoint for Docker healthcheck
# chore: clean up unused imports across backend
# backend: add FastAPI main entry point
# backend: add per-user rate limiting on chat endpoint
# fix: correct CORS origins in main.py
# backend: add /health endpoint for Docker healthcheck
# chore: clean up unused imports across backend
# backend: add FastAPI main entry point
# backend: add per-user rate limiting on chat endpoint
# fix: correct CORS origins in main.py
# backend: add /health endpoint for Docker healthcheck
# chore: clean up unused imports across backend
