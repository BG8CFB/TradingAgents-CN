import { Component, type ReactNode } from 'react'
import { Button, Result, Collapse, Typography, Alert } from 'antd'
import { ReloadOutlined, BugOutlined } from '@ant-design/icons'

interface Props {
  children: ReactNode
  /** 自定义降级 UI（可选） */
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: React.ErrorInfo | null
  /** 是否展开错误详情 */
  showDetails: boolean
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null, showDetails: false }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary] 捕获到未处理的错误:', error, errorInfo)
    this.setState({ errorInfo })

    // 生产环境下可上报错误到日志服务
    if (import.meta.env.PROD) {
      // 可扩展：发送到后端 /api/logs 接口
      const errorReport = {
        message: error.message,
        stack: error.stack,
        componentStack: errorInfo.componentStack,
        url: window.location.href,
        timestamp: new Date().toISOString(),
        userAgent: navigator.userAgent,
      }
      console.warn('[ErrorBoundary] 错误报告:', errorReport)
    }
  }

  /** 重置错误状态，尝试重新渲染 */
  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null, showDetails: false })
  }

  /** 刷新整个页面 */
  handleReload = () => {
    window.location.reload()
  }

  /** 切换详情显示 */
  toggleDetails = () => {
    this.setState((prev) => ({ showDetails: !prev.showDetails }))
  }

  render() {
    // 使用自定义降级 UI
    if (this.state.hasError && this.props.fallback) {
      return this.props.fallback
    }

    if (this.state.hasError) {
      const { error, errorInfo, showDetails } = this.state

      return (
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'flex-start',
          minHeight: '100vh',
          padding: '64px 24px',
          background: 'var(--bg-base)',
          color: 'var(--text-primary)',
        }}>
          <Result
            status="500"
            title="页面出错了"
            subTitle={
              <Typography.Text type="secondary">
                {error?.message || '页面加载失败，请刷新重试'}
              </Typography.Text>
            }
            extra={[
              <Button key="reset" icon={<ReloadOutlined />} onClick={this.handleReset}>
                重试渲染
              </Button>,
              <Button key="reload" type="primary" onClick={this.handleReload}>
                刷新页面
              </Button>,
              <Button
                key="detail"
                icon={<BugOutlined />}
                onClick={this.toggleDetails}
                size="small"
                style={{ marginTop: 8 }}
              >
                {showDetails ? '隐藏' : '查看'}错误详情
              </Button>,
            ]}
          >
            {/* 错误详情 */}
            {showDetails && (
              <div style={{ marginTop: 16, textAlign: 'left', maxWidth: 640 }}>
                <Alert
                  type="error"
                  showIcon
                  title="错误信息"
                  description={
                    <Collapse
                      ghost
                      size="small"
                      defaultActiveKey={['message']}
                      items={[
                        {
                          key: 'message',
                          label: '错误消息',
                          children: (
                            <pre style={{
                              background: '#1a1a2e',
                              color: '#ff6b6b',
                              padding: 12,
                              borderRadius: 4,
                              fontSize: 12,
                              overflow: 'auto',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-all',
                            }}>
                              {error?.message || '(未知错误)'}
                            </pre>
                          ),
                        },
                        {
                          key: 'stack',
                          label: '堆栈跟踪',
                          children: (
                            <pre style={{
                              background: '#1a1a2e',
                              color: '#a0a0b0',
                              padding: 12,
                              borderRadius: 4,
                              fontSize: 11,
                              overflow: 'auto',
                              maxHeight: 300,
                            }}>
                              {error?.stack || '(无堆栈信息)'}
                            </pre>
                          ),
                        },
                        ...(errorInfo?.componentStack
                          ? [{
                              key: 'componentStack',
                              label: '组件堆栈',
                              children: (
                                <pre style={{
                                  background: '#1a1a2e',
                                  color: '#4d96ff',
                                  padding: 12,
                                  borderRadius: 4,
                                  fontSize: 11,
                                  overflow: 'auto',
                                  maxHeight: 200,
                                }}>
                                  {errorInfo.componentStack}
                                </pre>
                              ),
                            }]
                          : []),
                      ]}
                    />
                  }
                  style={{ textAlign: 'left' }}
                />
              </div>
            )}
          </Result>
        </div>
      )
    }

    return this.props.children
  }
}
