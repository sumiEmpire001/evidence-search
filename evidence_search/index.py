"""Local full-text retrieval with revision-bound, verifiable quotations."""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Index:
    def __init__(self, path="evidence.db"):
        if str(path) == ":memory:":
            raise ValueError("Use a filesystem database")
        self.path = str(path)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, revision TEXT NOT NULL,
                    source TEXT NOT NULL, text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                    revision TEXT NOT NULL, first_line INTEGER NOT NULL,
                    last_line INTEGER NOT NULL, text TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                    text, chunk_id UNINDEXED, document_id UNINDEXED,
                    tokenize='unicode61'
                );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, document_id, text, *, title=None, source="local", lines_per_chunk=8):
        if not isinstance(document_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", document_id):
            raise ValueError("Document ID must be 1..80 letters, numbers, dots, underscores or hyphens")
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise ValueError("Document must contain nonempty text without NUL characters")
        if len(text.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Document exceeds 2 MiB")
        if type(lines_per_chunk) is not int or not 1 <= lines_per_chunk <= 100:
            raise ValueError("lines_per_chunk must be an integer from 1 to 100")
        if not isinstance(source, str) or not source or (title is not None and (not isinstance(title, str) or not title)):
            raise ValueError("Title and source must be nonempty strings")
        # Normalize line endings once, before revision hashing and citation offsets.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        revision = digest(text)
        lines = text.splitlines(keepends=True)
        chunks = []
        for offset in range(0, len(lines), lines_per_chunk):
            content = "".join(lines[offset:offset + lines_per_chunk])
            if not content.strip():
                continue
            first, last = offset + 1, min(len(lines), offset + lines_per_chunk)
            citation = f"{document_id}@{revision}:L{first}-L{last}"
            chunks.append((citation, document_id, revision, first, last, content))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM search WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
            db.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)", (document_id, title or document_id, revision, source, text))
            db.executemany("INSERT INTO chunks VALUES(?,?,?,?,?,?)", chunks)
            db.executemany("INSERT INTO search(text,chunk_id,document_id) VALUES(?,?,?)", [(c[5], c[0], c[1]) for c in chunks])
        return {"id": document_id, "revision": revision, "chunks": len(chunks)}

    def add_file(self, document_id, path, **options):
        file = Path(path)
        if file.suffix.lower() not in (".txt", ".md"):
            raise ValueError("Only UTF-8 .txt and .md files are supported")
        if file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Document exceeds 2 MiB")
        return self.add(document_id, file.read_text(encoding="utf-8"), source=str(file), **options)

    def delete(self, document_id):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            removed = db.execute("DELETE FROM documents WHERE id=?", (document_id,)).rowcount
            db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM search WHERE document_id=?", (document_id,))
            return bool(removed)

    def documents(self):
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT id,title,revision,source FROM documents ORDER BY id")]

    def search(self, query, *, limit=5, mode="all"):
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("Query must be a string of at most 1000 characters")
        if type(limit) is not int or not 1 <= limit <= 50 or mode not in ("all", "any"):
            raise ValueError("limit must be 1..50; mode must be all or any")
        terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)))
        if not terms:
            return []
        # Quoted lexical tokens prevent users from injecting FTS operators/syntax.
        expression = (" AND " if mode == "all" else " OR ").join('"' + term + '"' for term in terms)
        with self._db() as db:
            rows = db.execute("""SELECT c.id AS citation,c.document_id,c.revision,c.first_line,
                                 c.last_line,c.text,d.title,d.source,bm25(search) AS rank
                                 FROM search JOIN chunks c ON c.id=search.chunk_id
                                 JOIN documents d ON d.id=c.document_id AND d.revision=c.revision
                                 WHERE search MATCH ? ORDER BY rank,c.id LIMIT ?""", (expression, limit)).fetchall()
            return [dict(row) for row in rows]

    def answer(self, query, *, limit=3):
        results = self.search(query, limit=limit)
        # Return quotations, not fabricated abstractive answers or fake LLM output.
        return {"query": query, "mode": "extractive", "supported": bool(results),
                "excerpts": [{"citation": row["citation"], "quote": row["text"], "source": row["source"], "title": row["title"]} for row in results]}

    def verify(self, citation, quote):
        if not isinstance(citation, str) or not isinstance(quote, str) or not quote.strip():
            return False
        with self._db() as db:
            row = db.execute("""SELECT c.text FROM chunks c JOIN documents d
                                 ON c.document_id=d.id AND c.revision=d.revision WHERE c.id=?""", (citation,)).fetchone()
            return row is not None and quote in row["text"]

    def evaluate(self, cases, *, k=3):
        if not isinstance(cases, list) or not cases:
            raise ValueError("Evaluation requires a nonempty list")
        results = []
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("expected"), list) or not all(isinstance(x, str) for x in case["expected"]):
                raise ValueError("Each case requires query and expected document ID list")
            hits = self.search(case["query"], limit=k)
            expected = set(case["expected"])
            actual = {hit["document_id"] for hit in hits}
            passed = bool(expected & actual) if expected else not hits
            results.append({"query": case["query"], "expected": sorted(expected), "retrieved": sorted(actual), "passed": passed,
                            "citations_valid": all(self.verify(hit["citation"], hit["text"]) for hit in hits)})
        return {"k": k, "cases": results, "pass_rate": sum(row["passed"] for row in results) / len(results),
                "citations_valid": all(row["citations_valid"] for row in results)}
