import json
import logging
import os
from typing import Any, Optional

from openai import AzureOpenAI, BadRequestError, OpenAI

from src.services.signal_card_schema import SignalCard, SignalCardWithAccession, TickerSignalCardsResponse


EXTRACTION_SYSTEM_PROMPT = """You are a senior energy sector analyst extracting structured signals
from SEC 10-K filings. You will receive Item 1A (Risk Factors) and Item 7 (MD&A) across multiple
years (when available) to enable cross-year comparison analysis.

Extract a Signal Card with the following guidelines:

CAPITAL ALLOCATION: Determine CapEx direction from MD&A discussion. Look for YoY comparisons,
maintenance vs growth splits, and language around "optimizing", "accelerating", or "preserving".

SUPPLY CHAIN TIGHTNESS: Identify specific supply chain constraints mentioned - equipment
availability, input costs, lead times, supplier concentration. Rate severity based on language
intensity and quantified impact. Only include signals with direct textual evidence.

DEMAND SIGNALS: Extract customer growth trends, backlog changes, and load/volume shifts from
MD&A. Use "not_mentioned" for fields with no evidence rather than inferring.

NEW RISK FACTORS (Multi-Year Comparison):
- Identify risks appearing for the FIRST TIME in the TARGET FILING (most recent year)
- Mark "new" ONLY if this risk is completely ABSENT from all available prior years
- Risks that are carried forward with minor rewording are NOT new — they are escalated instead
- Search Item 1A for new risk language; cite the new risk verbatim
- If you cannot gather sufficient prior-year context to confirm "new" status, note uncertainty in evidence

ESCALATED RISK FACTORS (Multi-Year Comparison):
- Identify risks where LANGUAGE, SEVERITY, or QUANTIFIED EXPOSURE has intensified from prior years
- Compare the TARGET FILING's Item 1A to prior years' Item 1A sections
- Examples of escalation: more specific naming, higher quantified impact, elevated urgency, expanded scope
- Provide BOTH prior-year framing (brief summary) AND current-year framing (brief summary) with quotes
- Do NOT include risks that are merely mentioned again without language change
- If multiple prior years exist, compare against the MOST RECENT prior year first

REGULATORY EXPOSURE: Extract pending regulatory actions, compliance deadlines, and investment
commitments related to emissions, rate cases, or safety mandates.

STRATEGIC POSTURE: Determine overall direction from the tone and substance of MD&A.
"Expansion" = new capacity, new markets, growth CapEx. "Contraction" = asset optimization,
capital return, maintenance mode. "Pivot" = strategic shift (e.g., fossil to renewable).

GENERATION MIX SHIFT: For utilities and power generators only. Extract retirement schedules,
renewable additions, storage plans, and dispatchable adequacy concerns. For non-utility companies,
populate all fields with "Not applicable - not a utility/generator."

FUEL AND INPUT EXPOSURE: Extract commodity price sensitivity, hedging coverage changes, and
PPA terms from MD&A financial discussions.

CRITICAL RULES:
- Every field must have direct textual evidence from the filing. Do not infer or speculate.
- Quote relevant passages in the evidence fields.
- If information is not present, say "Not mentioned in filing" - do not fabricate.
- For severity ratings, anchor to quantified impact where available.
- For multi-year fields (new_risk_factors, escalated_risk_factors), use all provided years as context.
- Target the MOST RECENT filing year (FILING #1) for identifying new and escalated risks.
- Generate ONLY risks where evidence exists; leave empty arrays for sections without findings."""


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PROMPTS_JSON_PATH = os.path.join(
    PROJECT_ROOT,
    "instructions",
    "extraction-llm",
    "signal_card_prompts.json",
)


class SECSignalCardService:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        self.api_version = os.getenv("OPENAI_API_VERSION", "2024-10-21").strip()
        self.enabled = os.getenv("SIGNAL_CARD_ENABLED", "true").strip().lower() == "true"
        prompts_from_file = self._load_prompts_from_json(PROMPTS_JSON_PATH)

        # Prefer the standalone prompt file, then env overrides, then code defaults.
        self.system_prompt = (
            prompts_from_file.get("system_prompt", "")
            or os.getenv("SIGNAL_CARD_SYSTEM_PROMPT", "").strip()
            or EXTRACTION_SYSTEM_PROMPT
        )
        self.extraction_prompt = (
            prompts_from_file.get("extraction_prompt", "")
            or os.getenv("SIGNAL_CARD_EXTRACTION_PROMPT", "").strip()
            or self._default_extraction_prompt()
        )

        logging.info(
            "Signal card prompt source resolved: prompts_file=%s file_loaded=%s",
            PROMPTS_JSON_PATH,
            bool(prompts_from_file),
        )
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
        return self.enabled and self._client is not None

    def build_extraction_request(
        self,
        ticker: str,
        fiscal_year: Optional[int],
        filing_date: Optional[str],
        target_accession: Optional[str] = None,
        historical_filings: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Build extraction request components without making API call.
        Useful for batch processing.
        Returns dict with system_prompt, user_prompt, and schema.
        """
        normalized_year = fiscal_year or 0
        normalized_filing_date = (filing_date or "").strip()

        prompt = self._build_prompt(
            ticker=ticker,
            fiscal_year=normalized_year,
            filing_date=normalized_filing_date,
            target_accession=target_accession,
            historical_filings=historical_filings or [],
        )

        schema = {
            "name": "SignalCard",
            "strict": True,
            "schema": SignalCard.model_json_schema(),
        }

        return {
            "system_prompt": self.system_prompt,
            "user_prompt": prompt,
            "schema": schema,
        }

    def extract_signal_card(
        self,
        ticker: str,
        fiscal_year: Optional[int],
        filing_date: Optional[str],
        target_accession: Optional[str] = None,
        historical_filings: Optional[list[dict[str, Any]]] = None,
    ) -> SignalCard:
        if not self.is_enabled:
            raise RuntimeError("Signal card extraction is disabled or OPENAI_API_KEY is missing.")

        normalized_year = fiscal_year or 0
        normalized_filing_date = (filing_date or "").strip()

        logging.info(
            "Signal card extraction starting: ticker=%s target_accession=%s fiscal_year=%s filing_date=%s",
            ticker,
            target_accession,
            normalized_year,
            normalized_filing_date,
        )

        # Log historical filings summary
        historical_filings_safe = historical_filings or []
        historical_accessions = [f.get("accession", "") for f in historical_filings_safe]
        historical_years = [f.get("fiscal_year") for f in historical_filings_safe]
        logging.info(
            "Historical filings for multi-year context: count=%d accessions=%s years=%s",
            len(historical_filings_safe),
            historical_accessions,
            historical_years,
        )

        prompt = self._build_prompt(
            ticker=ticker,
            fiscal_year=normalized_year,
            filing_date=normalized_filing_date,
            target_accession=target_accession,
            historical_filings=historical_filings_safe,
        )

        logging.debug(
            "Built LLM prompt for ticker=%s: prompt_length=%d chars",
            ticker,
            len(prompt),
        )
        logging.info(
            "Signal card prompt prepared: ticker=%s target_accession=%s prompt_length_chars=%d",
            ticker,
            target_accession,
            len(prompt),
        )

        schema = {
            "name": "SignalCard",
            "strict": True,
            "schema": SignalCard.model_json_schema(),
        }

        try:
            logging.info(
                "Calling OpenAI structured extraction: model=%s ticker=%s target_accession=%s",
                self.model,
                ticker,
                target_accession,
            )
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.system_prompt,
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_schema", "json_schema": schema},
            )
            content = completion.choices[0].message.content or "{}"
            payload = json.loads(content)
            signal_card = SignalCard.model_validate(payload)
            logging.info(
                "Signal card extraction succeeded: ticker=%s target_accession=%s",
                ticker,
                target_accession,
            )
            return signal_card
        except BadRequestError as exc:
            error_payload = None
            try:
                error_payload = exc.response.json() if getattr(exc, "response", None) else None
            except Exception:
                error_payload = None

            logging.error(
                "OpenAI BadRequest during structured extraction: ticker=%s fiscal_year=%s target_accession=%s prompt_length_chars=%d error_payload=%s",
                ticker,
                normalized_year,
                target_accession,
                len(prompt),
                error_payload,
            )
            raise
        except Exception:
            logging.exception("Structured extraction failed for ticker=%s fiscal_year=%s", ticker, normalized_year)
            raise

    def _build_prompt(
        self,
        ticker: str,
        fiscal_year: int,
        filing_date: str,
        target_accession: Optional[str],
        historical_filings: list[dict[str, Any]],
    ) -> str:
        sections: list[str] = []
        for index, filing in enumerate(historical_filings, start=1):
            entry_accession = str(filing.get("accession", "")).strip()
            entry_year = filing.get("fiscal_year")
            entry_filing_date = filing.get("filing_date")
            entry_item1a = (filing.get("item1a_text") or "").strip()
            entry_item7 = (filing.get("item7_text") or "").strip()

            item1a_length = len(entry_item1a) if entry_item1a else 0
            item7_length = len(entry_item7) if entry_item7 else 0
            logging.debug(
                "Building prompt section FILING #%d: accession=%s year=%s item1a_chars=%d item7_chars=%d",
                index,
                entry_accession,
                entry_year,
                item1a_length,
                item7_length,
            )

            full_item1a = entry_item1a if entry_item1a else "Not provided."
            full_item7 = entry_item7 if entry_item7 else "Not provided."
            sections.append(
                (
                    f"FILING #{index}\n"
                    f"accession={entry_accession}\n"
                    f"fiscal_year={entry_year}\n"
                    f"filing_date={entry_filing_date}\n"
                    f"ITEM 1A (Risk Factors):\n{full_item1a}\n\n"
                    f"ITEM 7 (MD&A):\n{full_item7}"
                )
            )

        historical_context_block = "\n\n".join(sections) if sections else "No filing sections provided."
        logging.debug(
            "Historical context block built: total_sections=%d total_length=%d chars",
            len(sections),
            len(historical_context_block),
        )

        return (
            f"{self.extraction_prompt}\n\n"
            f"ticker={ticker}\n"
            f"fiscal_year={fiscal_year}\n"
            f"filing_date={filing_date}\n"
            f"target_accession={target_accession or ''}\n"
            "Use all provided filing sections as multi-year context for this ticker.\n"
            "Generate one SignalCard for the target filing metadata above.\n\n"
            "Historical filing sections:\n"
            f"{historical_context_block}"
        )

    def _build_ticker_prompt(
        self,
        ticker: str,
        historical_filings: list[dict[str, Any]],
    ) -> str:
        sections: list[str] = []
        expected_cards: list[str] = []

        for index, filing in enumerate(historical_filings, start=1):
            entry_accession = str(filing.get("accession", "")).strip()
            entry_year = filing.get("fiscal_year")
            entry_filing_date = filing.get("filing_date")
            entry_item1a = (filing.get("item1a_text") or "").strip()
            entry_item7 = (filing.get("item7_text") or "").strip()

            full_item1a = entry_item1a if entry_item1a else "Not provided."
            full_item7 = entry_item7 if entry_item7 else "Not provided."

            expected_cards.append(
                f"accession={entry_accession}, fiscal_year={entry_year}, filing_date={entry_filing_date}"
            )
            sections.append(
                (
                    f"FILING #{index}\n"
                    f"accession={entry_accession}\n"
                    f"fiscal_year={entry_year}\n"
                    f"filing_date={entry_filing_date}\n"
                    f"ITEM 1A (Risk Factors):\n{full_item1a}\n\n"
                    f"ITEM 7 (MD&A):\n{full_item7}"
                )
            )

        expected_cards_block = "\n".join(expected_cards) if expected_cards else "No filings provided."
        historical_context_block = "\n\n".join(sections) if sections else "No filing sections provided."

        return (
            f"{self.extraction_prompt}\n\n"
            f"ticker={ticker}\n"
            "Generate exactly one SignalCard output object per filing listed below.\n"
            "Return cards for all listed accessions in a single JSON response.\n"
            "CRITICAL: FILING #1 (most recent) is the TARGET year where new/escalated risks are evaluated.\n"
            "Use FILING #2+ (older years) ONLY as prior-year context for comparing to FILING #1.\n"
            "Every card must include accession, ticker, fiscal_year, and filing_date copied from filing metadata.\n"
            "Use NEW_RISK_FACTORS to mark risks appearing for first time in FILING #1.\n"
            "Use ESCALATED_RISK_FACTORS to show risks whose language intensified from FILING #2+ to FILING #1.\n"
            "Use all filing sections as cross-year context to evaluate risk trajectory.\n\n"
            "Expected output cards:\n"
            f"{expected_cards_block}\n\n"
            "Historical filing sections:\n"
            f"{historical_context_block}"
        )

    def build_ticker_extraction_request(
        self,
        ticker: str,
        historical_filings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = self._build_ticker_prompt(ticker=ticker, historical_filings=historical_filings)
        schema = {
            "name": "TickerSignalCardsResponse",
            "strict": True,
            "schema": TickerSignalCardsResponse.model_json_schema(),
        }
        return {
            "system_prompt": self.system_prompt,
            "user_prompt": prompt,
            "schema": schema,
        }

    def extract_ticker_signal_cards(
        self,
        ticker: str,
        historical_filings: list[dict[str, Any]],
    ) -> list[SignalCardWithAccession]:
        if not self.is_enabled:
            raise RuntimeError("Signal card extraction is disabled or OPENAI_API_KEY is missing.")

        request = self.build_ticker_extraction_request(ticker=ticker, historical_filings=historical_filings)
        prompt = request["user_prompt"]
        schema = request["schema"]

        logging.info(
            "Ticker-level signal card extraction starting: ticker=%s filings=%d prompt_length_chars=%d",
            ticker,
            len(historical_filings),
            len(prompt),
        )

        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_schema", "json_schema": schema},
            )
            content = completion.choices[0].message.content or "{}"
            payload = json.loads(content)
            validated = TickerSignalCardsResponse.model_validate(payload)
            logging.info(
                "Ticker-level signal card extraction succeeded: ticker=%s cards_returned=%d",
                ticker,
                len(validated.cards),
            )
            return validated.cards
        except BadRequestError as exc:
            error_payload = None
            try:
                error_payload = exc.response.json() if getattr(exc, "response", None) else None
            except Exception:
                error_payload = None
            logging.error(
                "OpenAI BadRequest during ticker-level extraction: ticker=%s prompt_length_chars=%d error_payload=%s",
                ticker,
                len(prompt),
                error_payload,
            )
            raise

    def _default_extraction_prompt(self) -> str:
        return (
            "Build a SignalCard JSON object from the provided 10-K filings.\n"
            "\n"
            "FILING STRUCTURE:\n"
            "- FILING #1 is the TARGET (most recent year) where new/escalated risks are measured\n"
            "- FILING #2+ provide prior-year context for comparison\n"
            "\n"
            "INSTRUCTIONS:\n"
            "1) Use evidence strings that are short quote-like excerpts from the filings.\n"
            "2) Do not fabricate facts; if absent, use 'not mentioned' in free-text fields.\n"
            "3) Enum fields must use only allowed values.\n"
            "4) For CAPITAL ALLOCATION, DEMAND SIGNALS, REGULATORY EXPOSURE: extract from target year (FILING #1) MD&A.\n"
            "5) For NEW_RISK_FACTORS: scan FILING #1 Item 1A. Only mark risk as NEW if completely absent from all prior years.\n"
            "6) For ESCALATED_RISK_FACTORS: compare FILING #1 Item 1A against prior years' Item 1A.\n"
            "   - Provide TWO summary sentences: (a) prior-year language/severity, (b) current-year language/severity.\n"
            "   - Include direct quotes demonstrating the intensification.\n"
            "   - Do NOT include risks mentioned in both years without escalation.\n"
            "7) If multiple candidate passages exist, choose the strongest and most specific evidence.\n"
            "8) Keep summaries concise and analytical, not narrative.\n"
            "9) For supply_chain_tightness and risk factor lists, include only material items with quantified or specific evidence."
        )

    def _load_prompts_from_json(self, file_path: str) -> dict[str, str]:
        if not os.path.exists(file_path):
            logging.warning("Prompt file not found, using env/default prompts: %s", file_path)
            return {}

        try:
            with open(file_path, "r", encoding="utf-8") as file:
                payload = json.load(file)

            # Support both single-string and paragraph-array JSON structures.
            system_prompt = str(payload.get("signal_card_system_prompt", "")).strip()
            extraction_prompt = str(payload.get("signal_card_extraction_prompt", "")).strip()

            system_prompt_paragraphs = payload.get("signal_card_system_prompt_paragraphs")
            extraction_prompt_paragraphs = payload.get("signal_card_extraction_prompt_paragraphs")

            if isinstance(system_prompt_paragraphs, list) and system_prompt_paragraphs:
                system_prompt = "\n\n".join(str(p).strip() for p in system_prompt_paragraphs if str(p).strip())
            if isinstance(extraction_prompt_paragraphs, list) and extraction_prompt_paragraphs:
                extraction_prompt = "\n\n".join(str(p).strip() for p in extraction_prompt_paragraphs if str(p).strip())

            return {
                "system_prompt": system_prompt,
                "extraction_prompt": extraction_prompt,
            }
        except Exception:
            logging.exception("Failed to load prompt file, using env/default prompts: %s", file_path)
            return {}
