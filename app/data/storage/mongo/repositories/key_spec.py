"""域主键注册表 — 各业务域 upsert filter 的唯一事实源。

与 app/data/storage/mongo/index_definitions.py 的唯一索引定义保持一致
（tests/data/test_index_definitions.py 之外，这里再提供运行时查询入口）：

- Repo upsert filter 一律从本模块取键，禁止各处手写 filter 字段列表
- 单版本覆盖语义：键不含 data_source，备用源覆盖同自然键记录
"""

from typing import Dict, List

from app.data.storage.mongo.index_definitions import INDEX_DEFINITIONS


def get_domain_key(domain: str) -> List[str]:
    """返回指定业务域的唯一键字段列表（即 upsert filter 键）。"""
    for fields, unique in INDEX_DEFINITIONS[domain]:
        if unique:
            return [k for k, _ in fields]
    raise KeyError(f"domain {domain} 未定义唯一键")


def get_domain_keys() -> Dict[str, List[str]]:
    """返回全部域的唯一键映射（含元数据域）。"""
    result: Dict[str, List[str]] = {}
    for domain, specs in INDEX_DEFINITIONS.items():
        for fields, unique in specs:
            if unique:
                result[domain] = [k for k, _ in fields]
                break
    return result


def build_filter(domain: str, record: dict) -> dict:
    """按域唯一键从记录构造 upsert filter。

    Args:
        domain: 数据域。
        record: 标准化后的业务记录。

    Raises:
        KeyError: 记录缺少唯一键字段时抛出（由调用方决定跳过或报错）。
    """
    filter_doc = {}
    for field in get_domain_key(domain):
        value = record.get(field)
        if value is None:
            raise KeyError(f"{domain} 记录缺少唯一键字段 {field}")
        filter_doc[field] = value
    return filter_doc
