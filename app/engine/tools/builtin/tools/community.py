"""
社区情绪工具 - 个股社区讨论热度与机构参与度

数据来源：东方财富（akshare）
"""
import logging
from typing import Optional

from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes

logger = logging.getLogger(__name__)


def get_community_sentiment(
    stock_code: str,
) -> str:
    """
    获取个股社区讨论热度、综合评分、机构参与度等量化指标。

    数据来源为东方财富，反映市场对该股票的关注度和机构参与情况。

    Args:
        stock_code: 股票代码，如 "000001"

    Returns:
        JSON 格式的 ToolResult
    """
    try:
        import akshare as ak
        symbol = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                           .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)

        sections = []

        # 1. 综合评分（近30天趋势）
        try:
            df_score = ak.stock_comment_detail_zhpj_lspf_em(symbol=symbol)
            if df_score is not None and not df_score.empty:
                latest = df_score.iloc[-1]
                avg = df_score['评分'].mean()
                trend = "上升" if df_score['评分'].iloc[-1] > df_score['评分'].iloc[-5] else "下降"
                sections.append(
                    f"## 综合评分（东方财富）\n"
                    f"- 最新评分: {latest['评分']:.1f}\n"
                    f"- 30日均值: {avg:.1f}\n"
                    f"- 近期趋势: {trend}\n"
                    f"- 评分区间: {df_score['评分'].min():.1f} ~ {df_score['评分'].max():.1f}"
                )
        except Exception as e:
            logger.debug(f"综合评分获取失败: {e}")

        # 2. 机构参与度
        try:
            df_inst = ak.stock_comment_detail_zlkp_jgcyd_em(symbol=symbol)
            if df_inst is not None and not df_inst.empty:
                latest_inst = df_inst.iloc[-1]
                avg_inst = df_inst['机构参与度'].mean()
                sections.append(
                    f"## 机构参与度\n"
                    f"- 最新参与度: {latest_inst['机构参与度']:.2f}%\n"
                    f"- 均值: {avg_inst:.2f}%"
                )
        except Exception as e:
            logger.debug(f"机构参与度获取失败: {e}")

        # 3. 用户关注度
        try:
            df_focus = ak.stock_comment_detail_scrd_focus_em(symbol=symbol)
            if df_focus is not None and not df_focus.empty:
                latest_focus = df_focus.iloc[-1]
                sections.append(
                    f"## 用户关注度\n"
                    f"- 最新关注指数: {latest_focus['用户关注指数']:.1f}"
                )
        except Exception as e:
            logger.debug(f"用户关注度获取失败: {e}")

        # 4. 市场综合评论（全市场排名）
        try:
            df_comment = ak.stock_comment_em()
            if df_comment is not None and not df_comment.empty:
                row = df_comment[df_comment['代码'] == symbol]
                if not row.empty:
                    r = row.iloc[0]
                    sections.append(
                        f"## 市场综合评论\n"
                        f"- 综合得分: {r.get('综合得分', 'N/A')}\n"
                        f"- 关注指数: {r.get('关注指数', 'N/A')}\n"
                        f"- 排名: {r.get('目前排名', 'N/A')}\n"
                        f"- 排名变化: {r.get('上升', 'N/A')}"
                    )
        except Exception as e:
            logger.debug(f"市场综合评论获取失败: {e}")

        if not sections:
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"无法获取 {stock_code} 的社区情绪数据",
                suggestion="请确认股票代码正确"
            ))

        result = f"# {stock_code} 社区情绪分析\n\n" + "\n\n".join(sections)
        return format_tool_result(success_result(result))

    except Exception as e:
        logger.error(f"get_community_sentiment failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, str(e)
        ))
