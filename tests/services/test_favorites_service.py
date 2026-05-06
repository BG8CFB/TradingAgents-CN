"""测试自选股服务"""

import pytest
from datetime import datetime

from app.services.favorites_service import FavoritesService


class TestIsValidObjectId:
    def test_valid_hex_string(self):
        svc = FavoritesService()
        assert svc._is_valid_object_id("507f1f77bcf86cd799439011") is True

    def test_invalid_string(self):
        svc = FavoritesService()
        assert svc._is_valid_object_id("not-a-valid-id") is False

    def test_empty_string(self):
        svc = FavoritesService()
        assert svc._is_valid_object_id("") is False

    def test_short_hex(self):
        svc = FavoritesService()
        # ObjectId.is_valid 需要恰好24位十六进制字符
        assert svc._is_valid_object_id("507f1f") is False


class TestFormatFavorite:
    def test_basic_formatting(self):
        svc = FavoritesService()
        fav = {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "market": "A股",
            "added_at": datetime(2024, 1, 1, 0, 0, 0),
            "tags": ["银行"],
            "notes": "关注",
        }
        result = svc._format_favorite(fav)
        assert result["stock_code"] == "000001"
        assert result["stock_name"] == "平安银行"
        assert isinstance(result["added_at"], str)

    def test_missing_fields_default(self):
        svc = FavoritesService()
        result = svc._format_favorite({"stock_code": "600519"})
        assert result["stock_code"] == "600519"
        assert result["stock_name"] is None
        assert result["market"] == "A股"
        assert result["tags"] == []
