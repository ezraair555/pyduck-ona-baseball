# Kimi code review — `pybaseball-nl-east`

**Reviewer:** Kimi subagent · **Date:** 2026-06-27
**Codebase size:** ~1,500 LOC across `nl_east/` (4 files) + `examples/` (6 files) + manifests.
**Method:** Static review against the live `pyduck-ona`, `pyduck-ona-viz`, and `pyduck-ona-profile` source trees; spot-checked query results against the Parquet fixtures in `data/raw/` and `data/org/`. I did **not** re-run the network calls or examples.

---

## Top 5 P0/P1 findings

### P0-1 · Yankees (AL) are silently attributed to NL East — affects every output

**Location:** `nl_east/constants.py:71-78` (`is_nl_east_full_name`) and `nl_east/extract.py:91` (`_filter_nl_east`).

```python
# constants.py
def is_nl_east_full_name(name: str) -> bool:
    parts = {p.strip() for p in name.split(",")}
    return any(p in TEAM_ABBREV for p in parts)   # ← TEAM_ABBREV maps "New York" → NYM
```

`pybaseball.batting_stats_range` / `pitching_stats_range` return **every MLB player** in the date range, not just NL teams. `Tm` is full team names; `"New York"` is ambiguous between the Mets (NL East) and the Yankees (AL East).

I verified against the fixture: `data/raw/batting_2024.parquet` contains 38 rows with `Tm = "New York"`, including Aaron Judge, Giancarlo Stanton, Gleyber Torres, and Alex Verdugo — all 2024 Yankees. Pitching 2024 has 52 such rows.

**Downstream impact:**
- **Every org CSV** in `data/org/org_NYM_*.csv` includes Yankees players in the Mets hierarchy (their `mlbID`s are routed to `NYM-L3-INFIELD` / `NYM-L3-OUTFIELD` / `NYM-L3-BULLPEN` / `NYM-L3-STARTERS`).
- **`examples/01_orgchart_overview.py`**: NYM betweenness, span-of-control, and PageRank numbers are inflated by ~52 phantom players per season. The README's "every team's `L3-BULLPEN` coach has the highest span of control" claim survives, but the magnitudes are wrong for NYM.
- **`examples/02_visualize_orgchart.py`**: NYM year-over-year HTML dashboards contain Yankees nodes.
- **`examples/04_nl_queries.py`**: `"Pitchers with the lowest ERA"`, `"Top HR hitters"`, `"Best OPS hitters"` all return mixed Mets+Yankees rankings.
- **`examples/05_performance_models.py`** (most consequential): `run_anova` filters on `Tm.isin({"Atlanta", "Miami", "New York", "Philadelphia", "Washington"})`. The `"New York"` bucket conflates Mets and Yankees hitters, so the ANOVA `OPS ~ Tm` mixes ~25 Yankees hitters into the "NYM" group per season. This **changes the F-statistic and p-values** for every season.

**Why it's not flagged in known-limitations:** The README's limitation #3 only mentions multi-stint *trades*, not single-team disambiguation.

**Fix (small, safe):** maintain a parallel set of full names that are *uniquely NL East* — i.e., exclude `"New York"` from the auto-include path and only keep `"New York"` when no other `Tm` is present (i.e., the player was Mets-only that season). Concretely:

```python
# constants.py
TEAM_ABBREV_UNIQUE_NL: dict[str, str] = {
    "ATL": "Atlanta", "MIA": "Miami", "PHI": "Philadelphia", "WSN": "Washington",
}
TEAM_ABBREV_AMBIGUOUS_NL: dict[str, str] = {"NYM": "New York"}  # also AL: NYY

def is_nl_east_full_name(name: str) -> bool:
    """Keep rows where *all* stints are NL East; the row's 'final' team must be
    a unique NL East name, OR (for ambiguous names) the row's `Tm` must contain
    that name and no other NL stint names so we know it's not a multi-team row
    that happened to be Mets-only at the end.
    """
    parts = {p.strip() for p in name.split(",")}
    if parts & set(TEAM_ABBREV_UNIQUE_NL.values()):
        return True
    # For the "New York" case, we need to know if this is the Mets or Yankees.
    # pybaseball's Tm is final-stint-last, so a Mets-only row will be exactly
    # "New York"; a player who played for multiple teams will list them all.
    # True Mets-only rows are still "New York" — so we can't disambiguate from
    # Tm alone. The clean fix is to also require league info; if that's not
    # available, drop "New York" entirely from the keep-set and accept that
    # the Mets org chart excludes Mets hitters.
    return False
```

Even if you can't recover Mets hitters cleanly, the safer default is to drop the ambiguous rows and ship a clean (smaller) org chart. The current state — including Yankees — is worse than the alternative.

If you want to keep Mets coverage, you'd need a per-player league join. The simplest version is to fetch the active 26-man + 40-man rosters via `pybaseball.roster` (which exposes `Tm`, `League`, `playerID`) once per season and join on `mlbID`. That keeps the showcase scope, since you're already calling Baseball Reference.

---

### P0-2 · The example 03 workaround is **unnecessary** — the comment misdiagnoses the integration gap

**Location:** `examples/03_player_profile.py:140-147` and the README's "Workaround" section.

```python
# Workaround: Timeline._auto_detect looks for ona.compensation as an attribute,
# but DuckONA keeps tables in ona._table_names instead.
ona.hris = ona.con.sql("SELECT * FROM hris")
ona.compensation = ona.con.sql("SELECT * FROM compensation")
if "attendance" in ona._table_names:
    ona.attendance = ona.con.sql("SELECT * FROM attendance")
```

I traced the upstream code:

- `pyduck-ona-profile/src/pyduck_ona_profile/subject.py` `_relation_to_df` has **three** fallbacks: `getattr(ona, table)`, `getattr(ona, "_" + table)`, then **`getattr(ona, "con").sql(...)` when the table name appears in `getattr(ona, "_table_names")`**. Since `DuckONA.load_compensation` (in `pyduck-ona/src/pyduck_ona/analysis.py`) does `self._table_names.add(table_name)`, the third fallback succeeds for any loaded table.
- `pyduck-ona-profile/src/pyduck_ona_profile/timeline.py` `_try_get_relation` only tries `("compensation", "_compensation")` — i.e., it tries `getattr(ona, "compensation")` and `getattr(ona, "_compensation")`. If those are both None, it returns None and the event detector silently no-ops (returns an empty events DataFrame per `events.py:_empty_events`).
- The `_auto_detect` path therefore **also** fails to detect events. So even with the workaround, `tl.manager_changes()` and `tl.promotions()` return **empty DataFrames** because the loaded HRIS has no `snapshot_date` column — see P0-3.

So:
- The workaround does help `Subject.profile()` (which uses the third-fallback path), so removing it would break the Subject view's compensation/attendance lookups.
- But the comment's *reason* is wrong — it's not about `_table_names`, it's about the attribute-vs-connection lookup chain.
- More importantly, **the workaround doesn't fix what the README says it fixes**: the manager_change detector still won't fire because the org CSV has no `snapshot_date` column.

**Fix:**
1. Update the comment to be accurate: "DuckONA exposes `con` and `_table_names` but not `hris` / `compensation` / `attendance` as public attributes, and `Subject._relation_to_df`'s first two `getattr` attempts both return None, so we expose the relations explicitly. (The third fallback in `Subject` would also work; this is the most direct path.)"
2. Drop the `if "attendance" in ona._table_names:` guard — it's already implicit in `_try_get_relation` returning None when the attribute is missing; instead just always assign: `ona.attendance = ona.con.sql("SELECT * FROM attendance")`.
3. Either remove the workaround (Subject will still work via the third fallback) or keep it and update the rationale — but **don't keep the wrong rationale**.

---

### P0-3 · Trade / promotion / manager-change events are silently empty (no `snapshot_date`)

**Location:** `examples/03_player_profile.py:101-114` (HRIS loader) and `pyduck-ona-profile/src/pyduck_ona_profile/events.py:55-90`.

The current `load_hris_for_team` returns the per-season org CSV, which has columns `employee_id, supervisor_id, name, title, department, job_level, team, season, mlb_id, role, games, gs, pa` — **no `snapshot_date`**. The event detectors in `events.py` all require `snapshot_date`:

```python
if df.empty or snapshot_col not in df.columns:
    return _empty_events(employee_col)
```

So `tl.manager_changes()`, `tl.comp_history()`-on-hris, and `tl.promotions()` all return empty DataFrames.

**Comp_history still works** because `load_player_stats_as_compensation` (line 84) *does* include `snapshot_date`. So you'd see `comp_change` events for year-over-year OPS moves — but **no `manager_change` events**, even though the README explicitly claims "Manager_change events (trades)" and the docstring at the top of `examples/03_player_profile.py` says "render manager_change events (trades)".

**Fix (two options):**

a) **Generate trade events explicitly from multi-stint data.** When you load `Tm` for a player across seasons, split each multi-stint comma-separated `Tm` into per-team rows, then emit a `manager_change` event for each team transition with `event_date = season-end (e.g., 2024-09-30)`. This is the proper "trade detection" the README mentions under known-limitation #3.

b) **Tag the org with `snapshot_date`.** If you want to keep the single-season-per-org model, add `snapshot_date = MAKE_DATE(season, 7, 1)` to the HRIS load. `detect_manager_changes` will still find 0 changes per single-snapshot frame (because there's only one observation), which is the correct answer for an intra-season view. The `comp_history` view will then have the full event log.

Option (a) is the showcase-worthy choice — it actually delivers the "trade as manager_change" feature the README advertises.

---

### P1-1 · `examples/04_nl_queries.py` year-extraction regex grabs the *first* year in multi-year questions

**Location:** `examples/04_nl_queries.py:51-55`.

```python
year_match = re.search(r"\b(20\d{2})\b", question)
has_year = year_match is not None
effective_season = (
    int(year_match.group(1)) if has_year else season_default
)
```

If a user asks "Top HR hitters from 2023 to 2024", `year_match` captures `"2023"` and the post-processor substitutes `batting_2023` into the rendered SQL. The user's intent (compare 2023 vs 2024, or use 2024 as "current") is lost.

Not a blocker for the current `QUESTIONS` list (which has at most one year per question), but the showcase would benefit from either:
- Documenting the limitation explicitly: *"the wrapper assumes a single year per question; multi-year questions resolve to the earliest year."*
- Or upgrading to a list-based extraction: `re.findall(r"\b(20\d{2})\b", question)` and a sane default (the **last** year, or the maximum year ≤ current).

I'd go with documenting it for now — the showcase questions don't exercise it.

---

### P1-2 · `examples/05_performance_models.py` logistic "positives" column in the Markdown report is wrong

**Location:** `examples/05_performance_models.py:222-227`.

```python
R("| Season | positives | n |")
R("|--------|-----------|---|")
for g in log_glances:
    n_pos = int(g["nobs"].iloc[0])  # placeholder, won't be exact
    R(f"| {int(g['season'].iloc[0])} | (see CSV) | "
      f"{int(g['nobs'].iloc[0])} |")
```

The Markdown table has two columns but only fills one (`n_pos` is assigned to the wrong column and then ignored — the literal string "(see CSV)" is what gets printed). The CSV file does have the correct info (the `logistic_coefficients_all.csv` file is fine). 

**Fix:** Compute `n_pos` from the per-season batting frame (`prep_batting` already filters and sets `is_all_star`). Add `log_positives = int(df["is_all_star"].sum())` in the loop where `df` is still in scope, and store it on the glance dict or pass to the report builder.

---

## P2 recommendations

### Architecture (P2)

- **`_common.py` is fine, no leakage.** Each call to `load_all()` opens a fresh `duckdb.connect(":memory:")` and re-registers views; nothing is module-level state that would persist across examples. The only shared module-level state is the path constants (`FIGURES`, `HTML`, etc.), which is harmless.
- **`install_baseball_patterns` is global state.** It mutates `pyduck_ona_profile.query.ask._MATCHER`. **A subprocess per `ask()` call is overkill** for this showcase — the script runs once per process. If you later wanted to host `ask()` as a service, you'd want to inject the matcher via the `matcher=` kwarg in `ask()` (which the upstream API already supports) rather than rely on the module-level singleton.
- **Coaching hierarchy location is correct.** Living in `nl_east/coaching.py` is the right call: it's domain-specific to the showcase (would never go in pyduck-ona), and keeping it next to the extraction keeps the data-model coupled.
- **Consider a `nl_east.pipeline` module.** The two-step CLI (`extract → build_orgchart`) is implicit. If you add a third step (e.g., a manifest validator or a pre-flight check for cross-team collisions), a thin orchestrator that imports both CLIs and runs them in order would help. For the current two-step pipeline, the README's run sequence is fine.

### Documentation (P2)

- **`README.md` is solid but misses three things:**
  1. **The Yankees attribution issue** (see P0-1). This should be in the known-limitations list.
  2. **What columns the per-example output lands where.** You list "45 PNGs, 18 HTML, 8 CSVs, 5 reports" in aggregate but not which file goes with which example. A small table per example would help.
  3. **Reproducibility note.** The showcase reads `date.today()` for the 2026 end date (in `extract.py:64`). Add a one-liner: *"For reproducibility, run `python -m nl_east.extract --today 2026-06-27`."* Also the synthetic coaching names are taken from recent staffs but aren't dated — a future reader won't know whether "Brian Snitker" is the 2024 or 2025 manager.
- **Per-example walkthroughs vs. `outputs/reports/*.md`:** I'd keep the Markdown reports **inside `outputs/reports/`** (they're generated artifacts and they live alongside the figures). A short `docs/` walkthrough that explains *what to look for* in each report would complement them — e.g., `docs/01_orgchart_overview.md` says "open `outputs/figures/focal_centrality_ATL_2024.png` and note the L3-BULLPEN coach at the top of betweenness." Currently the report filenames map 1-to-1 to example filenames, but the *insights* in each are buried inside the report.
- **`TODO.md` is mostly stale.** The README claims it's "running plan + design notes" but all Phase 1-8 items are either done or being done. Either mark it deprecated in a header (`> ⚠️ TODO.md is a planning artifact; for current state see README.md.`) or delete the unchecked items.

### Tests (P2)

Highest-value tests given the showcase nature, in order of ROI:

1. **`test_extract.py` — `is_nl_east_full_name` and `_filter_nl_east`.** Unit tests for:
   - `"New York"` returns False (after the P0-1 fix; currently returns True).
   - `"Atlanta,Miami"` returns True (any stint is NL East).
   - `"Atlanta,Cleveland"` returns True (Atlanta is NL East).
   - `"Tampa Bay"` returns False.
   - Multi-stint rows preserve all columns.
2. **`test_build_orgchart.py` — coaching hierarchy construction.** Assert:
   - Exactly 10 coaches per team per season (matches manifest).
   - Exactly 1 root.
   - All `supervisor_id` values resolve to an `employee_id` in the same DataFrame (no broken chains).
   - Multi-stint players appear once per org (with consistent L3 split) — currently they appear once but with different supervisor_ids across teams.
3. **`test_examples_smoke.py` — each example imports and reaches the report-writing line.** Don't actually run the network or sentence-transformer. Use `subprocess.run(["python", "-c", "import examples.01_orgchart_overview"])` plus a `monkeypatch` on the heavy functions. The aim is to catch broken imports and signature drift in pyduck-ona.
4. **`test_ask_wrapper.py` — the season-default wrapper in example 04.** Pure unit tests on the `ask()` wrapper's regex substitution:
   - `("Who has the most HR?", season_default=2025)` → SQL contains `batting_2025`.
   - `("Who has the most HR in 2024?", season_default=2025)` → SQL contains `batting_2024`.
   - `("Best ERA pitchers 2023 to 2024", season_default=2025)` → documents the limitation (returns 2023) or asserts the fix.
5. **`test_player_profile.py` — Subject/Timeline plumbing.** Construct a minimal DuckONA from a 2-row hris (with `snapshot_date`) and a 2-row compensation frame, then assert `Timeline(subject).manager_changes().shape == (1, ...)` after a synthetic manager swap.

Skip: nothing in `examples/02_visualize_orgchart.py` needs a test — the figures are visual artifacts and the upstream `pyduck-ona-viz` already has tests.

### Things I should NOT have done (P2)

- **MD5-hash split for hitters (INFIELD vs OUTFIELD) is fine for the showcase but is a misdirection if you ever extend it.** The TODO asks: "is that the right call, or should I be using real position data?" Answer: for the showcase, the MD5 split is correct — it's reproducible across runs and seasons, and `pyduck-ona` doesn't care about position semantics for ONA (it only needs the hierarchy to be connected and acyclic). If you ever want to do anything with *position* — say, "do catchers have different betweenness than outfielders" — you'd need real position data. For that, `pybaseball` has `pybaseball.fielding_stats_range(start, end)` which gives you position-level stats. Adding a `--real-positions` flag to `build_orgchart.py` that switches the L3 split to a real `Pos` column would be a 30-line change.

- **Two-way player handling is mis-commented (P2).** In `coaching.py:300-309`, the comment says "Make the hitter tree the primary reporting line; the pitcher tree becomes a 'secondary' relationship" but the code just `continue`s, leaving the player as a Pitcher (because pitching is iterated first). Either flip the iteration order (batting first) or change the comment to "skip — the pitcher entry wins as the primary supervisor."

- **Dead import in `examples/04_nl_queries.py:125`** — `TEAM_ABBREV_BY_FULL` is imported but never used. Lint will complain. Remove it.

- **`_filter_nl_east` re-adds `stat_type` but the org-chart builders ignore it.** That's fine — `batting_df` and `pitching_df` come in with the column already, and `coaching.build_orgchart` doesn't use it. But it means the column persists into the final CSV (`pa`, `games`, `gs` columns survive). Harmless.

---

## Verdict

**Fix P0-1 (Yankees/NYM attribution) and P0-3 (empty Timeline events) before publishing the showcase.** The Yankees bug is the kind of thing that undermines the whole pitch ("pyduck-ona analyzes baseball rosters correctly") the moment someone looks at the NYM org chart and asks "why is Aaron Judge a Met?". The Timeline workaround is a smaller fix but matters because the README explicitly advertises manager_change events. **Ship after those two fixes; everything else (P1, P2) is polish.**