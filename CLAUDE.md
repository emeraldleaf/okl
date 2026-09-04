# okl — repo instructions

Read [evals/REPORT.md](evals/REPORT.md) before touching anything measurement-adjacent —
it is the most load-bearing document in the repo (method, results, threats to validity).

## The loop is LIVE in this repo

The hooks fire on your own session: `UserPromptSubmit` injects the store's briefing into
your context before you start; `Stop` blocks your first stop to ask what was learned.
Answer it honestly — record with a deliberate scope (`org` spreads to every repo,
`repo` stays local) and tags from the closed vocabulary in `store.KNOWN_TAGS`. Growing
that vocabulary is an edit to the set plus a note in the tags ADR, never an ad-hoc tag.

- **`applies_to` is where a lesson is TRUE; tags are where it was FOUND.** Leave it unset
  unless the lesson is false or meaningless off that stack — unset reaches every repo and
  is the safe default, while a wrong value hides the record silently. Never derive it from
  a tag: that is the reverted §4d defect, which measured worse than no filter at all.

- **Verification is evidence-based**: `okl verify <id> --run "<check>" --expect "<signal>"`.
  Never re-record with `--verified` to clear drift — run the check.
- **After changing files a rule governs, `okl drift` goes red on purpose.** Re-verify
  the affected nodes (their tests are usually the right `--run`) before finishing.
- The local store (`.okl/okl.db`, gitignored) should hold all 11 seed files plus
  recorded nodes; `okl seed seed/` loads the `*-defects.json` set, while
  `dotnet-{canon,decisions,review-surfaces}.json` and `frontend-canon.json` load explicitly.

## Commands

```bash
pytest -q                          # full suite; must be green before any commit
ruff check .                       # lint (config in pyproject.toml)
python3 evals/ab_harness.py --dry-run     # eval harness; see evals/README.md before running live
okl drift                          # rules whose governed source changed after verification
```

## Rules that are enforced (and why)

- **Mirror files are byte-identical, test-enforced**: `ci/okl-verify.yml` ==
  `.github/workflows/okl-verify.yml` == `src/okl/scaffold/ci/okl-verify.yml`,
  `hooks/*.sh` == `src/okl/scaffold/hooks/*.sh`, and
  `gates/*.sh` == `src/okl/scaffold/gates/*.sh`. The scaffold copies are what consumers
  receive; the repo copies are the dogfood. Edit ONE, copy to the others in the same
  change — `tests/test_scaffold.py::test_mirror_files_identical` fails otherwise.
- **ruff `E702` is ignored deliberately** (semicolon one-liners): the tests use a
  compact setup style throughout; re-enabling it is a repo-wide style decision, not a
  cleanup.
- **Audits read the repo, not the working tree**: any gate/check that scans content
  must scan `git ls-files` output (committed reality), never the dirty working tree —
  scanning the tree makes an uncommitted edit pass or fail an audit that main would
  answer differently. (Bit the .NET platform twice.)
- **Eval integrity**: the harness refuses judge==generator; never quote a number from a
  run marked RESULTS NOT USABLE; every cited figure needs a committed receipt in
  `evals/results/`.
- **The diagram and README move with the system**: they are drift-enrolled
  (`n_b550ba9c5c8a`). `docs/okl-sixth-surface.svg` is a *render* of the `.excalidraw`
  — if you edit the source, re-render or say loudly in the commit that the render is
  stale.

## Layout truth

`src/okl/` is the package (store/core/client/cli/service/mcp + scaffold templates);
`seed/` is the curated 161-node corpus (real lessons, real project names — deliberate);
`evals/` is the A/B harness and receipts; `docs/posts/` is the 3-part write-up;
`e2e/` (gitignored) holds scratch repos for end-to-end loop tests.

This file stays lean — always-on rules only. Everything conditionally relevant belongs
in the store, where the briefing selects it per task. If you're about to add a section
here, ask whether it should be an `okl record` instead. It usually should.
