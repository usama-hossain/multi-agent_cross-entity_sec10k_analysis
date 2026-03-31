import json
import logging
import os
from typing import Any, Optional

from openai import AzureOpenAI, OpenAI

from src.services.signal_card_schema import SignalCard


class SECSignalCardBatchService:
    """
    Batch API service for signal card extraction.
    Submits requests to OpenAI batch jobs instead of making immediate calls.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        self.api_version = os.getenv("OPENAI_API_VERSION", "2024-10-21").strip()

        if self.api_key and self.azure_endpoint:
            self._client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.azure_endpoint,
                api_version=self.api_version,
            )
        elif self.api_key:
            self._client = OpenAI(api_key=self.api_key)
        else:
            self._client = None

    @property
    def is_enabled(self) -> bool:
        return self._client is not None

    def build_batch_request_item(
        self,
        custom_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build a single batch request item for the batch input file.
        custom_id should be unique and traceable (e.g., ticker-accession-timestamp).
        """
        item = {
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_schema", "json_schema": schema},
            },
        }
        logging.debug(
            "Built batch request item: custom_id=%s model=%s system_prompt_len=%d user_prompt_len=%d",
            custom_id,
            self.model,
            len(system_prompt),
            len(user_prompt),
        )
        return item

    @staticmethod
    def _format_timestamp(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _create_batch_input_file(self, jsonl_path: str):
        """Create an OpenAI batch input file using stable SDK first, with beta fallback."""
        with open(jsonl_path, "rb") as f:
            if hasattr(self._client, "files") and hasattr(self._client.files, "create"):
                return self._client.files.create(file=f, purpose="batch")

            beta = getattr(self._client, "beta", None)
            beta_files = getattr(beta, "files", None) if beta else None
            if beta_files and hasattr(beta_files, "upload"):
                return beta_files.upload(
                    file=(f.name, f, "application/x-ndjson"),
                    purpose="batch",
                )

        raise RuntimeError("OpenAI SDK does not support batch file upload APIs")

    def _create_batch_job(self, file_id: str):
        """Create OpenAI batch job using stable SDK first, with beta fallback."""
        if hasattr(self._client, "batches") and hasattr(self._client.batches, "create"):
            return self._client.batches.create(
                input_file_id=file_id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
            )

        beta = getattr(self._client, "beta", None)
        beta_batches = getattr(beta, "batches", None) if beta else None
        if beta_batches and hasattr(beta_batches, "create"):
            return beta_batches.create(
                input_file_id=file_id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
            )

        raise RuntimeError("OpenAI SDK does not support batch creation APIs")

    def _retrieve_batch_job(self, batch_id: str):
        """Retrieve OpenAI batch job using stable SDK first, with beta fallback."""
        if hasattr(self._client, "batches") and hasattr(self._client.batches, "retrieve"):
            return self._client.batches.retrieve(batch_id)

        beta = getattr(self._client, "beta", None)
        beta_batches = getattr(beta, "batches", None) if beta else None
        if beta_batches and hasattr(beta_batches, "retrieve"):
            return beta_batches.retrieve(batch_id)

        raise RuntimeError("OpenAI SDK does not support batch retrieval APIs")

    def _get_file_content(self, file_id: str):
        """Fetch OpenAI file content using stable SDK first, with beta fallback."""
        if hasattr(self._client, "files") and hasattr(self._client.files, "content"):
            return self._client.files.content(file_id)

        beta = getattr(self._client, "beta", None)
        beta_files = getattr(beta, "files", None) if beta else None
        if beta_files and hasattr(beta_files, "content"):
            return beta_files.content(file_id)

        raise RuntimeError("OpenAI SDK does not support file content APIs")

    def submit_batch(self, batch_request_items: list[dict[str, Any]]) -> Optional[str]:
        """
        Submit batch request items to OpenAI.
        Returns batch_id if successful, None otherwise.
        """
        if not self.is_enabled:
            logging.error("Batch service is not enabled or OPENAI_API_KEY is missing.")
            return None

        if not batch_request_items:
            logging.warning("No batch request items provided.")
            return None

        try:
            # Convert items to JSONL format
            jsonl_content = "\n".join(json.dumps(item) for item in batch_request_items)

            logging.info(
                "Submitting batch to OpenAI: item_count=%d total_size=%d bytes model=%s",
                len(batch_request_items),
                len(jsonl_content),
                self.model,
            )

            # Upload batch input file
            logging.debug("Uploading batch input file to OpenAI...")
            with open("/tmp/batch_input.jsonl", "w") as f:
                f.write(jsonl_content)

            file_response = self._create_batch_input_file("/tmp/batch_input.jsonl")

            file_id = file_response.id
            logging.info("Batch input file uploaded successfully: file_id=%s", file_id)

            # Create batch job
            logging.debug("Creating batch job with file_id=%s...", file_id)
            batch_response = self._create_batch_job(file_id)

            batch_id = batch_response.id
            status = batch_response.status
            logging.info(
                "Batch job created successfully: batch_id=%s status=%s file_id=%s submission_time=%s",
                batch_id,
                status,
                file_id,
                self._format_timestamp(getattr(batch_response, "created_at", None)) or "unknown",
            )
            return batch_id

        except Exception:
            logging.exception("Failed to submit batch to OpenAI")
            return None

    def get_batch_status(self, batch_id: str) -> Optional[dict[str, Any]]:
        """
        Get current status of a batch job.
        Returns dict with status info, or None if failed.
        """
        if not self.is_enabled:
            logging.warning("Batch service is not enabled, cannot retrieve status for batch_id=%s", batch_id)
            return None

        try:
            batch = self._retrieve_batch_job(batch_id)
            request_counts_obj = getattr(batch, "request_counts", None)
            if request_counts_obj is None:
                request_counts = {}
            elif hasattr(request_counts_obj, "model_dump"):
                request_counts = request_counts_obj.model_dump()
            elif isinstance(request_counts_obj, dict):
                request_counts = request_counts_obj
            else:
                request_counts = {}

            status_info = {
                "batch_id": batch.id,
                "status": batch.status,
                "request_counts": request_counts,
                "output_file_id": batch.output_file_id,
                "error_file_id": batch.error_file_id,
                "created_at": self._format_timestamp(getattr(batch, "created_at", None)),
                "expires_at": self._format_timestamp(getattr(batch, "expires_at", None)),
            }

            logging.info(
                "Batch status retrieved: batch_id=%s status=%s total_requests=%d completed=%d failed=%d erred=%d expires_at=%s",
                batch_id,
                batch.status,
                request_counts.get("total", 0),
                request_counts.get("completed", 0),
                request_counts.get("failed", 0),
                request_counts.get("errored", 0),
                status_info["expires_at"],
            )
            return status_info

        except Exception:
            logging.exception("Failed to retrieve batch status: batch_id=%s", batch_id)
            return None

    def fetch_batch_results(self, batch_id: str, output_file_id: str) -> Optional[list[dict[str, Any]]]:
        """
        Fetch and parse completed batch results from output file.
        Returns list of result dicts with custom_id and response data.
        """
        if not self.is_enabled:
            logging.warning("Batch service is not enabled, cannot fetch results for batch_id=%s", batch_id)
            return None

        try:
            logging.debug("Fetching batch output file: batch_id=%s output_file_id=%s", batch_id, output_file_id)
            file_content = self._get_file_content(output_file_id)
            results = []

            raw_text = getattr(file_content, "text", "") or ""
            for index, line in enumerate(raw_text.strip().split("\n"), start=1):
                if not line:
                    continue
                result = json.loads(line)
                results.append(result)

            logging.info(
                "Batch results fetched and parsed: batch_id=%s total_results=%d",
                batch_id,
                len(results),
            )
            return results

        except Exception:
            logging.exception(
                "Failed to fetch batch results: batch_id=%s output_file_id=%s",
                batch_id,
                output_file_id,
            )
            return None

    def parse_batch_result(self, result: dict[str, Any]) -> tuple[Optional[str], Optional[SignalCard], Optional[str]]:
        """
        Parse a single batch result item.
        Returns (custom_id, signal_card, error_message).
        """
        custom_id = result.get("custom_id")

        if "error" in result:
            error_obj = result["error"]
            error_msg = f"{error_obj.get('message', 'Unknown error')}"
            logging.warning(
                "Batch result has error: custom_id=%s error=%s",
                custom_id,
                error_msg,
            )
            return custom_id, None, error_msg

        try:
            response = result.get("response") or {}
            status_code = response.get("status_code")

            if status_code != 200:
                error_msg = f"HTTP {status_code}: {response.get('body', {}).get('error', {}).get('message', 'Unknown error')}"
                logging.warning(
                    "Batch result HTTP error: custom_id=%s status_code=%s error=%s",
                    custom_id,
                    status_code,
                    error_msg,
                )
                return custom_id, None, error_msg

            body = response.get("body") or {}
            choices = body.get("choices") or []

            if not choices:
                error_msg = "No choices in response body"
                logging.warning("Batch result has no choices: custom_id=%s", custom_id)
                return custom_id, None, error_msg

            content = choices[0].get("message", {}).get("content", "{}")
            logging.debug(
                "Parsing SignalCard from batch result: custom_id=%s content_len=%d",
                custom_id,
                len(content),
            )

            payload = json.loads(content)
            signal_card = SignalCard.model_validate(payload)

            logging.info(
                "Batch result parsed successfully: custom_id=%s signal_card_validated=true",
                custom_id,
            )
            return custom_id, signal_card, None

        except Exception as e:
            error_msg = f"Failed to parse result: {str(e)}"
            logging.exception(
                "Batch result parsing failed: custom_id=%s error=%s",
                custom_id,
                error_msg,
            )
            return custom_id, None, error_msg
