class BlobPaths:
    @staticmethod
    def raw_html(ticker: str, accession: str) -> str:
        return f"raw/html/{ticker}/{accession}/10-K.html"

    @staticmethod
    def markdown(ticker: str, accession: str) -> str:
        return f"processed/md/{ticker}/{accession}/10-K.md"

    @staticmethod
    def item1a(ticker: str, accession: str) -> str:
        return f"processed/md/{ticker}/{accession}/item1a.md"

    @staticmethod
    def item7(ticker: str, accession: str) -> str:
        return f"processed/md/{ticker}/{accession}/item7.md"

    @staticmethod
    def signal_card(ticker: str, accession: str) -> str:
        return f"processed/signals/{ticker}/{accession}/signal_card.json"

    @staticmethod
    def ticker_insight(ticker: str) -> str:
        return f"processed/insights/{ticker}/ticker_insight.json"
