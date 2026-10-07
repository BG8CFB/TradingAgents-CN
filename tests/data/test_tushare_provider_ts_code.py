"""TushareCNProvider._to_ts_code 的市场后缀映射（回归测试）。

背景：该映射曾漏掉两类代码段，导致整批标的取不到数据——
  - 沪市基金/ETF（5 开头，如 510050/588000/560000）被误判为 .SZ；
  - 北交所 920 新代码段被误判为 .SZ。
后果：对应标的在资金流/复权/财务等域全量为空。
"""

import pytest

from app.data.sources.cn.tushare.provider import TushareCNProvider


class TestToTsCode:
    """symbol → 带市场后缀的 ts_code。"""

    @pytest.mark.parametrize(
        ("code", "suffix"),
        [
            # 沪市：股票、科创板、B股
            ("600519", ".SH"),
            ("688111", ".SH"),
            ("900901", ".SH"),
            # 沪市：基金 / ETF（回归点）
            ("510050", ".SH"),
            ("588000", ".SH"),
            ("560000", ".SH"),
            # 深市：股票、创业板、基金
            ("000001", ".SZ"),
            ("300750", ".SZ"),
            ("159915", ".SZ"),
            # 北交所：4/8 段
            ("430047", ".BJ"),
            ("830799", ".BJ"),
            ("871981", ".BJ"),
            # 北交所：920 新代码段（回归点）
            ("920001", ".BJ"),
            ("920099", ".BJ"),
        ],
    )
    def test_market_suffix(self, code: str, suffix: str) -> None:
        assert TushareCNProvider._to_ts_code(code).endswith(suffix)

    def test_short_code_is_zero_padded(self) -> None:
        assert TushareCNProvider._to_ts_code("1") == "000001.SZ"
