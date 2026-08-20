type Props = {
  onStart: () => void
  onBrainstorm: () => void
  onDocs: () => void
}

const TASK_STEPS = [
  ['01', '提交题目与数据'],
  ['02', '拆解问题 · 自动建模'],
  ['03', '代码求解 · 结果验证'],
  ['04', '报告撰写 · 自动审查'],
]

const DELIVERABLES = [
  ['建模报告', 'Markdown / DOCX'],
  ['可复现代码', 'Python 与运行日志'],
  ['图表与数据', 'Figures / CSV / Tables'],
  ['审查意见', '结论与证据可追溯'],
]

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  )
}

export default function Home({ onStart, onBrainstorm, onDocs }: Props) {
  const [typed, setTyped] = useState('')

  useEffect(() => {
    const words = ['更高效', '更科学']
    let word_index = 0
    let character_index = 0
    let deleting = false
    let timer = 0

    const tick = () => {
      const word = words[word_index]
      if (deleting) {
        setTyped(word.slice(0, --character_index))
        if (character_index === 0) {
          deleting = false
          word_index = (word_index + 1) % words.length
        }
      } else {
        setTyped(word.slice(0, ++character_index))
        if (character_index === word.length) {
          deleting = true
          timer = window.setTimeout(tick, 1700)
          return
        }
      }
      timer = window.setTimeout(tick, deleting ? 70 : 140)
    }

    tick()
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <div className="home home-redesign">
      <section className="landing-hero">
        <div className="landing-copy">
          <div className="landing-eyebrow"><span /> 数学建模智能体</div>
          <h1>让<span className="gradient-text">数学建模</span><br /><em className="typing-text">{typed}</em><span className="cursor">|</span></h1>
          <div className="landing-actions">
            <button className="landing-primary" onClick={onStart}>新建建模任务 <ArrowIcon /></button>
            <button className="landing-secondary" onClick={onBrainstorm}>先做头脑风暴</button>
          </div>
        </div>

        <div className="solution-preview" aria-label="建模任务产出预览">
          <div className="preview-topbar"><span>任务进行中</span><b>自动求解</b></div>
          <div className="preview-title"><span className="preview-mark">M</span><div><strong>城市配送路径优化</strong><small>含 3 个子问题 · 4 份数据附件</small></div></div>
          <div className="preview-progress"><div><span>建模与求解</span><b>已完成</b></div><i><span /></i></div>
          <div className="preview-result">
            <div><small>当前最优目标值</small><strong>18.42%</strong><span>较基准方案降低总成本</span></div>
            <svg viewBox="0 0 150 62" fill="none" aria-hidden="true"><path d="M2 51C18 52 22 36 36 40S50 51 63 35s15-12 26-20 15 5 27-5 17-7 32-7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" /><path d="M2 51C18 52 22 36 36 40S50 51 63 35s15-12 26-20 15 5 27-5 17-7 32-7V62H2Z" fill="currentColor" opacity=".08" /></svg>
          </div>
          <div className="preview-check"><span>✓</span> 结果验证通过 <small>可生成报告</small></div>
        </div>
      </section>

      <section className="landing-paths">
        <div className="landing-section-heading"><span>两条路径，按你的工作方式开始</span><h2>从问题到结论，始终由你掌控</h2></div>
        <div className="path-grid">
          <article className="path-card path-card-main">
            <div className="path-icon"><ArrowIcon /></div><span className="path-label">PATH 01 · 直接求解</span>
            <h3>交给智能体，完成一次端到端建模</h3>
            <p>提交题目和数据，系统会在需要时向你澄清信息；其余过程自动推进，并保留完整过程产物。</p>
            <button onClick={onStart}>开始建模 <ArrowIcon /></button>
          </article>
          <article className="path-card path-card-brainstorm">
            <div className="path-icon"><SparkIcon /></div><span className="path-label">PATH 02 · 思路先行</span>
            <h3>用自己的资料，把方法论变成建模思路</h3>
            <p>上传文献、案例或竞赛资料，获得带来源引用的对话式检索回答，再将思路带入建模任务。</p>
            <button onClick={onBrainstorm}>进入头脑风暴 <ArrowIcon /></button>
          </article>
        </div>
      </section>

      <section className="landing-workflow">
        <div className="landing-section-heading"><span>建模任务的工作方式</span><h2>每一步都有依据，也都可回看</h2></div>
        <div className="task-steps">
          {TASK_STEPS.map(([number, title]) => <div className="task-step" key={number}><b>{number}</b><span>{title}</span></div>)}
        </div>
        <div className="workflow-footnote">遇到题意不清或需调整预算时，任务会停在恰当的位置，等待你的决策。</div>
      </section>

      <section className="landing-deliverables">
        <div className="deliverable-copy"><span>不止一个答案</span><h2>拿到完整成果，<br />也保留复核能力。</h2><p>报告中的结论、证据与决策日志相互对应，方便修改、复盘和沉淀为下一次建模经验。</p><button className="landing-text-button" onClick={onDocs}>查看功能说明 <ArrowIcon /></button></div>
        <div className="deliverable-list">{DELIVERABLES.map(([name, description]) => <div key={name}><span>✓</span><strong>{name}</strong><small>{description}</small></div>)}</div>
      </section>
    </div>
  )
}
import { useEffect, useState } from 'react'
