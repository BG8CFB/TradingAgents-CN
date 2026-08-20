def main():
    from app.engine.runtime import AnalysisRuntime
    from app.engine.default_config import DEFAULT_CONFIG
    from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
    import logging

    logging.getLogger('default')  # 初始化根日志器

    # Create a custom config
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "google"
    config["backend_url"] = "https://generativelanguage.googleapis.com/v1beta"
    config["debate_llm"] = "gemini-2.0-flash"
    config["analyst_llm"] = "gemini-2.0-flash"
    config["max_debate_rounds"] = 1
    config["online_tools"] = True

    # 阶段1智能体需从配置文件加载，避免硬编码
    selected_analysts = [a.get("slug") for a in DynamicAnalystFactory.get_all_agents() if a.get("slug")]
    if not selected_analysts:
        raise ValueError("未找到阶段1智能体配置，请先在 phase1_agents_config.yaml 中添加。")

    # Initialize with custom config
    ta = AnalysisRuntime(selected_analysts=selected_analysts, debug=True, config=config)

    # forward propagate
    _, decision = ta.propagate_sync("NVDA", "2024-05-10")
    print(decision)


if __name__ == "__main__":
    main()
