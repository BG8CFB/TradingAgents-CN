"""报告抽取与持久化（自 analysis_service.py 拆分）。

职责：state → reports 五层提取、分模块报告落盘 data 目录（Web 目录结构）、
analysis_reports 写入与 analysis_tasks.result 瘦身引用拷贝（Web Style）、
token 用量回填、analysis_reports 集合按 task_id 读取。
"""
# data-access-exempt: 应用层集合（analysis_reports/analysis_tasks/token_usage）直查属架构豁免（与原 analysis_service 同口径）

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.database import get_mongo_db
from app.utils.runtime_paths import get_analysis_results_dir
from app.utils.timezone import format_date_short, format_iso, now_config_tz, now_utc

logger = logging.getLogger(__name__)


class ReportsMixin:
    """报告抽取与持久化 mixin。"""

    # -------------------------------------------------------------------------
    # Report Extraction Helper
    # -------------------------------------------------------------------------
    def _extract_reports_from_state(self, state: dict) -> dict:
        """从 LangGraph 状态中提取所有报告（5 层提取策略）。"""
        reports = {}
        if not isinstance(state, dict):
            return reports

        # 1. 动态发现所有 *_report 字段和已知非 _report 后缀的报告字段
        known_non_report_keys = [
            "trader_investment_plan",
            "investment_plan",
            "final_trade_decision",
        ]

        report_keys_found = [k for k in state.keys() if k.endswith("_report") or k in known_non_report_keys]
        logger.info(f"[报告提取] state中发现的报告键: {report_keys_found}")

        for key in state.keys():
            if key.endswith("_report") or key in known_non_report_keys:
                content = state[key]
                if content:
                    if isinstance(content, str):
                        reports[key] = content
                    elif hasattr(content, "content") and isinstance(content.content, str):
                        reports[key] = content.content
                    else:
                        try:
                            reports[key] = str(content)
                        except Exception as e:
                            logger.warning(f"[报告提取] 无法提取报告 {key}: 类型={type(content)}, 错误: {e}")

        logger.info(f"[报告提取] 根级报告: {list(reports.keys())}")

        # 2. 提取 investment_debate_state (多空博弈)
        if "investment_debate_state" in state and isinstance(state["investment_debate_state"], dict):
            inv_state = state["investment_debate_state"]
            for state_key, report_key in {
                "bull_history": "bull_researcher",
                "bear_history": "bear_researcher",
                "judge_decision": "research_team_decision",
            }.items():
                if state_key in inv_state and inv_state[state_key]:
                    reports[report_key] = inv_state[state_key]

        # 3. 提取 risk_debate_state (风险管理)
        if "risk_debate_state" in state and isinstance(state["risk_debate_state"], dict):
            risk_state = state["risk_debate_state"]
            for state_key, report_key in {
                "risky_history": "risky_analyst",
                "safe_history": "safe_analyst",
                "neutral_history": "neutral_analyst",
                "judge_decision": "risk_management_decision",
            }.items():
                if state_key in risk_state and risk_state[state_key]:
                    reports[report_key] = risk_state[state_key]

        # 4. 从 reports 字典中提取 (动态添加的智能体)
        if "reports" in state and isinstance(state["reports"], dict):
            dynamic_reports = state["reports"]
            logger.info(f"[报告提取] 从 reports 字典发现 {len(dynamic_reports)} 个: {list(dynamic_reports.keys())}")
            for key, content in dynamic_reports.items():
                if key not in reports and content:
                    reports[key] = content if isinstance(content, str) else str(content)

        # 5. 从 messages 列表中提取 (最终兜底)
        if "messages" in state and isinstance(state["messages"], list):
            from app.llm.core.types import Message, Role

            messages_reports_count = 0
            for msg in reversed(state["messages"]):
                # 新层 Message 无 name 字段；命名报告消息（若上游附加）作兜底提取
                msg_name = getattr(msg, "name", "")
                if (
                    isinstance(msg, Message)
                    and msg.role == Role.ASSISTANT
                    and msg_name
                    and msg_name.endswith("_report")
                ):
                    report_key = msg.name
                    if report_key not in reports:
                        content = msg.content
                        if content and isinstance(content, str):
                            reports[report_key] = content
                            messages_reports_count += 1
            if messages_reports_count > 0:
                logger.info(f"[报告提取] 从消息历史中恢复了 {messages_reports_count} 个报告")

        return reports

    async def _save_analysis_results_complete(self, task_id: str, result: Dict[str, Any]):
        """完整的分析结果保存"""
        try:
            stock_symbol = result.get("stock_symbol") or result.get("stock_code", "UNKNOWN")
            # 1. 保存到本地
            await self._save_modular_reports_to_data_dir(result, stock_symbol)
            # 2. 保存到数据库 (Web Style)
            await self._save_analysis_result_web_style(task_id, result)
        except Exception as e:
            logger.error(f"❌ 保存结果失败: {e}", exc_info=True)

    async def _save_modular_reports_to_data_dir(self, result: Dict[str, Any], stock_symbol: str) -> Dict[str, str]:
        """保存分模块报告到data目录 - 完全采用web目录的文件结构"""
        try:
            # 使用统一的路径获取方式
            runtime_base = settings.RUNTIME_BASE_DIR
            results_dir = get_analysis_results_dir(runtime_base)

            analysis_date_raw = result.get("analysis_date", now_config_tz())

            # 确保 analysis_date 是字符串格式
            if isinstance(analysis_date_raw, datetime):
                analysis_date_str = analysis_date_raw.strftime("%Y-%m-%d")
            elif isinstance(analysis_date_raw, str):
                # 如果已经是字符串，检查格式
                try:
                    # 尝试解析日期字符串，确保格式正确
                    datetime.strptime(analysis_date_raw, "%Y-%m-%d")
                    analysis_date_str = analysis_date_raw
                except ValueError:
                    # 如果格式不正确，使用当前日期
                    analysis_date_str = format_date_short(now_config_tz())
            else:
                # 其他类型，使用当前日期
                analysis_date_str = format_date_short(now_config_tz())

            stock_dir = results_dir / stock_symbol / analysis_date_str
            reports_dir = stock_dir / "reports"
            await asyncio.to_thread(reports_dir.mkdir, parents=True, exist_ok=True)

            # 创建message_tool.log文件 - 与web目录保持一致（线程池中执行避免阻塞事件循环）
            log_file = stock_dir / "message_tool.log"
            await asyncio.to_thread(log_file.touch, exist_ok=True)

            # 获取已提取的报告
            reports = result.get("reports", {})
            saved_files = {}

            # 🔥 报告标题映射（registry 单一权威表）：分析师段 + 非分析师固定报告键。
            # 非分析师标题从硬编码中文统一切 YAML 配置名（与 router 层 report_titles 一致）
            from app.engine.orchestrator.registry import (
                analyst_report_display_names,
                names_by_slug,
                slug_for_report_key,
            )

            known_report_titles = analyst_report_display_names()
            try:
                slug_names = names_by_slug()
                for fixed_key in (
                    "investment_plan",
                    "trader_investment_plan",
                    "bull_researcher",
                    "bear_researcher",
                    "research_team_decision",
                    "risky_analyst",
                    "safe_analyst",
                    "neutral_analyst",
                    "risk_management_decision",
                    "risk_manager_decision",
                ):
                    slug = slug_for_report_key(fixed_key)
                    name = slug_names.get(slug) if slug else None
                    if name:
                        known_report_titles[fixed_key] = f"{name}报告"
            except Exception as e:  # noqa: BLE001 - 标题解析失败走 key 兜底，不阻断落盘
                logger.warning(f"⚠️ 无法加载报告标题: {e}")

            # 🔥 动态保存所有报告（包括新添加的智能体报告）
            for report_key, report_content in reports.items():
                try:
                    if report_content:
                        # 生成文件名：使用 report_key 作为文件名
                        filename = f"{report_key}.md"
                        # 获取友好标题，如果没有则使用 key 的格式化版本
                        title = known_report_titles.get(report_key, report_key.replace("_", " ").title() + "报告")

                        file_path = reports_dir / filename
                        await asyncio.to_thread(file_path.write_text, report_content, encoding="utf-8")

                        saved_files[report_key] = str(file_path)
                        logger.info(f"✅ 保存模块报告: {file_path} ({title})")
                except Exception as e:
                    logger.warning(f"⚠️ 保存模块 {report_key} 失败: {e}")

            # 保存最终决策报告 - 完全按照web目录的方式
            decision = result.get("decision", {})
            if decision:
                decision_content = f"# {stock_symbol} 最终投资决策\n\n"
                if isinstance(decision, dict):
                    decision_content += "## 投资建议\n\n"
                    decision_content += f"**行动**: {decision.get('action', 'N/A')}\n\n"
                    decision_content += f"**置信度**: {decision.get('confidence', 0):.1%}\n\n"
                    decision_content += f"**风险评分**: {decision.get('risk_score', 0):.1%}\n\n"
                    decision_content += f"**目标价位**: {decision.get('target_price', 'N/A')}\n\n"
                    decision_content += f"## 分析推理\n\n{decision.get('reasoning', '暂无分析推理')}\n\n"
                else:
                    decision_content += f"{str(decision)}\n\n"

                decision_file = reports_dir / "final_trade_decision.md"
                await asyncio.to_thread(decision_file.write_text, decision_content, encoding="utf-8")
                saved_files["final_trade_decision"] = str(decision_file)

            # 保存分析元数据文件 - 完全按照web目录的方式
            metadata = {
                "stock_symbol": stock_symbol,
                "analysis_date": analysis_date_str,
                "timestamp": format_iso(now_config_tz()),
                "analysts": result.get("analysts", []),
                "status": "completed",
                "reports_count": len(saved_files),
                "report_types": list(saved_files.keys()),
            }

            metadata_file = reports_dir.parent / "analysis_metadata.json"
            await asyncio.to_thread(
                metadata_file.write_text,
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            return saved_files
        except Exception as e:
            logger.error(f"❌ 保存分模块报告失败: {e}", exc_info=True)
            return {}

    async def _save_analysis_result_web_style(self, task_id: str, result: Dict[str, Any]):
        """保存分析结果 (Web Style)"""
        try:
            db = get_mongo_db()
            stock_symbol = result.get("stock_symbol") or result.get("stock_code", "UNKNOWN")
            timestamp = now_utc()
            analysis_id = result.get("analysis_id") or f"{stock_symbol}_{timestamp.strftime('%Y%m%d_%H%M%S')}"

            # 处理 reports，确保为字符串内容，避免空值
            raw_reports = result.get("reports") or {}
            cleaned_reports: Dict[str, str] = {}
            if isinstance(raw_reports, dict):
                for key, value in raw_reports.items():
                    if value is None:
                        continue
                    if isinstance(value, str):
                        content = value.strip()
                    else:
                        # 对非字符串内容进行 JSON 序列化，保持可读
                        content = json.dumps(value, ensure_ascii=False, indent=2)
                    if content:
                        cleaned_reports[key] = content

            # 关键字段兜底
            analysis_date = result.get("analysis_date") or timestamp.strftime("%Y-%m-%d")
            summary = result.get("summary", "")
            recommendation = result.get("recommendation", "")
            risk_level = result.get("risk_level", "中等")
            confidence_score = result.get("confidence_score", 0.0)
            key_points = result.get("key_points") or []
            analysts = result.get("analysts") or result.get("selected_analysts") or []
            model_info = result.get("model_info") or result.get("llm_model") or "Unknown"
            tokens_used = result.get("tokens_used") or result.get("token_usage", {}).get("total_tokens", 0)
            # token 用量回填：从 token_usage 集合按任务聚合（per-call 记录的权威汇总）
            token_usage_detail = {}
            try:
                usage_rows = await db.token_usage.aggregate(
                    [
                        {"$match": {"task_id": task_id}},
                        {
                            "$group": {
                                "_id": None,
                                "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                                "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                                "cache_read_tokens": {"$sum": {"$ifNull": ["$cache_read_input_tokens", 0]}},
                                "cache_creation_tokens": {"$sum": {"$ifNull": ["$cache_creation_input_tokens", 0]}},
                                "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
                            }
                        },
                    ]
                ).to_list(length=1)
                if usage_rows:
                    row = usage_rows[0]
                    token_usage_detail = {
                        "input_tokens": row.get("input_tokens", 0),
                        "output_tokens": row.get("output_tokens", 0),
                        "cache_read_tokens": row.get("cache_read_tokens", 0),
                        "cache_creation_tokens": row.get("cache_creation_tokens", 0),
                        "cost": row.get("cost", 0.0),
                    }
                    tokens_used = token_usage_detail["input_tokens"] + token_usage_detail["output_tokens"]
            except Exception as usage_err:  # noqa: BLE001 - 统计回填失败不阻断保存
                logger.warning(f"⚠️ token 用量回填失败 task={task_id}: {usage_err}")
            execution_time = result.get("execution_time", 0)
            structured_summary = result.get("structured_summary") or {}
            market_type = result.get("market_type") or result.get("parameters", {}).get("market_type") or "A股"

            # 执行计划快照提取：任务文档存 workflow_snapshot（冻结的 spec 版本 + 编译参数，
            # 供回放/审计「这个任务当时跑的是什么拓扑」）；同时从对外 state 剥离（内部执行元数据）
            workflow_snapshot = None
            state_obj = result.get("state")
            if isinstance(state_obj, dict):
                snap = state_obj.pop("_plan_snapshot", None)
                if isinstance(snap, dict) and snap:
                    workflow_snapshot = snap

            document = {
                "analysis_id": analysis_id,
                "stock_symbol": stock_symbol,
                "stock_name": await self._resolve_stock_name(stock_symbol),
                "analysis_date": analysis_date,
                "market_type": market_type,
                "status": result.get("status", "completed"),
                "decision": result.get("decision", {}),
                "structured_summary": structured_summary,  # 🔥 显式保存结构化总结到DB
                "task_id": task_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "summary": summary,
                "recommendation": recommendation,
                "reports": cleaned_reports,
                "confidence_score": confidence_score,
                "risk_level": risk_level,
                "key_points": key_points,
                "analysts": analysts,
                "model_info": model_info,
                "tokens_used": tokens_used,
                "token_usage_detail": token_usage_detail,
                "execution_time": execution_time,
                "source": result.get("source", "analysis_service"),
            }
            if workflow_snapshot is not None:
                document["workflow_snapshot"] = workflow_snapshot

            # 写入报告集合
            insert_result = await db.analysis_reports.insert_one(document)

            # 任务集合只存瘦身引用拷贝（排除 reports 等大对象，全量以
            # analysis_reports 为准）：result 保留 analysis_id 等索引键，供
            # _find_report_by_task_id / reports_service 反查关联报告；
            # 携带 report_id 便于前端关联
            document_for_task = {
                k: v for k, v in document.items() if k not in ("reports", "state")
            }
            document_for_task["_id"] = insert_result.inserted_id
            await db.analysis_tasks.update_one({"task_id": task_id}, {"$set": {"result": document_for_task}})
        except Exception as e:
            logger.error(f"❌ 保存DB结果失败: {e}", exc_info=True)

    async def _find_report_by_task_id(
        self,
        task_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        从 analysis_reports 中根据 task_id 查找报告。
        兼容旧数据：如果直接查不到，通过 analysis_tasks.result.analysis_id 兜底。

        Args:
            task_id: 任务 ID
            user_id: 可选用户 ID，用于所有权过滤。非 None 时仅返回该用户的报告。
        """
        try:
            db = get_mongo_db()
            filter_doc: Dict[str, Any] = {"task_id": task_id}
            if user_id is not None:
                # 老数据兼容：早期记录可能不含 user_id 字段
                filter_doc["$or"] = [
                    {"user_id": user_id},
                    {"user_id": {"$exists": False}},
                    {"user_id": None},
                ]
            report = await db.analysis_reports.find_one(filter_doc)
            if report:
                return report

            # 兼容旧数据：analysis_reports 旧记录可能不含 user_id，回退到 analysis_tasks 查 analysis_id
            tasks_filter: Dict[str, Any] = {"task_id": task_id}
            if user_id is not None:
                tasks_filter["$or"] = [
                    {"user_id": user_id},
                    {"user_id": {"$exists": False}},
                    {"user_id": None},
                ]
            tasks_doc = await db.analysis_tasks.find_one(tasks_filter, {"result.analysis_id": 1})
            if tasks_doc:
                analysis_id = tasks_doc.get("result", {}).get("analysis_id")
                if analysis_id:
                    return await db.analysis_reports.find_one({"analysis_id": analysis_id})
        except Exception as e:
            logger.warning(f"⚠️ _find_report_by_task_id 失败: {e}")
        return None
