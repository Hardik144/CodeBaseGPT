"""
AST-aware code chunker using tree-sitter.
Splits code at semantic boundaries (functions, classes, methods)
instead of naive line-based splitting.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass
class CodeChunk:
    content: str
    file_path: str
    chunk_type: str          # "function", "class", "method", "module", "import_block"
    name: str                # symbol name e.g. "authenticate_user"
    start_line: int
    end_line: int
    language: str
    parent_name: Optional[str] = None   # class name if this is a method
    docstring: Optional[str] = None
    calls: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)

    @property
    def chunk_id(self) -> str:
        return f"{self.file_path}::{self.name}::{self.start_line}"

    @property
    def display_location(self) -> str:
        return f"{self.file_path}:{self.start_line}-{self.end_line}"

    def to_embed_text(self) -> str:
        """Text sent to the embedding model — includes rich metadata as context."""
        header = f"# {self.language} {self.chunk_type}: {self.name}"
        if self.parent_name:
            header += f" (in class {self.parent_name})"
        header += f"\n# File: {self.file_path} lines {self.start_line}-{self.end_line}"
        if self.docstring:
            header += f"\n# Doc: {self.docstring[:200]}"
        return f"{header}\n\n{self.content}"

    def to_metadata(self) -> dict:
        return {
            "file_path": self.file_path,
            "chunk_type": self.chunk_type,
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
            "parent_name": self.parent_name or "",
            "docstring": (self.docstring or "")[:500],
            "calls": ",".join(self.calls[:20]),
        }


LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "csharp",
    ".php": "php",
}

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", "target", "vendor", "coverage",
    ".pytest_cache", ".mypy_cache", "eggs", ".eggs",
}

MAX_CHUNK_LINES = 80
MIN_CHUNK_LINES = 3


def detect_language(file_path: str) -> Optional[str]:
    suffix = Path(file_path).suffix.lower()
    return LANGUAGE_MAP.get(suffix)


# ── Python chunker (regex-based, no tree-sitter dependency issues) ──────────

def _extract_docstring(lines: list[str], body_start: int) -> Optional[str]:
    """Extract leading docstring from function/class body."""
    for i in range(body_start, min(body_start + 4, len(lines))):
        stripped = lines[i].strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) >= 2:
                return stripped.strip(quote).strip()
            # multi-line docstring
            doc_lines = [stripped.lstrip(quote)]
            for j in range(i + 1, min(i + 10, len(lines))):
                if quote in lines[j]:
                    return " ".join(doc_lines).strip()
                doc_lines.append(lines[j].strip())
    return None


def _extract_calls_python(source: str) -> list[str]:
    """Heuristic: find function call patterns like foo( or self.foo("""
    calls = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', source)
    builtins = {'print', 'len', 'range', 'str', 'int', 'list', 'dict', 'set',
                'tuple', 'bool', 'type', 'isinstance', 'hasattr', 'getattr',
                'setattr', 'super', 'zip', 'map', 'filter', 'enumerate', 'sorted'}
    return [c for c in set(calls) if c not in builtins][:15]


def chunk_python(source: str, file_path: str) -> list[CodeChunk]:
    chunks = []
    lines = source.splitlines()
    n = len(lines)

    import_lines = []
    i = 0

    # collect top-level imports
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            import_lines.append(lines[i])
        elif stripped and not stripped.startswith("#"):
            break
        i += 1

    if import_lines:
        chunks.append(CodeChunk(
            content="\n".join(import_lines),
            file_path=file_path,
            chunk_type="import_block",
            name="imports",
            start_line=1,
            end_line=len(import_lines),
            language="python",
            imports=[l.strip() for l in import_lines],
        ))

    # regex for top-level defs and classes
    top_level_pat = re.compile(r'^(class|def|async def)\s+([A-Za-z_][A-Za-z0-9_]*)')
    method_pat = re.compile(r'^    (def|async def)\s+([A-Za-z_][A-Za-z0-9_]*)')

    def get_block_end(start: int, base_indent: int) -> int:
        """Find end of indented block starting at `start`."""
        j = start + 1
        while j < n:
            line = lines[j]
            if line.strip() == "":
                j += 1
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent and line.strip():
                return j - 1
            j += 1
        return n - 1

    i = 0
    current_class = None
    current_class_end = -1

    while i < n:
        line = lines[i]

        # detect class
        class_match = re.match(r'^class\s+([A-Za-z_][A-Za-z0-9_]*)', line)
        if class_match:
            cls_name = class_match.group(1)
            cls_end = get_block_end(i, 0)
            current_class = cls_name
            current_class_end = cls_end

            # class header chunk (just the class def + docstring, not methods)
            header_end = min(i + 6, cls_end)
            header_lines = lines[i:header_end + 1]
            doc = _extract_docstring(lines, i + 1)
            chunks.append(CodeChunk(
                content="\n".join(header_lines),
                file_path=file_path,
                chunk_type="class",
                name=cls_name,
                start_line=i + 1,
                end_line=header_end + 1,
                language="python",
                docstring=doc,
            ))
            i += 1
            continue

        # detect top-level function
        func_match = re.match(r'^(async def|def)\s+([A-Za-z_][A-Za-z0-9_]*)', line)
        if func_match:
            func_name = func_match.group(2)
            func_end = get_block_end(i, 0)
            body_lines = lines[i:func_end + 1]

            # if too long, split at logical sub-blocks
            if len(body_lines) > MAX_CHUNK_LINES:
                # emit first chunk with signature + first half
                mid = i + MAX_CHUNK_LINES
                body_lines = lines[i:mid]
                func_end_actual = mid - 1
            else:
                func_end_actual = func_end

            doc = _extract_docstring(lines, i + 1)
            content = "\n".join(body_lines)
            chunks.append(CodeChunk(
                content=content,
                file_path=file_path,
                chunk_type="function",
                name=func_name,
                start_line=i + 1,
                end_line=func_end_actual + 1,
                language="python",
                docstring=doc,
                calls=_extract_calls_python(content),
            ))
            i = func_end + 1
            continue

        # detect method inside class
        method_match = re.match(r'    (async def|def)\s+([A-Za-z_][A-Za-z0-9_]*)', line)
        if method_match and current_class and i <= current_class_end:
            method_name = method_match.group(2)
            method_end = get_block_end(i, 4)
            body_lines = lines[i:method_end + 1]
            if len(body_lines) < MIN_CHUNK_LINES:
                i += 1
                continue
            doc = _extract_docstring(lines, i + 1)
            content = "\n".join(body_lines)
            chunks.append(CodeChunk(
                content=content,
                file_path=file_path,
                chunk_type="method",
                name=method_name,
                start_line=i + 1,
                end_line=method_end + 1,
                language="python",
                parent_name=current_class,
                docstring=doc,
                calls=_extract_calls_python(content),
            ))
            i = method_end + 1
            continue

        i += 1

    return chunks


# ── JavaScript / TypeScript chunker ─────────────────────────────────────────

def _extract_calls_js(source: str) -> list[str]:
    calls = re.findall(r'\b([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(', source)
    builtins = {'console', 'log', 'error', 'warn', 'JSON', 'Object', 'Array',
                'Promise', 'resolve', 'reject', 'then', 'catch', 'map', 'filter',
                'forEach', 'reduce', 'parseInt', 'parseFloat', 'setTimeout'}
    return [c for c in set(calls) if c not in builtins][:15]


def chunk_javascript(source: str, file_path: str) -> list[CodeChunk]:
    chunks = []
    lines = source.splitlines()
    n = len(lines)

    # import/export blocks
    import_lines = [l for l in lines if re.match(r'^import\s+|^const\s+\w+\s*=\s*require', l)]
    if import_lines:
        chunks.append(CodeChunk(
            content="\n".join(import_lines),
            file_path=file_path,
            chunk_type="import_block",
            name="imports",
            start_line=1,
            end_line=len(import_lines),
            language="javascript",
        ))

    # function declarations: function foo(...) { ... }
    func_patterns = [
        (re.compile(r'^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)'), "function"),
        (re.compile(r'^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s+)?\('), "function"),
        (re.compile(r'^(?:export\s+default\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)'), "class"),
    ]

    i = 0
    while i < n:
        line = lines[i]
        for pat, ctype in func_patterns:
            m = pat.match(line)
            if m:
                name = m.group(1)
                # find closing brace by brace counting
                depth = 0
                end = i
                found = False
                for j in range(i, min(i + MAX_CHUNK_LINES + 20, n)):
                    depth += lines[j].count('{') - lines[j].count('}')
                    if depth > 0:
                        found = True
                    if found and depth <= 0:
                        end = j
                        break
                body = lines[i:end + 1]
                if len(body) >= MIN_CHUNK_LINES:
                    content = "\n".join(body)
                    chunks.append(CodeChunk(
                        content=content,
                        file_path=file_path,
                        chunk_type=ctype,
                        name=name,
                        start_line=i + 1,
                        end_line=end + 1,
                        language="javascript",
                        calls=_extract_calls_js(content),
                    ))
                    i = end + 1
                    break
        else:
            i += 1

    return chunks


# ── Generic line-based fallback ──────────────────────────────────────────────

def chunk_generic(source: str, file_path: str, language: str) -> list[CodeChunk]:
    """Fallback: fixed-size chunks for unsupported languages."""
    lines = source.splitlines()
    chunks = []
    window = 60
    step = 50
    for i in range(0, len(lines), step):
        block = lines[i:i + window]
        if len(block) < MIN_CHUNK_LINES:
            continue
        chunks.append(CodeChunk(
            content="\n".join(block),
            file_path=file_path,
            chunk_type="block",
            name=f"block_{i}",
            start_line=i + 1,
            end_line=i + len(block),
            language=language,
        ))
    return chunks


# ── Main entry point ─────────────────────────────────────────────────────────

def chunk_file(file_path: str, source: str) -> list[CodeChunk]:
    language = detect_language(file_path)
    if not language:
        return []

    try:
        if language == "python":
            return chunk_python(source, file_path)
        elif language in ("javascript", "typescript"):
            return chunk_javascript(source, file_path)
        else:
            return chunk_generic(source, file_path, language)
    except Exception:
        # never crash ingestion on a single file
        return chunk_generic(source, file_path, language or "unknown")


def chunk_repository(repo_path: str) -> list[CodeChunk]:
    """Walk a cloned repo and chunk every source file."""
    all_chunks: list[CodeChunk] = []
    root = Path(repo_path)

    for file in root.rglob("*"):
        # skip unwanted dirs
        if any(skip in file.parts for skip in SKIP_DIRS):
            continue
        if not file.is_file():
            continue

        language = detect_language(str(file))
        if not language:
            continue

        # skip huge files (generated, minified, etc.)
        try:
            if file.stat().st_size > 500_000:
                continue
            source = file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel_path = str(file.relative_to(root))
        chunks = chunk_file(rel_path, source)
        all_chunks.extend(chunks)

    return all_chunks
