# 设计：模型级思考控制（thinking effort）

- 日期：2026-08-30
- 状态：已实施（2026-08-30 首版；2026-08-31 按实测修订，见 §11）
- 项目状态：开发中（用户口头确认），按标准可维护改动执行

## 1. 背景与目标

在「添加/编辑模型」时支持：

1. 标记该模型是否为思考（推理）模型；
2. 为其配置默认的思考强度；
3. 控制范围覆盖项目全部双协议（anthropic 原生 / OpenAI 兼容）主力厂家。

### 决策记录（用户拍板）

| 决策点 | 结论 |
|---|---|
| 方案选型 | 统一「开关+强度」抽象 + 协议层方言映射（方案 A）；原始参数透传方案弃用 |
| 项目状态 | 开发中，非维护 → 标准可维护改动，不留堆砌 |
| 档位枚举 | 七档 `None/off/minimal/low/medium/high/max`（经 2026-08 各家官方文档核实） |
| 范围 | 仅模型级默认；任务发起时临时覆盖留作后续迭代 |

## 2. 现状分析（2026-08-30 代码事实）

### 2.1 配置链路

```
前端 LLMConfigDialog.vue 表单
  → POST /api/config/llm（app/routers/config/llm.py，请求体 LLMConfigRequest）
  → config_service.update_llm_config（app/services/config/llm_service.py:182，按 model_name upsert）
  → system_configs.llm_configs（MongoDB，Pydantic LLMConfig）
  → providers.py _CONFIG_FIELDS 白名单（app/llm/providers.py:190）→ ResolvedProvider / EngineClientBundle
  → orchestrator/invoker.py:82、orchestrator/agents.py:235（agent 调用点透传）
  → llm/runner.py run_conversation（thinking_budget 参数，app/llm/runner.py:102）
  → 协议客户端 anthropic_client / openai_client 的 chat / chat_stream
```

### 2.2 现有能力与缺口

| 环节 | 现状 | 缺口 |
|---|---|---|
| `LLMConfig.thinking_budget`（app/models/config.py:228） | 仅 Anthropic 协议消费 | 无「是否思考模型」标记、无强度概念 |
| `LLMConfigRequest`（app/models/config.py:389） | **缺 `thinking_budget` 字段** | **存量 bug：前端表单的思考预算提交即被丢弃（Pydantic 默认忽略未知字段），该功能从未生效** |
| anthropic 协议（anthropic_client.py:50 `_apply_thinking`） | 完整：budget≥1024 且 <max_tokens、开思考强制 temperature=1 | 无档位概念 |
| openai 兼容协议（openai_client.py:194） | **显式忽略** thinking_budget，注释「OpenAI 兼容无对应参数」已过时 | 主力厂家（zhipu/qwen/deepseek/openai/openrouter/kimi/聚合渠道）思考完全不可控 |
| 展示层 | thinking_delta/thinking 事件、前端 StreamingThinkingBubble/ThinkingMessage 已能渲染 reasoning_content | 只缺控制面，不缺展示面 |
| 测试 | 全仓库无任何 thinking_budget/reasoning_effort 相关测试 | 丢字段 bug 因此未被发现 |

## 3. 数据模型设计

### 3.1 新字段（单一字段，避免 `enabled=false`+`effort=high` 类非法组合）

```python
# LLMConfig 与 LLMConfigRequest 同步新增
thinking_effort: Optional[str] = Field(
    default=None,
    description="思考强度：None=不干预(默认，不注入任何思考参数)；"
                "off=显式关闭；minimal/low/medium/high/max=开启并设定强度档"
)
```

校验：枚举 `"off" | "minimal" | "low" | "medium" | "high" | "max"`，其余值 422。

`thinking_budget` 保留，语义收窄为「Anthropic 协议精确预算覆盖」：显式填写时优先于 effort 换算值；`LLMConfigRequest` 补齐该字段（修复存量 bug）。

### 3.2 档位语义（canonical 枚举）

| 取值 | 语义 | UI 标识 |
|---|---|---|
| `None`（默认） | 不干预：不注入任何思考参数，行为与现状完全一致 | 无 |
| `off` | 显式关闭模型自带思考 | 「思考已关闭」 |
| `minimal` | 极简思考 | 💭 极简 |
| `low` / `medium` / `high` | 低 / 中 / 高 | 💭 + 档位 |
| `max` | 极限思考（对齐 DeepSeek/GLM-5/Kimi 原生 max；OpenAI 侧映射 xhigh） | 💭 极限 |

## 4. 协议方言映射

### 4.1 行业现状（2026-08 官方文档核实）

| 厂商/模型 | 开关 | 强度档位 |
|---|---|---|
| OpenAI gpt-5.x | — | `none/minimal/low/medium/high/xhigh`（档位依模型而定，gpt-5.1 起 none 为默认） |
| DeepSeek V4 | 模型级 | `low/high/max`（官方映射 medium→high、xhigh→max） |
| Kimi K2-thinking/K3 | 仅思考不可关 | `low/high/max`（顶层 reasoning_effort） |
| GLM-4.5/4.6 | `thinking.type` 开/关 | 无档位 |
| GLM-5.2 | `thinking.type` | none~max（官方映射 none/minimal→放弃思考、low/medium→high、xhigh→max） |
| GLM-5.3 | 不可关 | `low/high/max`（传 disabled 报错） |
| Qwen3 | `enable_thinking` | `thinking_budget` 数值；新一代支持 `reasoning_effort`（两者互斥） |
| Gemini 3 | — | `thinking_level: minimal/low/medium/high`（2.5 系为数值 thinkingBudget） |
| Anthropic | `thinking.type` | `budget_tokens` 数值 |

来源：OpenAI Reasoning guide、DeepSeek Thinking Mode / Chat Completions、Kimi 思考模型文档、智谱思考模式与 GLM-5.3 模型页、阿里云百炼深度思考、Google Gemini thinking 文档。

### 4.2 映射表（表结构冻结；单元格参数名/数值实现时按当期官方文档校准）

| canonical | OpenAI 系 | DeepSeek | Kimi | GLM-4.5/4.6 | GLM-5.2+ | Qwen | Gemini 3 | Anthropic |
|---|---|---|---|---|---|---|---|---|
| off | `none`（旧 o 系不支持则不发+提示） | 忽略+提示 | 不支持，忽略 | `type:disabled` | 5.2：`type:disabled`；5.3 不可关，忽略+提示 | `enable_thinking:false` | 不支持，忽略 | 不发参数 |
| minimal | `minimal` | →`low` | →`low` | 忽略（仅开/关） | →放弃思考 | budget≈1024 | `minimal` | budget=1024 |
| low | `low` | `low` | `low` | enabled | `low` | budget≈4k | `low` | budget≈4k |
| medium | `medium` | →`high` | →`high` | enabled | →`high` | budget≈16k | `medium` | budget≈16k |
| high | `high` | `high` | `high` | enabled | `high` | budget≈32k | `high` | budget≈32k |
| max | `xhigh` | `max` | `max` | enabled | `max` | budget≈64k | →`high` | budget≈64k |

- 数值换算沿用现有 clamp 逻辑：`[1024, max_tokens-1]`。
- **用户显式 `thinking_budget` 仅对 Anthropic 协议生效并覆盖 effort 换算值**；Qwen 侧数值一律由 effort 换算，不消费显式 budget（两协议解耦，语义各自完整）。
- 厂商自身已给出兼容映射（DeepSeek medium→high、GLM-5.2 low/medium→high 等）直接采用官方口径。

### 4.3 方言判定与实现位置

- 新建 `app/llm/protocols/thinking.py`：纯函数映射模块（canonical → 各方言请求参数 dict），无 I/O、可独立单测。
- 方言判定：**provider 名优先，模型名模式兜底**（聚合渠道模型名保留原厂命名，如 `openai/o3`、`qwen3-max`，模式匹配可覆盖聚合场景）。
- 无匹配方言 → 不注入任何参数 + 一条 INFO 日志（保守策略：不盲发 `reasoning_effort`，不引入 400 降级重试——YAGNI）。
- 管道缺口修复：当前协议客户端不知道自己属于哪个厂家，`create_client` / `build_client` 增加 `provider` 参数将厂家名烙入客户端实例，两客户端在参数构建处调用 mapper。

## 5. 运行时管道

> 2026-08-31 修订：本节为首版方案，实施时改为「思考参数烙入客户端实例默认」
>（对齐 temperature 惯例），消除压缩器/子代理/fallback 三处透传缺口。
> 现行管道见 §11.3。

数据流与 `max_tokens`/`temperature` 每模型参数完全同构：

```
llm_configs.thinking_effort / thinking_budget
  → providers.py _CONFIG_FIELDS 白名单 + ResolvedProvider + EngineClientBundle 新增字段
  → runner.run_conversation 新增 thinking_effort 参数（与 thinking_budget 并列）
  → 协议客户端 chat/chat_stream 签名新增 thinking_effort
  → thinking.py 映射 → 请求参数
```

需同步加字段的三个解析路径：`resolve_provider`、`_resolve_fallback`（fallback 客户端）、`resolve_task_override_bundle`（任务覆盖继承）。

## 6. 前端设计（frontend/src/views/Settings/components/LLMConfigDialog.vue）

1. 基础区新增「思考强度」选择：`默认（不干预）/ 关闭 / 极简 / 低 / 中 / 高 / 极限`；
2. 添加模型时按模型名模式智能预填（o 系/gpt-5/qwq/r1/thinking/glm-5 等 → 预选合适档位，用户可改；仅新增时预填，编辑不覆盖已有配置）；
3. 选项旁按当前厂家动态提示实际下发参数（如 DeepSeek + medium → 「该模型将映射为 high」）；
4. 高级区「思考预算」保留，提示语改为「仅 Anthropic 协议生效，填写后优先于强度换算」；
5. 模型列表页（Settings LLM 管理）为已配置思考的模型加 💭 标识；
6. `frontend/src/api/config.ts` 的 `LLMConfig` 接口与 `validateLLMConfig` 同步新字段校验。

## 7. 兼容与迁移

- **零迁移**：MongoDB 无 schema，存量配置无 `thinking_effort` → Pydantic 默认 `None` → 不注入任何参数，行为与现状逐字节一致；
- 未标记思考强度的模型在 UI/日志/请求层面均无变化；
- `thinking_budget` 修复后语义向后兼容（此前该字段从未生效，无存量用户依赖）。

## 8. 测试计划（全真 I/O，禁 mock 底层）

1. **单元**：`thinking.py` 各方言参数形状（每格一断言）、budget clamp（<1024、>max_tokens-1 边界）、off 对不可关模型的行为、无匹配方言不注入、显式 budget 覆盖 effort 换算；
2. **API 往返**（integration，连容器化 MongoDB）：`POST /api/config/llm` 带 `thinking_effort`/`thinking_budget` → `GET /api/config/llm` 回读一致（同时锁死 LLMConfigRequest 丢字段 bug 不复发）；
3. **协议客户端**：anthropic `_apply_thinking` 档位换算路径；openai 客户端 extra_body/reasoning_effort 参数组装（不发真实请求，断言 params dict）；
4. 静态检查：`ruff check app/ tests/`、`lint-imports`、前端 `npm run type-check && npm run lint`；
5. 相关 pytest：宿主机 conda 环境 `python -m pytest tests/ -m "not integration and not slow and not ai" -q` + 集成层。

## 9. 明确不在本期范围

- 任务发起时临时覆盖思考强度（后续迭代，涉及分析发起 UI 与任务覆盖管道扩展）；
- token 用量按思考/正文拆分统计；
- 未匹配方言厂家的 reasoning_effort 盲发与 400 降级重试。

## 10. 实施清单（文件级触点）

| 文件 | 改动 |
|---|---|
| `app/models/config.py` | `LLMConfig`/`LLMConfigRequest` 新增 `thinking_effort`（+校验）；Request 补 `thinking_budget` |
| `app/llm/protocols/thinking.py` | 新建：方言判定 + canonical→方言映射（纯函数） |
| `app/llm/core/base.py` | `chat`/`chat_stream` 签名加 `thinking_effort` |
| `app/llm/core/factory.py` | `create_client` 加 `provider` 参数（2026-08-31 再加 `thinking_budget/thinking_effort` 烙入实例） |
| `app/llm/providers.py` | `_CONFIG_FIELDS`、`ResolvedProvider`、三处解析路径加字段；`build_client` 传 provider 与思考参数 |
| `app/llm/protocols/anthropic_client.py` | 参数构建处接入 mapper（budget 换算，沿用现有 clamp 与 temperature=1） |
| `app/llm/protocols/openai_client.py` | 删除「忽略」注释，接入 mapper（reasoning_effort / extra_body） |
| `app/llm/runner.py` | `run_conversation` 加 `thinking_effort` 参数并透传 |
| `app/engine/orchestrator/invoker.py`、`agents.py` | 调用点透传 bundle.thinking_effort |
| `frontend/src/views/Settings/components/LLMConfigDialog.vue` | 思考强度选择器 + 智能预填 + 动态映射提示 |
| `frontend/src/api/config.ts` | `LLMConfig` 接口 + `validateLLMConfig` 校验 |
| `frontend/src/views/Settings/ConfigManagement.vue` | 模型列表 💭 思考标识（LLMConfigDialog 的宿主视图） |
| `app/services/config/system_service.py:524` | `_llm_sanitize_in` 的空值清洗字段列表加入 `thinking_effort`（导入路径拒绝 `""`，与 thinking_budget 同策略） |
| `tests/` | mapper 单测、API 往返集成测试、协议客户端参数组装测试 |

## 11. 2026-08-31 修订（实测驱动，用户拍板）

### 11.1 两条根因（NAS 网关 vLLM + Qwen3.8-27B 三轮实测）

1. **形状错配**：首版 Qwen 方言下发百炼形状（顶层 `enable_thinking` + `thinking_budget`），vLLM 完全静默无视——不报 400、照样思考，比报错更隐蔽；
2. **方言不识别**：用户 DB 里该模型 `provider=openai`，`detect_dialect("openai", "Qwen3.8-27B")` 模式不匹配 → None → 不注入 → 「设置无效且无报错」。

实测生效形状（详见项目记忆 local-framework-thinking-params）：

| 控制 | 形状 | 效果 |
|---|---|---|
| 硬开关 | `chat_template_kwargs.enable_thinking=false` | 思考归零（1.1s 最快） |
| 硬预算 | 顶层 `thinking_token_budget: N` | 剂量响应完美（10→18 / 30→88 / 200→198 字），唯一确定性控制 |
| 软档位 | `chat_template_kwargs.reasoning_effort` | 仅 `low/medium/xhigh`（high 必 400，出自模型自带 Jinja2 模板）；梯度 xhigh ≫ low ≈ medium |

### 11.2 方言收敛（用户决策：分厂商）

删除 Kimi/GLM/Qwen/Gemini 方言，收敛为六类；框架方言以 provider 名判定、不做模型门控、不参与模型名兜底：

| canonical | OpenAI 系 | DeepSeek | vLLM | llama.cpp | Ollama /v1 | Anthropic |
|---|---|---|---|---|---|---|
| off | gpt-5：`reasoning_effort=none`；o 系不支持→不注入 | 不支持→不注入 | ctk `enable_thinking=false` | ctk `enable_thinking=false` | 不支持→不注入 | 不发参数 |
| minimal | `minimal` | →`low` | ctk `low` | ctk `low` | `low` | budget=1024 |
| low | `low` | `low` | ctk `low` | ctk `low` | `low` | budget≈4k |
| medium | `medium` | →`high` | ctk `medium` | ctk `medium` | `medium` | budget≈16k |
| high | `high` | `high` | ctk `high`（Qwen3.8 模板→`xhigh`） | ctk `high` | `high` | budget≈32k |
| max | `xhigh` | `max` | ctk `high`（Qwen3.8→`xhigh`） | ctk `high` | `high` | budget≈64k |
| 显式 budget | 忽略 | 忽略 | 顶层 `thinking_token_budget`（硬上限） | 忽略（服务端 `--reasoning-budget`） | 忽略 | 覆盖换算值 |

（ctk = `chat_template_kwargs`；Qwen3.8 系模型名把 high/max 归一到 xhigh，模板只收三档。）

前端 ProviderDialog 预设同步收敛：OpenAI / Anthropic / DeepSeek / vLLM（本地）/ Ollama（本地）/ llama.cpp（本地）/ 自定义 OpenAI 兼容 / 自定义 Anthropic 协议。

### 11.3 注入架构改为「烙入客户端实例」（对齐 temperature 惯例）

首版方案（§5：bundle 字段 + 调用链透传）存在三个缺口：压缩器 `_summarize`、
子代理 `run_conversation`、fallback 备模型均不透传思考参数。修订为与
temperature 相同的实例默认值机制，三个缺口一次全消：

```
llm_configs.thinking_effort / thinking_budget
  → ResolvedProvider（不变）
  → build_client → create_client(..., thinking_budget=, thinking_effort=)
  → 客户端实例默认值（OpenAILLMClient / AnthropicLLMClient 构造器烙入）
  → chat/chat_stream 内：调用处显式传参优先，否则回落实例默认
```

配套调整：`EngineClientBundle` 删除 `thinking_*` 顶层字段；
`invoker.py`/`agents.py` 调用点不再透传（getattr 兜底转发到 primary 客户端
的同名属性，兼容残留读取）；`runner.run_conversation` 签名保留（显式传参
仍可临时覆盖，不传即实例默认）。
