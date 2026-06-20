---
name: risk-aware-analysis
description: 风险优先的股票分析框架。当用户强调"风险控制""防守""回撤""仓位控制"或分析周期为熊市/震荡市时使用。提供基于 VaR、最大回撤、波动率的风险量化方法。
version: 1.0.0
user-invocable: true
license: Apache-2.0
compatibility: "需要 daily_quotes 与 daily_indicators 数据可用"
metadata:
  author: TradingAgents-CN
  category: risk
  tags: "风险控制 仓位管理 回撤 波动率 VaR"
allowed-tools: daily_quotes daily_indicators
---

# 风险优先分析技能

## 适用场景

- 用户明确要求"风险优先""防守型""低回撤"
- 当前市场处于熊市或震荡市
- 分析标的是高波动个股（波动率 > 30%）
- 需要做仓位控制建议

## 分析框架

### 第一步：基础风险指标

基于日线行情计算以下指标（20日/60日窗口）：

1. **日收益率波动率**：std(daily_returns) * sqrt(252)
2. **最大回撤**：max((peak - trough) / peak)
3. **VaR(95%)**：percentile(daily_returns, 5) * position_value
4. ** beta **：cov(stock, market) / var(market)

### 第二步：风险等级划分

| 等级 | 波动率 | 最大回撤 | 建议 |
|---|---|---|---|
| 低风险 | < 20% | < 10% | 可满仓 |
| 中风险 | 20%-40% | 10%-25% | 半仓至七成 |
| 高风险 | 40%-60% | 25%-40% | 三成以下 |
| 极高风险 | > 60% | > 40% | 观望或对冲 |

### 第三步：仓位建议公式

```
建议仓位 = min(
    1.0,
    (0.20 / 波动率) * 风险偏好系数
)
```

风险偏好系数：保守=0.5，平衡=0.8，激进=1.2

## 输出格式

分析报告中必须包含：

1. **风险等级**：[低/中/高/极高] + 一句话理由
2. **关键指标**：波动率、最大回撤、VaR、beta
3. **仓位建议**：百分比 + 计算过程
4. **止损位**：基于 ATR 或支撑位
5. **风险提示**：至少 2 条具体风险点（不要泛泛而谈）

## 常见误区

- ❌ 只看 PE/PB 给仓位：忽略波动率
- ❌ 用历史最大回撤做未来预测：需结合波动率
- ❌ 忽略相关性与 beta：单一股票的风险不等于组合风险

## 数据需求

本技能依赖以下 builtin 工具：
- `daily_quotes`：至少 60 个交易日数据
- `daily_indicators`：估值指标作为辅助参考

调用示例（分析师 LLM 自动判断）：
- 拉取 60 日日线 → 计算波动率与回撤 → 划分风险等级 → 给出仓位建议
