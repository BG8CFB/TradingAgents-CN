# CLAUDE.md

本项目的完整开发规则以 **`AGENTS.md` 为单一事实源**（项目概览、环境、架构、数据层约束、测试规则均在那里）。本文件只保留 Claude Code 工作时的最常用入口，请先阅读：

@AGENTS.md

## 快速命令

```bash
# 开发环境（默认，热重载）
docker compose -f docker-compose.dev.yml up --build -d   # 首次/改依赖后
docker compose -f docker-compose.dev.yml up -d mongodb redis  # 只起基础设施（测试用）

# 测试（宿主机 Miniconda tradingagents 环境，禁 venv）
conda activate tradingagents
python -m pytest tests/ -m "not integration and not slow and not ai" -q  # unit 层
python -m pytest tests/ -m "integration and not ai" -q                   # integration 层
bash scripts/run_full_tests.sh                            # tag 前全量预检（必须通过才能 tag）

# 静态检查与架构契约
ruff check app/ tests/ scripts/
lint-imports

# 前端
cd frontend && npm run dev | npm run type-check | npm run lint
```

## 硬性约束（速查，完整说明见 AGENTS.md）

- 消费数据只走 `DataInterface.get_instance()`；routers 不得 import `app.data.storage` / `app.data.sources`（import-linter 强制）、不得直接调用 MongoDB 方法（pytest lint 强制）
- 禁止 import 已移除的 `config_manager`（ruff banned-api 强制）
- `os.getenv()` 仅限配置层白名单模块（白名单见 AGENTS.md / `tests/lint/test_env_access_conventions.py`）
- 路由规范：`prefix="/api/<domain>"`、英文 Title-Case `tags`
- 新代码统一 `symbol`（非 `code`）、`data_source`（非 `source`）
- 测试全真 I/O，禁止任何 mock 底层；HK/US 集合用 `_hk`/`_us` 后缀
- 数据源接入只写自己的 Provider/Adapter 入标准库；消费方禁止"查库不到就直连数据源兜底"

## 参考文档（按需阅读，勿放入规则文件）

- `docs/skill-architecture.md` — Skill 能力包架构与依赖安装安全控制
- `docs/全市场股票数据架构设计文档.md` — 数据层设计
- `docs/tsc.md`、`docs/智能体工作流程.md`
