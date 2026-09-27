## OKL briefing — orders-api · task: Add GET /orders/search?q=<text> that returns the caller's orders whose item contains the text, case-insensitive.
_12 relevant node(s) from the org's encoded body._

### ✅ Do this (routed actions)
- **ARM: Gate every executable directory; lint each import-tree from its own root** — when you see: lint clean locally but I001/import-order fails in CI, or a dir has no gate at all
    → one lint step per import-tree run from that tree's root; add every shipping dir to CI trigger paths
    catches: Code outside the linter/type/scan source-roots is gated by nothing, ruff isort is CWD-anchored: sibling imports sort differently from a subdir vs the repo root
    why: Add each shipping dir to the CI trigger paths and the lint/type/scan invocation. Subtlety: ruff's isort first-party detection is CWD-anchored, so `ruff check ../otherdir` from a subpackage classifies 
- **FIX: Missing ownership scope check is an IDOR (CWE-639) and slips through tests-by-omission** — when you see: an endpoint fetches an entity by id with no owner/tenant predicate
    → add the caller's owner id to the WHERE clause; return 404 (not 403) on no match
    why: A resource endpoint that doesn't scope by the caller's identity leaks other users' data. Portable fix: push the ownership predicate INTO the query (read handlers) or check on the tracked entity (write
- **FIX: When a hazard is structural and no analyzer can express it, enforce it with a CI grep step** — when you see: a real hazard 'enforced' only by convention because no analyzer rule exists
    → encode it as a CI grep/audit step; ugly beats unenforced
    why: Static mutable collections are a real concurrency hazard the analyzer stack cannot detect (structural, not syntactic); the ban is enforced with a grep step in CI instead. An ugly-but-automated text ch
- **FIX: The aggregate pattern only earns its keep when someone observes the invariant — otherwise it's ceremony** — when you see: a factory + private setters + status enum on a type nothing persists or re-reads
    → reserve the aggregate shape for persisted, invariant-bearing entities; inline validation elsewhere
    why: Persisted entities with non-trivial invariants get factories, private setters, and method-guarded state changes. But an in-memory, single-use object discarded after the handler returns needs none of t
- **FIX: Tests are Arrange-Act-Assert with story comments — a junior reads the test and understands the contract without the SUT** — when you see: a security or concurrency test whose assertions don't say what failure they guard against
    → narrate the phases; number and justify multi-invariant assertions
    why: Each phase explains what's set up and why it matters, what's called, and what each assertion guards. Multi-invariant asserts are numbered with the why (especially security boundaries, idempotency guar
- **FIX: Encode every 'never again / always when' finding to the smallest surface that catches it — a fix PR without the rule is a half-finished job** — when you see: a merged fix for a recurring antipattern with no corresponding rule/gate change
    → land the rule with the fix (same or paired PR); track deferred encodings as labeled placeholders, never as the encoding itself
    why: Findings from any review surface get encoded the same session, into the smallest applicable layer: always-on canon only if every session needs it (keep it lean — size-budgeted in CI), else file-scoped
- **FIX: Prove outbox atomicity with rollback tests — force the commit to fail and assert no event escaped** — when you see: a write-then-publish path whose atomicity is asserted by code review only
    → add a forced-rollback integration test asserting entity rolled back AND no event dispatched
    why: A save-interceptor throws when the entity commits; the test asserts both that the entity rolled back and that no event was dispatched. On the broken code the order rolled back but the event had alread
- **FIX: An identifier sweep is done when grep returns zero — not when the docs you remembered are updated** — when you see: a removal PR that updates 'the docs I remembered' with no grep-to-zero check
    → grep every removed public identifier to zero across md/comments/CI/scripts; tombstone it so CI holds the line
    why: The compiler catches stale identifiers in code; nothing catches them in prose. Memory-based sweeps left 15+ docs teaching the removed transport as current, plus a metric documented as THE alarm that n
- **FIX: Pin every tool that gates CI; an unpinned linter is a time-bomb** — when you see: a CI gate step runs `pip install <tool>` / `npm i -g <tool>` with no version
    → pin the exact version; bumps are deliberate PRs
    why: Any tool whose output can fail a build — ruff, black, mypy, eslint, prettier, a Sonar scanner image — must be version-pinned in CI. Unpinned, the gate's behavior changes on the vendor's release cadenc
- **FIX: Rate-limit the endpoints backed by expensive unindexable queries — before one client can DOS the database** — when you see: an unauthenticated or expensive-query endpoint with no rate limit
    → named central policies, applied selectively; search/payment/auth first
    why: A search endpoint running a leading-wildcard LIKE cannot use an index well, so one scraping client could take down the database; a named fixed-window policy (30 req/10s, no queueing, 429 on reject) ap
- **FIX: Structured logging: message templates with placeholders, summaries not per-item lines, no null scope keys** — when you see: interpolated log strings, per-item logging in a loop, or nullable values added to log scopes
    → templates + placeholders; summary logs; guard scope keys and use ordinal comparers
    why: Templates ('User {UserId} logged in') keep logs queryable and are required for correlation scopes; interpolation/concatenation destroys both. Tight loops log a summary count, not per-item lines. Scope
- **FIX: Co-located feature files carry a soft size cap (~300 lines) — split into sibling files, not into layers** — when you see: a feature file well past ~300 lines, or a size complaint used to argue for layer folders
    → split into sibling files within the feature; keep the slice co-located
    why: One-file-per-use-case (command + validator + handler) is the canon, and 'giant file per slice' is its known failure mode. Past the cap, extract the validator or record types into sibling files in the 

> 9 lower-ranked record(s) were trimmed to keep this briefing short. Raise --limit or narrow the task if you expected more.
