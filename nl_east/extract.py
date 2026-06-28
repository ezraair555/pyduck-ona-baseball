"""
Fetch pybaseball stats for the NL East across seasons.

What this does
--------------
1. For each season (2023, 2024, 2025, 2026) and each stat type (batting,
   pitching), call ``pybaseball.batting_stats_range`` /
   ``pybaseball.pitching_stats_range`` with the bracketing dates.
2. Filter rows to NL East teams (full-name match, with comma-split
   support for multi-stint players).
3. Write one Parquet file per ``(season, stat_type)`` to ``data/raw/``.
4. Emit ``data/raw/_manifest.json`` summarising row counts.

Why Parquet
-----------
DuckDB reads Parquet natively and zero-copy. This makes every downstream
analysis (pyduck-ona, pyduck-ona-viz, pyduck-ona-profile) snappy and means
we only hit the pybaseball HTTP endpoint once per season.

CLI
---
    python -m nl_east.extract                 # fetch all seasons
    python -m nl_east.extract --refresh       # ignore cache
    python -m nl_east.extract --season 2024   # single season
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pybaseball

from .constants import (
    NL_EAST_TEAMS,
    SEASON_DATE_RANGES,
    SEASONS,
    TEAM_ABBREV,
    TEAM_LABEL,
    is_nl_east_full_name,
    is_nl_east_full_name_for_league,
)


# Default project-relative data directory. ``nl_east/extract.py`` lives two
# levels deep in the project (``pybaseball-nl-east/nl_east/extract.py``),
# so parents[1] is the project root itself.
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # ``pybaseball-nl-east/``


def _resolve_end_date(season: int, today: date | None = None) -> str:
    """Return the end date string for a season query.

    For complete seasons (2023-2025), use the SEASON_DATE_RANGES end. For
    the in-progress 2026 season, use today.
    """
    if season in SEASON_DATE_RANGES:
        return SEASON_DATE_RANGES[season][1]
    return (today or date.today()).isoformat()


def _filter_nl_east(df: pd.DataFrame, *, stat_type: str) -> pd.DataFrame:
    """Filter a pybaseball stats frame to NL East teams (strict).

    The ``Tm`` column can be:
      - a single team full name (``"Atlanta"``)
      - a comma-separated list when a player was traded (``"Atlanta,Miami"``)
      - (rarely) multi-team interleaved (``"Arizona,Atlanta,Los Angeles"``)

    ``pybaseball.batting_stats_range`` / ``pitching_stats_range`` return
    *every* MLB player in the date range, not just NL teams. The ``Tm``
    column is ambiguous for ``"New York"`` (Mets are NL East, Yankees are
    AL East). We disambiguate using the ``Lev`` column that pybaseball
    ships alongside ``Tm``: keep only rows where ``Lev == "Maj-NL"``.

    Parameters
    ----------
    df
        Output of ``pybaseball.batting_stats_range`` or
        ``pybaseball.pitching_stats_range``.
    stat_type
        ``"batting"`` or ``"pitching"`` — purely for logging.
    """
    if "Tm" not in df.columns:
        raise ValueError(
            f"Expected a `Tm` column in the {stat_type} data; "
            f"got columns: {df.columns.tolist()}"
        )
    # Two-step filter:
    #   1. Loose NL East match on the team name (handles multi-stint).
    #   2. Strict ``Lev == "Maj-NL"`` to drop Yankees rows from the Mets
    #      bucket and any interleaved stints.
    # If the ``Lev`` column is missing for some reason we fall back to
    # the loose match but log a warning so callers can investigate.
    if "Lev" in df.columns:
        mask = df.apply(
            lambda r: is_nl_east_full_name_for_league(
                str(r["Tm"]), str(r["Lev"])
            ),
            axis=1,
        )
    else:
        import warnings
        warnings.warn(
            f"pybaseball {stat_type} frame has no 'Lev' column; "
            "falling back to loose team-name match (Yankees may be "
            "misattributed to the Mets).",
            stacklevel=2,
        )
        mask = df["Tm"].apply(is_nl_east_full_name)
    out = df.loc[mask].copy()
    out["stat_type"] = stat_type
    return out


def fetch_season(
    season: int,
    *,
    today: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch + filter both batting and pitching for one season.

    Returns
    -------
    (batting_df, pitching_df)
        Both filtered to NL East rows.
    """
    if season not in SEASON_DATE_RANGES and season < min(SEASONS):
        raise ValueError(f"Season {season} is before the configured range.")

    start, _ = SEASON_DATE_RANGES.get(season, ("2026-03-25", "2026-06-27"))
    end = _resolve_end_date(season, today=today)

    print(f"[extract] season {season}: {start} → {end}")

    raw_batting = pybaseball.batting_stats_range(start, end)
    raw_pitching = pybaseball.pitching_stats_range(start, end)

    bat = _filter_nl_east(raw_batting, stat_type="batting")
    pit = _filter_nl_east(raw_pitching, stat_type="pitching")

    # Add a season column for downstream joins.
    bat["season"] = season
    pit["season"] = season

    print(
        f"[extract]   batting: {len(bat):>4} NL East rows "
        f"({bat['Tm'].nunique()} distinct team values)"
    )
    print(
        f"[extract]   pitching: {len(pit):>4} NL East rows "
        f"({pit['Tm'].nunique()} distinct team values)"
    )

    return bat, pit


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write a DataFrame as Parquet, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def run(
    *,
    seasons: list[int] | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    refresh: bool = False,
    today: date | None = None,
) -> dict[str, dict]:
    """Run the extraction across seasons. Returns the manifest."""
    seasons = seasons or SEASONS
    manifest: dict[str, dict] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today": (today or date.today()).isoformat(),
        "seasons": {},
    }

    for season in seasons:
        bat_path = data_dir / f"batting_{season}.parquet"
        pit_path = data_dir / f"pitching_{season}.parquet"
        cached = bat_path.exists() and pit_path.exists() and not refresh

        if cached:
            print(f"[extract] {season}: cache hit ({bat_path.name}, {pit_path.name})")
            bat = pd.read_parquet(bat_path)
            pit = pd.read_parquet(pit_path)
        else:
            bat, pit = fetch_season(season, today=today)
            write_parquet(bat, bat_path)
            write_parquet(pit, pit_path)

        manifest["seasons"][str(season)] = {
            "batting_rows": int(len(bat)),
            "pitching_rows": int(len(pit)),
            "batting_path": str(bat_path.relative_to(PROJECT_ROOT)),
            "pitching_path": str(pit_path.relative_to(PROJECT_ROOT)),
            "cached": cached,
            "end_date": _resolve_end_date(season, today=today),
        }

    manifest_path = data_dir / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[extract] manifest → {manifest_path}")

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract NL East stats via pybaseball")
    parser.add_argument(
        "--season", type=int, action="append", default=None,
        help="Limit extraction to one or more seasons (repeatable). Default: all configured.",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR,
        help=f"Output directory for raw Parquet files (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch even if cached Parquet exists.",
    )
    args = parser.parse_args(argv)

    seasons = args.season if args.season else SEASONS
    for s in seasons:
        if s not in SEASONS:
            print(f"[extract] WARN: season {s} not in configured {SEASONS}", file=sys.stderr)

    run(seasons=seasons, data_dir=args.data_dir, refresh=args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
