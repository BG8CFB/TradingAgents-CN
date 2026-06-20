#!/usr/bin/env python3
"""
Tushare配置管理

从数据库读取 Tushare Token 配置，不从环境变量读取。
"""

import logging
from typing import Dict, Any


class TushareConfig:
    """Tushare配置管理器"""

    def __init__(self):
        self.load_config()

    def load_config(self):
        """从数据库加载Tushare配置"""
        self.token = ""
        self.enabled = False
        self.default_source = "akshare"
        self.cache_enabled = True
        self.cache_ttl_hours = "24"

        from app.core.error_handling import safe_execute

        token = safe_execute(
            _load_tushare_token,
            default="",
            context="tushare_config.load_config",
            log_level=logging.WARNING,
        )
        if token:
            self.token = token
            self.enabled = True

        self._debug_config()

    def _debug_config(self):
        """输出调试配置信息"""
        import logging
        _logger = logging.getLogger("tradingagents.tushare_config")
        _logger.debug(f"Tushare配置: token={'已设置' if self.token else '未设置'} ({len(self.token)}字符), "
                      f"enabled={self.enabled}, source={self.default_source}, cache={self.cache_enabled}")

    def is_valid(self) -> bool:
        """检查配置是否有效"""
        if not self.enabled:
            return False
        if not self.token:
            return False
        if len(self.token) < 30:
            return False
        return True

    def get_validation_result(self) -> Dict[str, Any]:
        """获取详细的验证结果"""
        result = {
            'valid': False,
            'enabled': self.enabled,
            'token_set': bool(self.token),
            'token_length': len(self.token),
            'issues': [],
            'suggestions': []
        }

        if not self.enabled:
            result['issues'].append("Tushare 未启用")
            result['suggestions'].append("在 Web UI 配置管理中添加 Tushare Token")

        if not self.token:
            result['issues'].append("Tushare Token 未配置")
            result['suggestions'].append("在 Web UI 配置管理中添加 Tushare Token")
        elif len(self.token) < 30:
            result['issues'].append("Tushare Token 格式可能不正确")
            result['suggestions'].append("检查 Token 是否完整（通常为40字符）")

        if not result['issues']:
            result['valid'] = True

        return result


def get_tushare_config() -> TushareConfig:
    """获取Tushare配置实例"""
    return TushareConfig()


def _load_tushare_token() -> str:
    """从 DB 读取 Tushare token。失败由 safe_execute 统一捕获并降级为 WARNING。"""
    from app.utils.ds_key_utils import get_datasource_api_key

    return get_datasource_api_key("tushare") or ""
