# 智能体自由编排设计（裸节点 × 模组 × 连线拓扑）

- 日期：2026-09-15
- 状态：已获用户批准的方向性设计，待实施
- 前置：`2026-09-14-workflow-generalization-design.md`（spec → compile → execute 三段编排骨架，本设计在其上重塑）

## 1. 背景与问题

现行画布把「智能体进画布」按 kind 自动分流：分析师拖空白建单成员并行组、辩手建辩论组、裁决/终端建辩论组落裁决位、交易/总结建单智能体组。用户否定了这套模型：

> 智能体是智能体，模组是模组，用户可以随意组合。模组是一个对现有工作流的扩展功能，而不是把所有智能体都归类到组件里。如果我添加一百个其他类型的智能体，怎么还要用户去选择它是辩手还是分析师？

三个现行模型跑不通的核心场景：

| # | 场景 | 现状阻塞点 |
|---|---|---|
| S1 | 三个分析师独立分析 → 辩论 → 辩论结束后**再次调用其中一个智能体**（如拿辩论结果再跑一次分析师） | 任意类型智能体单独执行：`executor._materialize_node` 工厂白名单仅 `trader`/`summary`，其余 slug 启动即 RuntimeError |
| S2 | 分析师 A 分析完**把结果交给分析师 B**，B 调自己的工具再分析（串行链） | batch 成员的 `NodeRef.inputs` 在编译期被丢弃（`compiler.py`），`_stage_inputs` 不覆盖 batch，`run_analyst` 只读 ticker/date |
| S3 | **在辩论阶段添加分析师当辩手** | `validator` 禁止 phase1 池成员当辩手；辩手物化丢弃 `execution`/工具能力（generic 单轮） |

## 2. 概念模型

画布上只有三种元素，**角色由位置决定，不由智能体类型决定**：

```
① 独立智能体节点（裸卡，无组壳）          ② 模组（可选编排容器）
   ┌──────────┐                          ┌─ 并行模组 ──────────┐
   │ ③ 分析师B │                          │ [分析师C] [分析师D]  │ ← 组内并行执行
   └──────────┘                          └────────────────────┘
        ↑ 连线 = 数据流                      ┌─ 公平辩论模组 ───────┐
   ┌──────────┐                            │ [辩手1] [辩手2] …    │ ← 轮流等轮次
   │ ① 分析师A │──A 的报告──→ 辩论模组        │        [裁决]       │
   └──────────┘   （辩论产出再连下游）        └────────────────────┘
```

- **智能体**：一等独立节点。可单独存在、可串行连线、可进任意模组、同一智能体可多处使用（数据模型本就允许同 slug 多处引用）。
- **模组**：对工作流的可选编排扩展——并行模组（组内同时执行加速）、公平辩论模组（轮流 + 等轮次交锋 + 裁决收束）。模组不承载智能体分类。
- **kind 只影响图标**，不再决定任何建组/落位行为。
- 唯一保留的类型约束：辩论模组的**裁决位**要求 judge/terminal 类型（后端裁决物化依赖；这是语义角色约束而非分类）。

## 3. 用户已确认的决策

| 决策点 | 结论 |
|---|---|
| 执行顺序 | **连线自动推导**：随便连 A→B 或 B→A，系统按依赖自动排到正确执行顺序；无连线的内容按数组（创建）顺序 |
| 工具能力 | **所有类型智能体都可调用工具**；存量智能体（内置辩手等）默认关闭保持现状，**后续新增智能体默认开启** |
| 报告机制 | 维持现有 **submit_report 显式提交**（深度分析结论：对话最后一轮可能是工具确认等中间态，显式提交强制收束、产出可靠；且为项目既有机制，零新增不确定性）。带工具的辩手 = 工具轮结束后 submit_report 收尾 |
| n8n 吸收 | ①节点运行状态徽标；②节点级禁用开关。其余（pin 数据/错误分支/表达式系统/画布数据面板）不做 |

## 4. 数据模型变更（spec.py）

全部为**可选字段增量**，存量数据零迁移：

```python
class NodeSpec:                    # 全局智能体定义（agent_specs 集合）
    tools_enabled: bool | None     # None=按存量默认（analyst 开、其余关）；显式值覆盖

class NodeRef:                     # batch 成员引用
    disabled: bool | None          # True=本工作流内该成员跳过

class SingleStageSpec:             # 独立节点（渲染为裸卡）
    disabled: bool | None          # True=该节点跳过
```

- 辩论成员**不提供**禁用（公平辩论需全员参与，与现有组面板文案语义一致）；辩论组的跳过走既有 stage.optional。
- batch 的 pool 动态成员（任务发起时选择的分析师池）无 NodeRef，不适用禁用。

## 5. 编译与执行

### 5.1 拓扑执行序（compiler + validator）

- **依赖边推导**：stage B 依赖 stage A ⟺ B 的组输入（debate.inputs / single.inputs）或 batch 成员输入（NodeRef.inputs）绑定的键落在 A 的产出键集合内。产出键集合**复用 `validator.stage_output_keys` 现有口径**（成员 report_keys + debate 的 `state_key` 含派生 `{state_key}.judge_decision` + terminal 节点写入的 `decision_field` 根），不另起推导。
- **排序**：Kahn 算法；就绪队列按 stages 数组序取（稳定 tie-break）。无连线的 stage 与其它 stage 并列时按数组序。编译产物 `CompiledPlan.stages` 即拓扑序。
- **环**：检测到环 → `CompileError`，报错列出成环 stage id 链。validator 同步增加环检测（保存期拦截，先于编译）。
- **方向解禁**：validator 不再要求「inputs 只能引用数组序靠前的 stage」——前端连线与绑定允许任意方向，序由拓扑推导。
- **golden 兼容**：默认工作流无回连，拓扑序与数组序一致，行为零变化。

### 5.2 任意智能体独立执行（executor `_materialize_node` 扩展）

single stage 物化按 NodeSpec 解析分流——**先按内置 slug 命中现有工厂，未命中再按 kind 分流**（现有工厂按 slug 精确绑定，仅内置 `trader`/`summary` 两个 slug；用户自建的同 kind 智能体不得再落入该工厂）：

| 解析顺序 | 条件 | 物化路径 | 说明 |
|---|---|---|---|
| 1 | slug ∈ {trader, summary}（内置） | 现有工厂 | 不变（golden 锚点） |
| 2 | kind = analyst | `build_analyst_specs` 单成员 + 工具循环 | 复用分析师装配器 |
| 3 | 其余 kind（debater/judge/terminal/trader/summarizer 自建） | generic 单轮发言（debaters/generic.py 范式） | 产出报告按 report_keys |

single 的 inputs **解析**沿既有 `_stage_inputs` 路径（已覆盖 single）；但现有消费端只有 trader/summary/generic 辩手读它——**single 分析师节点的上游注入走 §5.3 的 `run_analyst` 注入参数**（与 batch 分析师同一条接线），S1 场景（辩论产出→再跑一次分析师）由此打通。

### 5.3 分析师串行链（分析师上游注入，batch 与 single 同一接线）

- `plan.py`：`PlannedBatch` 增加成员级 inputs（编译产物）；`compiler` 不再丢弃 `NodeRef.inputs`，逐成员解析为 `{source_stage, keys}` 透传。
- `executor._stage_inputs`：从仅覆盖 debate/single 扩展到 batch——逐成员解析上游值。
- `agents.run_analyst`：签名增加上游注入参数，**batch 成员与 single 分析师节点共用**；按 `generic.py inject_report_messages` 范式把上游报告以包裹标签（`<upstream-report key="...">`）注入首轮 history，分析师带着上游结果调工具再分析。
- 注入内容缺键（上游被禁用/跳过）：warning 日志 + 跳过该键注入，不中断（与 optional 组跳过同口径）。

### 5.4 辩手工具开关（能力全量开放）

- `compiler`：PlannedNode 保留 `kind` / `execution` / `tools_enabled`（现状：编译期丢弃）。同时 `_planned_node` 的节点解析源从仅 workflow `spec.nodes` 扩展到 registry 动态段（agent_specs）——S3 解禁后辩手/sides 可来自动态智能体库，未命中 `spec.nodes` 时回落 registry 查找，仍无则 CompileError。
- `executor._materialize_side`：辩手发言轮当 `tools_enabled` 生效时装配该智能体的 toolkit + submit_report——工具轮发生在 `run_agent_turn` 内部（max_turns 保护），**发言轮结构不变**（轮流 + 等轮次 + 每轮一次发言事件），公平性口径为「结构性轮次对等」，事件序列形状与 golden 断言兼容。
- 默认值口径：`tools_enabled=None` → analyst 开、其余关（存量行为）；内置辩手 seeds 不动（None → 关）；**智能体管理新增智能体默认写 `tools_enabled: true`**（前端表单默认值 + 后端创建路径兜底）。

### 5.5 节点级禁用

- compiler：`NodeRef.disabled` / `SingleStageSpec.disabled` → `PlannedNode.disabled`。
- executor：disabled 成员/节点跳过执行，发一次 skipped 类事件（对齐现有事件枚举，无则新增 `node_skipped`）；不产报告。
- 下游引用被禁用节点的产出键：`_stage_inputs` 按缺键容忍（warning + 跳过注入，见 5.3）。
- 发起分析的计划预览（RunPlanPreview）明确标示「已禁用，将跳过」。

### 5.6 报告机制（不变，仅明确口径）

所有节点统一 submit_report 显式提交：无工具节点单轮提交；带工具节点（分析师 / tools_enabled 辩手）工具轮结束后提交。同 slug 多次调用的产出为同名报告键**后次覆盖前次**（现状语义，见 §8）。

## 6. 前端画布交互

- **拖空白**：任何智能体拖到画布空白 = 创建 single 独立节点（裸卡）。删除 createStageForAgent 的全部 kind 分流。
- **拖入模组**：拖到并行/辩论模组内 = 成为成员（分析师进辩论组即辩手，validator 的 phase1 池限制放开后合法）。
- **single 裸节点渲染**：无 band 壳/组头，卡片 = 图标（按 kind）+ 名称 + 自动执行序徽标 + 输入/输出端口（沿用 edgeRules 端口派生）。防重叠与位置记忆复用现有 `memberNodeId` / `freeSpotInBand` / `seedBandPosition` 机制。
- **连线方向解禁**：edgeRules 不再限制只能连向数组序大的 stage；卡上执行序徽标显示前端拓扑算法（与 compiler 同口径：依赖边 + 数组序 tie-break）算出的序。
- **PropertyPanel**：组面板「执行顺序」区改为「执行序由连线自动推导；同层并列时按数组序」——↑↓ 按钮保留但仅影响同层并列顺序；节点实例区（batch 成员 / single 节点）新增「禁用」开关。
- **术语**：并行模组 = 组内同时执行加速；公平辩论模组 = 轮流等轮次交锋。single 渲染为裸节点后，「单智能体组」的组壳概念消失（存量 single stage 自动以裸卡呈现，数据不变）。

## 7. 运行状态徽标（n8n 吸收①）

- 落点：发起分析页 RunPlanPreview + 任务详情侧栏——节点粒度实时状态：待执行 / 运行中 / 成功 / 失败 / 已跳过。**skipped 仅指节点被禁用**（§5.5）；上游缺键不改变节点状态（§5.3 口径：缺键容忍、节点照常运行，仅少一份输入注入）。
- 数据源：现有 agent_event WS 事件流，纯前端消费；节点条目按拓扑序排列。
- 状态机：pending → running → done | failed；禁用节点直接 skipped。

## 8. 兼容性与明确不做

**兼容**：数据模型只增不改，存量工作流（内置 + 用户自定义）零迁移；默认工作流执行行为不变（golden 等价测试守门）；存量 single stage 从组壳渲染变裸卡，连线与绑定不变。

**明确不做（二期评估）**：

- 同 slug 多次调用产出独立分键（现为同名键覆盖；如需保留首次产出再议后缀键方案，涉及画布端口派生与 report_titles 联动）。
- 画布级输入/输出数据面板、pin 固定输出、错误分支节点、表达式系统。
- 实例级（每工作流）工具开关覆盖——先全局（智能体库）级 tools_enabled。

## 9. 测试策略

- **golden 等价测试必须绿**（默认行为不变是兼容性核心锚点）。
- 新增单测：拓扑排序（常规/并列稳定序/环拒绝）；batch 成员 inputs 编译透传 + 运行注入端到端；**single 分析师节点上游注入端到端（S1：辩论产出 → 再跑分析师）**；非白名单 slug（analyst/debater/judge）single 执行；tools_enabled 辩手装配与发言轮结构；禁用成员跳过与下游缺键容忍；validator 环检测与 phase1 辩手解禁。
- 前端：type-check / eslint / build 三件套 + 手工核查清单（拖空白裸节点、反向连线自动排正、串行链、分析师进辩论组、新增智能体默认带工具、禁用跳过、状态徽标流转、存量工作流回归）。
