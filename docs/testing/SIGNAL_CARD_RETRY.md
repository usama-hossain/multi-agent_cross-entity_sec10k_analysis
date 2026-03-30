# Signal Card Retry / Reprocessing Guide

## Overview

The codebase processes signal cards incrementally to avoid redundant LLM calls. Once a signal card blob exists (`processed/signals/{ticker}/{accession}/signal_card.json`), the system skips reprocessing by default.

To retry LLM extraction after changes (e.g., prompt refinements), use one of the methods below.

---

## Retry Methods

### **Method 1: Query Parameter (Simplest)**

Restart LLM processing with a single HTTP call:

```bash
curl -X POST http://localhost:7071/api/kickoff?force_reprocess_signal_cards=true
```

**How it works:**
- Skips final "already_complete" check when `force_reprocess_signal_cards=true`
- Still requires markdown + section files to exist
- Allows signal card blob to be reprocessed

**Limitations:**
- Does NOT delete existing signal card blobs (only skips the skip-check)
- LLM sees the same prompt structure, only processes if status allows

---

### **Method 2: REST Endpoint for Status Reset**

Reset table storage status to allow reprocessing:

```bash
# For specific tickers
curl -X POST "http://localhost:7071/api/reset-signal-cards?tickers=NEE,DUK,SO"

# For specific accessions
curl -X POST "http://localhost:7071/api/reset-signal-cards?accessions=0000753308-26-000015,0001326160-25-000072"
```

**What it does:**
- Sets `SignalCardStatus = "not_started"` in table storage
- Allows markdown worker to re-enter signal card extraction logic
- **NOTE:** Does NOT delete signal card JSON blobs

**Manual cleanup required:**
```bash
# Delete blobs manually via Azure Storage Explorer:
# - processed/signals/{ticker}/{accession}/signal_card.json

# Then re-run kickoff:
curl -X POST http://localhost:7071/api/kickoff
```

---

### **Method 3: Python Script (Bulk Operations)**

For automation or bulk resets:

```bash
# Reset all tickers
python scripts/reset_signal_cards.py --all-tickers

# Reset specific tickers
python scripts/reset_signal_cards.py --ticker NEE,DUK,SO

# Reset specific accessions
python scripts/reset_signal_cards.py --accession 0000753308-26-000015,0001326160-25-000072
```

**Output:**
- Lists all accessions to be reset
- Logs which blobs need manual deletion
- Provides ready-to-run kickoff command

---

## Current Skip Logic (What Blocks Reprocessing)

### **In Kickoff:**
```python
if markdown_exists and item1a_exists and item7_exists and signal_card_exists:
    skip_reason = "already_complete"
    # Continues to next filing (unless force_reprocess_signal_cards=true)
```

### **In Markdown Worker:**
```python
if markdown_exists and item1a_exists and item7_exists and signal_card_exists:
    state_service.set_signal_card_status(accession, "extracted")
    return  # Early exit - skips signal card extraction
```

**To unblock**: Delete signal card blob OR skip the blob-existence check.

---

## Recommended Workflow for Prompt Refinement

1. **Modify the system prompt** → update `EXTRACTION_SYSTEM_PROMPT` in [src/services/signal_card_extractor.py](../src/services/signal_card_extractor.py)

2. **Reset signal cards:**
   ```bash
   # Option A: Via REST endpoint
   curl -X POST "http://localhost:7071/api/reset-signal-cards?tickers=NEE"
   
   # Option B: Via script
   python scripts/reset_signal_cards.py --ticker NEE
   ```

3. **Delete signal card blobs** from Azure Blob Storage:
   - Path: `processed/signals/NEE/*/signal_card.json`
   - Use Azure Storage Explorer or Azure CLI

4. **Retrigger extraction:**
   ```bash
   curl -X POST http://localhost:7071/api/kickoff
   ```

5. **Verify output:**
   - Check logs for LLM call execution
   - Inspect new signal card JSON blobs
   - Confirm `SignalCardStatus = "extracted"` in table storage

---

## Signal Card Status States

| Status | Meaning | Can Reprocess? |
|--------|---------|---|
| `not_started` | Never processed | ✅ Yes |
| `extracted` | Successfully generated | ❌ No (skipped) |
| `skipped` | No section files available | ✅ Yes (if sections added) |
| `error` | Processing failed | ✅ Yes (retry allowed) |
| `queued_for_batch` | Queued for batch API | ⚠️ Caution (batch mode) |
| `batch_submitted` | Batch job in flight | ⚠️ Caution (batch mode) |

---

## Troubleshooting

### "Signal card not reprocessing even with force flag"
- ✅ Confirm table status is not `"extracted"`
- ✅ Confirm section files (item1a.md, item7.md) exist
- ✅ Check logs for "Skipping signal card extraction..."

### "Empty risk factor arrays after retry"
- ✅ Verify all 5 years of context are available (or acceptable partial context logged)
- ✅ Check system prompt was updated and deployed
- ✅ Confirm LLM call was actually executed (look for "Calling OpenAI structured extraction" logs)

### "Blob not deleted after reset"
- Reset only updates **table status**, not blobs
- Must manually delete: `processed/signals/{ticker}/{accession}/signal_card.json`
- The system checks blob existence before seeing table status

---

## Reference

- **Force reprocess query param:** `force_reprocess_signal_cards=true`
- **Reset endpoint:** `POST /api/reset-signal-cards?tickers=...` or `?accessions=...`
- **Reset script:** `python scripts/reset_signal_cards.py`
- **Storage state:** Table `SECProcessingState` (PartitionKey: `Utility_10K_2026`)
- **Blob paths:** `processed/signals/{ticker}/{accession}/signal_card.json`
