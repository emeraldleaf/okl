## OKL briefing — orders-api · task: Add GET /orders/{order_id} that returns one order as JSON for the authenticated caller. Follow the existing style in app/main.py.
_11 relevant node(s) from the org's encoded body._

### ✅ Do this (routed actions)
- **ARM: Gate every executable directory; lint each import-tree from its own root** — when you see: lint clean locally but I001/import-order fails in CI, or a dir has no gate at all
    → one lint step per import-tree run from that tree's root; add every shipping dir to CI trigger paths
    catches: Code outside the linter/type/scan source-roots is gated by nothing, ruff isort is CWD-anchored: sibling imports sort differently from a subdir vs the repo root
    why: Add each shipping dir to the CI trigger paths and the lint/type/scan invocation. Subtlety: ruff's isort first-party detection is CWD-anchored, so `ruff check ../otherdir` from a subpackage classifies 
- **FIX: Missing ownership scope check is an IDOR (CWE-639) and slips through tests-by-omission** — when you see: an endpoint fetches an entity by id with no owner/tenant predicate
    → add the caller's owner id to the WHERE clause; return 404 (not 403) on no match
    why: A resource endpoint that doesn't scope by the caller's identity leaks other users' data. Portable fix: push the ownership predicate INTO the query (read handlers) or check on the tracked entity (write
- **FIX: Code outside the linter/type/scan source-roots is gated by nothing** — when you see: a .py/.ts/.cs dir ships code but appears in no linter/type/scan source-root and no CI trigger path
    → add the dir to CI trigger paths + the lint/scan invocation; list remaining ungated zones in the ledger
    why: Python under olmoearth_run_data/ and docs/ was covered by no linter, no type-checker, no Sonar rule, and no AI-review path rule: CI ran ruff only on the package, sonar.sources listed three dirs, CodeR
- **FIX: Unpinned linter/formatter in CI retro-fails a branch that changed nothing** — when you see: a CI lint/format/type step fails on code the PR didn't change, right after a tool release
    → pin the exact tool version; treat bumps as deliberate PRs that address the new findings
    why: CI ran `pip install ruff` (unpinned). A new release (0.15→0.16) promoted rules to default (RUF059, I001, RUF012, SIM117) and failed a previously-green branch on pre-existing code the PR never touched.
- **FIX: Prove outbox atomicity with rollback tests — force the commit to fail and assert no event escaped** — when you see: a write-then-publish path whose atomicity is asserted by code review only
    → add a forced-rollback integration test asserting entity rolled back AND no event dispatched
    why: A save-interceptor throws when the entity commits; the test asserts both that the entity rolled back and that no event was dispatched. On the broken code the order rolled back but the event had alread
- **FIX: Pick ONE error-flow canon and name the flip triggers — here: exceptions at the handler boundary, no Result<T>** — when you see: a Result<T>-style return introduced into an exception-canon codebase (or vice versa)
    → follow the declared canon; flip only when a named trigger fires, repo-wide
    why: Expected business errors throw at the handler boundary and a global handler translates to RFC 7807 ProblemDetails. The Result/OneOf/ErrorOr pattern is defensible (exhaustiveness, allocation-cheap) but
- **FIX: The aggregate pattern only earns its keep when someone observes the invariant — otherwise it's ceremony** — when you see: a factory + private setters + status enum on a type nothing persists or re-reads
    → reserve the aggregate shape for persisted, invariant-bearing entities; inline validation elsewhere
    why: Persisted entities with non-trivial invariants get factories, private setters, and method-guarded state changes. But an in-memory, single-use object discarded after the handler returns needs none of t
- **FIX: Error responses: generic detail + trace ID only — the full W3C traceparent leaks server call structure** — when you see: an error body carrying exception details, entity IDs, or a full traceparent string
    → generic ProblemDetails + bare trace ID; details to server logs keyed by that ID
    why: Clients get RFC 7807 ProblemDetails with a correlation trace ID; internal state, entity IDs, and stack traces stay in server logs. Subtlety: expose Activity.TraceId (32 hex chars), NOT Activity.Id — t
- **FIX: An identifier sweep is done when grep returns zero — not when the docs you remembered are updated** — when you see: a removal PR that updates 'the docs I remembered' with no grep-to-zero check
    → grep every removed public identifier to zero across md/comments/CI/scripts; tombstone it so CI holds the line
    why: The compiler catches stale identifiers in code; nothing catches them in prose. Memory-based sweeps left 15+ docs teaching the removed transport as current, plus a metric documented as THE alarm that n
- **FIX: Long-running work belongs on the message bus — reshape >~1s write paths as 202 Accepted** — when you see: a synchronous HTTP handler (or message handler) doing multi-second work inline
    → persist a tracking row + publish + return 202; throttled per-item messages for fan-out
    why: Validate, persist a tracking row (the aggregate being created can BE the tracking row), publish a message, return 202 immediately. The same rule applies inside message handlers: minutes-scale work mov
- **FIX: Principal-vs-resource authorization adapts at the transport edge — handlers never see HttpContext or claims** — when you see: a handler reaching into HttpContext/ClaimsPrincipal
    → adapt auth context to domain values at the endpoint; dispatch clean commands/queries
    why: The JWT principal and HttpContext are HTTP concepts; application-layer handlers must not know about them. The endpoint compares the authenticated user's claim to the requested resource owner (or passe

> 7 lower-ranked record(s) were trimmed to keep this briefing short. Raise --limit or narrow the task if you expected more.
