import { marked } from 'marked'
import readmeRaw from '../../../README.md?raw'

const readmeHtml = marked.parse(readmeRaw, { gfm: true, breaks: false }) as string

export default function Docs() {
  return (
    <div className="docs-page">
      <div className="section readme">
        <div className="section-header">
          <div className="section-tag">PROJECT README</div>
          <h2 className="section-title">项目文档</h2>
          <p className="section-subtitle">完整的功能说明与使用指南（与仓库 README.md 同步）</p>
        </div>
        <div className="readme-body" dangerouslySetInnerHTML={{ __html: readmeHtml }} />
      </div>
    </div>
  )
}
