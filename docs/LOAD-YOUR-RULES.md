# Load your rules, and keep them current

This guide is for a team adopting okl in a repository that already has written rules: a `CLAUDE.md` or `AGENTS.md`, architecture decision records (ADRs), a standards doc, specs. It covers four things:

- turning those rules into okl lessons your agent is briefed on;
- deciding which lessons to prove;
- keeping the lessons, the docs and the code comments in step as the code moves;
- sharing the lessons with teammates.

It assumes okl is installed and `okl init` has run in the repo ([Getting started](GETTING-STARTED.md), section 1). The commands match okl 0.8.7. Steps marked **Claude Code** need it. Everything else works with any agent, or with none.

## What okl does with your rules

okl does not read your docs and judge them. It does three things with a lesson:

- **It briefs it.** Before a task, okl picks the lessons that share words with the task and hands them to the agent.
- **It watches it**, if the lesson has `files`. A commit that changes any of those files re-opens the lesson. `okl drift` then lists the lesson, the pre-push hook blocks the push, and CI fails if you run the gate there.
- **It proves it**, if the lesson has a check. `okl verify` stamps the lesson only when the check passes, and `okl reverify` re-runs the check after a change.

A lesson with no `files` is only briefed. A lesson with `files` is only as good as its check. Most of this guide is about choosing which lessons get which.

## 1. Decide what goes where

| The material | Where it goes | Why |
|---|---|---|
| A rule every session needs, whatever the task; commands; "for X, read Y" pointers | the always-on file: `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/`, `.github/copilot-instructions.md` | it loads in full every session |
| A convention, a decision and its reason, or a mistake already made once, that matters for some tasks | okl, briefing only | the briefing picks it for the tasks it fits |
| A claim about specific code or a doc that nothing else checks | okl, with `files` and a check | a change to those files re-opens it until the check passes |
| Formatting, style, anything a test or CI step already enforces | the formatter, linter, test or CI check | it runs on every change; a lesson can only remind |
| A procedure: release, setup, migration | a skill, runbook or script | it is read whole and in order |
| Open work: tickets, milestones, a plan's steps | your issue tracker | work expires; a lesson outlives it |
| Secrets, credentials, personal data | nowhere near okl | lessons are copied into agent context |

If CI already runs the check for a rule, do not give its lesson `files`. CI is the enforcement, and a second gate on the same thing only adds re-checks. You can still record the lesson without `files` (as a `Gate`, when a check exists), so the briefing mentions it.

**Do not import:**

- tasks, dates, milestones and open questions from specs and plans. When a task has a lasting reason, keep the reason and drop the task.
- proposed or rejected ADRs as rules. A rejected option belongs in the reason of the accepted decision.
- superseded ADRs as live decisions (see step 6).
- style that a formatter or linter enforces, or a whole style guide.
- what the agent can read from the code: directory tours, dependency lists, file-by-file descriptions.
- generic advice any engineer already knows.
- okl's own templates. If `okl scaffold` wrote `AGENTS.md`, `CLAUDE.md` or `METHOD.md`, those files are okl's boilerplate, not your team's rules.
- rules okl already holds. `okl init` loaded starter lessons on web security, CI, docs and verification. Search before you add one: `okl search "order owner"`.

## 2. Get ready

**Know the repo's name.** `okl init --repo <name>` set it. It is the `"repo"` value in `.okl/config.json`. A lesson scoped to any other name is never briefed here.

**List what you have**, and note which agent already reads it:

| Kind | Where it usually lives |
|---|---|
| Always-on rules | `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/`, `.cursorrules`, `.github/copilot-instructions.md`, `.github/instructions/`, `GEMINI.md`, `.claude/rules/` |
| Decisions | `docs/adr/`, `docs/decisions/` |
| Standards | `CONTRIBUTING.md`, a standards or style doc, linter and CI config |
| Specs and plans | `docs/specs/`, design docs, the plan for current work |
| Mistakes already paid for | postmortems, runbooks, fix commits |

**Get the seeding prompt.** okl ships a prompt, `seed-from-docs`, that has an agent read these docs and write proposed lessons to a file. It imports nothing.

- **Claude Code with the okl plugin:** run `/seed-from-docs`.
- **Claude Code without the plugin:** `okl init` does not install the prompt. `okl scaffold .` does, but it also writes `AGENTS.md`, `CLAUDE.md`, `METHOD.md`, `docs/`, `gates/`, `registries/`, `evals/`, `ci/` and a CI workflow into your repo (it keeps files you already have unless you pass `--force`). To take only the prompt, scaffold into a scratch folder and copy it:

  ```bash
  okl scaffold /tmp/okl-kit          # writes template files there; touches no store
  mkdir -p .claude/commands
  cp /tmp/okl-kit/.claude/commands/seed-from-docs.md .claude/commands/
  ```

- **Any other agent (Cursor, Codex, Copilot, Gemini CLI, and others):** make the same scratch copy and tell the agent: *"Follow the instructions in /tmp/okl-kit/.claude/commands/seed-from-docs.md for this repository."* The file is plain Markdown. It also lives in the okl repository at `src/okl/scaffold/claude/commands/seed-from-docs.md`.
- **No agent:** write the file yourself in the format shown in step 4, or record lessons one at a time (end of step 3).

Everything after the proposal is a plain CLI command: `okl seed`, `okl retire`, `okl verify` and `okl drift`.

## 3. Propose lessons from your docs

Run the prompt. It works like this:

- It reads rules files first, then ADRs, specs, plans, runbooks and postmortems.
- It keeps the sentences that stay true after the work item closes, in the document's own words.
- Each record cites the line it came from, in `found_by`.
- It writes `okl-from-docs.json`.
- It reports what it read but did not record, and where two documents contradict each other.

Read that report. A contradiction is a place where your docs have already drifted.

The prompt does not cover everything this guide needs. Give the agent these extra instructions with it:

> Also:
> - Use `"scope": "repo"` on every record and leave out the `"repo"` field.
> - Read each ADR's status. Accepted: one `Decision`, with the reason and the rejected options. Proposed or rejected: no record. Superseded or deprecated: no record; name it in the body of the decision that replaced it.
> - Do not set `"status"`, `"verified"` or `"files"`.
> - To see the tags in use, run `okl seed` (it lists each bundled pack's tags) or `okl search '' --limit 200 --format json`. A new tag needs a `Vocabulary` record placed before the first record that uses it.
> - After the `path:line` in `found_by`, add the heading that line sits under.
> - Skip anything okl's own templates wrote: `METHOD.md`, and any `AGENTS.md` or `CLAUDE.md` that `okl scaffold` created.
> - If a lessons file already exists, keep the key of every record that is still true, and list the keys of records that are gone.
> - In your report, for each record about specific code, name the files it governs and a test or command that fails if the record is broken.

**Recording by hand instead.** Add one rule at a time, and cite its source:

```bash
okl record --type Decision --scope repo --id adr-0004-money-decimal \
  --title "Money is a Decimal, never a float or integer cents" \
  --body "why: <the ADR's reason, in its own words>. Replaces ADR 0002 (integer cents)." \
  --found-by "docs/adr/0004-money-decimal.md:9 (Decision)"
```

A lesson recorded this way lives only in your store. On a team, put it in the lessons file instead (step 10).

## 4. Review the proposal

This step is what makes the import worth trusting. For each record:

1. Open the `found_by` line. Delete the record if the line does not say what the record says.
2. Delete tasks, vague lines ("keep handlers thin"), and anything a linter or CI already enforces.
3. Delete lines that will stay in the always-on file (step 7).
4. Check for overlap with lessons already in the store: `okl search "<a few words>"`. Keep one copy.
5. Put the decision and its reason at the start of `body`. A briefing shows only the start of a long body.
6. Leave `applies_to` unset. It filters only org-scoped lessons, and a wrong value hides a lesson without warning.
7. Give every Rule, Defect and Gate a `symptom` in the words a developer uses when it bites ("users get logged out when they refresh", not "token storage"). A prompt that describes what went wrong reaches a lesson through its symptom, and a record without one is found only by a prompt that happens to use its title's words. `okl seed` warns when one is missing.
8. Add `aliases` where your team's words differ from the lesson's: the phrases a developer types when it bites (`"aliases": ["logged out on refresh", "session lost"]`). They are indexed like the symptom and count toward the line a lesson must clear (three shared subject words in its title, symptom, aliases and triggers, or two rare ones), so they are the cheapest way to make a lesson reachable from a bug report or a paraphrase (#258). Write them from the lesson, not from one prompt that missed.
9. Add `triggers`: three to ten whole phrasings of the moments the lesson applies (`"triggers": ["add a refresh-token flow to the SPA", "users get logged out after reloading the page"]`): the work a developer would be doing, what they would see once it went wrong, and the other words for it. The bundled packs carry ten per lesson, and the default briefing measured best with them (REPORT §4w); on a real store, recorded lessons without them were found far less (§4x). For lessons already in a store, `okl triggers` lists the ones that lack them and `/triggers` drafts them.

Then check the file as a whole:

- `"_proposed_by"` is still at the top. With it, `okl seed` refuses the whole file if any record lacks `found_by`.
- Every record has `"scope": "repo"`, or `"repo:<name>"` with exactly the name in `.okl/config.json`.
- No record has `"status"`. `okl seed` refuses `superseded` and `obsolete` (only `okl retire` sets them), and the import stops partway.
- No record has `"verified": true`. That stamps a lesson with no check behind it. On a lesson with `files`, it blocks your push and makes CI refuse the snapshot.
- Records use only these fields: `key`, `type`, `title`, `scope`, `repo`, `body`, `symptom`, `aliases`, `triggers`, `fix`, `tags`, `applies_to`, `files`, `found_by`, `owner`, `ttl_days`. Any other field, such as a check command, crashes the import partway.
- Every tag is known (see the extra instructions above).

Here is the format, with a new tag:

```json
{
  "_proposed_by": "seed-from-docs",
  "nodes": [
    {"key": "tag_payments", "type": "Vocabulary", "scope": "org", "title": "payments",
     "body": "lessons about how this service handles money",
     "found_by": "declared for docs/adr/0004-money-decimal.md"},
    {"key": "adr_0004_money_decimal", "type": "Decision", "scope": "repo", "tags": "payments",
     "title": "Money is a Decimal, never a float or integer cents",
     "body": "why: <the ADR's reason, in its own words>. Rejected: floats; integer cents (ADR 0002, replaced by this one).",
     "found_by": "docs/adr/0004-money-decimal.md:9 (Decision)"},
    {"key": "price_from_catalogue", "type": "Rule", "scope": "repo", "tags": "security",
     "title": "Prices come from the catalogue, never from the request body",
     "symptom": "a request model with a price, total or discount field",
     "fix": "drop the field; look the price up on the server",
     "found_by": "CLAUDE.md:33 (Orders)"}
  ],
  "edges": []
}
```

Edges are optional. Each one is `{"src": "<key>", "rel": "<RELATION>", "dst": "<key>"}`. Only `CATCHES` (a Gate catches a Defect) shows up in a briefing.

## 5. Import

**Name the file before the first import.** Each lesson's id is `seed:<file name without .json>:<key>`. Renaming the file or a key later creates new lessons and leaves the old ones in briefings. The seeding prompt always writes `okl-from-docs.json`, so running it again would overwrite your reviewed file. Pick a lasting name now:

```bash
mv okl-from-docs.json okl-lessons.json
okl seed okl-lessons.json        # ids: seed:okl-lessons:<key>
```

`okl seed <folder>` imports every `.json` file directly inside that folder. Give it the file, not `.`.

What you may see:

- **A warning on every record** saying the seed node has no `repo` and its provenance is recorded as unknown. The warning is wrong: the lesson is stored under this repo. Adding `"repo": "<name>"` to each record silences it.
- **"incoming record(s) resemble records already in the store".** On a first import, read these: they are possible duplicates. On later imports, every record also matches itself at 1.00. Ignore those matches.
- **An error.** Records before the bad one are already written; the rest of the records, and all edges, are not. Fix the file and run `okl seed` again. It updates the same lessons in place.

Then check what the agent will get:

```bash
okl show seed:okl-lessons:price_from_catalogue
okl check --task "let customers apply a discount code at checkout"
```

Try tasks written in your team's words, not the doc's words. The briefing matches shared words and does no stemming, so "rename" does not match "renaming". When a lesson you expected is missing, add your team's words to its `aliases` or `triggers` in the file, and run `okl seed` again.

## 6. ADRs, including superseded ones

- **Accepted:** one `Decision`. The title is the choice. The body starts with `why:`, then gives the reason, then the rejected options.
- **Proposed or rejected:** no record.
- **Superseded or deprecated:** no record of its own. Name it in the body of the decision that replaced it. This works in every clone that loads the file.

If a superseded ADR is already in your store, retire it in favour of its replacement:

```bash
okl retire seed:okl-lessons:adr_0002_money_cents \
  --by seed:okl-lessons:adr_0004_money_decimal \
  --reason "ADR 0004 supersedes ADR 0002"
```

Briefings then leave it out and print a one-line pointer to the replacement. Re-seeding keeps it retired. The retirement lives only in your store, so a fresh clone needs the same command (step 10). The replacement must have the same scope as the old lesson, or be `org`.

Two things look right but do not work:

- `"status": "superseded"` in the file. It is refused, and the import stops at that record.
- A `SUPERSEDES` edge in the file. The edge is stored, but both decisions stay in briefings.

When a new ADR replaces one you imported, add the new decision to the file, run `okl seed`, then run `okl retire <old> --by <new>`.

## 7. Settle the always-on file

Each rule should live in one place. In a trial run, `CLAUDE.md` still said "integer cents (see ADR 0002)" after ADR 0004 had replaced that decision. The seeding prompt flagged the contradiction; nothing would have caught it later.

- **Keep** in `CLAUDE.md` or `AGENTS.md`: rules every session needs, commands and pointers. With `okl scaffold`, a gate warns when `CLAUDE.md` passes 200 lines and fails above 300 (`gates/check-canon-size.sh`).
- **Remove** the lines that are now lessons. On a team, wait until every clone loads the lessons file (step 10). Until then, the always-on file is the only copy your teammates' agents see.
- **If you keep a line in both places**, add the rules file to that lesson's `files`, so an edit to the line re-opens the lesson.

**Other agents:** the briefing is not automatic. Add this line to `AGENTS.md` or `.cursor/rules/`: *"Before each task, call `okl_check` with the task description and follow what it returns. When we learn something worth keeping, record it with `okl_record`."* The `AGENTS.md` that `okl scaffold` writes does not contain this line.

## 8. Prove the lessons that govern code or docs

You do not need to prove every lesson. Prove them in this order:

1. lessons that `okl metric` lists as shown most often with no stored check;
2. lessons about mistakes already made, or costly ones;
3. doc claims nothing else checks: install steps, commands, flags, defaults, security statements.

For each one:

1. Find or write a check that fails when the lesson is broken. Commit it.
2. Add `files` to the record in `okl-lessons.json`. List the code the lesson governs, plus the doc it came from when it restates a doc. Then run `okl seed okl-lessons.json`.

   Include what the behaviour depends on, too: a caller whose contract the rule relies on, or the lockfile when a dependency's version matters. Drift re-opens a lesson only when one of its own `files` changes, so a rule broken from outside them (a caller changed, a dependency bumped) stays stamped until something else runs the check. Every file you add also means more re-checks, so list the inputs that matter, not the whole tree.
3. Prove it:

   ```bash
   okl verify seed:okl-lessons:adr_0003_problem_details \
     --run "pytest -q tests/test_errors.py" --expect "passed"
   ```

4. If CI reads `okl-drift.json`, commit it. `okl verify` refreshes it.

The commit order matters: the code first, then `okl verify`, then `okl-drift.json`. Verifying before the code commit leaves the lesson drifted.

Add `files` only when you are about to prove the lesson. A lesson with `files` and no proof counts as "never verified", and it blocks your push until its check passes.

`okl verify <id>` without `--run` lists tests that mention the governed files. Treat the list as a hint. It counts any path containing "test" or "spec", so it can suggest a Markdown spec and miss the real test.

Edit the file rather than running `okl update --files`. The next `okl seed` puts back the file's version of every field. A lesson whose `files` came only from `okl update` loses them, and its proof with them, and the gate then has nothing to check. `okl update` warns about this on a seeded lesson.

## 9. Keep lessons in step with their source docs

Where each thing lives:

- **The doc** (an ADR, a spec, `CONTRIBUTING.md`) records what was decided and why.
- **`okl-lessons.json`**, in git, holds the lesson text. Edit lessons there.
- **Your store** (`.okl/`, gitignored) is a local copy, plus your proofs.
- **`okl-drift.json`**, in git, is the copy of the proofs that CI reads.

**When a source doc changes:**

- **If the lesson's `files` include the doc,** drift flags the lesson once the change is committed. Read what changed before you prove it again:

  ```bash
  okl show seed:okl-lessons:adr_0003_problem_details   # prints "verified ... on commit <sha>"
  git diff <sha> HEAD -- docs/adr/0003-errors.md app/errors.py
  ```

  If the meaning changed, edit the lesson in the file (and the code), run `okl seed`, then `okl reverify`. If it did not, just run `okl reverify`.

  Be careful with `okl reverify`: it stamps whenever the check passes, and it never shows you the diff. In a trial run, two changes were re-stamped this way because the check tested neither: an ADR edit that renamed every error code, and a code comment that had been made false.
- **If the lesson has no `files`,** nothing tells you. Re-run the seeding prompt on the changed doc, and merge what is new into `okl-lessons.json` by hand, keeping existing keys.

**When a rule is removed from a doc**, delete it from the file and retire it. Deleting it from the file does not remove it from any store:

```bash
okl retire seed:okl-lessons:log_4xx_at_info --obsolete --reason "removed from CLAUDE.md"
```

`--obsolete` takes the lesson out of briefings. Without `--obsolete` or `--by`, a retired lesson counts as wrong and stays briefed as AVOID.

**Habits:**

- Correct lessons in the file, then re-seed. A re-seed rewrites every field the file sets. A field the file leaves out keeps the store's value, so `files` or triggers added with `okl update` stay.
- Never rename the file or a key.
- Line numbers in `found_by` go stale as the doc is edited. The heading you added after them helps a reviewer find the line.
- After you change a lesson's `files` and re-seed, run `okl reverify`: the re-seed cleared the lesson's stamp and kept its stored check. A re-seed never stamps a lesson, even when the file says `"verified": true`; only `okl verify` does.
- A bundled pack updated in a new okl release reaches your store only when you run `okl seed <pack>`. `okl init` seeds only an empty store.

## 10. On a team

The store is one gitignored file per clone. Three things follow:

- A teammate's clone has none of your lessons, proofs or retirements.
- No okl command writes a store's lessons out to a file.
- `okl-drift.json` is rebuilt from the store of whoever last ran `okl verify` or `okl reverify`. okl refuses to drop a rule the committed file holds and that store does not: the snapshot is not refreshed, and the rules are named, until that store holds them too. `okl export --drift --allow-shrink` drops them on purpose.

What works today, with no server: the lessons live in a file in git, reviewed by pull request like any other change, and each clone loads and proves them with a setup script.

1. Commit `okl-lessons.json`. New team lessons reach it by pull request and are reviewed like code.
2. Commit a script that loads the file, applies retirements and runs each check:

   ```bash
   #!/usr/bin/env bash
   # scripts/okl-setup.sh: load the team's lessons into this clone and prove them here.
   # Run after `okl init --repo <name>`, on a clean, committed tree.
   set -euo pipefail
   okl seed okl-lessons.json
   # Removed rules: retire them where this store holds them. A fresh clone never loaded
   # them, so skip only an id the store does not have; any other failure stops the script.
   retire_removed() { if okl show "$1" >/dev/null 2>&1; then okl retire "$@"; fi; }
   retire_removed seed:okl-lessons:log_4xx_at_info --obsolete --reason "removed from CLAUDE.md"
   okl verify seed:okl-lessons:order_owner_scope \
     --run "pytest -q tests/test_ownership.py" --expect "passed"
   okl verify seed:okl-lessons:adr_0003_problem_details \
     --run "pytest -q tests/test_errors.py" --expect "passed"
   ```

3. Every teammate runs `okl init --repo <the same name>`, then the script. Without the script, their pre-push hook blocks on lessons their store marks "never verified".
4. One person owns `okl-drift.json`, or each teammate runs the script before committing it.
5. A lesson someone records in their own store (with `okl record`, `okl_record` or the end-of-session question) reaches no one else. To share it, add it to the file under a new key, run `okl seed`, then retire the original: `okl retire <old-id> --by seed:okl-lessons:<key> --reason "moved to the team file"`.

**Across repositories.** An `org`-scoped lesson reaches another repo when that repo loads a file containing it with `okl seed`, as the bundled packs do. Keep org lessons in a file of their own and load it in each repo. Proof does not travel: each repo proves the lessons that govern its own files. An org lesson whose tags all fall outside a repo's interests is not briefed there. Run `okl check --task "..." --interests ""` to see whether that is the reason.

## 11. Keep the docs and code comments current

### A reminder is not a check

A lesson that says "keep the docs current" is briefing text. It is picked only when a task shares its words, and it detects nothing. In a trial run, okl's three starter lessons about docs were not shown in any of 22 briefings. That included the briefing for a rename that left stale mentions in a code comment, in `CLAUDE.md` and in an API doc.

### One claim, one rule, both files, one check

> A doc claim is a Rule that governs both the doc and the code it describes, verified by a check that fails if the claim is false. ([Getting started](GETTING-STARTED.md), section 3)

Example: the README says "20 orders per page by default". The check reads that number from the README and compares it with the code:

```python
# tests/test_readme_claims.py
import re
from pathlib import Path
from app import config

def test_readme_default_page_size_matches_the_code():
    m = re.search(r"(\d+) orders per page by default", Path("README.md").read_text())
    assert m, "README no longer states the default page size"
    assert int(m.group(1)) == config.PAGE_SIZE
```

```bash
okl record --type Rule --scope repo --id doc-readme-defaults \
  --title "README's default page size matches app/config.py" \
  --symptom "the README states a default the code no longer uses" \
  --fix "change README.md and app/config.py in the same commit, then okl reverify" \
  --files "README.md,app/config.py"
okl verify doc-readme-defaults --run "pytest -q tests/test_readme_claims.py" --expect "passed"
```

Now, changing the default in the code fails the check and blocks the push until the README agrees. On a team, put this record in `okl-lessons.json` instead of running `okl record`.

- **Test the claim, not the words.** Compare the doc's value with the code's value.
- **Keep the value out of the lesson's title.** A title that says "default is 20" goes stale itself, because the check reads the README, not the lesson.
- **A file is watched whole.** Every committed edit to it re-opens every lesson on it, typo fixes included. If one doc gathers many such re-checks, move the busy claims (setup steps, say) into a smaller file of their own.
- **Drift sees commits**, not your working tree. **Claude Code:** the end-of-session recap also names lessons whose governed files you changed but have not committed.

### Code comments

Nothing in okl reads a comment. Here is what you can do instead:

- **Move the claim into a test.** A test named for the claim fails when the claim stops being true. A comment does not.
- **Govern the file.** For a comment that states something the code must keep true, give a lesson `files` naming that source file, and a check that tests the behaviour. Any committed edit to the file then re-opens the lesson. Read the diff before you run `okl reverify` (step 9): a passing behaviour test does not prove the comment. A change in another file can also make the comment false, and okl misses it unless that file is in `files` too.
- **Docstrings:** structural checks (doctests, a docstring linter) belong to your stack's tools, run in CI.
- **Retired names:** use the tombstone gate, described next.

### Retired names and withdrawn claims (okl scaffold)

`okl scaffold` adds gates for CI. They are separate from okl's store: a `Tombstone` or `Retraction` lesson does not feed them, so add each entry to both places.

- **`registries/tombstones.txt`:** one retired identifier per line, then a TAB, the reason, another TAB and the date. If you use spaces instead of tabs, the whole line becomes the identifier and never matches.
  - `gates/check-tombstones.sh` fails when an identifier appears in a `.md`, `.py`, `.ts`, `.tsx`, `.cs`, `.yaml`, `.yml`, `.json` or `.sh` file, comments included.
  - Other file types (`.js`, `.go`, `.rs`, `.java`, `.rst`, `.toml` and more) are not scanned. Add `--include` lines to your copy of the script.
  - Only paths containing `registries/` are skipped, so a CHANGELOG or an old ADR that names the identifier fails too.
- **`registries/RETRACTIONS.md`:** a withdrawn claim, written in double quotes.
  - `gates/check-retractions.sh` fails when that exact text appears in a `.md` file.
  - It does not read code, comments or docstrings, and it misses a reworded claim.
  - It also reads quotes inside HTML comments, including the template's example.
- Both gates scan the working tree, untracked files included.
- Run them with `bash gates/run-gates.sh`. In CI, either `.github/workflows/method-gates.yml` (from `okl scaffold`) or the workflow from `okl init --ci` runs it when the script is present. The pre-push hook runs only `okl drift --gate`, not these gates.

## 12. Keep learning as you build

| When | Do |
|---|---|
| A new rule is decided | Record it (on a team, add it to `okl-lessons.json`). If it governs specific code, prove it. |
| A mistake happens | Record a `Defect` with the symptom you saw. If it happens again, write a test. |
| `okl drift` is red, or a push is blocked | Read the diff (step 9), then run `okl reverify`. If a check fails, fix the code, the doc or the lesson. |
| A test fails against a lesson | Decide which one is true, in the same change: fix the code, or update or retire the lesson (in the file too). |
| A doc changes and no lesson governs it | Ask whether a claim in it deserves a lesson with a check. |
| Every few weeks | Run `okl metric` (lessons never shown; unproven lessons shown most), `okl dedup` (near-duplicates) and `okl drift`. |

**Claude Code:** at the first stop of a session that changed files, a hook asks what was learned. It offers the session's failed commands as candidates. It also lists the lessons the session was briefed on and those whose governed files changed, with the update, retire and verify commands for each.

**Other agents:** there is no end-of-session question. Add this to the instruction file: *"Before you finish, if this task taught us something worth keeping, record it with `okl_record`. Run `okl drift` and report any lesson it lists."* Over MCP, okl offers `okl_check`, `okl_record`, `okl_update`, `okl_retire`, `okl_get` and `okl_search`. Seeding, verifying and drift are CLI commands the agent runs in a shell.

## 13. Worked example

This comes from a trial run of okl 0.8.7 on 2026-10-12, on a small FastAPI orders service. The repo had:

- a team `CLAUDE.md`;
- ADRs 0001 to 0004, where 0004 ("Money is a Decimal") superseded 0002 ("integer cents");
- a standards doc, a spec and a README.

The trial kept the file name `okl-from-docs.json`, so ids were `seed:okl-from-docs:<key>`.

1. `okl init --repo orders-api` loaded the starter lessons and the Python pack. It said nothing about the docs already in the repo.
2. An agent following the seeding prompt proposed 26 records. It flagged that `CLAUDE.md` still said "integer cents (see ADR 0002)".
3. Review kept 23. One record was merged into the ADR 0003 decision, one stayed in `CLAUDE.md` as always-on, and one was dropped as too vague. `okl seed` imported the 23.
4. Briefings found the team's rules when a task used the same words. They missed "support orders priced in Japanese yen" (neither money ADR came up) and a reworded ownership task.
5. ADR 0002 was briefed as a live decision despite a `SUPERSEDES` edge. Running `okl retire ... --by` with the ADR 0004 lesson replaced it with a one-line pointer.
6. The ownership rule got `files` (`app/main.py,app/store.py`), a new test and an `okl verify`. Then the owner check was removed from the code: drift flagged it, the push was blocked, and `okl reverify` refused to stamp.
7. The ADR 0003 lesson got `files` naming the ADR and `app/errors.py`, plus a test comparing the ADR's documented error URL with the code. Changing the URL in the ADR failed the check. Renaming the error codes in the ADR, which the test did not cover, was re-stamped by `okl reverify`.
8. Re-seeding the file without editing it reverted an `okl update` correction. It also stripped `files` and proof from the ownership rule, and `okl drift` then checked nothing.
9. A teammate's clone that loaded the file briefed ADR 0002 as live again. Its gate failed until the checks ran there.
10. Renaming `fetch_order_by_id` left stale mentions behind. The tombstone gate caught a `.py` comment and a `CLAUDE.md` line, missed a `.rst` doc, and did not run at push.

What the trial suggests:

- prove the few lessons that matter;
- keep the lesson text in a committed file;
- read the diff before proving a doc lesson again;
- give every clone a setup script.

## 14. When something is off

| You see | It means | Do |
|---|---|---|
| A warning on every record that the seed node has no `repo` | The message is wrong: the lessons are stored under this repo | Ignore it, or add `"repo": "<name>"` |
| `unknown tag(s)`, and the import stops | Records before it were written; the rest were not | Declare the tag with a `Vocabulary` record earlier in the file, or fix the tag; run `okl seed` again |
| `status 'superseded' is set by okl retire` | The file sets a status only `okl retire` may set | Remove the status, re-seed, then `okl retire <old> --by <new>` |
| A traceback ending in `unexpected keyword argument` | The file has a field okl does not know | Remove it. A check command cannot travel in the file; put it in the setup script |
| Imported lessons are never briefed | Their scope names another repo, or tasks share no words with them | Compare the scope with `"repo"` in `.okl/config.json`; use `"scope": "repo"`; add the team's words to the title |
| An org lesson is never briefed | Its tags fall outside this repo's interests | Run `okl check --task "..." --interests ""` to confirm |
| On a re-import, every record "resembles" itself at 1.00 | A known false alarm in the near-duplicate report | Ignore the self-matches |
| A correction disappeared after `okl seed` | The file owns a seeded lesson's text | Make the correction in the file |
| `okl drift` checks nothing after a re-seed | The file lacked `files` that `okl update` had added | Add `files` to the file, re-seed, run `okl reverify` |
| `okl reverify` says a lesson has no stored check | This clone never ran it: checks do not travel with the file | `okl verify <id> --run ... --expect ...` |
| A rule deleted from the file is still briefed | Seeding never removes lessons | `okl retire <id> --obsolete --reason "..."` |
| The same lesson appears twice | A key or the file was renamed | `okl retire <old-id> --by <new-id> --reason "..."` |
| Push blocked: a lesson is "stamped ..., unverified" | The file had `"verified": true` | Remove it, and prove the lesson with `okl verify` |
| Push blocked right after seeding: lessons "never verified" | Proofs do not travel with the file | Run the setup script (step 10) |
| Push blocked after importing `okl-bootstrap.json` | Its doc pointers carry `files` that nothing can verify | Remove their `files`, or delete them. Each `okl bootstrap` run makes new keys, so importing two runs duplicates them |
| `okl verify` says `okl-drift.json` was NOT refreshed: it would drop rules this store does not hold | The committed file holds rules from another clone's store | Run the setup script and verify again. `okl export --drift --allow-shrink` if they should leave the gate |
| The tombstone gate fails on a CHANGELOG or an old ADR | The gate skips only `registries/` | Reword, or add an exclusion to your copy of the script |
| A tombstone never matches | The line uses spaces, not TABs | Separate the fields with TABs |
| All gates are green, but a stale name remains in a `.js` or `.rst` file | The gate does not scan that file type | Add `--include` lines to your copy of the script |
| `okl search '' --limit 200` shows no tags | The text output leaves them out | Add `--format json` |
| `okl seed .` imported a draft or a second pack | It imports every `.json` file in the folder | Give it the lessons file by name |
