# TradingAgents-CN 前端重构计划：Vue 3 → React 19

## Context

当前前端使用 Vue 3 + Element Plus，约 65 个组件、37,000 行代码、180+ API 端点。因版权合规需求，需**完全重写**为 React。同时移除模拟交易功能，UI 全面重新设计为简约现代风格。

**目标**：全新 React 19 + Ant Design 5 前端，不复用任何 Vue 代码，但功能覆盖不遗漏。

---

## 技术选型

| 类别 | 选择 | 理由 |
|------|------|------|
| 框架 | React 19 + TypeScript 5 | 生态最大、就业市场广 |
| UI 库 | Ant Design 5 | 企业级组件完整、中文生态最佳、与 Element Plus 功能对标 |
| 状态管理 | Zustand 5 | 轻量简洁、最接近 Pinia 体验 |
| 路由 | React Router v7 | 声明式路由、类型安全 |
| 构建 | Vite | 保持不变、快速 |
| 表单 | React Hook Form + Zod | 复杂表单类型安全验证 |
| 图表 | ECharts for React | K线图等金融图表 |
| HTTP | Axios | 拦截器、重试、Token 刷新 |

---

## 项目目录结构

```
frontend-react/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── .env.development
├── .env.production
└── src/
    ├── main.tsx                           # 入口
    ├── App.tsx                            # 根组件（ConfigProvider + RouterProvider）
    │
    ├── router/                            # 路由
    │   ├── index.tsx                      # 路由表 + RouterProvider
    │   ├── guards.tsx                     # 认证守卫
    │   └── routes/                        # 分模块路由定义
    │       ├── auth.routes.ts
    │       ├── analysis.routes.ts
    │       ├── stocks.routes.ts
    │       ├── settings.routes.ts
    │       └── system.routes.ts
    │
    ├── layouts/                           # 布局
    │   ├── AppLayout/                     # 主布局（侧边栏+顶栏+内容区）
    │   │   ├── index.tsx
    │   │   ├── Sidebar.tsx
    │   │   ├── Header.tsx
    │   │   ├── NotificationCenter.tsx
    │   │   └── UserDropdown.tsx
    │   └── AuthLayout/                    # 登录/注册布局
    │       └── index.tsx
    │
    ├── pages/                             # 页面（按功能域分目录）
    │   ├── auth/LoginPage.tsx
    │   ├── dashboard/DashboardPage.tsx
    │   ├── analysis/
    │   │   ├── SingleAnalysisPage.tsx
    │   │   └── BatchAnalysisPage.tsx
    │   ├── tasks/TaskCenterPage.tsx
    │   ├── reports/
    │   │   ├── ReportListPage.tsx
    │   │   ├── ReportDetailPage.tsx
    │   │   └── TokenStatisticsPage.tsx
    │   ├── stocks/StockDetailPage.tsx
    │   ├── screening/ScreeningPage.tsx
    │   ├── favorites/FavoritesPage.tsx
    │   ├── learning/
    │   │   ├── LearningIndexPage.tsx
    │   │   └── ArticlePage.tsx
    │   ├── settings/
    │   │   ├── SettingsPage.tsx
    │   │   ├── ConfigManagementPage.tsx
    │   │   ├── MCPManagementPage.tsx
    │   │   ├── MCPToolsPage.tsx
    │   │   ├── AgentManagementPage.tsx
    │   │   ├── CacheManagementPage.tsx
    │   │   └── UsageStatisticsPage.tsx
    │   ├── system/
    │   │   ├── DatabaseManagementPage.tsx
    │   │   ├── SyncManagementPage.tsx
    │   │   ├── SchedulerPage.tsx
    │   │   ├── OperationLogsPage.tsx
    │   │   └── SystemLogsPage.tsx
    │   └── errors/NotFoundPage.tsx
    │
    ├── features/                          # 功能模块（组件+hooks+schema 聚合）
    │   ├── analysis/
    │   │   ├── components/
    │   │   │   ├── StockCodeInput.tsx
    │   │   │   ├── MarketSelector.tsx
    │   │   │   ├── AnalystTeamSelector.tsx
    │   │   │   ├── DepthSelector.tsx
    │   │   │   ├── AnalysisConfigForm.tsx
    │   │   │   ├── AnalysisProgressBar.tsx
    │   │   │   ├── AnalysisStepTimeline.tsx
    │   │   │   ├── AnalysisResultView.tsx
    │   │   │   ├── BatchStockInput.tsx
    │   │   │   └── TaskStatusBadge.tsx
    │   │   ├── hooks/
    │   │   │   ├── useAnalysisSubmit.ts
    │   │   │   ├── useAnalysisProgress.ts
    │   │   │   └── useTaskList.ts
    │   │   └── schemas/analysis.schema.ts
    │   │
    │   ├── stocks/
    │   │   ├── components/
    │   │   │   ├── StockSearch.tsx
    │   │   │   ├── StockQuoteCard.tsx
    │   │   │   ├── KlineChart.tsx
    │   │   │   ├── FundamentalsTable.tsx
    │   │   │   ├── NewsList.tsx
    │   │   │   └── FavoriteButton.tsx
    │   │   └── hooks/
    │   │       ├── useStockQuote.ts
    │   │       └── useKlineData.ts
    │   │
    │   ├── screening/
    │   │   ├── components/
    │   │   │   ├── FilterPanel.tsx
    │   │   │   ├── ConditionBuilder.tsx
    │   │   │   └── ScreeningResultTable.tsx
    │   │   └── hooks/useScreening.ts
    │   │
    │   ├── config/
    │   │   ├── components/
    │   │   │   ├── ProviderDialog.tsx
    │   │   │   ├── ModelCatalogManager.tsx
    │   │   │   ├── DataSourceConfigDialog.tsx
    │   │   │   ├── MarketCategoryManager.tsx
    │   │   │   ├── SortableDataSourceList.tsx
    │   │   │   ├── ConfigValidator.tsx
    │   │   │   └── ImportExportPanel.tsx
    │   │   └── hooks/
    │   │       ├── useConfig.ts
    │   │       └── useProviders.ts
    │   │
    │   ├── mcp/
    │   │   ├── components/
    │   │   │   ├── ConnectorCard.tsx
    │   │   │   ├── ConnectorForm.tsx
    │   │   │   ├── ToolCard.tsx
    │   │   │   └── ToolCategoryGroup.tsx
    │   │   └── hooks/useMCP.ts
    │   │
    │   ├── scheduler/
    │   │   ├── components/
    │   │   │   ├── JobList.tsx
    │   │   │   ├── JobExecutionHistory.tsx
    │   │   │   └── SchedulerStats.tsx
    │   │   └── hooks/useScheduler.ts
    │   │
    │   └── dashboard/
    │       ├── components/
    │       │   ├── WelcomeSection.tsx
    │       │   ├── QuickActionsCard.tsx
    │       │   ├── RecentAnalysesCard.tsx
    │       │   └── SystemStatusCard.tsx
    │       └── hooks/useDashboardData.ts
    │
    ├── components/                        # 全局共享组件
    │   ├── ui/
    │   │   ├── PageHeader.tsx
    │   │   ├── StatCard.tsx
    │   │   ├── EmptyState.tsx
    │   │   ├── LoadingFallback.tsx
    │   │   ├── ErrorBoundary.tsx
    │   │   └── MarkdownRenderer.tsx
    │   ├── feedback/
    │   │   └── NetworkStatus.tsx
    │   └── charts/
    │       ├── KlineECharts.tsx
    │       ├── PieChart.tsx
    │       └── BarChart.tsx
    │
    ├── services/                          # API 服务层
    │   ├── http/
    │   │   ├── client.ts                  # Axios 实例 + 拦截器
    │   │   ├── types.ts                   # ApiResponse, RequestConfig
    │   │   └── error-handler.ts           # 错误处理、401重试、消息去重
    │   ├── api/                           # API 调用函数（按后端模块对应）
    │   │   ├── auth.ts
    │   │   ├── analysis.ts
    │   │   ├── stocks.ts
    │   │   ├── multi-market.ts
    │   │   ├── config.ts
    │   │   ├── favorites.ts
    │   │   ├── screening.ts
    │   │   ├── scheduler.ts
    │   │   ├── sync.ts
    │   │   ├── mcp.ts
    │   │   ├── tools.ts
    │   │   ├── agents.ts
    │   │   ├── cache.ts
    │   │   ├── usage.ts
    │   │   ├── notifications.ts
    │   │   ├── logs.ts
    │   │   ├── operation-logs.ts
    │   │   ├── database.ts
    │   │   └── templates.ts
    │   └── websocket/
    │       ├── notification-ws.ts
    │       └── reconnect-strategy.ts
    │
    ├── stores/                            # Zustand 状态管理
    │   ├── auth.store.ts
    │   ├── app.store.ts
    │   ├── notification.store.ts
    │   └── mcp.store.ts
    │
    ├── hooks/                             # 全局自定义 Hooks
    │   ├── useAuth.ts
    │   ├── useWebSocket.ts
    │   ├── useSSE.ts
    │   ├── useTheme.ts
    │   └── useApi.ts
    │
    ├── types/                             # TypeScript 类型
    │   ├── auth.types.ts
    │   ├── analysis.types.ts
    │   ├── stocks.types.ts
    │   ├── config.types.ts
    │   ├── mcp.types.ts
    │   ├── scheduler.types.ts
    │   ├── screening.types.ts
    │   ├── favorites.types.ts
    │   ├── reports.types.ts
    │   └── common.types.ts
    │
    ├── utils/                             # 工具函数
    │   ├── market.ts
    │   ├── stock.ts
    │   ├── datetime.ts
    │   ├── format.ts
    │   ├── storage.ts
    │   └── token.ts
    │
    ├── constants/                         # 常量
    │   ├── markets.ts
    │   ├── analysts.ts
    │   └── routes.ts
    │
    └── assets/styles/
        ├── global.css
        ├── variables.css
        └── ant-overrides.css
```

---

## 分层架构

```
Pages（瘦页面，只组合布局和功能模块）
  ↓
Features（按业务域组织的组件 + hooks + schemas）
  ↓
Stores（Zustand 全局状态） + Services（API + WebSocket）
  ↓
Utils + Types + Constants（基础设施，无副作用）
```

**状态管理策略：**
| 数据类别 | 存储方式 |
|---------|---------|
| 全局持久（token、用户、主题） | Zustand + localStorage persist |
| 页面表单 | React Hook Form |
| 服务器缓存 | 组件 state + useApi hook |
| 组件本地（弹窗、分页） | React useState |

---

## UI 设计方向：星海雅金 (Elegant Gold & Steel Blue)

**核心理念**：以您提供的”星海科幻金+钢蓝+暖白”3D参考图作为色彩基调灵感，但**摒弃所有 3D 渲染、发光特效与动态渐变**。回归纯粹、干净的 2D 网页设计（Flat Design）。在保证”高级、大气”的同时，确保作为金融终端的数据清晰度，**严格保留股票界面的标准红绿配色**。

### 色彩系统（已实施 - v2 星海雅金）

```
┌─ 主基调 (暖白底色，优雅不刺眼) ───────────────────────┐
│  背景     #FAF8F5 (暖米白，整体页面背景)               │
│  卡片     #FFFFFF (纯白卡片)                           │
│  侧边栏   #FDFBFA (极微暖白)                           │
│  主文字   #2C2C2C (深炭灰，高对比度)                   │
│  次文字   #6B7280 (中灰，辅助信息)                     │
│  弱化文字 #9CA3AF (浅灰，占位符等)                     │
└──────────────────────────────────────────────────────┘

┌─ 强调色系统 (雅金 + 钢蓝 + 标准红绿) ─────────────────┐
│  主强调金   #C9A96E (雅金 - 按钮/Logo/选中态)          │
│  次强调金   #D4A574 (浅金 - Hover状态)                 │
│  钢蓝链接   #4A7DB8 (钢蓝 - 链接/Info/次要强调)        │
│  浅蓝Hover  #5B8FC4 (浅蓝 - 链接Hover)                 │
│  涨色/成功  #52C41A (标准绿 - 股票上涨)                │
│  跌色/错误  #FF4D4F (标准红 - 股票下跌)                │
│  琥珀警告  #D48806 (警告黄)                            │
└──────────────────────────────────────────────────────┘

┌─ 边框系统 (极淡金线) ─────────────────────────────────┐
│  默认边框 rgba(201, 169, 110, 0.22)                    │
│  Hover边框 rgba(201, 169, 110, 0.45)                   │
└──────────────────────────────────────────────────────┘

┌─ 暗色模式 (Dark Mode) ───────────────────────────────┐
│  背景     #131314 (深墨底)                             │
│  卡片     #1A1A1D (深卡片)                             │
│  浮层     #222225                                      │
│  主文字   #EDEDED                                       │
│  雅金保持 #C9A96E / #D4A574                            │
│  钢蓝加深 #5B8FC4 / #6BA3D6                            │
└──────────────────────────────────────────────────────┘
```

### 视觉特征

- **扁平化设计 (Flat Design)**：无 `backdrop-filter`（毛玻璃）、无彩色发光 `box-shadow`、无按钮渐变。按钮为纯粹的单色雅金，卡片仅保留极浅的基础阴影（`box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04)`），页面极度整洁。
- **雅金 + 钢蓝双强调**：主要操作（按钮/Logo/选中态）使用 `#C9A96E` 雅金；链接和次要信息使用 `#4A7DB8` 钢蓝。Hover 采用极淡的金色透明度反馈。
- **暖白底色**：整体背景 `#FAF8F5` 暖米白，区别于之前的冷灰白 `#F5F7FA`，视觉更温暖高级。
- **标准金融色**：严格遵守金融规范，股票红绿（`#FF4D4F` / `#52C41A`）全局统一。

### 布局

- 侧边栏：浅色模式 `#FDFBFA` 极微暖白。菜单选中态背景淡金色块，文字雅金。
- 内容区：背景 `#FAF8F5` 暖米白，纯白卡片通过 1px 淡金边框区分层次。
- 登录页：居中白色卡片，雅金标题和按钮，暖金色调阴影。

### Ant Design 主题覆盖

```typescript
// App.tsx - 已实施 v2 星海雅金主题
const antTheme = {
  algorithm: effectiveTheme === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
  token: {
    colorPrimary: '#C9A96E',         // 雅金 - 主强调
    colorInfo: '#4A7DB8',            // 钢蓝 - 链接/Info
    colorSuccess: '#52C41A',         // 标准绿 (涨)
    colorError: '#FF4D4F',           // 标准红 (跌)
    colorWarning: '#D48806',         // 琥珀警告
    colorBgBase: effectiveTheme === 'dark' ? '#131314' : '#FAF8F5',
    colorBgContainer: effectiveTheme === 'dark' ? '#1A1A1D' : '#FFFFFF',
    colorBgElevated: effectiveTheme === 'dark' ? '#222225' : '#FFFFFF',
    colorText: effectiveTheme === 'dark' ? '#EDEDED' : '#2C2C2C',
    colorTextSecondary: effectiveTheme === 'dark' ? '#9CA3AF' : '#6B7280',
    colorLink: '#4A7DB8',            // 钢蓝链接
    colorLinkHover: '#5B8FC4',       // 浅蓝Hover
    borderRadius: 6,
    fontFamily: `'Inter', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif`,
  },
  components: {
    Layout: { headerBg, siderBg },
    Menu: { itemSelectedBg, itemSelectedColor: '#C9A96E', itemHoverBg },
    Button: { primaryShadow: 'none' },
    Table: { rowHoverBg },
    Input: { activeBorderColor: '#C9A96E' },
    // ... 完整配置见 App.tsx
  },
}
```

---

## 分阶段实施计划

### Phase 0：项目脚手架（2-3 天）

**产出**：可运行的空壳项目

1. `npm create vite@latest frontend-react -- --template react-ts`
2. 安装依赖：antd、zustand、react-router、axios、echarts-for-react、react-hook-form、@hookform/resolvers、zod、dayjs、lodash-es
3. 配置 `vite.config.ts`（路径别名 @、API 代理 → localhost:8000、WebSocket 代理、manualChunks 分包）
4. 配置 `tsconfig.json`（strict、路径映射）
5. 编写 `services/http/client.ts`：Axios 实例、请求/响应拦截器、401 Token 刷新、消息去重、网络重试
6. 编写 `services/http/types.ts` + `services/http/error-handler.ts`
7. 编写 `types/common.types.ts`（ApiResponse<T>、Pagination 等）
8. 编写 `utils/` 全部工具函数
9. 编写 `constants/` 全部常量
10. 编写 `stores/auth.store.ts` + `stores/app.store.ts`
11. 编写 `assets/styles/` 基础样式

**深度测试（必须全部通过才能进入 Phase 1）：**
1. `npm run build` 构建通过，无警告
2. `npm run dev` 启动正常，浏览器访问无白屏
3. `npx tsc --noEmit` 零类型错误
4. Axios 拦截器单元测试：401 自动刷新、消息去重、网络重试
5. Zustand stores 单元测试：auth store 登录/登出/token 刷新状态转换
6. Utils 单元测试：market 市场判断、stock 代码验证、token JWT 解析
7. 手动验证：Vite 代理到后端 API 可正常通信（`/api/health` 返回 200）

### Phase 1：认证与布局（3-4 天）

**产出**：登录/登出流程 + 主布局框架

1. 编写 `services/api/auth.ts`（9 个 API）
2. 编写 `types/auth.types.ts`
3. 编写 `services/websocket/notification-ws.ts`
4. 编写 `stores/notification.store.ts`
5. 编写 `layouts/AuthLayout/index.tsx`
6. 编写 `pages/auth/LoginPage.tsx`
7. 编写 `layouts/AppLayout/` 全部组件（Sidebar、Header、NotificationCenter、UserDropdown）
8. 编写 `router/index.tsx`（完整路由表，所有页面 lazy 到占位符）
9. 编写 `router/guards.tsx`（认证守卫）
10. 编写 `App.tsx`（ConfigProvider + RouterProvider）
11. 编写 `hooks/useAuth.ts` + `hooks/useTheme.ts`
12. 编写 `components/feedback/NetworkStatus.tsx`

**深度测试（必须全部通过才能进入 Phase 2）：**
1. 构建和类型检查通过
2. 登录流程端到端测试：输入用户名密码 → 获取 token → 跳转仪表板
3. 登出流程测试：清除 token → 跳转登录页
4. 路由守卫测试：未登录访问受保护页面 → 重定向到登录页
5. Token 刷新测试：模拟 token 过期 → 自动刷新 → 原请求重试成功
6. 布局渲染测试：侧边栏展开/折叠、菜单高亮、面包屑正确
7. WebSocket 连接测试：登录后 WS 自动连接、断线自动重连
8. 通知功能测试：收到 WS 消息 → 通知列表更新 → 标记已读
9. 主题渲染验证：暗色主题色彩系统正确应用（背景 #0C0E1A、卡片 #141627 等）

### Phase 2：核心分析功能（5-6 天）

**产出**：单股分析 + 批量分析 + 任务中心

1. 编写 `services/api/analysis.ts`（21 个 API）
2. 编写 `types/analysis.types.ts`
3. 编写 `features/analysis/schemas/analysis.schema.ts`
4. 编写 `features/analysis/components/` 全部组件（StockCodeInput、MarketSelector、AnalystTeamSelector、DepthSelector、AnalysisConfigForm、AnalysisProgressBar、AnalysisStepTimeline、AnalysisResultView、BatchStockInput、TaskStatusBadge）
5. 编写 `features/analysis/hooks/`（useAnalysisSubmit、useAnalysisProgress、useTaskList）
6. 编写 `pages/analysis/SingleAnalysisPage.tsx`
7. 编写 `pages/analysis/BatchAnalysisPage.tsx`
8. 编写 `pages/tasks/TaskCenterPage.tsx`
9. 编写 `hooks/useSSE.ts`
10. 编写 `components/ui/MarkdownRenderer.tsx`
11. 编写 `components/charts/KlineECharts.tsx`

**深度测试（必须全部通过才能进入 Phase 3）：**
1. 构建和类型检查通过
2. 单股分析全流程测试：输入代码 → 选择参数 → 提交 → SSE 进度更新 → 查看结果
3. 批量分析测试：输入多个代码 → 提交 → 批次状态跟踪 → 各股票结果
4. 任务中心测试：任务列表加载、状态筛选、分页、取消/删除任务
5. SSE 进度流测试：实时进度更新无延迟、断线重连恢复
6. 表单验证测试：空代码、错误格式、必填项缺失均有正确提示
7. Markdown 渲染测试：分析报告中的 Markdown 正确渲染（标题、列表、代码块、表格）
8. K线图渲染测试：ECharts 组件正确挂载、数据绑定、交互（缩放、拖拽）

### Phase 3：股票数据（3-4 天）

**产出**：股票详情页 + 自选股 + 筛选

1. 编写 `services/api/stocks.ts` + `multi-market.ts` + `favorites.ts` + `screening.ts`
2. 编写对应 types
3. 编写 `features/stocks/components/`（StockSearch、StockQuoteCard、KlineChart、FundamentalsTable、NewsList、FavoriteButton）
4. 编写 `features/stocks/hooks/`
5. 编写 `features/screening/` 全部组件和 hooks
6. 编写 `pages/stocks/StockDetailPage.tsx`
7. 编写 `pages/screening/ScreeningPage.tsx`
8. 编写 `pages/favorites/FavoritesPage.tsx`

**深度测试（必须全部通过才能进入 Phase 4）：**
1. 构建和类型检查通过
2. 股票详情页测试：行情数据展示、K线图多周期切换、基本面数据加载、新闻列表
3. 自选股 CRUD 测试：添加 → 列表展示 → 删除 → 检查收藏状态
4. 筛选功能测试：选择行业 → 设置指标范围 → 执行筛选 → 结果表格展示
5. 多市场测试：A股/美股/港股切换，代码验证规则随市场变化
6. 数据加载状态测试：loading 态、空数据态、错误态均有正确 UI

### Phase 4：报告与仪表板（3 天）

**产出**：报告系统 + 仪表板 + 学习中心

1. 编写 `services/api/reports.ts` + types
2. 编写报告页面（ReportListPage、ReportDetailPage、TokenStatisticsPage）
3. 编写 `features/dashboard/components/`（WelcomeSection、QuickActionsCard、RecentAnalysesCard、SystemStatusCard）
4. 编写 `pages/dashboard/DashboardPage.tsx`
5. 编写学习中心页面
6. 编写 `components/charts/PieChart.tsx` + `BarChart.tsx`

**深度测试（必须全部通过才能进入 Phase 5）：**
1. 构建和类型检查通过
2. 仪表板测试：统计卡片数据正确、快速操作可跳转、最近分析列表加载
3. 报告列表测试：分页、搜索、排序、删除
4. 报告详情测试：Markdown 渲染正确、评分展示、操作按钮可用
5. Token 统计图表测试：折线图/饼图数据绑定正确
6. 学习中心测试：文章列表、分类导航、文章详情

### Phase 5：系统配置（4-5 天）

**产出**：配置管理 + 设置 + 缓存 + 使用统计

1. 编写 `services/api/config.ts`（约 40 个方法，最大 API 模块）
2. 编写 `types/config.types.ts`
3. 编写 `features/config/components/`（ProviderDialog、ModelCatalogManager、DataSourceConfigDialog、MarketCategoryManager、SortableDataSourceList、ConfigValidator、ImportExportPanel）
4. 编写 `pages/settings/ConfigManagementPage.tsx`（左侧菜单 + 右侧内容区）
5. 编写 `pages/settings/SettingsPage.tsx` + `CacheManagementPage.tsx` + `UsageStatisticsPage.tsx`

**深度测试（必须全部通过才能进入 Phase 6）：**
1. 构建和类型检查通过
2. 配置管理各 Tab 测试：厂家管理、模型目录、数据源、系统设置
3. 厂家 CRUD 测试：添加 → 编辑 → 删除 → 启用/禁用 → API 测试连接
4. 数据源 CRUD 测试：添加 → 设为默认 → 删除
5. 拖拽排序测试：数据源优先级拖拽调整，顺序持久化
6. 配置导入导出测试：导出 JSON → 清空 → 导入 → 数据恢复
7. 配置验证器测试：检测缺失配置项，显示警告
8. 缓存管理测试：查看统计 → 清理过期 → 清空全部
9. 使用统计测试：按供应商/模型/日统计图表正确渲染

### Phase 6：MCP、智能体、定时任务（3-4 天）

**产出**：MCP 管理 + 智能体 + 定时任务 + 数据同步 + 数据库管理

1. 编写 MCP 相关 services/types/components/pages
2. 编写智能体管理页面
3. 编写 `features/scheduler/` 全部组件和 hooks
4. 编写 `pages/system/SchedulerPage.tsx`
5. 编写 `pages/system/SyncManagementPage.tsx`
6. 编写 `pages/system/DatabaseManagementPage.tsx`

**深度测试（必须全部通过才能进入 Phase 7）：**
1. 构建和类型检查通过
2. MCP 连接器测试：列表展示 → 启用/禁用 → 配置编辑
3. MCP 工具测试：工具列表 → 按类别分组 → 启用/禁用切换
4. 智能体管理测试：查看配置 → 编辑参数 → 保存
5. 定时任务测试：任务列表 → 手动触发 → 暂停/恢复 → 查看执行历史
6. 数据同步测试：查看同步状态 → 触发同步 → 进度跟踪
7. 数据库管理测试：状态查看 → 测试连接 → 备份/恢复

### Phase 7：收尾（2-3 天）

**产出**：剩余页面 + 全局优化

1. 编写日志管理页面（OperationLogsPage、SystemLogsPage）
2. 编写 NotFoundPage
3. 全局错误处理完善
4. 响应式适配（移动端）
6. 性能优化（虚拟列表、图表懒加载）
7. 端到端全流程测试

**最终深度测试（全部通过才能标记项目完成）：**
1. 构建和类型检查通过，零 warning
2. 日志管理测试：操作日志列表/筛选/详情、系统日志文件读取/导出
3. 404 页面测试：无效路径正确显示 404
4. 全局错误处理测试：模拟 500/502/503 错误，UI 正确提示
5. 暗色主题全页面截图对比：每个页面色彩一致、无白色闪烁
6. 响应式测试：1920px / 1366px / 768px / 375px 四种宽度
7. 性能测试：首屏加载 < 3s、路由切换 < 500ms
8. 全功能端到端回归测试：登录 → 分析 → 查看报告 → 配置管理 → 登出

---

## 移除 Paper Trading 清单

- 不创建 `/paper` 路由和页面
- 不编写 `services/api/paper.ts`
- 侧边栏菜单不包含"模拟交易"
- 股票详情页不包含"模拟交易"按钮

---

## 关键参考文件（仅作为功能参考，不复用代码）

| 文件 | 参考目的 |
|------|---------|
| `frontend/src/api/request.ts` | HTTP 拦截器逻辑（401 刷新、重试、消息去重）的功能清单 |
| `frontend/src/stores/auth.ts` | 认证状态管理的完整功能清单 |
| `frontend/src/router/index.ts` | 路由表和守卫逻辑的功能覆盖 |
| `frontend/src/api/config.ts` | 配置管理 API 的完整接口列表 |
| `app/main.py` | 后端路由注册，API 模块完整性的权威参考 |

---

## 验证总则

**铁律：每个 Phase 的深度测试必须全部通过，才能进入下一个 Phase。**

每个 Phase 完成后执行：
1. `npm run build` 构建通过（零 warning）
2. `npx tsc --noEmit` 零类型错误
3. 对应 Phase 页面的功能测试全部通过（见各 Phase 详细测试清单）
4. 回归测试：前序 Phase 的功能未被破坏
5. 浏览器控制台无报错（允许的 CDN 警告除外）
