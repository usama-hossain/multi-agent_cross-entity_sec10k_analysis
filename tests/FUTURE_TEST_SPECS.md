# Test Specifications for Future Features

Every test written for this project must adhere to the following **Six Quality Attributes** and structural guidelines.

---

## Six Quality Attributes (Non-Negotiable)

### 1. **Maintainable**
- Test code is as clear as feature code.
- No magic numbers, hardcoded paths, or obscure assertions.
- Reusable fixtures and helper functions for common setups.
- Comments only where intent is non-obvious.
- Single responsibility per test function.

### 2. **Complete**
- Happy path **and** all documented error conditions.
- Boundary cases (empty, null, max, min values).
- State transitions and invariants.
- Covers the feature's documented contract end-to-end.

### 3. **Fast**
- Unit tests: < 100ms (or justify in docstring).
- Integration tests: < 2s per test.
- No unnecessary sleeps or retries in non-`live` tests.
- Prefer test data in memory over file I/O when possible.
- `live` tests isolated and skippable (marked with `@pytest.mark.live`).

### 4. **Isolated**
- Each test is independent; order doesn't matter.
- No shared global state; use fixtures for setup/teardown.
- Mock external services (SEC, OpenAI, Azure, DB, queues) in non-`live` tests.
- Temp directories (`tmpdir` fixture) for file I/O.
- No test should depend on another test's output.

### 5. **Reliable**
- Deterministic results (no flakiness).
- Failures are actionable (clear assertion message).
- No environment-specific assumptions (paths, credentials).
- Retry logic only in `live` tests (guarded by `@pytest.mark.live`).
- Failures point to the actual bug, not test setup issues.

### 6. **Expressive**
- Test name describes the behavior being tested.
- Arrange → Act → Assert pattern (clear structure).
- Assertion messages explain the "why," not just the "what."
- Schema validation is explicit, not implicit.
- Error messages include relevant context (IDs, values, state).

---

## Test Layer Definitions

### **Unit Tests** (`tests/unit/`)
- **Scope**: Single function or class in isolation.
- **Marker**: `@pytest.mark.unit`
- **Mocking**: Mock all external dependencies (files, network, DB, services).
- **Examples**: schema validation, string parsing, business logic branches.
- **Speed**: < 100ms per test.

### **Integration Tests** (`tests/integration/`)
- **Scope**: Multiple components wired together; real I/O and data structures.
- **Marker**: `@pytest.mark.integration`
- **Mocking**: Mock external services only (SEC, OpenAI, Azure, queues, external APIs).
- **Examples**: service-to-service calls, state transitions, reconciliation logic.
- **Speed**: < 2s per test.
- **Note**: Use controlled test fixtures (local files, test dicts, in-memory storage).

### **Live Smoke Tests** (`tests/integration/test_live_*.py`)
- **Scope**: Real external systems (SEC EDGAR, OpenAI, Azure Blob, etc.).
- **Marker**: `@pytest.mark.live`
- **Mocking**: None. Real credentials and endpoints.
- **Examples**: SEC filing fetch, PDF-to-markdown conversion, batch reconciliation against real storage.
- **Speed**: 5–60s per test (acceptable given external latency).
- **Guard**: Require explicit env var (e.g., `ENABLE_LIVE_TESTS=1`) or `--live` CLI flag.
- **Failure handling**: Log, don't fail silently; external timeouts are expected; report degraded mode.

### **End-to-End Tests** (`tests/e2e/`)
- **Scope**: Full feature workflow from kickoff to completion.
- **Marker**: `@pytest.mark.e2e`
- **Mocking**: Minimal; mock only external boundaries.
- **Examples**: full signal-card extraction pipeline with state tracking; complete batch reconciliation.
- **Speed**: < 10s (use test fixtures, not live data).

---

## Required Test Metadata

Every new test module should include:

```python
"""
Module: test_[feature_name].py
Purpose: [One-line description of what's tested]
Dependencies: [external systems or data files used; e.g., "SEC fixture", "mock OpenAI"]
Markers: unit | integration | live | e2e
"""
```

---

## Test Function Naming Convention

```
test_<subject>__<scenario>__<expected_outcome>
```

**Examples**:
- `test_signal_card_extractor__given_valid_html__returns_schema_conformant_dict`
- `test_reconciler__given_partial_state_failure__retries_and_logs`
- `test_sec_downloader__given_invalid_cik__raises_value_error`
- `test_batch_service__given_empty_queue__returns_empty_list_not_error`

---

## Acceptance Criteria Template

When writing a new test, confirm:

- [ ] Test name is expressive (describes behavior, not internal details).
- [ ] Arrange/Act/Assert sections are visually distinct.
- [ ] All inputs are either fixtures (parameterized) or explicitly generated.
- [ ] All assertions have explanatory messages (use pytest's `assert x == y, "msg"`).
- [ ] Test runs deterministically (same result every time).
- [ ] Test is independent (doesn't rely on other tests or global state).
- [ ] Test is fast (within layer speed budget).
- [ ] Error case: test includes a reasonable failure message, e.g., schema validation errors.

---

## Definition of Done for New Feature Tests

A feature is not complete until:

1. **Unit tests** exist for all business logic branches (happy path + errors).
2. **Integration tests** exist for service wiring and state transitions.
3. **Live smoke test** exists (if the feature touches external systems).
4. **All tests pass locally** with `pytest tests/ -v`.
5. **Tests are committed** to the feature branch.
6. **CI runs and passes** (see CI Policy below).
7. **Test coverage** is reviewed (target: ≥ 80% for new code).
8. **Test documentation** in this file is updated if a new test layer or marker is introduced.

---

## Flakiness and Reliability Policy

- **No flaky tests allowed in CI.** If a test fails intermittently, it's a bug.
- **Live tests are allowed to be slow** but must be deterministic (same data = same result).
- **Retries are only for live tests:** Do not add retry logic to unit/integration tests; instead, investigate the root cause.
- **Timeouts:** Set explicit timeouts in live tests; prefer fixture-based data over network waits.
- **Assertion messages must be actionable.** Example:
  ```python
  assert extracted_text == expected, (
      f"Extracted text mismatch.\n"
      f"Expected: {expected[:100]}...\n"
      f"Got: {extracted_text[:100]}...\n"
      f"Full HTML length: {len(html)}"
  )
  ```

---

## CI Test Policy

### **Pull Request (Pre-Merge)**
```bash
pytest tests/unit tests/integration -v --tb=short -m "not live"
```
- **Time**: < 30s
- **Markers excluded**: `live`
- **Result**: Must be 100% green to merge.

### **Nightly / Manual Full Run**
```bash
pytest tests/ -v --tb=short -m "unit or integration or e2e or live"
```
- **Time**: < 5 min
- **Markers included**: All
- **Result**: Actionable failures logged; live failures reported but don't block deployment.

### **Post-Deployment Smoke**
```bash
pytest tests/ -v --tb=short -m "live"
```
- **Time**: 2–5 min
- **Markers included**: `live` only
- **Result**: Confirms system health in production; failures notify on-call.

---

## Running Tests Locally

```bash
# All non-live tests (default)
./scripts/run_tests.sh --standard

# Only unit
pytest tests/unit -v

# Unit + integration
pytest tests/unit tests/integration -v -m "not live"

# Only integration + live
pytest tests/integration -v -m "live"

# Specific test
pytest tests/unit/test_signal_card_schema.py::test_validate_signal_card__valid_dict__passes -v
```

---

## Example Test Structure

```python
import pytest
from src.services.signal_card_extractor import extract_signal_card

@pytest.mark.unit
class TestSignalCardExtractor:
    """Unit tests for signal card extraction logic."""
    
    def test_extract_signal_card__given_valid_filing__returns_schema_conformant_dict(self):
        """Verify extraction produces valid schema-conformant output."""
        # Arrange
        filing_html = "<html><body>Test content</body></html>"
        
        # Act
        result = extract_signal_card(filing_html)
        
        # Assert
        assert isinstance(result, dict), "Result must be a dict."
        assert "ticker" in result, "Result must contain 'ticker' key."
        assert result["ticker"] is not None, "Ticker cannot be None."
    
    def test_extract_signal_card__given_empty_html__raises_value_error(self):
        """Verify extraction raises ValueError for empty input."""
        # Arrange
        filing_html = ""
        
        # Act & Assert
        with pytest.raises(ValueError, match="HTML content cannot be empty"):
            extract_signal_card(filing_html)
```

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-26 | Team | Initial spec: 6 quality attributes, 4 test layers, CI policy. |
