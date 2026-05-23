"""
eval.py — Automated retrieval quality evaluation.
Run this after indexing a repo to measure RAG accuracy.

Usage:
  python eval.py --repo-url https://github.com/pallets/flask --api http://localhost:8000

Outputs MRR@5, Hit@1, Hit@3, Hit@5 and a per-question breakdown.
"""

import argparse
import json
import time
import httpx

# Golden QA set — questions with expected file/symbol hints
# Extend this with repo-specific questions for your eval
GOLDEN_QA = [
    {
        "question": "How does the application handle HTTP request routing?",
        "expected_symbols": ["route", "add_url_rule", "dispatch_request", "Router"],
    },
    {
        "question": "Where is authentication or login handled?",
        "expected_symbols": ["login", "authenticate", "auth", "token", "session"],
    },
    {
        "question": "How are errors and exceptions handled globally?",
        "expected_symbols": ["errorhandler", "handle_exception", "error_handler", "HTTPException"],
    },
    {
        "question": "How does the application connect to the database?",
        "expected_symbols": ["connect", "engine", "session", "database", "db"],
    },
    {
        "question": "Where is middleware or request preprocessing done?",
        "expected_symbols": ["middleware", "before_request", "after_request", "dispatch"],
    },
    {
        "question": "How is configuration loaded and managed?",
        "expected_symbols": ["config", "Config", "from_object", "settings", "load_config"],
    },
    {
        "question": "How does the app handle static files and templates?",
        "expected_symbols": ["render_template", "send_file", "static", "template"],
    },
    {
        "question": "How are background tasks or async jobs handled?",
        "expected_symbols": ["async", "task", "background", "worker", "celery", "queue"],
    },
]


def wait_for_ingestion(api: str, job_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = httpx.get(f"{api}/api/jobs/{job_id}")
        job = resp.json()
        status = job["status"]
        print(f"  [{status}] {job.get('progress', 0)}% — {job.get('indexed_chunks', 0)}/{job.get('total_chunks', '?')} chunks")
        if status == "done":
            return job
        if status == "error":
            raise RuntimeError(f"Ingestion failed: {job.get('error')}")
        time.sleep(3)
    raise TimeoutError("Ingestion timed out")


def ask(api: str, repo_id: str, question: str) -> list[dict]:
    """Send a chat request and return the sources."""
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{api}/api/chat",
            json={"repo_id": repo_id, "question": question, "history": []},
        )
        sources = []
        buffer = ""
        for line in resp.iter_lines():
            if line.startswith("data: "):
                chunk = line[6:]
                buffer += chunk
                if "[SOURCES]" in buffer and "[/SOURCES]" in buffer:
                    import re
                    match = re.search(r"\[SOURCES\](.*?)\[/SOURCES\]", buffer, re.DOTALL)
                    if match:
                        try:
                            sources = json.loads(match.group(1))
                        except Exception:
                            pass
        return sources


def evaluate(api: str, repo_url: str):
    print(f"\n{'='*60}")
    print(f"CodebaseGPT Eval")
    print(f"Repo: {repo_url}")
    print(f"API:  {api}")
    print(f"{'='*60}\n")

    # Step 1: ingest
    print("Step 1: Indexing repository…")
    resp = httpx.post(f"{api}/api/ingest", json={"repo_url": repo_url}, timeout=30)
    job = resp.json()
    print(f"  Job ID: {job['job_id']}")

    if job["status"] != "done":
        job = wait_for_ingestion(api, job["job_id"])

    repo_id = job["repo_id"]
    total_chunks = job["total_chunks"]
    print(f"\n  ✓ Indexed {total_chunks} chunks (repo_id: {repo_id})\n")

    # Step 2: run questions
    print("Step 2: Running evaluation questions…\n")
    results = []

    for i, qa in enumerate(GOLDEN_QA):
        q = qa["question"]
        expected = set(s.lower() for s in qa["expected_symbols"])
        print(f"  Q{i+1}: {q}")

        try:
            sources = ask(api, repo_id, q)
        except Exception as e:
            print(f"      ERROR: {e}")
            results.append({"question": q, "hit_rank": None, "sources": []})
            continue

        # Check if any source matches expected symbols
        hit_rank = None
        for rank, src in enumerate(sources[:5]):
            name_lower = src.get("name", "").lower()
            file_lower = src.get("file", "").lower()
            if any(sym in name_lower or sym in file_lower for sym in expected):
                hit_rank = rank + 1
                break

        symbol_preview = ", ".join(s.get("name", "?") for s in sources[:3])
        status = f"HIT@{hit_rank}" if hit_rank else "MISS"
        print(f"      {status} — top sources: {symbol_preview}\n")
        results.append({"question": q, "hit_rank": hit_rank, "sources": sources})
        time.sleep(1)  # avoid rate limits

    # Step 3: compute metrics
    print(f"\n{'='*60}")
    print("Results\n")

    n = len(results)
    hits_at_1 = sum(1 for r in results if r["hit_rank"] == 1)
    hits_at_3 = sum(1 for r in results if r["hit_rank"] and r["hit_rank"] <= 3)
    hits_at_5 = sum(1 for r in results if r["hit_rank"] and r["hit_rank"] <= 5)
    mrr = sum(1 / r["hit_rank"] for r in results if r["hit_rank"]) / n

    print(f"  Hit@1  : {hits_at_1}/{n}  ({100*hits_at_1/n:.0f}%)")
    print(f"  Hit@3  : {hits_at_3}/{n}  ({100*hits_at_3/n:.0f}%)")
    print(f"  Hit@5  : {hits_at_5}/{n}  ({100*hits_at_5/n:.0f}%)")
    print(f"  MRR@5  : {mrr:.3f}")
    print(f"\n  Total chunks indexed: {total_chunks}")
    print(f"{'='*60}\n")

    # Save results
    output = {
        "repo_url": repo_url,
        "repo_id": repo_id,
        "total_chunks": total_chunks,
        "metrics": {
            "hit_at_1": hits_at_1 / n,
            "hit_at_3": hits_at_3 / n,
            "hit_at_5": hits_at_5 / n,
            "mrr_at_5": mrr,
        },
        "results": results,
    }
    with open("eval_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print("  Full results saved to eval_results.json\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate CodebaseGPT retrieval quality")
    parser.add_argument("--repo-url", required=True, help="GitHub repo URL to test")
    parser.add_argument("--api", default="http://localhost:8000", help="Backend API URL")
    args = parser.parse_args()
    evaluate(args.api, args.repo_url)
# backend: add eval harness for retrieval quality
# backend: improve eval with precision and recall metrics
# backend: add eval harness for retrieval quality
# backend: improve eval with precision and recall metrics
# backend: add eval harness for retrieval quality
# backend: improve eval with precision and recall metrics
# backend: add eval harness for retrieval quality
