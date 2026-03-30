# Testing Guide

This project now supports a one-command test workflow with fast mocked tests and optional live smoke tests.

## One Command

From project root:

```bash
bash scripts/run_tests.sh
```

What this does:
- Runs all unit tests in `tests/unit`
- Runs integration live smoke tests in `tests/integration` only if `RUN_LIVE_BATCH_TESTS=true`

You can also run tests from VS Code with one click:
- Command Palette -> `Tasks: Run Task` -> `Run All Tests`
- Or use the Testing panel (`Run All`) with unittest discovery enabled in `.vscode/settings.json`

## Test Types

### 1) Unit tests (default)
- No real OpenAI calls
- No real Azure Storage calls
- Fast and deterministic

### 2) Optional live smoke tests
- File: `tests/integration/test_live_batch_smoke.py`
- Disabled by default
- Executes real OpenAI Batch API calls when enabled

Enable live smoke tests:

```bash
export RUN_LIVE_BATCH_TESTS=true
bash scripts/run_tests.sh
```

Enable full completion smoke test (submit -> poll -> fetch -> parse):

```bash
export RUN_LIVE_BATCH_TESTS=true
export RUN_LIVE_BATCH_COMPLETE=true
export LIVE_BATCH_TIMEOUT_SECONDS=900
export LIVE_BATCH_POLL_SECONDS=10
bash scripts/run_tests.sh
```

## Required Environment Variables and Secrets

### Core app/runtime vars
- `AzureWebJobsStorage`: Storage account connection string (queues + table + blob if using connection string auth)
- `BLOB_CONTAINER_NAME`: Blob container name (default `sec-filings`)
- `SEC_STATE_TABLE_NAME`: Table name (default `SECProcessingState`)
- `SEC_STATE_PARTITION_KEY`: Partition key (default `Utility_10K_2026`)

### OpenAI vars (for signal card batch)
- `OPENAI_API_KEY`: required
- `OPENAI_MODEL`: optional (default from code)
- `AZURE_OPENAI_ENDPOINT`: optional; set if using Azure OpenAI endpoint
- `OPENAI_API_VERSION`: optional for Azure OpenAI mode

### Live smoke test flags
- `RUN_LIVE_BATCH_TESTS=true`: enables live smoke test module
- `RUN_LIVE_BATCH_COMPLETE=true`: enables completion polling test
- `LIVE_BATCH_TIMEOUT_SECONDS`: optional timeout for completion test
- `LIVE_BATCH_POLL_SECONDS`: optional polling interval

## Storage Access Requirements

For local/Codespaces execution you need one of:

1. Connection-string based access
- Set `AzureWebJobsStorage` to a valid account connection string
- Ensure permissions on Blob/Queue/Table for that account

2. Managed Identity / AAD (if used)
- `BLOB_ACCOUNT_URL` configured
- Identity granted:
  - `Storage Blob Data Contributor`
  - `Storage Queue Data Contributor`
  - `Storage Table Data Contributor` (or equivalent table data role)

## Network Access Requirements

Allow outbound HTTPS from your environment to:
- OpenAI (or Azure OpenAI endpoint)
- `*.blob.core.windows.net`
- `*.queue.core.windows.net`
- `*.table.core.windows.net`
- `www.sec.gov` and `data.sec.gov` for SEC metadata/data flows

If running in GitHub Codespaces:
- Ensure repo/environment secrets are mapped into runtime env vars
- Ensure no organization policy blocks outbound to OpenAI/Azure Storage endpoints

## Recommended CI/Local Strategy

- Run unit suite on every commit (default command, no secrets)
- Run live smoke tests manually or on protected branch only
- Keep live smoke tests optional to avoid cost/flakiness in normal dev loops
