import os
from azure.identity import DefaultAzureCredential # type : ignore
from azure.keyvault.secrets import SecretClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat

class HTMLToMarkdownService:
    def __init__(self):
        # 1. Setup Identity
        self.credential = DefaultAzureCredential()
        
        # 2. Get Endpoint from Environment (set by Pipeline)
        self.endpoint = os.getenv("DOC_INTEL_ENDPOINT")
        
        # 3. Fetch Key from the Vault created by your Bicep
        # Note: 'kv-utility-...' name comes from your Bicep output or env
        vault_url = os.getenv("KEY_VAULT_URL") 
        self.kv_client = SecretClient(vault_url=vault_url, credential=self.credential)
        
        # Pull the secret name we defined in Bicep
        self.key = self.kv_client.get_secret("DocIntelligenceApiKey").value

        # 4. Initialize Client
        self.client = DocumentIntelligenceClient(
            endpoint=self.endpoint, 
            credential=self.credential if not self.key else None, # Can use Key or Identity
            api_key=self.key
        )

    def convert(self, file_path: str) -> str:
        """Processes local HTML and returns Markdown structure."""
        with open(file_path, "rb") as f:
            poller = self.client.begin_analyze_document(
                "prebuilt-layout",
                AnalyzeDocumentRequest(bytes_source=f.read()),
                output_content_format=DocumentContentFormat.MARKDOWN
            )
        return poller.result().content