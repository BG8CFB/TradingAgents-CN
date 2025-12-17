"""
AKShare data source adapter
"""
from typing import Optional, Dict
import logging
import requests
import json
from datetime import datetime, timedelta
import pandas as pd

from .base import DataSourceAdapter

logger = logging.getLogger(__name__)


class AKShareAdapter(DataSourceAdapter):
    """AKShare数据源适配器"""

    def __init__(self):
        super().__init__()  # 调用父类初始化

    @property
    def name(self) -> str:
        return "akshare"

    def _get_default_priority(self) -> int:
        return 2  # 数字越大优先级越高

    def is_available(self) -> bool:
        """检查AKShare是否可用"""
        try:
            import akshare as ak  # noqa: F401
            
            # 修复 pandas read_excel 问题
            import pandas as pd
            if not hasattr(pd, '_read_excel_patched_adapter'):
                original_read_excel = pd.read_excel
                
                def patched_read_excel(io, **kwargs):
                    if 'engine' not in kwargs:
                        # 优先尝试 openpyxl
                        try:
                            return original_read_excel(io, engine='openpyxl', **kwargs)
                        except:
                            pass
                    return original_read_excel(io, **kwargs)
                    
                pd.read_excel = patched_read_excel
                pd._read_excel_patched_adapter = True
                
            return True
        except ImportError:
            return False

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取股票列表（使用 AKShare 的 stock_info_a_code_name 接口获取真实股票名称）"""
        if not self.is_available():
            return None
        try:
            import akshare as ak
            logger.info("AKShare: Fetching stock list with real names from stock_info_a_code_name()...")

            # 使用 AKShare 的 stock_info_a_code_name 接口获取股票代码和名称
            df = ak.stock_info_a_code_name()

            if df is None or df.empty:
                logger.warning("AKShare: stock_info_a_code_name() returned empty data")
                return None

            # 标准化列名（AKShare 返回的列名可能是中文）
            # 通常返回的列：code（代码）、name（名称）
            df = df.rename(columns={
                'code': 'symbol',
                '代码': 'symbol',
                'name': 'name',
                '名称': 'name'
            })

            # 确保有必需的列
            if 'symbol' not in df.columns or 'name' not in df.columns:
                logger.error(f"AKShare: Unexpected column names: {df.columns.tolist()}")
                return None

            # 生成 ts_code 和其他字段
            def generate_ts_code(code: str) -> str:
                """根据股票代码生成 ts_code"""
                if not code:
                    return ""
                code = str(code).zfill(6)
                if code.startswith(('60', '68', '90')):
                    return f"{code}.SH"
                elif code.startswith(('00', '30', '20')):
                    return f"{code}.SZ"
                elif code.startswith(('8', '4')):
                    return f"{code}.BJ"
                else:
                    return f"{code}.SZ"  # 默认深圳

            def get_market(code: str) -> str:
                """根据股票代码判断市场"""
                if not code:
                    return ""
                code = str(code).zfill(6)
                if code.startswith('000'):
                    return '主板'
                elif code.startswith('002'):
                    return '中小板'
                elif code.startswith('300'):
                    return '创业板'
                elif code.startswith('60'):
                    return '主板'
                elif code.startswith('688'):
                    return '科创板'
                elif code.startswith('8'):
                    return '北交所'
                elif code.startswith('4'):
                    return '新三板'
                else:
                    return '未知'

            # 添加 ts_code 和 market 字段
            df['ts_code'] = df['symbol'].apply(generate_ts_code)
            df['market'] = df['symbol'].apply(get_market)
            df['area'] = ''
            df['industry'] = ''
            df['list_date'] = ''

            logger.info(f"AKShare: Successfully fetched {len(df)} stocks with real names")
            return df

        except Exception as e:
            logger.error(f"AKShare: Failed to fetch stock list: {e}")
            return None

    def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """获取每日基础财务数据（快速版）"""
        if not self.is_available():
            return None
        try:
            import akshare as ak  # noqa: F401
            logger.info(f"AKShare: Attempting to get basic financial data for {trade_date}")

            stock_df = self.get_stock_list()
            if stock_df is None or stock_df.empty:
                logger.warning("AKShare: No stock list available")
                return None

            max_stocks = 10
            stock_list = stock_df.head(max_stocks)

            basic_data = []
            processed_count = 0
            import time
            start_time = time.time()
            timeout_seconds = 30

            for _, stock in stock_list.iterrows():
                if time.time() - start_time > timeout_seconds:
                    logger.warning(f"AKShare: Timeout reached, processed {processed_count} stocks")
                    break
                try:
                    symbol = stock.get('symbol', '')
                    name = stock.get('name', '')
                    ts_code = stock.get('ts_code', '')
                    if not symbol:
                        continue
                    info_data = ak.stock_individual_info_em(symbol=symbol)
                    if info_data is not None and not info_data.empty:
                        info_dict = {}
                        for _, row in info_data.iterrows():
                            item = row.get('item', '')
                            value = row.get('value', '')
                            info_dict[item] = value
                        latest_price = self._safe_float(info_dict.get('最新', 0))
                        # 🔥 AKShare 的"总市值"单位是万元，需要转换为亿元（与 Tushare 一致）
                        total_mv_wan = self._safe_float(info_dict.get('总市值', 0))  # 万元
                        total_mv_yi = total_mv_wan / 10000 if total_mv_wan else None  # 转换为亿元
                        basic_data.append({
                            'ts_code': ts_code,
                            'trade_date': trade_date,
                            'name': name,
                            'close': latest_price,
                            'total_mv': total_mv_yi,  # 亿元（与 Tushare 一致）
                            'turnover_rate': None,
                            'pe': None,
                            'pb': None,
                        })
                        processed_count += 1
                        if processed_count % 5 == 0:
                            logger.debug(f"AKShare: Processed {processed_count} stocks in {time.time() - start_time:.1f}s")
                except Exception as e:
                    logger.debug(f"AKShare: Failed to get data for {symbol}: {e}")
                    continue

            if basic_data:
                df = pd.DataFrame(basic_data)
                logger.info(f"AKShare: Successfully fetched basic data for {trade_date}, {len(df)} records")
                return df
            else:
                logger.warning("AKShare: No basic data collected")
                return None
        except Exception as e:
            logger.error(f"AKShare: Failed to fetch basic data for {trade_date}: {e}")
            return None

    def _safe_float(self, value) -> Optional[float]:
        try:
            if value is None or value == '' or value == 'None':
                return None
            return float(value)
        except (ValueError, TypeError):
            return None


    def get_realtime_quotes(self, source: str = "eastmoney"):
        """
        获取全市场实时快照，返回以6位代码为键的字典

        Args:
            source: 数据源选择，"eastmoney"（东方财富）或 "sina"（新浪财经）

        Returns:
            Dict[str, Dict]: {code: {close, pct_chg, amount, ...}}
        """
        if not self.is_available():
            return None

        try:
            import akshare as ak  # type: ignore

            # 根据 source 参数选择接口
            if source == "sina":
                df = ak.stock_zh_a_spot()  # 新浪财经接口
                logger.info("使用 AKShare 新浪财经接口获取实时行情")
            else:  # 默认使用东方财富
                df = ak.stock_zh_a_spot_em()  # 东方财富接口
                logger.info("使用 AKShare 东方财富接口获取实时行情")

            if df is None or getattr(df, "empty", True):
                logger.warning(f"AKShare {source} 返回空数据")
                return None

            # 列名兼容（两个接口的列名可能不同）
            code_col = next((c for c in ["代码", "code", "symbol", "股票代码"] if c in df.columns), None)
            price_col = next((c for c in ["最新价", "现价", "最新价(元)", "price", "最新", "trade"] if c in df.columns), None)
            pct_col = next((c for c in ["涨跌幅", "涨跌幅(%)", "涨幅", "pct_chg", "changepercent"] if c in df.columns), None)
            amount_col = next((c for c in ["成交额", "成交额(元)", "amount", "成交额(万元)", "amount(万元)"] if c in df.columns), None)
            open_col = next((c for c in ["今开", "开盘", "open", "今开(元)"] if c in df.columns), None)
            high_col = next((c for c in ["最高", "high"] if c in df.columns), None)
            low_col = next((c for c in ["最低", "low"] if c in df.columns), None)
            pre_close_col = next((c for c in ["昨收", "昨收(元)", "pre_close", "昨收价", "settlement"] if c in df.columns), None)
            volume_col = next((c for c in ["成交量", "成交量(手)", "volume", "成交量(股)", "vol"] if c in df.columns), None)

            if not code_col or not price_col:
                logger.error(f"AKShare {source} 缺少必要列: code={code_col}, price={price_col}, columns={list(df.columns)}")
                return None

            result: Dict[str, Dict[str, Optional[float]]] = {}
            for _, row in df.iterrows():  # type: ignore
                code_raw = row.get(code_col)
                if not code_raw:
                    continue
                # 标准化股票代码：处理交易所前缀（如 sz000001, sh600036）
                code_str = str(code_raw).strip()

                # 如果代码长度超过6位，去掉前面的交易所前缀（如 sz, sh）
                if len(code_str) > 6:
                    # 去掉前面的非数字字符（通常是2个字符的交易所代码）
                    code_str = ''.join(filter(str.isdigit, code_str))

                # 如果是纯数字，移除前导0后补齐到6位
                if code_str.isdigit():
                    code_clean = code_str.lstrip('0') or '0'  # 移除前导0，如果全是0则保留一个0
                    code = code_clean.zfill(6)  # 补齐到6位
                else:
                    # 如果不是纯数字，尝试提取数字部分
                    code_digits = ''.join(filter(str.isdigit, code_str))
                    if code_digits:
                        code = code_digits.zfill(6)
                    else:
                        # 无法提取有效代码，跳过
                        continue

                close = self._safe_float(row.get(price_col))
                pct = self._safe_float(row.get(pct_col)) if pct_col else None
                amt = self._safe_float(row.get(amount_col)) if amount_col else None
                op = self._safe_float(row.get(open_col)) if open_col else None
                hi = self._safe_float(row.get(high_col)) if high_col else None
                lo = self._safe_float(row.get(low_col)) if low_col else None
                pre = self._safe_float(row.get(pre_close_col)) if pre_close_col else None
                vol = self._safe_float(row.get(volume_col)) if volume_col else None

                # 🔥 日志：记录AKShare返回的成交量
                if code in ["300750", "000001", "600000"]:  # 只记录几个示例股票
                    logger.info(f"📊 [AKShare实时] {code} - volume_col={volume_col}, vol={vol}, amount={amt}")

                result[code] = {
                    "close": close,
                    "pct_chg": pct,
                    "amount": amt,
                    "volume": vol,
                    "open": op,
                    "high": hi,
                    "low": lo,
                    "pre_close": pre
                }

            logger.info(f"✅ AKShare {source} 获取到 {len(result)} 只股票的实时行情")
            return result

        except Exception as e:
            logger.error(f"获取AKShare {source} 实时快照失败: {e}")
            return None

    def _to_em_symbol(self, ts_code: str) -> str:
        """Convert ts_code (000001.SZ) to EM symbol (SZ000001)"""
        if not ts_code: return ""
        code, market = ts_code.split('.')
        if market.upper() == 'SH':
            return f"SH{code}"
        elif market.upper() == 'SZ':
            return f"SZ{code}"
        elif market.upper() == 'BJ':
            return f"BJ{code}"
        return result

    def _fetch_stock_news_em_custom(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        替代 ak.stock_news_em 的自定义抓取方法
        抓取东方财富股吧资讯页面: https://guba.eastmoney.com/list,{symbol},1,f.html
        """
        try:
            from parsel import Selector
        except ImportError:
            logger.error("parsel not installed, cannot fetch news")
            return None

        url = f"https://guba.eastmoney.com/list,{symbol},1,f.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch EM news: HTTP {resp.status_code}")
                return None
                
            sel = Selector(text=resp.text)
            items = sel.css(".listitem")
            
            data = []
            current_year = datetime.now().year
            
            for item in items:
                try:
                    title = item.css(".title a::text").get()
                    link = item.css(".title a::attr(href)").get()
                    update_time = item.css(".update::text").get()
                    
                    if not title or not link:
                        continue
                        
                    # 处理链接
                    if not link.startswith("http"):
                        link = "https://guba.eastmoney.com" + link if link.startswith("/") else "https://guba.eastmoney.com/" + link
                    
                    # 处理时间 (MM-DD HH:mm)
                    if update_time:
                        full_time_str = f"{current_year}-{update_time}"
                        try:
                            dt = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M")
                            # 如果生成的时间比当前时间晚很多（比如当前1月，解析出12月），可能是去年
                            if dt > datetime.now() + timedelta(days=30):
                                full_time_str = f"{current_year - 1}-{update_time}"
                        except:
                            pass
                    else:
                        full_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                    data.append({
                        "title": title,
                        "url": link,
                        "datetime": full_time_str,
                        "source": "东方财富",
                        "code": symbol
                    })
                except Exception as e:
                    continue
                    
            if not data:
                return None
                
            return pd.DataFrame(data)
            
        except Exception as e:
            logger.error(f"Error fetching EM news custom: {e}")
            return None

    def _get_market_prefix(self, ts_code: str) -> str:
        """
        Get market prefix for AKShare (sh/sz/bj)
        """
        if not ts_code:
            return ""
        # Remove any existing prefix like sh600000
        if ts_code.startswith(('sh', 'sz', 'bj', 'SH', 'SZ', 'BJ')):
             ts_code = ts_code[2:]
             
        # If has suffix
        if ts_code.endswith('.SH'):
            return "sh"
        elif ts_code.endswith('.SZ'):
            return "sz"
        elif ts_code.endswith('.BJ'):
            return "bj"
            
        # Try to guess from code
        code = ts_code.split('.')[0]
        if code.startswith('6'):
            return "sh"
        elif code.startswith(('0', '3')):
            return "sz"
        elif code.startswith(('8', '4')):
            return "bj"
        return "sz" # Default

    def query(self, api_name: str, **kwargs) -> Optional[pd.DataFrame]:
        """
        通用查询接口，模拟 Tushare 的 pro.query 接口
        """
        if not self.is_available():
            return None
            
        try:
            import akshare as ak
            
            # 参数预处理
            ts_code = kwargs.get('ts_code', '')
            symbol = ts_code.split('.')[0] if ts_code else kwargs.get('symbol', '')
            start_date = kwargs.get('start_date', '')
            end_date = kwargs.get('end_date', '')
            
            logger.info(f"AKShare query: {api_name} for {symbol} ({start_date}-{end_date})")

            # --- 宏观经济数据 ---
            if api_name == 'cn_gdp' or api_name == 'gdp':
                df = ak.macro_china_gdp()
                # 统一字段名
                df = df.rename(columns={'季度': 'quarter', '国内生产总值-绝对值': 'gdp', '国内生产总值-同比增长': 'gdp_yoy'})
                return self._filter_by_date(df, 'quarter', start_date, end_date)
            
            elif api_name == 'cn_cpi' or api_name == 'cpi':
                df = ak.macro_china_cpi()
                df = df.rename(columns={'月份': 'month', '全国-同比增长': 'cpi'})
                return self._filter_by_date(df, 'month', start_date, end_date)

            elif api_name == 'shibor':
                df = ak.macro_china_shibor_all()
                # 字段: 日期, 隔夜, 1周, 2周, 1个月, 3个月, 6个月, 9个月, 1年
                df = df.rename(columns={'日期': 'date'})
                return self._filter_by_date(df, 'date', start_date, end_date)

            # --- 基础信息 ---
            elif api_name == 'company_basic' or api_name == 'stock_company':
                if not symbol: return None
                try:
                    # 获取个股异动/基本信息
                    # ak.stock_individual_info_em(symbol="000001")
                    df = ak.stock_individual_info_em(symbol=symbol)
                    
                    # 增加类型检查：如果返回标量，视为无效
                    if isinstance(df, (str, int, float, bool)):
                         logger.warning(f"stock_individual_info_em returned scalar: {df}")
                         return None
                    
                    if df is not None and not df.empty:
                        # stock_individual_info_em 返回两列: item, value
                        # 转置为一行
                        data = {}
                        for _, row in df.iterrows():
                            val = row['value']
                            if pd.isna(val): val = None
                            data[row['item']] = val
                            
                        df_ret = pd.DataFrame([data])
                        
                        # 映射字段
                        col_map = {
                            '股票代码': 'ts_code',
                            '股票简称': 'name', 
                            '总股本': 'total_share',
                            '流通股': 'float_share',
                            '总市值': 'total_mv',
                            '流通市值': 'circ_mv',
                            '行业': 'industry',
                            '上市时间': 'list_date'
                        }
                        df_ret = df_ret.rename(columns=col_map)
                        
                        # 补充
                        if 'ts_code' not in df_ret.columns: df_ret['ts_code'] = ts_code
                        
                        return df_ret
                except Exception as e:
                    logger.warning(f"Company basic info error: {e}")
                    return None

            # --- K线数据 (分钟) ---
            elif api_name == 'stk_mins':
                # 分钟线
                if not symbol: return None
                freq = kwargs.get('freq', '1min') # 1min, 5min, 15min, 30min, 60min
                
                # AKShare 分钟线接口需要带市场前缀 (如 sh600519)
                market_prefix = self._get_market_prefix(ts_code)
                symbol_with_market = f"{market_prefix}{symbol}"
                
                # AKShare 分钟线接口
                # period: '1', '5', '15', '30', '60'
                freq_map = {
                    '1min': '1', '1m': '1',
                    '5min': '5', '5m': '5',
                    '15min': '15', '15m': '15',
                    '30min': '30', '30m': '30',
                    '60min': '60', '60m': '60'
                }
                period = freq_map.get(freq, '1')
                
                # 处理 adjust
                adjust = kwargs.get('adj', '')
                if adjust not in ['qfq', 'hfq']: adjust = ""
                
                try:
                    df = ak.stock_zh_a_minute(symbol=symbol_with_market, period=period, adjust=adjust)
                    if df is not None and not df.empty:
                        # day, open, high, low, close, volume, amount, ...
                        df = df.rename(columns={
                            'day': 'trade_time', '时间': 'trade_time',
                            'open': 'open', '开盘': 'open',
                            'high': 'high', '最高': 'high',
                            'low': 'low', '最低': 'low',
                            'close': 'close', '收盘': 'close',
                            'volume': 'vol', '成交量': 'vol',
                            'amount': 'amount', '成交额': 'amount'
                        })
                        
                        # 过滤时间
                        if 'trade_time' in df.columns:
                            # 统一格式
                            df['trade_time'] = pd.to_datetime(df['trade_time'])
                            
                            if start_date:
                                # start_date 可能是 "2023-01-01 09:30:00"
                                s_dt = pd.to_datetime(start_date)
                                df = df[df['trade_time'] >= s_dt]
                            if end_date:
                                e_dt = pd.to_datetime(end_date)
                                df = df[df['trade_time'] <= e_dt]
                                
                            # 转回字符串
                            df['trade_time'] = df['trade_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
                            
                        return df
                except Exception as e:
                    logger.warning(f"AKShare minute data failed: {e}")
                    return None

            # --- 新闻数据 ---
            elif api_name == 'news' or api_name == 'major_news':
                # 个股新闻查询支持 (仅针对 'news' 接口，避免 major_news 递归)
                query_term = kwargs.get('query', '') or kwargs.get('q', '')
                if api_name == 'news' and query_term and (query_term.isdigit() or (len(query_term) == 9 and query_term[0].isdigit())):
                    # 如果是股票代码，尝试获取个股新闻
                    logger.info(f"AKShare fetching individual stock news for: {query_term}")
                    return self.get_news(code=query_term, include_announcements=False)

                # 7x24小时财经快讯
                try:
                    # 如果没有指定 symbol，则获取全球快讯
                    if not symbol:
                        # 使用财联社电报 (全球快讯)
                        df = ak.stock_info_global_cls()
                        if df is not None and not df.empty:
                            # 字段: 标题, 内容, 发布时间, 发布日期
                            df = df.rename(columns={
                                '标题': 'title',
                                '内容': 'content',
                                '发布时间': 'time',
                                '发布日期': 'date'
                            })
                            
                            # 构造 datetime
                            if 'datetime' not in df.columns:
                                # 确保 date 和 time 是字符串
                                if 'date' in df.columns:
                                    df['date'] = df['date'].astype(str)
                                if 'time' in df.columns:
                                    df['time'] = df['time'].astype(str)
                                    
                                if 'date' in df.columns and 'time' in df.columns:
                                    df['datetime'] = df['date'] + ' ' + df['time']
                                elif 'date' in df.columns:
                                    df['datetime'] = df['date']
    
                            # 兼容 Tushare 字段
                            df['source'] = 'cls'
                            df['type'] = 'news'
                            
                            logger.info(f"Global news fetched: {len(df)} rows. Filtering {start_date}-{end_date}")
                            
                            # 过滤关键词 (query)
                            query_term = kwargs.get('query', '') or kwargs.get('q', '')
                            if query_term:
                                logger.info(f"Filtering news by query: {query_term}")
                                # Filter if title or content contains query_term
                                mask = df['title'].astype(str).str.contains(query_term, case=False, na=False) | \
                                       df['content'].astype(str).str.contains(query_term, case=False, na=False)
                                df = df[mask]
                            
                            # 过滤
                            if start_date:
                                try:
                                    s_dt = pd.to_datetime(start_date)
                                    df['dt_obj'] = pd.to_datetime(df['datetime'])
                                    df = df[df['dt_obj'] >= s_dt]
                                except Exception as e:
                                    logger.warning(f"News start date filter error: {e}")
                            
                            if end_date:
                                try:
                                    e_dt = pd.to_datetime(end_date)
                                    if 'dt_obj' not in df.columns:
                                         df['dt_obj'] = pd.to_datetime(df['datetime'])
                                    df = df[df['dt_obj'] <= e_dt]
                                except Exception as e:
                                    logger.warning(f"News end date filter error: {e}")
                            
                            logger.info(f"Global news after filter: {len(df)} rows")
                            
                            if 'dt_obj' in df.columns:
                                del df['dt_obj']
                                
                            limit = kwargs.get('limit', 100)
                            return df.head(limit)
                        else:
                            logger.warning("AKShare CLS news returned empty.")
                            return None
                    
                    # 如果有 symbol，获取个股新闻
                    else:
                        # df = ak.stock_news_em(symbol=symbol) # Interface broken
                        df = self._fetch_stock_news_em_custom(symbol=symbol)
                        
                        if df is not None and not df.empty:
                            # 东方财富新闻字段: 关键词, 标题, 来源, 发布时间, 文章链接
                            # Custom method already returns standardized columns: title, datetime, url, source, code
                            # So we don't need rename if we match the keys
                            
                            # Original rename was:
                            # df = df.rename(columns={
                            #    '标题': 'title', 
                            #    '发布时间': 'datetime', 
                            #    '文章链接': 'url',
                            #    '来源': 'source'
                            # })
                            
                            # The custom method returns columns: title, url, datetime, source, code
                            # So no rename needed.
                            
                            # 过滤
                            if start_date:
                                df = df[df['datetime'] >= start_date]
                            if end_date:
                                df = df[df['datetime'] <= end_date]
                            
                            return df.head(kwargs.get('limit', 50))
                        
                except Exception as e:
                    logger.warning(f"AKShare news failed: {e}")
                    return None

            # --- 美股数据 ---
            elif api_name == 'us_daily':
                if not symbol: return None
                # ak.stock_us_daily 需要 symbol="AAPL"
                # 注意：Tushare 和 AKShare 美股代码格式可能一致
                df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        'date': 'trade_date', '日期': 'trade_date',
                        'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close',
                        'volume': 'vol', 'amount': 'amount'
                    })
                    return self._filter_by_date(df, 'trade_date', start_date, end_date)

            elif api_name in ['us_income', 'us_balancesheet', 'us_cashflow', 'us_fina_indicator']:
                if not symbol: return None
                # 使用新浪美股财务
                try:
                    sheet_map = {
                        'us_income': '利润表',
                        'us_balancesheet': '资产负债表',
                        'us_cashflow': '现金流量表',
                        'us_fina_indicator': '财务指标'
                    }
                    
                    try:
                        df = ak.stock_financial_report_sina(stock=symbol, symbol=sheet_map[api_name])
                    except Exception as inner_e:
                        logger.warning(f"AKShare stock_financial_report_sina failed for {symbol}: {inner_e}")
                        df = None
                    
                    if df is None or df.empty:
                        logger.warning(f"AKShare US financial data empty for {symbol} ({api_name})")
                        return None
                        
                    # 字段映射需要根据实际返回调整，这里做通用处理
                    # AKShare 新浪接口通常返回中文列名
                    # 简单返回，让上层处理或后续完善映射
                    return df
                except Exception as e:
                    logger.error(f"AKShare US financial error ({api_name}): {e}")
                    return None

            # --- 宏观经济数据 (补充) ---
            elif api_name == 'cn_ppi' or api_name == 'ppi':
                df = ak.macro_china_ppi()
                df = df.rename(columns={'月份': 'month', '工业生产者出厂价格指数-同比增长': 'ppi'})
                return self._filter_by_date(df, 'month', start_date, end_date)
            
            elif api_name == 'cn_m' or api_name == 'money_supply':
                df = ak.macro_china_money_supply()
                df = df.rename(columns={'月份': 'month', '货币和准货币(M2)-数量(亿元)': 'm2', '货币和准货币(M2)-同比增长': 'm2_yoy'})
                return self._filter_by_date(df, 'month', start_date, end_date)

            elif api_name == 'cn_pmi':
                df = ak.macro_china_pmi()
                df = df.rename(columns={'月份': 'month', '制造业PMI': 'pmi'})
                return self._filter_by_date(df, 'month', start_date, end_date)
            
            elif api_name == 'cn_sf':
                # 社会融资规模
                df = ak.macro_china_shrzgm()
                df = df.rename(columns={'月份': 'month', '社会融资规模增量': 'sf_month'})
                return self._filter_by_date(df, 'month', start_date, end_date)

            elif api_name == 'lpr_data':
                df = ak.macro_china_lpr()
                df = df.rename(columns={'日期': 'trade_date', '1年期LPR': '1y', '5年期以上LPR': '5y'})
                return self._filter_by_date(df, 'trade_date', start_date, end_date)

            # --- 指数数据 ---
            elif api_name == 'index_daily':
                if not symbol: return None
                # 指数日线
                # symbol 如 "sh000001"
                market_prefix = self._get_market_prefix(ts_code)
                idx_symbol = f"{market_prefix}{symbol}"
                df = ak.stock_zh_index_daily(symbol=idx_symbol)
                if df is not None:
                     df = df.rename(columns={'date': 'trade_date', 'volume': 'vol'})
                     return self._filter_by_date(df, 'trade_date', start_date, end_date)



            # --- 资金流向 ---
            elif api_name == 'moneyflow_dc' or api_name == 'stock_individual_fund_flow':
                # 个股资金流
                if not symbol: return None
                try:
                    # ak.stock_individual_fund_flow 需要 market 参数
                    market = self._get_market_prefix(ts_code)
                    logger.info(f"Fetching moneyflow for {symbol} market={market}")
                    
                    # 增加重试机制，应对网络抖动或IP限制
                    df = None
                    for attempt in range(3):
                        try:
                            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
                            if df is not None and not df.empty:
                                break
                            import time
                            time.sleep(1) # 简单的避让
                        except Exception as e_retry:
                            logger.warning(f"Moneyflow attempt {attempt+1} failed: {e_retry}")
                            import time
                            time.sleep(1)

                    if df is None or df.empty:
                        logger.warning(f"Moneyflow returned empty for {symbol} after retries")
                        return None
                        
                    # 适配 Tushare 字段
                    df = df.rename(columns={
                        '日期': 'trade_date', 
                        '主力净流入-净额': 'net_mf_amount',
                        '超大单净流入-净额': 'net_large_amount',
                        '大单净流入-净额': 'net_med_amount',
                        '中单净流入-净额': 'net_small_amount',
                        '小单净流入-净额': 'net_little_amount'
                    })
                    
                    # 确保 trade_date 是字符串格式
                    if 'trade_date' in df.columns:
                        df['trade_date'] = df['trade_date'].apply(lambda x: str(x).split(' ')[0] if x else '')
                        
                    return self._filter_by_date(df, 'trade_date', start_date, end_date)
                except Exception as e:
                    logger.warning(f"AKShare moneyflow error: {e}")
                    return None

            # --- 财务数据 ---
            elif api_name in ['income', 'balancesheet', 'cashflow', 'hk_income', 'hk_balancesheet', 'hk_cashflow']:
                if not symbol: return None
                
                is_hk = 'hk_' in api_name or (ts_code and ts_code.endswith('.HK'))
                
                try:
                    if is_hk:
                        # 港股财务
                        # AKShare 新浪接口通常使用 5 位数字代码，如 "00700"
                        # ts_code 可能是 "00700.HK"
                        hk_symbol = symbol
                        if symbol.isdigit():
                             hk_symbol = str(int(symbol)).zfill(5)
                        
                        if api_name == 'hk_income':
                             try:
                                 df = ak.stock_financial_report_sina(stock=hk_symbol, symbol="利润表")
                             except Exception as e:
                                 logger.warning(f"AKShare Sina HK income failed: {e}")
                                 df = None
                                 
                             # 如果为空，尝试使用年度指标作为 fallback
                             if df is None or df.empty:
                                try:
                                    logger.info(f"Using fallback analysis indicator for {hk_symbol}")
                                    df = ak.stock_financial_hk_analysis_indicator_em(symbol=hk_symbol, indicator="年度")
                                    if df is not None:
                                         # 映射字段
                                         df = df.rename(columns={
                                             'REPORT_DATE': 'end_date',
                                             'OPERATE_INCOME': 'total_revenue',
                                             'HOLDER_PROFIT': 'n_income',
                                             'BASIC_EPS': 'basic_eps',
                                             'ROE_AVG': 'roe'
                                         })
                                         # 添加缺失字段
                                         if 'ann_date' not in df.columns and 'end_date' in df.columns:
                                             df['ann_date'] = df['end_date']
                                         
                                         logger.info(f"Fallback HK analysis data: {len(df)} rows. Columns: {df.columns.tolist()}")
                                except Exception as e:
                                    logger.warning(f"Fallback HK analysis error: {e}")
                                    pass
                        elif api_name == 'hk_balancesheet':
                            try:
                                df = ak.stock_financial_report_sina(stock=hk_symbol, symbol="资产负债表")
                            except Exception:
                                df = None
                        elif api_name == 'hk_cashflow':
                            try:
                                df = ak.stock_financial_report_sina(stock=hk_symbol, symbol="现金流量表")
                            except Exception:
                                df = None
                        else:
                            df = None
                        
                        # 新浪返回的列名通常是中文，需要映射
                        if df is not None and not df.empty:
                            # 简单列名映射尝试
                            # 利润表: 截止日期, 营业收入, 净利润...
                            # 资产负债表: 截止日期, 资产总计, 负债总计...
                            col_map = {
                                '截止日期': 'end_date',
                                '营业收入': 'revenue',
                                '净利润': 'n_income',
                                '资产总计': 'total_assets',
                                '负债总计': 'total_liab',
                                '经营活动现金流量净额': 'n_cashflow_act'
                            }
                            df = df.rename(columns=col_map)
                            # 确保有 ann_date (用 end_date 填充)
                            if 'end_date' in df.columns and 'ann_date' not in df.columns:
                                df['ann_date'] = df['end_date']
                    else:
                        # A股财务 (东方财富接口需要带市场标识的 symbol，如 SZ000001)
                        em_symbol = self._to_em_symbol(ts_code)
                        logger.info(f"Fetching financial data ({api_name}) for {em_symbol}")
                        
                        if api_name == 'income':
                            df = ak.stock_profit_sheet_by_quarterly_em(symbol=em_symbol)
                            # 利润表映射
                            if df is not None:
                                df = df.rename(columns={
                                    'NOTICE_DATE': 'ann_date',
                                    'REPORT_DATE': 'end_date',
                                    'BASIC_EPS': 'basic_eps',
                                    'TOTAL_PROFIT': 'total_profit',
                                    'NETPROFIT': 'n_income',
                                    'OPERATE_INCOME': 'total_revenue', # 银行等金融类
                                    'TOTAL_OPERATE_INCOME': 'total_revenue', # 一般企业
                                    'OPERATE_PROFIT': 'op_income'
                                })
                        elif api_name == 'balancesheet':
                            # 资产负债表：注意使用 by_report 接口
                            df = ak.stock_balance_sheet_by_report_em(symbol=em_symbol)
                            if df is not None:
                                df = df.rename(columns={
                                    'NOTICE_DATE': 'ann_date',
                                    'REPORT_DATE': 'end_date',
                                    'TOTAL_ASSETS': 'total_assets',
                                    'TOTAL_LIABILITIES': 'total_liab',
                                    'TOTAL_EQUITY': 'total_hldr_eqy_exc_min_int', # 近似
                                    'SHARE_CAPITAL': 'total_share',
                                    'MONETARYFUNDS': 'money_cap', # 一般企业
                                })
                        elif api_name == 'cashflow':
                            df = ak.stock_cash_flow_sheet_by_quarterly_em(symbol=em_symbol)
                            if df is not None:
                                df = df.rename(columns={
                                    'NOTICE_DATE': 'ann_date',
                                    'REPORT_DATE': 'end_date',
                                    'NETPROFIT': 'net_profit',
                                    'TOTAL_OPERATE_INFLOW': 'c_inf_fr_operate_a',
                                    'TOTAL_OPERATE_OUTFLOW': 'c_out_fr_operate_a',
                                    'NETCASH_OPERATE': 'n_cashflow_act',
                                    'NETCASH_INVEST': 'n_cashflow_inv_act',
                                    'NETCASH_FINANCE': 'n_cashflow_fina_act',
                                    'CCE_ADD': 'n_incr_cash_cash_equ'
                                })
                        else:
                            df = None
                    
                    if df is not None and not df.empty:
                        # 通用清理：日期格式 "YYYY-MM-DD 00:00:00" -> "YYYYMMDD" (Tushare format)
                        for col in ['ann_date', 'end_date']:
                            if col in df.columns:
                                df[col] = df[col].astype(str).apply(lambda x: x.split(' ')[0].replace('-', '') if x and x != 'nan' else '')
                        
                        # 添加 ts_code
                        if 'ts_code' not in df.columns and ts_code:
                            df['ts_code'] = ts_code
                            
                        # 尝试找到日期列进行过滤
                        date_col = 'end_date' if 'end_date' in df.columns else ('ann_date' if 'ann_date' in df.columns else None)
                        if date_col:
                            return self._filter_by_date(df, date_col, start_date, end_date)
                        return df
                    else:
                        logger.warning(f"Financial data empty for {symbol} ({api_name})")
                        return None
                except Exception as e:
                    logger.error(f"AKShare financial data error ({api_name}): {e}")
                    return None

            # --- 基金数据 ---
            elif api_name == 'fund_basic':
                # 基金列表
                try:
                    df = None
                    # 尝试多种接口
                    for func_name in ['fund_name_em', 'fund_em_fund_name', 'fund_open_fund_daily_em']:
                        if hasattr(ak, func_name):
                            try:
                                df = getattr(ak, func_name)()
                                if df is not None and not df.empty:
                                    break
                            except:
                                pass
                             
                    if df is not None:
                         # 统一重命名
                         rename_map = {'基金代码': 'ts_code', '基金简称': 'name', '基金类型': 'fund_type'}
                         df = df.rename(columns=rename_map)
                         return df.head(100) # 限制返回数量
                except Exception as e:
                    logger.error(f"Fund basic error: {e}")
                    return None
            
            elif api_name == 'fund_nav':
                # 基金净值
                if not symbol: return None
                try:
                    logger.info(f"Fetching fund nav for {symbol}")
                    # API 变更为 symbol 参数
                    df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势")
                    if df is None or df.empty:
                        logger.warning(f"Fund nav empty for {symbol}")
                        return None
                    df = df.rename(columns={'净值日期': 'nav_date', '单位净值': 'unit_nav', '日增长率': 'adj_nav'})
                    return self._filter_by_date(df, 'nav_date', start_date, end_date)
                except Exception as e:
                    logger.error(f"Fund nav error: {e}")
                    return None

            elif api_name == 'fund_portfolio':
                # 基金持仓
                if not symbol: return None
                try:
                    # ak.fund_portfolio_hold_em(symbol="000001", date="2021")
                    # 这里简化，获取最新持仓
                    df = ak.fund_portfolio_hold_em(symbol=symbol)
                    if df is not None:
                        df = df.rename(columns={'股票代码': 'symbol', '股票名称': 'name', '占净值比例': 'stk_mkv_ratio'})
                        return df
                except Exception as e:
                     logger.warning(f"Fund portfolio error: {e}")
                     return None
            




            elif api_name == 'top_inst':
                # 龙虎榜机构成交
                try:
                    date_str = kwargs.get('trade_date', '').replace('-', '')
                    if not date_str: 
                        if start_date:
                            date_str = start_date.replace('-', '')
                        else:
                            date_str = self.find_latest_trade_date()
                    
                    # stock_lhb_detail_em 需要 start_date 和 end_date
                    # 如果只查一天，则 start=end
                    s_date = date_str
                    e_date = date_str
                    if start_date and end_date:
                        s_date = start_date.replace('-', '')
                        e_date = end_date.replace('-', '')
                        
                    df = ak.stock_lhb_detail_em(start_date=s_date, end_date=e_date)
                    if df is not None:
                         df = df.rename(columns={'代码': 'ts_code', '名称': 'name', '上榜原因': 'reason', '交易日期': 'trade_date'})
                         return df
                except Exception as e:
                     logger.warning(f"Dragon tiger error: {e}")
                     return None

            # --- 融资融券 ---
            elif api_name == 'margin':
                # 融资融券交易汇总 (市场总计)
                # Tushare: trade_date, exchange_id, balance, ...
                # AKShare: stock_margin_sse, stock_margin_szse
                try:
                    exchange = kwargs.get('exchange_id', '')
                    start_dt = start_date.replace('-', '') if start_date else ''
                    end_dt = end_date.replace('-', '') if end_date else ''
                    
                    frames = []
                    
                    # 上交所
                    if not exchange or exchange == 'SSE':
                        try:
                            # stock_margin_sse 支持时间范围
                            df_sh = ak.stock_margin_sse(start_date=start_dt, end_date=end_dt)
                            if df_sh is not None and not df_sh.empty:
                                df_sh['exchange_id'] = 'SSE'
                                df_sh = df_sh.rename(columns={
                                    '信用交易日期': 'trade_date',
                                    '融资余额': 'rzye',
                                    '融资买入额': 'rzmre',
                                    '融券余额': 'rqye',
                                    '融券卖出量': 'rqmcl',
                                    '融券余量': 'rqyl'
                                })
                                frames.append(df_sh)
                        except Exception as e:
                            logger.warning(f"AKShare margin SSE error: {e}")

                    # 深交所
                    if not exchange or exchange == 'SZSE':
                        try:
                            # stock_margin_szse 只支持单日? 或者是时间范围?
                            # 文档显示 stock_margin_szse(date='20220210')
                            # 如果是范围，可能需要循环。这里简化，只获取 start_date 或 end_date
                            target_date = end_dt if end_dt else start_dt
                            if target_date:
                                df_sz = ak.stock_margin_szse(date=target_date)
                                if df_sz is not None and not df_sz.empty:
                                    df_sz['exchange_id'] = 'SZSE'
                                    df_sz = df_sz.rename(columns={
                                        '融资融券交易日期': 'trade_date',
                                        '融资余额': 'rzye',
                                        '融资买入额': 'rzmre',
                                        '融券余额': 'rqye',
                                        '融券卖出量': 'rqmcl',
                                        '融券余量': 'rqyl'
                                    })
                                    frames.append(df_sz)
                        except Exception as e:
                            logger.warning(f"AKShare margin SZSE error: {e}")
                            
                    if frames:
                        df_res = pd.concat(frames)
                        return df_res
                    return None
                except Exception as e:
                    logger.error(f"AKShare margin error: {e}")
                    return None

            elif api_name == 'margin_detail':
                # 融资融券交易明细 (个股)
                # Tushare: trade_date, ts_code, rzye, ...
                # AKShare: stock_margin_detail_sse(date=...), stock_margin_detail_szse(date=...)
                try:
                    # 只能按日期查询，如果提供了 ts_code 和 range，效率很低
                    # 这里简化：只查询 end_date (或 start_date)
                    query_date = end_date.replace('-', '') if end_date else (start_date.replace('-', '') if start_date else '')
                    if not query_date:
                        query_date = self.find_latest_trade_date()
                    
                    frames = []
                    
                    # 上交所
                    try:
                        df_sh = ak.stock_margin_detail_sse(date=query_date)
                        if df_sh is not None and not df_sh.empty:
                            df_sh = df_sh.rename(columns={
                                '信用交易日期': 'trade_date',
                                '标的证券代码': 'symbol',
                                '标的证券简称': 'name',
                                '融资余额': 'rzye',
                                '融资买入额': 'rzmre',
                                '融资偿还额': 'rzche',
                                '融券余额': 'rqye',
                                '融券卖出量': 'rqmcl',
                                '融券偿还量': 'rqchl',
                                '融券余量': 'rqyl'
                            })
                            # 添加 ts_code
                            df_sh['ts_code'] = df_sh['symbol'].apply(lambda x: f"{str(x).zfill(6)}.SH")
                            frames.append(df_sh)
                    except Exception:
                        pass
                        
                    # 深交所
                    try:
                        df_sz = ak.stock_margin_detail_szse(date=query_date)
                        if df_sz is not None and not df_sz.empty:
                             df_sz = df_sz.rename(columns={
                                '证券代码': 'symbol',
                                '证券简称': 'name',
                                '融资余额': 'rzye',
                                '融资买入额': 'rzmre',
                                '融资偿还额': 'rzche',
                                '融券余额': 'rqye',
                                '融券卖出量': 'rqmcl',
                                '融券偿还量': 'rqchl',
                                '融券余量': 'rqyl',
                                '交易日期': 'trade_date' # 有些接口可能没有日期列
                            })
                             # 深交所接口可能不返回日期列，需手动添加
                             if 'trade_date' not in df_sz.columns:
                                 df_sz['trade_date'] = query_date
                                 
                             df_sz['ts_code'] = df_sz['symbol'].apply(lambda x: f"{str(x).zfill(6)}.SZ")
                             frames.append(df_sz)
                    except Exception:
                        pass
                        
                    if frames:
                        df_all = pd.concat(frames)
                        # 如果指定了 ts_code，过滤
                        if ts_code:
                            df_all = df_all[df_all['ts_code'] == ts_code]
                        return df_all
                    return None
                except Exception as e:
                    logger.error(f"AKShare margin detail error: {e}")
                    return None

            # --- 指数成分股权重 ---
            elif api_name == 'index_weight':
                # 中证指数成分股权重
                # index_code: 399300.SZ -> 000300
                index_code = kwargs.get('index_code', '')
                if not index_code: return None
                
                try:
                    # 映射代码
                    symbol = index_code.split('.')[0]
                    # Tushare 399300.SZ 是沪深300，AKShare 中证指数用 000300
                    if index_code == '399300.SZ': symbol = '000300'
                    if index_code == '000300.SH': symbol = '000300'
                    
                    logger.info(f"Fetching index weight for {symbol}")
                    df = ak.index_stock_cons_weight_csindex(symbol=symbol)
                    
                    if df is not None and not df.empty:
                        # 字段: 成分券代码, 成分券名称, 权重(%)
                        df = df.rename(columns={
                            '成分券代码': 'member_code',
                            '成分券名称': 'member_name',
                            '权重(%)': 'weight'
                        })
                        # 补充 ts_code (index code)
                        df['index_code'] = index_code
                        # 补充 date (AKShare 接口不返回日期，假设是最新)
                        df['trade_date'] = end_date if end_date else datetime.now().strftime('%Y%m%d')
                        
                        return df
                except Exception as e:
                    logger.error(f"AKShare index weight error: {e}")
                    return None

            elif api_name == 'block_trade':
                # 大宗交易
                try:
                    # stock_dzjy_mrtj 每日统计，可能不需要参数获取最近，或需要 start_date/end_date
                    s_date = start_date.replace('-', '') if start_date else self.find_latest_trade_date()
                    e_date = end_date.replace('-', '') if end_date else s_date
                    
                    try:
                        df = ak.stock_dzjy_mrtj(start_date=s_date, end_date=e_date)
                    except TypeError:
                         # 如果不支持日期参数，尝试无参调用（通常返回最近交易日）
                         df = ak.stock_dzjy_mrtj()
                         
                    if df is not None:
                         df = df.rename(columns={'证券代码': 'ts_code', '证券简称': 'name', '成交价': 'price', '成交量': 'vol', '成交额': 'amount', '交易日期': 'trade_date'})
                         return df
                except Exception as e:
                     logger.warning(f"Block trade error: {e}")
                     return None

            # --- 可转债 ---
            elif api_name == 'cb_basic' or api_name == 'cb_issue':
                try:
                    # 尝试多种接口
                    df = None
                    for func_name in ['bond_zh_cov_spot_em', 'bond_zh_hs_cov_spot', 'bond_zh_cov_spot']:
                        if hasattr(ak, func_name):
                            try:
                                df = getattr(ak, func_name)()
                                if df is not None and not df.empty:
                                    break
                            except:
                                pass
                        
                    if df is not None:
                        df = df.rename(columns={'代码': 'ts_code', '名称': 'name', '最新价': 'price'})
                        return df
                except Exception as e:
                     logger.warning(f"Convertible bond error: {e}")
                     return None
            
            # --- 融资融券明细 ---
            elif api_name == 'margin_detail':
                # 确定日期：优先使用 end_date，如果没有则使用 start_date，如果没有则使用昨天
                query_date = end_date or start_date or self.find_latest_trade_date()
                query_date = query_date.replace('-', '')
                
                df_list = []
                try:
                    df_sz = ak.stock_margin_detail_szse(date=query_date)
                    if df_sz is not None and not df_sz.empty:
                        # 预先重命名
                        df_sz = df_sz.rename(columns={
                            '证券代码': 'ts_code', '证券简称': 'name', 
                            '融资买入额': 'rzmre', '融资余额': 'rzye', 
                            '融券卖出量': 'rqmcl', '融券余量': 'rqyl', 
                            '融券余额': 'rqye', '融资融券余额': 'rzrqye'
                        })
                        df_list.append(df_sz)
                except: pass
                
                try:
                    df_sh = ak.stock_margin_detail_sse(date=query_date)
                    if df_sh is not None and not df_sh.empty:
                        # 预先重命名
                        df_sh = df_sh.rename(columns={
                            '标的证券代码': 'ts_code', '标的证券简称': 'name',
                            '融资买入额': 'rzmre', '融资偿还额': 'rzche', '融资余额': 'rzye',
                            '融券卖出量': 'rqmcl', '融券偿还量': 'rqchl', '融券余量': 'rqyl', '融券余额': 'rqye',
                            '信用交易日期': 'trade_date'
                        })
                        df_list.append(df_sh)
                except: pass
                
                if df_list:
                    df = pd.concat(df_list, ignore_index=True)
                    # 补全日期
                    if 'trade_date' not in df.columns:
                        df['trade_date'] = query_date
                    # 过滤
                    if ts_code:
                        code_no_suffix = ts_code.split('.')[0]
                        df = df[df['ts_code'] == code_no_suffix]
                    return df
                return None

            # --- 基金经理 ---
            elif api_name == 'fund_manager':
                try:
                    df = ak.fund_manager_em()
                    name = kwargs.get('name', '')
                    logger.info(f"Fund Manager Search: '{name}', Total records: {len(df) if df is not None else 0}")
                    
                    if name:
                        # 尝试精确匹配
                        df_filtered = df[df['姓名'] == name]
                        logger.info(f"Exact match count: {len(df_filtered)}")
                        
                        if df_filtered.empty:
                            # 尝试模糊匹配
                            df_filtered = df[df['姓名'].astype(str).str.contains(name, na=False)]
                            logger.info(f"Fuzzy match count: {len(df_filtered)}")
                        
                        return df_filtered
                    return df
                except Exception as e:
                    logger.warning(f"AKShare fund_manager error: {e}")
                    return None

            # --- 指数成分股权重 ---
            elif api_name == 'index_weight':
                index_code = kwargs.get('index_code', '')
                symbol = index_code.split('.')[0]
                logger.info(f"Index Weight Search: {index_code} -> {symbol}")
                
                # 尝试中证指数官网接口 (通常更准确，但需要 openpyxl)
                try:
                    logger.info("Trying csindex interface...")
                    df = ak.index_stock_cons_weight_csindex(symbol=symbol)
                    logger.info(f"csindex success, records: {len(df)}")
                    df = df.rename(columns={
                        '日期': 'trade_date',
                        '指数代码': 'index_code',
                        '成分券代码': 'con_code',
                        '权重': 'weight'
                    })
                    return df
                except Exception as e:
                    logger.warning(f"AKShare index_weight (csindex) failed: {e}, trying fallback...")
                
                # 回退：新浪接口
                try:
                    logger.info("Trying sina interface...")
                    df = ak.index_stock_cons_sina(symbol=symbol)
                    logger.info(f"sina success, records: {len(df)}")
                    # 新浪接口返回: symbol, name, pub_date
                    # 注意：新浪接口可能不包含权重，只包含成分股列表
                    # 列名: 代码, 名称
                    df = df.rename(columns={'代码': 'con_code', '名称': 'con_name'})
                    df['index_code'] = symbol
                    df['weight'] = 0  # 新浪接口无权重数据
                    df['trade_date'] = datetime.now().strftime("%Y%m%d")
                    return df
                except Exception as e:
                    logger.warning(f"AKShare index_weight (sina) failed: {e}")
                    return None

            # --- 其他 ---
            elif api_name == 'daily' or api_name == 'hk_daily':
                # 日线行情 (fallback for get_stock_data)
                if not symbol: return None
                
                if api_name == 'hk_daily':
                     df = ak.stock_hk_daily(symbol=symbol, adjust="qfq")
                else:
                     s_date = start_date.replace('-','') if start_date else "19900101"
                     e_date = end_date.replace('-','') if end_date else datetime.now().strftime("%Y%m%d")
                     df = ak.stock_zh_a_hist(symbol=symbol, start_date=s_date, end_date=e_date, adjust="qfq")
                
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        '日期': 'trade_date', 'date': 'trade_date',
                        '开盘': 'open', '收盘': 'close', 
                        '最高': 'high', '最低': 'low', 
                        '成交量': 'vol', 'volume': 'vol',
                        '成交额': 'amount',
                        '涨跌幅': 'pct_chg', '涨跌额': 'change', 
                        '换手率': 'turnover'
                    })
                    # 添加 price 字段兼容
                    if 'close' in df.columns:
                        df['price'] = df['close']
                    return df

            logger.warning(f"AKShare query: API {api_name} not implemented or failed mapping.")
            return None
            
        except Exception as e:
            logger.error(f"AKShare query failed for {api_name}: {e}")
            return None

    def _filter_by_date(self, df, date_col, start_date, end_date):
        if df is None or df.empty: return df
        try:
            # 统一转为 datetime
            df[date_col] = pd.to_datetime(df[date_col])
            
            if start_date:
                s_date = pd.to_datetime(start_date)
                df = df[df[date_col] >= s_date]
            if end_date:
                e_date = pd.to_datetime(end_date)
                df = df[df[date_col] <= e_date]
                
            # 转回字符串以便显示
            df[date_col] = df[date_col].dt.strftime('%Y-%m-%d')
            return df
        except:
            return df

    def _get_market_prefix(self, ts_code):
        if not ts_code: return "sh"
        if ts_code.endswith('.SH'): return "sh"
        if ts_code.endswith('.SZ'): return "sz"
        if ts_code.endswith('.BJ'): return "bj"
        return "sh" # default

    def get_kline(self, code: str, period: str = "day", limit: int = 120, adj: Optional[str] = None):
        """AKShare K-line as fallback. Try daily/week/month via stock_zh_a_hist; minutes via stock_zh_a_minute."""
        if not self.is_available():
            return None
        try:
            import akshare as ak
            code6 = str(code).zfill(6)
            items = []
            if period in ("day", "week", "month"):
                period_map = {"day": "daily", "week": "weekly", "month": "monthly"}
                adjust_map = {None: "", "qfq": "qfq", "hfq": "hfq"}
                df = ak.stock_zh_a_hist(symbol=code6, period=period_map[period], adjust=adjust_map.get(adj, ""))
                if df is None or getattr(df, 'empty', True):
                    return None
                df = df.tail(limit)
                for _, row in df.iterrows():
                    items.append({
                        "time": str(row.get('日期') or row.get('date') or ''),
                        "open": self._safe_float(row.get('开盘') or row.get('open')),
                        "high": self._safe_float(row.get('最高') or row.get('high')),
                        "low": self._safe_float(row.get('最低') or row.get('low')),
                        "close": self._safe_float(row.get('收盘') or row.get('close')),
                        "volume": self._safe_float(row.get('成交量') or row.get('volume')),
                        "amount": self._safe_float(row.get('成交额') or row.get('amount')),
                    })
                return items
            else:
                # minutes
                per_map = {"5m": "5", "15m": "15", "30m": "30", "60m": "60"}
                if period not in per_map:
                    return None
                df = ak.stock_zh_a_minute(symbol=code6, period=per_map[period], adjust=adj if adj in ("qfq", "hfq") else "")
                if df is None or getattr(df, 'empty', True):
                    return None
                df = df.tail(limit)
                for _, row in df.iterrows():
                    items.append({
                        "time": str(row.get('时间') or row.get('day') or ''),
                        "open": self._safe_float(row.get('开盘') or row.get('open')),
                        "high": self._safe_float(row.get('最高') or row.get('high')),
                        "low": self._safe_float(row.get('最低') or row.get('low')),
                        "close": self._safe_float(row.get('收盘') or row.get('close')),
                        "volume": self._safe_float(row.get('成交量') or row.get('volume')),
                        "amount": self._safe_float(row.get('成交额') or row.get('amount')),
                    })
                return items
        except Exception as e:
            logger.error(f"AKShare get_kline failed: {e}")
            return None

    def get_news(self, code: str, days: int = 2, limit: int = 50, include_announcements: bool = True):
        """AKShare-based news/announcements fallback"""
        if not self.is_available():
            return None
        try:
            import akshare as ak
            code6 = str(code).zfill(6)
            items = []
            
            # Note: stock_news_em interface is currently unstable/broken (dynamic callback issue + empty data)
            # We skip the direct individual stock news call to avoid errors and rely on global news search fallback.
            
            # Fallback: Search in global news
            try:
                # 使用 major_news 避免递归调用 get_news
                # 尝试放宽搜索条件
                df_global = self.query("major_news", query=code6, limit=limit)
                if df_global is not None and not df_global.empty:
                     # query("news") 已经做了字段标准化
                     # df_global: title, content, datetime, source, type
                     for _, row in df_global.iterrows():
                         items.append({
                             "title": str(row.get('title', '')),
                             "content": str(row.get('content', '')), # global news has content
                             "source": str(row.get('source', 'akshare')),
                             "time": str(row.get('datetime', '')),
                             "type": "news"
                         })
            except Exception as e:
                logger.warning(f"Global news search failed for {code6}: {e}")
            
            # announcements
            try:
                if include_announcements:
                    dfa = ak.stock_announcement_em(symbol=code6)
                    if dfa is not None and not dfa.empty:
                        for _, row in dfa.head(max(0, limit - len(items))).iterrows():
                            items.append({
                                "title": str(row.get('公告标题') or row.get('title') or ''),
                                "source": "akshare",
                                "time": str(row.get('公告时间') or row.get('time') or ''),
                                "url": str(row.get('公告链接') or row.get('url') or ''),
                                "type": "announcement",
                            })
            except Exception:
                pass
            return items if items else None
        except Exception as e:
            logger.error(f"AKShare get_news failed: {e}")
            return None

    def find_latest_trade_date(self) -> Optional[str]:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        logger.info(f"AKShare: Using yesterday as trade date: {yesterday}")
        return yesterday

