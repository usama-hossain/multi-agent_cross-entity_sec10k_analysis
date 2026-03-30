#!/usr/bin/env python3
"""
Debug script to inspect the exact input being sent to OpenAI Batch API.
Shows JSONL structure, request format, prompt content, and schema.
"""

import json
import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.signal_card_batch import SECSignalCardBatchService
from src.services.signal_card_extractor import SECSignalCardService


def main():
    """Build and display batch request that would be sent to OpenAI."""
    
    print("=" * 80)
    print("DEBUG: Batch Input Verification")
    print("=" * 80)
    
    # Initialize services
    batch_service = SECSignalCardBatchService()
    extractor = SECSignalCardService()
    
    if not batch_service.is_enabled:
        print("ERROR: Batch service not enabled. Check OPENAI_API_KEY env var.")
        sys.exit(1)
    
    # Build extraction request (same as live test)
    print("\n1. Building extraction request...")
    request = extractor.build_extraction_request(
        ticker="VRT",
        fiscal_year=2024,
        filing_date="2024-12-31",
        target_accession="0001628280-22-004533",
        historical_filings=[
            {
                "accession": "0001628280-22-004533",
                "fiscal_year": 2024,
                "filing_date": "2024-12-31",
                "item1a_text": "Risk factors include supply chain disruption and cybersecurity incidents.",
                "item7_text": "Management discussion indicates stable capex and moderate demand growth.",
            }
        ],
    )
    
    # Build batch request item
    print("2. Building batch request item...")
    custom_id = f"debug-{int(time.time())}"
    batch_item = batch_service.build_batch_request_item(
        custom_id=custom_id,
        system_prompt=request["system_prompt"],
        user_prompt=request["user_prompt"],
        schema=request["schema"],
    )
    
    # Display the request item structure
    print("\n" + "=" * 80)
    print("BATCH REQUEST ITEM STRUCTURE")
    print("=" * 80)
    
    print(f"\ncustom_id: {batch_item['custom_id']}")
    print(f"method: {batch_item['method']}")
    print(f"url: {batch_item['url']}")
    
    body = batch_item["body"]
    print(f"\nBody fields:")
    print(f"  model: {body['model']}")
    print(f"  messages: {len(body['messages'])} items")
    
    # System prompt
    print(f"\n  [0] System Message ({len(body['messages'][0]['content'])} chars):")
    print("      " + body['messages'][0]['content'][:200].replace("\n", "\n      ") + "...")
    
    # User prompt
    user_msg = body['messages'][1]['content']
    print(f"\n  [1] User Message ({len(user_msg)} chars):")
    print("      " + user_msg[:300].replace("\n", "\n      ") + "...")
    
    # Schema
    json_schema_obj = body['response_format']['json_schema']
    schema = json_schema_obj['schema']
    print(f"\n  response_format:")
    print(f"    type: json_schema")
    print(f"    json_schema name: {json_schema_obj['name']}")
    print(f"    json_schema strict: {json_schema_obj['strict']}")
    print(f"    json_schema properties: {list(schema['properties'].keys())}")
    print(f"    json_schema required fields: {schema['required']}")
    
    # JSONL format
    print("\n" + "=" * 80)
    print("JSONL FORMAT (what's uploaded to OpenAI)")
    print("=" * 80)
    jsonl_line = json.dumps(batch_item)
    print(f"\nTotal JSONL line size: {len(jsonl_line)} bytes")
    print(f"System prompt size: {len(request['system_prompt'])} chars")
    print(f"User prompt size: {len(request['user_prompt'])} chars")
    print(f"Schema size: {len(json.dumps(request['schema']))} chars")
    
    print("\nJSONL line structure (truncated):")
    print(json.dumps(batch_item, indent=2)[:1000] + "\n...")
    
    # Show all request items that would be sent
    print("\n" + "=" * 80)
    print("READY TO SUBMIT")
    print("=" * 80)
    print(f"\nWould submit 1 batch item:")
    print(f"  custom_id: {batch_item['custom_id']}")
    print(f"  model: {body['model']}")
    print(f"  ticker: VRT")
    print(f"  fiscal_year: 2024")
    print(f"  Has system prompt: Yes ({len(body['messages'][0]['content'])} chars)")
    print(f"  Has user content: Yes ({len(user_msg)} chars)")
    print(f"  Has schema: Yes (SignalCard with {len(schema['properties'])} fields)")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
