# Contributor Quickstart

This guide is the shortest safe path to start making changes in this project.

## 1) What To Read First (in order)

1. `.github/copilot-instructions.md`
2. `.github/instructions/modularity-core.instructions.md`
3. `.github/instructions/ingestion-layer.instructions.md`
4. `.github/instructions/storage-state-layer.instructions.md`

You can ignore other scoped instruction files for now. They are placeholders.

## 2) Active Scope Right Now

Only these scoped domains are currently active:

- Ingestion orchestration and SEC retrieval
- Storage/state persistence and lifecycle transitions

## 3) Core Rules You Must Preserve

### Ingestion contract
- Tickers are normalized, trimmed, deduplicated, and validated.
- Ingestion targets 10-K filings and currently caps at 5 filings per ticker.
- Kickoff remains idempotent: skip completed, skip explicit error-state entries, enqueue partials, and download/upload only for new accessions.
- Queue payload compatibility is preserved unless a planned migration is included.

### Storage/state contract
- Accession remains the identity key for filing state/idempotency behavior.
- Status updates must be validated against allowed status sets.
- Mutations remain explicit and minimal (only intended fields are changed).
- Every mutation updates UTC timestamp fields.
- Persisted error text remains bounded and actionable.

## 4) How To Work Safely

1. Decide whether your change is ingestion-facing or storage-state-facing.
2. Read only the relevant scoped instruction file above plus global instructions.
3. Keep module responsibilities focused; do not mix SEC fetch logic with state mutation internals.
4. If behavior changes, update tests first or in the same change.

## 5) Required Test Practice

- Use unit tests for orchestration/state logic.
- Mock external systems in non-live tests (SEC, Azure Blob/Queue/Table, OpenAI).
- Assert positive and negative side effects.

Run focused ingestion/state tests:

```bash
python -m unittest tests.unit.test_ingestion_ticker_loading tests.unit.test_ingestion_kickoff_filtering tests.unit.test_ingestion_kickoff_state_paths tests.unit.test_sec_downloader_characterization
```

## 6) When You Need Broader Rules

Use these only when intentionally expanding architecture/instruction scope:

- `.github/instructions/modularity-contracts.md`
- `.github/instructions/instruction-governance.md`

## 7) Simple Decision Tree

- Changing kickoff, ticker selection, SEC metadata/download behavior -> follow ingestion rules.
- Changing status fields, transition setters, idempotency state checks -> follow storage-state rules.
- Changing both -> follow both and add tests for each touched contract.
