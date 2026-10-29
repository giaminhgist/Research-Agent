"""Searchable knowledge base: global (~/.research-agent/knowledge) and per project (.research-agent/kb + research-wiki).

Search uses SQLite FTS5 with bm25 ranking (falls back to LIKE if FTS5 is unavailable). Indexes update
incrementally by file mtime. A search never opens another project's index. Project items reach the global
knowledge base only through `promote(..., approved=True)`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter, paths, trace

STOPWORDS = {"a", "an", "the", "on", "of", "for", "in", "to", "and", "with", "via", "towards", "toward", "from", "by", "at", "is", "are"}


@dataclass
class Hit:
    scope: str
    path: Path
    title: str
    snippet: str
    score: float


# ---- locations ---------------------------------------------------------------------------------------------------
def global_dir() -> Path:
    return paths.ra_home() / "knowledge"


def project_dir(project: Path) -> Path:
    return paths.state_dir(project) / "kb"


def _roots(scope: str, project: Path | None) -> tuple[list[Path], Path]:
    if scope == "global":
        g = global_dir()
        return [g / "papers", g / "notes", g / "promoted"], g / ".index.sqlite"
    p = project_dir(project)
    return [p / "papers", p / "notes", Path(project) / "research-wiki"], p / ".index.sqlite"


# ---- papers ------------------------------------------------------------------------------------------------------
def _ascii(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _family_name(author: str) -> str:
    author = author.strip()
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = author.split()
    if not parts:
        return "anon"
    # "Nguyen Van A": a trailing initial means family-name-first order.
    return parts[0] if len(parts[-1].rstrip(".")) <= 1 and len(parts) > 1 else parts[-1]


def paper_slug(meta: dict) -> str:
    if meta.get("key"):
        return str(meta["key"])
    authors = meta.get("authors") or ["anon"]
    last = re.sub(r"[^a-z]", "", _ascii(_family_name(str(authors[0]))).lower()) or "anon"
    words = [re.sub(r"[^a-z0-9]", "", w) for w in _ascii(str(meta.get("title", ""))).lower().split()]
    word = next((w for w in words if w and w not in STOPWORDS), "untitled")
    return f"{last}{meta.get('year', '')}_{word}"


def _bibtex(slug: str, meta: dict) -> str:
    fields = {"title": meta.get("title"), "author": " and ".join(meta.get("authors", [])), "year": meta.get("year"),
              "journal": meta.get("venue"), "doi": meta.get("doi"), "eprint": meta.get("arxiv"), "url": meta.get("url")}
    if meta.get("arxiv"):
        fields["archiveprefix"] = "arXiv"
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@article{{{slug},\n{body}\n}}\n"


def _yaml_list(xs) -> str:
    return "[" + ", ".join(json.dumps(str(x), ensure_ascii=False) for x in xs) + "]"


def add_paper(meta: dict, body: str, scope: str, project: Path | None) -> Path:
    if scope not in ("project", "global"):
        raise ValueError("scope must be 'project' or 'global'")
    if scope == "project" and project is None:
        raise ValueError("project scope needs a project")
    base = global_dir() if scope == "global" else project_dir(project)
    slug = paper_slug(meta)
    fm = ["---", f"title: {json.dumps(str(meta.get('title', '')), ensure_ascii=False)}", f"slug: {slug}",
          f"authors: {_yaml_list(meta.get('authors', []))}", f"year: {meta.get('year', '')}"]
    for k in ("venue", "doi", "arxiv", "url"):
        if meta.get(k):
            fm.append(f"{k}: {json.dumps(str(meta[k]), ensure_ascii=False)}")
    fm += [f"tags: {_yaml_list(meta.get('tags', []))}", f"added: {time.strftime('%Y-%m-%d')}", "---", ""]
    text = "\n".join(fm) + f"# {meta.get('title', slug)}\n\n" + (meta.get("summary", "") + "\n\n" if meta.get("summary") else "") + body.strip() + "\n"
    out = base / "papers" / f"{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    bib = base / "library.bib"
    existing = bib.read_text(encoding="utf-8") if bib.is_file() else ""
    if f"{{{slug}," not in existing:
        with bib.open("a", encoding="utf-8") as fh:
            fh.write(_bibtex(slug, meta) + "\n")
    return out


def bib_keys(project: Path | None) -> set[str]:
    keys: set[str] = set()
    bases = [global_dir()] + ([project_dir(project)] if project else [])
    for base in bases:
        bib = base / "library.bib"
        if bib.is_file():
            keys |= set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib.read_text(encoding="utf-8", errors="replace")))
        for sub in ("papers", "notes", "promoted"):
            keys |= {p.stem for p in (base / sub).rglob("*.md")} if (base / sub).is_dir() else set()
    if project:
        for bib in Path(project).rglob("*.bib"):
            if paths.STATE_DIRNAME in bib.parts or ".git" in bib.parts:
                continue
            keys |= set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib.read_text(encoding="utf-8", errors="replace")))
        wiki = Path(project) / "research-wiki"
        if wiki.is_dir():
            keys |= {p.stem for p in wiki.rglob("*.md")}
    return keys


# ---- index & search ------------------------------------------------------------------------------------------------
def _connect(db: Path) -> tuple[sqlite3.Connection, bool]:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL)")
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2')")
        return con, True
    except sqlite3.OperationalError:
        con.execute("CREATE TABLE IF NOT EXISTS docs(path TEXT, title TEXT, body TEXT)")
        return con, False


def _title(text: str, path: Path) -> str:
    meta, body = frontmatter.parse(text)
    if meta.get("title"):
        return str(meta["title"])
    m = re.search(r"^#\s+(.+)$", body, re.M)
    return m.group(1).strip() if m else path.stem


def index(scope: str, project: Path | None) -> int:
    roots, db = _roots(scope, project)
    con, _ = _connect(db)
    seen: dict[str, float] = {}
    for r in roots:
        if r.is_dir():
            for f in r.rglob("*.md"):
                seen[str(f)] = f.stat().st_mtime
    known = dict(con.execute("SELECT path, mtime FROM files"))
    changed = 0
    for p in set(known) - set(seen):
        con.execute("DELETE FROM docs WHERE path = ?", (p,))
        con.execute("DELETE FROM files WHERE path = ?", (p,))
        changed += 1
    for p, mt in seen.items():
        if known.get(p) == mt:
            continue
        text = Path(p).read_text(encoding="utf-8", errors="replace")
        con.execute("DELETE FROM docs WHERE path = ?", (p,))
        con.execute("INSERT INTO docs(path, title, body) VALUES (?, ?, ?)", (p, _title(text, Path(p)), text))
        con.execute("INSERT OR REPLACE INTO files(path, mtime) VALUES (?, ?)", (p, mt))
        changed += 1
    con.commit()
    con.close()
    return changed


def _search_one(scope: str, project: Path | None, query: str, limit: int) -> list[Hit]:
    index(scope, project)
    _, db = _roots(scope, project)
    con, fts = _connect(db)
    toks = re.findall(r"\w+", query, re.UNICODE)
    if not toks:
        return []
    rows = []
    try:
        if fts:
            for joiner in (" ", " OR "):
                q = joiner.join(f'"{t}"' for t in toks)
                rows = con.execute(
                    "SELECT path, title, snippet(docs, 2, '[', ']', '…', 12), bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
                    (q, limit)).fetchall()
                if rows:
                    break
        else:
            like = f"%{toks[0]}%"
            rows = [(p, t, b[:160], 0.0) for p, t, b in con.execute(
                "SELECT path, title, body FROM docs WHERE body LIKE ? OR title LIKE ? LIMIT ?", (like, like, limit))]
    finally:
        con.close()
    return [Hit(scope, Path(p), t, s.replace("\n", " "), -float(score)) for p, t, s, score in rows]


def search(query: str, project: Path | None, scope: str = "all", limit: int = 10) -> list[Hit]:
    scopes = {"all": ["project", "global"], "project": ["project"], "global": ["global"]}[scope]
    hits: list[Hit] = []
    for sc in scopes:
        if sc == "project" and project is None:
            continue
        hits += _search_one(sc, project, query, limit)
    return sorted(hits, key=lambda h: -h.score)[:limit]


# ---- promotion queue -----------------------------------------------------------------------------------------------
def _queue_file(project: Path) -> Path:
    return project_dir(project) / "promotion-queue.jsonl"


def _read_queue(project: Path) -> list[dict]:
    f = _queue_file(project)
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _write_queue(project: Path, items: list[dict]) -> None:
    f = _queue_file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")


def queue_candidates(project: Path, since: float | None = None, origin_agent: str | None = None) -> list[dict]:
    project = Path(project)
    sources = [(project_dir(project) / "papers", "paper"), (project_dir(project) / "notes", "note"),
               (project / "research-wiki" / "papers", "paper")]
    queue = _read_queue(project)
    queued_paths = {q["path"] for q in queue}
    g = global_dir()
    new = []
    for d, kind in sources:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if since is not None and f.stat().st_mtime <= since:
                continue
            if str(f) in queued_paths:
                continue
            if any((g / sub / f.name).exists() for sub in ("papers", "notes")):
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            item = {"id": hashlib.sha1(str(f).encode()).hexdigest()[:8], "path": str(f), "title": _title(text, f),
                    "kind": kind, "origin_agent": origin_agent, "ts": time.time(), "status": "queued"}
            new.append(item)
    if new:
        _write_queue(project, queue + new)
    marker = project_dir(project) / ".last_scan"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(time.time()), encoding="utf-8")
    return new


def last_scan(project: Path) -> float | None:
    try:
        return float((project_dir(project) / ".last_scan").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_queue(project: Path, status: str = "queued") -> list[dict]:
    return [q for q in _read_queue(project) if q.get("status") == status]


def _with_provenance(text: str, project: Path) -> str:
    extra = f"promoted_from: {Path(project).name}\npromoted_at: {time.strftime('%Y-%m-%d')}\n"
    if text.startswith("---"):
        nl = text.index("\n") + 1
        return text[:nl] + extra + text[nl:]
    return f"---\n{extra}---\n\n{text}"


def promote(project: Path, ids: list[str], approved: bool) -> list[Path]:
    if not approved:
        raise PermissionError("promotion to the global knowledge base needs the user's approval (--approved)")
    queue = _read_queue(project)
    g = global_dir()
    out = []
    proj_bib = project_dir(project) / "library.bib"
    proj_bib_text = proj_bib.read_text(encoding="utf-8") if proj_bib.is_file() else ""
    for item in queue:
        if item["id"] not in ids or item.get("status") != "queued":
            continue
        src = Path(item["path"])
        if not src.is_file():
            item["status"] = "missing"
            continue
        dest = g / ("papers" if item["kind"] == "paper" else "notes") / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_with_provenance(src.read_text(encoding="utf-8"), project), encoding="utf-8")
        m = re.search(r"@\w+\s*\{\s*" + re.escape(src.stem) + r"\s*,.*?\n\}\n", proj_bib_text, re.S)
        gbib = g / "library.bib"
        if m and f"{{{src.stem}," not in (gbib.read_text(encoding="utf-8") if gbib.is_file() else ""):
            with gbib.open("a", encoding="utf-8") as fh:
                fh.write(m.group(0) + "\n")
        item["status"] = "promoted"
        item["promoted_to"] = str(dest)
        out.append(dest)
    _write_queue(project, queue)
    if out:
        trace.append(project, "kb.promote", items=[str(p) for p in out])
    return out


def dismiss(project: Path, ids: list[str]) -> int:
    queue = _read_queue(project)
    n = 0
    for item in queue:
        if item["id"] in ids and item.get("status") == "queued":
            item["status"] = "dismissed"
            n += 1
    _write_queue(project, queue)
    return n
