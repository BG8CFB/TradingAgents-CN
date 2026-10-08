import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Exercise the production pure presentation functions, without a fake server,
// API interception or mocking Vue/application dependencies.
const source = await readFile(new URL('../src/utils/screeningDaily.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
})
const { parseDailyResponse, dailyEmptyNotice, dailyFreshnessNotice, strategyEmptyText } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

const empty = { trade_date: null, strategies: [] }

test('accepts the API envelope and the legacy direct response shape', () => {
  assert.deepEqual(parseDailyResponse({ success: true, data: empty }), empty)
  assert.deepEqual(parseDailyResponse(empty), empty)
})

test('failed or malformed responses are not reinterpreted as an empty recommendation', () => {
  for (const value of [null, {}, { data: null }, { strategies: {} },
    { strategies: [{ strategy_id: 'example' }] },
    { success: false, data: empty }]) {
    assert.throws(() => parseDailyResponse(value), /推荐接口/)
  }
})

test('missing factors and not-yet-generated recommendations have different guidance', () => {
  const noFactors = dailyEmptyNotice({ ...empty, status: 'no_factor_data' })
  const notGenerated = dailyEmptyNotice({ ...empty, status: 'not_generated' })
  assert.equal(noFactors.title, '暂无可用因子数据')
  assert.equal(notGenerated.title, '推荐尚未生成')
  assert.match(notGenerated.description, /不表示没有股票符合条件/)
})

test('legacy empty data does not claim that generation ran or there were zero matches', () => {
  assert.match(dailyEmptyNotice(empty).description, /无法判断/)
  assert.match(dailyEmptyNotice({ ...empty, status: 'ready' }).description, /无法判断/)
})

test('freshness is based on the backend trading-calendar result, never a browser date guess', () => {
  assert.equal(dailyFreshnessNotice({ ...empty, is_stale: false }), null)
  for (const is_stale of [null, undefined]) {
    assert.equal(dailyFreshnessNotice({ ...empty, is_stale }).title, '数据时效未确认')
  }
  const stale = dailyFreshnessNotice({ ...empty, is_stale: true, expected_trade_date: '2026-10-08' })
  assert.equal(stale.title, '推荐数据已过期')
  assert.match(stale.description, /2026-10-08/)
  assert.match(stale.description, /不能视为当前交易日推荐/)
})

test('only complete strategy input coverage can be described as a true zero-match result', () => {
  const strategy = { strategy_id: 'example', items: [] }
  assert.match(strategyEmptyText(strategy), /数据覆盖情况未知/)
  assert.match(strategyEmptyText({ ...strategy, data_quality: { status: 'unknown' } }), /数据覆盖情况未知/)
  assert.match(strategyEmptyText({ ...strategy, data_quality: { status: 'complete' } }), /没有符合条件的股票/)
  assert.match(strategyEmptyText({ ...strategy, data_quality: { status: 'partial' } }), /不能代表完整股票池/)
  assert.match(strategyEmptyText({ ...strategy, data_quality: { status: 'insufficient' } }), /暂时无法给出可靠/)
})

test('a replaced factor batch needs new recommendations even on the same trading date', () => {
  const changed = dailyFreshnessNotice({
    ...empty, trade_date: '2026-10-08', factor_trade_date: '2026-10-08',
    expected_trade_date: '2026-10-08', is_stale: true, recommendation_needs_refresh: true
  })
  assert.equal(changed.title, '推荐结果待重新生成')
  assert.match(changed.description, /因子批次已变化/)
})

test('a future data date is an anomaly, not a historical result', () => {
  const future = dailyFreshnessNotice({
    ...empty, trade_date: '2028-12-31', expected_trade_date: '2026-10-08', is_stale: true
  })
  assert.equal(future.title, '推荐数据日期异常')
  assert.match(future.description, /晚于已完成交易日/)
})
