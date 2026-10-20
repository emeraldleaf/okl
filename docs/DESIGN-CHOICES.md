# Design choices, and why

Part of okl's documentation; the [README](../README.md) is the short version.

- **Read before you work, automatically.** The value is entirely in the lesson being
  in front of you at the start — not in a database you *could* have searched. So the
  read is a hook / a first step, not an optional lookup.
- **It fails closed.** An unreachable store blocks or warns; it never reports "clean."
  Silence and safety are different things.
- **The scope decision is human curation.** `org` reaches any repo that loads it, through
  a pack; `repo:<name>` stays local. A person picks which when recording — that's what keeps a shared store
  from filling with one project's noise.
- **Staleness demotes, never deletes.** A note carries when it was last verified and
  how long that's good for; past that it's shown as `STALE`, not removed — deleting it
  would lose the record that it was ever true.
- **Start simple, grow on evidence.** A stdlib-only core and a single SQLite file by
  default; add the shared service, Postgres, or anything heavier only when a concrete
  symptom demands it (recorded as a decision in `docs/decisions/`).
- **Records, not an ontology store.** Lessons are typed records found by ranked full-text
  search, with one-step relationships for reporting. An RDF triple store would answer
  precise structural questions okl does not ask, and could not rank a task sentence
  without adding back a search engine. [The decision](docs/decisions/2026-10-05-records-not-an-ontology-store.md)
  explains how lessons are stored and found now, and when a one-way RDF export would earn
  its place.
