"""TradingAgents AI 分析引擎

本模块是 TradingAgents 项目的核心 AI 分析引擎，提供以下主要功能：

主要组件:
    - agents: AI Agent 实现，包括各种专业分析角色
    - config: 配置管理模块（数据模型）
    - orchestrator: 手写保序编排（替代 LangGraph）
    - tools: 工具集（builtin 工具 + MCP 配置管理面）
    - utils: 引擎内部工具函数

LLM 调用统一走新层 app/llm（双协议直连官方 SDK，工具注册/压缩/重试/事件）。

导入路径变更说明:
    原路径 'tradingagents.*' 已迁移至 'app.engine.*'
    例如:
        - tradingagents.config → app.engine.config
        - tradingagents.tools.mcp → app.llm.mcp（运行时+管理面唯一家）

使用示例:
    from app.engine.config import ModelConfig

版本: 2.0.0
"""
