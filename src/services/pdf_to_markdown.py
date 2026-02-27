import os
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat

load_dotenv()  # Load environment variables from .env file

class PDFToMarkdownService:
    def __init__(self):
        # 1. Setup Identity
        self.credential = DefaultAzureCredential()

        # 2. Get Endpoint from Environment (set by Pipeline)
        self.endpoint = os.getenv("DOC_INTEL_ENDPOINT")
        self.key = os.getenv("DOC_INTEL_KEY")  # Optional: If using API Key instead of Identity
        # 3. Fetch Key from the Vault created by your Bicep
        # Note: 'kv-utility-...' name comes from your Bicep output or env
        # vault_url = os.getenv("KEY_VAULT_URL")


        print("--- Local Environment Validation ---")
        print(f"✅ Doc Intel Endpoint: {self.endpoint if self.endpoint else 'MISSING'}")
        print("------------------------------------\n")

        if not self.endpoint:
            raise EnvironmentError("Local setup failed. Check your src/.env file.")


        # Initialize the Document Intelligence Client
        if self.key:
            self.client = DocumentIntelligenceClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(self.key),
                api_version="2024-11-30"
            )
        else:
            self.client = DocumentIntelligenceClient(
                endpoint=self.endpoint,
                credential=self.credential
            )

    def convert(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = os.path.getsize(file_path)
        print(f"📊 Sending file: {os.path.basename(file_path)} ({file_size} bytes)")

        """Processes a local PDF and returns Markdown structure."""
        with open(file_path, "rb") as f:
            raw_content = f.read()

            poller = self.client.begin_analyze_document(
                "prebuilt-layout",
                raw_content,
                content_type="application/pdf",
                output_content_format=DocumentContentFormat.MARKDOWN
            )
        return poller.result().content

    def convert_pdf_bytes(self, pdf_content: bytes) -> str:
        poller = self.client.begin_analyze_document(
            "prebuilt-layout",
            pdf_content,
            content_type="application/pdf",
            output_content_format=DocumentContentFormat.MARKDOWN
        )
        return poller.result().content


if __name__ == "__main__":
    service = PDFToMarkdownService()

    target_file = "/workspaces/codespaces-blank/Project1/data/raw/sec-edgar-filings/DUK/10-K/0001326160-25-000072/primary-document.pdf"

    try:
        markdown_output = service.convert(target_file)

        print("\n--- Markdown Output ---")
        print(markdown_output[:1000])  # Print first 1000 chars for brevity
        print("-----------------------\n")

        with open("test_output.md", "w", encoding="utf-8") as md_file:
            md_file.write(markdown_output)

        print("Markdown saved to test_output.md")

    except Exception as e:
        print(f"Error during conversion: {e}")
