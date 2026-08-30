"""思考档位配置往返集成测试（真实 MongoDB，无 mock）

覆盖链路：LLMConfigRequest（API 请求模型）→ LLMConfig（落库模型）→
config_service.update_llm_config 写入 system_configs.llm_configs →
get_system_config 回读 → providers.resolve_provider 解析出
thinking_effort / thinking_budget / provider 名（引擎消费管道）。

背景：LLMConfigRequest 此前缺失 thinking_budget 字段（前端表单提交即被
Pydantic extra=ignore 静默丢弃），本测试锁定两个思考字段的往返不回退。
"""

import pytest
from pydantic import ValidationError

from app.models.config import LLMConfig, LLMConfigRequest, SystemConfig
from app.llm.providers import _normalize_llm_configs, resolve_provider
from app.services.config import config_service

TEST_PROVIDER = "zhipu"
TEST_MODEL = "test-glm-5.3-thinking"
TEST_CONFIG_NAME = "thinking-effort-test"


@pytest.fixture(autouse=True)
async def _real_mongo(mongodb_available):
    """真实 MongoDB（tradingagents_test 隔离库）。

    - 每用例重建客户端（motor 绑定事件循环，pytest-asyncio 每用例新循环）
    - 测试库无 system_configs 活跃文档：插入一份空配置作为 update_llm_config
      的前置条件（服务实现依赖已存在的活跃配置）
    - ConfigServiceFacade 子服务缓存 db 引用，跨用例必须重置指向新客户端
    """
    import app.core.database as db_mod
    from app.core.database import close_database, get_mongo_db, init_database

    for svc in (config_service._llm, config_service._system):
        svc.db = None
    await init_database()
    db = get_mongo_db()
    await db.system_configs.delete_many({"config_name": TEST_CONFIG_NAME})
    await config_service.save_system_config(
        SystemConfig(config_name=TEST_CONFIG_NAME, config_type="system")
    )
    yield
    await db.system_configs.delete_many({"config_name": TEST_CONFIG_NAME})
    await close_database()
    db_mod.mongo_db = None
    db_mod.mongo_client = None
    for svc in (config_service._llm, config_service._system):
        svc.db = None


@pytest.mark.requires_db
class TestThinkingConfigRoundTrip:
    async def test_effort_and_budget_persist_and_resolve(self):
        """表单值（档位+预算）落库、回读一致，并解析进引擎 ResolvedProvider"""
        request = LLMConfigRequest(
            provider=TEST_PROVIDER,
            model_name=TEST_MODEL,
            thinking_effort="high",
            thinking_budget=16384,
        )
        llm_config = LLMConfig(**request.model_dump())
        assert llm_config.thinking_effort == "high"
        assert llm_config.thinking_budget == 16384

        assert await config_service.update_llm_config(llm_config), "配置写入必须成功"
        try:
            config = await config_service.get_system_config()
            assert config is not None, "系统配置必须存在"
            stored = next(
                (c for c in config.llm_configs if c.model_name == TEST_MODEL), None
            )
            assert stored is not None, f"模型 {TEST_MODEL} 必须已落库"
            assert stored.thinking_effort == "high"
            assert stored.thinking_budget == 16384

            # 引擎消费管道：白名单字段 → ResolvedProvider 透传（含 provider 名）
            normalized = _normalize_llm_configs(
                [c.model_dump() for c in config.llm_configs]
            )
            resolved = resolve_provider(normalized)
            assert resolved is not None
            assert resolved.model == TEST_MODEL
            assert resolved.thinking_effort == "high"
            assert resolved.thinking_budget == 16384
            assert (resolved.provider or "").lower() == TEST_PROVIDER
        finally:
            assert await config_service.delete_llm_config(TEST_PROVIDER, TEST_MODEL)

    async def test_unset_effort_stays_none(self):
        """未设置（前端提交空串）→ 落库为 None，解析不注入"""
        request = LLMConfigRequest(
            provider=TEST_PROVIDER,
            model_name=TEST_MODEL,
            thinking_effort="",
            thinking_budget="",
        )
        assert request.thinking_effort is None
        assert request.thinking_budget is None

        llm_config = LLMConfig(**request.model_dump())
        assert await config_service.update_llm_config(llm_config)
        try:
            config = await config_service.get_system_config()
            stored = next(
                (c for c in config.llm_configs if c.model_name == TEST_MODEL), None
            )
            assert stored is not None
            assert stored.thinking_effort is None
            assert stored.thinking_budget is None
        finally:
            assert await config_service.delete_llm_config(TEST_PROVIDER, TEST_MODEL)


class TestRequestValidation:
    """API 请求模型边界（纯 Pydantic 校验，无 DB）"""

    def test_invalid_effort_rejected(self):
        with pytest.raises(ValidationError):
            LLMConfigRequest(provider="openai", model_name="x", thinking_effort="ultra")

    def test_budget_lower_bound_enforced(self):
        with pytest.raises(ValidationError):
            LLMConfigRequest(provider="openai", model_name="x", thinking_budget=100)

    def test_empty_strings_tolerated(self):
        req = LLMConfigRequest(
            provider="openai", model_name="x", thinking_effort="", thinking_budget=""
        )
        assert req.thinking_effort is None
        assert req.thinking_budget is None
