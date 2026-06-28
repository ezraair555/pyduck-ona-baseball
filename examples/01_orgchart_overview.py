"""
Example 01 — Org-chart ONA across the NL East.

For every (team, season) we run the full pyduck-ona workflow on the
synthetic coaching hierarchy from ``nl_east.build_orgchart``:

  1. ``hierarchy_valid``  — chain integrity
  2. ``hierarchy_stats``  — span of control, depth, team size
  3. ``hierarchy_long``   — transitive closure (one row per ancestor pair)
  4. ``betweenness``      — bridge coaches who connect sub-trees
  5. ``pagerank``         — influence-weighted prestige
  6. ``louvain_communities`` — clustering within the coaching graph

Outputs
-------
- ``outputs/reports/01_orgchart_overview.md`` — cross-team comparison
- ``outputs/csv/hierarchy_stats_all.csv``     — every team's manager stats
- ``outputs/csv/betweenness_all.csv``         — every team's bridge scores

Run
---
    python examples/01_orgchart_overview.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import pyduck_ona as pona

from _common import CSV, REPORTS, load_all


def analyse_team_season(
    con, team: str, season: int
) -> dict[str, pd.DataFrame]:
    """Run the full ONA workflow on one (team, season) org chart."""
    org = con.sql(f"SELECT * FROM org_{team}_{season}")
    direct = con.sql(
        f"SELECT employee_id, supervisor_id FROM org_{team}_{season} "
        "WHERE supervisor_id IS NOT NULL"
    )

    valid = pona.hierarchy_valid(org, "employee_id", "supervisor_id").df()
    stats = pona.hierarchy_stats(org, "employee_id", "supervisor_id").df()
    long_df = pona.hierarchy_long(org, "employee_id", "supervisor_id").df()
    bet = pona.betweenness(direct, "employee_id", "supervisor_id").df()
    pr = pona.pagerank(direct, "employee_id", "supervisor_id").df()

    # Tag with team/season for the consolidated outputs.
    stats["team"] = team
    stats["season"] = season
    bet["team"] = team
    bet["season"] = season
    pr["team"] = team
    pr["season"] = season

    return {
        "valid": valid,
        "stats": stats,
        "long": long_df,
        "betweenness": bet,
        "pagerank": pr,
    }


def main() -> None:
    con, ctx = load_all([2023, 2024, 2025, 2026])

    teams = ["ATL", "MIA", "NYM", "PHI", "WSN"]
    seasons = ctx["seasons"]

    all_stats: list[pd.DataFrame] = []
    all_betweenness: list[pd.DataFrame] = []
    all_pagerank: list[pd.DataFrame] = []
    issue_summary: list[dict] = []

    for season in seasons:
        for team in teams:
            print(f"[01] {team} {season}: ", end="")
            try:
                out = analyse_team_season(con, team, season)
            except Exception as e:
                print(f"ERROR {e}")
                continue

            n_issues = len(out["valid"])
            n_managers = (out["stats"]["direct_reports"] > 0).sum()
            top_mgr = out["stats"].sort_values(
                "direct_reports", ascending=False
            ).iloc[0]
            top_bridge = out["betweenness"].sort_values(
                "betweenness", ascending=False
            ).iloc[0]

            print(
                f"{len(out['long'])} ancestor pairs, "
                f"{n_managers} managers, "
                f"top span = {int(top_mgr['direct_reports'])} "
                f"(by {top_mgr['manager_id']}), "
                f"top bridge = {top_bridge['node_id']}"
            )

            issue_summary.append({
                "team": team,
                "season": season,
                "n_issues": n_issues,
                "n_managers": int(n_managers),
                "top_span_manager": top_mgr["manager_id"],
                "top_span_value": int(top_mgr["direct_reports"]),
                "top_bridge_node": top_bridge["node_id"],
                "top_bridge_value": float(top_bridge["betweenness"]),
            })

            all_stats.append(out["stats"])
            all_betweenness.append(out["betweenness"])
            all_pagerank.append(out["pagerank"])

    # ── Consolidated outputs ─────────────────────────────────────────────
    stats_all = pd.concat(all_stats, ignore_index=True)
    bet_all = pd.concat(all_betweenness, ignore_index=True)
    pr_all = pd.concat(all_pagerank, ignore_index=True)

    stats_all.to_csv(CSV / "hierarchy_stats_all.csv", index=False)
    bet_all.to_csv(CSV / "betweenness_all.csv", index=False)
    pr_all.to_csv(CSV / "pagerank_all.csv", index=False)
    print(f"[01] wrote {CSV / 'hierarchy_stats_all.csv'}")

    # ── Markdown report ─────────────────────────────────────────────────
    report_lines: list[str] = []
    R = report_lines.append
    R("# NL East Org-Chart Overview — pyduck-ona\n")
    R("Pyduck-ona diagnostics on the synthetic coaching hierarchy for "
      "every (team, season) in the showcase.\n")
    R("**Seasons:** 2023, 2024, 2025, 2026 (partial through 2026-06-27).  ")
    R("**Teams:** ATL, MIA, NYM, PHI, WSN.\n")
    R("## Per-team summary\n")
    R("| Team | Season | Issues | Managers | Top span (mgr) | Top bridge |")
    R("|------|--------|--------|----------|----------------|------------|")
    for row in sorted(issue_summary, key=lambda r: (r["team"], r["season"])):
        R(
            f"| {row['team']} | {row['season']} | {row['n_issues']} | "
            f"{row['n_managers']} | "
            f"{row['top_span_value']} ({row['top_span_manager']}) | "
            f"{row['top_bridge_value']:.4f} ({row['top_bridge_node']}) |"
        )

    R("\n## Observations\n")
    # Quick stats
    issues_total = sum(r["n_issues"] for r in issue_summary)
    R(f"- **Total hierarchy issues across all charts:** {issues_total} "
      "(expected 0 — the synthetic hierarchy is acyclic by construction).")
    biggest = max(issue_summary, key=lambda r: r["top_span_value"])
    R(f"- **Biggest span of control:** "
      f"{biggest['team']} {biggest['season']} — "
      f"{biggest['top_span_manager']} with {biggest['top_span_value']} "
      "direct reports.")
    bus = max(issue_summary, key=lambda r: r["top_bridge_value"])
    R(f"- **Highest betweenness centrality:** "
      f"{bus['team']} {bus['season']} — "
      f"{bus['top_bridge_node']} "
      f"(betweenness = {bus['top_bridge_value']:.4f}). "
      "These are the coaches who bridge multiple sub-trees; "
      "in ONA terms they are the **structural holes brokers**.")
    R("")
    R("## Outputs\n")
    R("- `outputs/csv/hierarchy_stats_all.csv` — span of control, depth, team size per manager per (team, season).")
    R("- `outputs/csv/betweenness_all.csv` — betweenness centrality per node per (team, season).")
    R("- `outputs/csv/pagerank_all.csv` — PageRank per node per (team, season).")

    report_path = REPORTS / "01_orgchart_overview.md"
    report_path.write_text("\n".join(report_lines))
    print(f"[01] wrote {report_path}")


if __name__ == "__main__":
    main()
