# Deploying the shared service

okl runs in two modes. **Local mode** keeps a SQLite file next to your config and needs
no deployment; it is the right choice for one person on one machine, and everything in
the README works there. **Shared mode** puts one service in front of one database so
that every repo, on every machine, reads and writes the same curated knowledge. This
document covers the second.

The reason to bother: a lesson recorded in one repo is worth something only if a
different repo, weeks later, is told about it before it makes the same mistake. That
cross-repo hop is the whole point of the layer, and it needs a shared store.

Every command below was run against a real Postgres and a real service while writing
this page. Where something is **not** verified, it says so.

---

## 1. A database

Postgres is the supported shared backend. The service selects it with one environment
variable and nothing else in the code changes:

```bash
export OKL_DATABASE_URL="postgresql://user:pass@host:5432/okl"
```

Any managed Postgres works — RDS, Cloud SQL, Neon, Supabase, Fly Postgres. The schema
is created on first connect; there is no migration step to run.

To try it locally first, a throwaway cluster in four commands:

```bash
initdb -D /tmp/oklpg/data -U okl --auth=trust
pg_ctl -D /tmp/oklpg/data -o "-p 55432 -k /tmp/oklpg -c listen_addresses=''" start
createdb -h /tmp/oklpg -p 55432 -U okl okltest
export OKL_TEST_POSTGRES_URL="postgresql://okl@/okltest?host=/tmp/oklpg&port=55432"
```

That last variable also switches on the backend-parity test, which loads one corpus into
both SQLite and Postgres and asserts they rank the same record first for the same query:

```bash
pytest -k postgres_matches
```

Run it when you change anything about retrieval. SQLite ranks with BM25 and Postgres with
`ts_rank`; they have diverged before, and the failure mode is quiet — a repo that moves to
the shared service silently gets worse retrieval than it had on a laptop. The test builds
its tables in a temporary schema and drops them afterwards, so it is safe to point at a
database that already has data, though pointing it at production is still a strange thing
to do.

## 2. A token

**Set `OKL_TOKEN`.** It is optional in the code and mandatory in practice:

```bash
export OKL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

With it set, every endpoint requires `Authorization: Bearer <token>` except `/health`.
Without it, every endpoint is open to anyone who can reach the port — including
`GET /nodes`, which returns the entire store in one request. A mature okl store is a
catalogue of your organization's known defects, its retired identifiers and its internal
architecture decisions. That is a map of where you are weak, and it is precisely the
material the layer exists to accumulate.

`/health` stays open deliberately: schedulers and load balancers probe it before they
hold any credential, and a service that cannot be health-checked never goes live. It
returns a record count and a backend name, never record content.

The token is a single shared secret with no per-repo scoping, rotation or audit trail.
That is honest for what this is. If you need more, put a real authenticating proxy in
front and leave `OKL_TOKEN` set underneath as defence in depth.

## 3. Run it

```bash
pip install "org-knowledge-layer[service]"
okl serve --port 8080                       # convenience wrapper
uvicorn okl.service:app --host 0.0.0.0 --port 8080   # standard ASGI entrypoint
```

Both work and serve the same app. Use the second one under a process manager or in a
container, since it is the form every platform's default start command takes.

Confirm it is up:

```bash
curl -s localhost:8080/health
# {"ok":true,"nodes":5,"backend":"postgresql"}
```

`backend` in that response is worth reading on every deploy. If it says `sqlite` when you
expected `postgresql`, `OKL_DATABASE_URL` did not reach the process, and the service is
happily serving an empty file-backed store that will vanish with the container.

## 4. Point repos at it

In each repo:

```bash
okl init --repo checkout-api
okl connect https://okl.internal --token "$OKL_TOKEN"
```

`connect` writes the URL and token to `.okl/config.json`, and okl drops a `.gitignore`
inside `.okl/` so that file is never committed. Prefer supplying the token through the
`OKL_TOKEN` environment variable in CI and shared machines; the config file is a
convenience for a developer laptop.

That is the whole client setup. From then on:

```bash
# in checkout-api
okl record --type Defect --scope org \
  --title "Refund amount trusted from the client body" \
  --symptom "a refund endpoint reads amount from the request" \
  --fix "look the original charge up server-side and refund that"

# later, in billing-worker — a different repo, a different machine
okl check --task "add an endpoint that issues a refund" --format actions
# OKL — 1 rule(s) apply before you start:
# - FIX: Refund amount trusted from the client body [when: a refund endpoint reads amount from the request]
#   -> look the original charge up server-side and refund that
```

Note the scope. `--scope org` is what makes a lesson cross repo boundaries; `--scope repo`
keeps it local to the repo that recorded it. Getting this wrong is the most common way a
shared store disappoints: everything is recorded, nothing propagates.

## 5. What failure looks like

The service being unreachable, or refusing your token, must never be reported as "no
rules apply". Silence and safety are indistinguishable to an agent, and only one of them
is safe. Both cases exit non-zero and say which is which:

```
$ okl check --task "issue a refund"          # no token
OKL REFUSED THE CHECK — refusing to report a clean check.
OKL service rejected the request (401): missing or bad bearer token

$ okl check --task "issue a refund"          # service down
OKL UNREACHABLE — refusing to report a clean check.
OKL service unreachable at http://okl.internal/check: ...
```

The pre-task hook and the CI verifier both treat a non-zero exit as a block. If you wrap
okl in your own tooling, do the same: a check that cannot run has not passed.

## Containers

**Not verified.** No Docker daemon was available where this was written, so the project
ships no Dockerfile rather than an untested one. The service is an ordinary ASGI app with
no filesystem state when `OKL_DATABASE_URL` points at Postgres, so a container is four
lines over `python:3.12-slim`: install `org-knowledge-layer[service]`, expose the port,
and run the `uvicorn okl.service:app` command above. Set `OKL_DATABASE_URL` and
`OKL_TOKEN` as secrets, and point the platform's health check at `/health`.

If you build one, a PR adding it — with the build running in CI, so the claim is backed
by something — is welcome.

## Cost of the shared mode

Worth stating plainly before you commit to it. One service and one database is one more
thing to run, monitor and back up, and okl gives you no operational tooling for any of
that. It has no migrations, no backup command, no per-repo access control and no audit
log. Local mode has none of those problems.

Move to shared mode when a second repo actually needs a first repo's lessons. Before
that, the file on your laptop is doing the same job with none of the operations.
