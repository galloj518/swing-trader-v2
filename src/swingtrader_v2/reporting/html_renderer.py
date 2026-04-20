"""Static HTML rendering for dashboard view models.

The renderer is presentation-only. It formats precomputed reporting contracts
and does not rerun business logic, indicators, gates, or prioritization.
"""

from __future__ import annotations

from html import escape

from swingtrader_v2.reporting.contracts import DashboardRenderModel, FamilyTable, GateFailureGroup, PacketSummaryCard, QueueRow


def _render_list(items: tuple[str, ...], *, empty_label: str = "none") -> str:
    values = items or (empty_label,)
    return "".join(f"<li>{escape(item)}</li>" for item in values)


def _render_queue_rows(rows: tuple[QueueRow, ...]) -> str:
    if not rows:
        return "<p class='empty'>No review queue items available from artifacts.</p>"
    rendered = []
    for row in rows:
        rendered.append(
            "<tr>"
            f"<td>{row.queue_position if row.queue_position is not None else 'unsupported'}</td>"
            f"<td>{escape(row.symbol)}</td>"
            f"<td>{escape(row.setup_family)}</td>"
            f"<td>{escape(row.priority_label)}</td>"
            f"<td>{escape(row.eligibility_label)}</td>"
            f"<td>{escape(row.prioritization_label)}</td>"
            f"<td><ul>{_render_list(row.degraded_reasons, empty_label='none')}</ul></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Queue</th><th>Symbol</th><th>Family</th><th>Priority</th>"
        "<th>Eligibility</th><th>Prioritization</th><th>Degraded State</th></tr></thead>"
        f"<tbody>{''.join(rendered)}</tbody></table>"
    )


def _render_family_table(table: FamilyTable) -> str:
    rows = []
    for row in table.rows:
        rows.append(
            "<tr>"
            f"<td>{row.family_rank if row.family_rank is not None else 'unsupported'}</td>"
            f"<td>{escape(row.symbol)}</td>"
            f"<td>{escape(row.priority_label)}</td>"
            f"<td><ul>{_render_list(row.sort_key_explanations, empty_label='unsupported')}</ul></td>"
            "</tr>"
        )
    body = "".join(rows) if rows else "<tr><td colspan='4'>No ranked rows.</td></tr>"
    return (
        f"<section><h3>{escape(table.family)}</h3>"
        "<table><thead><tr><th>Family Rank</th><th>Symbol</th><th>Priority</th><th>Sort Key Explanations</th></tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _render_packet_summary(card: PacketSummaryCard) -> str:
    return (
        "<article class='packet-card'>"
        f"<h4>{escape(card.symbol)} <span>{escape(card.setup_family)}</span></h4>"
        f"<p><strong>Packet:</strong> {escape(card.packet_id)}</p>"
        f"<p><strong>Summary:</strong> {escape(card.summary)}</p>"
        f"<p><strong>Data Status:</strong> {escape(card.data_status)}</p>"
        f"<ul>{_render_list(card.missing_or_unsupported, empty_label='none')}</ul>"
        "</article>"
    )


def _render_gate_failure(group: GateFailureGroup) -> str:
    return (
        "<article class='gate-failure'>"
        f"<h4>{escape(group.symbol)} <span>{escape(group.packet_id)}</span></h4>"
        f"<ul>{_render_list(group.reasons, empty_label='none')}</ul>"
        "</article>"
    )


def render_dashboard_html(model: DashboardRenderModel) -> str:
    eligible_counts = "".join(
        f"<li>{escape(family)}: {count}</li>"
        for family, count in sorted(model.eligible_counts_by_family.items())
    ) or "<li>none</li>"
    family_tables = "".join(_render_family_table(table) for table in model.family_tables) or "<p>No family-ranked tables available.</p>"
    packet_cards = "".join(_render_packet_summary(card) for card in model.packet_summaries) or "<p>No packet summaries available.</p>"
    gate_failures = "".join(_render_gate_failure(group) for group in model.gate_failures) or "<p>No gate failures recorded.</p>"
    outcome_rows = "".join(
        f"<li>{escape(status)}: {count}</li>"
        for status, count in sorted(model.outcome_summary.status_counts.items())
    ) or "<li>unsupported</li>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(model.title)}</title>
  <style>
    body {{ font-family: Georgia, "Times New Roman", serif; margin: 0; background: linear-gradient(180deg, #f6f1e7 0%, #ffffff 100%); color: #1f2a37; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    .banner {{ border: 2px solid #b45309; background: #fff7ed; padding: 16px; margin-bottom: 20px; }}
    .banner.ok {{ border-color: #166534; background: #f0fdf4; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .stat {{ background: #ffffffcc; padding: 16px; border: 1px solid #d1d5db; }}
    section {{ margin-bottom: 28px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; vertical-align: top; text-align: left; }}
    .packet-card, .gate-failure {{ background: #fff; border: 1px solid #d1d5db; padding: 12px; margin-bottom: 12px; }}
    .empty {{ color: #6b7280; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(model.title)}</h1>
    <div class="banner {'ok' if model.run_health.level == 'ok' else ''}">
      <h2>{escape(model.run_health.title)}</h2>
      <p>{escape(model.run_health.body)}</p>
    </div>
    <div class="stats">
      <div class="stat"><strong>Universe Count</strong><div>{model.universe_count}</div></div>
      <div class="stat"><strong>Candidate Count</strong><div>{model.candidate_count}</div></div>
      <div class="stat"><strong>Eligible By Family</strong><ul>{eligible_counts}</ul></div>
    </div>
    <section>
      <h2>Top Review Queue</h2>
      {_render_queue_rows(model.top_review_queue)}
    </section>
    <section>
      <h2>Family Ranked Tables</h2>
      {family_tables}
    </section>
    <section>
      <h2>Packet Summaries</h2>
      {packet_cards}
    </section>
    <section>
      <h2>Gate Failure Reasons</h2>
      {gate_failures}
    </section>
    <section>
      <h2>Watchlist Changes Vs Prior Session</h2>
      <div class="stats">
        <div class="stat"><strong>Added</strong><ul>{_render_list(model.watchlist_changes.added, empty_label='none')}</ul></div>
        <div class="stat"><strong>Removed</strong><ul>{_render_list(model.watchlist_changes.removed, empty_label='none')}</ul></div>
        <div class="stat"><strong>Unchanged</strong><ul>{_render_list(model.watchlist_changes.unchanged, empty_label='none')}</ul></div>
      </div>
    </section>
    <section>
      <h2>Outcome Summary</h2>
      <ul>{outcome_rows}</ul>
    </section>
    <section>
      <h2>Survivorship Bias Disclosure</h2>
      <p>{escape(model.survivorship_bias_disclosure)}</p>
    </section>
  </main>
</body>
</html>"""
