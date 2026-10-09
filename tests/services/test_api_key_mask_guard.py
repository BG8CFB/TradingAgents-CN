"""数据源 API Key 的脱敏回显防护守卫。

前端展示的是脱敏形态（前 6 位 + "..." + 后 6 位）。若保存时把该回显值当真值落库，
真实密钥会被掩码覆盖 → 该数据源此后所有取数失败（实测发生过：Tushare 令牌被写成
15 字符掩码，导致财务/资金流/两融等全部 `token 不对`）。
"""

from __future__ import annotations

from app.routers.config.data_sources import _truncate_api_key, resolve_submitted_api_key

FULL_KEY = "dde8ac7d39990edfd9cf39f022e5723fefffbfc738ec090bf59cc3c3"
MASKED = "dde8ac...9cc3c3"  # 真实掩码 = 前6位 + "..." + 后6位


def test_mask_format_matches_frontend_display():
    assert _truncate_api_key(FULL_KEY) == MASKED
    assert len(MASKED) == 15


class TestResolveSubmittedApiKey:
    def test_unchanged_mask_keeps_stored_full_key(self):
        """掩码与现值一致 = 用户没改过 → 必须保留库内完整密钥，绝不能写回掩码。"""
        value, error = resolve_submitted_api_key(MASKED, FULL_KEY)
        assert error is None
        assert value == FULL_KEY

    def test_mismatched_mask_is_rejected(self):
        """掩码对不上现值 → 拒收（否则真实密钥被覆盖）。"""
        value, error = resolve_submitted_api_key("aaaaaa...bbbbbb", FULL_KEY)
        assert error and "脱敏" in error
        assert value == FULL_KEY, "拒收时不得改动已有密钥"

    def test_mask_without_stored_key_is_rejected(self):
        """新增数据源时提交掩码 → 没有现值可比对，一律拒收。"""
        value, error = resolve_submitted_api_key(MASKED, None)
        assert error is not None
        assert value == ""

    def test_full_key_is_saved_as_is(self):
        _, error = resolve_submitted_api_key(FULL_KEY, None)
        new_key = "0123456789abcdef0123456789abcdef0123456789abcdef01234567"
        value, err2 = resolve_submitted_api_key(new_key, FULL_KEY)
        assert error is None and err2 is None
        assert value == new_key

    def test_placeholder_values_are_not_treated_as_masks(self):
        """占位符/自定义本地模型 key 不能被误判成掩码（否则会拒掉正常保存）。"""
        for candidate in ("your-openai-api-key", "local-model", "", "sk-abc.def.ghi"):
            value, error = resolve_submitted_api_key(candidate, FULL_KEY)
            assert error is None, candidate
            assert value == candidate

    def test_none_keeps_current(self):
        value, error = resolve_submitted_api_key(None, FULL_KEY)
        assert error is None and value == FULL_KEY

    def test_none_without_current_is_empty(self):
        value, error = resolve_submitted_api_key(None, None)
        assert error is None and value == ""
