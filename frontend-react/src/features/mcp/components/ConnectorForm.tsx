/**
 * MCP 连接器配置表单（手动添加/编辑）
 * 支持 JSON 格式的 MCP Server 配置输入
 */

import { useState } from 'react'
import { Modal, Input, Alert, Typography } from 'antd'
import { WarningFilled } from '@ant-design/icons'

const { Paragraph } = Typography

interface ConnectorFormProps {
  open: boolean
  onClose: () => void
  onSubmit: (mcpServers: Record<string, unknown>) => Promise<void>
  submitting?: boolean
}

/** 默认示例配置 */
const EXAMPLE_CONFIG = `{
  "mcpServers": {
    "example-server": {
      "command": "npx",
      "args": ["-y", "mcp-server-example"]
    }
  }
}`

export default function ConnectorForm({ open, onClose, onSubmit, submitting = false }: ConnectorFormProps) {
  const [jsonConfig, setJsonConfig] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)

  const handleConfirm = async () => {
    const trimmed = jsonConfig.trim()
    if (!trimmed) return

    let config: unknown
    try {
      config = JSON.parse(trimmed)
      setParseError(null)
    } catch {
      setParseError('JSON 解析失败，请检查格式是否正确')
      return
    }

    if (!config || typeof config !== 'object' || !('mcpServers' in config) || typeof (config as Record<string, unknown>).mcpServers !== 'object') {
      setParseError('无效的配置格式，必须包含 "mcpServers" 对象')
      return
    }

    await onSubmit(config as Record<string, unknown>)
    setJsonConfig('')
  }

  const handleCancel = () => {
    setJsonConfig('')
    setParseError(null)
    onClose()
  }

  return (
    <Modal
      title="手动添加 MCP 配置"
      open={open}
      onCancel={handleCancel}
      onOk={handleConfirm}
      confirmLoading={submitting}
      okText="确认添加"
      cancelText="取消"
      width={640}
      destroyOnHidden
    >
      <div style={{ marginBottom: 16 }}>
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          请从 MCP Servers 的介绍页面复制配置 JSON（优先使用 NPX 或 UVX 配置），并粘贴到下方输入框中。
        </Paragraph>

        <Input.TextArea
          value={jsonConfig}
          onChange={(e) => {
            setJsonConfig(e.target.value)
            if (parseError) setParseError(null)
          }}
          placeholder={EXAMPLE_CONFIG}
          rows={14}
          style={{
            fontFamily: "'Menlo', 'Monaco', 'Courier New', monospace",
            fontSize: 13,
            lineHeight: 1.6,
          }}
        />

        {parseError && (
          <Alert type="error" showIcon title={parseError} style={{ marginTop: 8 }} />
        )}

        <Alert
          type="warning"
          showIcon
          icon={<WarningFilled />}
          style={{ marginTop: 12 }}
          title="配置前请确认来源，甄别风险"
        />
      </div>
    </Modal>
  )
}
