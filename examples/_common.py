"""
Shared setup for the pybaseball-nl-east example scripts.

Every example needs:

1. A DuckDB connection with the org charts registered as views.
2. Pybaseball batting/pitching parquet registered as views, keyed by
   (season, stat_type).
3. Convenience loaders for pyduck-ona.

This module centralises that bootstrap so the example scripts stay
focused on the analysis.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

# Project root is two levels up from examples/ (``pybaseball-nl-east/``).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_ORG = PROJECT_ROOT / "data" / "org"
OUTPUTS = PROJECT_ROOT / "outputs"
FIGURES = OUTPUTS / "figures"
HTML = OUTPUTS / "html"
CSV = OUTPUTS / "csv"
REPORTS = OUTPUTS / "reports"

for _d in (FIGURES, HTML, CSV, REPORTS):
    _d.mkdir(parents=True, exist_ok=True)


def connect() -> duckdb.DuckDBPyConnection:
    """Open a fresh in-memory DuckDB connection."""
    return duckdb.connect(":memory:")


def register_views(con: duckdb.DuckDBPyConnection, seasons: list[int]) -> None:
    """Register pybaseball Parquet as ``batting_<year>`` / ``pitching_<year>``
    and every (team, season) org chart as ``org_<team>_<year>``.

    Also unions everything into ``batting_all`` / ``pitching_all`` /
    ``org_all`` for cross-season queries.
    """
    batting_paths = [str(DATA_RAW / f"batting_{s}.parquet") for s in seasons]
    pitching_paths = [str(DATA_RAW / f"pitching_{s}.parquet") for s in seasons]

    # Per-season parquet views.
    for season, bp, pp in zip(seasons, batting_paths, pitching_paths):
        con.execute(
            f"CREATE OR REPLACE VIEW batting_{season} AS "
            f"SELECT * FROM read_parquet('{bp}')"
        )
        con.execute(
            f"CREATE OR REPLACE VIEW pitching_{season} AS "
            f"SELECT * FROM read_parquet('{pp}')"
        )

    # Combined views.
    con.execute(
        "CREATE OR REPLACE VIEW batting_all AS " +
        " UNION ALL ".join(f"SELECT * FROM batting_{s}" for s in seasons)
    )
    con.execute(
        "CREATE OR REPLACE VIEW pitching_all AS " +
        " UNION ALL ".join(f"SELECT * FROM pitching_{s}" for s in seasons)
    )

    # Org charts — one per (team, season).
    org_paths = sorted(DATA_ORG.glob("org_*_*.csv"))
    for op in org_paths:
        # Filename is ``org_<TEAM>_<YEAR>.csv``
        stem = op.stem  # e.g. "org_ATL_2024"
        _, team, year = stem.split("_")
        view = f"org_{team}_{year}"
        con.execute(
            f"CREATE OR REPLACE VIEW {view} AS "
            f"SELECT * FROM read_csv_auto('{op}')"
        )

    con.execute(
        "CREATE OR REPLACE VIEW org_all AS " +
        " UNION ALL ".join(
            f"SELECT * FROM read_csv_auto('{p}')" for p in org_paths
        )
    )


def load_all(
    seasons: list[int] | None = None,
) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """Open a connection and register views for the given seasons.

    Returns
    -------
    (con, ctx)
        ``ctx`` is a small dict with paths so example scripts can reference
        output locations without recomputing them.
    """
    if seasons is None:
        seasons = [2023, 2024, 2025, 2026]

    con = connect()
    register_views(con, seasons)
    ctx = {
        "seasons": seasons,
        "project_root": PROJECT_ROOT,
        "outputs": OUTPUTS,
        "figures": FIGURES,
        "html": HTML,
        "csv": CSV,
        "reports": REPORTS,
    }
    return con, ctx
