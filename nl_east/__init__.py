"""
pybaseball-nl-east — Showcase: pyduck-ona on National League East rosters.

This package wraps the data extraction, org-chart synthesis, and team/season
constants used across the example scripts.

Seasons covered: 2023, 2024, 2025, 2026 (partial, up to most current date).

NL East teams (5): Atlanta Braves, Miami Marlins, New York Mets,
Philadelphia Phillies, Washington Nationals.
"""

from .constants import NL_EAST_TEAMS, SEASONS, TEAM_FULL, TEAM_ABBREV

__all__ = ["NL_EAST_TEAMS", "SEASONS", "TEAM_FULL", "TEAM_ABBREV"]

__version__ = "0.1.0"
