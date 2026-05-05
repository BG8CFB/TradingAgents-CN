# 测试文档

> 生成日期: 2026-05-04 | 总测试数: 845+ (非AI: 829) | 通过率: 100%

---

## 快速测试命令

```bash
# 运行全部测试（不含 AI 调用）
python -m pytest tests/ -v -m "not ai" --tb=short

# 运行全部测试（含 AI 调用，需要网络）
python -m pytest tests/ -v --tb=short

# 仅运行 AI 集成测试（MiniMax 实际调用）
python -m pytest tests/ai_integration/ -v -s

# 按功能点运行
python -m pytest tests/features/ -v                        # 功能点测试
python -m pytest tests/core/ -v                            # 核心模块测试
python -m pytest tests/auth/ -v                            # 认证模块测试
python -m pytest tests/engine/ -v                          # 引擎组件测试
python -m pytest tests/models/ -v                          # 数据模型测试
python -m pytest tests/routers/ -v                         # 路由和中间件测试
python -m pytest tests/integration/ -v                     # 集成测试

# 跳过慢速测试
python -m pytest tests/ -v -m "not slow and not ai"

# 运行指定关键字的测试
python -m pytest tests/ -v -k "test_login"
python -m pytest tests/ -v -k "test_minimax"
python -m pytest tests/ -v -k "TestLLMActualCalls"

# 查看测试覆盖率
python -m pytest tests/ --cov=app --cov-report=term-missing
```

---

## 测试目录结构

```
tests/
├── conftest.py                      # 全局 fixtures（数据库 mock、认证 token、测试客户端）
├── README.md                        # 本文档
│
├── core/                            # 核心基础设施模块测试
│   ├── test_core_config.py          # Settings 配置类：默认值、MONGO_URI、REDIS_URL、安全检查
│   ├── test_core_response.py        # API 响应格式：ok()/fail() 信封、safe_error_message 防泄露
│   ├── test_core_rate_limiter.py    # 速率限制器：滑动窗口算法、Tushare/AKShare/BaoStock 三级限制
│   ├── test_core_database.py        # 数据库管理器：初始化、健康检查、连接关闭、未初始化异常
│   ├── test_core_startup_validator.py # 启动验证：必需/推荐配置检测、安全默认值检测
│   └── test_core_logging_context.py # 日志上下文：trace_id ContextVar、LoggingContextFilter
│
├── auth/                            # 认证与用户模块测试
│   ├── test_auth_service.py         # JWT 服务：Token 创建/验证、过期处理、自定义过期时间
│   ├── test_user_service.py         # 用户服务：CRUD、认证、密码管理、管理员创建（mock DB）
│   └── test_password_utils.py       # 密码工具：bcrypt 哈希、SHA256 兼容、重哈希检测
│
├── analysis/                        # 分析服务模块测试
│   ├── test_analysis_service.py     # 分析服务：任务创建、状态查询、列表过滤、股票搜索
│   └── test_health_api.py           # 健康检查 API：/health、/healthz、/readyz 三个探针
│
├── engine/                          # 多智能体引擎组件测试
│   ├── test_engine_agent_states.py  # Agent 状态：AgentState/InvestDebateState/RiskDebateState 字段与 reducer
│   ├── test_engine_conditional_logic.py # 条件路由：辩论轮次、Bull/Bear 交替、风险讨论循环
│   ├── test_engine_default_config.py # 默认配置：必需键、值类型、路径解析、工具开关
│   └── test_engine_tool_registry.py # 工具注册表：单例模式、初始化守卫、工具禁用
│
├── models/                          # 数据模型验证测试
│   ├── test_models_user.py          # 用户模型：UserCreate/UserUpdate/UserResponse/PyObjectId
│   ├── test_models_analysis.py      # 分析模型：AnalysisStatus/BatchStatus/AnalysisTask/请求验证
│   ├── test_models_screening.py     # 筛选模型：OperatorType/FieldType/ScreeningCondition
│   ├── test_models_config.py        # 配置模型：LLMProvider/LLMConfig/DataSourceConfig/SystemConfig
│   ├── test_models_operation_log.py # 操作日志模型：ActionType/OperationLogCreate/OperationLogResponse
│   ├── test_models_notification.py  # 通知模型：NotificationType/NotificationCreate/NotificationOut
│   └── test_models_stock.py         # 股票模型：StockBasicInfoExtended/MarketQuotesExtended/MarketType
│
├── routers/                         # 路由与中间件测试
│   ├── test_middleware.py           # 请求中间件：RequestID/RateLimit/OperationLog
│   ├── test_tools.py                # MCP 工具路由：工具数据结构、端点定义
│   └── utils/test_utils.py         # 工具函数：stock_utils/time_utils/symbol/stock_validator
│
├── features/                        # 按功能点组织的 API 端到端测试
│   ├── test_auth_and_user.py        # 功能点：认证登录/注册/刷新/用户信息/健康检查
│   └── test_analysis_tasks.py       # 功能点：分析任务提交/查询/状态/搜索/统计
│
├── ai_integration/                  # AI 模型实际调用集成测试（需要网络和 API Key）
│   └── test_llm_minimax.py         # MiniMax LLM：适配器初始化/实际对话/工具调用/多轮对话/错误处理
│
├── integration/                     # 架构集成测试
│   └── test_subgraph_architecture.py # 图架构：DynamicAnalystFactory/ProgressManager/GraphSetup
│
├── lint/                            # 代码规范检查测试
│   └── test_router_conventions.py   # 路由规范：API 前缀、英文标签、无直接 MongoDB 调用
│
└── mcp/                             # MCP 协议模块测试
    └── test_basic.py                # MCP 配置：MCPServerConfig/加载器/任务管理器/健康监控
```

---

## 各文件详细说明

### core/ - 核心基础设施（135 个测试）

| 文件 | 测试数 | 覆盖的源文件 | 测试要点 |
|------|--------|-------------|---------|
| test_core_config.py | 28 | app/core/config.py | Settings 默认值、MONGO_URI 构建（有/无认证）、REDIS_URL 构建、is_production 属性、runtime_dir 解析 |
| test_core_response.py | 23 | app/core/response.py | ok() 返回结构验证、fail() 错误码验证、safe_error_message 开发/生产模式区分 |
| test_core_rate_limiter.py | 31 | app/core/rate_limiter.py | 滑动窗口限流算法、Tushare 积分等级映射、安全边际计算、未知等级回退、全局单例重置 |
| test_core_database.py | 22 | app/core/database.py | DatabaseManager 初始化/健康检查/关闭连接、get_mongo_db/get_redis_client 未初始化异常 |
| test_core_startup_validator.py | 22 | app/core/startup_validator.py | ConfigItem/ValidationResult 模型、必需/推荐配置检测、端口范围验证、JWT 长度检查 |
| test_core_logging_context.py | 10 | app/core/logging_context.py | trace_id_var 默认值/设置/获取、LoggingContextFilter 注入与异常处理 |

### auth/ - 认证与用户管理（104 个测试）

| 文件 | 测试数 | 覆盖的源文件 | 测试要点 |
|------|--------|-------------|---------|
| test_auth_service.py | 22 | app/services/auth_service.py | JWT Token 创建（默认/自定义分钟/秒）、验证（有效/过期/无效）、TokenData 模型 |
| test_user_service.py | 46 | app/services/user_service.py | 用户创建/认证/查询/更新/禁用/激活/密码管理/管理员创建（mock MongoDB） |
| test_password_utils.py | 36 | app/utils/passwords.py | bcrypt 哈希生成/验证、SHA256 兼容、重哈希检测、前缀识别 |

### analysis/ - 分析服务（33 个测试）

| 文件 | 测试数 | 覆盖的源文件 | 测试要点 |
|------|--------|-------------|---------|
| test_analysis_service.py | 19 | app/services/analysis_service.py | 任务创建、状态查询、用户任务过滤、股票搜索、热门股票、标记失败/删除 |
| test_health_api.py | 14 | app/routers/health.py | /health 端点结构、/healthz 存活探针、/readyz 就绪探针、get_version 函数 |

### engine/ - 多智能体引擎（110 个测试）

| 文件 | 测试数 | 覆盖的源文件 | 测试要点 |
|------|--------|-------------|---------|
| test_engine_agent_states.py | 33 | app/engine/agents/utils/agent_states.py | AgentState/InvestDebateState/RiskDebateState 所有字段、update_reports reducer 合并逻辑 |
| test_engine_conditional_logic.py | 22 | app/engine/graph/conditional_logic.py | 辩论路由（Bull/Bear 交替、最大轮次）、风险讨论路由（Risky/Safe/Neutral） |
| test_engine_default_config.py | 29 | app/engine/default_config.py | DEFAULT_CONFIG 必需键、值类型、路径解析、工具开关（环境变量控制） |
| test_engine_tool_registry.py | 26 | app/engine/tools/registry.py | ToolRegistry 单例模式（线程安全）、初始化守卫、工具注册/查找/禁用 |

### models/ - 数据模型（247 个测试）

| 文件 | 测试数 | 覆盖的源文件 | 测试要点 |
|------|--------|-------------|---------|
| test_models_user.py | 40 | app/models/user.py | UserCreate/UserUpdate/UserResponse/UserPreferences/FavoriteStock/PyObjectId |
| test_models_analysis.py | 39 | app/models/analysis.py | AnalysisStatus/BatchStatus/AnalysisTask/SingleAnalysisRequest/BatchAnalysisRequest |
| test_models_config.py | 42 | app/models/config.py | LLMProvider/LLMConfig/DataSourceConfig/SystemConfig/DatabaseConfig/MarketCategory |
| test_models_screening.py | 37 | app/models/screening.py | OperatorType/FieldType/ScreeningCondition/ScreeningRequest/BASIC_FIELDS_INFO |
| test_models_stock.py | 39 | app/models/stock_models.py | StockBasicInfoExtended/MarketQuotesExtended/MarketType/ExchangeType/StockStatus |
| test_models_operation_log.py | 27 | app/models/operation_log.py | ActionType/OperationLogCreate/OperationLogResponse/ClearLogsRequest |
| test_models_notification.py | 23 | app/models/notification.py | NotificationType/NotificationStatus/NotificationCreate/NotificationDB |

### routers/ - 路由与中间件（150 个测试）

| 文件 | 测试数 | 覆盖的源文件 | 测试要点 |
|------|--------|-------------|---------|
| test_middleware.py | 32 | app/middleware/*.py | RequestID UUID 生成/响应头、RateLimit Redis 降级、OperationLog 路径跳过/操作映射 |
| test_tools.py | 11 | app/routers/tools.py | MCP 工具数据结构完整性、名称唯一性、路由端点路径验证 |
| utils/test_utils.py | 107 | app/utils/*.py | 股票代码解析/市场检测、时区时间处理、Symbol 规范化、股票代码验证 |

### features/ - 按功能点的端到端测试（23 个测试）

| 文件 | 测试数 | 覆盖的 API 端点 | 测试要点 |
|------|--------|-----------------|---------|
| test_auth_and_user.py | 16 | POST /api/auth/login, /register, /refresh; GET /api/auth/me, /health, /healthz, /readyz | 登录成功/失败/空字段、注册验证/重复/短密码、Token 刷新/无效/空、用户信息、健康检查三探针 |
| test_analysis_tasks.py | 7 | POST /api/analysis/single; GET /api/analysis/tasks, /tasks/all, /tasks/{id}/status, /search, /stats | 任务提交、用户/全部任务列表、任务状态、股票搜索、分析统计 |

### ai_integration/ - AI 模型实际调用测试（需要网络，16 个测试）

| 文件 | 测试数 | 覆盖的源文件 | 测试要点 |
|------|--------|-------------|---------|
| test_llm_minimax.py | 16 | app/engine/llm_adapters/*.py + app/engine/graph/trading_graph.py | MiniMax API 初始化（ChatOpenAI/OpenAICompatibleBase/create_llm_by_provider）、基本对话、系统提示对话、同步/异步调用、JSON 输出、工具调用、多轮对话、条件逻辑处理、Agent 状态承载、提示构建、错误处理（无效 Key/超时/空模型）、Token 统计 |

---

## 测试分类标签

```python
# pytest markers 定义在 conftest.py 中
@pytest.mark.asyncio     # 异步测试
@pytest.mark.ai          # AI 集成测试（需要网络和 API Key）
@pytest.mark.slow        # 慢速测试
@pytest.mark.integration # 集成测试
```

---

## AI 集成测试说明

AI 测试使用 MiniMax API 进行真实调用：

| 配置项 | 值 |
|--------|---|
| API Base | https://api.minimaxi.com/v1 |
| Model | MiniMax-M2.7 |
| Context Window | 200,000 |
| Max Tokens | 131,072 |

运行 AI 测试前确保网络可用。跳过 AI 测试：`python -m pytest tests/ -m "not ai"`

---

## 二次快速测试

```bash
# 最快：只跑核心 + 认证（无网络依赖，约 30 秒）
python -m pytest tests/core/ tests/auth/ -q

# 快速：核心 + 认证 + 模型（约 60 秒）
python -m pytest tests/core/ tests/auth/ tests/models/ -q

# 中等：全部非 AI 测试，829 个（约 6 分钟）
python -m pytest tests/ -m "not ai" -q

# 完整：含 AI 调用（约 10 分钟，需要网络）
python -m pytest tests/ -q

# 按功能点快速验证
python -m pytest tests/features/ -v
```
