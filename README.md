# Cross-Entity SEC 10-K Signal Analysis Engine

> An Azure pipeline that ingests SEC 10-K filings for a sector-linked group of energy/utilities companies and extracts structured, per-company risk and supply-chain signals for cross-entity comparison.

---

## Status

| Layer | State |
|---|---|
| Ingestion pipeline (download → markdown → section extraction, Azure Table Storage state machine) | ✅ Implemented, tested |
| Structured Signal Card extraction (GPT-4.1 + Pydantic, Azure OpenAI Batch API) | ✅ Implemented, tested |
| Streamlit Signal Card browser | ✅ Implemented, deployed |
| Cross-entity comparison view / live analysis runner in dashboard | 🚧 In progress |
| Adversarial multi-agent validation (Analyst vs. Contrarian, LangGraph) | 📋 Planned — designed, not yet built |

---

## Table of Contents

- [Project Summary](#project-summary)
- [Early Observations](#early-observations)
- [Core Features](#core-features)
- [Roadmap](#roadmap)
- [Technical Architecture](#technical-architecture)
- [Technology Stack](#technology-stack)

---

## Project Summary

The Cross-Entity SEC 10-K Signal Analysis Engine is an Azure pipeline that processes SEC 10-K filings across a sector-linked group of energy/utilities companies — competitors, suppliers, and customers along the Vistra power/data-center supply chain — and extracts structured analytical signals from each filing year.

Where traditional financial analysis reads filings in isolation, this system is built to read the sector at once. A 12-field **Signal Card** schema captures risk sentiment, supply chain posture, capacity constraints, and regulatory exposure for each company per filing year, extracted via a single structured **GPT-4.1** call per company's filing history.

The pipeline currently covers **9 companies** across 5 filing years each (see [`config/tickers.json`](config/tickers.json)); expanding sector coverage is on the [roadmap](#roadmap). Extracted Signal Cards are browsable through a Streamlit dashboard deployed on Azure Web App.

The next major piece of the system — a two-agent **LangGraph** pipeline (Analyst vs. Contrarian) intended to stress-test each company's claims against peer-company evidence — is designed but not yet implemented. See [Roadmap](#roadmap).

---

## Diagram

![Cross-Entity SEC 10-K Signal Analysis Engine](c4-context-signal-card-platform-v2.svg)

---

## Early Observations

*The following came from manually reviewing extracted Signal Cards, not from an automated cross-entity analysis system — that layer is still on the [roadmap](#roadmap). They're included here as a sense of what the underlying data can surface, not as validated findings from a running pipeline.*

### Vistra (VST) Backlog Signal

Pre-2023 Signal Cards for Vistra show a near-doubling of contracted backlog relative to revenue, at a time when market commentary was focused on near-term margin compression. The capacity-constraint field flagged this before the market repriced the stock on data-center power-demand tailwinds roughly 18 months later — worth a closer, more rigorous look once cross-entity comparison tooling exists.

### Energy Sector Power Scarcity

Reading supply-tightness and capacity-constraint fields side by side for Constellation Energy (CEG) and Equinix (EQIX) suggests coordinated supply-side pressure building in 2021–2022 filings, ahead of the broader data-center power-demand surge. This is the kind of pattern the planned Contrarian agent is meant to check systematically against peer evidence rather than by eye.

### Narrative Divergence as a Potential Signal

When one company's risk disclosures diverge sharply from sector peers on the same risk theme, that divergence itself may be informative — a hypothesis motivating the cross-entity comparison work, not yet something the system quantifies automatically.

---

## Core Features

*Everything in this section is implemented and covered by tests unless noted otherwise.*

### Idempotent Ingestion Pipeline
State-table-driven orchestration with skip-on-complete logic across three phases — download, markdown conversion, and section extraction — backed by **Azure Table Storage**. Re-runs are safe; completed phases are skipped automatically.

### Structured Signal Card Extraction
A 12-field schema purpose-built for energy-sector analysis. Each company's full filing history is processed via **GPT-4.1** with Pydantic-enforced structured outputs. Bulk extraction runs through the **Azure OpenAI Batch API**; a measured cost-savings figure will be added here once a benchmarking script is committed.

### Model Selection
GPT-4.1 was chosen over GPT-4.1-mini after informal side-by-side comparison across three prompt iterations, based on citation accuracy and signal differentiation. This was a qualitative pass, not an automated benchmark — an eval script quantifying the difference is a good candidate for the roadmap.

### Streamlit Signal Card Browser
Deployed on **Azure Web App**. Lets you search/filter by ticker, see per-company coverage (which filing years have been processed), and inspect the full structured Signal Card for any ticker/year. Secured via Managed Identities, Key Vault secrets, and Azure DevOps CI/CD.

---

## Roadmap

- **Adversarial multi-agent validation.** A two-agent LangGraph pipeline — an Analyst agent producing initial claims and a Contrarian agent retrieving peer-company Signal Cards to challenge them — intended to improve factual groundedness of cross-entity claims. Not yet implemented; no `langgraph` dependency or agent code exists in the repo yet. Once built, this section will report real ablation numbers with the eval script that produced them.
- **Cross-entity comparison view.** Side-by-side Signal Card comparison and timeline view in the dashboard, beyond the current single-ticker browser.
- **Live analysis runner.** Trigger extraction/analysis for a new filing directly from the dashboard rather than via the API/CLI.
- **Sector coverage expansion.** Grow beyond the current 9-company roster toward broader energy/utilities sector coverage.
- **Automated groundedness/differentiation eval.** Replace the informal model-selection comparison with a committed, re-runnable benchmark.

---

## Technology Stack

| Category | Technologies |
|---|---|
| **Cloud Platform** | Azure (OpenAI Service, Blob Storage, Table Storage, Web App, Key Vault, Managed Identities, DevOps CI/CD) |
| **LLM** | GPT-4.1, Azure OpenAI Batch API |
| **Data Extraction** | `edgartools`, SEC EDGAR API, XBRL |
| **Validation** | Pydantic (structured output enforcement) |
| **Dashboard** | Streamlit |
| **Language** | Python |
| **Version Control** | Git, Azure DevOps Repos |
| **Planned** | LangGraph (multi-agent validation layer — see [Roadmap](#roadmap)) |

---

*Built with Azure OpenAI · Python · Streamlit*
