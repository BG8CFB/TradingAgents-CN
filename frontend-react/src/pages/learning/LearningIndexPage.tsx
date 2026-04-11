import { useState } from 'react'
import {
  Card,
  Typography,
  Row,
  Col,
  Tag,
  Input,
  Space,
  Empty,
  Button,
} from 'antd'
import {
  BookOutlined,
  RobotOutlined,
  BulbOutlined,
  ExperimentOutlined,
  SafetyCertificateOutlined,
  LinkOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  TeamOutlined,
  BankOutlined,
} from '@ant-design/icons'
// MarkdownRenderer will be used when article content is available
// eslint-disable-next-line @typescript-eslint/no-unused-vars
import _MarkdownRenderer from '@/components/ui/MarkdownRenderer'

const { Title, Text, Paragraph } = Typography

interface ArticleMeta {
  title: string
  description: string
  category: string
  difficulty: string
  readTime: string
  icon: React.ReactNode
  content?: string
}

/** 学习中心内容目录（静态数据，后续可改为从 API 获取） */
const LEARNING_CATEGORIES: Array<{
  key: string
  name: string
  icon: React.ReactNode
  color: string
  articles: ArticleMeta[]
}> = [
  {
    key: 'basics',
    name: 'AI 基础',
    icon: <RobotOutlined />,
    color: '#C9A96E',
    articles: [
      {
        title: '什么是大语言模型',
        description: '了解 LLM 的基本概念、原理及其在金融分析中的应用潜力',
        category: 'AI 基础',
        difficulty: '入门',
        readTime: '10 分钟',
        icon: <RobotOutlined />,
      },
    ],
  },
  {
    key: 'prompt',
    name: '提示工程',
    icon: <BulbOutlined />,
    color: '#4A7DB8',
    articles: [
      {
        title: 'Prompt 基础',
        description: '掌握提示词编写的基本原则和技巧，提升 AI 交互质量',
        category: '提示工程',
        difficulty: '入门',
        readTime: '8 分钟',
        icon: <BulbOutlined />,
      },
      {
        title: '最佳实践',
        description: '金融领域提示工程的高级技巧与常见模式',
        category: '提示工程',
        difficulty: '进阶',
        readTime: '12 分钟',
        icon: <ThunderboltOutlined />,
      },
    ],
  },
  {
    key: 'model',
    name: '模型选择',
    icon: <ExperimentOutlined />,
    color: '#52C41A',
    articles: [
      {
        title: '主流模型对比',
        description: 'DeepSeek、通义千问、GPT 等模型在金融分析场景下的对比评测',
        category: '模型选择',
        difficulty: '进阶',
        readTime: '15 分钟',
        icon: <ExperimentOutlined />,
      },
    ],
  },
  {
    key: 'analysis',
    name: '分析原理',
    icon: <TeamOutlined />,
    color: '#D48806',
    articles: [
      {
        title: '多智能体系统',
        description: '深入理解 TradingAgents 的多 Agent 协作架构与分析流程',
        category: '分析原理',
        difficulty: '进阶',
        readTime: '20 分钟',
        icon: <TeamOutlined />,
      },
    ],
  },
  {
    key: 'risks',
    name: '风险与限制',
    icon: <SafetyCertificateOutlined />,
    color: '#FF4D4F',
    articles: [
      {
        title: '风险警告',
        description: '使用 AI 进行投资分析的局限性与风险提示，请务必阅读',
        category: '风险与限制',
        difficulty: '入门',
        readTime: '5 分钟',
        icon: <SafetyCertificateOutlined />,
      },
    ],
  },
  {
    key: 'resources',
    name: '资源与参考',
    icon: <LinkOutlined />,
    color: '#722ED1',
    articles: [
      {
        title: '项目介绍',
        description: 'TradingAgents 项目背景、核心理念与技术架构详解',
        category: '资源与参考',
        difficulty: '进阶',
        readTime: '15 分钟',
        icon: <BankOutlined />,
      },
      {
        title: '论文指南',
        description: '相关学术论文、研究报告推荐阅读列表',
        category: '资源与参考',
        difficulty: '高级',
        readTime: '10 分钟',
        icon: <BookOutlined />,
      },
    ],
  },
  {
    key: 'faq',
    name: '常见问题',
    icon: <QuestionCircleOutlined />,
    color: '#13C2C2',
    articles: [
      {
        title: '通用问题',
        description: '平台使用中的常见问题解答（FAQ）',
        category: '常见问题',
        difficulty: '入门',
        readTime: '8 分钟',
        icon: <QuestionCircleOutlined />,
      },
    ],
  },
]

const DIFFICULTY_MAP: Record<string, { color: string; label: string }> = {
  '入门': { color: 'green', label: '入门' },
  '进阶': { color: 'gold', label: '进阶' },
  '高级': { color: 'red', label: '高级' },
}

export default function LearningIndexPage() {
  const [searchText, setSearchText] = useState('')
  const [selectedArticle, setSelectedArticle] = useState<ArticleMeta | null>(null)

  const filteredCategories = LEARNING_CATEGORIES.map((cat) => ({
    ...cat,
    articles: cat.articles.filter(
      (a) =>
        !searchText ||
        a.title.includes(searchText) ||
        a.description.includes(searchText)
    ),
  })).filter((cat) => cat.articles.length > 0)

  const totalArticles = filteredCategories.reduce((sum, cat) => sum + cat.articles.length, 0)

  return (
    <div style={{ padding: '0 4px' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ color: 'var(--text-primary)', marginBottom: 4 }}>
          <BookOutlined style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
          学习中心
        </Title>
        <Paragraph type="secondary" style={{ margin: 0, fontSize: 14 }}>
          系统学习 AI 股票分析与 TradingAgents 平台使用方法 · 共 {totalArticles} 篇文章
        </Paragraph>
      </div>

      {/* 搜索栏 */}
      <Input
        placeholder="搜索文章..."
        value={searchText}
        onChange={(e) => setSearchText(e.target.value)}
        prefix={<SearchOutlined style={{ color: 'var(--text-muted)' }} />}
        allowClear
        style={{
          maxWidth: 400,
          marginBottom: 20,
          background: 'var(--bg-card)',
          borderColor: 'var(--border-color)',
        }}
      />

      {/* 文章详情视图 */}
      {selectedArticle ? (
        <Card
          style={{ background: 'var(--bg-card)', border: 'none', marginBottom: 16 }}
          styles={{
            header: {
              background: 'transparent',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            },
          }}
          title={
            <span>
              <Button
                type="link"
                size="small"
                onClick={() => setSelectedArticle(null)}
                style={{ paddingLeft: 0, marginRight: 12 }}
              >
                ← 返回目录
              </Button>
              <span style={{ color: 'var(--text-primary)' }}>{selectedArticle.title}</span>
            </span>
          }
        >
          <Space style={{ marginBottom: 16 }}>
            <Tag color={DIFFICULTY_MAP[selectedArticle.difficulty]?.color}>
              {DIFFICULTY_MAP[selectedArticle.difficulty]?.label}
            </Tag>
            <Tag>{selectedArticle.category}</Tag>
            <Tag icon={<BookOutlined />}>{selectedArticle.readTime}</Tag>
          </Space>
          <div style={{
            padding: '16px 0',
            borderTop: '1px solid var(--border-color)',
            minHeight: 300,
            color: 'var(--text-secondary)',
            lineHeight: 1.8,
          }}>
            <Paragraph>
              {selectedArticle.description}
            </Paragraph>
            <Paragraph type="secondary">
              文章内容正在整理中，敬请期待。您可以在左侧目录中选择其他文章浏览。
            </Paragraph>
          </div>
        </Card>
      ) : (
        <>
          {/* 分类卡片列表 */}
          {filteredCategories.length === 0 ? (
            <Empty description="未找到匹配的文章" />
          ) : (
            filteredCategories.map((category) => (
              <Card
                key={category.key}
                style={{
                  background: 'var(--bg-card)',
                  border: 'none',
                  marginBottom: 16,
                }}
                styles={{
                  header: {
                    borderBottom: '1px solid var(--border-color)',
                    background: 'transparent',
                  },
                }}
                title={
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: category.color, fontSize: 18 }}>{category.icon}</span>
                    <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                      {category.name}
                    </span>
                    <Tag style={{ marginLeft: 8 }}>{category.articles.length} 篇</Tag>
                  </span>
                }
              >
                <Row gutter={[16, 16]}>
                  {category.articles.map((article, idx) => (
                    <Col xs={24} sm={12} lg={8} key={idx}>
                      <Card
                        hoverable
                        size="small"
                        onClick={() => setSelectedArticle(article)}
                        style={{
                          height: '100%',
                          border: '1px solid var(--border-color)',
                          borderRadius: 8,
                          cursor: 'pointer',
                          transition: 'all 0.2s',
                        }}
                        styles={{
                          body: { padding: '16px', display: 'flex', flexDirection: 'column', gap: 8 },
                        }}
                      >
                        <span style={{ fontSize: 22, color: category.color }}>{article.icon}</span>
                        <Text strong style={{ color: 'var(--text-primary)', fontSize: 14 }}>
                          {article.title}
                        </Text>
                        <Paragraph
                          type="secondary"
                          ellipsis={{ rows: 2 }}
                          style={{ margin: 0, fontSize: 12, lineHeight: 1.6, flex: 1 }}
                        >
                          {article.description}
                        </Paragraph>
                        <div style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
                          <Tag
                            color={DIFFICULTY_MAP[article.difficulty]?.color}
                            style={{ fontSize: 11, margin: 0 }}
                          >
                            {DIFFICULTY_MAP[article.difficulty]?.label}
                          </Tag>
                          <Tag style={{ fontSize: 11, margin: 0 }}>{article.readTime}</Tag>
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </Card>
            ))
          )}
        </>
      )}
    </div>
  )
}
