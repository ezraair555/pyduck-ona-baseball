"""
Synthetic coaching hierarchies for the NL East teams.

pybaseball exposes rosters and stats but not the coaching tree. For a
``pyduck-ona`` showcase we need a reporting hierarchy to anchor the ONA
analysis (span-of-control, betweenness, hierarchy integrity, etc.).

This module generates a **plausible 4-level hierarchy** per team:

    L1 Manager
      └─ L2 Bench / Pitching / Hitting coaches
           └─ L3 Position coaches (1B, 3B, Bullpen, Infield, Outfield)
                └─ L4 Players (from the batting/pitching data)

Players are assigned to a position coach based on their role:
    - Pitchers → Pitching Coach → Bullpen Coach (relievers) or
      Position Coach (starters)
    - Position players → Hitting Coach → position-specific L3 coach

The hierarchy is deterministic given a season's roster, so the same
season + team always produces the same org chart (useful for diffing
across seasons in the ONA dashboards).

Each node gets:
    - ``employee_id``: ``"{TEAM}-{role}-{slug}"`` for coaches, or
      the pybaseball ``mlbID`` for players (so we can join back to stats).
    - ``supervisor_id``: parent node's id.
    - ``department``: ``"Coaching Staff"`` for L1-L3, ``"Player"`` for L4.
    - ``job_level``: 1-4 (1 = Manager, 4 = Player).
    - ``title``: human-readable role.
    - ``name``: coach name or player name.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pandas as pd

from .constants import TEAM_LABEL


# ──────────────────────────────────────────────────────────────────────
# Fixed coaching names per team. These are the real MLB managers / coaches
# for each NL East team in recent years; they let the org chart be named
# (more useful in the viz) without scraping coaching rosters.
# We keep this small enough to maintain by hand; the pyduck-ona machinery
# doesn't care about the names, only the structure.
# ──────────────────────────────────────────────────────────────────────

# Each team gets: Manager, Bench Coach, Pitching Coach, Hitting Coach.
COACHING_STAFF: dict[str, dict[str, str]] = {
    "ATL": {
        "manager":     "Brian Snitker",
        "bench":       "Walt Weiss",
        "pitching":    "Rick Kranitz",
        "hitting":     "Kevin Seitzer",
    },
    "MIA": {
        "manager":     "Skip Schumaker",
        "bench":       "Luis Ugueto",
        "pitching":    "Mel Stottlemyre Jr.",
        "hitting":     "Marcus Thames",
    },
    "NYM": {
        "manager":     "Carlos Mendoza",
        "bench":       "John Gibbons",
        "pitching":    "Jeremy Hefner",
        "hitting":     "Eric Chavez",
    },
    "PHI": {
        "manager":     "Rob Thomson",
        "bench":       "Mike Calitri",
        "pitching":    "Caleb Cotham",
        "hitting":     "Kevin Long",
    },
    "WSN": {
        "manager":     "Dave Martinez",
        "bench":       "Miguel Cairo",
        "pitching":    "Jim Hickey",
        "hitting":     "Rick Schu",
    },
}


@dataclass
class OrgNode:
    """One node in the coaching hierarchy."""

    employee_id: str
    supervisor_id: str | None
    name: str
    title: str
    department: str
    job_level: int
    team: str
    season: int
    # Optional metadata for player nodes.
    mlb_id: int | None = None
    role: str | None = None  # e.g. "SP", "RP", "C", "1B"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        # Add ``snapshot_date`` so pyduck-ona-profile event detectors
        # (``detect_manager_changes``, ``detect_promotions``) can find
        # the column they expect. For a single-snapshot org chart this
        # means zero events are detected — which is the correct answer
        # for a within-season view. For multi-season views we'd attach
        # the snapshot to the date the org was valid (mid-season).
        d = {
            "employee_id": self.employee_id,
            "supervisor_id": self.supervisor_id,
            "name": self.name,
            "title": self.title,
            "department": self.department,
            "job_level": self.job_level,
            "team": self.team,
            "season": self.season,
            "snapshot_date": f"{self.season}-07-01",
        }
        if self.mlb_id is not None:
            d["mlb_id"] = self.mlb_id
        if self.role is not None:
            d["role"] = self.role
        d.update(self.extra)
        return d


def _slug(name: str) -> str:
    """Make a stable id-suffix from a coach name."""
    return name.lower().replace(" ", "-").replace(".", "")


def _role_from_position(df_row: pd.Series, stat_type: str) -> str:
    """Classify a player into a coarse role used to pick their position coach.

    Pitching data has no position column. We treat all pitchers as ``"P"``
    (further split into starters vs relievers via ``GS`` elsewhere).

    Batting data has no position column either; pybaseball's ``Tm``-only
    batting stats don't tell us infield vs outfield. For the showcase we
    bucket hitters as ``"H"`` (generic hitter) — fine for routing them to
    the Hitting Coach and then the Infield/Outfield L3 coaches via a
    deterministic hash split.
    """
    if stat_type == "pitching":
        return "P"
    return "H"


def _stable_split(mlb_id: int | str, parts: int) -> int:
    """Deterministically bucket an mlb_id into ``parts`` groups (0..parts-1)."""
    if mlb_id is None:
        return 0
    h = hashlib.md5(str(mlb_id).encode("utf-8")).hexdigest()
    return int(h[:8], 16) % parts


def build_orgchart(
    team: str,
    season: int,
    batting_df: pd.DataFrame,
    pitching_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build a 4-level org chart for one team in one season.

    Parameters
    ----------
    team
        One of ``"ATL"``, ``"MIA"``, ``"NYM"``, ``"PHI"``, ``"WSN"``.
    season
        The year (used as a label).
    batting_df
        pybaseball batting frame (already filtered to this team / season).
    pitching_df
        pybaseball pitching frame (already filtered to this team / season).

    Returns
    -------
    pd.DataFrame
        One row per node (coaches + players), with the columns expected by
        ``pyduck_ona.hierarchy_*``:
            ``employee_id``, ``supervisor_id``, ``name``, ``title``,
            ``department``, ``job_level``, ``team``, ``season``.
    """
    if team not in COACHING_STAFF:
        raise ValueError(f"No coaching staff configured for team {team!r}")

    staff = COACHING_STAFF[team]
    nodes: list[OrgNode] = []

    team_prefix = team

    # ── L1: Manager ──────────────────────────────────────────────────────
    mgr_id = f"{team_prefix}-MGR-{_slug(staff['manager'])}"
    nodes.append(
        OrgNode(
            employee_id=mgr_id,
            supervisor_id=None,
            name=staff["manager"],
            title="Manager",
            department="Coaching Staff",
            job_level=1,
            team=team,
            season=season,
        )
    )

    # ── L2: Bench / Pitching / Hitting coaches (report to Manager) ───────
    l2_coaches = [
        ("bench",    staff["bench"],    "Bench Coach"),
        ("pitching", staff["pitching"], "Pitching Coach"),
        ("hitting",  staff["hitting"],  "Hitting Coach"),
    ]
    l2_ids: dict[str, str] = {}
    for slug_key, name, title in l2_coaches:
        node_id = f"{team_prefix}-L2-{slug_key.upper()}-{_slug(name)}"
        l2_ids[slug_key] = node_id
        nodes.append(
            OrgNode(
                employee_id=node_id,
                supervisor_id=mgr_id,
                name=name,
                title=title,
                department="Coaching Staff",
                job_level=2,
                team=team,
                season=season,
            )
        )

    # ── L3: Position coaches (report to one of L2) ───────────────────────
    # Pitching → Bullpen Coach + Starting Pitcher Coach
    # Hitting  → Infield Coach + Outfield Coach
    # Bench    → Base Coach 1B + Base Coach 3B (sub-categorise under bench)
    l3_specs = [
        # (parent_l2_slug, suffix, title)
        ("pitching", "BULLPEN",  "Bullpen Coach"),
        ("pitching", "STARTERS", "Starting Pitchers Coach"),
        ("hitting",  "INFIELD",  "Infield Coach"),
        ("hitting",  "OUTFIELD", "Outfield Coach"),
        ("bench",    "1B",       "First Base Coach"),
        ("bench",    "3B",       "Third Base Coach"),
    ]
    l3_ids: dict[str, str] = {}
    for parent_slug, suffix, title in l3_specs:
        node_id = f"{team_prefix}-L3-{suffix}"
        l3_ids[suffix] = node_id
        nodes.append(
            OrgNode(
                employee_id=node_id,
                supervisor_id=l2_ids[parent_slug],
                name=title,  # role name doubles as label for sub-coaches
                title=title,
                department="Coaching Staff",
                job_level=3,
                team=team,
                season=season,
            )
        )

    # ── L4: Players ──────────────────────────────────────────────────────
    # Each player reports to the position coach that matches their role.
    # Pitchers → STARTERS or BULLPEN based on GS volume
    # Hitters  → INFIELD or OUTFIELD via deterministic hash split
    def _classify_hitter(mlb_id: int | None) -> str:
        bucket = _stable_split(mlb_id, 2)
        return "INFIELD" if bucket == 0 else "OUTFIELD"

    def _classify_pitcher(gs: int | None, g: int | None) -> str:
        # A pitcher is a starter if they have a non-trivial number of GS;
        # otherwise they're a reliever.
        if (gs or 0) >= max(2, (g or 0) // 3):
            return "STARTERS"
        return "BULLPEN"

    # Pitching players
    for _, row in pitching_df.iterrows():
        mlb_id = row.get("mlbID")
        if pd.isna(mlb_id):
            continue
        suffix = _classify_pitcher(row.get("GS"), row.get("G"))
        player_id = f"MLB-{int(mlb_id)}"
        nodes.append(
            OrgNode(
                employee_id=player_id,
                supervisor_id=l3_ids[suffix],
                name=str(row.get("Name", player_id)),
                title="Pitcher",
                department="Player",
                job_level=4,
                team=team,
                season=season,
                mlb_id=int(mlb_id),
                role="P",
                extra={"games": int(row.get("G") or 0),
                       "gs": int(row.get("GS") or 0)},
            )
        )

    # Batting players
    for _, row in batting_df.iterrows():
        mlb_id = row.get("mlbID")
        if pd.isna(mlb_id):
            continue
        suffix = _classify_hitter(mlb_id)
        player_id = f"MLB-{int(mlb_id)}"
        # Two-way players (e.g. position players who pitch in blowouts)
        # appear in BOTH the pitching and batting pybaseball frames. We
        # iterate pitching first, so the pitcher entry wins as the
        # primary supervisor. The hitter-side relationship is not
        # modelled separately — a richer ONA could add a secondary edge,
        # but the showcase keeps a single reporting line per employee_id.
        if any(n.employee_id == player_id for n in nodes):
            continue
        nodes.append(
            OrgNode(
                employee_id=player_id,
                supervisor_id=l3_ids[suffix],
                name=str(row.get("Name", player_id)),
                title="Position Player",
                department="Player",
                job_level=4,
                team=team,
                season=season,
                mlb_id=int(mlb_id),
                role="H",
                extra={"pa": int(row.get("PA") or 0)},
            )
        )

    return pd.DataFrame([n.to_dict() for n in nodes])


def summarise_orgchart(org_df: pd.DataFrame) -> dict:
    """Quick counts useful for sanity-checking the built org chart."""
    return {
        "n_nodes": len(org_df),
        "n_coaches": int((org_df["department"] == "Coaching Staff").sum()),
        "n_players": int((org_df["department"] == "Player").sum()),
        "n_levels": int(org_df["job_level"].nunique()),
        "n_roots": int(org_df["supervisor_id"].isna().sum()),
    }
