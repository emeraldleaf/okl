## OKL briefing — orders-api · task: Add POST /orders that creates an order for the authenticated caller from a JSON body with item, quantity and unit_price, and returns it.
_11 relevant node(s) from the org's encoded body._

### ✅ Do this (routed actions)
- **ARM: Gate every executable directory; lint each import-tree from its own root** — when you see: lint clean locally but I001/import-order fails in CI, or a dir has no gate at all
    → one lint step per import-tree run from that tree's root; add every shipping dir to CI trigger paths
    catches: Code outside the linter/type/scan source-roots is gated by nothing, ruff isort is CWD-anchored: sibling imports sort differently from a subdir vs the repo root
    why: Add each shipping dir to the CI trigger paths and the lint/type/scan invocation. Subtlety: ruff's isort first-party detection is CWD-anchored, so `ruff check ../otherdir` from a subpackage classifies 
- **FIX: Server-controlled fields trusted from the client body = tampering vulnerability** — when you see: a [FromBody] DTO carries Price/Amount/Status/IsAdmin
    → drop those fields from the DTO; compute them server-side from the catalog/service
    why: A [FromBody] DTO carrying Price/BuyerId/Status/IsAdmin lets a client submit Price=0.01 for a $999 product. Portable rule: money, authorization identifiers, state-machine columns, and security flags ar
- **FIX: Missing ownership scope check is an IDOR (CWE-639) and slips through tests-by-omission** — when you see: an endpoint fetches an entity by id with no owner/tenant predicate
    → add the caller's owner id to the WHERE clause; return 404 (not 403) on no match
    why: A resource endpoint that doesn't scope by the caller's identity leaks other users' data. Portable fix: push the ownership predicate INTO the query (read handlers) or check on the tracked entity (write
- **FIX: Authorization behavior is only proven by an authorization-FAILURE test — clean builds and passing unit tests say nothing** — when you see: a scoped-entity endpoint shipped without a cross-user access-denied test
    → add the X-cannot-read-Y integration test asserting 404 with every scoped endpoint
    why: Every endpoint returning or mutating a scoped entity requires an integration test that authenticates as user X, requests user Y's resource, and asserts 404 (not 200, not 403). The absence of exactly t
- **FIX: Encode every 'never again / always when' finding to the smallest surface that catches it — a fix PR without the rule is a half-finished job** — when you see: a merged fix for a recurring antipattern with no corresponding rule/gate change
    → land the rule with the fix (same or paired PR); track deferred encodings as labeled placeholders, never as the encoding itself
    why: Findings from any review surface get encoded the same session, into the smallest applicable layer: always-on canon only if every session needs it (keep it lean — size-budgeted in CI), else file-scoped
- **FIX: An identifier sweep is done when grep returns zero — not when the docs you remembered are updated** — when you see: a removal PR that updates 'the docs I remembered' with no grep-to-zero check
    → grep every removed public identifier to zero across md/comments/CI/scripts; tombstone it so CI holds the line
    why: The compiler catches stale identifiers in code; nothing catches them in prose. Memory-based sweeps left 15+ docs teaching the removed transport as current, plus a metric documented as THE alarm that n
- **FIX: The aggregate pattern only earns its keep when someone observes the invariant — otherwise it's ceremony** — when you see: a factory + private setters + status enum on a type nothing persists or re-reads
    → reserve the aggregate shape for persisted, invariant-bearing entities; inline validation elsewhere
    why: Persisted entities with non-trivial invariants get factories, private setters, and method-guarded state changes. But an in-memory, single-use object discarded after the handler returns needs none of t
- **FIX: Prove outbox atomicity with rollback tests — force the commit to fail and assert no event escaped** — when you see: a write-then-publish path whose atomicity is asserted by code review only
    → add a forced-rollback integration test asserting entity rolled back AND no event dispatched
    why: A save-interceptor throws when the entity commits; the test asserts both that the entity rolled back and that no event was dispatched. On the broken code the order rolled back but the event had alread
- **FIX: Structured logging: message templates with placeholders, summaries not per-item lines, no null scope keys** — when you see: interpolated log strings, per-item logging in a loop, or nullable values added to log scopes
    → templates + placeholders; summary logs; guard scope keys and use ordinal comparers
    why: Templates ('User {UserId} logged in') keep logs queryable and are required for correlation scopes; interpolation/concatenation destroys both. Tight loops log a summary count, not per-item lines. Scope
- **FIX: Deleting or renaming a file requires grepping for the old path in the same PR** — when you see: git mv / git rm without a repo-wide grep for the old path
    → grep and sweep every reference to the old path in the same PR; wire a hook + CI link audit as the mechanical catch
    why: References live in docs, inline comments, Dockerfile COPY lines, project references, CI run: blocks, and review-bot config — none of which the compiler checks. the .NET platform's Dockerfile.catalog r
- **FIX: Error responses: generic detail + trace ID only — the full W3C traceparent leaks server call structure** — when you see: an error body carrying exception details, entity IDs, or a full traceparent string
    → generic ProblemDetails + bare trace ID; details to server logs keyed by that ID
    why: Clients get RFC 7807 ProblemDetails with a correlation trace ID; internal state, entity IDs, and stack traces stay in server logs. Subtlety: expose Activity.TraceId (32 hex chars), NOT Activity.Id — t

> 8 lower-ranked record(s) were trimmed to keep this briefing short. Raise --limit or narrow the task if you expected more.
