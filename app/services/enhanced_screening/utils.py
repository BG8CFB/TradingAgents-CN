"""
Utility helpers for EnhancedScreeningService to separate analysis and conversion logic.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.screening import ScreeningCondition, FieldType, BASIC_FIELDS_INFO


def analyze_conditions(conditions: List[ScreeningCondition]) -> Dict[str, Any]:
    analysis = {
        "total_conditions": len(conditions),
        "database_supported_conditions": 0,
        "technical_conditions": 0,
        "fundamental_conditions": 0,
        "basic_conditions": 0,
        "can_use_database": True,
        "needs_technical_indicators": False,
        "unsupported_fields": [],
        "condition_types": [],
    }

    for condition in conditions:
        field = condition.field

        if field in BASIC_FIELDS_INFO:
            field_info = BASIC_FIELDS_INFO[field]
            field_type = field_info.field_type

            if field_type == FieldType.BASIC:
                analysis["basic_conditions"] += 1
            elif field_type == FieldType.FUNDAMENTAL:
                analysis["fundamental_conditions"] += 1
            elif field_type == FieldType.TECHNICAL:
                analysis["technical_conditions"] += 1

            analysis["condition_types"].append(field_type.value)

            if field in set(BASIC_FIELDS_INFO.keys()):
                analysis["database_supported_conditions"] += 1
            else:
                analysis["can_use_database"] = False
                analysis["unsupported_fields"].append(field)
        else:
            analysis["can_use_database"] = False
            analysis["needs_technical_indicators"] = True
            analysis["unsupported_fields"].append(field)

    if analysis["technical_conditions"] > 0 or analysis["needs_technical_indicators"]:
        analysis["needs_technical_indicators"] = True

    return analysis


def convert_conditions_to_traditional_format(conditions: List[ScreeningCondition]) -> Dict[str, Any]:
    """将 ScreeningCondition 列表转为 eval_utils 期望的 DSL 树结构。

    DSL 格式:
      单条件叶节点: {"field": "pe", "op": ">", "value": 15}
      多条件组节点: {"op": "group", "logic": "AND", "children": [...]}
    空条件列表返回 {}，eval_utils 对空节点直接返回 True。
    """
    if not conditions:
        return {}

    children = []
    for condition in conditions:
        children.append({
            "field": condition.field,
            "op": condition.operator,  # use_enum_values=True → 已是字符串
            "value": condition.value,
        })

    if len(children) == 1:
        return children[0]

    return {
        "op": "group",
        "logic": "AND",
        "children": children,
    }

