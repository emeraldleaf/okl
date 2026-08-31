---
description: Wolverine / RabbitMQ messaging, outbox, gRPC, versioning rules
paths: ["**/Program.cs", "**/Features/**/*.cs", "**/*RecoveryJob*.cs"]
---

# Communication patterns (.NET — Wolverine / RabbitMQ / gRPC)

> Ported verbatim from the .NET platform CLAUDE.md. Each bullet is a dated distributed-systems trap.

## Transport & topology

- **Messaging transport is RabbitMQ** in every environment (dev matches prod). Wolverine maps saga pub/sub onto fanout exchanges (one per event family) with a queue per consumer. **Azure Service Bus was evaluated and removed** — its local emulator can't run the saga; re-add only if Azure becomes a real target.
- **Fanout exchanges silently DISCARD unroutable messages; AutoProvision declares topology lazily per service.** An event published before a consumer's first boot is dropped while the outbox marks it delivered. Rule: **each publisher declares its own exchange AND its consumers' queues+bindings** (`BindExchange(...).ToQueue(...)`), names from `MessagingExchanges`/`MessagingQueues` constants — never inline literals (a typo'd name is auto-provisioned as an empty object and the consumer starves silently).
- **Wolverine durability is per-direction.** `UseDurableOutboxOnAllSendingEndpoints()` covers ONLY the send side; default listeners are buffered (acked before handlers run — a crash loses the buffer). Store-backed services call `UseDurableInboxOnAllListeners()`; store-less services use `.ProcessInline()`. Every new `ListenToRabbitQueue` gets one of the two.
- **Durability ≠ replay.** Durable pub/sub (RabbitMQ durable queues + transactional outbox + idempotent handlers) does NOT lose messages. Reach for a stream (Kafka/Event Hubs/Redis Streams) only when you need replay-from-offset, multi-day retention, an ordered append-only log, or N independent re-reading consumers — not merely "don't lose messages."

## Outbox atomicity

- **Transactional publishing must use the enlisted context, NOT constructor-injected `IEventPublisher`.** Only the `IMessageContext` Wolverine injects as a `HandleAsync` parameter (or an `IDbContextOutbox` in non-handler code) is enlisted in the outbox transaction. A constructor-injected `IMessageBus`/`IEventPublisher` publishes inline under Wolverine 6 — before commit — breaking outbox atomicity.
- **Outbox outside a handler:** `BeginTransactionAsync` → entity write + `PublishAsync` → **`SaveChangesAsync`** → `CommitAsync`. Skipping the `SaveChangesAsync` between publish and commit silently drops the staged envelope.

## Handler discovery, gRPC, REST versioning

- **Wolverine handler discovery is NOT DI registration — two separate containers.** `opts.Discovery.IncludeAssembly(...)` builds Wolverine's internal message→handler map; Wolverine constructs handlers itself. `serviceProvider.GetRequiredService<MyHandler>()` throws unless you also `AddScoped<MyHandler>()`. The path that hits this is integration tests resolving handlers directly — every such handler needs an explicit `AddScoped<T>()`.
- **No `IRequestHandler`/`IFooHandler` interface per handler.** Handlers are plain classes; Wolverine's bus is the abstraction. Handler interfaces fail the consumer-substitution test the same way `IFooRepository` did.
- **gRPC** (sync) for real-time inter-service queries, versioned via `.proto` `package`. **REST** (HTTP) for frontend only, URL-segment versioned — always `app.MapV1ApiGroup("Tag", "resource")`, never hand-rolled `NewVersionedApi(...).MapGroup(...).HasApiVersion(...)` chains.

## Package management (Aspire)

- Central Package Management via `Directory.Packages.props`; `.csproj` references packages without versions.
- **Aspire SDK and runtime packages must match** (minor included) — bump together. **Aspire 13+ Azure resources need explicit local-dev fallbacks** (gate on `IsPublishMode`). **`WithReference(x)` ≠ wait-for-healthy** — every `WithReference` on a non-trivial dependency gets a matching `.WaitFor(x)`.
