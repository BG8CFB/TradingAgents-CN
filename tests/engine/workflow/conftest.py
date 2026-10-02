"""workflow 测试共享夹具。

种子 builtin 升级对齐（与生产 lifespan 的 seeder 语义一致）：种子 JSON 变化后
测试 DB 中的 builtin 条目按 hash 覆盖升级，避免「DB 旧条目 + 新种子代码」错配
（用户自建 builtin=false 条目不受影响）。agents 与 workflows 两个集合都同步——
否则集合一旦非空（如用例插入自定义条目），「空集合→种子降级」路径关闭，
内置条目将查不到。夹具后清缓存，防跨用例串味。
"""

import pytest


@pytest.fixture(autouse=True)
def _sync_workflow_seeds():
    from app.engine.orchestrator.workflow import store
    from app.engine.orchestrator.workflow.loader import clear_workflow_cache
    from app.engine.orchestrator.workflow.seeder import sync_agent_specs, sync_workflow_specs

    sync_agent_specs()
    sync_workflow_specs()
    store.invalidate_store_cache()
    clear_workflow_cache()
    yield
    store.invalidate_store_cache()
    clear_workflow_cache()
