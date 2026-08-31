# .NET microservices profile

Canon extracted verbatim from the .NET platform (`.NET 10 / Aspire / RabbitMQ-Wolverine / gRPC / EF Core`).
Installed to `.claude/rules/` as path-scoped rule files (load only when matching files are in context):

- `architecture.md` — VSA + DDD + CQRS; consumer-substitution interface rule; VSA→Clean promotion signal
- `security.md` — IDOR→404, JWT ClockSkew, server-controlled fields, rate-limiter scale-out
- `performance-and-data.md` — DbContext-direct (no repository wrappers), EF projection, async, Guid v7
- `messaging.md` — Wolverine/RabbitMQ topology, outbox atomicity, handler-discovery≠DI, gRPC/REST versioning

Has a React frontend? The React canon is a **separate, backend-agnostic profile** — stack it on:
`okl scaffold --profile dotnet --profile react`.
