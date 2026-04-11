import { z } from 'zod'
import { validateStockSymbol } from '@/services/api/analysis'

export const singleAnalysisSchema = z
  .object({
    symbol: z.string().min(1, '请输入股票代码'),
    market_type: z.string().min(1, '请选择市场类型'),
    analysis_date: z.string().optional(),
    selected_analysts: z.array(z.string()).default([]),
    custom_prompt: z.string().optional(),
    include_sentiment: z.boolean().default(true),
    include_risk: z.boolean().default(true),
    language: z.string().default('zh-CN'),
    quick_analysis_model: z.string().optional(),
    deep_analysis_model: z.string().optional(),
    phase2_enabled: z.boolean().default(false),
    phase2_debate_rounds: z.number().int().min(1).max(5).default(2),
    phase3_enabled: z.boolean().default(false),
    phase3_debate_rounds: z.number().int().min(1).max(5).default(2),
    phase4_enabled: z.boolean().default(false),
    phase4_debate_rounds: z.number().int().min(1).max(5).default(1),
    mcp_enabled: z.boolean().default(false),
    mcp_tool_ids: z.array(z.string()).default([]),
  })
  .superRefine((data, ctx) => {
    if (data.symbol && !validateStockSymbol(data.symbol, data.market_type)) {
      ctx.addIssue({
        path: ['symbol'],
        code: z.ZodIssueCode.custom,
        message: '股票代码格式不正确',
      })
    }
  })

export const batchAnalysisSchema = z
  .object({
    title: z.string().min(1, '请输入批次标题').max(50, '标题最多50个字符'),
    description: z.string().max(200, '描述最多200个字符').optional(),
    symbols: z
      .array(z.string().min(1, '股票代码不能为空'))
      .min(1, '请至少输入一个股票代码')
      .max(10, '最多支持10个股票'),
    market_type: z.string().min(1, '请选择市场类型'),
    parameters: z
      .object({
        selected_analysts: z.array(z.string()).default([]),
        custom_prompt: z.string().optional(),
        include_sentiment: z.boolean().default(true),
        include_risk: z.boolean().default(true),
        language: z.string().default('zh-CN'),
        quick_analysis_model: z.string().optional(),
        deep_analysis_model: z.string().optional(),
        phase2_enabled: z.boolean().default(false),
        phase2_debate_rounds: z.number().int().min(1).max(5).default(2),
        phase3_enabled: z.boolean().default(false),
        phase3_debate_rounds: z.number().int().min(1).max(5).default(2),
        phase4_enabled: z.boolean().default(false),
        phase4_debate_rounds: z.number().int().min(1).max(5).default(1),
        mcp_enabled: z.boolean().default(false),
        mcp_tool_ids: z.array(z.string()).default([]),
      })
      .default({
        selected_analysts: [],
        include_sentiment: true,
        include_risk: true,
        language: 'zh-CN',
        phase2_enabled: false,
        phase2_debate_rounds: 2,
        phase3_enabled: false,
        phase3_debate_rounds: 2,
        phase4_enabled: false,
        phase4_debate_rounds: 1,
        mcp_enabled: false,
        mcp_tool_ids: [],
      }),
  })
  .superRefine((data, ctx) => {
    data.symbols.forEach((sym, idx) => {
      if (sym && !validateStockSymbol(sym, data.market_type)) {
        ctx.addIssue({
          path: ['symbols', idx],
          code: z.ZodIssueCode.custom,
          message: '股票代码格式不正确',
        })
      }
    })
  })

export type SingleAnalysisFormValues = z.infer<typeof singleAnalysisSchema>
export type BatchAnalysisFormValues = z.infer<typeof batchAnalysisSchema>
