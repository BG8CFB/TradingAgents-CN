/**
 * LLM 厂家管理弹窗
 * 支持添加/编辑 LLM 厂家，含 API Key 输入、功能标签选择、测试连接
 */

import { useState, useEffect } from 'react'
import {
  Modal, Form, Input, Switch, Select, Button, Space, Tag, message, Typography,
} from 'antd'
import {
  ApiOutlined, CheckCircleOutlined, LoadingOutlined,
} from '@ant-design/icons'
import type { LLMProviderResponse, LLMProviderRequest, SupportedFeature } from '@/types/config.types'
import { testProviderAPI } from '@/services/api/config'

const { Text } = Typography
const { TextArea } = Input

/** 支持的功能选项 */
const FEATURE_OPTIONS: { label: string; value: SupportedFeature }[] = [
  { label: '对话', value: 'chat' },
  { label: '文本补全', value: 'completion' },
  { label: '嵌入', value: 'embedding' },
  { label: '图像生成', value: 'image_generation' },
  { label: '视觉理解', value: 'vision' },
  { label: '工具调用', value: 'tool_calling' },
  { label: '函数调用', value: 'function_calling' },
  { label: '流式输出', value: 'streaming' },
  { label: 'JSON 模式', value: 'json_mode' },
]

interface ProviderDialogProps {
  open: boolean
  provider?: LLMProviderResponse | null
  onClose: () => void
  onSave: (data: LLMProviderRequest) => Promise<void>
}

export default function ProviderDialog({ open, provider, onClose, onSave }: ProviderDialogProps) {
  const [form] = Form.useForm<LLMProviderRequest>()
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const isEdit = !!provider

  useEffect(() => {
    if (open) {
      if (provider) {
        form.setFieldsValue({
          name: provider.name,
          display_name: provider.display_name,
          description: provider.description || '',
          website: provider.website || '',
          api_doc_url: provider.api_doc_url || '',
          logo_url: provider.logo_url || '',
          is_active: provider.is_active,
          supported_features: provider.supported_features,
          default_base_url: provider.default_base_url || '',
          api_key: '', // 编辑时不回填密钥，用户需重新输入
          api_secret: '',
          is_aggregator: provider.is_aggregator || false,
          aggregator_type: provider.aggregator_type,
          model_name_format: provider.model_name_format || '',
        })
      } else {
        form.resetFields()
        form.setFieldsValue({ is_active: true, supported_features: ['chat', 'completion'] })
      }
      setTestResult(null)
    }
  }, [open, provider, form])

  const handleTest = async () => {
    if (!provider?.id && !isEdit) {
      message.warning('请先保存厂家后再测试连接')
      return
    }
    setTesting(true)
    setTestResult(null)
    try {
      const res = await testProviderAPI(provider!.id!)
      setTestResult({ success: res.data.success, message: res.data.message })
      message[res.data.success ? 'success' : 'error'](res.data.message)
    } catch {
      setTestResult({ success: false, message: '连接测试失败' })
    } finally {
      setTesting(false)
    }
  }

  const handleOk = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      await onSave(values)
      message.success(isEdit ? '厂家更新成功' : '厂家添加成功')
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
      title={isEdit ? `编辑厂家：${provider?.display_name}` : '添加 LLM 厂家'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={saving}
      width={640}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ is_active: true, supported_features: ['chat', 'completion'] }}
      >
        <Space size="middle" wrap style={{ width: '100%' }}>
          <Form.Item name="name" label="标识名" rules={[{ required: true, message: '请输入标识名' }]} style={{ minWidth: 200, flex: 1 }}>
            <Input placeholder="如 deepseek、openai" disabled={isEdit} />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]} style={{ minWidth: 200, flex: 1 }}>
            <Input placeholder="如 DeepSeek" />
          </Form.Item>
        </Space>

        <Form.Item name="description" label="描述">
          <TextArea rows={2} placeholder="简要描述该厂家的特点..." />
        </Form.Item>

        <Space size="middle" wrap style={{ width: '100%' }}>
          <Form.Item name="website" label="官网" style={{ minWidth: 200, flex: 1 }}>
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item name="api_doc_url" label="API 文档" style={{ minWidth: 200, flex: 1 }}>
            <Input placeholder="https://..." />
          </Form.Item>
        </Space>

        <Space size="middle" wrap style={{ width: '100%' }}>
          <Form.Item name="default_base_url" label="默认 Base URL" style={{ minWidth: 300, flex: 2 }}>
            <Input placeholder="https://api.example.com/v1" />
          </Form.Item>
          <Form.Item name="logo_url" label="Logo URL" style={{ minWidth: 200, flex: 1 }}>
            <Input placeholder="可选" />
          </Form.Item>
        </Space>

        <Form.Item name="api_key" label="API Key" tooltip="编辑时留空表示不修改">
          <Input.Password placeholder={isEdit ? '留空不修改，输入新值则更新' : '请输入 API Key'} />
        </Form.Item>

        <Form.Item name="api_secret" label="API Secret（可选）">
          <Input.Password placeholder="部分厂家需要" />
        </Form.Item>

        <Space size="middle" align="start" style={{ width: '100%' }}>
          <Form.Item name="is_active" label="启用状态" valuePropName="checked" style={{ marginBottom: 0 }}>
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
          <Form.Item name="is_aggregator" label="聚合渠道" valuePropName="checked" style={{ marginBottom: 0 }}>
            <Switch checkedChildren="是" unCheckedChildren="否" />
          </Form.Item>
        </Space>

        <Form.Item noStyle shouldUpdate={(prev, cur) => prev.is_aggregator !== cur.is_aggregator}>
          {({ getFieldValue }) =>
            getFieldValue('is_aggregator') ? (
              <Form.Item name="aggregator_type" label="聚合类型">
                <Select
                  options={[
                    { label: 'OpenRouter', value: 'openrouter' },
                    { label: '302.AI', value: '302ai' },
                    { label: 'SiliconFlow', value: 'siliconflow' },
                    { label: '自定义', value: 'custom' },
                  ]}
                  placeholder="选择聚合渠道类型"
                />
              </Form.Item>
            ) : null
          }
        </Form.Item>

        <Form.Item name="model_name_format" label="模型名称格式" tooltip="用于聚合渠道的模型名映射模板">
          <Input placeholder="如 {provider}/{model}" />
        </Form.Item>

        <Form.Item name="supported_features" label="支持的功能">
          <Select mode="multiple" options={FEATURE_OPTIONS} placeholder="选择支持的功能" />
        </Form.Item>

        {/* 测试连接区域 */}
        {isEdit && (
          <>
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 16, marginTop: 8 }}>
              <Text type="secondary">连接测试</Text>
              <div style={{ marginTop: 8 }}>
                <Button
                  icon={testing ? <LoadingOutlined /> : <ApiOutlined />}
                  onClick={handleTest}
                  loading={testing}
                >
                  测试 API 连接
                </Button>
                {testResult && (
                  <span style={{ marginLeft: 12 }}>
                    {testResult.success ? (
                      <Tag icon={<CheckCircleOutlined />} color="success">{testResult.message}</Tag>
                    ) : (
                      <Tag color="error">{testResult.message}</Tag>
                    )}
                  </span>
                )}
              </div>
            </div>
          </>
        )}
      </Form>
    </Modal>
  )
}
