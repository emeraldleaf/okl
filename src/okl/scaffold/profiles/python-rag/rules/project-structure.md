---
description: Python project structure — one-way dependency, packaging, CLI hygiene
paths: ["**/pyproject.toml", "**/Dockerfile*", "**/main.py", "**/src/**/*.py"]
---

# Project structure & packaging (Python)

> Ported from the RAG service docs/project-structure.md + code-review.md cross-cutting findings.

## One dependency direction, installed as a package

- **The app imports the library; the library never imports the app.** Two Python roots, one direction:
  the reusable library in `src/<pkg>/`, the app in `app/` consuming it as an *installed* package.
- **Install the library as a package — no `sys.path`/`PYTHONPATH` hacks** (Dockerfile:74: the library was never installed, just path-hacked via `PYTHONPATH=/app/src` with dependencies hand-mirrored in `requirements.txt`, so the two manifests drifted; rag_pipeline.py:36: a `sys.path` hack counted two `..` hops too many and pointed at a directory that never existed — dead code documenting a false import mechanism). `pip install .` against a curated manifest, no path edits.
- **Heavy optional capabilities live behind extras** (pyproject.toml:20: the library declared streamlit, deepeval, docling, sentence-transformers, pytesseract, langchain as *mandatory* core deps though they serve only CLI/eval/dashboard paths — making the package uninstallable in a lean backend and forcing the `requirements.txt` workaround). Keep `pip install .` lean; gate the rest behind `[ingestion]`, `[eval]`, `[dashboard]` extras.

## Organize by seam, not concern-per-folder

- Feature/service code stays adjacent by seam so a change to a provider Protocol and its consumers is one directory away, not six. Every standard concern (app shell, agent core, memory, routing, security, eval, observability, deploy) has exactly one home.
- Deliberate deviations are allowed and documented (no agent-framework folder when the loop is ~200 explicit lines; no vendor security wrapper when the harness is in-repo and readable).

## CLI / composition-root hygiene

- **Consistent embedder defaults across commands** (main.py:551: `ingest` defaulted to `--embedder openai` (1536-dim) but `query` defaulted to `--embedder voyage` (1024-dim), so the documented happy path broke).
- **Don't ship dead course/tutorial artifacts as commands** (main.py:1318: 8 of 16 CLI commands were course-week artifacts whose default paths didn't exist; main.py:1 tutorial narration was ~1/3 of the file, burying the signal).
- **Fail the same way on the same bad input** (main.py:567: `query` silently swallowed an invalid `--embedder` (`except ValueError: pass`) and proceeded with a None dimension while `ingest` hard-failed on the same input).
- **Never rewrite a data file in place with a plain `open('w')`** (main.py:472: `dedup --apply` rewrote `documents.jsonl` in place, so a crash mid-write destroyed the processed corpus). Write to a temp file and atomically rename.
- **Business logic belongs in a service, not the composition root** (main.py:1133: `eval-pairwise`/`build-golden-dataset` embedded prompt templates, dual LLM clients, and regex JSON parsing inside the CLI entrypoint, contradicting the file's own stated design; Qdrant payload-index creation was inlined in the ingest handler instead of the infrastructure layer).
