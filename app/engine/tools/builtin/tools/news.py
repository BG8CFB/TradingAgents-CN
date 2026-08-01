"""
新闻工具 - 股票新闻数据获取
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.utils.time_utils import now_utc
from app.engine.tools.common.tool_result import success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from app.engine.tools.common.format import format_result
from app.core.async_utils import run_async
from app.data.sources.cn.tushare.api.news import _fetch_targeted_news
logger = logging.getLogger(__name__)


def _get_market_for_code(stock_code: str) -> str:
    """根据股票代码判断市场。"""
    try:
        from app.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(stock_code)
        if market_info.get('is_hk'):
            return "HK"
        if market_info.get('is_us'):
            return "US"
    except Exception as e:
        logger.debug(f"市场类型检测失败，默认CN: {e}")
        pass
    return "CN"


def _clean_symbol(stock_code: str) -> str:
    """清理股票代码后缀。"""
    return stock_code.replace('.SH', '').replace('.SZ', '').replace('.SS', '') \
                     .replace('.XSHE', '').replace('.XSHG', '').replace('.HK', '')


def _get_industry_info(stock_code: str) -> dict:
    """获取股票的行业分类信息（一级行业、二级行业、上下游）。"""
    info = {"l1": None, "l2": None, "upstream": [], "downstream": [], "stock_name": None}
    ts_code = f"{stock_code}.SZ" if stock_code.startswith(('0', '3')) else f"{stock_code}.SH"

    try:
        from app.data.sources.cn.stock_name_utils import get_stock_name_sync
        info["stock_name"] = get_stock_name_sync(stock_code)
    except Exception:
        pass

    try:
        from app.data.sources.cn.tushare.api.connection import get_tushare_api
        conn = get_tushare_api()
        if not conn.is_available():
            return info

        # 遍历同花顺行业找到所属行业
        df_industries = conn.api.ths_index(type='I')
        if df_industries is None or df_industries.empty:
            return info

        for _, row in df_industries.iterrows():
            try:
                m = conn.api.ths_member(ts_code=row['ts_code'])
                if m is not None and not m.empty and ts_code in m['con_code'].values:
                    info["l1"] = row['name']
                    break
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"获取行业信息失败: {e}")

    return info


def _append_news(news_list: list, items: list, category: str, seen_titles: set):
    """添加新闻到列表（去重）。"""
    for item in items:
        title = item.get('title', '')
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        news_list.append({
            'title': title,
            'content': item.get('content', '') or item.get('summary', ''),
            'source': f"{item.get('source', item.get('data_source', '未知'))} ({category})",
            'publish_time': item.get('publish_time', now_utc()),
            'sentiment': item.get('sentiment', 'neutral'),
            'url': item.get('url', ''),
        })


def _fetch_news_data(stock_code: str, max_results: int = 10) -> list:
    """分层获取新闻：A股市场 → 一级行业 → 二级行业 → 上下游 → 个股。"""
    news_list = []
    seen_titles = set()
    market = _get_market_for_code(stock_code)
    clean_code = _clean_symbol(stock_code)

    # 获取行业信息
    industry = _get_industry_info(clean_code)
    stock_name = industry.get("stock_name") or clean_code

    # ── 第1层：A股整体市场新闻（DB） ──
    try:
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()
        result = run_async(di.read(market, "news"))
        data = result.get("data")
        if data and isinstance(data, list):
            _append_news(news_list, data[:max_results], "A股市场", seen_titles)
            logger.info(f"[新闻工具] A股市场新闻: {len(data)} 条")
    except Exception as e:
        logger.warning(f"[新闻工具] 市场新闻获取失败: {e}")

    # ── 第2层：一级行业新闻（tushare 按行业搜索） ──
    if industry.get("l1"):
        try:
            from app.data.sources.cn.tushare.api.connection import get_tushare_api
            from app.data.sources.cn.tushare.api.news import fetch_news
            conn = get_tushare_api()
            if conn.is_available():
                # 用行业名称作为关键词搜索
                l1_name = industry["l1"].replace("(A股)", "").strip()
                result = run_async(fetch_news(conn, symbol=l1_name, limit=max_results))
                if result and isinstance(result, list):
                    _append_news(news_list, result, f"行业:{l1_name}", seen_titles)
                    logger.info(f"[新闻工具] 一级行业({l1_name})新闻: {len(result)} 条")
        except Exception as e:
            logger.debug(f"[新闻工具] 一级行业新闻失败: {e}")

    # ── 第3层：个股新闻（tushare 按股票代码搜索） ──
    try:
        from app.data.sources.cn.tushare.api.connection import get_tushare_api
        from app.data.sources.cn.tushare.api.news import fetch_news
        conn = get_tushare_api()
        if conn.is_available():
            result = run_async(fetch_news(conn, symbol=clean_code, limit=max_results))
            if result and isinstance(result, list):
                _append_news(news_list, result, "个股", seen_titles)
                logger.info(f"[新闻工具] 个股({clean_code})新闻: {len(result)} 条")
    except Exception as e:
        logger.debug(f"[新闻工具] 个股新闻失败: {e}")

    if news_list:
        logger.info(f"[新闻工具] 最终返回: {len(news_list)} 条")
        return news_list

    # 最终回退：DB refresh
    try:
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()
        refresh_result = run_async(di.refresh(market, clean_code, domains=["news"], force=True, timeout=30))
        if refresh_result and refresh_result.domains.get("news"):
            result = run_async(di.read(market, "news", symbol=clean_code))
            data = result.get("data")
            if data and isinstance(data, list):
                _append_news(news_list, data, "Refreshed", seen_titles)
    except Exception as e:
        logger.warning(f"[新闻工具] 刷新失败: {e}")

    return news_list


def _format_news_list(news_list: list, source_label: str = None) -> str:
    """格式化新闻列表为 Markdown（按来源分组）。"""
    if not news_list:
        return "暂无新闻数据"

    report = f"# 最新新闻 {'(' + source_label + ')' if source_label else ''}\n\n"
    report += f"查询时间: {now_utc().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"新闻数量: {len(news_list)} 条\n\n"

    # 按来源分组
    groups = {}
    for news in news_list:
        source = news.get('source', '未知来源')
        # 从 source 中提取分组标签: "tushare (个股)" → "个股"
        if '(' in source and ')' in source:
            group = source.split('(')[-1].rstrip(')')
        else:
            group = "其他"
        groups.setdefault(group, []).append(news)

    # 按优先级排序：A股市场 → 行业 → 个股 → 其他
    priority = {"A股市场": 0, "行业": 1, "个股": 2, "其他": 3, "DB": 4, "Refreshed": 5}
    sorted_groups = sorted(groups.items(), key=lambda x: priority.get(x[0], 99))

    idx = 1
    for group_name, items in sorted_groups:
        report += f"## 【{group_name}】({len(items)} 条)\n\n"
        for news in items[:8]:  # 每组最多8条
            title = news.get('title', '无标题')
            content = news.get('content', '')
            source = news.get('source', '未知来源')
            pub_time = news.get('publish_time', now_utc())
            if isinstance(pub_time, datetime):
                pub_time_str = pub_time.strftime('%m-%d %H:%M')
            else:
                pub_time_str = str(pub_time)[:16]

            sentiment = news.get('sentiment', 'neutral')
            sentiment_icon = {"positive": "↑", "negative": "↓", "neutral": "→"}.get(sentiment, "")

            report += f"{idx}. **{title}** {sentiment_icon}\n"
            report += f"   {source} | {pub_time_str}\n"
            if content:
                preview = content[:200] + '...' if len(content) > 200 else content
                report += f"   {preview}\n"
            report += "\n"
            idx += 1

    return report


def get_stock_news(
    stock_code: str,
    max_results: int = 10
) -> str:
    """
    获取指定股票的最新新闻。

    返回格式化的新闻列表，包含标题、来源、时间和摘要。

    Args:
        stock_code: 股票代码，如 "000001.SZ"(A股)、"AAPL"(美股)、"00700.HK"(港股)
        max_results: 返回的最大新闻数，建议范围 5-20，默认 10

    Returns:
        JSON 格式的 ToolResult，包含 status、data、error_code、suggestion 字段
    """
    if not stock_code:
        return format_tool_result(error_result(
            ErrorCodes.MISSING_PARAM,
            "未提供股票代码"
        ))

    try:
        news_list = _fetch_news_data(stock_code, max_results)

        if news_list:
            return format_tool_result(success_result(_format_news_list(news_list, "多源聚合")))

        return format_tool_result(no_data_result(
            message=f"未找到 {stock_code} 的新闻数据",
            suggestion="这是正常状态，不要重试或尝试其他参数"
        ))
    except Exception as e:
        logger.error(f"get_stock_news failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            str(e)
        ))


def get_announcements(
    stock_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取上市公司公告（重大事项、股东大会、业绩披露等）。"""
    try:
        import pandas as pd
        from app.data.core.interface import DataInterface
        if not end_date:
            end_date = now_utc().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (now_utc() - timedelta(days=90)).strftime('%Y-%m-%d')
        clean_code = _clean_symbol(stock_code)
        di = DataInterface.get_instance()
        result = run_async(di.read("CN", "announcement", symbol=clean_code,
                                   start_date=start_date, end_date=end_date))
        data = result.get("data")
        if data:
            df = pd.DataFrame(data) if isinstance(data, list) else data
            return format_tool_result(success_result(format_result(df, f"公告: {stock_code}")))

        # 兜底：DB 无同步公告时，改走东方财富公告实时接口拉取。
        # 说明：tushare 的 anns/major_anns 接口当前 token 返回"接口不存在"，故不复用 tushare；
        # 而 _fetch_targeted_news（东方财富公告 API）已验证可用于按代码取公告。
        try:
            targeted = run_async(_fetch_targeted_news(clean_code, 10))
            if targeted:
                fallback_df = pd.DataFrame([{
                    "title": n.get("title", ""),
                    "publish_time": n.get("publish_time", ""),
                    "source": n.get("source", ""),
                    "url": n.get("url", ""),
                } for n in targeted])
                logger.info(f"[公告兜底] 东方财富实时公告: {len(targeted)} 条 ({stock_code})")
                return format_tool_result(success_result(
                    format_result(fallback_df, f"公告(实时兜底): {stock_code}")
                ))
        except Exception as fe:
            logger.warning(f"[公告兜底] 东方财富实时公告获取失败: {fe}")

        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, f"{stock_code} 无公告数据",
            suggestion="请先同步公告数据"
        ))
    except Exception as e:
        logger.error(f"get_announcements failed: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, str(e)))
