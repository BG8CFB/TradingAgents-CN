import { Button, Result } from 'antd'
import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <Result
      status="404"
      title="404"
      subTitle="页面走丢了，试试返回首页重新开始"
      extra={
        <Link to="/dashboard">
          <Button type="primary" size="large">返回首页</Button>
        </Link>
      }
      style={{ padding: '80px 24px', color: 'var(--text-primary)' }}
    />
  )
}
