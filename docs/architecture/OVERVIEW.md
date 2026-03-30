# Project 1 — SEC 10-K Filing Ingestion Pipeline: Code Overview

This document is a top-down walkthrough of every file in the project. Its goal is to give a clear picture of what the system does, how data flows through it, and what each piece of code is responsible for.

For ingestion and storage/state ownership boundaries used during refactors, see `docs/architecture/MODULARITY_BOUNDARIES.md`.

---

## What This Project Does

This is an **automated data ingestion pipeline** that:

1. Downloads the latest annual 10-K filings (HTML) from the SEC EDGAR database for 5 major US utility companies.
2. Converts those HTML documents to PDF.
3. Converts the PDFs to structured Markdown using Azure AI Document Intelligence.
4. Stores all artifacts in Azure Blob Storage.
5. Tracks the processing state of each filing in Azure Table Storage so no work is repeated if the pipeline is re-run.

The 5 companies tracked are:

| Ticker | Company |
|--------|---------|
| NEE | NextEra Energy |
| DUK | Duke Energy |
| SO | The Southern Company |
| AEP | American Electric Power |
| CEG | Constellation Energy |

---

## Architecture at a Glance

```
HTTP POST /kickoff
       │
       ▼
 manual_kickoff (Azure Function)
       │
       ├─ Calls SEC EDGAR API → Downloads HTML → Uploads to Blob Storage
       │
       └─ Puts message on ──► [sec-html-jobs queue]
                                      │
                                      ▼
                          html_to_pdf_worker (Azure Function)
                                      │
                                      ├─ Reads HTML from Blob
                                      ├─ Converts HTML → PDF (Playwright / xhtml2pdf)
                                      ├─ Uploads PDF to Blob Storage
                                      │
                                      └─ Puts message on ──► [sec-pdf-jobs queue]
                                                                    │
                                                                    ▼
                                                     pdf_to_markdown_worker (Azure Function)
                                                                    │
                                                                    ├─ Reads PDF from Blob
                                                                    ├─ Sends to Azure AI Document Intelligence
                                                                    ├─ Receives Markdown back
                                                                    └─ Uploads Markdown to Blob Storage

Throughout all steps: Processing state is tracked in Azure Table Storage
```

---

## Entry Point: `function_app.py`

This is the **heart of the application**. It defines all three Azure Functions that make up the pipeline. Azure reads this file automatically when the Function App starts.

### Function 1: `manual_kickoff` (HTTP Trigger)

**Route:** `POST /api/kickoff`

This function is the "start button" for the entire pipeline. When called, it loops over all 5 tickers and decides what to do with each one, based on where it is in the processing lifecycle.

**Decision logic per ticker:**

| Current State in Table | What happens |
|---|---|
| `markdown_converted` | Skip — already fully processed |
| `error` | Skip — avoid retrying broken filings |
| `pdf_converted` | Enqueue directly to the **PDF queue** (HTML→PDF already done) |
| `ready` | Enqueue to the **HTML queue** (PDF conversion still needed) |
| `None` (new) | Download HTML from SEC → Upload to Blob → Create table record → Enqueue to **HTML queue** |

Returns a JSON summary: how many were enqueued to each queue, skipped, and which failed.

---

### Function 2: `html_to_pdf_worker` (Queue Trigger)

**Queue:** `sec-html-jobs`

Triggered automatically whenever a message lands in the `sec-html-jobs` queue. One message = one filing.

**What it does:**
1. Reads the queue message (contains ticker, accession number, blob paths).
2. Checks the filing's current status in Table Storage — guards against duplicate processing.
3. If the PDF doesn't already exist in Blob Storage, downloads the HTML blob and converts it to PDF.
4. Uploads the resulting PDF to Blob Storage.
5. Updates the filing's state to `pdf_converted`.
6. Puts a new message on the `sec-pdf-jobs` queue to hand off to the next step.

---

### Function 3: `pdf_to_markdown_worker` (Queue Trigger)

**Queue:** `sec-pdf-jobs`

Triggered automatically whenever a message lands in the `sec-pdf-jobs` queue.

**What it does:**
1. Reads the queue message.
2. Checks state — skips if already `markdown_converted`.
3. Downloads the PDF from Blob Storage.
4. Sends the PDF bytes to **Azure AI Document Intelligence** which returns structured Markdown.
5. Uploads the Markdown to Blob Storage.
6. Updates the filing's state to `markdown_converted`.

---

## Blob Storage Layout

All files live inside a single container (`sec-filings` by default):

```
sec-filings/
├── raw/html/{TICKER}/{ACCESSION}/10-K.html       ← Step 1: raw download
├── processed/pdf/{TICKER}/{ACCESSION}/10-K.pdf   ← Step 2: converted PDF
└── processed/md/{TICKER}/{ACCESSION}/10-K.md     ← Step 3: final Markdown
```

---

## `src/services/` — The Service Layer

These four files contain the business logic. The functions in `function_app.py` all delegate to these services.

---

### `sec_downloader.py` — `SECDownloaderService`

Everything related to talking to the SEC EDGAR API and Azure Blob Storage.

**Initialization:**
- Reads `SEC_COMPANY_NAME` and `SEC_EMAIL` from env vars to build a compliant `User-Agent` header. The SEC requires this on all API requests to prevent 403 errors.
- Connects to Azure Blob Storage — tries `BLOB_ACCOUNT_URL` first (managed identity, preferred for production), then falls back to a connection string from `AzureWebJobsStorage`.
- On startup, fetches and caches the full SEC ticker-to-CIK map from `https://www.sec.gov/files/company_tickers.json`. This map converts a ticker symbol (e.g., `NEE`) into a CIK number (an SEC internal ID required for API calls).

**Key methods:**

| Method | What it does |
|---|---|
| `fetch_latest_10k_metadata(ticker)` | Hits the SEC submissions API, finds the most recent 10-K filing, and returns its metadata (accession number, CIK, company name, download URL). |
| `download_filing_html(file_url)` | Downloads the raw HTML of the filing and returns it as bytes. |
| `blob_exists(blob_name)` | Checks if a given file already exists in Blob Storage (used to avoid re-uploading). |
| `upload_blob(blob_name, data, content_type)` | Uploads bytes to Blob Storage with optional MIME type. |
| `download_blob(blob_name)` | Downloads a file from Blob Storage and returns raw bytes. |
| `fetch_and_upload_10k(tickers)` | (Older utility method) Fetches and uploads 10-Ks in one shot — used for local testing. |

---

### `html_to_pdf.py` — `HTMLToPDFService`

Converts HTML documents to PDF. Handles the messy reality that SEC HTML filings contain external resources (scripts, images, remote stylesheets) that need to be stripped before rendering.

**Two rendering engines (with automatic fallback):**

1. **Primary: Playwright (Chromium headless browser)**
   - Launches a headless Chromium browser in a temp directory.
   - Intercepts and blocks all external HTTP/HTTPS network requests (security + reliability).
   - Renders the page and exports it with `page.pdf()`.
   - Most faithful rendering of complex HTML layouts.

2. **Fallback: xhtml2pdf (`pisa`)**
   - A pure-Python HTML-to-PDF library — no browser needed.
   - Less capable with complex layouts but works everywhere.
   - Used if Playwright fails (e.g., missing OS dependencies in a restricted environment).

**HTML sanitization (`_sanitize_html_for_xhtml2pdf`):**
Before either renderer runs, the HTML is cleaned:
- Removes `<script>`, `<iframe>`, `<object>`, `<embed>` tags.
- Strips explicit `height` attributes from table elements (prevents layout explosion).
- Removes `url(...)` references in CSS `style` attributes pointing to external servers.
- Removes external `<link>` tags and external `href` attributes.
- Removes `<img>` tags pointing to external URLs (only keeps data URIs).

**Key method:**

| Method | What it does |
|---|---|
| `convert_html_bytes(html_content: bytes) → bytes` | Full pipeline: decode → sanitize → try Playwright → fallback to xhtml2pdf. Used by the queue worker. |
| `convert(html_file_path, output_pdf_path)` | Local file wrapper — reads a file, converts, writes output. Used for local testing. |

---

### `pdf_to_markdown.py` — `PDFToMarkdownService`

Converts a PDF to structured Markdown using **Azure AI Document Intelligence** (formerly Form Recognizer).

**Initialization:**
- Reads `DOC_INTEL_ENDPOINT` from env vars.
- Authenticates with either an API key (`DOC_INTEL_KEY`) or Managed Identity (`DefaultAzureCredential`) — key takes priority if present.
- Raises `EnvironmentError` immediately on startup if the endpoint is missing.

**Key method:**

| Method | What it does |
|---|---|
| `convert_pdf_bytes(pdf_content: bytes) → str` | Sends PDF bytes to the `prebuilt-layout` model, requests output in Markdown format, polls for completion, and returns the Markdown string. Used by the queue worker. |
| `convert(file_path: str) → str` | Reads a local PDF file and calls the same API. Used for local testing. |

The `prebuilt-layout` model is a general-purpose document understanding model that recognizes headings, tables, paragraphs, and lists, outputting them as clean Markdown.

---

### `processing_state.py` — `ProcessingStateService`

Tracks the processing status of every filing in **Azure Table Storage**. This is what prevents the pipeline from re-processing a filing it already completed.

**Table structure:**
- **Table name:** `SECProcessingState` (configurable via `SEC_STATE_TABLE_NAME`)
- **Partition key:** `Utility_10K_2026` (configurable via `SEC_STATE_PARTITION_KEY`)
- **Row key:** The accession number (e.g., `0000004904-26-000013`) — unique per filing

**Allowed statuses:**

| Status | Meaning |
|---|---|
| `ready` | HTML downloaded and uploaded to blob; waiting to be converted to PDF |
| `pdf_converted` | PDF generated and uploaded; waiting to be converted to Markdown |
| `markdown_converted` | Fully processed — nothing more to do |
| `error` | Processing failed; error message stored in `LastError` column |

**Key methods:**

| Method | What it does |
|---|---|
| `upsert_filing(...)` | Creates a new record for a filing with all metadata fields. Called when a filing is first discovered. |
| `update_status(accession, status)` | Updates just the `Status` and `LastUpdatedUtc` columns. Called at each pipeline step. |
| `get_status(accession)` | Returns the current `Status` string for a given accession, or `None` if not found. |
| `get_entity(accession)` | Returns the full entity row. |

---

## `scripts/` — Utility Scripts

These are standalone helper scripts intended to be run manually (not part of the automated pipeline).

---

### `scripts/create_state_table.py`

A **one-time setup script** that seeds the Azure Table Storage with initial state for all 5 filings. Useful for:
- Bootstrapping the pipeline state after a fresh deployment.
- Resetting/pre-populating state to a specific status (e.g., `markdown_converted`) for testing.

Connects to Azure Storage using `AZURE_STORAGE_CONNECTION_STRING` from `config/.env`, creates the `SECProcessingState` table if it doesn't exist, and upserts 5 rows — one per company.

---

### `scripts/extract_sec_metadata.py`

A **standalone metadata extraction tool** that scans HTML blobs already uploaded to Blob Storage and extracts structured metadata from them.

It reads the HTML, parses it with BeautifulSoup, and looks for standard SEC metadata tags:
- `dei:EntityCentralIndexKey` → CIK number
- `dei:EntityRegistrantName` → Company name
- Accession number from the blob path (or from an `ACCESSION NUMBER:` header in the document)

Output can be written as **JSON** or **CSV**, and results can optionally be uploaded back to Blob Storage as a metadata index file (`sec_metadata.json`).

This script is useful for auditing what's in your blob container without needing to query the SEC API again.

---

## `infra/main.bicep` — Azure Infrastructure

This is an **Infrastructure-as-Code** file written in Bicep (Azure's ARM template language). It defines every Azure cloud resource the project needs. Running this file provisions the entire environment.

**Resources created:**

| Resource | Purpose |
|---|---|
| **Log Analytics Workspace** | Centralized logging for all Azure resources |
| **Azure OpenAI** | Reserved for future RAG / AI querying features |
| **Azure AI Search** | Reserved for future semantic search over processed filings |
| **User-Assigned Managed Identity** (`project1-id`) | Identity used by services to authenticate without passwords |
| **Azure Key Vault** | Secure secret storage — holds the Document Intelligence API key |
| **Azure Storage Account** | Stores blobs (HTML/PDF/Markdown files), queues, and table state |
| **Blob Container** (`sec-filings`) | The main container for all filing artifacts |
| **Azure AI Document Intelligence** | The `prebuilt-layout` model used to convert PDFs to Markdown |
| **Azure Function App** (Consumption plan, Linux, Python 3.11) | Hosts all three pipeline functions |

**Security configuration in Bicep:**
- Storage account: HTTPS only, TLS 1.2 minimum, no public blob access, soft-delete enabled (7-day retention).
- Key Vault: RBAC authorization enabled (no legacy access policies).
- Function App: HTTPS only, uses System-Assigned identity.
- All secrets are injected as Key Vault references in Function App settings (e.g., `@Microsoft.KeyVault(SecretUri=...)`).

**RBAC role assignments wired up automatically:**
- Project managed identity → `Storage Blob Data Contributor`
- Function App identity → `Storage Blob Data Contributor`
- Function App identity → `Storage Queue Data Contributor`
- Function App identity → `Key Vault Secrets User`
- Deploying user → `Key Vault Secrets Officer`

**Outputs** (used by the CI/CD pipeline):
- `openAiEndpoint`, `docIntelligenceEndpoint`, `searchEndpoint`
- `storageAccountNameOut`, `blobAccountUrl`, `blobContainerNameOut`
- `functionAppNameOut`

---

## `azure-pipelines.yml` — CI/CD Pipeline

An **Azure DevOps pipeline** that runs on every push to `main`. It performs 6 steps end-to-end:

| Step | What it does |
|---|---|
| 1. Provision Resources | Deploys `infra/main.bicep` using the ARM Template task — creates or updates all Azure resources. |
| 2. Parse Bicep Outputs | Extracts the output variables (endpoints, names) from the Bicep deployment using `jq` and stores them as pipeline variables. |
| 3. Print Success | Echoes the provisioned endpoint URLs for logging/auditing. |
| 4. Archive Code | Zips the entire project into `functionapp.zip` for deployment. |
| 5. Deploy Function App | Deploys `functionapp.zip` to the Function App provisioned in step 1. |
| 6. Final Status | Always prints a completion message regardless of earlier step outcomes. |

The pipeline uses a **service connection** (`UtilityProjectConnection`) to authenticate to Azure and targets the resource group `rg-scarredentos-0001` in `eastus`.

---

## `host.json` — Function Runtime Configuration

Configures the Azure Functions runtime (v4) behavior. Key settings for the queue triggers:

| Setting | Value | Effect |
|---|---|---|
| `batchSize` | `1` | Process one queue message at a time per worker instance |
| `maxDequeueCount` | `5` | Retry a failing message up to 5 times before moving it to the poison queue |
| `visibilityTimeout` | `00:00:30` | If a worker crashes mid-processing, the message becomes visible again after 30 seconds |
| `maxPollingInterval` | `00:00:02` | Poll the queue every 2 seconds for new messages |
| `messageEncoding` | `none` | Messages are plain JSON strings, not base64-encoded |

---

## `tests/unit/test_kickoff_dry_run.py`

A unit test for the `manual_kickoff` function. It uses Python's `unittest.mock` framework to test the routing logic **without making any real Azure or HTTP calls**.

**How it works:**
- Imports `function_app` with service dependencies replaced by stub (fake) classes.
- Uses `FakeDownloader` that maps each ticker to a predefined accession number with a known status.
- Uses `FakeStateService` that returns pre-set statuses for each accession.
- Uses `FakeQueueClient` that records which messages were sent to which queues.

**What it verifies:**
- A filing with status `markdown_converted` → skipped (no queue message sent).
- A filing with status `pdf_converted` → message sent to the PDF queue.
- A filing with status `ready` → message sent to the HTML queue.
- A filing with status `error` → skipped.
- A filing with no existing status → HTML downloaded, blob uploaded, record created, message sent to HTML queue.

This test ensures the kickoff routing logic works correctly without needing a live Azure environment.

---

## `config/local.settings.json` — Local Development Config

Contains environment variables used when running the Function App locally with `func start`. These values are **not deployed** to Azure — they are for local development only.

Key variables:

| Variable | Purpose |
|---|---|
| `AzureWebJobsStorage` | Connection string to the Azure Storage account (queues + table state) |
| `BLOB_ACCOUNT_URL` | Azure Blob endpoint (if using managed identity instead of connection string) |
| `BLOB_CONTAINER_NAME` | Name of the blob container (`sec-filings`) |
| `SEC_COMPANY_NAME` / `SEC_EMAIL` | Identifies this app to the SEC API |
| `SEC_HTML_QUEUE_NAME` | Queue name for HTML conversion jobs |
| `SEC_PDF_QUEUE_NAME` | Queue name for PDF conversion jobs |
| `SEC_STATE_TABLE_NAME` | Azure Table name for processing state |
| `SEC_STATE_PARTITION_KEY` | Partition key used in Table Storage |
| `DOC_INTEL_ENDPOINT` / `DOC_INTEL_KEY` | Document Intelligence credentials |

---

## `data/raw/` — Local Copies of SEC Filings

Sample filing documents downloaded for local development and testing. Each filing follows the path:

```
data/raw/sec-edgar-filings/{TICKER}/10-K/{ACCESSION}/
    ├── full-submission.txt     ← Complete SEC submission package
    └── primary-document.html  ← The actual 10-K filing document
```

Filings present: AEP, CEG, DUK, NEE, SO — one 10-K each.

These files are **not used by the pipeline at runtime** (which works with blobs in Azure). They exist for local inspection and ad-hoc testing.

---

## `sec_metadata.json` — Scraped Metadata Index

A JSON file generated by `scripts/extract_sec_metadata.py`. Contains the extracted metadata (CIK, company name, accession number) for each HTML blob in the storage container.

---

## `requirements.txt` — Python Dependencies

| Package | Used for |
|---|---|
| `azure-functions` | Azure Functions Python worker |
| `azure-identity` | Managed identity / `DefaultAzureCredential` auth |
| `azure-data-tables` | Azure Table Storage (processing state) |
| `azure-storage-blob` | Azure Blob Storage (file storage) |
| `azure-storage-queue` | Azure Queue Storage (pipeline messaging) |
| `azure-ai-documentintelligence` | PDF → Markdown via Document Intelligence |
| `beautifulsoup4` + `lxml` | HTML parsing (sanitization + metadata extraction) |
| `xhtml2pdf` | Fallback HTML → PDF renderer |
| `playwright` | Primary HTML → PDF renderer (headless Chromium) |
| `langchain-text-splitters` + `openai` | Reserved for future RAG / chunking features |
| `python-dotenv` | Load `config/.env` for local development |
| `requests` | HTTP calls to SEC EDGAR API |

---

## End-to-End Data Flow Summary

```
SEC EDGAR API
    │
    │  (HTTP GET — Company tickers + filing metadata)
    ▼
SECDownloaderService.fetch_latest_10k_metadata()
    │
    │  (HTTP GET — Raw HTML bytes)
    ▼
Azure Blob Storage: raw/html/{TICKER}/{ACCESSION}/10-K.html
    │
    │  (Queue message on sec-html-jobs)
    ▼
HTMLToPDFService.convert_html_bytes()
    │  → Sanitize HTML
    │  → Playwright headless render (or xhtml2pdf fallback)
    ▼
Azure Blob Storage: processed/pdf/{TICKER}/{ACCESSION}/10-K.pdf
    │
    │  (Queue message on sec-pdf-jobs)
    ▼
PDFToMarkdownService.convert_pdf_bytes()
    │  → Azure AI Document Intelligence (prebuilt-layout model)
    ▼
Azure Blob Storage: processed/md/{TICKER}/{ACCESSION}/10-K.md
    │
    │  (State tracked throughout in Azure Table Storage)
    ▼
Final state: markdown_converted ✓
```
