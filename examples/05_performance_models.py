"""
Example 05 — Performance regression models.

Run ``pyduck_ona`` statistical models against the NL East batting data:

  1. **OLS** — what drives OPS in 2024?
        ``OPS ~ Age + log_PA + HR + RBI``
  2. **ANOVA** — does OPS differ by team within the NL East in 2024?
        ``OPS ~ Tm``
  3. **Logistic** — which players cross the all-star OPS threshold (>= 0.800)?
        ``is_all_star ~ Age + HR + RBI``

The "all-star OPS" cutoff is a synthetic binary outcome used to exercise
the logistic regression API; in real baseball analysis you'd plug in WAR,
wRC+, or some other composite.

Outputs
-------
- ``outputs/csv/ols_coefficients_<year>.csv``
- ``outputs/csv/ols_glance_<year>.csv``
- ``outputs/csv/anova_<year>.csv``
- ``outputs/csv/logistic_<year>.csv``
- ``outputs/reports/05_performance_models.md``

Run
---
    python examples/05_performance_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make _common + nl_east importable when running from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pyduck_ona as pona

from _common import CSV, REPORTS, load_all
from nl_east.constants import NL_EAST_TEAMS


ALL_STAR_OPS_THRESHOLD = 0.800  # industry heuristic


def prep_batting(df: pd.DataFrame) -> pd.DataFrame:
    """Cast numeric columns, drop nulls in the model variables."""
    for c in ("Age", "PA", "HR", "RBI", "BA", "OBP", "SLG", "OPS"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Age", "PA", "HR", "RBI", "OPS"]).copy()
    df["log_PA"] = np.log(df["PA"].clip(lower=1))
    df["is_all_star"] = (df["OPS"] >= ALL_STAR_OPS_THRESHOLD).astype(int)
    return df


def run_ols(df: pd.DataFrame, season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """OLS: OPS ~ Age + log_PA + HR + RBI."""
    tidy, glance = pona.ols(df, "OPS ~ Age + log_PA + HR + RBI")
    tidy["season"] = season
    glance["season"] = season
    return tidy, glance


def run_anova(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """ANOVA: does mean OPS differ across NL East teams?"""
    # Restrict to NL East teams for a clean comparison.
    nle = df[df["Tm"].isin({"Atlanta", "Miami", "New York", "Philadelphia", "Washington"})].copy()
    if nle["Tm"].nunique() < 2:
        return pd.DataFrame()
    out = pona.anova(nle, "OPS ~ Tm")
    out["season"] = season
    return out


def run_logistic(df: pd.DataFrame, season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Logistic: is_all_star ~ Age + HR + RBI (PA as offset via log_PA)."""
    if df["is_all_star"].sum() < 5 or df["is_all_star"].sum() > len(df) - 5:
        # Too few or too many positives — skip.
        return pd.DataFrame(), pd.DataFrame()
    tidy, glance = pona.logistic(df, "is_all_star ~ Age + HR + RBI + log_PA")
    tidy["season"] = season
    glance["season"] = season
    return tidy, glance


def main() -> int:
    con, _ = load_all([2023, 2024, 2025, 2026])

    ols_tidies, ols_glances = [], []
    anovas, log_tidies, log_glances = [], [], []
    # Track positives per season so the Markdown report can show
    # the actual count (the upstream logistic glance frame
    # doesn't expose it).
    log_positives_per_season: dict[int, int] = {}

    for season in [2023, 2024, 2025, 2026]:
        raw = con.sql(f"""
            SELECT Name, Tm, Age, PA, HR, RBI, BA, OBP, SLG, OPS
            FROM batting_{season}
            WHERE PA > 100
        """).df()
        df = prep_batting(raw)
        if df.empty:
            print(f"[05] {season}: no rows after prep, skipping")
            continue
        print(f"[05] {season}: {len(df)} rows, "
              f"{int(df['is_all_star'].sum())} all-star-level hitters")

        # OLS
        try:
            t, g = run_ols(df, season)
            ols_tidies.append(t); ols_glances.append(g)
            # ``pona.ols`` returns a glance frame with one row; the
            # column is named ``rsquared`` (not ``r_squared``).
            rsq = float(g["rsquared"].iloc[0])
            n = int(g["nobs"].iloc[0])
            print(f"  OLS R² = {rsq:.3f}, n = {n}")
        except Exception as e:
            print(f"  OLS error: {e}")

        # ANOVA
        try:
            an = run_anova(df, season)
            if not an.empty:
                anovas.append(an)
                print(f"  ANOVA F = {float(an['statistic'].iloc[0]):.3f}, "
                      f"p = {float(an['p.value'].iloc[0]):.4f}")
        except Exception as e:
            print(f"  ANOVA error: {e}")

        # Logistic
        try:
            n_pos = int(df["is_all_star"].sum())
            t, g = run_logistic(df, season)
            if not t.empty:
                log_tidies.append(t); log_glances.append(g)
                log_positives_per_season[season] = n_pos
                print(f"  Logistic n = {int(g['nobs'].iloc[0])}, "
                      f"positives = {n_pos}")
        except Exception as e:
            print(f"  Logistic error: {e}")

    # ── Persist outputs ──────────────────────────────────────────────────
    if ols_tidies:
        all_t = pd.concat(ols_tidies, ignore_index=True)
        all_t.to_csv(CSV / "ols_coefficients_all.csv", index=False)
    if ols_glances:
        all_g = pd.concat(ols_glances, ignore_index=True)
        all_g.to_csv(CSV / "ols_glance_all.csv", index=False)
    if anovas:
        pd.concat(anovas, ignore_index=True).to_csv(
            CSV / "anova_nl_east.csv", index=False
        )
    if log_tidies:
        pd.concat(log_tidies, ignore_index=True).to_csv(
            CSV / "logistic_coefficients_all.csv", index=False
        )
        pd.concat(log_glances, ignore_index=True).to_csv(
            CSV / "logistic_glance_all.csv", index=False
        )

    # ── Markdown report ──────────────────────────────────────────────────
    lines: list[str] = []
    R = lines.append
    R("# NL East Performance Models — pyduck-ona")
    R("")
    R("Three statistical models run against the NL East batting data, "
      "one per season (2023, 2024, 2025, 2026 partial).")
    R("")
    R("## 1. OLS — what drives OPS?")
    R("")
    R("**Formula:** `OPS ~ Age + log_PA + HR + RBI`")
    R("")
    R("Filtered to batters with `PA > 100` to avoid small-sample noise.")
    R("")
    R("| Season | R² | Adj-R² | n |")
    R("|--------|----|--------|---|")
    for g in ols_glances:
        # pona.ols glance columns are rsquared / rsquared_adj / nobs
        # (one-row frame; pull scalars).
        rsq = float(g["rsquared"].iloc[0])
        adj = float(g["rsquared_adj"].iloc[0])
        n = int(g["nobs"].iloc[0])
        season = int(g["season"].iloc[0])
        R(f"| {season} | {rsq:.3f} | {adj:.3f} | {n} |")
    R("")
    if ols_tidies:
        R("**Coefficients (most-recent season with results):**")
        latest_season = max(set(int(t['season'].iloc[0]) for t in ols_tidies))
        latest = next(t for t in ols_tidies if int(t['season'].iloc[0]) == latest_season)
        R("")
        R("| term | estimate | std error | t | p | conf.low | conf.high |")
        R("|------|----------|-----------|---|---|----------|-----------|")
        for _, row in latest.iterrows():
            R(
                f"| {row['term']} | {float(row['estimate']):.4f} | "
                f"{float(row['std.error']):.4f} | "
                f"{float(row['t_stat']):.3f} | "
                f"{float(row['p.value']):.4f} | "
                f"{float(row['conf.low']):.4f} | "
                f"{float(row['conf.high']):.4f} |"
            )
    R("")
    R("## 2. ANOVA — does OPS differ by NL East team?")
    R("")
    R("**Formula:** `OPS ~ Tm` (filtered to NL East teams)")
    R("")
    R("| Season | F | df | p |")
    R("|--------|---|----|----|")
    for an in anovas:
        # ANOVA table: term, sum_sq, df, statistic, p.value
        rows = an[an["term"] == "Tm"]
        if rows.empty:
            continue
        r = rows.iloc[0]
        R(f"| {int(r['season'])} | {float(r['statistic']):.3f} | "
          f"{int(r['df'])} | {float(r['p.value']):.4f} |")
    R("")
    R("If p < 0.05 the NL East teams have a statistically detectable "
      "difference in mean OPS. The NL East is competitive so we'd expect "
      "this to be marginal.")
    R("")
    R("## 3. Logistic — what predicts being all-star-level?")
    R("")
    R(f"**Outcome:** `is_all_star` = (OPS >= {ALL_STAR_OPS_THRESHOLD})")
    R("")
    R("**Formula:** `is_all_star ~ Age + HR + RBI + log_PA`")
    R("")
    R("| Season | positives | n |")
    R("|--------|-----------|---|")
    for g in log_glances:
        season = int(g['season'].iloc[0])
        n = int(g['nobs'].iloc[0])
        n_pos = log_positives_per_season.get(season, "?")
        R(f"| {season} | {n_pos} | {n} |")
    R("")
    R("Full coefficient tables in `outputs/csv/`.")

    out = REPORTS / "05_performance_models.md"
    out.write_text("\n".join(lines))
    print(f"\n[05] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
