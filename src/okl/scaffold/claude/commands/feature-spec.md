---
description: Draft a structured feature spec — value gate, significance check, prior-art check, and a validate plan. The ritual at the start of any non-trivial work.
argument-hint: "<one-line feature description>"
disable-model-invocation: true
---

# /feature-spec — the front of the loop

Produce a short spec for: **$ARGUMENTS**

Do NOT write implementation code. Produce the spec, then stop for review.

## 1. Value gate
- What problem does this solve, and for whom? What breaks if we don't build it?
- What is the smallest version that delivers the value? (Build that; note the rest as deferred.)
- Set a stop condition up front (a token/time budget for experiments). When it runs out, the
  default is "we learned what we needed; we don't continue."

## 2. Significance check
- Is this **pattern-conforming** (matches an existing shape → gate review suffices) or
  **non-pattern-conforming** (new bounded context, novel dependency, security-model change,
  multi-step refactor → stay present during implementation, route through architecture-reviewer)?

## 3. Prior-art / knowledge check (mandatory)
- Run `okl check --task "$ARGUMENTS"`. Record any armed gates to adopt, retractions to respect,
  and THREAT prior-art. If this is a research/novelty claim, treat prior art as falsifying until shown otherwise.

## 4. Contract + validate plan
- Inputs, outputs, invariants, error cases.
- **Every assertion in this spec that could be wrong from memory gets a mechanical `validate` step.**
  (Do the class paths exist? Does the config parse? Are the class counts right?) List them as
  gate/test items, not prose claims. This is the one SDD rung we keep.

## 5. Handoff
- List the tasks. Flag which are pattern-conforming vs not. Name the gates that must be green to merge.

<!-- <<FILL: STACK-SPECIFIC SPEC SECTIONS>>  e.g. migration plan, API version bump, deploy steps. -->
