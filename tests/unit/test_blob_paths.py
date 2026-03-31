"""
Module: test_blob_paths.py
Purpose: Unit tests for BlobPaths utility covering path construction for all filing artifact types.
Dependencies: None (stateless utility, no external deps)
Markers: unit
"""

import pytest
from src.core.blob_paths import BlobPaths


# ========== FIXTURES (REUSABLE TEST DATA) ==========

@pytest.fixture
def sample_ticker():
    """Standard ticker for test cases."""
    return "EQIX"


@pytest.fixture
def sample_accession():
    """Standard accession for test cases."""
    return "0001234567-23-000002"


@pytest.fixture
def test_cases():
    """Parameterized test data: (ticker, accession) tuples."""
    return [
        ("EQIX", "0001628280-25-005126"),
        ("AEP", "0000004904-26-000013"),
        ("CEG", "0001868275-25-000023"),
        ("DUK", "0001326160-25-000072"),
        ("NEE", "0000067066-26-000011"),
        ("SO", "0000102993-26-000019"),
    ]


# ========== RAW HTML PATH TESTS ==========

class TestBlobPathsRawHtml:
    """Tests for BlobPaths.raw_html() path construction."""

    def test_raw_html__given_valid_ticker_and_accession__returns_correct_path(self, sample_ticker, sample_accession):
        """Verify raw_html constructs standard path: raw/html/{ticker}/{accession}/10-K.html"""
        # Act
        result = BlobPaths.raw_html(sample_ticker, sample_accession)

        # Assert
        expected = f"raw/html/{sample_ticker}/{sample_accession}/10-K.html"
        assert result == expected, (
            f"Raw HTML path format mismatch.\n"
            f"Expected: {expected}\n"
            f"Got: {result}"
        )

    @pytest.mark.parametrize("ticker,accession", [
        ("EQIX", "0001628280-25-005126"),
        ("TEST123", "0009999999-99-999999"),
        ("A", "0000000001-00-000001"),  # Edge: min lengths
    ])
    def test_raw_html__given_various_tickers_and_accessions__preserves_input_format(self, ticker, accession):
        """Verify raw_html preserves ticker and accession exactly as provided."""
        # Act
        result = BlobPaths.raw_html(ticker, accession)

        # Assert
        assert ticker in result, f"Ticker '{ticker}' should appear in path: {result}"
        assert accession in result, f"Accession '{accession}' should appear in path: {result}"

    def test_raw_html__raw_path_structure__has_correct_prefix(self):
        """Verify raw html paths start with 'raw/html/' prefix."""
        # Act
        result = BlobPaths.raw_html("TEST", "0001111111-11-111111")

        # Assert
        assert result.startswith("raw/html/"), f"Path should start with 'raw/html/': {result}"
        assert result.endswith("10-K.html"), f"Path should end with '10-K.html': {result}"


# ========== MARKDOWN PATH TESTS ==========

class TestBlobPathsMarkdown:
    """Tests for BlobPaths.markdown() path construction."""

    def test_markdown__given_valid_inputs__returns_correct_path(self, sample_ticker, sample_accession):
        """Verify markdown constructs standard path: processed/md/{ticker}/{accession}/10-K.md"""
        # Act
        result = BlobPaths.markdown(sample_ticker, sample_accession)

        # Assert
        expected = f"processed/md/{sample_ticker}/{sample_accession}/10-K.md"
        assert result == expected, (
            f"Markdown path format mismatch.\n"
            f"Expected: {expected}\n"
            f"Got: {result}"
        )

    @pytest.mark.parametrize("ticker,accession", [
        ("EQIX", "0001628280-25-005126"),
        ("DUK", "0001326160-25-000072"),
        ("123", "0000000001-00-000001"),  # Numeric ticker
    ])
    def test_markdown__various_tickers__path_format_consistent(self, ticker, accession):
        """Verify markdown path format is consistent across different inputs."""
        # Act
        result = BlobPaths.markdown(ticker, accession)

        # Assert
        parts = result.split("/")
        assert len(parts) == 5, f"Path should have 5 parts separated by '/': {result}"
        assert parts[0] == "processed", f"First part should be 'processed': {result}"
        assert parts[1] == "md", f"Second part should be 'md': {result}"
        assert parts[2] == ticker, f"Third part should be ticker '{ticker}': {result}"
        assert parts[3] == accession, f"Fourth part should be accession '{accession}': {result}"
        assert parts[4] == "10-K.md", f"Fifth part should be '10-K.md': {result}"


# ========== SECTION PATHS (ITEM 1A, ITEM 7) TESTS ==========

class TestBlobPathsItemSections:
    """Tests for BlobPaths.item1a() and item7() path construction."""

    def test_item1a__given_valid_inputs__returns_correct_path(self, sample_ticker, sample_accession):
        """Verify item1a constructs path: processed/md/{ticker}/{accession}/item1a.md"""
        # Act
        result = BlobPaths.item1a(sample_ticker, sample_accession)

        # Assert
        expected = f"processed/md/{sample_ticker}/{sample_accession}/item1a.md"
        assert result == expected, (
            f"Item 1A path mismatch.\n"
            f"Expected: {expected}\n"
            f"Got: {result}"
        )

    def test_item7__given_valid_inputs__returns_correct_path(self, sample_ticker, sample_accession):
        """Verify item7 constructs path: processed/md/{ticker}/{accession}/item7.md"""
        # Act
        result = BlobPaths.item7(sample_ticker, sample_accession)

        # Assert
        expected = f"processed/md/{sample_ticker}/{sample_accession}/item7.md"
        assert result == expected, (
            f"Item 7 path mismatch.\n"
            f"Expected: {expected}\n"
            f"Got: {result}"
        )

    def test_item1a_and_item7__same_filing__have_same_directory_hierarchy(
        self, sample_ticker, sample_accession
    ):
        """Verify item1a and item7 for same filing have identical directory structure."""
        # Act
        path_1a = BlobPaths.item1a(sample_ticker, sample_accession)
        path_7 = BlobPaths.item7(sample_ticker, sample_accession)

        # Assert - extract directory paths (everything except filename)
        dir_1a = "/".join(path_1a.split("/")[:-1])
        dir_7 = "/".join(path_7.split("/")[:-1])

        assert dir_1a == dir_7, (
            f"Item 1A and Item 7 should share directory hierarchy.\n"
            f"Item 1A dir: {dir_1a}\n"
            f"Item 7 dir: {dir_7}"
        )

    @pytest.mark.parametrize("ticker,accession", [
        ("EQIX", "0001628280-25-005126"),
        ("AEP", "0000004904-26-000013"),
        ("SO", "0000102993-26-000019"),
    ])
    def test_sections__various_filings__path_structure_consistent(self, ticker, accession):
        """Verify item1a/item7 paths follow consistent structure for various filings."""
        # Act
        path_1a = BlobPaths.item1a(ticker, accession)
        path_7 = BlobPaths.item7(ticker, accession)

        # Assert
        for path in [path_1a, path_7]:
            parts = path.split("/")
            assert parts[0] == "processed", f"Should use 'processed' prefix: {path}"
            assert parts[1] == "md", f"Should use 'md' subdirectory: {path}"
            assert parts[2] == ticker, f"Should include ticker: {path}"
            assert parts[3] == accession, f"Should include accession: {path}"


# ========== SIGNAL CARD PATH TESTS ==========

class TestBlobPathsSignalCard:
    """Tests for BlobPaths.signal_card() path construction."""

    def test_signal_card__given_valid_inputs__returns_correct_path(self, sample_ticker, sample_accession):
        """Verify signal_card constructs path: processed/signals/{ticker}/{accession}/signal_card.json"""
        # Act
        result = BlobPaths.signal_card(sample_ticker, sample_accession)

        # Assert
        expected = f"processed/signals/{sample_ticker}/{sample_accession}/signal_card.json"
        assert result == expected, (
            f"Signal card path mismatch.\n"
            f"Expected: {expected}\n"
            f"Got: {result}"
        )

    @pytest.mark.parametrize("ticker,accession", [
        ("EQIX", "0001101239-26-000032"),
        ("AEP", "0000004904-26-000013"),
        ("CEG", "0001868275-25-000023"),
        ("DUK", "0001326160-25-000072"),
    ])
    def test_signal_card__various_filings__path_format_consistent(self, ticker, accession):
        """Verify signal_card path format is consistent across different filings."""
        # Act
        result = BlobPaths.signal_card(ticker, accession)

        # Assert
        parts = result.split("/")
        assert len(parts) == 5, f"Path should have 5 parts: {result}"
        assert parts[0] == "processed", f"Should use 'processed' prefix: {result}"
        assert parts[1] == "signals", f"Should use 'signals' subdirectory: {result}"
        assert parts[2] == ticker, f"Should include ticker: {result}"
        assert parts[3] == accession, f"Should include accession: {result}"
        assert parts[4] == "signal_card.json", f"Should end with 'signal_card.json': {result}"


# ========== PATH ISOLATION & UNIQUENESS TESTS ==========

class TestBlobPathsIsolation:
    """Tests ensuring different artifact paths don't collide."""

    def test_all_path_types__same_filing__produce_unique_paths(self, sample_ticker, sample_accession):
        """Verify different artifact types for same filing produce unique paths."""
        # Act
        paths = {
            "raw_html": BlobPaths.raw_html(sample_ticker, sample_accession),
            "markdown": BlobPaths.markdown(sample_ticker, sample_accession),
            "item1a": BlobPaths.item1a(sample_ticker, sample_accession),
            "item7": BlobPaths.item7(sample_ticker, sample_accession),
            "signal_card": BlobPaths.signal_card(sample_ticker, sample_accession),
        }

        # Assert - all paths should be distinct
        path_list = list(paths.values())
        unique_paths = set(path_list)
        assert len(unique_paths) == len(path_list), (
            f"All paths should be unique. Duplicates found:\n"
            f"{paths}"
        )

    def test_same_function_different_tickers__produce_different_paths(self, sample_accession):
        """Verify same function with different tickers produces different paths."""
        # Arrange
        ticker1, ticker2 = "EQIX", "DUK"

        # Act
        path1 = BlobPaths.signal_card(ticker1, sample_accession)
        path2 = BlobPaths.signal_card(ticker2, sample_accession)

        # Assert
        assert path1 != path2, (
            f"Different tickers should produce different paths.\n"
            f"Ticker1 ({ticker1}): {path1}\n"
            f"Ticker2 ({ticker2}): {path2}"
        )
        assert ticker1 in path1 and ticker1 not in path2, f"Path1 should have ticker1: {path1}"
        assert ticker2 in path2 and ticker2 not in path1, f"Path2 should have ticker2: {path2}"

    def test_same_function_different_accessions__produce_different_paths(self, sample_ticker):
        """Verify same function with different accessions produces different paths."""
        # Arrange
        accession1 = "0001111111-11-111111"
        accession2 = "0002222222-22-222222"

        # Act
        path1 = BlobPaths.signal_card(sample_ticker, accession1)
        path2 = BlobPaths.signal_card(sample_ticker, accession2)

        # Assert
        assert path1 != path2, (
            f"Different accessions should produce different paths.\n"
            f"Accession1: {path1}\n"
            f"Accession2: {path2}"
        )


# ========== EDGE CASE TESTS ==========

class TestBlobPathsEdgeCases:
    """Tests for boundary and unusual input handling."""

    @pytest.mark.parametrize("ticker", [
        "A",           # Single character
        "A1",          # Mixed alphanumeric
        "123",         # Numeric only
        "VERY_LONG_TICKER_NAME",  # Long name
    ])
    def test_paths__various_ticker_formats__constructs_valid_paths(self, ticker):
        """Verify paths handle various ticker formats without error."""
        # Arrange
        accession = "0001111111-11-111111"

        # Act & Assert - should not raise
        path_raw = BlobPaths.raw_html(ticker, accession)
        path_sig = BlobPaths.signal_card(ticker, accession)

        assert ticker in path_raw, f"Ticker should appear in raw path: {path_raw}"
        assert ticker in path_sig, f"Ticker should appear in signal path: {path_sig}"

    def test_paths__accession_with_all_zeros__handles_gracefully(self, sample_ticker):
        """Verify paths handle accession with all zeros."""
        # Arrange
        accession = "0000000000-00-000000"

        # Act
        result = BlobPaths.signal_card(sample_ticker, accession)

        # Assert
        assert accession in result, f"All-zero accession should appear in path"
        assert result.endswith("signal_card.json"), "Path should still be valid JSON signal card path"

    def test_paths__accession_with_sequential_digits__handles_gracefully(self, sample_ticker):
        """Verify paths handle sequential digit accessions."""
        # Arrange
        accession = "0123456789-12-345678"

        # Act
        result = BlobPaths.item1a(sample_ticker, accession)

        # Assert
        assert accession in result, f"Sequential accession should appear in path"
        assert result.endswith("item1a.md"), "Path should end with item1a.md"


# ========== CONSISTENCY & STRUCTURE TESTS ==========

class TestBlobPathsStructure:
    """Tests verifying overall path structure consistency."""

    @pytest.fixture
    def all_path_functions(self):
        """Helper to test all path functions consistently."""
        return [
            ("raw_html", BlobPaths.raw_html),
            ("markdown", BlobPaths.markdown),
            ("item1a", BlobPaths.item1a),
            ("item7", BlobPaths.item7),
            ("signal_card", BlobPaths.signal_card),
        ]

    def test_all_functions__given_valid_inputs__return_non_empty_strings(
        self, sample_ticker, sample_accession, all_path_functions
    ):
        """Verify all path functions return non-empty strings for valid inputs."""
        # Act & Assert
        for func_name, func in all_path_functions:
            result = func(sample_ticker, sample_accession)
            assert isinstance(result, str), (
                f"{func_name}() should return string, got {type(result)}"
            )
            assert len(result) > 0, f"{func_name}() should not return empty string"
            assert "/" in result, f"{func_name}() should have forward slash(es): {result}"

    def test_processed_paths__all_include_processed_prefix(self, sample_ticker, sample_accession):
        """Verify all processed artifact paths use 'processed/' prefix."""
        # Act
        processed_paths = [
            BlobPaths.markdown(sample_ticker, sample_accession),
            BlobPaths.item1a(sample_ticker, sample_accession),
            BlobPaths.item7(sample_ticker, sample_accession),
            BlobPaths.signal_card(sample_ticker, sample_accession),
        ]

        # Assert
        for path in processed_paths:
            assert path.startswith("processed/"), (
                f"Processed artifact should start with 'processed/': {path}"
            )

    def test_raw_path__uses_raw_prefix(self, sample_ticker, sample_accession):
        """Verify raw HTML path uses 'raw/' prefix."""
        # Act
        result = BlobPaths.raw_html(sample_ticker, sample_accession)

        # Assert
        assert result.startswith("raw/"), f"Raw HTML path should start with 'raw/': {result}"

    def test_all_paths__include_ticker_and_accession_in_hierarchy(
        self, sample_ticker, sample_accession, all_path_functions
    ):
        """Verify all paths include ticker and accession in directory structure."""
        # Act & Assert
        for func_name, func in all_path_functions:
            path = func(sample_ticker, sample_accession)
            assert sample_ticker in path, (
                f"{func_name}(): ticker should appear in path: {path}"
            )
            assert sample_accession in path, (
                f"{func_name}(): accession should appear in path: {path}"
            )
