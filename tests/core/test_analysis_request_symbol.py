"""回归：分析请求的标的解析必须兼容新旧字段。

背景（真实事故）：
`SingleAnalysisRequest` 迁移到 `symbol` 字段后，`app/services/analysis_service.py`
里有 5 处已改用 `request.get_symbol()`，但最关键的两处漏改，仍读已废弃的
`request.stock_code`：

* `propagate_sync(request.stock_code, ...)` —— 决定整个流水线的
  `company_of_interest`，漏改会让只传 `symbol` 的客户端拿到「标的 None」，
  六位分析师全部在提示词里看到 `请对股票 None (None)`，报告只能写「数据获取失败」。
* 结果字典 `stock_code` / `stock_symbol` —— 落库与分析报告里的标的记录。

这里同时守住「模型语义」与「调用点不再回退到废弃字段」两层。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.analysis import SingleAnalysisRequest

SERVICE_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "services" / "analysis_service.py"
)


class TestSingleAnalysisRequestSymbol:
    """:meth:`SingleAnalysisRequest.get_symbol` 是新旧字段的唯一正确入口。"""

    def test_symbol_only(self) -> None:
        """只传新字段 symbol —— 事故场景，get_symbol 必须返回它。"""
        req = SingleAnalysisRequest(symbol="605589")
        assert req.get_symbol() == "605589"

    def test_stock_code_only(self) -> None:
        """只传废弃字段 stock_code —— 老客户端仍要能用。"""
        req = SingleAnalysisRequest(stock_code="605589")
        assert req.get_symbol() == "605589"

    def test_symbol_wins_over_stock_code(self) -> None:
        """两个都传时以新字段为准。"""
        req = SingleAnalysisRequest(symbol="605589", stock_code="000001")
        assert req.get_symbol() == "605589"

    def test_both_empty_rejected(self) -> None:
        """两个都空必须校验失败，不允许静默产出空标的分析。"""
        with pytest.raises(Exception):
            SingleAnalysisRequest()

    def test_deprecated_field_alone_leaves_symbol_empty(self) -> None:
        """把事故根因写成断言：只传 symbol 时，`request.stock_code` 就是 None。

        任何直接读 `request.stock_code` 的调用点都会因此拿到 None。
        """
        req = SingleAnalysisRequest(symbol="605589")
        assert req.stock_code is None


class TestAnalysisServiceUsesGetSymbol:
    """静态守卫：生产代码不得再直接读废弃字段。"""

    def test_no_deprecated_field_reads(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        offenders = [
            f"{i}: {line.strip()}"
            for i, line in enumerate(source.splitlines(), 1)
            if re.search(r"request\.stock_code\b", line)
            and not line.strip().startswith("#")
        ]
        assert not offenders, (
            "analysis_service.py 仍在直接读 request.stock_code（已废弃字段），"
            "只传 symbol 的客户端会拿到 None：\n" + "\n".join(offenders)
        )

    def test_pipeline_gets_resolved_symbol(self) -> None:
        """propagate_sync 的标的实参必须是解析后的 symbol。"""
        source = SERVICE_PATH.read_text(encoding="utf-8")
        # 容忍实参前的注释与空白：只要求 propagate_sync( 的第一个实参是 request.get_symbol()
        import re as _re

        m = _re.search(
            r"propagate_sync\(\s*(?:#[^\n]*\n\s*)*request\.get_symbol\(\)", source
        )
        assert m, "propagate_sync 的首个实参必须是 request.get_symbol()"
        # 且不得再读已废弃的 request.stock_code
        assert "propagate_sync(\n                    request.stock_code" not in source
