---
description: SOLID / DDD / VSA architecture rules for .NET microservices
paths: ["**/*.cs"]
---

# Architecture (.NET microservices — VSA + DDD + CQRS)

> Ported verbatim from the .NET platform CLAUDE.md. Stack: .NET 10, Aspire, RabbitMQ (Wolverine),
> gRPC, EF Core, React. DDD + CQRS + event-driven.

## Vertical Slice Architecture is the default for every service

- Organize by **feature**, not by kind. `ServiceName/Features/` holds one file per use case:
  command/query record + validator + handler co-located. Saga event-handlers live here too.
- `Domain/` holds only what is *genuinely shared* across features — aggregates, value objects, enums,
  and consumer-substitution ports. `Infrastructure/` holds EF Core, caching, gateways, DI. `Program.cs`
  is the composition root.
- **Feature-file soft cap ~300 lines.** Past it, extract the validator or line-item record into a
  sibling file in `Features/` — the cap is on size, not file-count-per-slice.
- **Don't apply both VSA and Clean across one service.** Pick one shape per service and commit. The
  cross-service pattern diff is intentional — it's the project's lesson, not an inconsistency.

## Promotion signal — when to consider Clean Architecture

- VSA stays the default. Consider a multi-project split ONLY at 5+ aggregates per service with
  cross-cutting domain rules several features coordinate on, AND `Domain/` growing faster than `Features/`.
- The **dependency rule** (Domain → nothing; IO at the edges) is already in force in VSA at every scale —
  it is not complexity-gated. Only the multi-project *structure* is gated.
- Escalate enforcement as the cost of a violated boundary rises: **convention → architecture tests
  (NetArchTest/analyzer) → project split.** The middle rung enforces the same boundary the 4-project
  split does, deterministically, without the project ceremony. Reach for the split only when you want
  the *compiler* (not a test) to hold the line, or need separate deploy/versioning units.

## SOLID (the load-bearing parts)

- Domain → nothing. Application → Domain. Infrastructure → Domain + Application. Api → all (composition root).
- A service with no domain entities doesn't need a Domain project — ports (`I*Sender`, `I*Resolver`)
  live in `Application/Interfaces/`.
- **Interfaces earn their keep through consumer substitution, not "future swap."** A port/adapter
  interface is justified only if **(a)** it's substituted by tests today (`grep "Substitute.For<IFoo"`),
  **(b)** 2+ concrete impls are registered today, or **(c)** a second impl is on a *concrete* near-term
  roadmap. If none hold, it's speculative coupling — delete it, take the concrete class.
- **Factory / `[FromKeyedServices]` is the shape ONCE condition (b) holds — not before.** A factory
  that returns the same single impl for every input is the same speculative coupling as a deleted
  `I*Repository`. Introduce it the day the second impl actually ships.

## DDD

- **Rich domain entities only when someone observes the invariant.** Persisted entity with non-trivial
  observable invariants → state changes go through methods, never public setters, with validating
  `static Create()` factories. In-memory, single-use, discarded-after-handler → skip the aggregate shape,
  inline the validation or use a FluentValidation rule.
- Value objects for Money (amount+currency), Quantity (non-negative). Aggregates control their children —
  no mutable collection exposure (`IReadOnlyList<T>` over `private readonly List<T>`; add via `AddLine()`).
- Domain events for state changes that affect other bounded contexts.
