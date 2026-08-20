"""
AI 可调用内置工具包

与 datasources/（预注入数据源，代码控制）相对：这里的工具注册为
ToolDef、由 LLM 在对话循环中主动调用。
- calc.py  确定性数值计算（orchestrator 无条件挂载，不经注册表）
- registry.py  可调用注册面（skill 脚本入口动态注册/卸载）
"""
