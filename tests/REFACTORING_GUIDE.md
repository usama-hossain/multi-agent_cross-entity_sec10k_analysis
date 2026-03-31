"""
REFACTORING GUIDE: Converting Tests to Project Standards
=======================================================

This document explains the gaps and provides a pattern for refactoring all unit tests.

## COMPLIANCE GAPS IN CURRENT TESTS

### 1. ❌ Using unittest instead of pytest
**Before (Current):**
```python
class BlobStorageAdapterUnitTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
    
    def test_blob_adapter__given_account_url__initializes(self):
        ...
```

**After (pytest standard):**
```python
@pytest.fixture
def original_env():
    env = os.environ.copy()
    yield env
    os.environ.clear()
    os.environ.update(env)

def test_blob_adapter__given_account_url__initializes(original_env):
    ...
```

### 2. ❌ Missing @pytest.mark.unit decorator
**Before:**
```python
def test_html_to_pdf__given_html_with_script__removes_script(self):
    ...
```

**After:**
```python
@pytest.mark.unit
def test_html_to_pdf__given_html_with_script__removes_script():
    ...
```

### 3. ❌ Repetitive mock setup (not DRY)
**Before:**
```python
def setUp(self):
    mock_exists.return_value = True
    os.environ["DOC_INTEL_ENDPOINT"] = "https://..."
    service = PDFToMarkdownService()
```

Repeated 10+ times in each test file.

**After (using fixtures):**
```python
@pytest.fixture
def mock_doc_intel_endpoint(monkeypatch):
    """Standard Document Intelligence endpoint for tests."""
    endpoint = "https://myintelligence.cognitiveservices.azure.com/"
    monkeypatch.setenv("DOC_INTEL_ENDPOINT", endpoint)
    return endpoint

@pytest.fixture
def doc_intel_service(mock_doc_intel_endpoint, mocker):
    """Initialized service with mocked client."""
    with patch("src.services.pdf_to_markdown.DocumentIntelligenceClient") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        service = PDFToMarkdownService()
        service._client = mock_instance
        return service

# Use in tests
def test_pdf_to_markdown__given_valid_pdf__calls_api(doc_intel_service):
    # No setup needed - fixture handles it
    result = doc_intel_service.convert("/path/to/doc.pdf")
    ...
```

### 4. ❌ Inconsistent assertion messages
**Before (weak):**
```python
self.assertTrue(result)
self.assertIsNotNone(result)
```

**After (expressive):**
```python
assert result is not None, (
    f"PDF conversion should return content.\n"
    f"File: {pdf_path}\n"
    f"Result: {result}"
)
```

### 5. ❌ Not using parameterization
**Before (repeated code):**
```python
def test_html_to_sanitize__given_html_with_script__removes_script(self):
    html = '<script>alert("xss")</script>'
    sanitized = service._sanitize_html_for_xhtml2pdf(html)
    self.assertNotIn("<script>", sanitized)

def test_html_to_sanitize__given_html_with_iframe__removes_iframe(self):
    html = '<iframe src="http://evil.com"></iframe>'
    sanitized = service._sanitize_html_for_xhtml2pdf(html)
    self.assertNotIn("<iframe", sanitized)

def test_html_to_sanitize__given_html_with_object__removes_object(self):
    html = '<object></object>'
    sanitized = service._sanitize_html_for_xhtml2pdf(html)
    self.assertNotIn("<object", sanitized)
```

**After (parametrized):**
```python
@pytest.mark.parametrize("dangerous_html,dangerous_tag", [
    ('<script>alert("xss")</script>', "<script>"),
    ('<iframe src="http://evil.com"></iframe>', "<iframe"),
    ('<object></object>', "<object"),
    ('<embed />', "<embed"),
])
def test_html_to_sanitize__given_dangerous_tags__removes_all(self, dangerous_html, dangerous_tag):
    sanitized = service._sanitize_html_for_xhtml2pdf(dangerous_html)
    assert dangerous_tag not in sanitized, (
        f"'{dangerous_tag}' should be removed from sanitized HTML.\n"
        f"Input: {dangerous_html}\n"
        f"Output: {sanitized}"
    )
```

### 6. ❌ Test classes using unittest structure
**Before:**
```python
class HTMLToPDFServiceUnitTests(unittest.TestCase):
    def setUp(self):
        self.service = HTMLToPDFService()
    
    def test_...(self):
        ...
```

**After (pytest classes for organization):**
```python
class TestHTMLToPDFSanitization:
    """Tests for HTML sanitization logic."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = HTMLToPDFService()
    
    def test_...(self):
        ...


class TestHTMLToPDFConversion:
    """Tests for PDF rendering."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = HTMLToPDFService()
    
    def test_...(self):
        ...
```

---

## REFACTORING CHECKLIST FOR EACH TEST FILE

For each file (`test_*.py`), apply these steps:

### Step 1: Convert to pytest and add marker
- [ ] Remove `import unittest`
- [ ] Remove `class XxxUnitTests(unittest.TestCase):`
- [ ] Remove `setUp()` and `tearDown()` methods
- [ ] Add `@pytest.mark.unit` to each test
- [ ] Organize tests into logical test classes (TestXxxFunctionality, TestXxxErrors, etc.)

### Step 2: Extract shared setup into fixtures
- [ ] Identify common setup patterns
- [ ] Create pytest fixtures (@pytest.fixture) for:
  - Environment variables (use `monkeypatch`)
  - Service initialization
  - Common mock objects
  - Test data (use factory pattern for complex objects)

### Step 3: Parameterize repeated tests
- [ ] Find tests with nearly identical structure
- [ ] Replace with single parameterized test using `@pytest.mark.parametrize`
- [ ] Reduces code by 50-70% typically

### Step 4: Improve assertion messages
- [ ] Add explanatory messages to ALL assertions
- [ ] Include context: input values, expected vs actual
- [ ] Follow pattern: `assert X == Y, f"Explanation.\nExpected: {Y}\nGot: {X}"`

### Step 5: Remove magic values
- [ ] Extract hardcoded strings/numbers to named constants or fixtures
- [ ] Create fixture for "standard" test values

---

## EXAMPLE: Refactoring blob_storage_adapter.py

### Current Structure (150+ lines, hard to maintain):
```
class BlobStorageAdapterUnitTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
        for key in [...]:
            os.environ.pop(key, None)
    
    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)
    
    @patch("src.adapters.blob_storage.DefaultAzureCredential")
    @patch("src.adapters.blob_storage.BlobServiceClient")
    def test_blob_adapter__given_account_url_and_managed_identity__initializes(self, ...):
        mock_credential_instance = MagicMock()
        mock_credential.return_value = mock_credential_instance
        mock_service_instance = MagicMock()
        mock_blob_service.return_value = mock_service_instance
        mock_container = MagicMock()
        mock_service_instance.get_container_client.return_value = mock_container
        ...
```

### Refactored Structure (~80 lines, easier to maintain):
```
@pytest.fixture
def clean_env_vars():
    """Isolate environment for blob storage tests."""
    original = os.environ.copy()
    for key in ["BLOB_ACCOUNT_URL", "AzureWebJobsStorage", "BLOB_CONTAINER_NAME"]:
        os.environ.pop(key, None)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture
def mock_blob_service(mocker):
    """Mocked BlobServiceClient for all tests."""
    return mocker.patch("src.adapters.blob_storage.BlobServiceClient")


@pytest.fixture
def mock_azure_credential(mocker):
    """Mocked DefaultAzureCredential."""
    return mocker.patch("src.adapters.blob_storage.DefaultAzureCredential")


@pytest.mark.unit
class TestBlobStorageAdapterInitialization:
    """Initialization behavior with various auth methods."""
    
    def test_adapter__given_account_url_and_identity__initializes_with_credential(
        self, clean_env_vars, mock_blob_service, mock_azure_credential, monkeypatch
    ):
        """Verify adapter uses managed identity when BLOB_ACCOUNT_URL is set."""
        # Arrange
        monkeypatch.setenv("BLOB_ACCOUNT_URL", "https://myaccount.blob.core.windows.net")
        monkeypatch.setenv("BLOB_CONTAINER_NAME", "test-container")
        
        mock_credential = MagicMock()
        mock_azure_credential.return_value = mock_credential
        
        mock_service = MagicMock()
        mock_blob_service.return_value = mock_service
        
        mock_container = MagicMock()
        mock_service.get_container_client.return_value = mock_container
        mock_container.exists.return_value = True
        
        # Act
        adapter = AzureBlobArtifactStore()
        
        # Assert
        mock_azure_credential.assert_called_once()
        assert adapter.container_client == mock_container
```

---

## FILES REQUIRING REFACTORING (Priority Order)

High Priority (most used):
- [ ] test_blob_storage_adapter.py
- [ ] test_blob_paths.py (delete old version, use test_blob_paths_refactored.py)
- [ ] test_sec_edgar_markdown_service.py
- [ ] test_sec_edgar_sections_service.py

Medium Priority:
- [ ] test_html_to_pdf_service.py
- [ ] test_pdf_to_markdown_service.py
- [ ] test_signal_card_batch_service_errors.py

Apply the pattern from test_blob_paths_refactored.py to all of these.

---

## New Testing Tools Needed

Update requirements.txt to include:
- `pytest` (already likely present)
- `pytest-cov` (for coverage reports)
- `pytest-mock` (for mocker fixture instead of manual mocking)
- `pytest-xdist` (for parallel test execution)

Add to conftest.py:
```python
# tests/conftest.py
"""Shared fixtures for all tests."""
import pytest
import os


@pytest.fixture
def clean_env():
    """Isolate environment for each test."""
    original = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original)
```

---

## BENEFITS AFTER REFACTORING

✅ 40-50% less test code (less duplication)
✅ 10x faster to add new tests (copy/parametrize pattern)
✅ Fewer test maintenance issues (change fixture = fix all uses)
✅ Better IDE support (pytest fixtures autocomplete)
✅ Parallel test execution support
✅ Easier CI debugging (clearer test names, better failure output)
✅ Follows project standards (compliance)
"""
