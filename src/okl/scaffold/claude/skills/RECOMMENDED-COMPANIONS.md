# Recommended companion skills (install separately)

This kit ships two first-party skills — **`encoding-loop`** (turn a finding into a
promoted, recorded rule) and **`verify-before-claiming`** (evidence before assertion).
They are the two disciplines specific to this method.

The broader engineering-discipline skills that pair well with it — systematic debugging,
test-driven development, plan writing/execution, git-worktree isolation — are **not
bundled here on purpose.** The best-maintained open versions live in third-party skill
collections, and vendoring them would mean redistributing someone else's work (with its
own license and attribution) and shipping cross-references to sibling skills this kit
doesn't contain. Point at them instead of copying:

## Superpowers (obra)

A collection of Claude Code skills for disciplined agentic development. The skills below
reference each other via the `superpowers:` namespace, so install the collection as a
unit rather than cherry-picking files:

- `systematic-debugging` — root-cause-before-symptom, pressure-resistant debugging
- `test-driven-development` — red/green/refactor discipline
- `writing-plans` / `executing-plans` — spec → reviewed multi-step execution
- `using-git-worktrees` — isolated workspace per feature
- `verification-before-completion` — the upstream cousin of this kit's `verify-before-claiming`

Install: follow the Superpowers project's own instructions (it manages its own namespace
and inter-skill references). Verify its license permits your use before redistributing it
inside your own repo.

## How they fit with this method

- Use **`encoding-loop`** whenever any of the companion skills surfaces a durable lesson —
  a debugging root cause, a test that should always exist, a plan step that must not be
  skipped — and record it to the knowledge layer so the next task inherits it.
- Use **`verify-before-claiming`** as the last step of any companion skill that ends in a
  "done"/"passing"/"fixed" claim.

Keeping the general skills external and the method skills first-party is deliberate: the
kit stays cleanly installable and license-clean, and you always run the companions'
latest upstream versions rather than a frozen copy that drifts.
