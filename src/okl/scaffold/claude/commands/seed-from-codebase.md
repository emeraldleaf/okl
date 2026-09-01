---
description: Read this repository and propose okl records for its real conventions, guard rails and decisions. Outputs a reviewable file; imports nothing.
---

# Seed the knowledge layer from this codebase

`okl bootstrap` reads git history and file names. You can read the code. Your job is to
propose a starter set of records for **this** repository, grounded in what is actually
there, so its first `okl check` returns something earned rather than nothing.

## The rule that governs this whole task

**Every proposed record cites evidence, or it does not exist.** You are reading a
codebase, and a codebase invites confident invention: a plausible-sounding rule that no
file supports is worse than an empty store, because it will be injected into every future
task and believed. If you cannot point at a file and line, do not propose it.

Three consequences, all non-negotiable:

- **Everything you propose is `"scope": "repo:<this repo>"`.** Promoting a record to `org`
  claims it is true for every project in the organization. That is a human judgment about
  the world, not something to infer from one codebase.
- **Nothing is `verified`.** Verification means an observed check passed. You ran no
  check; you read code. Leave `verified` unset and let a person earn the stamp with
  `okl verify`.
- **`found_by` carries the citation** — `path/to/file.py:42`, a commit sha, a config key.
  A reviewer must be able to check your work in one click.

## What to look for, in order of value

1. **Guard rails already in the code.** A validation the code performs, an ownership
   predicate in a query, an explicit timeout, a retry with a cap. Each one exists because
   something went wrong once. Record it as a `Rule` with the symptom that would indicate
   it is missing.
2. **Deliberate choices with rationale.** A comment explaining why the obvious approach
   was rejected, an ADR, a "we tried X, it broke Y" note. These are `Decision` records —
   the point is that nobody silently reverses them later.
3. **Conventions the linter or CI enforces.** Read the ruff/eslint/analyzer config, the
   CI workflow, the pre-commit hooks. A rule already mechanically enforced makes a good
   `Gate` record, linked with `CATCHES` to the defect it prevents if you can name one.
4. **Fix and revert commits.** `git log --grep="fix\\|revert\\|regression" -20`. A commit
   that repairs something names a real defect. Read the diff before proposing it: the
   commit message is a claim, the diff is the evidence.
5. **Existing canon.** If `CLAUDE.md`, `AGENTS.md` or `docs/` already state rules, those
   are the highest-confidence records in the repo. Cite the file.

## What NOT to propose

- Generic engineering advice ("write tests", "handle errors"). If it is not specific to
  this codebase, it is noise that will crowd out the records that are.
- Anything from a framework's documentation rather than this repo's use of it.
- Style preferences the formatter already enforces silently.
- A rule you inferred from an absence. "This code has no rate limiting" is not evidence
  that it should; it might be a deliberate choice you cannot see.

## Output

Write `okl-bootstrap.json` in the seed format. Do **not** run `okl seed` yourself —
importing is the human's decision, made after reading what you proposed.

```json
{
  "_comment": "Proposed from <repo> on <date> by reading the codebase. UNVERIFIED, repo-scoped. Review each record, delete the ones that are wrong, then: okl seed okl-bootstrap.json",
  "nodes": [
    {
      "key": "orders_ownership",
      "type": "Rule",
      "scope": "repo:<this repo>",
      "tags": "security",
      "title": "Order queries filter by the requesting buyer, and return 404 rather than 403",
      "body": "cause: every order query in this repo carries the buyer predicate in the WHERE clause rather than checking after the fetch, so a non-owner's row never leaves the database.",
      "symptom": "an order fetched by id with no buyer/tenant predicate in the query",
      "fix": "add the caller's id to the WHERE clause; return 404 on no match",
      "found_by": "app/orders/queries.py:88, app/orders/routes.py:24"
    }
  ],
  "edges": []
}
```

Tags must come from the closed vocabulary; run `okl seed` with no arguments to see which
subjects the packs use, or read `KNOWN_TAGS` in `okl/store.py`. An unknown tag is
rejected at import.

## Finishing

Report to the human: how many records you propose, what evidence each rests on, and
explicitly **what you looked for and did not find**. A short honest list beats a long
speculative one — and "this repo has no explicit authorization pattern I could find" is
itself a useful finding.
