## OKL briefing — orders-api · task: Add POST /orders that creates an order for the authenticated caller from a JSON body with item, quantity and unitPrice, and returns it with 201. Add a test.
_9 relevant node(s) from the org's encoded body._

### ✅ Do this (routed actions)
- **FIX: Missing ownership scope check is an IDOR (CWE-639) and slips through tests-by-omission** — when you see: an endpoint fetches an entity by id with no owner/tenant predicate
    → add the caller's owner id to the WHERE clause; return 404 (not 403) on no match
    why: A resource endpoint that doesn't scope by the caller's identity leaks other users' data. Portable fix: push the ownership predicate INTO the query (read handlers) or check on the tracked entity (write
- **FIX: Server-controlled fields trusted from the client body = tampering vulnerability** — when you see: a [FromBody] DTO carries Price/Amount/Status/IsAdmin
    → drop those fields from the DTO; compute them server-side from the catalog/service
    why: A [FromBody] DTO carrying Price/BuyerId/Status/IsAdmin lets a client submit Price=0.01 for a $999 product. Portable rule: money, authorization identifiers, state-machine columns, and security flags ar
- **FIX: Prove outbox atomicity with rollback tests — force the commit to fail and assert no event escaped** — when you see: a write-then-publish path whose atomicity is asserted by code review only
    → add a forced-rollback integration test asserting entity rolled back AND no event dispatched
    why: A save-interceptor throws when the entity commits; the test asserts both that the entity rolled back and that no event was dispatched. On the broken code the order rolled back but the event had alread
- **FIX: Authorization behavior is only proven by an authorization-FAILURE test — clean builds and passing unit tests say nothing** — when you see: a scoped-entity endpoint shipped without a cross-user access-denied test
    → add the X-cannot-read-Y integration test asserting 404 with every scoped endpoint
    why: Every endpoint returning or mutating a scoped entity requires an integration test that authenticates as user X, requests user Y's resource, and asserts 404 (not 200, not 403). The absence of exactly t
- **FIX: Encode every 'never again / always when' finding to the smallest surface that catches it — a fix PR without the rule is a half-finished job** — when you see: a merged fix for a recurring antipattern with no corresponding rule/gate change
    → land the rule with the fix (same or paired PR); track deferred encodings as labeled placeholders, never as the encoding itself
    why: Findings from any review surface get encoded the same session, into the smallest applicable layer: always-on canon only if every session needs it (keep it lean — size-budgeted in CI), else file-scoped
- **FIX: Migrations are immutable once applied anywhere; destructive changes need a multi-step plan** — when you see: a diff editing an already-applied migration, or a one-shot destructive schema change
    → add a new migration; stage destructive changes across deploys
    why: Editing an applied migration desynchronizes environments that already ran it — the schema history lies. Drop/rename/NOT-NULL-on-existing-column changes ship as expand-migrate-contract sequences, never
- **FIX: Enforce the dependency rule by escalation: convention → architecture tests → project split** — when you see: a proposal to split Domain/Application/Infrastructure csprojs 'to enforce boundaries'
    → add an architecture test first; split projects only on 5+ aggregates with cross-cutting rules AND Domain/ outgrowing Features/
    why: Two things wear the name Clean Architecture: the dependency rule (Domain references nothing — always in force, never complexity-gated) and the multi-project split (only buys compile-time enforcement).
- **FIX: An identifier sweep is done when grep returns zero — not when the docs you remembered are updated** — when you see: a removal PR that updates 'the docs I remembered' with no grep-to-zero check
    → grep every removed public identifier to zero across md/comments/CI/scripts; tombstone it so CI holds the line
    why: The compiler catches stale identifiers in code; nothing catches them in prose. Memory-based sweeps left 15+ docs teaching the removed transport as current, plus a metric documented as THE alarm that n
- **FIX: No N+1 — never query inside a loop over another query's results** — when you see: a query executed inside a foreach over results from another query
    → collapse into one query via Include or a projection
    why: Use Include or (better) projection so the database answers in one round-trip. A loop of per-item queries is the canonical serialized-latency bug and is invisible in tests against tiny datasets.

> 16 lower-ranked record(s) were trimmed to keep this briefing short. Raise --limit or narrow the task if you expected more.
