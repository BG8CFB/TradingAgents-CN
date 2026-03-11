"""TradingAgents AI 分析引擎

本模块是 TradingAgents 项目的核心 AI 分析引擎，提供以下主要功能：

主要组件:
    - agents: AI Agent 实现，包括各种专业分析角色
    - config: 配置管理系统，支持 MongoDB 和 JSON 文件存储
    - llm_adapters: 大语言模型适配器，支持多种 LLM 提供商
    - tools: 工具集，包括 MCP (Model Context Protocol) 工具支持
    - utils: 引擎内部工具函数

导入路径变更说明:
    原路径 'tradingagents.*' 已迁移至 'app.engine.*'
    例如:
        - tradingagents.config.config_manager → app.engine.config.config_manager
        - tradingagents.tools.mcp → app.engine.tools.mcp

使用示例:
    from app.engine.config.config_manager import config_manager
    from app.engine.llm_adapters import get_llm_adapter

版本: 2.0.0
"""
