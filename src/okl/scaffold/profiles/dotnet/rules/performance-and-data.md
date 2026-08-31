---
description: EF Core, async, concurrency, pagination performance rules
paths: ["**/Features/**/*.cs", "**/Infrastructure/**/*.cs", "**/Domain/**/*.cs"]
---

# Performance & data correctness (.NET / EF Core)

> Ported verbatim from the .NET platform CLAUDE.md "Performance Rules" + "Data access". Always-on headlines;
> full rationale lives in the source repo's docs/performance-and-data-correctness.md.

## Data access: DbContext directly, no repository wrappers

- **Handlers take `DbContext` (or `IDbContextFactory<T>`) directly. No `IFooRepository` interfaces.**
  `DbContext` is already the Unit of Work; `DbSet<T>` is already the Repository. The only reason to wrap
  was unit-test mocking — replaced by integration tests against Testcontainers.
- **Reads project to DTOs inside the IQueryable:** `context.Orders.AsNoTracking().Where(...).Select(o => new OrderSummaryDto { ... }).ToListAsync(ct)` — in the handler, no method wrapping, no in-memory mapper. The projection IS the read contract. EF auto-splits projected collection navigations (no cartesian rows).
- **Writes load the aggregate tracked and call `SaveChangesAsync`.** Optimistic concurrency tokens fire on `SaveChanges`.
- **Exception: outbox-atomic non-handler code** (`BackgroundService` sweepers) needs an explicit transactional wrap (`BeginTransactionAsync` → work → `SaveChangesAsync` → `CommitAsync`) so Wolverine's staged outbox envelopes persist atomically.

## The always-on rules

- **Reads: `AsNoTracking()` + `.Select(...)` into a DTO inside the IQueryable.** Plain `AsNoTracking()` returning an entity is a half-fix.
- **No N+1** — `Include` or projection; never query inside a `foreach` over another query's results.
- **Non-sargable predicates defeat indexes — fix at write time.** `u.Email.ToLower() == x` can't use a B-tree index; normalize on insert (`EmailNormalized`) or use a case-insensitive collation. Leading-wildcard `LIKE '%text%'` needs `tsvector`/Elasticsearch when load justifies it.
- **Async on request paths:** `await` everywhere. Never `.Result`/`.Wait()`/`.GetAwaiter().GetResult()` (banned at build time). Every async method propagates `CancellationToken`.
- **Parallelize independent awaits with `Task.WhenAll`** — but not dependent ops, not a shared `DbContext` (use `IDbContextFactory<T>`), and when N calls hit the SAME service prefer a batch endpoint (one round-trip, server-atomic).
- **Long-running work (>~1s) belongs on the message bus** — reshape as 202 Accepted: validate + persist tracking row + publish Wolverine message + return. Same for handlers themselves.
- **Fan-out belongs on the message bus, not a synchronous handler loop** — one message per recipient/batch, throttled with `MaxDegreeOfParallelism`.
- **Pagination:** every list endpoint paginates with a server-side cap (≤100); keyset for large offsets.
- **Bulk ops:** `ExecuteUpdateAsync`/`ExecuteDeleteAsync`, never load thousands of rows to mutate.
- **Optimistic concurrency:** every updatable aggregate has a token (Postgres `xmin` or row-version). Last-write-wins is not acceptable.
- **Entity IDs use `Guid.CreateVersion7()`, not `Guid.NewGuid()`** — time-ordered, so PK inserts append-extend the B-tree index instead of fragmenting it. Apply in aggregate factories. (Not for IDs where mint time is sensitive.)
- **`DbContext` is not thread-safe** — parallel queries require `IDbContextFactory<T>`, one per task.
- **Migrations are immutable once applied** — destructive changes need a multi-step plan.
- **Measure before optimizing** — BenchmarkDotNet / `dotnet-counters` / `ToQueryString()`. No caching/compiled-queries/`AsSplitQuery()` on intuition.
- **Dapper is the sanctioned escape hatch from EF**, not a peer — only for provider-specific SQL, proven EF bottleneck, or LINQ-obscured aggregation; share the EF connection via `ctx.Database.GetDbConnection()`.
