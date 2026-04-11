import json
import logging
import os

import azure.functions as func

from src.core.blob_paths import BlobPaths
from src.core.ports import PendingSignalCardBatch
from src.functions import pipeline_shared as shared


reconciler_bp = func.Blueprint()


@reconciler_bp.function_name(name="signal_card_batch_reconciler")
@reconciler_bp.timer_trigger(arg_name="timer", schedule="0 */15 * * * *")
def signal_card_batch_reconciler(timer: func.TimerRequest) -> None:
    schedule_status = getattr(timer, "schedule_status", None)
    trigger_time = getattr(schedule_status, "last", None) if schedule_status else None
    logging.info(
        "Signal card batch reconciler started: trigger_time=%s is_past_due=%s",
        trigger_time or "unknown",
        getattr(timer, "past_due", False),
    )

    execution_mode = os.getenv("SIGNAL_CARD_EXECUTION_MODE", "sync").strip().lower()
    if execution_mode != "batch":
        logging.info(
            "Skipping signal card batch reconciler because execution mode is not batch: execution_mode=%s",
            execution_mode,
        )
        return

    deps = shared._build_reconciler_dependencies()
    state_service = deps.state_store
    blob_store = deps.blob_store
    batch_service = deps.batch_service

    if not batch_service.is_enabled:
        logging.info("Batch service is not enabled, skipping batch reconciliation")
        return

    reconciliation_stats = {
        "batches_checked": 0,
        "batches_completed": 0,
        "batches_failed": 0,
        "batches_in_progress": 0,
        "results_processed": 0,
        "results_successful": 0,
        "results_failed": 0,
    }

    raw_pending_entities = state_service.list_pending_signal_card_batches()
    pending_entities = []
    for raw_entity in raw_pending_entities:
        normalized = shared._normalize_pending_batch(raw_entity)
        if normalized is None:
            logging.warning("Skipping unsupported pending batch contract object type=%s", type(raw_entity).__name__)
            continue
        pending_entities.append(normalized)

    if not pending_entities:
        logging.info("No pending signal card batches found for reconciliation")
    else:
        logging.info("Reconciling pending signal card batches: entity_count=%d", len(pending_entities))

    entities_by_batch_id: dict[str, list[PendingSignalCardBatch]] = {}

    for entity in pending_entities:
        accession = entity.accession
        signal_card_status = entity.signal_card_status
        batch_id = entity.batch_id

        if signal_card_status == "queued_for_batch" and (not batch_id or batch_id == "pending"):
            logging.warning(
                "Found queued_for_batch entity without submitted batch_id; marking batch_failed: accession=%s",
                accession,
            )
            state_service.update_signal_card_batch_status(
                accession,
                "failed",
                error_message="Queued for batch without a submitted batch id",
            )
            state_service.set_signal_card_status(
                accession,
                "batch_failed",
                error_message="Queued for batch without a submitted batch id",
            )
            reconciliation_stats["results_failed"] += 1
            continue

        if not batch_id or batch_id == "pending":
            logging.warning(
                "Skipping entity without usable batch_id: accession=%s signal_card_status=%s batch_id=%s",
                accession,
                signal_card_status,
                batch_id,
            )
            continue

        if batch_id not in entities_by_batch_id:
            entities_by_batch_id[batch_id] = []
        entities_by_batch_id[batch_id].append(entity)

    for batch_id, batch_entities in entities_by_batch_id.items():
        reconciliation_stats["batches_checked"] += 1
        accessions = [e.accession for e in batch_entities]
        logging.info(
            "Polling batch status: batch_id=%s filings_in_batch=%d accessions=%s",
            batch_id,
            len(batch_entities),
            accessions,
        )

        status_info = batch_service.get_batch_status(batch_id)
        if not status_info:
            logging.warning("Batch status unavailable; will retry on next run: batch_id=%s", batch_id)
            continue

        batch_status = str(status_info.get("status", "")).strip().lower()
        logging.info(
            "Batch status evaluated: batch_id=%s status=%s output_file_id=%s",
            batch_id,
            batch_status,
            status_info.get("output_file_id"),
        )

        if batch_status in {"queued", "validating", "in_progress", "finalizing", "cancelling"}:
            reconciliation_stats["batches_in_progress"] += 1
            for entity in batch_entities:
                accession = entity.accession
                state_service.update_signal_card_batch_status(accession, "in_progress")
                state_service.set_signal_card_status(accession, "batch_submitted")
            continue

        if batch_status == "completed":
            reconciliation_stats["batches_completed"] += 1
            output_file_id = str(status_info.get("output_file_id", "")).strip()
            if not output_file_id:
                logging.error(
                    "Completed batch missing output_file_id; marking all entities failed: batch_id=%s",
                    batch_id,
                )
                for entity in batch_entities:
                    accession = entity.accession
                    state_service.update_signal_card_batch_status(
                        accession,
                        "failed",
                        error_message="Batch completed without output file",
                    )
                    state_service.set_signal_card_status(
                        accession,
                        "batch_failed",
                        error_message="Batch completed without output file",
                    )
                    reconciliation_stats["results_failed"] += 1
                continue

            batch_results = batch_service.fetch_batch_results(batch_id, output_file_id)
            if batch_results is None:
                logging.error(
                    "Failed to fetch completed batch output; will retry next run: batch_id=%s output_file_id=%s",
                    batch_id,
                    output_file_id,
                )
                continue

            result_by_custom_id = {
                str(result.get("custom_id", "")).strip(): result
                for result in batch_results
                if str(result.get("custom_id", "")).strip()
            }

            logging.info(
                "Processing completed batch results: batch_id=%s result_items=%d expected_entities=%d",
                batch_id,
                len(result_by_custom_id),
                len(batch_entities),
            )

            for entity in batch_entities:
                accession = entity.accession
                custom_id = entity.custom_id
                ticker = shared._resolve_ticker_for_batch_entity(entity)

                reconciliation_stats["results_processed"] += 1

                if not ticker:
                    error_message = "Unable to resolve ticker for batch entity"
                    logging.error(
                        "Failed to materialize batch result: accession=%s custom_id=%s reason=%s",
                        accession,
                        custom_id,
                        error_message,
                    )
                    state_service.update_signal_card_batch_status(accession, "failed", error_message=error_message)
                    state_service.set_signal_card_status(accession, "batch_failed", error_message=error_message)
                    reconciliation_stats["results_failed"] += 1
                    continue

                result = result_by_custom_id.get(custom_id)
                if not result:
                    error_message = f"No batch result item found for custom_id={custom_id}"
                    logging.error(
                        "Missing batch result item: batch_id=%s accession=%s custom_id=%s",
                        batch_id,
                        accession,
                        custom_id,
                    )
                    state_service.update_signal_card_batch_status(accession, "failed", error_message=error_message)
                    state_service.set_signal_card_status(accession, "batch_failed", error_message=error_message)
                    reconciliation_stats["results_failed"] += 1
                    continue

                _, signal_card, error_message = batch_service.parse_batch_result(result)
                if error_message or signal_card is None:
                    final_error = error_message or "Unknown batch parse error"
                    logging.error(
                        "Batch result parse failed: batch_id=%s accession=%s custom_id=%s error=%s",
                        batch_id,
                        accession,
                        custom_id,
                        final_error,
                    )
                    state_service.update_signal_card_batch_status(accession, "failed", error_message=final_error)
                    state_service.set_signal_card_status(accession, "batch_failed", error_message=final_error)
                    reconciliation_stats["results_failed"] += 1
                    continue

                signal_card_blob = BlobPaths.signal_card(ticker, accession)
                try:
                    blob_store.upload_blob(
                        signal_card_blob,
                        json.dumps(signal_card.model_dump(mode="json"), indent=2).encode("utf-8"),
                        content_type="application/json",
                    )
                    state_service.update_signal_card_batch_status(accession, "completed")
                    state_service.set_signal_card_status(accession, "extracted")
                    logging.info(
                        "Batch result materialized successfully: batch_id=%s accession=%s custom_id=%s signal_card_blob=%s",
                        batch_id,
                        accession,
                        custom_id,
                        signal_card_blob,
                    )
                    reconciliation_stats["results_successful"] += 1
                except Exception:
                    logging.exception(
                        "Failed to upload batch signal card artifact: batch_id=%s accession=%s custom_id=%s signal_card_blob=%s",
                        batch_id,
                        accession,
                        custom_id,
                        signal_card_blob,
                    )
                    state_service.update_signal_card_batch_status(
                        accession,
                        "failed",
                        error_message="Artifact upload failed after batch completion",
                    )
                    state_service.set_signal_card_status(
                        accession,
                        "batch_failed",
                        error_message="Artifact upload failed after batch completion",
                    )
                    reconciliation_stats["results_failed"] += 1
            continue

        if batch_status in {"failed", "expired", "cancelled"}:
            reconciliation_stats["batches_failed"] += 1
            mapped_status = "expired" if batch_status == "expired" else "failed"
            for entity in batch_entities:
                accession = entity.accession
                error_message = f"OpenAI batch ended with status={batch_status}"
                state_service.update_signal_card_batch_status(accession, mapped_status, error_message=error_message)
                state_service.set_signal_card_status(accession, "batch_failed", error_message=error_message)
                reconciliation_stats["results_failed"] += 1
                logging.error(
                    "Batch marked failed for accession due to terminal status: batch_id=%s accession=%s status=%s",
                    batch_id,
                    accession,
                    batch_status,
                )
            continue

        logging.warning(
            "Unhandled batch status encountered; preserving in-progress state: batch_id=%s status=%s",
            batch_id,
            batch_status,
        )
        reconciliation_stats["batches_in_progress"] += 1
        for entity in batch_entities:
            accession = entity.accession
            state_service.update_signal_card_batch_status(accession, "in_progress")
            state_service.set_signal_card_status(accession, "batch_submitted")

    logging.info(
        "Signal card batch reconciler completed: batches_checked=%d completed=%d failed=%d in_progress=%d results_processed=%d successful=%d failed=%d",
        reconciliation_stats["batches_checked"],
        reconciliation_stats["batches_completed"],
        reconciliation_stats["batches_failed"],
        reconciliation_stats["batches_in_progress"],
        reconciliation_stats["results_processed"],
        reconciliation_stats["results_successful"],
        reconciliation_stats["results_failed"],
    )
