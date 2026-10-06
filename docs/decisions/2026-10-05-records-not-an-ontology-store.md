# ADR: Lessons stay typed records found by full-text search; an ontology is a one-way export when something needs one

- **Status:** Accepted (2026-10-05)
- **Context prompted by:** the question of whether okl should ingest an ontology, store its
  lessons as RDF and query them with SPARQL, in place of its own records. It came up while
  building the briefing exposure log (#129, PR #135). This record states how okl stores and
  finds lessons now, why that stays, and what would change it. It extends
  [the flat-retrieval ADR](2026-07-17-flat-retrieval-until-scale.md), which already refuses
  to start as a graph, and [the subject-tags ADR](2026-07-21-subject-tags-controlled-vocabulary.md).

## How okl stores and finds lessons now

**Storage.** Each lesson is one record in a SQLite file (the default) or in Postgres (behind
the shared service). A record has a type, a title, a body, the symptom that tells a reader it
applies, the fix, a scope (`org` or `repo:<name>`), subject tags, an optional `applies_to`,
the files it governs, and the evidence and commit of the check that last proved it. The core
needs nothing beyond Python's standard library.

That is already a small ontology: a fixed set of kinds of thing and the ways they relate.

- **10 record types:** Defect, Rule, Decision, Gate, Claim, Retraction, Tombstone, PriorArt,
  Vocabulary and Entity (`store.NODE_TYPES`).
- **9 relationship types:** CATCHES, ENCODES, REFUTES, RETRACTS, SUPERSEDES, VERIFIED_ON,
  RECURS_IN, CONTRADICTS and DEFINED_IN (`store.EDGE_RELS`), each one row in an edge table.
- **A closed tag vocabulary:** 14 subject tags ship as the floor (`store.KNOWN_TAGS`), and a
  store adds its own with Vocabulary records.

**Relationships are followed one step, for reporting.** A briefing names the defect each gate
catches (CATCHES). `okl metric` counts lessons that came back, split by whether a gate
existed (RECURS_IN). Retractions and supersession mark what is withdrawn. Nothing follows a
chain of relationships, and nothing uses them to find lessons.

**Finding lessons (`okl check`)** runs four steps on every prompt, in about a tenth of a second.
The pipeline diagram, [`docs/okl-retrieval-pipeline.svg`](../okl-retrieval-pipeline.svg), is
generated from this code and shows the counts at each step.

1. **Search.** Full-text search (SQLite FTS5 with BM25 ranking, or Postgres's weighted
   tsvector) matches the task sentence against every record. Title counts 8, body and symptom
   4 each, fix 2 and tags 1, and a match in the content always ranks ahead of a match on tags
   alone. It fetches three times the cap, because the next step discards records.
2. **Filter.** `_in_scope` keeps what this repo may see (scope), drops lessons whose
   `applies_to` excludes this repo, and drops org lessons tagged entirely outside the repo's
   declared interests. Untagged lessons and the repo's own always pass.
3. **Bucket** the survivors by type, so gates and defects lead the briefing.
4. **Route** them into an ordered list of actions. The briefing keeps the top 12 and says how
   many it trimmed.

**Exposure (new in #135).** Each briefing logs which lesson ids it showed, never the task
text. `okl metric` reports the lessons never shown and the ones shown most with no stored
check, led by how many briefings the log covers.

## Context: what an ontology store would change

An ontology store keeps facts as subject-predicate-object triples (RDF) and answers precise
structural questions with SPARQL: everything of type X that relates by Y to Z, including the
sub-types of X. It is built for that question, and okl does not ask it.

okl's question is fuzzy: here is a sentence describing a task; which of these lessons matter,
best first? That is ranked free-text search. SPARQL has no relevance ranking of its own; its
text matching is regex and substring filters, which Apache Jena's documentation describes as
"a test on a value retrieved earlier in the query so its use is not indexed". Stores that
offer ranked text search attach a separate engine for it (Jena's text extension "combines
SPARQL and full text search via Lucene", or Elasticsearch). An ontology core would have to
add back the search okl already runs, then pay for a triple store on every prompt.

## Decision

1. **Keep** typed records, full-text search and one-step relationships as okl's storage and
   query model.
2. **When something needs okl's lessons in an ontology tool, export them one way**, as
   [JSON-LD](https://www.w3.org/TR/json-ld11/) (a W3C Recommendation since 2020, and plain
   JSON, so the standard library can write it). Never import it back and never keep a second
   source of truth. That is the rule okl already follows for its drift snapshot: a committed
   snapshot of store state is a one-way export.
3. **Build the export when it has a user** (the first trigger below), not before. An exporter
   with no consumer is the speculative interface the Python canon warns about
   (`py_classes_earn_place`).

## Why

- **The job is ranked free text, under a tight budget.** The briefing runs inside a prompt
  hook on other people's machines, with no service to call and nothing extra installed.
- **Strict classification measured worse here.** In §4d of [the eval report](../../evals/REPORT.md)
  (receipt `ab-20260902-0538`), treating stack tags as an exclusive classification hid 35 of
  172 org records from a repo that shared their subject. The briefed arm then reproduced a
  defect the hidden rule describes, and was the worst of four comparable runs (13%). The change
  was reverted. An ontology makes classification the main way in.
- **okl's precise questions are already one line of SQL.** Which gate catches which defect,
  and what recurred where, are lookups. The RAG seed pack records the general rule: "Don't
  infer by resemblance what you can look up", because a corpus-wide question is a GROUP BY.
- **Graph machinery is not free and does not automatically win.** Mem0 removed its graph
  layer after its own benchmarks, as the flat-retrieval ADR records.

## Revisit when

Any one of these, measured rather than assumed:

- **A consumer needs RDF.** A team wants okl's lessons inside an existing knowledge graph or
  ontology tool, or a tool worth adopting only reads RDF. Then build `okl export --rdf`:
  record types as classes, relationships as properties, tags as concepts, and security defects
  linked to their CWE entries. Its test parses the output with a real RDF parser, as a
  test-only dependency, so the export is proven valid rather than assumed to be.
- **Misses cluster around related concepts.** The exposure log and the A/B harness show lessons
  missed because the task and the lesson name the same concept in different words. The first
  step is small and measured: a map of equivalent terms applied at search time, A/B-tested
  before it becomes the default. This overlaps the flat-retrieval ADR's vocabulary-mismatch
  trigger, whose remedy is embeddings; measure which one fixes the misses.
- **The job becomes reasoning.** okl has to infer across a shared hierarchy of concepts, such
  as "this repo uses SQLAlchemy, which is an ORM, so brief the ORM lessons", across many
  organisations and thousands of lessons.

## Consequences

- **Positive:** install, speed and readable records stay as they are; ranked retrieval stays;
  ontology tools stay available through an export that costs about a day when it is wanted.
- **Negative:** no inference across concepts. A lesson phrased in different words from the
  task can be missed until a trigger fires. That is accepted, as it is in the flat-retrieval
  ADR, and the exposure log is now the instrument that will show it.
