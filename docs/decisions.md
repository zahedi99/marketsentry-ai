# Architecture Decision Records

Short records of meaningful choices: what we decided, why, and what it costs us.
New ADRs go at the bottom. Superseded ADRs stay, marked as superseded.

| # | Title | Status |
|---|-------|--------|
| 001 | Monorepo tooling and package naming | Accepted |
| 002 | Agent framework (own loop vs LangGraph vs Claude Agent SDK) | Pending — decide before build step 8 |

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
