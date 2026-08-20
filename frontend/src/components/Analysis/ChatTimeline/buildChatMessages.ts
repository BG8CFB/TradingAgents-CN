/**
 * 事件流 → Claude Code 式对话消息序列（纯函数，无 Vue/Pinia 依赖，可单测）。
 *
 * 消息类型：
 * - prompt    llm_request：messages_full=true 时携带完整 messages 原文；否则仅条数摘要
 * - thinking  thinking 事件（独立于 llm_response 的思考文本）
 * - assistant llm_response 的最终文本（markdown）
 * - tool      tool_call ↔ tool_result 配对（tool_use_id 优先，缺失按相邻顺序+工具名兜底）
 * - tool_group 连续同名 tool 消息折叠组（渲染层展开）
 * - user      用户注入消息（含乐观本地消息）
 * - boundary  系统边界（compact 等提示条）
 *
 * 降级契约（存量旧事件，新字段缺失）：
 * - llm_request 无 messages / messages_full → count 摘要行；无 count → 记录缺失
 * - llm_response 无 text → text='' 且 missing=true，渲染层显示占位
 * - 无 tool_use_id → 顺序+名配对（与旧 ProcessPanel 行为一致）
 */
import type { AgentEvent } from '@/api/analysis'

export interface PromptChatMessage {
  kind: 'prompt'
  id: string
  /** 完整消息原文（仅 agent 首轮 messages_full=true 时存在） */
  messages: Array<{ role: string; content: string }> | null
  /** 消息条数（messages_full=false 的后续轮次；旧事件可能缺失 → null） */
  messagesCount: number | null
  messagesFull: boolean
}

export interface ThinkingChatMessage {
  kind: 'thinking'
  id: string
  text: string
}

export interface AssistantChatMessage {
  kind: 'assistant'
  id: string
  text: string
  /** 旧事件无 text 字段：回放态显示"早于过程录制增强"占位 */
  missing: boolean
}

export interface ToolChatMessage {
  kind: 'tool'
  id: string
  name: string
  input: string
  output: string
  durationMs: number | null
  isError: boolean
  toolUseId: string | null
  hasResult: boolean
}

export interface ToolGroupChatMessage {
  kind: 'tool_group'
  id: string
  name: string
  items: ToolChatMessage[]
}

export interface UserChatMessage {
  kind: 'user'
  id: string
  text: string
  /** 本地乐观消息（未收到服务器回显） */
  local: boolean
}

export interface BoundaryChatMessage {
  kind: 'boundary'
  id: string
  /** boundary 子类型：compact / info */
  subtype: string
  text: string
}

export type ChatMessage =
  | PromptChatMessage
  | ThinkingChatMessage
  | AssistantChatMessage
  | ToolChatMessage
  | ToolGroupChatMessage
  | UserChatMessage
  | BoundaryChatMessage

/** 连续同名工具折叠组的最少成员数（2 个起才折叠） */
const TOOL_GROUP_MIN = 2

function payload(ev: AgentEvent): Record<string, unknown> {
  return ev.payload ?? {}
}

/** 截断超长文本用于折叠展示 */
export function truncateText(value: unknown, max = 800): string {
  let text: string
  if (typeof value === 'string') {
    text = value
  } else {
    try {
      text = JSON.stringify(value, null, 2)
    } catch {
      text = String(value)
    }
  }
  if (!text) return ''
  return text.length > max ? `${text.slice(0, max)}…(已截断)` : text
}

/** 从 system-reminder 包装中提取用户原文（服务器落库全文） */
export function extractUserText(raw: string): string {
  const m = raw.match(/while you were working:\s*([\s\S]*?)\s*\n\s*IMPORTANT:/)
  return m ? m[1].trim() : raw
}

/** compact 提示文案：事件真实字段 level/messages，token 收缩字段可选 */
function compactBoundaryText(p: Record<string, unknown>): string {
  const level = typeof p.level === 'string' ? p.level : ''
  const messages = typeof p.messages === 'number' ? p.messages : null
  const before = p.before_tokens ?? p.tokens_before
  const after = p.after_tokens ?? p.tokens_after
  let text = '上下文压缩'
  if (level) text += `（${level}）`
  if (typeof before === 'number' && typeof after === 'number') {
    text += ` ${before} → ${after} tokens`
  } else if (messages != null) {
    text += ` · ${messages} 条消息`
  }
  return text
}

/**
 * 由单个 agent 的事件流（seq 升序）构建消息序列。
 * tool_call/tool_result 配对：优先 tool_use_id；缺失时按"工具名 + 到达顺序"队列兜底。
 * 连续同名 tool 消息折叠为 tool_group。
 */
export function buildChatMessages(evs: AgentEvent[]): ChatMessage[] {
  const messages: ChatMessage[] = []
  /** tool_use_id → 未匹配 tool_call 在 items 中的下标 */
  const pendingById = new Map<string, number>()
  /** 工具名 → 未匹配 tool_call（无 id）下标队列（顺序兜底） */
  const pendingByName = new Map<string, number[]>()

  function registerPending(name: string, id: string | null) {
    const idx = messages.length - 1
    if (id) pendingById.set(id, idx)
    const queue = pendingByName.get(name) ?? []
    queue.push(idx)
    pendingByName.set(name, queue)
  }

  /** 匹配结果：优先 id，其次同名顺序队列；返回 tool 消息下标或 null */
  function matchResult(name: string, id: string | null): number | null {
    if (id) {
      const byId = pendingById.get(id)
      if (byId !== undefined) {
        pendingById.delete(id)
        // 同步清理顺序队列中的同一项，避免后续重复消费
        const queue = pendingByName.get(name)
        if (queue) {
          const qi = queue.indexOf(byId)
          if (qi >= 0) queue.splice(qi, 1)
        }
        return byId
      }
    }
    const queue = pendingByName.get(name)
    const idx = queue?.shift()
    if (idx != null) {
      // 反查该下标的 tool_useId 以同步清理 id 索引
      const item = messages[idx]
      if (item && item.kind === 'tool' && item.toolUseId) pendingById.delete(item.toolUseId)
      return idx
    }
    return null
  }

  for (const ev of evs) {
    const p = payload(ev)
    switch (ev.event_type) {
      case 'llm_request': {
        const rawMsgs = Array.isArray(p.messages) ? p.messages : null
        const full = p.messages_full === true
        let msgs: PromptChatMessage['messages'] = null
        if (full && rawMsgs) {
          msgs = rawMsgs
            .filter((m): m is Record<string, unknown> => m !== null && typeof m === 'object')
            .map((m) => ({
              role: typeof m.role === 'string' ? m.role : 'unknown',
              content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content ?? ''),
            }))
        }
        const count =
          typeof p.messages_count === 'number' ? p.messages_count
          : rawMsgs && rawMsgs.length > 0 ? rawMsgs.length
          : null
        messages.push({
          kind: 'prompt',
          id: `e${ev.seq}`,
          messages: msgs,
          messagesCount: full ? (msgs?.length ?? count) : count,
          messagesFull: full && msgs !== null,
        })
        break
      }
      case 'thinking': {
        const text = typeof p.text === 'string' ? p.text : ''
        if (text) messages.push({ kind: 'thinking', id: `e${ev.seq}`, text })
        break
      }
      case 'llm_response': {
        const text = typeof p.text === 'string' ? p.text : (typeof p.summary === 'string' ? p.summary : '')
        messages.push({
          kind: 'assistant',
          id: `e${ev.seq}`,
          text,
          // 旧事件 text/summary 均无（纯工具轮落库时可能只有 token 数）→ 占位
          missing: !text,
        })
        break
      }
      case 'user_message_injected': {
        const raw = typeof p.text === 'string' ? p.text : ''
        messages.push({
          kind: 'user',
          id: `e${ev.seq}`,
          text: raw ? extractUserText(raw) : '(空消息)',
          local: p.local === true,
        })
        break
      }
      case 'compact': {
        messages.push({
          kind: 'boundary',
          id: `e${ev.seq}`,
          subtype: 'compact',
          text: compactBoundaryText(p),
        })
        break
      }
      case 'tool_call': {
        const name =
          typeof p.tool === 'string' ? p.tool
          : typeof p.name === 'string' ? p.name
          : 'unknown_tool'
        const toolUseId = typeof p.tool_use_id === 'string' ? p.tool_use_id : null
        messages.push({
          kind: 'tool',
          id: `e${ev.seq}`,
          name,
          input: truncateText(p.input ?? p.arguments ?? p.parameters ?? ''),
          output: '',
          durationMs: null,
          isError: false,
          toolUseId,
          hasResult: false,
        })
        registerPending(name, toolUseId)
        break
      }
      case 'tool_result': {
        const name =
          typeof p.tool === 'string' ? p.tool
          : typeof p.name === 'string' ? p.name
          : 'unknown_tool'
        const toolUseId = typeof p.tool_use_id === 'string' ? p.tool_use_id : null
        const result = {
          output: truncateText(p.output ?? p.result ?? ''),
          durationMs: typeof p.duration_ms === 'number' ? p.duration_ms : null,
          isError: p.is_error === true,
          hasResult: true,
        }
        const idx = matchResult(name, toolUseId)
        const target = idx != null ? messages[idx] : undefined
        if (idx != null && target && target.kind === 'tool') {
          Object.assign(target, result)
        } else {
          // 没有配对 tool_call 的结果，单独展示
          messages.push({
            kind: 'tool',
            id: `e${ev.seq}`,
            name,
            input: '',
            output: result.output,
            durationMs: result.durationMs,
            isError: result.isError,
            toolUseId,
            hasResult: true,
          })
        }
        break
      }
      default:
        // agent_start / agent_end / report_ready 等非对话内容事件不进消息流
        break
    }
  }

  return groupConsecutiveTools(messages)
}

/** 连续同名 tool 消息折叠为 tool_group（≥TOOL_GROUP_MIN 个才折叠） */
function groupConsecutiveTools(messages: ChatMessage[]): ChatMessage[] {
  const out: ChatMessage[] = []
  let i = 0
  while (i < messages.length) {
    const msg = messages[i]
    if (msg.kind !== 'tool') {
      out.push(msg)
      i += 1
      continue
    }
    const isSameTool = (m: ChatMessage): m is ToolChatMessage => m.kind === 'tool' && m.name === msg.name
    let j = i
    while (j < messages.length && isSameTool(messages[j])) j += 1
    const run = messages.slice(i, j) as ToolChatMessage[]
    if (run.length >= TOOL_GROUP_MIN) {
      out.push({
        kind: 'tool_group',
        id: `${msg.id}~${run[run.length - 1].id}`,
        name: msg.name,
        items: run,
      })
    } else {
      out.push(...run)
    }
    i = j
  }
  return out
}
