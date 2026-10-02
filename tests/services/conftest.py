"""services 层测试共享 fixtures。

real_mongo_db 复用 tests/data/conftest.py 的实现（连接真实 MongoDB 容器 +
双向 reset_client 防 SimulatedMongoDB 泄漏），这里仅做包内导入注册。
"""

from tests.data.conftest import real_mongo_db  # noqa: F401
