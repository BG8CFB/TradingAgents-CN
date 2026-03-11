# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TradingAgents-CN** is a Chinese stock analysis platform using a multi-agent AI system built with LangGraph. It consists of:

- **Backend API**: FastAPI (`app/`) - Web server, database management, real-time notifications
- **Frontend**: Vue 3 + Element Plus (`frontend/`) - Modern SPA UI
- **Core Engine**: LangGraph multi-agent system (`tradingagents/`) - Analysis workflow
- **Data Layer**: Multi-source stock data with MongoDB + Redis caching

## Common Commands

### Development Setup

```bash
# Install Python dependencies (requires Python 3.10+)
pip install -r requirements.txt
# or using uv
uv sync

# Install frontend dependencies
cd frontend && npm install

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

# Start frontend (in frontend/ directory)
cd frontend
npm run dev          # Development server
npm run build        # Production build
npm run type-check   # TypeScript check
npm run lint         # ESLint
```

### Docker Deployment

```bash
# Full stack with Docker Compose (includes MongoDB, Redis, Nginx)
docker-compose -f docker-compose.build.yml up -d

# Access: http://localhost:3000 (Nginx proxy)
# API: http://localhost:8000/api
```

### Running Tests

```bash
# Run pytest
python -m pytest tests/

# Run specific test file
python -m pytest tests/integration/test_subgraph_architecture.py

# Run MCP tests
python -m pytest tests/mcp/test_basic.py
```

## Architecture Overview

### Multi-Agent Workflow (tradingagents/)

The core analysis engine uses **LangGraph** with a 4-stage pipeline:

1. **Stage 1 (Analysts)**: Vertical analysts (market, news, fundamentals, etc.) run in parallel
   - Configured in `config/agents/phase1_agents_config.yaml`
   - Dynamic loading via `tradingagents/agents/analysts/dynamic_analyst.py`

2. **Stage 2 (Research Debate)**: Bull/Bear researchers debate based on stage 1 outputs
   - Configured in `config/agents/phase2_agents_config.yaml`

3. **Stage 3 (Risk Management)**: Risk teams evaluate trading plans
   - Configured in `config/agents/phase3_agents_config.yaml`

4. **Stage 4 (Trader)**: Trader agent generates final trading decision

**Key Files**:
- `tradingagents/graph/trading_graph.py` - Main workflow orchestration
- `tradingagents/graph/setup.py` - Graph construction
- `tradingagents/graph/propagation.py` - State propagation logic
- `tradingagents/default_config.py` - Default configuration

### Data Layer (tradingagents/dataflows/)

Unified data access with automatic fallback:

- **Interface**: `interface.py` - Public API for all data access
- **Data Source Manager**: `data_source_manager.py` - Multi-source management with auto-degradation
- **Providers**:
  - China: Tushare, AKShare, Baostock (in `providers/china/`)
  - US: Yahoo Finance, Finnhub (in `providers/us/`)
  - HK: HK stock providers (in `providers/hk/`)
- **Cache**: Multi-level caching (file, MongoDB, Redis) in `cache/`

**Usage**:
```python
from tradingagents.dataflows.interface import get_china_stock_data_unified

data = get_china_stock_data_unified("000001", "2024-01-01", "2024-12-31")
```

### Backend API (app/)

FastAPI application structure:

- `main.py` - Application entry, lifespan management
- `routers/` - API route handlers (auth, analysis, config, etc.)
- `services/` - Business logic (analysis, screening, sync services)
- `models/` - Database models (MongoDB with Motor)
- `core/` - Core configuration, database, logging
- `worker/` - Background task workers (data sync, scheduled jobs)
- `middleware/` - Request/response middleware

### LLM Integration (tradingagents/llm_adapters/)

Adapter pattern for multiple LLM providers:

- `dashscope_adapter.py` - Aliyun DashScope
- `deepseek_adapter.py` - DeepSeek
- `openai_compatible_base.py` - OpenAI-compatible APIs
- Custom adapters for Google, etc.

Configuration via database or environment variables in `.env`.

### MCP Server (tradingagents/mcp_server/)

Model Context Protocol tools for agent data access:

- `server.py` - MCP server implementation
- `tools/` - Tool definitions for stock data, news, etc.

## Configuration

### Environment Variables (.env)

Required for startup:
- `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_USERNAME`, `MONGODB_PASSWORD` - Database
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` - Cache
- `JWT_SECRET`, `CSRF_SECRET` - Security

Optional for AI features:
- `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `GOOGLE_API_KEY` - LLM providers
- `TUSHARE_TOKEN` - Professional A-share data

### Runtime Configuration (config/)

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

2. Implement tool in `tradingagents/tools/` if needed

3. Agent is automatically loaded by `DynamicAnalystFactory`

### Data Source Fallback

The system automatically degrades data sources when one fails:
- China stocks: MongoDB → Tushare → AKShare → Baostock
- Configured in `data_source_manager.py`

### Running Analysis Programmatically

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.agents.analysts.dynamic_analyst import DynamicAnalystFactory

# Get configured analysts
selected_analysts = [a.get("slug") for a in DynamicAnalystFactory.get_all_agents() if a.get("slug")]

# Initialize graph
ta = TradingAgentsGraph(selected_analysts=selected_analysts, debug=True)

# Run analysis
_, decision = ta.propagate("000001", "2024-12-31")
```

## Important Notes

- **app/** and **frontend/** are under proprietary license; other code is Apache 2.0
- Analysis requires data sync first - use the web UI or API to sync stock data
- Uses `uv.lock` for Python dependency locking
- Frontend uses Vite for building and Element Plus for UI components
- Real-time updates use SSE (Server-Sent Events) and WebSocket
