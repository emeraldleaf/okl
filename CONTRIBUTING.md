# Contributing

Thanks for looking. This is a v0 project with one maintainer, so the most useful
contributions are small, verifiable, and self-contained.

## Setup

```bash
git clone https://github.com/emeraldleaf/okl && cd okl
pip install -e ".[dev]"
pytest -q          # must be green before and after your change
ruff check .
```

Try it end to end in a scratch directory before changing anything:

```bash
mkdir /tmp/try && cd /tmp/try && git init
okl init --repo try --interests security
okl seed
okl check --task "add an endpoint that returns an order for the logged-in user"
```

## The repo has rules about itself

Read [CLAUDE.md](CLAUDE.md) (identical to AGENTS.md) before a first PR. It is short, and
it is the actual contract. The parts that will fail your build if you miss them:

- **Mirror files are byte-identical.** `ci/okl-verify.yml`, `.github/workflows/okl-verify.yml`
  and `src/okl/scaffold/ci/okl-verify.yml` must match, as must `hooks/*.sh` and their
  `src/okl/scaffold/hooks/` twins. Edit one, copy to the others in the same change.
  `tests/test_scaffold.py::test_mirror_files_identical` enforces it.
- **The `okl-verify` check can fail on your PR, and that is not yours to fix.** CI reads
  the committed `okl-drift.json`: the rules that govern files, and when each was last
  verified. Change a governed file and CI names the rules that need re-checking. The
  store that can re-verify them is the maintainer's, not in the repo, so the maintainer
  re-runs each check and pushes the refreshed `okl-drift.json` to your branch. Leave
  "Allow edits by maintainers" on. Do not edit `okl-drift.json` by hand: an entry whose
  timestamp does not match its verification evidence is refused.
- **Maintainers: `okl drift` goes red when you change a file a stored rule governs.**
  That is the system working. Commit the change first, then re-verify with an actual
  check, `okl verify <id> --run "pytest -q -k <test>" --expect "passed"`, then commit
  the `okl-drift.json` that `okl verify` refreshed. Verifying before the code commit
  does not count: the commit is newer than the stamp, so the rule drifts again. Do not
  clear drift by re-recording with `--verified`; stamps come from observed runs.
- **Tags come from a closed vocabulary** (`store.KNOWN_TAGS`). Growing it is a deliberate
  edit to that set plus a note in the tags ADR, not an ad-hoc string.
- **Evaluation claims need a committed receipt.** If you change the harness or quote a
  number, the run that produced it belongs in `evals/results/`. Never cite a run the
  harness marked RESULTS NOT USABLE.

## What is most welcome

- **Bug reports with a reproduction.** Especially anything where the tool reports success
  it did not earn; that class of defect is the project's whole subject.
- **The open work in the store.** `okl check --task "improve retrieval precision"` will
  show you the recorded defects against the tool itself, including the briefing relevance
  cutoff that is still unfinished.
- **Portability fixes.** Hooks, path resolution, and CI have been exercised on macOS and
  GitHub Actions and nowhere else.
- **Hook wiring for another agent.** `okl init` auto-registers hooks for Claude Code
  only, so everywhere else the pre-task read is discretionary rather than enforced. The
  scripts in `src/okl/scaffold/hooks/` are plain bash reading JSON on stdin and writing
  the briefing to stdout; nothing in them is Claude-specific. What is missing is the
  per-agent registration, plus confirming the agent fires an event before the model reads
  the prompt (Codex CLI documents `userpromptsubmit`; OpenCode's plugin API appears to
  cover tool events but not pre-prompt, so there it may only ever be a tool call). A PR adding `okl init --agent <name>` for the tool you actually use
  daily would be the single most valuable contribution here. Bring evidence it fires: a
  behavioral check against a bare control repo, not just a log line, because a hook that
  fires is not a hook that is heard.

- **A live-Postgres test.** The ranked search path for Postgres is currently asserted at
  the SQL-shape level against a fake connection; it has never run against a real server.

## What is out of scope for now

Embedding or vector retrieval, unless one of the triggers in
[the flat-retrieval ADR](docs/decisions/2026-07-17-flat-retrieval-until-scale.md) has
actually fired and you bring the measurement showing it. The decision is falsifiable on
purpose; falsify it with data rather than preference.

## Pull requests

**Comment on the issue before you start.** It stops two people building the same thing,
and it gives me a chance to tell you what the issue does not say. A PR that arrives
without one is still welcome, but it may wait while I check it fits.

**If an AI tool wrote the change, say so,** and say which parts you checked yourself.
That is not a mark against it; most of this repository was written with one. It changes
how I review: generated changes tend to satisfy the letter of an issue and miss what only
the surrounding code shows. So before you open the PR, read the tests next to the code you
changed and follow their setup. For example, tests that drive the CLI clear
`OKL_DATABASE_URL` and `OKL_SERVICE_URL` first, because the CLI honours both and a test
that inherits them runs against the developer's own store instead of its temp directory.

Keep them single-purpose. Say what you changed and what you ran to check it, and include
the real output rather than a description of it. If your change surfaced something
non-obvious, record it in the store the way the repo records its own findings; a PR that
teaches the system something is worth more than one that only fixes code.

By contributing you agree your work is licensed under the repository's
[MIT License](LICENSE).
