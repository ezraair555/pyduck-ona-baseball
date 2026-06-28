# TODO — pybaseball NL East showcase (pyduck-ona + pyduck-ona-viz + pyduck-ona-profile)

## Concept
A showcase repository that demonstrates `pyduck-ona`, `pyduck-ona-viz`, and
`pyduck-ona-profile` on **baseball roster data** rather than workforce HR data.

**Stretch:** It is the same data shape — players have employee_id (mlbID),
supervisor_id (manager: hitting coach, pitching coach, manager), department
(position group: Batter / Pitcher / Catcher / Infielder / Outfielder),
job_level (rookie → star), hire_date (debut date), compensation (salary), etc.

**Angles:**
1. **Org-chart analysis on team rosters** — who reports to whom in a coaching
   hierarchy, span of control by coach, central players (betweenness on
   trade/lineup network), communities (lineup-cluster detection).
2. **Player-as-subject** — `Subject` view for any player: career timeline
   (trades = manager_change events), compensation history, performance trend.
3. **Natural-language queries on roster** — `ask("Who leads the Mets in HR?")`
   via the sentence-transformer pattern bank.
4. **Performance regressions** — `ols(WAR ~ age + position)`,
   `logistic(all_star)`, `anova(ops by team)`.

## Seasons
2023, 2024, 2025, 2026 (up to current date 2026-06-27).

## NL East teams
- Atlanta Braves (ATL)
- Miami Marlins (MIA)
- New York Mets (NYM)
- Philadelphia Phillies (PHI)
- Washington Nationals (WSN)

## Steps

### Phase 1: Project skeleton
- [x] Create `projects/pybaseball-nl-east/` directory
- [ ] Create `README.md` with full concept, install, run, and outputs
- [ ] Create `pyproject.toml` so the project is installable
- [ ] Create `requirements.txt`
- [ ] Create `nl_east/` package with `__init__.py` + helpers
- [ ] Create `examples/` directory

### Phase 2: Data extraction (pybaseball)
- [ ] `nl_east/extract.py` — fetch batting + pitching for each season via
      `batting_stats_range` / `pitching_stats_range`, filter to NL East,
      save parquet to `data/raw/{season}/{team}.parquet`
- [ ] Add a `--refresh` flag to skip if cached
- [ ] Save a manifest `data/raw/_manifest.json` with row counts per
      (season, team, type)

### Phase 3: Org-chart construction (synthetic coaching hierarchy)
- [ ] `nl_east/build_orgchart.py` — synthesize a 4-level coaching hierarchy
      per team (Manager → Bench Coach → Pitching Coach / Hitting Coach →
      Position Coaches → Players)
- [ ] Apply span-of-control / depth diagnostics with `pyduck_ona`
- [ ] Save org charts as CSVs to `data/org/{team}_{season}.csv`

### Phase 4: ONA — graph analysis
- [ ] `examples/01_orgchart_overview.py` — run pyduck-ona on each team:
      hierarchy_valid, hierarchy_long, hierarchy_wide, hierarchy_stats,
      betweenness, pagerank, louvain_communities on the player-coach graph
- [ ] Compare 2023-2026 seasons side by side

### Phase 5: Viz
- [ ] `examples/02_visualize_orgchart.py` — span_of_control,
      span_vs_depth, hierarchy_depth_heatmap, centrality_dashboard,
      silo_map, org_chart_tree per team
- [ ] Save PNGs to `outputs/figures/` and HTML to `outputs/html/`

### Phase 6: Profile (Subject + Timeline + ask())
- [ ] `examples/03_player_profile.py` — use DuckONA + pyduck-ona-profile
      to build a Subject view for a star player (e.g. Ronald Acuña Jr.,
      Bryce Harper, Juan Soto, etc.) showing trade history (manager_change),
      season-by-season stats, and an `as_of` snapshot
- [ ] `examples/04_nl_queries.py` — natural-language queries on the
      roster, e.g. "Top HR leaders in the NL East in 2024?",
      "Which Mets pitchers have the lowest ERA in 2025?",
      "Players with the most strikeouts in 2026 so far?"

### Phase 7: Statistical analysis
- [ ] `examples/05_performance_models.py` — OLS regression of OPS ~ age +
      position + team; logistic regression of all_star ~ age + war + team;
      ANOVA on OPS by team

### Phase 8: Documentation & polish
- [ ] Top-level `README.md` — narrative writeup of the whole showcase
- [ ] `docs/` — per-example markdown walkthrough
- [ ] Verify all examples run end-to-end with `python -m`
- [ ] Write a `memory/2026-06-27_pybaseball_nl_east.md` summary entry

## Decisions to confirm
1. **Coaching hierarchy** — pybaseball doesn't expose coaching hierarchies
   directly. Plan: synthesize a plausible 4-level hierarchy per team so the
   pyduck-ona graph tooling has something to chew on. Real coaching tree
   can be hard-coded for 1-2 teams as a bonus.

2. **Trade detection as "manager_change"** — `batting_stats_range` shows
   `Tm` as a comma-separated list when a player was traded mid-season.
   We'll split that into per-stint rows and treat the trade as a
   manager_change event for pyduck-ona-profile timeline.

3. **Compensation** — pybaseball doesn't include salary. We'll either
   skip compensation entirely or pull from a separate source (Chadwick
   CSV / spotrac scrape). Initial scope: skip compensation; rely on
   performance stats + roster moves for the subject view.

4. **Scope of seasons** — 2023-2026 inclusive. 2026 will be partial
   (~25% of season). We'll mark 2026 as "partial" in the manifest.

5. **NL East teams** — 5 teams confirmed. We'll use MLB team full names
   in the filter ("Atlanta", "Philadelphia", etc.) since `Tm` is full names.
