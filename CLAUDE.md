# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TradingAgents-CN** is a Chinese stock analysis platform using a multi-agent AI system built with LangGraph. It consists of:

- **Backend API**: FastAPI (`app/`) - Web server, database management, real-time notifications
- **Frontend (Legacy)**: Vue 3 + Element Plus (`frontend/`) - Original SPA UI
- **Frontend (New)**: React 19 + Ant Design (`frontend-react/`) - Experimental new UI
- **Core Engine**: LangGraph multi-agent system (`app/engine/`) - Analysis workflow
- **Data Layer**: Multi-source stock data with MongoDB + Redis caching

## Common Commands

### Development Setup

```bash
# Install Python dependencies (requires Python 3.10+)
# pyproject.toml is primary; requirements.txt is deprecated
pip install -e .
# or using uv
uv sync

# Install legacy frontend dependencies
cd frontend && npm install

# Install React frontend dependencies
cd frontend-react && npm install

# Configure environment
copy .env.example .env  # Windows
cp .env.example .env    # Linux/Mac, then edit with your API keys
```

### Running the Application

```bash
# Start backend (from project root)
python -m app
# or with uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start legacy frontend (in frontend/ directory)
cd frontend
npm run dev          # Development server
npm run build        # Production build
npm run type-check   # TypeScript check
npm run lint         # ESLint

# Start React frontend (in frontend-react/ directory)
cd frontend-react
npm run dev
npm run build
npm run lint
```

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

### Major Refactor Notice

The `tradingagents/` directory was merged into `app/engine/` (commit `951efcb`). All core agent logic, graph workflows, and tools now live under `app/engine/`. Any remaining imports referencing `tradingagents` are compatibility shims.

### Multi-Agent Workflow (`app/engine/`)

The core analysis engine uses **LangGraph** with a 4-stage pipeline:

1. **Stage 1 (Analysts)**: Vertical analysts (market, news, fundamentals, etc.) run in parallel
   - Configured in `config/agents/phase1_agents_config.yaml`
   - Dynamic loading via `app/engine/agents/analysts/dynamic_analyst.py`

2. **Stage 2 (Research Debate)**: Bull/Bear researchers debate based on stage 1 outputs
   - Configured in `config/agents/phase2_agents_config.yaml`

3. **Stage 3 (Risk Management)**: Risk teams evaluate trading plans
   - Configured in `config/agents/phase3_agents_config.yaml`

4. **Stage 4 (Trader)**: Trader agent generates final trading decision

**Key Files**:
- `app/engine/graph/trading_graph.py` - Main workflow orchestration and LLM provider routing
- `app/engine/graph/setup.py` - Graph construction
- `app/engine/graph/propagation.py` - State propagation logic
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

### Data Layer (`app/data/`)

Unified data access with automatic fallback:

- **Interface**: `interface.py` - Public API for all data access (A-share, HK, US)
- **Data Source Manager**: `data_source_manager.py` - Multi-source management with auto-degradation
- **Providers**:
  - China: Tushare, AKShare, Baostock (in `providers/china/`)
  - US: Yahoo Finance, Finnhub (in `providers/us/`)
  - HK: HK stock providers (in `providers/hk/`)
- **Cache**: Multi-level caching (file, MongoDB, Redis) controlled by `TA_CACHE_STRATEGY`

**Usage**:
```python
from app.data.interface import get_china_stock_data_unified

data = get_china_stock_data_unified("000001", "2024-01-01", "2024-12-31")
```

### Backend API (`app/`)

FastAPI application structure:

- `main.py` - Application entry, lifespan management, APScheduler setup
- `routers/` - API route handlers (auth, analysis, config, MCP, tools, etc.)
- `services/` - Business logic (analysis, screening, sync services, quotes ingestion)
- `models/` - Database models (MongoDB with Motor)
- `core/` - Core configuration, database, logging, config bridge
- `worker/` - Background task workers (data sync, scheduled jobs)
- `middleware/` - Request/response middleware

### LLM Integration (`app/engine/llm_adapters/`)

Adapter pattern for multiple LLM providers:

- `dashscope_adapter.py` - Aliyun DashScope
- `deepseek_adapter.py` - DeepSeek with token tracking
- `openai_compatible_base.py` - OpenAI-compatible APIs (SiliconFlow, OpenRouter, Qianfan, Zhipu, custom)
- Custom adapters for Google, Anthropic, etc.

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
- `logging.toml` - Logging configuration

## Key Patterns

### Adding a New Analyst Agent

1. Define agent in `config/agents/phase1_agents_config.yaml`:
```yaml
analysts:
  - slug: "custom_analyst"
    name: "Custom Analyst"
    role: "Analyze custom metrics"
    tools:
      - "tool_name"
```

2. Implement tool in `app/engine/tools/` if needed

3. Agent is automatically loaded by `DynamicAnalystFactory`

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

- `app/` and `frontend/` are under proprietary license; other code is Apache 2.0
- Analysis requires data sync first - use the web UI or API to sync stock data
- Uses `uv.lock` for Python dependency locking
- Legacy frontend uses Vite for building and Element Plus for UI components
- React frontend uses Vite, Ant Design, Zustand, and React Router v7
- Real-time updates use SSE, WebSocket, and Redis PubSub
