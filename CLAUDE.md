# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TradingAgents-CN** (currently `v1.1.0-preview`) is a Chinese stock analysis platform using a multi-agent AI system built with LangGraph. It consists of:

- **Backend API**: FastAPI (`app/`) - Web server, database management, real-time notifications
- **Frontend**: Vue 3 + Element Plus + Vite (`frontend/`) - Single SPA UI
- **Core Engine**: LangGraph multi-agent system (`app/engine/`) - Analysis workflow
- **Data Layer**: Multi-source stock data with MongoDB + Redis caching
- **Runtime artifacts**: `runtime/` holds `cache/`, `data/`, `logs/`, `results/` and is created at startup

## Common Commands

### Development Setup

```bash
# Install Python dependencies (requires Python >=3.10,<3.14)
# pyproject.toml is the source of truth; requirements.txt is deprecated
pip install -e .
# or using uv (uv.lock is committed)
uv sync

# Optional extras: qianfan support
pip install -e ".[qianfan]"

# Install frontend dependencies
cd frontend && npm install

# Configure environment (.env.example is NOT shipped; create the file manually
# in the project root and populate the keys listed under "Configuration" below)
```

### Conda Environment (Recommended)

A `environment.yml` is provided for Miniconda/Anaconda users. **Do NOT use the base environment.**

```bash
# Create and activate dedicated conda environment
conda env create -f environment.yml       # or: conda create -n tradingagents python=3.12 -y
conda activate tradingagents

# Verify installation
python -c "import fastapi; print(f'fastapi={fastapi.__version__}')"
python -m pytest tests/ -q                # 1199 tests should pass
```

### Running the Application

```bash
# Start backend (from project root) — entry handles Windows UTF-8 setup, .env discovery, and uvicorn launch
python -m app
# or with uvicorn directly (skips the bootstrap above)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start frontend (in frontend/ directory)
cd frontend
npm run dev          # Vite dev server
npm run build        # `vue-tsc` type check + production build
npm run type-check   # vue-tsc --noEmit only
npm run lint         # ESLint with --fix
npm run format       # Prettier
```

### CLI / Programmatic Entry

`pyproject.toml` registers a console entry point: `tradingagents -> scripts.examples.run_analysis:main`. After `pip install -e .` you can run a sample end-to-end analysis with the `tradingagents` command.

### Docker Deployment

```bash
# Full stack with Docker Compose (includes MongoDB, Redis, Nginx)
docker compose -f docker-compose.build.yml up -d

# Access: http://localhost:3000 (Nginx proxy)
# API: http://localhost:8000/api
```

### Running Tests

```bash
# Run all pytest tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/integration/test_subgraph_architecture.py
python -m pytest tests/mcp/test_basic.py
python -m pytest tests/routers/test_tools.py
```

## Architecture Overview

### Legacy Code Layout Notice

The historical `tradingagents/` package has been merged into `app/engine/`. All core agent logic, graph workflows, and tools now live under `app/engine/`. Any remaining imports referencing `tradingagents` are compatibility shims — prefer `app.engine.*` for new code. The repo is not a git checkout in some local environments, so do not rely on `git log` for context.

### Governance & Pre-commit Hooks

A `.pre-commit-config.yaml` is provided at the project root with the following local hooks:

- **`no-mongo-in-routers`** — Rejects `find_one()` / `aggregate()` / `insert_one()` / `update_one()` / `delete_one()` in `app/routers/`
- **`no-bare-os-getenv`** — Ensures `os.getenv()` is only used in whitelisted config modules (`core/config.py`, `core/config_bridge.py`, `core/config_initializer.py`, `engine/graph/trading_graph.py`, `engine/llm_adapters/`, `worker/scheduler_setup.py`)
- **`no-config-manager-import`** — Blocks re-introduction of the removed `config_manager` module
- **`ruff`** + **`ruff-format`** — Standard Python linting via `ruff-pre-commit`

Convention tests in `tests/lint/test_router_conventions.py` enforce router naming standards (API prefix, English tags, no direct MongoDB calls).

### Multi-Agent Workflow (`app/engine/`)

The core analysis engine uses **LangGraph** with a 4-stage pipeline. Code under `app/engine/agents/` mirrors the stage layout:

1. **Stage 1 — Analysts** (`app/engine/agents/analysts/`): Vertical analysts (market, news, fundamentals, etc.) run in parallel
   - Configured in `config/agents/phase1_agents_config.yaml`
   - Dynamic loading via `app/engine/agents/analysts/dynamic_analyst.py`

2. **Stage 2 — Research Debate** (`app/engine/agents/stage_2/`): Bull/Bear researchers debate based on stage 1 outputs
   - Configured in `config/agents/phase2_agents_config.yaml`

3. **Stage 3 — Risk Management** (`app/engine/agents/stage_3/`): Risk teams evaluate trading plans
   - Configured in `config/agents/phase3_agents_config.yaml`

4. **Stage 4 — Trader** (`app/engine/agents/stage_4/`): Trader agent generates final trading decision

Shared agent helpers live in `app/engine/agents/utils/`.

**Key Files**:

- `app/engine/graph/trading_graph.py` - Main workflow orchestration and LLM provider routing; the public entry is `TradingAgentsGraph.propagate(company_name, trade_date, progress_callback=None, task_id=None)`
- `app/engine/graph/setup.py` - Graph construction
- `app/engine/graph/propagation.py` - State propagation logic
- `app/engine/graph/conditional_logic.py`, `reflection.py`, `signal_processing.py` - Routing, post-mortem reflection, and signal extraction
- `app/engine/default_config.py` - Default configuration
- `app/engine/agents/analysts/dynamic_analyst.py` - Dynamic analyst factory with MCP circuit breaker integration

### MCP Tool Architecture (`app/engine/tools/mcp/`)

MCP (Model Context Protocol) tools are managed as application-level infrastructure:

- **Loader**: `loader.py` - Based on `langchain-mcp-adapters`, loads local and external MCP tools
- **Task Manager**: `task_manager.py` - Task-level MCP manager with circuit breakers, retry mechanisms, and concurrency control
- **Health Monitor**: `health_monitor.py` - 30-second health check loop for all MCP connections
- **Tool Node**: `tool_node.py` - Custom tool node creation with error handlers
- **Config Utils**: `config_utils.py` - `MCPServerConfig`, config validation, and persistence

MCP connections are initialized at application startup (`app/main.py` lifespan) and kept alive throughout the application lifecycle.

### MCP Provider Server (`app/engine/mcp_provider/`)

A standalone MCP server implementation that exposes finance tools via the MCP protocol:

- **Server**: `server.py` - FastMCP server entry point wrapping data-source logic as MCP tools
- **Tools**: `tools/finance/` - Finance tool implementations (market data, fundamentals, news)

This was renamed from `mcp_server/` to `mcp_provider/` to avoid confusion with the MCP tool infrastructure in `app/engine/tools/mcp/`.

### Data Layer (`app/data/`)

Unified data access with automatic fallback:

- **Interface**: `interface.py` - Public API for all data access (A-share, HK, US)
- **Data Source Manager**: `data_source_manager.py` - Multi-source management with auto-degradation
- **Schema Layer**: `app/data/schema/` - Standardized field definitions for all collections
  - `base.py` - `BaseSchema`, `MarketType`, `get_full_symbol()`
  - `collections.py` - Collection name mapping by market
  - Per-entity schemas: `stock_basic_info.py`, `stock_daily_quotes.py`, `market_quotes.py`, `stock_financial_data.py`, `stock_news.py`
- **Sources Layer**: `app/data/sources/` - Provider + Adapter pattern by market
  - `base/` - `BaseProvider`, `BaseAdapter`
  - `cn/tushare/`, `cn/akshare/`, `cn/baostock/` - A-share data sources
  - `hk/akshare_hk/`, `hk/yfinance_hk/` - HK stock data sources
  - `us/yfinance_us/`, `us/finnhub_us/` - US stock data sources
- **Providers** (legacy, still actively used):
  - China: Tushare, AKShare, Baostock (in `providers/china/`)
  - US: Yahoo Finance, Finnhub (in `providers/us/`)
  - HK: HK stock providers (in `providers/hk/`)
- **Cache**: Multi-level caching (file, MongoDB, Redis) controlled by `TA_CACHE_STRATEGY`

**Field Standard**: All new code uses `symbol` (not `code`) and `data_source` (not `source`). The dual-write compatibility mode has been disabled — MongoDB migration is complete.

**Per-Market Collections**: A-share uses base collection names; HK/US use `_hk`/`_us` suffixes (e.g., `stock_basic_info_hk`).

**Usage**:

```python
from app.data.interface import get_china_stock_data_unified

data = get_china_stock_data_unified("000001", "2024-01-01", "2024-12-31")
```

### Backend API (`app/`)

FastAPI application structure:

- `main.py` - Application entry, lifespan management, APScheduler setup
- `routers/` - API route handlers (auth, analysis, config, MCP, tools, etc.)
  - Convention: every router must declare `prefix="/api/<domain>"` and use English Title-Case `tags=[]`
  - Sub-directory `config/` holds config-domain routers (data sources, LLM, markets, system)
  - Sub-directory `sync/` holds per-market sync routers (`cn_sync.py`, `hk_sync.py`, `us_sync.py`)
  - Direct MongoDB calls (`find_one`, `aggregate`, etc.) are forbidden in routers — use the service layer instead
- `services/` - Business logic (analysis, screening, sync services, quotes ingestion)
- `models/` - Database models (MongoDB with Motor)
- `core/` - Core configuration, database, logging, config bridge
- `worker/` - Background task workers (data sync, scheduled jobs)
  - `cn/` - A-share scheduled sync (wraps tushare/akshare/baostock_sync_service)
  - `hk/` - HK on-demand cache service (`hk_cache_service.py`)
  - `us/` - US on-demand cache service (`us_cache_service.py`)
- `middleware/` - Request/response middleware

### LLM Integration (`app/engine/llm_adapters/`)

Adapter pattern for multiple LLM providers — the directory is intentionally small because most providers are accessed through OpenAI-compatible endpoints:

- `dashscope_openai_adapter.py` - Aliyun DashScope (OpenAI-compatible mode)
- `deepseek_adapter.py` - DeepSeek with token tracking
- `google_openai_adapter.py` - Gemini via OpenAI-compatible API
- `openai_compatible_base.py` - Shared base for OpenAI-compatible APIs (SiliconFlow, OpenRouter, Qianfan, Zhipu, custom). Anthropic is integrated via `langchain-anthropic`, not a custom adapter.

Configuration is loaded dynamically from the database at runtime (via `config_service`), with `.env` as fallback.

## Configuration

### Environment Variables (`.env`)

Required for startup:

- `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_USERNAME`, `MONGODB_PASSWORD` - Database
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` - Cache
- `JWT_SECRET`, `CSRF_SECRET` - Security

Optional for AI features:

- `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `GOOGLE_API_KEY` - LLM providers
- `TUSHARE_TOKEN` - Professional A-share data

### Runtime Configuration (`config/`)

- `agents/phase1_agents_config.yaml` - Stage 1 analyst definitions
- `agents/phase2_agents_config.yaml` - Stage 2 debate configuration
- `agents/phase3_agents_config.yaml` - Stage 3 risk configuration
- `models.json` - LLM model definitions
- `pricing.json` - Token pricing for cost tracking
- `mcp.json` - MCP server configuration
- `settings.json` - Runtime system settings (auto-generated)
- `logging.toml` / `logging_docker.toml` - Logging profiles for local vs. container runs
- `defaults/`, `skills/` - Bundled default configs and skill definitions

The `config/README.md` notes that several `.json` files in this directory are auto-generated and may contain sensitive usage statistics — do not commit them.

## Key Patterns

### Adding a New Analyst Agent

1. Define the agent in `config/agents/phase1_agents_config.yaml`:

   ```yaml
   analysts:
     - slug: "custom_analyst"
       name: "Custom Analyst"
       role: "Analyze custom metrics"
       tools:
         - "tool_name"
   ```

2. Implement the tool under `app/engine/tools/` if needed.
3. The agent is automatically picked up by `DynamicAnalystFactory` — no Python registration required.

### Data Source Fallback

The system automatically degrades data sources when one fails:

- China stocks: User-configured priority (default Tushare → AKShare → BaoStock)
- Configured in `app/data/data_source_manager.py` and user settings

### Running Analysis Programmatically

```python
from app.engine.graph.trading_graph import TradingAgentsGraph
from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

# Get configured analysts
selected_analysts = [a.get("slug") for a in DynamicAnalystFactory.get_all_agents() if a.get("slug")]

# Initialize graph
ta = TradingAgentsGraph(selected_analysts=selected_analysts, debug=True)

# Run analysis
_, decision = ta.propagate("000001", "2024-12-31")
```

## Important Notes

- `app/` and `frontend/` are under proprietary license (`app/LICENSE`, `frontend/LICENSE`); other code is Apache 2.0
- Analysis requires data sync first — use the web UI or API to sync stock data before running an analysis end-to-end
- Python deps are locked in `uv.lock`; the legacy `requirements.txt` / `requirements-lock.txt` files are kept only for legacy installs
- Frontend is Vue 3 + Element Plus + Pinia + Vue Router 4, built with Vite (see `frontend/package.json`)
- Real-time updates use SSE, WebSocket, and Redis PubSub — see `app/routers/sse.py`, `app/routers/websocket_notifications.py`
