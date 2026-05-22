# TradingAgents/graph/trading_graph.py

import os
from pathlib import Path
import json
import copy
from datetime import date
from typing import Dict, Any, Tuple, List, Optional
import time

from app.engine.llm_adapters import create_llm

from app.engine.agents import *
from app.engine.default_config import DEFAULT_CONFIG
from app.engine.agents.utils.memory import FinancialSituationMemory

# 导入统一日志系统
from app.utils.logging_init import get_logger
from app.utils.runtime_paths import get_cache_dir, get_eval_results_dir
logger = get_logger('agents')
from app.engine.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
import logging as _logging
_logger_compat = _logging.getLogger(__name__)
def _set_config_noop(config):
    """兼容旧版 set_config — 新架构通过 DataInterface 管理。"""
    _logger_compat.debug("set_config 兼容调用（空操作）")

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


def _classify_node(node_name: str) -> str:
    """将节点名称分类为类别标识"""
    if 'Risky' in node_name or 'Safe' in node_name or 'Neutral' in node_name or 'Risk Judge' in node_name:
        return "risk"
    if 'Analyst' in node_name:
        return "analyst"
    if node_name.startswith('tools_'):
        return "tool"
    if node_name.startswith('Msg Clear'):
        return "msg_clear"
    if 'Researcher' in node_name or 'Research Manager' in node_name:
        return "research"
    if 'Trader' in node_name:
        return "trader"
    return "other"


def _merge_state_update(target: Dict[str, Any], update: Dict[str, Any]) -> None:
    """安全合并节点增量到最终状态，确保 reports 和 messages 不会被后续节点覆盖。"""
    if target is None or not update:
        return

    if "reports" in update and isinstance(update.get("reports"), dict):
        existing_reports = target.get("reports") or {}
        target["reports"] = {**existing_reports, **update["reports"]}

    if "messages" in update and isinstance(update.get("messages"), list):
        existing_messages = target.get("messages") or []
        existing_ids = set()
        existing_content_sigs = set()
        for msg in existing_messages:
            msg_id = getattr(msg, 'id', None)
            if msg_id:
                existing_ids.add(msg_id)
            content_sig = (getattr(msg, 'type', ''), str(getattr(msg, 'content', ''))[:200])
            existing_content_sigs.add(content_sig)

        new_messages = []
        for msg in update["messages"]:
            msg_id = getattr(msg, 'id', None)
            content_sig = (getattr(msg, 'type', ''), str(getattr(msg, 'content', ''))[:200])
            if msg_id and msg_id in existing_ids:
                continue
            if not msg_id and content_sig in existing_content_sigs:
                continue
            new_messages.append(msg)
        target["messages"] = existing_messages + new_messages

    if "error" in update and update["error"]:
        existing_errors = target.get("error") or []
        if isinstance(existing_errors, str):
            existing_errors = [existing_errors]
        elif not isinstance(existing_errors, list):
            existing_errors = [str(existing_errors)]
        if isinstance(update["error"], str):
            update_errors = [update["error"]]
        elif isinstance(update["error"], list):
            update_errors = update["error"]
        else:
            update_errors = [str(update["error"])]
        target["error"] = existing_errors + update_errors

    for k, v in update.items():
        if k in ("reports", "messages", "error"):
            continue
        target[k] = v


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=None,
        debug=False,
        config: Dict[str, Any] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        if not selected_analysts:
            raise ValueError("selected_analysts 不能为空，请先配置阶段1分析师。")

        # 如果外部已注入 loader 但未显式开启开关，则自动开启
        if self.config.get("mcp_tool_loader") and not self.config.get("enable_mcp", False):
            self.config["enable_mcp"] = True
            logger.info("🔧 [TradingGraph] 检测到 MCP loader，已自动启用 MCP 工具")

        # Update the interface's config
        _set_config_noop(self.config)

        # Create necessary directories
        cache_root = self.config.get("data_cache_dir") or str(get_cache_dir() / "dataflows")
        os.makedirs(cache_root, exist_ok=True)

        # Initialize LLMs — 使用统一工厂函数创建所有 provider 的 LLM
        analyst_config = self.config.get("analyst_model_config", {})
        debate_config = self.config.get("debate_model_config", {})

        analyst_max_tokens = analyst_config.get("max_tokens", 4000)
        analyst_temperature = analyst_config.get("temperature", 0.7)
        analyst_timeout = analyst_config.get("timeout", 180)

        debate_max_tokens = debate_config.get("max_tokens", 4000)
        debate_temperature = debate_config.get("temperature", 0.7)
        debate_timeout = debate_config.get("timeout", 180)

        # 从 config 中读取 provider 和 model 信息
        # 优先使用 analysis_service 设置的 analyst_provider/debate_provider（精确的 per-model provider）
        # 回退到 llm_provider（全局 provider，兼容旧配置）
        analyst_provider = self.config.get("analyst_provider") or self.config.get("llm_provider", "openai")
        debate_provider = self.config.get("debate_provider") or self.config.get("llm_provider", "openai")

        logger.info(f"[LLM初始化] 分析师: {self.config['analyst_llm']} ({analyst_provider})")
        logger.info(f"[LLM初始化] 辩论推理: {self.config['debate_llm']} ({debate_provider})")

        self.analyst_llm = create_llm(
            provider=analyst_provider,
            model=self.config["analyst_llm"],
            api_key=self.config.get("analyst_api_key"),
            base_url=self.config.get("analyst_backend_url") or self.config.get("backend_url"),
            temperature=analyst_temperature,
            max_tokens=analyst_max_tokens,
            timeout=analyst_timeout,
        )

        self.debate_llm = create_llm(
            provider=debate_provider,
            model=self.config["debate_llm"],
            api_key=self.config.get("debate_api_key"),
            base_url=self.config.get("debate_backend_url") or self.config.get("backend_url"),
            temperature=debate_temperature,
            max_tokens=debate_max_tokens,
            timeout=debate_timeout,
        )

        logger.info("[LLM初始化] 完成")
        
        self.toolkit = Toolkit(config=self.config)

        # Initialize memories (如果启用)
        memory_enabled = self.config.get("memory_enabled", True)
        if memory_enabled:
            # 使用单例ChromaDB管理器，避免并发创建冲突
            self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
            self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
            self.trader_memory = FinancialSituationMemory("trader_memory", self.config)
            self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", self.config)
            self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory", self.config)
        else:
            # 创建空的内存对象
            self.bull_memory = None
            self.bear_memory = None
            self.trader_memory = None
            self.invest_judge_memory = None
            self.risk_manager_memory = None

        # Create tool nodes
        # 🔥 子图模式：每个分析师子图内部处理工具调用，不再需要外部 ToolNode

        # Initialize components
        # 🔥 [修复] 从配置中读取辩论轮次参数 (优先使用阶段配置)
        # 注意：用户配置的是"辩论轮次"（不含初始报告），内部逻辑需要+1（包含初始报告轮）
        max_debate_rounds = self.config.get("phase2_debate_rounds")
        if max_debate_rounds is None:
             max_debate_rounds = self.config.get("max_debate_rounds", 1)
        
        # 确保转换为整数
        if max_debate_rounds is not None:
            max_debate_rounds = int(max_debate_rounds)
        
        if self.config.get("phase2_enabled") is False:
             max_debate_rounds = 0
             
        max_risk_rounds = self.config.get("phase3_debate_rounds")
        if max_risk_rounds is None:
             max_risk_rounds = self.config.get("max_risk_discuss_rounds", 1)
             
        if self.config.get("phase3_enabled") is False:
             max_risk_rounds = 0

        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=max_debate_rounds,
            max_risk_discuss_rounds=max_risk_rounds
        )
        logger.info(f"🔧 [ConditionalLogic] 初始化完成:")
        logger.info(f"   - max_debate_rounds: {self.conditional_logic.max_debate_rounds}")
        logger.info(f"   - max_risk_discuss_rounds: {self.conditional_logic.max_risk_discuss_rounds}")

        self.graph_setup = GraphSetup(
            self.analyst_llm,
            self.debate_llm,
            self.toolkit,
            self.bull_memory,
            self.bear_memory,
            self.trader_memory,
            self.invest_judge_memory,
            self.risk_manager_memory,
            self.conditional_logic,
            self.config,
            getattr(self, 'react_llm', None),
        )

        self.propagator = Propagator()
        self.reflector = Reflector(self.debate_llm)
        self.signal_processor = SignalProcessor(self.debate_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph
        import time
        setup_start = time.time()
        logger.info(f"⏱️ [性能追踪] 开始 setup_graph，分析师数量: {len(selected_analysts)}")
        self.graph = self.graph_setup.setup_graph(selected_analysts)
        setup_elapsed = time.time() - setup_start
        logger.info(f"⏱️ [性能追踪] setup_graph 完成，耗时: {setup_elapsed:.2f} 秒")
        if setup_elapsed > 30:
            logger.warning(f"⚠️ [性能瓶颈] setup_graph 耗时 {setup_elapsed:.2f} 秒！")

    def propagate(self, company_name, trade_date, progress_callback=None, task_id=None):
        """Run the trading agents graph for a company on a specific date.

        Args:
            company_name: Company name or stock symbol
            trade_date: Date for analysis
            progress_callback: Optional callback function for progress updates
            task_id: Optional task ID for tracking performance data
        """

        # 注册进度回调到全局管理器
        from app.engine.agents.analysts.dynamic_analyst import ProgressManager
        if progress_callback:
            # 使用 task_id 隔离不同任务的回调，支持并发安全
            effective_task_id = task_id or id(progress_callback)
            ProgressManager.set_callback(effective_task_id, progress_callback)
            logger.debug(f"🔧 [进度管理器] 已注册进度回调, task_id={effective_task_id}")

        # 添加详细的接收日志
        logger.debug(f"🔍 [GRAPH DEBUG] ===== TradingAgentsGraph.propagate 接收参数 =====")
        logger.debug(f"🔍 [GRAPH DEBUG] 接收到的company_name: '{company_name}' (类型: {type(company_name)})")
        logger.debug(f"🔍 [GRAPH DEBUG] 接收到的trade_date: '{trade_date}' (类型: {type(trade_date)})")
        logger.debug(f"🔍 [GRAPH DEBUG] 接收到的task_id: '{task_id}'")

        self.ticker = company_name
        logger.debug(f"🔍 [GRAPH DEBUG] 设置self.ticker: '{self.ticker}'")

        # 分析前刷新核心数据域（非阻塞，刷新失败不中断分析）
        try:
            import asyncio
            from app.data.core.interface import DataInterface

            symbol = company_name
            di = DataInterface.get_instance()

            async def _do_refresh():
                return await di.refresh("CN", symbol, domains=["daily_quotes", "daily_indicators"], force=False, timeout=30)

            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    refresh_result = loop.run_in_executor(
                        pool, lambda: asyncio.run(_do_refresh())
                    )
                logger.info("📊 [数据刷新] %s 后台刷新已提交", symbol)
            except RuntimeError:
                refresh_result = asyncio.run(_do_refresh())
                logger.info(
                    "📊 [数据刷新] %s 刷新结果: %s (%dms)",
                    symbol, refresh_result.status, refresh_result.total_latency_ms,
                )
        except Exception as refresh_err:
            logger.warning(f"⚠️ [数据刷新] 刷新失败，使用现有数据: {refresh_err}")

        # Initialize state
        logger.debug(f"🔍 [GRAPH DEBUG] 创建初始状态，传递参数: company_name='{company_name}', trade_date='{trade_date}'")
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date, task_id=task_id
        )

        # 注入阶段配置参数到初始状态 (交易员始终执行，phase4 固定为 True)
        init_agent_state["phase2_enabled"] = self.config.get("phase2_enabled", False)
        init_agent_state["phase3_enabled"] = self.config.get("phase3_enabled", False)
        init_agent_state["phase4_enabled"] = True

        logger.debug(f"🔍 [GRAPH DEBUG] 初始状态中的company_of_interest: '{init_agent_state.get('company_of_interest', 'NOT_FOUND')}'")
        logger.debug(f"🔍 [GRAPH DEBUG] 初始状态中的trade_date: '{init_agent_state.get('trade_date', 'NOT_FOUND')}'")
        logger.debug(f"🔍 [GRAPH DEBUG] 阶段配置注入状态: P2={init_agent_state['phase2_enabled']}, P3={init_agent_state['phase3_enabled']}, P4={init_agent_state['phase4_enabled']}")

        # 初始化计时器
        node_timings = {}  # 记录每个节点的执行时间
        total_start_time = time.time()  # 总体开始时间
        current_node_start = None  # 当前节点开始时间
        current_node_name = None  # 当前节点名称

        # 保存task_id用于后续保存性能数据
        self._current_task_id = task_id

        # 根据是否有进度回调选择不同的stream_mode
        args = self.propagator.get_graph_args(use_progress_callback=bool(progress_callback))

        if not progress_callback:
            logger.info("⏱️ 使用 stream 模式执行分析（无进度回调）")

        trace = []
        final_state = None
        is_updates_mode = args.get("stream_mode") == "updates"

        try:
            for chunk in self.graph.stream(init_agent_state, **args):
                # ---- 节点计时 ----
                for node_name in chunk.keys():
                    if not node_name.startswith('__'):
                        if current_node_name and current_node_start:
                            elapsed = time.time() - current_node_start
                            node_timings[current_node_name] = elapsed
                            logger.info(f"⏱️ [{current_node_name}] 耗时: {elapsed:.2f}秒")
                            if progress_callback:
                                logger.info(f"🔍 [TIMING] 节点切换: {current_node_name} → {node_name}")

                        current_node_name = node_name
                        current_node_start = time.time()
                        if progress_callback:
                            logger.info(f"🔍 [TIMING] 开始计时: {node_name}")
                        break

                # ---- 进度回调 ----
                if progress_callback:
                    self._send_progress_update(chunk, progress_callback)

                # ---- 状态累积 ----
                if is_updates_mode or progress_callback:
                    # updates 模式：chunk = {node_name: state_update}
                    if final_state is None:
                        final_state = copy.deepcopy(init_agent_state)
                    for node_name, node_update in chunk.items():
                        if not node_name.startswith('__'):
                            _merge_state_update(final_state, node_update)
                else:
                    # values 模式：chunk = 完整状态
                    if self.debug:
                        if len(chunk.get("messages", [])) > 0:
                            chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
                    final_state = chunk
        except Exception as e:
            logger.error(f"❌ 分析流程执行异常: {e}")
            raise
        finally:
            if progress_callback:
                effective_task_id = task_id or id(progress_callback)
                ProgressManager.clear_callback(effective_task_id)
                logger.debug(f"🔧 [进度管理器] 已清除进度回调, task_id={effective_task_id}")

        # values 模式 + trace：使用最后一个完整状态
        if trace and not is_updates_mode and not progress_callback:
            final_state = trace[-1]

        # 记录最后一个节点的时间
        if current_node_name and current_node_start:
            elapsed = time.time() - current_node_start
            node_timings[current_node_name] = elapsed
            logger.info(f"⏱️ [{current_node_name}] 耗时: {elapsed:.2f}秒")

        # 🔥 将 reports 字典中的动态报告回填到顶层 *_report 字段（支持自定义智能体）
        if final_state is None:
            logger.error("final_state 为 None，分析流程未产生任何输出")
            final_state = {}
        merged_reports = final_state.get("reports") or {}
        for report_key, report_content in merged_reports.items():
            if (
                report_key.endswith("_report")
                and report_content
                and not final_state.get(report_key)
            ):
                final_state[report_key] = report_content

        # 计算总时间
        total_elapsed = time.time() - total_start_time

        # 调试日志
        logger.info(f"🔍 [TIMING DEBUG] 节点计时数量: {len(node_timings)}")
        logger.info(f"🔍 [TIMING DEBUG] 总耗时: {total_elapsed:.2f}秒")
        logger.info(f"🔍 [TIMING DEBUG] 节点列表: {list(node_timings.keys())}")

        # 打印详细的时间统计
        logger.info("🔍 [TIMING DEBUG] 准备调用 _print_timing_summary")
        self._print_timing_summary(node_timings, total_elapsed)
        logger.info("🔍 [TIMING DEBUG] _print_timing_summary 调用完成")

        # 构建性能数据
        performance_data = self._build_performance_data(node_timings, total_elapsed)

        # 将性能数据添加到状态中
        final_state['performance_metrics'] = performance_data

        # Store current state for reflection
        self.curr_state = final_state

        # Log state
        self._log_state(trade_date, final_state)

        # 获取模型信息
        model_info = ""
        try:
            if hasattr(self.debate_llm, 'model_name'):
                model_info = f"{self.debate_llm.__class__.__name__}:{self.debate_llm.model_name}"
            else:
                model_info = self.debate_llm.__class__.__name__
        except Exception:
            model_info = "Unknown"

        # 处理决策并添加模型信息（兼容未启用后续阶段）
        final_signal = (
            final_state.get("final_trade_decision")
            or final_state.get("investment_plan")
            or (final_state.get("risk_debate_state") or {}).get("judge_decision")
            or final_state.get("trader_investment_plan")
            or ""
        )
        if final_signal:
            decision = self.process_signal(final_signal, company_name)
        else:
            decision = {
                "action": "观望",
                "target_price": None,
                "confidence": 0,
                "risk_score": 0,
                "risk_level": "未知",
                "reasoning": "未开启深度决策阶段，未生成最终决策",
                "reason": "未开启深度决策阶段，未生成最终决策",
            }
        decision["model_info"] = model_info

        # Return decision and processed signal
        return final_state, decision

    def _send_progress_update(self, chunk, progress_callback):
        """发送进度更新到回调函数

        LangGraph stream 返回的 chunk 格式：{node_name: {...}}
        节点名称示例：
        - "Market Analyst", "Fundamentals Analyst", "News Analyst", "Social Analyst"
        - "tools_market", "tools_fundamentals", "tools_news", "tools_social"
        - "Msg Clear Market", "Msg Clear Fundamentals", etc.
        - "Bull Researcher", "Bear Researcher", "Research Manager"
        - "Trader"
        - "Risky Analyst", "Safe Analyst", "Neutral Analyst", "Risk Judge"
        """
        try:
            # 从chunk中提取当前执行的节点信息
            if not isinstance(chunk, dict):
                return

            # 获取第一个非特殊键作为节点名
            node_name = None
            for key in chunk.keys():
                if not key.startswith('__'):
                    node_name = key
                    break

            if not node_name:
                return

            logger.info(f"🔍 [Progress] 节点名称: {node_name}")

            # 检查是否为结束节点
            if '__end__' in chunk:
                logger.info(f"📊 [Progress] 检测到__end__节点")
                progress_callback("📊 生成报告")
                return

            # 动态构建节点名称映射表（从配置文件加载）
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            node_mapping = DynamicAnalystFactory.build_node_mapping()

            # 查找映射的消息
            message = node_mapping.get(node_name)

            if message is None:
                # None 表示跳过（工具节点、消息清理节点）
                logger.debug(f"⏭️ [Progress] 跳过节点: {node_name}")
                return

            if message:
                # 发送进度更新
                logger.info(f"📤 [Progress] 发送进度更新: {message}")
                progress_callback(message)
            else:
                # 未知节点，使用节点名称
                logger.warning(f"⚠️ [Progress] 未知节点: {node_name}")
                progress_callback(f"🔍 {node_name}")

        except Exception as e:
            logger.error(f"❌ 进度更新失败: {e}", exc_info=True)

    def _build_performance_data(self, node_timings: Dict[str, float], total_elapsed: float) -> Dict[str, Any]:
        """构建性能数据结构

        Args:
            node_timings: 每个节点的执行时间字典
            total_elapsed: 总执行时间

        Returns:
            性能数据字典
        """
        analyst_nodes = {}
        tool_nodes = {}
        msg_clear_nodes = {}
        research_nodes = {}
        trader_nodes = {}
        risk_nodes = {}
        other_nodes = {}

        for node_name, elapsed in node_timings.items():
            cat = _classify_node(node_name)
            target = {
                "analyst": analyst_nodes, "tool": tool_nodes,
                "msg_clear": msg_clear_nodes, "research": research_nodes,
                "trader": trader_nodes, "risk": risk_nodes, "other": other_nodes,
            }.get(cat, other_nodes)
            target[node_name] = elapsed

        # 计算统计数据
        slowest_node = max(node_timings.items(), key=lambda x: x[1]) if node_timings else (None, 0)
        fastest_node = min(node_timings.items(), key=lambda x: x[1]) if node_timings else (None, 0)
        avg_time = sum(node_timings.values()) / len(node_timings) if node_timings else 0

        return {
            "total_time": round(total_elapsed, 2),
            "total_time_minutes": round(total_elapsed / 60, 2),
            "node_count": len(node_timings),
            "average_node_time": round(avg_time, 2),
            "slowest_node": {
                "name": slowest_node[0],
                "time": round(slowest_node[1], 2)
            } if slowest_node[0] else None,
            "fastest_node": {
                "name": fastest_node[0],
                "time": round(fastest_node[1], 2)
            } if fastest_node[0] else None,
            "node_timings": {k: round(v, 2) for k, v in node_timings.items()},
            "category_timings": {
                "analyst_team": {
                    "nodes": {k: round(v, 2) for k, v in analyst_nodes.items()},
                    "total": round(sum(analyst_nodes.values()), 2),
                    "percentage": round(sum(analyst_nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
                },
                "tool_calls": {
                    "nodes": {k: round(v, 2) for k, v in tool_nodes.items()},
                    "total": round(sum(tool_nodes.values()), 2),
                    "percentage": round(sum(tool_nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
                },
                "message_clearing": {
                    "nodes": {k: round(v, 2) for k, v in msg_clear_nodes.items()},
                    "total": round(sum(msg_clear_nodes.values()), 2),
                    "percentage": round(sum(msg_clear_nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
                },
                "research_team": {
                    "nodes": {k: round(v, 2) for k, v in research_nodes.items()},
                    "total": round(sum(research_nodes.values()), 2),
                    "percentage": round(sum(research_nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
                },
                "trader_team": {
                    "nodes": {k: round(v, 2) for k, v in trader_nodes.items()},
                    "total": round(sum(trader_nodes.values()), 2),
                    "percentage": round(sum(trader_nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
                },
                "risk_management_team": {
                    "nodes": {k: round(v, 2) for k, v in risk_nodes.items()},
                    "total": round(sum(risk_nodes.values()), 2),
                    "percentage": round(sum(risk_nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
                },
                "other": {
                    "nodes": {k: round(v, 2) for k, v in other_nodes.items()},
                    "total": round(sum(other_nodes.values()), 2),
                    "percentage": round(sum(other_nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
                }
            },
            "llm_config": {
                "provider": self.config.get('llm_provider', 'unknown'),
                "debate_model": self.config.get('debate_llm', 'unknown'),
                "analyst_model": self.config.get('analyst_llm', 'unknown')
            }
        }

    def _print_timing_summary(self, node_timings: Dict[str, float], total_elapsed: float):
        """打印详细的时间统计报告"""
        logger.info("=" * 80)
        logger.info("⏱️  分析性能统计报告")
        logger.info("=" * 80)

        categories = {"analyst": [], "tool": [], "msg_clear": [], "research": [], "trader": [], "risk": [], "other": []}
        for node_name, elapsed in node_timings.items():
            categories.setdefault(_classify_node(node_name), categories["other"]).append((node_name, elapsed))

        def print_category(title: str, nodes: List[Tuple[str, float]]):
            if not nodes:
                return
            logger.info(f"\n📊 {title}")
            logger.info("-" * 80)
            total_category_time = sum(t for _, t in nodes)
            for node_name, elapsed in sorted(nodes, key=lambda x: x[1], reverse=True):
                percentage = (elapsed / total_elapsed * 100) if total_elapsed > 0 else 0
                logger.info(f"  • {node_name:40s} {elapsed:8.2f}秒  ({percentage:5.1f}%)")
            logger.info(f"  {'小计':40s} {total_category_time:8.2f}秒  ({total_category_time/total_elapsed*100:5.1f}%)")

        print_category("分析师团队", categories["analyst"])
        print_category("工具调用", categories["tool"])
        print_category("消息清理", categories["msg_clear"])
        print_category("研究团队", categories["research"])
        print_category("交易团队", categories["trader"])
        print_category("风险管理团队", categories["risk"])
        print_category("其他节点", categories["other"])

        # 打印总体统计
        logger.info("\n" + "=" * 80)
        logger.info(f"🎯 总执行时间: {total_elapsed:.2f}秒 ({total_elapsed/60:.2f}分钟)")
        logger.info(f"📈 节点总数: {len(node_timings)}")
        if node_timings:
            avg_time = sum(node_timings.values()) / len(node_timings)
            logger.info(f"⏱️  平均节点耗时: {avg_time:.2f}秒")
            slowest_node = max(node_timings.items(), key=lambda x: x[1])
            logger.info(f"🐌 最慢节点: {slowest_node[0]} ({slowest_node[1]:.2f}秒)")
            fastest_node = min(node_timings.items(), key=lambda x: x[1])
            logger.info(f"⚡ 最快节点: {fastest_node[0]} ({fastest_node[1]:.2f}秒)")

        # 打印LLM配置信息
        logger.info(f"\n🤖 LLM配置:")
        logger.info(f"  • 提供商: {self.config.get('llm_provider', 'unknown')}")
        logger.info(f"  • 辩论推理模型: {self.config.get('debate_llm', 'unknown')}")
        logger.info(f"  • 分析师模型: {self.config.get('analyst_llm', 'unknown')}")
        logger.info("=" * 80)

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        inv_state = final_state.get("investment_debate_state") or {}
        risk_state = final_state.get("risk_debate_state") or {}

        def _safe(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else default

        # 🔥 动态发现所有 *_report 字段，自动支持新添加的分析师报告
        all_reports = {}
        for key in final_state.keys():
            if key.endswith("_report"):
                all_reports[key] = final_state.get(key, "")
        
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state.get("company_of_interest", ""),
            "trade_date": final_state.get("trade_date", ""),
            **all_reports,  # 🔥 动态包含所有报告
            "investment_debate_state": {
                "bull_history": _safe(inv_state, "bull_history"),
                "bear_history": _safe(inv_state, "bear_history"),
                "history": _safe(inv_state, "history"),
                "current_response": _safe(inv_state, "current_response"),
                "judge_decision": _safe(inv_state, "judge_decision"),
            },
            "trader_investment_decision": final_state.get(
                "trader_investment_plan", ""
            ),
            "risk_debate_state": {
                "risky_history": _safe(risk_state, "risky_history"),
                "safe_history": _safe(risk_state, "safe_history"),
                "neutral_history": _safe(risk_state, "neutral_history"),
                "history": _safe(risk_state, "history"),
                "judge_decision": _safe(risk_state, "judge_decision"),
            },
            "investment_plan": final_state.get("investment_plan", ""),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
        }

        # Save to file
        base_dir = get_eval_results_dir()
        directory = base_dir / self.ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_file = directory / "full_states_log.json"
        with log_file.open("w") as f:
            json.dump(self.log_states_dict, f, indent=4)

    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        if not self.curr_state:
            return

        inv_state = self.curr_state.get("investment_debate_state") or {}
        risk_state = self.curr_state.get("risk_debate_state") or {}

        # 仅在对应阶段参与时才写入记忆，避免缺失字段报错
        if inv_state and self.bull_memory:
            self.reflector.reflect_bull_researcher(
                self.curr_state, returns_losses, self.bull_memory
            )
        if inv_state and self.bear_memory:
            self.reflector.reflect_bear_researcher(
                self.curr_state, returns_losses, self.bear_memory
            )
        if inv_state and self.invest_judge_memory:
            self.reflector.reflect_invest_judge(
                self.curr_state, returns_losses, self.invest_judge_memory
            )

        if self.curr_state.get("trader_investment_plan") and self.trader_memory:
            self.reflector.reflect_trader(
                self.curr_state, returns_losses, self.trader_memory
            )

        if risk_state and self.risk_manager_memory:
            self.reflector.reflect_risk_manager(
                self.curr_state, returns_losses, self.risk_manager_memory
            )

    def process_signal(self, full_signal, stock_symbol=None):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal, stock_symbol)
