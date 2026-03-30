---
applyTo: "function_app.py,src/**/*.py,tests/**/*.py,scripts/**/*.py"
description: "Global modular architecture rules. Use when user asks for modular, SOLID, bounded context, interface-driven, low coupling, refactor-safe design, or architecture principles."
---

# Modularity Core Rules (Canonical)

## Bounded Contexts
- Keep ingestion orchestration, document retrieval/parsing, persistence/state, and downstream triggering as separate modules.
- Prevent cross-cutting business logic leakage between these contexts.

## Dependency Inversion
- Define storage and external-service interfaces in the core/domain layer.
- Implement Azure Blob/Table/Queue and other providers in adapter modules.

## Single Responsibility
- Each class/function should do one job: load inputs, validate, transform, persist, enqueue, or reconcile.
- Expose minimal APIs.

## Pure Core, Impure Edges
- Keep domain rules and transformations side-effect free.
- Isolate I/O (network, filesystem, cloud SDK calls) behind adapter boundaries.

## Explicit Contracts
- Use typed request/response models and schema validation at module boundaries.
- Avoid implicit coupling and contract drift.

## Idempotency by Design
- Ingestion and storage operations must be replay-safe.
- Use stable keys, dedupe checks, and upsert semantics.

## Deterministic State Transitions
- Represent processing states explicitly (queued, downloading, parsed, stored, failed, retriable).
- Enforce legal transition rules.

## Error Taxonomy and Policy
- Distinguish validation, transient, and terminal failures.
- Centralize retry/backoff/dead-letter behavior instead of ad hoc try/except logic.

## Configuration Over Hardcoding
- Centralize environment/config resolution and inject settings.
- Keep modules environment-agnostic and testable.

## Observability First
- Use structured logs, correlation IDs, metrics, and traceable state changes across ingestion/storage paths.

## Backward-Compatible Evolution
- Version message/schema contracts and persistence formats.
- Avoid breaking existing data and in-flight jobs.
- Extend by adding new implementations where possible; avoid rewriting stable domain behavior unless contract changes are intentional.

## Testability at Every Seam
- Unit tests for core logic.
- Contract tests for adapters.
- Thin integration tests for real storage boundaries.
- Avoid hidden global state.

## Minimal Shared Utilities
- Prefer small, stable shared primitives (serialization, clocks, IDs, retries).
- Avoid god helper modules.

## Explicit Composition Root
- Wire dependencies in one place (startup/factory), not inside business modules.
- Make storage/provider swapping straightforward.

## Performance and Concurrency Safety
- Support batching/streaming where needed.
- Avoid duplicate work under concurrent execution.
- Preserve consistency under retries.
