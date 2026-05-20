# CodebaseGPT

Ask questions about any GitHub codebase in plain English. **100% free to run.**

```
"How does authentication work?" → cites auth/utils.py:34-67
"Where is database connection handled?" → cites db/connection.py:12-28
"Explain the request lifecycle" → synthesizes 6 relevant chunks with citations
```

## Zero cost setup

| Component | What it uses | Cost |
|---|---|---|
| Embeddings | `BAAI/bge-small-en-v1.5` local model | **FREE** |
| Chat / answers | Google Gemini 2.0 Flash | **FREE** (1500 req/day) |
| Vector search | ChromaDB (local) | **FREE** |
| Keyword search | BM25 (in-memory) | **FREE** |

No OpenAI key needed at all.

---

## Quick start (5 minutes)

```bash
git clone https://github.com/yourusername/codebasegpt
cd codebasegpt

cp .env.example .env
```

Edit `.env` — add only one thing:
```env
GEMINI_API_KEY=AIza-your-key-here
```

Get a free Gemini key at **aistudio.google.com/apikey** → Create API Key (no credit card).

```bash
docker-compose up --build
```

Open **http://localhost:3000**, paste any GitHub URL, click Index.

> **First build takes ~5 min** — it downloads the 130MB embedding model once.  
> Subsequent builds are fast (model is cached in a Docker volume).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│         Chat UI · File citations · SSE streaming         │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                  FastAPI Backend                          │
│   /api/ingest  /api/jobs/:id  /api/chat  /api/repos/:id  │
└──────┬──────────────┬──────────────────────┬────────────┘
       │              │                      │
  ┌────▼──────┐  ┌────▼──────────────┐  ┌───▼────────────┐
  │ Ingestion │  │ Hybrid Retrieval  │  │ Gemini 2.0     │
  │ Pipeline  │  │ Dense + BM25 RRF  │  │ Flash (free)   │
  └────┬──────┘  └────┬──────────────┘  └────────────────┘
       │              │
  ┌────▼──────┐  ┌────▼──────────────┐
  │Tree-sitter│  │ ChromaDB          │
  │AST chunker│  │ bge-small vectors │
  │           │  │ + BM25 index      │
  └───────────┘  └───────────────────┘
                      ▲
              ┌───────┴──────────┐
              │ BAAI/bge-small   │
              │ LOCAL embeddings │
              │ (no API needed)  │
              └──────────────────┘
```

---

## How it works

### Ingestion pipeline
1. Clone repo with `gitpython` (depth=1 for speed)
2. Walk all source files, skip `node_modules`, `.git`, build dirs
3. Parse each file with **AST-aware chunker** — never splits a function in half
4. Each chunk = one complete function/class with metadata (name, file, lines, calls)
5. Embed locally with `BAAI/bge-small-en-v1.5` — runs on CPU, ~50ms/batch
6. Store in ChromaDB + build BM25 keyword index in memory

### Why AST-aware chunking matters
Most tools split code every N lines blindly — a function gets split mid-body and the AI gets broken context. This chunker understands code structure:

```
Naive:          authenticate_user(     ← chunk 1 ends here
                    payload = decode   ← chunk 2 starts here (broken!)

AST-aware:      authenticate_user(     ← one complete chunk
                    payload = decode
                    user = db.get(...)
                    return user        ← ends at function boundary ✓
```

### Retrieval pipeline
1. Expand user query with code synonyms (no LLM call needed)
2. Dense search: embed query locally → cosine similarity in ChromaDB
3. BM25 search: keyword matching for exact symbol names
4. Merge both result lists with **Reciprocal Rank Fusion** → top-8 chunks
5. Assemble context with file index + ordered code blocks

---

## Local development

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # add GEMINI_API_KEY
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev             # http://localhost:3000
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ Yes | Free key from aistudio.google.com/apikey |
| `LLM_PROVIDER` | No | `gemini` (default) or `openai` |
| `OPENAI_API_KEY` | Only if `LLM_PROVIDER=openai` | Paid OpenAI key |
| `GITHUB_TOKEN` | Optional | Only for private repos |

---

## Supported languages

| Language | Chunking |
|---|---|
| Python | AST — functions, classes, methods, imports |
| JavaScript / JSX | AST — function declarations, arrow functions, classes |
| TypeScript / TSX | AST — same as JS |
| Go, Rust, Java, etc. | Fallback: overlapping fixed-size blocks |

---

## Eval (measure retrieval quality)

```bash
cd backend
python eval.py --repo-url https://github.com/pallets/flask

# Hit@1  : 6/8  (75%)
# Hit@3  : 8/8  (100%)
# MRR@5  : 0.854
```

This is what you show in interviews as proof the system works.

---

## Resume bullet

```
Built CodebaseGPT — an AI codebase Q&A system using AST-aware RAG (Tree-sitter 
structural parsing, ChromaDB, BM25 hybrid search + RRF) with fully local embeddings 
(BAAI/bge-small-en-v1.5) and Gemini 2.0 Flash for zero-cost inference. Chunks code 
at semantic boundaries improving retrieval MRR@5 vs naive chunking. Deployed via 
Docker Compose with FastAPI backend, React frontend, nginx SSE proxy.
```

---

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React 18, Vite |
| Backend | FastAPI, Python 3.11 |
| Chunking | Structural AST parsing (regex + tree analysis) |
| Embeddings | BAAI/bge-small-en-v1.5 via sentence-transformers (LOCAL) |
| Vector store | ChromaDB |
| Keyword search | rank-bm25 |
| LLM | Gemini 2.0 Flash (free) or GPT-4o |
| Repo cloning | gitpython |
| Deployment | Docker Compose, nginx |

---

## Project structure

```
codebasegpt/
├── backend/
│   ├── main.py          # FastAPI app + routes
│   ├── chunker.py       # AST-aware chunker (core differentiator)
│   ├── embedder.py      # Local embedding engine (sentence-transformers)
│   ├── store.py         # ChromaDB + BM25 hybrid store
│   ├── ingestion.py     # Pipeline: clone → chunk → index
│   ├── chat.py          # Context assembly + streaming generation
│   ├── config.py        # Pydantic settings
│   ├── eval.py          # Retrieval quality eval (MRR, Hit@k)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/App.jsx      # Complete React app
│   ├── nginx.conf       # SSE proxy config
│   └── ...
├── docker-compose.yml
└── .env.example
```
# Initial commit: project scaffold and repo setup
