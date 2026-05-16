"""
测试标签服务

业务逻辑测试：使用 SimulatedMongoDB 模拟数据
"""

import pytest
from datetime import datetime
from bson import ObjectId

import app.core.database as db_module
from app.services.tags_service import TagsService
from test_infra import SimulatedMongoDB


class TestNormalizeUserId:
    def test_string_passthrough(self):
        svc = TagsService()
        assert svc._normalize_user_id("user123") == "user123"

    def test_int_to_string(self):
        svc = TagsService()
        assert svc._normalize_user_id(123) == "123"


class TestFormatDoc:
    def test_basic_formatting(self):
        svc = TagsService()
        oid = ObjectId()
        doc = {
            "_id": oid,
            "name": "关注",
            "color": "#FF0000",
            "sort_order": 1,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 6, 1),
        }
        result = svc._format_doc(doc)
        assert result["id"] == str(oid)
        assert result["name"] == "关注"
        assert result["color"] == "#FF0000"
        assert result["sort_order"] == 1

    def test_default_color(self):
        svc = TagsService()
        oid = ObjectId()
        doc = {"_id": oid, "name": "test"}
        result = svc._format_doc(doc)
        assert result["color"] == "#409EFF"
        assert result["sort_order"] == 0


class TestCreateTag:
    @pytest.mark.asyncio
    async def test_creates_with_correct_fields(self):
        svc = TagsService()
        sim_db = SimulatedMongoDB()
        svc.db = sim_db

        result = await svc.create_tag("user-1", "自选", color="#FF0000")
        assert result["name"] == "自选"
        assert result["color"] == "#FF0000"


class TestListTags:
    @pytest.mark.asyncio
    async def test_returns_formatted_list(self):
        svc = TagsService()
        oid = ObjectId()
        sim_db = SimulatedMongoDB()
        # 预置数据
        await sim_db.user_tags.insert_one({
            "_id": oid,
            "user_id": "user-1",
            "name": "关注",
            "color": "#FF0000",
            "sort_order": 0,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
        })

        original = db_module.mongo_db
        db_module.mongo_db = sim_db
        try:
            svc.db = sim_db
            result = await svc.list_tags("user-1")
            assert len(result) == 1
            assert result[0]["name"] == "关注"
        finally:
            db_module.mongo_db = original
