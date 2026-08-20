import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

import 'katex/dist/katex.min.css'

function normalizeMathDelimiters(content: string): string {
  return content
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, math: string) => `\n$$\n${math.trim()}\n$$\n`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_match, math: string) => `$${math}$`)
}

export default function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
        {normalizeMathDelimiters(content)}
      </ReactMarkdown>
    </div>
  )
}
