/**
 * 数据库管理页面
 * 功能：MongoDB + Redis 连接状态、统计、备份管理、导入/导出、数据清理
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Row, Col, Statistic, Table, Tag,
  Alert, Popconfirm, message, Modal, Upload, Select, Input, InputNumber,
  Descriptions, Checkbox,
} from 'antd'
import {
  DatabaseOutlined, CloudServerOutlined, ReloadOutlined,
  DownloadOutlined, UploadOutlined, DeleteOutlined,
  ExperimentOutlined,
  WarningOutlined, FileTextOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  getDatabaseStatus,
  getDatabaseStats,
  testDatabaseConnections,
  createBackup,
  listBackups,
  deleteBackup,
  cleanupAnalysisResults,
  cleanupOperationLogs,
  type DatabaseStatus,
  type DatabaseStats,
  type BackupInfo,
} from '@/services/api/database'

const { Title, Text, Paragraph } = Typography

/** 格式化字节数 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

/** 格式化运行时间 */
function formatUptime(seconds: number): string {
  if (!seconds || seconds <= 0) return '-'
  if (seconds < 60) return `${seconds.toFixed(0)}秒`
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins}分${Math.round(seconds % 60)}秒`
  const hours = Math.floor(mins / 60)
  return `${hours}小时${mins % 60}分`
}

export default function DatabaseManagementPage() {
  // --- 状态 ---
  const [dbStatus, setDbStatus] = useState<DatabaseStatus | null>(null)
  const [dbStats, setDbStats] = useState<DatabaseStats | null>(null)
  const [loading, setLoading] = useState(false)

  // --- 操作状态 ---
  const [testing, setTesting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [cleaning, setCleaning] = useState(false)

  // --- 导入导出 ---
  const [exportFormat, setExportFormat] = useState('json')
  const [exportCollection, setExportCollection] = useState('config_and_reports')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importOverwrite, setImportOverwrite] = useState(false)

  // --- 备份 ---
  const [backups, setBackups] = useState<BackupInfo[]>([])
  const [backupName, setBackupName] = useState('')
  const [backupDialogOpen, setBackupDialogOpen] = useState(false)

  // --- 清理 ---
  const [cleanupDays, setCleanupDays] = useState(30)
  const [logCleanupDays, setLogCleanupDays] = useState(90)

  /** 加载状态 */
  const loadStatus = useCallback(async () => {
    setLoading(true)
    try {
      const [statusRes, statsRes] = await Promise.all([
        getDatabaseStatus(),
        getDatabaseStats(),
      ])
      setDbStatus(statusRes?.data ?? null)
      setDbStats(statsRes?.data ?? null)
    } catch {
      message.error('加载数据库状态失败')
    } finally {
      setLoading(false)
    }
  }, [])

  /** 加载备份列表 */
  const loadBackups = useCallback(async () => {
    try {
      const res = await listBackups()
      setBackups(Array.isArray(res) ? res : [])
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    loadStatus()
    loadBackups()
  }, [loadStatus, loadBackups])

  /** 测试连接 */
  const handleTestConnections = async () => {
    setTesting(true)
    try {
      const res = await testDatabaseConnections()
      const data = res as unknown as Record<string, unknown>
      if ((data.overall as boolean) ?? false) {
        message.success('数据库连接测试成功')
      } else {
        message.warning('部分数据库连接测试失败')
      }
      await loadStatus()
    } catch {
      message.error('连接测试失败')
    } finally {
      setTesting(false)
    }
  }

  /** 创建备份 */
  const handleCreateBackup = async () => {
    if (!backupName.trim()) {
      message.warning('请输入备份名称')
      return
    }
    try {
      await createBackup(backupName.trim())
      message.success('备份创建成功')
      setBackupDialogOpen(false)
      setBackupName('')
      await loadBackups()
    } catch {
      message.error('备份创建失败')
    }
  }

  /** 删除备份 */
  const handleDeleteBackup = async (id: string) => {
    try {
      await deleteBackup(id)
      message.success('备份已删除')
      await loadBackups()
    } catch {
      message.error('删除失败')
    }
  }

  /** 导出数据 */
  const handleExport = async () => {
    setExporting(true)
    try {
      // 构建集合映射
      const collectionMap: Record<string, string[]> = {
        config_and_reports: ['system_configs', 'users', 'llm_providers', 'market_categories',
          'model_catalog', 'analysis_reports', 'analysis_tasks'],
        config_only: ['system_configs', 'users', 'llm_providers', 'market_categories', 'model_catalog'],
        analysis_reports: ['analysis_reports', 'analysis_tasks'],
        user_configs: ['user_configs', 'user_favorites'],
        operation_logs: ['operation_logs'],
      }
      const collections = collectionMap[exportCollection] ?? [exportCollection]
      const sanitize = exportCollection === 'config_only'

      // 调用导出 API（返回 Blob）
      const apiClient = (await import('@/services/http/client')).default
      const response = await apiClient.post('/database/export', {
        collections,
        format: exportFormat,
        sanitize,
      })

      // 创建下载链接
      const blob = new Blob([response as unknown as BlobPart])
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `database_export_${new Date().toISOString().split('T')[0]}.${exportFormat}`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)

      message.success('数据导出成功')
    } catch (e: unknown) {
      const err = e as { message?: string }
      message.error(`导出失败: ${err?.message || '未知错误'}`)
    } finally {
      setExporting(false)
    }
  }

  /** 导入数据 */
  const handleImport = async () => {
    if (!importFile) {
      message.warning('请先选择要导入的文件')
      return
    }
    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', importFile)

      const apiClient = (await import('@/services/http/client')).default
      const res = await apiClient.post('/database/import', formData, {
        params: { collection: 'imported_data', format: 'json', overwrite: String(importOverwrite) },
      } as Record<string, unknown>)

      const data = res as { data?: { total_inserted?: number; total_collections?: number; mode?: string } }
      if (data.data?.mode === 'multi_collection') {
        message.success(
          `数据导入成功！共导入 ${data.data.total_collections ?? 0} 个集合，${data.data.total_inserted ?? 0} 条文档`
        )
      } else {
        message.success(`数据导入成功！导入 ${data.data?.total_inserted ?? 0} 条文档`)
      }

      setImportFile(null)
      await loadStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`导入失败: ${err?.response?.data?.detail || err?.message || '未知错误'}`)
    } finally {
      setImporting(false)
    }
  }

  /** 清理分析结果 */
  const handleCleanupAnalysis = async () => {
    setCleaning(true)
    try {
      const res = await cleanupAnalysisResults(cleanupDays)
      message.success(`分析结果清理完成，删除了 ${(res as { deleted_count?: number }).deleted_count ?? 0} 条记录`)
      await loadStatus()
    } catch {
      message.error('清理失败')
    } finally {
      setCleaning(false)
    }
  }

  /** 清理操作日志 */
  const handleCleanupLogs = async () => {
    setCleaning(true)
    try {
      const res = await cleanupOperationLogs(logCleanupDays)
      message.success(`操作日志清理完成，删除了 ${(res as { deleted_count?: number }).deleted_count ?? 0} 条记录`)
      await loadStatus()
    } catch {
      message.error('清理失败')
    } finally {
      setCleaning(false)
    }
  }

  // ========== MongoDB 状态信息 ==========
  const mongoInfo = dbStatus?.mongodb as Record<string, unknown> | undefined
  const redisInfo = dbStatus?.redis as Record<string, unknown> | undefined

  // ========== 备份表格列定义 ==========
  const backupColumns: ColumnsType<BackupInfo> = [
    { title: '名称', dataIndex: 'name', width: 180 },
    {
      title: '大小',
      dataIndex: 'size',
      width: 100,
      render: (size: number) => formatBytes(size),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '集合数',
      dataIndex: 'collections',
      width: 80,
      render: (cols: string[]) => cols.length,
    },
    {
      title: '操作',
      width: 100,
      render: (_, record) => (
        <Popconfirm title="确定删除此备份？" onConfirm={() => handleDeleteBackup(record.id)}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 */}
      <Title level={4} style={{ marginBottom: 20 }}>
        <DatabaseOutlined style={{ marginRight: 8 }} />
        数据库管理
      </Title>
      <Paragraph type="secondary" style={{ marginTop: -12, marginBottom: 20 }}>
        MongoDB + Redis 数据库管理和监控
      </Paragraph>

      {/* 连接状态卡片 */}
      <Row gutter={24} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card
            size="small"
            title={
              <Space><CloudServerOutlined /> MongoDB 连接状态</Space>
            }
          >
            <div style={{ textAlign: 'center', marginBottom: 16 }}>
              <Tag color={(mongoInfo?.connected as boolean) ? 'success' : 'error'} style={{ fontSize: 14, padding: '4px 16px' }}>
                {(mongoInfo?.connected as boolean) ? '已连接' : '未连接'}
              </Tag>
            </div>

            {(mongoInfo?.connected as boolean) && (
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="服务器">
                  {String(mongoInfo?.host ?? 'localhost')}:{String(mongoInfo?.port ?? '27017')}
                </Descriptions.Item>
                <Descriptions.Item label="数据库">{String(mongoInfo?.database ?? '-')}</Descriptions.Item>
                <Descriptions.Item label="版本">{String(mongoInfo?.version ?? '-')}</Descriptions.Item>
                {typeof mongoInfo?.connected_at === 'string' && (
                  <Descriptions.Item label="连接时间">
                    {new Date(String(mongoInfo.connected_at)).toLocaleString()}
                  </Descriptions.Item>
                )}
                {(mongoInfo?.uptime as number | undefined) != null && (
                  <Descriptions.Item label="运行时间">
                    {formatUptime(Number(mongoInfo!.uptime))}
                  </Descriptions.Item>
                )}
              </Descriptions>
            )}

            <Space style={{ justifyContent: 'center', width: '100%', marginTop: 8 }}>
              <Button
                size="small"
                icon={<ExperimentOutlined />}
                loading={testing}
                onClick={handleTestConnections}
              >
                测试连接
              </Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={loadStatus} loading={loading}>
                刷新
              </Button>
            </Space>
          </Card>
        </Col>

        <Col span={12}>
          <Card
            size="small"
            title={
              <Space><CloudServerOutlined /> Redis 连接状态</Space>
            }
          >
            <div style={{ textAlign: 'center', marginBottom: 16 }}>
              <Tag color={(redisInfo?.connected as boolean) ? 'success' : 'error'} style={{ fontSize: 14, padding: '4px 16px' }}>
                {(redisInfo?.connected as boolean) ? '已连接' : '未连接'}
              </Tag>
            </div>

            {(redisInfo?.connected as boolean) && (
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="服务器">
                  {String(redisInfo?.host ?? 'localhost')}:{String(redisInfo?.port ?? '6379')}
                </Descriptions.Item>
                <Descriptions.Item label="版本">{String(redisInfo?.version ?? '-')}</Descriptions.Item>
                {(redisInfo?.memory_used as number | undefined) != null && (
                  <Descriptions.Item label="内存使用">
                    {formatBytes(Number(redisInfo!.memory_used))}
                  </Descriptions.Item>
                )}
                {(redisInfo?.connected_clients as number | undefined) != null && (
                  <Descriptions.Item label="连接数">
                    {String(redisInfo!.connected_clients)}
                  </Descriptions.Item>
                )}
              </Descriptions>
            )}

            <Space style={{ justifyContent: 'center', width: '100%', marginTop: 8 }}>
              <Button
                size="small"
                icon={<ExperimentOutlined />}
                loading={testing}
                onClick={handleTestConnections}
              >
                测试连接
              </Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={loadStatus} loading={loading}>
                刷新
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 统计概览 */}
      {dbStats && (
        <Row gutter={24} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="集合数"
                value={dbStats.total_collections}
                styles={{ content: { fontSize: 22 } }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="总文档数"
                value={dbStats.total_documents}
                styles={{ content: { fontSize: 22 } }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="数据库大小"
                value={formatBytes(dbStats.total_size)}
                styles={{ content: { fontSize: 18 } }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 集合详情 */}
      {dbStats?.collections && dbStats.collections.length > 0 && (
        <Card size="small" title="集合详情" style={{ marginBottom: 16 }}>
          <Table
            dataSource={dbStats.collections.map(c => ({ ...c, key: c.name }))}
            columns={[
              { title: '名称', dataIndex: 'name', width: 200 },
              { title: '文档数', dataIndex: 'documents', width: 120 },
              { title: '大小', dataIndex: 'size', render: (v: number) => formatBytes(v), width: 120 },
            ]}
            pagination={false}
            size="small"
            rowKey="name"
          />
        </Card>
      )}

      {/* 数据操作 */}
      <Card title="数据管理操作" size="small" style={{ marginBottom: 16 }}>
        {/* 导入导出 */}
        <Row gutter={24}>
          <Col span={12}>
            <div>
              <Text strong>数据导出</Text>
              <br />
              <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 12 }}>导出数据库数据到文件</Paragraph>

              <Space orientation="vertical" style={{ width: '100%' }} size="small">
                <div>
                  <Text type="secondary">导出格式</Text>
                  <Select
                    value={exportFormat}
                    onChange={setExportFormat}
                    options={[
                      { value: 'json', label: 'JSON' },
                      { value: 'csv', label: 'CSV' },
                    ]}
                    style={{ width: '100%', marginTop: 4 }}
                  />
                </div>
                <div>
                  <Text type="secondary">数据范围</Text>
                  <Select
                    value={exportCollection}
                    onChange={setExportCollection}
                    options={[
                      { value: 'config_and_reports', label: '配置和报告（用于迁移）' },
                      { value: 'config_only', label: '配置数据（已脱敏，用于演示系统）' },
                      { value: 'analysis_reports', label: '分析报告' },
                      { value: 'user_configs', label: '用户配置' },
                      { value: 'operation_logs', label: '操作日志' },
                    ]}
                    style={{ width: '100%', marginTop: 4 }}
                  />
                </div>
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  loading={exporting}
                  onClick={handleExport}
                  block
                >
                  导出数据
                </Button>
              </Space>
            </div>
          </Col>

          <Col span={12}>
            <div>
              <Text strong>数据导入</Text>
              <br />
              <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 12 }}>从导出文件导入数据</Paragraph>

              <Upload.Dragger
                beforeUpload={(file) => {
                  setImportFile(file)
                  return false // 阻止自动上传
                }}
                onRemove={() => { setImportFile(null); return true }}
                maxCount={1}
                accept=".json"
                fileList={importFile ? [importFile as unknown as { uid: string; name: string }] : []}
                style={{ marginBottom: 12 }}
              >
                <p className="ant-upload-drag-icon"><UploadOutlined /></p>
                <p className="ant-upload-text">拖拽文件到此处或点击上传</p>
                <p className="ant-upload-hint">仅支持 JSON 格式的导出文件</p>
              </Upload.Dragger>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Checkbox
                  checked={importOverwrite}
                  onChange={(e) => setImportOverwrite(e.target.checked)}
                />
                <span style={{ fontSize: 13 }}>覆盖现有数据</span>
              </div>
              {importOverwrite && (
                <Alert type="warning" showIcon style={{ marginTop: 4, padding: '2px 8px' }} title="勾选后将删除现有数据再导入" />
              )}

              <Button
                type="primary"
                icon={<UploadOutlined />}
                loading={importing}
                disabled={!importFile}
                onClick={handleImport}
                block
                style={{ marginTop: 8 }}
              >
                导入数据
              </Button>
            </div>
          </Col>
        </Row>

        {/* 备份说明 */}
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          title="数据备份与还原"
          description={
            <div style={{ lineHeight: 1.8 }}>
              <p style={{ margin: '4px 0' }}>由于数据量较大，Web 界面备份体验较差，建议使用 MongoDB 原生工具：</p>
              <div style={{
                background: '#f5f7fa', padding: '8px 12px', borderRadius: 4, fontFamily: 'monospace', fontSize: 12,
              }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>备份命令：</div>
                <code>mongodump --uri="mongodb://localhost:27017" --db=tradingagents --out=./backup --gzip</code>
                <div style={{ fontWeight: 600, margin: '8px 0 4px' }}>还原命令：</div>
                <code>mongorestore --uri="mongodb://localhost:27017" --db=tradingagents --gzip ./backup/tradingagents</code>
              </div>
            </div>
          }
        />

        {/* 备份列表 */}
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <Text strong>备份列表</Text>
            <Space>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={loadBackups}
              >刷新</Button>
              <Button
                size="small"
                type="primary"
                icon={<FileTextOutlined />}
                onClick={() => setBackupDialogOpen(true)}
              >新建备份</Button>
            </Space>
          </div>
          <Table
            dataSource={backups}
            columns={backupColumns}
            rowKey="id"
            pagination={false}
            size="small"
            locale={{ emptyText: '暂无备份记录' }}
          />
        </div>
      </Card>

      {/* 数据清理 */}
      <Card
        title="数据清理"
        size="small"
        style={{ marginBottom: 16 }}
      >
        <Alert
          type="warning"
          showIcon
          title="危险操作"
          description="以下操作将永久删除数据，请谨慎操作"
          style={{ marginBottom: 16 }}
        />

        <Row gutter={24}>
          <Col span={12}>
            <Text strong>清理过期分析结果</Text>
            <br />
            <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 8 }}>
              删除指定天数之前的分析结果
            </Paragraph>
            <Space>
              <InputNumber
                min={1} max={365}
                value={cleanupDays}
                onChange={(v) => v != null && setCleanupDays(v)}
              />
              <span style={{ fontSize: 13 }}>天前</span>
            </Space>
            <br /><br />
            <Button danger icon={<WarningOutlined />} loading={cleaning} onClick={handleCleanupAnalysis}>
              清理分析结果
            </Button>
          </Col>

          <Col span={12}>
            <Text strong>清理操作日志</Text>
            <br />
            <Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 8 }}>
              删除指定天数之前的操作日志
            </Paragraph>
            <Space>
              <InputNumber
                min={1} max={365}
                value={logCleanupDays}
                onChange={(v) => v != null && setLogCleanupDays(v)}
              />
              <span style={{ fontSize: 13 }}>天前</span>
            </Space>
            <br /><br />
            <Button danger icon={<WarningOutlined />} loading={cleaning} onClick={handleCleanupLogs}>
              清理操作日志
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 新建备份对话框 */}
      <Modal
        title="创建备份"
        open={backupDialogOpen}
        onCancel={() => { setBackupDialogOpen(false); setBackupName('') }}
        onOk={handleCreateBackup}
        confirmLoading={false}
        okText="创建"
        cancelText="取消"
      >
        <Input
          placeholder="输入备份名称"
          value={backupName}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setBackupName(e.target.value)}
          onPressEnter={handleCreateBackup}
          autoFocus
        />
      </Modal>
    </div>
  )
}
