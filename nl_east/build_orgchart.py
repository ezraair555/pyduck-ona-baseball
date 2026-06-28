"""
Build org charts (coaching hierarchies) for every (team, season) and save.

Reads the raw Parquet from ``nl_east.extract`` and emits one CSV per
(season, team) into ``data/org/``.

CLI
---
    python -m nl_east.build_orgchart             # all seasons × all teams
    python -m nl_east.build_orgchart --season 2024
    python -m nl_east.build_orgchart --team ATL
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .constants import (
    NL_EAST_TEAMS,
    SEASONS,
    TEAM_ABBREV_BY_FULL,
    TEAM_LABEL,
)
from .coaching import build_orgchart, summarise_orgchart


# Same project-root resolution as extract.py.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_ORG_DIR = PROJECT_ROOT / "data" / "org"


def _load_team_season(
    season: int,
    team: str,
    raw_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the batting + pitching parquet for one (season, team) combo.

    pybaseball's ``Tm`` column carries full team names like ``"Atlanta"``;
    multi-stint rows have comma-separated lists. We:
      - include any row whose Tm *contains* the team's full name
      - when a player was traded (commas present) we keep only the stint
        rows for this team. We approximate that by duplicating the row
        and tagging it with this team, so downstream per-player views
        still resolve to a single employee_id. (The two-hop trade mechanic
        is modelled separately by ``examples/03_player_profile.py``.)
    """
    if team in TEAM_ABBREV_BY_FULL.values():
        # We were given an abbreviation like ``"ATL"`` — find the matching
        # full name.
        team_full = next(
            full for full, ab in TEAM_ABBREV_BY_FULL.items() if ab == team
        )
    elif team in TEAM_ABBREV_BY_FULL:
        # We were given the full name like ``"Atlanta"`` directly.
        team_full = team
    else:
        raise ValueError(
            f"Unknown team {team!r}; expected one of "
            f"{sorted(TEAM_ABBREV_BY_FULL.values())} or "
            f"{sorted(TEAM_ABBREV_BY_FULL.keys())}"
        )

    def _filter(df: pd.DataFrame) -> pd.DataFrame:
        # ``Tm`` may be a single team name (``"Atlanta"``) or a comma-
        # separated list of stints (``"Atlanta,Miami"``). We keep any row
        # where this team's full name appears as one of the stints.
        tm = df["Tm"].astype(str)
        mask = tm.apply(lambda s: team_full in [p.strip() for p in s.split(",")])
        return df.loc[mask].copy()

    bat = pd.read_parquet(raw_dir / f"batting_{season}.parquet")
    pit = pd.read_parquet(raw_dir / f"pitching_{season}.parquet")
    return _filter(bat), _filter(pit)


def run(
    *,
    seasons: list[int] | None = None,
    teams: list[str] | None = None,
    raw_dir: Path = DEFAULT_RAW_DIR,
    org_dir: Path = DEFAULT_ORG_DIR,
) -> dict:
    """Build all org charts and write CSV files. Returns a summary manifest."""
    seasons = seasons or SEASONS
    teams = teams or NL_EAST_TEAMS

    org_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"built": []}

    for season in seasons:
        for team in teams:
            try:
                bat, pit = _load_team_season(season, team, raw_dir)
            except FileNotFoundError as e:
                print(f"[build-org] {season} {team}: missing raw data ({e})",
                      file=sys.stderr)
                continue

            org = build_orgchart(team, season, bat, pit)
            stats = summarise_orgchart(org)
            print(f"[build-org] {season} {team}: {stats}")

            out_path = org_dir / f"org_{team}_{season}.csv"
            org.to_csv(out_path, index=False)

            manifest["built"].append({
                "season": season,
                "team": team,
                "path": str(out_path.relative_to(PROJECT_ROOT)),
                **stats,
            })

    manifest_path = org_dir / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[build-org] manifest → {manifest_path}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build coaching hierarchies")
    parser.add_argument("--season", type=int, action="append", default=None)
    parser.add_argument("--team", choices=NL_EAST_TEAMS, action="append", default=None)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--org-dir", type=Path, default=DEFAULT_ORG_DIR)
    args = parser.parse_args(argv)

    run(
        seasons=args.season,
        teams=args.team,
        raw_dir=args.raw_dir,
        org_dir=args.org_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
