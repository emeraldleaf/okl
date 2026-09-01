# Changelog

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
