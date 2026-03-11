from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import time
import json
import os

# 导入统一日志系统
from app.utils.logging_init import get_logger
logger = get_logger("default")


def create_bull_researcher(llm, memory):
    def bull_node(state) -> dict:
        logger.debug(f"🐂 [DEBUG] ===== 看涨研究员节点开始 =====")
        
        investment_debate_state = state["investment_debate_state"]
        
        # 初始化多轮状态（如果是第一次进入）
        rounds = investment_debate_state.get("rounds", [])
        current_round_index = investment_debate_state.get("current_round_index", 0)
        max_rounds = investment_debate_state.get("max_rounds", 2)
        bull_report_content = investment_debate_state.get("bull_report_content", "")
        
        # 核心报告直读 - 动态获取所有第一阶段基础报告
        all_reports = {}
        
        # 优先从 reports 字典获取（这是最可靠的源，由 reducer 合并）
        if "reports" in state and isinstance(state["reports"], dict):
            all_reports.update(state["reports"])
            
        # 兼容性补充：检查顶层 state 中的 _report 字段
        for key, value in state.items():
            if key.endswith("_report") and value and key not in all_reports:
                all_reports[key] = value
        
        # 获取报告显示名称映射
        report_display_names = {}
        try:
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            for agent in DynamicAnalystFactory.get_all_agents():
                slug = agent.get('slug', '')
                name = agent.get('name', '')
                if slug and name:
                    internal_key = slug.replace("-analyst", "").replace("-", "_")
                    report_key = f"{internal_key}_report"
                    report_display_names[report_key] = f"{name}报告"
        except Exception as e:
            logger.warning(f"⚠️ 无法从配置文件加载报告显示名称: {e}")
        
        # 使用统一的股票类型检测
        ticker = state.get('company_of_interest', 'Unknown')
        from app.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)
        is_china = market_info['is_china']

        # 获取公司名称
        def _get_company_name(ticker_code: str, market_info_dict: dict) -> str:
            """根据股票代码获取公司名称"""
            try:
                if market_info_dict['is_china']:
                    from app.data.interface import get_china_stock_info_unified
                    stock_info = get_china_stock_info_unified(ticker_code)
                    if stock_info and "股票名称:" in stock_info:
                        name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                        return name
                    else:
                        # 降级方案
                        try:
                            from app.data.data_source_manager import get_china_stock_info_unified as get_info_dict
                            info_dict = get_info_dict(ticker_code)
                            if info_dict and info_dict.get('name'):
                                name = info_dict['name']
                                return name
                        except Exception:
                            pass
                elif market_info_dict['is_hk']:
                    try:
                        from app.data.providers.hk.improved_hk import get_hk_company_name_improved
                        name = get_hk_company_name_improved(ticker_code)
                        return name
                    except Exception:
                        clean_ticker = ticker_code.replace('.HK', '').replace('.hk', '')
                        return f"港股{clean_ticker}"
                elif market_info_dict['is_us']:
                    us_stock_names = {
                        'AAPL': '苹果公司', 'TSLA': '特斯拉', 'NVDA': '英伟达',
                        'MSFT': '微软', 'GOOGL': '谷歌', 'AMZN': '亚马逊',
                        'META': 'Meta', 'NFLX': '奈飞'
                    }
                    return us_stock_names.get(ticker_code.upper(), f"美股{ticker_code}")
            except Exception as e:
                logger.error(f"❌ [多头研究员] 获取公司名称失败: {e}")
            return f"股票代码{ticker_code}"

        company_name = _get_company_name(ticker, market_info)
        currency = market_info['currency_name']
        currency_symbol = market_info['currency_symbol']

        logger.info(f"🐂 [多头研究员] 当前轮次: {current_round_index}/{max_rounds}, 股票: {company_name}")

        # --- 1. 构建基础 Context (分批发送报告) ---
        from app.engine.agents.utils.generic_agent import load_agent_config
        base_prompt = load_agent_config("bull-researcher")
        
        if not base_prompt:
             error_msg = "❌ 未找到 bull-researcher 智能体配置，请检查 phase2_agents_config.yaml 文件。"
             logger.error(error_msg)
             raise ValueError(error_msg)

        # 动态构建环境上下文（KV 格式）
        context_prefix = f"""
股票代码：{ticker}
公司名称：{company_name}
价格单位：{currency}（{currency_symbol}）
通用规则：请始终使用公司名称而不是股票代码来称呼这家公司
"""
        
        # 将动态上下文拼接到配置指令前 (移除 round_info，保持 System Prompt 静态以命中缓存)
        system_prompt = context_prefix + "\n\n" + base_prompt
        
        messages = [SystemMessage(content=system_prompt)]
        
        # 分批注入 Stage 1 报告
        for key, content in all_reports.items():
            if content:
                # 使用映射获取显示名称，如果没有则格式化 key
                display_name = report_display_names.get(key, key.replace("_report", "").replace("_", " ").title() + "报告")
                messages.append(HumanMessage(content=f"这是【{display_name}】：\n{content}"))

        # --- 2. 注入辩论历史上下文 (Context Injection) ---
        # 关键修复：让 LLM 看到自己和对手之前的完整发言，防止逻辑断层
        if current_round_index > 0:
            logger.info(f"🐂 [多头研究员] 注入历史辩论上下文 (Rounds 0 to {current_round_index-1})")
            for i in range(current_round_index):
                if i < len(rounds):
                    round_data = rounds[i]
                    
                    # 1. 注入己方之前的观点 (Memory)
                    if "bull" in round_data:
                        prev_bull_content = round_data["bull"]
                        if i == 0:
                            prefix = "【回顾】这是我在【初始阶段】建立的核心论点："
                        else:
                            prefix = f"【回顾】这是我在【辩论第 {i} 轮】建立的论点："
                        # 使用 AIMessage 表示这是"我"之前说的话
                        messages.append(AIMessage(content=f"{prefix}\n{prev_bull_content}"))
                    
                    # 2. 注入对手之前的观点 (Counter-argument)
                    if "bear" in round_data:
                        prev_bear_content = round_data["bear"]
                        if i == 0:
                            prefix = "【回顾】这是对手（看跌分析师）在【初始阶段】提出的观点："
                        else:
                            prefix = f"【回顾】这是对手（看跌分析师）在【辩论第 {i} 轮】提出的观点："
                        # 使用 HumanMessage 表示这是对手说的话
                        messages.append(HumanMessage(content=f"{prefix}\n{prev_bear_content}"))

        # --- 3. 轮次触发指令 ---
        # 核心指令已移至 YAML System Prompt 中，这里仅作为触发器
        
        # 动态生成轮次说明（放在这里而不是 System Prompt，以利用 Context Caching）
        if current_round_index == 0:
            round_context = "当前分析阶段：初始观点陈述（基于第一阶段报告生成初始分析报告）"
            trigger_msg = f"{round_context}\n请基于提供的基础报告，撰写你的【初始分析报告】。重点阐述核心投资论点，构建完整的逻辑框架。本阶段暂不需要反驳对手（因为辩论尚未开始）。"
            argument_prefix = "# 【多头分析师 - 初始报告】"
        else:
            round_context = f"当前分析阶段：辩论第 {current_round_index} 轮（共 {max_rounds} 轮辩论）"
            trigger_msg = f"{round_context}\n现在是辩论第 {current_round_index} 轮。请严格按照 System Prompt 中的【任务指南】开始发言。"
            argument_prefix = f"# 【多头分析师 - 第 {current_round_index} 轮辩论】"
        
        if current_round_index > 0:
            # 再次提醒关注最新一轮的对手观点
            prev_round_idx = current_round_index - 1
            if prev_round_idx < len(rounds) and "bear" in rounds[prev_round_idx]:
                trigger_msg += "\n请特别注意反驳对手刚刚提出的最新观点（见上文）。"

        messages.append(HumanMessage(content=trigger_msg))

        # --- 4. 执行推理 ---
        response = llm.invoke(messages)
        content = response.content
        
        # 清洗内容：去除可能存在的报告大标题（如 "# 看涨分析报告"）
        lines = content.strip().split('\n')
        cleaned_lines = []
        for line in lines:
            # 去除以 # 开头但不是 ## 或 ### 的行（即一级标题）
            # 同时也去除包含 "看涨分析报告" 字样的标题行
            if line.strip().startswith("# ") or (line.strip().startswith("## ") and "分析报告" in line):
                continue
            cleaned_lines.append(line)
        content = '\n'.join(cleaned_lines).strip()
        
        # --- 4. 状态更新与报告累积 ---
        # 确保当前轮次的字典存在
        if current_round_index >= len(rounds):
            rounds.append({})
            
        # 存入纯文本供对手下一轮读取
        rounds[current_round_index]["bull"] = content
        
        # 累积到最终报告
        if current_round_index == 0:
            section_title = "## 初始报告：核心投资论点"
        else:
            section_title = f"## 第 {current_round_index} 轮辩论报告：针对空方观点的反驳与辩护"
        
        # 防重检查：如果报告中已包含当前章节标题，则不再重复添加
        if section_title in bull_report_content:
            logger.warning(f"🐂 [WARNING] 报告中已包含 Round {current_round_index} 内容，跳过追加。")
        else:
            new_report_section = f"\n\n{section_title}\n\n{content}"
            bull_report_content += new_report_section

        # --- 5. 文件保存 (如果需要) ---
        # 只有在最后一轮，或者每一轮都实时更新文件
        # 这里选择实时覆盖更新文件，保证用户随时能看到最新进度
        try:
            filename = "看涨分析报告.md"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# {company_name} ({ticker}) 看涨投资分析报告\n\n")
                f.write(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"> 货币单位：{currency}\n\n")
                f.write(bull_report_content)
            logger.info(f"🐂 [多头研究员] 已更新报告文件: {filename}")
        except Exception as e:
            logger.error(f"🐂 [ERROR] 保存报告文件失败: {e}")

        # 保持对旧 state 字段的兼容（防止其他节点报错）
        # 修复：使用更友好的中文标题替代 "Bull Analyst (Round X)"
        if current_round_index == 0:
            argument_prefix = "# 【多头分析师 - 初始报告】"
        else:
            argument_prefix = f"# 【多头分析师 - 第 {current_round_index} 轮辩论】"
            
        # 修复：移除内容截断，确保前端展示和历史记录完整
        argument = f"{argument_prefix}\n{content}"
        
        history = state["investment_debate_state"].get("history", "")
        bull_history = state["investment_debate_state"].get("bull_history", "")

        # 防重检查：如果历史记录中已包含当前轮次前缀，则不再重复添加
        if argument_prefix in bull_history:
            logger.warning(f"🐂 [WARNING] 历史记录中已包含 Round {current_round_index}，跳过追加。")
        else:
            history = history + "\n" + argument
            bull_history = bull_history + "\n" + argument

        new_investment_debate_state = {
            "history": history,
            "bull_history": bull_history,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state.get("count", 0) + 1,
            # 新字段更新
            "rounds": rounds,
            "bull_report_content": bull_report_content,
            "bear_report_content": investment_debate_state.get("bear_report_content", ""), # 保持不变
            "current_round_index": (investment_debate_state.get("count", 0) + 1) // 2, # 修复：确保下一轮索引正确更新
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            # 显式保存为报告，供前端展示
            "reports": {
                "bull_researcher": bull_report_content
            }
        }

    return bull_node
