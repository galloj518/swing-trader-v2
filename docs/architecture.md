# SwingTrader v2 Architecture

## Product Scope

SwingTrader v2 is a discretionary decision-support system for liquid U.S. equities. Its purpose is to help a human operator review end-of-day setup candidates, inspect structured evidence, apply judgment outside the codebase, and track outcomes over time.

The product is not intended to automate trading decisions or hide discretionary behavior inside the system. The software produces deterministic artifacts and rankings from defined inputs and configuration, while leaving final trade decisions to the operator.

## Supported In v1

- End-of-day only workflows
- Liquid U.S. equities
- Packet-first candidate inspection
- Hard eligibility gating before ranking
- Setup-type separation by family
- Config-driven anchor definitions
- Artifact-first inspectability
- Explicit missing and unsupported data signaling
- Deterministic outputs from identical inputs and config
- Schema versioning for major machine-readable artifacts
- Baseline market data support through yfinance
- AVWAP implemented only as a clearly labeled daily-bar proxy
- Artifact-driven reporting
- Post-decision and outcome tracking

## Unsupported In v1

- Intraday or real-time workflows
- Exact intraday AVWAP
- Automated order execution
- Live broker coupling as a core dependency
- News or sentiment as a core dependency
- Black-box ML prediction
- Hidden discretionary overrides in code
- Reporting that recomputes business logic
- Schwab as a required dependency

Schwab support may be added later as an optional integration, but it is not part of the v1 core path.

## Major Modules And Responsibilities

- `domain`
  Core entities, value objects, enums, setup identifiers, artifact metadata, and shared contracts.
- `config`
  Configuration loading, environment overlays, defaults, and validation of operator-controlled settings.
- `data`
  Market-data provider adapters, normalization, raw input capture, and explicit missing-data handling.
- `market`
  Reusable end-of-day market structure derivations built from normalized data.
- `analysis`
  Shared analytical primitives that do not belong to scanning, selection, or presentation.
- `anchors`
  Config-driven anchor generation and anchor metadata construction.
- `scanner`
  Setup-family-specific candidate identification and classification.
- `packet`
  Assembly of candidate packets and schema-versioned artifact serialization.
- `selector`
  Hard eligibility gate evaluation followed by deterministic prioritization of eligible packets.
- `reporting`
  Human-facing outputs generated strictly from artifacts without recomputing business logic.
- `tracking`
  Decision journaling, follow-up state, and outcome tracking after review.
- `pipelines`
  Thin orchestration for end-to-end workflows.

## Packet Shape

The packet is the primary inspectable artifact in the system. Exact schemas will be formalized later, but every packet should conceptually include:

- packet metadata
  Packet schema version, generation timestamp, environment, config fingerprint, and data provenance.
- symbol context
  Ticker, instrument metadata, liquidity context, and relevant date range.
- setup identity
  Setup family, setup subtype if applicable, and scanner rationale.
- input completeness
  Explicit missing, unsupported, stale, or partial-data indicators.
- anchor set
  Config-driven anchor values and anchor provenance, including any daily-bar AVWAP proxy labels.
- analytical evidence
  Derived end-of-day features needed by downstream eligibility and ranking logic.
- eligibility results
  Hard gate pass/fail outcomes with reasons.
- ranking inputs
  Deterministic scoring inputs for already-eligible candidates only.
- operator inspection payload
  Human-readable summaries or references that are produced from artifacts, not ad hoc recomputation.

## Setup Families

v1 should separate setup handling by family rather than blending all patterns into one monolithic classifier. Exact families can be finalized during implementation, but the architecture assumes distinct flows such as:

- continuation setups
- pullback or trend-resumption setups
- breakout or range-resolution setups
- reversal or repair setups

Each family should own its own scan criteria, evidence expectations, and possibly family-specific ranking inputs, while still feeding a common packet contract.

## Gate Ordering

Gate ordering is strict:

1. Inputs are loaded and normalized.
2. Anchors and shared end-of-day derived context are built.
3. Scanners identify candidates by setup family.
4. Hard eligibility gates evaluate those candidates.
5. Only eligible candidates are packetized for ranking and downstream review.
6. Selector prioritization orders eligible packets.
7. Reporting renders outputs from artifacts only.
8. Tracking records operator decisions and later outcomes.

No prioritization should run before eligibility is complete.

## Ranking Philosophy

Ranking is comparative prioritization, not prediction. The selector should:

- operate only on already-eligible candidates
- remain deterministic from identical inputs and config
- prefer transparent scoring inputs over opaque models
- preserve inspectability so an operator can understand why one packet outranked another
- avoid hidden overrides or undocumented heuristics

No black-box ML prediction is allowed in v1.

## Artifact Contracts

All major machine-readable artifacts must be schema-versioned and designed for inspectability. Expected artifact categories include:

- normalized market-data artifacts
- anchor artifacts
- candidate packets
- selector outputs
- reporting inputs and outputs
- tracking records

Contracts should make unsupported or missing data explicit instead of silently omitting fields. Reporting must consume these artifacts directly and must not recompute scanner or selector logic.

## Tracking Approach

Tracking should remain downstream from selection and reporting. It should capture:

- operator decisions and notes
- watchlist or follow-up state
- outcome measurements after review
- artifact references needed for auditability

Tracking is for feedback and process review, not for secretly altering the live selection logic outside versioned code and config.

## Testing Strategy

The testing approach should mirror the architecture:

- schema and contract tests for machine-readable artifacts
- unit tests per module boundary
- packet tests focused on inspectability and deterministic structure
- scanner tests separated by setup family
- selector tests covering hard gates before ranking
- reporting tests ensuring artifact-only consumption
- tracking tests for auditability and deterministic record shaping
- integration tests for end-to-end end-of-day flows

Tests and schemas should be added with implementation rather than deferred.

## Phased Implementation Plan

### Phase 1: Foundation

- establish package scaffolding
- define configuration layout
- draft schema versioning conventions
- formalize core domain entities and artifact contracts

### Phase 2: Data And Anchors

- implement baseline yfinance ingestion
- normalize end-of-day market data
- add explicit missing-data signaling
- implement config-driven anchors
- implement clearly labeled daily-bar proxy AVWAP

### Phase 3: Scanning And Packets

- implement setup-family scanners
- assemble packet artifacts
- add packet schema validation

### Phase 4: Eligibility And Selection

- implement hard eligibility gates
- implement deterministic prioritization for eligible packets
- emit selector artifacts

### Phase 5: Reporting And Tracking

- implement artifact-only reporting
- implement decision and outcome tracking
- add operator-facing output formats

### Phase 6: Pipeline Hardening

- wire end-to-end pipelines
- add broader integration coverage
- harden reproducibility and artifact auditability
- prepare for optional later integrations such as Schwab without coupling v1 core logic to them
