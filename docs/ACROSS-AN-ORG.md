# Across an org: packs, a ledger repo, and lessons re-proven where they land

Part of okl's documentation; the [README](../README.md) is the short version. Filling one
repo's store is [SEEDING.md](SEEDING.md); the shared service, for teams that want one store,
is in [SCAFFOLD.md](SCAFFOLD.md#run-the-shared-service). This page is the other way to run
okl across many repositories, and the one the design favours: lessons travel as files
through git, and every repo that loads one proves it again on its own code.

That last clause is the whole difference. Every agent vendor can now push an instruction
file to every repo in an organisation. None of them can show, in the receiving repo, that
what arrived is still true.

## The unit is a pack

A pack is a seed file: a JSON list of `org`-scoped lessons, each with its symptom, cause and
fix, its tags, a `found_by` naming where it was paid for, and, where it governs code, the
files and the check. The twelve bundled packs in [seed/](../seed/) are the worked example:
real, dated records from several production codebases. `okl seed <path>` imports one, and
running it again on the edited file updates the same rows; [SEEDING.md](SEEDING.md) lists
the two things a re-seed will not do.

## The ledger repo

One git repository holds the organisation's packs. A lesson enters it the way code does, as a
pull request: the diff shows the symptom, the fix and the check, and the reviewer's question
is whether the check would fail if the rule were broken. Merged, the lesson is a row in a
file with a history. A wrong lesson is retired in place with a reason and the id that
replaces it, so the row and its provenance stay; nothing is deleted from a pack.

A consuming repo declares what it cares about at init, `okl init --repo <name> --interests
<tags>`, then loads the packs it wants from a checkout of the ledger: `okl seed
<path-to-pack>`. Its store stays local (`.okl/okl.db`, gitignored), nothing in the loop calls
a service, and a repo that loads a pack it has no interest in simply fills its briefings with
noise, which is why `okl seed --all` is explicit on purpose.

## Re-proven where it lands

Imported records are briefed, not watched. The receiving repo gives a rule the files it
governs there and proves it with `okl verify <id> --run "<check>" --expect "<signal>"`. From
then on drift marks the lesson stale when those files move, the push gate holds until the
check passes again, and the briefing carries the verdict. The same pack row can be proven in
one repo, stale in a second and unwatched in a third, because the stamps live in each repo's
own `okl-drift.json`, not in the ledger. That is what "verified" means across an org: not
that the ledger reviewer believed it, but that this repo's check ran.

## Scope is the curation step

`org` for a lesson true in any repo, `repo` for one true only here, and `applies_to` left
unset unless the lesson is false or meaningless off a stack. The reason this is written down
is a measured mistake: in September 2026 applicability was derived from the tags that record
where a lesson was *found*. That hid 35 of 172 org records from one repo and measured worse
than no filter at all ([evals/REPORT.md](../evals/REPORT.md) §4d). It was reverted, and a tag
is never read as a scope again.

## What transfers

The research caught up with this in 2026: a cross-domain memory pool helps, the gain comes
from abstract insights and validation routines, and raw traces cause negative transfer
([RELATED-WORK.md](RELATED-WORK.md)). A pack row is therefore a Rule, a Decision, a Gate, or
a Defect with its cause, never a transcript of how it was found. okl's own measured figure is
a transfer result in the same sense: the eight A/B tasks are fresh code written from a task
prompt, the defect classes they invite were learned in other projects and arrive through six
of the twelve packs, and 78 of 186 unbriefed attempts repeated one against 13 of 188 briefed
(REPORT §5, finding 7). Measuring which lesson shapes transfer, and which do not, is #254.

## Hygiene, and what to watch

- An `org` lesson that names one repository's paths or project is the kind that transfers
  badly; reporting that rate per pack is tracked in #252, and a warning at `okl seed` time in #255.
- `okl dedup` reports the same lesson recorded twice across packs; give new lessons a stable
  `--id` so a re-record is refused rather than duplicated.
- `okl retire <id> --reason ... --by <new-id>` keeps the chain: the briefing drops the old row
  and the link to its replacement stays in the store.
- The briefing reaches Claude Code through a hook and any MCP agent through `okl_check`; the
  push gate and the CI workflow run the same checks whoever wrote the code. One pack, every
  agent, one set of receipts.
