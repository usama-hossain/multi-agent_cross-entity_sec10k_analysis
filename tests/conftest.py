"""
Shared pytest fixtures for all test modules.
Centralizes common setup/teardown logic and mocks to reduce duplication.

Includes:
  - Environment isolation (clean_env)
  - Azure credential mocks
  - Standard test data (endpoints, containers, paths)
  - Client mocks (Blob Storage, Document Intelligence, OpenAI)

Available to all tests in tests/ and subdirectories without explicit import.
"""

import os
import pytest
from unittest.mock import MagicMock, patch


# ========== ENVIRONMENT FIXTURES ==========

@pytest.fixture
def clean_env():
    """
    Isolate test environment by preserving and restoring environment variables.
    
    Ensures tests don't pollute global environment state.
    Clear all env vars at start of test, restore at end.
    """
    original = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture
def isolated_env(monkeypatch):
    """
    Monkeypatch-based environment isolation (alternative to clean_env).
    
    Useful when you want to set specific env vars with monkeypatch.setenv()
    and have them automatically cleaned up.
    """
    return monkeypatch


# ========== AZURE CREDENTIAL FIXTURES ==========

@pytest.fixture
def mock_azure_credential():
    """Mocked DefaultAzureCredential for testing."""
    with patch("src.services.pdf_to_markdown.DefaultAzureCredential") as mock:
        yield mock


@pytest.fixture
def mock_api_key_credential():
    """Mocked AzureKeyCredential for API key authentication."""
    with patch("src.services.pdf_to_markdown.AzureKeyCredential") as mock:
        yield mock


@pytest.fixture
def mock_blob_credential():
    """Mocked credential for Blob Storage authentication."""
    with patch("src.adapters.blob_storage.DefaultAzureCredential") as mock:
        yield mock


# ========== STANDARD TEST DATA FIXTURES ==========

@pytest.fixture
def standard_endpoint():
    """Standard Azure service endpoint for testing."""
    return "https://eastus.api.cognitive.microsoft.com/"


@pytest.fixture
def standard_connection_string():
    """Standard Azure Storage connection string for testing."""
    return "DefaultEndpointsProtocol=https;AccountName=testaccount;AccountKey=dGVzdGtleQ==;EndpointSuffix=core.windows.net"


@pytest.fixture
def standard_container():
    """Standard Azure Blob Storage container name."""
    return "test-container"


@pytest.fixture
def standard_company_name():
    """Standard company name for SEC/Edgar services."""
    return "EnergyAI"


@pytest.fixture
def standard_email():
    """Standard email for SEC/Edgar services."""
    return "research@example.com"


@pytest.fixture
def standard_api_key():
    """Standard API key for external services."""
    return "sk-test-key-12345"


@pytest.fixture
def sample_ticker():
    """Sample stock ticker for testing."""
    return "EQIX"


@pytest.fixture
def sample_accession():
    """Sample SEC filing accession number."""
    return "0001234567-23-000002"


@pytest.fixture
def sample_pdf_url():
    """Sample PDF URL for testing."""
    return "https://example.com/sample.pdf"


@pytest.fixture
def sample_html():
    """Sample HTML content for testing."""
    return """
    <html>
        <head><title>Test Document</title></head>
        <body>
            <h1>Test Heading</h1>
            <p>This is test content.</p>
        </body>
    </html>
    """


# ========== AZURE SERVICES CLIENT FIXTURES ==========

@pytest.fixture
def mock_blob_service_client():
    """Mocked BlobServiceClient."""
    with patch("src.adapters.blob_storage.BlobServiceClient") as mock:
        yield mock


@pytest.fixture
def mock_container_client():
    """Mocked ContainerClient."""
    with patch("src.adapters.blob_storage.ContainerClient") as mock:
        yield mock


@pytest.fixture
def mock_document_intelligence_client():
    """Mocked DocumentIntelligenceClient."""
    with patch("src.services.pdf_to_markdown.DocumentIntelligenceClient") as mock:
        yield mock


# ========== EXTERNAL SERVICES FIXTURES ==========

@pytest.fixture
def mock_openai_client():
    """Mocked OpenAI client."""
    with patch("src.services.signal_card_batch.OpenAI") as mock:
        yield mock


@pytest.fixture
def mock_beautiful_soup():
    """Mocked BeautifulSoup class."""
    with patch("src.services.html_to_pdf.BeautifulSoup") as mock:
        yield mock


# ========== EDGAR/SEC LIBRARY FIXTURES ==========

@pytest.fixture
def mock_set_identity():
    """Mocked edgar.set_identity function."""
    with patch("src.services.sec_edgar_markdown.set_identity") as mock:
        yield mock


@pytest.fixture
def mock_company_class():
    """Mocked edgar.Company class."""
    with patch("src.services.sec_edgar_markdown.Company") as mock:
        yield mock


@pytest.fixture
def mock_tenk_class():
    """Mocked edgar.TenK class."""
    with patch("src.services.sec_edgar_sections.TenK") as mock:
        yield mock


# ========== TEMPORARY FILES FIXTURES ==========

@pytest.fixture
def temp_output_path(tmp_path):
    """Temporary directory for test output files."""
    return tmp_path / "test_output.pdf"


@pytest.fixture
def temp_directory(tmp_path):
    """Temporary directory for test files."""
    return tmp_path


# ========== PYTEST CONFIGURATION ==========

def pytest_configure(config):
    """
    Configure pytest with custom markers and settings.
    """
    # Register custom markers
    config.addinivalue_line(
        "markers", "unit: Unit tests (isolated, single responsibility)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests (multiple components)"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests (full system)"
    )
    config.addinivalue_line(
        "markers", "slow: Slow tests (> 1 second)"
    )
    config.addinivalue_line(
        "markers", "network: Tests requiring network access"
    )
    config.addinivalue_line(
        "markers", "azure: Tests requiring Azure services"
    )


# ========== TEST COLLECTION HOOKS ==========

def pytest_collection_modifyitems(config, items):
    """
    Automatically add markers to tests based on module/class names.
    
    Pattern:
    - tests/unit/* -> @pytest.mark.unit
    - tests/integration/* -> @pytest.mark.integration
    - tests/e2e/* -> @pytest.mark.e2e
    """
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
