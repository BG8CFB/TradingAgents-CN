# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TradingAgents-CN** (`v1.1.0-preview`) is a Chinese stock analysis platform using a multi-agent AI system built with LangGraph. It consists of:

- **Backend API**: FastAPI (`app/`) — Web server, database management, real-time notifications
- **Frontend**: Vue 3 + Element Plus + Vite (`frontend/`) — Single SPA UI
- **Core Engine**: LangGraph multi-agent system (`app/engine/`) — 4-stage analysis pipeline
- **Data Layer**: Multi-source stock data with MongoDB + Redis caching
- **Runtime**: `runtime/` holds `cache/`, `data/`, `logs/`, `results/` (created at startup)

## Environment & Execution Model

### Two Execution Modes

| Mode | Where to Run | Infrastructure | When to Use |
|------|-------------|----------------|-------------|
| **Development** | Docker containers | MongoDB, Redis in Docker Compose | Running the app, API development, feature work |
| **Testing** | Host machine (Miniconda) | Connect to Docker-hosted MongoDB/Redis | Running tests, debugging, CI |

### Development Mode (Container-First)

The project runs inside Docker containers during development. Database and Redis are always containerized.

```bash
# Start full dev environment (backend hot-reload + frontend HMR + MongoDB + Redis)
docker compose -f docker-compose.dev.yml up --build

# Start only infrastructure services (for testing or standalone scripts)
docker compose -f docker-compose.dev.yml up -d mongodb redis

# Access points:
#   Frontend (Vite HMR): http://localhost:3000
#   Backend API docs:    http://localhost:8000/docs
#   MongoDB:             localhost:27017
#   Redis:               localhost:6379
```

**Why containers?** The backend Docker image includes all Python dependencies pre-installed. Source code is volume-mounted for hot-reload (`./app:/app/app`). No need to manage Python environments on the host for development.

### Testing Mode (Host + Miniconda)

Tests run on the host machine inside a Miniconda conda environment. They connect to containerized MongoDB/Redis for real I/O.

```bash
# 1. Ensure infrastructure is running
docker compose -f docker-compose.dev.yml up -d mongodb redis

# 2. Activate conda environment
conda activate tradingagents

# 3. Run tests
python -m pytest tests/ -v --tb=short
```

**Environment Setup (Miniconda Only):**

```bash
# Create conda environment (do NOT use the base environment)
conda env create -f environment.yml       # or: conda create -n tradingagents python=3.12 -y
conda activate tradingagents

# Install project dependencies inside conda env
pip install -e .                          # pyproject.toml is the source of truth

# Optional extras
pip install -e ".[qianfan]"
pip install -e ".[dev]"

# Verify installation
python -c "import fastapi; print(f'fastapi={fastapi.__version__}')"

# Frontend dependencies (if working on frontend)
cd frontend && npm install
```

**Environment Rules**:
- **Miniconda only** — never use system Python, venv, or virtualenv
- All `pip install` commands run inside the activated conda environment
- Do not create `.venv/` or `venv/` directories — if found, delete them
- `uv.lock` is committed for reference; `uv sync` only within conda env if used

## Docker Reference

**Container Selection Rule**: 默认始终使用 `docker-compose.dev.yml`（开发模式）。仅在用户明确要求"生产部署"时才切换到 `docker-compose.build.yml`。

| Compose File | Mode | Use When |
|--------------|------|----------|
| `docker-compose.dev.yml` | Development (hot-reload, HMR) | **默认** — 始终优先使用 |
| `docker-compose.build.yml` | Production (Nginx, built images) | 用户明确说"生产部署" |

### 开发模式热重载机制（重要）

`docker-compose.dev.yml` 的后端服务通过 volume 挂载 + uvicorn `--reload` 实现代码热重载：

- **`./app:/app/app`** — Python 源码卷挂载，修改后 uvicorn 自动检测并重启
- **`./config:/app/config`** — 配置文件挂载
- **`./frontend:/app/frontend`** — 前端源码挂载，Vite HMR 热更新

**因此：修改 Python 代码后不需要重新构建容器镜像。** 只需要保存文件，uvicorn 会自动重载。只有在以下场景才需要重新构建：
- 修改了 `pyproject.toml` 中新增/删除了依赖包（首次 `--build` 时安装）
- 修改了 `Dockerfile.backend` 本身
- 第一次启动项目

```bash
# ── Development (DEFAULT) ──
# 首次启动或修改了依赖/Dockerfile（需要 --build）
docker compose -f docker-compose.dev.yml up --build -d

# 日常开发：修改 Python 代码后无需任何操作，uvicorn 自动重载
# 如果容器已在运行，直接保存文件即可

# 如果需要重启后端服务（不重新构建）
docker compose -f docker-compose.dev.yml restart backend

# ── Production (ONLY when user requests) ──
# Full stack (MongoDB + Redis + Nginx + backend + frontend)
docker compose -f docker-compose.build.yml up -d
# Access: http://localhost:3000 (Nginx proxy) | API: http://localhost:8000/api

# ── Infrastructure Only (for testing) ──
docker compose -f docker-compose.dev.yml up -d mongodb redis
# Tear down when done
docker compose -f docker-compose.dev.yml down
```

## CLI / Programmatic Entry

`pyproject.toml` registers `tradingagents -> scripts.examples.run_analysis:main`. After `pip install -e .` (inside conda env), run `tradingagents` for a sample end-to-end analysis.

## Frontend Commands

```bash
cd frontend
npm run dev          # Vite dev server
npm run build        # vue-tsc type check + production build
npm run type-check   # vue-tsc --noEmit only
npm run lint         # ESLint with --fix
npm run format       # Prettier
```

## Testing Rules (Mandatory)

**All tests must be real — no mocks allowed. All tests run inside the Miniconda conda environment.**

1. **Real Database & Cache**: Tests needing MongoDB or Redis connect to containerized instances:
   ```bash
   docker compose -f docker-compose.dev.yml up -d mongodb redis
   # Wait for health checks, then run tests
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
