"""测试标签服务"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.tags_service import TagsService


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
        doc = {
            "_id": MagicMock(),
            "name": "关注",
            "color": "#FF0000",
            "sort_order": 1,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 6, 1),
        }
        doc["_id"].__str__ = lambda self: "507f1f77bcf86cd799439011"
        result = svc._format_doc(doc)
        assert result["id"] == "507f1f77bcf86cd799439011"
        assert result["name"] == "关注"
        assert result["color"] == "#FF0000"
        assert result["sort_order"] == 1

    def test_default_color(self):
        svc = TagsService()
        doc = {"_id": MagicMock(), "name": "test"}
        doc["_id"].__str__ = lambda self: "abc"
        result = svc._format_doc(doc)
        assert result["color"] == "#409EFF"
        assert result["sort_order"] == 0


class TestCreateTag:
    @pytest.mark.asyncio
    async def test_creates_with_correct_fields(self):
        svc = TagsService()
        mock_db = AsyncMock()
        mock_db.user_tags.insert_one = AsyncMock(return_value=MagicMock(inserted_id="tag-001"))
        mock_db.user_tags.create_index = AsyncMock()
        svc.db = mock_db

        with patch.object(svc, "ensure_indexes", new_callable=AsyncMock):
            result = await svc.create_tag("user-1", "自选", color="#FF0000")

        assert result["name"] == "自选"
        assert result["color"] == "#FF0000"


class TestListTags:
    @pytest.mark.asyncio
    async def test_returns_formatted_list(self):
        svc = TagsService()
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"_id": MagicMock(), "name": "关注", "color": "#FF0000", "sort_order": 0,
             "created_at": datetime(2024, 1, 1), "updated_at": datetime(2024, 1, 1)},
        ])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_db = AsyncMock()
        mock_db.user_tags.find = MagicMock(return_value=mock_cursor)
        mock_db.user_tags.create_index = AsyncMock()
        svc.db = mock_db

        with patch.object(svc, "ensure_indexes", new_callable=AsyncMock):
            result = await svc.list_tags("user-1")

        assert len(result) == 1
        assert result[0]["name"] == "关注"
