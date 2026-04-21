# SwingTrader v2

SwingTrader v2 is a production-grade discretionary swing trading decision-support system for liquid U.S. equities.

The repository implements an end-of-day, packet-first workflow that normalizes daily market data, derives descriptive technical state, resolves anchors, scans setup families, assembles inspectable packets, applies ordered eligibility gates, builds a transparent review queue, renders artifact-only reporting, and tracks lifecycle and outcome history without inferring trades the operator did not log.

## v1 Architecture

The current v1 implementation follows these non-negotiable design rules:

- end-of-day only
- packet-first architecture
- strict separation of concerns
- hard eligibility gates before prioritization
- setup-family separation
- config-driven anchors
- artifact-first inspectability
- explicit missing, stale, unsupported, and low-confidence handling
- deterministic outputs from identical inputs and config
- no business logic in reporting or presentation
- no black-box ML, auto-execution, broker coupling, or news/sentiment dependency

Primary layers:

- `src/swingtrader_v2/data/`: provider contracts, freshness, symbol master, corporate actions, portfolio snapshot normalization
- `src/swingtrader_v2/market/`: NYSE calendar, bar normalization, benchmark prep, universe filtering
- `src/swingtrader_v2/analysis/`: descriptive moving averages, momentum, volume, volatility, patterns, and relative strength
- `src/swingtrader_v2/anchors/`: deterministic anchor resolution and daily-bar AVWAP proxy support
- `src/swingtrader_v2/scanner/`: independent family detectors plus candidate/rejection artifacts
- `src/swingtrader_v2/packet/`: packet assembly, validation, completeness, and trade-plan scaffold
- `src/swingtrader_v2/selector/`: setup classification, ordered eligibility, and transparent review-order prioritization
- `src/swingtrader_v2/reporting/`: artifact-only dashboard payloads and static HTML rendering
- `src/swingtrader_v2/tracking/`: append-only lifecycle, manual decision ingestion, and forward outcome tracking
- `src/swingtrader_v2/pipelines/`: thin orchestration entrypoints for scan, packets, rankings, dashboard, and tracking

## Supported v1 Scope

- Daily-bars only
- Liquid U.S. equities
- Baseline provider path through `yfinance`
- Setup families:
  - `trend_pullback`
  - `base_breakout`
  - `avwap_reclaim`
- Explicit split handling and dividend tagging
- Daily-bar AVWAP proxy only, clearly labeled as a proxy
- Artifact schemas for packets, candidate lists, rankings, dashboard payloads, run manifests, decision events, and outcome records
- Static GitHub Actions orchestration for deterministic end-of-day artifact generation

## Unsupported v1 Scope

- Intraday or real-time workflows
- Exact intraday AVWAP
- Automated order execution
- Live broker coupling as a required dependency
- News/sentiment-driven logic
- Hidden discretionary overrides in code
- Black-box predictive models
- Reporting that recomputes business logic
- Backtesting engine or full simulation framework

## Current Implementation Status

Phase and module status:

- Phase 1 foundation: implemented
  - schemas, domain contracts, config loading/validation, deterministic config hashing
- Phase 2 data and market backbone: implemented
  - yfinance adapter, universe filtering, freshness, corporate actions, symbol master, SPY benchmark prep
- Phase 3 descriptive analysis and anchors: implemented
  - feature computation, anchor resolution, daily-bar AVWAP proxy, provenance
- Phase 4 scanner: implemented
  - independent detectors, rejection taxonomy, candidate artifacts
- Phase 5A packets: implemented
  - canonical packet assembly, validation, completeness, discretionary trade-plan scaffold
- Phase 5B and Phase 6 selector: implemented
  - family classification, ordered eligibility gates, transparent prioritization
- Phase 7 reporting: implemented
  - schema-valid dashboard payload plus static HTML renderer
- Phase 8 tracking: implemented
  - append-only lifecycle history, explicit manual decisions, forward outcomes
- Phase 9 orchestration: implemented
  - pipeline entrypoints and GitHub Actions workflows
- Final hardening: implemented
  - shared fixture catalog, deterministic regression tests, integration coverage, checked-in golden artifacts

Current test surface:

- schema and contract tests
- module unit tests
- scanner and selector correctness tests
- packet determinism and completeness tests
- anchor determinism tests
- reporting contract and rendering tests
- tracking replay/outcome tests
- offline end-to-end integration and golden-artifact regression tests

## Running Tests

Recommended setup:

```bash
python -m venv .venv
. .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

Run the full deterministic suite:

```bash
PYTHONPATH=src python -m pytest tests --basetemp=.pytest_tmp -q -p no:cacheprovider
```

Useful narrower runs:

```bash
PYTHONPATH=src python -m pytest tests/scanner tests/selector -q -p no:cacheprovider
PYTHONPATH=src python -m pytest tests/integration/test_pipeline_regression.py -q -p no:cacheprovider
```

Notes:

- The checked-in regression suite is intentionally offline and deterministic.
- Live `yfinance` behavior is not exercised by default in CI.
- Golden artifacts live under [tests/fixtures/golden/final_pipeline](C:/Users/gallo/swing-trader-v2/tests/fixtures/golden/final_pipeline).

## GitHub Actions

The repository currently defines two workflows:

- [`.github/workflows/daily_eod_scan.yml`](C:/Users/gallo/swing-trader-v2/.github/workflows/daily_eod_scan.yml)
  - scheduled weekday end-of-day orchestration
  - runs daily scan, packet build, rankings, and dashboard generation
  - uploads resulting artifacts
  - does not run tracking by default because tracking depends on explicit operator decision inputs and later outcome windows
- [`.github/workflows/regression_artifacts.yml`](C:/Users/gallo/swing-trader-v2/.github/workflows/regression_artifacts.yml)
  - runs the deterministic regression suite on pushes, pull requests, and manual dispatch
  - covers packet, scanner, selector, anchors, reporting, tracking, integration, and the supporting data/market/analysis tests they depend on
  - keeps provider-network behavior out of the regression lane so artifact determinism stays testable

## Open v1 Trust Blockers

- Live-provider smoke coverage: not yet automated. The deterministic suite proves offline contract behavior, but there is still no committed CI lane that validates real `yfinance` responses end-to-end.
- Selector anchor-policy status: still needs an explicit product decision. The current tests expose that some otherwise clean trend cases can become ineligible when anchor availability makes packet data sufficiency fail; that behavior is visible now, but it is not yet a closed policy decision.
- CI coverage status: deterministic CI coverage is now broad, but it still intentionally excludes network-dependent provider smoke checks and any workflow path that requires manual decision inputs.
- Operational trust status: the repository is implementation-grade for deterministic iteration, but not yet "production trusted" until the live-provider lane and the selector anchor-policy decision are closed explicitly.
