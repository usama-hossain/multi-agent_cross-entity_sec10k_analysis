---
applyTo: "src/services/processing_state.py,src/services/processing/**/*.py"
description: "Use when editing processing state, status transitions, state persistence, or storage-layer idempotency behavior."
---

# Storage and State Layer Rules

## Scope
- Applies to table-state persistence, status transition methods, and state query/update behavior.
- This layer is the source of truth for processing lifecycle and retry-safe idempotency.

## Design Constraints
- Single responsibility:
  - State modules define and enforce lifecycle status transitions.
  - Do not add SEC retrieval, file conversion, or LLM extraction logic here.
- Interface-driven:
  - Expose explicit state operations (get, upsert, set_status, list_pending) as the only contract consumed by orchestration.
  - Keep callers unaware of table field layout where possible.
- Open/closed:
  - Add new status domains via constants and dedicated setter methods.
  - Avoid breaking existing status semantics used by running workflows.
- Low coupling:
  - No imports from signal-card extraction or conversion modules.
  - No business branching based on queue/message structure.

## Behavioral Contracts
- Preserve accession-based identity and idempotency semantics.
- Validate all status writes against allowed status sets.
- Keep transition updates minimal and explicit (only intended fields updated).
- Preserve partition/table defaults unless migration steps are included.
- Include UTC update timestamps on every mutation.

## Error Handling and Safety
- Fail fast on missing storage configuration.
- Keep errors specific and bounded (truncate stored error messages safely).
- Prefer additive state fields over repurposing existing ones.

## Testing Requirements
- Unit tests must verify:
  - status validation rules,
  - transition behavior,
  - idempotent upsert semantics,
  - pending-batch selection logic where applicable.
- Mock table client in non-live tests and assert exact entities/fields written.
