/**
 * 系统日志管理页面
 * 功能：日志文件列表、读取文件内容（支持筛选）、导出、删除、统计概览
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, Select, Input,
  Row, Col, Statistic, Modal, Spin, Empty, Alert,
  Popconfirm, message, InputNumber, Tooltip,
} from 'antd'
import {
  FileTextOutlined, ReloadOutlined, DeleteOutlined,
  EyeOutlined, DownloadOutlined,
  SearchOutlined, WarningOutlined, CodeOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  listLogFiles,
  readLogFile,
  exportLogs,
  getLogStatistics,
  deleteLogFile,
  type LogFileInfo,
  type LogContentResponse,
  type LogStatistics,
} from '@/services/api/system-logs'

const { Title, Text } = Typography

/** 日志级别选项 */
const LOG_LEVEL_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' },
  { value: 'CRITICAL', label: 'CRITICAL' },
]

/** 日志级别颜色映射 */
const LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'default',
  INFO: 'processing',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'error',
}

/** 格式化字节数 */
function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  if (!Number.isFinite(bytes)) return `${bytes} B`
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1)
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export default function SystemLogsPage() {
  // --- 文件列表 ---
  const [files, setFiles] = useState<LogFileInfo[]>([])
  const [filesLoading, setFilesLoading] = useState(false)

  // --- 统计数据 ---
  const [stats, setStats] = useState<LogStatistics | null>(null)

  // --- 文件阅读 ---
  const [readerOpen, setReaderOpen] = useState(false)
  const [currentFile, setCurrentFile] = useState<LogFileInfo | null>(null)
  const [logLines, setLogLines] = useState<string[]>([])
  const [logStats, setLogStats] = useState<Record<string, unknown> | null>(null)
  const [readingLoading, setReadingLoading] = useState(false)

  // --- 阅读器筛选 ---
  const [readLevel, setReadLevel] = useState('')
  const [readKeyword, setReadKeyword] = useState('')
  const [readLineCount, setReadLineCount] = useState<number>(200)
  const [readStartTime, setReadStartTime] = useState('')
  const [readEndTime, setReadEndTime] = useState('')

  // --- 导出 ---
  const [exporting, setExporting] = useState(false)

  /** 加载文件列表 */
  const loadFiles = useCallback(async () => {
    setFilesLoading(true)
    try {
      const res = await listLogFiles()
      setFiles(Array.isArray(res) ? res : [])
    } catch {
      message.error('加载日志文件列表失败')
    } finally {
      setFilesLoading(false)
    }
  }, [])

  /** 加载统计 */
  const loadStats = useCallback(async () => {
    try {
      const res = await getLogStatistics(7)
      setStats(res.data ?? null)
    } catch {
      // 统计加载失败不阻塞主流程
    }
  }, [])

  useEffect(() => {
    loadFiles()
    loadStats()
  }, [loadFiles, loadStats])

  /** 打开文件阅读器 */
  const handleOpenReader = async (file: LogFileInfo) => {
    setCurrentFile(file)
    setReaderOpen(true)
    setLogLines([])
    setLogStats(null)
    await doReadFile(file.name)
  }

  /** 执行读取文件 — 接受显式参数避免闭包竞态 */
  const doReadFile = async (
    filename: string,
    opts?: { lineCount?: number; level?: string; keyword?: string; startTime?: string; endTime?: string },
  ) => {
    setReadingLoading(true)
    try {
      const { lineCount = readLineCount, level = readLevel, keyword = readKeyword, startTime = readStartTime, endTime = readEndTime } = opts ?? {}
      const res = await readLogFile({
        filename,
        lines: lineCount,
        level: level || undefined,
        keyword: keyword || undefined,
        start_time: startTime || undefined,
        end_time: endTime || undefined,
      })
      const data = res.data as LogContentResponse ?? { lines: [], stats: {} }
      setLogLines(data.lines ?? [])
      setLogStats(data.stats ?? null)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`读取失败: ${err?.response?.data?.detail || err?.message || '未知错误'}`)
    } finally {
      setReadingLoading(false)
    }
  }

  /** 阅读器中重新搜索/筛选 — 显式传入当前 UI 值 */
  const handleReSearch = () => {
    if (currentFile) {
      doReadFile(currentFile.name, {
        lineCount: readLineCount,
        level: readLevel,
        keyword: readKeyword,
        startTime: readStartTime,
        endTime: readEndTime,
      })
    }
  }

  /** 删除文件 */
  const handleDelete = async (filename: string) => {
    try {
      await deleteLogFile(filename)
      message.success('日志文件已删除')
      await loadFiles()
      await loadStats()
    } catch {
      message.error('删除失败')
    }
  }

  /** 导出日志 */
  const handleExport = async () => {
    setExporting(true)
    try {
      await exportLogs({
        level: (readLevel || undefined) as 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL' | undefined,
        start_time: readStartTime || undefined,
        end_time: readEndTime || undefined,
        format: 'zip',
      })
      message.success('导出请求已发送')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`导出失败: ${err?.response?.data?.detail || err?.message || '未知错误'}`)
    } finally {
      setExporting(false)
    }
  }

  // ========== 文件表格列定义 ==========
  const fileColumns: ColumnsType<LogFileInfo> = [
    {
      title: '文件名',
      dataIndex: 'name',
      ellipsis: true,
      render: (name: string) => (
        <Space>
          <CodeOutlined style={{ color: '#C9A96E' }} />
          <Tooltip title={name}>
            <span className="font-mono" style={{ fontSize: 12 }}>{name}</span>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      render: (type: string) => (
        <Tag color="blue" style={{ marginRight: 0 }}>{type}</Tag>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size_mb',
      width: 90,
      sorter: true,
      render: (mb: number) => formatBytes(mb * 1024 * 1024),
    },
    {
      title: '修改时间',
      dataIndex: 'modified_at',
      width: 170,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '操作',
      width: 160,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleOpenReader(record)}
          >
            查看
          </Button>
          <Popconfirm
            title={`确定删除 ${record.name} 吗？`}
            onConfirm={() => handleDelete(record.name)}
            okText="确定"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 + 统计 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <Title level={4} style={{ margin: '0 0 8px' }}>
              <FolderOpenOutlined style={{ marginRight: 8 }} />
              系统日志
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              查看和管理系统运行日志文件
            </Text>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadFiles} loading={filesLoading}>
              刷新
            </Button>
            <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>
              导出日志
            </Button>
          </Space>
        </div>

        {/* 统计卡片 */}
        {stats && (
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Statistic
                title="日志文件数"
                value={stats.total_files}
                styles={{ content: { fontSize: 20 } }}
                prefix={<FileTextOutlined />}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="总大小"
                value={stats.total_size_mb}
                suffix="MB"
                styles={{ content: { fontSize: 20 } }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="异常文件数"
                value={stats.error_files}
                styles={{ content: { fontSize: 20, color: stats.error_files > 0 ? '#FF4D4F' : '#52C41A' } }}
                prefix={<WarningOutlined />}
              />
            </Col>
            <Col span={6}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>日志类型分布</Text>
                <div style={{ marginTop: 4 }}>
                  {Object.entries(stats.log_types).map(([type, count]) => (
                    <Tag key={type} color={LEVEL_COLORS[type] ?? 'default'} style={{ marginBottom: 2 }}>
                      {type}: {count as number}
                    </Tag>
                  ))}
                  {Object.keys(stats.log_types).length === 0 && (
                    <Text type="secondary">-</Text>
                  )}
                </div>
              </div>
            </Col>
          </Row>
        )}

        {/* 最近错误提示 */}
        {stats?.recent_errors && stats.recent_errors.length > 0 && (
          <Alert
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            style={{ marginTop: 12 }}
            title="最近检测到异常"
            description={
              <ul style={{ margin: 0, paddingLeft: 16, maxHeight: 80, overflow: 'auto' }}>
                {stats.recent_errors.map((err, i) => (
                  <li key={i}>{String(err)}</li>
                ))}
              </ul>
            }
          />
        )}
      </Card>

      {/* 文件列表 */}
      <Card size="small">
        <Table
          dataSource={files.map((f) => ({ ...f, key: f.name + f.path }))}
          columns={fileColumns}
          loading={filesLoading}
          scroll={{ x: 700 }}
          size="small"
          pagination={{
            pageSize: 15,
            showTotal: (t) => `共 ${t} 个文件`,
            showSizeChanger: false,
          }}
          locale={{
            emptyText: <Empty description="暂无日志文件" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          }}
        />
      </Card>

      {/* 日志阅读器弹窗 */}
      <Modal
        title={
          <Space>
            <CodeOutlined />
            <span>{currentFile?.name}</span>
            <Tag>{formatBytes(currentFile?.size ?? 0)}</Tag>
          </Space>
        }
        open={readerOpen}
        onCancel={() => { setReaderOpen(false); setCurrentFile(null); setLogLines([]) }}
        width={900}
        footer={[
          <Button key="close" onClick={() => setReaderOpen(false)}>关闭</Button>,
          <Button
            key="export"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={handleExport}
          >
            导出
          </Button>,
        ]}
      >
        {/* 阅读器工具栏 */}
        <Card size="small" style={{ marginBottom: 12 }}>
          <Space wrap size="small">
            <SearchOutlined style={{ color: '#C9A96E' }} />
            <Input
              placeholder="关键字过滤"
              allowClear
              value={readKeyword}
              onChange={(e) => setReadKeyword(e.target.value)}
              onPressEnter={handleReSearch}
              style={{ width: 160 }}
            />
            <Input
              placeholder="起始时间 (YYYY-MM-DD HH:mm:ss)"
              allowClear
              value={readStartTime}
              onChange={(e) => setReadStartTime(e.target.value)}
              style={{ width: 200 }}
            />
            <Input
              placeholder="结束时间 (YYYY-MM-DD HH:mm:ss)"
              allowClear
              value={readEndTime}
              onChange={(e) => setReadEndTime(e.target.value)}
              style={{ width: 200 }}
            />
            <Select
              value={readLevel}
              onChange={(v) => { setReadLevel(v); handleReSearch() }}
              options={LOG_LEVEL_OPTIONS}
              style={{ width: 110 }}
            />
            <Space size={4}>
              <Text type="secondary" style={{ fontSize: 12 }}>行数:</Text>
              <InputNumber
                min={10}
                max={5000}
                value={readLineCount}
                onChange={(v) => v != null && setReadLineCount(v)}
                style={{ width: 80 }}
              />
            </Space>
            <Button type="primary" size="small" onClick={handleReSearch}>
              搜索
            </Button>
          </Space>
        </Card>

        {/* 日志内容区域 */}
        <Spin spinning={readingLoading}>
          {/* 统计信息 */}
          {logStats && typeof logStats === 'object' && Object.keys(logStats).length > 0 && (
            <Alert
              type="info"
              showIcon={false}
              style={{ marginBottom: 8, padding: '4px 12px' }}
              title={
                <Space size="large" style={{ fontSize: 12 }}>
                  {(Object.entries(logStats) as [string, unknown][]).map(([k, v]) => (
                    <span key={k}><Text type="secondary">{k}: </Text><strong>{String(v)}</strong></span>
                  ))}
                </Space>
              }
            />
          )}

          {/* 日志行 */}
          {logLines.length > 0 ? (
            <div
              style={{
                background: '#1a1a2e',
                borderRadius: 6,
                padding: 12,
                maxHeight: 450,
                overflow: 'auto',
                fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
                fontSize: 12,
                lineHeight: 1.6,
              }}
            >
              {logLines.map((line, idx) => {
                // 根据级别高亮
                let lineColor = '#a0a0b0'
                if (line.includes('ERROR') || line.includes('CRITICAL')) lineColor = '#FF6B6B'
                else if (line.includes('WARNING')) lineColor = '#FFD93D'
                else if (line.includes('INFO')) lineColor = '#6BCB77'
                else if (line.includes('DEBUG')) lineColor = '#4D96FF'

                return (
                  <div
                    key={idx}
                    style={{
                      color: lineColor,
                      padding: '1px 0',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                    }}
                  >
                    <span style={{ color: '#555', marginRight: 8, userSelect: 'none' }}>
                      {String(idx + 1).padStart(4, '\u00A0')}
                    </span>
                    {line}
                  </div>
                )
              })}
            </div>
          ) : !readingLoading ? (
            <Empty description="无匹配的日志内容" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : null}
        </Spin>
      </Modal>
    </div>
  )
}
