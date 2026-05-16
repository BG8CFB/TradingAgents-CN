"""
多维度循环检测器

检测以下循环模式：
1. 连续相同工具（A → A → A）
2. 交替循环（A → B → A → B）
3. 三角循环（A → B → C → A → B → C）
4. 同工具不同参数（A(x=1) → A(x=2) → A(x=3)）
5. 错误重试循环（工具失败 → 重试 → 又失败）
"""

import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from app.utils.logging_init import get_logger

logger = get_logger("executors.loop_detector")


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    tool_name: str
    args: Dict
    result_summary: str = ""
    is_error: bool = False
    error_type: Optional[str] = None


@dataclass
class LoopDetectionResult:
    """循环检测结果"""
    is_loop: bool = False
    loop_type: Optional[str] = None  # same / alternate / triangle / similar_args / error_retry
    confidence: float = 0.0
    message: str = ""  # 给 LLM 的警告消息
    triggered_tools: List[str] = field(default_factory=list)


class LoopDetector:
    """
    多维度循环检测器

    通过多个独立检测维度综合判断是否存在循环行为。
    任一维度触发即认为检测到循环，置信度取最高值。
    """

    def __init__(
        self,
        max_consecutive_same: int = 2,
        max_window_repeats: int = 3,
        window_size: int = 6,
        similarity_threshold: float = 0.85,
        max_error_retry: int = 2,
    ):
        """
        Args:
            max_consecutive_same: 连续相同工具调用阈值（超过则认为循环）
            max_window_repeats: 滑动窗口内同一工具重复阈值
            window_size: 滑动窗口大小
            similarity_threshold: 参数相似度阈值（0-1）
            max_error_retry: 同一工具错误重试次数阈值
        """
        self.max_consecutive_same = max_consecutive_same
        self.max_window_repeats = max_window_repeats
        self.window_size = window_size
        self.similarity_threshold = similarity_threshold
        self.max_error_retry = max_error_retry

    def check(
        self,
        current_tool_calls: List[Dict],
        history: List[ToolCallRecord],
    ) -> LoopDetectionResult:
        """
        检测当前工具调用是否构成循环

        Args:
            current_tool_calls: 当前 LLM 响应中的 tool_calls
            history: 历史工具调用记录

        Returns:
            LoopDetectionResult
        """
        if not current_tool_calls:
            return LoopDetectionResult(is_loop=False)

        # 提取当前工具签名
        current_names = sorted([tc.get("name", "") for tc in current_tool_calls if tc.get("name")])
        current_signature = ",".join(current_names)

        # 维度1: 连续相同工具检测
        result = self._check_consecutive_same(current_signature, history)
        if result.is_loop:
            logger.warning(f"🚨 [循环检测] 连续相同工具触发: {result.message}")
            return result

        # 维度2: 滑动窗口重复检测
        result = self._check_window_repeats(history)
        if result.is_loop:
            logger.warning(f"🚨 [循环检测] 窗口重复触发: {result.message}")
            return result

        # 维度3: 交替循环检测
        result = self._check_alternate_loop(history)
        if result.is_loop:
            logger.warning(f"🚨 [循环检测] 交替循环触发: {result.message}")
            return result

        # 维度4: 三角循环检测
        result = self._check_triangle_loop(history)
        if result.is_loop:
            logger.warning(f"🚨 [循环检测] 三角循环触发: {result.message}")
            return result

        # 维度5: 同工具不同参数检测
        result = self._check_similar_args(history)
        if result.is_loop:
            logger.warning(f"🚨 [循环检测] 相似参数触发: {result.message}")
            return result

        # 维度6: 错误重试循环检测
        result = self._check_error_retry(history)
        if result.is_loop:
            logger.warning(f"🚨 [循环检测] 错误重试触发: {result.message}")
            return result

        return LoopDetectionResult(is_loop=False)

    def _check_consecutive_same(
        self, current_signature: str, history: List[ToolCallRecord]
    ) -> LoopDetectionResult:
        """检测连续相同工具组合"""
        if not current_signature or not history:
            return LoopDetectionResult(is_loop=False)

        # 计算连续相同次数
        consecutive_count = 0
        for record in reversed(history):
            record_sig = record.tool_name
            # 如果历史是多工具调用，需要比较组合签名
            # 简化：比较单工具名或组合名
            if record_sig == current_signature or (
                len(current_names := current_signature.split(",")) == 1
                and record.tool_name == current_names[0]
            ):
                consecutive_count += 1
            else:
                break

        if consecutive_count >= self.max_consecutive_same:
            return LoopDetectionResult(
                is_loop=True,
                loop_type="same",
                confidence=min(1.0, consecutive_count / (self.max_consecutive_same + 1)),
                message=(
                    f"⚠️ 检测到连续 {consecutive_count} 次调用相同工具 [{current_signature}]。"
                    f"请停止重复调用，基于已有数据生成报告。"
                ),
                triggered_tools=current_signature.split(",") if current_signature else [],
            )
        return LoopDetectionResult(is_loop=False)

    def _check_window_repeats(self, history: List[ToolCallRecord]) -> LoopDetectionResult:
        """检测滑动窗口内工具重复次数"""
        if len(history) < self.window_size:
            return LoopDetectionResult(is_loop=False)

        recent = history[-self.window_size:]
        tool_counts: Dict[str, int] = {}
        for record in recent:
            tool_counts[record.tool_name] = tool_counts.get(record.tool_name, 0) + 1

        for tool_name, count in tool_counts.items():
            if count >= self.max_window_repeats:
                return LoopDetectionResult(
                    is_loop=True,
                    loop_type="window_repeat",
                    confidence=min(1.0, count / self.max_window_repeats),
                    message=(
                        f"⚠️ 工具 [{tool_name}] 在最近 {self.window_size} 次调用中出现了 {count} 次。"
                        f"这可能表明陷入了循环。请换用其他工具或直接生成报告。"
                    ),
                    triggered_tools=[tool_name],
                )
        return LoopDetectionResult(is_loop=False)

    def _check_alternate_loop(self, history: List[ToolCallRecord]) -> LoopDetectionResult:
        """检测交替循环模式（A→B→A→B）"""
        if len(history) < 4:
            return LoopDetectionResult(is_loop=False)

        recent = history[-4:]
        names = [r.tool_name for r in recent]

        # 检测 A→B→A→B 模式
        if names[0] == names[2] and names[1] == names[3] and names[0] != names[1]:
            return LoopDetectionResult(
                is_loop=True,
                loop_type="alternate",
                confidence=0.85,
                message=(
                    f"⚠️ 检测到交替循环模式: {names[0]} → {names[1]} → {names[0]} → {names[1]}。"
                    f"请停止在两个工具之间反复切换，基于已有数据生成报告。"
                ),
                triggered_tools=[names[0], names[1]],
            )
        return LoopDetectionResult(is_loop=False)

    def _check_triangle_loop(self, history: List[ToolCallRecord]) -> LoopDetectionResult:
        """检测三角循环模式（A→B→C→A→B→C）"""
        if len(history) < 6:
            return LoopDetectionResult(is_loop=False)

        recent = history[-6:]
        names = [r.tool_name for r in recent]

        # 检测 A→B→C→A→B→C 模式
        if names[0] == names[3] and names[1] == names[4] and names[2] == names[5]:
            if len(set(names[:3])) == 3:  # A, B, C 互不相同
                return LoopDetectionResult(
                    is_loop=True,
                    loop_type="triangle",
                    confidence=0.9,
                    message=(
                        f"⚠️ 检测到三角循环模式: {names[0]} → {names[1]} → {names[2]} 反复出现。"
                        f"请在三个工具之外寻找新信息，或直接基于已有数据生成报告。"
                    ),
                    triggered_tools=names[:3],
                )
        return LoopDetectionResult(is_loop=False)

    def _check_similar_args(self, history: List[ToolCallRecord]) -> LoopDetectionResult:
        """检测同一工具被用相似参数反复调用"""
        if len(history) < 3:
            return LoopDetectionResult(is_loop=False)

        # 按工具名分组，检查每组最近三次的参数相似度
        tool_groups: Dict[str, List[ToolCallRecord]] = {}
        for record in history:
            tool_groups.setdefault(record.tool_name, []).append(record)

        for tool_name, records in tool_groups.items():
            if len(records) < 3:
                continue

            # 检查最近三次的参数相似度
            recent_three = records[-3:]
            similarities = []
            for i in range(len(recent_three) - 1):
                args_a = json.dumps(recent_three[i].args, sort_keys=True, ensure_ascii=False)
                args_b = json.dumps(recent_three[i + 1].args, sort_keys=True, ensure_ascii=False)
                similarity = SequenceMatcher(None, args_a, args_b).ratio()
                similarities.append(similarity)

            # 如果三次参数高度相似，认为在循环
            if all(s > self.similarity_threshold for s in similarities):
                return LoopDetectionResult(
                    is_loop=True,
                    loop_type="similar_args",
                    confidence=sum(similarities) / len(similarities),
                    message=(
                        f"⚠️ 工具 [{tool_name}] 被用非常相似的参数连续调用了 {len(recent_three)} 次。"
                        f"如果前几次调用未能获取有效数据，请尝试更换工具或调整参数，"
                        f"而不是反复微调相同参数。"
                    ),
                    triggered_tools=[tool_name],
                )
        return LoopDetectionResult(is_loop=False)

    def _check_error_retry(self, history: List[ToolCallRecord]) -> LoopDetectionResult:
        """检测错误重试循环（同一工具反复失败）"""
        if len(history) < 2:
            return LoopDetectionResult(is_loop=False)

        # 按工具名检查连续失败次数
        error_streak: Dict[str, int] = {}
        for record in reversed(history):
            if record.is_error:
                error_streak[record.tool_name] = error_streak.get(record.tool_name, 0) + 1
            else:
                # 遇到成功调用，重置该工具的计数
                if record.tool_name in error_streak:
                    break

        for tool_name, count in error_streak.items():
            if count >= self.max_error_retry:
                return LoopDetectionResult(
                    is_loop=True,
                    loop_type="error_retry",
                    confidence=min(1.0, count / (self.max_error_retry + 1)),
                    message=(
                        f"⚠️ 工具 [{tool_name}] 已连续失败 {count} 次。"
                        f"请停止使用该工具，尝试其他数据源或直接基于已有数据生成报告。"
                    ),
                    triggered_tools=[tool_name],
                )
        return LoopDetectionResult(is_loop=False)
