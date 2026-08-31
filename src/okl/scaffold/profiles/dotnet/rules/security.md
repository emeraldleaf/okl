---
description: Security rules — IDOR, JWT, server-controlled fields, rate limiting
paths: ["**/Endpoints/**/*.cs", "**/Features/**/*.cs", "**/ServiceDefaults/**/*.cs", "**/Program.cs"]
---

# Security (.NET microservices)

> Ported verbatim from the .NET platform CLAUDE.md "Security Requirements". Each rule earned its place from a
> dated defect.

## Authorization — the IDOR pattern (CWE-639)

A missing scope check is an IDOR, and IDORs slip through tests-by-omission. Canonical buyer-scoped shape:

- Endpoint reads `ClaimTypes.NameIdentifier` from the JWT → passes as `RequestingBuyerId` into the query/command.
- **Read handlers push the ownership predicate INTO the EF `Where` clause** (`Where(o => o.Id == OrderId && o.BuyerId == RequestingBuyerId)`). Non-owner rows never leave the DB — tighter than a post-materialization C# check a buggy refactor could weaken.
- **Write handlers** load the aggregate tracked, check ownership on the loaded entity, return `false`/`null` on mismatch (NOT throw, NOT 403).
- Endpoint translates `null`/`false` → **404**. Returning **403 leaks existence** ("this exists, just not yours"). 404 is indistinguishable from "not found."
- **An integration test asserting buyer X cannot read buyer Y's entity is REQUIRED** for every new scoped-entity endpoint. Its absence is how the original `GET /orders/{id}` IDOR survived the codebase's lifetime.

## JWT validation (explicit, not implicit)

- `ValidateIssuerSigningKey = true` (explicit is auditable).
- `ClockSkew = TimeSpan.FromSeconds(30)` — the default is **5 minutes**, which on 5-minute access tokens doubles every token's effective lifetime.
- `ValidateAudience` / `ValidateIssuer` / `ValidateLifetime` all `true`.
- **`RequireHttpsMetadata` is fail-closed outside Development** — never derived silently from the authority scheme. An http authority in Production must fail loudly at startup (plaintext OIDC/JWKS = MITM can inject signing keys). Legitimate internal-http opts out explicitly via `Authentication:RequireHttpsMetadata=false` (logs a warning).
- Keycloak token policy pinned in `auth-realm.json`, never realm defaults: 5-min access tokens, single-use rotated refresh tokens, session idle 30m / max 10h.

## Server-controlled fields — computed server-side, never trusted from the client

Money (price, currency, tax), authorization identifiers (`BuyerId`/`SellerId` — must match JWT `sub`),
state-machine columns (`Status`), and security flags (`IsAdmin`, `IsDeleted`) are server-controlled.
A `[FromBody]` DTO with a `Price` field is a price-tampering vuln (client submits `Price = 0.01` for a
$999 product). The handler fetches the authoritative value from its source (CatalogService gRPC for
`Price`+`Currency`, JWT `sub` for buyer identity, DB for `Status`) and uses *that* — the request DTO is
untrusted input.

## Error handling & transport security

- Never expose internal state, stack traces, or entity IDs. Response `traceId` uses `Activity.TraceId.ToString()` (32 hex) only, NOT `Activity.Id` (the full W3C traceparent leaks span structure).
- HTTPS redirection enforced in prod; explicit CORS allowing only known frontend origins.
- **Rate limiting on search + payment endpoints minimum.** In-memory limiters silently weaken to N× the limit at N instances — swap to a Redis-backed limiter once a service runs 2+ instances, with the `INCR`+`EXPIRE` pair wrapped in a Lua `EVAL` for atomicity. Single-instance today = in-memory is correct *for now* + a comment naming the swap trigger.
