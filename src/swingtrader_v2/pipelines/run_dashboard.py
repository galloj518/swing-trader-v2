"""Dashboard payload and static HTML orchestration."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from swingtrader_v2.domain.enums import EnvironmentName
from swingtrader_v2.pipelines.common import artifact_ref, build_run_context, read_json, update_run_manifest, write_json
from swingtrader_v2.reporting.dashboard_payload import DashboardAssemblerInput, build_dashboard_bundle
from swingtrader_v2.reporting.html_renderer import render_dashboard_html


def run_dashboard(
    *,
    ranking_path: str | Path,
    run_manifest_path: str | Path,
    packets_dir: str | Path,
    prior_dashboard_path: str | Path | None = None,
    as_of_date: date | None = None,
    environment: EnvironmentName = EnvironmentName.LOCAL,
    config_root: str | Path = "config",
    artifact_root: str | Path = "artifacts",
) -> dict[str, str]:
    manifest = read_json(run_manifest_path)
    context = build_run_context(
        as_of_date=as_of_date or date.fromisoformat(manifest["as_of_date"]),
        environment=environment,
        config_root=config_root,
        artifact_root=artifact_root,
    )
    ranking = read_json(ranking_path)
    packet_paths = sorted(Path(packets_dir).glob("pkt_*.json"))
    packets = tuple(read_json(path) for path in packet_paths)
    prior_dashboard = read_json(prior_dashboard_path) if prior_dashboard_path else None
    dashboard = build_dashboard_bundle(
        DashboardAssemblerInput(
            run_manifest=manifest,
            ranking=ranking,
            packets=packets,
            prior_dashboard_payload=prior_dashboard,
        )
    )
    payload_path = write_json(context.dashboard_dir / "dashboard_payload.json", dashboard.artifact.payload)
    html_path = context.dashboard_dir / "dashboard.html"
    html_path.write_text(render_dashboard_html(dashboard.render_model), encoding="utf-8")
    update_run_manifest(context, [artifact_ref("dashboard_payload", str(payload_path.relative_to(context.run_root)))])
    return {
        "run_root": str(context.run_root),
        "dashboard_payload_path": str(payload_path),
        "dashboard_html_path": str(html_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dashboard payload and static HTML.")
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--run-manifest", required=True)
    parser.add_argument("--packets-dir", required=True)
    parser.add_argument("--prior-dashboard")
    parser.add_argument("--as-of-date")
    parser.add_argument("--environment", default="local", choices=[item.value for item in EnvironmentName])
    parser.add_argument("--config-root", default="config")
    parser.add_argument("--artifact-root", default="artifacts")
    args = parser.parse_args()
    result = run_dashboard(
        ranking_path=args.ranking,
        run_manifest_path=args.run_manifest,
        packets_dir=args.packets_dir,
        prior_dashboard_path=args.prior_dashboard,
        as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
        environment=EnvironmentName(args.environment),
        config_root=args.config_root,
        artifact_root=args.artifact_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
