# Modularity Contracts (Phase 3)

## Status
- Active contracts are defined for ingestion and storage-state domains.
- Non-ingestion domains are intentionally deferred in this phase.

## Public Contract Principles
- Orchestration code consumes service methods, not storage-client internals.
- State identity is accession-centered for idempotent behavior.
- Queue and state payload changes must preserve compatibility unless migration is included.
- Domain-specific modules own their own status/validation semantics.

## Transitional Policy
- Preserve current behavior contracts first (characterization tests).
- Refactor internals behind stable external behavior.
- Prefer additive contract evolution over breaking contract changes.
