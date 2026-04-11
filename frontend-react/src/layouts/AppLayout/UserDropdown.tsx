import { Dropdown, Avatar, Space } from 'antd'
import { UserOutlined, LogoutOutlined, ProfileOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth.store'

export default function UserDropdown() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const menuItems = [
    {
      key: 'profile',
      icon: <ProfileOutlined />,
      label: '个人设置',
      onClick: () => navigate('/settings/profile'),
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: () => logout(),
    },
  ]

  return (
    <Dropdown menu={{ items: menuItems as unknown as [] }} placement="bottomRight">
      <Space style={{ cursor: 'pointer' }}>
        <Avatar size="small" icon={<UserOutlined />} style={{ background: 'var(--accent-primary)' }} />
        <span style={{ color: 'var(--text-primary)', fontSize: 14 }}>
          {user?.username ?? '用户'}
        </span>
      </Space>
    </Dropdown>
  )
}
