import { useMemo } from 'react'
import { Typography, Tag } from 'antd'

const { Title, Paragraph, Text } = Typography

interface MarkdownRendererProps {
  content: string
  className?: string
}

/** 轻量 Markdown 渲染器（支持常用语法） */
export default function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  const blocks = useMemo(() => parseMarkdown(content), [content])

  return (
    <div className={className} style={{ color: 'var(--text-primary)', lineHeight: 1.8 }}>
      {blocks.map((block, idx) => renderBlock(block, idx))}
    </div>
  )
}

type BlockType =
  | { type: 'heading'; level: number; text: string }
  | { type: 'paragraph'; children: InlineNode[] }
  | { type: 'code'; language?: string; code: string }
  | { type: 'blockquote'; children: InlineNode[] }
  | { type: 'list'; ordered: boolean; items: InlineNode[][] }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'divider' }
  | { type: 'empty' }

type InlineNode =
  | { type: 'text'; text: string }
  | { type: 'bold'; text: string }
  | { type: 'italic'; text: string }
  | { type: 'codeInline'; text: string }
  | { type: 'link'; text: string; href: string }

function parseMarkdown(content: string): BlockType[] {
  const lines = content.split('\n')
  const blocks: BlockType[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    if (line.trim() === '') {
      i++
      continue
    }

    if (line.startsWith('---') || line.startsWith('***') || line.startsWith('___')) {
      blocks.push({ type: 'divider' })
      i++
      continue
    }

    if (line.startsWith('> ')) {
      const quoteLines: string[] = []
      while (i < lines.length && lines[i].startsWith('> ')) {
        quoteLines.push(lines[i].slice(2))
        i++
      }
      blocks.push({ type: 'blockquote', children: parseInline(quoteLines.join(' ')) })
      continue
    }

    if (line.startsWith('```')) {
      const lang = line.slice(3).trim()
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++
      blocks.push({ type: 'code', language: lang || undefined, code: codeLines.join('\n') })
      continue
    }

    if (/^#{1,6}\s/.test(line)) {
      const level = line.match(/^(#{1,6})\s/)?.[1].length ?? 1
      blocks.push({ type: 'heading', level, text: line.slice(level).trim() })
      i++
      continue
    }

    if (/^\s*[-*+]\s/.test(line)) {
      const items: InlineNode[][] = []
      while (i < lines.length && /^\s*[-*+]\s/.test(lines[i])) {
        const text = lines[i].replace(/^\s*[-*+]\s/, '')
        items.push(parseInline(text))
        i++
      }
      blocks.push({ type: 'list', ordered: false, items })
      continue
    }

    if (/^\s*\d+\.\s/.test(line)) {
      const items: InlineNode[][] = []
      while (i < lines.length && /^\s*\d+\.\s/.test(lines[i])) {
        const text = lines[i].replace(/^\s*\d+\.\s/, '')
        items.push(parseInline(text))
        i++
      }
      blocks.push({ type: 'list', ordered: true, items })
      continue
    }

    if (line.includes('|')) {
      const tableLines: string[] = []
      while (i < lines.length && lines[i].includes('|')) {
        tableLines.push(lines[i])
        i++
      }
      const parsed = parseTable(tableLines)
      if (parsed) {
        blocks.push(parsed)
        continue
      }
    }

    const paraLines: string[] = []
    while (i < lines.length && lines[i].trim() !== '' && !isBlockStart(lines[i])) {
      paraLines.push(lines[i])
      i++
    }
    blocks.push({ type: 'paragraph', children: parseInline(paraLines.join(' ')) })
  }

  return blocks
}

function isBlockStart(line: string): boolean {
  return (
    line.startsWith('#') ||
    line.startsWith('> ') ||
    line.startsWith('```') ||
    line.startsWith('---') ||
    line.startsWith('***') ||
    line.startsWith('___') ||
    /^\s*[-*+]\s/.test(line) ||
    /^\s*\d+\.\s/.test(line) ||
    (line.includes('|') && line.split('|').filter(Boolean).length > 1)
  )
}

function parseTable(lines: string[]): BlockType | null {
  if (lines.length < 2) return null
  const rows = lines.map((l) => l.split('|').map((c) => c.trim()).filter(Boolean))
  if (rows.some((r) => r.length === 0)) return null
  const headers = rows[0]
  const bodyRows = rows.slice(2)
  if (bodyRows.length === 0 && !rows[1].every((c) => /^[-:]+$/.test(c))) {
    bodyRows.push(...rows.slice(1))
  }
  return { type: 'table', headers, rows: bodyRows }
}

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = []
  let remaining = text

  const patterns = [
    { regex: /\*\*\*(.+?)\*\*\*/g, type: 'boldItalic' as const },
    { regex: /\*\*(.+?)\*\*/g, type: 'bold' as const },
    { regex: /\*(.+?)\*/g, type: 'italic' as const },
    { regex: /`(.+?)`/g, type: 'codeInline' as const },
    { regex: /\[(.+?)\]\((.+?)\)/g, type: 'link' as const },
  ]

  while (remaining.length > 0) {
    let earliest: { index: number; match: RegExpExecArray; type: string } | null = null

    for (const p of patterns) {
      p.regex.lastIndex = 0
      const m = p.regex.exec(remaining)
      if (m && (earliest === null || m.index < earliest.index)) {
        earliest = { index: m.index, match: m, type: p.type }
      }
    }

    if (!earliest) {
      nodes.push({ type: 'text', text: remaining })
      break
    }

    if (earliest.index > 0) {
      nodes.push({ type: 'text', text: remaining.slice(0, earliest.index) })
    }

    const m = earliest.match
    switch (earliest.type) {
      case 'boldItalic':
        nodes.push({ type: 'bold', text: m[1] })
        break
      case 'bold':
        nodes.push({ type: 'bold', text: m[1] })
        break
      case 'italic':
        nodes.push({ type: 'italic', text: m[1] })
        break
      case 'codeInline':
        nodes.push({ type: 'codeInline', text: m[1] })
        break
      case 'link':
        nodes.push({ type: 'link', text: m[1], href: m[2] })
        break
    }

    remaining = remaining.slice(earliest.index + m[0].length)
  }

  return nodes
}

function renderBlock(block: BlockType, key: number): React.ReactNode {
  switch (block.type) {
    case 'heading':
      return (
        <Title
          key={key}
          level={Math.min(block.level + 1, 5) as 1 | 2 | 3 | 4 | 5}
          style={{ color: 'var(--text-primary)', marginTop: 16, marginBottom: 8 }}
        >
          {block.text}
        </Title>
      )
    case 'paragraph':
      return (
        <Paragraph key={key} style={{ marginBottom: 12 }}>
          {block.children.map((child, i) => renderInline(child, `${key}-${i}`))}
        </Paragraph>
      )
    case 'code':
      return (
        <pre
          key={key}
          style={{
            background: 'rgba(0,0,0,0.3)',
            padding: 16,
            borderRadius: 8,
            overflowX: 'auto',
            fontFamily: 'monospace',
            fontSize: 13,
            border: '1px solid rgba(255,255,255,0.06)',
            marginBottom: 16,
          }}
        >
          {block.language && (
            <Tag color="default" style={{ marginBottom: 8, fontSize: 12 }}>
              {block.language}
            </Tag>
          )}
          <code style={{ color: 'var(--accent-secondary)', whiteSpace: 'pre' }}>{block.code}</code>
        </pre>
      )
    case 'blockquote':
      return (
        <blockquote
          key={key}
          style={{
            borderLeft: '3px solid var(--accent-primary)',
            paddingLeft: 16,
            margin: '12px 0',
            color: 'var(--text-secondary)',
          }}
        >
          {block.children.map((child, i) => renderInline(child, `${key}-${i}`))}
        </blockquote>
      )
    case 'list': {
      const ListTag = block.ordered ? 'ol' : 'ul'
      return (
        <div key={key} style={{ marginBottom: 12, paddingLeft: 8 }}>
          <ListTag style={{ paddingLeft: 20, margin: 0 }}>
            {block.items.map((item, i) => (
              <li key={`${key}-li-${i}`} style={{ marginBottom: 4 }}>
                {item.map((child, j) => renderInline(child, `${key}-${i}-${j}`))}
              </li>
            ))}
          </ListTag>
        </div>
      )
    }
    case 'table':
      return (
        <div key={key} style={{ overflowX: 'auto', marginBottom: 16 }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 14,
              border: '1px solid rgba(255,255,255,0.08)',
            }}
          >
            <thead>
              <tr style={{ background: 'rgba(201,169,110,0.10)' }}>
                {block.headers.map((h, i) => (
                  <th
                    key={`${key}-th-${i}`}
                    style={{
                      padding: 10,
                      border: '1px solid rgba(255,255,255,0.08)',
                      textAlign: 'left',
                      fontWeight: 600,
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={`${key}-tr-${r}`}>
                  {row.map((cell, c) => (
                    <td
                      key={`${key}-td-${r}-${c}`}
                      style={{
                        padding: 10,
                        border: '1px solid rgba(255,255,255,0.08)',
                      }}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    case 'divider':
      return (
        <hr
          key={key}
          style={{
            border: 0,
            height: 1,
            background: 'linear-gradient(90deg, transparent, rgba(201,169,110,0.2), transparent)',
            margin: '24px 0',
          }}
        />
      )
    default:
      return null
  }
}

function renderInline(node: InlineNode, key: string): React.ReactNode {
  switch (node.type) {
    case 'text':
      return <span key={key}>{node.text}</span>
    case 'bold':
      return (
        <Text key={key} strong style={{ color: 'var(--accent-secondary)' }}>
          {node.text}
        </Text>
      )
    case 'italic':
      return (
        <em key={key} style={{ color: 'var(--text-secondary)' }}>
          {node.text}
        </em>
      )
    case 'codeInline':
      return (
        <code
          key={key}
          style={{
            background: 'rgba(255,255,255,0.08)',
            padding: '2px 6px',
            borderRadius: 4,
            fontFamily: 'monospace',
            fontSize: 13,
            color: 'var(--accent-secondary)',
          }}
        >
          {node.text}
        </code>
      )
    case 'link':
      return (
        <a
          key={key}
          href={node.href}
          target="_blank"
          rel="noreferrer"
          style={{ color: 'var(--accent-secondary)', textDecoration: 'underline' }}
        >
          {node.text}
        </a>
      )
    default:
      return null
  }
}
