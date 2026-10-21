"""QMT 原始列 → 标准 Schema 字段映射（DD-05：映射唯一权威）。

原始列来自 ``QmtDatadirReader``（xtdata 同形列名，见 datadir_reader 模块
docstring）；标准 Schema 见 ``app/data/schema/domains/``。

语义基准（技术方案 V-1/V-2，对齐 TushareCNAdapter 的库内格式）：
- symbol：ts_code 前段 6 位裸码（'000001.SZ' → '000001'）
- exchange：SH→SSE / SZ→SZSE（datadir 仅沪深，PRD 4.2 剔除北交所）
- trade_date / cal_date：'YYYY-MM-DD'
- volume：QMT K 线单位为**手**，×100 → 股（Schema 注释单位=股；手→股基准
  实证 814373 手 ×100×11.89 ≈ amount 969948436 元，见 reader 模块注释）
- amount：QMT 直存**元**（u64），不再换算（区别于 tushare 的千元 → 元 ×1000）
- 复权：只存原始价；``adj_f_cum``（累计因子）→ AdjFactorsSchema.adj_factor，
  ``fore/back_adj_factor`` QMT 无对应槽位置 None（技术方案 V-3）
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

_TZ_BEIJING = timezone(timedelta(hours=8))

LOT_TO_SHARE = 100.0  # 手 → 股

# O-2（tick volume 单位）—— **2026-10-20 已用真实 datadir 定版**：
# 同一股票同一日，tick 末条记录的「累计 volume / amount」与日线 bar 的
# volume / amount **逐值相等**（600000.SH 20261020: 605,133 / 589,321,380；
# 000001.SZ: 1,245,097 / 1,429,559,866）。日线已确认单位为「手」（见下方
# LOT_TO_SHARE 的 amount 交叉验证），故 tick 的 volume 同为「手」，需 ×100。
# 注意：QMT tick 的 volume/amount 是**当日累计值**，不是单笔增量。
TICK_VOLUME_TO_SHARE = 100.0

# ── 分红送配（FR-07 / V-3）──
# **2026-10-20 已用真实 datadir 定版**：QMT DividData 的 `interest` 字段单位是
# **每股**（不是每 10 股）。实证：600000.SH 近四年 interest = 0.320 / 0.321 /
# 0.410 / 0.420，对应浦发银行「每 10 股派 3.2 / 3.21 / 4.1 / 4.2 元」的公开方案；
# 000001.SZ = 0.236 / 0.360 / 0.249 对应平安银行「每 10 股派 2.36 / 3.60 /
# 2.49 元」。故换算系数为 1.0（早前按「每 10 股」的假设会把分红缩小 10 倍）。
DIVIDEND_PER_UNIT = 1.0

# QMT 除权日 [88:92] 无效时会回退用 LevelDB key 的时间戳派生，实测 437 条错位
# （reader._load_dividends 注释）。这类记录的 ex_date 不可信 → 默认不落库，
# 符合 PRD「绝不写可疑值」；确认可信的部署可打开此开关。
CORPORATE_ACTIONS_TRUST_TS_KEY = False

# reader 输出的 K 线原始列（xtdata 同形）→ 用途说明（映射在 adapter 内逐域执行）
KLINE_RAW_COLUMNS = (
    "time", "open", "high", "low", "close", "volume", "amount",
    "preClose", "suspendFlag", "adj_f_evt", "adj_f_cum",
)


def ts_code_to_symbol(ts_code: str) -> str:
    """'000001.SZ' → '000001'（V-1：库内 symbol 为 6 位裸码）。"""
    if isinstance(ts_code, str) and "." in ts_code:
        return ts_code.split(".")[0]
    return str(ts_code).zfill(6)


def ts_code_to_exchange(ts_code: str) -> str:
    """'000001.SZ' → 'SZSE'；datadir 不含 BJ（split_code 已拒读）。"""
    if isinstance(ts_code, str) and "." in ts_code:
        suffix = ts_code.split(".")[1].upper()
        return {"SH": "SSE", "SZ": "SZSE"}.get(suffix, suffix)
    return ""


def ms_to_trade_date(ms: int) -> str:
    """毫秒 epoch → 'YYYY-MM-DD'（北京时区；日线 ts=交易日 00:00）。"""
    return datetime.fromtimestamp(int(ms) / 1000, _TZ_BEIJING).strftime("%Y-%m-%d")


def ms_to_datetime_str(ms: int) -> str:
    """毫秒 epoch → 'YYYY-MM-DD HH:MM:SS'（北京时区；M2 分时/tick 用）。"""
    return datetime.fromtimestamp(int(ms) / 1000, _TZ_BEIJING).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def ms_to_time_of_day_ms(ms: int) -> int:
    """毫秒 epoch → 当日毫秒时刻（北京时区 00:00 起算）。

    ``TickQuotesSchema.time_ms`` 的口径是**当日毫秒**而非 epoch 绝对时刻：
    逐笔唯一键要跨日可分区、跨时区可比较，且 09:15:00.000 这类语义在当日
    毫秒下直观（34200000 = 09:30:00）。
    """
    dt = datetime.fromtimestamp(int(ms) / 1000, _TZ_BEIJING)
    return (
        (dt.hour * 3600 + dt.minute * 60 + dt.second) * 1000
        + dt.microsecond // 1000
    )


# ── 分时频率词表（M2/FR-04） ──
# 平台既有 freq 词表（tushare/akshare 与 agent 工具统一）：'1min'/'5min'/
# '15min'/'30min'/'60min'；datadir 只有两种周期目录 → 只映射 '1m'/'5m'。
FREQ_TO_READER_PERIOD = {"1min": "1m", "5min": "5m"}
READER_PERIOD_TO_FREQ = {v: k for k, v in FREQ_TO_READER_PERIOD.items()}


def freq_to_reader_period(freq: str) -> str:
    """平台 freq（'5min'）→ datadir 周期标识（'5m'）。

    Raises:
        ValueError: 不支持的频率。QMT datadir 仅有 1 分钟与 5 分钟两个周期
            目录（``_PERIOD_DIR``），其余频率（15/30/60min）需由上层聚合，
            不在数据源层伪造 —— 明确报错好过静默返回别的周期。
    """
    key = str(freq or "").strip().lower()
    period = FREQ_TO_READER_PERIOD.get(key)
    if period is None:
        raise ValueError(
            f"QMT datadir 不支持 freq={freq!r}；"
            f"支持 {sorted(FREQ_TO_READER_PERIOD)}"
        )
    return period


def reader_period_to_freq(period: str) -> str:
    """datadir 周期标识（'5m'）→ 平台 freq（'5min'）。"""
    freq = READER_PERIOD_TO_FREQ.get(str(period).strip().lower())
    if freq is None:
        raise ValueError(f"未知 datadir 周期 {period!r}")
    return freq


def iso_to_yyyymmdd(date_str: Optional[str]) -> Optional[str]:
    """'YYYY-MM-DD' → 'YYYYMMDD'（reader 的 start/end 参数口径）。"""
    if not date_str:
        return None
    s = str(date_str).strip().replace("-", "")
    return s if len(s) == 8 and s.isdigit() else None


def bare_to_ts_code(symbol: str) -> str:
    """裸 6 位代码 → ts_code（按交易所代码段规则补市场后缀）。

    段位规则与 reader._STOCK_PREFIXES 一致：6 开头 → SH；0/3 开头 → SZ；
    4/8/9 开头按北交所处理（reader.split_code 会拒读 BJ，返回 None 走缺口）。
    已带后缀的原样返回。
    """
    s = str(symbol).strip()
    if "." in s:
        return s
    s = s.zfill(6)
    if s.startswith("6"):
        return f"{s}.SH"
    if s.startswith(("4", "8", "9")):
        return f"{s}.BJ"
    return f"{s}.SZ"
