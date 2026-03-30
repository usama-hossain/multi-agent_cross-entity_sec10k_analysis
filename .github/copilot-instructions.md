# Copilot Instructions - Project1

## Modularity Program (6-Phase)

- Phase 1: Global modular rules are active in this file.
- Phase 2: Scoped rules are active only for ingestion and storage-state layers.
- Phase 3: Public module contracts are documented and should be respected.
- Phase 4: Exception and payload contract guidance is active for ingestion/storage flows.
- Phase 5: Governance checklist is active for all instruction updates.
- Phase 6: Manual conformance audit gate is required after instruction changes.
- Non-ingestion scoped layers are intentionally placeholders for now.

## Canonical Modularity Source

- Primary modular architecture guidance across all layers is defined in `.github/instructions/modularity-core.instructions.md`.
- When a request mentions modular design, SOLID, bounded contexts, interface-driven design, low coupling, or architecture refactoring, apply that file first.
- Layer-specific instruction files refine the core rules and must not contradict the canonical source.

## Module Boundaries and Dependency Direction

- Keep business domains separated: ingestion, storage-state, conversion, signal-cards.
- Prefer one-way dependencies from orchestrators to services, and from services to core utilities/schemas.
- Do not introduce reverse imports from storage-state into ingestion orchestration internals.
- Do not couple orchestration code to table field shape when service methods can express intent.
- Add behavior by extending via new classes/functions where possible instead of rewriting stable paths.

## Interface and Coupling Rules

- Depend on service-level operations (get, upsert, set status, enqueue) rather than storage/client details.
- Keep queue payload contracts backward compatible unless a coordinated migration is included.
- Keep module responsibilities focused: orchestration, domain retrieval, state persistence, conversion, extraction.
- Avoid cross-domain helper leakage; shared generic helpers belong in `src/core`.

## Contracts and Transition Policy

- Current public modular contracts are documented in `.github/instructions/modularity-contracts.md`.
- Use transitional policy: preserve current behavior contracts first, then evolve internals behind tests.
- New fields in state or message payloads should be additive and optional-first where practical.

## Exception and Payload Principles

- Use explicit, contextual logging with ticker/accession for ingestion/storage flows.
- Fail fast on missing mandatory configuration.
- Keep error messages actionable and bounded for persisted storage fields.
- Prefer typed payload models for queue/state handoffs when introducing new contract surfaces.

## Testing Standards

- Write characterization tests before refactoring existing workflows: lock current behavior first, then refactor behind those tests.
- Prefer unit tests for service and orchestration logic; mock all external dependencies (SEC endpoints, Azure Blob/Queue/Table, OpenAI) in non-live tests.
- Keep tests deterministic and isolated: no network, no real cloud resources, no cross-test shared state.
- Cover both positive and negative paths: happy path, boundary cases, validation errors, and state-transition branches (including skip/no-op paths).
- Assert outcomes and side effects: response payloads, status transitions, queued messages, storage writes, and explicit "did not happen" checks.
- Use clear Arrange-Act-Assert structure and behavior-focused test names.
- Organize tests by behavior/domain in small cohesive modules; avoid monolithic test files.
- Reuse shared fakes/helpers for common setup, but keep assertions local to each test's intent.
- Keep tests focused on contract/behavior, not internal implementation details.

## Ingestion-Layer Specific Guidance

- Preserve ticker loading contract: normalization, deduplication, stable ordering, and empty-config failure behavior.
- Preserve kickoff contract: storage precondition checks, ticker filter validation, and per-accession routing behavior.
- Preserve idempotency contract: skip when artifacts already exist, skip error-state entries, enqueue existing partials, and download/upload only for new filings.
- Preserve SEC metadata contract: include only 10-K filings and respect the 5-filing cap/order.

## Execution Guidance

- Run targeted unit tests for changed behavior first, then run broader unit discovery.
- If a test fails, fix root cause (or test contamination) rather than weakening assertions.

## Instruction Governance

- Follow governance checklist in `.github/instructions/instruction-governance.md` for all instruction changes.
- Use narrow `applyTo` scopes; avoid broad catch-all patterns unless truly cross-cutting.
- Keep scoped instruction files small, non-overlapping, and contract-focused.
- Run and document a manual conformance audit after instruction updates (scope, overlap, and validation checks).
