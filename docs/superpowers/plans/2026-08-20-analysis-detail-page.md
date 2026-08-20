# 分析任务详情页实现计划

日期：2026-08-20
规格文档：`docs/superpowers/specs/2026-08-20-analysis-detail-page-design.md`

## Goal

新增分析任务详情页 `/analysis/tasks/:taskId`（Claude Code 式单一纵向实时事件流 + 报告 tab），新增批量分析聚合页 `/analysis/batches/:batchId`，`/analysis/single` 瘦身为纯提交表单。后端仅两处最小改动：events 接口扩展 `order=desc` + `before_seq` 分页、新增 overview 聚合接口。

## Architecture

- **后端（最小化）**：
  - `GET /api/analysis/tasks/{id}/events`（`app/routers/analysis.py:964-998`）增加 `order` / `before_seq` 查询参数，向后兼容（默认升序行为不变）
  - 新增 `GET /api/analysis/tasks/{id}/overview`：任务参数 + 股票基础信息（走 `DataInterface.get_instance()`，router 不直连 MongoDB `app.data.sources`，import-linter 强制）
  - 事件流基建（`app/llm/events.py` EventSink、WS `/api/analysis/ws/task/{id}`、`app/services/analysis_events.py`）全部复用不改
- **前端（主要工作量）**：
  - `frontend/src/api/analysis.ts` 增类型与方法
  - 新页面 `frontend/src/views/Analysis/TaskDetail.vue` + 子组件 `frontend/src/components/Analysis/TaskDetailSidebar.vue`
  - `frontend/src/components/Analysis/ProcessPanel.vue` 从"按 agent 分 tab"改造为单一纵向事件流（agent 折叠段落）
  - `frontend/src/stores/analysisProcess.ts` 增强：desc 首拉/向前翻页、live+回放续接、text_delta
  - `SingleAnalysis.vue` 瘦身；新页面 `frontend/src/views/Analysis/BatchDetail.vue`
  - 路由注册 `frontend/src/router/index.ts`（/analysis children，54-78 行模式）

## Tech Stack

- 后端：FastAPI + Motor(MongoDB)，Python 3.12，conda env `tradingagents`
- 前端：Vue 3 `<script setup>` + Element Plus + Pinia + Vite，markdown 渲染走 `renderMarkdown`（DOMPurify 消毒，`frontend/src/utils/markdown.ts:36`）

## 硬性约束（每个任务都必须遵守）

1. **智能体中文显示名禁止前端硬编码**：一律来自 `report_titles`（后端 `app/routers/analysis.py:495-503` 注入 result）或 `loadAgentDisplayNames()`（`frontend/src/utils/agentDisplayNames.ts:27`）。ProcessPanel 现有 `agentLabels`（来自 `agent_start` 事件 `payload.name`，`stores/analysisProcess.ts:100-101`）也合规。
2. **测试全真 I/O，禁止任何 mock**（无 unittest.mock / pytest-mock / patch）。integration 测试连容器 MongoDB：`docker compose -f docker-compose.dev.yml up -d mongodb redis` 先起。
3. **pytest 在宿主机 conda env 跑**：`conda activate tradingagents`。全量跑需前缀 `DOCKER_CONTAINER=true`（见项目 memory：单文件可先试不带，环境相关失败再补）。
4. **不要设置 PYTHONIOENCODING**（宿主机 GBK 解码假失败，见 memory）。
5. **前端组件用 Element Plus**，状态完整（loading/error/empty/disabled），响应式不溢出。
6. 新后端接口挂在已有 `router = APIRouter(prefix="/api/analysis", tags=["Analysis"])`（`app/routers/analysis.py:21`），无需新增 tags。
7. `symbol`（非 `code`）、`data_source`（非 `source`）命名。
8. markdown 渲染必须走 `renderMarkdown`，禁止 `v-html` 直插未消毒内容。

---

**REQUIRED SUB-SKILL: superpowers:subagent-driven-development**
执行本计划前先阅读该 skill。每个 Task 由独立 subagent 执行，主 agent 负责审查与集成。也可以用 superpowers:executing-plans 串行执行。步骤完成即勾选 `- [ ]` → `- [x]`。

---

## Task 1: 后端 events 接口扩展（order=desc + before_seq，TDD）

### Files

- **Create**: `tests/integration/test_analysis_events_paging.py`
- **Modify**: `app/services/analysis_events.py`（`load_events`，130-153 行）
- **Modify**: `app/routers/analysis.py`（`get_task_events`，964-998 行）

### 背景（真实代码现状）

`load_events`（`app/services/analysis_events.py:130-153`）当前只支持升序：

```python
async def load_events(
    task_id: str,
    *,
    agent_key: Optional[str] = None,
    event_type: Optional[str] = None,
    after_seq: int = 0,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"task_id": task_id, "seq": {"$gt": after_seq}}
    ...
    cursor = db[EVENTS_COLLECTION].find(query).sort("seq", 1).limit(max(1, min(limit, 5000)))
```

路由层（`app/routers/analysis.py:964-998`）直接透传 `after_seq`/`limit`，无 `order`/`before_seq`。

### 步骤

- [x] 1.1 写失败测试。新建 `tests/integration/test_analysis_events_paging.py`，完全参照 `tests/integration/test_analysis_events.py` 的模式（`_mk_event` 构造真实事件 → `persist_events` 落库 → 断言 → `delete_many` 清理；`_real_mongo` autouse fixture 每用例 `init_database()`/`close_database()`；`@pytest.mark.requires_db`）：

```python
"""load_events desc/before_seq 分页集成测试（真实 MongoDB，无 mock）"""
import uuid
import pytest
from app.services.analysis_events import EVENTS_COLLECTION, load_events, persist_events


def _mk_event(task_id: str, seq: int):
    return {"task_id": task_id, "seq": seq, "ts": 1700000000.0 + seq,
            "phase": "analysts", "agent_key": "Market Analyst",
            "event_type": "tool_call", "payload": {"n": seq}}


@pytest.fixture(autouse=True)
async def _real_mongo(mongodb_available):
    import app.core.database as db_mod
    from app.core.database import close_database, init_database
    await init_database()
    yield
    await close_database()
    db_mod.mongo_db = None
    db_mod.mongo_client = None


@pytest.mark.requires_db
class TestLoadEventsPaging:
    async def test_desc_returns_latest_first(self):
        from app.core.database import get_mongo_db
        task_id = f"evt-pg-{uuid.uuid4().hex[:8]}"
        await persist_events([_mk_event(task_id, i) for i in range(1, 8)])  # seq 1..7
        try:
            page = await load_events(task_id, order="desc", limit=3)
            assert [e["seq"] for e in page] == [7, 6, 5]
        finally:
            await get_mongo_db()[EVENTS_COLLECTION].delete_many({"task_id": task_id})

    async def test_before_seq_pages_backwards(self):
        # desc + before_seq=5 → 取 seq<5 的最近 3 条：[4, 3, 2]
        ...

    async def test_default_unchanged(self):
        # 不传 order/before_seq → 行为与现状一致（升序、after_seq 语义不变）
        ...
```

  补全 `test_before_seq_pages_backwards` 与 `test_default_unchanged` 的完整断言（插入 seq 1..7，`load_events(task_id, order="desc", before_seq=5, limit=3)` 期望 `[4, 3, 2]`；`load_events(task_id, after_seq=2)` 期望 `[3,4,5,6,7]`）。

- [x] 1.2 跑测试确认失败（TypeError: unexpected keyword `order`）：

```bash
docker compose -f docker-compose.dev.yml up -d mongodb redis
conda activate tradingagents
python -m pytest tests/integration/test_analysis_events_paging.py -q
# 期望：3 failed（load_events 不认识 order/before_seq）
```

- [x] 1.3 实现 `load_events` 扩展（`app/services/analysis_events.py:130`）：

```python
async def load_events(
    task_id: str,
    *,
    agent_key: Optional[str] = None,
    event_type: Optional[str] = None,
    after_seq: int = 0,
    before_seq: Optional[int] = None,
    order: str = "asc",  # "asc" | "desc"
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """读取任务事件（回放）。

    - asc（默认，向后兼容）：seq > after_seq 升序
    - desc：seq 降序，取"最近 limit 条"；before_seq 给定时取 seq < before_seq 的一段（向前翻页）
    """
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    if order == "desc":
        seq_cond: Dict[str, Any] = ({"$lt": before_seq} if before_seq is not None
                                    else {"$gt": -1})
        query: Dict[str, Any] = {"task_id": task_id, "seq": seq_cond}
        sort_dir = -1
    else:
        query = {"task_id": task_id, "seq": {"$gt": after_seq}}
        sort_dir = 1
    if agent_key:
        query["agent_key"] = agent_key
    if event_type:
        query["event_type"] = event_type

    cursor = db[EVENTS_COLLECTION].find(query).sort("seq", sort_dir).limit(max(1, min(limit, 5000)))
    out: List[Dict[str, Any]] = []
    async for doc in cursor:
        doc.pop("_id", None)
        out.append(doc)
    return out
```

- [x] 1.4 扩展路由参数（`app/routers/analysis.py:964-998`）：

```python
@router.get("/tasks/{task_id}/events")
async def get_task_events(
    task_id: str,
    agent_key: Optional[str] = None,
    event_type: Optional[str] = None,
    after_seq: int = 0,
    before_seq: Optional[int] = None,
    order: str = "asc",  # asc | desc
    limit: int = 500,
    user: dict = Depends(get_current_user),
):
```

  `load_events(...)` 调用处（991-997 行）透传 `before_seq=before_seq, order=order`。对 `order` 做白名单校验：非 `asc`/`desc` 时返回 400（`raise HTTPException(status_code=400, detail="order 仅支持 asc/desc")`）。权限校验逻辑（980-989 行）不动。

- [x] 1.5 跑通过 + 回归既有测试：

```bash
python -m pytest tests/integration/test_analysis_events_paging.py tests/integration/test_analysis_events.py -q
# 期望：全部 passed（含既有 4 个用例，证明向后兼容）
ruff check app/services/analysis_events.py app/routers/analysis.py
# 期望：All checks passed
```

- [x] 1.6 Commit: `✨ feat(api): events 接口支持 order=desc 与 before_seq 向前分页（详情页最近500条）`

## Task 2: 后端 overview 聚合接口（TDD）

### Files

- **Create**: `tests/integration/test_task_overview_api.py`
- **Modify**: `app/routers/analysis.py`（在 `get_task_events` 之后、`get_task_details`（1001 行）之前插入新端点）

### 设计

`GET /api/analysis/tasks/{task_id}/overview` 返回：

```json
{
  "success": true,
  "data": {
    "task": { "task_id", "status", "symbol", "market_type", "parameters", "created_at", "started_at", "completed_at" },
    "stock_info": { "symbol", "name", "market", "industry", "latest_price" }
  }
}
```

- task 部分复用 `get_analysis_service().get_task_with_status_fallback(task_id, user_id)`（与 `get_task_status_new` 89-124 行相同的权限与回退语义：管理员任意、普通用户仅自己）
- stock_info 走 `DataInterface.get_instance()`（`app/data/core/interface.py:38` 单例，`read` 56-89 行）：`basic_info` 域取名称/行业，`daily_quotes` 域用 `read_latest`（91-99 行）取最新价。市场映射复用 `analysis_service.py:1323` 的 `_market_map = {"A股": "CN", "港股": "HK", "美股": "US"}` 模式。查询失败/无数据时 `stock_info` 返回 `None`，不 5xx（详情页左侧栏降级显示占位）。

### 步骤

- [x] 2.1 写失败测试 `tests/integration/test_task_overview_api.py`。参照 `tests/features/test_analysis_tasks.py` 的 `authed_client`（`tests/conftest.py:324-336`，dependency_overrides + Bearer token）用法 + `test_analysis_events.py` 的真实 Mongo fixture。真实创建任务：

```python
@pytest.mark.requires_db
class TestTaskOverview:
    async def test_overview_returns_task_and_optional_stock(self, authed_client):
        # 真实建任务（无 mock）：走 create_analysis_task 真实 I/O
        from app.services.analysis_service import get_analysis_service
        from app.models.analysis import SingleAnalysisRequest
        svc = get_analysis_service()
        created = await svc.create_analysis_task(
            authed_client.headers["Authorization"].split("Bearer ")[1] and TEST_USER_ID,
            SingleAnalysisRequest(symbol="000001", parameters={"market_type": "A股"}),
        )
        task_id = created["task_id"]
        try:
            resp = await authed_client.get(f"/api/analysis/tasks/{task_id}/overview")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["task"]["task_id"] == task_id
            assert data["task"]["symbol"] in ("000001",)
            assert "stock_info" in data  # 可能为 None（测试库无 basic_info 时不失败）
        finally:
            await svc.delete_task_by_id(task_id, user_id=TEST_USER_ID)

    async def test_overview_404_for_other_user(self, user_client):
        # 普通用户查不存在的任务 → 404（权限语义与 /status 一致）
        resp = await user_client.get("/api/analysis/tasks/nonexistent/overview")
        assert resp.status_code == 404
```

  注：`TEST_USER_ID` 从 `admin_user_data` fixture 取（写测试时先读 `tests/conftest.py` 对应 fixture 确认真实字段名，以实际为准，禁止臆造）。若测试库中恰好有 000001 的 basic_info（CN 集合），可加断言 `stock_info["symbol"] == "000001"`；否则只断结构。

- [x] 2.2 跑失败：

```bash
python -m pytest tests/integration/test_task_overview_api.py -q
# 期望：404 failed（端点不存在）
```

- [x] 2.3 实现端点（插入 `app/routers/analysis.py` 约 999 行处）：

```python
@router.get("/tasks/{task_id}/overview")
async def get_task_overview(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    """任务详情页聚合入口：任务参数 + 股票基础信息（一次请求）。

    股票信息走 DataInterface（消费层不直连 sources/storage）。
    """
    from app.services.analysis_service import get_analysis_service

    user_id = None if user.get("is_admin") else user["id"]
    task = await get_analysis_service().get_task_with_status_fallback(task_id, user_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")

    stock_info = None
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()
        symbol = task.get("symbol") or task.get("stock_code")
        market_map = {"A股": "CN", "港股": "HK", "美股": "US"}
        market = market_map.get(task.get("market_type") or "")
        if symbol and market:
            info = await di.read(market, "basic_info", symbol)
            records = info.get("data") or []
            latest = await di.read_latest(market, "daily_quotes", symbol,
                                          projection={"close": 1, "trade_date": 1})
            base = records[0] if records else {}
            stock_info = {
                "symbol": symbol,
                "name": base.get("name"),
                "market": market,
                "industry": base.get("industry"),
                "latest_price": (latest or {}).get("close"),
            }
    except Exception as e:  # noqa: BLE001 - 股票信息缺失不阻断详情页
        logger.warning(f"⚠️ [OVERVIEW] 读取股票信息失败 task={task_id}: {e}")

    return {
        "success": True,
        "data": {
            "task": {
                "task_id": task.get("task_id", task_id),
                "status": task.get("status"),
                "symbol": task.get("symbol") or task.get("stock_code"),
                "market_type": task.get("market_type"),
                "parameters": task.get("parameters") or {},
                "created_at": task.get("created_at"),
                "started_at": task.get("started_at"),
                "completed_at": task.get("completed_at"),
            },
            "stock_info": stock_info,
        },
    }
```

  注：`task` dict 的真实字段以 `get_task_with_status_fallback` 实际返回为准——实现前先读该方法确认字段名（`app/services/analysis_service.py` 内），若字段名不同按真实值调整，结构不变。

- [x] 2.4 跑通过 + 架构契约：

```bash
python -m pytest tests/integration/test_task_overview_api.py -q
ruff check app/routers/analysis.py
lint-imports   # router 不得 import app.data.storage/sources（本实现 import 的是 core.interface，合规）
python -m pytest tests/lint/ -q   # 路由约定 lint
# 期望：全 passed / no contracts violated
```

- [x] 2.5 Commit: `✨ feat(api): 新增任务 overview 聚合接口（任务参数+股票基础信息，走 DataInterface）`

## Task 3: 前端 api/analysis.ts 增加类型与方法

### Files

- **Modify**: `frontend/src/api/analysis.ts`（`AgentEvent` 111-128 行附近加类型；`analysisApi` 内 241 行 `getTaskEvents` 后加方法）

### 步骤

- [x] 3.1 在 `AgentEvent`（111-128 行）的 `event_type` 联合中确认已含所需类型，并新增 `text_delta`（联合类型已用 `| string` 兜底，显式加 `'text_delta'` 以便类型提示）。新增 overview 响应类型：

```ts
/** 任务详情页聚合信息（GET /tasks/{id}/overview） */
export interface TaskOverview {
  task: {
    task_id: string
    status: string
    symbol?: string
    market_type?: string
    parameters?: Record<string, unknown>
    created_at?: string
    started_at?: string
    completed_at?: string
  }
  stock_info: {
    symbol: string
    name?: string
    market?: string
    industry?: string
    latest_price?: number
  } | null
}
```

- [x] 3.2 扩展 `getTaskEvents`（233-241 行）参数并新增方法：

```ts
getTaskEvents(taskId: string, params?: {
  agent_key?: string
  event_type?: string
  after_seq?: number
  before_seq?: number
  order?: 'asc' | 'desc'
  limit?: number
}): Promise<ApiResponse<AgentEvent[]>> {
  return request.get(`/api/analysis/tasks/${taskId}/events`, { params })
},

// 任务详情页聚合信息
getTaskOverview(taskId: string): Promise<ApiResponse<TaskOverview>> {
  return request.get(`/api/analysis/tasks/${taskId}/overview`)
},

// 取消任务
cancelTask(taskId: string): Promise<{ success: boolean; message: string }> {
  return request.post(`/api/analysis/tasks/${taskId}/cancel`, {})
},
```

- [x] 3.3 验证：

```bash
cd frontend && npm run type-check
# 期望：无错误
```

- [x] 3.4 Commit: `📝 feat(front): analysis API 增加 overview/分页 events/cancel 方法与类型`

## Task 4: 路由注册 + 详情页骨架（三区布局 + 状态机）

### Files

- **Modify**: `frontend/src/router/index.ts`（/analysis children，65-78 行后追加）
- **Create**: `frontend/src/views/Analysis/TaskDetail.vue`
- **Create**: `frontend/src/components/Analysis/TaskDetailSidebar.vue`

### 设计

- 路由：`path: 'tasks/:taskId', name: 'AnalysisTaskDetail', component: () => import('@/views/Analysis/TaskDetail.vue')`，挂 `/analysis` 下（与 65-78 行 `single`/`batch` 同级同模式，懒加载）。
- TaskDetail.vue 三区布局：顶栏（返回按钮 + 股票代码/名称 + 状态徽标 + 已耗时 + 右对齐操作组）、左侧栏 280px（TaskDetailSidebar：分析配置卡片 = 智能体 chips + 辩论轮次 + 模型 + 分析日期，来自 overview `task.parameters`；股票信息卡片 = name/market/industry/latest_price 统一 el-descriptions）、主区域（阶段化进度条 + `el-tabs`：实时过程 / 分析报告）。窄屏（<1200px）左侧栏折叠为顶部摘要行。
- 状态机（页面核心 ref `taskStatus`）：`pending/running` → 连事件流（Task 6）+ 轮询 status 兜底；`completed` → 自动切"分析报告" tab；`failed` → el-alert 错误 + 失败 agent 红色标记；`cancelled` → 灰色徽标 + 提示。
- 顶栏操作：running → 取消（`analysisApi.cancelTask`，二次确认 ElMessageBox）；completed → 下载 dropdown（md/docx/pdf/json，Task 7 迁移）；cancelled → "重新发起分析"（`router.push('/analysis/single')`）。
- agent chips 显示名：`loadAgentDisplayNames()`（`agentDisplayNames.ts:27`）映射 `parameters.selected_analysts` slug，禁止硬编码中文。

### 步骤

- [x] 4.1 注册路由（`router/index.ts` 73 行 `batch` 之后）：

```ts
{
  path: 'tasks/:taskId',
  name: 'AnalysisTaskDetail',
  component: () => import('@/views/Analysis/TaskDetail.vue'),
},
```

- [x] 4.2 创建 `TaskDetailSidebar.vue`：props `{ overview: TaskOverview | null, loading: boolean }`；两个 el-card；配置项从 `overview.task.parameters`（`selected_analysts`/`debate_rounds` 类字段按真实 parameters 键渲染，用 `loadAgentDisplayNames()` 转中文）；stock_info 为 null 时显示 el-skeleton。emit 无（纯展示）。
- [x] 4.3 创建 `TaskDetail.vue` 骨架（此任务只做布局 + overview 加载 + 状态机 + 轮询，事件流与报告 tab 分别由 Task 6/7 填充）：

```vue
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { analysisApi, type TaskOverview } from '@/api/analysis'

const route = useRoute()
const router = useRouter()
const taskId = route.params.taskId as string

const overview = ref<TaskOverview | null>(null)
const loading = ref(true)
const taskStatus = ref('')
const activeTab = ref('process')  // process | report
let pollTimer: ReturnType<typeof setInterval> | null = null
const startTime = ref<number | null>(null)

const statusTagType = computed(() =>
  ({ completed: 'success', failed: 'danger', cancelled: 'info' } as Record<string, any>)[taskStatus.value] || 'warning')

async function loadOverview() {
  try {
    const res = await analysisApi.getTaskOverview(taskId)
    overview.value = res.data
    taskStatus.value = res.data.task.status ?? ''
  } finally { loading.value = false }
}

async function startPolling() { /* 5s 轮询 getTaskStatus；终态停表并按状态机切 tab/停止 */ }
async function handleCancel() {
  await ElMessageBox.confirm('确定取消该分析任务？', '取消任务', { type: 'warning' })
  const res = await analysisApi.cancelTask(taskId)
  if (res.success) { ElMessage.success('任务已取消'); await loadOverview() }
}

onMounted(async () => {
  await loadOverview()
  if (['pending', 'running'].includes(taskStatus.value)) startPolling()
  if (taskStatus.value === 'completed') activeTab.value = 'report'
})
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })
</script>
```

  模板：`el-page-header`/返回 `router.back()`；`el-container`（`el-aside width="280px"` + `el-main`）；状态徽标 `el-tag :type="statusTagType"`；耗时用 started_at 起算的响应式计时。失败态顶部 `el-alert :title="errorMessage" type="error"`；cancelled 态 `el-alert type="info" title="任务已取消"`。
- [x] 4.4 验证：`npm run type-check && npm run lint`（期望通过）；`npm run dev` 后浏览器打开 `/analysis/tasks/<任一真实任务ID>`（从任务中心取），检查三区布局、窄屏（DevTools 1000px 宽）左栏折叠、四种状态徽标样式（可临时改 taskStatus 验证后还原）。
- [x] 4.5 Commit: `✨ feat(front): 分析任务详情页路由与三区布局骨架（状态机+overview 加载）`

## Task 5: ProcessPanel 改造为单一纵向事件流

### Files

- **Modify**: `frontend/src/components/Analysis/ProcessPanel.vue`（模板 25-119 行 tabs 区重写；`buildTimeline` 234-305 行保留复用；脚本新增段落折叠与滚动控制）
- **Modify**: `frontend/src/stores/analysisProcess.ts`（新增渲染窗口 state，见下）

### 设计（对照现有代码）

- 删除 `el-tabs`（30-119 行），改为单一纵向容器：`v-for="agent in visibleAgents"` 渲染**可折叠段落**。段落头部：`● {label} {完成 ✓ + 耗时 | 运行中 Loading 旋转}`；label 用 `agent.label`（store `agentLabels`，源自 `agent_start` payload.name，合规）。
- 段内时间线复用 `buildTimeline(agent.key)`（234-305 行，工具配对/400 字符截断逻辑不动）。llm_response 气泡改 markdown 渲染：`v-html="renderMarkdown(item.text)"`（`utils/markdown.ts:36`，DOMPurify 消毒）。compact 行格式化为「上下文压缩 {before} → {after} tokens」（payload 字段以 `app/llm/events.py` compact 事件真实字段为准，实现前先读）。
- 折叠策略：当前运行中 agent（`agentStatus[key]==='running'`）自动展开；`agent_end` 后自动折叠为摘要行；用户手动点击可覆盖（本地 `manualExpanded: Record<string, boolean>` 优先级最高）。
- 滚动策略：单一滚动容器 `streamEl`；`watch(events.length)` 时若用户未上滚（`streamEl.scrollTop + clientHeight >= scrollHeight - 60`）则 `nextTick` 后滚底；用户上滚出现悬浮"回到底部"按钮（fixed 在容器右下）。
- 渲染上限：store 新增 `renderWindow = 500`。`events` 全量保存，新增 getter `visibleEvents`（最近 500 条：按 seq 排序后 `slice(-500)`，本地乐观 seq<0 消息保留）。`visibleAgents` 基于 `visibleEvents` 过滤的 agentOrder。容器顶部显示"加载更早事件"按钮（调 Task 6 的 `loadEarlier()`；无更早时隐藏）。
- 底部消息输入框：保留单输入框（不再按 agent 分 tab），目标 agent 用下拉选择当前 running 的 agent（`store.agents.filter(a => a.status==='running')`）；仅 live 且 `store.connected` 时可用。复用 `store.sendAgentMessage`（`analysisProcess.ts:245`）与现有回执处理（ProcessPanel 311-326 行 `sendMessage`）。
- `text_delta`：仅 live 渲染——store 在 live 模式收到 `text_delta` 时累积到 `streamingText[agent_key]`，面板在对应 agent 段落尾部渲染实时气泡；收到该 agent 的 `llm_response` 时清空 `streamingText[agent_key]`。回放模式忽略 `text_delta`（不落库，天然没有）。

### 步骤

- [x] 5.1 store 改造（`analysisProcess.ts`）：新增 `streamingText = ref<Record<string, string>>({})`、`visibleEvents` computed、`hasMoreEarlier = ref(false)`、`loadEarlier()`（Task 6 实现，先留空壳返回）；`handleWSMessage` 的 `agent_event` 分支加 `text_delta` 累积与 `llm_response` 清空。
- [x] 5.2 ProcessPanel 模板重写：单一纵向流 + agent 折叠段落 + 滚动控制 + 回到底部按钮 + 底部输入区。样式沿用现有 `.timeline/.bubble/.tool-item/.compact-bar` 类（457-578 行），新增段落头样式（`.agent-section-head`）。
- [x] 5.3 验证：`npm run type-check && npm run lint`；浏览器验证——发起一次真实分析（或回放已完成任务，`<ProcessPanel replay task-id="..."/>`），检查：agent 段落折叠/展开动画、运行中自动展开、工具行展开参数/结果、markdown 气泡、上滚暂停自动滚底、回到底部按钮、消息输入框禁用态。
- [x] 5.4 Commit: `♻️ refactor(front): ProcessPanel 改造为 Claude Code 式单一纵向事件流（折叠段落+500条窗口+滚动策略）`

## Task 6: 详情页接入事件流（live + 回放续接 + 失败/取消态）

### Files

- **Modify**: `frontend/src/stores/analysisProcess.ts`（`loadReplay` 279-304 行改造；新增 `loadLatestAndConnect()`）
- **Modify**: `frontend/src/views/Analysis/TaskDetail.vue`（process tab 挂 `<ProcessPanel/>`）

### 设计（基于真实 store 代码）

- store 去重已具备：`applyAgentEvent`（90-112 行）按 `seq + agent_key` 去重，WS 与回放混发安全——这是续接的关键，直接复用。
- 新增 `loadLatestAndConnect(id: string)`（详情页 running 主入口）：
  1. `order=desc&limit=500` 首拉最近 500 条（`analysisApi.getTaskEvents(id, { order: 'desc', limit: 500 })`），本地 `reverse()` 为升序后逐条 `applyAgentEvent`；记录 `maxSeq = events.at(-1)?.seq ?? 0`；若返回满 500 条置 `hasMoreEarlier = true`。
  2. `store.start(id)` 连 WS（`start` 216-224 行内部先 `stop()+reset()`——注意顺序：先 `reset()` 会清掉已回放的事件。**实现时把回放填充放在 start() 之后**：`start(id)` 先连 WS（期间 WS 事件正常进入），随后立刻 desc 首拉回填历史，`applyAgentEvent` 去重保证与 WS 增量无缝拼接；若 WS 事件 seq 落在回放窗口内的空洞（首拉与 WS 之间的增量），补一次 `after_seq=maxSeq` 升序拉取即可）。
  3. `loadEarlier()`：`getTaskEvents(id, { order: 'desc', before_seq: 当前 visibleEvents 最小 seq, limit: 500 })`，reverse 后 `applyAgentEvent`；返回不满 500 条时 `hasMoreEarlier = false`。
- **回放循环分页拉全量**（completed/failed/cancelled 或刷新页面时）：改造 `loadReplay`（279-304 行）——现有实现已是 while 循环升序拉全量（`after_seq` 递增），保留该循环作为数据完整性通道（store.events 全量），渲染层由 Task 5 的 `visibleEvents` 只显示最近 500 条；`hasMoreEarlier` 由总数 > 500 决定。
- TaskDetail 集成：`onMounted` 时若 status ∈ {pending, running} → `loadLatestAndConnect(taskId)`；否则 → `loadReplay(taskId)` + `<ProcessPanel replay :task-id="taskId"/>`。轮询发现进入终态：running→completed 时 `store.stop()`（227-242 行）后自动切 report tab；failed 时 `stop()` + 顶部 el-alert 展示 `error_message` + 时间线失败 agent 红色（`agentStatus` 无 failed 概念，用 task 的 error 信息中的 agent 名或最后运行的 agent 标红——以后端 status 返回真实字段为准）；cancelled 定格事件流（`stop()` 不清 events，227 行注释明确保留）。
- WS 断连提示条：store 已有指数退避重连（198-210 行，最多 10 次）+ `connected` ref。TaskDetail 在 `mode==='live' && !connected` 时顶部显示"连接中断，重连中…"提示条，并以 5s 轮询 `getTaskStatus` 兜底进度（Task 4 已建轮询，复用）。

### 步骤

- [x] 6.1 store 实现 `loadLatestAndConnect` / `loadEarlier` / `loadReplay` 改造（含 `hasMoreEarlier` 维护）。
- [x] 6.2 TaskDetail process tab 集成 + 终态联动（completed 自动切 tab、failed/cancelled 呈现）。
- [x] 6.3 验证：`npm run type-check && npm run lint`；浏览器四态验证（spec 验证计划要求）：running（发起新分析跳详情页，观察 live 流 + text_delta + 消息注入）、completed（刷新页面纯回放 + 自动切报告 tab）、failed、cancelled（取消一个运行中任务，事件流定格）。
- [x] 6.4 Commit: `✨ feat(front): 详情页接入事件流（live+回放desc分页续接、text_delta 流式、终态联动）`

## Task 7: 结果报告 tab + 下载迁移 + report_titles 驱动

### Files

- **Create**: `frontend/src/components/Analysis/TaskReportPanel.vue`
- **Modify**: `frontend/src/views/Analysis/TaskDetail.vue`（report tab 挂载 + 顶栏下载按钮）
- **参考迁移源**: `frontend/src/views/Analysis/SingleAnalysis.vue` 结果区 480-709 行、`downloadReport` 1636-1688 行

### 设计

- `TaskReportPanel.vue`：props `{ taskId: string, visible: boolean }`；首次可见时 `analysisApi.getTaskResult(taskId)` 拉取（返回结构见 `app/routers/analysis.py:414-518`：`data.reports`、`data.report_titles`、`data.decision`、`data.structured_summary`）。
- 报告子 tab 标题 = `report_titles[key] ?? key`（后端 `build_report_titles` 注入，`analysis.py:495-503`）——**禁止前端写死中文名**；`report_titles` 缺失时 fallback `loadAgentDisplayNames()` 映射（`agentDisplayNames.ts` 已含 `*_report` 键别名，41-42 行）。
- 报告正文：迁移 SingleAnalysis 480-709 行的决策卡（structured_summary/decision）+ 风险提示 alert + 各报告 markdown 渲染（`renderMarkdown`）；迁移时去掉对 `analysisForm` 的依赖（用 overview.task 数据替代 488 行 `analysisForm.symbol` 兜底链）。
- 下载：迁移 `downloadReport`（1636-1688 行）到 TaskReportPanel/TaskDetail，`reportsApi.download(reportId, format)`（`frontend/src/api/reports.ts:70`），文件名 `${symbol}_分析报告_${date}.${ext}` 逻辑照搬；顶栏下载 dropdown（md/docx/pdf/json）触发同一函数。
- cancelled 且无报告：report tab 显示空态 + "重新发起分析"按钮。

### 步骤

- [x] 7.1 创建 TaskReportPanel（结构迁移 + report_titles 驱动）。
- [x] 7.2 TaskDetail 顶栏下载按钮 + completed 自动切 tab 联动（Task 4/6 状态机已具备，此处补下载调用）。
- [x] 7.3 验证：type-check/lint；浏览器打开一个 completed 任务详情页，检查报告子 tab 中文标题（来自 report_titles）、markdown 正文、决策卡、四种格式下载（pandoc 缺失时的错误提示也要验证）。
- [x] 7.4 Commit: `✨ feat(front): 详情页分析报告 tab（report_titles 驱动标题+决策卡+下载迁移）`

## Task 8: SingleAnalysis.vue 瘦身（提交跳转 + localStorage 用户隔离）

### Files

- **Modify**: `frontend/src/views/Analysis/SingleAnalysis.vue`（`submitAnalysis` 1142-1249 行、缓存函数 1868-1911 行、`restoreTaskFromCache` 1914-1990 行；删除进度卡片/结果区/ProcessPanel 引用）

### 设计

- `submitAnalysis`（1142-1249 行）截断：拿到 `task_id` + `saveTaskToCache` 后直接 `router.push({ name: 'AnalysisTaskDetail', params: { taskId } })`，删除 1209-1242 行的 `analysisProcessStore.start`/`startPollingTaskStatus`/初始查询 timer。失败保留原错误提示。
- localStorage 隔离：`TASK_CACHE_KEY`（1868 行）从固定 `'trading_analysis_task'` 改为 `` `trading_analysis_task:${userId}` ``（`useAuthStore().user?.id`，未登录不写缓存）；`saveTaskToCache`/`getTaskFromCache`/`clearTaskCache`（1878/1885/1902 行）同步改 key 计算。旧 key 数据自然过期（30 分钟 duration 不变），不做迁移。
- 删除：`startPollingTaskStatus`（1252-1362 行）、`restoreTaskFromCache`（1914-1990 行）整体、结果区模板（480-709 行）、`showProcessPanel`/ProcessPanel 引用（376-383、749、789 行）、`downloadReport`（1636-1688 行）及相关仅被它们使用的 state/工具函数。改为 onMounted 时轻量检查当前用户缓存是否有 running 任务 → 仅显示"有进行中任务，点击查看"提示条（链接详情页），不再原地恢复。
- BatchAnalysis.vue 顺带改一行跳转（722 行）：`router.push({ path: '/tasks', query: { batch_id } })` → `router.push({ name: 'AnalysisBatchDetail', params: { batchId: batch_id } })`（Task 9 的路由；本任务先写好跳转，Task 9 前允许 404，或与 Task 9 合并验证）。

### 步骤

- [x] 8.1 改 `submitAnalysis` 为提交即跳转 + 缓存 key 用户隔离。
- [x] 8.2 删除进度/结果/ProcessPanel/下载代码（先全局搜索被删函数引用，确保无残留 import；`analysisProcessStore` 等 import 一并清理）。
- [x] 8.3 验证：type-check/lint（会暴露残留引用）；浏览器：提交一次分析 → 自动跳详情页；同浏览器切换另一账号 → 不出现前一账号任务恢复提示；刷新 `/analysis/single` 只有表单。
- [x] 8.4 Commit: `♻️ refactor(front): SingleAnalysis 瘦身为纯提交表单（提交跳转详情页+缓存按用户隔离）`

## Task 9: 批量详情页 /analysis/batches/:batchId

### Files

- **Modify**: `frontend/src/router/index.ts`（analysis children 追加 `batches/:batchId`）
- **Create**: `frontend/src/views/Analysis/BatchDetail.vue`

### 设计（基于真实批量接口）

- 数据源：`analysisApi.getBatch(batchId)`（`api/analysis.ts:213-216`）→ 后端 `GET /batches/{batch_id}`（`analysis.py:724-729`，QueueService.get_batch，校验 `b.user == user.id`）。批次返回结构以 `QueueService.get_batch` 真实返回为准（实现前先读 `app/services/queue_service.py` 确认 tasks 数组字段名：task_id/status/symbol/进度/结论，禁止臆造）。
- 顶部汇总卡：`el-progress type="circle"`（终态数/总数）+ 状态计数（running/pending/completed/failed el-tag 组）+ "全部下载"按钮（循环对 completed 任务调 `reportsApi.download`，串行下载避免并发爆破）。
- 卡片网格：`el-row/el-col :xs=24 :sm=12 :md=8`；每卡 = symbol+名称（`overview.stock_info.name` 或任务 symbol，名称经 `searchStocks` 不划算——直接显示 symbol + 状态；若 get_batch 已含名称则用真实字段）/ 状态徽标 / completed 显示最终决策 tag（从 `getTaskResult` 的 `decision.action` 或 `structured_summary.final_signal` 拉，惰性：卡片只展示已随批次返回的结论字段，没有则显示"查看详情"引导）/ 耗时；底部两个等宽按钮：`查看详情`（push AnalysisTaskDetail）、`下载报告`（completed 才可用）。
- 轮询：5s `setInterval` 调 `getBatch`；全部任务终态（无 pending/running）→ 停止轮询。onBeforeUnmount 清 timer。深浅路由复用（batchId 变化）时重置轮询。

### 步骤

- [x] 9.1 注册路由 + 创建 BatchDetail.vue（汇总卡 + 网格 + 轮询）。
- [x] 9.2 BatchAnalysis.vue 提交跳转改指本页（若 Task 8 未改，此处改 722 行）。
- [x] 9.3 验证：type-check/lint；浏览器提交一次 2-3 只股票的批量分析 → 跳转批量页，观察卡片随轮询更新状态、全部完成后轮询停止（Network 面板确认无后续 `/batches/` 请求）、卡片按钮跳详情正确、窄屏网格换行正常。
- [x] 9.4 Commit: `✨ feat(front): 批量分析聚合详情页（汇总卡+卡片网格+5s轮询终态停止）`

## Task 10: 全量验证与收尾

### Files

- 无新增（只验证与修补）

### 步骤

- [x] 10.1 后端静态检查与契约：

```bash
conda activate tradingagents
ruff check app/ tests/ scripts/
lint-imports
# 期望：All checks passed / no contracts violated
```

- [x] 10.2 后端测试（容器基础设施先起）：

```bash
docker compose -f docker-compose.dev.yml up -d mongodb redis
python -m pytest tests/ -m "integration and not ai" -q
python -m pytest tests/ -m "not integration and not slow and not ai" -q
# 期望：全 passed（对照 memory 存量失败清单，不引入新失败）
```

  注：若环境相关失败，按 memory 加 `DOCKER_CONTAINER=true` 前缀重跑；不设 PYTHONIOENCODING。
- [x] 10.3 前端：

```bash
cd frontend && npm run type-check && npm run lint && npm run build
# 期望：全部通过
```

- [x] 10.4 浏览器端到端走查（spec 验证计划）：详情页四态（running live/完成回放/failed/cancelled）+ 批量页轮询停止 + 桌面/窄屏视口 + 长文本（超长工具 output、超长报告）不溢出。
- [x] 10.5 回查硬性约束：全局搜索新前端代码无硬编码智能体中文（`grep -rn "分析师\|研究员\|交易员" frontend/src/views/Analysis/ frontend/src/components/Analysis/`，命中处确认来自后端数据或 agentDisplayNames 而非字面量）；无 `v-html` 直插未消毒内容；新代码 `symbol` 命名。
- [x] 10.6 收尾 commit: `✅ test: 分析详情页全量验证通过（ruff/lint-imports/pytest integration/前端 type-check+lint+build）`

---

## 风险与备注

- **Task 6 的 start/reset 顺序**是本计划最易错点：`store.start()`（216-224 行）内部先 `stop()+reset()` 清空 events，回放填充必须放在 start 之后，依赖 `applyAgentEvent` 的 seq 去重（93 行）保证正确性。
- overview 的 task 字段名以 `get_task_with_status_fallback` 真实返回为准（Task 2 实现前先读），计划中的字段清单是目标 shape，不是断言现状。
- `get_batch` 返回结构以 `QueueService.get_batch` 为准（Task 9 前先读），卡片字段按真实数据裁剪。
- events 接口 `limit` 现状 clamp 是 5000（`load_events` 148 行 `min(limit, 5000)`），非 spec 所述 500——前端始终显式传 `limit: 500`，不依赖服务端 clamp。
