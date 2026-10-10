# ADR: Org lessons live in a ledger repository and are adopted by pull request

- **Status:** Proposed (2026-10-10)
- **Context prompted by:** the question of how a team decides which lessons apply across its
  repositories, when its projects follow different practices, and who gets to decide. The
  answer has to keep okl local-first and git-native: every repo keeps its own store. It
  builds on [the subject-tags ADR](2026-07-21-subject-tags-controlled-vocabulary.md)
  (interests) and on the planned `okl update` and `okl retire` verbs
  ([part 6](https://emeraldleaf.dev/writing/recording-is-the-easy-half/)).

## How org lessons work now

**Two scopes.** A lesson is `org` (meant for every repo) or `repo:<name>` (one repo).
`_in_scope` in `core.py` passes a repo's own lessons, then passes an org lesson unless its
`applies_to` excludes the repo or its tags fall entirely outside the repo's declared
interests.

**Each repo has its own store.** It is `.okl/okl.db` beside `.okl/config.json`, and it is
gitignored. A lesson recorded with `--scope org` is written into that one repo's store, and
no other repo reads it. On a default install, "org" is a label, not a way to share. (The Stop
hook and this repo's CLAUDE.md say `org` "spreads to every repo"; that is not true today.)

**Packs are the one path that reaches other repos.** A pack is a committed JSON file of
lessons and links. `okl seed <file or dir>` loads it and gives each lesson the id
`seed:<pack>:<key>`, so loading it again updates the same rows, and a re-seed changes a
lesson's content without touching its proof (#110). okl ships 12 packs, and `okl init`
offers the ones that match a repo's interests. A pack marked `_proposed_by` is refused unless
every lesson cites a source, and gets a near-duplicate report. Tags come from a closed
vocabulary that a store grows with Vocabulary records.

**What a team is missing:**

1. **Review.** Anyone who runs okl can write an org lesson, and nobody approves it.
2. **Distribution.** Outside okl's bundled packs, getting a lesson into another repo means
   copying a file by hand.
3. **Per-project choice.** Interests narrow org lessons by subject, but a project cannot
   say "we follow the payments rules, not the mobile ones" or "not yet".
4. **Withdrawal.** A lesson deleted from a pack stays in every store that loaded it, briefed
   as before. Nothing tells those stores it was withdrawn.
5. **History.** Nothing records who adopted an org lesson, when, or why.

## Decision (proposed)

Org lessons live in a separate git repository, the **org ledger**. A lesson becomes an org
lesson through a pull request to the ledger, approved by the people CODEOWNERS names for its
area. Merging is adoption. Each project names, in a committed file, which areas of the ledger
it follows and at which ledger commit, and loads them into its own store. A lesson learned in
a project stays a repo lesson, in use there at once, until someone proposes it.

### The ledger repository

```
acme-okl-ledger/
  areas/
    core/              one file per lesson: <key>.json
    security/
    payments/
    frontend/
  ledger.json          which areas every project must follow
  vocabulary.json      subject tags this org adds to okl's floor
  CODEOWNERS
  .github/workflows/ledger.yml    runs `okl ledger check` on every pull request
```

- **An area is a directory.** It is the unit of ownership and of subscription. CODEOWNERS
  gives each area its approvers (`areas/core/ @acme/principals`,
  `areas/payments/ @acme/payments-leads`). With branch protection set to require code-owner
  review, the forge will not merge a pull request until an owner of every area it touches
  approves.
- **One file per lesson.** A pull request's diff then shows exactly the lessons it changes,
  two proposals in one area do not conflict, and `git log` on a file is that lesson's history:
  who changed it, when, and the pull request that says why. The fields are the ones a pack
  lesson already has (type, title, symptom, body, fix, tags, `applies_to`, files, `found_by`),
  plus a status and an optional suggested check (`run` and `expect`). It should be the same
  format as the planned committed files for a repo's own lessons, so a lesson moves between a
  repo and the ledger without conversion.
- **No proof in the ledger.** A verification stamp records that a check passed on one repo's
  code at one commit. The ledger may suggest a check; it never carries a stamp. A stamp copied
  into a store is a claim, not an observation, and it would never drift.

### Proposing a lesson

`okl propose <id> --area security` reads a lesson from the repo's store and writes it as
`areas/security/<key>.json` on a new branch of a local clone of the ledger. It sets the scope
to org, keeps the citation, and adds where the lesson was learned and proven (the repo, the
commit, the check and its last result) as provenance. Then it opens the pull request with the
forge's command-line tool if one is installed, or prints the branch to push.

An agent can run it, and the Stop question can mention it for a lesson that holds beyond the
repo where it was learned. The lesson stays a working repo lesson while the pull request is
open. Agents never approve: only the people CODEOWNERS names can.

**When the org copy arrives.** After the pull request merges and the project syncs, its store
holds the repo lesson and the org copy, which names the repo lesson's id in its provenance.
Sync retires the repo lesson in favour of the org copy (`okl retire <id> --by <org id>`), so
it is briefed once. Proof does not move with it: sync prints the `okl verify` command with the
stored check, and running it proves the org copy in this repo. A stamp is only ever written by
a check that ran.

### The ledger's CI: `okl ledger check`

It runs the checks okl already applies to packs, as a gate, on every pull request:

- every file parses, has a known type and a title, and has a symptom and a fix where its type
  needs them;
- tags come from okl's floor plus `vocabulary.json`, and growing that vocabulary is itself a
  pull request, as the subject-tags ADR requires;
- every lesson cites a source (`found_by`), the rule `_proposed_by` packs follow today;
- keys are unique, and a key is never reused for a different lesson;
- no lesson carries a verification stamp;
- no field holds a secret or invisible characters;
- near-duplicates across all areas are reported in the pull request, as advice only, because
  the similarity score cannot separate a paraphrase from a related lesson.

### Subscribing and syncing

A project commits `okl-ledger.json` beside `okl-drift.json`:

```json
{
  "ledger": "git@github.com:acme/okl-ledger.git",
  "ref": "3f2a9c1",
  "areas": ["core", "security", "payments"]
}
```

- **It is committed**, unlike `.okl/config.json`, which holds machine-local paths. Everyone
  on the project gets the same org lessons.
- **`ref` pins a ledger commit**, as a lockfile pins a dependency. `okl ledger sync` fetches
  that commit and loads the subscribed areas into the repo's store. A changed lesson keeps its
  local proof unless its governed files change, which is the rule planned for `okl update`.
- **A ledger lesson's id never changes.** It is `seed:ledger-<area>:<key>`, the id `okl seed`
  already gives a lesson keyed `<key>` in a pack file named `ledger-<area>.json`. The first
  slice below loads such pack files with today's `okl seed`, and `okl ledger sync` later
  writes the same ids, so no store ever holds two copies of one lesson or needs its proof
  moved from one id to another. The `ledger-` prefix keeps an area from colliding with a
  bundled pack's name.
- **Withdrawals propagate.** A lesson that is gone from a subscribed area at the new ref, or
  marked retired there, is retired in the store with the reason "retired in the ledger at
  <commit>", through `okl retire`. Without this, a withdrawn org rule stays in every briefing
  of every repo that ever loaded it.
- **Unsubscribing retires too.** When a project drops an optional area from
  `okl-ledger.json`, sync retires that area's lessons in its store with the reason "area
  <area> unsubscribed". Briefings do not filter by area, and an untagged org lesson passes
  every other filter, so a lesson left live would keep being briefed. Subscribing again
  restores them. Sync owns the content and status of `seed:ledger-` lessons only; a project's
  own lessons, its deviations included, are never touched.
- **A project takes updates on purpose.** `okl ledger update` moves `ref` to the ledger's
  newest commit and prints what changes for this repo: lessons added, changed and retired in
  its areas. The project commits that in its own pull request, so its reviewers see which org
  lessons change.
- **Sync stays out of the prompt hook**, which stays fast and offline. `okl doctor`, and one
  line in the briefing, say when the store was synced from a different commit than
  `okl-ledger.json` names, as after a pull that moved `ref`.

It is plain git, so it works offline and air-gapped, on any forge.

### Required areas

Cursor and Claude Code, which let a repo choose what it follows, also have a tier it cannot
drop: Cursor's Required mode, and Claude Code's force-enabled plugins and managed CLAUDE.md
(see Prior art). The ledger has one too: a `ledger.json` at its root lists required areas,
such as `core`, and changing that list is a pull request the core area's owners approve.
`okl ledger sync` always loads the required areas, whatever `okl-ledger.json` lists. A project
that must depart from a required lesson records a deviation (below); it cannot unsubscribe.
Like every control surveyed, this is enforced by the client a developer runs: it makes a
departure visible, not impossible.

### Projects that differ

Three levels of choice, cheapest first:

1. **Subscription.** A project follows only the areas that apply to it, beyond the required
   ones.
2. **`applies_to`, set in review.** A lesson true only on some stacks says so in the ledger,
   and the existing exclusive filter keeps it out of the rest.
3. **A recorded deviation.** When a project deliberately departs from an org lesson it
   follows, it records a repo Decision and links it `SUPERSEDES seed:ledger-<area>:<key>`. Its
   briefings then show the decision in place of the org lesson, through the one-hop
   SUPERSEDES handling planned with `okl retire`. Once a repo's own lessons are committed
   files, the departure is a file a reviewer can find, never a lesson that quietly stopped
   appearing.

### What stays as it is

- **Repo lessons** are recorded freely and used at once. Learning stays cheap where it
  happens.
- **Without a ledger,** `okl record --scope org` keeps working as now, for one developer.
  **In a repo that has `okl-ledger.json`,** it refuses (exit 2) and prints the `okl propose`
  command, so an org lesson cannot skip review.
- **okl's bundled packs** stay. An org adopts one by importing it into its ledger by pull
  request, which is also how it chooses which bundled lessons it wants.

## Prior art

Checked 2026-10-10 against each tool's own documentation. Most pages carry no date.

**Org rules set by an admin, applied without review.**
[GitHub Copilot's organization instructions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-organization-instructions)
(generally available [2026-04-02](https://github.blog/changelog/2026-04-02-copilot-organization-custom-instructions-are-generally-available/))
are typed into org settings by an owner. [Cursor's Team Rules](https://cursor.com/docs/context/rules)
are written by team admins in a dashboard and can be enforced. Claude Code's
[managed settings](https://code.claude.com/docs/en/server-managed-settings), which can carry a
managed CLAUDE.md, are changed by an org owner in the admin console; they keep an audit log,
but nothing is reviewed before a change applies. In each, one admin role decides, and a change
takes effect at once.

**Git-backed distribution with per-repo opt-in.** Claude Code
[plugin marketplaces](https://code.claude.com/docs/en/plugins/org) are fetched from a git
repository. A repository can require plugins through its committed `.claude/settings.json`,
managed settings can force-enable them, and two refs of one marketplace serve as release
channels. Cursor's [team marketplaces](https://cursor.com/docs/plugins) import from git hosts
with Default Off, Default On and Required modes. GitHub's
[custom agents](https://docs.github.com/en/copilot/how-tos/administer-copilot/manage-for-enterprise/manage-agents/prepare-for-custom-agents)
live in an org's `.github-private` repository, where a ruleset can let members open pull
requests that only enterprise owners merge. These distribute prompts, rules or agents; none
ties a rule to a check that proves it.

**The closest match: Packmind.** Developers or their agents submit
[change proposals](https://docs.packmind.com/playbook-maintenance/change-proposals.md) through
a skill or the CLI. A team reviews them in Packmind's web interface, and accepting one creates
a new version. [Distribution](https://docs.packmind.com/governance/distribution.md) commits
instruction files into each repository, and each repository lists its packages in a
`packmind.json`. So proposal, review, adoption and per-repo subscription all exist there
already. Review happens in Packmind's interface rather than in git, and the documentation
describes no check that a rule is still true.

**Memory with evidence.** [Copilot Memory](https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/agents/copilot-memory)
stores facts with citations to code and checks them against the current branch before use. It
writes memories itself, per repository, with no approval step.

**What this design adds, narrowly.** None of the proposal, the review gate, git-backed
distribution or per-repo subscription is new; this ADR applies them to okl's lessons. Two
parts were not found in the tools above: approval per area through ordinary pull requests and
CODEOWNERS, with the history in git; and an org lesson that each repo proves with its own
check, which goes stale when the code it governs changes. At least one user has
[asked Cursor](https://forum.cursor.com/t/team-rules-and-skills-from-a-git-repo-context-engineering-as-code/173422)
(2026-09-30) for team rules kept in git with review, CI and rollback.

## Alternatives considered

1. **Keep direct org writes.** On a default install they reach one repo, and nobody reviews
   them. That works for one developer and is not a team mechanism.
2. **A review queue in each store (#97).** Complementary, not a replacement. The candidate
   inbox reviews possible lessons before they become repo lessons. A queue inside one repo's
   gitignored store cannot give an approver one place to decide for every repo, or a history
   anyone else can read.
3. **Org instructions set by an admin** (Copilot, Cursor, Claude Code; see Prior art). One
   role decides and a change applies at once, with no review before it and no check behind
   it, and each belongs to one agent. A ledger lesson is an okl record, so it reaches any
   agent okl briefs.
4. **Copy packs into each repo, or add the ledger as a git submodule.** Copies drift, with no
   single place to approve. A submodule gives the pin, but every clone and CI job then has to
   handle it; `okl-ledger.json` gives the pin without one.
5. **One pack file per area instead of one file per lesson.** The loader exists today, but
   every proposal edits the same file, so proposals conflict and no single lesson's history is
   readable. Pack files are fine for the first slice.

## Consequences

**Gains:**

- Every org lesson has an owner, a review and a history: `git log` on its file says who
  adopted it, when and why.
- Each project chooses its areas and when it takes changes.
- Withdrawing a lesson reaches every project that follows its area.
- A person approves every lesson before it reaches every repo. That is the main defence
  against a careless or planted lesson spreading through a team.

**Costs:**

- **Delay.** A lesson waits for review before it is org-wide. It is in use in its own repo
  meanwhile.
- **Reviewer load.** If agents propose freely, approvers drown. The citation rule, the
  duplicate report and a CI that refuses malformed proposals keep the queue to lessons worth a
  look. An area whose proposals sit unreviewed needs different owners, not a softer gate.
- **One more repository** to own, and a sync that can lag; `okl doctor` reports the lag.
- **Proof stays per repo.** An org rule that governs files has to be proven in each repo
  where those files exist. That is deliberate: a check that passed in one codebase says
  nothing about another.

## Order of work

It depends on three planned changes: lesson ids in the briefing with `okl update`,
`okl retire` with SUPERSEDES handling, and the committed file format for lessons.

1. **Now, with no new code:** document the pattern with what exists. A ledger repository of
   one pack file per area, named `ledger-<area>.json` so its lessons already carry the ids
   sync will use; CODEOWNERS; a CI job that loads every pack into a throwaway store with
   `okl seed` (packs declare `_proposed_by`, so the citation rule applies); and projects that
   run `okl seed` on the areas they follow. Missing: the pin, withdrawal, cleanup when a
   project drops an area, and refusing direct org writes.
2. `okl-ledger.json`, `ledger.json`'s required areas, `okl ledger sync` and
   `okl ledger update`, with withdrawal through `okl retire`, and `okl doctor` reporting a
   store synced from another commit.
3. `okl propose`, `okl ledger check`, areas as one file per lesson, and the refusal of
   `--scope org` in a subscribed repo.
4. Deviations through SUPERSEDES.

The Stop hook's and CLAUDE.md's "org spreads to every repo" should be corrected before any
of this: until the ledger exists, an org lesson reaches another repo only through a pack.

## Open questions

- **Who may move `ref` in a project?** Anyone, or the owners CODEOWNERS names for
  `okl-ledger.json` there.
- **Suggested checks.** Proposed: a sync never stamps anything. Someone, or the project's CI,
  runs the suggested check with `okl verify`, keeping "no run, no stamp".
- **More than one ledger,** such as a company ledger and a team ledger. Proposed: one ledger
  per org, divided into areas, until a real case needs two; `okl-ledger.json` could later list
  several.
- **Is an org lesson ever shown?** The exposure log is per repo and private by design. An
  opt-in export of counts is the only way to answer this across repos, and it is not part of
  this decision.
