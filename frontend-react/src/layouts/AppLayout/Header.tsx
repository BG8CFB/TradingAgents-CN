import useIsMobile from '@/hooks/useIsMobile'
import { Layout, Breadcrumb, Space, Button, Badge, Tooltip } from 'antd'
import {
  BellOutlined,
  GlobalOutlined,
  MoonOutlined,
  SunOutlined,
} from '@ant-design/icons'
import { useLocation, Link } from 'react-router-dom'
import { useAppStore, getEffectiveTheme } from '@/stores/app.store'
import { useNotificationStore } from '@/stores/notification.store'
import UserDropdown from './UserDropdown'

const { Header: AntHeader } = Layout

/** 响应式断点 */
const MOBILE_BREAKPOINT = 768

const routeNameMap: Record<string, string> = {
  '/dashboard': '仪表盘',
  '/analysis/single': '单股分析',
  '/analysis/batch': '批量分析',
  '/tasks': '任务中心',
  '/reports': '报告列表',
  '/reports/view': '报告详情',
  '/reports/token': 'Token 统计',
  '/stocks': '股票详情',
  '/screening': '智能筛选',
  '/favorites': '我的自选股',
  '/settings/profile': '个人设置',
  '/settings/config': '配置管理',
  '/settings/mcp': 'MCP 服务',
  '/settings/mcp-tools': 'MCP 工具',
  '/settings/agents': '智能体管理',
  '/settings/cache': '缓存管理',
  '/settings/usage': '使用统计',
  '/system/database': '数据库管理',
  '/system/sync': '数据同步',
  '/system/scheduler': '定时任务',
  '/system/operation-logs': '操作日志',
  '/system/system-logs': '系统日志',
  '/learning': '学习中心',
}

export default function Header() {
  const location = useLocation()
  const { theme, setTheme } = useAppStore()
  const { unreadCount } = useNotificationStore()
  const effectiveTheme = getEffectiveTheme(theme)
  const isMobile = useIsMobile(MOBILE_BREAKPOINT)

  const pathSnippets = location.pathname.split('/').filter((i) => i)
  const breadcrumbItems = pathSnippets.map((snippet, index) => {
    const url = `/${pathSnippets.slice(0, index + 1).join('/')}`
    const name = routeNameMap[url] ?? snippet
    const isLast = index === pathSnippets.length - 1
    return {
      title: isLast ? name : <Link to={url}>{name}</Link>,
      key: url,
    }
  })

  // 当前页面名称（移动端标题）
  const currentPageName = routeNameMap[location.pathname]
    || routeNameMap[`/${pathSnippets.slice(0, -1).join('/')}`]
    || pathSnippets[pathSnippets.length - 1]
    || '首页'

  return (
    <AntHeader
      style={{
        height: 56,
        padding: isMobile ? '0 48px 0 56px' : '0 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'var(--bg-sidebar)',
        borderBottom: '1px solid var(--border-color)',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        minWidth: 0,
      }}
    >
      {/* 左侧：移动端显示页面标题，桌面端显示面包屑 */}
      <div style={{ minWidth: 0, overflow: 'hidden' }}>
        {isMobile ? (
          <span
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {currentPageName}
          </span>
        ) : (
          <Breadcrumb
            items={[
              { title: <Link to="/dashboard">首页</Link>, key: 'home' },
              ...breadcrumbItems,
            ]}
            style={{ color: 'var(--text-secondary)' }}
          />
        )}
      </div>

      {/* 右侧操作区 */}
      <Space size={isMobile ? 'small' : 'middle'}>
        <Tooltip title={effectiveTheme === 'dark' ? '切换到亮色' : '切换到暗色'}>
          <Button
            type="text"
            icon={effectiveTheme === 'dark' ? <SunOutlined /> : <MoonOutlined />}
            onClick={() => setTheme(effectiveTheme === 'dark' ? 'light' : 'dark')}
            style={{ color: 'var(--text-secondary)' }}
            size={isMobile ? 'small' : 'middle'}
          />
        </Tooltip>
        {!isMobile && (
          <Button type="text" icon={<GlobalOutlined />} style={{ color: 'var(--text-secondary)' }} />
        )}
        <Badge count={unreadCount} size="small" offset={[-2, 2]}>
          <Button
            type="text"
            icon={<BellOutlined />}
            style={{ color: 'var(--text-secondary)' }}
            size={isMobile ? 'small' : 'middle'}
          />
        </Badge>
        <UserDropdown />
      </Space>
    </AntHeader>
  )
}
