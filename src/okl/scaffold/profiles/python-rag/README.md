# Python RAG / agentic profile

Canon extracted from the RAG service (`FastAPI / Qdrant hybrid / Redis / Postgres / Ollama / deepeval`).
Installed to `.claude/rules/`:

- `rag-pipeline.md` — retrieval-vs-identity (index & pre-filter, GROUP BY ≠ similarity), eval integrity (failure-count-first, judge≠generator, cross-tab, real fixtures), the read-only agent contract, embedder-not-hot-swappable
- `fastapi-backend.md` — async event-loop discipline (no sync/CPU work on the loop), middleware order & auth, streaming scrub-before-emit, one-orchestrator-per-pipeline, config through the settings layer
- `project-structure.md` — one-way app→library dependency, install-as-package (no sys.path hacks), extras for heavy deps, CLI/composition-root hygiene

Note: the RAG service ships a React UI, but its own canon (docs/) contains no stated frontend rule set —
so this profile ports backend + library rules only. React rules live in the separate, backend-agnostic
`react` profile — stack it on if your repo has a React frontend:
`okl scaffold --profile python-rag --profile react`.
