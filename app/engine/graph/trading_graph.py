# TradingAgents/graph/trading_graph.py
# 手写编排入口（orchestrator/pipeline）— LangGraph/langchain 已完全移除

import asyncio
import json
import os
import time
from typing import Any, Dict

from app.engine.agents.utils.agent_utils import Toolkit
from app.engine.agents.utils.memory import FinancialSituationMemory
from app.engine.default_config import DEFAULT_CONFIG
from app.engine.orchestrator.pipeline import PipelineDeps, run_pipeline
from app.utils.logging_init import get_logger
from app.utils.runtime_paths import get_eval_results_dir

logger = get_logger("agents")


def _classify_node(node_name: str) -> str:
    """将节点名称分类为类别标识（节点命名与旧图一致）"""
    if "Risky" in node_name or "Safe" in node_name or "Neutral" in node_name or "Risk Judge" in node_name:
        return "risk"
    if "Analyst" in node_name:
        return "analyst"
    if "Researcher" in node_name or "Research Manager" in node_name:
        return "research"
    if "Trader" in node_name:
        return "trader"
    return "other"


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=None,
        debug=False,
        config: Dict[str, Any] = None,
    ):
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        if not selected_analysts:
            raise ValueError("selected_analysts 不能为空，请先配置阶段1分析师。")

        self.selected_analysts = list(selected_analysts)

        # 如果外部已注入 MCP 开关
        if self.config.get("mcp_tool_loader") and not self.config.get("enable_mcp", False):
            self.config["enable_mcp"] = True
            logger.info("🔧 [TradingGraph] 检测到 MCP 配置，已自动启用 MCP 工具")

        # Create necessary directories
        cache_root = self.config.get("data_cache_dir") or str(get_eval_results_dir().parent / "cache" / "dataflows")
        os.makedirs(cache_root, exist_ok=True)

        self.toolkit = Toolkit(config=self.config)

        # Initialize memories（如果启用）
        memory_enabled = self.config.get("memory_enabled", True)
        if memory_enabled:
            self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
            self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
            self.trader_memory = FinancialSituationMemory("trader_memory", self.config)
            self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", self.config)
            self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory", self.config)
        else:
            self.bull_memory = None
            self.bear_memory = None
            self.trader_memory = None
            self.invest_judge_memory = None
            self.risk_manager_memory = None

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}

    # ── 客户端解析 ────────────────────────────────────────────────────

    async def _resolve_clients(self) -> Dict[str, Any]:
        """数据库模型配置优先（providers.get_engine_clients），
        任务级 config 显式指定 provider/model/api_key 时覆盖。"""
        from app.llm.providers import get_engine_clients, resolve_task_override_bundle

        clients = await get_engine_clients()

        async def _override(role: str):
            model = self.config.get(f"{role}_llm")
            if not model or model == "default":
                return
            provider = self.config.get(f"{role}_provider") or self.config.get("llm_provider", "openai")
            api_key = self.config.get(f"{role}_api_key") or self.config.get("api_key")
            base_url = (
                self.config.get(f"{role}_backend_url")
                or self.config.get("backend_url")
            )
            # 经 providers 解析：从数据库同模型配置继承 max_tokens 等每模型参数，
            # 避免覆盖路径丢失 DB 参数回落 .env 默认 4096（推理模型截断空响应）
            bundle = await resolve_task_override_bundle(
                model, provider=provider, api_key=api_key or None, base_url=base_url or None
            )
            if bundle is None:
                return  # 无凭据时沿用数据库配置
            clients[role] = bundle
            logger.info(f"[LLM初始化] {role}: {getattr(bundle, 'protocol', 'unknown')}:{model} (任务配置覆盖)")

        await _override("analyst")
        await _override("debate")
        return clients

    # ── 主入口 ────────────────────────────────────────────────────────

    def propagate(self, company_name, trade_date, progress_callback=None, task_id=None, event_sink=None, user_id=None):
        """Run the analysis pipeline for a company on a specific date."""
        from app.engine.agents.analysts.dynamic_analyst import ProgressManager

        logger.debug(
            f"🔍 [GRAPH DEBUG] propagate: company='{company_name}', "
            f"trade_date='{trade_date}', task_id='{task_id}'"
        )
        self.ticker = company_name

        effective_task_id = None
        if progress_callback:
            effective_task_id = task_id or id(progress_callback)

        total_start_time = time.time()
        self._current_task_id = task_id

        async def _run() -> Dict[str, Any]:
            clients = await self._resolve_clients()
            self._last_debate_client = clients["debate"]
            deps = PipelineDeps(
                analyst_client=clients["analyst"],
                debate_client=clients["debate"],
                toolkit=self.toolkit,
                bull_memory=self.bull_memory,
                bear_memory=self.bear_memory,
                trader_memory=self.trader_memory,
                invest_judge_memory=self.invest_judge_memory,
                risk_manager_memory=self.risk_manager_memory,
                config=self.config,
            )
            return await run_pipeline(
                deps,
                company_name,
                trade_date,
                self.selected_analysts,
                task_id=task_id,
                progress_callback=progress_callback,
                event_sink=event_sink,
                user_id=user_id,
            )

        try:
            if effective_task_id is not None:
                ProgressManager.set_callback(effective_task_id, progress_callback)
            final_state = asyncio.run(_run())
        except Exception as e:
            logger.error(f"❌ 分析流程执行异常: {e}")
            e.partial_state = getattr(e, "partial_state", None)  # type: ignore[attr-defined]
            raise
        finally:
            if effective_task_id is not None:
                ProgressManager.clear_callback(effective_task_id)

        if final_state is None:
            logger.error("final_state 为 None，分析流程未产生任何输出")
            final_state = {}

        total_elapsed = time.time() - total_start_time
        node_timings = final_state.get("node_timings") or {}
        self._print_timing_summary(node_timings, total_elapsed)

        performance_data = self._build_performance_data(node_timings, total_elapsed)
        final_state["performance_metrics"] = performance_data

        self.curr_state = final_state
        self._log_state(trade_date, final_state)

        model_info = ""
        try:
            debate_client = getattr(self, "_last_debate_client", None)
            if debate_client is not None:
                model_info = f"{type(debate_client).__name__}:{getattr(debate_client, 'model', '')}"
        except Exception as e:
            logger.debug(f"获取模型信息失败: {e}")
            model_info = "Unknown"

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

        return final_state, decision

    # ── 性能统计 ─────────────────────────────────────────────────────

    def _build_performance_data(self, node_timings: Dict[str, float], total_elapsed: float) -> Dict[str, Any]:
        analyst_nodes, research_nodes, trader_nodes, risk_nodes, other_nodes = {}, {}, {}, {}, {}
        for node_name, elapsed in node_timings.items():
            cat = _classify_node(node_name)
            target = {
                "analyst": analyst_nodes,
                "research": research_nodes,
                "trader": trader_nodes,
                "risk": risk_nodes,
            }.get(cat, other_nodes)
            target[node_name] = elapsed

        slowest = max(node_timings.items(), key=lambda x: x[1]) if node_timings else (None, 0)
        fastest = min(node_timings.items(), key=lambda x: x[1]) if node_timings else (None, 0)
        avg = sum(node_timings.values()) / len(node_timings) if node_timings else 0

        def _cat(nodes: Dict[str, float]) -> Dict[str, Any]:
            return {
                "nodes": {k: round(v, 2) for k, v in nodes.items()},
                "total": round(sum(nodes.values()), 2),
                "percentage": round(sum(nodes.values()) / total_elapsed * 100, 1) if total_elapsed > 0 else 0,
            }

        return {
            "total_time": round(total_elapsed, 2),
            "total_time_minutes": round(total_elapsed / 60, 2),
            "node_count": len(node_timings),
            "average_node_time": round(avg, 2),
            "slowest_node": {"name": slowest[0], "time": round(slowest[1], 2)} if slowest[0] else None,
            "fastest_node": {"name": fastest[0], "time": round(fastest[1], 2)} if fastest[0] else None,
            "node_timings": {k: round(v, 2) for k, v in node_timings.items()},
            "category_timings": {
                "analyst_team": _cat(analyst_nodes),
                "research_team": _cat(research_nodes),
                "trader_team": _cat(trader_nodes),
                "risk_management_team": _cat(risk_nodes),
                "other": _cat(other_nodes),
            },
            "llm_config": {
                "provider": self.config.get("llm_provider", "unknown"),
                "debate_model": self.config.get("debate_llm", "unknown"),
                "analyst_model": self.config.get("analyst_llm", "unknown"),
            },
        }

    def _print_timing_summary(self, node_timings: Dict[str, float], total_elapsed: float):
        logger.info("=" * 80)
        logger.info("⏱️  分析性能统计报告")
        logger.info("=" * 80)
        for node_name, elapsed in sorted(node_timings.items(), key=lambda x: x[1], reverse=True):
            pct = elapsed / total_elapsed * 100 if total_elapsed > 0 else 0
            logger.info(f"  • {node_name:40s} {elapsed:8.2f}秒  ({pct:5.1f}%)")
        logger.info("=" * 80)
        logger.info(f"🎯 总执行时间: {total_elapsed:.2f}秒 ({total_elapsed / 60:.2f}分钟)")
        logger.info(f"📈 节点总数: {len(node_timings)}")

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        inv_state = final_state.get("investment_debate_state") or {}
        risk_state = final_state.get("risk_debate_state") or {}

        def _safe(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else default

        all_reports = {
            key: final_state.get(key, "")
            for key in final_state.keys()
            if key.endswith("_report")
        }

        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state.get("company_of_interest", ""),
            "trade_date": final_state.get("trade_date", ""),
            **all_reports,
            "investment_debate_state": {
                "bull_history": _safe(inv_state, "bull_history"),
                "bear_history": _safe(inv_state, "bear_history"),
                "history": _safe(inv_state, "history"),
                "current_response": _safe(inv_state, "current_response"),
                "judge_decision": _safe(inv_state, "judge_decision"),
            },
            "trader_investment_decision": final_state.get("trader_investment_plan", ""),
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

        base_dir = get_eval_results_dir()
        directory = base_dir / (self.ticker or "unknown") / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_file = directory / "full_states_log.json"
        tmp_file = log_file.with_suffix(log_file.suffix + ".tmp")
        with tmp_file.open("w") as f:
            json.dump(self.log_states_dict, f, indent=4, ensure_ascii=False)
        os.replace(tmp_file, log_file)

    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        from .reflection import Reflector

        if not self.curr_state:
            return
        if not hasattr(self, "_reflector"):
            # 反思需要 LLM 客户端：用数据库配置解析
            reflector = None
            try:
                clients = asyncio.run(self._resolve_clients())
                reflector = Reflector(
                    clients["debate"],
                    task_id=self.curr_state.get("task_id") or "",
                    user_id=self.curr_state.get("user_id") or "",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"⚠️ 反思客户端初始化失败: {e}")
                return
            self._reflector = reflector

        inv_state = self.curr_state.get("investment_debate_state") or {}
        risk_state = self.curr_state.get("risk_debate_state") or {}

        if inv_state and self.bull_memory:
            self._reflector.reflect_bull_researcher(self.curr_state, returns_losses, self.bull_memory)
        if inv_state and self.bear_memory:
            self._reflector.reflect_bear_researcher(self.curr_state, returns_losses, self.bear_memory)
        if inv_state and self.invest_judge_memory:
            self._reflector.reflect_invest_judge(self.curr_state, returns_losses, self.invest_judge_memory)
        if self.curr_state.get("trader_investment_plan") and self.trader_memory:
            self._reflector.reflect_trader(self.curr_state, returns_losses, self.trader_memory)
        if risk_state and self.risk_manager_memory:
            self._reflector.reflect_risk_manager(self.curr_state, returns_losses, self.risk_manager_memory)

    def process_signal(self, full_signal, stock_symbol=None):
        """Process a signal to extract the core decision."""
        from .signal_processing import SignalProcessor

        if not hasattr(self, "_signal_processor"):
            try:
                clients = asyncio.run(self._resolve_clients())
                self._signal_processor = SignalProcessor(
                    clients["debate"],
                    task_id=(self.curr_state or {}).get("task_id") or "",
                    user_id=(self.curr_state or {}).get("user_id") or "",
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"❌ 信号处理客户端初始化失败: {e}")
                return {
                    "action": "持有",
                    "target_price": None,
                    "confidence": 0.5,
                    "risk_score": 0.5,
                    "reasoning": "信号处理初始化失败",
                }
        return self._signal_processor.process_signal(full_signal, stock_symbol)
