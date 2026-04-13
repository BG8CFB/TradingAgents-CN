/**
 * 全局 Message 实例引用
 * 用于在非 React 组件中（如 HTTP 错误处理器）使用 App 组件提供的 message 实例
 */
import type { MessageInstance } from 'antd/es/message/interface'

export let globalMessage: MessageInstance | null = null

export function setGlobalMessage(instance: MessageInstance) {
  globalMessage = instance
}
