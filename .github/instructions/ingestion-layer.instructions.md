---
applyTo: "function_app.py,src/services/sec_downloader.py,src/services/sec/**/*.py"
description: "Use when editing ticker ingestion, SEC fetch logic, kickoff orchestration, or ingestion queue handoff behavior."
---

# Ingestion Layer Rules

## Scope
- Applies to ticker ingestion, SEC metadata lookup, filing download decisions, and kickoff orchestration.
- Keep orchestration in `function_app.py` thin: coordinate services and routing, avoid embedding parsing/storage internals.

## Design Constraints
- Single responsibility:
  - `function_app.py` orchestrates and routes.
  - SEC service modules fetch/transform SEC data.
  - Storage state logic belongs in processing-state modules only.
- Open/closed:
  - Add new ticker sources, filters, or SEC retrieval strategies via new functions/classes.
  - Do not rewrite stable orchestration branches unless behavior must change.
- Low coupling:
  - Avoid direct knowledge of table schema details in ingestion orchestration.
  - Depend on service methods, not storage implementation details.

## Behavioral Contracts
- Preserve ticker loading contract: normalize to uppercase, trim, deduplicate while preserving first-seen order, fail on empty result.
- Preserve ingestion limit contract: only 10-K filings and max 5 filings per ticker unless explicitly changed.
- Preserve idempotent kickoff behavior:
  - Skip already-complete artifacts.
  - Skip explicit error-state accessions by default.
  - Re-enqueue existing partials without unnecessary re-downloads.
  - Download/upload only for new accessions.
- Queue payloads must remain backward compatible unless a coordinated migration is included.

## Error Handling
- Validate environment preconditions early (storage connection and required settings).
- Return structured, actionable errors for invalid request inputs.
- Log ticker and accession context for every failure branch.

## Testing Requirements
- Add/maintain unit characterization tests for any orchestration branch changes.
- Mock SEC/Azure/queue dependencies in non-live tests.
- Assert both positive side effects (enqueue/upload/upsert) and negative side effects (did not enqueue/download).
