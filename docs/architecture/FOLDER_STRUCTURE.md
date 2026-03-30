# Folder Structure Guide

This document defines the target folder structure for Project1 and the responsibility of each area. This is a structural baseline only; existing files are intentionally not migrated yet.

## Top-Level Layout

- `src/`: Application code
- `tests/`: Automated tests and test assets
- `config/`: Runtime and project configuration files
- `infra/`: Infrastructure as code and deployment assets
- `scripts/`: Operational and developer utility scripts
- `data/`: Local data assets used for development/testing workflows
- `docs/`: Project documentation
- `logs/`: Local runtime logs (non-source artifacts)

## Source Code Layout (`src/`)

- `src/functions/`: Azure Function handlers and trigger entrypoints
- `src/services/`: Business logic and use-case orchestration
- `src/services/sec/`: SEC-specific domain/service logic
- `src/services/processing/`: Pipeline processing state and workflow logic
- `src/services/signal_cards/`: Signal-card generation and related workflows
- `src/schemas/`: Pydantic models and data contracts
- `src/core/`: Shared internals (logging, settings, constants, helpers)
- `src/adapters/`: External system adapters (Azure, OpenAI, SEC clients)

## Test Layout (`tests/`)

- `tests/unit/`: Fast isolated unit tests
- `tests/integration/`: Component wiring and integration behavior tests
- `tests/e2e/`: End-to-end workflow tests
- `tests/fixtures/`: Shared fixtures and reusable test data

## Scripts Layout (`scripts/`)

- `scripts/admin/`: Environment/state maintenance scripts
- `scripts/testing/`: Test execution and diagnostic scripts

## Data and Docs

- `data/raw/`: Source or ingested raw data
- `data/processed/`: Processed/intermediate local outputs
- `docs/architecture/`: Architecture notes and diagrams
- `docs/testing/`: Testing policies and test strategy docs

## Notes

- Existing folders were preserved as-is.
- Missing folders were created to establish a stable, layered structure.
- File migration and import-path updates are a separate follow-up step.
