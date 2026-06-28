"""
Example 02 — Visualisations for the NL East org charts.

For one focal team (default: ATL 2024) and a year-over-year look
(NYM 2023 → 2024 → 2025 → 2026) we render every relevant figure from
``pyduck_ona_viz``:

  - ``span_of_control``            — bar chart of top managers
  - ``span_vs_depth``              — quadrant bubble chart
  - ``hierarchy_depth_heatmap``    — manager × level matrix
  - ``centrality_dashboard``       — 2×2 betweenness/PageRank/eigenvector/degree
  - ``silo_map``                   — community-coloured network
  - ``org_chart_tree``             — interactive D3 tree (HTML)
  - ``summary_dashboard``          — single-page exec dashboard (HTML)

Run
---
    python examples/02_visualize_orgchart.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless backend — no display required
import matplotlib.pyplot as plt
import pyduck_ona as pona
import pyduck_ona_viz as viz

from _common import FIGURES, HTML, load_all


def focal_team_viz(
    con,
    team: str,
    season: int,
    *,
    label_prefix: str = "focal",
) -> None:
    """Render every viz for one (team, season)."""
    print(f"[02] rendering {team} {season} ({label_prefix})")
    org_rel = con.sql(f"SELECT * FROM org_{team}_{season}")
    direct = con.sql(
        f"SELECT employee_id, supervisor_id FROM org_{team}_{season} "
        "WHERE supervisor_id IS NOT NULL"
    )

    long_df = pona.hierarchy_long(org_rel, "employee_id", "supervisor_id").df()
    stats_df = pona.hierarchy_stats(org_rel, "employee_id", "supervisor_id").df()
    bet = pona.betweenness(direct, "employee_id", "supervisor_id").df()
    pr = pona.pagerank(direct, "employee_id", "supervisor_id").df()
    eig = pona.eigenvector_centrality(direct, "employee_id", "supervisor_id").df()
    deg = pona.degree_centrality(direct, "employee_id", "supervisor_id").df()

    metadata = org_rel.df()[[
        "employee_id", "name", "title", "department", "job_level", "team", "season"
    ]]

    # ``hierarchy_long`` produces transitive closure (one row per ancestor
    # pair) which has duplicate employee_ids. For ONA graphs we need
    # *direct edges* — that's the unfiltered ``org_rel`` view minus NULLs.
    direct_edges_df = direct.df()

    # 1. Span of control
    fig = viz.span_of_control(
        stats_df, top_n=10, id_col="manager_id",
        title=f"{team} {season} — Span of control",
    )
    fig.savefig(FIGURES / f"{label_prefix}_span_of_control_{team}_{season}.png",
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 2. Span vs depth
    fig = viz.span_vs_depth(
        stats_df, id_col="manager_id",
        title=f"{team} {season} — Span × depth (quadrant view)",
        metadata=metadata,
    )
    fig.savefig(FIGURES / f"{label_prefix}_span_vs_depth_{team}_{season}.png",
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3. Centrality dashboard
    fig = viz.centrality_dashboard(
        betweenness=bet, pagerank=pr, eigenvector=eig, degree=deg,
        betweenness_col="betweenness",
        pagerank_col="pagerank",
        eigenvector_col="eigenvector",
        degree_col="degree_centrality",
        metadata=metadata, top_n=8,
        title=f"{team} {season} — Centrality dashboard",
    )
    fig.savefig(
        FIGURES / f"{label_prefix}_centrality_{team}_{season}.png",
        dpi=150, bbox_inches="tight",
    )
    plt.close(fig)

    # 4. Hierarchy depth heatmap
    wide = pona.hierarchy_wide(
        org_rel, "employee_id", "supervisor_id", max_depth=4,
    ).df()
    fig = viz.hierarchy_depth_heatmap(
        wide, title=f"{team} {season} — Reporting depth",
        metadata=metadata,
    )
    fig.savefig(
        FIGURES / f"{label_prefix}_depth_heatmap_{team}_{season}.png",
        dpi=150, bbox_inches="tight",
    )
    plt.close(fig)

    # 5. Silo map (community detection)
    try:
        fig = viz.silo_map(
            direct_edges_df,
            metadata=metadata,
            title=f"{team} {season} — Community / silo map",
        )
        fig.savefig(
            FIGURES / f"{label_prefix}_silo_map_{team}_{season}.png",
            dpi=150, bbox_inches="tight",
        )
        plt.close(fig)
    except Exception as e:
        print(f"[02]   silo_map: skipped ({e})")

    # 6. Interactive org chart (HTML)
    html = viz.org_chart_tree(
        direct_edges_df,
        metadata=metadata,
        color_by="department",
        title=f"{team} {season} — Coaching hierarchy",
    )
    (HTML / f"{label_prefix}_org_chart_{team}_{season}.html").write_text(html)

    # 7. Executive summary dashboard (HTML)
    html = viz.summary_dashboard(
        stats_df,
        betweenness=bet,
        pagerank=pr,
        title=f"{team} {season} — Org summary",
    )
    (HTML / f"{label_prefix}_summary_{team}_{season}.html").write_text(html)


def year_over_year(team: str = "NYM") -> None:
    """Render a side-by-side comparison for one team across seasons."""
    print(f"[02] year-over-year render for {team}")
    con, _ = load_all([2023, 2024, 2025, 2026])
    for season in [2023, 2024, 2025, 2026]:
        try:
            focal_team_viz(con, team, season, label_prefix=f"yoy_{team}")
        except Exception as e:
            print(f"[02]   {team} {season}: ERROR {e}")


def main() -> None:
    con, _ = load_all([2023, 2024, 2025, 2026])

    # Pick ATL 2024 as the canonical focal team.
    focal_team_viz(con, "ATL", 2024, label_prefix="focal")

    # Year-over-year for NYM (most active roster, biggest orgs).
    year_over_year("NYM")

    # And PHI (smaller roster, clean comparison).
    year_over_year("PHI")

    print("[02] done — see outputs/figures/ and outputs/html/")


if __name__ == "__main__":
    main()
