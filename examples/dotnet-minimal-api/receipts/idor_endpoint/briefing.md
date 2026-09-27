## OKL briefing — orders-api · task: Add GET /orders/{id} that returns one order as JSON for the authenticated caller. Follow the existing style in src/Program.cs and add a test in tests/ApiTests.cs.
_10 relevant node(s) from the org's encoded body._

### ✅ Do this (routed actions)
- **FIX: Missing ownership scope check is an IDOR (CWE-639) and slips through tests-by-omission** — when you see: an endpoint fetches an entity by id with no owner/tenant predicate
    → add the caller's owner id to the WHERE clause; return 404 (not 403) on no match
    why: A resource endpoint that doesn't scope by the caller's identity leaks other users' data. Portable fix: push the ownership predicate INTO the query (read handlers) or check on the tracked entity (write
- **FIX: Prove outbox atomicity with rollback tests — force the commit to fail and assert no event escaped** — when you see: a write-then-publish path whose atomicity is asserted by code review only
    → add a forced-rollback integration test asserting entity rolled back AND no event dispatched
    why: A save-interceptor throws when the entity commits; the test asserts both that the entity rolled back and that no event was dispatched. On the broken code the order rolled back but the event had alread
- **FIX: Migrations are immutable once applied anywhere; destructive changes need a multi-step plan** — when you see: a diff editing an already-applied migration, or a one-shot destructive schema change
    → add a new migration; stage destructive changes across deploys
    why: Editing an applied migration desynchronizes environments that already ran it — the schema history lies. Drop/rename/NOT-NULL-on-existing-column changes ship as expand-migrate-contract sequences, never
- **FIX: Authorization behavior is only proven by an authorization-FAILURE test — clean builds and passing unit tests say nothing** — when you see: a scoped-entity endpoint shipped without a cross-user access-denied test
    → add the X-cannot-read-Y integration test asserting 404 with every scoped endpoint
    why: Every endpoint returning or mutating a scoped entity requires an integration test that authenticates as user X, requests user Y's resource, and asserts 404 (not 200, not 403). The absence of exactly t
- **FIX: Enforce the dependency rule by escalation: convention → architecture tests → project split** — when you see: a proposal to split Domain/Application/Infrastructure csprojs 'to enforce boundaries'
    → add an architecture test first; split projects only on 5+ aggregates with cross-cutting rules AND Domain/ outgrowing Features/
    why: Two things wear the name Clean Architecture: the dependency rule (Domain references nothing — always in force, never complexity-gated) and the multi-project split (only buys compile-time enforcement).
- **FIX: Tests are Arrange-Act-Assert with story comments — a junior reads the test and understands the contract without the SUT** — when you see: a security or concurrency test whose assertions don't say what failure they guard against
    → narrate the phases; number and justify multi-invariant assertions
    why: Each phase explains what's set up and why it matters, what's called, and what each assertion guards. Multi-invariant asserts are numbered with the why (especially security boundaries, idempotency guar
- **FIX: Pick ONE error-flow canon and name the flip triggers — here: exceptions at the handler boundary, no Result<T>** — when you see: a Result<T>-style return introduced into an exception-canon codebase (or vice versa)
    → follow the declared canon; flip only when a named trigger fires, repo-wide
    why: Expected business errors throw at the handler boundary and a global handler translates to RFC 7807 ProblemDetails. The Result/OneOf/ErrorOr pattern is defensible (exhaustiveness, allocation-cheap) but
- **FIX: Error responses: generic detail + trace ID only — the full W3C traceparent leaks server call structure** — when you see: an error body carrying exception details, entity IDs, or a full traceparent string
    → generic ProblemDetails + bare trace ID; details to server logs keyed by that ID
    why: Clients get RFC 7807 ProblemDetails with a correlation trace ID; internal state, entity IDs, and stack traces stay in server logs. Subtlety: expose Activity.TraceId (32 hex chars), NOT Activity.Id — t
- **FIX: The aggregate pattern only earns its keep when someone observes the invariant — otherwise it's ceremony** — when you see: a factory + private setters + status enum on a type nothing persists or re-reads
    → reserve the aggregate shape for persisted, invariant-bearing entities; inline validation elsewhere
    why: Persisted entities with non-trivial invariants get factories, private setters, and method-guarded state changes. But an in-memory, single-use object discarded after the handler returns needs none of t
- **FIX: Multi-impl ports route via keyed DI; premature factories and unrouted multi-registrations are twin failure modes** — when you see: every call routes to one impl regardless of the selector field, or an unused factory wraps a single impl
    → one impl: plain registration. multiple + per-call selection: keyed services keyed by the routing value
    why: Two DI-registration bugs: (1) premature factory — a keyed/factory setup wrapping a port with exactly one implementation is speculative coupling; plain scoped registration is right until a second impl 

> 16 lower-ranked record(s) were trimmed to keep this briefing short. Raise --limit or narrow the task if you expected more.
