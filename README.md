# EvidenceSearch

Local document ingestion and full-text retrieval with **revision-bound source citations**, exact quotations, deletion and a repeatable evaluation harness. Built for Lord_Sumi's portfolio.

This is a provider-free retrieval baseline. It returns extractive answers, not generated prose. There is no LLM subscription, remote embedding API or claim that quotations establish truth.

## Run

Python 3.10+ with SQLite FTS5 support is required. Most standard Python distributions include FTS5. Runtime dependencies: standard library only.

```bash
git clone https://github.com/sumiEmpire001/evidence-search.git
cd evidence-search
python -m evidence_search --db demo.db add queue examples/queue.md
python -m evidence_search --db demo.db add sensor examples/sensor.md
python -m evidence_search --db demo.db search "leases"
python -m evidence_search --db demo.db answer "calibration"
python -m evidence_search --db demo.db evaluate examples/evaluation.json
python -m unittest discover -s tests -v
```

The sample documents are synthetic. Their four evaluation cases should report `pass_rate: 1.0` and valid citations; this tiny fixture is a reproducible smoke evaluation, not a real-world quality benchmark.

```bash
python -m evidence_search --db demo.db documents
python -m evidence_search --db demo.db delete sensor
```

All data stays in your chosen local SQLite database. Deletion removes the document from active document records, chunk records and search results. It does not guarantee forensic erasure of freed SQLite pages or backups.

## Citation contract

Each citation has the form `document-id@FULL_SHA256:Lfirst-Llast`. The hash identifies normalized UTF-8 content. CRLF and CR are normalized to LF before hashing. Line numbers are one-based and inclusive. Chunk quotations preserve their normalized text and line boundaries.

Replacing a document atomically replaces its indexed chunks. A citation to an older revision stops verifying once that document changes. Exact repeated ingestion does not duplicate search results. Citation IDs are chunk identifiers; their format alone is not proof of authenticity.

## Python API

```python
from evidence_search import Index

index = Index("notes.db")
index.add("handbook", "Workers renew leases.\nFailed work retries.", lines_per_chunk=1)
hit = index.search("leases")[0]
assert index.verify(hit["citation"], hit["text"])
assert not index.verify(hit["citation"], "A fabricated statement")
answer = index.answer("leases")
assert answer["supported"]
```

`search` uses all query terms by default; use `mode="any"` in the library for broad matching. Results use SQLite BM25 ranking with a stable citation-ID tie-breaker. No synonym expansion, semantic embeddings or claim inference are performed. Empty retrieval returns `supported: false` and no excerpts.

## Architecture

- `documents`: current document title, source label, normalized text and full revision hash.
- `chunks`: fixed line windows and exact source locations.
- `search`: SQLite FTS5 lexical index referencing active chunks.
- Write transactions replace all three representations together. Read results join on the current revision.
- Query text is tokenized into quoted lexical tokens, so FTS operators cannot be injected through a query.
- `verify` checks the active source revision and exact quotation membership. It establishes provenance to local content, not factual correctness.
- `evaluate` checks expected document retrieval within top-k and verifies every returned citation. An expected empty list explicitly represents a no-answer case.

## Verification

Local checks on 30 October 2026: **14 tests passed**. Cases cover concurrent revision replacement, restart persistence, deduplication, deletion, stale citations, fabricated quotes, Unicode, line endings, FTS syntax inputs, result limits, expected empty retrieval and source-location accuracy. GitHub Actions is configured for Python 3.10, 3.12 and 3.13; remote results are tracked separately.

## Limitations

UTF-8 `.txt` and `.md` input only, up to 2 MiB per document. No PDF parser, OCR, browser fetching, access-control system, encryption, secure erasure, hosted API or live AI integration. The database may contain sensitive source text and local source labels; protect it accordingly. Fixed line chunks can split related passages, and all-term lexical matching can miss paraphrases. The same content re-chunked under a different window may have different valid chunk IDs. Document IDs must be 1..80 letters, numbers, dots, underscores or hyphens and start with a letter or number.

MIT license; see [LICENSE](LICENSE).
