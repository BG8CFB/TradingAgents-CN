# Skill 架构（`app/engine/tools/skill/`）

> 从根目录规则文件（原 CLAUDE.md）迁移的参考文档。规则文件只保留一行指引，细节在此按需查阅。

Skill 是**可分发的能力包**（对齐 [Agent Skills 规范](https://agentskills.io/specification)），支持纯 prompt、带脚本、带依赖三种形态。

## 目录结构（每个 skill 是一个目录）

```
config/skills/{skill-name}/        # 用户本地（最高优先级，git 可追踪）
├── SKILL.md                       # 必需：标准 frontmatter + 指令
├── manifest.yaml                  # 可选：依赖与脚本入口声明
├── scripts/                       # 可选：可执行脚本
│   ├── __init__.py
│   └── entry.py
├── references/                    # 可选：REFERENCE.md 等按需加载文档
└── assets/                        # 可选：静态资源
```

## 三个扫描目录（优先级从高到低）

1. `config/skills/` — 用户本地（手写或 git clone）
2. `config/skills/.cache/` — Git URL 安装的临时缓存（已 gitignore）
3. `app/engine/tools/skill/builtin/` — 内置示例（随代码发布，只读）

## 关键组件

| 组件 | 职责 |
|---|---|
| `registry.py` | `SkillRegistry` 单例，发现/缓存/启停状态管理 |
| `loader.py` | SKILL.md frontmatter 解析（yaml.safe_load） |
| `manifest.py` | `manifest.yaml` 解析为 `SkillManifest` Pydantic 模型 |
| `availability.py` | 依赖可用性检查（不安装） |
| `dependency_installer.py` | 首次加载自动安装（subprocess pip install，强制走默认 PyPI，带审计日志） |
| `state_store.py` | MongoDB `skill_state` + `skill_install_logs` 持久化 |
| `entrypoint_loader.py` | 把脚本入口注册为 `BuiltinToolSpec`，LLM 通过 ToolRegistry 调用 |
| `git_installer.py` | Git URL 安装（白名单校验 + 浅克隆 + 删 `.git`） |

## 依赖自动安装安全控制

- 全局开关 `SKILL_AUTO_INSTALL`（默认 `true`，可关）
- 强制走默认 PyPI，禁 `--index-url` / `--extra-index-url`
- 可选白名单 `SKILL_ALLOWED_PACKAGES`（逗号分隔，空则不限制）
- `manifest.hash` 字段触发 `--require-hashes`
- 所有安装记录写入 MongoDB `skill_install_logs` 审计
- 仅在 Docker 容器内执行，不污染宿主机
- 容器重启后通过 `ensure_all_skills_dependencies()` 从 `skill_state` 幂等重装

## 与 builtin 工具的集成

- Skill 的 `entrypoints` 通过 `register_skill_entrypoint` 追加到 `BUILTIN_TOOL_REGISTRY`
- `tool_id` 形如 `{skill_name}.{entrypoint_name}`（如 `my-skill.calc-indicators`）
- `is_skill_tool(tool_id)` 判断是否为 skill 脚本入口
- `simple_agent_factory` 中 skill 工具保留为"可调用工具"（不进入 `inject_tools` 预注入）

## API 与前端

- **API 路由**：`app/routers/skills.py`，`prefix=/api/skills`，`tags=["Skills"]`
- **前端管理页**：`/settings/skills`（`SkillsManagement.vue`），独立 Pinia store `stores/skills.ts`

## Skill 目录规划

| 目录 | 角色 | 说明 |
|---|---|---|
| `config/skills/` | 用户 skill 根 | 可写；Git 安装落地处、手工编辑；优先级最高，可覆盖内置同名 skill |
| `config/skills/.cache/` | 安装缓存 | Git/registry 安装的临时缓存（gitignore） |
| `app/engine/tools/skill/builtin/` | 内置只读 skill | 随代码发布，优先级最低（当前为空，预留） |

## 内置计算工具（builtin tool，非 skill）

LLM 心算/金额计算易错，数值计算不依赖提示词，统一走确定性 function-calling 工具：

- 实现：`app/engine/tools/builtin/tools/calc.py`（纯标准库，Decimal 精度）
- 工具：`calc_expression`（ast 白名单安全求值）、`pct_change`、`position_size`、`risk_reward`、`calc_pnl`、`compound`、`max_drawdown`、`var_95`
- 注入：`build_analyst_specs` 无条件追加进每个分析师的 `callable_tools`（零 YAML 配置），执行走 runner 的 ad-hoc extra_defs 路径
- 测试：`tests/engine/test_engine_builtin_calc.py`
