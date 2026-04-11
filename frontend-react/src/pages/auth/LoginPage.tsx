import { Button, Form, Input, Checkbox, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth.store'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, isLoading } = useAuthStore()
  const [form] = Form.useForm()

  const handleSubmit = async (values: { username: string; password: string; remember?: boolean }) => {
    const success = await login({ username: values.username, password: values.password })
    if (success) {
      message.success('登录成功')
      navigate('/dashboard')
    }
  }

  return (
    <Form form={form} layout="vertical" onFinish={handleSubmit}>
      <Form.Item
        name="username"
        rules={[{ required: true, message: '请输入用户名' }]}
      >
        <Input
          prefix={<UserOutlined style={{ color: 'var(--text-muted)' }} />}
          placeholder="用户名"
          size="large"
          style={{
            background: 'var(--bg-base)',
            borderColor: 'var(--border-hover)',
            color: 'var(--text-primary)',
          }}
        />
      </Form.Item>

      <Form.Item
        name="password"
        rules={[{ required: true, message: '请输入密码' }]}
      >
        <Input.Password
          prefix={<LockOutlined style={{ color: 'var(--text-muted)' }} />}
          placeholder="密码"
          size="large"
          style={{
            background: 'var(--bg-base)',
            borderColor: 'var(--border-hover)',
            color: 'var(--text-primary)',
          }}
        />
      </Form.Item>

      <Form.Item>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Checkbox style={{ color: 'var(--text-secondary)' }}>记住我</Checkbox>
          <a style={{ color: 'var(--accent-secondary)', fontSize: 13 }}>忘记密码？</a>
        </div>
      </Form.Item>

      <Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          size="large"
          block
          loading={isLoading}
          style={{
            height: 44,
            background: 'var(--accent-primary)',
            borderColor: 'var(--accent-primary)',
            fontSize: 15,
            fontWeight: 500,
          }}
        >
          登录
        </Button>
      </Form.Item>
    </Form>
  )
}
