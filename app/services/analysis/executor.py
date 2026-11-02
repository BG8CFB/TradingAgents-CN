"""后台执行编排（自 analysis_service.py 拆分）。

职责：共享线程池调度（_execute_analysis_sync）、后台执行主流程
（execute_analysis_background：校验/进度跟踪/事件汇聚/结果保存/通知结算）、
同步执行实现（_run_analysis_sync：配置组装、MCP 注入、AnalysisRuntime 创建、
propagate_sync 调用）。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.engine.runtime import AnalysisRuntime
from app.llm.mcp import service as mcp_service
from app.models.analysis import AnalysisStatus, SingleAnalysisRequest
from app.models.notification import NotificationCreate
from app.services.analysis.providers import (
    _DEPRECATED_MODELS,
    _get_default_provider_by_model,
    create_analysis_config,
    get_provider_and_url_by_model_sync,
)
from app.services.memory_state_manager import TaskStatus
from app.services.progress.log_handler import (
    register_analysis_tracker,
    unregister_analysis_tracker,
)
from app.services.progress.tracker import RedisProgressTracker
from app.services.websocket_manager import get_websocket_manager
from app.utils.dataflow_utils import get_trading_date_range
from app.utils.stock_utils import StockUtils
from app.utils.timezone import format_date_short, now_config_tz, now_utc

logger = logging.getLogger(__name__)


class ExecutorMixin:
    """后台执行编排 mixin：线程池执行与同步分析主流程。"""

    def _get_trading_graph(self, config: Dict[str, Any]) -> AnalysisRuntime:
        """获取或创建TradingAgents实例 (每次创建新实例以保证线程安全)"""
        selected = config.get("selected_analysts") or []
        if not selected:
            raise ValueError("selected_analysts 不能为空，请先在阶段1配置分析师后再发起任务。")
        return AnalysisRuntime(selected_analysts=selected, debug=config.get("debug", False), config=config)

    def _auto_enable_mcp(self, config: Dict[str, Any], selected_tool_ids: Optional[List[str]] = None) -> None:
        """
        自动为分析任务注入 MCP 工具加载器：
        - 若用户未显式开启 MCP，但外部 MCP 工具可用，则启用并绑定 loader
        - 仅加载外部 MCP 工具（include_local=False），避免与本地 MCP 工具重复

        注意：MCP 连接在应用启动时已建立，此处直接使用已初始化的工厂
        """
        if config.get("enable_mcp"):
            return

        try:
            # 新层 MCPManager：有启用的 server 则启用，连接与工具发现由 orchestrator pipeline 执行
            enabled = mcp_service.enabled_server_configs()
            if enabled:
                config["enable_mcp"] = True
                config.setdefault("mcp_tool_ids", selected_tool_ids or [])
                logger.info(f"自动启用MCP工具: {len(enabled)} 个 server")
            else:
                logger.info("MCP支持已检测，无可用外部工具")
        except Exception as exc:
            logger.warning(f"自动注入MCP工具失败: {exc}")

    async def execute_analysis_background(self, task_id: str, user_id: str, request: SingleAnalysisRequest):
        """在后台执行分析任务 (Core Logic)"""
        stock_code = request.get_symbol()
        progress_tracker = None
        try:
            logger.info(f"🚀 开始后台执行分析任务: {task_id}")

            # 验证股票代码
            from app.utils.stock_validator import prepare_stock_data_async

            market_type = request.parameters.market_type if request.parameters else "A股"
            analysis_date = request.parameters.analysis_date if request.parameters else None

            if analysis_date and isinstance(analysis_date, datetime):
                analysis_date = analysis_date.strftime("%Y-%m-%d")
            elif analysis_date and isinstance(analysis_date, str):
                try:
                    parsed_date = datetime.strptime(analysis_date, "%Y-%m-%d")
                    analysis_date = parsed_date.strftime("%Y-%m-%d")
                except ValueError:
                    analysis_date = format_date_short(now_config_tz())

            validation_result = await prepare_stock_data_async(
                stock_code=stock_code,
                market_type=market_type,
                period_days=30,
                analysis_date=analysis_date,
            )

            if not validation_result.is_valid:
                error_msg = f"❌ 股票代码无效: {validation_result.error_message}"
                await self.memory_manager.update_task_status(
                    task_id=task_id,
                    status=AnalysisStatus.FAILED,
                    progress=0,
                    error_message=error_msg,
                )
                await self._update_task_status(task_id, AnalysisStatus.FAILED, 0, error_message=error_msg)
                return

            # 创建Redis进度跟踪器
            # 获取当前的 event loop (用于在子线程中调度 WebSocket 发送)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("无法获取当前事件循环，WebSocket 推送可能失效")
                loop = None

            # 阶段配置（与前端保持一致，交易员始终执行）
            phase_config = {
                "phase2_enabled": getattr(request.parameters, "phase2_enabled", False) if request.parameters else False,
                "phase2_debate_rounds": getattr(request.parameters, "phase2_debate_rounds", 2)
                if request.parameters
                else 1,
                "phase3_enabled": getattr(request.parameters, "phase3_enabled", False) if request.parameters else False,
                "phase3_debate_rounds": getattr(request.parameters, "phase3_debate_rounds", 2)
                if request.parameters
                else 1,
                "phase4_enabled": True,
                "phase4_debate_rounds": 1,
            }

            selected_analysts = (
                (request.parameters.selected_nodes or request.parameters.selected_analysts)
                if request.parameters
                else []
            ) or []
            if not selected_analysts:
                raise ValueError("selected_analysts 不能为空，请先在阶段1配置并选择分析师。")

            def progress_callback(data):
                """进度更新回调：通过 WebSocket 广播消息"""
                if not loop:
                    return
                try:
                    ws_manager = get_websocket_manager()
                    # 构造消息
                    message = {
                        "type": "progress_update",
                        "task_id": task_id,
                        "status": data.get("status"),
                        "progress": data.get("progress_percentage"),
                        "message": data.get("last_message"),
                        "current_step": data.get("current_step"),
                        "steps": data.get("steps"),
                    }
                    # 在主循环中调度发送任务
                    asyncio.run_coroutine_threadsafe(ws_manager.send_progress_update(task_id, message), loop)
                except Exception as e:
                    logger.error(f"WebSocket 广播失败: {e}", exc_info=True)

            def create_progress_tracker():
                return RedisProgressTracker(
                    task_id=task_id,
                    analysts=selected_analysts,
                    phase_config=phase_config,
                    llm_provider=_get_default_provider_by_model(
                        getattr(request.parameters, "analyst_model", "qwen-turbo")
                    ),
                    on_update=progress_callback,
                )

            progress_tracker = await asyncio.to_thread(create_progress_tracker)
            self._progress_trackers[task_id] = progress_tracker
            register_analysis_tracker(task_id, progress_tracker)

            # 更新初始状态
            await asyncio.to_thread(
                progress_tracker.update_progress,
                {"progress_percentage": 5, "last_message": "🚀 开始股票分析"},
            )
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.RUNNING,
                progress=5,
                message="分析开始...",
                current_step="initialization",
            )
            await self._update_task_status(task_id, AnalysisStatus.PROCESSING, 5)

            # 记录 MCP 工具选择（实际加载在同步执行阶段完成）
            selected_mcp_tools = []
            if request.parameters:
                selected_mcp_tools = (
                    getattr(request.parameters, "mcp_tool_ids", None)
                    or getattr(request.parameters, "mcp_tools", [])
                    or []
                )
                if selected_mcp_tools:
                    logger.info(f"MCP工具选择: {selected_mcp_tools}")

            # 执行实际分析
            result = await self._execute_analysis_sync(
                task_id,
                user_id,
                request,
                progress_tracker,
                mcp_tool_ids=selected_mcp_tools,
            )

            # 完成
            await asyncio.to_thread(progress_tracker.mark_completed)

            # 保存结果
            await self._save_analysis_results_complete(task_id, result)

            # 更新完成状态：内存只留摘要——全量 result（含 state/messages 大对象）
            # 已由 _save_analysis_results_complete 落入 analysis_reports 与
            # analysis_tasks.result，内存 LRU 驻留全量会放大数百 KB/任务的占用；
            # /result 端点读取全量时走 DB 路径
            result_summary = {
                "analysis_id": result.get("analysis_id"),
                "status": "completed",
                "progress": 100,
                "decision": result.get("decision"),
            }
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                message="分析完成",
                current_step="completed",
                result_data=result_summary,
            )
            await self._update_task_status(task_id, AnalysisStatus.COMPLETED, 100)

            # 结算登记：把本次合格决策写入 decision_settlements（兜底包自动过滤，失败不影响分析）
            try:
                from app.services.settlement_service import get_settlement_service

                await get_settlement_service().register_from_result(task_id, user_id, result)
            except Exception as e:
                logger.warning(f"结算登记失败(忽略) task={task_id}: {e}", exc_info=True)

            # 发送通知
            try:
                from app.services.notifications_service import get_notifications_service

                svc = get_notifications_service()
                summary = str(result.get("summary", ""))[:120]
                await svc.create_and_publish(
                    payload=NotificationCreate(
                        user_id=str(user_id),
                        type="analysis",
                        title=f"{stock_code} 分析完成",
                        content=summary,
                        link=f"/stocks/{stock_code}",
                        source="analysis",
                    )
                )
            except Exception as e:
                logger.debug(f"发送分析完成通知失败: {e}")

        except Exception as e:
            logger.error(f"❌ 后台分析任务失败: {task_id} - {e}", exc_info=True)
            if progress_tracker:
                progress_tracker.mark_failed(str(e))
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.FAILED,
                progress=0,
                message="分析失败",
                error_message=str(e),
            )
            await self._update_task_status(task_id, AnalysisStatus.FAILED, 0, str(e))
        finally:
            if task_id in self._progress_trackers:
                del self._progress_trackers[task_id]
            unregister_analysis_tracker(task_id)

    # -------------------------------------------------------------------------
    # Internal Execution Logic (from simple_analysis_service.py)
    # -------------------------------------------------------------------------
    async def _execute_analysis_sync(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest,
        progress_tracker: Optional[RedisProgressTracker] = None,
        mcp_tool_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """同步执行分析（在共享线程池中运行）"""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._thread_pool,
            self._run_analysis_sync,
            task_id,
            user_id,
            request,
            progress_tracker,
            mcp_tool_ids or [],
            loop,
        )
        return result

    def _run_analysis_sync(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest,
        progress_tracker: Optional[RedisProgressTracker] = None,
        mcp_tool_ids: Optional[List[str]] = None,
        server_loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> Dict[str, Any]:
        """同步执行分析的具体实现"""
        # 任务级 MCP 管理器（用于隔离和管理 MCP 工具状态）
        task_mcp_manager = None

        try:
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            from app.llm.mcp.task_manager import (
                get_task_mcp_manager,
                remove_task_mcp_manager,
            )

            # 创建任务级 MCP 管理器
            task_mcp_manager = get_task_mcp_manager(task_id)
            logger.info(f"🔧 [任务管理器] 创建任务级 MCP 管理器: {task_id}")

            # 进度更新回调
            def update_progress_sync(progress: int, message: str, step: str):
                try:
                    if progress_tracker:
                        progress_tracker.update_progress({"progress_percentage": progress, "last_message": message})

                    # 1. 更新内存状态（同步）
                    self.memory_manager.update_task_status_sync(
                        task_id=task_id,
                        status=TaskStatus.RUNNING,
                        progress=progress,
                        message=message,
                        current_step=step,
                    )

                    # 2. 更新MongoDB（同步复用连接，避免频繁创建）
                    sync_db = self._get_sync_mongo_db()
                    if sync_db is not None:
                        sync_db.analysis_tasks.update_one(
                            {"task_id": task_id},
                            {
                                "$set": {
                                    "progress": progress,
                                    "current_step": step,
                                    "message": message,
                                    "updated_at": now_utc(),
                                }
                            },
                        )
                except Exception as e:
                    logger.warning(f"⚠️ [Sync] 更新进度失败: {e}")

            update_progress_sync(6, "⚙️ 配置分析参数", "configuration")

            # 选中分析师列表（完全依赖配置文件加载，禁止写死；P5-c：selected_nodes 优先）
            selected_analysts = []
            if request.parameters:
                _picked = (
                    getattr(request.parameters, "selected_nodes", None)
                    or getattr(request.parameters, "selected_analysts", [])
                    or []
                )
                selected_analysts = [str(a).strip() for a in _picked if a]
            if not selected_analysts:
                raise ValueError("selected_analysts 不能为空，请先在阶段1配置并选择分析师。")

            # 通过配置文件映射规范化（兼容 slug / 简短ID / 中文名），保持顺序去重
            try:
                lookup = DynamicAnalystFactory.build_lookup_map()
                normalized: List[str] = []
                seen = set()
                for key in selected_analysts:
                    mapped = key
                    if key in lookup:
                        mapped = lookup[key].get("slug") or lookup[key].get("internal_key") or key
                    if mapped and mapped not in seen:
                        normalized.append(mapped)
                        seen.add(mapped)
                selected_analysts = normalized
            except Exception as e:
                logger.warning(f"⚠️ 规范化分析师列表失败，使用原始输入: {e}")

            if not selected_analysts:
                raise ValueError("selected_analysts 不能为空，请先在阶段1配置并选择分析师。")

            # 🔍 调试日志：打印最终的分析师列表
            logger.info(f"📋 [分析师选择] 最终分析师列表: {selected_analysts}")

            # 模型选择逻辑
            from app.services.model_capability_service import (
                get_model_capability_service,
            )

            capability_service = get_model_capability_service()

            if (
                request.parameters
                and getattr(request.parameters, "analyst_model", None)
                and getattr(request.parameters, "debate_model", None)
            ):
                analyst_model = request.parameters.analyst_model
                debate_model = request.parameters.debate_model
            else:
                analyst_model, debate_model = capability_service.recommend_models()

            # 未添加任何启用模型时给出明确错误，而不是静默使用不存在的默认模型
            if not analyst_model or not debate_model:
                raise ValueError("未添加任何启用的模型，请先在 设置 → 模型配置 中添加并启用模型")

            # DeepSeek 旧模型弃用提醒
            for _mn in [analyst_model, debate_model]:
                if _mn in _DEPRECATED_MODELS:
                    _repl, _date = _DEPRECATED_MODELS[_mn]
                    logger.warning(f"[Deprecation] 模型 '{_mn}' 将于 {_date} 弃用，请迁移至 '{_repl}'")

            analyst_provider_info = get_provider_and_url_by_model_sync(analyst_model)
            debate_provider_info = get_provider_and_url_by_model_sync(debate_model)
            analyst_provider = analyst_provider_info["provider"]

            # 获取市场类型 - 优先使用 StockUtils 自动识别
            if request.parameters and request.parameters.market_type:
                market_type = request.parameters.market_type
            else:
                try:
                    # 自动识别市场类型
                    market_info = StockUtils.get_market_info(request.get_symbol())
                    if market_info.get("is_china"):
                        market_type = "A股"
                    elif market_info.get("is_hk"):
                        market_type = "港股"
                    elif market_info.get("is_us"):
                        market_type = "美股"
                    else:
                        market_type = "A股"  # 默认兜底
                    logger.info(f"📊 [自动识别] 股票 {request.get_symbol()} 市场类型: {market_type}")
                except Exception as e:
                    logger.warning(f"⚠️ 无法识别股票市场类型: {e}，使用默认值 'A股'")
                    market_type = "A股"

            config = create_analysis_config(
                selected_analysts=selected_analysts,
                analyst_model=analyst_model,
                debate_model=debate_model,
                llm_provider=analyst_provider,
                market_type=market_type,
            )

            # 注入MCP工具加载器（惰性加载，避免提前长连接）
            selected_mcp_tools: List[str] = []
            if mcp_tool_ids:
                selected_mcp_tools = list(mcp_tool_ids)
            elif request.parameters:
                selected_mcp_tools = (
                    getattr(request.parameters, "mcp_tool_ids", None)
                    or getattr(request.parameters, "mcp_tools", [])
                    or []
                )

            if selected_mcp_tools:
                # 新层 MCPManager：启用 MCP，工具发现与按 id 过滤由 orchestrator pipeline 执行
                config["enable_mcp"] = True
                config["mcp_tool_ids"] = selected_mcp_tools
                logger.info(f"启用MCP工具（按选择过滤）: {len(selected_mcp_tools)}个")

            # 若未显式选择但外部 MCP 工具已配置，则自动启用
            self._auto_enable_mcp(config, selected_mcp_tools)

            if request.parameters:
                config["phase2_enabled"] = getattr(request.parameters, "phase2_enabled", False)
                config["phase2_debate_rounds"] = getattr(request.parameters, "phase2_debate_rounds", 2)
                config["phase3_enabled"] = getattr(request.parameters, "phase3_enabled", False)
                config["phase3_debate_rounds"] = getattr(request.parameters, "phase3_debate_rounds", 2)
                config["phase4_enabled"] = True
                config["phase4_debate_rounds"] = 1
            else:
                # 默认阶段配置：交易员始终执行
                config.setdefault("phase2_enabled", False)
                config.setdefault("phase3_enabled", False)
                config.setdefault("phase4_enabled", True)
                config.setdefault("phase2_debate_rounds", 1)
                config.setdefault("phase3_debate_rounds", 1)
                config.setdefault("phase4_debate_rounds", 1)

            # 统一轮次配置到 ConditionalLogic
            config["max_debate_rounds"] = config.get("phase2_debate_rounds", 1)
            config["max_risk_discuss_rounds"] = config.get("phase3_debate_rounds", 1)

            # 工作流通用化（P5-c）：workflow_slug 与显式 stage_overrides 直通编译层
            # （params_from_legacy_config 中按字段级优先合并 phaseN_* legacy 映射）
            config["workflow_slug"] = getattr(request, "workflow_slug", None)
            if request.parameters and getattr(request.parameters, "stage_overrides", None):
                config["stage_overrides"] = dict(request.parameters.stage_overrides)

            # 期限贯通：仅显式指定时携带（None 不设键，deps.config 通道直达
            # executor 物化点，不进 state/事件/spec）
            if request.parameters and getattr(request.parameters, "horizon", None):
                config["horizon"] = request.parameters.horizon

            # 注入模型 provider 路由信息
            config["analyst_provider"] = analyst_provider
            config["debate_provider"] = debate_provider_info["provider"]
            config["analyst_backend_url"] = analyst_provider_info["backend_url"]
            config["debate_backend_url"] = debate_provider_info["backend_url"]
            config["backend_url"] = analyst_provider_info["backend_url"]

            # 注入任务级 MCP 管理器
            config["task_mcp_manager"] = task_mcp_manager
            config["task_id"] = task_id
            logger.info(f"🔧 [任务管理器] 已将 MCP 管理器注入配置: task_id={task_id}")

            update_progress_sync(8, "🚀 初始化AI分析引擎", "engine_initialization")

            # 预计算内置工具可用性（基于数据域状态）
            try:
                from app.engine.tools.datasources.domain_checker import AvailabilityCache
                from app.engine.tools.datasources.registry import DATASOURCE_REGISTRY

                _market_map = {"A股": "CN", "港股": "HK", "美股": "US"}
                _market = _market_map.get(market_type, "CN")
                _cache = AvailabilityCache.get_instance()
                from app.core.async_utils import run_async

                run_async(_cache.compute(_market, DATASOURCE_REGISTRY))
                logger.info(f"📊 [工具可用性] 市场={_market}, 结果={_cache.all_results}")
            except Exception as _e:
                logger.warning(f"⚠️ [工具可用性] 预计算失败（不影响分析）: {_e}")

            # ── 预拉取阶段：拉取该股票在该市场的全部数据域到 MongoDB ──
            # 用户可通过 parameters.prefetch_data=False 关闭（直接使用库内已有数据）
            _prefetch_enabled = True
            if request.parameters is not None:
                _prefetch_enabled = bool(getattr(request.parameters, "prefetch_data", True))
            if _prefetch_enabled:
                update_progress_sync(10, "📊 预拉取股票数据...", "data_prefetch")
                try:
                    _prefetch_symbol = self._normalize_symbol_for_data(request.get_symbol(), _market)
                    prefetch_result = self._prefetch_stock_data(_market, _prefetch_symbol)
                    logger.info(f"📊 [数据预拉取] 结果: {prefetch_result}")
                    # 预拉取后重新计算工具可用性
                    run_async(_cache.compute(_market, DATASOURCE_REGISTRY))
                    logger.info(f"📊 [工具可用性] 预拉取后重新计算: {_cache.all_results}")
                except Exception as _prefetch_err:
                    logger.warning(f"⚠️ [数据预拉取] 失败（不影响分析，使用现有数据）: {_prefetch_err}")
                update_progress_sync(12, "📊 数据预拉取完成", "data_prefetch_done")
            else:
                logger.info("📊 [数据预拉取] 用户已关闭，直接使用库内数据")
                update_progress_sync(12, "📊 跳过数据预拉取（使用库内数据）", "data_prefetch_skipped")

            # 🔥 添加时间戳日志，精确定位耗时
            import time

            graph_init_start = time.time()
            logger.info("⏱️ [性能追踪] 开始创建 AnalysisRuntime...")

            trading_graph = self._get_trading_graph(config)

            graph_init_elapsed = time.time() - graph_init_start
            logger.info(
                f"⏱️ [性能追踪] AnalysisRuntime 创建完成，耗时: {graph_init_elapsed:.2f} 秒 ({graph_init_elapsed / 60:.2f} 分钟)"
            )

            if graph_init_elapsed > 60:
                logger.warning("⚠️ [性能瓶颈] AnalysisRuntime 初始化耗时超过 1 分钟！这是主要性能瓶颈！")

            start_time = now_config_tz()
            analysis_date = format_date_short(now_config_tz())
            if request.parameters and request.parameters.analysis_date:
                ad = request.parameters.analysis_date
                if isinstance(ad, datetime):
                    analysis_date = ad.strftime("%Y-%m-%d")
                elif isinstance(ad, str):
                    analysis_date = ad

            # 🔧 智能日期范围处理：获取最近10天的数据，自动处理周末/节假日
            data_start_date, data_end_date = get_trading_date_range(analysis_date, lookback_days=10)
            logger.info(f"📅 分析目标日期: {analysis_date}, 数据范围: {data_start_date} 至 {data_end_date}")

            update_progress_sync(15, "🤖 开始多智能体协作分析", "agent_analysis")

            # 结构化进度回调：pipeline 完成驱动计数（payload: completed/total/percent/step_text），
            # 经 EventSink.on_progress 通道转发至此，写入 tracker 供 5s 轮询兜底；
            # 前端实时进度直接消费 WS agent_event 流中的 progress 事件。
            def graph_progress_callback(payload: dict):
                try:
                    if not progress_tracker:
                        return
                    percent = int(payload.get("percent") or 0)
                    step_text = str(payload.get("step_text") or "")
                    completed = payload.get("completed")
                    total = payload.get("total")
                    message = f"{step_text}（{completed}/{total}）" if completed and total else step_text
                    current_progress = progress_tracker.progress_data.get("progress_percentage", 0)
                    if percent >= current_progress:
                        update_progress_sync(percent, message, step_text)
                    else:
                        # 单调保护：乱序回退仅更新文案
                        progress_tracker.update_progress({"last_message": message})
                except Exception as e:
                    logger.debug(f"进度回调更新失败: {e}")

            # 执行分析（事件汇聚点：实时 WS + Mongo 落库，供过程面板/回放）
            from app.services.analysis_events import create_event_sink, release_event_sink

            event_sink = create_event_sink(task_id, server_loop=server_loop, on_progress=graph_progress_callback)
            try:
                state, decision = trading_graph.propagate_sync(
                    request.get_symbol(),
                    analysis_date,
                    task_id=task_id,
                    event_sink=event_sink,
                    user_id=user_id,
                    progress_range=(15, 92),
                )
            finally:
                release_event_sink(task_id, server_loop=server_loop)

            update_progress_sync(95, "处理分析结果...", "result_processing")
            execution_time = (now_config_tz() - start_time).total_seconds()

            # 提取 reports 从 state
            reports = self._extract_reports_from_state(state)

            # 提取结构化总结
            structured_summary = state.get("structured_summary") or {}

            # 优先从结构化总结中获取摘要和建议
            summary_text = ""
            if structured_summary and structured_summary.get("analysis_summary"):
                summary_text = structured_summary.get("analysis_summary")
            elif isinstance(decision, dict):
                summary_text = str(decision.get("summary", ""))[:200]

            recommendation_text = ""
            if structured_summary and structured_summary.get("investment_recommendation"):
                recommendation_text = structured_summary.get("investment_recommendation")
            elif isinstance(decision, dict):
                recommendation_text = str(decision.get("recommendation", ""))

            # 构建结果 (简化版，完整版在 _save_analysis_result_web_style 中重构)
            # 这里直接返回字典
            result = {
                "stock_code": request.get_symbol(),
                "stock_symbol": request.get_symbol(),
                "analysis_date": analysis_date,
                "market_type": market_type,
                "summary": summary_text,
                "recommendation": recommendation_text,
                "confidence_score": decision.get("confidence_score", 0.0) if isinstance(decision, dict) else 0.0,
                "risk_level": decision.get("risk_level", "中等") if isinstance(decision, dict) else "中等",
                "detailed_analysis": decision,
                "execution_time": execution_time,
                "state": state,
                "structured_summary": structured_summary,  # 🔥 显式添加到顶层结果
                "reports": reports,  # 🔥 添加提取的报告
                "decision": decision,
                "model_info": decision.get("model_info", "Unknown") if isinstance(decision, dict) else "Unknown",
                "analysts": selected_analysts,
                # 期限贯通：结算登记从内存 result 直接读取（register_from_result），
                # parameters 快照为 durable 备份；None=旧任务（结算回落默认 7 日）
                "horizon": request.parameters.horizon if request.parameters else None,
            }
            return result

        except Exception as e:
            logger.error(f"❌ 分析执行失败: {task_id} - {e}", exc_info=True)
            raise

        finally:
            # 清理任务级 MCP 管理器
            if task_mcp_manager is not None:
                try:
                    # 探测当前是否有运行中的事件循环（无则抛 RuntimeError）
                    asyncio.get_running_loop()
                    # 用 task_registry 持强引用，避免 task 被 GC 中断
                    from app.core.task_registry import task_registry

                    task_registry.register(
                        remove_task_mcp_manager(task_id),
                        name=f"mcp_cleanup_{task_id}",
                        critical=False,
                    )
                    logger.info(f"🔧 [任务管理器] 已调度清理任务级 MCP 管理器: {task_id}")
                except RuntimeError:
                    # 无运行中的事件循环（worker thread）：同步从 LRU 失效
                    # BoundedLRUCache.invalidate 会触发 on_evict 回调，
                    # 但 on_evict 内部 get_running_loop 也会抛 RuntimeError 被吞掉，
                    # 此时只能依赖 OS 回收进程资源
                    try:
                        from app.llm.mcp.task_manager import _task_managers

                        _task_managers.invalidate(task_id)
                        logger.info(f"🔧 [任务管理器] 已同步失效任务级 MCP 管理器: {task_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ [任务管理器] 同步清理失败: {e}")
                except Exception as e:
                    logger.warning(f"⚠️ [任务管理器] 清理任务管理器失败: {e}")
