"""
进度跟踪器（过渡期）
- 暂时从旧模块导入 RedisProgressTracker 类
- 在本模块内提供 get_progress_by_id 的实现（与旧实现一致，修正 cls 引用）
"""
from typing import Any, Dict, Optional, List
import json
import os
import logging
import time



logger = logging.getLogger("app.services.progress.tracker")

from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class AnalysisStep:
    """分析步骤数据类"""
    name: str
    description: str
    status: str = "pending"  # pending, current, completed, failed
    weight: float = 0.1  # 权重，用于计算进度
    start_time: Optional[float] = None
    end_time: Optional[float] = None


def safe_serialize(data):
    """安全序列化，处理不可序列化的对象"""
    if isinstance(data, dict):
        return {k: safe_serialize(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [safe_serialize(item) for item in data]
    elif isinstance(data, (str, int, float, bool, type(None))):
        return data
    elif hasattr(data, '__dict__'):
        return safe_serialize(data.__dict__)
    else:
        return str(data)



class RedisProgressTracker:
    """Redis进度跟踪器（移除分级深度，按阶段配置动态生成步骤）"""

    def __init__(
        self,
        task_id: str,
        analysts: List[str],
        phase_config: Dict[str, Any],
        llm_provider: str,
        on_update=None,
    ):
        self.task_id = task_id
        self.analysts = analysts
        self.phase_config = phase_config or {}
        self.llm_provider = llm_provider
        self.on_update = on_update

        # 阶段配置（默认：仅开启最终交易阶段）
        self.phase2_enabled = bool(self.phase_config.get("phase2_enabled", False))
        self.phase2_rounds = int(self.phase_config.get("phase2_debate_rounds", 1))
        self.phase3_enabled = bool(self.phase_config.get("phase3_enabled", False))
        self.phase3_rounds = int(self.phase_config.get("phase3_debate_rounds", 1))
        self.phase4_enabled = bool(self.phase_config.get("phase4_enabled", True))
        self.phase4_rounds = int(self.phase_config.get("phase4_debate_rounds", 1))

        # Redis连接
        self.redis_client = None
        self.use_redis = self._init_redis()

        # 进度数据
        self.progress_data = {
            'task_id': task_id,
            'status': 'running',
            'progress_percentage': 0.0,
            'current_step': 0,  # 当前步骤索引（数字）
            'total_steps': 0,
            'current_step_name': '初始化',
            'current_step_description': '准备开始分析',
            'last_message': '分析任务已启动',
            'start_time': time.time(),
            'last_update': time.time(),
            'elapsed_time': 0.0,
            'remaining_time': 0.0,
            'steps': []
        }

        # 生成分析步骤
        self.analysis_steps = self._generate_dynamic_steps()
        self.progress_data['total_steps'] = len(self.analysis_steps)
        self.progress_data['steps'] = [asdict(step) for step in self.analysis_steps]

        # 🔧 计算并设置预估总时长
        base_total_time = self._get_base_total_time()
        self.progress_data['estimated_total_time'] = base_total_time
        self.progress_data['remaining_time'] = base_total_time  # 初始时剩余时间 = 总时长

        # 保存初始状态
        self._save_progress()

        logger.info(f"📊 [Redis进度] 初始化完成: {task_id}, 步骤数: {len(self.analysis_steps)}")

    def _init_redis(self) -> bool:
        """初始化Redis连接"""
        try:
            # 检查REDIS_ENABLED环境变量
            redis_enabled = os.getenv('REDIS_ENABLED', 'false').lower() == 'true'
            if not redis_enabled:
                logger.info(f"📊 [Redis进度] Redis未启用，使用文件存储")
                return False

            import redis

            # 从环境变量获取Redis配置
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            redis_password = os.getenv('REDIS_PASSWORD', None)
            redis_db = int(os.getenv('REDIS_DB', 0))

            # 创建Redis连接
            if redis_password:
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password,
                    db=redis_db,
                    decode_responses=True
                )
            else:
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    decode_responses=True
                )

            # 测试连接
            self.redis_client.ping()
            logger.info(f"📊 [Redis进度] Redis连接成功: {redis_host}:{redis_port}")
            return True
        except Exception as e:
            logger.warning(f"📊 [Redis进度] Redis连接失败，使用文件存储: {e}")
            return False

    def _generate_dynamic_steps(self) -> List[AnalysisStep]:
        """根据分析师数量与阶段开关动态生成分析步骤"""
        steps: List[AnalysisStep] = []

        # 定义各阶段的基础权重（会按启用情况重新归一化）
        block_defs = []

        # 1) 基础准备阶段
        prep_steps = [
            AnalysisStep("📋 准备阶段", "验证股票代码，检查数据源可用性", "pending", 0.0),
            AnalysisStep("🔧 环境检查", "检查API密钥配置，确保数据获取正常", "pending", 0.0),
            AnalysisStep("⚙️ 参数设置", "配置分析参数和AI模型选择", "pending", 0.0),
            AnalysisStep("🚀 启动引擎", "初始化AI分析引擎，准备开始分析", "pending", 0.0),
        ]
        block_defs.append(("prep", 0.1, prep_steps))

        # 2) 分析师团队阶段
        analyst_steps = []
        analyst_weight = 0.35
        for analyst in self.analysts:
            info = self._get_analyst_step_info(analyst)
            analyst_steps.append(AnalysisStep(info["name"], info["description"], "pending", 0.0))
        block_defs.append(("analysts", analyst_weight, analyst_steps if analyst_steps else [AnalysisStep("🔍 分析师", "执行基础分析", "pending", 0.0)]))

        # 3) 研究辩论阶段（可选）
        if self.phase2_enabled:
            debate_steps = [
                AnalysisStep("🐂 看涨研究员", "基于分析师报告构建买入论据", "pending", 0.0),
                AnalysisStep("🐻 看跌研究员", "识别潜在风险和问题", "pending", 0.0),
            ]
            rounds = max(self.phase2_rounds, 1)
            for i in range(rounds):
                debate_steps.append(AnalysisStep(f"🎯 研究辩论 第{i+1}轮", "多空研究员深度辩论", "pending", 0.0))
            debate_steps.append(AnalysisStep("👔 研究经理", "综合辩论结果，形成研究共识", "pending", 0.0))
            block_defs.append(("debate", 0.25, debate_steps))

        # 4) 投资组合/风险团队阶段（可选，第三阶段）
        if self.phase3_enabled:
            risk_steps = [
                AnalysisStep("🔥 激进策略", "从激进角度制定组合方案", "pending", 0.0),
                AnalysisStep("🛡️ 保守策略", "从保守角度制定组合方案", "pending", 0.0),
                AnalysisStep("⚖️ 中性策略", "从中性角度制定组合方案", "pending", 0.0),
                AnalysisStep("🎯 投资组合经理", "综合各策略，形成组合决策", "pending", 0.0),
            ]
            block_defs.append(("portfolio", 0.15, risk_steps))

        # 5) 最终决策与产出阶段（始终存在）
        final_steps = []
        if self.phase4_enabled:
            final_steps.append(AnalysisStep("💼 交易员决策", "基于研究结果制定具体交易策略", "pending", 0.0))
        final_steps.extend([
            AnalysisStep("📡 信号处理", "处理所有分析结果，生成交易信号", "pending", 0.0),
            AnalysisStep("📊 生成报告", "整理分析结果，生成完整报告", "pending", 0.0),
        ])
        block_defs.append(("final", 0.15, final_steps))

        # 归一化权重
        total_weight = sum(weight for _, weight, _ in block_defs if weight > 0)
        total_weight = total_weight or 1.0

        for _, weight, block_steps in block_defs:
            if not block_steps:
                continue
            per_step_weight = (weight / total_weight) / len(block_steps)
            for step in block_steps:
                step.weight = per_step_weight
                steps.append(step)

        return steps

    def _get_debate_rounds(self) -> int:
        """兼容旧调用：返回投资辩论轮次"""
        return max(self.phase2_rounds, 1)

    def _get_analyst_step_info(self, analyst: str) -> Dict[str, str]:
        """获取分析师步骤信息（名称与描述）- 动态从配置文件加载"""
        try:
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            
            # 尝试从配置文件获取分析师信息
            lookup = DynamicAnalystFactory.build_lookup_map()
            if analyst in lookup:
                config_info = lookup[analyst]
                name = config_info.get('name', analyst)
                icon = DynamicAnalystFactory._get_analyst_icon(config_info.get('slug', ''), name)
                return {
                    "name": f"{icon} {name}",
                    "description": f"进行{name}相关的专业分析"
                }
        except Exception:
            pass
        
        # 降级到默认映射
        return {"name": f"🔍 {analyst}分析师", "description": f"进行{analyst}相关的专业分析"}

    def _estimate_step_time(self, step: AnalysisStep) -> float:
        """估算步骤执行时间（秒）"""
        return self._get_base_total_time() * step.weight

    def _get_base_total_time(self) -> float:
        """
        根据阶段配置预估总时长（秒）
        规则与前端估算保持一致：
        - 基础耗时：5分钟
        - 第二阶段：每轮约3分钟
        - 第三阶段：每轮约3分钟
        - 第四阶段：每轮约2分钟
        """
        time_minutes = 5

        if self.phase2_enabled:
            time_minutes += 3 * max(self.phase2_rounds, 1)

        if self.phase3_enabled:
            time_minutes += 3 * max(self.phase3_rounds, 1)

        if self.phase4_enabled:
            time_minutes += 2 * max(self.phase4_rounds, 1)

        # 简单考虑分析师数量对耗时的影响（每增加一名分析师增加20%）
        analyst_multiplier = 1 + max(len(self.analysts) - 1, 0) * 0.2

        return time_minutes * 60 * analyst_multiplier

    def _calculate_time_estimates(self) -> tuple[float, float, float]:
        """返回 (elapsed, remaining, estimated_total)"""
        now = time.time()
        start = self.progress_data.get('start_time', now)
        elapsed = now - start
        pct = self.progress_data.get('progress_percentage', 0)
        base_total = self._get_base_total_time()

        if pct >= 100:
            # 任务已完成
            est_total = elapsed
            remaining = 0
        else:
            # 使用预估的总时长（固定值）
            est_total = base_total
            # 预计剩余 = 预估总时长 - 已用时间
            remaining = max(0, est_total - elapsed)

        return elapsed, remaining, est_total

    @staticmethod
    def _calculate_static_time_estimates(progress_data: dict) -> dict:
        """静态：为已有进度数据计算时间估算"""
        if 'start_time' not in progress_data or not progress_data['start_time']:
            return progress_data
        now = time.time()
        elapsed = now - progress_data['start_time']
        progress_data['elapsed_time'] = elapsed
        pct = progress_data.get('progress_percentage', 0)

        if pct >= 100:
            # 任务已完成
            est_total = elapsed
            remaining = 0
        else:
            # 使用预估的总时长（固定值），如果没有则使用默认值
            est_total = progress_data.get('estimated_total_time', 300)
            # 预计剩余 = 预估总时长 - 已用时间
            remaining = max(0, est_total - elapsed)

        progress_data['estimated_total_time'] = est_total
        progress_data['remaining_time'] = remaining
        return progress_data

    def update_progress(self, progress_update: Any) -> Dict[str, Any]:
        """update progress and persist; accepts dict or plain message string"""
        try:
            if isinstance(progress_update, dict):
                self.progress_data.update(progress_update)
            elif isinstance(progress_update, str):
                self.progress_data['last_message'] = progress_update
                self.progress_data['last_update'] = time.time()
            else:
                # try to coerce iterable of pairs; otherwise fallback to string
                try:
                    self.progress_data.update(dict(progress_update))
                except Exception:
                    self.progress_data['last_message'] = str(progress_update)
                    self.progress_data['last_update'] = time.time()

            # 根据进度百分比自动更新步骤状态
            progress_pct = self.progress_data.get('progress_percentage', 0)
            self._update_steps_by_progress(progress_pct)

            # 获取当前步骤索引
            current_step_index = self._detect_current_step()
            self.progress_data['current_step'] = current_step_index

            # 更新当前步骤的名称和描述
            if 0 <= current_step_index < len(self.analysis_steps):
                current_step_obj = self.analysis_steps[current_step_index]
                self.progress_data['current_step_name'] = current_step_obj.name
                self.progress_data['current_step_description'] = current_step_obj.description

            elapsed, remaining, est_total = self._calculate_time_estimates()
            self.progress_data['elapsed_time'] = elapsed
            self.progress_data['remaining_time'] = remaining
            self.progress_data['estimated_total_time'] = est_total

            # 更新 progress_data 中的 steps
            self.progress_data['steps'] = [asdict(step) for step in self.analysis_steps]

            self._save_progress()
            
            # 触发回调
            if self.on_update:
                try:
                    self.on_update(self.progress_data)
                except Exception as e:
                    logger.warning(f"Progress update callback failed: {e}")

            return self.progress_data
            logger.debug(f"[RedisProgress] updated: {self.task_id} - {self.progress_data.get('progress_percentage', 0)}%")
            return self.progress_data
        except Exception as e:
            logger.error(f"[RedisProgress] update failed: {self.task_id} - {e}")
            return self.progress_data

    def _update_steps_by_progress(self, progress_pct: float) -> None:
        """根据进度百分比自动更新步骤状态"""
        try:
            cumulative_weight = 0.0
            current_time = time.time()

            for step in self.analysis_steps:
                step_start_pct = cumulative_weight
                step_end_pct = cumulative_weight + (step.weight * 100)

                if progress_pct >= step_end_pct:
                    # 已完成的步骤
                    if step.status != 'completed':
                        step.status = 'completed'
                        step.end_time = current_time
                elif progress_pct > step_start_pct:
                    # 当前正在执行的步骤
                    if step.status != 'current':
                        step.status = 'current'
                        step.start_time = current_time
                else:
                    # 未开始的步骤
                    if step.status not in ('pending', 'failed'):
                        step.status = 'pending'

                cumulative_weight = step_end_pct
        except Exception as e:
            logger.debug(f"[RedisProgress] update steps by progress failed: {e}")

    def _detect_current_step(self) -> int:
        """detect current step index by status"""
        try:
            # 优先查找状态为 'current' 的步骤
            for index, step in enumerate(self.analysis_steps):
                if step.status == 'current':
                    return index
            # 如果没有 'current'，查找第一个 'pending' 的步骤
            for index, step in enumerate(self.analysis_steps):
                if step.status == 'pending':
                    return index
            # 如果都完成了，返回最后一个步骤的索引
            for index, step in enumerate(reversed(self.analysis_steps)):
                if step.status == 'completed':
                    return len(self.analysis_steps) - 1 - index
            return 0
        except Exception as e:
            logger.debug(f"[RedisProgress] detect current step failed: {e}")
            return 0

    def _find_step_by_name(self, step_name: str) -> Optional[AnalysisStep]:
        for step in self.analysis_steps:
            if step.name == step_name:
                return step
        return None

    def _find_step_by_pattern(self, pattern: str) -> Optional[AnalysisStep]:
        for step in self.analysis_steps:
            if pattern in step.name:
                return step
        return None

    def _save_progress(self) -> bool:
        """
        保存进度到 Redis 或文件
        
        🔥 修复 S5: 返回保存是否成功，并在失败时记录详细错误
        
        Returns:
            bool: 保存是否成功
        """
        try:
            progress_copy = self.to_dict()
            serialized = json.dumps(progress_copy)
            if self.use_redis and self.redis_client:
                key = f"progress:{self.task_id}"
                self.redis_client.set(key, serialized)
                self.redis_client.expire(key, 3600)
            else:
                os.makedirs("./data/progress", exist_ok=True)
                with open(f"./data/progress/{self.task_id}.json", 'w', encoding='utf-8') as f:
                    f.write(serialized)
            return True
        except Exception as e:
            logger.error(f"[RedisProgress] save progress failed: {self.task_id} - {e}")
            # 🔥 修复: 标记进度数据为不同步状态
            self.progress_data['_sync_error'] = str(e)
            self.progress_data['_sync_failed_at'] = time.time()
            return False

    def mark_completed(self) -> Dict[str, Any]:
        try:
            self.progress_data['progress_percentage'] = 100
            self.progress_data['status'] = 'completed'
            self.progress_data['completed'] = True
            self.progress_data['completed_time'] = time.time()
            for step in self.analysis_steps:
                if step.status != 'failed':
                    step.status = 'completed'
                    step.end_time = step.end_time or time.time()
            self._save_progress()
            return self.progress_data
        except Exception as e:
            logger.error(f"[RedisProgress] mark completed failed: {self.task_id} - {e}")
            return self.progress_data

    def mark_failed(self, reason: str = "") -> Dict[str, Any]:
        try:
            self.progress_data['status'] = 'failed'
            self.progress_data['failed'] = True
            self.progress_data['failed_reason'] = reason
            self.progress_data['completed_time'] = time.time()
            for step in self.analysis_steps:
                if step.status not in ('completed', 'failed'):
                    step.status = 'failed'
                    step.end_time = step.end_time or time.time()
            self._save_progress()
            return self.progress_data
        except Exception as e:
            logger.error(f"[RedisProgress] mark failed failed: {self.task_id} - {e}")
            return self.progress_data

    def to_dict(self) -> Dict[str, Any]:
        try:
            return {
                'task_id': self.task_id,
                'analysts': self.analysts,
                'phase_config': self.phase_config,
                'llm_provider': self.llm_provider,
                'steps': [asdict(step) for step in self.analysis_steps],
                'start_time': self.progress_data.get('start_time'),
                'elapsed_time': self.progress_data.get('elapsed_time', 0),
                'remaining_time': self.progress_data.get('remaining_time', 0),
                'estimated_total_time': self.progress_data.get('estimated_total_time', 0),
                'progress_percentage': self.progress_data.get('progress_percentage', 0),
                'status': self.progress_data.get('status', 'pending'),
                'current_step': self.progress_data.get('current_step')
            }
        except Exception as e:
            logger.error(f"[RedisProgress] to_dict failed: {self.task_id} - {e}")
            return self.progress_data





def get_progress_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    """根据任务ID获取进度（与旧实现一致，修正 cls 引用）"""
    try:
        # 检查REDIS_ENABLED环境变量
        redis_enabled = os.getenv('REDIS_ENABLED', 'false').lower() == 'true'

        # 如果Redis启用，先尝试Redis
        if redis_enabled:
            try:
                import redis

                # 从环境变量获取Redis配置
                redis_host = os.getenv('REDIS_HOST', 'localhost')
                redis_port = int(os.getenv('REDIS_PORT', 6379))
                redis_password = os.getenv('REDIS_PASSWORD', None)
                redis_db = int(os.getenv('REDIS_DB', 0))

                # 创建Redis连接
                if redis_password:
                    redis_client = redis.Redis(
                        host=redis_host,
                        port=redis_port,
                        password=redis_password,
                        db=redis_db,
                        decode_responses=True
                    )
                else:
                    redis_client = redis.Redis(
                        host=redis_host,
                        port=redis_port,
                        db=redis_db,
                        decode_responses=True
                    )

                key = f"progress:{task_id}"
                data = redis_client.get(key)
                if data:
                    progress_data = json.loads(data)
                    progress_data = RedisProgressTracker._calculate_static_time_estimates(progress_data)
                    return progress_data
            except Exception as e:
                logger.debug(f"📊 [Redis进度] Redis读取失败: {e}")

        # 尝试从文件读取
        progress_file = f"./data/progress/{task_id}.json"
        if os.path.exists(progress_file):
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress_data = json.load(f)
                progress_data = RedisProgressTracker._calculate_static_time_estimates(progress_data)
                return progress_data

        # 尝试备用文件位置
        backup_file = f"./data/progress_{task_id}.json"
        if os.path.exists(backup_file):
            with open(backup_file, 'r', encoding='utf-8') as f:
                progress_data = json.load(f)
                progress_data = RedisProgressTracker._calculate_static_time_estimates(progress_data)
                return progress_data

        return None

    except Exception as e:
        logger.error(f"📊 [Redis进度] 获取进度失败: {task_id} - {e}")
        return None
