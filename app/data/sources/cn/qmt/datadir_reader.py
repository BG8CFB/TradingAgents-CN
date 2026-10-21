"""QMT datadir 本地二进制直读器（移植自 StockQuant，2026-10）。

【移植说明】本文件整体移植自 StockQuant `src/data/qmt/datadir_reader.py`
（2026-10-20 快照，1144 行），除以下三处外逻辑零改动：
1. 移除模块函数 ``datadir_root()``（原为 StockQuant Config 耦合点）——
   datadir 路径改由本包 ``config.get_qmt_datadir()`` 注入构造参数；
2. 新增 ``QmtSelfCheckReport`` / ``QmtDatadirReader.self_check()``——
   聚合自检视图，供 ``QmtProvider.connect()/is_available()`` 与 Web UI
   连通性测试复用，不改变任何单文件读取方法「失败返回 None」的契约；
3. 模块 docstring 头部追加本说明。
「RPC 兜底」字样为原项目语境：本项目无 RPC 通道（PRD D-7），
返回 None 的语义由上层 QmtProvider 翻译为「缺口登记 + 回退链接管」。

D盘 QMT datadir 本地二进制直读器（P0-2 原型，2026-09-10）。

数据链路升级「下载/读取分离 + D盘本地直读」（docs/plans/数据链路升级实施方案-20260910.md）
的读取面核心模块：不启动 QMT 客户端、不走 Redis RPC，纯文件 IO 直接解析 D 盘 datadir
二进制文件。格式实证依据：docs/plans/数据链路升级方案-下载读取分离与D盘本地直读-20260910.md
§3.2（探针脚本 tmp/scripts/probe_qmt_dat{,2,3,4}.py，结论经 E 盘真值逐字段对账）。

格式规范（小端）：
- K线（日线/1m/5m 同构，路径 {市场}/{86400|60|300}/{code}.DAT）：
  文件 = 8B 头（i64 哨兵 0x7FFFFFFFFFFFFFFE）+ N × 64B 记录
  记录 = ts[0:4]u32秒 | open/high/low/close×1000[4:20] | 保留[20:24]
        | volume[24:28]u32 | status[28:32]文件级常量 | amount[32:40]u64元
        | openInterest[40:44] | 单次因子f[44:48]f32 | 累计因子Πf[48:52]f32
        | preClose×1000[52:56] | 保留[56:60] | 尾哨兵[60:64] ∈ {0x7FFC, 0x7FFD, 0x7FFE}
  （[44:52] 因子槽语义原标注「待查证」，2026-09-15 已查证：`f_slot2 ≡ Πdr`
    相对偏差 3.3e-08、恒等式 F(n)=F(n−1)×f(n) 偏差 1.4e-07；
    日线/1m/5m 均带此两槽，tick 无。
    尾哨兵原写「恒32765」有误：实测 **两种取值并存**，日线 100% 为 0x7FFC
    （见下方 KLINE_TAIL_SENTINELS 说明））
- tick（路径 {市场}/0/{code}/{YYYYMMDD}.dat，144B 定长，无头）：
  raw_ts[0:4]当日毫秒+可变基偏移 | lastPrice[8:12]÷1000 | amount[16:24]u64元
  | volume[24:28] | openInt[28:32]（集合竞价段取值 12）
  | transactionNum[36:40] | open[44:48]÷1000 | high[48:52]÷1000 | low[52:56]÷1000
  | lastClose[60:64]÷1000 | askPrice[64:84]÷1000 | askVol[84:104]
  | bidPrice[104:124]÷1000 | bidVol[124:144]
  （2026-09-10 审计 D3/D15 逐槽位元素级实证修订——见下方 _TICK_DTYPE 注释）

与 qmt-parser 参考实现的关系（2026-09-15 逐条实测复核，勿照抄其偏移）：
1. **两种读法等价**（原写「其偏移表不跳头，照抄会漏掉最后一条记录」**不成立**）：
   qmt-parser 用「64B 滑窗 + 窗口内 set_position(8)」（其 buffer[0:8] 恰为
   上一条记录的尾 8 字节 / 首次为文件头），与本模块「整文件 offset=8、步长 64」
   **数学恒等**；实测 5 文件 / 23,489 条 / 7 字段**逐条全等**，末条一致。
2. tick 时间戳基偏移按「首条竞价行 = 09:15:00.000」自校准（基值随日期/文件
   变化，本机实测与其固定常量不符），不使用其固定常量。
3. **`amount` 一律直存（u64 元），勿引入 `/100`** —— 参考实现 day.rs 有
   `AMOUNT_SCALE=100` 而 min.rs 不除（其自相矛盾）；E 盘真值 3/3 比值
   =1.000000 证实直存正确（且 `vol` 单位为「手」：
   814,373×100×11.89 ≈ amount 969,948,436）。
4. 参考实现**不校验**头/尾哨兵，故对尾哨兵双值天然免疫；本模块保留校验
   （更强的格式漂移防护），但必须用**白名单**而非等值比较。

输出契约：与 xtdata 兼容层返回形状对齐（time=ms epoch、volume/preClose/suspendFlag
等原始列名），使采集器既有 _standardize_fields/_convert_timestamp 管道零改动复用；
列集合以 E 盘产品库现有 parquet schema 为准（2026-09-10 实读 data/daily、data/tick）：
- K线输出 time/open/high/low/close/volume/amount/preClose/suspendFlag
  + settelementPrice(0.0)/openInterest([40:44]槽位，实测恒15) 对齐现库列；
- tick 输出 time/lastPrice/amount/volume/lastClose + askPrice/askVol/bidPrice/bidVol
  （逐行 5 元素 list，与现库 object 列形态一致）+ open/high/low/openInt/transactionNum
  （2026-09-10 审计 D3 解码，原为 0 占位）+ market_phase_status（openInt 同源别名，
  向后兼容既有落盘 schema）；E 盘实测恒 0 的列（pvolume/stockStatus/结算价）保持 0。

自检策略（格式漂移防护，设计文档 §七-4）：
- 头哨兵 / 尾哨兵 / status 文件级全等且量级合理 / ts 单调 → 任一不满足拒读该文件
  （返回 None + 告警），绝不静默读出错值；
- preClose==前条close 链 → 仅告警不拒读：D盘缺中间记录（历史缺口）时该链天然断裂，
  属合法数据形态（与解析错位的大面积断裂由上述强校验兜底）。

P3 范围（2026-09-10 已完成）：finance（4 张多行结构表）/ dividends（LevelDB）/
industry+concept（文本与板块目录）/ 指数日线+权重 / 交易日历派生 / 复权本地复算。
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---- 格式常量（设计文档 §3.2 实证） ----
KLINE_HEADER_SENTINEL = 0x7FFFFFFFFFFFFFFE  # 8B 头 i64 小端哨兵
# 记录尾 [60:64] 哨兵。实测**两种取值并存**（2026-09-15 全量扫描 64,309 个 DAT）：
#   0x7FFC (32764) —— 日线 100%（SH/86400 2580/2580、SZ/86400 3321/3323）、
#                    SZ/300 99.8%、SH/300 49.1%、SH/60 10.0%、SZ/60 13.7%
#   0x7FFD (32765) —— 其余（分钟线多数）
# 两值仅差 1，且同一市场不同周期混合存在 → 属 **QMT 版本/批次差异**，非格式漂移。
# 原实现按等值 32765 校验，导致**本地日线读取全线失效**（reader.daily() 恒 None
# → 静默回退 RPC）。0x7FFC 文件的数据完好性已逐项验证：status 全等(433)、
# ts 单调、preClose 链 98.6~99.7%、价格区间合理、f_slot2>0 且单调非降。
# 故改为**白名单**：仍能拦截任何第三种取值（保留格式漂移防护能力）。
# 尾哨兵观测史存档（【2026-09-23 起不再校验】，仅记录已观测取值）：
#   0x7FFC / 0x7FFD —— 2026-09-15 实测两值并存（日线 100% 为 0x7FFC）；
#   0x7FFE —— 2026-09-23 实测：QMT 客户端当日全量重写后哨兵漂移为 0x7FFE
#   （SH/86400 全体文件文件级全等 0x7FFE，mtime 稳定 4h+ 无半写迹象）。
#   白名单校验已于 2026-09-23 移除（Deacon 决策）：两次事故证明白名单机制
#   会把 QMT 版本演进放大成全线故障；防错位由 status/ts/头哨兵自检承接。
#   若需恢复强校验，参考 tests/data/test_kline_sentinel_whitelist.py 历史。
KLINE_TAIL_SENTINELS = frozenset({0x7FFC, 0x7FFD, 0x7FFE})
KLINE_RECORD_SIZE = 64
# [28:32] 状态字：文件级常量，实测值随数据批次漂移（2026-09-09 样本 544=0x220、
# 2026-09-10 全量复核 440=0x1B8），不能钉死具体值——自检改为「全等 + 量级合理」
# （修复 2026-09-10：恒等 544 校验误拒真实文件，冒烟测试暴露）
KLINE_STATUS_MAX = 0xFFFFF                  # 量级上界：错位读价格/amount 高位必超
# 尾哨兵观测史定义于文件上方（KLINE_TAIL_SENTINELS，2026-09-23 起不再校验）
TICK_RECORD_SIZE = 144
# 集合竞价段标记：openInt 槽位（[28:32]）在集合竞价期间取值 12，据此锚定时间基。
# 2026-09-10 审计：原命名 TICK_PHASE_AUCTION（误作独立「相位」字段）——实测
# [28:32] 与 E 盘 openInt 列元素级 100% 一致，其语义即 openInt；12 只是该列的
# 竞价段取值，功能正确但命名误导，已更名。
TICK_AUCTION_MARKER = 12
TICK_PHASE_AUCTION = TICK_AUCTION_MARKER   # 向后兼容别名（deprecated）
PRICE_SCALE = 1000.0                         # 价格列 ×1000 存储
_TZ_BEIJING = timezone(timedelta(hours=8))

# 增量后缀文件（_4002/_9000）已告警过的路径集合。本机实测这些文件为元数据
# （如 24B = 3×i64），非 bar 数据、不参与合并，但每次读取都告警会刷屏
# （审计修复 D10）——同一路径只告警一次，重复降为 DEBUG。
_WARNED_INCREMENT_FILES: set = set()

# 周期 → datadir 目录名
_PERIOD_DIR = {'1d': '86400', '1m': '60', '5m': '300'}

# 64B K线记录结构化 dtype（日线/分钟线同构；u64 amount 落库前 astype(float64)）
_KLINE_DTYPE = np.dtype([
    ('ts', '<u4'), ('open', '<u4'), ('high', '<u4'), ('low', '<u4'),
    ('close', '<u4'), ('rsv1', '<u4'), ('volume', '<u4'), ('status', '<u4'),
    ('amount', '<u8'), ('open_interest', '<u4'), ('f_slot1', '<f4'), ('f_slot2', '<f4'),
    ('pre_close', '<u4'), ('rsv2', '<u4'), ('tail', '<u4'),
])

# 144B tick 记录 dtype。2026-09-10 审计 D3/D15：对 4 只股票做 D盘 vs E盘
# **元素级槽位匹配**（100% 吻合）后确定的真实布局：
#   amount          [16:24] u64 元  ← 原实现取 u32 [16:20]，>2^32 时静默回绕（D15）
#   openInt         [28:32] u32     ← 原命名 phase 且置 0（值被误搬进 market_phase_status）
#   transactionNum  [36:40] u32     ← 原 r5 占位未解码
#   open/high/low   [44:48]/[48:52]/[52:56] ÷1000  ← 原置 0 占位
# D15 影响：20260908 全市场 5217 只中 55 只（1.1%）日成交额 > 2^32（300308 262亿、
# 300750 174亿 等最活跃大票），其 tick amount 为回绕垃圾值。
_TICK_DTYPE = np.dtype([
    ('raw_ts', '<u4'),            # 0
    ('r1', '<u4'),                # 4
    ('last', '<u4'),              # 8   ÷1000
    ('r2', '<u4'),                # 12
    ('amount', '<u8'),            # 16  u64 元（勿改回 u4，见 D15）
    ('volume', '<u4'),            # 24
    ('open_interest', '<u4'),     # 28
    ('r4', '<u4'),                # 32
    ('transaction_num', '<u4'),   # 36
    ('r6', '<u4'),                # 40
    ('open', '<u4'),              # 44  ÷1000
    ('high', '<u4'),              # 48  ÷1000
    ('low', '<u4'),               # 52  ÷1000
    ('r7', '<u4'),                # 56
    ('last_close', '<u4'),        # 60  ÷1000
    ('ask_price', '<u4', (5,)),   # 64
    ('ask_vol', '<u4', (5,)),     # 84
    ('bid_price', '<u4', (5,)),   # 104
    ('bid_vol', '<u4', (5,)),     # 124
])

# dtype 槽位防错：占位字段数量写错会使 itemsize≠记录长度、自检前记录就整体
# 错位（2026-09-10 实测踩坑），import 期即拦截
assert _KLINE_DTYPE.itemsize == KLINE_RECORD_SIZE, _KLINE_DTYPE.itemsize
assert _TICK_DTYPE.itemsize == TICK_RECORD_SIZE, _TICK_DTYPE.itemsize


# 【移植改造】原 StockQuant 的模块函数 ``datadir_root()`` 已移除——那是与
# StockQuant Config 的唯一耦合点（lazy import + 硬编码 D 盘路径）。本项目
# 的 datadir 路径解析在 ``app/data/sources/cn/qmt/config.py::get_qmt_datadir()``
# （Mongo system_configs 优先、QMT_DATADIR 环境变量回退），经构造参数注入。


@dataclass
class QmtSelfCheckReport:
    """datadir 聚合自检结果（健康探针视图，移植改造新增）。"""

    ok: bool
    path_missing: bool = False          # datadir 根目录不存在
    universe_size: int = 0              # 本机有日线文件的 A 股代码数
    checked_files: int = 0              # 实际抽检并通过计数
    rejected_samples: List[str] = field(default_factory=list)  # 四级自检拒读的样本代码
    latest_trade_date: Optional[str] = None  # 交易日历最新日（YYYYMMDD），停更判定依据


# ---- LevelDB SSTable 只读解析（P3-2，2026-09-10） ----
# plyvel 在 Windows 无可用 wheel（编译失败实测），DividData 本机 36 个 .ldb
# 均为 type=0 无压缩块（探针5 实证）——纯 Python 解析 footer→index→data blocks。
_LDB_MAGIC = 0xDB4775248B80FB57  # SSTable footer 魔数
_LDB_TRAILER_SIZE = 8            # internal key 尾部 seq<<8|type


def _ldb_varint(b: bytes, pos: int) -> tuple:
    """LevelDB varint64 解码 → (value, new_pos)。"""
    result = 0
    shift = 0
    while True:
        if pos >= len(b):
            raise ValueError('varint 越界')
        c = b[pos]
        pos += 1
        result |= (c & 0x7F) << shift
        if not (c & 0x80):
            return result, pos
        shift += 7


def _ldb_block_entries(raw: bytes, off: int, size: int):
    """迭代 block 的 (key, value)（前缀压缩展开；仅支持 type=0 无压缩）。"""
    blk = raw[off:off + size]
    num_restarts = struct.unpack('<I', blk[-4:])[0]
    data_end = size - 4 * (num_restarts + 1)
    pos = 0
    last_key = b''
    while pos < data_end:
        shared, pos = _ldb_varint(blk, pos)
        non_shared, pos = _ldb_varint(blk, pos)
        vlen, pos = _ldb_varint(blk, pos)
        key_delta = blk[pos:pos + non_shared]
        pos += non_shared
        value = blk[pos:pos + vlen]
        pos += vlen
        key = last_key[:shared] + key_delta
        yield key, value
        last_key = key


def _iter_ldb_file(path: Path):
    """迭代单个 .ldb 的全部 (internal_key, value)。

    【2026-09-21 修复 P1】补**长度栅栏**。原实现存在多处越界/崩溃风险：
      * `raw[-48:]` 未校验文件长度 —— 文件 < 48B 时 `foot` 为空，
        `struct.unpack` 直接 `struct.error`；
      * `raw[off + sz]` 未校验 `off+sz < len(raw)` —— 越界时 `IndexError`；
      * `_ldb_varint` 在块尾可能越界。
    这些都属**环境/数据异常**（QMT 客户端并发写、文件半写、版本差异），
    原实现只在上层捕 `NotImplementedError`，其余异常会让整条 dividends
    加载崩掉（表 A 链断）。现统一按「文件不可解析」返回空（跳过该 .ldb），
    并由调用方决定是否告警 —— 单个坏文件不应拖垮全量。
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.warning('[ldb] 读取失败 %s: %s', path.name, e)
        return
    if len(raw) < 48:                               # footer 都放不下
        logger.warning('[ldb] 文件过短（%d B < 48），跳过: %s', len(raw), path.name)
        return
    foot = raw[-48:]
    try:
        magic = struct.unpack('<Q', foot[-8:])[0]
    except struct.error as e:
        logger.warning('[ldb] footer 解析失败 %s: %s', path.name, e)
        return
    if magic != _LDB_MAGIC:
        return
    try:
        pos = 0
        _, pos = _ldb_varint(foot, pos)   # metaindex offset（忽略）
        _, pos = _ldb_varint(foot, pos)   # metaindex size（忽略）
        i_off, pos = _ldb_varint(foot, pos)
        i_sz, pos = _ldb_varint(foot, pos)
    except Exception as e:                          # noqa: BLE001
        logger.warning('[ldb] index 元数据解析失败 %s: %s', path.name, e)
        return
    if i_sz <= 0 or i_off < 0 or i_off + i_sz > len(raw):
        logger.warning('[ldb] index 区间越界（off=%d sz=%d len=%d），跳过: %s',
                       i_off, i_sz, len(raw), path.name)
        return
    try:
        for _, handle in _ldb_block_entries(raw, i_off, i_sz):
            hpos = 0
            off, hpos = _ldb_varint(handle, hpos)
            sz, hpos = _ldb_varint(handle, hpos)
            # 长度栅栏：数据块尾部还有 1 字节 compression type
            if off < 0 or sz <= 0 or off + sz >= len(raw):
                logger.warning('[ldb] 数据块区间越界（off=%d sz=%d len=%d），跳过该块: %s',
                               off, sz, len(raw), path.name)
                continue
            if raw[off + sz] != 0:
                raise NotImplementedError(
                    f'{path.name}: block 压缩（type={raw[off + sz]}），需 snappy')
            yield from _ldb_block_entries(raw, off, sz)
    except NotImplementedError:
        raise                                    # 压缩块：语义明确，交由上层处理
    except Exception as e:                       # noqa: BLE001
        logger.warning('[ldb] 块迭代异常（已截断该文件后续块）%s: %s', path.name, e)
        return


class QmtDatadirReader:
    """D盘 datadir 本地二进制直读器（纯文件 IO，无 QMT/Redis 依赖）。

    所有公开读取方法在「文件缺失 / 自检拒读 / 市场不支持」时返回 None
    （或全 False 位图），由调用方（采集器）决定回退 RPC——本模块不抛业务异常。
    """

    def __init__(self, datadir: str):
        self._root = Path(datadir)
        # 分红 LevelDB 全扫缓存：{ts_code: df}；None=未加载，加载后 dict
        # （P3-2：单股查询频繁，全扫 36 个 .ldb 一次摊销）
        self._divid_cache: Optional[dict] = None

    # ---------- DividData 分红 LevelDB（P3-2，2026-09-10） ----------

    def dividends(self, ts_code: str, with_record_date: bool = False) -> Optional[pd.DataFrame]:
        """读单股分红送配全量历史（DividData LevelDB 直读）。

        返回与 adjustment 采集管道同形：trade_date/ts_code/interest/
        stock_bonus/stock_gift/allot_num/allot_price/gugai/dr。
        首次调用全扫 DividData/*.ldb 建缓存（~88 万 entry，一次性成本），
        后续查缓存。DividData 不存在 → None（调用方回退 RPC）；
        该股无分红记录 → None（合法空）。

        Parameters
        ----------
        with_record_date : bool
            是否附带两个**诊断列**（默认 False 以保持上述列契约不变 ——
            既有采集管道与测试按精确列序断言）：
            * `record_date` —— 股权登记日 R 日（源 `[80:84]`）
            * `date_src` —— `trade_date` 的来源：`'ex_u32'`（`[88:92]` 有效）
              或 `'ts_key'`（**回退派生，不可信**）。v5.0 实测 437 条除权日
              错位即来自该回退；`data.adjust.audit` 需要它来定位待校正事件。
            表 A 构建（`data/adjust/`）走 `_load_dividends()` 缓存直接取。

        格式依据：qmt-parser dividend.rs + 探针5（600000.SH 27/27 条
        interest/dr/除权日逐值对账通过；ex_date u32=0 时 ts_key 派生
        北京日期亦吻合）。
        """
        cache = self._load_dividends()
        if cache is None:
            return None
        df = cache.get(ts_code)
        if df is None:
            return None
        if with_record_date:
            return df
        # 默认剔除**诊断列**，保持既有列契约不变（采集管道与测试按精确列序断言）
        extra = [c for c in ('record_date', 'date_src') if c in df.columns]
        return df.drop(columns=extra) if extra else df

    def _load_dividends(self) -> Optional[dict]:
        """全扫 DividData 聚合 {ts_code: df}（幂等缓存；目录缺失 → None）。"""
        if self._divid_cache is not None:
            return self._divid_cache
        divid_dir = self._root / 'DividData'
        if not divid_dir.is_dir():
            # 审计修复 D11：负结果也缓存（空 dict），否则每次 dividends() 调用
            # 都会重做一次 is_dir() 文件系统检查。
            self._divid_cache = {}
            return None
        agg: dict = {}
        for ldb in sorted(divid_dir.glob('*.ldb')):
            try:
                for key, value in _iter_ldb_file(ldb):
                    # internal key 剥离 8B trailer → user key `SH|600000|4000|{ts}`
                    ukey = key[:-_LDB_TRAILER_SIZE] if len(key) > _LDB_TRAILER_SIZE else key
                    parts = ukey.split(b'|')
                    if len(parts) < 4:
                        continue
                    try:
                        ts_key = int(parts[-1])
                    except ValueError:
                        continue
                    if ts_key == 0 or ts_key > 3_000_000_000_000:
                        continue  # 哨兵 key
                    if len(value) < 96:
                        continue
                    market, sym = parts[0].decode('utf-8', 'replace'), parts[1].decode('utf-8', 'replace')
                    if market not in ('SH', 'SZ'):
                        continue
                    ex_u32 = struct.unpack_from('<I', value, 88)[0]
                    # ⚠️ v5.0（2026-09-15）：`[88:92]` 无效时的 `ts_key` 回退**不可信**。
                    # 实测 437 条除权日错位（2006 年 137 条、2015 年 78 条）——
                    # `ts_key` 常为**公告日或股权登记日**而非除权日，落成 `ex_date`
                    # 会让 `F(t)` 的台阶落在错误的交易日（错位日与真实除权日各错一天）。
                    # 因此这里**显式标记来源** `date_src`，由 `data.adjust.audit`
                    # 用 D 盘 K 线 `f_slot2` 跳变日校正；调用方不得再默认信任 `trade_date`。
                    if 19000101 < ex_u32 < 29991231:
                        trade_date, date_src = str(ex_u32), 'ex_u32'
                    else:
                        trade_date, date_src = self._ms_to_yyyymmdd(ts_key), 'ts_key'
                    # [80:84] = 股权登记日 R 日（2026-09-15 新解码；实测 63.2%
                    # 恰为除权日前 1 天、28.2% 差 2~5 天）。0 / 越界 → 空串。
                    rec_u32 = struct.unpack_from('<I', value, 80)[0]
                    record_date = (
                        str(rec_u32) if 19000101 < rec_u32 < 29991231 else ''
                    )
                    agg.setdefault(f'{sym}.{market}', []).append({
                        'trade_date': trade_date,
                        'date_src': date_src,
                        'record_date': record_date,
                        'interest': struct.unpack_from('<d', value, 16)[0],
                        'stock_bonus': struct.unpack_from('<d', value, 24)[0],
                        'stock_gift': struct.unpack_from('<d', value, 32)[0],
                        'allot_num': struct.unpack_from('<d', value, 40)[0],
                        'allot_price': struct.unpack_from('<d', value, 48)[0],
                        'gugai': struct.unpack_from('<d', value, 56)[0],
                        'dr': struct.unpack_from('<d', value, 72)[0],  # adjust_factor 槽
                    })
            except NotImplementedError as e:
                logger.warning(f'[datadir] {e}，跳过该文件')
                continue
        # 股内按除权日排序去重（同日多版本记录保留最后）
        cache: dict = {}
        for code, rows in agg.items():
            df = pd.DataFrame(rows)
            df = df.drop_duplicates(subset=['trade_date'], keep='last')
            df = df.sort_values('trade_date').reset_index(drop=True)
            df.insert(1, 'ts_code', code)
            cache[code] = df
        self._divid_cache = cache
        return cache

    @property
    def available(self) -> bool:
        """datadir 根目录存在（P1 构造期据此决定是否启用直读）。"""
        return self._root.is_dir()

    def self_check(self, sample_size: int = 3) -> QmtSelfCheckReport:
        """聚合自检（健康探针用，移植改造新增）：路径 → 宇宙 → 抽样四级自检 → 最新交易日。

        与单文件「拒读返回 None」契约的区别：本方法是聚合视图，只读不改任何
        数据；抽样覆盖首/中/尾不同批次文件，任一样本被四级自检拒读即判
        ``ok=False``。文件级缺失（``has_daily_file`` 为 False）不算拒读——
        ``stock_codes()`` 本就是「本机已下载」的下界（见其 docstring）。
        """
        report = QmtSelfCheckReport(ok=False)
        if not self.available:
            report.path_missing = True
            return report
        codes = self.stock_codes()
        report.universe_size = len(codes)
        if not codes:
            return report
        if len(codes) <= sample_size:
            sample = codes
        else:
            step = max(1, len(codes) // sample_size)
            sample = codes[::step][:sample_size]
        for code in sample:
            if not self.has_daily_file(code):
                continue
            report.checked_files += 1
            if self.daily(code) is None:
                report.rejected_samples.append(code)
        dates = self.trading_dates()
        report.latest_trade_date = dates[-1] if dates else None
        report.ok = report.checked_files > 0 and not report.rejected_samples
        return report

    # ---------- 市场映射 ----------

    @staticmethod
    def split_code(ts_code: str) -> Optional[Tuple[str, str]]:
        """'000001.SZ' → ('SZ', '000001')。

        BJ（北交所）暂无本地文件实证（本机 datadir 仅 SH/SZ），返回 None
        由调用方走 RPC 兜底（实施方案 P1-2）。
        """
        if not isinstance(ts_code, str) or '.' not in ts_code:
            return None
        symbol, _, market = ts_code.partition('.')
        market = market.upper()
        if market not in ('SH', 'SZ') or not symbol:
            return None
        return market, symbol

    # ---------- K线（日线/分钟线同构） ----------

    def daily(
        self, ts_code: str,
        start: Optional[str] = None, end: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """读单只日线（xtdata 形状：time(ms)/OHLC/volume/amount/preClose/suspendFlag...）。

        start/end 为 YYYYMMDD（闭区间）；返回 None 表示文件不可用/拒读（走 RPC 兜底）。
        """
        return self._kline(ts_code, '1d', start, end)

    def minute(
        self, ts_code: str, period: str,
        start: Optional[str] = None, end: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """读单只分钟线（period='1m'/'5m'，记录与日线同构 64B）。"""
        if period not in ('1m', '5m'):
            raise ValueError(f"period 仅支持 '1m'/'5m'，收到 {period!r}")
        return self._kline(ts_code, period, start, end)

    def has_daily(self, ts_code: str, dates: List[str]) -> np.ndarray:
        """存在性位图（对账用）：dates 中每个交易日是否在 D盘日线文件中有记录。

        文件缺失/拒读/市场不支持 → 全 False（D盘视角「无数据」，由对账层触发兜底）。
        """
        n = len(dates)
        if n == 0:
            return np.zeros(0, dtype=bool)
        mc = self.split_code(ts_code)
        if mc is None:
            return np.zeros(n, dtype=bool)
        arr = self._parse_kline(self._kline_path(mc[0], mc[1], '1d'))
        if arr is None or len(arr) == 0:
            return np.zeros(n, dtype=bool)
        have = {
            datetime.fromtimestamp(int(t), _TZ_BEIJING).strftime('%Y%m%d')
            for t in arr['ts']
        }
        return np.array([d in have for d in dates], dtype=bool)

    def has_daily_file(self, ts_code: str) -> bool:
        """日线文件是否存在（文件级判别，与 has_daily 的「有记录」语义区分）。

        P2-3 缺口收窄用：文件缺失 = 数据源缺失（下载兜底候选）；文件存在但
        某日无记录（停牌/历史缺口）≠ 需要下载——重读 fill 可补停牌行。
        """
        mc = self.split_code(ts_code)
        if mc is None:
            return False
        return self._kline_path(mc[0], mc[1], '1d').exists()

    # ---------- 代码枚举（本地宇宙派生，2026-09-20） ----------

    #: A 股代码前缀（用于过滤掉指数/基金等非股票 .DAT）
    _STOCK_PREFIXES = {
        'SH': ('600', '601', '603', '605', '688', '689'),
        'SZ': ('000', '001', '002', '003', '300', '301'),
    }

    def stock_codes(self, markets: Tuple[str, ...] = ('SH', 'SZ')) -> List[str]:
        """枚举 datadir 中**本机有日线文件**的 A 股代码（`ts_code` 形式，升序）。

        用于 `meta --local-only` 的本地宇宙派生（RPC 板块列表不可用时的兜底）。
        只取 6 位纯数字文件名（排除 `000001_9000.DAT` 这类变体/指数），并按
        市场前缀过滤——`SH/86400/` 下同时存在指数 `000001.DAT` 等非股票文件。

        语义边界：本列表 = **本机已下载数据的代码**（含退市股文件），是宇宙的
        **下界**；新上市/未下载的代码由 tushare `stock_basic` 镜像补（见
        `MetaCollector._collect_stock_list_local`）。
        """
        out: List[str] = []
        for market in markets:
            base = self._root / market / '86400'
            prefixes = self._STOCK_PREFIXES.get(market)
            if not base.is_dir() or not prefixes:
                continue
            try:
                names = [p.name for p in base.glob('*.DAT')]
            except OSError:
                continue
            for name in names:
                symbol = name[:-4]
                if len(symbol) != 6 or not symbol.isdigit():
                    continue
                if symbol.startswith(prefixes):
                    out.append(f'{symbol}.{market}')
        return sorted(set(out))

    # ---------- 复权复算（P4-1，2026-09-10） ----------

    def adjust_frame(
        self, df: pd.DataFrame, ts_code: str, dividend_type: str,
    ) -> pd.DataFrame:
        """对直读 K线帧做前/后复权（**纯乘式，两式同源同基准**）。

        【B2 修复 2026-09-11】原实现是**两套不同数学构造**，导致轨道间不自洽：
          front(t) = (p − Σ_{e>t}i + Σ_{e>t}ap·an) / Π_{e>t}(1+b+g+an)   ← 减法式
          back(t)  = p×G(t) + Σ_{e≤t} cash×G                             ← 加现金项
        实测后果（生产数据判定，见 tmp/verify_0910/logs/）：
          * `back/front` 比值随价格逐日漂移（CV 1.3e-2 ~ 2.3e-1，正确式应为常数）；
          * front 在长历史高现金分红股票上产出**负价格**
            （600519.SH 4,052 行中 1,581 行为负，最小 −221.78）。

        **现行公式（不变量：`back/front ≡ F_max` 恒定）**
          F(t)   = Π_{e≤t} (1 + stock_bonus + stock_gift + allot_num)   # 股本扩张倍数，单调非降
          F_max  = F(最后一个事件)
          front(t) = close(t) × F(t) / F_max      # 最新日因子 = 1
          back(t)  = close(t) × F(t)              # 最早日因子 = 1
        实测：正确式 CV = 1e-16；错误式 CV = 1.3e-2~2.3e-1。

        **不使用 `dr` 字段**：实测 `dr ≠ 1+stock_bonus+stock_gift+allot_num`
        （56,041 条中 55,164 条不等，如 000001.SZ 19910502：dr=1.409486 vs 1.40），
        `dr` 是除权参考价比例，不是股本扩张倍数。

        - OHLC/preClose 全调；volume/amount 不调（E盘实测 37302→37302）。
        - 事件当日计入（`e ≤ t`）；纯现金分红事件 grow=1 ⇒ F 不变 ⇒ 价格不变
          （现金分红对**价格序列**不产生阶跃，仅影响收益率口径）。
        - 无事件/非法类型：原样返回（副本）。向量化：searchsorted + cumprod。
        """
        if dividend_type not in ('front', 'back'):
            # 审计修复 D13：返回副本而非入参别名（原实现直接 return df，
            # 调用方就地改动会串扰原始帧）。
            return df.copy() if df is not None else df
        events = self.dividends(ts_code)
        if events is None or events.empty:
            return df.copy() if df is not None else df

        ev_dates = np.asarray(events['trade_date'].astype(str).tolist())
        # 【口径说明】本函数为**纯乘式**：grow = 1 + 送股 + 转增 + 配股，
        # 现金分红不参与分母（原「减法式」会产出负价）。
        #
        # ⚠️ 注意：`tests/data/test_adjust_local.py` 顶部 docstring 写的是
        # **2026-09-10 P4-1 版本**的总和式，已被同文件**类级 docstring**
        # 记录的 B2 修复（2026-09-11）取代 —— 后者明确指出：
        #   * 旧「减法式」在长历史高现金分红股上产出**负价格**
        #     （600519.SH 4052 行中 1581 行为负）；
        #   * 与 back 不同源 → back/front 比值漂移（旧式 1.103039 ≠ 应有 g²=1.21）。
        # 故现行为**纯乘式**是**有意设计**，且测试期望值由独立数学推导给出
        # （不取自实现）。2026-09-21 审计曾误判此处"漏 interest"为缺陷，
        # 已证伪 —— **勿改为总和式，勿使用 `dr` 字段**
        # （同文件已实证「dr ≠ 除权因子」：000430 dr=1.15 vs 实际 2.0）。
        grow = (
            1.0
            + events['stock_bonus'].fillna(0).astype(float).to_numpy()
            + events['stock_gift'].fillna(0).astype(float).to_numpy()
            + events['allot_num'].fillna(0).astype(float).to_numpy()
        )

        # 防御：grow 必须为正，否则说明数据异常（负/零会让乘式产生非正价格）
        if not np.all(grow > 0):
            logger.warning(
                "[datadir] %s 的复权因子存在非正值，复权已跳过以保持原值", ts_code
            )
            return df.copy()

        out = df.copy()
        row_td = (
            pd.to_datetime(out['time'], unit='ms', utc=True)
            .dt.tz_convert('Asia/Shanghai').dt.strftime('%Y%m%d').to_numpy()
        )
        # idx = 该行日期之前（含当日）的事件数
        idx = np.searchsorted(ev_dates, row_td, side='right')
        price_cols = [c for c in ('open', 'high', 'low', 'close', 'preClose')
                      if c in out.columns]

        # F[k] = Π_{j<k} grow[j]；F(t) = F[idx]（含当日事件，因 idx 为 <=t 的个数）
        F = np.concatenate([[1.0], np.cumprod(grow)])
        F_t = F[idx]
        F_max = F[-1]

        if dividend_type == 'front':
            scale = F_t / F_max
        else:
            scale = F_t
        for c in price_cols:
            out[c] = out[c].astype(float) * scale
        return out

    # ---------- 指数权重/交易日历（P3-4/P3-5，2026-09-10） ----------

    def index_weights(self, index_code: str) -> Optional[dict]:
        """Weight/sectorWeightData.txt → {ts_code: weight}（真实权重，P3-4）。

        文件格式（探针实证）：每行 `SH000300;600000.SH,0.453;600009.SH,0.299;...`
        ——行首为无点指数代码（SH000300），段为 `ts_code,weight(百分比)`。
        覆盖全部宽基（SH000300 301 成分/SZ399001 501/...），替代等权占位。
        文件缺失或该指数无记录 → None。
        """
        try:
            text = (self._root / 'Weight' / 'sectorWeightData.txt').read_text(encoding='utf-8')
        except OSError:
            return None
        # 000300.SH → SH000300（行首无点格式）
        mc = self.split_code(index_code)
        if mc is None:
            return None
        row_key = f'{mc[0]}{mc[1]}'
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith(row_key + ';'):
                continue
            weights = {}
            for seg in line.split(';')[1:]:
                if ',' not in seg:
                    continue
                code, _, w = seg.partition(',')
                code = code.strip()
                try:
                    weights[code] = float(w)
                except ValueError:
                    continue
            return weights or None
        return None

    def trading_dates(self) -> Optional[List[str]]:
        """D盘上证指数日线（SH/86400/000001.DAT）→ 升序 YYYYMMDD 列表（P3-5）。

        上证指数每个交易日一根 bar，天然为完整日历（真实验证：E盘日历 4053 天
        零冲突全包含于 D盘 5722 天集合，且多 1669 天 2003~2010 历史）。
        文件缺失/拒读 → None（调用方回退 xtdata API）。
        """
        arr = self._parse_kline(self._root / 'SH' / '86400' / '000001.DAT')
        if arr is None or len(arr) == 0:
            return None
        return sorted({
            datetime.fromtimestamp(int(t), _TZ_BEIJING).strftime('%Y%m%d')
            for t in arr['ts']
        })

    # ---------- 行业/概念板块（P3-3，2026-09-10） ----------

    def industry_data(self) -> Optional[List[Tuple[str, List[str]]]]:
        """IndustryData.txt → [(行业名, [ts_code])]（证监会行业，P3-3）。

        每行 `行业名,代码,代码,...`；代码 SH600003 → 600003.SH（E 盘 ts_code 格式）。
        文件缺失 → None（调用方降级）。
        """
        p = self._root / 'Industry' / 'IndustryData.txt'
        try:
            text = p.read_text(encoding='utf-8')
        except OSError:
            return None
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line or ',' not in line:
                continue
            parts = [x for x in line.split(',') if x]
            if len(parts) < 2:
                continue
            name, raw_codes = parts[0], parts[1:]
            codes = []
            for rc in raw_codes:
                rc = rc.strip()
                if len(rc) >= 8 and rc[:2] in ('SH', 'SZ', 'BJ') and rc[2:].isdigit():
                    codes.append(f'{rc[2:]}.{rc[:2]}')
                elif '.' in rc:
                    codes.append(rc)
            if codes:
                rows.append((name, codes))
        return rows or None

    def sector_names(self, kind: str, base: str = 'Sector') -> Optional[List[str]]:
        """`{base}/{kind}/` 下板块名列表（排除 .xml 等配置文件，字母序）。

        kind 如 'D概念' / 'T行业' / '申万行业' / 'GICS'。目录缺失 → None。

        base（2026-09-15 D25 新增，默认 'Sector' 向后兼容）：
          * `Sector`  —— **当前生效快照**，QMT 客户端会定期重写（实测 2026-09-15
                          11:21~11:23 把 `指数成分股板块` 由 608 个文件重写为 21 个）
          * `Sector/Temple` —— **全量分类仓库**（30 类 / 7,029 文件 / 7.2 MB，
                          实测 mtime 稳定），含 `GICS`/`概念`/`申万行业`/`指数` 等
                          **可 100% 复现产品表 `meta/industry`(39,397 行) 与
                          `meta/concept`(GN 前缀)** 的本地源。
        """
        d = self._root / base / kind
        if not d.is_dir():
            return None
        return sorted(
            p.name for p in d.iterdir()
            if p.is_file() and not p.name.lower().endswith(('.xml', '.dat', '.ini', '.cfg'))
        )

    def sector_members(self, kind: str, name: str, base: str = 'Sector') -> Optional[List[str]]:
        """`{base}/{kind}/{name}` 文件 → 成员 ts_code 列表（逗号分隔，UTF-8）。

        base 语义见 `sector_names`。空文件返回 None。
        """
        p = self._root / base / kind / name
        try:
            text = p.read_text(encoding='utf-8')
        except OSError:
            return None
        return [x.strip() for x in text.split(',') if x.strip()] or None

    # ---------- Finance 财务数据（P3-1，2026-09-10） ----------

    # 8 表记录步长（qmt-parser FINANCE.md + 本机 600000 全 8 表整除实证 2026-09-10）
    FINANCE_RECORD_SIZES = {
        7001: 1264, 7002: 664, 7003: 920, 7004: 56,
        7005: 64, 7006: 416, 7007: 416, 7008: 344,
    }
    # P3-1 直读范围：4 张多行结构表（raw 通道不支持、大QMT 下被显式跳过的表）；
    # 三大报表+比率（7001/7002/7003/7008）列级对齐复杂（xtdata 重排列序），
    # 且 raw 通道已覆盖，留后续迭代。
    _FINANCE_LOCAL_TABLES = {7004, 7005, 7006, 7007}
    _FINANCE_NAN_SENTINEL = 0x7FEFFFFFFFFFFFFF  # 空值位模式（FINANCE.md §1.3）

    def finance(self, ts_code: str, table_id: int) -> Optional[pd.DataFrame]:
        """读单只财务表（P3-1：7004 股本 / 7005 股东户数 / 7006 十大股东 / 7007 流通十大）。

        路径 Finance/{市场}/86400/{code}_{table_id}.DAT（本机实证：SH/SZ，BJ 不支持）。
        输出列形状与 E 盘 fundamentals schema 逐列对齐（dtype 亦对齐：日期列 str
        YYYYMMDD、数值列 float64——探针4 实证；stock_code 由采集层补）：
        - 7004 → m_timetag/m_anntime/total_capital/circulating_capital/
                 restrict_circulating_capital/freeFloatCapital
        - 7005 → declareDate/endDate/shareholder{,A,B,H,Float,Other}
        - 7006/7007 → declareDate/endDate/quantity/ratio/rank/name/type/reason/nature

        NaN 哨兵 0x7FEFFFFFFFFFFFFF → NaN；文件缺失/空 → None。
        布局依据：FINANCE.md + 探针4（600000 值级对账：7004 股本 4 值一致、
        7005 户数一致）。
        2026-09-10 审计 D7 修正：7006/7007 语义原写反（Top10Holder↔7007）。
        5 只股票全历史元素级实证：7006=E top10_holder、7007=E top10_flow_holder
        各 100.0% 吻合；consumer 侧映射见 collector/fundamental.LOCAL_FINANCE_TABLES。
        """
        if table_id not in self._FINANCE_LOCAL_TABLES:
            # 审计修复 D12：与 daily/minute/tick 的「不可用返回 None」契约一致
            # （原实现抛 ValueError；FINANCE_RECORD_SIZES 虽广告 8 张表，但
            # 三大报表/比率列级对齐复杂且 raw 通道已覆盖，不在此实现范围）。
            logger.debug(
                f"[datadir] finance 表 {table_id} 未实现本地直读，返回 None"
                f"（支持 {sorted(self._FINANCE_LOCAL_TABLES)}）"
            )
            return None
        mc = self.split_code(ts_code)
        if mc is None:
            return None
        market, symbol = mc
        path = self._root / 'Finance' / market / '86400' / f'{symbol}_{table_id}.DAT'
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        stride = self.FINANCE_RECORD_SIZES[table_id]
        n = len(raw) // stride
        if n == 0:
            return None

        if table_id == 7004:
            return self._fin_capital(raw, n)
        if table_id == 7005:
            return self._fin_holder_num(raw, n)
        return self._fin_top10(raw, n)

    def _fin_i64(self, raw: bytes, rec_i: int, off: int) -> int:
        return struct.unpack_from('<q', raw, rec_i + off)[0]

    def _fin_f64(self, raw: bytes, rec_i: int, off: int) -> float:
        """f64 槽位；NaN 哨兵 → NaN（非垃圾大数）。"""
        q = struct.unpack_from('<q', raw, rec_i + off)[0]
        if q == self._FINANCE_NAN_SENTINEL:
            return float('nan')
        return struct.unpack_from('<d', raw, rec_i + off)[0]

    @staticmethod
    def _fin_cstr(raw: bytes, rec_i: int, off: int, n: int) -> str:
        """定长 UTF-8 字符槽（\\0 截断）。"""
        b = raw[rec_i + off:rec_i + off + n]
        return b.split(b'\x00', 1)[0].decode('utf-8', errors='replace')

    def _ms_to_yyyymmdd(self, ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, _TZ_BEIJING).strftime('%Y%m%d')

    def _fin_capital(self, raw: bytes, n: int) -> pd.DataFrame:
        """7004 股本结构（56B：ReportDate/AnnounceDate + 4×f64 股本 + 8B 保留）。"""
        rows = []
        for i in range(n):
            o = i * 56
            rows.append({
                'm_timetag': self._ms_to_yyyymmdd(self._fin_i64(raw, o, 0)),
                'm_anntime': self._ms_to_yyyymmdd(self._fin_i64(raw, o, 8)),
                'total_capital': self._fin_f64(raw, o, 16),
                'circulating_capital': self._fin_f64(raw, o, 24),
                'restrict_circulating_capital': self._fin_f64(raw, o, 32),
                'freeFloatCapital': self._fin_f64(raw, o, 40),
            })
        return pd.DataFrame(rows)

    def _fin_holder_num(self, raw: bytes, n: int) -> pd.DataFrame:
        """7005 股东户数（64B：[0:8]=AnnounceDate→declareDate [8:16]=ReportDate→endDate + 6×f64）。"""
        rows = []
        for i in range(n):
            o = i * 64
            rows.append({
                'declareDate': self._ms_to_yyyymmdd(self._fin_i64(raw, o, 0)),
                'endDate': self._ms_to_yyyymmdd(self._fin_i64(raw, o, 8)),
                'shareholder': self._fin_f64(raw, o, 16),
                'shareholderA': self._fin_f64(raw, o, 24),
                'shareholderB': self._fin_f64(raw, o, 32),
                'shareholderH': self._fin_f64(raw, o, 40),
                'shareholderFloat': self._fin_f64(raw, o, 48),
                'shareholderOther': self._fin_f64(raw, o, 56),
            })
        return pd.DataFrame(rows)

    def _fin_top10(self, raw: bytes, n: int) -> pd.DataFrame:
        """7006/7007 十大股东（416B，FINANCE.md §3.1 偏移，探针4 实证）。"""
        rows = []
        for i in range(n):
            o = i * 416
            rows.append({
                'declareDate': self._ms_to_yyyymmdd(self._fin_i64(raw, o, 0)),
                'endDate': self._ms_to_yyyymmdd(self._fin_i64(raw, o, 8)),
                'name': self._fin_cstr(raw, o, 16, 192),
                'type': self._fin_cstr(raw, o, 216, 56),
                'quantity': self._fin_f64(raw, o, 272),
                'reason': self._fin_cstr(raw, o, 280, 16),
                'ratio': self._fin_f64(raw, o, 304),
                'nature': self._fin_cstr(raw, o, 312, 96),
                'rank': float(struct.unpack_from('<I', raw, o + 412)[0]),
            })
        return pd.DataFrame(rows)

    # ---------- tick ----------

    def tick(self, ts_code: str, trade_date: str) -> Optional[pd.DataFrame]:
        """读单只单日分笔（144B 定长，含 5 档买卖盘与竞价段标记）。

        时间戳基偏移自校准：首条竞价行（openInt=12）锚定 09:15:00.000。
        无竞价行 → 时间基不可校准 → 拒读返回 None（修复 2026-09-10 P2-2：
        原「退化为相对时刻仍返回数据」会使落库 time 列自 00:00 起算、语义
        错误——实测 000113.SH 即此形态；采集层据 None 走 RPC 兜底）。

        2026-09-10 审计 D3/D15：open/high/low/openInt/transactionNum 改为解码
        真实槽位（原 0 占位）；amount 改按 u64 解码（原 u32 → >2^32 回绕）。
        """
        mc = self.split_code(ts_code)
        if mc is None:
            return None
        market, symbol = mc
        path = self._root / market / '0' / symbol / f'{trade_date}.dat'
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        recs = len(raw) // TICK_RECORD_SIZE
        if recs == 0:
            return None
        if len(raw) % TICK_RECORD_SIZE:
            # QMT 运行中半写尾记录：容忍截断为整记录
            logger.info(
                f"[datadir] tick 半写截断 {ts_code} {trade_date}"
                f"（弃尾 {len(raw) % TICK_RECORD_SIZE}B）"
            )
        arr = np.frombuffer(raw, dtype=_TICK_DTYPE, count=recs)

        day0 = datetime.strptime(trade_date, '%Y%m%d').replace(tzinfo=_TZ_BEIJING)
        auction_open_ms = int(
            day0.replace(hour=9, minute=15).timestamp() * 1000
        )
        auction_idx = np.flatnonzero(arr['open_interest'] == TICK_AUCTION_MARKER)
        if len(auction_idx) == 0:
            # 无竞价行 → 基值不可校准 → 拒读（走 RPC 兜底），不返回相对时刻
            logger.warning(
                f"[datadir] tick {ts_code} {trade_date} 无竞价行，"
                f"时间基不可校准，拒读（走 RPC 兜底）"
            )
            return None
        # 首条竞价行 = 09:15:00.000（实证：文件内毫秒差分严格线性）
        base = int(arr['raw_ts'][auction_idx[0]])
        time_ms = arr['raw_ts'].astype('int64') - base + auction_open_ms
        # 范围合理性（09:00~15:35 之外告警，不拒读）
        day0_ms = int(day0.timestamp() * 1000)
        tod = time_ms - day0_ms
        if tod.size and (tod.min() < 9 * 3600 * 1000 or tod.max() > 15 * 3600 * 1000 + 35 * 60 * 1000):
            logger.warning(
                f"[datadir] tick {ts_code} {trade_date} 校准后时刻越界"
                f"（{tod.min()}~{tod.max()}ms），请核查基偏移"
            )

        n = len(arr)
        df = pd.DataFrame({
            'time': time_ms,
            'lastPrice': arr['last'] / PRICE_SCALE,
            # u64 元：整日累计成交额可超 2^32（D15），不可改回 u32
            'amount': arr['amount'].astype('float64'),
            'volume': arr['volume'].astype('int64'),
            'lastClose': arr['last_close'] / PRICE_SCALE,
            # openInt 同源别名：保留既有落盘 schema 兼容（值 == openInt）
            'market_phase_status': arr['open_interest'].astype('int64'),
            # 5 档：逐行 5 元素 list，对齐现库 object 列形态
            'askPrice': (arr['ask_price'] / PRICE_SCALE).tolist(),
            'askVol': arr['ask_vol'].astype('int64').tolist(),
            'bidPrice': (arr['bid_price'] / PRICE_SCALE).tolist(),
            'bidVol': arr['bid_vol'].astype('int64').tolist(),
            # 2026-09-10 审计 D3：以下 5 列由 0 占位改为真实解码
            'open': arr['open'] / PRICE_SCALE,
            'high': arr['high'] / PRICE_SCALE,
            'low': arr['low'] / PRICE_SCALE,
            'openInt': arr['open_interest'].astype('int64'),
            'transactionNum': arr['transaction_num'].astype('int64'),
            # E 盘实测亦恒 0 的列：保持 0（无信息可解）
            'pvolume': np.zeros(n, dtype='int64'),
            'stockStatus': np.zeros(n, dtype='int64'),
            'lastSettlementPrice': np.zeros(n, dtype='float64'),
            'settlementPrice': np.zeros(n, dtype='float64'),
        })
        return df

    # ---------- 内部实现 ----------

    def _kline_path(self, market: str, symbol: str, period: str) -> Path:
        return self._root / market / _PERIOD_DIR[period] / f'{symbol}.DAT'

    def _kline(
        self, ts_code: str, period: str,
        start: Optional[str], end: Optional[str],
    ) -> Optional[pd.DataFrame]:
        mc = self.split_code(ts_code)
        if mc is None:
            return None
        market, symbol = mc
        path = self._kline_path(market, symbol, period)
        self._warn_increment_files(path)
        arr = self._parse_kline(path)
        if arr is None:
            return None
        lo, hi = self._date_bounds(start, end)
        if lo is not None or hi is not None:
            ts = arr['ts'].astype('int64')
            mask = np.ones(len(arr), dtype=bool)
            if lo is not None:
                mask &= ts >= lo
            if hi is not None:
                mask &= ts < hi
            arr = arr[mask]
        n = len(arr)
        df = pd.DataFrame({
            # 秒→ms epoch：日线=交易日 00:00、分钟线=bar 时刻（_convert_timestamp 契约）
            'time': arr['ts'].astype('int64') * 1000,
            'open': arr['open'] / PRICE_SCALE,
            'high': arr['high'] / PRICE_SCALE,
            'low': arr['low'] / PRICE_SCALE,
            'close': arr['close'] / PRICE_SCALE,
            'volume': arr['volume'].astype('int64'),
            'amount': arr['amount'].astype('float64'),  # u64 元，无溢出顾虑
            'preClose': arr['pre_close'] / PRICE_SCALE,
            # 真实成交记录恒 0；停牌补齐行由采集层按日历 reindex 生成（P1-3）
            'suspendFlag': np.zeros(n, dtype='int64'),
            # 对齐现库列（xtdata 透传槽位）：settelementPrice 恒 0.0、
            # openInterest=[40:44] 槽位（实测恒 15，与 E盘 daily 现值吻合）
            'settelementPrice': np.zeros(n, dtype='float64'),
            'openInterest': arr['open_interest'].astype('int64'),
        })
        self._attach_factor_columns(df, arr, period)
        return df

    @staticmethod
    def _attach_factor_columns(df: pd.DataFrame, arr: np.ndarray, period: str) -> None:
        """就地补 `adj_f_evt` / `adj_f_cum` 两列（P1，方案 §3.3 表 B）。

        * `adj_f_evt` = `[44:48]` 单次因子 `f`（**除权日含当日**）
        * `adj_f_cum` = `[48:52]` 累计因子 `Πf`（等价于 `Πdr`，与表 A 一致）

        **分钟线特殊处理**：实测除权日仅**首根 bar** 携带真实 `f_slot1`，
        其余 bar 为首值 `1.0`（5min 实测 1/48 = 2.1%）。故按**交易日聚合**
        「当日非 1.0 的首个值」，全无事件则回填 1.0 —— 等价于按日 ffill，
        但不依赖「非事件 bar 为 NaN」这一不成立的前提。
        `adj_f_cum` 实测已日级恒定、100% 填充，无需处理（仅做一致性告警）。
        """
        df['adj_f_evt'] = arr['f_slot1'].astype('float64')
        df['adj_f_cum'] = arr['f_slot2'].astype('float64')
        if len(df) == 0:
            return
        if period != '1d':
            day = pd.Series(
                (arr['ts'].astype('int64') + 8 * 3600) // 86400, index=df.index
            )
            raw = df['adj_f_evt']
            day_f = raw.where(raw != 1.0).groupby(day).transform('first')
            df['adj_f_evt'] = day_f.fillna(1.0)
            # V6 自检（告警级）：分钟线累计因子应在日内恒定
            n_per_day = day.value_counts()
            intraday_days = set(n_per_day[n_per_day > 1].index)
            if intraday_days:
                sub = df[day.isin(intraday_days)]
                nuniq = sub.groupby(day)['adj_f_cum'].nunique()
                if int(nuniq.max()) > 1:
                    logger.warning(
                        f"[datadir] adj_f_cum 日内非恒定（{int((nuniq > 1).sum())} 天，"
                        f"最大 {int(nuniq.max())} 个取值），疑似记录错位"
                    )

    def _parse_kline(self, path: Path) -> Optional[np.ndarray]:
        """读 + 自检 + 向量化解析；文件缺失/过小/拒读返回 None。"""
        try:
            raw = path.read_bytes()
        except OSError as e:
            logger.warning(f"[datadir] 读取失败 {path.name}: {e}")
            return None
        n = len(raw)
        if n < 8 + KLINE_RECORD_SIZE:
            # 空文件/仅头：视为无数据（正常形态，不告警刷屏）
            return None
        (header,) = struct.unpack('<q', raw[:8])
        if header != KLINE_HEADER_SENTINEL:
            logger.warning(f"[datadir] 头哨兵异常 {path}（0x{header:X}），拒读")
            return None
        body = n - 8
        if body % KLINE_RECORD_SIZE:
            dropped = body % KLINE_RECORD_SIZE
            body -= dropped
            logger.info(f"[datadir] {path.name} 尾部半写 {dropped}B，截断容忍")
        recs = body // KLINE_RECORD_SIZE
        arr = np.frombuffer(raw, dtype=_KLINE_DTYPE, count=recs, offset=8)

        # ── 拒读级自检（格式漂移防护，任一不满足整文件拒读） ──
        # 【2026-09-23 移除尾哨兵校验（白名单 + 文件级全等）——Deacon 决策】
        # 该校验自 2026-09-15 引入后两次成为全线故障源：
        #   09-15 当天：0x7FFC 未入白名单 → 日线直读全线失效（本文件测试背景）；
        #   09-23 当天：QMT 客户端全量重写后哨兵漂移 0x7FFE → 全量拒读 →
        #   D 盘派生日历失效 → 行情采集判 FAIL（job 18:31 事故）。
        # 尾哨兵的防错位价值已由「status 文件级全等 + 量级合理 + ts 单调 +
        # 头哨兵」覆盖（参考实现不校验尾哨兵，天然免疫此类漂移）。
        # 观测史存档：0x7FFC（日线）/0x7FFD（分钟）/0x7FFE（2026-09-23 起），
        # 若未来需要恢复强校验，参考 tests/data/test_kline_sentinel_whitelist.py。
        # status：文件级常量，值随数据批次漂移（440/544 均实测过）——
        # 校验「全等 + 量级合理」而非恒等：错位读出的价格/amount 高位必超界或非全等
        status_vals = arr['status']
        if not bool(np.all(status_vals == status_vals[0])):
            logger.warning(
                f"[datadir] status 非全等 {path.name}"
                f"（疑似格式漂移/记录错位），拒读"
            )
            return None
        if int(status_vals[0]) > KLINE_STATUS_MAX:
            logger.warning(
                f"[datadir] status 量级异常 {path.name}"
                f"（{int(status_vals[0])} > {KLINE_STATUS_MAX}，疑似格式漂移），拒读"
            )
            return None
        # u4 差分需先转 i64，否则递减回绕成大正数使校验失效
        if recs > 1 and not bool(
            np.all(np.diff(arr['ts'].astype('int64')) > 0)
        ):
            logger.warning(f"[datadir] ts 非单调 {path.name}，拒读")
            return None
        # ── 告警级：preClose 链断裂（D盘缺中间记录的合法形态，见模块 docstring） ──
        if recs > 1:
            chain_ok = arr['pre_close'][1:] == arr['close'][:-1]
            bad = int(np.count_nonzero(~chain_ok))
            if bad:
                logger.warning(
                    f"[datadir] {path.name} preClose 链断裂 {bad} 处"
                    f"（疑似历史缺记录，不影响解析）"
                )
        return arr

    @staticmethod
    def _date_bounds(
        start: Optional[str], end: Optional[str],
    ) -> Tuple[Optional[int], Optional[int]]:
        """YYYYMMDD → 北京时区当日 00:00 unix 秒。

        返回 (lo, hi 排他上界)：end 取次日 0 点，使日线（当日 00:00）与
        分钟线（当日 15:00 前）均在闭区间内。
        """
        lo = hi = None
        if start:
            lo = int(
                datetime.strptime(start, '%Y%m%d')
                .replace(tzinfo=_TZ_BEIJING).timestamp()
            )
        if end:
            d = datetime.strptime(end, '%Y%m%d') + timedelta(days=1)
            hi = int(d.replace(tzinfo=_TZ_BEIJING).timestamp())
        return lo, hi

    def _warn_increment_files(self, path: Path) -> None:
        """增量后缀文件（_4002/_9000）非零时告警（本机实测 0 字节）。

        语义未知不参与合并（设计文档 §3.3-4），非零即提示人工核查。
        审计修复 D10：同一路径只告警一次（实测 SZ/86400/000001_4002.DAT 为
        24B 元数据记录而非 bar），重复触发降为 DEBUG，避免每次读取刷 WARNING。
        """
        for suffix in ('_4002', '_9000'):
            inc = path.with_name(f"{path.stem}{suffix}{path.suffix}")
            try:
                if not inc.exists():
                    continue
                size = inc.stat().st_size
            except OSError:
                continue
            if size <= 0:
                continue
            key = str(inc)
            if key in _WARNED_INCREMENT_FILES:
                logger.debug(
                    f"[datadir] 增量文件非零 {inc.name}（{size}B），已告警过，跳过"
                )
                continue
            _WARNED_INCREMENT_FILES.add(key)
            logger.warning(
                f"[datadir] 增量文件非零 {inc.name}"
                f"（{size}B），未参与合并，请核查"
            )
