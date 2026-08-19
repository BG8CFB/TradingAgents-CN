"""
压缩 prompt（参考 claude-code src/services/compact/prompt.ts 的 9 段式摘要指令）
"""

COMPACT_SYSTEM_PROMPT = "你是一个对话摘要助手。请严格按照要求的格式输出摘要，不要调用任何工具。"

COMPACT_INSTRUCTIONS = """请对以上对话历史进行摘要，摘要将被用于继续此对话（原历史将被丢弃）。
请按以下结构组织摘要，无法确定的部分标注"无"：

1. Primary Request and Intent: 用户的原始请求与真实意图
2. Key Technical Concepts: 涉及的关键技术概念、约束
3. Files and Code Sections: 讨论过的文件与代码段（含路径）
4. Errors and fixes: 遇到的错误及修复方式
5. Problem Solving: 已尝试的方案与解决进展
6. All user messages: 按顺序列出用户的每条消息（保留原意）
7. Pending Tasks: 尚未完成的事项
8. Current Work: 当前正在处理的内容与最近状态
9. Optional Next Step: 建议的下一步

要求：保留所有关键事实（数据、名称、路径、决策），删除寒暄与冗余；
输出为中文；直接输出摘要正文，不要输出其他说明。"""

CONTINUATION_HEADER = "本次会话由早前的对话压缩继续。以下是此前对话的摘要，请基于它继续当前任务：\n\n"
