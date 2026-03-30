# Modularity Boundaries (Phase 1)

This document defines Phase 1 ownership boundaries for ingestion and storage/state.
It is a conformance map for refactor work and code review.

## Context Ownership

- Ingestion orchestration:
  - File scope: `function_app.py`
  - Responsibility: request parsing, routing, service coordination, queue handoff.
  - Must not: read/write table schema fields directly.

- SEC retrieval/parsing domain:
  - File scope: `src/services/sec_downloader.py`, `src/services/sec_edgar_markdown.py`, `src/services/sec_edgar_sections.py`
  - Responsibility: SEC metadata lookup, filing download, document parsing support.
  - Must not: own processing lifecycle status transitions.

- Storage/state domain:
  - File scope: `src/services/processing_state.py`
  - Responsibility: accession-based lifecycle persistence, status validation, idempotent updates.
  - Must not: perform SEC retrieval, conversion, or extraction orchestration.

- Artifact storage adapter:
  - File scope: `src/services/sec_downloader.py` (`BlobArtifactStore`)
  - Responsibility: blob existence/read/write operations for filing artifacts.
  - Must not: own SEC metadata filtering decisions.

## Conformance Rules

1. No cross-context schema leakage.
- Ingestion code calls state service methods; it does not construct table entities.

2. No cross-context business leakage.
- State service defines status behavior; SEC services do not define lifecycle transitions.

3. Separation inside ingestion service layer.
- SEC API concerns and blob I/O concerns are separate responsibilities.

4. Backward compatibility during extraction.
- Existing call sites may continue to use compatibility facades while boundaries are being extracted.

## Current Phase 1 Implementation Notes

- `BlobArtifactStore` introduced in `src/services/sec_downloader.py` to own blob I/O.
- `SECDownloaderService` now delegates blob operations to `BlobArtifactStore` via compatibility methods.
- `ProcessingStateService` module-level ownership is explicitly documented as the processing lifecycle source of truth.

## Current Phase 2 Implementation Notes

- Port contracts introduced in `src/core/ports.py`:
  - `SecFilingsPort`
  - `BlobStoragePort`
  - `ProcessingStatePort`
  - `QueueClientPort`
  - `MarkdownConversionPort`
  - `SectionExtractionPort`
  - `SignalCardExtractionPort`
  - `BatchServicePort`
- Blob path construction centralized in `src/core/blob_paths.py` (`BlobPaths`).
- Azure blob implementation moved to adapter layer:
  - `src/adapters/blob_storage.py` (`AzureBlobArtifactStore`)
  - `src/services/sec_downloader.py` keeps `BlobArtifactStore` as compatibility alias.
- Orchestration dependency wiring added in `function_app.py` with composition helpers:
  - `_build_kickoff_dependencies`
  - `_build_worker_dependencies`
  - `_build_reconciler_dependencies`
  - `_build_reset_dependencies`
- Function entrypoints now consume dependency bundles instead of directly coupling all logic to concrete classes at each call site.

## Current Phase 3 Implementation Notes

- Public reconciliation contract added in `src/core/ports.py`:
  - `PendingSignalCardBatch`
- Storage-state service now emits typed reconciliation contracts instead of raw table entities:
  - `src/services/processing_state.py` (`list_pending_signal_card_batches`)
- Orchestration reconciler now consumes contract objects and no longer depends on table-field names:
  - `function_app.py` (`signal_card_batch_reconciler`)
- Transitional compatibility preserved:
  - reconciler accepts legacy dict-shaped pending entities from tests/fakes via normalization helper.

## Current Phase 4 Implementation Notes

- Queue handoff contract typed in orchestration:
  - `function_app.py` (`KickoffQueueMessage`, `_build_kickoff_queue_message`, `_parse_worker_payload`)
- Backward-compatible payload evolution maintained:
  - existing queue fields unchanged; validation only enforces required `ticker` and `accession`.
- Exception payload hardening added for ingestion/storage paths:
  - bounded persisted/reported error text via `_bounded_error_message`.

## Out of Scope for Phase 1

- Interface package extraction and dependency injection composition root.
- Typed queue contract migration.
- Artifact path centralization into a dedicated path builder.
- Concurrency and batch-state hardening.
