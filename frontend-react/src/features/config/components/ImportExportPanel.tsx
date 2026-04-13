/**
 * 配置导入导出面板
 * 支持 JSON 格式的完整配置导出和导入
 */

import { useState } from 'react'
import { Card, Button, Space, message, Modal, Typography, Alert, Upload, Descriptions, Tag } from 'antd'
import {
  DownloadOutlined, UploadOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { exportConfig, importConfig } from '@/services/api/config'

const { Text } = Typography

interface ImportExportPanelProps {
  onImported?: () => void
}

export default function ImportExportPanel({ onImported }: ImportExportPanelProps) {
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [previewData, setPreviewData] = useState<Record<string, unknown> | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [lastExportTime, setLastExportTime] = useState<string | null>(null)

  /** 导出配置 */
  const handleExport = async () => {
    setExporting(true)
    try {
      const res = await exportConfig()
      const data = res.data
      setLastExportTime(data.exported_at)

      // 生成 JSON 文件下载
      const jsonStr = JSON.stringify(data.data, null, 2)
      const blob = new Blob([jsonStr], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `tradingagents-config-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)

      message.success(`配置已导出（包含 ${Object.keys(data.data).length} 个模块）`)
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  /** 导入配置（从文件读取） */
  const handleImportFile = (file: File) => {
    const reader = new FileReader()
    reader.onload = async (e) => {
      try {
        const data = JSON.parse(e.target?.result as string)
        setPreviewData(data)
        setPreviewOpen(true)
      } catch {
        message.error('文件格式错误，必须是有效的 JSON')
      }
    }
    reader.readAsText(file)
    // 返回 false 阻止自动上传
    return false
  }

  /** 确认导入 */
  const handleConfirmImport = async () => {
    if (!previewData) return
    setImporting(true)
    try {
      const res = await importConfig(previewData)
      message.success(res.data.message || '配置导入成功')
      setPreviewOpen(false)
      setPreviewData(null)
      onImported?.()
    } catch {
      message.error('导入失败，请检查文件格式是否正确')
    } finally {
      setImporting(false)
    }
  }

  /** 获取配置预览摘要 */
  const getPreviewSummary = (data: Record<string, unknown>) => {
    const keys = Object.keys(data)
    return keys.map(key => {
      const val = data[key]
      const count = Array.isArray(val) ? val.length : typeof val === 'object' && val ? Object.keys(val).length : 1
      return { key, count, type: Array.isArray(val) ? 'array' : typeof val }
    })
  }

  return (
    <Card
      size="small"
      title="配置导入 / 导出"
      style={{ marginBottom: 16 }}
    >
      <Space orientation="vertical" style={{ width: '100%' }} size="middle">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Text type="secondary">将当前全部配置导出为 JSON 文件，或从备份文件恢复配置。</Text>
            {lastExportTime && (
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                最近导出：{lastExportTime}
              </Text>
            )}
          </div>
          <Space>
            <Button
              icon={<DownloadOutlined />}
              onClick={handleExport}
              loading={exporting}
            >
              导出配置
            </Button>
            <Upload
              accept=".json"
              showUploadList={false}
              beforeUpload={handleImportFile}
            >
              <Button icon={<UploadOutlined />}>选择文件导入</Button>
            </Upload>
          </Space>
        </div>

        <Alert
          type="warning"
          showIcon
          icon={<ExclamationCircleOutlined />}
          title="导入将覆盖现有配置，建议先导出当前配置作为备份"
          style={{ marginBottom: 0 }}
        />
      </Space>

      {/* 导入预览确认弹窗 */}
      <Modal
        title="确认导入配置"
        open={previewOpen}
        onCancel={() => { setPreviewOpen(false); setPreviewData(null) }}
        onOk={handleConfirmImport}
        confirmLoading={importing}
        okText="确认导入"
        okButtonProps={{ danger: true }}
        width={560}
      >
        <Alert
          type="error"
          showIcon
          title="此操作将覆盖当前所有配置，且不可撤销！"
          style={{ marginBottom: 16 }}
        />

        {previewData && (
          <Descriptions size="small" bordered column={2}>
            {getPreviewSummary(previewData).map(item => (
              <Descriptions.Item key={item.key} label={item.key}>
                <Tag color={item.type === 'array' ? 'blue' : 'geekblue'}>
                  {item.type === 'array' ? `${item.count} 条记录` : `${item.count} 个字段`}
                </Tag>
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </Modal>
    </Card>
  )
}
