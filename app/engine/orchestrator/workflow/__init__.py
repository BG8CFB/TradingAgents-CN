"""工作流通用化子系统：spec / 种子 / 存取 / 校验 / 编译 / 执行。

模块职责：
- spec:      WorkflowSpec pydantic 模型（拓扑 + 节点身份 + 终端契约）
- seeds:     本地 JSON 种子加载（仅初始注入与 DB 不可达降级）
- store:     agent_specs / workflow_specs 两集合的 DB 存取（tombstone 防复活）
- validator: 结构与 registry 锚点校验
- loader:    默认工作流装配（spec 来源 = store）
"""
