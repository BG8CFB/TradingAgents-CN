# TradingAgents-CN

> 社区维护版 | 由 [BG8CFB](https://github.com/BG8CFB) 二次开发与持续维护

> **免责声明**: 本项目仅供学习与研究使用，不构成任何投资建议。所有策略和数据均为模拟，不涉及真实交易。使用者需自行承担风险。

---

## 项目简介

**TradingAgents-CN** 是一个面向中文市场的**多智能体 AI 股票分析平台**，基于 LangGraph 构建 4 阶段协作式分析流水线，模拟真实投研团队的研究决策流程。

- 多空辩论机制 — 看多/看空研究员多轮对抗，模拟真实投研团队博弈
- 多市场覆盖 — A股 / 港股 / 美股，支持 Tushare、AKShare、BaoStock 等数据源
- 多模型适配 — DeepSeek、通义千问、SiliconFlow、OpenRouter、Google Gemini、百度千帆、Anthropic 等
- 全中文投研框架 — A股特有指标（北向资金、融资融券、龙虎榜）全面覆盖
- 一键 Docker 部署 — 预构建镜像，5 分钟完成部署

### 联系方式

- **QQ 群**:

<div align="left">
  <img src="docs/BG8CFBQQ.jpg" alt="QQ交流群" width="180" style="margin-left: 20px;"/>
</div>

- **GitHub Issues**: [提交 Bug 或建议](https://github.com/BG8CFB/TradingAgents-CN/issues)

---

## 核心特性

### 技术架构

| 层级 | 技术选型 |
|------|---------|
| **后端** | FastAPI + Uvicorn，异步 RESTful API |
| **前端** | Vue 3 + Element Plus + Pinia + Vue Router 4，Vite 构建 |
| **AI 引擎** | LangGraph 4 阶段多智能体流水线 |
| **数据层** | MongoDB 7.0 + Redis 7，统一数据接口 + 多源自动降级 |
| **部署** | Docker Compose（amd64/arm64），Nginx 反向代理 |
| **实时通信** | SSE + WebSocket 双通道推送 |

### 功能亮点

- **动态分析师配置** — YAML 定义分析师角色，无需修改 Python 代码即可增删分析师
- **多数据源自动降级** — Tushare → AKShare → BaoStock 自动切换，保障数据可用性
- **权限管理** — 完整的用户认证、角色管理与操作日志
- **配置中心** — 可视化管理大模型配置、数据源及系统设置
- **实时进度** — SSE + WebSocket 双通道推送，实时掌握分析进度
- **批量分析** — 支持多只股票并发分析
- **专业报告** — 支持 Markdown / Word / PDF 格式导出
- **MCP 工具生态** — 内置 MCP Provider / Consumer 双向架构，可扩展外部工具

---

## 智能体工作流

本项目采用 **LangGraph** 构建多智能体协作网络，整个分析过程分为四个阶段：

```
┌─────────────────────────────────────────────────────────────────┐
│                     阶段 1 — 多维度分析师                        │
│  财经新闻 | 市场分析 | 技术分析 | 基本面 | 社交情绪 | 短线资金     │
│                     （并行工作，独立输出报告）                     │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     阶段 2 — 研究辩论                            │
│                                                                  │
│   ┌──────────┐    多轮辩论    ┌──────────┐                       │
│   │ 看多研究员 │ ◄──────────► │ 看空研究员 │                       │
│   └─────┬────┘               └─────┬────┘                       │
│         └──────────┬───────────────┘                            │
│                    ▼                                             │
│           ┌──────────────┐                                      │
│           │ 研究部主管裁决 │                                      │
│           └──────┬───────┘                                      │
└──────────────────┼──────────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                     阶段 3 — 交易决策                            │
│              专业交易员制定具体交易计划                             │
│       （逐日价格区间、入场/止损/止盈点位、仓位管理）               │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     阶段 4 — 风险控制                            │
│      激进/保守/中立三视角风险团队 + 风控经理最终拍板               │
│              （含应急处理预案、最大回撤约束）                       │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
                    结构化投资分析报告
```

### 核心创新：多空辩论机制

阶段 2 的多空辩论是本项目的核心创新：

1. **看多研究员 (Bull)** — 挖掘增长潜力、竞争优势、催化剂，构建看涨论证
2. **看空研究员 (Bear)** — 识别估值泡沫、风险因素、行业天花板，构建看跌论证
3. **多轮对抗** — 双方基于阶段 1 的分析师报告进行多轮辩论，相互反驳
4. **研究部主管裁决** — 综合多空双方观点，给出最终投资评级和目标价格

### 相比原版项目的增强

| 维度 | 原版项目 | 本社区版 |
|------|---------|---------|
| **辩论结构** | 单轮辩论即出结论 | **多轮对抗式辩论**，逐步逼近真相 |
| **数据约束** | 辩论依据较泛化 | **强制引用阶段1报告**，禁止凭空论证 |
| **裁决机制** | 简单汇总 | **研究部主管独立裁决**，给出量化目标价格 |
| **威科夫分析** | 无 | 辩论双方必须判断威科夫阶段 |
| **短期协同性** | 无 | 未来 7 天协同性分析，量化多空信号强度 |
| **交易执行** | 笼统建议 | 逐日价格区间（3天买入/7天卖出），含具体入场、止损、止盈 |
| **风控体系** | 基础风控 | 三视角风险团队 + 风控经理最终拍板 |
| **中文适配** | 英文为主 | 全中文投研框架，A股特有指标全面覆盖 |

---

## 快速部署

### 一键部署（推荐）

最快 5 分钟完成部署，无需克隆代码仓库。

#### 1. 下载部署文件

下载 [`docker-compose.hub.nginx.yml`](./docker-compose.hub.nginx.yml) 到任意目录：

```bash
# 命令行下载
curl -O https://raw.githubusercontent.com/BG8CFB/TradingAgents-CN/main/docker-compose.hub.nginx.yml

# 或浏览器访问上方链接，右键"另存为"
```

#### 2.（可选）配置 AI 模型密钥

在 `docker-compose.hub.nginx.yml` 同目录下创建 `.env` 文件：

```env
# AI 模型密钥（至少配置一个，不配置也能启动系统）
DASHSCOPE_API_KEY=your_dashscope_key
DASHSCOPE_ENABLED=true

# DEEPSEEK_API_KEY=your_deepseek_key
# DEEPSEEK_ENABLED=true

# 数据源（可选）
# TUSHARE_TOKEN=your_tushare_token
# TUSHARE_ENABLED=true
```

> AkShare 和 BaoStock 数据源默认启用，无需密钥。

#### 3. 启动服务

```bash
docker compose -f docker-compose.hub.nginx.yml up -d
```

Docker 自动从 GitHub Container Registry 拉取预构建镜像（后端 + 前端 + MongoDB + Redis + Nginx），无需编译。

#### 4. 访问系统

- **地址**: http://localhost:8080
- **默认管理员**: `admin` / `admin123`（首次登录后请修改密码）

#### 常用命令

```bash
# 查看服务状态
docker compose -f docker-compose.hub.nginx.yml ps

# 查看后端日志
docker compose -f docker-compose.hub.nginx.yml logs -f backend

# 停止服务
docker compose -f docker-compose.hub.nginx.yml down

# 更新到最新版本
docker compose -f docker-compose.hub.nginx.yml pull && docker compose -f docker-compose.hub.nginx.yml up -d
```

#### 自定义端口

默认 `8080`，如需修改：

```bash
NGINX_PORT=9090 docker compose -f docker-compose.hub.nginx.yml up -d
```

> **注意**: 分析股票前，请先完成数据同步（系统内"数据管理"页面），否则可能导致分析结果异常。

### 本地开发

适用于参与代码贡献或二次开发的开发者。

#### 环境要求

- Python 3.10 - 3.13
- Node.js >= 18.0.0
- Docker（用于 MongoDB / Redis）
- Miniconda（推荐）

#### 启动开发环境

```bash
# 1. 启动基础设施
docker compose -f docker-compose.dev.yml up -d mongodb redis

# 2. 创建 conda 环境
conda create -n tradingagents python=3.12 -y
conda activate tradingagents
pip install -e .

# 3. 启动后端（热重载）
docker compose -f docker-compose.dev.yml up -d backend

# 4. 启动前端（HMR）
cd frontend && npm install && npm run dev
```

#### 访问地址

| 服务 | 地址 |
|------|------|
| 前端（Vite HMR） | http://localhost:3000 |
| 后端 API 文档 | http://localhost:8000/docs |
| Nginx 统一入口 | http://localhost:3080 |

---

## 项目结构

```
TradingAgents-CN/
├── app/                        # 后端应用
│   ├── main.py                 # FastAPI 入口
│   ├── routers/                # API 路由（auth, analysis, config, sync...）
│   ├── services/               # 业务逻辑层
│   ├── models/                 # MongoDB 数据模型
│   ├── core/                   # 配置、数据库、日志
│   ├── data/                   # 数据层（多源采集、存储、调度）
│   ├── engine/                 # AI 引擎（LangGraph 多智能体）
│   │   ├── agents/             # 分析师、研究员、交易员、风控
│   │   ├── graph/              # 图构建与状态传播
│   │   ├── llm_adapters/       # LLM 适配器（DeepSeek, Gemini 等）
│   │   └── tools/              # 内置工具 + MCP 工具
│   ├── worker/                 # 后台任务（数据同步）
│   └── middleware/             # 中间件
├── frontend/                   # Vue 3 前端
│   └── src/
│       ├── views/              # 页面组件
│       ├── components/         # 通用组件
│       ├── stores/             # Pinia 状态管理
│       ├── router/             # 路由配置
│       └── api/                # API 请求封装
├── config/                     # 运行时配置
│   ├── agents/                 # 智能体 YAML 配置
│   ├── defaults/               # 默认配置
│   └── skills/                 # 技能定义
├── tests/                      # 测试套件
├── docker/                     # Docker 构建文件
├── docs/                       # 文档
├── scripts/                    # 辅助脚本
└── runtime/                    # 运行时产物（日志、缓存、结果）
```

---

## 贡献指南

欢迎参与贡献！

- **提交代码**: Fork → 创建分支 → 提交 PR
- **贡献类型**: Bug 修复、新功能开发、文档改进、多语言翻译
- **问题反馈**: [GitHub Issues](https://github.com/BG8CFB/TradingAgents-CN/issues)

---

## 许可证

本项目采用 **混合许可证**：

- **Apache 2.0** — 除 `app/` 和 `frontend/` 外的核心代码
- **专有协议** — `app/`（后端）和 `frontend/`（前端）企业级功能组件需商业授权（个人学习研究可免费使用）

详见 [LICENSE](LICENSE) 文件。

---

## 风险提示

**本项目仅供学习与研究使用，严禁用于非法用途。**

- AI 模型输出具有不确定性，不构成任何投资建议
- 股市有风险，投资需谨慎。实盘交易请咨询专业持牌机构

---

## 致谢

本项目基于 [TradingAgents](https://github.com/TauricResearch/TradingAgents)（Tauric Research）开发，感谢原作者的开源贡献。本仓库为社区维护版本，由 [BG8CFB](https://github.com/BG8CFB) 进行中文本地化、功能增强和持续维护。

---

<div align="center">

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.10%20--%203.13-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/Version-v1.1.0_preview-green.svg)](./VERSION)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

**如果这个项目对您有帮助，请点亮 Star 支持我们！**

[GitHub 仓库](https://github.com/BG8CFB/TradingAgents-CN)

</div>
