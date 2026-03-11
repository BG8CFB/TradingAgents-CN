def main():
    from app.engine.graph.trading_graph import TradingAgentsGraph
    from app.engine.default_config import DEFAULT_CONFIG
    from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
    from app.utils.logging_manager import get_logger

    logger = get_logger('default')

    # Create a custom config
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "google"
    config["backend_url"] = "https://generativelanguage.googleapis.com/v1beta"
    config["deep_think_llm"] = "gemini-2.0-flash"
    config["quick_think_llm"] = "gemini-2.0-flash"
    config["max_debate_rounds"] = 1
    config["online_tools"] = True

    # 阶段1智能体需从配置文件加载，避免硬编码
    selected_analysts = [a.get("slug") for a in DynamicAnalystFactory.get_all_agents() if a.get("slug")]
    if not selected_analysts:
        raise ValueError("未找到阶段1智能体配置，请先在 phase1_agents_config.yaml 中添加。")

    # Initialize with custom config
    ta = TradingAgentsGraph(selected_analysts=selected_analysts, debug=True, config=config)

    # forward propagate
    _, decision = ta.propagate("NVDA", "2024-05-10")
    print(decision)


if __name__ == "__main__":
    main()
