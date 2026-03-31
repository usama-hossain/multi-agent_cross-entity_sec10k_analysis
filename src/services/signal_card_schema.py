from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupplyChainSignal(StrictSchemaModel):
    signal: str
    severity: Literal["low", "moderate", "high"]
    evidence: str


class CapitalAllocation(StrictSchemaModel):
    capex_direction: Literal["growing", "stable", "declining"]
    capex_details: str
    capex_split: str
    language_tone: str


class DemandSignals(StrictSchemaModel):
    customer_growth: str
    backlog_direction: Literal["growing", "stable", "declining", "not_mentioned"]
    load_changes: str
    evidence: str


class RiskFactor(StrictSchemaModel):
    risk: str
    category: str
    evidence: str


class EscalatedRiskFactor(StrictSchemaModel):
    risk: str
    category: str
    prior_language_summary: str
    current_language_summary: str
    evidence: str


class RegulatoryExposure(StrictSchemaModel):
    pending_rate_cases: str
    emissions_mandates: str
    compliance_investments: str
    evidence: str


class StrategicPosture(StrictSchemaModel):
    direction: Literal["expansion", "stable", "contraction", "pivot"]
    summary: str
    evidence: str


class GenerationMixShift(StrictSchemaModel):
    coal_retirements: str
    renewable_additions: str
    battery_storage: str
    dispatchable_adequacy: str
    evidence: str


class FuelInputExposure(StrictSchemaModel):
    price_sensitivity: str
    hedging_changes: str
    ppa_terms: str
    evidence: str


class SignalCard(StrictSchemaModel):
    ticker: str
    fiscal_year: int
    filing_date: str
    capital_allocation: CapitalAllocation
    supply_chain_tightness: list[SupplyChainSignal]
    demand_signals: DemandSignals
    new_risk_factors: list[RiskFactor]
    escalated_risk_factors: list[EscalatedRiskFactor]
    regulatory_exposure: RegulatoryExposure
    strategic_posture: StrategicPosture
    generation_mix_shift: GenerationMixShift
    fuel_and_input_exposure: FuelInputExposure


class SignalCardWithAccession(SignalCard):
    accession: str


class TickerSignalCardsResponse(StrictSchemaModel):
    cards: list[SignalCardWithAccession]
