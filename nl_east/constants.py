"""
Constants for the pybaseball NL East showcase.

pybaseball's ``batting_stats_range`` / ``pitching_stats_range`` return a ``Tm``
column with full team names (not abbreviations). When a player is traded
mid-season, ``Tm`` becomes a comma-separated list of teams the player
appeared for (e.g. ``"Atlanta,Miami"``).

NL East (5 teams):
  - Atlanta Braves        — ATL
  - Miami Marlins         — MIA
  - New York Mets         — NYM
  - Philadelphia Phillies — PHI
  - Washington Nationals  — WSN
"""

from __future__ import annotations

# Canonical team metadata for the showcase.
TEAM_FULL: dict[str, str] = {
    "ATL": "Atlanta",
    "MIA": "Miami",
    "NYM": "New York",  # Mets — disambiguated by league filter
    "PHI": "Philadelphia",
    "WSN": "Washington",
}

# Reverse lookup: pybaseball full name (``"Atlanta"``) → abbreviation (``"ATL"``).
# The name TEAM_ABBREV_BY_FULL makes the direction unambiguous.
TEAM_ABBREV_BY_FULL: dict[str, str] = {v: k for k, v in TEAM_FULL.items()}
# Backwards-compat alias.
TEAM_ABBREV = TEAM_ABBREV_BY_FULL

# Pretty labels for plotting / reports.
TEAM_LABEL: dict[str, str] = {
    "ATL": "Atlanta Braves",
    "MIA": "Miami Marlins",
    "NYM": "New York Mets",
    "PHI": "Philadelphia Phillies",
    "WSN": "Washington Nationals",
}

NL_EAST_TEAMS: list[str] = list(TEAM_FULL.keys())

# Seasons we cover.
# 2023, 2024, 2025 are complete; 2026 is partial (through today's date).
SEASONS: list[int] = [2023, 2024, 2025, 2026]

# Season start/end dates (inclusive) used to bracket pybaseball queries.
# 2026 uses the current date — caller can pass an override.
SEASON_DATE_RANGES: dict[int, tuple[str, str]] = {
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-28", "2024-09-30"),
    2025: ("2025-03-27", "2025-09-28"),
    # 2026 is partial — end date is set by ``extract.py`` at runtime.
}


def team_full_name(abbrev: str) -> str:
    """Return the pybaseball full-name for an abbreviation, e.g. ``ATL → Atlanta``."""
    return TEAM_FULL[abbrev]


def is_nl_east_full_name(name: str) -> bool:
    """Return True if a pybaseball ``Tm`` value refers to an NL East team.

    ``name`` may be a comma-separated list (multi-stint). We return True if
    *any* stint is on an NL East team. (We do not try to disentangle interleaved
    stints here; callers that need per-stint rows do the split themselves.)

    NOTE: ``pybaseball`` returns *all* MLB hitters/pitchers in the date range,
    so ``"New York"`` is ambiguous between the **Mets** (NL East) and the
    **Yankees** (AL East). Callers that need accurate NL-only attribution must
    additionally filter on the ``Lev`` column (``"Maj-NL"``).
    Use :func:`is_nl_east_full_name_for_league` for that.
    """
    parts = {p.strip() for p in name.split(",")}
    return any(p in TEAM_ABBREV for p in parts)


def is_nl_east_full_name_for_league(
    name: str, league: str | None
) -> bool:
    """Strict NL East filter that also requires the league.

    The ``Lev`` column from ``batting_stats_range`` / ``pitching_stats_range``
    has values like ``"Maj-NL"`` or ``"Maj-AL"``. Pass it through to filter
    out the **Yankees** rows that would otherwise be misattributed to the
    **Mets** when ``Tm == "New York"``.

    Parameters
    ----------
    name
        The ``Tm`` value (full team name, possibly comma-separated).
    league
        The ``Lev`` value (``"Maj-NL"`` / ``"Maj-AL"`` / ``None``).

    Returns
    -------
    bool
        True iff at least one stint is on an NL East team AND the row's
        ``Lev`` is ``"Maj-NL"``. For multi-stint rows we are conservative
        and require an explicit ``Maj-NL`` league signal.
    """
    if league is None or league != "Maj-NL":
        # Without a confirmed league signal we cannot disambiguate
        # "New York" from a Mets-vs-Yankees perspective. Be safe and
        # drop the row; the rest of the showcase still has 4 teams of
        # data to work with.
        return False
    return is_nl_east_full_name(name)
