# 智能体工作流通用化设计（受限 DAG）

- 日期：2026-09-14
- 状态：设计定稿（已与用户逐项确认七个关键决策）
- 性质：结构性建设（分期实施，每期独立可验证）

## 1. 背景与目标

当前分析流水线是硬编码的固定 4 阶段拓扑（分析师并行 → 多空辩论 → Trader → 风险辩论 → Summary），仅提供 3 种开关组合。目标：把「执行什么」（拓扑、节点目录、身份映射）从代码中抽成数据，让用户可以创建自己的工作流与智能体；「怎么执行」（重试、事件、公平 barrier、黑板合并）保留为引擎机制。

非目标：任意分支/条件 DAG、脚本级编排、按用户私有隔离（作用域为全局共享）。

## 2. 现状深度分析（证据）

### 2.1 已经是黑板模式（有利条件）

- 节点契约统一：`node_fn(state) -> update dict`，update 经 `_merge_state_update` 合并（reports 字典合并、messages 追加、其余覆盖），`app/engine/orchestrator/pipeline.py:103-115`
- `state["reports"]` 字典是报告唯一聚合点；顶层 `*_report` 字段为出口兼容层（`pipeline.py:686-689`）
- 辩论内容 canonical 存 `*_debate_state.rounds`，报告视图派生（`app/engine/orchestrator/state.py:186-261`）

### 2.2 固定的五件事（改造对象）

1. **拓扑**：`run_pipeline` 硬编码阶段顺序（`pipeline.py:509-684`）
2. **节点目录**：辩手/裁决/交易/总结是硬编码工厂（`create_researcher` 只认 bull/bear，`app/engine/agents/stage_2/researcher_factory.py:29-80`；Phase3 固定 Risky→Safe→Neutral，`pipeline.py:647-653`）
3. **状态 schema**：`investment_debate_state`/`risk_debate_state` 的边写死在 TypedDict（`state.py:37-54`）
4. **身份映射**：`_NODE_SLUG_MAP`/`_NODE_EVENT_KEYS`/`_NODE_DISPLAY_FALLBACK`/`_SLUG_ALIAS` 四张硬编码表（`pipeline.py:27-54, 127-135`）+ builder 与 trader 各自的报告显示名解析（`app/engine/prompts/builder.py:52-66`、`app/engine/agents/stage_2/trader.py:69-80`）+ 前端 `agentDisplayNames.ts`（含 `REPORT_KEY_SLUG_ALIAS`）——新增一个智能体需同步 6 处
5. **进度记账**：`compute_total_units` 按固定阶段公式（`pipeline.py:243-261`）

### 2.3 报告消费是「黑名单」而非「依赖声明」

- 多空研究员：`collect_reports(state, exclude_ids={bull, bear})`（`researcher_factory.py:123`）
- Trader：自写收集逻辑，硬编码排除 6 键（`trader.py:21-38`）
- 字段级隐式依赖：trader 直读 `judge_decision`，P2 关闭时用默认文案兜底（`trader.py:63-65`）
- 隐含语义：数据流由代码执行顺序隐式保证；辩论同轮防泄漏靠排除表 + rounds 只读历史轮（`pipeline.py:468-473`）——该公平性语义必须保留

### 2.4 prompt 层的软依赖（最隐蔽耦合）

phase2/3 YAML 提示词硬编码引用六份 Stage1 报告中文名（`config/agents/phase2_agents_config.yaml:10-16` 等）；用户裁掉分析师后 prompt 仍引用不存在的报告，程序层零校验、静默劣化。

### 2.5 两种执行语义并存

| | Stage 1 分析师 | Stage 2/3/4 全部节点 |
|---|---|---|
| 执行 | `run_conversation` 多轮工具循环（`app/engine/orchestrator/agents.py:227-248`） | `run_agent_turn` 单轮、`tools=[]`（`app/engine/orchestrator/invoker.py:73-79`） |
| 工具 | skills + MCP + 计算 + 可选子代理 | 零工具 |
| 报告产出 | `final_text` 隐式截取（`agents.py:250`） | `final_text` 隐式截取（`invoker.py:94`） |

### 2.6 终局链路（终端契约）

- Summary 实为结构化 JSON 终端节点：硬编码 4 个核心报告键（`app/engine/agents/stage_4/summary_agent.py:120-123`）、输入体检（`:24-44`）、截断长度（500/1500/300）、JSON 三级兜底（`:251-275`）；system prompt 为系统契约（`app/engine/prompts/parts.py:4-40`，8 字段 JSON schema + 真实性检查）
- 信号回退链硬编码 `final_trade_decision → investment_plan → risk_debate_state.judge_decision → trader_investment_plan`（`app/engine/runtime.py:198-202`）
- 持久化：`analysis_reports` 集合（`app/services/analysis_service.py:2168-2201`）；服务层两份手写报告键清单（`analysis_service.py:1559-1617`、`app/routers/analysis.py:206-259`）
- trader 的 9 节输出结构被 `SignalProcessor` 正则解析——输出契约藏在用户提示词里

### 2.7 前端耦合面（比预想弱）

- 事件流按 `agent_key` 分 tab 渲染（不按 phase）——过程面板天然兼容自定义拓扑
- 硬编码仅三处：`frontend/src/constants/phases.ts`、TaskDetailSidebar 的 `phaseN_enabled` 键、agentDisplayNames 别名表

### 2.8 其余耦合

- 记忆槽硬编码 5 个（`pipeline.py:84-89`）；reflector 读旧形状键（`app/engine/agents/postprocess/reflector.py:62-106`），仅回测时触发
- 事件 14 类，主键 agent_key + 附属 phase，落库回放（`app/llm/events.py`）

## 3. 决策记录

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 自定义粒度 | 拓扑级：用户可新建完整工作流 |
| 2 | 编辑载体 | 表单先行 → 画布后置（spec 稳定后画布不返工） |
| 3 | 拓扑模型 | **受限 DAG**：有序阶段列表 × 三种阶段模式（并行批/辩论组/单节点），节点本身完全自由 |
| 4 | 作用域 | 全局共享（DB 存储，管理员维护；内置默认定义以 YAML 种子随版本发布，启动时 seed 入库——运行时单一 DB 数据源） |
| 5 | 关系模型 | **入口自由、存储统一**：全局智能体库 + 工作流引用；工作流编辑器内可新建智能体（自动入库） |
| 6 | 内置提示词 | 用户角色段 + 系统层（提示词契约段 + submit_report 参数 schema，按节点 type 自动装配、不可关闭）|
| 7 | 失败语义 | 节点结果三态协议 `ok / dead(reason)`，dead 降级为值不中断 |

选择受限 DAG 而非任意 DAG 的理由：辩论公平性（同轮并行 + 只读历史轮 + barrier 合并）是本项目最精密的语义，封装为「阶段模式」而非让用户连线复刻；任意分支/条件边对股票分析场景收益低、复杂度指数上升。

## 4. 架构设计

```
WorkflowSpec（DB 文档；内置默认定义随代码以 YAML 种子分发，启动时 seed 入库——单一运行时数据源）
   │  WorkflowValidator —— 保存/启动前校验（fail-fast，错误定位到字段）
   ▼
WorkflowCompiler —— spec → ExecutionPlan（展开辩论轮次、动态数进度单元、绑定节点工厂）
   ▼
GraphExecutor —— 遍历执行计划，复用现有节点机制（_execute_node/_run_debate_round/黑板合并）
   │  state 黑板（reports + 声明式输出字段）
   ▼
TerminalContract —— decision 字段 + 信号回退链 → SignalProcessor → analysis_reports 持久化
```

原则：「执行什么」（spec 数据）与「怎么执行」（executor 机制）分离；执行内核 Ports 化（LLM 调用/事件/记忆/工具注册经接口注入），编排内核可独立单测。

### 4.1 AgentRegistry（身份收敛，P1）

单一注册表管理六标识映射：`slug ↔ internal_key ↔ report_key ↔ event_key ↔ display_name ↔ icon`。替换 pipeline 四张硬编码表、builder/trader 显示名解析、`report_titles.py` 别名表；前端 agentDisplayNames 改为经 API 拉取（后端唯一事实源）。每个任务的执行计划实例化一份 runtime 视图（含自定义节点）。

### 4.2 NodeSpec（节点定义）

```yaml
slug: macro-researcher
name: 宏观研判员
type: analyst            # 见下方 type 枚举与职责表
execution: tool_loop     # tool_loop | single_turn
memory: null             # 记忆槽绑定（trader/bull/.../null）
prompt: |                # 用户角色段，占位符引用输入槽
  你是宏观研判专家，请综合 {{inputs.市场技术分析报告}} …
template_inputs:         # 模板契约：本节点需要哪些输入槽、缺槽怎么降级。
                           # 示例假设该自定义节点插在研究辩论之后——两槽拓扑可达（stage-1 节点无上游槽）
  - slot: 市场技术分析报告   # 连线来源（槽接哪个上游）由工作流的 NodeRef.inputs 决定，见 4.3
    required: false
    missing_policy: "暂无市场技术分析，请基于已有信息判断"
  - slot: 研究裁决
    required: false
    missing_policy: "暂无研究部主管裁决"
tools:                   # execution=tool_loop 时生效
  data_tools: [...]      # 预注入
  skills: [...]          # 可调用
  mcp: [...]
output:
  report_key: macro_research
```

**节点两层模型**（解决「节点是什么」与「节点在工作流里怎么接」的耦合）：

- **全局库层（NodeSpec）= 类型定义**：这个智能体是什么——slug/type/execution/prompt 模板/`template_inputs` 契约/tools/output。库中 slug 全局唯一（DB 唯一索引）：内置定义只读、定制必经 fork（强制新 slug），因此不存在用户定义与内置同 slug 的覆盖歧义——「内置 → 用户自定义」同 slug 覆盖链整体删除（原设计矛盾根源之一，随 seed-to-DB 单一存储一并消解，见 4.3）。
- **工作流层（WorkflowSpec 内的节点条目 NodeRef）= 实例配置**：这个智能体在本工作流里怎么接、怎么配——`ref`（指向库 slug）、`inputs`（每个槽连哪个上游）、`default_selected`、运行参数覆盖。连线天然工作流私有，工作流 A 里拖线不会影响工作流 B。
- **fork（复制为私有副本）**：在某工作流中要改全局字段（prompt/tools）而节点是共享引用或内置只读时——复制库定义为新 slug、本工作流 `NodeRef.ref` 切换到新 slug，之后编辑只影响本工作流。定制内置智能体的唯一路径 = fork。
- 槽值解析：`prompt` 的 `{{inputs.槽名}}` 在渲染时从黑板取值，取值来源 = `NodeRef.inputs` 中该槽的连线；缺槽 → `required` ? 启动前拒绝 : `missing_policy` 文案。

校验规则：`debater` 强制 `single_turn`（保辩论公平：开放数据获取类工具会引入不可对齐的副作用——debater 工具白名单 = 仅 submit_report，见 4.6b）；`analyst` 强制 `tool_loop` 之外，`trader/judge/summarizer/terminal` 默认 `single_turn`、允许显式声明 `tool_loop`（如需实时行情核对的 trader——当前内置节点全部为 single_turn，仅对自定义节点开放）；`output.report_key` 全工作流内唯一；prompt 占位符与 `template_inputs` 槽名一一匹配（库保存时校验）；`NodeRef.inputs` 连线覆盖模板引用的全部槽（工作流保存时校验，见 4.6）。

**type 枚举与职责**（每个 type 绑定输出字段语义与系统契约——提交载体为 submit_report 参数，见 4.6b/4.7）：

| type | 职责 | 输出字段（submit_report 参数落点） | 系统契约（见 4.7） |
|---|---|---|---|
| `analyst` | 产出领域报告（可调工具） | `output.report_key` 入黑板 | 计算硬规则 |
| `debater` | 辩论发言（仅辩论组内） | rounds[side]（辩论组管理） | 辩论规则 + 引用要求 |
| `judge` | 辩论裁决 | `output.report_key` + `judge_decision`（所属辩论组 state_key） | 裁决输出结构 + 引用要求 |
| `trader` | 交易计划 | `trader_investment_plan`（或 spec 覆盖） | 交易计划输出结构 + Buy/Sell/Hold 关键词 |
| `summarizer` | 结构化总结 | `structured_summary`（8 字段 JSON） | JSON schema 契约 + 真实性检查 |
| `terminal` | 最终决策产出 | workflow `terminal.decision_field` 指定的字段 | 决策输出结构 + 信号关键词（Buy/Sell/Hold） |

说明：当前 `final_trade_decision` 由 risk_manager（judge 类型）写入——迁移时该内置节点同时标 `terminal: true`（一个 judge 可以兼任 terminal，decision_field 由 workflow 声明指向其输出）。`terminal.decision_field` 的写入者 = spec 中标记 `terminal: true` 的节点。

### 4.3 WorkflowSpec（拓扑定义）

```yaml
version: 1
slug: default-4stage
name: 默认四阶段分析
description: 市场/新闻/基本面/情绪分析师 → 研究辩论 → 交易计划 → 风险辩论 → 总结
enabled: true             # 禁用后不出现在分析页选择器
terminal:
  decision_field: final_trade_decision
  # 点路径表示法：顶层字段直接写键名，嵌套字段用点路径
  signal_fallback:
    - final_trade_decision
    - investment_plan
    - risk_debate_state.judge_decision
    - trader_investment_plan
  summary_node: summary
stages:
  - id: analysts
    mode: parallel_batch
    nodes:                      # NodeRef 条目：字符串简写 = {ref: <slug>}（inputs 缺省 all_upstream，见 4.6）
      - ref: market
        default_selected: true  # 分析页初始勾选态（工作流层语义：同一分析师在不同工作流可有不同默认）
      - {ref: news}
      - {ref: fundamentals}
      - {ref: sentiment}
      - {ref: china_market}
      - {ref: short_term_capital}
    concurrency: 5
  - id: research_debate
    mode: debate
    optional: true          # 可被 stage_overrides.enabled 跳过（analysts/trader/summary 不可跳过）
    state_key: investment_debate_state
    sides: [bull, bear]     # 简写 = 辩手 NodeRef；辩手 inputs 缺省继承组输入
    rounds: 1
    judge: research-manager
    inputs:                 # 组输入：注入全体辩手与 judge 的公共上游报告（stage 级声明载体，N 方泛化时形状不变）
      分析师报告: [market_report, news_report, fundamentals_report,
                  sentiment_report, china_market_report, short_term_capital_report]
  - id: trader
    mode: single
    node:                   # 内置默认工作流全部显式枚举（等价锁定，见 4.6）——不使用选择器
      ref: trader           # type: trader
      inputs:
        分析师报告:         # 枚举清单 = 现有 trader 输入集（黑名单排除辩论 judge 报告与辩手键后的 6 份报告；新模型下辩手无主输出，结果集一致）
          [market_report, news_report, fundamentals_report,
           sentiment_report, china_market_report, short_term_capital_report]
        研究裁决: investment_debate_state.judge_decision  # field 槽（点路径，来自 stage 2 裁决；阶段关闭时走 missing_policy）
  - id: risk_debate
    mode: debate
    optional: true
    state_key: risk_debate_state
    sides: [risky, safe, neutral]
    rounds: 1
    judge: risk-manager   # type: judge，内置定义中兼标 terminal: true → 写 final_trade_decision
    inputs:               # 组输入 = 现有 stage3 输入集（分析师报告 + trader 计划）
      分析师报告: [market_report, news_report, fundamentals_report,
                  sentiment_report, china_market_report, short_term_capital_report]
      交易计划: trader_investment_plan
  - id: summary
    mode: single
    node:                   # summary 显式声明 = 现状输入集（动态收集全部 *_report + 3 个 field 槽）
      ref: summary         # type: summarizer
      inputs:
        分析师报告:         # 现状动态收集顶层全部 *_report → 枚举 6 份；裁剪后未入库的报告走 missing_policy
          [market_report, news_report, fundamentals_report,
           sentiment_report, china_market_report, short_term_capital_report]
        交易计划: trader_investment_plan
        最终决策: final_trade_decision
        风险辩论历史: risk_debate_state.rounds   # 派生视图经点路径引用（现状读风险辩论轮次历史）
```

> 示例中的 report_key 为示意写法（按 slug 派生）；真实键名以 §4.1 AgentRegistry 收敛结果为准，由 golden 等价测试（§8）锁定，规划/实施时不以本示例字面为准。

- 辩论组泛化为任意 N 方（`per_turn = len(sides)`，公平 barrier 逻辑不变）
- 现有 phase1/2/3 YAML 智能体迁移为内置 NodeSpec（`builtin: true`，可 fork 不可改删）
- **存储：seed-to-DB 单一存储**（运行时唯一数据源 = MongoDB）：
  - 种子分发格式 = JSON（`config/seeds/`，随代码进 git，可 review、可 diff、承载内置定义的版本演进），运行时不读任何 YAML
  - 启动 seed（lifespan，与 config 初始化同期）：DB 无该 slug → 写入；已有且 `builtin: true` 且种子内容 hash 变化 → 覆盖升级（内置只读，无用户改动冲突；fork 副本 slug 不同，不受升级影响）；重复启动幂等；带 tombstone（`deleted` 标记）的内置条目不复活（管理页删除语义保持）。边界情形：若该 slug 已被用户自定义（非 builtin）占用，新内置定义不落地并打 WARNING 日志（提示重命名占用者或更换内置 slug）
  - **首次迁移**（2026-09-14 修订：seed-to-DB 与智能体库迁移随 P2 一并落地，YAML 运行时存放整体退役）：启动时现有 phase1/2/3 YAML 条目逐条与种子比对——完全一致 → 以 builtin 入库；有差异 → 保留用户版本（builtin=false，不被种子升级覆盖）；迁移完成后 YAML 文件退役
  - 用户自建 NodeSpec / NodeRef / WorkflowSpec 与内置同库同 schema（`builtin` 字段区分），CRUD/校验/编译只走一条 DB 路径——不再有「读 YAML + 读 DB 再合并」的双源逻辑
  - slug 全局唯一（DB 唯一索引）：与内置同 slug 的新建请求直接 409，不触发任何覆盖
  - **内置 WorkflowSpec 与内置 NodeSpec 同样只读**（PUT/DELETE 均 403，UI 隐藏编辑/删除入口）——定制内置工作流 = 复制为自定义工作流再改；这是「hash 变化覆盖升级」前提不被用户改动破坏的保证
- 复制工作流 = 复制 NodeRef 列表（引用不动、连线和参数跟工作流走），因此「复制内置工作流」即得到安全的定制起点，不会触碰全局库

### 4.4 WorkflowCompiler

编译签名：`compile(spec, params) -> ExecutionPlan`。**spec 是静态蓝图，params 是每次任务的运行时裁剪**，两者分离：

| params 参数 | 语义 | 对 spec 的作用 |
|---|---|---|
| `selected_nodes` | 本次选中的智能体（含现有 `selected_analysts` 机制） | 对 `parallel_batch` 阶段的节点列表取子集（保序）；辩论组 sides 不可裁（结构完整性） |
| `stage_overrides.enabled` | 阶段启停（承接现有 `phase2_enabled`/`phase3_enabled`） | 跳过标记为 `optional: true` 的阶段；辩论组关闭时下游 judge 一并跳过、trader 直连上游（保持现有 P2 关闭语义） |
| `stage_overrides.rounds` | 辩论轮数覆盖（承接现有 `phase2_debate_rounds` 等，clamp 到 MAX_ROUNDS=10） | 覆盖 spec 中的默认 rounds |
| `stage_overrides.concurrency` | 并发覆盖 | 覆盖 parallel_batch 默认并发 |

- **校验**：输入引用的 report_key 在拓扑序上可达；辩论组 sides≥2 且有 judge；terminal 声明的节点存在且类型匹配；占位符匹配；slug/report_key 唯一；required 检查（见 4.6）
- **展开**：辩论组 → `rounds+1` 个执行单元/侧；进度单元总数 = 执行计划长度（替代 `compute_total_units` 硬编码公式——开关/子集化后动态数）
- **绑定**：NodeSpec 按 `type × execution` 选工厂（现有 analyst 装配线、debater/judge 工厂参数化）

**与现有行为的关系**：现有的三拓扑（P2+P3 / 仅 P2 / 仅 P3）= 同一份默认 spec 在不同 `stage_overrides` 下的编译结果；`selected_analysts`（含 `default_selected` 默认勾选机制）完整保留为 `selected_nodes` 的输入。分析页交互从「选分析师 + 拨阶段开关」升级为「选工作流 + （工作流暴露的可调参数）」——默认工作流暴露的就是上述 params，用户感知不变。

**任务创建 API 契约**：`POST /api/analysis/single` 请求体新增 `workflow_slug`（缺省 = 默认工作流；默认工作流由管理员在工作流管理页「设为默认」，持久化在 system_configs），`parameters` 里现有的 `selected_analysts`/`phaseN_enabled`/`phaseN_debate_rounds` 字段保留兼容，映射为编译参数。

### 4.5 GraphExecutor

重构 `run_pipeline`：从硬编码阶段序列变为遍历 ExecutionPlan。保留全部执行器机制：`_execute_node` 的计时/critical 重试/事件、`_run_debate_round` 的公平 barrier、`_merge_state_update`、MCP 生命周期管理。`_phase` 事件字段取阶段 id。记忆绑定按 NodeSpec.memory 泛化。节点结果三态协议：`ok / dead(reason枚举)`，reason 进 errors[] 与事件流（对齐现有「失败降级不中断」语义并使其正式化）；`ok` 附报告元数据 `submission: structured | fallback_text`（见 4.6b 提交协议）。

### 4.6 Prompt 渲染与报告提交

**（a）输入渲染**

- `{{inputs.槽名}}` 占位符由渲染器从黑板取值，取值来源 = `NodeRef.inputs` 中该槽的连线（两层模型见 4.2）；槽未被连线覆盖 = 工作流保存时校验失败，连线指向拓扑上不可达的上游 = 启动前校验失败（非运行中静默幻觉）
- 系统层保持不可关闭：`<report>`/`<tool_data>` 边界符与抗注入说明、环境前缀、CALC_ENFORCEMENT、辩论轮次触发语与历史重建
- 输入可见性从「全量拉取+黑名单」翻转为「节点显式声明」；**`all_upstream` 选择器解析集明确定义**：拓扑序在本节点之前的全部节点主输出（各节点的 `output.report_key`），**不含**辩论轮次派生视图、**不含** type 附带字段（`judge_decision`/`trader_investment_plan` 等必须显式 field 槽引用）——该选择器仅供自定义工作流的宽松模式使用；**内置默认工作流全部逐槽显式枚举**（见 4.3 示例）以锁定等价行为，其枚举清单 = 现状各节点真实输入集（trader 的 6 报告 + 研究裁决 field 槽；summary 的 6 报告 + 交易计划/最终决策/风险辩论历史 field 槽）；辩论同轮防泄漏由 debate 模式内部保证
- 下游节点声明缺失降级文案（`template_inputs.missing_policy`——trader 现有 judge_decision 兜底模式的泛化）
- **required 输入检查（fail-fast）**：槽在 `template_inputs` 中标 `required: true`（编译期校验裁剪后的执行计划仍满足）；内置默认工作流将市场技术、短线资金标为辩手/trader/summary 的 required 槽——**行为变更声明**：当前裁掉这两个分析师会静默跑出劣质报告，P3 起任务创建时拒绝并提示，这是「不可裁」约束的正式化

**（b）报告提交协议（submit_report）——替代「取最后一轮回复」**

现状报告 = `result.final_text` 隐式截取（`agents.py:250` / `invoker.py:94`），报告边界靠约定、机器可解析输出靠提示词 + 解析兜底（summarizer 三级 JSON 兜底、SignalProcessor 关键词正则）。改为**显式工具提交协议**（对齐 Anthropic/OpenAI structured outputs 与 LangGraph 显式 state 写入的行业方向——工具参数天然带 schema 校验，机器可解析链从提示词约定升级为 API 级强制）：

- **每个节点装配唯一必然工具 `submit_report`**：所有 type 一律经它提交产出。参数 = `content`（markdown 正文，人类可读）+ 按 type 的结构化字段（4.7 表：trader/terminal 的 `decision`(Buy/Sell/Hold 枚举) 与关键点位、summarizer 的 8 字段、judge 的 `judge_decision`）——**§4.7 的输出结构契约从提示词迁移为工具参数 schema**，schema 校验失败 = 工具执行报错返回给模型重试（bounded，计入 max_turns）
- **执行语义调整**：single_turn 节点（Stage 2-4）从 `tools=[]`、max_turns=1 变为 `tools=[submit_report]`、max_turns=2（生成 + 提交）；analyst 的工具集 = 现有工具 + submit_report
- **辩论公平性重述**：debater 约束从「零工具」改为「工具白名单 = 仅 submit_report」——纯提交、无信息获取、无外部副作用，同轮辩手能力仍严格对齐，公平性不降
- **写入路径**：submit_report 执行器即时写黑板（`state["reports"][report_key]` + type 附带字段；**debater 例外**：提交内容落 `rounds[side]`，由辩论组管理，不写 reports 主键——见 4.2 类型表），并发 `report_ready` 事件（携带完整 content 与 `submission: structured` 标记）——报告 tab 有了精确触发锚点，不再依赖会话结束推断
- **降级路径（可靠性保证）**：模型到 max_turns 仍未调用 / provider 不支持 tool calling → 取 final_text 作 content、结构化字段回退现有文本解析（正则/JSON 提取）、标记 `submission: fallback_text`；三态协议不变（ok/dead），提交来源作为报告元数据随事件与结果落库
- **收益与代价**：删掉 summarizer 三级 JSON 兜底与 SignalProcessor 正则优先路径（降为 fallback 分支）；代价是报告在工具参数中传一遍的少量 token（提示词契约段要求「提交后简短收尾，不再重复报告内容」）
- **行为变更声明**：golden 等价测试的事件序列自 P3 起包含 submit_report 工具调用事件；黑板键集合与报告语义不变

### 4.7 系统契约（内置提示词与输出 schema 边界）

用户提示词只写角色段；系统层按 type 自动装配两样东西：

| type | submit_report 参数 schema（结构化输出） | 提示词契约段（行为约束） |
|---|---|---|
| analyst | `content`（markdown 正文） | 计算硬规则（CALC_ENFORCEMENT）+ 提交规范 |
| debater | `content`（本轮发言） | 辩论规则 + 引用要求 + 轮次行为约束 + 提交规范 |
| judge | `content` + `judge_decision` | 裁决引用要求 + 提交规范 |
| trader | `content` + `decision`(枚举) + 点位/仓位字段 | 交易计划骨架说明 + 提交规范 |
| summarizer | 8 字段结构化参数（原 structured_summary schema） | 真实性检查 + 纯文本/数值类型约束 + 提交规范 |
| terminal | `content` + `decision`(枚举)（写入 workflow 声明的 decision_field） | 决策输出说明 + 信号关键词回退要求 |

机器可解析输出（SignalProcessor、summary JSON）以工具参数为一手来源、文本解析仅存于 fallback 分支；输出截断长度、输入体检规则随 type 走，不进用户提示词——用户改角色提示词不会弄断机器解析链。

### 4.8 报告存取与终端契约（三级存放视图）

报告的存放与读取收敛为三层，各层单一职责：

| 层 | 写入时机 | 内容 | 读取方 |
|---|---|---|---|
| 运行时黑板 `state["reports"]` + type 附带字段 | submit_report 执行器即时写入（或降级时会话结束写入） | 完整报告正文 + 结构化字段 | 下游节点（NodeRef.inputs 连线取值）、Executor |
| 事件流 `analysis_events` | `report_ready` 事件（携带完整 content + `submission` 来源标记） | 同上 + 提交来源 | 前端实时展示（LiveReportPanel）、历史回放 |
| 任务文档 `analysis_reports` | 任务完成时 TerminalContract 汇总 | 全部报告 + 终端结构化产物 | 结果页、回测、reflector |

- **信号提取优先级翻转**：结构化字段（submit_report 的 `decision` 参数）为一手来源，文本关键词正则降为 fallback_text 提交时的回退分支；WorkflowSpec 声明的 `terminal.signal_fallback`（点路径链）仅在各级结构化字段缺失时按序探取
- analysis_service 与 routers 的两份手写报告键清单收敛为 workflow 元数据 + AgentRegistry 驱动
- `structured_summary` 契约由 `summarizer` 类型节点的 submit_report schema 内置（字段级校验前置到工具参数；输入体检保留）；注意 `terminal` 是独立类型（最终决策产出），与 `terminal: true` 标记（judge 可兼任）含义不同

### 4.9 关系模型（入口自由、存储统一）

- 所有智能体（内置迁移 + 用户自建）都是全局库 NodeSpec：一套 CRUD、一套校验、引用计数（被引用不可删）
- 编辑工作流时可「+ 新建智能体」→ 弹表单创建 → 自动入全局库并插入当前阶段
- 工作流引用库的方式 = NodeRef（`ref` + 连线 + 参数，见 4.2 两层模型）；编辑共享节点的全局字段时前端提示影响范围（「将影响 N 个工作流」），用户可选「编辑全局定义」或「fork 为私有副本」（内置节点只读，定制必经 fork）
- 与 Claude Code 的 subagent 全局定义 + workflow 按名引用模式同构

## 5. 前端设计

### 5.1 页面地图与信息架构

```
分析（业务入口）
└─ 单只分析页 SingleAnalysis.vue（改造：工作流选择 + 阶段分组节点选择 + 参数区）

设置（管理入口，管理员）
├─ 工作流管理 WorkflowManagement.vue（新增：列表 + 新建/复制/删除，内置只可复制）
├─ 工作流编辑器 WorkflowEditor.vue（新增：表单视图 P5 → 画布视图 P6，同一份 spec 的两种视图）
└─ 智能体管理 AgentManagement.vue（扩展：从「按 phase 编辑 YAML」升级为全局 NodeSpec 库）
```

两层关系的前端表达：
- **定义层**（工作流编辑器）：工作流引用哪些智能体、怎么编排——连线与阶段配置
- **运行层**（分析页）：本次分析启用工作流中的哪些可裁节点、覆盖哪些参数——勾选与开关

### 5.2 分析页：启动分析的完整交互

改造 `SingleAnalysis.vue`，流程从「选分析师 + 拨阶段开关」升级为：

```
① 选标的（股票/日期，不变）
② 选工作流：下拉/卡片选择器（默认 = 默认四阶段分析；列出管理员创建的工作流，
   显示名称 + 描述 + 节点数；仅列出 enabled 且校验通过的工作流）
③ 选智能体（工作流感知的裁剪区）：
   按 spec 的阶段顺序分组展示节点卡片；每张卡片的可裁性由后端 spec 决定：
   - parallel_batch 成员（分析师等）→ 勾选框可选，NodeRef 的 default_selected 决定初始勾选态
     （承接现有默认勾选机制与用户偏好覆盖 preferences.default_analysts）
   - 辩论组 sides / trader / summary / 标记 required 的节点 → 锁定态（置灰 + 🔒图标 +
     tooltip「该工作流必选」），不可取消
   - optional 阶段（如两场辩论）→ 阶段级开关 + 轮数控件（承接现有 phase2/phase3 交互，
     由 spec 的 optional/rounds 声明自动生成，不再来自 constants/phases.ts 硬编码）
④ 参数区：spec 暴露的可调参数（轮数/并发，与 §4.4 params 表一致）自动生成表单
⑤ 提交 → POST /api/analysis/single：
   { stock_code, analysis_date, workflow_slug, parameters: {
       selected_nodes: [...勾选的节点 slug...],
       stage_overrides: { research_debate: {enabled: false, rounds: 2}, ... } } }
   （parameters 内 selected_analysts/phaseN_enabled 旧字段保留兼容映射）
⑥ 运行中/结果：ProcessPanel / LiveReportPanel / TaskReportPanel 面板结构与按 agent_key 渲染不变
   （自定义节点自动获得对话 tab 与实时报告 tab），两处内容源适配 submit_report 协议（见 4.6b）：
   - 对话流新增专属工具卡类型：submit_report 渲染为「📄 提交报告」卡（摘要行 + 展开查看完整 content），
     与 calc/skill 等工具卡同渲染路径、专属图标样式——报告提交在过程流中有显式锚点
   - 报告 tab 内容源从「会话结束的 final_text」切换为 report_ready 事件携带的工具参数 content；
     submission: fallback_text 的报告 tab 显示「非结构化提交」标记（模型未走工具协议，质量差异可见）
   - 历史回放走同一渲染路径（事件已落库），无需适配
⑦ 任务详情侧栏：从「phaseN_enabled chips」改为「工作流名 + 节点 chips + 参数摘要」
```

裁剪冲突的即时反馈：勾选/取消即时调用 `POST /api/workflows/validate-run`（轻量编译校验），不满足 required 槽（`template_inputs.required: true`）时在对应锁定节点上显示红色提示（如「裁掉了市场技术，但多头研究员依赖其报告」），提交按钮禁用。

### 5.3 画布编辑器（连线语义与排版）

**核心统一**：画布连线不是新的执行语义，而是 `NodeRef.inputs` 声明（工作流实例层，见 4.2 两层模型）的图形化编辑载体——表单视图手动填 inputs 连线列表，画布视图拖线生成完全相同的数据。两种视图编辑同一份 spec，互相同步；连线数据属于本工作流，不影响全局库与其他工作流。

**布局——垂直分段泳道**：

```
┌─ 阶段 1 · 并行批（分析师）─────────────────────────────┐
│  [🛠 市场技术分析师]   [📰 新闻分析师]   [📊 基本面分析师] │
│      │report              │                    │        │
└──────┼────────────────────┼────────────────────┼────────┘
       ▼                    ▼                    ▼
┌─ 阶段 2 · 辩论组（可整体关闭）──────────────────────────┐
│  ┌(辩论组容器：内部的边由模式封装，用户不可连)──────────┐ │
│  │  [🐂 多头研究员] ⇄ (rounds 轮自动交替) ⇄ [🐻 空头研究员] │ │
│  │                    ▼ 裁决                            │ │
│  │           [⚖ 研究部主管]──judge_decision──────────┐ │ │
│  └───────────────────────────────────────────────────┼─┘ │
└───────────────────────────────────────────────────────┼───┘
                                                        ▼
┌─ 阶段 3 · 单节点 ──────────────────────────────────────┐
│  [💰 交易员]（多输入端口：分析师报告×3 + judge_decision） │
└────────────────────────────────────────────────────────┘
```

- 分段容器自上而下 = 执行顺序（受限 DAG 的「有序阶段」在视觉上一目了然）；拖动节点跨分段 = 改变所属阶段
- 辩论组是一个**封闭容器**：组内辩手之间的交替/反驳边由模式封装不显示为可编辑连线；组对外的接口只有「组输入（上游报告注入）」和「裁决输出（judge_decision + 裁决报告）」

**节点卡片与端口**：

- 每个节点卡片：图标 + 名称 + type 徽标 + execution 徽标（⚙ tool_loop / 💬 single_turn）
- **输出端口**（右侧）：主输出 = `output.report_key`；type 附带字段输出追加端口（judge 的 `judge_decision`、trader 的 `trader_investment_plan` 等，按 §4.2 类型表自动生成）
- **输入端口**（左侧）：按节点 `template_inputs` 契约逐槽显示端口（连线写入本工作流 `NodeRef.inputs` 的对应槽）；`all_upstream` 选择器显示为单个聚合端口（标注「全部上游」）
- **多输入**：多条入边分别落到不同输入槽端口（如交易员同时接 3 份分析师报告 + judge_decision）
- **多输出**：一份输出端口可拉出多条出边到多个下游（同一份报告被多个下游声明引用——黑板语义天然支持）

**连线校验（拖线时即时、保存时后端复检）**：

- 边只能从「上游阶段的输出端口」连到「下游阶段的输入端口」（允许跨多段）；连向上游方向直接拒绝并回弹
- 不成环（分段有序 + 方向限制保证）
- 辩论组容器边界不可穿透（不能连到组内辩手，只能连到组的对外接口）
- 输入槽类型匹配：report 槽只能接 report 输出端口，field 槽只能接对应字段输出
- 连线落库即写入本工作流的 `NodeRef.inputs`；删除连线即移除对应声明；编译校验（可达性/槽覆盖）在保存时统一跑

**交互规范（定稿——行业标准做法，对齐 n8n/Dify/Langflow/Figma 的成熟手感）**：

*连线*：
- 从输出端口按住拖出 bezier 曲线，拖动过程中**合法目标输入端口实时高亮（绿色描边）、非法目标置灰**（类型不匹配/方向非法/辩论组边界）；松手于非法区域 = 连线回弹 + toast 说明拒绝原因
- 一个输出端口可拉出多条边（fan-out 多输出）；一个输入槽端口接受多条入边时聚合成「多源」徽标（report 槽 = 报告列表语义）；**field 槽仅接受单一来源**（标量语义），多条入边在连线校验中拒绝
- 点击选中边（加粗高亮）→ Delete 键或悬停 × 按钮删除；删除带一次 Undo 可恢复

*节点*：
- 单击 = 选中并打开属性面板；双击 = 选中 + 聚焦属性面板首个字段；拖拽 = 移动（网格吸附 8px）；拖拽跨分段容器 = 改变所属阶段（实时重算分段归属与连线校验）；**拖入辩论组容器 = 追加为该组新 side**
- 节点卡片右下角「+」按钮 = 快捷添加下游节点（拉出临时连线到空白处释放 → 弹出智能体库选择器，n8n 同款）
- Delete = 从本工作流移除节点（不删全局库定义，确认弹窗注明）；Ctrl+D = 复制节点为新 NodeRef（自动偏移放置）
- hover 节点 = tooltip 显示 type/execution/被引用数；锁定节点（required）显示 🔒 角标

*端口*：
- hover 端口 = 放大 + 显示槽名/字段名 + 已连接数；`all_upstream` 聚合端口有专属「全部上游」样式（虚线边框）

*视图导航*：
- 滚轮缩放（以指针为中心）、按住空格或空白区拖拽平移、工具栏 fit-view / zoom-to-fit / 缩放百分比控件；minimap 右下角（可折叠）
- 分段容器可折叠（收起后节点收拢为计数徽标，连线聚合显示）；「自动布局」按钮 = dagre 分层布局（阶段为 rank、同段内按现有连线最小化交叉）

*编辑保障*：
- 撤销/重做：Ctrl+Z / Ctrl+Y，操作栈覆盖连线/节点/属性/阶段变更（快照式，栈深 50）
- Ctrl+S = 保存（触发后端全量校验）；未保存变更离开页面 = 确认提示
- 校验可视化：校验失败的节点/连线红框 + 错误 tooltip；错误列表侧栏（点击条目画布定位到对应元素并脉冲高亮）
- 只读模式：查看内置工作流时禁用全部编辑 affordance（拖拽/连线/删除入口隐藏，端口不响应），顶部横幅「内置工作流（只读）— 复制后可编辑」+「复制」快捷按钮
- fork 入口：内置节点属性面板全局定义区的「fork 为私有副本」按钮（§4.9 语义）

*键盘与无障碍（基础级）*：
- Tab 在节点间循环聚焦、Enter 选中、Esc 关闭属性面板、Delete 删除选中元素；全部交互元素有 aria-label

*性能与边界*：
- 单画布节点数上限 100（超出提示拆分工作流——受限 DAG 阶段制下远超实际需要）；Vue Flow 自带视口虚拟化，百级节点无性能问题
- **移动端声明**：画布编辑仅支持桌面端（≥1024px + 精确指针）；移动端可平移缩放查看但禁用编辑（管理后台场景的行业标准取舍，Element Plus 体系一致）

**属性面板（双区，对应两层模型）**：选中节点 → 右侧抽屉分两区——
- **工作流实例区**（只影响本工作流）：inputs 连线（槽 → 上游映射）、default_selected、参数覆盖
- **全局定义区**（影响库中该 NodeSpec）：prompt 模板（含 `{{inputs.槽名}}` 补全）、tools、type、memory、template_inputs 契约。编辑前若该节点被 N>1 个工作流引用，提示「将影响 N 个工作流」并给出「编辑全局定义 / fork 为私有副本」选择；内置节点全局区只读，仅提供「fork 为私有副本」
- 选中阶段容器 → 编辑阶段属性（模式/rounds/optional/concurrency，辩论容器含 sides 与组输入编辑）；选中连线 → 显示输入槽映射与缺失降级文案

**技术选型**：Vue Flow（`@vue-flow/core`）——Vue 3 生态最成熟的节点/边/端口/拖拽/缩放库，自定义节点与 Handle（端口）原生支持上述设计；泳道用背景分组实现。这是选型建议（行业惯例），实施时可换自研 SVG，但端口/连线/校验的产品语义不变。

### 5.4 工作流管理页与智能体库

**工作流列表**（WorkflowManagement.vue）：

- 卡片字段：名称、描述、阶段数/节点数、更新时间、内置标记（builtin 徽标）、启用状态、被引用统计（最近任务数）
- 操作：新建（从空白/复制现有，复制内置 = 推荐的定制起点——内置工作流只读，编辑必经复制）、编辑（仅自定义；内置 403 且 UI 隐藏入口）、设为默认（默认工作流持久化在 system_configs，`workflow_slug` 缺省时使用）、删除（内置不可删；被任务引用过的工作流软删除保留历史任务可回放）
- 编辑入口进 WorkflowEditor（表单/画布双视图切换，P5 先表单）

**智能体库**（AgentManagement.vue 扩展）：

- 从「phase1/2/3 三页签编辑 YAML」升级为全局 NodeSpec 库：列表 + 筛选（type / 来源：内置·自定义 / 被引用工作流）
- 卡片显示：图标、名称、slug、type 徽标、execution、引用计数（被哪些工作流引用，展开可见）
- 编辑表单（编辑的是全局库 NodeSpec = 类型定义）：基本信息（slug 新建后锁定/name/description/type/execution/memory）→ prompt 模板编辑器（`{{inputs.槽名}}` 占位符自动补全）→ template_inputs 契约声明（表格：槽名/required/缺失降级文案——只声明「需要什么」，不连线）→ tools 配置（data_tools/skills/mcp，按 execution 显隐）→ output（report_key，slug 派生可改）。连线（inputs 接哪个上游）不在此页——在工作流编辑器的节点属性「工作流实例区」配置；工作流保存时校验连线覆盖模板引用的全部槽
- 内置智能体：查看 + 复制（fork），不可编辑删除——定制路径 = fork 出私有副本，再在工作流中引用副本（或在工作流编辑器里直接 fork，见 5.3 属性面板）
- 保存时后端校验，错误定位到表单字段高亮
- 工作流编辑器内的「+ 新建智能体」按钮打开同一份表单（入口自由、存储统一：保存后自动入全局库并插入当前阶段）

### 5.5 前端消费的 API 契约

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/workflows` | GET/POST | 列表（含内置+自定义，带启用/校验状态）/ 新建 |
| `/api/workflows/{slug}` | GET/PUT/DELETE | 详情（完整 spec）/ 更新（内置 403，定制走复制）/ 删除（内置 403） |
| `/api/workflows/validate` | POST | 编辑保存前校验，错误定位到字段/连线 |
| `/api/workflows/validate-run` | POST | 分析页裁剪的轻量编译校验（selected_nodes + overrides → 可行性） |
| `/api/agents` | GET/POST | 智能体库列表（type/builtin/引用计数）/ 新建 |
| `/api/agents/{slug}` | GET/PUT/DELETE | 详情 / 更新（全局定义，提示影响范围由前端负责；内置 403，定制走 fork） / 删除（被引用 409 + 引用列表；内置 403） |
| `/api/agents/{slug}/fork` | POST | 复制为私有副本（新 slug，内置定制的唯一路径；可在工作流编辑器内调用后自动切换 NodeRef.ref） |
| `/api/registry/display-names` | GET | AgentRegistry 的 report_key/node → 显示名映射（替代前端 agentDisplayNames 硬编码） |
| `/api/analysis/single` | POST | 现有端点扩展 `workflow_slug` + parameters 新字段（旧字段兼容映射） |

路由规范遵循项目约定：`prefix="/api/<domain>"`、英文 Title-Case tags。

### 5.6 组件与前端改造清单

| 组件 | 动作 | 期 |
|---|---|---|
| `components/Workflow/WorkflowSelector.vue` | 新增：分析页工作流选择器 | P5 |
| `components/Workflow/NodeSelectGrid.vue` | 新增：阶段分组节点选择（勾选/锁定态/required 提示） | P5 |
| `views/Settings/WorkflowManagement.vue` | 新增：列表页 | P5 |
| `views/Settings/WorkflowEditor.vue` | 新增：表单视图编辑器 | P5 |
| `views/Settings/AgentManagement.vue` | 扩展：全局库化 | P5 |
| `SingleAnalysis.vue` | 改造：接 WorkflowSelector + NodeSelectGrid，退役阶段开关硬编码 | P5 |
| `constants/phases.ts` | 退役：阶段元数据改由 spec 驱动 | P5 |
| `utils/agentDisplayNames.ts` | 改为 `/api/registry/display-names` 驱动（P1 内完成后端 API + 前端接入，满足「显示名单一来源」验收） | P1 |
| `components/Analysis/ProcessPanel.vue` 工具卡 | 扩展：submit_report 专属「📄 提交报告」卡类型（§5.2⑥） | P3 |
| 实时报告 tab（LiveReportPanel 路径） | 改造：内容源切 report_ready 工具参数 content + `submission: fallback_text` 标记（§5.2⑥） | P3 |
| `components/Analysis/TaskDetailSidebar.vue` | 改造：phaseN chips → 工作流 + 节点 chips | P5 |
| `components/Workflow/Canvas/*`（CanvasStage、NodeCard、EdgeLayer、PropertyPanel） | 新增：Vue Flow 画布 | P6 |
| `WorkflowEditor.vue` 画布视图 | 新增：与表单视图双视图切换 | P6 |

前端遵循既有规范：Element Plus 组件体系、配置驱动展示（禁止写死智能体中文显示名——统一走 registry API）、响应式。

## 6. 展示兼容矩阵

| 展示面 | 依赖 | DAG 化后 |
|---|---|---|
| 实时过程面板（对话/思考/工具调用） | agent_key（不按 phase 分组） | 面板结构不变；P3 新增 submit_report 专属工具卡类型（§5.2⑥） |
| 实时报告面板 | report_ready + title | 面板不变；内容源 P3 从 final_text 切换为工具参数 content + submission 来源标记 |
| 进度条 | completed/total/percent | 无影响（分母编译期动态数） |
| 用户向运行中智能体发消息 | agent_key 消息门禁 | 无影响 |
| decision 卡片 | final_signal 回退链 | P3 信号提取优先级翻转为结构化字段一手来源；P4 终端契约参数化后无影响 |
| structured_summary 卡片 | summary JSON 契约 | P3 schema 前置到 submit_report 参数（8 字段），三级兜底删除 |
| 任务详情侧栏 | phaseN_enabled 硬编码 | P5 改为展示工作流 + 节点清单 |
| 分析页阶段开关 | constants/phases.ts | P5 改为选择工作流 |
| 历史任务回放 | 事件已落库 | 无影响 |
| 回测反思 | 旧形状辩论键 | P4 记忆绑定 + 输入声明泛化 |

## 7. 参考项目（claude-code CCB）对照

采纳 5 项：执行内核 Ports 化（引擎/宿主分离）；节点结果三态协议 + 死因分类；配置错误 fail-fast；工作流级 token 预算（可选扩展，挂在并发临界区检查）；内置默认与用户定制分离（CCB 的覆盖优先级链思想，落地为 YAML 种子 seed-to-DB + fork 新 slug，替代同 slug 覆盖链——单一存储下覆盖歧义不存在）。

不采纳：journal 断点重放（行情数据非确定性，重放语义不成立；断点续跑列为远期可选）；脚本沙箱（定义层面向 Web 用户）；子工作流嵌套与多后端路由（无需求，不预留复杂度）。

不照抄定义层的原因：CCB 面向开发者用 JS 脚本编排、脚本内变量传数据；本产品面向 Web 端用户，画布/表单只能安全产出声明式结构，且必须封装本项目特有的辩论公平性语义。

## 8. 测试策略

- **Golden 等价测试**：默认 spec 编译执行后，事件序列（类型+agent_key+顺序）、最终 state 形状（export_legacy_state）、reports 键集合与现有 pipeline 逐项对比锁定——重构无漂移的硬保证。**必须覆盖三拓扑变体**（P2+P3 / 仅 P2 / 仅 P3，即三种 `stage_overrides` 编译结果）以及分析师子集化（`selected_nodes` 裁剪）场景，因为这些都是当前 pipeline 的强制行为
- 编译器单测：非法 spec（坏引用/缺 judge/占位符不匹配/环）拒绝且错误定位准确
- seed 幂等与升级测试（真实 Mongo）：重复启动不重复写入；内置种子 hash 变化时覆盖升级且 fork 副本不受影响；与内置同 slug 新建返回 409
- submit_report 协议测试：schema 校验失败 → 工具报错返回模型重试（bounded）；到 max_turns 未调用 → 降级取 final_text 且标记 fallback_text；debater 工具白名单 = 仅 submit_report（同轮辩手工具集一致）；golden 事件序列自 P3 起含工具调用事件（行为变更声明见 4.6b）
- 辩论公平性回归：现有 barrier/只读历史轮测试保留，扩展 N≠2/3 方
- 遵守项目规则：全真 I/O、无 mock；Mongo/Redis 走容器化实例

## 9. 分期交付

| 期 | 内容 | 性质 | 验收 |
|---|---|---|---|
| P1 | AgentRegistry 身份收敛（后端 6 处 + 前端别名表） | 债务清理 | 全量测试通过；显示名单一来源 |
| P2 | spec schema + Compiler + Executor 重构（默认 spec 等价）+ **seed-to-DB（JSON 种子注入 Mongo，智能体库 phase1/2/3 YAML 同期迁移，YAML 运行时存放退役）** | 结构性建设 | Golden 等价测试通过（存储迁移与编排重构双等价）；seed 幂等/升级/首次迁移测试通过 |
| P3 | 输入契约 + prompt 模板化 + **submit_report 提交协议（§4.6b：工具 schema 化输出、报告三级存取、降级路径）** | 语义翻转 | 黑名单逻辑移除；占位符校验生效；submit 协议测试通过（summarizer 三级兜底删除） |
| P4 | 辩论组 N 方泛化 + 终端契约参数化 + 记忆绑定（+可选 token 预算） | 能力扩展 | 自定义 N 方辩论工作流可跑通 |
| P5 | 工作流/智能体 CRUD API（fork/引用计数/409）+ 校验 + 分析页改造（§5.2）+ 工作流/智能体管理页（§5.4，表单编辑） | 产品面 | 全局共享库可用（单一 DB 数据源）；引用计数生效；分析页可选工作流启动分析 |
| P6 | 画布编辑器（§5.3，spec 的可视化视图，交互规范全量落实） | 前端工程 | 画布产出 spec 与表单等价；§5.3 交互规范逐项验收（连线校验/撤销重做/只读模式/键盘可达） |

## 10. 风险与开放问题

- **辩论公平性回归**：N 方泛化改动 `_merge_debate_updates` 的 per_turn 语义，需专项测试
- **submit_report 的 provider 兼容**：个别自托管/小众模型 tool calling 不稳定——降级路径保底（fallback_text + 现有文本解析），协议不成为可用性单点；主流模型（双协议 SDK 覆盖面内）无此问题
- **golden 事件序列变化**：P3 起事件流含 submit_report 工具调用事件，P2 建立的 golden 基线需在 P3 落地时同步更新（已在 4.6b 声明为行为变更，非静默漂移）
- **prompt 迁移**：内置 YAML 中硬编码的报告引用改占位符，语义需逐字对齐（可先双轨：无占位符时保持全量注入行为）；输出契约迁移到工具 schema 后提示词只留行为约束，迁移期双轨校验
- **reflector 兼容**：自定义工作流无辩论状态时反思输入为空，需声明式输入适配
- **执行计划快照**：任务启动时冻结「spec 版本 + 编译参数」（selected_nodes/stage_overrides 一并冻结为 ExecutionPlan 快照），在跑任务不受工作流编辑影响——P2 实现
- 开放问题：断点续跑（远期）
