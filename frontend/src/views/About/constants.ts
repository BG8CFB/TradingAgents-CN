import type { Component } from 'vue'
import {
  TrendCharts,
  Search,
  Files,
  Document,
  Monitor,
  Setting,
  Message,
  ChatDotRound,
  Cpu,
  Star,
  User,
  Connection
} from '@element-plus/icons-vue'

// 声明 Vite 注入的全局常量
declare const __APP_VERSION__: string
declare const __BUILD_TIME__: string

export const APP_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0+unknown'
export const BUILD_TIME = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : new Date().toISOString()

export interface FeatureItem {
  icon: Component
  title: string
  desc: string
  tags: string[]
  variant: 'primary' | 'success' | 'warning' | 'info' | 'danger'
}

export const FEATURES: FeatureItem[] = [
  {
    icon: User,
    title: '智能体管理系统',
    desc: '全新重构的智能体架构，支持动态添加/删除智能体，可在线修改 Prompt 提示词，定制您的专属分析师。',
    tags: ['动态管理', 'Prompt编辑', '代码重构'],
    variant: 'primary'
  },
  {
    icon: Connection,
    title: 'MCP 协议支持',
    desc: '全面升级 AI 框架，支持 Model Context Protocol (MCP)，轻松接入海量开源工具与数据生态。',
    tags: ['AI框架升级', '生态接入'],
    variant: 'success'
  },
  {
    icon: TrendCharts,
    title: '多智能体分析',
    desc: '基本面、技术面、新闻分析、社媒分析等智能体协作，提供全方位的股票分析视角。',
    tags: ['基本面分析', '技术分析', '新闻分析', '社媒分析'],
    variant: 'primary'
  },
  {
    icon: Search,
    title: '智能股票筛选',
    desc: '多维度筛选条件，智能算法推荐，快速发现具有投资价值的优质股票。',
    tags: ['多维筛选', '智能推荐'],
    variant: 'success'
  },
  {
    icon: Files,
    title: '批量分析处理',
    desc: '支持批量股票分析，并行处理提高效率，适合大规模投资组合分析。',
    tags: ['批量处理', '并行计算'],
    variant: 'warning'
  },
  {
    icon: Document,
    title: '专业分析报告',
    desc: '生成详细的分析报告，支持 PDF、Excel 等多种格式导出，便于分享和存档。',
    tags: ['PDF导出', 'Excel报表'],
    variant: 'info'
  },
  {
    icon: Monitor,
    title: '实时监控',
    desc: '实时监控分析进度和系统状态，提供详细的任务执行日志和性能指标。',
    tags: ['实时监控', '性能分析'],
    variant: 'danger'
  },
  {
    icon: Setting,
    title: '个性化配置',
    desc: '灵活的参数配置和个人偏好设置，支持自定义分析策略和风险偏好。',
    tags: ['自定义策略', '风险配置'],
    variant: 'primary'
  }
]

export interface TechCategory {
  title: string
  icon: Component
  variant: 'frontend' | 'backend' | 'ai'
  items: { name: string; desc: string }[]
}

export const TECH_STACK: TechCategory[] = [
  {
    title: '前端技术',
    icon: Monitor,
    variant: 'frontend',
    items: [
      { name: 'Vue 3', desc: '现代化前端框架' },
      { name: 'TypeScript', desc: '类型安全开发' },
      { name: 'Element Plus', desc: '企业级UI组件库' },
      { name: 'Pinia', desc: '状态管理' },
      { name: 'Vite', desc: '快速构建工具' }
    ]
  },
  {
    title: '后端技术',
    icon: Cpu,
    variant: 'backend',
    items: [
      { name: 'FastAPI', desc: '高性能API框架' },
      { name: 'Python 3.12', desc: '现代Python开发' },
      { name: 'Redis', desc: '高性能缓存和队列' },
      { name: 'MongoDB', desc: '文档数据库' },
      { name: 'LangGraph', desc: '多智能体编排' }
    ]
  },
  {
    title: 'AI 技术',
    icon: Cpu,
    variant: 'ai',
    items: [
      { name: '多智能体系统', desc: '协作式AI分析' },
      { name: '大语言模型', desc: 'DeepSeek/Claude/Qwen等' },
      { name: 'MCP 协议', desc: '工具调用生态' },
      { name: '数据挖掘', desc: '深度数据分析' }
    ]
  }
]

export interface ContactItem {
  icon: Component
  title: string
  content: string
  desc: string
  variant: 'qq' | 'email' | 'wechat' | 'docs'
  link?: string
}

export const CONTACTS: ContactItem[] = [
  {
    icon: ChatDotRound,
    title: '交流群 (BG8CFB)',
    content: '请查看文档中的二维码',
    desc: '新版维护交流与反馈',
    variant: 'qq'
  },
  {
    icon: Message,
    title: 'Bug 反馈',
    content: '提交 Issue',
    desc: '在 GitHub 提交问题或建议',
    variant: 'email',
    link: 'https://github.com/BG8CFB/TradingAgents-CN/issues'
  },
  {
    icon: ChatDotRound,
    title: '微信公众号',
    content: 'TradingAgents-CN',
    desc: '最新动态和使用教程',
    variant: 'wechat'
  },
  {
    icon: Document,
    title: '使用文档',
    content: '查看详细文档',
    desc: '完整的使用指南和API文档',
    variant: 'docs',
    link: 'https://mp.weixin.qq.com/s/ppsYiBncynxlsfKFG8uEbw'
  }
]

export interface ProjectLink {
  title: string
  url: string
  description: string
  highlights: string[]
  icon: Component
  variant: 'primary' | 'success'
}

export const PROJECT_LINKS: ProjectLink[] = [
  {
    title: 'TradingAgents-CN',
    url: 'https://github.com/BG8CFB/TradingAgents-CN',
    description: '由 BG8CFB 维护，致力于为中文用户提供更好的使用体验。基于开源多智能体股票分析框架开发。',
    highlights: [
      '完整的中文支持：针对中国A股市场优化',
      '现代化Web界面：Vue 3 + Element Plus',
      '增强的数据源：Tushare、AKShare 等中国市场数据',
      '多LLM支持：DeepSeek、Claude、智谱AI、通义千问等',
      '定期更新维护：每周更新，重大问题实时修复',
      '社区支持：欢迎提交 Issue 和 PR',
      '中文交流群：微信群和 QQ 群交流支持',
      '完整文档：详细的使用教程和部署指南'
    ],
    icon: Star,
    variant: 'primary'
  }
]
