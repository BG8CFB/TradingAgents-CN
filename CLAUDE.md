# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目基本信息

- **项目名称**: TradingAgents-CN (中文增强版)
- **版本**: v1.0.0-preview
- **技术栈**: Python 3.10+ / FastAPI / Vue 3 + TypeScript / MongoDB + Redis / LangGraph
- **项目类型**: 多智能体股票分析学习平台（企业级 Web 应用）
- **许可证**: 混合许可证（核心代码 Apache 2.0，app/ 和 frontend/ 目录专有）

## 常用开发命令

### 后端开发

```bash
# 安装依赖
pip install -e .

# 启动后端服务（开发模式）
python main.py

# 启动 FastAPI 后端服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 运行测试
pytest tests/

# 运行特定测试
pytest tests/integration/test_xxx.py -v
```

### 前端开发

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 类型检查
npm run type-check

# 代码检查
npm run lint

# 代码格式化
npm run format
```

### Docker 部署

```bash
# 构建并启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down

# 重新构建特定服务
docker compose build backend
docker compose up -d backend
```

## 代码架构与结构

### 顶级目录结构

```
TradingAgents-CN/
├── tradingagents/          # 核心分析引擎 (Apache 2.0 开源)
├── app/                    # FastAPI 后端服务 (企业级)
├── frontend/               # Vue 3 前端应用 (企业级)
├── config/                 # 统一配置目录 (容器挂载)
├── data/                   # 数据存储目录
├── docker/                 # Docker 容器化配置
├── tests/                  # 测试代码
├── docs/                   # 文档
├── examples/               # 示例代码
├── install/                # 安装脚本
├── logs/                   # 日志文件
├── runtime/                # 运行时数据
├── .github/                # GitHub Actions 工作流
├── main.py                 # 项目根入口 (示例)
├── pyproject.toml          # Python 项目配置
├── requirements.txt        # Python 依赖
├── docker-compose.yml      # Docker Compose 编排
├── README.md               # 项目说明
├── CLAUDE.md               # AI 开发规范
└── LICENSE                 # 许可证
```

### 项目组织原则

本项目采用**前后端分离**架构，核心分析引擎与 Web 服务分离：

- **tradingagents/**: 核心分析引擎（Apache 2.0 开源），基于 LangGraph 的多智能体工作流
- **app/**: FastAPI 后端服务（企业级功能，专有协议）
- **frontend/**: Vue 3 前端应用（企业级 UI，专有协议）
- **config/**: 统一配置目录，持久化挂载到容器

---

## 详细目录结构

### 一、核心分析引擎 (tradingagents/)

**功能**: 基于 LangGraph 的多智能体股票分析工作流引擎

```
tradingagents/
├── agents/                 # 智能体实现
│   ├── analysts/           # 阶段1: 分析师智能体
│   │   └── dynamic_analyst.py      # 动态分析师工厂 (34KB)
│   ├── stage_2/            # 阶段2: 多空辩论研究员
│   │   ├── bull_researcher.py      # 看多研究员
│   │   ├── bear_researcher.py      # 看空研究员
│   │   └── research_manager.py     # 研究经理
│   ├── stage_3/            # 阶段3: 风险控制智能体
│   │   ├── aggresive_debator.py    # 激进派
│   │   ├── conservative_debator.py # 保守派
│   │   ├── neutral_debator.py      # 中立派
│   │   └── risk_manager.py         # 风控经理
│   ├── stage_4/            # 阶段4: 交易策略智能体
│   │   ├── trader.py               # 交易员
│   │   └── summary_agent.py        # 总结智能体
│   ├── utils/              # 智能体工具函数
│   ├── phase1_agents_config.yaml       # 阶段1配置 (51KB)
│   └── stock_analysis_agents_config.yaml # 完整配置 (95KB)
├── graph/                  # LangGraph 工作流
│   ├── trading_graph.py    # 主交易图 (74KB)
│   ├── setup.py            # 图设置
│   ├── conditional_logic.py # 条件逻辑
│   ├── propagation.py      # 状态传播
│   ├── reflection.py       # 反思机制
│   └── signal_processing.py # 信号处理
├── dataflows/              # 数据流管理
│   ├── interface.py        # 统一数据接口 (80KB)
│   ├── manager.py          # 数据流管理器 (28KB)
│   ├── realtime_metrics.py # 实时指标 (22KB)
│   ├── stock_data_service.py # 股票数据服务 (12KB)
│   ├── data_completeness_checker.py # 数据完整性检查
│   ├── cache/              # 多级缓存实现
│   ├── news/               # 新闻数据流
│   ├── providers/          # 数据源适配器
│   │   ├── base_provider.py       # 基础适配器 (8KB)
│   │   ├── china/                  # 中国市场数据源
│   │   │   ├── akshare.py         # AkShare 适配器 (96KB)
│   │   │   ├── tushare.py         # Tushare 适配器 (75KB)
│   │   │   ├── baostock.py        # BaoStock 适配器 (35KB)
│   │   │   └── optimized.py       # 优化版本 (119KB)
│   │   ├── hk/                    # 港股数据源
│   │   └── us/                    # 美股数据源
│   └── technical/          # 技术指标计算
├── llm_adapters/           # LLM 统一适配器
│   ├── openai_compatible_base.py  # OpenAI 兼容基类 (23KB)
│   ├── google_openai_adapter.py   # Google Gemini 适配器 (22KB)
│   ├── dashscope_openai_adapter.py # 阿里百炼适配器 (12KB)
│   └── deepseek_adapter.py        # DeepSeek 适配器 (10KB)
├── tools/                  # 工具集合
│   ├── manager.py          # 工具管理器
│   ├── registry.py         # 工具注册表
│   ├── analysis/           # 分析工具
│   ├── local/              # 本地工具
│   └── mcp/                # MCP 工具集成
│       ├── loader.py       # MCP 加载器 (35KB)
│       ├── task_manager.py # 任务管理器
│       ├── validators.py   # 验证器
│       └── tools/          # MCP 工具实现
│           ├── finance.py  # 金融工具 (55KB)
│           └── reports.py  # 报告工具
├── mcp_server/             # MCP 工具服务器
│   ├── server.py           # MCP 服务器
│   └── tools/              # 服务器工具
├── config/                 # 配置管理
│   ├── config_manager.py   # 配置管理器 (34KB)
│   ├── mongodb_storage.py  # MongoDB 存储 (12KB)
│   ├── database_config.py  # 数据库配置
│   └── runtime_settings.py # 运行时设置
├── utils/                  # 工具函数
│   ├── logging_manager.py  # 日志管理器 (18KB)
│   ├── stock_validator.py  # 股票验证器 (64KB)
│   ├── dataflow_utils.py   # 数据流工具
│   ├── news_filter_integration.py # 新闻过滤集成
│   ├── time_utils.py       # 时间工具
│   └── tool_logging.py     # 工具日志 (16KB)
├── constants/              # 常量定义
│   └── data_sources.py     # 数据源常量
├── models/                 # 数据模型
│   └── stock_data_models.py # 股票数据模型
├── api/                    # API 接口
│   └── stock_api.py        # 股票 API (10KB)
└── default_config.py       # 默认配置
```

**关键文件说明**:

| 文件路径 | 功能描述 |
|---------|---------|
| `tradingagents/graph/trading_graph.py` | LangGraph 主工作流，定义四阶段分析流程 |
| `tradingagents/agents/analysts/dynamic_analyst.py` | 动态分析师工厂，支持配置驱动的智能体加载 |
| `tradingagents/dataflows/interface.py` | 统一数据接口，抽象多数据源访问 |
| `tradingagents/llm_adapters/openai_compatible_base.py` | LLM 适配器基类，统一多种模型接口 |
| `tradingagents/tools/mcp/finance.py` | MCP 金融工具实现 |
| `tradingagents/utils/stock_validator.py` | 股票代码验证器，支持多市场 |

---

### 二、后端服务 (app/)

**功能**: FastAPI 企业级后端，提供 REST API 和实时通知

```
app/
├── main.py                 # FastAPI 主应用 (37KB)
├── worker.py               # 后台工作进程 (9KB)
├── core/                   # 核心配置
│   ├── config.py           # 配置管理 (16KB)
│   ├── unified_config.py   # 统一配置 (18KB)
│   ├── database.py         # 数据库连接 (16KB)
│   ├── logging_config.py   # 日志配置 (18KB)
│   ├── redis_client.py     # Redis 客户端
│   ├── rate_limiter.py     # 限流器
│   ├── startup_validator.py # 启动验证
│   └── response.py         # 响应模型
├── routers/                # API 路由 (40+ 模块)
│   ├── analysis.py         # 分析任务 API (57KB)
│   ├── stocks.py           # 股票数据 API (30KB)
│   ├── stock_sync.py       # 股票同步 API (35KB)
│   ├── config.py           # 配置管理 API (91KB)
│   ├── reports.py          # 报告生成 API (29KB)
│   ├── screening.py        # 选股器 API (15KB)
│   ├── paper.py            # 模拟交易 API (22KB)
│   ├── scheduler.py        # 定时任务 API (17KB)
│   ├── news_data.py        # 新闻数据 API (17KB)
│   ├── social_media.py     # 社交媒体 API (12KB)
│   ├── sse.py              # SSE 通知 (12KB)
│   ├── websocket_notifications.py # WebSocket 通知 (11KB)
│   ├── auth_db.py          # 认证 API (18KB)
│   ├── agent_configs.py    # 智能体配置 (10KB)
│   ├── multi_market_stocks.py # 多市场股票 (10KB)
│   ├── multi_period_sync.py # 多周期同步 (14KB)
│   ├── historical_data.py  # 历史数据 API (8KB)
│   ├── tushare_init.py     # Tushare 初始化 (11KB)
│   ├── akshare_init.py     # AkShare 初始化 (12KB)
│   ├── baostock_init.py    # BaoStock 初始化 (11KB)
│   ├── internal_messages.py # 内部消息 (13KB)
│   ├── operation_logs.py   # 操作日志 (9KB)
│   ├── favorites.py        # 收藏管理 (10KB)
│   ├── multi_source_sync.py # 多源同步 (18KB)
│   ├── financial_data.py   # 财务数据 (11KB)
│   ├── prompts.py          # 提示词管理 (3KB)
│   ├── mcp.py              # MCP 工具 (9KB)
│   └── tools.py            # 工具管理 (5KB)
├── services/               # 业务逻辑服务层
│   ├── analysis_service.py # 分析服务 (83KB)
│   ├── config_service.py   # 配置服务 (195KB)
│   ├── foreign_stock_service.py # 外股服务 (75KB)
│   ├── financial_data_service.py # 财务数据服务 (20KB)
│   ├── historical_data_service.py # 历史数据服务 (20KB)
│   ├── news_data_service.py # 新闻服务 (28KB)
│   ├── social_media_service.py # 社交媒体服务 (13KB)
│   ├── stock_data_service.py # 股票数据服务 (13KB)
│   ├── unified_stock_service.py # 统一股票服务 (10KB)
│   ├── scheduler_service.py # 调度服务 (40KB)
│   ├── quotes_ingestion_service.py # 行情摄取服务 (28KB)
│   ├── basics_sync_service.py # 基本面同步 (18KB)
│   ├── multi_source_basics_sync_service.py # 多源基本面同步 (13KB)
│   ├── favorites_service.py # 收藏服务 (18KB)
│   ├── internal_message_service.py # 内部消息服务 (15KB)
│   ├── operation_log_service.py # 操作日志服务 (13KB)
│   ├── user_service.py     # 用户服务 (16KB)
│   ├── memory_state_manager.py # 记忆状态管理 (19KB)
│   ├── log_export_service.py # 日志导出服务 (19KB)
│   ├── screening_service.py # 选股服务 (10KB)
│   ├── enhanced_screening_service.py # 增强选股服务 (13KB)
│   ├── database_screening_service.py # 数据库选股服务 (23KB)
│   ├── analysis/           # 分析子服务
│   │   └── status_update_utils.py
│   ├── database/           # 数据库子服务
│   │   ├── backups.py      # 备份服务 (20KB)
│   │   ├── cleanup.py      # 清理服务
│   │   └── status_checks.py # 状态检查
│   ├── basics_sync/        # 基本面同步子服务
│   ├── data_sources/       # 数据源子服务
│   ├── progress/           # 进度跟踪子服务
│   └── queue/              # 队列子服务
├── worker/                 # 后台工作进程
│   ├── analysis_worker.py  # 分析工作进程 (10KB)
│   ├── tushare_sync_service.py # Tushare 同步 (58KB)
│   ├── akshare_sync_service.py # AkShare 同步 (51KB)
│   ├── baostock_sync_service.py # BaoStock 同步 (25KB)
│   ├── tushare_init_service.py # Tushare 初始化 (19KB)
│   ├── akshare_init_service.py # AkShare 初始化 (19KB)
│   ├── baostock_init_service.py # BaoStock 初始化 (16KB)
│   ├── hk_sync_service.py  # 港股同步 (20KB)
│   ├── hk_data_service.py  # 港股数据 (7KB)
│   ├── us_sync_service.py  # 美股同步 (16KB)
│   ├── us_data_service.py  # 美股数据 (7KB)
│   ├── multi_period_sync_service.py # 多周期同步 (14KB)
│   ├── news_data_sync_service.py # 新闻数据同步 (21KB)
│   ├── example_sdk_sync_service.py # 示例 SDK 同步 (14KB)
│   └── financial_data_sync_service.py # 财务数据同步 (12KB)
├── models/                 # MongoDB 数据模型
│   ├── analysis.py         # 分析模型
│   ├── config.py           # 配置模型
│   ├── stock_models.py     # 股票模型 (10KB)
│   ├── screening.py        # 选股模型
│   ├── user.py             # 用户模型
│   ├── operation_log.py    # 操作日志模型
│   └── notification.py     # 通知模型
├── schemas/                # Pydantic 请求/响应模式
├── middleware/             # 中间件
│   ├── operation_log_middleware.py # 操作日志中间件
│   ├── rate_limit.py       # 限流中间件
│   ├── error_handler.py    # 错误处理中间件
│   └── request_id.py       # 请求 ID 中间件
├── constants/              # 常量定义
│   └── model_capabilities.py # 模型能力 (20KB)
├── utils/                  # 工具函数
│   ├── timezone.py         # 时区工具
│   ├── error_formatter.py  # 错误格式化 (18KB)
│   ├── report_exporter.py  # 报告导出 (21KB)
│   └── api_key_utils.py    # API 密钥工具
└── scripts/                # 脚本工具
```

**关键文件说明**:

| 文件路径 | 功能描述 |
|---------|---------|
| [app/main.py](app/main.py) | FastAPI 主应用入口，包含所有路由注册和生命周期管理 |
| [app/core/config.py](app/core/config.py) | 配置管理，支持环境变量和配置文件 |
| [app/services/analysis_service.py](app/services/analysis_service.py) | 分析任务核心服务，协调多智能体工作流 |
| [app/services/config_service.py](app/services/config_service.py) | 配置服务，管理运行时配置 |
| [app/routers/analysis.py](app/routers/analysis.py) | 分析任务 API 端点 |
| [app/constants/model_capabilities.py](app/constants/model_capabilities.py) | LLM 模型能力声明 |

---

### 三、前端应用 (frontend/)

**功能**: Vue 3 + TypeScript 单页应用，提供用户界面

```
frontend/
├── src/
│   ├── main.ts             # 应用入口
│   ├── App.vue             # 根组件
│   ├── views/              # 页面视图组件
│   │   ├── Dashboard/      # 仪表板页面
│   │   ├── Analysis/       # 分析页面
│   │   ├── Stocks/         # 股票页面
│   │   ├── Screening/      # 选股页面
│   │   ├── PaperTrading/   # 模拟交易页面
│   │   ├── Queue/          # 任务队列页面
│   │   ├── Reports/        # 报告页面
│   │   ├── Settings/       # 设置页面
│   │   ├── System/         # 系统页面
│   │   ├── Tasks/          # 任务页面
│   │   ├── Favorites/      # 收藏页面
│   │   ├── Learning/       # 学习页面
│   │   ├── About/          # 关于页面
│   │   ├── Auth/           # 认证页面
│   │   └── Error/          # 错误页面
│   ├── components/         # 可复用组件
│   │   ├── Layout/         # 布局组件
│   │   ├── Dashboard/      # 仪表板组件
│   │   ├── Settings/       # 设置组件
│   │   ├── Sync/           # 同步组件
│   │   ├── Dev/            # 开发组件
│   │   ├── Global/         # 全局组件
│   │   ├── ConfigValidator.vue # 配置验证器 (20KB)
│   │   ├── ConfigWizard.vue    # 配置向导 (18KB)
│   │   ├── ModelConfig.vue     # 模型配置 (12KB)
│   │   └── NetworkStatus.vue   # 网络状态
│   ├── layouts/            # 布局模板
│   ├── router/             # Vue Router 配置
│   │   └── index.ts        # 路由定义 (12KB)
│   ├── stores/             # Pinia 状态管理
│   │   ├── app.ts          # 应用状态
│   │   ├── auth.ts         # 认证状态 (15KB)
│   │   ├── notifications.ts # 通知状态
│   │   └── mcp.ts          # MCP 状态
│   ├── api/                # API 客户端封装
│   │   ├── request.ts      # HTTP 请求封装 (19KB)
│   │   ├── analysis.ts     # 分析 API (13KB)
│   │   ├── config.ts       # 配置 API (19KB)
│   │   ├── stocks.ts       # 股票 API
│   │   ├── screening.ts    # 选股 API
│   │   ├── reports.ts      # 报告 API
│   │   ├── auth.ts         # 认证 API
│   │   ├── sync.ts         # 同步 API (5KB)
│   │   ├── scheduler.ts    # 调度 API
│   │   ├── operationLogs.ts # 操作日志 API (7KB)
│   │   └── ...             # 其他 API 模块
│   ├── types/              # TypeScript 类型定义
│   │   ├── analysis.ts     # 分析类型 (13KB)
│   │   ├── config.ts       # 配置类型
│   │   ├── agents.ts       # 智能体类型
│   │   ├── auth.ts         # 认证类型
│   │   └── ...             # 其他类型
│   ├── constants/          # 常量定义
│   ├── utils/              # 工具函数
│   └── styles/             # 样式文件
├── public/                 # 静态资源
├── package.json            # 依赖配置
├── vite.config.ts          # Vite 配置
├── tsconfig.json           # TypeScript 配置
└── README.md               # 前端说明
```

**关键文件说明**:

| 文件路径 | 功能描述 |
|---------|---------|
| [frontend/src/router/index.ts](frontend/src/router/index.ts) | 路由配置，定义所有页面路由 |
| [frontend/src/api/request.ts](frontend/src/api/request.ts) | HTTP 请求封装，基于 Axios |
| [frontend/src/stores/auth.ts](frontend/src/stores/auth.ts) | 认证状态管理，JWT Token 处理 |
| [frontend/src/types/analysis.ts](frontend/src/types/analysis.ts) | 分析相关 TypeScript 类型定义 |

---

### 四、配置目录 (config/)

**功能**: 统一配置管理，挂载到 Docker 容器

```
config/
├── agents/                 # 智能体配置
│   ├── phase1_agents_config.yaml       # 阶段1分析师配置 (51KB)
│   └── stock_analysis_agents_config.yaml # 完整智能体配置 (97KB)
├── models.json             # LLM 模型配置 (1KB)
├── pricing.json            # 模型定价配置 (3KB)
├── settings.json           # 系统设置 (2KB)
├── mcp.json                # MCP 工具配置 (272B)
├── logging.toml            # 日志配置
├── logging_docker.toml     # Docker 日志配置
└── README.md               # 配置说明
```

**关键文件说明**:

| 文件路径 | 功能描述 |
|---------|---------|
| [config/agents/phase1_agents_config.yaml](config/agents/phase1_agents_config.yaml) | 阶段1分析师智能体配置，包含所有分析师的提示词和参数 |
| [config/models.json](config/models.json) | LLM 模型配置，定义支持的模型供应商 |
| [config/pricing.json](config/pricing.json) | 模型定价信息，用于成本计算 |

---

### 五、Docker 容器化 (docker/)

**功能**: Docker 多容器部署配置

```
docker/
├── Dockerfile.backend      # 后端容器镜像 (4KB)
├── Dockerfile.frontend     # 前端容器镜像 (2KB)
├── mongo-init.js           # MongoDB 初始化脚本
└── nginx/                  # Nginx 反向代理配置
    ├── frontend.conf       # 前端路由配置
    └── reverse-proxy.conf  # 反向代理配置 (3KB)
```

**关键文件说明**:

| 文件路径 | 功能描述 |
|---------|---------|
| [docker/Dockerfile.backend](docker/Dockerfile.backend) | 后端 Python 应用容器镜像 |
| [docker/Dockerfile.frontend](docker/Dockerfile.frontend) | 前端 Node.js 应用容器镜像 |
| [docker/nginx/reverse-proxy.conf](docker/nginx/reverse-proxy.conf) | Nginx 反向代理配置，统一后端 API 路由 |

---

### 六、测试目录 (tests/)

**功能**: 集成测试和单元测试

```
tests/
├── integration/            # 集成测试
│   ├── test_mcp_integration.py    # MCP 集成测试
│   └── test_subgraph_architecture.py # 子图架构测试
└── mcp/                    # MCP 工具测试
    └── test_basic.py       # MCP 基础测试
```

---

### 七、数据目录 (data/)

**功能**: 数据存储和缓存

```
data/
├── analysis_results/       # 分析结果存储
├── cache/                  # 本地缓存
├── reports/                # 报告生成
└── scripts/                # 数据脚本
```

---

### 八、其他目录

```
TradingAgents-CN/
├── docs/                   # 文档资源
├── examples/               # 示例代码
│   └── mcp/                # MCP 工具示例
├── install/                # 安装脚本
├── logs/                   # 运行日志
├── runtime/                # 运行时数据
│   ├── cache/              # 运行时缓存
│   ├── data/               # 运行时数据
│   ├── logs/               # 运行时日志
│   └── results/            # 运行时结果
├── .github/                # GitHub Actions 工作流
│   └── workflows/          # CI/CD 配置
└── .streamlit/             # Streamlit 配置 (遗留)
```

---

## 核心架构概述

### 多智能体工作流 (四阶段)

基于 LangGraph 构建的四阶段多智能体工作流：

1. **阶段 1 (分析师)**: 各领域分析师并行/串行工作
   - 财经新闻分析、中国市场技术分析、市场技术分析、社交媒体情绪分析、基本面分析、短线资金流向分析
   - 位置: `tradingagents/agents/analysts/`

2. **阶段 2 (研究辩论)**: 多空博弈
   - 看多研究员 vs 看空研究员多轮辩论
   - 位置: `tradingagents/agents/stage_2/`

3. **阶段 4 (交易策略)**: 制定交易计划
   - 交易员综合多空观点，制定具体交易计划
   - 位置: `tradingagents/agents/stage_4/`

4. **阶段 3 (风险控制)**: 风险评估
   - 激进派、保守派、中立派讨论，风控经理最终决策
   - 位置: `tradingagents/agents/stage_3/`

### 数据流架构

**多级缓存系统**:
1. 文件缓存（本地数据）
2. 数据库缓存（MongoDB）
3. Redis 缓存（会话和实时数据）

**数据源适配器** (tradingagents/dataflows/providers/):
- **中国股市**: AkShare（免费）、Tushare（需 token）、BaoStock（免费）
- **国际市场**: yFinance（美股）、Finnhub（美股实时）、EODHD（国际市场）
- **新闻数据**: Google News、Reddit (r/wallstreetbets)、中文财经网站

### LLM 适配器架构

统一适配多种 LLM 提供商，基类位于 `tradingagents/llm_adapters/openai_compatible_base.py`：

- OpenAI GPT 系列
- Google Gemini
- DeepSeek
- 阿里百炼 (DashScope)
- SiliconFlow
- OpenRouter

配置文件: `config/models.json`, `config/pricing.json`

## 开发规则（必须遵守）

### 1. 多智能体工作流开发

- **禁止**直接修改已定义的阶段顺序（Phase 1 → Phase 2 → Phase 4 → Phase 3）
- 新增分析师需在 `tradingagents/agents/analysts/` 创建，并在 `config/agents/phase1_agents_config.yaml` 注册
- 所有智能体必须继承 `DynamicAnalystBase` 基类
- 智能体工具调用需通过 MCP 工具服务器（`tradingagents/mcp_server/`）

### 2. 数据源开发

- 新增数据源需在 `tradingagents/dataflows/providers/` 创建适配器
- 必须实现统一的数据接口（返回标准化的 DataFrame）
- 添加数据源后需在配置文件中启用并在数据库同步
- 优先使用缓存，避免重复请求外部 API

### 3. LLM 模型配置

- 新增 LLM 供应商需在 `tradingagents/llm_adapters/` 创建适配器
- 在 `config/models.json` 注册模型配置
- 在 `config/pricing.json` 添加定价信息
- 确保模型能力声明与实际能力一致（见 `app/constants/model_capabilities.py`）

### 4. 前后端交互

- 前端通过 `/api` 前缀调用后端 API（Nginx 代理配置）
- 实时通知优先使用 SSE（`/api/sse/`），WebSocket 作为备选
- 认证使用 JWT Token，存放在 localStorage
- 所有 API 响应遵循统一的 JSON 格式

### 5. 数据库操作

- 使用 Motor（异步 MongoDB 驱动）
- 所有数据模型定义在 `app/models/`
- 禁止在业务逻辑中直接拼接查询语句，使用模型方法
- Redis 用于会话管理和缓存，MongoDB 用于持久化存储

### 6. 配置管理

- **持久化配置**: `config/` 目录挂载到容器，需重启服务生效
  - `models.json`: LLM 模型配置
  - `mcp.json`: MCP 工具服务器配置
  - `agents/`: 智能体配置
  - `settings.json`: 系统设置
- **环境变量**: `.env` 文件，包含敏感信息（API Key、数据库密码）
- **运行时配置**: 通过 Web 界面修改，存放在数据库

### 7. 日志规范

- 使用 Python `logging` 模块，配置在 `config/logging.toml`
- 日志文件存放在 `logs/` 目录
- **重要**: LLM 调用、外部 API 请求、数据库操作必须记录日志
- 错误日志必须包含完整的堆栈信息和上下文

### 8. 时区处理规范（强制）

**核心原则**:
1. **禁止使用 naive datetime**: 所有 datetime 对象必须带时区信息（timezone-aware）
2. **统一工具库**: 使用 `tradingagents.utils.time_utils` 提供的函数
3. **存储标准**: 数据库存储使用 UTC 时区
4. **显示标准**: 前端显示使用配置时区（Asia/Shanghai）

**允许的函数**:
- ✅ `now_utc()` - 获取当前UTC时间（aware）
- ✅ `now_config_tz()` - 获取配置时区时间（aware）
- ✅ `parse_date_aware(date_str)` - 解析日期字符串为aware datetime
- ✅ `fromtimestamp_aware(ts)` - 从时间戳创建aware datetime
- ✅ `ensure_tz(dt)` - 确保datetime带时区信息

**禁止的函数**:
- ❌ `datetime.strptime()` - 使用 `parse_date_aware()` 代替
- ❌ `datetime.fromtimestamp()` - 使用 `fromtimestamp_aware()` 代替
- ❌ `datetime.now()` - 使用 `now_utc()` 或 `now_config_tz()` 代替
- ❌ `datetime.utcnow()` - 使用 `now_utc()` 代替

**示例代码**:

❌ **错误示例**:
```python
# 错误：创建naive datetime
dt = datetime.strptime("2024-01-01", "%Y-%m-%d")
ts_datetime = datetime.fromtimestamp(1704067200.0)

# 错误：naive与aware比较或运算
if dt < now_utc():
    pass
delta = aware_dt - dt  # TypeError!
```

✅ **正确示例**:
```python
from tradingagents.utils.time_utils import parse_date_aware, fromtimestamp_aware, now_utc

# 正确：创建aware datetime
dt = parse_date_aware("2024-01-01", to_config_tz=False)  # UTC
ts_datetime = fromtimestamp_aware(1704067200.0)  # 自动转换到配置时区

# 正确：aware与aware比较和运算
if dt < now_utc():
    pass
delta = aware_dt - dt  # ✅ 正常工作
```

**为什么有这个规范**:
- Python 3.6+ 严格禁止 naive 和 aware datetime 之间的比较和运算
- 混用时区会导致 `TypeError: can't compare/subtract offset-naive and offset-aware datetimes`
- 统一使用 aware datetime 可以避免时区相关的隐蔽错误
- 数据库统一使用 UTC 存储便于跨时区协作
- 日志文件存放在 `logs/` 目录
- **重要**: LLM 调用、外部 API 请求、数据库操作必须记录日志
- 错误日志必须包含完整的堆栈信息和上下文

### 8. Docker 容器化

- 所有服务通过 `docker-compose.yml` 编排
- 数据持久化通过 volumes 映射
- 配置文件挂载到容器（`./config:/app/config`）
- 容器内时区统一为 `Asia/Shanghai`

## 架构约定

### 通信模式

1. **同步请求**: HTTP RESTful API（FastAPI）
2. **异步通知**: SSE（Server-Sent Events）+ WebSocket 双通道
3. **后台任务**: APScheduler 定时任务 + 队列系统

### 权限与认证

- JWT Token 认证，有效期 480 分钟（8 小时）
- 角色管理：Admin、User、Guest
- 所有需要认证的接口需通过 `app/api/dependencies.py` 的依赖注入

### 错误处理

- 统一异常处理：`app/core/exceptions.py`
- 错误响应格式：`{"error": "错误信息", "detail": "详细描述"}`
- 所有异常必须记录日志

### 多市场支持

- **A股**: Tushare、AkShare、BaoStock
- **港股**: AkShare
- **美股**: yFinance、Finnhub
- 市场选择通过股票代码前缀自动识别（SH/SZ、HK、US）

### 报告生成

- 支持 Markdown、Word、PDF 三种格式
- 报告模板存放在 `data/reports/`
- 使用 `python-docx` 修复中文 Word 文档方向问题
- PDF 生成需要安装 `wkhtmltopdf`

## 历史决策记录

1. **架构升级 (v1.0.0-preview)**: 从 Chainlit 迁移到 FastAPI + Vue 3，实现前后端分离和企业级功能
2. **双数据库架构**: MongoDB（持久化）+ Redis（缓存），提升性能和可扩展性
3. **MCP 工具服务器**: 集成 LangChain MCP 适配器，统一金融工具管理
4. **多模型支持**: 动态添加 LLM 供应商，根据任务自动匹配最佳模型
5. **中文本地化**: 全中文界面、A 股特色分析（涨跌停、T+1）、国产大模型集成
6. **Docker 部署**: 完善 Docker 支持，兼容 amd64/arm64 架构
