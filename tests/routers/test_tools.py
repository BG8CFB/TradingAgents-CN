"""
工具清单 API 测试

测试 /api/tools/available 端点与辅助函数。
直接调用真实的数据结构和函数，不使用 patch/MagicMock。
"""

import pytest


class TestToolsAPI:
    """测试工具清单 API 结构和数据"""

    def test_disabled_tools_file_handling(self):
        """验证禁用工具文件读取"""
        from app.routers.tools import _get_disabled_tools

        disabled = _get_disabled_tools()
        assert isinstance(disabled, set)

    def test_router_has_correct_prefix_and_tags(self):
        """验证路由前缀和标签"""
        from app.routers.tools import router

        assert router.prefix == "/api/tools"
        assert router.tags is not None


class TestToolsEndpoints:
    """测试工具 API 端点定义"""

    @pytest.mark.asyncio
    async def test_list_available_tools_endpoint(self):
        """测试 GET /api/tools/available 端点定义"""
        from app.routers.tools import router

        routes = [r.path for r in router.routes]
        assert "/api/tools/available" in routes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
