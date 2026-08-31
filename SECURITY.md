# Security

## Reporting a vulnerability

Please report privately via GitHub's **Report a vulnerability** button on the
[Security tab](https://github.com/emeraldleaf/okl/security), not in a public issue.
Expect an acknowledgement within a week. This is a v0 project maintained by one person;
fixes are best-effort, and the honest expectation is a patch release or a documented
mitigation, not a same-day turnaround.

Supported: the latest `0.1.x` release. Older versions get nothing.

## What this software does that you should know about

Three behaviors are deliberate, not bugs. If any of them is wrong for your environment,
that is a configuration decision you need to make before deploying.

### 1. The shared service leaves reads unauthenticated by default

`okl serve` gates **writes** behind `OKL_TOKEN` when that variable is set. **Reads are
always open**: `/check`, `/search`, `/nodes`, `/metric/recurrence` and `/health` require
no credential. `/nodes` returns the entire store.

That matters because of what a mature store contains: your defect history, the security
mistakes you have already made, internal architecture decisions, retired identifiers,
and the shape of your systems. **Treat the store as sensitive** and assume anyone who
can reach the port can read all of it.

If you deploy it beyond localhost:

- put it behind a reverse proxy that enforces authentication on every route, or bind it
  to a private network;
- terminate TLS upstream (the app speaks plain HTTP and has no certificate handling);
- set `OKL_TOKEN` so writes are not anonymous;
- expect no rate limiting, no audit log of reads, and no per-user access control.

### 2. `okl verify --run` executes a shell command by design

The verification command runs whatever you pass to `--run` through a shell, reads the
real exit status, and records the command as evidence. That is the feature: verification
must come from an executed check. It also means **never pass untrusted input to
`--run`**, and never wire it to a command built from unreviewed data.

### 3. The hooks execute scripts from your repository

`okl init` installs shell hooks into `.claude/hooks/` and registers them. They run
whenever your agent runs. Read them before installing, the same as any other hook, and
review changes to them the same way you would review CI configuration.

## What ships in the package

The published distribution includes seed data: real engineering rules, architecture
decisions, and defect classes from the author's own projects, with project identities
genericized. It contains no credentials, no customer data, and no third-party code.
The scaffold deliberately does not vendor other people's skills; see
`RECOMMENDED-COMPANIONS.md` in the kit for what it points at instead.
