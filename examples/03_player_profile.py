"""
Example 03 — Player-as-Subject with pyduck-ona-profile.

For a focal player we exercise the full ``pyduck-ona-profile`` machinery:

  1. Load the org chart as HRIS into ``DuckONA``.
  2. Load season-by-season batting/pitching as the "compensation" stream
     (proxy: salary isn't in pybaseball, so we use ``OPS`` as the metric).
  3. Build a ``Subject`` view for the player — every concept they're in.
  4. Build a ``Timeline`` and render manager_change events (trades),
     comp_change events (year-over-year OPS jumps), promotion events.
  5. Snapshot the player at a specific ``as_of`` date.

The whole showcase demonstrates that pyduck-ona-profile, designed for HR
data, composes with roster + stats data with zero modification.

Default focal player: Ronald Acuña Jr. (ATL, mlbID 660670).
Override with ``--player "Bryce Harper"`` or ``--mlbid 547180``.

Run
---
    python examples/03_player_profile.py
    python examples/03_player_profile.py --player "Bryce Harper"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from pyduck_ona import DuckONA
from pyduck_ona_profile import Subject, Timeline

# Make _common + nl_east importable when running from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _common import CSV, REPORTS, load_all
from nl_east.constants import TEAM_ABBREV_BY_FULL


def lookup_player(name: str, con) -> dict | None:
    """Find a player's mlbID + team by name across all seasons of batting.

    Returns the most-recent season's row for the player with the most
    career plate appearances. (If two players share a substring like
    "Ronald", we pick the one who actually plays — the loud one.)
    """
    df = con.sql(f"""
        WITH career AS (
            SELECT Name, mlbID, SUM(COALESCE(PA, 0)) AS career_pa
            FROM batting_all
            WHERE Name ILIKE '%{name}%'
            GROUP BY Name, mlbID
        ),
        top_player AS (
            SELECT mlbID FROM career ORDER BY career_pa DESC LIMIT 1
        )
        SELECT b.Name, b.mlbID, b.Tm, b.season
        FROM batting_all b
        WHERE b.mlbID = (SELECT mlbID FROM top_player)
        ORDER BY b.season DESC
        LIMIT 1
    """).df()
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def load_hris_for_team(con, team: str, season: int) -> pd.DataFrame:
    """Load the org chart as an HRIS frame for one (team, season)."""
    return con.sql(f"SELECT * FROM org_{team}_{season}").df()


def load_player_stats_as_compensation(con, mlb_id: int) -> pd.DataFrame:
    """Build a per-season "compensation" frame from batting stats.

    pybaseball doesn't include salary, but OPS is a continuous per-season
    performance metric — perfect for the comp_change event detector. We
    include PA so empty seasons are filtered.
    """
    return con.sql(f"""
        SELECT
            'MLB-{mlb_id}'                                    AS employee_id,
            DATE_TRUNC('year', MAKE_DATE(season, 7, 1))       AS snapshot_date,
            OPS                                               AS salary,
            PA                                                AS units,
            Name                                              AS note
        FROM batting_all
        WHERE mlbID = {mlb_id}
          AND PA IS NOT NULL
          AND PA > 0
        ORDER BY season
    """).df()


def load_attendance_proxy(con, mlb_id: int) -> pd.DataFrame:
    """Use games played (G) as an attendance proxy: high G = high attendance."""
    return con.sql(f"""
        SELECT
            'MLB-{mlb_id}'                                    AS employee_id,
            DATE_TRUNC('year', MAKE_DATE(season, 7, 1))       AS snapshot_date,
            G                                                 AS days_present,
            GS                                                AS days_scheduled,
            Name                                              AS note
        FROM pitching_all
        WHERE mlbID = {mlb_id}
          AND G IS NOT NULL
          AND G > 0
        ORDER BY season
    """).df()


def render_profile(player_id: str, ona, role: str = "hrbp") -> dict:
    """Return a dict-form of the Subject view, optionally redacted by role.

    ``Subject.with_role(role)`` returns a ``Profile`` dataclass directly
    (it's not a method on Profile — Profile is the result).
    """
    prof = Subject(player_id, ona).with_role(role)
    return {
        "identity":     prof.identity,
        "position":     prof.position,
        "compensation": prof.compensation,
        "attendance":   prof.attendance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Player-as-Subject showcase")
    parser.add_argument("--player", default="Ronald",
                        help="Substring of the player name (case-insensitive)")
    parser.add_argument("--mlbid", type=int, default=None,
                        help="Override name lookup with an explicit MLBAM id")
    args = parser.parse_args()

    con, _ = load_all([2023, 2024, 2025, 2026])

    # ── Resolve the player ───────────────────────────────────────────────
    if args.mlbid is not None:
        info = con.sql(f"""
            SELECT Name, mlbID, Tm, season
            FROM batting_all WHERE mlbID = {args.mlbid}
            ORDER BY season DESC LIMIT 1
        """).df().iloc[0].to_dict()
    else:
        info = lookup_player(args.player, con)
        if info is None:
            print(f"No player found matching {args.player!r}")
            return 1
    print(f"[03] resolved: {info}")

    player_id = f"MLB-{int(info['mlbID'])}"
    team_full = info["Tm"].split(",")[0]  # most-recent stint
    team = TEAM_ABBREV_BY_FULL[team_full]  # map full name → abbreviation

    # ── Build the DuckONA instance ───────────────────────────────────────
    # Pick the most-recent season for the org chart; the Subject view is
    # for a single point in time, but Timeline spans seasons via comp +
    # attendance streams.
    season = int(info["season"])
    hris = load_hris_for_team(con, team, season)
    comp = load_player_stats_as_compensation(con, int(info["mlbID"]))
    att = load_attendance_proxy(con, int(info["mlbID"]))

    print(f"[03] HRIS rows for {team} {season}: {len(hris)}")
    print(f"[03] comp rows: {len(comp)}, attendance rows: {len(att)}")

    ona = DuckONA()
    ona.load_hris(hris)
    ona.load_compensation(comp)
    ona.load_attendance(att)

    # Integration shim: ``DuckONA`` doesn't expose loaded tables as
    # public attributes (only ``self._table_names``); meanwhile
    # ``pyduck_ona_profile.Timeline._auto_detect`` looks them up via
    # ``getattr(ona, name)`` first and silently skips when that returns
    # None. We expose the relations as attributes so the auto-detector
    # finds them. (``Subject.profile()`` would also work via the
    # ``getattr(ona, "con").sql(...)`` fallback in ``_relation_to_df``,
    # but the direct attribute path is the one both ``Subject`` and
    # ``Timeline`` consistently pick up.)
    ona.hris = ona.con.sql("SELECT * FROM hris")
    ona.compensation = ona.con.sql("SELECT * FROM compensation")
    ona.attendance = ona.con.sql("SELECT * FROM attendance")

    # ── Subject view ─────────────────────────────────────────────────────
    print(f"\n[03] === Subject view ({player_id}) ===")
    for role in ("hrbp", "manager", "self"):
        try:
            view = render_profile(player_id, ona, role=role)
            print(f"\n  role={role}:")
            for concept, val in view.items():
                print(f"    {concept}: {val}")
        except Exception as e:
            print(f"  role={role}: ERROR {e}")

    # ── Timeline ─────────────────────────────────────────────────────────
    print(f"\n[03] === Timeline ===")
    try:
        tl = Timeline(Subject(player_id, ona))
        all_events = tl.all()
        print(f"  total events: {len(all_events)}")
        if not all_events.empty:
            print(all_events.to_string(index=False))
    except Exception as e:
        print(f"  timeline all: ERROR {e}")

    try:
        tl = Timeline(Subject(player_id, ona))
        mc = tl.manager_changes()
        print(f"\n  manager_change events: {len(mc)}")
        if not mc.empty:
            print(mc.to_string(index=False))
    except Exception as e:
        print(f"  manager_changes: ERROR {e}")

    try:
        tl = Timeline(Subject(player_id, ona))
        cc = tl.comp_history()
        print(f"\n  comp_change events: {len(cc)}")
        if not cc.empty:
            print(cc.to_string(index=False))
    except Exception as e:
        print(f"  comp_history: ERROR {e}")

    # ── Snapshot at a key date ──────────────────────────────────────────
    print(f"\n[03] === as_of snapshot at {season}-06-15 ===")
    try:
        tl = Timeline(Subject(player_id, ona))
        snap = tl.as_of(pd.Timestamp(f"{season}-06-15"))
        import json
        print(json.dumps(snap, indent=2, default=str))
    except Exception as e:
        print(f"  as_of: ERROR {e}")

    # ── Markdown report ─────────────────────────────────────────────────
    lines: list[str] = []
    R = lines.append
    R(f"# Player profile: {info['Name']}")
    R("")
    R(f"- **MLBAM ID:** {int(info['mlbID'])}")
    R(f"- **Most-recent team:** {info['Tm']}")
    R(f"- **Subject view as_of season:** {season}")
    R("")
    R("This profile was generated by ``pyduck-ona-profile`` against an "
      "org chart built from pybaseball stats. The Subject view, Timeline "
      "events, and as-of snapshots are the same APIs you'd use for an "
      "employee — just pointed at roster data.")
    R("")
    R("## Source data")
    R("")
    R(f"- HRIS: org chart for {team} {season} ({len(hris)} rows)")
    R(f"- Compensation proxy: per-season OPS (no salary in pybaseball; {len(comp)} rows)")
    R(f"- Attendance proxy: per-season games played ({len(att)} rows)")

    out = REPORTS / f"03_player_profile_{player_id}.md"
    out.write_text("\n".join(lines))
    print(f"\n[03] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
