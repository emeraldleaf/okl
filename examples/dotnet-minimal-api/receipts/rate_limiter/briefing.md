## OKL briefing — orders-api · task: Add GET /orders/search?q=<text> that returns the caller's orders whose item contains the text, case-insensitive. Add a test.
_11 relevant node(s) from the org's encoded body._

### ✅ Do this (routed actions)
- **FIX: Missing ownership scope check is an IDOR (CWE-639) and slips through tests-by-omission** — when you see: an endpoint fetches an entity by id with no owner/tenant predicate
    → add the caller's owner id to the WHERE clause; return 404 (not 403) on no match
    why: A resource endpoint that doesn't scope by the caller's identity leaks other users' data. Portable fix: push the ownership predicate INTO the query (read handlers) or check on the tracked entity (write
- **FIX: Non-sargable predicates defeat indexes — fix at write time, not query time** — when you see: a Where clause applying a function to the column, or LIKE '%text%'
    → normalize at write time / use collation; adopt a text index only when load demands
    why: A WHERE that wraps the column in a function (lower(email) = x) can't use a B-tree index. Normalize on insert/update (a normalized column populated by the aggregate factory) or use a case-insensitive c
- **FIX: Prove outbox atomicity with rollback tests — force the commit to fail and assert no event escaped** — when you see: a write-then-publish path whose atomicity is asserted by code review only
    → add a forced-rollback integration test asserting entity rolled back AND no event dispatched
    why: A save-interceptor throws when the entity commits; the test asserts both that the entity rolled back and that no event was dispatched. On the broken code the order rolled back but the event had alread
- **FIX: Tests are Arrange-Act-Assert with story comments — a junior reads the test and understands the contract without the SUT** — when you see: a security or concurrency test whose assertions don't say what failure they guard against
    → narrate the phases; number and justify multi-invariant assertions
    why: Each phase explains what's set up and why it matters, what's called, and what each assertion guards. Multi-invariant asserts are numbered with the why (especially security boundaries, idempotency guar
- **FIX: Authorization behavior is only proven by an authorization-FAILURE test — clean builds and passing unit tests say nothing** — when you see: a scoped-entity endpoint shipped without a cross-user access-denied test
    → add the X-cannot-read-Y integration test asserting 404 with every scoped endpoint
    why: Every endpoint returning or mutating a scoped entity requires an integration test that authenticates as user X, requests user Y's resource, and asserts 404 (not 200, not 403). The absence of exactly t
- **FIX: When a hazard is structural and no analyzer can express it, enforce it with a CI grep step** — when you see: a real hazard 'enforced' only by convention because no analyzer rule exists
    → encode it as a CI grep/audit step; ugly beats unenforced
    why: Static mutable collections are a real concurrency hazard the analyzer stack cannot detect (structural, not syntactic); the ban is enforced with a grep step in CI instead. An ugly-but-automated text ch
- **FIX: The aggregate pattern only earns its keep when someone observes the invariant — otherwise it's ceremony** — when you see: a factory + private setters + status enum on a type nothing persists or re-reads
    → reserve the aggregate shape for persisted, invariant-bearing entities; inline validation elsewhere
    why: Persisted entities with non-trivial invariants get factories, private setters, and method-guarded state changes. But an in-memory, single-use object discarded after the handler returns needs none of t
- **FIX: Encode every 'never again / always when' finding to the smallest surface that catches it — a fix PR without the rule is a half-finished job** — when you see: a merged fix for a recurring antipattern with no corresponding rule/gate change
    → land the rule with the fix (same or paired PR); track deferred encodings as labeled placeholders, never as the encoding itself
    why: Findings from any review surface get encoded the same session, into the smallest applicable layer: always-on canon only if every session needs it (keep it lean — size-budgeted in CI), else file-scoped
- **FIX: Enforce the dependency rule by escalation: convention → architecture tests → project split** — when you see: a proposal to split Domain/Application/Infrastructure csprojs 'to enforce boundaries'
    → add an architecture test first; split projects only on 5+ aggregates with cross-cutting rules AND Domain/ outgrowing Features/
    why: Two things wear the name Clean Architecture: the dependency rule (Domain references nothing — always in force, never complexity-gated) and the multi-project split (only buys compile-time enforcement).
- **FIX: Rate-limit the endpoints backed by expensive unindexable queries — before one client can DOS the database** — when you see: an unauthenticated or expensive-query endpoint with no rate limit
    → named central policies, applied selectively; search/payment/auth first
    why: A search endpoint running a leading-wildcard LIKE cannot use an index well, so one scraping client could take down the database; a named fixed-window policy (30 req/10s, no queueing, 429 on reject) ap
- **FIX: Migrations are immutable once applied anywhere; destructive changes need a multi-step plan** — when you see: a diff editing an already-applied migration, or a one-shot destructive schema change
    → add a new migration; stage destructive changes across deploys
    why: Editing an applied migration desynchronizes environments that already ran it — the schema history lies. Drop/rename/NOT-NULL-on-existing-column changes ship as expand-migrate-contract sequences, never

> 18 lower-ranked record(s) were trimmed to keep this briefing short. Raise --limit or narrow the task if you expected more.
