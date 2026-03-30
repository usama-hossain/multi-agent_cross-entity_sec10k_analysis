# SEC 10-K State-Driven Processing (Current Refactor)

This refactor makes the pipeline state-aware so it does not re-download filings that are already in storage and tracked in table state.

## State-Driven Processing Flow

The pipeline uses table `SECProcessingState` as runtime source of truth with status values:

- `ready`
- `pdf_converted`
- `markdown_converted`
- `error`

Flow when kickoff is triggered:

1. Call SEC submissions API to fetch latest filing metadata and accession first (no file download yet).
2. Check ledger row by accession.
3. If status is `ready`, `pdf_converted`, or `markdown_converted`, skip HTML re-download.
4. If row is missing, download HTML once, upload blob, and write row as `ready`.
5. Route work by state:
	- `ready` -> enqueue HTML->PDF worker
	- `pdf_converted` -> enqueue PDF->Markdown worker
	- `markdown_converted` -> no-op
	- `error` -> no automatic retry (manual reset policy)

Worker behavior:

- HTML->PDF worker runs only for `ready`; on success updates to `pdf_converted`, on failure sets `error`.
- PDF->Markdown worker runs only for `pdf_converted`; on success updates to `markdown_converted`, on failure sets `error`.

Retry policy:

- Single attempt only. Failures are persisted as `error` and not auto-requeued.

## Runtime Configuration

Required/used settings in `config/local.settings.json`:

- `SEC_STATE_TABLE_NAME` (default `SECProcessingState`)
- `SEC_STATE_PARTITION_KEY` (default `Utility_10K_2026`)

If the table does not exist, runtime will create it using the same entity shape used by the original initialization script.

## Known Gaps / Constraints

- **Concurrency race is deferred:** simultaneous kickoff runs may still race before state write.
- **Partition key alignment required:** runtime partition key must match existing rows, or rows may appear "missing".
- **Single-attempt tradeoff:** transient failures remain in `error` until manual reset.
- **State/blob drift risk:** ledger and blob storage can become inconsistent if external changes occur.

## Future Improvements

- Add atomic claim/lease semantics around kickoff state transitions to prevent concurrent duplicate processing.