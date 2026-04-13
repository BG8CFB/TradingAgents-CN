/**
 * 数据源配置弹窗
 * 支持添加/编辑数据源，含市场分类关联、优先级设置
 */

import { useState, useEffect } from 'react'
import {
  Modal, Form, Input, Select, Switch, InputNumber, Space, message,
} from 'antd'
import type { DataSourceConfig, DataSourceConfigRequest, MarketCategory, DataSourceType } from '@/types/config.types'

const { TextArea } = Input

interface DataSourceConfigDialogProps {
  open: boolean
  dataSource?: DataSourceConfig | null
  categories: MarketCategory[]
  onClose: () => void
  onSave: (data: DataSourceConfigRequest) => Promise<void>
}

const DS_TYPE_OPTIONS: { label: string; value: DataSourceType }[] = [
  { label: 'Tushare', value: 'tushare' },
  { label: 'AKShare', value: 'akshare' },
  { label: 'BaoStock', value: 'baostock' },
  { label: 'Finnhub', value: 'finnhub' },
  { label: 'Yahoo Finance', value: 'yahoo_finance' },
  { label: '东方财富', value: 'eastmoney' },
  { label: '新浪财经', value: 'sina' },
  { label: '自定义', value: 'custom' },
]

export default function DataSourceConfigDialog({
  open, dataSource, categories, onClose, onSave,
}: DataSourceConfigDialogProps) {
  const [form] = Form.useForm<DataSourceConfigRequest>()
  const [saving, setSaving] = useState(false)
  const isEdit = !!dataSource

  useEffect(() => {
    if (open) {
      if (dataSource) {
        form.setFieldsValue({
          name: dataSource.name,
          type: dataSource.type,
          api_key: '', // 编辑时清空，需重新输入
          api_secret: '',
          endpoint: dataSource.endpoint || '',
          timeout: dataSource.timeout ?? 30,
          rate_limit: dataSource.rate_limit ?? 100,
          enabled: dataSource.enabled ?? true,
          priority: dataSource.priority ?? 0,
          description: dataSource.description || '',
          market_categories: dataSource.market_categories ?? [],
          display_name: dataSource.display_name || '',
          provider: dataSource.provider || '',
          // config_params 以 JSON 字符串形式编辑，此处不预填
        } as Record<string, unknown>)
      } else {
        form.resetFields()
        form.setFieldsValue({
          enabled: true,
          timeout: 30,
          rate_limit: 100,
          priority: 0,
          type: 'akshare',
        })
      }
    }
  }, [open, dataSource, form])

  const handleOk = async () => {
    try {
      const values = await form.validateFields()

      // 解析 config_params JSON
      let configParams = {}
      if (values.config_params) {
        try {
          configParams = JSON.parse(String(values.config_params))
        } catch {
          message.error('扩展配置参数不是有效的 JSON 格式')
          return
        }
      }

      setSaving(true)
      await onSave({ ...values, config_params: configParams })
      message.success(isEdit ? '数据源更新成功' : '数据源添加成功')
      onClose()
    } catch (error) {
      if (!(error as { errorFields?: unknown }).errorFields) {
        message.error('保存失败，请重试')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? `编辑数据源：${dataSource?.display_name || dataSource?.name}` : '添加数据源'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={saving}
      width={620}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Space size="middle" wrap style={{ width: '100%' }}>
          <Form.Item name="name" label="标识名" rules={[{ required: true, message: '请输入标识名' }]} style={{ minWidth: 180, flex: 1 }}>
            <Input placeholder="唯一标识" disabled={isEdit} />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" style={{ minWidth: 180, flex: 1 }}>
            <Input placeholder="友好名称" />
          </Form.Item>
        </Space>

        <Space size="middle" wrap style={{ width: '100%' }}>
          <Form.Item name="type" label="数据源类型" rules={[{ required: true }]} style={{ minWidth: 180, flex: 1 }}>
            <Select options={DS_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" style={{ alignSelf: 'end' }}>
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Space>

        <Form.Item name="description" label="描述">
          <TextArea rows={2} placeholder="简要说明该数据源的用途..." />
        </Form.Item>

        <Space size="middle" wrap style={{ width: '100%' }}>
          <Form.Item name="endpoint" label="端点地址" style={{ minWidth: 260, flex: 2 }}>
            <Input placeholder="API 端点（如有）" />
          </Form.Item>
          <Form.Item name="provider" label="提供商" style={{ minWidth: 160, flex: 1 }}>
            <Input placeholder="可选" />
          </Form.Item>
        </Space>

        <Form.Item name="api_key" label="API Key" tooltip="编辑时留空表示不修改">
          <Input.Password placeholder={isEdit ? '留空不修改' : '请输入 API Key'} />
        </Form.Item>

        <Form.Item name="api_secret" label="API Secret（可选）">
          <Input.Password placeholder="部分数据源需要" />
        </Form.Item>

        <Space size="middle" wrap style={{ width: '100%' }}>
          <Form.Item name="timeout" label="超时(秒)" style={{ minWidth: 120, flex: 1 }}>
            <InputNumber min={1} max={300} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="rate_limit" label="速率限制(/分)" style={{ minWidth: 140, flex: 1 }}>
            <InputNumber min={1} max={10000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="priority" label="优先级" style={{ minWidth: 100, flex: 1 }}>
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>
        </Space>

        <Form.Item name="market_categories" label="适用市场分类" tooltip="选择该数据源服务的市场分类">
          <Select
            mode="multiple"
            placeholder="选择适用的市场分类"
            options={categories.map(c => ({ label: c.display_name, value: c.id }))}
          />
        </Form.Item>

        <Form.Item name="config_params" label="扩展配置 (JSON)" tooltip="额外的配置参数，JSON 格式">
          <TextArea rows={3} placeholder='{"key": "value"}' />
        </Form.Item>
      </Form>
    </Modal>
  )
}
