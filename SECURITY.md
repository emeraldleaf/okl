# Security

## Reporting a vulnerability

Please report privately via GitHub's **Report a vulnerability** button on the
[Security tab](https://github.com/emeraldleaf/okl/security), not in a public issue.
Expect an acknowledgement within a week. This is a v0 project maintained by one person;
fixes are best-effort, and the honest expectation is a patch release or a documented
mitigation, not a same-day turnaround.

Supported: the latest release (currently `0.8.x`). Older versions get nothing.

## What this software does that you should know about

Three behaviors are deliberate, not bugs. If any of them is wrong for your environment,
that is a configuration decision you need to make before deploying.

### 1. The shared service is open without a token

Without `OKL_TOKEN`, **every route is open**, reads and writes alike, to anyone who can
reach the port. `/nodes` returns the entire store in one request. With `OKL_TOKEN` set,
every route except `/health` requires `Authorization: Bearer <token>`, and the
`/openapi.json`, `/docs` and `/redoc` routes are switched off. `/health` stays open for
load balancers; it returns a record count and a backend name, never record content.

That matters because of what a mature store contains: your defect history, the security
mistakes you have already made, internal architecture decisions, retired identifiers,
and the shape of your systems. **Treat the store as sensitive** and assume anyone who
holds the token (or, without one, anyone who can reach the port) can read all of it.

`okl serve` binds `0.0.0.0` by default, so a container's port is reachable from outside
it. Without `OKL_TOKEN` it refuses to start on any address but loopback, unless you pass
`--allow-no-token` or set `OKL_ALLOW_NO_TOKEN=1`: either opens the store on whatever
address it binds. For local use, bind it to loopback: `okl serve --host 127.0.0.1`.
`uvicorn okl.service:app` cannot see its address, so with no token it refuses on any
address unless `OKL_ALLOW_NO_TOKEN=1` is set. Started open either way, the service logs a
warning that every route is open.

The write routes trust the caller as far as the token does. `POST /verify` records
whatever evidence string it is sent (nothing is executed server-side), and
`POST /record` accepts `verified: true` so imports can carry their stamps. On a shared
deployment without a token, anyone who can reach the port can mark any rule verified.

If you deploy it beyond localhost:

- put it behind a reverse proxy that enforces authentication on every route, or bind it
  to a private network;
- terminate TLS upstream (the app speaks plain HTTP and has no certificate handling);
- set `OKL_TOKEN` on any shared deployment, so no route but `/health` is open;
- expect no rate limiting, no audit log of reads, and no per-user access control.

### 2. `okl verify --run` executes a shell command by design

The verification command runs whatever you pass to `--run` through a shell, reads the
real exit status, and records the command as evidence. That is the feature: verification
must come from an executed check. It also means **never pass untrusted input to
`--run`**, and never wire it to a command built from unreviewed data.

Two commands run those recorded commands again, and on a shared store other people may have
recorded them. `okl reverify` lists them and runs them only after you confirm, or with
`--yes`. `okl on-edit add <id>` shows a lesson's command and, once you approve it, runs it
**unattended after every edit your agent makes to a file that lesson governs**, until you
`okl on-edit remove` it. An approval is pinned to the exact command and its expected signal,
so a command that changes in the store afterwards does not run until you approve it again,
and okl refuses to show for approval any command, signal, title or file list holding a
character a terminal can hide. Approve only commands you would run yourself, that finish in
seconds and need nothing but the checkout.

### 3. The hooks execute scripts from your repository

`okl init` installs shell hooks into `.claude/hooks/` and registers them. They run
whenever your agent runs; the one after an edit runs the commands you approved with
`okl on-edit add`, and nothing until you approve one. In a git repository it also installs a pre-push hook (in
`.git/hooks/` or your `core.hooksPath`) that runs on every push, from any git client, and
executes the okl named by `OKL_BIN` or `.okl/config.json`. Read them before installing, the same as any other hook, and
review changes to them the same way you would review CI configuration.

## What ships in the package

The published distribution includes seed data: real engineering rules, architecture
decisions, and defect classes from the author's own projects, with project identities
genericized. It contains no credentials, no customer data, and no third-party code.
The scaffold deliberately does not vendor other people's skills; see
`RECOMMENDED-COMPANIONS.md` in the kit for what it points at instead.
