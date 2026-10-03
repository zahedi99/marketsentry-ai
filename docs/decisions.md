# Architecture Decision Records

Short records of meaningful choices: what we decided, why, and what it costs us.
New ADRs go at the bottom. Superseded ADRs stay, marked as superseded.

| # | Title | Status |
|---|-------|--------|
| 001 | Monorepo tooling and package naming | Accepted |
| 002 | Agent framework (own loop vs LangGraph vs Claude Agent SDK) | Pending — decide before build step 8 |
| 003 | Hybrid significance: code scores moves, agents decide stories | Accepted |

---

## ADR-001: Monorepo tooling and package naming

**Date:** 2026-10-02 · **Status:** Accepted

### Context
MarketSentry is one repo with several Python packages (core logic, data sources,
tools, agents, db), three Python apps (API, worker, MCP server), and a Next.js web app.
The packages import each other and must stay version-consistent.

### Decision
- **Python: uv workspace.** The root `pyproject.toml` lists members; one `uv.lock` and one
  `.venv` cover all of them. Members depend on each other with
  `{ workspace = true }` sources and are installed editable, so changes are picked up
  without reinstalling. Install with `uv sync --all-packages` (plain `uv sync` installs
  only the root project, which has no dependencies).
- **Build backend: `uv_build`** with `module-root = ""` (flat layout: `pkg/pkg_name/`,
  not `pkg/src/pkg_name/`).
- **Lint/format: ruff** (one tool replacing flake8, isort, black). Rule `DTZ` bans naive
  datetimes, enforcing "timezone-aware UTC everywhere".
- **Types: mypy `strict`** across all Python code (the brief requires strict on
  `packages/`; applying it to apps too is simpler and costs little on a new codebase).
  The pydantic mypy plugin is enabled.
- **Tests: pytest with `--import-mode=importlib`**, so multiple folders named `tests`
  don't clash. Test folders have no `__init__.py`.
- **Web: pnpm workspace**, version pinned via `packageManager` and activated by corepack.
- **Task runner: Makefile** (`make install | lint | typecheck | test | check | up`), so a
  clean clone has one obvious entry point.

### Package naming
Distribution names use hyphens, import names underscores (Python convention).

| Folder | Distribution | Import | Why not the obvious name |
|---|---|---|---|
| `apps/api` | `api` | `api` | Both apps were `app`; they'd overwrite each other in one environment |
| `apps/worker` | `worker` | `worker` | Same as above |
| `packages/agents` | `briefing-agents` | `briefing_agents` | `agents` is the OpenAI Agents SDK's import name, a candidate in ADR-002 |
| `packages/tools` | `agent-tools` | `agent_tools` | `tools` is too generic and likely to collide |
| `packages/db` | `ms-db` | `ms_db` | `db` is too generic |

### Consequences
- One command (`make install`) sets up everything; lockfiles make installs reproducible.
- Strict mypy slows early prototyping slightly, but catches type bugs before runtime.
- `pytest` exits with code 5 ("no tests collected") until build step 2 adds tests.
- On Windows with the uv cache on a different drive from the repo, uv warns that it can't
  hardlink; set `UV_LINK_MODE=copy` to silence it (no functional impact).

---

## ADR-003: Hybrid significance: code scores moves, agents decide stories

**Date:** 2026-10-03 · **Status:** Accepted

### Context
Each night the watchlist produces many price moves; most are noise. Something must decide
which are worth investigating. Options considered:
1. **LLM-only:** agents read all raw moves and decide.
2. **Trained ML model:** learn "newsworthy or not" from labelled history.
3. **Code-only:** a fixed rule decides and nothing else.
4. **Hybrid:** code scores every move; agents make the final call with news context.

### Decision
**Hybrid (4).**
- **Code (`market_core.significance`)** scores each move by how unusual it is *for that
  instrument*: `|move %| / typical daily move %` (a z-score style measure, with volatility
  taken from the instrument's own recent history). It outputs a score, a level and a
  code-generated reason. Thresholds are deliberately low: the job is **recall**, not to
  have the final say.
- **Agents (Sentinel / Orchestrator)** receive the ranked candidates *plus* news-only
  events, and decide what becomes a story (**precision and judgment**). They may promote a
  low-score move with major news, or drop a high-score move with no driver. They never do
  the arithmetic.

### Scoring rules
- **Typical move:** sample standard deviation of the **last 20** daily % changes (about one
  trading month, the common window for recent volatility). With fewer than 20, it is "not
  enough history". One number serves as both minimum and window.
  - Why 20, not 10: the relative error of a sample stdev is about `1/sqrt(2(n-1))`, roughly
    24% at n=10 vs 16% at n=20. Longer windows go stale as volatility regimes change.
  - Cost: instruments with < 20 days use the cruder fallback. Mitigation: **backfill** at
    least a month of history from the data provider when an instrument is added (build
    steps 3/4), so the fallback applies only to genuinely new listings.
  - Tunable and cheap to change; evals (step 9) compare windows.
- **Sensitivity** is a user setting (per instrument later). A score at or above the
  threshold reaches that level:

  | Sensitivity | NOTABLE | MAJOR |
  |---|---|---|
  | high | 1.0 | 2.0 |
  | normal (default) | 1.5 | 3.0 |
  | low | 2.0 | 4.0 |

  Rationale: absolute size is misleading (0.8% is a big move for EUR/USD and a quiet day
  for Tesla), and at 1.5 roughly 13% of ordinary nights are flagged per instrument, which
  is acceptable noise because agents filter afterwards.
- **Not enough history:** fall back to an assumed typical move per asset class
  (equity 1.5%, index 1.0%, fx 0.5%, crypto 4.0%, commodity 1.5%), and flag that a
  fallback was used. A new instrument must never hide a move.
- **Zero volatility** (flat history): any non-zero move is MAJOR (score undefined); no move
  is NONE. When in doubt, surface it.

### Why not the alternatives
- **LLM-only:** unreliable at comparing many numbers, non-deterministic (hard to test),
  costly to run over every instrument nightly, and conflicts with "numbers come from data,
  never from an LLM".
- **Trained ML model:** needs labelled "newsworthy" examples that we don't have. The
  z-score is the standard baseline any learned model must beat.
- **Code-only:** misses news-driven stories with little price reaction (e.g. a CEO
  resigns after the close) and ignores context such as earnings days.

### Knowledge transfer
The design already relies on transferred knowledge: pretrained LLMs judge newsworthiness
zero-shot, and the z-score applies established quant practice. Future options, adopted
**only if they beat the baseline in evals**:
- Pretrained finance text models (e.g. FinBERT) to classify overnight news cheaply before
  LLM agents read it.
- A transfer-learned significance model trained on weak labels (e.g. a move followed by a
  spike in news coverage).

### Consequences
- Significance is deterministic, explainable and unit-tested.
- The Sentinel must also surface news-only events, not only scored moves (build step 8).
- Evals (step 9) compare score-only vs LLM-only vs hybrid on recorded nights.
- Known simplification: overnight windows are shorter than a trading day, so "typical
  daily move" overstates the normal overnight move. Revisit with time-scaling if evals
  show it matters.
