# Changelog

## 0.4.0

### Behaviour changes worth reading before upgrading

- **Stack tags now filter exclusively.** A record naming a stack (`dotnet`, `react`,
  `geospatial`, `python`, `python-rag`) is only shown to a repo that declared that stack
  in its `interests`. Previously any shared tag let it through, so a rule tagged
  `dotnet,method` reached every repo interested in `method` — a subject 75 records carry.
  **If you declare `interests`, expect fewer records after upgrading.** That is the point,
  but it is a change in what your briefings contain. Repos that declare no interests are
  unaffected, and untagged records still always pass.
- **`symptom` and `fix` are now searchable.** They were not, which meant a record written
  the way the docs tell you to write it — short title, the distinguishing words in the
  symptom — could not be retrieved at all. Existing stores rebuild their index on first
  open; you do not need to re-record anything.

### Added

- **`okl dedup`** reports near-duplicate records for review. Lexical and explainable:
  per-field weighted Jaccard over title, symptom and fix, IDF-weighted from your own
  corpus. It never merges or drops anything — the measured score bands for true
  paraphrases and for distinct-but-related records overlap, so the call is a person's.
  The same check runs as an advisory when importing an agent-proposed pack.
- **`/seed-from-docs`** mines the specs, ADRs and rules files you already wrote into typed
  records. Built around one distinction: a record is a standing instruction that outlives
  the work item it came from, so "deep offsets use keyset pagination" belongs and "add
  pagination to /orders this sprint" does not.
- A pack declaring `_proposed_by` is refused unless every node carries a `found_by`
  citation, so the rule the seeding commands state is enforced at import rather than
  remembered by a reviewer.

### Fixed

- `Client._remote_url` validates the URL scheme once. A `service_url` from config could
  name `file://`, turning a remote read into a local file read.
- `OKLUnreachable` is now `OKLUnreachableError`, with the old name kept as an alias so
  existing `except` clauses still work.
- Drift timestamps are timezone-aware; `utcfromtimestamp` is deprecated from Python 3.12
  and returned a naive datetime that read as local time when compared across machines.

### Internal

- `_Backend` is a `typing.Protocol` whose docstring states the behavioural contract, with
  one conformance test both backends run — the defect it guards (Postgres satisfying every
  signature while running an unranked match) was invisible to signatures alone.
- mypy, and ruff widened from 6 rule families to 15 including security and complexity,
  both wired into CI alongside a secret scan, the method gates and a coverage floor.


## 0.3.1

### Security

- **Setting `OKL_TOKEN` now also removes `/openapi.json`, `/docs` and `/redoc`.** They
  were left serving 200 to anonymous callers by the 0.3.0 work that closed every data
  route, because FastAPI mounts them itself — they are not handlers, so the per-handler
  auth sweep could not reach them. They leak no records, but they publish the endpoint
  list, every schema, and which routes want a credential. With no token set the
  interactive docs remain available, since that case is a developer's laptop.

## 0.3.0

Everything here came from running three things that had been written but never
executed: the MCP server, the Postgres backend, and a deployment.

### Security

- **The service token now covers reads.** Previously `OKL_TOKEN` gated writes only, so
  an unauthenticated `GET /nodes` returned the entire store — every recorded defect,
  retired identifier and architecture decision. Every route now requires the token when
  it is set, except `/health`, which is left open for schedulers and returns no record
  content.
- **`okl connect --token` no longer commits your secret.** The token is stored in
  cleartext in `.okl/config.json`, and a comment claimed the directory was gitignored
  while nothing wrote a `.gitignore`. `okl init` and `okl connect` now write
  `.okl/.gitignore`.
- **A rejected check no longer reports success.** A 401 surfaced as `ValueError` rather
  than `OKLUnreachable`, so an unauthorized `okl check` exited 0 with a traceback — which
  a pre-task hook reads as "no rules apply". It now fails closed with exit 2, as does
  every other command, via a backstop in `main()`.

**Breaking:** if you run a service with `OKL_TOKEN` set, clients must upgrade too.
Clients older than 0.3.0 send no credential on `GET` requests and will get 401s from
`okl drift` and the recurrence metric. Upgrade the service and its clients together, or
unset `OKL_TOKEN` during the rollover.

### Fixed

- `uvicorn okl.service:app` served a module-level `None`: the process started, bound the
  port, passed a port-liveness check and returned 500 to every request. The app is now
  built lazily in a module `__getattr__`, so the standard ASGI entrypoint works while
  importing the module still does not touch the database.
- The MCP server could not start under `mcp` 2.x, which renamed `FastMCP` to
  `MCPServer` — and the error handler told you to install the extra you had just
  installed. Both names are tried, and the real import error is reported.
- Every MCP `okl_record` call with `scope="repo"` failed. The repo default used
  `setdefault`, which cannot replace an explicit `None`, and the MCP tools pass every
  field explicitly.
- MCP validation errors raised as an opaque "Error executing tool". They now return the
  complaint, so an agent that invents a tag is told the vocabulary.

### Added

- `docs/DEPLOY.md`: the shared-service deployment path, including a throwaway Postgres
  for trying it locally and what each failure mode looks like. Every command in it was
  run against a real Postgres and a real service.
- Tests covering the live MCP server, the ASGI entrypoint, service auth on reads, the
  fail-closed 401, and the config `.gitignore`.
- The Postgres/SQLite parity test now runs in a scratch schema it creates and drops. The
  first version opened with `DELETE FROM node` against whatever `OKL_TEST_POSTGRES_URL`
  pointed at, which would have destroyed the store of anyone who set it to their real
  service.

## 0.2.0 and earlier

See the git history.
