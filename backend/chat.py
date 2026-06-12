"""
Chat engine — Gemini (free), Groq (free, fastest), OpenAI (paid).
Auto-fallback between models on quota/rate-limit errors.
"""

import json
import re
from typing import AsyncIterator
from openai import AsyncOpenAI

from store import get_store, RetrievedChunk
from config import get_settings

SYSTEM_PROMPT = """You are CodebaseGPT. Answer questions about a codebase using the provided code chunks.

STRICT OUTPUT FORMAT — follow exactly:

Line 1: One sentence direct answer. End with period.
Line 2: blank
Lines 3+: bullet points, one per line, each starting with "- "

Every bullet:  - **Label:** value [filename:lines]

Example:
The database connection is handled in `connectDB`.

- **File:** `backend/config/db.js` [backend/config/db.js:3-11]
- **Function:** `connectDB` calls `mongoose.connect()`
- **On error:** logs error and calls `process.exit(1)`
- **Also used in:** `server.js` at startup [server.js:8]

MANDATORY RULES:
- After line 1, ONLY blank lines or lines starting with "- "
- NO prose paragraphs after line 1
- NO numbered lists, NO headers (#, ##, ###)
- Max 6 bullets
- Every bullet has a [file:lines] citation
- Backticks around all code: `functionName`, `file.js`
"""

_SYNONYMS = {
    "login":      ["authenticate", "auth", "token", "session", "jwt"],
    "auth":       ["authenticate", "token", "jwt", "session", "login", "permission"],
    "database":   ["db", "sql", "query", "model", "schema", "orm", "connect"],
    "error":      ["exception", "handler", "try", "catch", "raise"],
    "route":      ["endpoint", "url", "path", "controller", "handler", "router"],
    "middleware": ["before_request", "after_request", "interceptor", "hook"],
    "config":     ["settings", "env", "environment", "configuration"],
    "test":       ["spec", "assert", "mock", "fixture", "pytest", "unittest"],
    "websocket":  ["socket", "ws", "realtime", "emit", "broadcast"],
    "cache":      ["redis", "ttl", "store", "invalidate"],
    "password":   ["hash", "bcrypt", "salt", "encrypt", "secret"],
    "upload":     ["file", "multipart", "storage", "s3", "blob"],
}

GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b"]
GROQ_MODELS   = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]


def _expand_query(question: str) -> str:
    lower = question.lower()
    extras = []
    for kw, syns in _SYNONYMS.items():
        if kw in lower:
            extras.extend(syns)
    return f"{question} {' '.join(set(extras))}" if extras else question


def _build_context(chunks: list[RetrievedChunk]) -> str:
    parts = []
    seen: dict[str, list[str]] = {}
    for rc in chunks:
        c = rc.chunk
        location = f"[{c.file_path}:{c.start_line}-{c.end_line}]"
        label = f"{c.chunk_type.upper()}: {c.name}"
        if c.parent_name:
            label += f" (in {c.parent_name})"
        header = f"LOCATION: {location}\nTYPE: {label}"
        if c.docstring:
            header += f"\nDOC: {c.docstring[:150]}"
        parts.append(f"{header}\n```{c.language}\n{c.content}\n```")
        seen.setdefault(c.file_path, []).append(c.name)

    index = "\n".join(f"  {fp}: {', '.join(s)}" for fp, s in seen.items())
    return f"REFERENCED FILES:\n{index}\n\n{'='*60}\n\n" + "\n\n".join(parts)


def _is_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return "429" in s or "quota" in s or "rate_limit" in s or "resource_exhausted" in s


def _enforce_format(raw: str) -> str:
    """
    No matter what the LLM returns, convert it to:
      Summary sentence.

      - **Label:** value [citation]
      - **Label:** value [citation]
    """
    if not raw or not raw.strip():
        return raw

    text = raw.strip().replace("\r\n", "\n").replace("\r", "\n")

    # Normalize common bullet markers and inline separators.
    text = re.sub(r"•\s*", "- ", text)
    text = re.sub(r"[·‣]\s*", "- ", text)
    text = re.sub(r"(^|\n)(\s*)[\*\+]\s+", r"\1\2- ", text)
    text = re.sub(r"([.!?])\s+(-\s+)", r"\1\n\2", text)
    text = re.sub(r"(?<!\n)\s+-\s+(?=[A-Z`\[\*])", "\n- ", text)
    text = re.sub(r"([.!?])\s+(\d+)[.)]\s+", r"\1\n- ", text)
    text = re.sub(r"([.!?])\s+([A-Z][A-Za-z ]{1,22}: )", r"\1\n- \2", text)
    text = re.sub(r"^\s*([A-Z][A-Za-z ]{1,22}: )", r"- \1", text, flags=re.MULTILINE)

    lines = [l.rstrip() for l in text.split("\n")]

    # ── Step 2: extract summary (first non-empty line) ────────────────────────
    summary = ""
    rest_start = 0
    for i, line in enumerate(lines):
        if line.strip():
            summary = line.strip()
            rest_start = i + 1
            break

    # ── Step 3: parse remaining lines into bullet list ────────────────────────
    bullets = []
    current = ""

    def flush():
        nonlocal current
        if current:
            bullets.append(current)
            current = ""

    for line in lines[rest_start:]:
        s = line.strip()
        if not s:
            continue

        # Already a bullet
        if s.startswith("- "):
            flush()
            current = s
            continue

        # Numbered list → bullet
        m = re.match(r"^\d+[.)]\s+(.*)", s)
        if m:
            flush()
            current = "- " + m.group(1)
            continue

        # Header → bullet
        m = re.match(r"^#{1,3}\s+(.*)", s)
        if m:
            flush()
            current = "- **" + m.group(1).strip() + "**"
            continue

        # "Label: value" → bullet (label must be short)
        m = re.match(r"^\*{0,2}([A-Za-z][A-Za-z\s]{0,20})\*{0,2}:\s+(.*)", s)
        if m and 2 <= len(m.group(1).strip()) <= 22:
            flush()
            label = m.group(1).strip().title()
            value = m.group(2).strip()
            current = f"- **{label}:** {value}"
            continue

        # Continuation or orphan sentence
        if current and len(current) < 120:
            current += " " + s
        else:
            flush()
            if len(s) > 8:
                current = "- " + s

    flush()
    bullets = bullets[:6]

    # ── Step 4: ensure every bullet has a bold label ──────────────────────────
    clean = []
    for b in bullets:
        content = b[2:].strip()
        if not re.match(r"\*\*[^*]+\*\*", content):
            # Try to split at first colon
            colon = content.find(":")
            if 0 < colon < 22 and not content.startswith(("[", "`")):
                lbl = content[:colon].strip()
                val = content[colon+1:].strip()
                content = f"**{lbl.title()}:** {val}"
            elif " — " in content:
                lbl, _, val = content.partition(" — ")
                content = f"**{lbl.strip()}** — {val.strip()}"
        clean.append("- " + content)

    if clean:
        return summary + "\n\n" + "\n".join(clean)
    return summary


async def stream_chat(
    repo_id: str,
    question: str,
    history: list[dict],
    k: int = 6,
) -> AsyncIterator[str]:
    settings = get_settings()
    store = get_store(repo_id)

    if store.count() == 0:
        yield "Repository not indexed yet — please wait for ingestion to finish."
        return

    retrieved = store.search(_expand_query(question), k=k)
    if not retrieved:
        yield "No relevant code found. Try asking about a specific function or file name."
        return

    context = _build_context(retrieved)
    user_content = f"CODEBASE CONTEXT:\n\n{context}\n\n{'='*60}\n\nQUESTION: {question}"
    provider = settings.llm_provider

    if provider == "gemini":
        messages = [{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_content}"}]
        async for token in _collect_and_format(
            messages, GEMINI_MODELS,
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            provider_name="Gemini",
        ):
            yield token

    elif provider == "groq":
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-4:],
            {"role": "user", "content": user_content},
        ]
        async for token in _collect_and_format(
            messages, GROQ_MODELS,
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            provider_name="Groq",
        ):
            yield token

    else:  # openai
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-4:],
            {"role": "user", "content": user_content},
        ]
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            full = ""
            stream = await client.chat.completions.create(
                model=settings.chat_model, messages=messages,
                stream=True, temperature=0.1, max_tokens=800,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full += delta
            yield _enforce_format(full)
        except Exception as e:
            yield f"OpenAI error: {e}"

    sources = [
        {"file": rc.chunk.file_path, "start": rc.chunk.start_line,
         "end": rc.chunk.end_line, "name": rc.chunk.name,
         "type": rc.chunk.chunk_type, "method": rc.retrieval_method}
        for rc in retrieved
    ]
    yield f"\n\n[SOURCES]{json.dumps(sources)}[/SOURCES]"


async def _collect_and_format(
    messages: list, models: list[str],
    api_key: str, base_url: str, provider_name: str,
) -> AsyncIterator[str]:
    """Collect full LLM response, post-process format, yield clean result."""
    if not api_key:
        yield (f"No API key for {provider_name}. "
               f"Add `{provider_name.upper()}_API_KEY` to `.env` and restart.")
        return

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    for model in models:
        try:
            full = ""
            stream = await client.chat.completions.create(
                model=model, messages=messages,
                stream=True, temperature=0.1, max_tokens=800,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full += delta
            yield _enforce_format(full)
            return

        except Exception as e:
            if _is_rate_limit(e):
                continue
            yield f"{provider_name} error ({model}): {e}"
            return

    if provider_name == "Groq":
        yield "Groq rate limit hit.\n\n- **Fix:** Wait 60 seconds and retry\n- **Alternative:** Set `LLM_PROVIDER=gemini` in `.env`"
    else:
        yield "Gemini daily quota reached.\n\n- **Fix:** Wait ~24h for reset\n- **Alternative:** Set `LLM_PROVIDER=groq` + `GROQ_API_KEY` in `.env`\n- **Get key:** [console.groq.com](https://console.groq.com)"
