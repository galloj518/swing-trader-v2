# SwingTrader v2 Repository Guidance

## Repository Purpose

SwingTrader v2 is a production-grade discretionary swing trading decision-support system for liquid U.S. equities.

The system is intended to help a human operator inspect eligible setups, compare candidates, and review deterministic artifacts produced from end-of-day market data and operator-supplied inputs. It is not an execution engine, not an autonomous trading system, and not a black-box prediction platform.

## High-Level Architecture

The repository follows a packet-first architecture with strict separation of concerns:

1. Data acquisition and normalization gather baseline market inputs.
2. Anchor construction produces configured reference levels and anchor metadata.
3. Scanner logic identifies setup candidates by setup family.
4. Eligibility gates remove disallowed or incomplete candidates before ranking.
5. Packet assembly produces inspectable machine-readable artifacts for each candidate.
6. Selector logic prioritizes only already-eligible packets.
7. Reporting consumes artifacts only and does not recompute business logic.
8. Tracking records post-decision outcomes and workflow state for later review.

All major machine-readable artifacts must be schema-versioned, deterministic from identical inputs and config, and explicit about missing or unsupported data.

## Non-Negotiables

The following constraints are fixed and must be treated as non-negotiable:

- v1 is end-of-day only
- packet-first architecture
- strict separation of concerns
- hard eligibility gates before prioritization
- setup-type separation
- config-driven anchors
- artifact-first inspectability
- explicit missing/unsupported-data handling
- deterministic outputs from identical inputs/config
- no business logic in the presentation layer
- schema versioning for all major machine-readable artifacts
- no black-box ML prediction
- no automated order execution
- no news/sentiment dependence as a core dependency
- no hidden discretionary overrides in code
- no live broker coupling as a core dependency
- yfinance is the baseline provider
- Schwab is optional and planned later
- AVWAP in v1 must be implemented as a clearly labeled daily-bar proxy, not exact intraday AVWAP
- reporting must consume artifacts only and must not recompute business logic

## Layer Ownership Rules

Keep ownership boundaries clear when editing files:

- `src/swingtrader_v2/domain/`
  Defines core domain concepts, enums, value objects, and artifact contracts. No provider-specific fetching, presentation logic, or ad hoc ranking logic.
- `src/swingtrader_v2/config/`
  Loads and validates configuration only. No market-data fetching, scanning, ranking, or reporting decisions.
- `src/swingtrader_v2/data/`
  Provider adapters, normalization, persistence of raw or normalized inputs, and missing-data surfacing. No setup classification or prioritization logic.
- `src/swingtrader_v2/market/`
  Shared market structure utilities and derived end-of-day series preparation. No reporting or presentation logic.
- `src/swingtrader_v2/anchors/`
  Config-driven anchor construction only. No ranking, reporting, or hidden discretionary overrides.
- `src/swingtrader_v2/scanner/`
  Setup-family-specific candidate discovery and classification only. Do not prioritize here.
- `src/swingtrader_v2/packet/`
  Packet assembly, artifact shaping, and schema-bound serialization only. No presentation-layer rendering.
- `src/swingtrader_v2/selector/`
  Eligibility enforcement and prioritization over already-scanned candidates and packets. Do not fetch data or render reports here.
- `src/swingtrader_v2/reporting/`
  Read artifacts and render human-consumable outputs only. Must not recompute business logic.
- `src/swingtrader_v2/tracking/`
  Journal, follow-up, and post-decision outcome tracking only. No scanning or ranking logic.
- `src/swingtrader_v2/pipelines/`
  Orchestration of the end-to-end flow. Keep orchestration thin; business rules belong in their owning layer.
- `schemas/`
  Versioned machine-readable contracts. Keep synchronized with artifact-producing code.
- `tests/`
  Tests should mirror the layer being changed and validate behavior at the correct boundary.

## Responsibility Separation Rules

Codex must not mix scanner, classifier, eligibility, prioritization, and reporting responsibilities in the same module or change set without clear necessity.

Specific guardrails:

- Scanner code may identify setup candidates, but must not rank them.
- Eligibility code must enforce hard gates before any prioritization is applied.
- Prioritization code may only operate on already-eligible candidates or packets.
- Reporting code must only consume produced artifacts and must not reconstruct scanner or selector logic.
- Presentation-layer code must not contain business rules.

## Change Discipline

- Make changes minimal and targeted.
- Prefer extending the smallest correct layer over broad refactors.
- Do not introduce convenience shortcuts that blur ownership boundaries.
- Preserve deterministic behavior from identical inputs, config, and environment assumptions.
- Surface missing or unsupported data explicitly instead of silently falling back.

## Tests And Schemas

- Add or update tests with every implementation change.
- Add or update schemas alongside any major machine-readable artifact introduction or modification.
- Schema changes must be intentional and versioned.
- Artifact producers and artifact consumers must stay aligned through tests.

## Conflict Handling

If a requested change conflicts with this architecture or any non-negotiable above, Codex should say so explicitly before proceeding and should propose a compliant alternative when possible.
