# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TradingAgents-CN** (`v1.1.0-preview`) is a Chinese stock analysis platform using a multi-agent AI system built with LangGraph. It consists of:

- **Backend API**: FastAPI (`app/`) — Web server, database management, real-time notifications
- **Frontend**: Vue 3 + Element Plus + Vite (`frontend/`) — Single SPA UI
- **Core Engine**: LangGraph multi-agent system (`app/engine/`) — 4-stage analysis pipeline
- **Data Layer**: Multi-source stock data with MongoDB + Redis caching
- **Runtime**: `runtime/` holds `cache/`, `data/`, `logs/`, `results/` (created at startup)

## Common Commands

### Development Setup (Miniconda Required)

**All Python dependencies must be installed in a Miniconda conda environment. Direct `pip install` to system Python or venv is forbidden.**

```bash
# 1. Create and activate conda environment (do NOT use the base environment)
conda env create -f environment.yml       # or: conda create -n tradingagents python=3.12 -y
conda activate tradingagents

# 2. Install project dependencies inside conda env
#    pyproject.toml is the source of truth
pip install -e .                          # installs into conda env, not system Python
# Optional extras: qianfan support
pip install -e ".[qianfan]"

# 3. Verify installation
python -c "import fastapi; print(f'fastapi={fastapi.__version__}')"
python -m pytest tests/ -q

# 4. Install frontend dependencies
cd frontend && npm install

# 5. Configure environment — create .env manually in project root
#    (see "Configuration" section for required keys)
```

**Environment Rules**:
- Use Miniconda only (not system Python, not venv, not virtualenv)
- All `pip install` commands run inside the activated conda environment
- Do not create `.venv/` or `venv/` directories — if found, delete them
- `uv.lock` is committed for reference; `uv sync` only within conda env if used

### Running the Application

```bash
# Start backend (from project root) — handles Windows UTF-8, .env discovery, uvicorn launch
python -m app
# or with uvicorn directly (skips bootstrap)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start frontend (in frontend/ directory)
cd frontend
npm run dev          # Vite dev server
npm run build        # vue-tsc type check + production build
npm run type-check   # vue-tsc --noEmit only
npm run lint         # ESLint with --fix
npm run format       # Prettier
```

### CLI / Programmatic Entry

`pyproject.toml` registers `tradingagents -> scripts.examples.run_analysis:main`. After `pip install -e .` (inside conda env), run `tradingagents` for a sample end-to-end analysis.

### Docker Deployment

```bash
# Full stack (MongoDB + Redis + Nginx + backend + frontend)
docker compose -f docker-compose.build.yml up -d
# Access: http://localhost:3000 (Nginx proxy) | API: http://localhost:8000/api

# Dev mode (hot reload backend, HMR frontend)
docker compose -f docker-compose.dev.yml up --build
```

### Running Tests

```bash
# All tests
python -m pytest tests/

# Specific file
python -m pytest tests/integration/test_subgraph_architecture.py
python -m pytest tests/routers/test_tools.py

# With verbose output
python -m pytest tests/ -v --tb=short
```

### Testing Rules (Mandatory)

**All tests must be real — no mocks allowed. All tests run inside the Miniconda conda environment.**

1. **Real Database & Cache**: Tests needing MongoDB or Redis must run against real instances via Docker Compose:
   ```bash
   # Start infrastructure only
   docker compose -f docker-compose.dev.yml up -d mongodb redis
   # Wait for health checks, then run tests
   docker compose -f docker-compose.dev.yml down
   ```

2. **Conda Environment Only**: Test dependencies in `tradingagents` conda env. **venv is forbidden** — delete `.venv/` or `venv/` if found.

3. **No Mocking**: No `unittest.mock`, `pytest-mock`, `MagicMock`, `patch`, or any mock library. Tests must exercise real code paths with real data and real I/O.

4. **Logical Coherence**: Tests must form coherent end-to-end flows — setup → action → assertion → cleanup.

5. **Test Structure**: Integration tests in `tests/integration/`, unit tests in `tests/` by domain. Temporary verification scripts in `.ai_temp/tests/` (deleted after use, covered by `.gitignore`).

## Architecture Overview

### Legacy Code Layout

The historical `tradingagents/` package has been merged into `app/engine/`. All core agent logic lives under `app/engine/`. Any remaining `tradingagents` imports are compatibility shims — use `app.engine.*` for new code.

### Governance & Pre-commit Hooks

`.pre-commit-config.yaml` enforces:

- **`no-mongo-in-routers`** — Rejects direct MongoDB calls (`find_one`, `aggregate`, etc.) in `app/routers/`
- **`no-bare-os-getenv`** — `os.getenv()` only in whitelisted config modules (`core/config.py`, `core/config_bridge.py`, `core/config_initializer.py`, `engine/config/env_utils.py`, `engine/graph/trading_graph.py`, `engine/llm_adapters/`, `worker/scheduler_setup.py`)
- **`no-config-manager-import`** — Blocks re-introduction of removed `config_manager`
- **`ruff`** + **`ruff-format`** — Standard Python linting

Convention tests in `tests/lint/test_router_conventions.py` enforce router naming (API prefix, English tags).

### Multi-Agent Workflow (`app/engine/`)

LangGraph 4-stage pipeline, configured via YAML files in `config/agents/`:

1. **Stage 1 — Analysts** (`app/engine/agents/analysts/`): Vertical analysts run in parallel. Dynamic loading via `dynamic_analyst.py`. Config: `phase1_agents_config.yaml`
2. **Stage 2 — Research Debate** (`app/engine/agents/stage_2/`): Bull/Bear debate. Config: `phase2_agents_config.yaml`
3. **Stage 3 — Risk Management** (`app/engine/agents/stage_3/`): Risk teams evaluate plans. Config: `phase3_agents_config.yaml`
4. **Stage 4 — Trader** (`app/engine/agents/stage_4/`): Final trading decision

**Key entry point**: `TradingAgentsGraph.propagate(company_name, trade_date, progress_callback=None, task_id=None)` in `app/engine/graph/trading_graph.py`

Graph construction: `app/engine/graph/setup.py`. State propagation: `propagation.py`. Routing/reflection/signal: `conditional_logic.py`, `reflection.py`, `signal_processing.py`.

### MCP Architecture

Two separate MCP-related directories — do not confuse them:

- **`app/engine/tools/mcp/`** — MCP tool **consumer** infrastructure (loader, task manager with circuit breakers, health monitor, tool node). Connections initialized at app startup in `main.py` lifespan.
- **`app/engine/mcp_provider/`** — MCP tool **provider** server (FastMCP server exposing finance tools as MCP resources)

### Data Layer (`app/data/`)

Unified multi-market platform with automatic fallback, circuit breaking, and scheduled sync. Key sub-directories:

- **`core/`** — `DataInterface` singleton facade, data reader, refresh service, domain/market utilities, registries
- **`schema/`** — `MarketType`, per-entity schemas (basic_info, daily_quotes, financial_data), market-specific fields (cn/hk/us)
- **`sources/`** — Provider + Adapter pattern, organized by market (`cn/`, `hk/`, `us/`) with `base/` for shared abstractions
- **`processor/`** — Fallback router, circuit breaker (closed → open → half-open), rate limiter, retry policy, normalizer, validator, post-processors
- **`storage/`** — MongoDB (`mongo/`), Redis (`redis/`), in-memory TTL cache
- **`scheduler/`** — APScheduler-based sync engine with per-market jobs
- **`monitoring/`** — Source health, completeness, reconciliation, alerts
- **`config/`** — YAML defaults for markets, capabilities, priorities, freshness

**Architectural Rules**:
- Consumers MUST use `DataInterface.get_instance()` — no direct `app.data.sources` or `app.data.storage` imports from outside `app/data/`
- Routers MUST NOT call MongoDB directly — use `DataInterface` or service layer
- All new code uses `symbol` (not `code`) and `data_source` (not `source`)
- Per-market collections: A-share uses base names; HK/US use `_hk`/`_us` suffixes

```python
from app.data.core.interface import DataInterface

di = DataInterface.get_instance()
result = await di.read("CN", "000001", "daily_quotes",
                       start_date="2024-01-01", end_date="2024-12-31")
```

### Backend API (`app/`)

- `main.py` — App entry, lifespan, APScheduler
- `routers/` — API handlers (auth, analysis, config, MCP, tools); sub-dirs `config/` and `sync/` for per-domain/market routes. Every router: `prefix="/api/<domain>"`, English Title-Case `tags=[]`, no direct MongoDB calls
- `services/` — Business logic (analysis, screening, sync, quotes ingestion)
- `models/` — MongoDB models (Motor async driver)
- `core/` — Config, database, logging, config bridge
- `worker/` — Background tasks (`cn/`, `hk/`, `us/` per-market sync workers)
- `middleware/` — Request/response middleware

### LLM Integration (`app/engine/llm_adapters/`)

Adapter pattern for multiple providers via OpenAI-compatible endpoints:

- `openai_compatible_base.py` — Shared base (SiliconFlow, OpenRouter, Qianfan, Zhipu, custom)
- `dashscope_openai_adapter.py`, `deepseek_adapter.py`, `google_openai_adapter.py` — Provider-specific adapters
- Anthropic via `langchain-anthropic` (not a custom adapter)

Config loaded dynamically from database at runtime (`config_service`), `.env` as fallback.

## Configuration

### Environment Variables (`.env`)

Required:
- `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_USERNAME`, `MONGODB_PASSWORD`
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- `JWT_SECRET`, `CSRF_SECRET`

Optional (AI features):
- `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `GOOGLE_API_KEY`
- `TUSHARE_TOKEN`

### Runtime Configuration (`config/`)

- `agents/phase1_agents_config.yaml` — Stage 1 analyst definitions
- `agents/phase2_agents_config.yaml`, `phase3_agents_config.yaml` — Stages 2-3
- `models.json` — LLM model definitions
- `mcp.json` — MCP server configuration
- `logging.toml` / `logging_docker.toml` — Local vs container logging profiles
- `defaults/`, `skills/` — Bundled default configs and skill definitions

Note: Several `.json` files are auto-generated and may contain sensitive stats — do not commit them.

## Key Patterns

### Adding a New Analyst Agent

1. Define in `config/agents/phase1_agents_config.yaml`:
   ```yaml
   analysts:
     - slug: "custom_analyst"
       name: "Custom Analyst"
       role: "Analyze custom metrics"
       tools: ["tool_name"]
   ```
2. Implement tool under `app/engine/tools/` if needed.
3. Auto-picked up by `DynamicAnalystFactory` — no Python registration required.

### Data Source Fallback

Automatic degradation when a source fails: user-configured priority (default Tushare → AKShare → BaoStock for A-shares).

### Running Analysis Programmatically

```python
from app.engine.graph.trading_graph import TradingAgentsGraph
from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

selected_analysts = [a.get("slug") for a in DynamicAnalystFactory.get_all_agents() if a.get("slug")]
ta = TradingAgentsGraph(selected_analysts=selected_analysts, debug=True)
_, decision = ta.propagate("000001", "2024-12-31")
```

## Important Notes

- `app/` and `frontend/` are proprietary license; other code is Apache 2.0
- Analysis requires data sync first — sync stock data via web UI or API before running analysis
- Python deps: Miniconda + `pyproject.toml`; `uv.lock` for reference; legacy `requirements.txt` kept for historical installs
- Frontend: Vue 3 + Element Plus + Pinia + Vue Router 4, built with Vite
- Real-time updates: SSE, WebSocket, Redis PubSub (`app/routers/sse.py`, `app/routers/websocket_notifications.py`)
