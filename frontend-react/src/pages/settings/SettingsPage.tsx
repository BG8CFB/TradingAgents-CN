/**
 * 个人设置页面
 * 用户个人信息管理、偏好设置
 */

import { useState } from 'react'
import {
  Card, Form, Input, Button, Select, message, Typography, Divider, Avatar, Space, Upload,
} from 'antd'
import { UserOutlined, MailOutlined, SaveOutlined, CameraOutlined } from '@ant-design/icons'
import { useAuthStore } from '@/stores/auth.store'

const { Title, Paragraph } = Typography

export default function SettingsPage() {
  const { user, updateUser } = useAuthStore()
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      // TODO: 调用更新用户信息 API
      // await updateUserInfo(values)
      updateUser({ ...values })
      message.success('个人设置保存成功')
    } catch {
      // 表单验证失败
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <Title level={4} style={{ marginBottom: 24 }}>个人设置</Title>

      {/* 基本信息 */}
      <Card title="基本信息" size="small" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            username: user?.username ?? '',
            email: user?.email ?? '',
            display_name: (user as unknown as Record<string, unknown>)?.display_name ?? '',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
            <Avatar size={64} icon={<UserOutlined />} style={{ backgroundColor: 'var(--accent-primary)' }} />
            <div>
              <Upload
                showUploadList={false}
                beforeUpload={() => false}
                accept="image/*"
              >
                <Button icon={<CameraOutlined />} size="small">更换头像</Button>
              </Upload>
            </div>
          </div>

          <Form.Item name="username" label="用户名">
            <Input prefix={<UserOutlined />} disabled />
          </Form.Item>

          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="display_name" label="显示名称" style={{ flex: 1, minWidth: 200 }}>
              <Input placeholder="显示名称" />
            </Form.Item>
            <Form.Item name="email" label="邮箱" style={{ flex: 1, minWidth: 240 }}>
              <Input prefix={<MailOutlined />} type="email" placeholder="邮箱地址" />
            </Form.Item>
          </Space>

          <Form.Item style={{ marginTop: 16, textAlign: 'right' }}>
            <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
              保存修改
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* 偏好设置 */}
      <Card title="使用偏好" size="small">
        <Form layout="vertical">
          <Form.Item label="默认分析市场">
            <Select
              defaultValue="china_a"
              options={[
                { value: 'china_a', label: 'A 股市场' },
                { value: 'us_stock', label: '美股市场' },
                { value: 'hk_stock', label: '港股市场' },
              ]}
            />
          </Form.Item>

          <Form.Item label="默认分析深度">
            <Select
              defaultValue="standard"
              options={[
                { value: 'quick', label: '快速分析' },
                { value: 'standard', label: '标准分析' },
                { value: 'deep', label: '深度分析' },
              ]}
            />
          </Form.Item>

          <Divider />

          <Paragraph type="secondary" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            更多偏好设置（如通知方式、界面语言等）将在后续版本中提供。
          </Paragraph>
        </Form>
      </Card>
    </div>
  )
}
