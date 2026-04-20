from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from swingtrader_v2.analysis.momentum import compute_momentum_features
from swingtrader_v2.analysis.moving_averages import compute_moving_averages
from swingtrader_v2.analysis.patterns import compute_pattern_features
from swingtrader_v2.analysis.relative_strength import compute_relative_strength_features
from swingtrader_v2.analysis.volume import compute_volume_features
from swingtrader_v2.analysis.volatility import compute_volatility_features
from swingtrader_v2.anchors.definitions import ManualAnchorDefinition
from swingtrader_v2.anchors.resolver import resolve_anchor
from swingtrader_v2.data.corporate_actions import CorporateAction
from swingtrader_v2.data.freshness import assess_freshness
from swingtrader_v2.data.portfolio_snapshot import PortfolioPosition, PortfolioSnapshot
from swingtrader_v2.domain.enums import ArtifactType, DataSupportStatus, EnvironmentName, SetupFamily
from swingtrader_v2.domain.ids import build_run_id
from swingtrader_v2.domain.models import ArtifactRef
from swingtrader_v2.market.bars import normalize_daily_bars
from swingtrader_v2.packet.assembler import PacketAssemblyInput, assemble_packet
from swingtrader_v2.packet.completeness import assess_packet_completeness
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate
from swingtrader_v2.selector.classifier import ClassificationResult, classify_candidates


NY_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _rows(count: int, *, start: date = date(2025, 1, 2), base: float = 100.0, slope: float = 0.45) -> list[dict]:
    rows: list[dict] = []
    for index in range(count):
        close = base + (index * slope) + (((index % 8) - 4) * 0.35)
        rows.append(
            {
                "date": (start.fromordinal(start.toordinal() + index)).isoformat(),
                "open": close - 0.6,
                "high": close + 1.1,
                "low": close - 1.0,
                "close": close,
                "adjusted_close": close,
                "volume": 1_600_000 + ((index % 9) * 120_000),
                "dividend": 0.0,
                "split_ratio": 1.0,
            }
        )
    return rows


def build_packet_bundle(
    *,
    symbol: str = "AAPL",
    family: SetupFamily = SetupFamily.TREND_PULLBACK,
    evidence: tuple[str, ...] = ("trend_intact", "support_proximity_present"),
    evidence_count: int | None = None,
    excess_return_63d: float = 0.18,
    median_dollar_volume_50d: float = 55_000_000.0,
    classification_status: DataSupportStatus = DataSupportStatus.OK,
) -> dict:
    config_fingerprint = "a" * 64
    as_of_date = date(2025, 9, 18)
    run_id = build_run_id(
        as_of_date=as_of_date,
        environment=EnvironmentName.LOCAL.value,
        universe_name="liquid_us_equities",
        config_fingerprint=config_fingerprint,
    )
    bar_result = normalize_daily_bars(symbol, _rows(260))
    bars = bar_result.bars
    benchmark = normalize_daily_bars("SPY", _rows(260, base=95.0, slope=0.25)).bars
    freshness = assess_freshness(last_bar_date=bars[-1].session_date, as_of=datetime(2025, 9, 18, 17, 0, tzinfo=NY_TZ))
    anchor = resolve_anchor(
        symbol=symbol,
        bars=bars,
        definition=ManualAnchorDefinition(
            family="manual_anchor",
            name="manual_reference",
            anchor_date=bars[-30].session_date,
            anchor_value=bars[-30].close,
        ),
        config_fingerprint=config_fingerprint,
    )
    candidate = ScannerCandidate(
        symbol=symbol,
        family=family,
        evidence=evidence,
        evidence_count=evidence_count if evidence_count is not None else len(evidence),
        excess_return_63d=excess_return_63d,
        median_dollar_volume_50d=median_dollar_volume_50d,
        classification_status=classification_status,
        reason_codes=(),
    )
    assembled = assemble_packet(
        PacketAssemblyInput(
            candidate=candidate,
            bar_result=bar_result,
            freshness=freshness,
            moving_averages=compute_moving_averages(bars),
            momentum=compute_momentum_features(bars),
            volume=compute_volume_features(bars),
            volatility=compute_volatility_features(bars),
            patterns=compute_pattern_features(bars),
            relative_strength=compute_relative_strength_features(
                bars,
                benchmark,
                peer_excess_returns={21: [0.03, 0.05, 0.09], 63: [0.08, 0.11, 0.14]},
            ),
            anchors=(anchor,),
            run_id=run_id,
            as_of_date=as_of_date,
            generated_at=datetime(2025, 9, 18, 21, 15, tzinfo=UTC),
            environment=EnvironmentName.LOCAL,
            config_fingerprint=config_fingerprint,
            artifact_lineage=(
                ArtifactRef(
                    artifact_type=ArtifactType.CANDIDATE_LIST,
                    artifact_id=f"cand_{symbol.lower()}_{family.value}",
                    schema_version="v1.0.0",
                ),
            ),
        )
    )
    return {
        "packet": assembled.payload,
        "trade_plan": assembled.trade_plan,
        "candidate": candidate,
        "completeness": assess_packet_completeness(assembled.payload),
    }


def build_classification(
    *candidates: ScannerCandidate,
    setup_config: dict | None = None,
) -> ClassificationResult:
    return classify_candidates(tuple(candidates), config=setup_config)


def build_instrument_context(*, exchange: str = "NASDAQ", asset_type: str = "common_stock", country: str = "US") -> dict:
    return {
        "exchange": exchange,
        "asset_type": asset_type,
        "country": country,
    }


def build_portfolio_snapshot(*symbols: str, degraded: bool = False) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        positions=tuple(PortfolioPosition(symbol=symbol, shares=10.0) for symbol in symbols),
        reason_codes=("duplicate_symbol_aggregated",) if degraded else (),
        degraded=degraded,
    )


def build_recent_split() -> tuple[CorporateAction, ...]:
    return (CorporateAction(action_type="split", ex_date=date(2025, 9, 10), value=2.0, raw_value="2:1"),)


def build_recent_dividend() -> tuple[CorporateAction, ...]:
    return (CorporateAction(action_type="dividend", ex_date=date(2025, 9, 16), value=0.25),)
