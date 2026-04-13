import { useState, useEffect, useCallback } from 'react'
import {
  Card,
  Table,
  Input,
  Select,
  DatePicker,
  Button,
  Tag,
  Space,
  Popconfirm,
  message,
  Typography,
  Empty,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  SearchOutlined,
  EyeOutlined,
  DownloadOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getReportList,
  deleteReport,
  getReportDownloadUrl,
  type ReportItem,
  type ReportListParams,
} from '@/services/api/reports'

const { Text } = Typography
const { RangePicker } = DatePicker

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  completed: { color: 'success', label: '已完成' },
  processing: { color: 'processing', label: '进行中' },
  pending: { color: 'default', label: '待处理' },
  failed: { color: 'error', label: '失败' },
}

const MARKET_OPTIONS = [
  { value: 'A股', label: 'A股' },
  { value: '港股', label: '港股' },
  { value: '美股', label: '美股' },
]

export default function ReportListPage() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [params, setParams] = useState<ReportListParams>({
    page: 1,
    page_size: 15,
  })
  const [searchKeyword, setSearchKeyword] = useState('')
  const [marketFilter, setMarketFilter] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null)

  const fetchReports = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getReportList({
        ...params,
        search_keyword: searchKeyword || undefined,
        market_filter: marketFilter,
        start_date: dateRange?.[0]?.format('YYYY-MM-DD'),
        end_date: dateRange?.[1]?.format('YYYY-MM-DD'),
      })
      setReports(res.data?.reports ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      message.error('获取报告列表失败')
    } finally {
      setLoading(false)
    }
  }, [params, searchKeyword, marketFilter, dateRange])

  useEffect(() => {
    fetchReports()
  }, [fetchReports])

  const handleSearch = () => {
    setParams((prev) => ({ ...prev, page: 1 }))
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteReport(id)
      message.success('报告已删除')
      fetchReports()
    } catch {
      message.error('删除失败')
    }
  }

  const handleDownload = (id: string) => {
    window.open(getReportDownloadUrl(id, 'markdown'), '_blank')
  }

  const columns = [
    {
      title: '报告标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (text: string, record: ReportItem) => (
        <a
          onClick={() => navigate(`/reports/view?id=${record.id}`)}
          style={{ color: 'var(--accent-blue)', fontWeight: 500 }}
        >
          {text}
        </a>
      ),
    },
    {
      title: '股票',
      key: 'stock',
      width: 140,
      render: (_: unknown, record: ReportItem) => (
        <span>
          <Text strong>{record.stock_name}</Text>
          <Text type="secondary" style={{ marginLeft: 4 }}>({record.stock_code})</Text>
        </span>
      ),
    },
    {
      title: '市场',
      dataIndex: 'market_type',
      key: 'market_type',
      width: 80,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string) => {
        const s = STATUS_MAP[v] ?? { color: 'default', label: v }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '分析日期',
      dataIndex: 'analysis_date',
      key: 'analysis_date',
      width: 120,
      render: (v: string) => v?.slice(0, 10) || '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v: string) => v?.slice(0, 19).replace('T', ' ') || '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      fixed: 'right' as const,
      render: (_: unknown, record: ReportItem) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/reports/view?id=${record.id}`)}
            style={{ color: 'var(--accent-blue)' }}
          >
            查看
          </Button>
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handleDownload(record.id)}
          >
            下载
          </Button>
          <Popconfirm title="确定删除此报告？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: '0 4px' }}>
      <Card
        style={{ background: 'var(--bg-card)', border: 'none', marginBottom: 16 }}
        styles={{ body: { padding: '16px 20px' } }}
      >
        {/* 搜索和筛选栏 */}
        <Space wrap size="middle" style={{ marginBottom: 16 }}>
          <Input
            placeholder="搜索股票代码/名称"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            onPressEnter={handleSearch}
            prefix={<SearchOutlined />}
            allowClear
            style={{ width: 220 }}
          />
          <Select
            placeholder="市场类型"
            value={marketFilter}
            onChange={setMarketFilter}
            options={MARKET_OPTIONS}
            allowClear
            style={{ width: 120 }}
          />
          <RangePicker
            value={dateRange}
            onChange={(dates) => setDateRange(dates as [dayjs.Dayjs, dayjs.Dayjs] | null)}
            placeholder={['开始日期', '结束日期']}
            style={{ width: 260 }}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            搜索
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchReports}>
            刷新
          </Button>
        </Space>

        {/* 报告表格 */}
        <Table
          columns={columns}
          dataSource={reports}
          rowKey="id"
          loading={loading}
          pagination={{
            current: params.page!,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条记录`,
            pageSizeOptions: ['10', '15', '20', '50'],
            onChange: (page, pageSize) =>
              setParams({ ...params, page, page_size: pageSize }),
          }}
          scroll={{ x: 900 }}
          locale={{ emptyText: <Empty description="暂无分析报告" /> }}
        />
      </Card>
    </div>
  )
}
