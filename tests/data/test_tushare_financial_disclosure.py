"""Real transformation tests: disclosure dates and statement scope, no network."""

import pandas as pd
import pytest

from app.data.sources.cn.tushare.adapter import TushareCNAdapter
from app.data.sources.cn.tushare.api.financial import (
    _INCOME_PERIOD_FIELDS,
    _merge_period_financials,
    _standardize,
)


def _indicator(**changes):
    row = dict(ts_code="000001.SZ", end_date="20260630", ann_date="20260820", roe=15)
    row.update(changes)
    return row


def _income(**changes):
    row = dict(ts_code="000001.SZ", end_date="20260630", ann_date="20260825",
               f_ann_date="20261005", report_type="1", total_revenue=100,
               revenue=100, n_income=20, n_income_attr_p=18)
    row.update(changes)
    return row


def _adapt(incomes, indicators=None):
    merged = _merge_period_financials(
        pd.DataFrame(indicators if indicators is not None else [_indicator()]),
        pd.DataFrame(incomes), "20260630",
    )
    return TushareCNAdapter().adapt_financial_data(merged)[0]


def test_batch_requests_income_disclosure_and_scope():
    assert {"ann_date", "f_ann_date", "report_type", "end_date"} <= set(
        _INCOME_PERIOD_FIELDS.split(",")
    )


def test_batch_late_income_correction_does_not_inherit_indicator_date():
    got = _adapt([_income()])
    assert got.announce_date == "2026-10-05"
    assert got.report_type == "1"
    assert got.net_profit == 20
    assert got.roe == 15
    assert got.source_disclosures["indicator"]["announce_date"] == "20260820"
    assert got.source_disclosures["income"]["actual_announce_date"] == "20261005"
    assert got.to_db_doc()["source_disclosures"] == got.source_disclosures


@pytest.mark.parametrize("changes", [
    {"ann_date": None, "f_ann_date": None},
    {"f_ann_date": "invalid"},
    {"f_ann_date": "20260230"},
    {"ann_date": "20260601", "f_ann_date": None},
    {"report_type": None},
    {"end_date": "20260331"},
    {"ts_code": "000002.SZ"},
])
def test_unproven_income_does_not_borrow_indicator_metadata(changes):
    got = _adapt([_income(**changes)])
    assert got.net_profit is None
    assert got.revenue is None
    assert got.roe == 15
    assert got.announce_date == "2026-08-20"
    assert got.report_type is None
    assert got.source_disclosures["income"]["included"] is False


def test_ambiguous_statement_scopes_are_not_selected_by_row_order():
    rows = [_income(report_type="1"), _income(report_type="2", n_income=999)]
    for ordered in (rows, rows[::-1]):
        got = _adapt(ordered)
        assert got.net_profit is None
        assert got.report_type is None


def test_same_scope_revision_uses_latest_actual_date_not_first_row():
    early = _income(f_ann_date="20260825", n_income=10)
    later = _income(f_ann_date="20261005", n_income=25)
    for rows in ([early, later], [later, early]):
        got = _adapt(rows)
        assert got.net_profit == 25
        assert got.announce_date == "2026-10-05"


def test_undated_indicator_cannot_be_certified_by_dated_income():
    indicator = _indicator()
    indicator["ann_date"] = None
    got = _adapt([_income()], [indicator])
    assert got.announce_date is None
    assert got.net_profit is None


def test_missing_income_keeps_indicator_only():
    got = _adapt([])
    assert got.announce_date == "2026-08-20"
    assert got.net_profit is None
    assert got.roe == 15


def test_integer_date_columns_and_zero_profit_survive_real_adapter():
    income = _income(ann_date=20260825.0, f_ann_date=20261005.0,
                     end_date=20260630.0, report_type=1.0, n_income=0)
    got = _adapt([income])
    assert got.announce_date == "2026-10-05"
    assert got.net_profit == 0
    assert got.report_type == "1"


def test_single_symbol_tables_only_join_same_period_and_statement_scope():
    got = _standardize({
        "income_statement": [_income()],
        "balance_sheet": [_income(end_date="20260331", total_assets=999)],
        "cashflow_statement": [_income(report_type="2", n_cashflow_act=999)],
        "financial_indicators": [_indicator()],
    }, "000001.SZ")
    assert got["report_period"] == "20260630"
    assert got["ann_date"] == "20261005"
    assert got["report_type"] == "1"
    assert got["total_assets"] is None
    assert got["n_cashflow_act"] is None
    assert got["roe"] == 15


def test_single_symbol_missing_disclosure_excludes_that_table_values():
    got = _standardize({
        "income_statement": [_income(ann_date=None, f_ann_date=None)],
        "balance_sheet": [_income(total_assets=200)],
        "financial_indicators": [_indicator()],
    }, "000001.SZ")
    assert got["net_profit"] is None
    assert got["net_profit_ttm"] is None
    assert got["total_assets"] == 200
    assert got["ann_date"] == "20261005"


def test_ttm_correction_date_participates_in_aggregate_bound():
    got = _standardize({"income_statement": [
        _income(f_ann_date="20260825", revenue=100),
        _income(end_date="20251231", ann_date="20260420",
                f_ann_date="20261007", revenue=150),
        _income(end_date="20250630", ann_date="20250820",
                f_ann_date="20250820", revenue=80),
    ]}, "000001.SZ")
    assert got["revenue_ttm"] == 170
    assert got["ann_date"] == "20261007"
    assert len(got["source_disclosures"]["ttm_income"]) == 3


def test_single_symbol_does_not_mix_ttm_statement_scope():
    got = _standardize({"income_statement": [
        _income(),
        _income(end_date="20251231", ann_date="20260420",
                f_ann_date="20260420", report_type="2", revenue=150),
        _income(end_date="20250630", ann_date="20250820",
                f_ann_date="20250820", revenue=80),
    ]}, "000001.SZ")
    assert got["revenue_ttm"] is None
