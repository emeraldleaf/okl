---
description: Read this repo's specs, plans and rules docs and propose okl records for the standing intent inside them. Outputs a reviewable file; imports nothing.
---

# Seed the knowledge layer from the docs you already wrote

Most teams have already written down how they want the code built — a spec, an ADR, a
rules file, a design doc, the plan for the current piece of work. That writing is the
highest-confidence material there is, because a human already decided it was true. It is
just sitting in prose nobody re-reads, where nothing selects it, nothing enforces it, and
nothing notices when it stops being true.

Your job is to move the **durable** parts of those documents into typed records, so they
can be injected before a task instead of filed.

## The distinction that governs this whole task

**A record is a standing instruction that outlives the work item it came from.**

A spec or plan contains two kinds of sentence, and only one of them belongs here:

| Belongs in the store | Does not |
|---|---|
| "Deep offsets use keyset pagination" | "Add pagination to `/orders` this sprint" |
| "Money is computed server-side, never trusted from the body" | "Build the checkout endpoint" |
| "We chose Postgres over Mongo because the access pattern is relational" | "Provision the database" |
| "Handlers throw; a global handler maps to ProblemDetails" | "Fix the 500 on `/invoices`" |

The left column is still true after the ticket closes. The right column is work, and work
expires. A store full of expired tasks is worse than an empty one: it will be injected
into future tasks and believed, and nobody will know which lines have gone stale.

When a sentence is a *task* whose *reason* is durable, record the reason and drop the
task. "Add a rate limit to search before launch" becomes "search runs an unindexable
leading-wildcard query, so it needs a rate limit before it is exposed."

## The other rules, all non-negotiable

- **Every proposal cites `path:line`, or it does not exist.** Prose invites confident
  paraphrase into something the document never said. `found_by` carries the citation so a
  reviewer can check you in one click. No citation, no record — and the import will
  refuse the file (see *Output*).
- **Everything is `"scope": "repo:<this repo>"`.** Promoting a record to `org` claims it
  is true for every project in the organization. That is a judgment about the world, made
  by a person, not inferred from one document.
- **Nothing is `verified`.** Verification means an observed check passed. You read a
  document. Leave `verified` unset and let a person earn the stamp with `okl verify`.
- **Prefer the document's own words.** If the spec says "never trust a client-supplied
  price", that is the `fix`. Rewriting it in your own voice loses the authority of the
  person who decided it and quietly changes its meaning.

## What to read, in order of value

1. **Rules and canon files** — `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, a
   `docs/rules/` or `.cursor/rules` directory. These are pure standing intent; nearly
   every line is a candidate.
2. **Architecture decision records** — `docs/decisions/`, `docs/adr/`. Each one is a
   `Decision` record: the choice, and critically the *reason*, so nobody silently
   reverses it. The rejected alternative matters as much as the accepted one.
3. **Specs and design docs** — mine the constraints and invariants, skip the work plan.
   A spec's "must never" and "always" sentences are usually records; its milestones are
   not.
4. **The plan for current work** — the same filter, applied harder. Its durable content
   is usually two or three constraints buried in a page of sequencing.
5. **Runbooks and postmortems** — a postmortem's "what we'll do differently" is a `Rule`
   whose `symptom` is the thing that went wrong.

## Choosing the type

- `Rule` — a convention the code follows. Most of what you find.
- `Decision` — a trade-off that was made, with the reason and the rejected option.
- `Gate` — a check that is actually armed somewhere (a test, a CI step, a hook). Only if
  it exists; a gate you *wish* existed is a `Rule` at most.
- `Defect` — something that went wrong here once, usually from a postmortem.
- `Tombstone` — a name, path or API that was retired and must stay dead.

Give every record a `symptom` where you can: the observable thing a reader would see that
means this record applies. A record with no symptom cannot be routed, only read.

Tags come from the closed vocabulary — run `okl seed` with no arguments to see the
subjects in use, or read `KNOWN_TAGS` in `okl/store.py`. An unknown tag is rejected at
import.

## Output

Write `okl-from-docs.json`. Do **not** run `okl seed` yourself — importing is the human's
decision, made after reading what you proposed.

```json
{
  "_proposed_by": "seed-from-docs",
  "_comment": "Proposed from <repo>'s docs on <date>. UNVERIFIED, repo-scoped. Review each record, delete the wrong ones, then: okl seed okl-from-docs.json",
  "nodes": [
    {
      "key": "money_server_side",
      "type": "Rule",
      "scope": "repo:<this repo>",
      "tags": "security",
      "title": "Money is computed server-side and never trusted from the request body",
      "body": "cause: the checkout spec fixes the price from the catalogue at order time; a client-supplied amount is a price-tampering vector.",
      "symptom": "a request DTO carrying a price, total or discount field",
      "fix": "drop the field from the request; compute it server-side from the catalogue",
      "found_by": "docs/specs/checkout.md:118"
    }
  ],
  "edges": []
}
```

`_proposed_by` is load-bearing: a file carrying it is held to the citation rule
mechanically, and `okl seed` refuses the whole import if any node lacks `found_by`. Leave
it in.

## Finishing

Report to the human: how many records you propose, which document each came from, and
explicitly **what you read and did not record**. A short honest list beats a long
speculative one, and "this spec is all sequencing, no standing constraints" is a real
finding — it tells them the document will not help a future task no matter what you do.

Flag separately anything you found that **contradicts** something else you read. Two docs
disagreeing is exactly the kind of thing that survives for years in prose and cannot
survive in a store, and the human needs to decide which one is true before either lands.
