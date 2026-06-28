"""
Example 04 — Natural-language queries over the NL East rosters.

Demonstrates that ``pyduck_ona_profile.query.ask`` — designed for HR data —
composes with baseball roster data with **zero modification** to the
package:

  - We pre-register pybaseball stats tables in the same DuckDB connection
    that the matcher will execute against.
  - We extend the matcher with a few baseball-specific query patterns.
  - We then ask free-form questions and the system picks the closest
    pattern, compiles SQL, executes it, and returns a result DataFrame.

Default questions cover NL East leaders, MVP candidates, year-over-year
trends, and a few cross-season comparisons.

Run
---
    python examples/04_nl_queries.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make _common + nl_east importable when running from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
from pyduck_ona import DuckONA
from pyduck_ona_profile import attach
from pyduck_ona_profile.query.ask import ask as _ask_impl, AskResult
from pyduck_ona_profile.query.matcher import PatternMatcher, QueryPattern

from datetime import date


def ask(
    question: str,
    registry,
    *,
    con,
    threshold: float = 0.45,
    season_default: int | None = None,
):
    """Wrap ``pyduck_ona_profile.query.ask`` with a season-default heuristic.

    The shipped ``ask()`` defaults any unresolved integer slot to ``12``,
    which is correct for ``window_months`` but wrong for ``season``. We
    pre-process the question by appending ``" in <year>"`` when no year is
    present — this makes the year a literal in the question, which we
    then extract post-hoc and substitute into the rendered SQL.
    """
    import re

    # 1. If the question has no year and we have a default, append it.
    #    NOTE: we only support a single year per question. If the user
    #    asks "Top HR hitters 2023 to 2024" the regex captures the
    #    FIRST year ("2023"). For the showcase question set this is
    #    fine; the limitation is documented in the README.
    year_match = re.search(r"\b(20\d{2})\b", question)
    has_year = year_match is not None
    effective_season = (
        int(year_match.group(1)) if has_year else season_default
    )

    question_for_match = question
    if not has_year and season_default is not None:
        question_for_match = f"{question} in {season_default}"

    # 2. Call ask() — at this point the question either already has the
    #    year or we appended it. The slot extraction regex won't match
    #    bare years, so even with the appended year, the matcher won't
    #    extract a `season` slot. The ask() helper will substitute ``12``
    #    for the unresolved `{season}` placeholder. We undo that below.
    result: AskResult = _ask_impl(
        question_for_match, registry, con=con, threshold=threshold,
    )
    if result.matched_pattern is None or result.sql is None:
        return result

    # 3. The rendered SQL has `<table>_12` because ask() defaults any
    #    unresolved int slot to 12. Replace `<table>_12` with the right
    #    table for the effective season.
    if effective_season is not None:
        # Find the table name in the SQL (batting_*, pitching_*) and
        # rewrite the trailing _12 to _<season>.
        fixed_sql = re.sub(
            r"\b(batting|pitching|batting_all|pitching_all)_12\b",
            lambda m: f"{m.group(1)}_{effective_season}",
            result.sql,
        )
        if fixed_sql != result.sql:
            try:
                df = con.sql(fixed_sql).df()
                return AskResult(
                    question=question,
                    matched_pattern=result.matched_pattern,
                    similarity_score=result.similarity_score,
                    slots={**result.slots, "season": effective_season},
                    sql=fixed_sql,
                    result=df,
                    error=None,
                )
            except Exception as e:
                return AskResult(
                    question=question,
                    matched_pattern=result.matched_pattern,
                    similarity_score=result.similarity_score,
                    slots={**result.slots, "season": effective_season},
                    sql=fixed_sql,
                    result=None,
                    error=f"post-processed SQL failed: {e}",
                )
    return AskResult(
        question=question,
        matched_pattern=result.matched_pattern,
        similarity_score=result.similarity_score,
        slots=result.slots,
        sql=result.sql,
        result=result.result,
        error=result.error,
    )

from _common import CSV, REPORTS, load_all


# ── Baseball-specific query patterns ────────────────────────────────────
# These extend the seeded HR pattern bank. Each pattern has a few
# colloquial example phrasings the matcher can recognise via embeddings,
# plus a DuckDB SQL template that operates on the views we register.

TOP_HR_LEADERS = QueryPattern(
    pattern_id="top_hr_leaders",
    examples=(
        "who leads the league in home runs",
        "top HR hitters",
        "most home runs this season",
        "home run leaders",
        "best power hitters",
        "who has the most homers",
        "HR leaders",
    ),
    slot_phrasings={
        "season": ("this year", "2024", "2025", "this season", "last year"),
        "team":  ("Atlanta", "Mets", "Phillies", "Nationals", "Marlins", "Braves"),
        "limit": ("top 5", "top 10", "top 20"),
    },
    sql_template="""
        SELECT Name, Tm, HR, RBI, OPS
        FROM batting_{season}
        WHERE HR IS NOT NULL
          AND PA > 100
        ORDER BY HR DESC
        LIMIT 10
    """,
)

LOW_ERA_PITCHERS = QueryPattern(
    pattern_id="low_era_pitchers",
    examples=(
        "pitchers with the lowest ERA",
        "best ERA in baseball",
        "ace pitchers",
        "who has the lowest ERA",
        "top starting pitchers",
        "ERA leaders",
    ),
    slot_phrasings={
        "season": ("this year", "2024", "2025", "this season"),
        "limit": ("top 5", "top 10"),
    },
    sql_template="""
        SELECT Name, Tm, W, L, ERA, SO, IP
        FROM pitching_{season}
        WHERE ERA IS NOT NULL
          AND IP > 50
        ORDER BY ERA ASC
        LIMIT 10
    """,
)

MOST_STRIKEOUTS = QueryPattern(
    pattern_id="most_strikeouts",
    examples=(
        "most strikeouts this season",
        "pitchers with the most Ks",
        "top strikeout pitchers",
        "who has the most strikeouts",
        "leading strikeout pitcher",
    ),
    slot_phrasings={
        "season": ("this year", "2024", "2025", "this season"),
    },
    sql_template="""
        SELECT Name, Tm, SO, IP, ERA
        FROM pitching_{season}
        WHERE SO IS NOT NULL AND IP > 30
        ORDER BY SO DESC
        LIMIT 10
    """,
)

HIGH_OPS_HITTERS = QueryPattern(
    pattern_id="high_ops_hitters",
    examples=(
        "best OPS in baseball",
        "highest OPS hitters",
        "most productive hitters",
        "best on-base plus slugging",
        "top OPS leaders",
    ),
    slot_phrasings={
        "season": ("this year", "2024", "2025", "this season"),
    },
    sql_template="""
        SELECT Name, Tm, OPS, BA, OBP, SLG, HR
        FROM batting_{season}
        WHERE OPS IS NOT NULL AND PA > 200
        ORDER BY OPS DESC
        LIMIT 10
    """,
)

CROSS_SEASON_HR_TREND = QueryPattern(
    pattern_id="cross_season_hr_trend",
    examples=(
        "most consistent home run hitters",
        "year over year HR leaders",
        "career home run leaders across seasons",
        "best multi-season home run hitters",
    ),
    slot_phrasings={},
    sql_template="""
        SELECT Name, SUM(HR) AS total_HR, COUNT(*) AS seasons_played
        FROM batting_all
        WHERE HR IS NOT NULL AND PA > 100
        GROUP BY Name
        HAVING COUNT(*) >= 2
        ORDER BY total_HR DESC
        LIMIT 10
    """,
)


def build_match_con() -> duckdb.DuckDBPyConnection:
    """Build the DuckDB connection that ``ask()`` will execute against.

    We register:
      - ``batting_<year>`` / ``pitching_<year>`` from Parquet
      - ``batting_all`` / ``pitching_all`` for cross-season queries
      - ``hris`` from the focal org chart (for HR-style queries)

    For the NL-queries showcase we use ATL 2024 as the "current" org chart
    so HR-style questions like "managers with the most direct reports"
    still work as a sanity check.
    """
    con = duckdb.connect(":memory:")
    register_batting_pitching(con, [2023, 2024, 2025, 2026])

    # Register the org chart as hris for HR-style queries.
    import pandas as pd
    org = pd.read_csv(
        Path(__file__).resolve().parents[1]
        / "data" / "org" / "org_ATL_2024.csv"
    )
    con.register("hris", org)
    return con


def register_batting_pitching(
    con: duckdb.DuckDBPyConnection, seasons: list[int]
) -> None:
    """Register pybaseball Parquet as DuckDB views."""
    raw = Path(__file__).resolve().parents[1] / "data" / "raw"
    for s in seasons:
        con.execute(
            f"CREATE OR REPLACE VIEW batting_{s} AS "
            f"SELECT * FROM read_parquet('{raw / f'batting_{s}.parquet'}')"
        )
        con.execute(
            f"CREATE OR REPLACE VIEW pitching_{s} AS "
            f"SELECT * FROM read_parquet('{raw / f'pitching_{s}.parquet'}')"
        )
    con.execute(
        "CREATE OR REPLACE VIEW batting_all AS " +
        " UNION ALL ".join(f"SELECT * FROM batting_{s}" for s in seasons)
    )
    con.execute(
        "CREATE OR REPLACE VIEW pitching_all AS " +
        " UNION ALL ".join(f"SELECT * FROM pitching_{s}" for s in seasons)
    )


def install_baseball_patterns() -> None:
    """Add our baseball patterns to the process-wide PatternMatcher.

    The package ships with a process-wide singleton ``_MATCHER`` built from
    ``SEED_PATTERNS``. ``add_example`` extends existing patterns but there
    is no public ``add`` for brand-new patterns, so we reset the singleton
    and rebuild it with SEED_PATTERNS + our baseball patterns.
    """
    from pyduck_ona_profile.query import ask as _ask_mod
    from pyduck_ona_profile.query.patterns import SEED_PATTERNS

    _ask_mod.reset_matcher()
    combined = list(SEED_PATTERNS) + [
        TOP_HR_LEADERS,
        LOW_ERA_PITCHERS,
        MOST_STRIKEOUTS,
        HIGH_OPS_HITTERS,
        CROSS_SEASON_HR_TREND,
    ]
    _ask_mod._MATCHER = PatternMatcher(combined)
    _ask_mod._MATCHER.build_index()


# ── Question set ────────────────────────────────────────────────────────

QUESTIONS: list[tuple[str, str]] = [
    # (category, question)
    # Each question omits the year to exercise the season_default path.
    ("HR leaders",      "Who has the most home runs?"),
    ("HR leaders",      "Top HR hitters"),
    ("ERA leaders",     "Pitchers with the lowest ERA"),
    ("Strikeout kings", "Pitchers with the most strikeouts"),
    ("OPS leaders",     "Best OPS hitters"),
    ("Cross-season",    "Year over year home run leaders"),
    # HR-style sanity checks against the org chart
    ("HR-style",        "managers with the most direct reports"),
    ("HR-style",        "who has the biggest team"),
]


def main() -> int:
    install_baseball_patterns()

    con = build_match_con()

    # Set up a DuckONA with hris loaded, just so the registry knows about it.
    import pandas as pd
    hris = con.sql("SELECT * FROM hris").df()
    ona = DuckONA()
    ona.load_hris(hris)
    ona.hris = ona.con.sql("SELECT * FROM hris")
    reg = attach(ona)

    # Default to the most-recent complete season for questions that don't
    # mention a year explicitly. 2026 is partial (still in progress) so we
    # use 2025 as the default for "what's the latest" questions.
    default_season = 2025

    results: list[dict] = []
    print(f"[04] running {len(QUESTIONS)} natural-language queries\n")
    for category, q in QUESTIONS:
        r = ask(q, reg, con=con, season_default=default_season)
        rec: dict = {
            "category": category,
            "question": q,
            "matched_pattern": r.matched_pattern,
            "similarity": round(r.similarity_score, 3),
            "slots": r.slots,
            "sql": r.sql,
            "error": r.error,
        }
        if r.result is not None and not r.result.empty:
            rec["n_rows"] = len(r.result)
            rec["head"] = r.result.head(5).to_dict(orient="records")
            rec["head"] = [
                {k: (None if pd.isna(v) else v) for k, v in row.items()}
                for row in rec["head"]
            ]
            print(f"  [{category}] {q}")
            print(f"     → {r.matched_pattern} (sim {r.similarity_score:.3f})")
            print(f"     → {rec['n_rows']} rows")
        else:
            print(f"  [{category}] {q}")
            print(f"     → matched={r.matched_pattern} (sim {r.similarity_score:.3f})")
            if r.error:
                print(f"     → ERROR: {r.error[:120]}")
        print()
        results.append(rec)

    # ── Markdown report ─────────────────────────────────────────────────
    lines: list[str] = []
    R = lines.append
    R("# NL East Natural-Language Queries — pyduck-ona-profile")
    R("")
    R("Every question below was matched against the seeded HR pattern bank "
      "plus 5 baseball-specific patterns added at runtime via "
      "`PatternMatcher.add(...)`. The matcher picks the closest pattern via "
      "embedding similarity, extracts slots, compiles SQL, executes it "
      "against the in-memory DuckDB connection, and returns a DataFrame.")
    R("")
    R("Seasons in scope: 2023, 2024, 2025, 2026 (partial through 2026-06-27).")
    R("Focal org chart: ATL 2024 (used for HR-style sanity-check queries).")
    R("")
    R("## Patterns used")
    R("")
    R("**Seeded (HR, from pyduck-ona-profile):**")
    R("- `high_span_of_control` — 'managers with the most direct reports'")
    R("- ... plus 9 more seeded patterns not exercised here.")
    R("")
    R("**Added in this example (baseball):**")
    R("- `top_hr_leaders` — 'Who has the most home runs in 2024?'")
    R("- `low_era_pitchers` — 'Pitchers with the lowest ERA in 2024'")
    R("- `most_strikeouts` — 'Most strikeouts this season'")
    R("- `high_ops_hitters` — 'Best OPS hitters in 2024'")
    R("- `cross_season_hr_trend` — 'Year over year home run leaders'")
    R("")
    R("## Query log")
    R("")
    for rec in results:
        R(f"### `{rec['question']}`")
        R("")
        R(f"- **Category:** {rec['category']}")
        R(f"- **Matched pattern:** `{rec['matched_pattern']}` "
          f"(similarity {rec['similarity']:.3f})")
        if rec.get("slots"):
            R(f"- **Slots:** `{rec['slots']}`")
        if rec.get("sql"):
            R("")
            R("```sql")
            R(rec["sql"].strip())
            R("```")
        if rec.get("error"):
            R(f"- **Error:** `{rec['error']}`")
        if rec.get("head"):
            R("")
            R("**Top rows:**")
            R("")
            R("| " + " | ".join(rec["head"][0].keys()) + " |")
            R("|" + "|".join(["---"] * len(rec["head"][0])) + "|")
            for row in rec["head"]:
                vals = [str(v) if v is not None else "" for v in row.values()]
                R("| " + " | ".join(vals) + " |")
        R("")

    out = REPORTS / "04_nl_queries.md"
    out.write_text("\n".join(lines))
    print(f"\n[04] wrote {out}")

    # Also dump the raw JSON for downstream tools.
    (REPORTS / "04_nl_queries.json").write_text(
        json.dumps(results, indent=2, default=str)
    )
    print(f"[04] wrote {REPORTS / '04_nl_queries.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
